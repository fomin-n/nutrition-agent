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
    density_g_per_ml: float | None = None
    food_category: str | None = None

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
    FallbackFood("avocado", 160, 2.0, 14.7, 8.5, ("avocado", "авокадо")),
    FallbackFood("almonds", 579, 21.2, 49.9, 21.6, ("almond", "almonds", "миндаль", "миндаля")),
    FallbackFood("tofu firm", 120, 14.0, 7.0, 2.5, ("tofu", "firm tofu", "тофу", "твердого тофу")),
    FallbackFood(
        "lentils cooked",
        116,
        9.0,
        0.4,
        20.1,
        ("lentils", "cooked lentils", "lentil", "чечевица", "чечевицы"),
    ),
    FallbackFood(
        "chickpeas cooked",
        164,
        8.9,
        2.6,
        27.4,
        ("chickpeas", "cooked chickpeas", "chickpea", "нут", "нута"),
    ),
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
    FallbackFood("yogurt plain", 61, 3.5, 3.3, 4.7, ("yogurt", "plain yogurt", "yoghurt", "йогурт")),
    FallbackFood(
        "Greek yogurt 2%",
        73,
        9.9,
        2.0,
        3.9,
        (
            "greek yogurt",
            "greek yogurt 2%",
            "греческий йогурт",
            "греческого йогурта",
            "греческом йогурте",
        ),
    ),
    FallbackFood(
        "skyr plain",
        63,
        11.0,
        0.2,
        4.0,
        ("skyr", "plain skyr", "natural skyr", "скир", "скира", "скыр"),
    ),
    FallbackFood(
        "cottage cheese",
        121,
        17.0,
        5.0,
        3.0,
        ("cottage cheese", "cottage cheese 5%", "творог", "творога", "твороге"),
    ),
    FallbackFood(
        "milk",
        61,
        3.2,
        3.3,
        4.8,
        ("milk", "whole milk", "молоко", "молока"),
        density_g_per_ml=1.0,
    ),
    FallbackFood(
        "water",
        0,
        0.0,
        0.0,
        0.0,
        (
            "water",
            "plain water",
            "drinking water",
            "tap water",
            "still water",
            "sparkling water",
            "вода",
            "воды",
            "воде",
            "воду",
            "водой",
            "обычная вода",
            "обычной воде",
            "обычной воды",
            "питьевая вода",
            "питьевой воды",
            "минеральная вода",
            "газированная вода",
        ),
        density_g_per_ml=1.0,
        food_category="plain_water",
    ),
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
        "dry oats",
        389,
        16.9,
        6.9,
        66.3,
        ("dry oats", "rolled oats dry", "сухие овсяные хлопья", "овсяных хлопьев"),
    ),
    FallbackFood(
        "butter croissant",
        406,
        8.2,
        21.0,
        45.8,
        ("butter croissant", "croissant", "круассан", "круассана"),
    ),
    FallbackFood(
        "pain au chocolat",
        414,
        7.5,
        22.0,
        45.0,
        ("pain au chocolat", "chocolate croissant", "шоколадный круассан"),
    ),
    FallbackFood("baguette", 274, 8.8, 1.0, 57.5, ("baguette", "багет", "багета")),
    FallbackFood(
        "potato chips",
        536,
        7.0,
        35.0,
        53.0,
        (
            "potato chips",
            "chips",
            "картофельные чипсы",
            "картофельных чипсов",
            "картофельными чипсами",
            "чипсы",
            "чипсов",
        ),
    ),
    FallbackFood(
        "Nutella",
        539,
        6.3,
        30.9,
        57.5,
        ("nutella", "нутелла", "нутеллы", "нутелле"),
    ),
    FallbackFood(
        "peanut butter",
        588,
        25.0,
        50.0,
        20.0,
        ("peanut butter", "арахисовая паста", "арахисовой пасты"),
    ),
    FallbackFood(
        "protein bar",
        380,
        33.0,
        12.0,
        38.0,
        ("protein bar", "протеиновый батончик", "протеиновом батончике"),
    ),
    FallbackFood(
        "instant noodles dry",
        470,
        10.0,
        20.0,
        62.0,
        (
            "instant noodles",
            "instant noodle pack",
            "лапша быстрого приготовления",
            "лапши быстрого приготовления",
        ),
    ),
    FallbackFood(
        "vanilla ice cream",
        207,
        3.5,
        11.0,
        23.6,
        ("vanilla ice cream", "ice cream", "ванильное мороженое", "мороженое"),
    ),
    FallbackFood(
        "tuna canned in water",
        116,
        25.5,
        0.8,
        0.0,
        ("canned tuna in water", "tuna in water", "canned tuna", "тунец в собственном соку"),
    ),
    FallbackFood(
        "dark chocolate",
        598,
        7.8,
        42.6,
        45.9,
        ("dark chocolate", "темный шоколад", "темного шоколада", "тёмный шоколад", "тёмного шоколада"),
    ),
    FallbackFood(
        "mozzarella",
        280,
        28.0,
        17.0,
        3.1,
        ("mozzarella", "mozzarella ball", "моцарелла", "моцареллы", "моцареллой"),
    ),
    FallbackFood("hummus", 166, 7.9, 9.6, 14.3, ("hummus", "хумус", "хумуса", "хумусе")),
    FallbackFood("granola", 471, 10.0, 20.0, 64.0, ("granola", "гранола", "гранолы")),
    FallbackFood(
        "Snickers",
        500,
        8.0,
        24.0,
        62.0,
        (
            "snickers",
            "snickers bar",
            "сникерс",
            "сникерса",
            "сникерсе",
            "сникерсом",
            "сникерсу",
        ),
    ),
    FallbackFood(
        "Twix",
        495,
        5.0,
        24.0,
        65.0,
        ("twix", "twix bar", "твикс", "твикса", "твиксе", "твиксом", "твиксу"),
    ),
    FallbackFood(
        "Bounty",
        488,
        4.0,
        26.0,
        59.0,
        ("bounty", "bounty bar", "баунти"),
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
        density_g_per_ml=1.0,
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
        density_g_per_ml=1.0,
    ),
    # Extra broad MVP fallbacks for common free-text meals.
    FallbackFood("pizza", 266, 11.0, 10.0, 33.0, ("pizza", "slice pizza", "pizza slice", "пицца", "пиццы")),
    FallbackFood(
        "hamburger",
        254,
        12.0,
        10.0,
        28.0,
        ("burger", "hamburger", "cheeseburger", "бургер", "гамбургер", "чизбургер"),
    ),
    FallbackFood("vegetable soup", 45, 2.0, 1.5, 6.5, ("soup", "vegetable soup", "суп", "овощной суп")),
    FallbackFood(
        "French fries",
        312,
        3.4,
        15.0,
        41.0,
        ("french fries", "fries", "картошка фри", "картошке фри", "картофель фри"),
    ),
    FallbackFood(
        "McDonald's Big Mac",
        257,
        12.0,
        15.0,
        20.0,
        ("big mac", "mcdonalds big mac", "биг мак", "биг мака"),
    ),
    FallbackFood(
        "Greek salad",
        120,
        3.5,
        9.0,
        7.0,
        ("greek salad", "греческий салат", "греческого салата"),
    ),
    FallbackFood(
        "chicken Caesar salad",
        180,
        13.0,
        11.0,
        9.0,
        (
            "chicken caesar salad",
            "caesar salad with chicken",
            "салат цезарь с курицей",
            "салате цезарь с курицей",
        ),
    ),
    FallbackFood(
        "pasta carbonara",
        220,
        9.0,
        11.0,
        24.0,
        ("pasta carbonara", "carbonara", "паста карбонара", "пасте карбонара"),
    ),
    FallbackFood(
        "borscht with sour cream",
        70,
        3.0,
        3.5,
        7.0,
        (
            "borscht with sour cream",
            "borsch with sour cream",
            "борщ со сметаной",
            "борща со сметаной",
            "борще со сметаной",
        ),
    ),
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
