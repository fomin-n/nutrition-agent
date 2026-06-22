import re
from dataclasses import dataclass

from app.tools.fallback_nutrition import (
    FALLBACK_FOODS,
    is_plain_water_query,
    lookup_fallback_profile,
    normalize_food_query,
)
from app.tools.food_query import PRODUCT_ALIASES, ProductAliasProfile


@dataclass(frozen=True)
class FoodMention:
    canonical_name: str
    matched_text: str
    start: int
    end: int
    product: ProductAliasProfile | None = None


@dataclass(frozen=True)
class QuantityMention:
    amount: float
    unit: str
    start: int
    end: int


@dataclass(frozen=True)
class PortionEstimate:
    grams_min: float
    grams_max: float
    note: str
    explicit: bool


# Patterns are intentionally conservative. They cover common inflections without a
# morphology dependency and avoid short prefixes such as `рис`, which can collide
# with unrelated words.
RUSSIAN_FOOD_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("banana", (r"банан\w*",)),
    ("apple", (r"яблок\w*",)),
    ("salmon cooked", (r"лосос\w*", r"семг\w*")),
    ("egg", (r"яйц\w*", r"яиц")),
    ("almonds", (r"миндал\w*",)),
    ("beef cooked", (r"говядин\w*",)),
    ("bread", (r"хлеб\w*",)),
    ("yogurt plain", (r"йогурт\w*",)),
    ("skyr plain", (r"ск[иы]р\w*",)),
    ("cottage cheese", (r"творог\w*",)),
    ("tofu firm", (r"тофу",)),
    ("lentils cooked", (r"чечевиц\w*",)),
    ("chickpeas cooked", (r"нут(?:а|е|ом|у)?",)),
    ("avocado", (r"авокадо",)),
    ("cooked buckwheat", (r"греч\w*",)),
    ("cooked white rice", (r"рис(?:а|е|ом|у)?",)),
    ("oatmeal cooked", (r"овсян\w*",)),
    ("potato boiled", (r"картоф\w*", r"картош\w*")),
    ("cheese", (r"сыр(?:а|е|ом|у|ы)?",)),
    ("milk", (r"молок\w*",)),
    ("tomato", (r"помидор\w*", r"томат\w*")),
    ("cucumber", (r"огур\w*",)),
    ("beet cooked", (r"свекл\w*",)),
    ("cabbage cooked", (r"капуст\w*",)),
    ("carrot cooked", (r"морков\w*",)),
    ("onion", (r"лук(?:а|е|ом|у)?",)),
    ("cooked pasta", (r"паст\w*", r"макарон\w*")),
    ("mixed salad vegetables", (r"салат\w*",)),
    ("hamburger", (r"бургер\w*", r"гамбургер\w*", r"чизбургер\w*")),
    ("vegetable soup", (r"суп\w*",)),
    ("water", (r"вод(?:а|ы|е|у|ой|ою)?",)),
)

DEFAULT_PORTIONS_G: dict[str, tuple[float, float]] = {
    "cooked white rice": (150, 220),
    "cooked pasta": (160, 240),
    "cooked buckwheat": (150, 220),
    "chicken breast cooked": (120, 180),
    "beef cooked": (100, 170),
    "salmon cooked": (120, 180),
    "egg": (45, 60),
    "olive oil": (10, 18),
    "butter": (8, 15),
    "potato boiled": (150, 250),
    "bread": (35, 55),
    "banana": (100, 140),
    "apple": (150, 220),
    "tomato": (80, 150),
    "cucumber": (80, 160),
    "beet cooked": (80, 150),
    "cabbage cooked": (80, 160),
    "carrot cooked": (70, 140),
    "onion": (30, 80),
    "mixed salad vegetables": (80, 180),
    "cheese": (25, 45),
    "yogurt plain": (125, 200),
    "skyr plain": (125, 200),
    "milk": (200, 300),
    "water": (250, 250),
    "oatmeal cooked": (180, 280),
    "almonds": (25, 35),
    "avocado": (120, 180),
    "tofu firm": (100, 180),
    "lentils cooked": (150, 220),
    "chickpeas cooked": (150, 220),
    "cottage cheese": (150, 220),
    "Nutella": (15, 20),
    "peanut butter": (25, 35),
    "protein bar": (50, 65),
    "instant noodles dry": (75, 100),
    "vanilla ice cream": (80, 140),
    "tuna canned in water": (100, 150),
    "dark chocolate": (20, 35),
    "mozzarella": (100, 125),
    "hummus": (80, 150),
    "granola": (40, 60),
    "butter croissant": (55, 75),
    "pain au chocolat": (65, 85),
    "baguette": (80, 120),
    "potato chips": (25, 40),
    "McDonald's Big Mac": (215, 215),
    "Coca-Cola": (330, 330),
    "Coca-Cola Zero Sugar": (330, 330),
    "pizza": (100, 160),
    "hamburger": (180, 280),
    "vegetable soup": (250, 400),
    "Greek salad": (250, 350),
    "chicken Caesar salad": (300, 400),
    "pasta carbonara": (300, 400),
    "borscht": (350, 450),
    "borscht with sour cream": (300, 450),
    "pelmeni": (12, 18),
    "KFC chicken wing": (35, 50),
    "mashed potatoes": (180, 250),
    "meat cutlet": (80, 120),
}

