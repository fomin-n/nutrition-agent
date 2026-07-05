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


def test_fresh_mozzarella_ball_uses_distinct_fresh_prior() -> None:
    food = lookup_fallback_food("125g mozzarella ball")

    assert food is not None
    assert food.food_name == "fresh mozzarella"
    assert food.calories_kcal == 250
    assert food.protein_g == 17.9
    assert food.fat_g == 17.9


def test_hummus_prior_matches_commercial_hummus_profile() -> None:
    food = lookup_fallback_food("100 g hummus")

    assert food is not None
    assert food.food_name == "hummus"
    assert food.calories_kcal == 229
    assert food.fat_g == 17.1


def test_unknown_food_returns_none() -> None:
    assert lookup_fallback_food("completely unknown ingredient") is None
