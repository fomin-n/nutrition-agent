# Golden Evaluation

The committed golden datasets cover English and Russian single-turn requests plus bounded conversation-memory flows. They include basic foods, branded and packaged products, mixed dishes, clarification cases, and safety refusals.

## Files

- `datasets/nutrition_agent_golden_single_turn_v2.jsonl`: 101 single-turn examples.
- `datasets/nutrition_agent_golden_single_turn_v2.csv`: spreadsheet view of the same IDs.
- `datasets/nutrition_agent_golden_conversations_v1.jsonl`: 10 conversation examples.
- `datasets/nutrition_agent_golden_conversations_v1.csv`: spreadsheet view of the same IDs.
- `datasets/nutrition_agent_phoenix_eval_datasets_v2.jsonl`: combined 111-example Phoenix-friendly dataset.

JSONL is the source of truth for the runner and Phoenix upload. CSV files are provided for human review. Every JSONL row preserves structured `input`, `output`, `metadata`, and `splits` values.

## Local Runs

Run the 18-case deterministic smoke split:

```bash
uv run python -m app.evals.run_golden_eval \
  --dataset evals/datasets/nutrition_agent_phoenix_eval_datasets_v2.jsonl \
  --split smoke
```

Run all 111 golden cases:

```bash
uv run python -m app.evals.run_golden_eval \
  --dataset evals/datasets/nutrition_agent_phoenix_eval_datasets_v2.jsonl \
  --split golden
```

Run the deterministic regression gate used by CI:

```bash
uv run python -m app.evals.run_golden_gate
```

The gate runs the full no-LLM/no-provider golden lane and enforces the current
minimum quality floor: overall pass rate at least 60%, safety-tag pass rate 100%,
refusal-behavior pass rate 100%, and zero unknown examples. This is a guardrail,
not a product-quality target; live parser/provider lanes remain manual because
they can spend API budget and vary with upstream providers.

Filter by one or more required metadata tags with repeated `--tag` options. The default run disables LLM calls and external nutrition providers, making it deterministic and cheap. `--live-providers` opts into configured nutrition APIs.

Parser lanes:

- `--llm-mode off`: default deterministic fallback path with no LLM calls.
- `--llm-mode stub`: production parser branch with deterministic golden fixtures. This mode patches parser LLM calls to fixed structured `MealUnderstanding` outputs and keeps moderation, scope, critic, image, and packaging model calls local/off. It is a regression lane, not a claim about actual model quality.
- `--llm-mode live --allow-paid-api`: real configured production LLM parser path. This may call paid APIs and should be run intentionally.
- `--use-llm --allow-paid-api`: deprecated alias for `--llm-mode live --allow-paid-api`.

Each run writes timestamped JSON and Markdown under `reports/eval/`. Use `--output-dir reports/eval/baseline` when producing a baseline that should be reviewed and committed. Ordinary generated reports remain ignored. The command exits nonzero when any example fails or is unknown, after writing the report.

Exact reference-answer matching is intentionally not used. Required checks are expected behavior, text markers, and calorie-range overlap. Macro ranges are parsed and reported as advisory diagnostics. Reports distinguish `pass`, `fail`, and `unknown`; an unparseable required calorie value is `unknown` unless another check is a definite failure. Every non-pass example also gets one deterministic triage classification: `likely_dataset_issue`, `evaluator_issue`, `unsupported_current_behavior`, or `real_system_failure`. These classifications identify where to investigate first and are not a substitute for human review.

Official measurement rows can be appended from generated run JSON files:

```bash
uv run python -m app.evals.metrics_history \
  --output reports/eval/metrics_history.jsonl \
  reports/eval/<lane>/<golden-run>.json
```

Committed milestone snapshots live under `reports/eval/milestones/`; bulky stdout
and stderr logs stay ignored. The history file records one compact row per lane
with pass rate, category/tag pass rates, calorie error metrics, confidence buckets,
and LLM usage/cost diagnostics when available.

Official live measurements should use the artifact wrapper so reports are durable:

```bash
uv run python -m app.evals.run_official_golden_eval \
  --label round2_live_parser_1 \
  --llm-mode live \
  --allow-paid-api \
  --commit \
  --push
```

Add `--live-providers` for the production-like provider lane. The wrapper writes a
Markdown summary, gzipped raw JSON, sanitized provenance, `COMMIT_SHA`,
`MANIFEST.sha256`, and one metrics-history row under `reports/eval/official/`.
Stdout/stderr logs remain ignored.

To create committed smoke and full baseline reports:

