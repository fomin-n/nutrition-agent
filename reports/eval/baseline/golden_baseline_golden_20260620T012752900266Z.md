# NutritionAgent Golden Eval

- Run ID: `golden_baseline_golden_20260620T012752900266Z`
- Dataset: `evals/datasets/nutrition_agent_phoenix_eval_datasets_v2.jsonl`
- Filters: split=`golden`, tags=`[]`
- Total: 110
- Passed: 28
- Failed: 82
- Unknown: 0
- Pass rate: 25.5%
- Numeric policy: calorie overlap is required; macro overlap is advisory.
- Diagnosis policy: issue classifications are deterministic triage hints, not ground truth.

## Breakdowns

### Kind

| Value | Passed | Failed | Unknown | Total | Rate |
|---|---:|---:|---:|---:|---:|
| conversation | 7 | 3 | 0 | 10 | 70.0% |
| single_turn | 21 | 79 | 0 | 100 | 21.0% |

### Language

| Value | Passed | Failed | Unknown | Total | Rate |
|---|---:|---:|---:|---:|---:|
| en | 15 | 38 | 0 | 53 | 28.3% |
| ru | 13 | 44 | 0 | 57 | 22.8% |

### Expected Behavior

| Value | Passed | Failed | Unknown | Total | Rate |
|---|---:|---:|---:|---:|---:|
| clarify | 4 | 6 | 0 | 10 | 40.0% |
| estimate | 21 | 76 | 0 | 97 | 21.6% |
| refuse | 3 | 0 | 0 | 3 | 100.0% |

### Category

| Value | Passed | Failed | Unknown | Total | Rate |
|---|---:|---:|---:|---:|---:|
| basic | 7 | 14 | 0 | 21 | 33.3% |
| branded | 2 | 4 | 0 | 6 | 33.3% |
| cafe | 0 | 3 | 0 | 3 | 0.0% |
| conversation_memory | 7 | 3 | 0 | 10 | 70.0% |
| edge_case | 6 | 4 | 0 | 10 | 60.0% |
| mixed_dish | 5 | 44 | 0 | 49 | 10.2% |
| packaged | 1 | 10 | 0 | 11 | 9.1% |

### Tag

| Value | Passed | Failed | Unknown | Total | Rate |
|---|---:|---:|---:|---:|---:|
| ambiguous | 0 | 1 | 0 | 1 | 0.0% |
| banana | 0 | 1 | 0 | 1 | 0.0% |
| basic | 7 | 14 | 0 | 21 | 33.3% |
| branded | 4 | 4 | 0 | 8 | 50.0% |
| cafe | 0 | 3 | 0 | 3 | 0.0% |
| chicken | 2 | 0 | 0 | 2 | 100.0% |
| clarification | 4 | 6 | 0 | 10 | 40.0% |
| clarify | 4 | 4 | 0 | 8 | 50.0% |
| cola | 1 | 0 | 0 | 1 | 100.0% |
| easy | 17 | 26 | 0 | 43 | 39.5% |
| edge_case | 6 | 4 | 0 | 10 | 60.0% |
| en | 15 | 38 | 0 | 53 | 28.3% |
| estimate | 15 | 75 | 0 | 90 | 16.7% |
| fish | 1 | 0 | 0 | 1 | 100.0% |
| followup | 5 | 0 | 0 | 5 | 100.0% |
| hard | 2 | 8 | 0 | 10 | 20.0% |
| medium | 2 | 45 | 0 | 47 | 4.3% |
| memory | 7 | 1 | 0 | 8 | 87.5% |
| missing_image | 0 | 1 | 0 | 1 | 0.0% |
| mixed_dish | 5 | 44 | 0 | 49 | 10.2% |
| new_request | 0 | 1 | 0 | 1 | 0.0% |
| packaged | 1 | 10 | 0 | 11 | 9.1% |
| prompt_injection | 1 | 0 | 0 | 1 | 100.0% |
| refuse | 2 | 0 | 0 | 2 | 100.0% |
| regression | 1 | 0 | 0 | 1 | 100.0% |
| retrieval | 3 | 14 | 0 | 17 | 17.6% |
| rice | 1 | 0 | 0 | 1 | 100.0% |
| ru | 13 | 44 | 0 | 57 | 22.8% |
| safety | 3 | 0 | 0 | 3 | 100.0% |
| smoke | 11 | 6 | 0 | 17 | 64.7% |
| yogurt | 1 | 0 | 0 | 1 | 100.0% |

