import logging
import re
from functools import lru_cache

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from openai import OpenAI
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.schemas.safety import ModerationDecision

LOGGER = logging.getLogger(__name__)

load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: SecretStr | None = None
    telegram_bot_token: SecretStr | None = None
    bot_auth_secret: SecretStr | None = None
    usda_api_key: SecretStr | None = None

    openai_text_model: str = "gpt-4.1-mini"
    openai_vision_model: str = "gpt-4.1-mini"
    openai_critic_model: str = "gpt-4.1-mini"
    openai_moderation_enabled: bool = True

    nutrition_cache_dir: str = ".cache/nutrition-agent"
    temp_image_dir: str = "/tmp/nutrition-agent-images"
    auth_db_path: str = "data/auth.sqlite3"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reveal_secret(secret: SecretStr | None) -> str | None:
    return secret.get_secret_value() if secret else None


def has_openai_key(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(reveal_secret(settings.openai_api_key))


def build_chat_model(model_name: str, *, temperature: float = 0.0) -> ChatOpenAI:
    settings = get_settings()
    api_key = reveal_secret(settings.openai_api_key)
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for LLM calls")
    return ChatOpenAI(model=model_name, temperature=temperature, api_key=api_key)


PROMPT_INJECTION_PATTERNS = (
    r"ignore (all )?(previous|prior|above) instructions",
    r"reveal (your )?(system|developer) prompt",
    r"reveal (your )?(system|developer) instructions",
    r"tell me (your )?(system|developer) prompt",
    r"print (your )?(system|developer) prompt",
    r"jailbreak",
    r"\bdan mode\b",
    r"bypass (safety|policy|instructions)",
    r"you are now",
)

HACKING_PATTERNS = (
    r"\bhack\b",
    r"\bexploit\b",
    r"steal (a )?(token|password|api key)",
    r"telegram bot token",
    r"bypass authentication",
)

UNSAFE_DIET_PATTERNS = (
    r"crash diet",
    r"lose \d+\s*kg in (a )?(week|few days)",
    r"lose \d+\s*pounds in (a )?(week|few days)",
    r"\bstarve\b",
    r"\bpurge\b",
    r"\blaxatives?\b",
    r"\bpro ana\b",
    r"\banorexia\b",
    r"\bbulimia\b",
    r"eating disorder",
)

MEDICAL_PATTERNS = (
    r"\bdiagnos(e|is)\b",
    r"\btreat\b.*\b(diabetes|kidney|cancer|disease|condition)\b",
    r"medical nutrition therapy",
    r"\binsulin\b.*\bdose\b",
)


def local_moderate_text(text: str | None) -> ModerationDecision:
    if not text:
        return ModerationDecision()
    lowered = text.lower()

    checks = (
        (PROMPT_INJECTION_PATTERNS, "prompt_injection", "Prompt-injection request."),
        (HACKING_PATTERNS, "hacking", "Hacking or credential-extraction request."),
        (UNSAFE_DIET_PATTERNS, "unsafe", "Unsafe diet or eating-disorder-related request."),
        (MEDICAL_PATTERNS, "medical", "Medical diagnosis or medical nutrition therapy request."),
    )
    for patterns, category, reason in checks:
        if any(re.search(pattern, lowered) for pattern in patterns):
            return ModerationDecision(allowed=False, category=category, reason=reason)

    return ModerationDecision()


class ModerationService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def moderate_text(self, text: str | None) -> ModerationDecision:
        local = local_moderate_text(text)
        if not local.allowed:
            return local
        if not text or not self.settings.openai_moderation_enabled:
            return local

        api_key = reveal_secret(self.settings.openai_api_key)
        if not api_key:
            return local

        try:
            client = OpenAI(api_key=api_key)
            response = client.moderations.create(model="omni-moderation-latest", input=text)
            result = response.results[0]
            if result.flagged:
                categories = result.categories.model_dump()
                flagged = sorted(name for name, value in categories.items() if value)
                return ModerationDecision(
                    allowed=False,
                    category="unsafe",
                    reason=f"OpenAI moderation flagged: {', '.join(flagged)}",
                )
        except Exception as exc:  # pragma: no cover - network/API fallback
            LOGGER.warning("OpenAI moderation unavailable; using local fallback: %s", exc)

        return local
