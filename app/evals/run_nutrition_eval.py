import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.evals.datasets import NutritionEvalCase, load_nutrition_cases
from app.evals.metrics import calculate_nutrition_errors, summarize_nutrition_errors
from app.graph.graph import get_compiled_graph
from app.graph.state import NutritionGraphState
from app.llm.client import get_settings
from app.schemas.inputs import UserInput
from app.schemas.nutrition import IngredientNutrition, MealUnderstanding, NutritionTotals
from app.schemas.outputs import CriticResult, FinalEstimate
from app.tools.fallback_nutrition import normalize_food_query

DEFAULT_MAX_EXAMPLES = 3
DEFAULT_OUTPUT_DIR = Path("reports/eval")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the tiny nutrition quality eval.")
    parser.add_argument("--dataset-path", type=Path, help="Optional nutrition eval JSONL dataset.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-examples", type=int, default=DEFAULT_MAX_EXAMPLES)
    parser.add_argument("--use-llm", action="store_true", help="Allow graph LLM paths.")
    parser.add_argument(
        "--allow-paid-api",
        action="store_true",
        help="Required together with --use-llm before any OpenAI-backed graph calls are allowed.",
    )
    parser.add_argument(
        "--allow-more-examples",
        action="store_true",
        help="Required to process more than the default 3 examples.",
    )
    args = parser.parse_args(argv)

    try:
        validate_eval_options(
            max_examples=args.max_examples,
            use_llm=args.use_llm,
            allow_paid_api=args.allow_paid_api,
            allow_more_examples=args.allow_more_examples,
        )
    except ValueError as exc:
        parser.error(str(exc))

    cases = load_nutrition_cases(args.dataset_path)
    run_output = run_nutrition_eval(cases=cases[: args.max_examples], use_llm=args.use_llm)
    json_path, markdown_path = write_results(run_output, output_dir=args.output_dir)

    print(
        json.dumps(
            {
                "summary": run_output["summary"],
                "json_path": str(json_path),
                "markdown_path": str(markdown_path),
            },
            indent=2,
        )
    )
    return 0


def validate_eval_options(
    *,
    max_examples: int,
    use_llm: bool,
    allow_paid_api: bool,
    allow_more_examples: bool,
) -> None:
    if max_examples < 1:
        raise ValueError("--max-examples must be at least 1")
    if max_examples > DEFAULT_MAX_EXAMPLES and not allow_more_examples:
        raise ValueError(
            f"--max-examples is capped at {DEFAULT_MAX_EXAMPLES}; pass --allow-more-examples to override"
        )
    if use_llm and not allow_paid_api:
        raise ValueError("--use-llm requires --allow-paid-api")


def run_nutrition_eval(*, cases: Sequence[NutritionEvalCase], use_llm: bool) -> dict[str, Any]:
    timestamp = datetime.now(UTC).replace(microsecond=0).isoformat()
    example_results = run_eval_cases(cases=cases, use_llm=use_llm)
    nutrition_metrics = [item["metrics"] for item in example_results]
    summary = summarize_nutrition_errors(nutrition_metrics)
    summary["mean_expected_ingredient_recall"] = _mean_expected_ingredient_recall(example_results)

    return {
        "run_id": f"nutrition_eval_{_timestamp_for_filename(timestamp)}",
        "timestamp_utc": timestamp,
        "config": _safe_config(use_llm=use_llm, max_examples=len(cases)),
        "summary": summary,
        "examples": example_results,
        "limitations": [
            "OpenIntro fastfood rows describe full menu items, while the default no-LLM parser may map them to generic ingredients and assumed portions.",
            "Portion estimation is recorded for debugging but not scored because the source dataset does not include serving weight.",
            "This tiny 3-example run is a smoke eval for reproducibility, not a statistically meaningful benchmark.",
        ],
    }