## Issue Classifications

- `likely_dataset_issue`: 1
- `real_system_failure`: 18
- `unsupported_current_behavior`: 63

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

### na_golden_003

- Input: `Сколько БЖУ в одном вареном яйце?`
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

### na_golden_004

- Input: `Calories and macros for 100g cooked chicken breast`
- Status: `fail`
- Classification: `real_system_failure`
- Expected behavior: `estimate`
- Actual behavior: `estimate`
- Failed checks: calories: predicted range does not overlap acceptable range
- Unknown checks: none
- Parsed nutrition: `{"calories_kcal": {"min": 200.0, "max": 300.0}, "protein_g": {"min": 37.0, "max": 56.0}, "fat_g": {"min": 4.0, "max": 6.0}, "carbs_g": {"min": 0.0, "max": 0.0}}`

```text
Estimated calories: 200-300 kcal
Protein: 37-56 g
Fat: 4-6 g
Carbs: 0-0 g
Main assumptions:
* chicken breast cooked: 120-180 g (assumed standard portion).
Confidence: medium
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

### na_golden_009

- Input: `Сколько калорий в двух кусках цельнозернового хлеба?`
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

### na_golden_010

- Input: `Macros for 100g avocado`
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

### na_golden_011

- Input: `Сколько калорий в 150 г твердого тофу?`
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

### na_golden_013

- Input: `Сколько БЖУ в 200 г греческого йогурта 2%?`
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

### na_golden_015

- Input: `Сколько калорий в 30 г миндаля?`
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

### na_golden_017

- Input: `Сколько калорий в 200 г жареного стейка из говядины?`
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

### na_golden_018

- Input: `Calories and macros in 200g cooked lentils`
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

### na_golden_019

- Input: `Сколько БЖУ в 200 г вареного нута?`
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

### na_golden_020

- Input: `Calories in one fried egg with 1 tsp oil`
- Status: `fail`
- Classification: `real_system_failure`
- Expected behavior: `estimate`
- Actual behavior: `estimate`
- Failed checks: calories: predicted range does not overlap acceptable range
- Unknown checks: none
- Parsed nutrition: `{"calories_kcal": {"min": 150.0, "max": 240.0}, "protein_g": {"min": 6.0, "max": 8.0}, "fat_g": {"min": 14.0, "max": 24.0}, "carbs_g": {"min": 0.0, "max": 0.0}}`

```text
Estimated calories: 150-240 kcal
Protein: 6-8 g
Fat: 14-24 g
Carbs: 0-0 g
Main assumptions:
* egg: 45-60 g (assumed standard portion).
* olive oil: 10-18 g (assumed standard portion).
Confidence: medium
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

### na_golden_024

- Input: `Calories and macros in a Big Mac`
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

### na_golden_025

- Input: `Сколько калорий в средней картошке фри из Макдональдса?`
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

### na_golden_026

- Input: `How many calories in a 60g butter croissant?`
- Status: `fail`
- Classification: `real_system_failure`
- Expected behavior: `estimate`
- Actual behavior: `estimate`
- Failed checks: calories: predicted range does not overlap acceptable range
- Unknown checks: none
- Parsed nutrition: `{"calories_kcal": {"min": 390.0, "max": 470.0}, "protein_g": {"min": 0.0, "max": 1.0}, "fat_g": {"min": 44.0, "max": 54.0}, "carbs_g": {"min": 0.0, "max": 0.0}}`

```text
Estimated calories: 390-470 kcal
Protein: 0-1 g
Fat: 44-54 g
Carbs: 0-0 g
Main assumptions:
* butter: 54-66 g (explicit gram estimate with small uncertainty).
Confidence: medium
```

### na_golden_027

- Input: `Сколько БЖУ в pain au chocolat 75 г?`
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

### na_golden_028

- Input: `Calories in 100g baguette`
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

### na_golden_029

- Input: `Сколько калорий в столовой ложке Нутеллы, примерно 15 г?`
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

### na_golden_031

- Input: `Сколько калорий в протеиновом батончике 60 г?`
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

### na_golden_032

