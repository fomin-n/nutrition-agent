import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.i18n import LanguageCode, detect_language
from app.llm.client import get_settings, local_moderate_text
from app.schemas.outputs import FinalEstimate
from app.tools.fallback_nutrition import normalize_food_query
from app.tools.food_normalization import find_food_mentions
from app.tools.food_query import normalize_food_description, product_profiles_in_text

MessageRole = Literal["user", "assistant"]


@dataclass(frozen=True)
class MemoryConfig:
    recent_messages: int = 10
    summarize_after_messages: int = 16
    summary_max_chars: int = 2000


class MemoryMessage(BaseModel):
    role: MessageRole
    text: str
    created_at: str


class MemoryFact(BaseModel):
    fact_type: str
    key: str
    value: str
    updated_at: str


class UnresolvedTask(BaseModel):
    kind: str = "nutrition_estimate"
    food_name: str
    canonical_query: str | None = None
    brand: str | None = None
    subtype: str | None = None
    variant: str | None = None
    language: LanguageCode = "unknown"
    quantity: str | None = None
    preparation: str | None = None
    cut: str | None = None
    required_fields: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    original_text: str = ""
    updated_at: str


class MemoryContext(BaseModel):
    user_id: str
    conversation_id: str
    summary: str = ""
    unresolved_task: UnresolvedTask | None = None
    recent_messages: list[MemoryMessage] = Field(default_factory=list)
    facts: list[MemoryFact] = Field(default_factory=list)


class PreparedMemoryInput(BaseModel):
    original_text: str | None
    effective_text: str | None
    unresolved_task: UnresolvedTask | None = None
    used_followup: bool = False


