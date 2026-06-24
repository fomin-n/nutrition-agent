import logging


class TraceContextFilter(logging.Filter):
    """Attach active OpenTelemetry identifiers to every application log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        trace_id = "-"
        span_id = "-"
        try:
            from opentelemetry import trace

            context = trace.get_current_span().get_span_context()
            if context.is_valid:
                trace_id = f"{context.trace_id:032x}"
                span_id = f"{context.span_id:016x}"
        except Exception:
            pass
        record.trace_id = trace_id
        record.span_id = span_id
        return True


def configure_trace_log_correlation() -> None:
    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(item, TraceContextFilter) for item in handler.filters):
            handler.addFilter(TraceContextFilter())
