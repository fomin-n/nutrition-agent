from app.graph.nodes.synthesizer import synthesize_answer
from app.schemas.inputs import NormalizedInput
from app.schemas.nutrition import (
    IngredientEstimate,
    IngredientNutrition,
    MacroRange,
    MealUnderstanding,
    NutritionPer100g,
    NutritionTotals,
    RetrievalFailure,
)


def test_english_estimate_uses_compact_plain_text_layout() -> None:
    state = _estimate_state(language="en", assumptions=["100 g cooked rice.", "120 g chicken."])

    answer = synthesize_answer(state)["final_estimate"].text

    assert answer.startswith("🔥 Calories: 405±105 kcal")
    assert "Protein: 34–52 g\nFat: 4–6 g\nCarbs: 28–56 g" in answer
    assert "📋 Assumptions:\n• 100 g cooked rice.\n• 120 g chicken." in answer
    assert answer.endswith("🟡 Confidence: Medium")


def test_russian_estimate_uses_compact_plain_text_layout() -> None:
    state = _estimate_state(language="ru", assumptions=["100 г риса.", "120 г курицы."])

    answer = synthesize_answer(state)["final_estimate"].text

    assert answer.startswith("🔥 Калории: 405±105 ккал")
    assert "Белки: 34–52 г\nЖиры: 4–6 г\nУглеводы: 28–56 г" in answer
    assert "📋 Допущения:\n• 100 г риса.\n• 120 г курицы." in answer
    assert answer.endswith("🟡 Уверенность: средняя")


def test_estimate_renders_all_assumptions() -> None:
    assumptions = [f"Assumption {index}." for index in range(1, 12)]
    state = _estimate_state(language="en", assumptions=assumptions)

    answer = synthesize_answer(state)["final_estimate"].text

    for assumption in assumptions:
        assert f"• {assumption}" in answer


def test_low_confidence_note_is_localized() -> None:
    state = _estimate_state(language="ru", assumptions=["Ориентировочная порция."])
    state["meal"] = state["meal"].model_copy(update={"confidence": "low"})

    answer = synthesize_answer(state)["final_estimate"].text

    assert "🔴 Уверенность: низкая" in answer
    assert "💡 Для более точной оценки" in answer


def test_partial_estimate_with_unresolved_components_becomes_clarification() -> None:
    state = _estimate_state(language="en", assumptions=["One component was resolved."])
    state["ingredient_nutrition"] = [
        IngredientNutrition(
            ingredient_name="rice",
            matched_food_name="cooked white rice",
            grams_min=100,
            grams_max=100,
            per_100g=NutritionPer100g(
                food_name="cooked white rice",
                calories_kcal=130,
                protein_g=2.7,
                fat_g=0.3,
                carbs_g=28.2,
                source="fallback",
            ),
            source="fallback",
        )
    ]
    state["retrieval_failures"] = [
        RetrievalFailure(ingredient_name="sauce", canonical_query="sauce", reason="no match"),
        RetrievalFailure(ingredient_name="topping", canonical_query="topping", reason="no match"),
    ]

    final = synthesize_answer(state)["final_estimate"]

    assert final.is_clarification is True
    assert final.confidence == "low"
    assert "couldn't find reliable nutrition data" in final.text


def test_unresolved_component_does_not_ship_incomplete_total() -> None:
    state = _estimate_state(language="en", assumptions=["One component was resolved."])
    state["ingredient_nutrition"] = [
        IngredientNutrition(
            ingredient_name="rice",
            matched_food_name="cooked white rice",
            grams_min=100,
            grams_max=100,
            per_100g=NutritionPer100g(
                food_name="cooked white rice",
                calories_kcal=130,
                protein_g=2.7,
                fat_g=0.3,
                carbs_g=28.2,
                source="fallback",
            ),
            source="fallback",
            warning="sauce: used a broad class prior; confidence reduced.",
        )
    ]
    state["retrieval_failures"] = [
        RetrievalFailure(
            ingredient_name="garnish",
            canonical_query="garnish",
            reason="no match",
            grams_min=10,
            grams_max=20,
        ),
    ]

    final = synthesize_answer(state)["final_estimate"]

    assert final.is_clarification is True
    assert final.confidence == "low"
    assert final.totals is None
    assert "garnish" in final.text