class MemoryService:
    def __init__(self, db_path: str | Path, config: MemoryConfig | None = None) -> None:
        self.db_path = Path(db_path)
        self.config = config or MemoryConfig()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._harden_permissions()

    @classmethod
    def from_settings(cls) -> "MemoryService":
        settings = get_settings()
        db_path = settings.memory_db_path or str(Path(settings.auth_db_path).with_name("memory.sqlite3"))
        return cls(
            db_path,
            MemoryConfig(
                recent_messages=settings.memory_recent_messages,
                summarize_after_messages=settings.memory_summarize_after_messages,
                summary_max_chars=settings.memory_summary_max_chars,
            ),
        )

    def load_context(self, user_id: str | int, conversation_id: str | int) -> MemoryContext:
        user_key = str(user_id)
        conversation_key = str(conversation_id)
        with self._connection() as conn:
            state = conn.execute(
                """
                SELECT summary, unresolved_task_json
                FROM conversation_state
                WHERE user_id = ? AND conversation_id = ?
                """,
                (user_key, conversation_key),
            ).fetchone()
            messages = list(
                conn.execute(
                    """
                    SELECT role, text, created_at
                    FROM conversation_messages
                    WHERE user_id = ? AND conversation_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (user_key, conversation_key, self.config.recent_messages),
                )
            )
            facts = list(
                conn.execute(
                    """
                    SELECT fact_type, key, value, updated_at
                    FROM user_memory_facts
                    WHERE user_id = ?
                    ORDER BY fact_type, key
                    """,
                    (user_key,),
                )
            )

        unresolved_task = None
        if state and state["unresolved_task_json"]:
            unresolved_task = UnresolvedTask.model_validate_json(state["unresolved_task_json"])

        return MemoryContext(
            user_id=user_key,
            conversation_id=conversation_key,
            summary=state["summary"] if state else "",
            unresolved_task=unresolved_task,
            recent_messages=[
                MemoryMessage(role=row["role"], text=row["text"], created_at=row["created_at"])
                for row in reversed(messages)
            ],
            facts=[MemoryFact(**dict(row)) for row in facts],
        )

    def prepare_input(self, text: str | None, context: MemoryContext) -> PreparedMemoryInput:
        if not text or context.unresolved_task is None:
            return PreparedMemoryInput(original_text=text, effective_text=text)

        if not _looks_like_followup(text, context.unresolved_task):
            return PreparedMemoryInput(original_text=text, effective_text=text)

        task = _merge_task_fields(context.unresolved_task, text)
        return PreparedMemoryInput(
            original_text=text,
            effective_text=_task_to_text(task),
            unresolved_task=task,
            used_followup=True,
        )

    def record_turn(
        self,
        *,
        user_id: str | int,
        conversation_id: str | int,
        user_text: str | None,
        assistant_text: str,
        effective_text: str | None = None,
        final_state: dict[str, Any] | None = None,
        prepared_task: UnresolvedTask | None = None,
    ) -> None:
        user_key = str(user_id)
        conversation_key = str(conversation_id)
        now = _now()
        final = _final_estimate(final_state)
        unresolved_task = self._next_unresolved_task(
            final=final,
            text=effective_text or user_text,
            prepared_task=prepared_task,
        )
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO conversation_state
                    (user_id, conversation_id, summary, unresolved_task_json, created_at, updated_at)
                VALUES (?, ?, '', ?, ?, ?)
                ON CONFLICT(user_id, conversation_id) DO UPDATE SET
                    unresolved_task_json = excluded.unresolved_task_json,
                    updated_at = excluded.updated_at
                """,
                (
                    user_key,
                    conversation_key,
                    unresolved_task.model_dump_json() if unresolved_task else None,
                    now,
                    now,
                ),
            )
            self._append_message(conn, user_key, conversation_key, "user", _user_memory_text(user_text), now)
            self._append_message(conn, user_key, conversation_key, "assistant", assistant_text, now)
            self._upsert_long_term_facts(conn, user_key, user_text, now)
            self._compact_if_needed(conn, user_key, conversation_key, now)

    def _next_unresolved_task(
        self,
        *,
        final: FinalEstimate | None,
        text: str | None,
        prepared_task: UnresolvedTask | None,
    ) -> UnresolvedTask | None:
        if final is not None and not final.is_clarification:
            return None
        if prepared_task is not None:
            return _refresh_missing_fields(prepared_task)
        if final is not None and final.is_clarification:
            return derive_unresolved_task(text)
        return None

    def _append_message(
        self,
        conn: sqlite3.Connection,
        user_id: str,
        conversation_id: str,
        role: MessageRole,
        text: str,
        now: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO conversation_messages (user_id, conversation_id, role, text, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, conversation_id, role, text, now),
        )

    def _compact_if_needed(
        self,
        conn: sqlite3.Connection,
        user_id: str,
        conversation_id: str,
        now: str,
    ) -> None:
        count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM conversation_messages
            WHERE user_id = ? AND conversation_id = ?
            """,
            (user_id, conversation_id),
        ).fetchone()["count"]
        if count <= self.config.summarize_after_messages:
            return

        rows_to_summarize = list(
            conn.execute(
                """
                SELECT id, role, text
                FROM conversation_messages
                WHERE user_id = ? AND conversation_id = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (user_id, conversation_id, max(0, count - self.config.recent_messages)),
            )
        )
        if not rows_to_summarize:
            return

        old_summary = conn.execute(
            """
            SELECT summary
            FROM conversation_state
            WHERE user_id = ? AND conversation_id = ?
            """,
            (user_id, conversation_id),
        ).fetchone()["summary"]
        summary = _merge_summary(
            old_summary,
            [
                f"{row['role']}: {_compact_text(row['text'], 160)}"
                for row in rows_to_summarize
            ],
            max_chars=self.config.summary_max_chars,
        )
        conn.execute(
            """
            UPDATE conversation_state
            SET summary = ?, updated_at = ?
            WHERE user_id = ? AND conversation_id = ?
            """,
            (summary, now, user_id, conversation_id),
        )
        conn.executemany(
            "DELETE FROM conversation_messages WHERE id = ?",
            [(row["id"],) for row in rows_to_summarize],
        )

    def _upsert_long_term_facts(
        self,
        conn: sqlite3.Connection,
        user_id: str,
        text: str | None,
        now: str,
    ) -> None:
        for fact_type, key, value in extract_long_term_facts(text):
            conn.execute(
                """
                INSERT INTO user_memory_facts (user_id, fact_type, key, value, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'user_message', ?, ?)
                ON CONFLICT(user_id, fact_type, key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (user_id, fact_type, key, value, now, now),
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with closing(self._connect()) as conn, conn:
            yield conn

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversation_state (
                    user_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    unresolved_task_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, conversation_id)
                );

                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_conversation_messages_scope
                    ON conversation_messages(user_id, conversation_id, id);

                CREATE TABLE IF NOT EXISTS user_memory_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    fact_type TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, fact_type, key)
                );

                CREATE INDEX IF NOT EXISTS idx_user_memory_facts_user
                    ON user_memory_facts(user_id);
                """
            )

    def _harden_permissions(self) -> None:
        try:
            self.db_path.parent.chmod(0o700)
            self.db_path.chmod(0o600)
        except OSError:
            pass


