import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from types import MappingProxyType
from typing import Any

import yaml

LOGGER = logging.getLogger(__name__)


def normalize_food_query(query: str) -> str:
    cleaned = query.lower().replace("ё", "е")
    cleaned = re.sub(r"[^\w\s]", " ", cleaned, flags=re.UNICODE)
    cleaned = cleaned.replace("_", " ")
    return re.sub(r"\s+", " ", cleaned).strip()


@dataclass(frozen=True)
class VocabularyFood:
    name: str
    calories_kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    aliases: tuple[str, ...]
    role: str = "unknown"
    density_g_per_ml: float | None = None
    food_category: str | None = None
    default_portion_g: tuple[float, float] | None = None
    localized_names: Mapping[str, str] = field(default_factory=dict)
    flags: frozenset[str] = frozenset()
    russian_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class VocabularyProduct:
    canonical_product: str
    brand: str
    category: str
    variant: str
    aliases: tuple[str, ...]
    product_type: str | None = None
    query_expansions: tuple[str, ...] = ()
    default_serving_amount: float | None = None
    default_serving_unit: str | None = None


@dataclass(frozen=True)
class PhraseTranslation:
    phrase: str
    replacement: str
    preparation: str | None = None


@dataclass(frozen=True)
class ScopeVocabulary:
    additional_food_terms: tuple[str, ...]
    generic_intent_terms: tuple[str, ...]
    russian_food_stems: tuple[str, ...]
    packaged_terms: tuple[str, ...]


