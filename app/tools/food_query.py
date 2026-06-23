import re
from dataclasses import dataclass
from typing import Literal

from app.i18n import detect_language
from app.tools.fallback_nutrition import lookup_fallback_profile, normalize_food_query
from app.tools.food_vocabulary import load_food_vocabulary

QueryKind = Literal[
    "generic_ingredient",
    "branded_product",
    "restaurant_menu_item",
    "standard_prepared_dish",
    "user_composite_meal",
    "photo_derived_food",
]
FoodCategory = Literal[
    "food",
    "chocolate_bar",
    "sugary_soft_drink",
    "zero_sugar_soft_drink",
    "plain_water",
    "unknown",
]
ProductVariant = Literal["regular", "zero_sugar", "unknown"]


@dataclass(frozen=True)
class ProductAliasProfile:
    canonical_product: str
    brand: str
    category: FoodCategory
    variant: ProductVariant
    aliases: tuple[str, ...]
    product_type: str | None = None
    query_expansions: tuple[str, ...] = ()
    default_serving_amount: float | None = None
    default_serving_unit: str | None = None


@dataclass(frozen=True)
class NormalizedFoodQuery:
    original: str
    language: str
    normalized_name: str
    canonical_query: str
    query_kind: QueryKind
    brand: str | None = None
    restaurant: str | None = None
    preparation: str | None = None
    quantity: float | None = None
    unit: str | None = None
    region: str | None = None
    food_category: FoodCategory = "unknown"
    product_variant: ProductVariant = "unknown"
    default_serving_amount: float | None = None
    default_serving_unit: str | None = None
    product_type: str | None = None
    query_expansions: tuple[str, ...] = ()


_VOCABULARY = load_food_vocabulary()

PRODUCT_ALIASES: tuple[ProductAliasProfile, ...] = tuple(
    ProductAliasProfile(
        canonical_product=product.canonical_product,
        brand=product.brand,
        category=product.category,  # type: ignore[arg-type]
        variant=product.variant,  # type: ignore[arg-type]
        aliases=product.aliases,
        product_type=product.product_type,
        query_expansions=product.query_expansions,
        default_serving_amount=product.default_serving_amount,
        default_serving_unit=product.default_serving_unit,
    )
    for product in _VOCABULARY.products
)

BRAND_ALIASES = dict(_VOCABULARY.brand_aliases)
RESTAURANT_ALIASES = dict(_VOCABULARY.restaurant_aliases)
REGION_ALIASES = dict(_VOCABULARY.region_aliases)
PHRASE_TRANSLATIONS = {
    item.phrase: (item.replacement, item.preparation)
    for item in _VOCABULARY.phrase_translations
}
STANDARD_PREPARED_DISHES = set(_VOCABULARY.standard_prepared_dishes)


def normalize_food_description(
    text: str,
    *,
    language: str | None = None,
    source_route: str | None = None,
) -> NormalizedFoodQuery:
    original = text.strip()
    detected_language = language or detect_language(original)
    normalized = normalize_food_query(original)
    quantity, unit = _extract_quantity(normalized)
    product = _find_product(normalized)
    fallback_profile = lookup_fallback_profile(normalized)
    brand = product.brand if product else _find_alias(normalized, BRAND_ALIASES)
    restaurant = _find_alias(normalized, RESTAURANT_ALIASES)
    if restaurant is None and (re.search(r"\bbig mac\b", normalized) or re.search(r"\bбиг мак\b", normalized)):
        restaurant = "McDonald's"
    region = _find_alias(normalized, REGION_ALIASES)
    canonical_query, preparation = (
        (product.canonical_product, None) if product else _canonical_query(normalized)
    )

    if brand and normalize_food_query(brand) in normalize_food_query(canonical_query):
        canonical_query = re.sub(
            rf"\b{re.escape(normalize_food_query(brand))}\b",
            brand,
            canonical_query,
            count=1,
            flags=re.IGNORECASE,
        )
    elif brand:
        canonical_query = f"{brand} {canonical_query}".strip()
    if restaurant and restaurant.lower().replace("'", "") not in canonical_query.lower().replace("'", ""):
        canonical_query = f"{restaurant} {canonical_query}".strip()

    query_kind = _classify_query_kind(
        normalized=normalized,
        canonical_query=canonical_query,
        source_route=source_route,
        brand=brand,
        restaurant=restaurant,
    )
    return NormalizedFoodQuery(
        original=original,
        language=detected_language,
        normalized_name=normalized,
        canonical_query=canonical_query or normalized,
        query_kind=query_kind,
        brand=brand,
        restaurant=restaurant,
        preparation=preparation,
        quantity=quantity,
        unit=unit,
        region=region,
        food_category=(
            product.category
            if product
            else fallback_profile.food_category
            if fallback_profile and fallback_profile.food_category
            else "unknown"
        ),
        product_variant=product.variant if product else "unknown",
        default_serving_amount=product.default_serving_amount if product else None,
        default_serving_unit=product.default_serving_unit if product else None,
        product_type=product.product_type if product else None,
        query_expansions=product.query_expansions if product else (),
    )


