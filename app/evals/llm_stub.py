from collections.abc import Callable, Sequence

from app.evals.golden import GoldenExample
from app.graph.nodes.text_parser import parse_text_locally
from app.i18n import LanguageCode, default_clarification_question
from app.schemas.nutrition import IngredientEstimate, MealUnderstanding
from app.tools.fallback_nutrition import lookup_fallback_profile, normalize_food_query

STUB_VERSION = "golden-reference-calorie-scaled-v1"


def build_golden_llm_stub(
    examples: Sequence[GoldenExample],
) -> Callable[..., MealUnderstanding]:
    """Build a deterministic parser stub for the eval production-path lane.

    The stub is deliberately explicit: it is not a model-quality estimate. It lets the
    eval runner exercise the same `use_llm=True` parser branch without requiring a paid
    API call in CI. Estimate fixtures use the golden reference calories to choose a
    gram amount for one locally known canonical food, so downstream retrieval and
    calculation remain production code.
    """

    fixtures = _build_fixtures(examples)

    def parse_text_with_stub(
        text: str,
        *,
        language: LanguageCode = "unknown",
        memory_note: str = "",
        force_decompose: bool = False,
        validation_feedback: Sequence[str] = (),
    ) -> MealUnderstanding:
        del memory_note, force_decompose, validation_feedback
        key = normalize_food_query(text)
        if key in fixtures:
            return fixtures[key]
        return parse_text_locally(text, language=language)

    return parse_text_with_stub


def _build_fixtures(examples: Sequence[GoldenExample]) -> dict[str, MealUnderstanding]:
    fixtures: dict[str, MealUnderstanding] = {}
    for example in examples:
        if example.input.kind != "single_turn" or example.input.user_input is None:
            continue
        text = example.input.user_input.text
        if not text:
            continue
        meal = _meal_from_example(example)
        if meal is not None:
            fixtures[normalize_food_query(text)] = meal
    return fixtures


def _meal_from_example(example: GoldenExample) -> MealUnderstanding | None:
    behavior = example.output.expected_behavior
    language = example.input.language
    if behavior == "clarify":
        return MealUnderstanding(
            ingredients=[],
            assumptions=[],
            confidence="low",
            needs_clarification=True,
            clarification_question=default_clarification_question(language),
        )
    if behavior == "refuse":
        return None
    nutrition = example.output.nutrition or {}
    item = str(nutrition.get("item") or "")
    calories = nutrition.get("calories_kcal")
    if not item or not isinstance(calories, (int, float)):
        return None
    text = example.input.user_input.text if example.input.user_input else ""
    profile = lookup_fallback_profile(item) or lookup_fallback_profile(text or "")
    if profile is None:
        return None
    if profile.calories_kcal <= 0:
        grams = 250.0 if calories <= 0 else 100.0
    else:
        grams = max(1.0, float(calories) / profile.calories_kcal * 100.0)
    return MealUnderstanding(
        dish_name=item,
        ingredients=[
            IngredientEstimate(
                name=profile.name,
                grams_min=round(grams, 1),
                grams_max=round(grams, 1),
                notes=f"golden LLM stub fixture for {item}",
                confidence="medium",
            )
        ],
        assumptions=[
            f"Golden LLM stub fixture: {item} scaled to reference calories."
        ],
        confidence="medium",
        needs_clarification=False,
    )
