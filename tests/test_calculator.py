from app.graph.nodes.calculator import calculate_totals
from app.schemas.nutrition import IngredientNutrition, NutritionPer100g


def test_calculator_range_aggregation() -> None:
    rice = NutritionPer100g(
        food_name="cooked white rice",
        calories_kcal=130,
        protein_g=2.7,
        fat_g=0.3,
        carbs_g=28.2,
        source="fallback",
    )
    chicken = NutritionPer100g(
        food_name="chicken breast cooked",
        calories_kcal=165,
        protein_g=31,
        fat_g=3.6,
        carbs_g=0,
        source="fallback",
    )
    totals = calculate_totals(
        [
            IngredientNutrition(
                ingredient_name="rice",
                matched_food_name="cooked white rice",
                grams_min=100,
                grams_max=200,
                per_100g=rice,
                source="fallback",
            ),
            IngredientNutrition(
                ingredient_name="chicken",
                matched_food_name="chicken breast cooked",
                grams_min=100,
                grams_max=150,
                per_100g=chicken,
                source="fallback",
            ),
        ]
    )

    assert totals.calories_kcal.min == 300
    assert totals.calories_kcal.max == 510
    assert totals.protein_g.min == 34
    assert totals.protein_g.max == 52
    assert totals.carbs_g.min == 28
    assert totals.carbs_g.max == 56