- Input: `Calories in 30g potato chips`
- Status: `fail`
- Classification: `real_system_failure`
- Expected behavior: `estimate`
- Actual behavior: `estimate`
- Failed checks: calories: predicted range does not overlap acceptable range
- Unknown checks: none
- Parsed nutrition: `{"calories_kcal": {"min": 20.0, "max": 30.0}, "protein_g": {"min": 1.0, "max": 1.0}, "fat_g": {"min": 0.0, "max": 0.0}, "carbs_g": {"min": 5.0, "max": 7.0}}`

```text
Estimated calories: 20-30 kcal
Protein: 1-1 g
Fat: 0-0 g
Carbs: 5-7 g
Main assumptions:
* potato boiled: 27-33 g (explicit gram estimate with small uncertainty).
Confidence: medium
```

### na_golden_033

- Input: `Сколько БЖУ в пачке лапши быстрого приготовления 85 г?`
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

### na_golden_034

- Input: `How many calories in 100g vanilla ice cream?`
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

### na_golden_036

- Input: `Calories and macros in 120g drained canned tuna in water`
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

### na_golden_037

- Input: `Сколько калорий в 30 г темного шоколада?`
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

### na_golden_038

- Input: `Macros for a 125g mozzarella ball`
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

### na_golden_039

- Input: `Сколько БЖУ в 100 г хумуса?`
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

### na_golden_040

- Input: `Calories in 50g granola`
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

### na_golden_041

- Input: `Сколько калорий в салате Цезарь с курицей, примерно 350 г?`
- Status: `fail`
- Classification: `unsupported_current_behavior`
- Expected behavior: `estimate`
- Actual behavior: `clarify`
- Failed checks: behavior: expected estimate, got clarify; must_contain_any: none of ['ккал', 'калор'] found; must_not_contain_any: found ['уточните']
- Unknown checks: calories: answer could not be parsed
- Parsed nutrition: `{}`

```text
Нужно еще немного информации для надежной оценки: Уточните, пожалуйста: какая часть курицы, как продукт был приготовлен.
```

### na_golden_042

- Input: `Calories and macros for a 300g Greek salad`
- Status: `fail`
- Classification: `real_system_failure`
- Expected behavior: `estimate`
- Actual behavior: `estimate`
- Failed checks: calories: predicted range does not overlap acceptable range
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

### na_golden_043

- Input: `Сколько БЖУ в тарелке куриного супа 400 г?`
- Status: `fail`
- Classification: `unsupported_current_behavior`
- Expected behavior: `estimate`
- Actual behavior: `clarify`
- Failed checks: behavior: expected estimate, got clarify; must_contain_any: none of ['ккал', 'калор'] found; must_not_contain_any: found ['уточните']
- Unknown checks: calories: answer could not be parsed
- Parsed nutrition: `{}`

