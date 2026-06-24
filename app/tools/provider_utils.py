import logging
import random
import re
import time
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

import httpx

LOGGER = logging.getLogger(__name__)

RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


class ProviderUnavailableError(RuntimeError):
    def __init__(self, provider: str, operation: str, reason: str, *, status_code: int | None = None) -> None:
        super().__init__(f"{provider} {operation} failed: {reason}")
        self.provider = provider
        self.operation = operation
        self.reason = reason
        self.status_code = status_code


def redacted_text(value: str) -> str:
    value = re.sub(r"(?i)(api[_-]?key=)[^&\s]+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)(authorization:\s*)(bearer|basic)\s+[^\s]+", r"\1\2 [REDACTED]", value)
    value = re.sub(r"(?i)(access_token[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)(client_secret[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+", r"\1[REDACTED]", value)
    return value


def request_json_with_retries(
    request: Callable[[], httpx.Response],
    *,
    provider: str,
    operation: str,
    max_retries: int = 2,
    backoff_base: float = 0.15,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    last_status: int | None = None
    for attempt in range(max_retries + 1):
        try:
            response = request()
            last_status = response.status_code
            if response.status_code in RETRY_STATUS_CODES and attempt < max_retries:
                _sleep_before_retry(backoff_base, attempt, sleep)
                continue
            if response.status_code in {401, 403, 429} or response.status_code >= 500:
                raise ProviderUnavailableError(
                    provider,
                    operation,
                    f"HTTP {response.status_code}",
                    status_code=response.status_code,
                )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ProviderUnavailableError(provider, operation, "malformed JSON payload", status_code=last_status)
            return payload
        except httpx.TimeoutException as exc:
            if attempt < max_retries:
                _sleep_before_retry(backoff_base, attempt, sleep)
                continue
            raise ProviderUnavailableError(provider, operation, "timeout") from exc
        except httpx.HTTPError as exc:
            if attempt < max_retries:
                _sleep_before_retry(backoff_base, attempt, sleep)
                continue
            raise ProviderUnavailableError(provider, operation, exc.__class__.__name__, status_code=last_status) from exc
        except ValueError as exc:
            raise ProviderUnavailableError(provider, operation, "malformed JSON payload", status_code=last_status) from exc

    raise ProviderUnavailableError(provider, operation, "unavailable", status_code=last_status)


def log_provider_failure(logger: logging.Logger, exc: ProviderUnavailableError, *, query: str | None = None) -> None:
    query_part = f" query={query!r}" if query else ""
    logger.warning(
        "%s provider operation=%s failed status=%s reason=%s%s",
        exc.provider,
        exc.operation,
        exc.status_code,
        redacted_text(exc.reason),
        redacted_text(query_part),
    )


@contextmanager
def retrieval_span(provider: str, operation: str, **attributes: str | int | float | bool | None):
    try:
        from openinference.instrumentation import get_attributes_from_context
        from openinference.semconv.trace import (
            OpenInferenceSpanKindValues,
            SpanAttributes,
        )
        from opentelemetry import trace
    except Exception:  # pragma: no cover - optional tracing dependency
        yield None
        return

    tracer = trace.get_tracer("nutrition-agent.retrieval")
    with tracer.start_as_current_span(f"nutrition.{provider}.{operation}") as span:
        span.set_attribute(
            SpanAttributes.OPENINFERENCE_SPAN_KIND,
            OpenInferenceSpanKindValues.TOOL.value,
        )
        span.set_attributes(dict(get_attributes_from_context()))
        span.set_attribute("nutrition.provider", provider)
        span.set_attribute("nutrition.operation", operation)
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(f"nutrition.{key}", value)
        yield span


def _sleep_before_retry(backoff_base: float, attempt: int, sleep: Callable[[float], None]) -> None:
    delay = backoff_base * (2**attempt) + random.uniform(0, backoff_base)
    if delay > 0:
        sleep(delay)
