import time

import pytest

from common.circuit_breaker import CircuitBreaker
from common.models import JobState
from common.settings import settings
from worker.worker import process_job


async def _submit(fake_redis, payload):
    job_id = "test-job"
    await fake_redis.hset(
        f"{settings.status_key_prefix}{job_id}",
        mapping={"job_id": job_id, "state": JobState.QUEUED.value, "submitted_at": time.time(), "updated_at": time.time()},
    )
    return {"job_id": job_id, "payload": payload}


@pytest.mark.asyncio
async def test_process_job_success(fake_redis):
    job = await _submit(fake_redis, {})
    await process_job(fake_redis, job, CircuitBreaker())
    status = await fake_redis.hgetall(f"{settings.status_key_prefix}{job['job_id']}")
    assert status["state"] == JobState.DONE.value


@pytest.mark.asyncio
async def test_process_job_simulated_failure(fake_redis):
    job = await _submit(fake_redis, {"simulate": "fail"})
    await process_job(fake_redis, job, CircuitBreaker())
    status = await fake_redis.hgetall(f"{settings.status_key_prefix}{job['job_id']}")
    assert status["state"] == JobState.FAILED.value
    assert "error" in status


@pytest.mark.asyncio
async def test_process_job_slow_completes(fake_redis):
    job = await _submit(fake_redis, {"simulate": "slow", "duration_s": 0})
    await process_job(fake_redis, job, CircuitBreaker())
    status = await fake_redis.hgetall(f"{settings.status_key_prefix}{job['job_id']}")
    assert status["state"] == JobState.DONE.value