@lru_cache(maxsize=1)
def get_memory_service() -> MemoryService:
    return MemoryService.from_settings()


def derive_unresolved_task(text: str | None) -> UnresolvedTask | None:
    if not text:
        return None
    language = detect_language(text)
    normalized = normalize_food_query(text)
    target = _identify_food_target(normalized)
    if target is None:
        return None
    task = UnresolvedTask(
        food_name=target["food_name"],
        canonical_query=target["canonical_query"],
        brand=target["brand"],
        language=language,
        required_fields=target["required_fields"],
        original_text=text,
        updated_at=_now(),
    )
    return _merge_task_fields(task, text)


def extract_long_term_facts(text: str | None) -> list[tuple[str, str, str]]:
    if not text:
        return []
    normalized = normalize_food_query(text)
    facts: list[tuple[str, str, str]] = []

    allergy_patterns = (
        r"\ballergic to ([a-zа-яё ,]+)",
        r"\ballergy to ([a-zа-яё ,]+)",
        r"\bаллергия на ([a-zа-яё ,]+)",
    )
    for pattern in allergy_patterns:
        match = re.search(pattern, normalized)
        if match:
            for item in _split_fact_items(match.group(1)):
                facts.append(("allergy", item, item))

    preference_map = {
        "vegetarian": ("dietary_preference", "vegetarian", "vegetarian"),
        "vegan": ("dietary_preference", "vegan", "vegan"),
        "gluten free": ("dietary_preference", "gluten_free", "gluten free"),
        "lactose intolerant": ("dietary_preference", "lactose_intolerant", "lactose intolerant"),
        "вегетариан": ("dietary_preference", "vegetarian", "vegetarian"),
        "веган": ("dietary_preference", "vegan", "vegan"),
        "не ем мясо": ("dietary_preference", "no_meat", "does not eat meat"),
    }
    for phrase, fact in preference_map.items():
        if phrase in normalized:
            facts.append(fact)

    if re.search(r"\b(prefer|use|show).{0,20}\b(grams|gram|metric)\b", normalized) or re.search(
        r"\b(предпочитаю|показывай|используй).{0,20}\b(грамм|граммы|метрич)",
        normalized,
    ):
        facts.append(("measurement_preference", "units", "metric"))

    goal_patterns = {
        r"\b(goal is to|trying to|want to).{0,20}\blose weight\b": "lose weight",
        r"\b(goal is to|trying to|want to).{0,20}\bgain muscle\b": "gain muscle",
        r"\bцель.{0,20}\bпохуд": "lose weight",
        r"\bхочу.{0,20}\bпохуд": "lose weight",
        r"\bцель.{0,20}\bнабрать мыш": "gain muscle",
    }
    for pattern, value in goal_patterns.items():
        if re.search(pattern, normalized):
            facts.append(("goal", value.replace(" ", "_"), value))

    return _dedupe_facts(facts)


def memory_context_prompt(context: dict[str, Any] | MemoryContext | None) -> str:
    if not context:
        return ""
    if isinstance(context, dict):
        context = MemoryContext.model_validate(context)
    lines: list[str] = []
    if context.summary:
        lines.append(f"Older conversation summary: {context.summary}")
    if context.unresolved_task:
        task = context.unresolved_task
        missing = ", ".join(task.missing_fields) or "none"
        lines.append(
            "Current unresolved task: "
            f"{task.canonical_query or task.food_name}; brand={task.brand or 'unknown'}; "
            f"subtype={task.subtype or 'unknown'}; quantity={task.quantity or 'unknown'}; "
            f"preparation={task.preparation or 'unknown'}; cut={task.cut or 'unknown'}; "
            f"variant={task.variant or 'unknown'}; "
            f"missing={missing}."
        )
    if context.facts:
        facts = "; ".join(f"{fact.fact_type}:{fact.key}={fact.value}" for fact in context.facts[:12])
        lines.append(f"Stable user facts: {facts}")
    if context.recent_messages:
        compact_messages = [
            f"user: {_compact_text(message.text, 120)}"
            for message in context.recent_messages[-6:]
            if message.role == "user"
        ]
        if compact_messages:
            lines.append("Recent user messages: " + " | ".join(compact_messages))
    return "\n".join(lines)


