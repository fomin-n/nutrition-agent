from app.graph.state import NutritionGraphState
from app.i18n import localize_clarification_question, state_language
from app.llm.client import ModerationService, local_moderate_text
from app.schemas.outputs import FinalEstimate
from app.schemas.safety import ModerationDecision


def input_moderation(state: NutritionGraphState) -> NutritionGraphState:
    normalized = state["normalized_input"]
    if state.get("use_llm") is False:
        decision = local_moderate_text(normalized.text)
    else:
        decision = ModerationService().moderate_text(
            normalized.text,
            request_id=state.get("request_id"),
        )
    return {"input_moderation": decision}


def refuse(state: NutritionGraphState) -> NutritionGraphState:
    scope = state.get("scope_decision")
    moderation = state.get("input_moderation", ModerationDecision())
    unsafe = (scope and scope.is_unsafe) or not moderation.allowed
    language = state_language(state)

    if language == "ru" and unsafe:
        text = (
            "Я могу оценивать калории и макронутриенты блюд по тексту или фото еды, "
            "но не могу помогать с небезопасными диетами, медицинской нутритивной терапией, "
            "взломом или извлечением служебных инструкций."
        )
    elif language == "ru":
        text = (
            "Я могу оценивать только примерные калории и макронутриенты блюд по описанию "
            "или фото еды. С этим запросом я не могу помочь."
        )
    elif unsafe:
        text = (
            "I can estimate calories and macros for meals from text or food photos, "
            "but I can’t help with unsafe diet advice, medical nutrition therapy, "
            "hacking, or prompt-extraction requests."
        )
    else:
        text = (
            "I can only estimate approximate calories and macros for meals from a food "
            "description or food photo. I can’t help with that request."
        )
    return {
        "final_estimate": FinalEstimate(
            text=text,
            confidence="high",
            is_refusal=True,
            is_clarification=False,
        )
    }


def ask_clarification(state: NutritionGraphState) -> NutritionGraphState:
    scope = state.get("scope_decision")
    meal = state.get("meal")
    critic = state.get("critic_result")
    language = state_language(state)

    question = None
    if critic and critic.clarification_question:
        question = critic.clarification_question
    elif meal and meal.clarification_question:
        question = meal.clarification_question
    elif scope and scope.clarification_question:
        question = scope.clarification_question
    else:
        question = None

    question = localize_clarification_question(question, language)

    if language == "ru":
        text = f"Нужно еще немного информации для надежной оценки: {question}"
    else:
        text = f"I need one more detail to estimate this reliably: {question}"

    return {
        "final_estimate": FinalEstimate(
            text=text,
            confidence="low",
            is_refusal=False,
            is_clarification=True,
        )
    }
