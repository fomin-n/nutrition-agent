import json
import logging
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import Any

from app.llm.client import Settings, get_settings

LOGGER = logging.getLogger(__name__)

_CONFIGURED = False
_ENABLED = False
_MAX_METADATA_VALUE_CHARS = 512
_ROOT_METADATA_KEYS = {
    "request_id",
    "source",
    "request_type",
    "request_language",
}
_ALLOWED_METADATA_KEYS = _ROOT_METADATA_KEYS | {
    "app_version", "graph_version", "use_llm", "openai_text_model", "openai_vision_model",
    "openai_vision_escalation_model", "openai_vision_escalation_confidence",
    "openai_critic_model", "critic_max_iterations",
    "telegram.update.id", "telegram.user.id", "telegram.user.username",
    "telegram.user.first_name", "telegram.user.last_name", "telegram.user.display_name",
    "telegram.user.language_code", "telegram.user.is_bot", "telegram.chat.id",
    "telegram.chat.type", "telegram.chat.title", "telegram.chat.username",
    "telegram.chat.is_forum", "telegram.conversation.id", "telegram.message.id",
    "telegram.message.thread_id", "telegram.message.date", "telegram.message.media_group_id",
    "telegram.message.is_topic_message",
}
_SENSITIVE_METADATA_KEY_PARTS = (
    "access_key",
    "access_token",
    "api_key",
    "authorization",
    "bot_token",
    "caption",
    "client_secret",
    "credential",
    "message_text",
    "password",
    "prompt",
    "raw_input",
    "raw_update",
    "refresh_token",
    "secret",
    "telegram_token",
    "update_payload",
    "user_input",
)


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
        from openinference.instrumentation.langchain import LangChainInstrumentor
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from phoenix.otel import GRPCSpanExporter, HTTPSpanExporter

        from app.observability.redaction import RedactingExporter, private_trace_config

        exporter_class = (
            HTTPSpanExporter if settings.phoenix_collector_endpoint.endswith("/v1/traces")
            else GRPCSpanExporter
        )
        provider = TracerProvider(resource=Resource.create({"openinference.project.name": settings.phoenix_project_name}))
        provider.add_span_processor(BatchSpanProcessor(RedactingExporter(
            exporter_class(endpoint=settings.phoenix_collector_endpoint)
        )))
        trace.set_tracer_provider(provider)
        LangChainInstrumentor().instrument(tracer_provider=provider, config=private_trace_config())
    except Exception as exc:  # pragma: no cover - optional integration fallback
        LOGGER.warning("Phoenix tracing initialization failed; error_type=%s", type(exc).__name__)
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

    stack = ExitStack()
    try:
        from openinference.semconv.trace import (
            OpenInferenceSpanKindValues,
            SpanAttributes,
        )
        from opentelemetry import trace
        from phoenix.otel import using_metadata, using_session, using_user

        safe_metadata = _safe_metadata(metadata or {})
        if user_id is not None:
            stack.enter_context(using_user(str(user_id)))
        if session_id is not None:
            stack.enter_context(using_session(session_id=str(session_id)))
        if safe_metadata:
            stack.enter_context(using_metadata(safe_metadata))
        span = stack.enter_context(
            trace.get_tracer("nutrition-agent.request").start_as_current_span(
                "nutrition_agent.request"
            )
        )
        span.set_attribute(
            SpanAttributes.OPENINFERENCE_SPAN_KIND,
            OpenInferenceSpanKindValues.CHAIN.value,
        )
        if user_id is not None:
            span.set_attribute(SpanAttributes.USER_ID, str(user_id))
        if session_id is not None:
            span.set_attribute(SpanAttributes.SESSION_ID, str(session_id))
        if safe_metadata:
            span.set_attribute(
                SpanAttributes.METADATA,
                json.dumps(safe_metadata, ensure_ascii=False, sort_keys=True),
            )
            for key, value in safe_metadata.items():
                if key.startswith("telegram.") or key in _ROOT_METADATA_KEYS:
                    span.set_attribute(key, value)
    except Exception as exc:  # pragma: no cover - optional integration fallback
        stack.close()
        LOGGER.warning("Phoenix trace context failed; error_type=%s", type(exc).__name__)
        yield
        return

    with stack:
        yield


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool]:
    safe: dict[str, str | int | float | bool] = {}
    for key, value in metadata.items():
        normalized_key = str(key).strip()
        if normalized_key not in _ALLOWED_METADATA_KEYS or _is_sensitive_metadata_key(normalized_key) or value is None:
            continue
        if isinstance(value, bool | int | float):
            safe[normalized_key] = value
        else:
            safe[normalized_key] = str(value)[:_MAX_METADATA_VALUE_CHARS]
    return safe


def _is_sensitive_metadata_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_").replace(".", "_")
    if normalized in {"caption", "text", "user_input"}:
        return True
    return any(part in normalized for part in _SENSITIVE_METADATA_KEY_PARTS)
