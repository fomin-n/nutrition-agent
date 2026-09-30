"""Cooperative budget shared with retrieval workers via copied ContextVars."""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_DEADLINE: ContextVar[float | None] = ContextVar("request_deadline", default=None)


@contextmanager
def request_budget(seconds: float) -> Iterator[None]:
    token = _DEADLINE.set(time.monotonic() + seconds)
    try:
        yield
    finally:
        _DEADLINE.reset(token)


def bounded_timeout(maximum: float) -> float:
    deadline = _DEADLINE.get()
    if deadline is None:
        return maximum
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("request budget exhausted")
    return min(maximum, remaining)


def request_budget_active() -> bool:
    return _DEADLINE.get() is not None