```text
Нужно еще немного информации для надежной оценки: Уточните, пожалуйста: какая часть курицы, как продукт был приготовлен.
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

### na_golden_045

- Input: `Сколько калорий в 250 г пельменей со сметаной?`
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

### na_golden_046

- Input: `Calories in 250g potato vareniki`
- Status: `fail`
- Classification: `real_system_failure`
- Expected behavior: `estimate`
- Actual behavior: `estimate`
- Failed checks: calories: predicted range does not overlap acceptable range
- Unknown checks: none
- Parsed nutrition: `{"calories_kcal": {"min": 200.0, "max": 240.0}, "protein_g": {"min": 4.0, "max": 5.0}, "fat_g": {"min": 0.0, "max": 0.0}, "carbs_g": {"min": 45.0, "max": 55.0}}`

```text
Estimated calories: 200-240 kcal
Protein: 4-5 g
Fat: 0-0 g
Carbs: 45-55 g
Main assumptions:
* potato boiled: 225-275 g (explicit gram estimate with small uncertainty).
Confidence: medium
```

### na_golden_047

- Input: `Сколько БЖУ в двух блинах со сметаной, примерно 200 г?`
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

### na_golden_048

- Input: `Calories and macros in 200g syrniki`
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

### na_golden_049

- Input: `Сколько калорий в гречке с курицей, порция 350 г?`
- Status: `fail`
- Classification: `unsupported_current_behavior`
- Expected behavior: `estimate`
- Actual behavior: `clarify`
- Failed checks: behavior: expected estimate, got clarify; must_contain_any: none of ['ккал', 'калор'] found; must_not_contain_any: found ['уточните']
- Unknown checks: calories: answer could not be parsed
- Parsed nutrition: `{}`

```text
Нужно еще немного информации для надежной оценки: Уточните, пожалуйста: какая часть курицы, как продукт был приготовлен.
```

### na_golden_051

- Input: `Сколько калорий в шакшуке 300 г?`
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

### na_golden_052

- Input: `Calories in avocado toast with one egg`
- Status: `fail`
- Classification: `real_system_failure`
- Expected behavior: `estimate`
- Actual behavior: `estimate`
- Failed checks: calories: predicted range does not overlap acceptable range
- Unknown checks: none
- Parsed nutrition: `{"calories_kcal": {"min": 160.0, "max": 220.0}, "protein_g": {"min": 9.0, "max": 12.0}, "fat_g": {"min": 5.0, "max": 7.0}, "carbs_g": {"min": 17.0, "max": 27.0}}`

```text
Estimated calories: 160-220 kcal
Protein: 9-12 g
Fat: 5-7 g
Carbs: 17-27 g
Main assumptions:
* egg: 45-55 g (estimated from egg count).
* bread: 35-55 g (assumed standard portion).
Confidence: medium
```

### na_golden_053

- Input: `Сколько БЖУ в сэндвиче с индейкой 220 г?`
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

### na_golden_054

- Input: `Calories and macros in a tuna sandwich`
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

### na_golden_055

- Input: `Сколько калорий в клаб-сэндвиче 300 г?`
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

### na_golden_056

- Input: `How many calories in a cheeseburger, about 180g?`
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

### na_golden_057

- Input: `Сколько БЖУ в буррито с курицей 400 г?`
- Status: `fail`
- Classification: `unsupported_current_behavior`
- Expected behavior: `estimate`
- Actual behavior: `clarify`
- Failed checks: behavior: expected estimate, got clarify; must_contain_any: none of ['ккал', 'калор'] found; must_not_contain_any: found ['уточните']
- Unknown checks: calories: answer could not be parsed
- Parsed nutrition: `{}`

```text
Нужно еще немного информации для надежной оценки: Уточните, пожалуйста: какая часть курицы, как продукт был приготовлен.
```

### na_golden_058

- Input: `Calories in two beef tacos, about 300g total`
- Status: `fail`
- Classification: `real_system_failure`
- Expected behavior: `estimate`
- Actual behavior: `estimate`
- Failed checks: calories: predicted range does not overlap acceptable range
- Unknown checks: none
- Parsed nutrition: `{"calories_kcal": {"min": 250.0, "max": 420.0}, "protein_g": {"min": 26.0, "max": 44.0}, "fat_g": {"min": 15.0, "max": 26.0}, "carbs_g": {"min": 0.0, "max": 0.0}}`

```text
Estimated calories: 250-420 kcal
Protein: 26-44 g
Fat: 15-26 g
Carbs: 0-0 g
Main assumptions:
* beef cooked: 100-170 g (assumed standard portion).
Confidence: medium
```

### na_golden_061

- Input: `Сколько калорий в лазанье 350 г?`
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

### na_golden_062

- Input: `How many calories in 2 slices of Margherita pizza, about 250g?`
- Status: `fail`
- Classification: `real_system_failure`
- Expected behavior: `estimate`
- Actual behavior: `estimate`
- Failed checks: calories: predicted range does not overlap acceptable range
- Unknown checks: none
- Parsed nutrition: `{"calories_kcal": {"min": 270.0, "max": 430.0}, "protein_g": {"min": 11.0, "max": 18.0}, "fat_g": {"min": 10.0, "max": 16.0}, "carbs_g": {"min": 33.0, "max": 53.0}}`

```text
Estimated calories: 270-430 kcal
Protein: 11-18 g
Fat: 10-16 g
Carbs: 33-53 g
Main assumptions:
* pizza: 100-160 g (assumed standard portion).
Confidence: medium
```

### na_golden_064

- Input: `Calories and macros in a 12-piece sushi set`
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

### na_golden_065

- Input: `Сколько калорий в поке с лососем 450 г?`
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

### na_golden_066

- Input: `How many calories in a pork ramen bowl, about 600g?`
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

### na_golden_067

- Input: `Сколько БЖУ в фо бо 600 г?`
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

### na_golden_068

- Input: `Calories in chicken pad thai, 450g`
- Status: `fail`
- Classification: `unsupported_current_behavior`
- Expected behavior: `estimate`
- Actual behavior: `clarify`
- Failed checks: behavior: expected estimate, got clarify; must_contain_any: none of ['kcal', 'calories'] found; must_not_contain_any: found ['please clarify']
- Unknown checks: calories: answer could not be parsed
- Parsed nutrition: `{}`

```text
I need one more detail to estimate this reliably: Please clarify what cut of chicken it was, how it was prepared.
```

### na_golden_069

- Input: `Сколько калорий в жареном рисе с яйцом и курицей 400 г?`
- Status: `fail`
- Classification: `unsupported_current_behavior`
- Expected behavior: `estimate`
- Actual behavior: `clarify`
- Failed checks: behavior: expected estimate, got clarify; must_contain_any: none of ['ккал', 'калор'] found; must_not_contain_any: found ['уточните']
- Unknown checks: calories: answer could not be parsed
- Parsed nutrition: `{}`

```text
Нужно еще немного информации для надежной оценки: Уточните, пожалуйста: какая часть курицы.
```

### na_golden_070

- Input: `Macros for a falafel wrap, about 350g`
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

### na_golden_071

- Input: `Сколько БЖУ в шаурме с курицей 350 г?`
- Status: `fail`
- Classification: `unsupported_current_behavior`
- Expected behavior: `estimate`
- Actual behavior: `clarify`
- Failed checks: behavior: expected estimate, got clarify; must_contain_any: none of ['ккал', 'калор'] found; must_not_contain_any: found ['уточните']
- Unknown checks: calories: answer could not be parsed
- Parsed nutrition: `{}`

```text
Нужно еще немного информации для надежной оценки: Уточните, пожалуйста: какая часть курицы, как продукт был приготовлен.
```

### na_golden_072

- Input: `Calories in a kebab plate with rice, about 500g`
- Status: `fail`
- Classification: `unsupported_current_behavior`
- Expected behavior: `estimate`
- Actual behavior: `clarify`
- Failed checks: behavior: expected estimate, got clarify; must_contain_any: none of ['kcal', 'calories'] found; must_not_contain_any: found ['please clarify']
- Unknown checks: calories: answer could not be parsed
- Parsed nutrition: `{}`

```text
I need one more detail to estimate this reliably: Please clarify how it was prepared.
```

### na_golden_073

- Input: `Сколько калорий в тарелке хумуса с питой, примерно 300 г?`
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

### na_golden_074

- Input: `Calories and macros in a quinoa veggie bowl, 400g`
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

### na_golden_075

- Input: `Сколько БЖУ в грибном ризотто 350 г?`
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

### na_golden_076

- Input: `How many calories in fish and chips, about 450g?`
- Status: `fail`
- Classification: `unsupported_current_behavior`
- Expected behavior: `estimate`
- Actual behavior: `clarify`
- Failed checks: behavior: expected estimate, got clarify; must_contain_any: none of ['kcal', 'calories'] found; must_not_contain_any: found ['please clarify']
- Unknown checks: calories: answer could not be parsed
- Parsed nutrition: `{}`

```text
I need one more detail to estimate this reliably: Please clarify what type of fish it was, how it was prepared.
```

### na_golden_077

- Input: `Сколько калорий в стейке с картошкой фри, порция 500 г?`
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

### na_golden_078

- Input: `Calories in 6 chicken nuggets`
- Status: `fail`
- Classification: `unsupported_current_behavior`
- Expected behavior: `estimate`
- Actual behavior: `clarify`
- Failed checks: behavior: expected estimate, got clarify; must_contain_any: none of ['kcal', 'calories'] found
- Unknown checks: calories: answer could not be parsed
- Parsed nutrition: `{}`

```text
I need one more detail to estimate this reliably: What cut of chicken, how much, and how was it prepared?
```

### na_golden_079

- Input: `Сколько БЖУ в овощном супе 400 г?`
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

### na_golden_080

- Input: `Calories and macros in 400g lentil soup`
- Status: `fail`
- Classification: `real_system_failure`
- Expected behavior: `estimate`
- Actual behavior: `estimate`
- Failed checks: calories: predicted range does not overlap acceptable range
- Unknown checks: none
- Parsed nutrition: `{"calories_kcal": {"min": 110.0, "max": 180.0}, "protein_g": {"min": 5.0, "max": 8.0}, "fat_g": {"min": 4.0, "max": 6.0}, "carbs_g": {"min": 16.0, "max": 26.0}}`

```text
Estimated calories: 110-180 kcal
Protein: 5-8 g
Fat: 4-6 g
Carbs: 16-26 g
Main assumptions:
* vegetable soup: 250-400 g (assumed standard portion).
Confidence: medium
```

### na_golden_081

- Input: `Сколько калорий в овсянке на молоке с бананом, порция 350 г?`
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

### na_golden_082

- Input: `Calories in 3 pancakes with syrup`
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

### na_golden_083

- Input: `Сколько БЖУ в мюсли с йогуртом и ягодами 350 г?`
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

### na_golden_084

- Input: `Calories and macros in 200g 5% cottage cheese`
- Status: `fail`
- Classification: `real_system_failure`
- Expected behavior: `estimate`
- Actual behavior: `estimate`
- Failed checks: calories: predicted range does not overlap acceptable range
- Unknown checks: none
- Parsed nutrition: `{"calories_kcal": {"min": 100.0, "max": 180.0}, "protein_g": {"min": 6.0, "max": 11.0}, "fat_g": {"min": 8.0, "max": 15.0}, "carbs_g": {"min": 0.0, "max": 1.0}}`

```text
Estimated calories: 100-180 kcal
Protein: 6-11 g
Fat: 8-15 g
Carbs: 0-1 g
Main assumptions:
* cheese: 25-45 g (assumed standard portion).
Confidence: medium
```

### na_golden_085

- Input: `Сколько калорий в цезарь-ролле с курицей 300 г?`
- Status: `fail`
- Classification: `unsupported_current_behavior`
- Expected behavior: `estimate`
- Actual behavior: `clarify`
- Failed checks: behavior: expected estimate, got clarify; must_contain_any: none of ['ккал', 'калор'] found; must_not_contain_any: found ['уточните']
- Unknown checks: calories: answer could not be parsed
- Parsed nutrition: `{}`

```text
Нужно еще немного информации для надежной оценки: Уточните, пожалуйста: какая часть курицы, как продукт был приготовлен.
```

### na_golden_087

- Input: `Сколько калорий в салате с помидорами и моцареллой 300 г?`
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

### na_golden_088

- Input: `Calories in scrambled eggs with toast`
- Status: `fail`
- Classification: `real_system_failure`
- Expected behavior: `estimate`
- Actual behavior: `estimate`
- Failed checks: calories: predicted range does not overlap acceptable range
- Unknown checks: none
- Parsed nutrition: `{"calories_kcal": {"min": 160.0, "max": 230.0}, "protein_g": {"min": 9.0, "max": 13.0}, "fat_g": {"min": 5.0, "max": 7.0}, "carbs_g": {"min": 17.0, "max": 27.0}}`

```text
Estimated calories: 160-230 kcal
Protein: 9-13 g
Fat: 5-7 g
Carbs: 17-27 g
Main assumptions:
* egg: 45-60 g (assumed standard portion).
* bread: 35-55 g (assumed standard portion).
Confidence: medium
```

### na_golden_089

- Input: `Сколько БЖУ в салате с креветками гриль 350 г?`
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

### na_golden_090

- Input: `Calories in 250g cottage cheese with honey`
- Status: `fail`
- Classification: `real_system_failure`
- Expected behavior: `estimate`
- Actual behavior: `estimate`
- Failed checks: calories: predicted range does not overlap acceptable range
- Unknown checks: none
- Parsed nutrition: `{"calories_kcal": {"min": 100.0, "max": 180.0}, "protein_g": {"min": 6.0, "max": 11.0}, "fat_g": {"min": 8.0, "max": 15.0}, "carbs_g": {"min": 0.0, "max": 1.0}}`

```text
Estimated calories: 100-180 kcal
Protein: 6-11 g
Fat: 8-15 g
Carbs: 0-1 g
Main assumptions:
* cheese: 25-45 g (assumed standard portion).
Confidence: medium
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

