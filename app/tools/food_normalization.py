import re
from dataclasses import dataclass

from app.llm.client import get_settings
from app.tools.fallback_nutrition import (
    FALLBACK_FOODS,
    is_plain_water_query,
    lookup_fallback_profile,
    normalize_food_query,
)
from app.tools.food_linker import (
    LinkedFoodSpan,
    find_embedding_food_mentions,
    record_shadow_disagreement,
)
from app.tools.food_query import PRODUCT_ALIASES, ProductAliasProfile
from app.tools.food_vocabulary import load_food_vocabulary


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


@dataclass(frozen=True)
class CompositeAllocation:
    canonical_name: str
    grams_min: float
    grams_max: float
    note: str


_VOCABULARY = load_food_vocabulary()

# Patterns are intentionally conservative. They cover common inflections without a
# morphology dependency and avoid short prefixes such as `рис`, which can collide
# with unrelated words.
RUSSIAN_FOOD_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    _VOCABULARY.russian_food_patterns
)

DEFAULT_PORTIONS_G: dict[str, tuple[float, float]] = dict(_VOCABULARY.default_portions_g)

CONVENTIONAL_DISH_PRIORS = set(_VOCABULARY.conventional_dish_priors)

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

HIGH_VARIANCE_FOODS = set(_VOCABULARY.high_variance_foods)
FOOD_ROLES = dict(_VOCABULARY.food_roles)

PREPARATION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("fried", r"\b(fried|pan fried|жарен\w*)\b"),
    ("baked", r"\b(baked|roasted|запеч\w*)\b"),
    ("boiled", r"\b(boiled|варен\w*|отварн\w*)\b"),
    ("grilled", r"\b(grilled|грил\w*)\b"),
    ("cooked", r"\b(cooked|приготовлен\w*)\b"),
    ("raw", r"\b(raw|сырой|сырая|сырое|сырого)\b"),
)


def find_food_mentions(text: str) -> tuple[FoodMention, ...]:
    legacy_mentions = _find_food_mentions_legacy(text)
    settings = get_settings()
    if settings.food_linker_shadow_enabled or settings.food_linker_embeddings_enabled:
        embedding_mentions = _embedding_food_mentions(text, settings.food_linker_similarity_threshold)
        if settings.food_linker_shadow_enabled:
            record_shadow_disagreement(
                legacy=tuple(mention.canonical_name for mention in legacy_mentions),
                embedding=tuple(mention.canonical_name for mention in embedding_mentions),
            )
        if settings.food_linker_embeddings_enabled and embedding_mentions:
            return embedding_mentions
    return legacy_mentions


def _find_food_mentions_legacy(text: str) -> tuple[FoodMention, ...]:
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


def _embedding_food_mentions(text: str, threshold: float) -> tuple[FoodMention, ...]:
    return tuple(_linked_span_to_mention(link) for link in find_embedding_food_mentions(text, threshold=threshold))


def _linked_span_to_mention(link: LinkedFoodSpan) -> FoodMention:
    product = next(
        (
            profile
            for profile in PRODUCT_ALIASES
            if profile.canonical_product == link.canonical_name
        ),
        None,
    )
    return FoodMention(
        canonical_name=link.canonical_name,
        matched_text=link.matched_text,
        start=link.start,
        end=link.end,
        product=product if link.is_product else None,
    )


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
        serving_count = _nearby_count(normalized, mention) or 1
        amount *= serving_count
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


def allocate_composite_portions(
    text: str,
    mentions: tuple[FoodMention, ...],
    *,
    preparation: str | None = None,
) -> tuple[CompositeAllocation, ...]:
    if len(mentions) < 2 or any(mention.product for mention in mentions):
        return ()
    total_grams = extract_total_portion_grams(text, mentions)
    if total_grams is None:
        return ()
    base_mentions = list(mentions)
    add_fat = (
        preparation == "fried"
        and not any(_food_role(mention.canonical_name) == "fat" for mention in mentions)
    )
    fat_fraction = 0.05 if add_fat else 0.0
    remaining_fraction = 1.0 - fat_fraction
    fractions = _composite_fractions(base_mentions)
    allocations = [
        _allocation(
            mention.canonical_name,
            total_grams * remaining_fraction * fractions[mention.canonical_name],
            "allocated from total composite portion",
            width=0.20,
        )
        for mention in base_mentions
    ]
    if add_fat:
        allocations.append(
            _allocation(
                "olive oil",
                total_grams * fat_fraction,
                "added for fried composite preparation",
                width=0.20,
            )
        )
    return tuple(allocations)


def extract_total_portion_grams(
    text: str,
    mentions: tuple[FoodMention, ...],
) -> float | None:
    normalized = normalize_food_query(text)
    quantities = [
        quantity
        for quantity in extract_quantity_mentions(normalized)
        if quantity.unit in {"g", "gram", "grams", "г", "гр", "грамм", "грамма", "граммов", "kg", "кг", "oz"}
    ]
    if len(mentions) < 2 or len(quantities) != 1:
        return None
    quantity = quantities[0]
    if not _quantity_looks_like_total_portion(normalized, quantity, mentions):
        return None
    if quantity.unit in {"kg", "кг"}:
        return quantity.amount * 1000
    if quantity.unit == "oz":
        return quantity.amount * 28.35
    return quantity.amount


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


def _quantity_looks_like_total_portion(
    normalized: str,
    quantity: QuantityMention,
    mentions: tuple[FoodMention, ...],
) -> bool:
    window = normalized[max(0, quantity.start - 40) : min(len(normalized), quantity.end + 24)]
    total_markers = (
        "portion",
        "serving",
        "plate",
        "bowl",
        "порци",
        "тарел",
        "мис",
    )
    if any(marker in window for marker in total_markers):
        return True
    nearest = min(mentions, key=lambda item: _span_distance(item, quantity))
    return quantity.start > max(mention.end for mention in mentions) and _span_distance(nearest, quantity) > 18


def _food_role(canonical_name: str) -> str:
    return FOOD_ROLES.get(canonical_name, "unknown")


def _composite_fractions(mentions: list[FoodMention]) -> dict[str, float]:
    roles = {mention.canonical_name: _food_role(mention.canonical_name) for mention in mentions}
    if len(mentions) == 2:
        starch = [name for name, role in roles.items() if role == "starch"]
        protein = [name for name, role in roles.items() if role == "protein"]
        vegetable = [name for name, role in roles.items() if role == "vegetable"]
        if starch and protein:
            return {starch[0]: 0.60, protein[0]: 0.40}
        if vegetable and protein:
            return {vegetable[0]: 0.60, protein[0]: 0.40}
    weights = {
        "starch": 0.55,
        "protein": 0.35,
        "vegetable": 0.30,
        "bread": 0.30,
        "dairy": 0.20,
        "fruit": 0.25,
        "fat": 0.05,
        "unknown": 0.25,
    }
    raw = {
        mention.canonical_name: weights.get(roles[mention.canonical_name], 0.25)
        for mention in mentions
    }
    total = sum(raw.values()) or 1.0
    return {name: value / total for name, value in raw.items()}


def _allocation(
    canonical_name: str,
    grams: float,
    note: str,
    *,
    width: float,
) -> CompositeAllocation:
    return CompositeAllocation(
        canonical_name=canonical_name,
        grams_min=round(max(1.0, grams * (1 - width)), 1),
        grams_max=round(max(1.0, grams * (1 + width)), 1),
        note=note,
    )
