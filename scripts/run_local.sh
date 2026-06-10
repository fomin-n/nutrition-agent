#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f .env ]]; then
  echo "No .env found. Copy .env.example to .env and fill OPENAI_API_KEY and TELEGRAM_BOT_TOKEN." >&2
fi

uv run python -m app.bot.telegram_bot

