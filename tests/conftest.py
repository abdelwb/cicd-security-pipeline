import fakeredis
import pytest

from common import redis_client


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    """Point every service at an in-memory Redis for the whole test session."""
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(redis_client, "_client", fake)
    yield fake
