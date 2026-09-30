import logging
import re
from functools import lru_cache
from typing import Literal

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from openai import OpenAI
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.execution import bounded_timeout, request_budget_active
from app.schemas.safety import Confidence, ModerationDecision

LOGGER = logging.getLogger(__name__)

load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: SecretStr | None = None
    telegram_bot_token: SecretStr | None = None
    bot_auth_secret: SecretStr | None = None
    usda_api_key: SecretStr | None = None
    fatsecret_client_id: SecretStr | None = None
    fatsecret_client_secret: SecretStr | None = None

    openai_text_model: str = "gpt-4.1-mini"
    openai_vision_model: str = "gpt-4.1-mini"
    openai_vision_escalation_model: str | None = "gpt-5.4-mini"
    openai_vision_escalation_confidence: Confidence = "low"
    openai_critic_model: str = "gpt-4.1-mini"
    openai_request_timeout_seconds: float = Field(default=45.0, gt=0)
    openai_max_retries: int = Field(default=1, ge=0, le=5)
    request_deadline_seconds: float = Field(default=90.0, gt=0, le=300)
    openai_max_output_tokens: int = Field(default=2048, ge=256, le=8192)
    openai_scope_max_output_tokens: int = Field(default=512, ge=128, le=2048)
    openai_critic_max_output_tokens: int = Field(default=512, ge=128, le=2048)
    openai_vision_max_output_tokens: int = Field(default=2048, ge=256, le=8192)
    openai_reasoning_effort: Literal["none", "low", "medium", "high"] | None = None
    openai_text_reasoning_effort: Literal["none", "low", "medium", "high"] | None = None
    usda_detail_limit: int = Field(default=3, ge=0, le=10)
    critic_max_iterations: int = Field(default=2, ge=0, le=3)
    qualitative_critic_enabled: bool = True
    max_image_bytes: int = Field(default=10_000_000, ge=1024, le=20_000_000)
    openai_moderation_enabled: bool = True

    bot_access_mode: Literal["invite", "open"] = "open"
    enable_phoenix_tracing: bool = False
    phoenix_project_name: str = "nutrition-agent"
    phoenix_collector_endpoint: str = "http://127.0.0.1:6006/v1/traces"

    nutrition_cache_dir: str = ".cache/nutrition-agent"
    nutrition_retrieval_max_workers: int = Field(default=3, ge=1, le=8)
    nutrition_diagnostics_include_raw: bool = False
    nutrition_diagnostics_max_payload_chars: int = 2000
    food_linker_embeddings_enabled: bool = False
    food_linker_shadow_enabled: bool = False
    food_linker_similarity_threshold: float = Field(default=0.62, ge=0.0, le=1.0)
    temp_image_dir: str = "/tmp/nutrition-agent-images"
    auth_db_path: str = "data/auth.sqlite3"
    usage_db_path: str | None = None
    bot_concurrent_updates: int = Field(default=8, ge=1, le=64)
    bot_per_user_in_flight_limit: int = Field(default=1, ge=0, le=16)
    bot_daily_user_request_limit: int = Field(default=100, ge=0)
    bot_daily_global_request_limit: int = Field(default=1000, ge=0)
    bot_user_burst_request_limit_per_minute: int = Field(default=6, ge=0)
    bot_daily_user_photo_limit: int = Field(default=25, ge=0)
    bot_global_usage_warning_ratio: float = Field(default=0.8, ge=0.0, le=1.0)
    bot_admin_chat_id: str | None = None
    memory_db_path: str | None = None
    memory_recent_messages: int = 10
    memory_summarize_after_messages: int = 16
    memory_summary_max_chars: int = 2000
    memory_retention_days: int = Field(default=0, ge=0)
    usage_counter_retention_days: int = Field(default=7, ge=0)
    health_http_enabled: bool = False
    health_http_host: str = "127.0.0.1"
    health_http_port: int = Field(default=8080, ge=0, le=65535)

    enable_usda: bool = True
    enable_fatsecret: bool = True
    enable_open_food_facts: bool = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reveal_secret(secret: SecretStr | None) -> str | None:
    return secret.get_secret_value() if secret else None


