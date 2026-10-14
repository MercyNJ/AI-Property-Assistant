import json
from typing import get_args

import pytest
from pydantic import ValidationError

from app.ai.conversation_store import ConversationStore
from app.ai.tools import TOOLS, run_tool
from app.config import PROJECT_ROOT, Settings
from app.models import PROPERTY_TYPES, Property
from app.schemas import PropertySearchFilters
from app.schemas.property import PropertyType
from app.services import property_service as svc


def search(db, **kw):
    return svc.search_properties(db, PropertySearchFilters(**kw))


def test_demo_query_returns_only_matching_listings(db):
    r = search(db, location="Ruiru", property_type="apartment", min_bedrooms=3, max_price_kes=80000, furnished=True)
    assert r.total_matches >= 2
    for p in r.results:
        assert p.location == "Ruiru" and p.bedrooms >= 3 and p.price_kes <= 80000 and p.furnished


def test_exact_bedroom_count_excludes_larger_units(db):
    exact = search(db, location="Ruiru", min_bedrooms=2, max_bedrooms=2, limit=10)
    at_least = search(db, location="Ruiru", min_bedrooms=2, limit=10)
    assert exact.total_matches == 3 and {p.bedrooms for p in exact.results} == {2}
    assert at_least.total_matches == 11  # what a min-only reading of "2-bedroom" would return


def test_prompt_and_tool_state_the_exact_bedroom_rule():
    from app.ai.prompts import SYSTEM_PROMPT

    params = next(t for t in TOOLS if t["name"] == "search_properties")["parameters"]["properties"]
    assert "means exactly that number" in SYSTEM_PROMPT
    assert "exact count" in params["min_bedrooms"]["description"]


def test_results_are_sorted_by_price_by_default(db):
    prices = [p.price_kes for p in search(db, location="Kilimani").results]
    assert prices == sorted(prices)


@pytest.mark.parametrize("loc,expected", [("nairobi", {"Westlands", "Kilimani", "Kasarani"}),
                                          ("Kamakis", {"Ruiru"}), ("Machakos County", {"Syokimau"})])
def test_location_matches_town_county_or_neighbourhood(db, loc, expected):
    r = search(db, location=loc, limit=10)
    assert r.total_matches > 0
    assert {p.location for p in r.results} <= expected


@pytest.mark.parametrize("phrase,expected", [
    ("Westlands, Nairobi", "Westlands"), ("Ruiru, Kiambu County", "Ruiru"), ("Kasarani town", "Kasarani"),
    ("Ruiru town", "Ruiru Town"),  # a real neighbourhood, so the more specific match wins
    ("Kilimani area", "Kilimani"), ("Nairobi, Kenya", "Nairobi"), ("kamakis", "Kamakis"),
])
def test_location_phrasings_resolve_to_a_known_place(db, phrase, expected):
    r = search(db, location=phrase, limit=10)
    assert r.total_matches > 0 and r.criteria_applied["location"] == expected


def test_stored_name_wins_over_an_alias(db):
    # "thika town" is an alias for Thika, but a neighbourhood with that exact name must not widen to all of Thika.
    db.add(Property(id=9002, title="Test flat", location="Thika", neighbourhood="Thika Town", county="Kiambu",
                    property_type="apartment", bedrooms=1, bathrooms=1, price_kes=20000, furnished=False,
                    description="Test listing."))
    db.flush()
    try:
        r = search(db, location="Thika Town", limit=10)
        assert r.criteria_applied["location"] == "Thika Town" and [p.id for p in r.results] == [9002]
    finally:
        db.rollback()


def test_named_town_is_not_widened_to_its_county(db):
    r = search(db, location="Kiambu Town", limit=10)
    assert r.total_matches == 5 and {p.location for p in r.results} == {"Kiambu Town"}


def test_property_type_literal_matches_model_constant():
    assert get_args(PropertyType) == PROPERTY_TYPES


def test_keywords_match_description(db):
    r = search(db, keywords="pool", limit=10)
    assert r.total_matches > 0
    assert all("pool" in p.description.lower() for p in r.results)


def test_welcome_example_kilimani_swimming_pool_finds_the_pool_listing(db):
    r = search(db, location="Kilimani", keywords="swimming pool")
    assert [p.id for p in r.results] == [27]  # its description says "pool", not "swimming pool"


@pytest.mark.parametrize("phrase,equivalent", [
    ("swimming pool", "pool"), ("swimming pools", "pool"), ("with a pool", "pool"), ("gyms", "gym"),
    ("balconies", "balcony"), ("parking spaces", "parking"), ("servants' quarters", "DSQ"), ("wifi", "wi-fi"),
])
def test_keyword_phrasings_match_listing_wording(db, phrase, equivalent):
    expected = search(db, keywords=equivalent, limit=10)
    assert expected.total_matches > 0
    assert search(db, keywords=phrase, limit=10).total_matches == expected.total_matches


