# AGENTS.md

This document is for contributors and coding agents working on `nutrition-agent`. It explains the implementation structure and operational guardrails without including private deployment details.

## Repository Structure

- `app/bot/`: Telegram polling bot entry point and handlers.
- `app/graph/`: LangGraph state definition and graph assembly.
- `app/graph/nodes/`: graph node implementations.
- `app/llm/`: settings, OpenAI/LangChain client setup, and structured-output helpers.
- `app/auth/`: SQLite-backed Telegram authorization service.
- `app/cli/`: operational CLI helpers such as access-key management.
- `app/i18n.py`: lightweight English/Russian language detection and localized user-facing strings.
- `app/tools/`: USDA, Open Food Facts, fallback nutrition, cache, and image helpers.
- `app/schemas/`: Pydantic models for inputs, safety decisions, nutrition values, and outputs.
- `app/evals/`: lightweight adversarial eval data and runner.
- `tests/`: offline unit tests.
- `systemd/`: generic example service unit.
- `scripts/`: generic example deployment helper.

## Graph State And Nodes

The graph uses `NutritionGraphState`, a typed dictionary carrying:

- raw and normalized user input
- moderation and scope decisions
- meal understanding
- ingredient nutrition matches
- deterministic macro totals
- final estimate
- critic result
- errors and test flags

Primary graph flow:

1. `normalize_input`
2. `input_moderation`
3. `scope_classifier`
4. `route`
5. one of `refuse`, `ask_clarification`, `parse_text_meal`, `recognize_dish_photo`, `combine_text_and_image`, or `recognize_packaging`
6. `retrieve_nutrition`
7. `calculate_macros`
8. `synthesize_answer`
9. `critic`
10. `output_moderation`

Keep the graph controlled. Do not replace it with an unconstrained agent loop.

## Pydantic Schemas

Structured schemas live under `app/schemas/`:

- `inputs.py`: raw and normalized user input.
- `safety.py`: moderation decisions, scope routes, confidence values, and refusals.
- `nutrition.py`: ingredient estimates, per-100 g nutrition, matched ingredient nutrition, and macro ranges.
- `outputs.py`: final estimate and critic result.

Any model output that changes routing or calculation inputs should be parsed through a schema.

## Model Configuration

Settings are loaded from environment variables via `pydantic-settings`:

- `OPENAI_TEXT_MODEL`
- `OPENAI_VISION_MODEL`
- `OPENAI_CRITIC_MODEL`
- `OPENAI_MODERATION_ENABLED`

The current MVP uses OpenAI models for structured classification/parsing and image recognition when enabled. Macro arithmetic, final formatting, and critic sanity checks are deterministic Python in the current implementation.

The service supports English and Russian user-facing text for meal estimates, clarification questions, and refusals. The local router/parser includes explicit Russian nutrition vocabulary and common food aliases; image-only requests default to English because no text language signal exists.

## Authorization Design

Telegram access control is implemented in `app/auth/service.py`.

- `BOT_AUTH_SECRET` is required.
- Access keys are generated with `secrets.token_urlsafe(32)`.
- Raw access keys are printed once by the CLI and are never stored.
- SQLite stores only an HMAC-SHA256 digest of each key.
- Keys are one-time by default and are marked used on successful login.
- Authorized Telegram users are stored in SQLite.
- Unauthorized users must not trigger graph execution, OpenAI calls, image download, image processing, or nutrition lookup.

CLI commands:

```bash
python -m app.cli.auth create-key --label "demo-user"
python -m app.cli.auth list-keys
python -m app.cli.auth revoke-key <key_id>
python -m app.cli.auth list-users
python -m app.cli.auth revoke-user <telegram_user_id>
```

## Nutrition Calculation

LLMs should not calculate totals. They may extract structured ingredients and estimated gram ranges. The deterministic calculator:

- maps each ingredient to per-100 g calories, protein, fat, and carbs
- scales each nutrient by `grams_min` and `grams_max`
- aggregates ingredient ranges
- rounds calories to practical 10 kcal increments
- checks macro-derived energy consistency

## Data Source Adapters

- `fallback_nutrition.py`: small local table for common foods.
- `usda_client.py`: USDA FoodData Central search with cache and nutrient-name normalization.
- `open_food_facts_client.py`: Open Food Facts product lookup for packaged foods.
- `cache.py`: JSON file cache.

External data should be treated as untrusted and potentially incomplete.

## Tests And Evals

Run:

```bash
uv run pytest
uv run ruff check .
uv run python -m app.evals.run_eval --mock
```

Tests must run without real API keys.

## Generic Deployment Notes

Use Telegram polling for the MVP. No public HTTP port, reverse proxy, firewall rule, or TLS certificate is required for the bot itself.

Deployment variables should be supplied by the target environment, not committed:

- `OPENAI_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `BOT_AUTH_SECRET`
- optional `USDA_API_KEY`
- optional model overrides
- optional `AUTH_DB_PATH`

Do not commit real server addresses, usernames, hostnames, private paths, service logs, `.env` files, auth databases, downloaded images, or access keys.

## Security Checklist For Contributors

- Run current-tree and history searches before public releases.
- Confirm `.env`, SQLite files, logs, caches, downloaded images, and virtual environments are ignored.
- Keep test user names and IDs synthetic.
- Do not log API URLs containing bot tokens.
- Keep authorization checks before any expensive or sensitive operation.
- Treat prompt text, OCR text, captions, API responses, and user input as untrusted data.
- Do not add deployment-specific IPs, usernames, hostnames, or private infrastructure details to docs or scripts.

## Coding Conventions

- Python 3.11+.
- Keep functions small and testable.
- Use async for Telegram and network-facing paths where appropriate.
- Prefer Pydantic schemas for structured data.
- Keep comments short and useful.
- Do not introduce broad refactors while making narrow safety changes.
