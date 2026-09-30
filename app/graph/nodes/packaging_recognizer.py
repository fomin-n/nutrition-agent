import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.graph.state import NutritionGraphState
from app.i18n import LanguageCode, response_language
from app.llm.client import build_chat_model, get_settings, has_openai_key
from app.llm.structured import read_prompt
from app.schemas.nutrition import IngredientEstimate, MealUnderstanding
from app.schemas.packaging import PackagingObservation
from app.tools.fallback_nutrition import normalize_food_query
from app.tools.food_normalization import UNIT_GRAMS, extract_quantity_mentions, is_mass_quantity
from app.tools.image_utils import encode_image_data_url
from app.tools.meal_validation import clarification_meal

LOGGER = logging.getLogger(__name__)


def recognize_packaging(state: NutritionGraphState) -> NutritionGraphState:
    normalized = state["normalized_input"]
    if state.get("use_llm", True) and has_openai_key() and normalized.image_path:
        try:
            observation = read_packaging_observation(
                image_path=normalized.image_path, mime_type=normalized.image_mime_type,
                caption=normalized.text or "",
            )
            return {"meal": meal_from_label(
                observation, caption=normalized.text or "", language=normalized.language,
            )}
        except Exception as exc:
            LOGGER.warning(
                (
                    "Packaging recognizer LLM fallback request_id=%s branch=packaged_food "
                    "error_type=%s error=%s; using local fallback"
                ),
                state.get("request_id"),
                type(exc).__name__,
                "redacted",
            )
    return {"meal": recognize_packaging_locally(normalized.text or "", language=normalized.language)}


def read_packaging_observation(*, image_path: str, mime_type: str | None, caption: str) -> PackagingObservation:
    settings = get_settings()
    content = [
        SystemMessage(content=read_prompt("packaging_recognizer.md")),
        HumanMessage(content=[
            {"type": "text", "text": f"Untrusted caption: {caption}"},
            {"type": "image_url", "image_url": {"url": encode_image_data_url(image_path, mime_type)}},
        ]),
    ]

    def read(model_name: str) -> PackagingObservation:
        model = build_chat_model(model_name, task="vision").with_structured_output(PackagingObservation)
        result = model.invoke(content)
        return result if isinstance(result, PackagingObservation) else PackagingObservation.model_validate(result)

    base = read(settings.openai_vision_model)
    escalation = settings.openai_vision_escalation_model
    confidence_level = {"low": 0, "medium": 1, "high": 2}
    below_threshold = confidence_level[base.confidence] <= confidence_level[settings.openai_vision_escalation_confidence]
    if base.is_food and (base.label is None or below_threshold) and escalation and escalation != settings.openai_vision_model:
        try:
            retry = read(escalation)
            if retry.is_food and retry.label is not None:
                return retry
        except Exception as exc:
            LOGGER.warning("Packaging escalation failed error_type=%s", type(exc).__name__)
    return base


def meal_from_label(observation: PackagingObservation, *, caption: str, language: LanguageCode) -> MealUnderstanding:
    quantities = [q for q in extract_quantity_mentions(caption) if is_mass_quantity(q)]
    if not observation.is_food or not observation.label or not observation.product_name or len(quantities) != 1:
        return clarification_meal(language)
    quantity = quantities[0]
    grams = quantity.amount * UNIT_GRAMS[quantity.unit]
    return MealUnderstanding(
        ingredients=[IngredientEstimate(
            name=observation.product_name, grams_min=grams, grams_max=grams,
            observed_label=observation.label, origin="observed_label", confidence=observation.confidence,
        )],
        assumptions=[
            "Значения прочитаны с этикетки; использован указанный вес порции."
            if response_language(language) == "ru" else
            "Values were transcribed from the label; the stated consumed portion was used."
        ], confidence=observation.confidence,
    )


def recognize_packaging_locally(text: str, *, language: LanguageCode = "unknown") -> MealUnderstanding:
    normalized = normalize_food_query(text)
    grams = _extract_grams(normalized) or 100.0
    product_name = _clean_product_name(text)
    if response_language(language) == "ru":
        assumption = f"{product_name}: {round(grams * 0.9)}-{round(grams * 1.1)} g порция упакованного продукта."
        notes = "упакованный продукт определен по подписи или OCR"
    else:
        assumption = f"{product_name}: {round(grams * 0.9)}-{round(grams * 1.1)} g packaged-food serving."
        notes = "packaged product inferred from caption/OCR"
    return MealUnderstanding(
        dish_name=product_name,
        ingredients=[
            IngredientEstimate(
                name=product_name,
                grams_min=grams * 0.9,
                grams_max=grams * 1.1,
                notes=notes,
                confidence="low" if product_name == "packaged food" else "medium",
            )
        ],
        assumptions=[assumption],
        confidence="low" if product_name == "packaged food" else "medium",
    )


def _extract_grams(normalized: str) -> float | None:
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*(g|gram|grams)\b", normalized)
    if not match:
        return None
    return float(match.group(1))


def _clean_product_name(text: str) -> str:
    cleaned = re.sub(r"(?i)\b(barcode|nutrition facts|label|packaged|package|wrapper|product)\b", " ", text)
    cleaned = " ".join(cleaned.split())
    return cleaned[:80] if cleaned else "packaged food"