def test_large_unresolved_component_still_clarifies() -> None:
    state = _estimate_state(language="en", assumptions=["One component was resolved."])
    state["ingredient_nutrition"] = [
        IngredientNutrition(
            ingredient_name="rice",
            matched_food_name="cooked white rice",
            grams_min=100,
            grams_max=100,
            per_100g=NutritionPer100g(
                food_name="cooked white rice",
                calories_kcal=130,
                protein_g=2.7,
                fat_g=0.3,
                carbs_g=28.2,
                source="fallback",
            ),
            source="fallback",
        )
    ]
    state["retrieval_failures"] = [
        RetrievalFailure(
            ingredient_name="main topping",
            canonical_query="main topping",
            reason="no match",
            grams_min=90,
            grams_max=120,
        ),
    ]

    final = synthesize_answer(state)["final_estimate"]

    assert final.is_clarification is True
    assert final.totals is None


def test_calorie_comparison_uses_refreshed_layout() -> None:
    state = _comparison_state(language="en")

    answer = synthesize_answer(state)["final_estimate"].text

    assert answer.startswith("🔥 Calorie comparison\n\n")
    assert "• rice (100 g): 130 kcal" in answer
    assert "• chicken (100 g): 170 kcal" in answer
    assert "Result: chicken has more calories." in answer
    assert answer.endswith("🟡 Confidence: Medium")


def test_russian_calorie_comparison_uses_refreshed_layout() -> None:
    state = _comparison_state(language="ru")

    answer = synthesize_answer(state)["final_estimate"].text

    assert answer.startswith("🔥 Сравнение калорийности\n\n")
    assert "• rice (100 г): 130 ккал" in answer
    assert "• chicken (100 г): 170 ккал" in answer
    assert "Итог: больше калорий в chicken." in answer
    assert answer.endswith("🟡 Уверенность: средняя")


def _estimate_state(*, language: str, assumptions: list[str]) -> dict:
    return {
        "normalized_input": NormalizedInput(
            text="rice and chicken",
            has_text=True,
            has_image=False,
            language=language,
        ),
        "meal": MealUnderstanding(
            ingredients=[
                IngredientEstimate(name="rice", grams_min=100, grams_max=200),
                IngredientEstimate(name="chicken", grams_min=100, grams_max=150),
            ],
            assumptions=assumptions,
            confidence="medium",
        ),
        "totals": NutritionTotals(
            calories_kcal=MacroRange(min=300, max=510),
            protein_g=MacroRange(min=34, max=52),
            fat_g=MacroRange(min=4, max=6),
            carbs_g=MacroRange(min=28, max=56),
        ),
        "ingredient_nutrition": [],
    }


def _comparison_state(*, language: str) -> dict:
    return {
        "normalized_input": NormalizedInput(
            text=(
                "Где больше калорий, rice или chicken?"
                if language == "ru"
                else "Which has more calories, rice or chicken?"
            ),
            has_text=True,
            has_image=False,
            language=language,
        ),
        "meal": MealUnderstanding(
            ingredients=[
                IngredientEstimate(name="rice", grams_min=100, grams_max=100),
                IngredientEstimate(name="chicken", grams_min=100, grams_max=100),
            ],
            assumptions=["100 g each."],
            confidence="medium",
        ),
        "totals": NutritionTotals(
            calories_kcal=MacroRange(min=300, max=300),
            protein_g=MacroRange(min=30, max=30),
            fat_g=MacroRange(min=5, max=5),
            carbs_g=MacroRange(min=30, max=30),
        ),
        "ingredient_nutrition": [
            IngredientNutrition(
                ingredient_name="rice",
                matched_food_name="rice",
                grams_min=100,
                grams_max=100,
                per_100g=NutritionPer100g(
                    food_name="rice",
                    calories_kcal=130,
                    protein_g=3,
                    fat_g=0,
                    carbs_g=28,
                    source="fallback",
                ),
                source="fallback",
            ),
            IngredientNutrition(
                ingredient_name="chicken",
                matched_food_name="chicken",
                grams_min=100,
                grams_max=100,
                per_100g=NutritionPer100g(
                    food_name="chicken",
                    calories_kcal=170,
                    protein_g=31,
                    fat_g=4,
                    carbs_g=0,
                    source="fallback",
                ),
                source="fallback",
            ),
        ],
    }