def run_eval_cases(*, cases: Sequence[NutritionEvalCase], use_llm: bool) -> list[dict[str, Any]]:
    graph = get_compiled_graph()
    results: list[dict[str, Any]] = []
    for case in cases:
        state = graph.invoke(
            {
                "user_input": UserInput(text=case.input_text, source="test"),
                "use_llm": use_llm,
            }
        )
        results.append(_example_result(case=case, state=state))
    return results


def write_results(run_output: dict[str, Any], *, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = str(run_output["run_id"])
    json_path = output_dir / f"{run_id}.json"
    markdown_path = output_dir / f"{run_id}.md"
    json_path.write_text(json.dumps(run_output, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(_render_markdown_summary(run_output), encoding="utf-8")
    return json_path, markdown_path


def _example_result(*, case: NutritionEvalCase, state: NutritionGraphState) -> dict[str, Any]:
    meal = state.get("meal")
    ingredient_nutrition = state.get("ingredient_nutrition", [])
    totals = state.get("totals")
    final = state.get("final_estimate")
    scope = state.get("scope_decision")
    critic = state.get("critic_result")

    metrics = calculate_nutrition_errors(case.ground_truth.model_dump(), _prediction_ranges(totals))
    parsed_ingredients = _serialize_meal(meal)
    lookup_rows = [_serialize_ingredient_nutrition(item) for item in ingredient_nutrition]

    return {
        "id": case.id,
        "input": case.input_text,
        "source": case.source.model_dump(),
        "ground_truth": case.ground_truth.model_dump(),
        "model_output": _serialize_final(final),
        "parsed_prediction": _serialize_totals(totals),
        "metrics": metrics,
        "components": {
            "scope_route": scope.route if scope else None,
            "extraction": _extraction_result(
                expected_ingredients=case.expected_ingredients,
                parsed_ingredients=parsed_ingredients,
            ),
            "portion_estimation": {
                "scored": False,
                "reason": "OpenIntro fastfood does not include serving weights.",
                "items": [
                    {
                        "name": item["name"],
                        "grams_min": item["grams_min"],
                        "grams_max": item["grams_max"],
                        "notes": item["notes"],
                    }
                    for item in parsed_ingredients
                ],
            },
            "nutrition_lookup": lookup_rows,
            "aggregation": _serialize_totals(totals),
            "critic": _serialize_critic(critic),
        },
    }


def _prediction_ranges(totals: NutritionTotals | None) -> dict[str, tuple[float | None, float | None]]:
    if totals is None:
        return {}
    return {
        "calories_kcal": (totals.calories_kcal.min, totals.calories_kcal.max),
        "protein_g": (totals.protein_g.min, totals.protein_g.max),
        "fat_g": (totals.fat_g.min, totals.fat_g.max),
        "carbs_g": (totals.carbs_g.min, totals.carbs_g.max),
    }


def _serialize_meal(meal: MealUnderstanding | None) -> list[dict[str, Any]]:
    if meal is None:
        return []
    return [ingredient.model_dump(mode="json") for ingredient in meal.ingredients]


def _serialize_ingredient_nutrition(item: IngredientNutrition) -> dict[str, Any]:
    dumped = item.model_dump(mode="json")
    candidate = dumped.get("candidate")
    if isinstance(candidate, dict):
        dumped["candidate"] = {
            "source": candidate.get("source"),
            "source_id": candidate.get("source_id"),
            "name": candidate.get("name"),
            "brand": candidate.get("brand"),
            "food_type": candidate.get("food_type"),
            "match_score": candidate.get("match_score"),
            "score_components": candidate.get("score_components"),
            "metadata": candidate.get("metadata"),
        }
    if dumped.get("source") == "fatsecret":
        dumped["per_100g"] = {
            "food_name": dumped.get("matched_food_name"),
            "source": "fatsecret",
            "source_id": dumped.get("per_100g", {}).get("source_id"),
            "redacted": "FatSecret nutrition values are not persisted in eval reports.",
        }
    return dumped


def _serialize_totals(totals: NutritionTotals | None) -> dict[str, Any] | None:
    return totals.model_dump(mode="json") if totals else None


def _serialize_final(final: FinalEstimate | None) -> dict[str, Any] | None:
    if final is None:
        return None
    dumped = final.model_dump(mode="json")
    dumped.pop("totals", None)
    return dumped


def _serialize_critic(critic: CriticResult | None) -> dict[str, Any] | None:
    return critic.model_dump(mode="json") if critic else None


def _extraction_result(
    *,
    expected_ingredients: list[str],
    parsed_ingredients: list[dict[str, Any]],
) -> dict[str, Any]:
    parsed_names = [str(item["name"]) for item in parsed_ingredients]
    matched = [
        expected
        for expected in expected_ingredients
        if any(_names_match(expected, parsed) for parsed in parsed_names)
    ]
    recall = len(matched) / len(expected_ingredients) if expected_ingredients else None
    return {
        "expected_ingredients": expected_ingredients,
        "parsed_ingredient_names": parsed_names,
        "matched_expected_ingredients": matched,
        "expected_ingredient_recall": recall,
    }


def _names_match(expected: str, parsed: str) -> bool:
    normalized_expected = normalize_food_query(expected)
    normalized_parsed = normalize_food_query(parsed)
    return normalized_expected in normalized_parsed or normalized_parsed in normalized_expected


def _mean_expected_ingredient_recall(example_results: list[dict[str, Any]]) -> float | None:
    values = [
        recall
        for item in example_results
        if isinstance(
            recall := item["components"]["extraction"]["expected_ingredient_recall"],
            int | float,
        )
    ]
    return sum(values) / len(values) if values else None


def _safe_config(*, use_llm: bool, max_examples: int) -> dict[str, Any]:
    settings = get_settings()
    return {
        "max_examples": max_examples,
        "use_llm": use_llm,
        "paid_api_allowed": use_llm,
        "openai_text_model": settings.openai_text_model,
        "openai_vision_model": settings.openai_vision_model,
        "openai_critic_model": settings.openai_critic_model,
        "openai_api_key_configured": bool(settings.openai_api_key),
        "usda_api_key_configured": bool(settings.usda_api_key),
    }


def _timestamp_for_filename(timestamp: str) -> str:
    return timestamp.replace("+00:00", "Z").replace(":", "").replace("-", "")


def _render_markdown_summary(run_output: dict[str, Any]) -> str:
    summary = run_output["summary"]
    lines = [
        "# Tiny Nutrition Eval",
        "",
        f"- Run ID: `{run_output['run_id']}`",
        f"- Timestamp UTC: `{run_output['timestamp_utc']}`",
        f"- Examples: {summary['total_examples']}",
        f"- Mean absolute calorie error: {_format_optional(summary['mean_absolute_calorie_error'])} kcal",
        f"- Mean absolute calorie percentage error: {_format_optional(summary['mean_absolute_calorie_percentage_error'])}%",
        f"- Calorie within-range rate: {_format_optional(summary['calorie_within_range_rate'])}",
        f"- Mean expected ingredient recall: {_format_optional(summary['mean_expected_ingredient_recall'])}",
        "",
        "## Examples",
        "",
    ]
    for example in run_output["examples"]:
        calorie_metrics = example["metrics"]["calories_kcal"]
        lines.extend(
            [
                f"### {example['id']}",
                "",
                f"- Input: {example['input']}",
                f"- Source item: {example['source']['restaurant']} - {example['source']['item']}",
                f"- Ground-truth calories: {calorie_metrics['actual']}",
                f"- Predicted calories: {calorie_metrics['predicted_min']}-{calorie_metrics['predicted_max']}",
                f"- Absolute calorie error: {_format_optional(calorie_metrics['absolute_error'])}",
                "",
            ]
        )
    lines.extend(["## Limitations", ""])
    lines.extend(f"- {item}" for item in run_output["limitations"])
    return "\n".join(lines) + "\n"


def _format_optional(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
