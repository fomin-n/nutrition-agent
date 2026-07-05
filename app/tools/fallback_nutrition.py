import re
from dataclasses import dataclass

from app.schemas.nutrition import NutritionPer100g
from app.tools.food_vocabulary import load_food_vocabulary, normalize_food_query


@dataclass(frozen=True)
class FallbackFood:
    name: str
    calories_kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    aliases: tuple[str, ...]
    density_g_per_ml: float | None = None
    food_category: str | None = None
    flags: frozenset[str] = frozenset()

    def as_nutrition(self) -> NutritionPer100g:
        return NutritionPer100g(
            food_name=self.name,
            calories_kcal=self.calories_kcal,
            protein_g=self.protein_g,
            fat_g=self.fat_g,
            carbs_g=self.carbs_g,
            source="fallback",
            source_id=self.name,
        )


def _load_fallback_foods() -> tuple[FallbackFood, ...]:
    return tuple(
        FallbackFood(
            name=food.name,
            calories_kcal=food.calories_kcal,
            protein_g=food.protein_g,
            fat_g=food.fat_g,
            carbs_g=food.carbs_g,
            aliases=food.aliases,
            density_g_per_ml=food.density_g_per_ml,
            food_category=food.food_category,
            flags=food.flags,
        )
        for food in load_food_vocabulary().foods
    )


FALLBACK_FOODS: tuple[FallbackFood, ...] = _load_fallback_foods()
_FOODS_BY_NAME = {food.name: food for food in FALLBACK_FOODS}
_COMPONENT_CLASS_PRIOR_NAMES = frozenset(
    food.name for food in FALLBACK_FOODS if "component_class_prior" in food.flags
)
_COMPONENT_CLASS_PRIOR_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(?:sauce|dressing|spread|соус\w*|заправк\w*)\b", "generic sauce"),
    (r"\b(?:mayonnaise|mayo|майонез\w*)\b", "mayonnaise"),
    (r"\b(?:mushroom\w*|гриб\w*|шампиньон\w*)\b", "mushrooms"),
    (r"\b(?:fried fish|battered fish|fish fillet|рыб\w*\s+в\s+кляр\w*)\b", "fried fish fillet"),
    (r"\b(?:oat flakes|rolled oats|овсян\w*\s+хлоп\w*)\b", "dry oats"),
)


def fallback_names() -> set[str]:
    return set(load_food_vocabulary().fallback_names)


def contains_water_reference(query: str) -> bool:
    normalized = normalize_food_query(query)
    return bool(
        re.search(r"\bwater\b", normalized)
        or re.search(r"\bвод(?:а|ы|е|у|ой|ою)?\b", normalized)
        or re.search(r"\bvitaminwater\b", normalized)
    )


def is_plain_water_query(query: str) -> bool:
    normalized = normalize_food_query(query)
    if not contains_water_reference(normalized):
        return False
    additive_patterns = (
        r"\b(?:flavored|flavoured|sweetened|sugar|syrup|vitaminwater|vitamin water|lemon|fruit)\b",
        r"\b(?:ароматизирован\w*|сладк\w*|сахар\w*|сироп\w*|витамин\w*|лимон\w*|фрукт\w*)\b",
    )
    return not any(re.search(pattern, normalized) for pattern in additive_patterns)


def lookup_fallback_profile(query: str) -> FallbackFood | None:
    normalized = normalize_food_query(query)
    if not normalized:
        return None

    best: FallbackFood | None = None
    best_alias_len = 0
    for food in FALLBACK_FOODS:
        if food.food_category == "plain_water" and not is_plain_water_query(normalized):
            continue
        aliases = (food.name, *food.aliases)
        for alias in aliases:
            normalized_alias = normalize_food_query(alias)
            if normalized == normalized_alias:
                return food
            if (
                re.search(rf"\b{re.escape(normalized_alias)}\b", normalized)
                and len(normalized_alias) > best_alias_len
            ):
                best = food
                best_alias_len = len(normalized_alias)
    return best


def lookup_fallback_food(query: str) -> NutritionPer100g | None:
    profile = lookup_fallback_profile(query)
    return profile.as_nutrition() if profile else None


def lookup_component_class_prior(query: str) -> FallbackFood | None:
    normalized = normalize_food_query(query)
    profile = lookup_fallback_profile(normalized)
    if profile and is_component_class_prior_name(profile.name):
        return profile
    for pattern, food_name in _COMPONENT_CLASS_PRIOR_PATTERNS:
        if re.search(pattern, normalized):
            return _FOODS_BY_NAME.get(food_name)
    return None


def is_component_class_prior_name(food_name: str) -> bool:
    return food_name in _COMPONENT_CLASS_PRIOR_NAMES


def is_high_variance_fallback_name(food_name: str) -> bool:
    profile = _FOODS_BY_NAME.get(food_name)
    return bool(profile and "high_variance" in profile.flags)
