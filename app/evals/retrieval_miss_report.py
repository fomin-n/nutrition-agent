from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_OUTPUT_DIR = Path("reports/eval")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate NutritionAgent retrieval diagnostics from golden eval runs."
    )
    parser.add_argument(
        "--golden-run",
        action="append",
        type=Path,
        required=True,
        help="Path to a golden eval JSON result. Repeat to merge runs.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    report = build_report(args.golden_run)
    json_path, markdown_path = write_report(report, args.output_dir)
    print(f"wrote {json_path}")
    print(f"wrote {markdown_path}")
    return 0


def build_report(paths: list[Path]) -> dict[str, Any]:
    runs = [_load_json(path) for path in paths]
    rows = [
        row
        for run, path in zip(runs, paths, strict=True)
        for row in _diagnostic_rows(run, source_path=path)
    ]
    fallback_rows = [
        row
        for row in rows
        if row["failure_class"]
        in {
            "explicit_fallback_selected",
            "generic_fallback_selected",
            "fallback_selected_over_provider",
            "all_candidates_rejected",
            "no_candidates",
        }
    ]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "input_paths": [str(path) for path in paths],
        "run_ids": [run.get("run_id") for run in runs],
        "total_diagnostics": len(rows),
        "fallback_or_miss_count": len(fallback_rows),
        "breakdowns": {
            "failure_class": _counter(rows, "failure_class"),
            "language": _counter(rows, "language"),
            "category": _counter(rows, "category"),
            "query_kind": _counter(rows, "query_kind"),
            "food_category": _counter(rows, "food_category"),
            "selected_source": _counter(rows, "selected_source"),
            "fallback_path": _counter(rows, "fallback_path"),
            "tag": _tag_counter(rows),
        },
        "rows": rows,
        "fallback_or_miss_rows": fallback_rows,
    }


def write_report(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"retrieval_miss_report_{stamp}.json"
    markdown_path = output_dir / f"retrieval_miss_report_{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _diagnostic_rows(run: dict[str, Any], *, source_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for example in run.get("examples", []):
        for invocation_index, invocation in enumerate(
            example.get("execution", {}).get("graph_invocations", [])
        ):
            for diagnostic_index, diagnostic in enumerate(invocation.get("retrieval_diagnostics", [])):
                candidates = list(diagnostic.get("candidates", []))
                selected_identity = diagnostic.get("selected_identity")
                selected_candidate = _selected_candidate(candidates, selected_identity)
                selected_source = selected_candidate.get("source") if selected_candidate else None
                candidate_source_counts = dict(Counter(str(candidate.get("source") or "unknown") for candidate in candidates))
                validation_rejections = [
                    {
                        "identity": candidate.get("identity"),
                        "source": candidate.get("source"),
                        "name": candidate.get("name"),
                        "reasons": candidate.get("validation", {}).get("reasons", []),
                    }
                    for candidate in candidates
                    if not candidate.get("validation", {}).get("accepted", False)
                ]
                row = {
                    "source_path": str(source_path),
                    "run_id": run.get("run_id"),
                    "example_id": example.get("id"),
                    "language": example.get("language"),
                    "category": example.get("category"),
                    "tags": list(example.get("tags", [])),
                    "input": example.get("input"),
                    "status": example.get("status"),
                    "invocation_index": invocation_index,
                    "diagnostic_index": diagnostic_index,
                    "ingredient": diagnostic.get("ingredient_name"),
                    "canonical_query": diagnostic.get("canonical_query"),
                    "query_kind": diagnostic.get("query_kind", "unknown"),
                    "food_category": diagnostic.get("food_category", "unknown"),
                    "product_variant": diagnostic.get("product_variant", "unknown"),
                    "provider_queries": list(diagnostic.get("provider_queries", [])),
                    "candidate_count": len(candidates),
                    "candidate_source_counts": candidate_source_counts,
                    "selected_identity": selected_identity,
                    "selected_source": selected_source,
                    "fallback_path": diagnostic.get("fallback_path"),
                    "failure_class": _failure_class(
                        selected_source=selected_source,
                        fallback_path=diagnostic.get("fallback_path"),
                        candidate_source_counts=candidate_source_counts,
                        candidates=candidates,
                    ),
                    "validation_rejections": validation_rejections,
                }
                rows.append(row)
    return rows


def _selected_candidate(
    candidates: list[dict[str, Any]],
    selected_identity: str | None,
) -> dict[str, Any] | None:
    if selected_identity is None:
        return None
    return next(
        (candidate for candidate in candidates if candidate.get("identity") == selected_identity),
        None,
    )


def _failure_class(
    *,
    selected_source: str | None,
    fallback_path: str | None,
    candidate_source_counts: dict[str, int],
    candidates: list[dict[str, Any]],
) -> str:
    provider_count = sum(
        count
        for source, count in candidate_source_counts.items()
        if source not in {"fallback", "generic_fallback"}
    )
    if selected_source == "generic_fallback":
        return "generic_fallback_selected"
    if selected_source == "fallback":
        if provider_count:
            return "fallback_selected_over_provider"
        return "explicit_fallback_selected"
    if selected_source:
        return "provider_selected"
    if not candidates:
        return "no_candidates"
    return "all_candidates_rejected"


def _counter(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    values = [str(row.get(key) or "none") for row in rows]
    return dict(sorted(Counter(values).items()))


def _tag_counter(rows: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        for tag in row.get("tags", []):
            counter[str(tag)] += 1
    return dict(sorted(counter.items()))


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Retrieval Miss Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Input runs: `{len(report['input_paths'])}`",
        f"- Total diagnostics: `{report['total_diagnostics']}`",
        f"- Fallback/miss diagnostics: `{report['fallback_or_miss_count']}`",
        "",
        "## Breakdowns",
        "",
    ]
    for name, breakdown in report["breakdowns"].items():
        lines.append(f"### {name}")
        lines.append("")
        if not breakdown:
            lines.append("_None_")
        else:
            for key, count in sorted(breakdown.items(), key=lambda item: (-item[1], item[0])):
                lines.append(f"- `{key}`: {count}")
        lines.append("")

    lines.extend(["## Fallback And Miss Rows", ""])
    if not report["fallback_or_miss_rows"]:
        lines.append("_No fallback or miss diagnostics._")
    for row in report["fallback_or_miss_rows"][:100]:
        rejection_reasons = sorted(
            {
                reason
                for rejection in row["validation_rejections"]
                for reason in rejection.get("reasons", [])
            }
        )
        lines.extend(
            [
                f"### {row['example_id']} · {row['ingredient']}",
                "",
                f"- Class: `{row['failure_class']}`",
                f"- Language/category: `{row['language']}` / `{row['category']}`",
                f"- Query: `{row['canonical_query']}` (`{row['query_kind']}`, `{row['food_category']}`)",
                f"- Provider queries: `{', '.join(row['provider_queries'])}`",
                f"- Candidate sources: `{row['candidate_source_counts']}`",
                f"- Selected: `{row['selected_identity'] or '<none>'}`",
                f"- Fallback path: `{row['fallback_path'] or '<none>'}`",
                f"- Rejection reasons: `{', '.join(rejection_reasons) or '<none>'}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