def has_openai_key(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(reveal_secret(settings.openai_api_key))


def build_chat_model(model_name: str, *, temperature: float = 0.0, task: str = "text") -> ChatOpenAI:
    settings = get_settings()
    api_key = reveal_secret(settings.openai_api_key)
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for LLM calls")
    reasoning = settings.openai_reasoning_effort
    if task == "text" and settings.openai_text_reasoning_effort is not None:
        reasoning = settings.openai_text_reasoning_effort
    if model_name.startswith("gpt-6-luna") and reasoning is None:
        reasoning = "none"
    if reasoning is not None and model_name.startswith("gpt-4."):
        raise ValueError("reasoning effort is unsupported by GPT-4 models")
    output_limit = {
        "scope": settings.openai_scope_max_output_tokens,
        "critic": settings.openai_critic_max_output_tokens,
        "vision": settings.openai_vision_max_output_tokens,
    }.get(task, settings.openai_max_output_tokens)
    return ChatOpenAI(
        model=model_name,
        temperature=temperature if reasoning in {None, "none"} else None,
        reasoning_effort=reasoning,
        max_tokens=output_limit,
        api_key=api_key,
        timeout=bounded_timeout(settings.openai_request_timeout_seconds),
        max_retries=0 if request_budget_active() else settings.openai_max_retries,
    )


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
    r"игнорируй(те)?.{0,40}(инструкци|правил|указани)",
    r"забудь(те)?.{0,40}(инструкци|правил|указани)",
    r"(покажи|выведи|раскрой|расскажи).{0,40}(системн\w*|developer|разработч\w*)"
    r".{0,30}(промпт|инструкци|сообщени)",
    r"(системн\w*|developer|разработч\w*).{0,30}(промпт|инструкци|сообщени)"
    r".{0,40}(покажи|выведи|раскрой)",
    r"обойди(те)?.{0,40}(безопасност|политик|инструкци|ограничени|правил)",
    r"\bджейлбрейк\b",
    r"\bdan режим\b",
    r"\bрежим dan\b",
    r"\bты теперь (не|будешь|являешься|должен|должна)\b",
)

HACKING_PATTERNS = (
    r"\bhack\b",
    r"\bexploit\b",
    r"steal (a )?(token|password|api key)",
    r"telegram bot token",
    r"bypass authentication",
    r"\bвзлом\w*\b",
    r"\bхакн\w*\b",
    r"(укради|украсть|получи|получить|достань|добыть).{0,40}"
    r"(токен|парол|api[ -]?ключ|ключ|секрет)",
    r"(токен|парол|api[ -]?ключ|ключ|секрет).{0,40}"
    r"(укради|украсть|получи|получить|достань|добыть)",
    r"(обойди|обойти).{0,40}(аутентификац|авторизац|логин|доступ)",
    r"telegram.{0,20}(бот)?.{0,20}токен",
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
    r"\bголодат\w*\b",
    r"\bголодани\w*\b",
    r"\bанорекси\w*\b",
    r"\bбулими\w*\b",
    r"\bслабительн\w*\b",
    r"\bпро[-\s]?ана\b",
    r"(похудеть|сбросить).{0,20}\b\d+\s*(кг|килограмм\w*)\b.{0,30}"
    r"(за неделю|за нескольк\w* дн\w*|за \d+\s*дн\w*)",
)

MEDICAL_PATTERNS = (
    r"\bdiagnos(e|is)\b",
    r"\btreat\b.*\b(diabetes|kidney|cancer|disease|condition)\b",
    r"medical nutrition therapy",
    r"\binsulin\b.*\bdose\b",
    r"\bдиагноз\b",
    r"\bдиагностир\w*\b",
    r"\bлечи\w*.{0,40}(диабет|почк\w*|рак|болезн\w*|заболеван\w*)",
    r"\bлечение\b.{0,40}(диабет|почк\w*|рак|болезн\w*|заболеван\w*)",
    r"(доз\w*|сколько).{0,30}инсулин\w*",
    r"инсулин\w*.{0,30}доз\w*",
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

    def moderate_text(self, text: str | None, *, request_id: str | None = None) -> ModerationDecision:
        local = local_moderate_text(text)
        if not local.allowed:
            return local
        if not text or not self.settings.openai_moderation_enabled:
            return local

        api_key = reveal_secret(self.settings.openai_api_key)
        if not api_key:
            return local

        try:
            client = OpenAI(
                api_key=api_key,
                timeout=bounded_timeout(self.settings.openai_request_timeout_seconds),
                max_retries=0 if request_budget_active() else self.settings.openai_max_retries,
            )
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
            LOGGER.warning(
                "OpenAI moderation unavailable request_id=%s error_type=%s error=%s; "
                "using local fallback",
                request_id,
                type(exc).__name__,
                "redacted",
            )

        return local
