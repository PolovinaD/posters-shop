"""
Circuit breaker for inter-service HTTP calls.

States: closed (normal) → open (failing fast) → half_open (probing)

Failure classification (per D-03):
  - Counts: 5xx HTTP responses raised as service-specific errors, httpx.RequestError
  - Ignores: 4xx business errors (InsufficientStockError, SkuNotFoundError, etc.)
"""
import asyncio
import os
import time
from typing import Callable, Awaitable, TypeVar

import httpx

from metrics import CIRCUIT_BREAKER_STATE_TRANSITIONS

T = TypeVar("T")

STATE_CLOSED = "closed"
STATE_OPEN = "open"
STATE_HALF_OPEN = "half_open"

# Exception types that are business errors (4xx) and must NOT trip the circuit.
# Import lazily to avoid circular imports — checked by module path string comparison.
_BUSINESS_ERROR_NAMES = frozenset({
    "InsufficientStockError",
    "SkuNotFoundError",
})


class CircuitOpenError(Exception):
    """Raised when a circuit breaker is open and the call is rejected."""

    def __init__(self, service: str):
        self.service = service
        super().__init__(f"{service} service unavailable — circuit open")


class CircuitBreaker:
    """
    Three-state circuit breaker (closed / open / half_open).

    Args:
        service: Label used in Prometheus metrics ("inventory" or "payments").
        failure_threshold: Consecutive failures before circuit opens.
        recovery_timeout: Seconds to wait in open state before probing.
    """

    def __init__(self, service: str, failure_threshold: int, recovery_timeout: float):
        self.service = service
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self._state = STATE_CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def call(self, coro_fn: Callable[[], Awaitable[T]]) -> T:
        """
        Execute the coroutine through the circuit breaker.

        Raises CircuitOpenError if the circuit is open.
        Re-raises the original exception on failure (after recording it).
        """
        async with self._lock:
            state = self._get_state()

            if state == STATE_OPEN:
                raise CircuitOpenError(self.service)

            if state == STATE_HALF_OPEN:
                # Allow this single probe through; handle result below
                pass

        try:
            result = await coro_fn()
            # Success path
            async with self._lock:
                if self._state == STATE_HALF_OPEN:
                    self._transition(STATE_CLOSED)
                self._failure_count = 0
            return result

        except Exception as exc:
            async with self._lock:
                if self._is_failure(exc):
                    self._failure_count += 1
                    if self._state == STATE_HALF_OPEN or self._failure_count >= self.failure_threshold:
                        self._transition(STATE_OPEN)
                        self._opened_at = time.monotonic()
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_state(self) -> str:
        """Return effective state, promoting open → half_open if timeout elapsed."""
        if self._state == STATE_OPEN:
            if self._opened_at is not None and (time.monotonic() - self._opened_at) >= self.recovery_timeout:
                self._transition(STATE_HALF_OPEN)
        return self._state

    def _transition(self, new_state: str) -> None:
        """Record a state transition and emit the Prometheus counter."""
        old_state = self._state
        self._state = new_state
        CIRCUIT_BREAKER_STATE_TRANSITIONS.labels(
            service=self.service,
            from_state=old_state,
            to_state=new_state,
        ).inc()

    @staticmethod
    def _is_failure(exc: Exception) -> bool:
        """
        Return True if this exception counts as a circuit-tripping failure.

        Failures: httpx.RequestError, and any exception whose class name is NOT
        in _BUSINESS_ERROR_NAMES (i.e. InventoryServiceError, PaymentServiceError).
        Non-failures: InsufficientStockError, SkuNotFoundError (4xx business errors).
        """
        if isinstance(exc, httpx.RequestError):
            return True
        if type(exc).__name__ in _BUSINESS_ERROR_NAMES:
            return False
        # All other exceptions (InventoryServiceError, PaymentServiceError) count as failures
        return True
