# NutritionAgent Golden Eval

- Run ID: `golden_baseline_smoke_20260620T012752900358Z`
- Dataset: `evals/datasets/nutrition_agent_phoenix_eval_datasets_v2.jsonl`
- Filters: split=`smoke`, tags=`[]`
- Total: 17
- Passed: 11
- Failed: 6
- Unknown: 0
- Pass rate: 64.7%
- Numeric policy: calorie overlap is required; macro overlap is advisory.
- Diagnosis policy: issue classifications are deterministic triage hints, not ground truth.

## Breakdowns

### Kind

| Value | Passed | Failed | Unknown | Total | Rate |
|---|---:|---:|---:|---:|---:|
| conversation | 5 | 0 | 0 | 5 | 100.0% |
| single_turn | 6 | 6 | 0 | 12 | 50.0% |

### Language

| Value | Passed | Failed | Unknown | Total | Rate |
|---|---:|---:|---:|---:|---:|
| en | 5 | 2 | 0 | 7 | 71.4% |
| ru | 6 | 4 | 0 | 10 | 60.0% |

### Expected Behavior

| Value | Passed | Failed | Unknown | Total | Rate |
|---|---:|---:|---:|---:|---:|
| clarify | 1 | 1 | 0 | 2 | 50.0% |
| estimate | 7 | 5 | 0 | 12 | 58.3% |
| refuse | 3 | 0 | 0 | 3 | 100.0% |

### Category

| Value | Passed | Failed | Unknown | Total | Rate |
|---|---:|---:|---:|---:|---:|
| basic | 1 | 2 | 0 | 3 | 33.3% |
| branded | 2 | 1 | 0 | 3 | 66.7% |
| conversation_memory | 5 | 0 | 0 | 5 | 100.0% |
| edge_case | 3 | 1 | 0 | 4 | 75.0% |
| mixed_dish | 0 | 1 | 0 | 1 | 0.0% |
| packaged | 0 | 1 | 0 | 1 | 0.0% |

### Tag

| Value | Passed | Failed | Unknown | Total | Rate |
|---|---:|---:|---:|---:|---:|
| basic | 1 | 2 | 0 | 3 | 33.3% |
| branded | 3 | 1 | 0 | 4 | 75.0% |
| chicken | 1 | 0 | 0 | 1 | 100.0% |
| clarification | 1 | 1 | 0 | 2 | 50.0% |
| clarify | 1 | 1 | 0 | 2 | 50.0% |
| easy | 6 | 3 | 0 | 9 | 66.7% |
| edge_case | 3 | 1 | 0 | 4 | 75.0% |
| en | 5 | 2 | 0 | 7 | 71.4% |
| estimate | 3 | 5 | 0 | 8 | 37.5% |
| fish | 1 | 0 | 0 | 1 | 100.0% |
| followup | 4 | 0 | 0 | 4 | 100.0% |
| medium | 0 | 3 | 0 | 3 | 0.0% |
| memory | 5 | 0 | 0 | 5 | 100.0% |
| mixed_dish | 0 | 1 | 0 | 1 | 0.0% |
| packaged | 0 | 1 | 0 | 1 | 0.0% |
| prompt_injection | 1 | 0 | 0 | 1 | 100.0% |
| refuse | 2 | 0 | 0 | 2 | 100.0% |
| retrieval | 2 | 2 | 0 | 4 | 50.0% |
| rice | 1 | 0 | 0 | 1 | 100.0% |
| ru | 6 | 4 | 0 | 10 | 60.0% |
| safety | 3 | 0 | 0 | 3 | 100.0% |
| smoke | 11 | 6 | 0 | 17 | 64.7% |
| yogurt | 1 | 0 | 0 | 1 | 100.0% |

## Issue Classifications

- `real_system_failure`: 1
- `unsupported_current_behavior`: 5

## Failed And Unknown Examples

### na_golden_001

- Input: `Сколько калорий в одном среднем банане?`
- Status: `fail`
- Classification: `unsupported_current_behavior`
- Expected behavior: `estimate`
- Actual behavior: `clarify`
- Failed checks: behavior: expected estimate, got clarify; must_contain_any: none of ['ккал', 'калор'] found
- Unknown checks: calories: answer could not be parsed
- Parsed nutrition: `{}`

```text
Нужно еще немного информации для надежной оценки: Какие продукты были в блюде и примерно сколько каждого?
```

### na_golden_005

- Input: `Сколько калорий в 150 г запеченного лосося?`
- Status: `fail`
- Classification: `unsupported_current_behavior`
- Expected behavior: `estimate`
- Actual behavior: `clarify`
- Failed checks: behavior: expected estimate, got clarify; must_contain_any: none of ['ккал', 'калор'] found
- Unknown checks: calories: answer could not be parsed
- Parsed nutrition: `{}`

```text
Нужно еще немного информации для надежной оценки: Какие продукты были в блюде и примерно сколько каждого?
```

### na_golden_023

- Input: `Сколько калорий в банке Coca-Cola Zero 330 мл?`
- Status: `fail`
- Classification: `unsupported_current_behavior`
- Expected behavior: `estimate`
- Actual behavior: `clarify`
- Failed checks: behavior: expected estimate, got clarify; must_contain_any: none of ['ккал', 'калор'] found
- Unknown checks: calories: answer could not be parsed
- Parsed nutrition: `{}`

```text
Нужно еще немного информации для надежной оценки: Какие продукты были в блюде и примерно сколько каждого?
```

### na_golden_035

- Input: `Сколько калорий и белка в 850 г натурального скира?`
- Status: `fail`
- Classification: `unsupported_current_behavior`
- Expected behavior: `estimate`
- Actual behavior: `clarify`
- Failed checks: behavior: expected estimate, got clarify; must_contain_any: none of ['ккал', 'калор'] found
- Unknown checks: calories: answer could not be parsed
- Parsed nutrition: `{}`

```text
Нужно еще немного информации для надежной оценки: Какие продукты были в блюде и примерно сколько каждого?
```

### na_golden_044

- Input: `How many calories in 400g borscht with sour cream?`
- Status: `fail`
- Classification: `unsupported_current_behavior`
- Expected behavior: `estimate`
- Actual behavior: `clarify`
- Failed checks: behavior: expected estimate, got clarify; must_contain_any: none of ['kcal', 'calories'] found
- Unknown checks: calories: answer could not be parsed
- Parsed nutrition: `{}`

```text
I need one more detail to estimate this reliably: What foods are in the meal and roughly how much of each?
```

### na_golden_092

- Input: `How many calories in a salad?`
- Status: `fail`
- Classification: `real_system_failure`
- Expected behavior: `clarify`
- Actual behavior: `estimate`
- Failed checks: behavior: expected clarify, got estimate; must_contain_any: none of ['need', 'clarify', 'detail'] found; must_not_contain_any: found ['Estimated calories']
- Unknown checks: none
- Parsed nutrition: `{"calories_kcal": {"min": 20.0, "max": 40.0}, "protein_g": {"min": 1.0, "max": 2.0}, "fat_g": {"min": 0.0, "max": 0.0}, "carbs_g": {"min": 3.0, "max": 7.0}}`

```text
Estimated calories: 20-40 kcal
Protein: 1-2 g
Fat: 0-0 g
Carbs: 3-7 g
Main assumptions:
* mixed salad vegetables: 80-180 g (assumed standard portion).
Confidence: medium
```
