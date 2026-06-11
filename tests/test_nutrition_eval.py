import pytest

from app.evals.datasets import load_nutrition_cases
from app.evals.metrics import calculate_nutrition_errors, summarize_nutrition_errors
from app.evals.run_nutrition_eval import run_eval_cases, validate_eval_options


def test_load_nutrition_sample() -> None:
    cases = load_nutrition_cases()

    assert len(cases) == 3
    assert cases[0].source.dataset == "OpenIntro fastfood"
    assert cases[0].ground_truth.calories_kcal > 0
    assert cases[0].ground_truth.protein_g is not None
    assert cases[0].expected_ingredients


def test_nutrition_metric_calculation() -> None:
    metrics = calculate_nutrition_errors(
        ground_truth={
            "calories_kcal": 100,
            "protein_g": 10,
            "fat_g": 5,
            "carbs_g": 20,
        },
        prediction_ranges={
            "calories_kcal": (80, 120),
            "protein_g": (8, 14),
            "fat_g": (3, 7),
            "carbs_g": (10, 20),
        },
    )
    summary = summarize_nutrition_errors([metrics])

    assert metrics["calories_kcal"]["predicted_midpoint"] == 100
    assert metrics["calories_kcal"]["absolute_error"] == 0
    assert metrics["calories_kcal"]["percentage_error"] == 0
    assert metrics["calories_kcal"]["within_range"] is True
    assert metrics["carbs_g"]["absolute_error"] == 5
    assert summary["mean_absolute_calorie_error"] == 0
    assert summary["calorie_within_range_rate"] == 1


def test_nutrition_eval_cost_safeguards() -> None:
    validate_eval_options(
        max_examples=3,
        use_llm=False,
        allow_paid_api=False,
        allow_more_examples=False,
    )

    with pytest.raises(ValueError, match="allow-more-examples"):
        validate_eval_options(
            max_examples=4,
            use_llm=False,
            allow_paid_api=False,
            allow_more_examples=False,
        )

    with pytest.raises(ValueError, match="allow-paid-api"):
        validate_eval_options(
            max_examples=3,
            use_llm=True,
            allow_paid_api=False,
            allow_more_examples=False,
        )


def test_nutrition_eval_no_llm_graph_path() -> None:
    case = load_nutrition_cases()[0]

    results = run_eval_cases(cases=[case], use_llm=False)

    assert len(results) == 1
    result = results[0]
    assert result["model_output"]["text"].startswith("Estimated calories:")
    assert result["components"]["scope_route"] == "text_meal"
    assert result["components"]["extraction"]["expected_ingredient_recall"] == 1
    assert result["parsed_prediction"]["calories_kcal"]["min"] > 0
    assert result["metrics"]["calories_kcal"]["absolute_error"] is not None