@dataclass(frozen=True)
class FoodVocabulary:
    version: int
    foods: tuple[VocabularyFood, ...]
    products: tuple[VocabularyProduct, ...]
    brand_aliases: Mapping[str, str]
    restaurant_aliases: Mapping[str, str]
    region_aliases: Mapping[str, str]
    phrase_translations: tuple[PhraseTranslation, ...]
    standard_prepared_dishes: frozenset[str]
    scope: ScopeVocabulary

    @property
    def foods_by_name(self) -> Mapping[str, VocabularyFood]:
        return MappingProxyType({food.name: food for food in self.foods})

    @property
    def fallback_names(self) -> frozenset[str]:
        names: set[str] = set()
        for food in self.foods:
            names.add(food.name)
            names.update(food.aliases)
        return frozenset(names)

    @property
    def default_portions_g(self) -> Mapping[str, tuple[float, float]]:
        return MappingProxyType(
            {
                food.name: food.default_portion_g
                for food in self.foods
                if food.default_portion_g is not None
            }
        )

    @property
    def food_roles(self) -> Mapping[str, str]:
        return MappingProxyType({food.name: food.role for food in self.foods})

    @property
    def conventional_dish_priors(self) -> frozenset[str]:
        return frozenset(
            food.name for food in self.foods if "conventional_dish_prior" in food.flags
        )

    @property
    def high_variance_foods(self) -> frozenset[str]:
        return frozenset(food.name for food in self.foods if "high_variance" in food.flags)

    @property
    def russian_food_patterns(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        return tuple(
            (food.name, food.russian_patterns) for food in self.foods if food.russian_patterns
        )

    @property
    def localized_food_names(self) -> Mapping[str, Mapping[str, str]]:
        localized: dict[str, dict[str, str]] = {}
        for food in self.foods:
            for language, display_name in food.localized_names.items():
                localized.setdefault(language, {})[food.name] = display_name
        return MappingProxyType(
            {language: MappingProxyType(names) for language, names in localized.items()}
        )


@lru_cache(maxsize=1)
def load_food_vocabulary() -> FoodVocabulary:
    raw = yaml.safe_load(
        resources.files("app.tools")
        .joinpath("food_vocabulary.yaml")
        .read_text(encoding="utf-8")
    )
    if not isinstance(raw, dict):
        raise RuntimeError("food_vocabulary.yaml must contain a mapping")
    vocabulary = _parse_vocabulary(raw)
    _validate_vocabulary(vocabulary)
    return vocabulary


def _parse_vocabulary(raw: dict[str, Any]) -> FoodVocabulary:
    foods = tuple(_parse_food(item) for item in _list(raw, "foods"))
    products = tuple(_parse_product(item) for item in _list(raw, "products"))
    translations = tuple(
        PhraseTranslation(
            phrase=_required_str(item, "phrase"),
            replacement=_required_str(item, "replacement"),
            preparation=_optional_str(item, "preparation"),
        )
        for item in _list(raw, "phrase_translations")
    )
    scope_raw = _dict(raw, "scope")
    return FoodVocabulary(
        version=int(raw.get("version") or 1),
        foods=foods,
        products=products,
        brand_aliases=MappingProxyType(_string_mapping(raw, "brand_aliases")),
        restaurant_aliases=MappingProxyType(_string_mapping(raw, "restaurant_aliases")),
        region_aliases=MappingProxyType(_string_mapping(raw, "region_aliases")),
        phrase_translations=translations,
        standard_prepared_dishes=frozenset(_string_list(raw, "standard_prepared_dishes")),
        scope=ScopeVocabulary(
            additional_food_terms=tuple(_string_list(scope_raw, "additional_food_terms")),
            generic_intent_terms=tuple(_string_list(scope_raw, "generic_intent_terms")),
            russian_food_stems=tuple(_string_list(scope_raw, "russian_food_stems")),
            packaged_terms=tuple(_string_list(scope_raw, "packaged_terms")),
        ),
    )


def _parse_food(raw: Any) -> VocabularyFood:
    if not isinstance(raw, dict):
        raise RuntimeError("food vocabulary entries must be mappings")
    nutrition = _dict(raw, "nutrition_per_100g")
    default_portion = raw.get("default_portion_g")
    if default_portion is not None:
        values = _string_or_number_list(default_portion, "default_portion_g")
        if len(values) != 2:
            raise RuntimeError(f"{raw.get('name')}: default_portion_g must contain two values")
        portion = (float(values[0]), float(values[1]))
    else:
        portion = None
    return VocabularyFood(
        name=_required_str(raw, "name"),
        calories_kcal=float(nutrition["calories_kcal"]),
        protein_g=float(nutrition["protein_g"]),
        fat_g=float(nutrition["fat_g"]),
        carbs_g=float(nutrition["carbs_g"]),
        aliases=tuple(_string_list(raw, "aliases")),
        role=_optional_str(raw, "role") or "unknown",
        density_g_per_ml=_optional_float(raw, "density_g_per_ml"),
        food_category=_optional_str(raw, "food_category"),
        default_portion_g=portion,
        localized_names=MappingProxyType(_string_mapping(raw, "localized_names")),
        flags=frozenset(_string_list(raw, "flags")),
        russian_patterns=tuple(_string_list(raw, "russian_patterns")),
    )


def _parse_product(raw: Any) -> VocabularyProduct:
    if not isinstance(raw, dict):
        raise RuntimeError("product vocabulary entries must be mappings")
    return VocabularyProduct(
        canonical_product=_required_str(raw, "canonical_product"),
        brand=_required_str(raw, "brand"),
        category=_required_str(raw, "category"),
        variant=_required_str(raw, "variant"),
        aliases=tuple(_string_list(raw, "aliases")),
        product_type=_optional_str(raw, "product_type"),
        query_expansions=tuple(_string_list(raw, "query_expansions")),
        default_serving_amount=_optional_float(raw, "default_serving_amount"),
        default_serving_unit=_optional_str(raw, "default_serving_unit"),
    )


def _validate_vocabulary(vocabulary: FoodVocabulary) -> None:
    names = [food.name for food in vocabulary.foods]
    duplicate_names = sorted({name for name in names if names.count(name) > 1})
    if duplicate_names:
        raise RuntimeError(f"duplicate canonical food names: {duplicate_names}")
    food_names = set(names)
    missing_products = [
        product.canonical_product
        for product in vocabulary.products
        if product.canonical_product not in food_names
    ]
    if missing_products:
        raise RuntimeError(f"product profiles without fallback food rows: {missing_products}")
    for food in vocabulary.foods:
        if not food.name.strip():
            raise RuntimeError("canonical food name cannot be empty")
        for alias in food.aliases:
            if not alias.strip():
                raise RuntimeError(f"{food.name}: empty alias")
        if food.default_portion_g and food.default_portion_g[0] > food.default_portion_g[1]:
            raise RuntimeError(f"{food.name}: default portion minimum exceeds maximum")
    LOGGER.debug(
        "Loaded food vocabulary version=%s foods=%s products=%s",
        vocabulary.version,
        len(vocabulary.foods),
        len(vocabulary.products),
    )


def _dict(raw: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key) or {}
    if not isinstance(value, dict):
        raise RuntimeError(f"{key} must be a mapping")
    return value


def _list(raw: Mapping[str, Any], key: str) -> list[Any]:
    value = raw.get(key) or []
    if not isinstance(value, list):
        raise RuntimeError(f"{key} must be a list")
    return value


def _required_str(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{key} must be a non-empty string")
    return value


def _optional_str(raw: Mapping[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"{key} must be a string")
    return value


def _optional_float(raw: Mapping[str, Any], key: str) -> float | None:
    value = raw.get(key)
    if value is None:
        return None
    return float(value)


def _string_mapping(raw: Mapping[str, Any], key: str) -> dict[str, str]:
    value = raw.get(key) or {}
    if not isinstance(value, dict):
        raise RuntimeError(f"{key} must be a mapping")
    return {str(item_key): str(item_value) for item_key, item_value in value.items()}


def _string_list(raw: Mapping[str, Any], key: str) -> list[str]:
    value = raw.get(key) or []
    return [str(item) for item in _string_or_number_list(value, key)]


def _string_or_number_list(value: Any, key: str) -> list[str | int | float]:
    if not isinstance(value, list):
        raise RuntimeError(f"{key} must be a list")
    if any(not isinstance(item, str | int | float) for item in value):
        raise RuntimeError(f"{key} must contain only scalar values")
    return value
