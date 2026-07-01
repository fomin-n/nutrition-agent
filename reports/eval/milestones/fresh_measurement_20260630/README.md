# Fresh Golden Measurement - 2026-06-30

## Provenance

- Repository: `fomin-n/nutrition-agent`
- HEAD commit: `5db1cc691be6b811f10cee362edd1e75e0423917`
- Working tree during run: eval-harness/reporting changes in `app/evals/golden.py`, `app/evals/run_golden_eval.py`, and `tests/test_golden_eval.py`; no product pipeline changes.
- Baseline compared: `reports/eval/live_golden_20260624/`
- Dataset: default combined golden dataset, 111 examples, no split filter.

## Commands

```bash
uv run ruff check .
uv run mypy app
uv run pytest --cov=app --cov-report=term-missing --cov-fail-under=75
uv run python -m app.evals.run_eval --mock
uv run python -m app.evals.run_golden_eval --split smoke
uv run pip-audit --progress-spinner off

uv run python -m app.evals.run_golden_eval --llm-mode off --output-dir reports/eval/fresh_measurement_20260630/off
uv run python -m app.evals.run_golden_eval --llm-mode stub --output-dir reports/eval/fresh_measurement_20260630/stub
uv run python -m app.evals.run_golden_eval --llm-mode live --allow-paid-api --output-dir reports/eval/fresh_measurement_20260630/live_parser_1
uv run python -m app.evals.run_golden_eval --llm-mode live --allow-paid-api --live-providers --output-dir reports/eval/fresh_measurement_20260630/live_providers
```

## Lane Summary

| Lane | Baseline pass | Current pass | Delta | Current duration | Current LLM calls | Current est. cost |
|---|---:|---:|---:|---:|---:|---:|
| off | 62.2% | 62.2% | +0.0% | 6.664s | 0 | $0.000000 |
| stub | 80.2% | 80.2% | +0.0% | 54.992s | 0 | $0.000000 |
| live_parser_1 | 66.7% | 67.6% | +0.9% | 1028.022s | 330 | $0.096556 |
| live_providers | 59.5% | 61.3% | +1.8% | 1624.438s | 327 | $0.095928 |

## Production-Like Live Providers

- Current pass: 68/111 (61.3%).
- Mixed dish: 16/49 (32.7%), unchanged from baseline and still the dominant weakness.
- Basic: 16/22 (72.7%).
- Branded: 5/6 (83.3%).
- Packaged: 9/11 (81.8%).
- Conversation memory: 10/10 (100%).
- Safety/refusal: 3/3 (100%), unchanged.
- RU: 35/58 (60.3%); EN: 33/53 (62.3%).

Current live-provider numeric calorie metrics:

- Mean absolute error: 112.2 kcal.
- Median absolute error: 35.0 kcal.
- P90 absolute error: 300.0 kcal.
- Mean percentage error: 30.8%.
- P90 percentage error: 60.3%.
- Max percentage error: 450.0%.
- Mean predicted range width: 73.2 kcal.
- Median predicted range width: 20.0 kcal.
- Within predicted range rate: 35.8%.

Confidence calibration in current live providers:

| Confidence | Pass rate | Calorie MAPE |
|---|---:|---:|
| high | 42/57 (73.7%) | 29.3% |
| medium | 13/25 (52.0%) | 27.9% |
| low | 13/29 (44.8%) | 44.8% |

Higher confidence has better pass rate than low confidence, but calorie MAPE is not strictly monotonic between high and medium.

## Status Movement Vs 2026-06-24 Live Providers

Fail -> pass:

- `na_golden_014`: basic EN, `Calories in 250ml 2% milk`.
- `na_golden_035`: packaged RU, `Сколько калорий и белка в 850 г натурального скира?`.
- `na_golden_088`: mixed_dish EN, `Calories in scrambled eggs with toast`.

Pass -> fail:

- `na_golden_049`: mixed_dish RU, `Сколько калорий в гречке с курицей, порция 350 г?`.

The earlier simple/basic-food regression improved slightly, but not fully: two former regressions now pass, while many basic/simple cases remain calorie-range failures in the live-provider lane.

## Current Lane Comparisons

- A(off) vs C1(live parser): 69 -> 75 passed, +5.4%; 8 fail->pass, 2 pass->fail.
- A(off) vs D(live providers): 69 -> 68 passed, -0.9%; 14 fail->pass, 15 pass->fail.
- B(stub) vs C1(live parser): 89 -> 75 passed, -12.6%; 4 fail->pass, 18 pass->fail.

## Metric Additions In This Working Tree

Golden reports now include per-example and aggregate numeric metrics for calories/protein/fat/carbs: midpoint absolute error, percentage error, p90/p95/max tails, predicted interval width, normalized width, within-prediction-range rate, and interval score. Breakdowns now include numeric metrics by kind, language, expected behavior, category, tag, confidence, and retrieval `query_kind`, plus a confidence-calibration summary.

## Deferred

- No append-only committed metric history was added in this pass.
- No deterministic full-golden CI gate was added in this pass.
- No repeated live variance suite was run beyond the single fresh live-parser and live-provider lanes, to keep cost bounded.
