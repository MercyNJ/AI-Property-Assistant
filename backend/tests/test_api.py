import httpx
import openai
from fastapi.testclient import TestClient

from app.ai.assistant import AssistantError, PropertyAssistant
from app.ai.conversation_store import ConversationStore
from app.api.deps import get_assistant
from app.config import get_settings
from app.schemas import PropertySearchFilters
from app.services import property_service as svc
from tests.conftest import FakeClient, FakeItem, FakeResponse, final, function_call


def test_health(client):
    body = client.get("/api/health").json()
    assert body["database"] is True and body["listings"] == 55


def test_get_property_404(client):
    r = client.get("/api/properties/99999")
    assert r.status_code == 404 and "not found" in r.json()["detail"]


def test_rest_search(client):
    r = client.get("/api/properties", params={"location": "Ruiru", "min_bedrooms": 3, "max_price_kes": 80000})
    assert r.status_code == 200 and r.json()["total_matches"] == 5


def test_chat_validation(client):
    assert client.post("/api/chat", json={"message": "   "}).status_code == 422
    assert client.post("/api/chat", json={"message": "x" * 1001}).status_code == 422
    assert client.post("/api/chat", json={}).status_code == 422
    r = client.post("/api/chat", json={"message": "hi", "conversation_id": "../../etc"})
    assert r.status_code == 422 and r.json()["detail"] == "The request was invalid."


def test_chat_search_then_follow_up(client, use_fake_ai):
    search_args = {"location": "Ruiru", "property_type": "apartment", "min_bedrooms": 3, "max_bedrooms": None,
                   "min_bathrooms": None, "max_price_kes": 80000, "furnished": True, "keywords": None,
                   "sort_by": "price_asc", "limit": None}

    def follow_up(kwargs):
        # The second turn must see the first turn's tool call and its results.
        items = kwargs["input"]
        assert any(i.get("type") == "function_call_output" for i in items)
        assert items[-1] == {"role": "user", "content": "Which one is cheapest?"}
        assert not any("id" in i for i in items if i.get("type") == "function_call")
        return final("The lowest-priced is the Membley apartment at KES 52,000.", [2])

    fake = use_fake_ai([
        FakeResponse([function_call("search_properties", search_args)]),
        final("I found 3 furnished 3-bedroom apartments in Ruiru within KES 80,000.", [2, 4, 5, 9999]),
        follow_up,
    ])

    r1 = client.post("/api/chat", json={"message": "Furnished 3 bed in Ruiru under 80k"})
    assert r1.status_code == 200
    body = r1.json()
    assert [p["id"] for p in body["properties"]] == [2, 4, 5]  # 9999 was never returned by a tool
    assert body["tool_calls"][0]["name"] == "search_properties"
    assert "limit" not in body["tool_calls"][0]["arguments"]

    second_call_input = fake.responses.calls[1]["input"]
    assert second_call_input[-1]["type"] == "function_call_output"

    r2 = client.post("/api/chat", json={"message": "Which one is cheapest?", "conversation_id": body["conversation_id"]})
    assert r2.status_code == 200
    assert [p["id"] for p in r2.json()["properties"]] == [2]
    assert r2.json()["tool_calls"] == []


def test_reset_conversation(client, use_fake_ai):
    def fresh(kwargs):
        assert len(kwargs["input"]) == 1  # history was cleared
        return final("Fresh start.", [])

    use_fake_ai([final("Hello!", []), fresh])
    cid = client.post("/api/chat", json={"message": "hi"}).json()["conversation_id"]
    assert client.delete(f"/api/chat/{cid}").status_code == 204
    assert client.post("/api/chat", json={"message": "hi again", "conversation_id": cid}).status_code == 200


def test_malformed_reply_falls_back_to_text(client, use_fake_ai):
    use_fake_ai([FakeResponse([], output_text="plain text answer")])
    body = client.post("/api/chat", json={"message": "hi"}).json()
    assert body["reply"] == "plain text answer" and body["properties"] == []


def test_model_refusal_is_shown_as_a_reply(client, use_fake_ai):
    refusal = FakeItem(type="message", role="assistant",
                       content=[FakeItem(type="refusal", refusal="I can only help with rental listings.")])
    use_fake_ai([FakeResponse([refusal], output_text="")])
    r = client.post("/api/chat", json={"message": "write me a poem"})
    assert r.status_code == 200
    assert r.json()["reply"] == "I can only help with rental listings." and r.json()["properties"] == []