CONVENTIONAL_DISH_PRIORS = {
    "cooked pasta",
    "mixed salad vegetables",
    "hamburger",
    "vegetable soup",
    "Greek salad",
    "chicken Caesar salad",
    "pasta carbonara",
    "borscht",
    "borscht with sour cream",
    "pelmeni",
    "KFC chicken wing",
    "mashed potatoes",
    "meat cutlet",
}

COUNT_WORDS: dict[str, float] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "a": 1,
    "an": 1,
    "один": 1,
    "одно": 1,
    "одна": 1,
    "одном": 1,
    "одной": 1,
    "одного": 1,
    "два": 2,
    "две": 2,
    "двух": 2,
    "три": 3,
    "трех": 3,
    "троих": 3,
    "четыре": 4,
    "четырех": 4,
    "пять": 5,
}

UNIT_GRAMS: dict[str, float] = {
    "g": 1,
    "gram": 1,
    "grams": 1,
    "г": 1,
    "гр": 1,
    "грамм": 1,
    "грамма": 1,
    "граммов": 1,
    "kg": 1000,
    "кг": 1000,
    "oz": 28.35,
    "ounce": 28.35,
    "ounces": 28.35,
    "tbsp": 14,
    "tablespoon": 14,
    "tablespoons": 14,
    "столовая ложка": 14,
    "столовой ложке": 14,
    "tsp": 5,
    "teaspoon": 5,
    "teaspoons": 5,
    "чайная ложка": 5,
    "чайной ложке": 5,
}

COUNT_UNITS = {
    "slice",
    "slices",
    "piece",
    "pieces",
    "кусок",
    "куска",
    "кусочка",
    "ломтик",
    "ломтика",
    "штука",
    "штуки",
    "штук",
}

VOLUME_ML: dict[str, float] = {
    "ml": 1,
    "milliliter": 1,
    "milliliters": 1,
    "мл": 1,
    "l": 1000,
    "liter": 1000,
    "liters": 1000,
    "litre": 1000,
    "litres": 1000,
    "л": 1000,
    "литр": 1000,
    "литра": 1000,
    "литре": 1000,
    "литров": 1000,
}

HIGH_VARIANCE_FOODS = {
    "mixed salad vegetables",
    "hamburger",
    "cooked pasta",
    "vegetable soup",
}

PREPARATION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("fried", r"\b(fried|pan fried|жарен\w*)\b"),
    ("baked", r"\b(baked|roasted|запеч\w*)\b"),
    ("boiled", r"\b(boiled|варен\w*|отварн\w*)\b"),
    ("grilled", r"\b(grilled|грил\w*)\b"),
    ("cooked", r"\b(cooked|приготовлен\w*)\b"),
    ("raw", r"\b(raw|сырой|сырая|сырое|сырого)\b"),
)


