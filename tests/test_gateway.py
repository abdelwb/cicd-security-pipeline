import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from common.settings import settings
from gateway.main import app


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_does_not_touch_redis(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_ready_ok_when_redis_up(client):
    resp = await client.get("/ready")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_submit_and_fetch_job(client):
    resp = await client.post("/jobs", json={"payload": {"simulate": "slow", "duration_s": 0}})
    assert resp.status_code == 202
    job = resp.json()
    assert job["state"] == "queued"

    resp = await client.get(f"/jobs/{job['job_id']}")
    assert resp.status_code == 200
    assert resp.json()["job_id"] == job["job_id"]


@pytest.mark.asyncio
async def test_unknown_job_is_404(client):
    resp = await client.get("/jobs/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_backpressure_rejects_when_queue_full(client, fake_redis):
    await fake_redis.rpush(settings.queue_key, *["x"] * settings.max_queue_length)
    resp = await client.post("/jobs", json={"payload": {}})
    assert resp.status_code == 503
    assert "Retry-After" in resp.headers


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_prometheus_text(client):
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert b"jobs_submitted_total" in resp.content
