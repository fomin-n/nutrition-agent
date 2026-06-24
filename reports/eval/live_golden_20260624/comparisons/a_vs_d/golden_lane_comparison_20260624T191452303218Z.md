# NutritionAgent Golden Lane Comparison

- Comparison ID: `golden_lane_comparison_20260624T191452303218Z`
- Fallback run: `golden_baseline_all_20260624T182303844174Z`
- LLM-path run: `golden_baseline_all_20260624T184717207399Z`
- Fallback config: `{"use_llm": false, "llm_mode": "off", "llm_stub_version": null, "live_providers": false, "macro_ranges_are_advisory": true, "openai_text_model": "gpt-4.1-mini", "openai_vision_model": "gpt-4.1-mini", "openai_critic_model": "gpt-4.1-mini", "temperature": 0.0, "critic_max_iterations": 2, "openai_moderation_enabled": true, "provider_flags": {"usda": true, "fatsecret": true, "open_food_facts": true}, "nutrition_cache_dir": null, "pricing": {"gpt-4.1-mini": {"input": 0.4, "cached_input": 0.1, "output": 1.6, "source": "https://developers.openai.com/api/docs/models/gpt-4.1-mini", "checked_date": "2026-06-24"}}}`
- LLM config: `{"use_llm": true, "llm_mode": "live", "llm_stub_version": null, "live_providers": true, "macro_ranges_are_advisory": true, "openai_text_model": "gpt-4.1-mini", "openai_vision_model": "gpt-4.1-mini", "openai_critic_model": "gpt-4.1-mini", "temperature": 0.0, "critic_max_iterations": 2, "openai_moderation_enabled": true, "provider_flags": {"usda": true, "fatsecret": true, "open_food_facts": true}, "nutrition_cache_dir": "/tmp/nutrition-agent-live-eval-cache-afbec09", "pricing": {"gpt-4.1-mini": {"input": 0.4, "cached_input": 0.1, "output": 1.6, "source": "https://developers.openai.com/api/docs/models/gpt-4.1-mini", "checked_date": "2026-06-24"}}}`
- Common examples: 111
- Fallback passed: 69
- LLM-path passed: 66
- Pass-rate delta: -2.7%

## Status Flips

- Fail -> pass: 14
- Pass -> fail: 17

### Fail -> Pass

| ID | Input | Fallback | LLM-path |
|---|---|---|---|
| `na_conv_010_photo_missing_stays_clarification` | `['На фото еда, посчитай']` | `fail` | `pass` |
| `na_golden_030` | `Macros in 2 tbsp peanut butter, 32g` | `fail` | `pass` |
| `na_golden_039` | `Сколько БЖУ в 100 г хумуса?` | `fail` | `pass` |
| `na_golden_049` | `Сколько калорий в гречке с курицей, порция 350 г?` | `fail` | `pass` |
| `na_golden_053` | `Сколько БЖУ в сэндвиче с индейкой 220 г?` | `fail` | `pass` |
| `na_golden_054` | `Calories and macros in a tuna sandwich` | `fail` | `pass` |
| `na_golden_055` | `Сколько калорий в клаб-сэндвиче 300 г?` | `fail` | `pass` |
| `na_golden_057` | `Сколько БЖУ в буррито с курицей 400 г?` | `fail` | `pass` |
| `na_golden_064` | `Calories and macros in a 12-piece sushi set` | `fail` | `pass` |
| `na_golden_066` | `How many calories in a pork ramen bowl, about 600g?` | `fail` | `pass` |
| `na_golden_069` | `Сколько калорий в жареном рисе с яйцом и курицей 400 г?` | `fail` | `pass` |
| `na_golden_070` | `Macros for a falafel wrap, about 350g` | `fail` | `pass` |
| `na_golden_076` | `How many calories in fish and chips, about 450g?` | `fail` | `pass` |
| `na_golden_082` | `Calories in 3 pancakes with syrup` | `fail` | `pass` |

### Pass -> Fail