def _final_estimate(final_state: dict[str, Any] | None) -> FinalEstimate | None:
    if not final_state:
        return None
    final = final_state.get("final_estimate")
    if isinstance(final, FinalEstimate):
        return final
    if isinstance(final, dict):
        return FinalEstimate.model_validate(final)
    return None


def _looks_like_followup(text: str, task: UnresolvedTask) -> bool:
    if not local_moderate_text(text).allowed:
        return False
    normalized = normalize_food_query(text)
    if not normalized:
        return False

    fields = _extract_task_fields(normalized)
    target = _identify_food_target(normalized)
    if target is not None and not _targets_are_compatible(task, target, fields):
        return False
    if _looks_like_new_request(normalized) and target is None:
        return False

    token_count = len(normalized.split())
    if token_count > 12:
        return False

    supplied_fields = {name for name, value in fields.items() if value}
    if target is not None and _targets_are_compatible(task, target, fields):
        return True
    if not supplied_fields:
        return False

    expected = set(task.missing_fields)
    return bool(supplied_fields & expected) or bool(supplied_fields & {"brand", "variant"})


def _merge_task_fields(task: UnresolvedTask, text: str) -> UnresolvedTask:
    normalized = normalize_food_query(text)
    fields = _extract_task_fields(normalized)
    target = _identify_food_target(normalized)
    canonical_query = task.canonical_query
    food_name = task.food_name
    if fields["subtype"]:
        canonical_query = _subtype_query(fields["subtype"])
        food_name = fields["subtype"]
    elif target is not None and _targets_are_compatible(task, target, fields):
        canonical_query = target["canonical_query"] or canonical_query

    merged = task.model_copy(
        update={
            "food_name": food_name,
            "canonical_query": canonical_query,
            "brand": fields["brand"] or task.brand,
            "subtype": fields["subtype"] or task.subtype,
            "variant": fields["variant"] or task.variant,
            "quantity": fields["quantity"] or task.quantity,
            "preparation": fields["preparation"] or task.preparation,
            "cut": fields["cut"] or task.cut,
            "updated_at": _now(),
        }
    )
    return _refresh_missing_fields(merged)


def _refresh_missing_fields(task: UnresolvedTask) -> UnresolvedTask:
    required_fields = task.required_fields or _legacy_required_fields(task)
    missing = [field for field in required_fields if not getattr(task, field, None)]
    return task.model_copy(update={"missing_fields": missing, "updated_at": _now()})


def _task_to_text(task: UnresolvedTask) -> str:
    parts = [_food_text(task)]
    if task.variant:
        parts.append(_localized_variant(task.variant, task.language))
    if task.quantity:
        parts.append(task.quantity)
    if task.preparation:
        parts.append(_localized_preparation(task.preparation, task.language))
    return ", ".join(part for part in parts if part)


def _food_text(task: UnresolvedTask) -> str:
    language = task.language
    if task.subtype:
        food = _localized_food(task.subtype, language)
    elif task.food_name == "chicken" and task.cut:
        food = _localized_chicken_cut(task.cut, language)
    else:
        food = _localized_food(task.canonical_query or task.food_name, language)
    if task.brand and normalize_food_query(task.brand) not in normalize_food_query(food):
        return f"{task.brand} {food}"
    return food


def _extract_task_fields(normalized: str) -> dict[str, str | None]:
    query = normalize_food_description(normalized)
    return {
        "quantity": _extract_quantity(normalized),
        "preparation": _extract_preparation(normalized),
        "cut": _extract_cut(normalized),
        "subtype": _extract_subtype(normalized),
        "brand": query.brand,
        "variant": _extract_variant(normalized),
    }


