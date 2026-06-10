import re

from app.graph.state import NutritionGraphState
from app.llm.client import get_settings, has_openai_key, local_moderate_text
from app.llm.structured import invoke_structured_text, read_prompt
from app.schemas.safety import ModerationDecision, RouteName, ScopeDecision
from app.tools.fallback_nutrition import fallback_names, normalize_food_query

FOOD_WORDS = fallback_names() | {
    "ate",
    "eaten",
    "meal",
    "breakfast",
    "lunch",
    "dinner",
    "snack",
    "plate",
    "bowl",
    "portion",
    "serving",
    "calorie",
    "calories",
    "kcal",
    "protein",
    "carbs",
    "fat",
    "macros",
    "sandwich",
    "wrap",
    "taco",
    "sushi",
    "fish",
    "meat",
    "vegetables",
    "fruit",
}

PACKAGED_WORDS = {
    "barcode",
    "packaged",
    "package",
    "wrapper",
    "label",
    "nutrition facts",
    "brand",
    "product",
}


def scope_classifier(state: NutritionGraphState) -> NutritionGraphState:
    moderation = state.get("input_moderation", ModerationDecision())
    normalized = state["normalized_input"]

    if not moderation.allowed:
        return {
            "scope_decision": ScopeDecision(
                route="unsafe" if moderation.category != "off_topic" else "off_topic",
                is_food_related=False,
                is_unsafe=moderation.category != "off_topic",
                needs_clarification=False,
                reason=moderation.reason,
                confidence="high",
            )
        }

    local_decision = classify_scope_locally(
        text=normalized.text,
        has_image=normalized.has_image,
        has_text=normalized.has_text,
    )

    use_llm = state.get("use_llm", True)
    if use_llm and has_openai_key() and local_decision.confidence != "high":
        try:
            prompt = read_prompt("scope_classifier.md")
            user_prompt = (
                f"Text: {normalized.text or ''}\n"
                f"Has image: {normalized.has_image}\n"
                "Return a conservative route for the controlled nutrition graph."
            )
            llm_decision = invoke_structured_text(
                model_name=get_settings().openai_text_model,
                schema=ScopeDecision,
                system_prompt=prompt,
                user_prompt=user_prompt,
            )
            return {"scope_decision": llm_decision}
        except Exception:
            return {"scope_decision": local_decision}

    return {"scope_decision": local_decision}


def classify_scope_locally(text: str | None, *, has_image: bool, has_text: bool) -> ScopeDecision:
    moderation = local_moderate_text(text)
    if not moderation.allowed:
        return ScopeDecision(
            route="unsafe",
            is_food_related=False,
            is_unsafe=True,
            reason=moderation.reason,
            confidence="high",
        )

    if not has_text and not has_image:
        return ScopeDecision(
            route="needs_clarification",
            is_food_related=True,
            needs_clarification=True,
            clarification_question="Please send a meal description or one food photo.",
            reason="No text or image was provided.",
            confidence="high",
        )

    normalized_text = normalize_food_query(text or "")
    if has_image and not has_text:
        return ScopeDecision(
            route="dish_photo",
            is_food_related=True,
            reason="Food photo without caption.",
            confidence="medium",
        )

    if any(word in normalized_text for word in PACKAGED_WORDS):
        return ScopeDecision(
            route="packaged_food",
            is_food_related=True,
            reason="Packaging or nutrition-label request.",
            confidence="medium",
        )

    if has_image and has_text:
        if _contains_food_signal(normalized_text):
            return ScopeDecision(
                route="image_with_text",
                is_food_related=True,
                reason="Food photo with caption.",
                confidence="medium",
            )
        return ScopeDecision(
            route="image_with_text",
            is_food_related=True,
            reason="Image request with text; treat as candidate meal photo.",
            confidence="low",
        )

    if _contains_food_signal(normalized_text) and _contains_meal_detail(normalized_text):
        return ScopeDecision(
            route="text_meal",
            is_food_related=True,
            reason="Meal description with food signals.",
            confidence="medium",
        )

    if _contains_food_signal(normalized_text):
        return ScopeDecision(
            route="needs_clarification",
            is_food_related=True,
            needs_clarification=True,
            clarification_question="What food did you eat and roughly how much?",
            reason="Nutrition intent without enough meal detail.",
            confidence="medium",
        )

    return ScopeDecision(
        route="off_topic",
        is_food_related=False,
        reason="No food or nutrition-estimation intent detected.",
        confidence="high",
    )


def route_from_scope(state: NutritionGraphState) -> RouteName:
    return state["scope_decision"].route


def route(state: NutritionGraphState) -> NutritionGraphState:
    return {}


def _contains_food_signal(normalized_text: str) -> bool:
    if any(re.search(rf"\b{re.escape(word)}\b", normalized_text) for word in FOOD_WORDS):
        return True
    return bool(re.search(r"\b\d+\s*(g|gram|grams|kg|oz|cup|cups|tbsp|tablespoon|slice|slices)\b", normalized_text))


def _contains_meal_detail(normalized_text: str) -> bool:
    generic_intent_words = {
        "ate",
        "eaten",
        "meal",
        "breakfast",
        "lunch",
        "dinner",
        "snack",
        "plate",
        "bowl",
        "portion",
        "serving",
        "calorie",
        "calories",
        "kcal",
        "protein",
        "carbs",
        "fat",
        "macros",
    }
    return any(
        re.search(rf"\b{re.escape(word)}\b", normalized_text)
        for word in FOOD_WORDS
        if word not in generic_intent_words
    )