def _canonical_query(normalized: str) -> tuple[str, str | None]:
    for phrase, (replacement, preparation) in sorted(PHRASE_TRANSLATIONS.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"\b{re.escape(normalize_food_query(phrase))}\b", normalized):
            return replacement, preparation

    fallback_profile = lookup_fallback_profile(normalized)
    if fallback_profile:
        return fallback_profile.name, None

    return normalized, None


def _classify_query_kind(
    *,
    normalized: str,
    canonical_query: str,
    source_route: str | None,
    brand: str | None,
    restaurant: str | None,
) -> QueryKind:
    if source_route in {"dish_photo", "image_with_text"}:
        return "photo_derived_food"
    if source_route == "packaged_food" or brand:
        return "branded_product"
    if restaurant:
        return "restaurant_menu_item"
    normalized_canonical = normalize_food_query(canonical_query)
    if any(re.search(rf"\b{re.escape(normalize_food_query(item))}\b", normalized_canonical) for item in STANDARD_PREPARED_DISHES):
        return "standard_prepared_dish"
    if any(token in normalized for token in (" with ", " and ", " с ", " и ", ",")):
        return "user_composite_meal"
    return "generic_ingredient"


def _extract_quantity(normalized: str) -> tuple[float | None, str | None]:
    match = re.search(
        r"\b(\d+(?:[.,]\d+)?)\s*(g|gram|grams|kg|oz|ml|milliliter|milliliters|l|liter|liters|litre|litres|г|гр|грамм|грамма|граммов|кг|мл|л|литр|литра|литре|литров)\b",
        normalized,
    )
    if not match:
        return None, None
    try:
        quantity = float(match.group(1).replace(",", "."))
    except ValueError:
        return None, None
    unit = match.group(2)
    return quantity, unit


def _find_alias(normalized: str, aliases: dict[str, str]) -> str | None:
    for alias, value in aliases.items():
        normalized_alias = normalize_food_query(alias)
        if re.search(rf"\b{re.escape(normalized_alias)}\b", normalized):
            return value
    return None


def _find_product(normalized: str) -> ProductAliasProfile | None:
    for product in PRODUCT_ALIASES:
        for alias in sorted(product.aliases, key=len, reverse=True):
            normalized_alias = normalize_food_query(alias)
            if re.search(rf"\b{re.escape(normalized_alias)}\b", normalized):
                return product
    return None


def product_profiles_in_text(text: str) -> tuple[ProductAliasProfile, ...]:
    normalized = normalize_food_query(text)
    matches: list[tuple[int, int, int, ProductAliasProfile]] = []
    for product in PRODUCT_ALIASES:
        best_match: tuple[int, int, int, ProductAliasProfile] | None = None
        for alias in product.aliases:
            normalized_alias = normalize_food_query(alias)
            match = re.search(rf"\b{re.escape(normalized_alias)}\b", normalized)
            if match is None:
                continue
            candidate = (len(normalized_alias), match.start(), match.end(), product)
            if best_match is None or candidate[0] > best_match[0]:
                best_match = candidate
        if best_match:
            matches.append(best_match)

    selected: list[tuple[int, int, ProductAliasProfile]] = []
    for _, start, end, product in sorted(matches, key=lambda item: item[0], reverse=True):
        if any(start < selected_end and end > selected_start for selected_start, selected_end, _ in selected):
            continue
        selected.append((start, end, product))
    return tuple(product for _, _, product in sorted(selected, key=lambda item: item[0]))


def product_profile_for_canonical(name: str) -> ProductAliasProfile | None:
    normalized_name = normalize_food_query(name)
    return next(
        (
            product
            for product in PRODUCT_ALIASES
            if normalize_food_query(product.canonical_product) == normalized_name
        ),
        None,
    )
