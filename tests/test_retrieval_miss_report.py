import json
from pathlib import Path

from app.evals.retrieval_miss_report import build_report, write_report


def test_retrieval_miss_report_classifies_and_groups_rows(tmp_path: Path) -> None:
    run_path = tmp_path / "golden.json"
    run_path.write_text(
        json.dumps(
            {
                "run_id": "golden-test",
                "examples": [
                    _example(
                        "provider",
                        language="en",
                        category="basic",
                        tags=["smoke"],
                        diagnostics=[
                            _diagnostic(
                                selected_identity="usda:banana:default",
                                candidates=[
                                    _candidate("usda:banana:default", "usda", accepted=True),
                                ],
                            )
                        ],
                    ),
                    _example(
                        "fallback",
                        language="ru",
                        category="branded",
                        tags=["smoke", "branded"],
                        diagnostics=[
                            _diagnostic(
                                query_kind="branded_product",
                                food_category="unknown",
                                fallback_path="explicit_category_or_food_fallback",
                                selected_identity="fallback:snack:default",
                                candidates=[
                                    _candidate("usda:wrong:default", "usda", reasons=["identity_mismatch"]),
                                    _candidate("fallback:snack:default", "fallback", accepted=True),
                                ],
                            ),
                            _diagnostic(
                                fallback_path="explicit_category_or_food_fallback",
                                selected_identity="fallback:banana:default",
                                candidates=[
                                    _candidate("fallback:banana:default", "fallback", accepted=True),
                                ],
                            ),
                            _diagnostic(
                                query_kind="user_composite_meal",
                                fallback_path="generic_mixed_food_for_composite_or_photo",
                                selected_identity="generic_fallback:meal:default",
                                candidates=[
                                    _candidate(
                                        "generic_fallback:meal:default",
                                        "generic_fallback",
                                        accepted=True,
                                    ),
                                ],
                            ),
                            _diagnostic(
                                selected_identity=None,
                                candidates=[
                                    _candidate("usda:bad:default", "usda", reasons=["macro_bounds"]),
                                ],
                            ),
                            _diagnostic(selected_identity=None, candidates=[]),
                        ],
                    ),
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_report([run_path])

    assert report["total_diagnostics"] == 6
    assert report["fallback_or_miss_count"] == 5
    assert report["breakdowns"]["failure_class"] == {
        "all_candidates_rejected": 1,
        "explicit_fallback_selected": 1,
        "fallback_selected_over_provider": 1,
        "generic_fallback_selected": 1,
        "no_candidates": 1,
        "provider_selected": 1,
    }
    assert report["breakdowns"]["language"] == {"en": 1, "ru": 5}
    assert report["breakdowns"]["query_kind"]["branded_product"] == 1
    assert report["breakdowns"]["selected_source"]["fallback"] == 2
    assert report["breakdowns"]["tag"] == {"branded": 5, "smoke": 6}
    fallback_row = next(
        row
        for row in report["rows"]
        if row["failure_class"] == "fallback_selected_over_provider"
    )
    assert fallback_row["candidate_source_counts"] == {"usda": 1, "fallback": 1}
    assert fallback_row["validation_rejections"][0]["reasons"] == ["identity_mismatch"]


def test_retrieval_miss_report_writes_json_and_markdown(tmp_path: Path) -> None:
    report = {
        "generated_at": "2026-06-29T00:00:00+00:00",
        "input_paths": ["golden.json"],
        "run_ids": ["golden-test"],
        "total_diagnostics": 1,
        "fallback_or_miss_count": 1,
        "breakdowns": {
            "failure_class": {"no_candidates": 1},
            "language": {"ru": 1},
            "category": {},
            "query_kind": {},
            "food_category": {},
            "selected_source": {},
            "fallback_path": {},
            "tag": {},
        },
        "rows": [],
        "fallback_or_miss_rows": [
            {
                "example_id": "example",
                "ingredient": "unknown",
                "failure_class": "no_candidates",
                "language": "ru",
                "category": "basic",
                "canonical_query": "unknown",
                "query_kind": "generic_ingredient",
                "food_category": "unknown",
                "provider_queries": ["unknown"],
                "candidate_source_counts": {},
                "selected_identity": None,
                "fallback_path": None,
                "validation_rejections": [],
            }
        ],
    }

    json_path, markdown_path = write_report(report, tmp_path)

    assert json.loads(json_path.read_text(encoding="utf-8"))["total_diagnostics"] == 1
    assert "# Retrieval Miss Report" in markdown_path.read_text(encoding="utf-8")


def _example(
    example_id: str,
    *,
    language: str,
    category: str,
    tags: list[str],
    diagnostics: list[dict],
) -> dict:
    return {
        "id": example_id,
        "language": language,
        "category": category,
        "tags": tags,
        "input": {"text": example_id},
        "status": "pass",
        "execution": {
            "graph_invocations": [
                {
                    "retrieval_diagnostics": diagnostics,
                }
            ]
        },
    }


def _diagnostic(
    *,
    query_kind: str = "generic_ingredient",
    food_category: str = "food",
    fallback_path: str | None = None,
    selected_identity: str | None,
    candidates: list[dict],
) -> dict:
    return {
        "ingredient_name": "banana",
        "canonical_query": "banana",
        "query_kind": query_kind,
        "food_category": food_category,
        "product_variant": "unknown",
        "provider_queries": ["banana"],
        "selected_identity": selected_identity,
        "fallback_path": fallback_path,
        "candidates": candidates,
    }


def _candidate(
    identity: str,
    source: str,
    *,
    accepted: bool = False,
    reasons: list[str] | None = None,
) -> dict:
    return {
        "identity": identity,
        "source": source,
        "name": identity,
        "validation": {
            "accepted": accepted,
            "reasons": reasons or [],
        },
    }