def _extract_quantity(normalized: str) -> str | None:
    match = re.search(
        r"\b(\d+(?:[.,]\d+)?)\s*(g|gram|grams|kg|oz|ounce|ounces|ml|milliliter|milliliters|"
        r"cup|cups|serving|servings|can|cans|г|гр|грамм|грамма|граммов|кг|мл|чашка|чашки|"
        r"порция|порции|банка|банки)\b",
        normalized,
    )
    if match:
        return f"{match.group(1).replace(',', '.')} {match.group(2)}"
    count_match = re.search(
        r"\b(one|a|одна|один|одно)\s+(can|serving|cup|банка|порция|чашка)\b",
        normalized,
    )
    return f"1 {count_match.group(2)}" if count_match else None


def _extract_preparation(normalized: str) -> str | None:
    preparation_terms = {
        "fried": (r"\bfried\b", r"\bжарен\w*\b", r"\bпожарен\w*\b"),
        "grilled": (r"\bgrilled\b", r"\bгрил\w*\b"),
        "baked": (r"\bbaked\b", r"\broasted\b", r"\bзапеч\w*\b"),
        "boiled": (r"\bboiled\b", r"\bварен\w*\b", r"\bотвар\w*\b"),
        "raw": (r"\braw\b", r"\bсыр(?:ой|ая|ое|ые|ого|ому|ым|ых)\b"),
        "cooked": (r"\bcooked\b", r"\bготов\w*\b"),
    }
    for value, patterns in preparation_terms.items():
        if any(re.search(pattern, normalized) for pattern in patterns):
            return value
    return None


def _extract_cut(normalized: str) -> str | None:
    cut_terms = {
        "breast": ("breast", "груд", "филе"),
        "thigh": ("thigh", "бедр"),
        "wing": ("wing", "крыл"),
        "leg": ("leg", "leg", "ножк", "голен"),
    }
    for value, terms in cut_terms.items():
        if any(term in normalized for term in terms):
            return value
    return None


def _extract_subtype(normalized: str) -> str | None:
    subtype_terms = {
        "salmon": (r"\bsalmon\b", r"\bлосос\w*\b", r"\bсемг\w*\b"),
        "tuna": (r"\btuna\b", r"\bтунц\w*\b"),
        "cod": (r"\bcod\b", r"\bтреск\w*\b"),
        "trout": (r"\btrout\b", r"\bфорел\w*\b"),
    }
    for value, patterns in subtype_terms.items():
        if any(re.search(pattern, normalized) for pattern in patterns):
            return value
    return None


def _extract_variant(normalized: str) -> str | None:
    if any(
        re.search(pattern, normalized)
        for pattern in (
            r"\bzero\b",
            r"\bdiet\b",
            r"\blight\b",
            r"\bsugar free\b",
            r"\bбез сахара\b",
            r"\bзеро\b",
            r"\bлайт\b",
        )
    ):
        return "zero_sugar"
    return None


def _identify_food_target(normalized: str) -> dict[str, Any] | None:
    if re.search(r"\b(chicken|куриц\w*|курин\w*)\b", normalized):
        return _target("chicken", "chicken", ["cut", "quantity", "preparation"])
    if re.search(r"\b(fish|рыб\w*)\b", normalized):
        return _target("fish", "fish", ["subtype", "quantity", "preparation"])
    if re.search(r"\b(rice|рис\w*)\b", normalized):
        return _target("rice", "rice", ["quantity", "preparation"])
    if re.search(r"\b(yogurt|yoghurt|йогурт\w*)\b", normalized):
        brand = normalize_food_description(normalized).brand
        return _target("yogurt", "yogurt", ["quantity"], brand=brand)

    product_profiles = product_profiles_in_text(normalized)
    if product_profiles:
        product = product_profiles[0]
        required = [] if product.default_serving_amount else ["quantity"]
        if product.category == "chocolate_bar":
            required = ["quantity"]
        return _target(
            product.canonical_product,
            product.canonical_product,
            required,
            brand=product.brand,
        )

    matched_food = _matched_fallback_food(normalized)
    if matched_food:
        return _target(matched_food, matched_food, ["quantity"])
    return None


