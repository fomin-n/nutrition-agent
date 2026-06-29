import logging

from app.graph.nodes import image_recognizer, packaging_recognizer
from app.llm.client import Settings
from app.schemas.inputs import NormalizedInput
from app.schemas.nutrition import IngredientEstimate, MealUnderstanding


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


def test_dish_photo_escalates_low_confidence_vision(monkeypatch) -> None:
    calls: list[str | None] = []
    monkeypatch.setattr(image_recognizer, "has_openai_key", lambda: True)
    monkeypatch.setattr(
        image_recognizer,
        "get_settings",
        lambda: Settings(
            openai_vision_model="base-vision",
            openai_vision_escalation_model="strong-vision",
        ),
    )

    def fake_recognition(*_args, model_name: str | None = None, **_kwargs):
        calls.append(model_name)
        if model_name == "strong-vision":
            return MealUnderstanding(
                confidence="medium",
                ingredients=[
                    IngredientEstimate(name="apple", grams_min=90, grams_max=120),
                    IngredientEstimate(name="yogurt", grams_min=120, grams_max=160),
                ],
            )
        return MealUnderstanding(
            confidence="low",
            ingredients=[IngredientEstimate(name="apple", grams_min=90, grams_max=120)],
        )

    monkeypatch.setattr(image_recognizer, "recognize_image_with_llm", fake_recognition)

    result = image_recognizer.recognize_dish_photo(
        {
            "normalized_input": NormalizedInput(
                image_path="/tmp/dish.jpg",
                image_mime_type="image/jpeg",
                has_image=True,
                language="en",
            ),
            "request_id": "request-escalate",
            "use_llm": True,
        }
    )

    assert calls == ["base-vision", "strong-vision"]
    assert result["meal"].confidence == "medium"
    assert [item.name for item in result["meal"].ingredients] == ["apple", "yogurt"]
    assert result["vision_escalation"] == {
        "branch": "dish_photo",
        "base_model": "base-vision",
        "base_confidence": "low",
        "escalation_model": "strong-vision",
        "escalated": True,
        "selected_model": "strong-vision",
        "selected_confidence": "medium",
        "failure_type": None,
        "escalated_confidence": "medium",
    }


def test_dish_photo_does_not_escalate_medium_confidence(monkeypatch) -> None:
    calls: list[str | None] = []
    monkeypatch.setattr(image_recognizer, "has_openai_key", lambda: True)
    monkeypatch.setattr(
        image_recognizer,
        "get_settings",
        lambda: Settings(
            openai_vision_model="base-vision",
            openai_vision_escalation_model="strong-vision",
        ),
    )

    def fake_recognition(*_args, model_name: str | None = None, **_kwargs):
        calls.append(model_name)
        return MealUnderstanding(
            confidence="medium",
            ingredients=[IngredientEstimate(name="apple", grams_min=90, grams_max=120)],
        )

    monkeypatch.setattr(image_recognizer, "recognize_image_with_llm", fake_recognition)

    result = image_recognizer.recognize_dish_photo(
        {
            "normalized_input": NormalizedInput(
                image_path="/tmp/dish.jpg",
                image_mime_type="image/jpeg",
                has_image=True,
                language="en",
            ),
            "request_id": "request-no-escalate",
            "use_llm": True,
        }
    )

    assert calls == ["base-vision"]
    assert result["meal"].confidence == "medium"
    assert result["vision_escalation"]["escalated"] is False
    assert result["vision_escalation"]["selected_model"] == "base-vision"


def test_dish_photo_skips_escalation_when_model_matches_base(monkeypatch) -> None:
    calls: list[str | None] = []
    monkeypatch.setattr(image_recognizer, "has_openai_key", lambda: True)
    monkeypatch.setattr(
        image_recognizer,
        "get_settings",
        lambda: Settings(
            openai_vision_model="same-model",
            openai_vision_escalation_model="same-model",
        ),
    )

    def fake_recognition(*_args, model_name: str | None = None, **_kwargs):
        calls.append(model_name)
        return MealUnderstanding(
            confidence="low",
            ingredients=[IngredientEstimate(name="apple", grams_min=90, grams_max=120)],
        )

    monkeypatch.setattr(image_recognizer, "recognize_image_with_llm", fake_recognition)

    result = image_recognizer.recognize_dish_photo(
        {
            "normalized_input": NormalizedInput(
                image_path="/tmp/dish.jpg",
                image_mime_type="image/jpeg",
                has_image=True,
                language="en",
            ),
            "request_id": "request-same-model",
            "use_llm": True,
        }
    )

    assert calls == ["same-model"]
    assert result["vision_escalation"]["escalated"] is False
    assert result["vision_escalation"]["escalation_model"] is None


def test_dish_photo_uses_base_when_escalation_fails(monkeypatch, caplog) -> None:
    monkeypatch.setattr(image_recognizer, "has_openai_key", lambda: True)
    monkeypatch.setattr(
        image_recognizer,
        "get_settings",
        lambda: Settings(
            openai_vision_model="base-vision",
            openai_vision_escalation_model="strong-vision",
        ),
    )

    def fake_recognition(*_args, model_name: str | None = None, **_kwargs):
        if model_name == "strong-vision":
            raise TimeoutError("escalation timeout")
        return MealUnderstanding(
            confidence="low",
            ingredients=[IngredientEstimate(name="apple", grams_min=90, grams_max=120)],
        )

    monkeypatch.setattr(image_recognizer, "recognize_image_with_llm", fake_recognition)

    with caplog.at_level(logging.WARNING):
        result = image_recognizer.recognize_dish_photo(
            {
                "normalized_input": NormalizedInput(
                    image_path="/tmp/private-dish.jpg",
                    image_mime_type="image/jpeg",
                    has_image=True,
                    language="en",
                ),
                "request_id": "request-escalation-fail",
                "use_llm": True,
            }
        )

    assert result["meal"].confidence == "low"
    assert result["vision_escalation"]["failure_type"] == "TimeoutError"
    assert result["vision_escalation"]["selected_model"] == "base-vision"
    assert "request-escalation-fail" in caplog.text
    assert "strong-vision" in caplog.text
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

    monkeypatch.setattr(
        packaging_recognizer,
        "recognize_image_with_optional_escalation",
        fail_recognition,
    )

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


def test_packaging_uses_vision_escalation_path(monkeypatch) -> None:
    monkeypatch.setattr(packaging_recognizer, "has_openai_key", lambda: True)

    def fake_escalation(*_args, **kwargs):
        return (
            MealUnderstanding(
                confidence="medium",
                ingredients=[IngredientEstimate(name="yogurt", grams_min=180, grams_max=180)],
            ),
            {
                "branch": kwargs["branch"],
                "base_model": "base-vision",
                "base_confidence": "low",
                "escalation_model": "strong-vision",
                "escalated": True,
                "selected_model": "strong-vision",
                "selected_confidence": "medium",
                "failure_type": None,
            },
        )

    monkeypatch.setattr(
        packaging_recognizer,
        "recognize_image_with_optional_escalation",
        fake_escalation,
    )

    result = packaging_recognizer.recognize_packaging(
        {
            "normalized_input": NormalizedInput(
                text="yogurt label 180g",
                image_path="/tmp/package.jpg",
                image_mime_type="image/jpeg",
                has_text=True,
                has_image=True,
                language="en",
            ),
            "request_id": "request-package",
            "use_llm": True,
        }
    )

    assert result["meal"].ingredients[0].name == "yogurt"
    assert result["vision_escalation"]["branch"] == "packaged_food"
    assert result["vision_escalation"]["escalated"] is True