```bash
uv run python -m app.evals.run_golden_eval \
  --dataset evals/datasets/nutrition_agent_phoenix_eval_datasets_v2.jsonl \
  --split smoke \
  --output-dir reports/eval/baseline

uv run python -m app.evals.run_golden_eval \
  --dataset evals/datasets/nutrition_agent_phoenix_eval_datasets_v2.jsonl \
  --split golden \
  --output-dir reports/eval/baseline
```

Compare a current smoke/full pair with the committed baseline:

```bash
uv run python -m app.evals.compare_golden_runs \
  --baseline-smoke reports/eval/baseline/golden_baseline_smoke_20260620T012752900358Z.json \
  --baseline-golden reports/eval/baseline/golden_baseline_golden_20260620T012752900266Z.json \
  --current-smoke reports/eval/post_change/<smoke-run>.json \
  --current-golden reports/eval/post_change/<golden-run>.json
```

Compare deterministic and LLM-path lanes case-by-case:

```bash
uv run python -m app.evals.compare_golden_lanes \
  --fallback-run reports/eval/<fallback-run>.json \
  --llm-run reports/eval/<llm-run>.json
```

The 2026-06-21 deterministic parser update improved smoke from 64.7% to 100%, full golden from 25.5% to 60.9%, Russian from 22.8% to 59.6%, and single-turn from 21.0% to 58.0%. Memory/follow-up and safety/refusal tags remained at 100%. See the committed comparison under `reports/eval/post_change/` for category changes and remaining failures.

## Other Local Evals

Run the adversarial safety eval without API keys:

```bash
uv run python -m app.evals.run_eval --mock
```

Run the tiny nutrition-quality eval:

```bash
uv run python -m app.evals.run_nutrition_eval --max-examples 3
```

The tiny nutrition eval uses 3 committed rows derived from OpenIntro's public `fastfood` dataset because it is small, CSV-based, downloadable without authentication, and includes calories plus protein, fat, and carbohydrate values. The sample lives in `app/evals/fastfood_tiny_sample.jsonl`; the full dataset is not committed.

OpenIntro describes the source dataset as 515 fast-food items with nutrition fields such as calories, total fat, total carbs, and protein. OpenIntro's license page says most OpenIntro resources are released under Creative Commons BY-SA 3.0; see:

- Dataset: https://www.openintro.org/data/index.php?data=fastfood
- CSV: https://www.openintro.org/data/csv/fastfood.csv
- License: https://www.openintro.org/license/

By default, the tiny nutrition eval runs exactly 3 examples with `use_llm=False`, so it exercises the deterministic/local graph path and does not call OpenAI. Processing more than 3 examples requires `--allow-more-examples`; using LLM-backed graph paths requires both `--use-llm` and `--allow-paid-api`.

Metrics are intentionally simple: predicted calorie midpoint versus ground-truth calories, absolute error, percentage error, mean absolute calorie error, and macro errors for protein, fat, and carbs when present. Fast-food menu rows describe complete prepared items, while the default no-LLM parser may map them to generic ingredients with assumed portions, so this is a smoke check rather than a benchmark.

Generate the food-linker shadow disagreement report:

```bash
uv run python -m app.evals.food_linker_shadow_report --threshold 0.62
```

The frozen detector baseline lives in `tests/fixtures/food_detection_baseline.json` and covers the golden single-turn and conversation datasets. Shadow reports are ignored under `reports/eval/`.

## Phoenix Upload

Phoenix 17 exposes dataset upload at `/v1/datasets/upload`. The uploader uses the existing `httpx` dependency and stable `metadata.id` values; repeated uploads update the dataset rather than duplicating examples.

```bash
uv run python -m app.evals.phoenix_datasets \
  --dataset evals/datasets/nutrition_agent_golden_single_turn_v2.jsonl \
  --name nutrition-agent-golden-single-turn-v2
```

Use the same command for `nutrition-agent-golden-conversations-v1` and `nutrition-agent-golden-combined-v2`. The default base URL is `PHOENIX_BASE_URL`, then `PHOENIX_COLLECTOR_ENDPOINT` without `/v1/traces`, then `http://127.0.0.1:6006`. Set `PHOENIX_API_KEY` only when the Phoenix deployment requires authentication. An unavailable server produces a concise error and does not affect local eval reports.

## Adding A Case

Add the case to the appropriate source JSONL and CSV, then regenerate or update the combined JSONL. Keep `metadata.id` globally unique, assign `golden` plus optional `smoke` splits, and use stable tags. Expectations should describe behavior and acceptable ranges, not exact prose. Run loader tests, the smoke split, and the full golden split before changing production logic in response to failures.

## Larger Future Datasets

Potential future datasets include Nutrition5k for image meal evaluation, NutriBench for text meal evaluation, and NutritionVerse-Real for real food image evaluation. Large datasets are intentionally not downloaded by this repository.
