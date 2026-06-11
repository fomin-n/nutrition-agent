import re
from typing import Any, Literal

LanguageCode = Literal["en", "ru", "unknown"]


def detect_language(text: str | None, *, has_image: bool = False) -> LanguageCode:
    if text and re.search(r"[а-яА-ЯёЁ]", text):
        return "ru"
    if text and text.strip():
        return "en"
    return "en" if has_image else "unknown"


def response_language(language: str | None) -> Literal["en", "ru"]:
    return "ru" if language == "ru" else "en"


def state_language(state: dict[str, Any]) -> Literal["en", "ru"]:
    normalized = state.get("normalized_input")
    if normalized is not None and getattr(normalized, "language", None):
        return response_language(normalized.language)

    scope = state.get("scope_decision")
    if scope is not None and getattr(scope, "language", None):
        return response_language(scope.language)

    return "en"


def default_clarification_question(language: str | None) -> str:
    if response_language(language) == "ru":
        return "Какие продукты были в блюде и примерно сколько каждого?"
    return "What foods are in the meal and roughly how much of each?"


def no_input_question(language: str | None) -> str:
    if response_language(language) == "ru":
        return "Пришлите описание блюда или одну фотографию еды."
    return "Please send a meal description or one food photo."


def visible_food_question(language: str | None) -> str:
    if response_language(language) == "ru":
        return "Какие продукты видны на фото и примерно сколько их?"
    return "What foods are visible in the photo and roughly how much is there?"


def largest_portions_question(language: str | None) -> str:
    if response_language(language) == "ru":
        return "Можете указать примерный размер порций для самых крупных ингредиентов?"
    return "Can you share approximate portion sizes for the largest items?"


def localize_clarification_question(question: str | None, language: str | None) -> str:
    language = response_language(language)
    if language == "en":
        return question or default_clarification_question(language)

    if not question:
        return default_clarification_question(language)

    known = {
        "Please send a meal description or one food photo.": no_input_question("ru"),
        "What foods are in the meal and roughly how much of each?": default_clarification_question("ru"),
        "What food did you eat and roughly how much?": default_clarification_question("ru"),
        "What foods are visible in the photo and roughly how much is there?": visible_food_question("ru"),
        "Can you share approximate portion sizes for the largest items?": largest_portions_question("ru"),
    }
    if question in known:
        return known[question]
    if re.search(r"[а-яА-ЯёЁ]", question):
        return question
    return default_clarification_question(language)
