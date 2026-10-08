from app.api.deps import get_chat_limiter
from app.api.rate_limit import ChatRateLimiter
from tests.conftest import final


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def limiter(per_minute=100, per_day=100, global_per_day=100):
    clock = Clock()
    return ChatRateLimiter(per_minute, per_day, global_per_day, clock=clock), clock


def test_per_minute_limit_and_recovery():
    rl, clock = limiter(per_minute=2)
    assert rl.check("a") is None and rl.check("a") is None
    blocked = rl.check("a")
    assert blocked and "too quickly" in blocked.message and 0 < blocked.retry_after <= 60
    clock.now += 61
    assert rl.check("a") is None  # blocked attempts were not counted


def test_per_day_limit_is_per_client():
    rl, clock = limiter(per_day=3)
    for _ in range(3):
        assert rl.check("a") is None
        clock.now += 61
    assert "today's message limit" in rl.check("a").message
    assert rl.check("b") is None


def test_global_daily_cap_applies_across_clients():
    rl, _ = limiter(global_per_day=3)
    for ip in ("a", "b", "c"):
        assert rl.check(ip) is None
    blocked = rl.check("d")
    assert blocked and "daily usage limit" in blocked.message


def test_day_window_slides():
    rl, clock = limiter(per_day=1)
    assert rl.check("a") is None
    clock.now += 24 * 3600 - 10
    assert rl.check("a").retry_after == 10
    clock.now += 11
    assert rl.check("a") is None


def test_chat_endpoint_returns_429_when_limited(client, use_fake_ai):
    use_fake_ai([final("Hi.", [])])
    tight = ChatRateLimiter(1, 100, 100)
    client.app.dependency_overrides[get_chat_limiter] = lambda: tight
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 200
    r = client.post("/api/chat", json={"message": "again"})
    assert r.status_code == 429 and "too quickly" in r.json()["detail"]
    assert int(r.headers["retry-after"]) > 0
    # Only the paid endpoint is limited.
    assert client.get("/api/properties").status_code == 200
    assert client.delete("/api/chat/abc").status_code == 204


def test_zero_or_negative_limits_are_treated_as_one():
    rl, _ = limiter(per_minute=0, per_day=-5, global_per_day=0)
    assert rl.check("a") is None
    assert rl.check("a") is not None