| ID | Input | Fallback | LLM-path |
|---|---|---|---|
| `na_golden_003` | `Сколько БЖУ в одном вареном яйце?` | `pass` | `fail` |
| `na_golden_010` | `Macros for 100g avocado` | `pass` | `fail` |
| `na_golden_011` | `Сколько калорий в 150 г твердого тофу?` | `pass` | `fail` |
| `na_golden_014` | `Calories in 250ml 2% milk` | `pass` | `fail` |
| `na_golden_016` | `Macros for 30g cheddar cheese` | `pass` | `fail` |
| `na_golden_020` | `Calories in one fried egg with 1 tsp oil` | `pass` | `fail` |
| `na_golden_023` | `Сколько калорий в банке Coca-Cola Zero 330 мл?` | `pass` | `fail` |
| `na_golden_033` | `Сколько БЖУ в пачке лапши быстрого приготовления 85 г?` | `pass` | `fail` |
| `na_golden_035` | `Сколько калорий и белка в 850 г натурального скира?` | `pass` | `fail` |
| `na_golden_041` | `Сколько калорий в салате Цезарь с курицей, примерно 350 г?` | `pass` | `fail` |
| `na_golden_042` | `Calories and macros for a 300g Greek salad` | `pass` | `fail` |
| `na_golden_050` | `Macros for a 3-egg omelette with cheese` | `pass` | `fail` |
| `na_golden_052` | `Calories in avocado toast with one egg` | `pass` | `fail` |
| `na_golden_062` | `How many calories in 2 slices of Margherita pizza, about 250g?` | `pass` | `fail` |
| `na_golden_063` | `Сколько БЖУ в одном куске пиццы пепперони 125 г?` | `pass` | `fail` |
| `na_golden_079` | `Сколько БЖУ в овощном супе 400 г?` | `pass` | `fail` |
| `na_golden_084` | `Calories and macros in 200g 5% cottage cheese` | `pass` | `fail` |

## Per-Case Status