def find_food_mentions(text: str) -> tuple[FoodMention, ...]:
    normalized = normalize_food_query(text)
    candidates: list[FoodMention] = []

    for product in PRODUCT_ALIASES:
        for alias in sorted(product.aliases, key=len, reverse=True):
            match = _search_alias(normalized, alias)
            if match:
                candidates.append(
                    FoodMention(
                        canonical_name=product.canonical_product,
                        matched_text=match.group(0),
                        start=match.start(),
                        end=match.end(),
                        product=product,
                    )
                )
                break

    for food in FALLBACK_FOODS:
        if food.food_category == "plain_water" and not is_plain_water_query(normalized):
            continue
        for alias in sorted((food.name, *food.aliases), key=len, reverse=True):
            match = _search_alias(normalized, alias)
            if match:
                candidates.append(
                    FoodMention(
                        canonical_name=food.name,
                        matched_text=match.group(0),
                        start=match.start(),
                        end=match.end(),
                    )
                )
                break

    for canonical, patterns in RUSSIAN_FOOD_PATTERNS:
        if canonical == "water" and not is_plain_water_query(normalized):
            continue
        for pattern in patterns:
            match = re.search(rf"\b(?:{pattern})\b", normalized)
            if match:
                candidates.append(
                    FoodMention(
                        canonical_name=canonical,
                        matched_text=match.group(0),
                        start=match.start(),
                        end=match.end(),
                    )
                )
                break

    selected: list[FoodMention] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (item.end - item.start, item.product is not None),
        reverse=True,
    ):
        if any(
            candidate.start < current.end and candidate.end > current.start
            for current in selected
        ):
            continue
        if any(current.canonical_name == candidate.canonical_name for current in selected):
            continue
        selected.append(candidate)
    return tuple(sorted(selected, key=lambda item: item.start))


def extract_quantity_mentions(text: str) -> tuple[QuantityMention, ...]:
    normalized = normalize_food_query(text)
    number_pattern = _number_pattern()
    units = tuple(UNIT_GRAMS) + tuple(COUNT_UNITS) + tuple(VOLUME_ML)
    unit_pattern = "|".join(re.escape(unit) for unit in sorted(units, key=len, reverse=True))
    matches: list[QuantityMention] = []
    for match in re.finditer(rf"\b(?P<amount>{number_pattern})\s*(?P<unit>{unit_pattern})\b", normalized):
        matches.append(
            QuantityMention(
                amount=_parse_number(match.group("amount")),
                unit=match.group("unit"),
                start=match.start(),
                end=match.end(),
            )
        )
    occupied = tuple((match.start, match.end) for match in matches)
    for match in re.finditer(r"\b(?:in|в)\s+(?P<unit>liter|litre|литре)\b", normalized):
        if any(match.start() < end and match.end() > start for start, end in occupied):
            continue
        matches.append(
            QuantityMention(
                amount=1,
                unit=match.group("unit"),
                start=match.start(),
                end=match.end(),
            )
        )
    return tuple(sorted(matches, key=lambda item: item.start))


def estimate_portion(
    text: str,
    mention: FoodMention,
    mentions: tuple[FoodMention, ...],
) -> PortionEstimate:
    normalized = normalize_food_query(text)
    quantities = extract_quantity_mentions(normalized)
    quantity = _quantity_for_mention(mention, mentions, quantities)
    if quantity:
        converted = _quantity_to_grams(quantity, mention.canonical_name)
        if converted:
            return converted

    if mention.product and mention.product.default_serving_amount:
        amount = mention.product.default_serving_amount
        count = _nearby_count(normalized, mention) or 1
        amount *= count
        unit = mention.product.default_serving_unit
        if unit in VOLUME_ML:
            density = _density_g_per_ml(mention.canonical_name)
            if density is None:
                return PortionEstimate(amount, amount, "assumed standard packaged serving", False)
            grams = amount * VOLUME_ML[unit] * density
            return PortionEstimate(
                grams,
                grams,
                "assumed standard packaged serving at beverage density of 1 g/ml",
                False,
            )
        return PortionEstimate(amount, amount, "assumed standard packaged serving", False)

    count = _nearby_count(normalized, mention)
    if count is not None:
        minimum, maximum = DEFAULT_PORTIONS_G.get(mention.canonical_name, (100, 150))
        return PortionEstimate(
            grams_min=minimum * count,
            grams_max=maximum * count,
            note="estimated from item count",
            explicit=False,
        )

    minimum, maximum = DEFAULT_PORTIONS_G.get(mention.canonical_name, (100, 150))
    return PortionEstimate(minimum, maximum, "assumed standard portion", False)