def test_history_reset_is_reported_for_unknown_conversation(client, use_fake_ai):
    use_fake_ai([final("Hi.", []), final("Still here.", []), final("Fresh start.", [])])
    first = client.post("/api/chat", json={"message": "hi"}).json()
    assert first["history_reset"] is False
    again = client.post("/api/chat", json={"message": "and?", "conversation_id": first["conversation_id"]}).json()
    assert again["history_reset"] is False
    lost = client.post("/api/chat", json={"message": "which is cheapest?", "conversation_id": "gone-after-restart"})
    assert lost.json()["history_reset"] is True


def test_missing_seed_file_is_logged_at_startup(monkeypatch, caplog, tmp_path):
    from app.config import get_settings
    from app.main import app

    monkeypatch.setattr(get_settings(), "seed_file", tmp_path / "missing.json")
    with TestClient(app):
        pass
    assert "not found" in caplog.text


def test_rest_search_rejects_inverted_bedroom_range(client):
    r = client.get("/api/properties", params={"min_bedrooms": 3, "max_bedrooms": 2})
    assert r.status_code == 422


def _req():
    return httpx.Request("POST", "https://api.openai.com/v1/responses")


def test_openai_errors_are_friendly(client, use_fake_ai):
    cases = [
        (openai.AuthenticationError("bad key sk-secret", response=httpx.Response(401, request=_req()), body=None), 503),
        (openai.RateLimitError("slow down", response=httpx.Response(429, request=_req()), body=None), 429),
        (openai.APITimeoutError(request=_req()), 504),
        (openai.APIConnectionError(request=_req()), 503),
    ]
    for exc, code in cases:
        use_fake_ai([exc])
        r = client.post("/api/chat", json={"message": "hi"})
        assert r.status_code == code
        assert "sk-secret" not in r.text and "Traceback" not in r.text


def test_unhandled_error_is_generic_and_keeps_cors_headers(client):
    class Broken:
        def chat(self, *args):
            raise RuntimeError("secret internal detail")

    app = client.app
    app.dependency_overrides[get_assistant] = lambda: Broken()
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/api/chat", json={"message": "hi"}, headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 500
    assert r.json()["detail"] == "Something went wrong on our side. Please try again."
    assert "secret internal detail" not in r.text
    # Without it, a cross-origin browser hides the response.
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_missing_api_key(client, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "openai_api_key", "")
    r = client.post("/api/chat", json={"message": "hi"})
    assert r.status_code == 503 and "OPENAI_API_KEY" in r.json()["detail"]


def test_tool_loop_is_bounded(client, use_fake_ai):
    loop = [FakeResponse([function_call("search_locations", {"query": None}, f"c{i}")]) for i in range(10)]
    use_fake_ai(loop)
    r = client.post("/api/chat", json={"message": "loop forever"})
    assert r.status_code == 502 and "rephrasing" in r.json()["detail"]


def _search(location: str) -> dict:
    return {"location": location, "property_type": None, "min_bedrooms": None, "max_bedrooms": None,
            "min_bathrooms": None, "max_price_kes": None, "furnished": None, "keywords": None,
            "sort_by": "price_asc", "limit": None}


def test_concurrent_turn_on_same_conversation_is_refused(db):
    store = ConversationStore()
    outcome = {}

    def overlapping(_):
        try:
            assistant.chat(db, "second message", "c1")
        except AssistantError as exc:
            outcome["status"] = exc.status_code
        return final("First reply.", [])

    assistant = PropertyAssistant(FakeClient([overlapping, final("Third reply.", [])]), get_settings(), store)
    assert assistant.chat(db, "first message", "c1").reply == "First reply."
    assert outcome["status"] == 409
    # The first turn was saved and the conversation is free again.
    assert assistant.chat(db, "third message", "c1").reply == "Third reply."
    assert [i["content"] for i in store.get("c1").items if i.get("role") == "user"] == [
        "first message", "third message"]


def test_cards_are_limited_to_retained_history(db):
    store = ConversationStore(max_turns=1)
    thika_ids = [p.id for p in svc.search_properties(db, PropertySearchFilters(location="Thika")).results]
    assistant = PropertyAssistant(FakeClient([
        FakeResponse([function_call("search_properties", _search("Thika"))]),
        final("Listings in Thika.", thika_ids[:1]),
        final("That Thika listing again.", thika_ids[:1]),
        final("And again.", thika_ids[:1]),
    ]), get_settings(), store)

    first = assistant.chat(db, "Thika rentals", None)
    cid = first.conversation_id
    assert [p.id for p in first.properties] == thika_ids[:1]
    # Turn 1 is still in the history the model saw for turn 2.
    assert [p.id for p in assistant.chat(db, "show it again", cid).properties] == thika_ids[:1]
    # Saving turn 2 trimmed turn 1, so its listings are no longer allowed as cards.
    assert assistant.chat(db, "once more", cid).properties == []
