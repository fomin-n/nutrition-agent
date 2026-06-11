from app.graph.state import NutritionGraphState
from app.i18n import state_language
from app.llm.client import ModerationService, local_moderate_text
from app.schemas.outputs import FinalEstimate


def output_moderation(state: NutritionGraphState) -> NutritionGraphState:
    final = state.get("final_estimate")
    language = state_language(state)
    if final is None:
        text = (
            "Не удалось безопасно сформировать оценку питания по этому вводу."
            if language == "ru"
            else "I couldn’t generate a safe nutrition estimate from that input."
        )
        return {
            "final_estimate": FinalEstimate(
                text=text,
                confidence="low",
                is_refusal=True,
            )
        }

    if final.is_refusal:
        return {}

    if state.get("use_llm") is False:
        decision = local_moderate_text(final.text)
    else:
        decision = ModerationService().moderate_text(final.text)
    if not decision.allowed:
        text = (
            "Я могу оценивать калории и макронутриенты блюд, но не могу предоставлять "
            "небезопасный, медицинский, хакерский или связанный с извлечением инструкций контент."
            if language == "ru"
            else (
                "I can estimate meal calories and macros, but I can’t provide unsafe, "
                "medical, hacking, or prompt-extraction content."
            )
        )
        return {
            "final_estimate": FinalEstimate(
                text=text,
                confidence="high",
                is_refusal=True,
            )
        }
    return {}