def detect_preparation(text: str) -> str | None:
    normalized = normalize_food_query(text)
    for preparation, pattern in PREPARATION_PATTERNS:
        if re.search(pattern, normalized):
            return preparation
    return None


def is_high_variance_without_detail(
    text: str,
    mentions: tuple[FoodMention, ...],
) -> bool:
    if len(mentions) != 1 or mentions[0].canonical_name not in HIGH_VARIANCE_FOODS:
        return False
    if extract_quantity_mentions(text):
        return False
    normalized = normalize_food_query(text)
    named_dish_markers = (
        "greek",
        "caesar",
        "carbonara",
        "bolognese",
        "cheeseburger",
        "греческ",
        "цезар",
        "карбонар",
        "болоньез",
        "чизбургер",
    )
    return not any(marker in normalized for marker in named_dish_markers)


def _search_alias(normalized: str, alias: str) -> re.Match[str] | None:
    normalized_alias = normalize_food_query(alias)
    return re.search(rf"\b{re.escape(normalized_alias)}\b", normalized)


def _number_pattern() -> str:
    words = "|".join(re.escape(word) for word in sorted(COUNT_WORDS, key=len, reverse=True))
    return rf"\d+(?:[.,]\d+)?|{words}"


def _parse_number(value: str) -> float:
    if value in COUNT_WORDS:
        return COUNT_WORDS[value]
    return float(value.replace(",", "."))


def _quantity_for_mention(
    mention: FoodMention,
    mentions: tuple[FoodMention, ...],
    quantities: tuple[QuantityMention, ...],
) -> QuantityMention | None:
    if not quantities:
        return None
    if len(mentions) == 1:
        return quantities[0]
    nearest = min(quantities, key=lambda item: _span_distance(mention, item))
    owner = min(mentions, key=lambda item: _span_distance(item, nearest))
    if owner != mention or _span_distance(mention, nearest) > 32:
        return None
    return nearest


def _span_distance(mention: FoodMention, quantity: QuantityMention) -> int:
    if quantity.end <= mention.start:
        return mention.start - quantity.end
    if mention.end <= quantity.start:
        return quantity.start - mention.end
    return 0


def _quantity_to_grams(
    quantity: QuantityMention,
    canonical_name: str,
) -> PortionEstimate | None:
    if quantity.unit in UNIT_GRAMS:
        grams = quantity.amount * UNIT_GRAMS[quantity.unit]
        note = "explicit gram weight" if quantity.unit not in {"tbsp", "tablespoon", "tablespoons", "tsp", "teaspoon", "teaspoons", "столовая ложка", "столовой ложке", "чайная ложка", "чайной ложке"} else "estimated from measured serving"
        return PortionEstimate(grams, grams, note, True)
    if quantity.unit in VOLUME_ML:
        density = _density_g_per_ml(canonical_name)
        if density is not None:
            grams = quantity.amount * VOLUME_ML[quantity.unit] * density
            return PortionEstimate(
                grams,
                grams,
                "volume converted at assumed beverage density of 1 g/ml",
                True,
            )
        return None
    if quantity.unit in COUNT_UNITS:
        minimum, maximum = DEFAULT_PORTIONS_G.get(canonical_name, (100, 150))
        return PortionEstimate(
            minimum * quantity.amount,
            maximum * quantity.amount,
            "estimated from serving count",
            False,
        )
    return None


def _density_g_per_ml(canonical_name: str) -> float | None:
    profile = lookup_fallback_profile(canonical_name)
    return profile.density_g_per_ml if profile else None


def _nearby_count(normalized: str, mention: FoodMention) -> float | None:
    prefix = normalized[max(0, mention.start - 48) : mention.start]
    match = re.search(
        rf"\b(?P<count>{_number_pattern()})\b(?:\s+[\w]+){{0,3}}\s*$",
        prefix,
    )
    return _parse_number(match.group("count")) if match else None
