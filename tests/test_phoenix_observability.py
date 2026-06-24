import json
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier

from openinference.instrumentation import get_attributes_from_context
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, use_span

from app.graph.graph import _trace_metadata
from app.llm.client import Settings
from app.observability import phoenix
from app.observability.request_context import TelegramRequestContext
from app.observability.trace_logging import TraceContextFilter


def test_phoenix_tracing_disabled() -> None:
    settings = Settings(enable_phoenix_tracing=False)

    assert phoenix.configure_phoenix_tracing(settings) is False


def test_trace_metadata_excludes_raw_input() -> None:
    settings = Settings()

    metadata = _trace_metadata(
        text="200g rice and chicken",
        image_path=None,
        source="test",
        use_llm=False,
        settings=settings,
        extra={"telegram.message.id": 123},
    )

    assert metadata["request_type"] == "text"
    assert metadata["request_language"] == "en"
    assert metadata["openai_text_model"] == settings.openai_text_model
    assert metadata["openai_critic_model"] == settings.openai_critic_model
    assert metadata["critic_max_iterations"] == settings.critic_max_iterations
    assert metadata["telegram.message.id"] == 123
    assert "text" not in metadata
    assert "openai_api_key" not in metadata


def test_telegram_context_omits_missing_optional_fields() -> None:
    update = type(
        "Update",
        (),
        {
            "effective_user": type(
                "User",
                (),
                {
                    "id": 1001,
                    "first_name": "Demo",
                    "full_name": "Demo",
                    "is_bot": False,
                },
            )(),
            "effective_chat": type("Chat", (), {"id": 2001, "type": "private"})(),
            "effective_message": type("Message", (), {"message_id": 3001})(),
        },
    )()

    context = TelegramRequestContext.from_update(update)

    assert context.user_id == 1001
    assert context.session_id == 2001
    assert context.username is None
    assert context.to_trace_metadata() == {
        "telegram.user.id": 1001,
        "telegram.user.first_name": "Demo",
        "telegram.user.display_name": "Demo",
        "telegram.user.is_bot": False,
        "telegram.chat.id": 2001,
        "telegram.chat.type": "private",
        "telegram.conversation.id": 2001,
        "telegram.message.id": 3001,
    }


class _CapturingSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value


class _CapturingTracer:
    def __init__(self) -> None:
        self.spans: list[_CapturingSpan] = []

    @contextmanager
    def start_as_current_span(self, name: str):
        assert name == "nutrition_agent.request"
        span = _CapturingSpan()
        self.spans.append(span)
        yield span


def test_request_root_span_contains_identity_metadata(monkeypatch) -> None:
    tracer = _CapturingTracer()
    monkeypatch.setattr(phoenix, "is_phoenix_tracing_enabled", lambda: True)
    monkeypatch.setattr(trace, "get_tracer", lambda name: tracer)

    with phoenix.phoenix_trace_context(
        user_id=1001,
        session_id=2001,
        metadata={
            "request_id": "request-1",
            "source": "telegram",
            "telegram.user.id": 1001,
            "telegram.user.username": "demo_user",
            "telegram.chat.id": 2001,
            "telegram.message.id": 3001,
            "message_text": "must not be traced",
            "telegram.message.caption": "must not be traced",
            "bot_token": "must not be traced",
            "bot_auth_secret": "must not be traced",
            "raw_prompt": "must not be traced",
        },
    ):
        child_context = dict(get_attributes_from_context())

    assert len(tracer.spans) == 1
    attributes = tracer.spans[0].attributes
    assert attributes["user.id"] == "1001"
    assert attributes["session.id"] == "2001"
    assert attributes["telegram.user.username"] == "demo_user"
    assert attributes["telegram.message.id"] == 3001
    root_metadata = json.loads(str(attributes["metadata"]))
    assert root_metadata["request_id"] == "request-1"
    assert "message_text" not in root_metadata
    assert "telegram.message.caption" not in root_metadata
    assert "bot_token" not in root_metadata
    assert "bot_auth_secret" not in root_metadata
    assert "raw_prompt" not in root_metadata

    assert child_context["user.id"] == "1001"
    assert child_context["session.id"] == "2001"
    child_metadata = json.loads(str(child_context["metadata"]))
    assert child_metadata["telegram.user.username"] == "demo_user"
    assert "message_text" not in child_metadata


def test_concurrent_request_contexts_do_not_mix(monkeypatch) -> None:
    tracer = _CapturingTracer()
    barrier = Barrier(2)
    monkeypatch.setattr(phoenix, "is_phoenix_tracing_enabled", lambda: True)
    monkeypatch.setattr(trace, "get_tracer", lambda name: tracer)

    def capture(user_id: int) -> tuple[str, str, dict[str, object]]:
        with phoenix.phoenix_trace_context(
            user_id=user_id,
            session_id=user_id + 1000,
            metadata={
                "request_id": f"request-{user_id}",
                "telegram.user.id": user_id,
                "telegram.user.username": f"user_{user_id}",
            },
        ):
            barrier.wait()
            attributes = dict(get_attributes_from_context())
            return (
                str(attributes["user.id"]),
                str(attributes["session.id"]),
                json.loads(str(attributes["metadata"])),
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = sorted(executor.map(capture, (1, 2)))

    assert results == [
        (
            "1",
            "1001",
            {
                "request_id": "request-1",
                "telegram.user.id": 1,
                "telegram.user.username": "user_1",
            },
        ),
        (
            "2",
            "1002",
            {
                "request_id": "request-2",
                "telegram.user.id": 2,
                "telegram.user.username": "user_2",
            },
        ),
    ]


def test_request_span_is_parent_of_instrumented_work(monkeypatch) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(phoenix, "is_phoenix_tracing_enabled", lambda: True)
    monkeypatch.setattr(trace, "get_tracer", lambda name: provider.get_tracer(name))

    with phoenix.phoenix_trace_context(
        user_id=1001,
        session_id=2001,
        metadata={"request_id": "request-parent", "telegram.message.id": 3001},
    ), provider.get_tracer("test-child").start_as_current_span("langgraph.child"):
        pass

    spans = {span.name: span for span in exporter.get_finished_spans()}
    root = spans["nutrition_agent.request"]
    child = spans["langgraph.child"]
    assert child.parent is not None
    assert child.parent.span_id == root.context.span_id
    assert root.attributes["user.id"] == "1001"
    assert root.attributes["telegram.message.id"] == 3001


def test_trace_log_filter_adds_current_trace_and_span_ids() -> None:
    span_context = SpanContext(
        trace_id=0x123,
        span_id=0x456,
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "message", (), None)

    with use_span(NonRecordingSpan(span_context)):
        assert TraceContextFilter().filter(record) is True

    assert record.trace_id == "00000000000000000000000000000123"
    assert record.span_id == "0000000000000456"
