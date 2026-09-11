"""Shared configuration for the gateway and worker services.

Everything is read from the environment so the same image can be reused
across local docker-compose, k3s, and CI without rebuilding.
"""
import os


class Settings:
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Backpressure: reject new submissions once the pending queue is this long.
    max_queue_length: int = int(os.getenv("MAX_QUEUE_LENGTH", "50"))

    # Circuit breaker tuning (shared by gateway + worker Redis calls).
    cb_failure_threshold: int = int(os.getenv("CB_FAILURE_THRESHOLD", "5"))
    cb_reset_timeout_s: float = float(os.getenv("CB_RESET_TIMEOUT_S", "10"))

    queue_key: str = os.getenv("QUEUE_KEY", "jobs:queue")
    status_key_prefix: str = os.getenv("STATUS_KEY_PREFIX", "jobs:status:")

    worker_poll_timeout_s: int = int(os.getenv("WORKER_POLL_TIMEOUT_S", "5"))
    metrics_port: int = int(os.getenv("METRICS_PORT", "9100"))


settings = Settings()
