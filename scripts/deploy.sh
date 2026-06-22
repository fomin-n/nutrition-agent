#!/usr/bin/env bash
set -euo pipefail

SERVER="${SERVER:-deploy-user@example-host}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
APP_DIR="${APP_DIR:-/opt/nutrition-agent}"
SERVICE_USER="${SERVICE_USER:-nutrition-agent}"
SERVICE_NAME="${SERVICE_NAME:-nutrition-agent}"
REPO_URL="${GITHUB_REPO_URL:-}"

if [[ -z "$REPO_URL" ]]; then
  REPO_URL="$(git remote get-url origin 2>/dev/null || true)"
fi

if [[ -z "$REPO_URL" ]]; then
  echo "No Git remote found. Set GITHUB_REPO_URL before deploying." >&2
  exit 2
fi

if [[ ! -f "$SSH_KEY" ]]; then
  echo "SSH key not found: $SSH_KEY" >&2
  exit 2
fi

if ! ssh -o BatchMode=yes -i "$SSH_KEY" "$SERVER" "true"; then
  cat >&2 <<EOF
Cannot connect non-interactively to $SERVER.
Set SERVER, SSH_KEY, APP_DIR, SERVICE_USER, and GITHUB_REPO_URL for your environment.
EOF
  exit 3
fi

ssh -i "$SSH_KEY" "$SERVER" \
  "REPO_URL='$REPO_URL' APP_DIR='$APP_DIR' SERVICE_USER='$SERVICE_USER' SERVICE_NAME='$SERVICE_NAME' bash -s" <<'REMOTE'
set -euo pipefail

if ! sudo -n true 2>/dev/null; then
  echo "Passwordless sudo is required for this generic deploy script." >&2
  exit 4
fi

sudo mkdir -p "$APP_DIR"
sudo chown "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" fetch --all --prune
  git -C "$APP_DIR" pull --ff-only
else
  git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"

if [[ ! -f .env ]]; then
  cat >&2 <<EOF
Missing $APP_DIR/.env.
Create it from .env.example and provide:

OPENAI_API_KEY
TELEGRAM_BOT_TOKEN
BOT_AUTH_SECRET

Optional:
USDA_API_KEY
OPENAI_TEXT_MODEL
OPENAI_VISION_MODEL
OPENAI_CRITIC_MODEL
CRITIC_MAX_ITERATIONS
AUTH_DB_PATH
EOF
  exit 5
fi

if command -v uv >/dev/null 2>&1; then
  uv sync
else
  python3 -m venv .venv
  . .venv/bin/activate
  python -m pip install --upgrade pip
  python -m pip install .
fi

sudo cp systemd/nutrition-agent.service "/etc/systemd/system/$SERVICE_NAME.service"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl status "$SERVICE_NAME" --no-pager
REMOTE
