import argparse
import json
from typing import Any

from app.schemas.nutrition import NutritionCandidate, NutritionValues
from app.tools.food_query import normalize_food_description
from app.tools.nutrition_ranking import rank_candidates
from app.tools.nutrition_tools import get_default_router

SMOKE_EXAMPLES = [
    "banana",
    "200 g cooked chicken breast",
    "Big Mac",
    "Danone Skyr 850 g",
    "борщ со сметаной",
    "паста карбонара",
    "гречка с курицей",
    "Snickers 50 g",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a tiny nutrition retrieval smoke test.")
    parser.add_argument("--live", action="store_true", help="Use configured live providers instead of mocked candidates.")
    parser.add_argument("--max-examples", type=int, default=len(SMOKE_EXAMPLES))
    args = parser.parse_args()

    examples = SMOKE_EXAMPLES[: args.max_examples]
    output = run_smoke(examples, live=args.live)
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


def run_smoke(examples: list[str], *, live: bool = False) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    router = get_default_router() if live else None
    for example in examples:
        query = normalize_food_description(example)
        candidates = router.retrieve_candidates(query) if router else _mock_candidates(query.canonical_query)
        ranked = candidates if live else rank_candidates(candidates, query)
        selected = next((candidate for candidate in ranked if candidate.to_per_100g() is not None), None)
        results.append(
            {
                "input": example,
                "normalized_query": query.__dict__,
                "selected_source": selected.source if selected else None,
                "selected_candidate": _candidate_summary(selected) if selected else None,
                "alternatives": [_candidate_summary(candidate) for candidate in ranked[:3]],
                "came_from_api": bool(live and selected and selected.source in {"usda", "fatsecret", "open_food_facts"}),
            }
        )
    return results


def _mock_candidates(query: str) -> list[NutritionCandidate]:
    return [
        NutritionCandidate(
            source="usda",
            source_id="mock-usda",
            name=query,
            food_type="generic",
            metric_serving_amount=100,
            metric_serving_unit="g",
            serving_description="per 100 g",
            values_per_100g=NutritionValues(calories_kcal=120, protein_g=7, carbohydrate_g=18, fat_g=3),
        ),
        NutritionCandidate(
            source="fatsecret",
            source_id="mock-fatsecret",
            name=query,
            food_type="branded",
            brand="Danone" if "skyr" in query.lower() else None,
            metric_serving_amount=100,
            metric_serving_unit="g",
            serving_description="per 100 g",
            values_per_100g=NutritionValues(calories_kcal=130, protein_g=8, carbohydrate_g=17, fat_g=4),
        ),
    ]


def _candidate_summary(candidate: NutritionCandidate | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    values = candidate.values_per_100g
    return {
        "source": candidate.source,
        "source_id": candidate.source_id,
        "name": candidate.name,
        "brand": candidate.brand,
        "food_type": candidate.food_type,
        "serving": candidate.serving_description,
        "metric_serving_amount": candidate.metric_serving_amount,
        "metric_serving_unit": candidate.metric_serving_unit,
        "calories_kcal_per_100g": values.calories_kcal if values else None,
        "protein_g_per_100g": values.protein_g if values else None,
        "fat_g_per_100g": values.fat_g if values else None,
        "carbohydrate_g_per_100g": values.carbohydrate_g if values else None,
        "match_score": candidate.match_score,
        "score_components": candidate.score_components,
    }


if __name__ == "__main__":
    raise SystemExit(main())
