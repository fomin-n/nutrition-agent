import re
from dataclasses import dataclass

from app.schemas.nutrition import NutritionPer100g


@dataclass(frozen=True)
class FallbackFood:
    name: str
    calories_kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    aliases: tuple[str, ...]

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


FALLBACK_FOODS: tuple[FallbackFood, ...] = (
    FallbackFood(
        "cooked white rice",
        130,
        2.7,
        0.3,
        28.2,
        ("rice", "white rice", "cooked rice", "рис", "риса", "рисом"),
    ),
    FallbackFood(
        "cooked pasta",
        158,
        5.8,
        0.9,
        30.9,
        ("pasta", "spaghetti", "noodles", "паста", "пасты", "пастой", "макароны", "макарон"),
    ),
    FallbackFood("cooked buckwheat", 92, 3.4, 0.6, 19.9, ("buckwheat", "kasha", "гречка", "гречки")),
    FallbackFood(
        "chicken breast cooked",
        165,
        31.0,
        3.6,
        0.0,
        ("chicken", "chicken breast", "курица", "курицы", "курицей", "куриная грудка"),
    ),
    FallbackFood("beef cooked", 250, 26.0, 15.0, 0.0, ("beef", "steak", "ground beef", "говядина", "стейк")),
    FallbackFood("salmon cooked", 206, 22.0, 12.0, 0.0, ("salmon", "cooked salmon", "лосось", "семга")),
    FallbackFood("egg", 143, 12.6, 9.5, 0.7, ("egg", "eggs", "omelet", "omelette", "яйцо", "яйца", "яиц", "омлет", "омлете")),
    FallbackFood("olive oil", 884, 0.0, 100.0, 0.0, ("olive oil", "oil", "оливковое масло", "масло")),
    FallbackFood("butter", 717, 0.9, 81.1, 0.1, ("butter", "сливочное масло")),
    FallbackFood("potato boiled", 87, 1.9, 0.1, 20.1, ("potato", "boiled potato", "potatoes", "картофель", "картошка")),
    FallbackFood("bread", 265, 9.0, 3.2, 49.0, ("bread", "toast", "slice of bread", "sourdough", "хлеб", "тост")),
    FallbackFood("banana", 89, 1.1, 0.3, 22.8, ("banana", "bananas", "банан", "банана")),
    FallbackFood(
        "apple",
        52,
        0.3,
        0.2,
        13.8,
        (
            "apple",
            "apples",
            "green apple",
            "яблоко",
            "яблока",
            "яблоке",
            "яблоком",
            "яблоку",
            "яблоки",
            "зеленое яблоко",
            "зеленом яблоке",
            "зеленого яблока",
            "зелёное яблоко",
            "зелёном яблоке",
            "зелёного яблока",
        ),
    ),
    FallbackFood("tomato", 18, 0.9, 0.2, 3.9, ("tomato", "tomatoes", "помидор", "томат", "помидоры")),
    FallbackFood("cucumber", 15, 0.7, 0.1, 3.6, ("cucumber", "cucumbers", "огурец", "огурцы")),
    FallbackFood(
        "mixed salad vegetables",
        20,
        1.2,
        0.2,
        4.0,
        (
            "mixed salad vegetables",
            "salad vegetables",
            "lettuce",
            "green salad",
            "mixed salad",
            "salad",
            "салат",
            "салата",
            "зеленый салат",
            "зелёный салат",
        ),
    ),
    FallbackFood("cheese", 402, 25.0, 33.0, 1.3, ("cheese", "cheddar", "hard cheese", "сыр", "сыра", "сыром")),
    FallbackFood("yogurt plain", 61, 3.5, 3.3, 4.7, ("yogurt", "plain yogurt", " yoghurt", "йогурт")),
    FallbackFood("milk", 61, 3.2, 3.3, 4.8, ("milk", "whole milk", "молоко", "молока")),
    FallbackFood(
        "oatmeal cooked",
        71,
        2.5,
        1.5,
        12.0,
        (
            "oatmeal",
            "porridge",
            "cooked oats",
            "oats",
            "овсянка",
            "овсянки",
            "овсянкой",
            "каша",
            "каши",
            "кашу",
            "кашей",
            "овсяная каша",
            "овсяной каши",
            "овсяную кашу",
            "овсяной кашей",
        ),
    ),
    FallbackFood(
        "Coca-Cola",
        42,
        0.0,
        0.0,
        10.6,
        (
            "regular cola soft drink",
            "regular cola",
            "coca cola",
            "coca-cola",
            "cocacola",
            "coke",
            "cola",
            "кока кола",
            "кока-кола",
            "кока колы",
            "кока-колы",
            "кола",
            "колы",
            "коле",
            "колу",
        ),
    ),
    FallbackFood(
        "Coca-Cola Zero Sugar",
        0.2,
        0.0,
        0.0,
        0.0,
        (
            "coca cola zero sugar",
            "coca-cola zero sugar",
            "coke zero",
            "cola zero",
            "diet cola",
            "coca cola light",
            "coca-cola light",
            "coke light",
            "cola light",
            "кока кола зеро",
            "кока-кола зеро",
            "кола зеро",
            "кола без сахара",
            "кока кола лайт",
            "кока-кола лайт",
            "кола лайт",
        ),
    ),
    # Extra broad MVP fallbacks for common free-text meals.
    FallbackFood("pizza", 266, 11.0, 10.0, 33.0, ("pizza", "slice pizza", "pizza slice", "пицца", "пиццы")),
    FallbackFood("hamburger", 254, 12.0, 10.0, 28.0, ("burger", "hamburger", "бургер", "гамбургер")),
    FallbackFood("vegetable soup", 45, 2.0, 1.5, 6.5, ("soup", "vegetable soup", "суп", "овощной суп")),
)


def normalize_food_query(query: str) -> str:
    cleaned = query.lower().replace("ё", "е")
    cleaned = re.sub(r"[^\w\s]", " ", cleaned, flags=re.UNICODE)
    cleaned = cleaned.replace("_", " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def fallback_names() -> set[str]:
    names: set[str] = set()
    for food in FALLBACK_FOODS:
        names.add(food.name)
        names.update(food.aliases)
    return names


def lookup_fallback_food(query: str) -> NutritionPer100g | None:
    normalized = normalize_food_query(query)
    if not normalized:
        return None

    best: FallbackFood | None = None
    best_alias_len = 0
    for food in FALLBACK_FOODS:
        aliases = (food.name, *food.aliases)
        for alias in aliases:
            normalized_alias = normalize_food_query(alias)
            if normalized == normalized_alias:
                return food.as_nutrition()
            if (
                re.search(rf"\b{re.escape(normalized_alias)}\b", normalized)
                and len(normalized_alias) > best_alias_len
            ):
                best = food
                best_alias_len = len(normalized_alias)
    return best.as_nutrition() if best else None
