"""FastAPI gateway: accepts job submissions, applies backpressure, and
protects itself from a struggling Redis with a circuit breaker.
"""
import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

from common.circuit_breaker import CircuitBreaker, CircuitOpenError
from common.models import JobState, JobStatus, JobSubmission
from common.redis_client import close_redis, get_redis
from common.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await close_redis()


app = FastAPI(title="job-gateway", version="1.0.0", lifespan=lifespan)
breaker = CircuitBreaker(
    failure_threshold=settings.cb_failure_threshold,
    reset_timeout_s=settings.cb_reset_timeout_s,
)

jobs_submitted_total = Counter("jobs_submitted_total", "Jobs accepted by the gateway")
jobs_rejected_backpressure_total = Counter(
    "jobs_rejected_backpressure_total", "Jobs rejected because the queue was full"
)
jobs_rejected_circuit_open_total = Counter(
    "jobs_rejected_circuit_open_total", "Jobs rejected because the circuit breaker was open"
)
circuit_breaker_state = Gauge(
    "circuit_breaker_state", "0=closed, 1=half_open, 2=open", ["component"]
)

_STATE_VALUE = {"closed": 0, "half_open": 1, "open": 2}


@app.get("/health")
async def health() -> dict:
    """Liveness: process is up. Does not touch Redis."""
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> Response:
    """Readiness: only healthy while Redis is reachable and the breaker is closed."""
    if breaker.state.value == "open":
        raise HTTPException(status_code=503, detail="circuit breaker open")
    try:
        await breaker.call(lambda: get_redis().ping())
    except Exception as exc:  # noqa: BLE001 - readiness probe reports any failure, breaker-open included
        raise HTTPException(status_code=503, detail=f"redis unreachable: {exc}") from exc
    return Response(status_code=204)


@app.get("/metrics")
async def metrics() -> Response:
    circuit_breaker_state.labels(component="gateway").set(_STATE_VALUE[breaker.state.value])
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/jobs", status_code=202)
async def submit_job(submission: JobSubmission) -> JobStatus:
    r = get_redis()

    # --- Backpressure -----------------------------------------------------
    try:
        queue_length = await breaker.call(lambda: r.llen(settings.queue_key))
    except CircuitOpenError as exc:
        jobs_rejected_circuit_open_total.inc()
        raise HTTPException(status_code=503, detail="downstream unavailable, try later") from exc
    except Exception as exc:  # noqa: BLE001 - genuine Redis failure, not breaker-open
        jobs_rejected_circuit_open_total.inc()
        raise HTTPException(status_code=503, detail=f"redis error: {exc}") from exc

    if queue_length >= settings.max_queue_length:
        jobs_rejected_backpressure_total.inc()
        raise HTTPException(
            status_code=503,
            detail=f"queue full ({queue_length}/{settings.max_queue_length}); retry later",
            headers={"Retry-After": "5"},
        )

    # --- Enqueue ------------------------------------------------------------
    job_id = str(uuid.uuid4())
    now = time.time()
    status = JobStatus(job_id=job_id, state=JobState.QUEUED, submitted_at=now, updated_at=now)

    async def _enqueue() -> None:
        pipe = r.pipeline()
        pipe.hset(
            f"{settings.status_key_prefix}{job_id}",
            mapping=status.model_dump(mode="json", exclude_none=True),
        )
        pipe.rpush(settings.queue_key, json.dumps({"job_id": job_id, **submission.model_dump()}))
        await pipe.execute()

    try:
        await breaker.call(_enqueue)
    except CircuitOpenError as exc:
        jobs_rejected_circuit_open_total.inc()
        raise HTTPException(status_code=503, detail="downstream unavailable, try later") from exc
    except Exception as exc:  # noqa: BLE001
        jobs_rejected_circuit_open_total.inc()
        raise HTTPException(status_code=503, detail=f"redis error: {exc}") from exc

    jobs_submitted_total.inc()
    return status


@app.get("/jobs/{job_id}")
async def get_job(job_id: str) -> JobStatus:
    r = get_redis()
    try:
        data = await breaker.call(lambda: r.hgetall(f"{settings.status_key_prefix}{job_id}"))
    except CircuitOpenError as exc:
        raise HTTPException(status_code=503, detail="downstream unavailable, try later") from exc
    if not data:
        raise HTTPException(status_code=404, detail="job not found")
    return JobStatus(**data)
