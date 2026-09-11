"""Redis-backed job worker.

Pulls job descriptors off the shared queue with BLPOP, updates job status in
a Redis hash, and honors a few `simulate` directives in the payload so the
system's failure behavior can be demonstrated on purpose:

    {"simulate": "slow", "duration_s": 3}   -> sleeps, then succeeds
    {"simulate": "fail"}                     -> raises, job marked failed
    {"simulate": "oom", "size_mb": 512}       -> allocates memory (see oom_sim.py)

Also wraps every Redis call in the same CircuitBreaker used by the gateway,
so a Redis outage makes the worker back off instead of busy-looping.
"""
import asyncio
import json
import logging
import time

from prometheus_client import Counter, Gauge, start_http_server

from common.circuit_breaker import CircuitBreaker, CircuitOpenError
from common.models import JobState
from common.redis_client import close_redis, get_redis
from common.settings import settings
from worker.oom_sim import allocate_and_hold

logging.basicConfig(level=logging.INFO, format="%(asctime)s worker %(levelname)s %(message)s")
log = logging.getLogger("worker")

jobs_processed_total = Counter("jobs_processed_total", "Jobs the worker finished", ["outcome"])
worker_up = Gauge("worker_up", "1 while the worker's main loop is running")


async def _set_status(r, job_id: str, **fields) -> None:
    fields["updated_at"] = time.time()
    await r.hset(f"{settings.status_key_prefix}{job_id}", mapping=fields)


async def process_job(r, job: dict, breaker: CircuitBreaker) -> None:
    job_id = job["job_id"]
    payload = job.get("payload") or {}
    simulate = payload.get("simulate")

    await breaker.call(lambda: _set_status(r, job_id, state=JobState.PROCESSING.value))

    try:
        if simulate == "fail":
            raise RuntimeError("job requested simulated failure")
        if simulate == "slow":
            await asyncio.sleep(float(payload.get("duration_s", 1)))
        if simulate == "oom":
            # Runs synchronously on purpose: we want this coroutine (and the
            # process) to actually feel the memory pressure.
            allocate_and_hold(int(payload.get("size_mb", 256)))
    except Exception as exc:  # noqa: BLE001 - deliberately broad: any job error is "failed"
        jobs_processed_total.labels(outcome="failed").inc()
        await breaker.call(
            lambda: _set_status(r, job_id, state=JobState.FAILED.value, error=str(exc))
        )
        log.warning("job %s failed: %s", job_id, exc)
        return

    jobs_processed_total.labels(outcome="done").inc()
    await breaker.call(lambda: _set_status(r, job_id, state=JobState.DONE.value, result="ok"))
    log.info("job %s done", job_id)


async def main() -> None:
    start_http_server(settings.metrics_port)
    r = get_redis()
    breaker = CircuitBreaker(
        failure_threshold=settings.cb_failure_threshold,
        reset_timeout_s=settings.cb_reset_timeout_s,
    )
    worker_up.set(1)
    log.info("worker started, polling %s", settings.queue_key)

    try:
        while True:
            try:
                popped = await breaker.call(
                    lambda: r.blpop([settings.queue_key], timeout=settings.worker_poll_timeout_s)
                )
            except CircuitOpenError:
                log.warning("circuit breaker open, backing off %.1fs", settings.cb_reset_timeout_s)
                await asyncio.sleep(settings.cb_reset_timeout_s)
                continue
            except Exception as exc:  # noqa: BLE001 - Redis connection errors etc.
                log.error("redis error while polling: %s", exc)
                await asyncio.sleep(1)
                continue

            if popped is None:
                continue  # poll timeout, nothing queued
            _, raw = popped
            job = json.loads(raw)
            await process_job(r, job, breaker)
    finally:
        worker_up.set(0)
        await close_redis()


if __name__ == "__main__":
    asyncio.run(main())
