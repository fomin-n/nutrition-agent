"""Last-mile privacy boundary, including instrumentation-generated exception events."""

import json
from collections.abc import Sequence

from openinference.instrumentation import TraceConfig
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import Status

from app.observability.phoenix import _ALLOWED_METADATA_KEYS, _safe_metadata


def private_trace_config() -> TraceConfig:
    return TraceConfig(
        hide_inputs=True,
        hide_outputs=True,
        hide_input_messages=True,
        hide_output_messages=True,
        hide_input_images=True,
        hide_input_text=True,
        hide_output_text=True,
        hide_llm_invocation_parameters=True,
        hide_llm_tools=True,
        hide_prompts=True,
        hide_choices=True,
    )


class RedactingExporter(SpanExporter):
    def __init__(self, exporter: SpanExporter) -> None:
        self.exporter = exporter

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        safe_spans = []
        for span in spans:
            attrs = {
                key: value
                for key, value in (span.attributes or {}).items()
                if key
                in {
                    "openinference.span.kind",
                    "llm.model_name",
                    "llm.provider",
                    "llm.system",
                    "user.id",
                    "session.id",
                    "metadata",
                    "request_id",
                    "source",
                    "request_type",
                    "request_language",
                    "nutrition.provider",
                    "nutrition.operation",
                }
                or key in _ALLOWED_METADATA_KEYS
                or key.startswith(("llm.token_count.", "nutrition_agent.vision."))
            }
            # Metadata is explicitly allowlisted by the application, but auto-instrumentors
            # may add arbitrary nested metadata. Keep only the request root's sanitized data.
            if span.name != "nutrition_agent.request":
                attrs.pop("metadata", None)
            elif "metadata" in attrs:
                try:
                    metadata = json.loads(str(attrs["metadata"]))
                    attrs["metadata"] = (
                        json.dumps(_safe_metadata(metadata)) if isinstance(metadata, dict) else "{}"
                    )
                except (ValueError, TypeError):
                    attrs.pop("metadata", None)
            safe_spans.append(
                ReadableSpan(
                    name=span.name,
                    context=span.context,
                    parent=span.parent,
                    resource=span.resource,
                    attributes=attrs,
                    events=(),
                    links=(),
                    kind=span.kind,
                    status=Status(span.status.status_code),
                    start_time=span.start_time,
                    end_time=span.end_time,
                    instrumentation_scope=span.instrumentation_scope,
                )
            )
        return self.exporter.export(safe_spans)

    def shutdown(self) -> None:
        self.exporter.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.exporter.force_flush(timeout_millis)
