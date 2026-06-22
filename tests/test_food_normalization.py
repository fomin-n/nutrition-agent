import pytest

from app.graph.nodes.text_parser import parse_text_locally
from app.tools.food_normalization import find_food_mentions


@pytest.mark.parametrize(
    ("text", "canonical"),
    [
        ("КБЖУ банана среднего размера", "banana"),
        ("калории в банане", "banana"),
        ("200 г лосося", "salmon cooked"),
        ("сколько калорий в семге 200 г", "salmon cooked"),
        ("БЖУ вареного яйца", "egg"),
        ("белок в йогурте", "yogurt plain"),
        ("калории натурального скира", "skyr plain"),
        ("30 г миндаля", "almonds"),
        ("200 г говядины", "beef cooked"),
        ("два куска хлеба", "bread"),
        ("порция творога", "cottage cheese"),
    ],
)
def test_russian_inflections_map_to_canonical_foods(text: str, canonical: str) -> None:
    assert [mention.canonical_name for mention in find_food_mentions(text)] == [canonical]


@pytest.mark.parametrize(
    "text",
    [
        "Риск дефицита бюджета высокий",
        "Сырая статистика за неделю",
        "Напиши функцию на Python",
    ],
)
def test_food_stems_do_not_match_unrelated_text(text: str) -> None:
    assert find_food_mentions(text) == ()


@pytest.mark.parametrize(
    ("text", "canonical", "minimum", "maximum"),
    [
        ("150 г запеченного лосося", "salmon cooked", 150, 150),
        ("лосось запеченный 150г", "salmon cooked", 150, 150),
        ("100g cooked chicken breast", "chicken breast cooked", 100, 100),
        ("30 г миндаля", "almonds", 30, 30),
        ("one medium banana", "banana", 100, 140),
        ("один средний банан", "banana", 100, 140),
        ("two slices of bread", "bread", 70, 110),
        ("два куска хлеба", "bread", 70, 110),
        ("банка 330 мл Coca-Cola Zero", "Coca-Cola Zero Sugar", 330, 330),
    ],
)
def test_portion_parser_handles_common_word_orders(
    text: str,
    canonical: str,
    minimum: float,
    maximum: float,
) -> None:
    meal = parse_text_locally(text)

    assert meal.needs_clarification is False
    assert len(meal.ingredients) == 1
    ingredient = meal.ingredients[0]
    assert ingredient.name == canonical
    assert ingredient.grams_min == minimum
    assert ingredient.grams_max == maximum


def test_multiple_food_quantities_are_owned_by_nearest_food() -> None:
    meal = parse_text_locally("one fried egg with 1 tsp oil")

    assert [ingredient.name for ingredient in meal.ingredients] == ["egg", "olive oil"]
    assert [(item.grams_min, item.grams_max) for item in meal.ingredients] == [
        (45, 60),
        (5, 5),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Calories in a burger?",
        "Сколько БЖУ в тарелке пасты?",
        "Сколько калорий в супе?",
        "How many calories in a salad?",
    ],
)
def test_materially_ambiguous_dishes_without_details_clarify(text: str) -> None:
    meal = parse_text_locally(text)

    assert meal.needs_clarification is True
    assert meal.ingredients == []
    assert meal.confidence == "low"
    assert meal.assumptions


@pytest.mark.parametrize(
    ("text", "canonical", "grams"),
    [
        ("Calories and macros for a 300g Greek salad", "Greek salad", 300),
        ("How many calories in a cheeseburger, about 180g?", "hamburger", 180),
        ("Сколько калорий в пасте карбонара 350 г?", "pasta carbonara", 350),
        ("Сколько калорий в борще со сметаной 400 г?", "borscht with sour cream", 400),
    ],
)
def test_named_or_sized_dishes_can_be_estimated(
    text: str,
    canonical: str,
    grams: float,
) -> None:
    meal = parse_text_locally(text)

    assert meal.needs_clarification is False
    assert [(item.name, item.grams_min, item.grams_max) for item in meal.ingredients] == [
        (canonical, grams, grams)
    ]


def test_zero_sugar_product_variant_is_preserved() -> None:
    zero = parse_text_locally("кола без сахара 500 мл")
    regular = parse_text_locally("обычная кола 500 мл")

    assert zero.ingredients[0].name == "Coca-Cola Zero Sugar"
    assert regular.ingredients[0].name == "Coca-Cola"


@pytest.mark.parametrize(
    ("text", "canonical"),
    [
        ("Macros for 45g rolled dry oats", "dry oats"),
        ("Estimate a 70 g croissant", "butter croissant"),
        ("КБЖУ 25 г картофельных чипсов", "potato chips"),
        ("Белок в 120 г хумуса", "hummus"),
        ("Calories in a 125g mozzarella ball", "mozzarella"),
        ("Estimate one Big Mac", "McDonald's Big Mac"),
    ],
)
def test_specific_common_food_aliases_win_over_generic_components(
    text: str,
    canonical: str,
) -> None:
    meal = parse_text_locally(text)

    assert meal.needs_clarification is False
    assert [ingredient.name for ingredient in meal.ingredients] == [canonical]
