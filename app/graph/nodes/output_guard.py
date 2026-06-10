from app.graph.state import NutritionGraphState
from app.llm.client import ModerationService, local_moderate_text
from app.schemas.outputs import FinalEstimate


def output_moderation(state: NutritionGraphState) -> NutritionGraphState:
    final = state.get("final_estimate")
    if final is None:
        return {
            "final_estimate": FinalEstimate(
                text="I couldn’t generate a safe nutrition estimate from that input.",
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
        return {
            "final_estimate": FinalEstimate(
                text=(
                    "I can estimate meal calories and macros, but I can’t provide unsafe, "
                    "medical, hacking, or prompt-extraction content."
                ),
                confidence="high",
                is_refusal=True,
            )
        }
    return {}