def _target(
    food_name: str,
    canonical_query: str,
    required_fields: list[str],
    *,
    brand: str | None = None,
) -> dict[str, Any]:
    return {
        "food_name": food_name,
        "canonical_query": canonical_query,
        "brand": brand,
        "required_fields": required_fields,
    }


def _matched_fallback_food(normalized: str) -> str | None:
    mentions = find_food_mentions(normalized)
    return mentions[0].canonical_name if mentions else None


def _targets_are_compatible(
    task: UnresolvedTask,
    target: dict[str, Any],
    fields: dict[str, str | None],
) -> bool:
    task_names = {
        normalize_food_query(task.food_name),
        normalize_food_query(task.canonical_query or ""),
    }
    target_names = {
        normalize_food_query(target["food_name"]),
        normalize_food_query(target["canonical_query"]),
    }
    if task_names & target_names:
        return True
    if task.food_name == "fish" and fields.get("subtype"):
        return True
    if task.food_name == "chicken" and fields.get("cut"):
        return True
    return bool(task.brand and task.brand == target.get("brand"))


def _looks_like_new_request(normalized: str) -> bool:
    return bool(
        re.search(
            r"\b(how many|how much|estimate|calculate|what can you do|"
            r"сколько|оцени|рассчитай|что ты умеешь|что можешь)\b",
            normalized,
        )
        or "?" in normalized
    )


def _legacy_required_fields(task: UnresolvedTask) -> list[str]:
    if task.food_name == "chicken":
        return ["cut", "quantity", "preparation"]
    return ["quantity"]


def _subtype_query(subtype: str) -> str:
    return {
        "salmon": "salmon",
        "tuna": "tuna",
        "cod": "cod",
        "trout": "trout",
    }.get(subtype, subtype)


def _localized_food(food: str, language: LanguageCode) -> str:
    if language != "ru":
        return food
    return {
        "chicken": "курица",
        "fish": "рыба",
        "rice": "рис",
        "yogurt": "йогурт",
        "salmon": "лосось",
        "tuna": "тунец",
        "cod": "треска",
        "trout": "форель",
        "cooked white rice": "рис",
        "yogurt plain": "йогурт",
        "chicken breast cooked": "курица",
        "salmon cooked": "лосось",
    }.get(food, food)


def _localized_chicken_cut(cut: str, language: LanguageCode) -> str:
    if language != "ru":
        return f"chicken {cut}"
    return {
        "breast": "куриная грудка",
        "thigh": "куриное бедро",
        "wing": "куриное крыло",
        "leg": "куриная ножка",
    }.get(cut, "курица")


def _localized_preparation(preparation: str, language: LanguageCode) -> str:
    if language != "ru":
        return preparation
    return {
        "fried": "жареный",
        "grilled": "на гриле",
        "baked": "запеченный",
        "boiled": "вареный",
        "raw": "сырой",
        "cooked": "приготовленный",
    }.get(preparation, preparation)


def _localized_variant(variant: str, language: LanguageCode) -> str:
    if variant == "zero_sugar":
        return "без сахара" if language == "ru" else "zero sugar"
    return variant


def _user_memory_text(text: str | None) -> str:
    return text if text else "[image request]"


def _split_fact_items(value: str) -> list[str]:
    value = re.split(r"\b(?:and|but|also|и|но|а также)\b", value, maxsplit=1)[0]
    value = value.strip(" .,:;")
    items = re.split(r",|\band\b|\bи\b", value)
    return [item.strip() for item in items if 2 <= len(item.strip()) <= 40]


def _dedupe_facts(facts: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str, str]] = []
    for fact_type, key, value in facts:
        dedupe_key = (fact_type, key)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        result.append((fact_type, key, value))
    return result


def _merge_summary(old_summary: str, lines: list[str], *, max_chars: int) -> str:
    addition = " | ".join(lines)
    summary = addition if not old_summary else f"{old_summary} | {addition}"
    if len(summary) <= max_chars:
        return summary
    return summary[-max_chars:].lstrip(" |")


def _compact_text(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 1)].rstrip() + "..."


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
