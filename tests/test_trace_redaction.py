import json

from langchain_core.runnables import RunnableLambda
from openinference.instrumentation.langchain import LangChainInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.observability.redaction import RedactingExporter, private_trace_config


def test_unrecognized_metadata_is_not_exportable():
    from app.observability.phoenix import _safe_metadata

    assert _safe_metadata(
        {"arbitrary": "PRIVATE", "telegram.unknown": "PRIVATE", "request_id": "test-id"}
    ) == {"request_id": "test-id"}


def test_exported_instrumented_content_and_errors_are_redacted():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(RedactingExporter(exporter)))
    instrumentor = LangChainInstrumentor()
    instrumentor.instrument(tracer_provider=provider, config=private_trace_config())
    try:
        RunnableLambda(lambda value: value).invoke({"private": "SYNTHETIC_PRIVATE_INPUT"})
        with provider.get_tracer("test").start_as_current_span("failure") as span:
            span.record_exception(ValueError("SYNTHETIC_PRIVATE_ERROR"))
            span.set_attribute("llm.token_count.total", 42)
        spans = exporter.get_finished_spans()
        assert spans
        serialized = json.dumps([json.loads(span.to_json()) for span in spans])
        assert "SYNTHETIC_PRIVATE" not in serialized
        assert "llm.token_count.total" in serialized
    finally:
        instrumentor.uninstrument()
        provider.shutdown()
