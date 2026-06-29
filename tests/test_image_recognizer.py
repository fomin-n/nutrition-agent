import logging

from app.graph.nodes import image_recognizer, packaging_recognizer
from app.schemas.inputs import NormalizedInput


def test_dish_photo_logs_llm_fallback_without_raw_image_path(monkeypatch, caplog) -> None:
    monkeypatch.setattr(image_recognizer, "has_openai_key", lambda: True)

    def fail_recognition(*_args, **_kwargs):
        raise TimeoutError("vision timeout")

    monkeypatch.setattr(image_recognizer, "recognize_image_with_llm", fail_recognition)

    with caplog.at_level(logging.WARNING):
        result = image_recognizer.recognize_dish_photo(
            {
                "normalized_input": NormalizedInput(
                    image_path="/tmp/private-dish.jpg",
                    image_mime_type="image/jpeg",
                    has_image=True,
                    language="en",
                ),
                "request_id": "request-image",
                "use_llm": True,
            }
        )

    assert result["meal"].needs_clarification
    assert "request-image" in caplog.text
    assert "dish_photo" in caplog.text
    assert "TimeoutError" in caplog.text
    assert "private-dish" not in caplog.text


def test_text_and_image_logs_llm_fallback_without_raw_caption(monkeypatch, caplog) -> None:
    monkeypatch.setattr(image_recognizer, "has_openai_key", lambda: True)

    def fail_recognition(*_args, **_kwargs):
        raise TimeoutError("vision timeout")

    monkeypatch.setattr(image_recognizer, "recognize_image_with_llm", fail_recognition)

    with caplog.at_level(logging.WARNING):
        result = image_recognizer.combine_text_and_image(
            {
                "normalized_input": NormalizedInput(
                    text="secret caption apple 100g",
                    image_path="/tmp/private-caption.jpg",
                    image_mime_type="image/jpeg",
                    has_text=True,
                    has_image=True,
                    language="en",
                ),
                "request_id": "request-image-caption",
                "use_llm": True,
            }
        )

    assert result["meal"].ingredients
    assert "request-image-caption" in caplog.text
    assert "image_with_text" in caplog.text
    assert "TimeoutError" in caplog.text
    assert "secret caption" not in caplog.text
    assert "private-caption" not in caplog.text


def test_packaging_logs_llm_fallback_without_raw_caption(monkeypatch, caplog) -> None:
    monkeypatch.setattr(packaging_recognizer, "has_openai_key", lambda: True)

    def fail_recognition(*_args, **_kwargs):
        raise TimeoutError("vision timeout")

    monkeypatch.setattr(packaging_recognizer, "recognize_image_with_llm", fail_recognition)

    with caplog.at_level(logging.WARNING):
        result = packaging_recognizer.recognize_packaging(
            {
                "normalized_input": NormalizedInput(
                    text="secret wrapper 50g",
                    image_path="/tmp/private-wrapper.jpg",
                    image_mime_type="image/jpeg",
                    has_text=True,
                    has_image=True,
                    language="en",
                ),
                "request_id": "request-packaging",
                "use_llm": True,
            }
        )

    assert result["meal"].ingredients
    assert "request-packaging" in caplog.text
    assert "packaged_food" in caplog.text
    assert "TimeoutError" in caplog.text
    assert "secret wrapper" not in caplog.text
    assert "private-wrapper" not in caplog.text
