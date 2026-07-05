import pytest

from app.graph.nodes.text_parser import parse_text_locally
from app.tools.food_normalization import (
    allocate_composite_portions,
    detect_preparation,
    extract_total_portion_grams,
    find_food_mentions,
)


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
        ("Calories in a 125g mozzarella ball", "fresh mozzarella"),
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


def test_negated_component_mentions_are_not_selected() -> None:
    assert [mention.canonical_name for mention in find_food_mentions("200 г пасты без соуса")] == [
        "cooked pasta"
    ]


def test_russian_chicken_soup_uses_whole_dish_prior() -> None:
    meal = parse_text_locally("Сколько БЖУ в тарелке куриного супа 400 г?", language="ru")

    assert meal.needs_clarification is False
    assert [ingredient.name for ingredient in meal.ingredients] == ["chicken soup"]
    assert meal.ingredients[0].grams_min == 400
    assert meal.ingredients[0].grams_max == 400


@pytest.mark.parametrize(
    ("text", "canonical", "grams"),
    [
        ("Сколько калорий в шакшуке 300 г?", "shakshuka", 300),
        ("Сколько калорий в лазанье 350 г?", "lasagna", 350),
        ("Calories and macros in 200g syrniki", "syrniki", 200),
        ("Сколько БЖУ в шаурме с курицей 350 г?", "chicken shawarma", 350),
        ("Macros for a falafel wrap, about 350g", "falafel wrap", 350),
        ("Calories in two beef tacos, about 300g total", "beef tacos", 300),
        ("Calories in 6 chicken nuggets", "chicken nuggets", 96),
        ("Calories in 3 pancakes with syrup", "pancakes with syrup", 270),
        ("Calories in 250g potato vareniki", "potato vareniki", 250),
        ("Сколько калорий в клаб-сэндвиче 300 г?", "club sandwich", 300),
        ("Сколько БЖУ в фо бо 600 г?", "beef pho", 600),
        ("Calories in chicken pad thai, 450g", "chicken pad thai", 450),
        ("Calories in a kebab plate with rice, about 500g", "kebab plate with rice", 500),
        ("Сколько калорий в цезарь-ролле с курицей 300 г?", "caesar chicken wrap", 300),
    ],
)
def test_targeted_composite_priors_parse_as_single_known_dishes(
    text: str,
    canonical: str,
    grams: float,
) -> None:
    meal = parse_text_locally(text)

    assert meal.needs_clarification is False
    assert [ingredient.name for ingredient in meal.ingredients] == [canonical]
    assert meal.ingredients[0].grams_min == grams


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Сколько БЖУ в мюсли с йогуртом и ягодами 350 г?", "muesli with yogurt and berries"),
        ("салат с помидорами и моцареллой 300 г", "tomato mozzarella salad"),
        ("салат с креветками гриль 350 г", "grilled shrimp salad"),
        ("Macros in beef udon noodles, about 500g", "beef udon noodles"),
        ("Сколько калорий в стейке с картошкой фри, порция 500 г?", "steak with fries"),
    ],
)
def test_high_variance_composite_golden_cases_use_whole_dish_priors(
    text: str,
    expected: str,
) -> None:
    meal = parse_text_locally(text)

    assert meal.needs_clarification is False
    assert [ingredient.name for ingredient in meal.ingredients] == [expected]
    assert meal.ingredients[0].confidence == "high"


def test_trailing_single_weight_allocates_natural_composite_total() -> None:
    text = "rice with chicken 400 g"
    mentions = find_food_mentions(text)
    total = extract_total_portion_grams(text, mentions)
    allocations = allocate_composite_portions(text, mentions, preparation=detect_preparation(text))

    assert [mention.canonical_name for mention in mentions] == [
        "cooked white rice",
        "chicken breast cooked",
    ]
    assert total == 400
    assert [(item.canonical_name, round(item.grams_min), round(item.grams_max)) for item in allocations] == [
        ("cooked white rice", 192, 288),
        ("chicken breast cooked", 128, 192),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Calories and macros in 400g lentil soup",
        "Calories and macros in lentil soup, 400 g",
    ],
)
def test_single_weight_on_lentil_soup_is_total_not_additive(text: str) -> None:
    mentions = find_food_mentions(text)
    total = extract_total_portion_grams(text, mentions)
    allocations = allocate_composite_portions(text, mentions, preparation=detect_preparation(text))

    assert [mention.canonical_name for mention in mentions] == [
        "lentils cooked",
        "vegetable soup",
    ]
    assert total == 400
    assert sum((item.grams_min + item.grams_max) / 2 for item in allocations) == 400


def test_leading_single_weight_on_chicken_salad_can_be_total() -> None:
    text = "300g chicken salad"
    mentions = find_food_mentions(text)

    assert extract_total_portion_grams(text, mentions) == 300
    assert [(item.canonical_name, round(item.grams_min), round(item.grams_max)) for item in allocate_composite_portions(text, mentions)] == [
        ("chicken breast cooked", 96, 144),
        ("mixed salad vegetables", 144, 216),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "200 g of rice with chicken",
        "100 g chicken with rice",
    ],
)
def test_leading_single_weight_stays_attached_to_the_nearest_ingredient(text: str) -> None:
    mentions = find_food_mentions(text)

    assert extract_total_portion_grams(text, mentions) is None
    assert allocate_composite_portions(text, mentions) == ()