### na_golden_093

- Input: `Сколько БЖУ в тарелке пасты?`
- Status: `fail`
- Classification: `real_system_failure`
- Expected behavior: `clarify`
- Actual behavior: `estimate`
- Failed checks: behavior: expected clarify, got estimate; must_contain_any: none of ['уточ', 'нужн'] found; must_not_contain_any: found ['Оценка калорий', 'ккал']
- Unknown checks: none
- Parsed nutrition: `{"calories_kcal": {"min": 250.0, "max": 380.0}, "protein_g": {"min": 9.0, "max": 14.0}, "fat_g": {"min": 1.0, "max": 2.0}, "carbs_g": {"min": 49.0, "max": 74.0}}`

```text
Оценка калорий: 250-380 ккал
Белки: 9-14 г
Жиры: 1-2 г
Углеводы: 49-74 г
Основные допущения:
* паста: 160-240 г (принята стандартная порция).
Уверенность: средняя
```

### na_golden_094

- Input: `Calories in a burger?`
- Status: `fail`
- Classification: `real_system_failure`
- Expected behavior: `clarify`
- Actual behavior: `estimate`
- Failed checks: behavior: expected clarify, got estimate; must_contain_any: none of ['need', 'clarify', 'detail'] found; must_not_contain_any: found ['Estimated calories']
- Unknown checks: none
- Parsed nutrition: `{"calories_kcal": {"min": 460.0, "max": 710.0}, "protein_g": {"min": 22.0, "max": 34.0}, "fat_g": {"min": 18.0, "max": 28.0}, "carbs_g": {"min": 50.0, "max": 78.0}}`

