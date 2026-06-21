# Golden Evaluation

The committed golden datasets cover English and Russian single-turn requests plus bounded conversation-memory flows. They include basic foods, branded and packaged products, mixed dishes, clarification cases, and safety refusals.

## Files

- `datasets/nutrition_agent_golden_single_turn_v2.jsonl`: 100 single-turn examples.
- `datasets/nutrition_agent_golden_single_turn_v2.csv`: spreadsheet view of the same IDs.
- `datasets/nutrition_agent_golden_conversations_v1.jsonl`: 10 conversation examples.
- `datasets/nutrition_agent_golden_conversations_v1.csv`: spreadsheet view of the same IDs.
- `datasets/nutrition_agent_phoenix_eval_datasets_v2.jsonl`: combined 110-example Phoenix-friendly dataset.

JSONL is the source of truth for the runner and Phoenix upload. CSV files are provided for human review. Every JSONL row preserves structured `input`, `output`, `metadata`, and `splits` values.

## Local Runs

Run the 17-case deterministic smoke split:

```bash
uv run python -m app.evals.run_golden_eval \
  --dataset evals/datasets/nutrition_agent_phoenix_eval_datasets_v2.jsonl \
  --split smoke
```

Run all 110 golden cases:

```bash
uv run python -m app.evals.run_golden_eval \
  --dataset evals/datasets/nutrition_agent_phoenix_eval_datasets_v2.jsonl \
  --split golden
```

Filter by one or more required metadata tags with repeated `--tag` options. The default run disables LLM calls and external nutrition providers, making it deterministic and cheap. `--live-providers` opts into configured nutrition APIs. LLM use requires both `--use-llm` and `--allow-paid-api`.

Each run writes timestamped JSON and Markdown under `reports/eval/`. Use `--output-dir reports/eval/baseline` when producing a baseline that should be reviewed and committed. Ordinary generated reports remain ignored. The command exits nonzero when any example fails or is unknown, after writing the report.

Exact reference-answer matching is intentionally not used. Required checks are expected behavior, text markers, and calorie-range overlap. Macro ranges are parsed and reported as advisory diagnostics. Reports distinguish `pass`, `fail`, and `unknown`; an unparseable required calorie value is `unknown` unless another check is a definite failure. Every non-pass example also gets one deterministic triage classification: `likely_dataset_issue`, `evaluator_issue`, `unsupported_current_behavior`, or `real_system_failure`. These classifications identify where to investigate first and are not a substitute for human review.

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

The 2026-06-21 deterministic parser update improved smoke from 64.7% to 100%, full golden from 25.5% to 60.9%, Russian from 22.8% to 59.6%, and single-turn from 21.0% to 58.0%. Memory/follow-up and safety/refusal tags remained at 100%. See the committed comparison under `reports/eval/post_change/` for category changes and remaining failures.

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
