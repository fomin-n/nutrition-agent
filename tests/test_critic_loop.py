import logging
from types import SimpleNamespace

import pytest

from app.graph import graph as graph_module
from app.graph.nodes import critic as critic_module
from app.graph.nodes import nutrition_retriever
from app.graph.nodes.synthesizer import synthesize_answer
from app.schemas.inputs import NormalizedInput, UserInput
from app.schemas.nutrition import (
    IngredientEstimate,
    MacroRange,
    MealUnderstanding,
    NutritionTotals,
)
from app.schemas.outputs import CriticResult, FinalEstimate
from app.tools.nutrition_tools import NutritionSourceRouter


def test_revise_route_and_iteration_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        critic_module,
        "get_settings",
        lambda: SimpleNamespace(critic_max_iterations=1),
    )
    state = {
        "critic_result": CriticResult(action="revise", issues=["fix formatting"]),
        "critic_iteration": 0,
    }

    assert critic_module.route_after_critic(state) == "revise"
    prepared = critic_module.prepare_critic_revision(state)
    assert prepared["critic_iteration"] == 1
    assert prepared["critic_feedback"] == ["fix formatting"]
    assert len(prepared["critic_history"]) == 1
    assert critic_module.route_after_critic({**state, **prepared}) == "critic_cap"


def test_deterministic_revision_restores_calculator_totals() -> None:
    state = _estimate_state(
        text="Estimated calories: 999 kcal\nProtein: unknown",
        use_llm=False,
    )

    first = critic_module.critic(state)["critic_result"]
    assert first.action == "revise"
    assert any("deterministic totals" in issue for issue in first.issues)

    prepared = critic_module.prepare_critic_revision({**state, "critic_result": first})
    revised_state = {**state, **prepared}
    revised_state.update(synthesize_answer(revised_state))
    second = critic_module.critic(revised_state)["critic_result"]

    assert revised_state["final_estimate"].text.startswith("🔥 Calories: 100–120 kcal")
    assert "999" not in revised_state["final_estimate"].text
    assert second.action == "accept"


def test_inverted_deterministic_range_is_rejected() -> None:
    state = _estimate_state(use_llm=False)
    state["totals"] = state["totals"].model_copy(
        update={"protein_g": MacroRange.model_construct(min=12, max=10)}
    )

    result = critic_module.critic(state)["critic_result"]

    assert result.action == "revise"
    assert "protein range is inverted" in result.issues


def test_llm_critic_uses_configured_model_and_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(critic_module, "has_openai_key", lambda: True)
    monkeypatch.setattr(
        critic_module,
        "get_settings",
        lambda: SimpleNamespace(
            openai_critic_model="critic-test-model",
            critic_max_iterations=2,
        ),
    )

    def invoke(**kwargs):
        captured.update(kwargs)
        return CriticResult(action="revise", issues=["wording is unclear"])

    monkeypatch.setattr(critic_module, "invoke_structured_text", invoke)

    result = critic_module.critic(_estimate_state(use_llm=True))["critic_result"]

    assert result.action == "revise"
    assert result.source == "llm"
    assert result.iteration == 0
    assert captured["model_name"] == "critic-test-model"
    assert captured["schema"] is CriticResult
    assert "Nutrition Answer Critic" in str(captured["system_prompt"])
    assert "deterministic_totals" in str(captured["user_prompt"])


def test_llm_critic_error_degrades_to_deterministic_accept(
    monkeypatch: pytest.MonkeyPatch,
    caplog,
) -> None:
    monkeypatch.setattr(critic_module, "has_openai_key", lambda: True)
    monkeypatch.setattr(
        critic_module,
        "get_settings",
        lambda: SimpleNamespace(
            openai_critic_model="critic-test-model",
            critic_max_iterations=2,
        ),
    )
    monkeypatch.setattr(
        critic_module,
        "invoke_structured_text",
        lambda **_kwargs: (_ for _ in ()).throw(TimeoutError("critic timeout")),
    )

    state = _estimate_state(use_llm=True)
    state["request_id"] = "request-critic"

    with caplog.at_level(logging.WARNING):
        result = critic_module.critic(state)["critic_result"]

    assert result.action == "accept"
    assert result.source == "deterministic"
    assert "request-critic" in caplog.text


def test_graph_always_rejected_answer_stops_at_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        critic_module,
        "get_settings",
        lambda: SimpleNamespace(critic_max_iterations=2),
    )
    monkeypatch.setattr(
        critic_module,
        "_deterministic_critic",
        lambda _state: CriticResult(action="revise", issues=["forced rejection"]),
    )
    monkeypatch.setattr(
        nutrition_retriever,
        "get_default_router",
        lambda: NutritionSourceRouter(usda=None, fatsecret=None, open_food_facts=None),
    )

    state = graph_module.build_graph().invoke(
        {
            "user_input": UserInput(text="How many calories are in a banana?", source="test"),
            "use_llm": False,
        }
    )

    assert state["critic_iteration"] == 2
    assert len(state["critic_history"]) == 3
    assert state["critic_result"].action == "clarify"
    assert state["final_estimate"].is_clarification is True
    assert state["final_estimate"].text.startswith("I need one more detail")
    assert "🔥 Calories:" not in state["final_estimate"].text


def test_critic_iteration_setting_is_bounded() -> None:
    from app.llm.client import Settings

    assert Settings(critic_max_iterations=0).critic_max_iterations == 0
    assert Settings(critic_max_iterations=3).critic_max_iterations == 3
    with pytest.raises(ValueError):
        Settings(critic_max_iterations=4)


def _estimate_state(
    *,
    text: str | None = None,
    use_llm: bool = False,
) -> dict:
    totals = NutritionTotals(
        calories_kcal=MacroRange(min=100, max=120),
        protein_g=MacroRange(min=10, max=12),
        fat_g=MacroRange(min=3, max=4),
        carbs_g=MacroRange(min=15, max=20),
    )
    answer = text or (
        "🔥 Calories: 100–120 kcal\n\n"
        "Protein: 10–12 g\n"
        "Fat: 3–4 g\n"
        "Carbs: 15–20 g\n\n"
        "📋 Assumptions:\n"
        "• Standard portion.\n\n"
        "🟢 Confidence: High"
    )
    return {
        "normalized_input": NormalizedInput(
            text="100 g test food",
            has_text=True,
            has_image=False,
            language="en",
        ),
        "meal": MealUnderstanding(
            ingredients=[IngredientEstimate(name="test food", grams_min=100, grams_max=100)],
            assumptions=["Standard portion."],
            confidence="high",
        ),
        "totals": totals,
        "final_estimate": FinalEstimate(text=answer, confidence="high", totals=totals),
        "use_llm": use_llm,
    }
