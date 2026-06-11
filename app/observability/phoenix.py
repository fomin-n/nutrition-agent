import logging
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import Any

from app.llm.client import Settings, get_settings

LOGGER = logging.getLogger(__name__)

_CONFIGURED = False
_ENABLED = False


def configure_phoenix_tracing(settings: Settings | None = None) -> bool:
    """Initialize Phoenix/OpenInference tracing when explicitly enabled."""
    global _CONFIGURED, _ENABLED

    settings = settings or get_settings()
    if not settings.enable_phoenix_tracing:
        _ENABLED = False
        return False

    if _CONFIGURED:
        return _ENABLED

    try:
        from phoenix.otel import register

        protocol = (
            "http/protobuf"
            if settings.phoenix_collector_endpoint.endswith("/v1/traces")
            else "grpc"
        )
        register(
            project_name=settings.phoenix_project_name,
            endpoint=settings.phoenix_collector_endpoint,
            protocol=protocol,
            auto_instrument=True,
        )
    except Exception as exc:  # pragma: no cover - optional integration fallback
        LOGGER.warning("Phoenix tracing initialization failed; continuing without traces: %s", exc)
        _ENABLED = False
    else:
        _ENABLED = True
        LOGGER.info(
            "Phoenix tracing enabled for project %s at %s",
            settings.phoenix_project_name,
            settings.phoenix_collector_endpoint,
        )
    finally:
        _CONFIGURED = True

    return _ENABLED


def is_phoenix_tracing_enabled() -> bool:
    return _CONFIGURED and _ENABLED


@contextmanager
def phoenix_trace_context(
    *,
    user_id: str | int | None = None,
    session_id: str | int | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[None]:
    if not is_phoenix_tracing_enabled():
        yield
        return

    try:
        from phoenix.otel import using_metadata, using_session, using_user

        with ExitStack() as stack:
            if user_id is not None:
                stack.enter_context(using_user(str(user_id)))
            if session_id is not None:
                stack.enter_context(using_session(session_id=str(session_id)))
            if metadata:
                stack.enter_context(using_metadata(_safe_metadata(metadata)))
            yield
    except Exception as exc:  # pragma: no cover - optional integration fallback
        LOGGER.warning("Phoenix trace context failed; continuing without trace metadata: %s", exc)
        yield


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool | None]:
    safe: dict[str, str | int | float | bool | None] = {}
    for key, value in metadata.items():
        if value is None or isinstance(value, str | int | float | bool):
            safe[key] = value
        else:
            safe[key] = str(value)
    return safe