```text
Estimated calories: 460-710 kcal
Protein: 22-34 g
Fat: 18-28 g
Carbs: 50-78 g
Main assumptions:
* hamburger: 180-280 g (assumed standard portion).
Confidence: medium
```

### na_golden_098

- Input: `How many calories in chicken and rice?`
- Status: `fail`
- Classification: `real_system_failure`
- Expected behavior: `clarify`
- Actual behavior: `estimate`
- Failed checks: behavior: expected clarify, got estimate; must_contain_any: none of ['need', 'clarify', 'detail'] found; must_not_contain_any: found ['Estimated calories']
- Unknown checks: none
- Parsed nutrition: `{"calories_kcal": {"min": 390.0, "max": 580.0}, "protein_g": {"min": 41.0, "max": 62.0}, "fat_g": {"min": 5.0, "max": 7.0}, "carbs_g": {"min": 42.0, "max": 62.0}}`

```text
Estimated calories: 390-580 kcal
Protein: 41-62 g
Fat: 5-7 g
Carbs: 42-62 g
Main assumptions:
* cooked white rice: 150-220 g (assumed standard portion).
* chicken breast cooked: 120-180 g (assumed standard portion).
Confidence: medium
```

### na_conv_007_pending_then_new_food_not_merged

- Input: `['Сколько калорий в курице?', 'Сколько калорий в банане?']`
- Status: `fail`
- Classification: `unsupported_current_behavior`
- Expected behavior: `estimate`
- Actual behavior: `clarify`
- Failed checks: behavior: expected estimate, got clarify; must_contain_any: none of ['банан', 'ккал', 'Оценка калорий'] found
- Unknown checks: none
- Parsed nutrition: `{}`

```text
Нужно еще немного информации для надежной оценки: Какие продукты были в блюде и примерно сколько каждого?
```

### na_conv_009_salad_stays_clarification

- Input: `['How many calories in a salad?']`
- Status: `fail`
- Classification: `real_system_failure`
- Expected behavior: `clarify`
- Actual behavior: `estimate`
- Failed checks: behavior: expected clarify, got estimate; must_contain_any: none of ['need', 'detail', 'ingredients', 'dressing'] found; must_not_contain_any: found ['Estimated calories']
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

### na_conv_010_photo_missing_stays_clarification

- Input: `['На фото еда, посчитай']`
- Status: `fail`
- Classification: `likely_dataset_issue`
- Expected behavior: `clarify`
- Actual behavior: `clarify`
- Failed checks: must_contain_any: none of ['фото', 'опишите', 'описание'] found
- Unknown checks: none
- Parsed nutrition: `{}`

```text
Нужно еще немного информации для надежной оценки: Какие продукты были в блюде и примерно сколько каждого?
```
