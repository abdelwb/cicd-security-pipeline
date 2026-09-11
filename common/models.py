from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class JobState(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class JobSubmission(BaseModel):
    """Payload accepted by POST /jobs.

    `payload` is intentionally an open dict so the demo failure modes
    (circuit breaker / backpressure / OOM) can be triggered without
    changing the API contract:
        {"simulate": "oom", "size_mb": 512}
        {"simulate": "slow", "duration_s": 3}
        {"simulate": "fail"}
    """

    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=0, ge=0, le=9)


class JobStatus(BaseModel):
    job_id: str
    state: JobState
    submitted_at: float
    updated_at: float
    result: Optional[str] = None
    error: Optional[str] = None
