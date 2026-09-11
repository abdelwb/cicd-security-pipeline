import redis.asyncio as redis

from .settings import settings

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """Lazily create a single shared async Redis client per process."""
    global _client
    if _client is None:
        _client = redis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
