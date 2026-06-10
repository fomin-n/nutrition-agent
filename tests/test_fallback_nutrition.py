from app.tools.fallback_nutrition import lookup_fallback_food


def test_fallback_lookup_alias() -> None:
    food = lookup_fallback_food("two eggs")
    assert food is not None
    assert food.food_name == "egg"
    assert food.protein_g > 10


def test_required_fallback_food_exists() -> None:
    food = lookup_fallback_food("cooked buckwheat")
    assert food is not None
    assert food.calories_kcal == 92


def test_unknown_food_returns_none() -> None:
    assert lookup_fallback_food("completely unknown ingredient") is None

