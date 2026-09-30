import logging


class TraceContextFilter(logging.Filter):
    """Attach active OpenTelemetry identifiers to every application log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Validation/API exception strings can embed complete inputs or credentials.
        if record.exc_info:
            error_type = record.exc_info[0]
            record.msg = f"{record.msg} error_type={error_type.__name__ if error_type else 'unknown'}"
            record.exc_info = None
            record.exc_text = None
        record.stack_info = None
        if isinstance(record.args, tuple):
            record.args = tuple(type(arg).__name__ if isinstance(arg, BaseException) else arg for arg in record.args)
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
