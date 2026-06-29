import logging
import re

from app.graph.nodes.image_recognizer import recognize_image_with_optional_escalation
from app.graph.state import NutritionGraphState
from app.i18n import LanguageCode, response_language
from app.llm.client import has_openai_key
from app.schemas.nutrition import IngredientEstimate, MealUnderstanding
from app.tools.fallback_nutrition import normalize_food_query

LOGGER = logging.getLogger(__name__)


def recognize_packaging(state: NutritionGraphState) -> NutritionGraphState:
    normalized = state["normalized_input"]
    if state.get("use_llm", True) and has_openai_key() and normalized.image_path:
        try:
            meal, diagnostic = recognize_image_with_optional_escalation(
                normalized.image_path,
                normalized.image_mime_type,
                caption=normalized.text,
                language=normalized.language,
                request_id=state.get("request_id"),
                branch="packaged_food",
            )
            return {
                "meal": meal,
                "vision_escalation": diagnostic,
            }
        except Exception as exc:
            LOGGER.warning(
                (
                    "Packaging recognizer LLM fallback request_id=%s branch=packaged_food "
                    "error_type=%s error=%s; using local fallback"
                ),
                state.get("request_id"),
                type(exc).__name__,
                exc,
            )
    return {"meal": recognize_packaging_locally(normalized.text or "", language=normalized.language)}


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
