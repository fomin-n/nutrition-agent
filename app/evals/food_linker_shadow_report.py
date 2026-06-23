from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.tools.food_linker import find_embedding_food_mentions

DEFAULT_BASELINE = Path("tests/fixtures/food_detection_baseline.json")
DEFAULT_OUTPUT_DIR = Path("reports/eval")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare embedding food linker against frozen baseline.")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--threshold", type=float, default=0.62)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    rows = json.loads(args.baseline.read_text(encoding="utf-8"))
    report = build_report(rows, threshold=args.threshold)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = args.output_dir / f"food_linker_shadow_{stamp}.json"
    md_path = args.output_dir / f"food_linker_shadow_{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")


def build_report(rows: list[dict[str, Any]], *, threshold: float) -> dict[str, Any]:
    disagreements: list[dict[str, Any]] = []
    for row in rows:
        expected = tuple(item["canonical_name"] for item in row["mentions"])
        actual_mentions = find_embedding_food_mentions(row["text"], threshold=threshold)
        actual = tuple(item.canonical_name for item in actual_mentions)
        if expected == actual:
            continue
        disagreements.append(
            {
                "id": row["id"],
                "dataset": row["dataset"],
                "turn_index": row["turn_index"],
                "language": row["language"],
                "text": row["text"],
                "legacy_canonical_names": list(expected),
                "embedding_canonical_names": list(actual),
                "embedding_matches": [
                    {
                        "canonical_name": item.canonical_name,
                        "matched_text": item.matched_text,
                        "score": round(item.score, 4),
                        "method": item.method,
                    }
                    for item in actual_mentions
                ],
            }
        )
    total = len(rows)
    agreement = total - len(disagreements)
    return {
        "threshold": threshold,
        "total": total,
        "agreements": agreement,
        "disagreements": len(disagreements),
        "agreement_rate": agreement / total if total else 0.0,
        "generated_at": datetime.now(UTC).isoformat(),
        "disagreement_examples": disagreements,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Food Linker Shadow Report",
        "",
        f"- Threshold: `{report['threshold']}`",
        f"- Total rows: `{report['total']}`",
        f"- Agreements: `{report['agreements']}`",
        f"- Disagreements: `{report['disagreements']}`",
        f"- Agreement rate: `{report['agreement_rate']:.3f}`",
        "",
        "## Disagreements",
        "",
    ]
    for item in report["disagreement_examples"][:50]:
        lines.extend(
            [
                f"### {item['id']}",
                "",
                f"- Dataset: `{item['dataset']}`",
                f"- Turn: `{item['turn_index']}`",
                f"- Text: {item['text']}",
                f"- Legacy: `{', '.join(item['legacy_canonical_names']) or '<none>'}`",
                f"- Embedding: `{', '.join(item['embedding_canonical_names']) or '<none>'}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    main()
