import time

import pytest

from common.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState


async def _ok():
    return "ok"


async def _boom():
    raise ConnectionError("redis unreachable")


@pytest.mark.asyncio
async def test_starts_closed():
    cb = CircuitBreaker()
    assert cb.state is CircuitState.CLOSED
    assert await cb.call(_ok) == "ok"


@pytest.mark.asyncio
async def test_opens_after_threshold_failures():
    cb = CircuitBreaker(failure_threshold=3, reset_timeout_s=60)
    for _ in range(3):
        with pytest.raises(ConnectionError):
            await cb.call(_boom)
    assert cb.state is CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        await cb.call(_ok)


@pytest.mark.asyncio
async def test_half_open_recovers_on_success():
    cb = CircuitBreaker(failure_threshold=1, reset_timeout_s=0)
    with pytest.raises(ConnectionError):
        await cb.call(_boom)
    assert cb.state is CircuitState.HALF_OPEN  # reset_timeout_s=0 -> cooled down immediately
    assert await cb.call(_ok) == "ok"
    assert cb.state is CircuitState.CLOSED


@pytest.mark.asyncio
async def test_half_open_reopens_on_repeat_failure():
    # A non-zero reset_timeout_s so OPEN is stably observable; the cooldown
    # is then faked as already elapsed to force exactly one half-open probe
    # (using reset_timeout_s=0 for that, as the other tests do, would make
    # every `.state` read report HALF_OPEN immediately - including right
    # after this test's second failure re-opens the breaker - since "elapsed
    # >= 0" is trivially true).
    cb = CircuitBreaker(failure_threshold=1, reset_timeout_s=60)
    with pytest.raises(ConnectionError):
        await cb.call(_boom)
    assert cb.state is CircuitState.OPEN

    cb._opened_at = time.monotonic() - 61  # simulate the cooldown elapsing
    assert cb.state is CircuitState.HALF_OPEN

    with pytest.raises(ConnectionError):
        await cb.call(_boom)
    assert cb.state is CircuitState.OPEN