@pytest.mark.parametrize("query", ["balcony", "balconies"])
def test_ies_plurals_match_both_spellings_in_listings(db, query):
    db.add(Property(id=9001, title="Test flat", location="Thika", neighbourhood="Makongeni", county="Kiambu",
                    property_type="apartment", bedrooms=2, bathrooms=1, price_kes=30000, furnished=False,
                    description="Two balconies and a laundry area."))
    db.flush()
    try:
        assert 9001 in {p.id for p in search(db, keywords=query, location="Thika", limit=10).results}
    finally:
        db.rollback()


@pytest.mark.parametrize("word", ["study", "key", "gym", "pool", "dsq"])
def test_short_words_are_not_over_trimmed(word):
    assert svc._keyword_terms(word) == [word]


def test_every_keyword_must_still_match(db):
    both = search(db, keywords="pool gym", limit=10)
    assert both.total_matches > 0
    assert all("pool" in p.description.lower() and "gym" in p.description.lower() for p in both.results)


def test_no_match_returns_relaxation_suggestions(db):
    r = search(db, location="Ruiru", min_bedrooms=3, furnished=True, max_price_kes=40000)
    assert r.total_matches == 0 and r.results == []
    budget = next(s for s in r.relaxation_suggestions if s.get("remove_criterion") == "max_price_kes")
    assert budget["lowest_matching_price_kes"] == 52000


def test_unknown_location_is_flagged(db):
    r = search(db, location="Mombasa")
    assert r.total_matches == 0
    assert "not a location" in r.relaxation_suggestions[0]["note"]


def test_get_property_invalid_id(db):
    with pytest.raises(svc.PropertyNotFound):
        svc.get_property(db, 99999)


def test_compare_summary(db):
    result = svc.compare_properties(db, [1, 2, 99999])
    assert result["missing_ids"] == [99999]
    assert result["summary"]["lowest_price_id"] == 1
    assert result["summary"]["furnished_ids"] == [2]


def test_location_summary_covers_whole_location_when_filtered_by_neighbourhood(db):
    ruiru = next(loc for loc in svc.list_locations(db) if loc.location == "Ruiru")
    assert svc.list_locations(db, "Kamakis") == [ruiru]


@pytest.mark.parametrize("text", ["%", "_", "100%"])
def test_like_wildcards_in_user_text_are_literal(db, text):
    assert search(db, keywords=text).total_matches == 0
    assert svc.list_locations(db, text) == []


def test_inverted_bedroom_range_is_rejected():
    with pytest.raises(ValidationError):
        PropertySearchFilters(min_bedrooms=3, max_bedrooms=2)


def test_compare_lists_each_missing_id_once(db):
    assert svc.compare_properties(db, [1, 2, 99999, 99999])["missing_ids"] == [99999]


def test_relative_seed_file_resolves_from_project_root(monkeypatch):
    monkeypatch.setenv("SEED_FILE", "data/properties.json")
    assert Settings().seed_file == PROJECT_ROOT / "data" / "properties.json"


@pytest.mark.parametrize("raw", ["null", "[1, 2]", "5", '"text"'])
def test_tool_dispatch_rejects_non_object_arguments(db, raw):
    for name in ("search_properties", "get_property", "compare_properties", "search_locations"):
        assert "error" in json.loads(run_tool(db, name, raw).output)


def test_empty_env_values_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("SEED_FILE", "")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("OPENAI_MODEL", "")
    s = Settings()
    assert s.seed_file == PROJECT_ROOT / "data" / "properties.json"
    assert s.database_url.startswith("sqlite:///") and s.database_url.endswith("properties.db")
    assert s.openai_model == "gpt-5.4-mini"


def test_history_limit_below_one_keeps_one_turn():
    items = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
             {"role": "user", "content": "c"}, {"role": "assistant", "content": "d"}]
    assert ConversationStore(max_turns=0)._trim(items) == items[2:]


def test_tool_schemas_are_strict():
    for tool in TOOLS:
        params = tool["parameters"]
        assert tool["strict"] is True and params["additionalProperties"] is False
        assert set(params["required"]) == set(params["properties"])


def test_tool_dispatch_validates_arguments(db):
    bad = json.loads(run_tool(db, "search_properties", json.dumps({"property_type": "castle"})).output)
    assert "Invalid arguments" in bad["error"]
    assert "error" in json.loads(run_tool(db, "drop_tables", "{}").output)
    assert "error" in json.loads(run_tool(db, "get_property", "not json").output)


def test_tool_dispatch_ignores_nulls_and_clamps_limit(db):
    args = {"location": "Thika", "property_type": None, "min_bedrooms": None, "max_bedrooms": None,
            "min_bathrooms": None, "max_price_kes": None, "furnished": None, "keywords": None,
            "sort_by": "price_desc", "limit": 50}
    result = run_tool(db, "search_properties", json.dumps(args))
    data = json.loads(result.output)
    assert data["total_matches"] == 6 and len(data["results"]) == 6
    assert result.property_ids[0] == data["results"][0]["id"]