| ID | Fallback | LLM-path |
|---|---|---|
| `na_conv_001_ru_chicken_three_turns` | `pass` | `pass` |
| `na_conv_002_en_chicken_three_turns` | `pass` | `pass` |
| `na_conv_003_ru_fish_followup` | `pass` | `pass` |
| `na_conv_004_en_rice_followup` | `pass` | `pass` |
| `na_conv_005_ru_danone_yogurt_followup` | `pass` | `pass` |
| `na_conv_006_pending_then_unsafe_not_merged` | `pass` | `pass` |
| `na_conv_007_pending_then_new_food_not_merged` | `pass` | `pass` |
| `na_conv_008_cola_after_previous_food_not_contaminated` | `pass` | `pass` |
| `na_conv_009_salad_stays_clarification` | `pass` | `pass` |
| `na_conv_010_photo_missing_stays_clarification` | `fail` | `pass` |
| `na_golden_001` | `pass` | `pass` |
| `na_golden_002` | `pass` | `pass` |
| `na_golden_003` | `pass` | `fail` |
| `na_golden_004` | `pass` | `pass` |
| `na_golden_005` | `pass` | `pass` |
| `na_golden_006` | `pass` | `pass` |
| `na_golden_007` | `pass` | `pass` |
| `na_golden_008` | `pass` | `pass` |
| `na_golden_009` | `pass` | `pass` |
| `na_golden_010` | `pass` | `fail` |
| `na_golden_011` | `pass` | `fail` |
| `na_golden_012` | `pass` | `pass` |
| `na_golden_013` | `pass` | `pass` |
| `na_golden_014` | `pass` | `fail` |
| `na_golden_015` | `pass` | `pass` |
| `na_golden_016` | `pass` | `fail` |
| `na_golden_017` | `pass` | `pass` |
| `na_golden_018` | `pass` | `pass` |
| `na_golden_019` | `pass` | `pass` |
| `na_golden_020` | `pass` | `fail` |
| `na_golden_021` | `pass` | `pass` |
| `na_golden_022` | `pass` | `pass` |
| `na_golden_023` | `pass` | `fail` |
| `na_golden_024` | `pass` | `pass` |
| `na_golden_025` | `pass` | `pass` |
| `na_golden_026` | `pass` | `pass` |
| `na_golden_027` | `pass` | `pass` |
| `na_golden_028` | `pass` | `pass` |
| `na_golden_029` | `pass` | `pass` |
| `na_golden_030` | `fail` | `pass` |
| `na_golden_031` | `pass` | `pass` |
| `na_golden_032` | `pass` | `pass` |
| `na_golden_033` | `pass` | `fail` |
| `na_golden_034` | `pass` | `pass` |
| `na_golden_035` | `pass` | `fail` |
| `na_golden_036` | `pass` | `pass` |
| `na_golden_037` | `pass` | `pass` |
| `na_golden_038` | `fail` | `fail` |
| `na_golden_039` | `fail` | `pass` |
| `na_golden_040` | `pass` | `pass` |
| `na_golden_041` | `pass` | `fail` |
| `na_golden_042` | `pass` | `fail` |
| `na_golden_043` | `fail` | `fail` |
| `na_golden_044` | `pass` | `pass` |
| `na_golden_045` | `pass` | `pass` |
| `na_golden_046` | `fail` | `fail` |
| `na_golden_047` | `fail` | `fail` |
| `na_golden_048` | `fail` | `fail` |
| `na_golden_049` | `fail` | `pass` |
| `na_golden_050` | `pass` | `fail` |
| `na_golden_051` | `fail` | `fail` |
| `na_golden_052` | `pass` | `fail` |
| `na_golden_053` | `fail` | `pass` |
| `na_golden_054` | `fail` | `pass` |
| `na_golden_055` | `fail` | `pass` |
| `na_golden_056` | `pass` | `pass` |
| `na_golden_057` | `fail` | `pass` |
| `na_golden_058` | `fail` | `fail` |
| `na_golden_059` | `fail` | `fail` |
| `na_golden_060` | `pass` | `pass` |
| `na_golden_061` | `fail` | `fail` |
| `na_golden_062` | `pass` | `fail` |
| `na_golden_063` | `pass` | `fail` |
| `na_golden_064` | `fail` | `pass` |
| `na_golden_065` | `fail` | `fail` |
| `na_golden_066` | `fail` | `pass` |
| `na_golden_067` | `fail` | `fail` |
| `na_golden_068` | `fail` | `fail` |
| `na_golden_069` | `fail` | `pass` |
| `na_golden_070` | `fail` | `pass` |
| `na_golden_071` | `fail` | `fail` |
| `na_golden_072` | `fail` | `fail` |
| `na_golden_073` | `pass` | `pass` |
| `na_golden_074` | `fail` | `fail` |
| `na_golden_075` | `fail` | `fail` |
| `na_golden_076` | `fail` | `pass` |
| `na_golden_077` | `fail` | `fail` |
| `na_golden_078` | `fail` | `fail` |
| `na_golden_079` | `pass` | `fail` |
| `na_golden_080` | `fail` | `fail` |
| `na_golden_081` | `fail` | `fail` |
| `na_golden_082` | `fail` | `pass` |
| `na_golden_083` | `fail` | `fail` |
| `na_golden_084` | `pass` | `fail` |
| `na_golden_085` | `fail` | `fail` |
| `na_golden_086` | `fail` | `fail` |
| `na_golden_087` | `fail` | `fail` |
| `na_golden_088` | `fail` | `fail` |
| `na_golden_089` | `fail` | `fail` |
| `na_golden_090` | `fail` | `fail` |
| `na_golden_091` | `pass` | `pass` |
| `na_golden_092` | `pass` | `pass` |
| `na_golden_093` | `pass` | `pass` |
| `na_golden_094` | `pass` | `pass` |
| `na_golden_095` | `pass` | `pass` |
| `na_golden_096` | `pass` | `pass` |
| `na_golden_097` | `pass` | `pass` |
| `na_golden_098` | `fail` | `fail` |
| `na_golden_099` | `pass` | `pass` |
| `na_golden_100` | `pass` | `pass` |
| `na_golden_101` | `pass` | `pass` |
