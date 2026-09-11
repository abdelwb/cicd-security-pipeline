"""A minimal three-state circuit breaker (CLOSED / OPEN / HALF_OPEN).

Used to wrap every Redis call made by the gateway and the worker so that a
Redis outage degrades the system predictably (fast failures + automatic
recovery probing) instead of piling up hung connections. This is the
behavior exercised by the "Redis down" failure demo described in the
README.
"""
import time
from enum import Enum
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """Raised instead of calling downstream when the breaker is OPEN."""


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, reset_timeout_s: float = 10.0):
        self.failure_threshold = failure_threshold
        self.reset_timeout_s = reset_timeout_s
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> CircuitState:
        if (
            self._state is CircuitState.OPEN
            and self._opened_at is not None
            and (time.monotonic() - self._opened_at) >= self.reset_timeout_s
        ):
            # Cool-down elapsed: allow exactly one probe through.
            self._state = CircuitState.HALF_OPEN
        return self._state

    def _on_success(self) -> None:
        self._failure_count = 0
        self._state = CircuitState.CLOSED
        self._opened_at = None

    def _on_failure(self) -> None:
        self._failure_count += 1
        if self._state is CircuitState.HALF_OPEN or self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()

    async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
        if self.state is CircuitState.OPEN:
            raise CircuitOpenError("circuit breaker is open; refusing to call Redis")
        try:
            result = await fn()
        except Exception:
            self._on_failure()
            raise
        else:
            self._on_success()
            return result
