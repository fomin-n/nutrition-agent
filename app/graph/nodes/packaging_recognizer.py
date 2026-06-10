import re

from app.graph.nodes.image_recognizer import recognize_image_with_llm
from app.graph.state import NutritionGraphState
from app.llm.client import has_openai_key
from app.schemas.nutrition import IngredientEstimate, MealUnderstanding
from app.tools.fallback_nutrition import normalize_food_query


def recognize_packaging(state: NutritionGraphState) -> NutritionGraphState:
    normalized = state["normalized_input"]
    if state.get("use_llm", True) and has_openai_key() and normalized.image_path:
        try:
            return {
                "meal": recognize_image_with_llm(
                    normalized.image_path,
                    normalized.image_mime_type,
                    caption=normalized.text,
                )
            }
        except Exception:
            pass
    return {"meal": recognize_packaging_locally(normalized.text or "")}


def recognize_packaging_locally(text: str) -> MealUnderstanding:
    normalized = normalize_food_query(text)
    grams = _extract_grams(normalized) or 100.0
    product_name = _clean_product_name(text)
    assumption = f"{product_name}: {round(grams * 0.9)}-{round(grams * 1.1)} g packaged-food serving."
    return MealUnderstanding(
        dish_name=product_name,
        ingredients=[
            IngredientEstimate(
                name=product_name,
                grams_min=grams * 0.9,
                grams_max=grams * 1.1,
                notes="packaged product inferred from caption/OCR",
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

