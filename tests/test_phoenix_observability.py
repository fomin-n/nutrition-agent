from app.graph.graph import _trace_metadata
from app.llm.client import Settings
from app.observability import phoenix


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
        extra={"telegram_message_id": 123},
    )

    assert metadata["request_type"] == "text"
    assert metadata["request_language"] == "en"
    assert metadata["openai_text_model"] == settings.openai_text_model
    assert metadata["telegram_message_id"] == 123
    assert "text" not in metadata
    assert "openai_api_key" not in metadata
