import logging
import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

from app.tools.fallback_nutrition import is_plain_water_query
from app.tools.food_vocabulary import load_food_vocabulary, normalize_food_query

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class LinkedFoodSpan:
    canonical_name: str
    matched_text: str
    start: int
    end: int
    score: float
    method: str
    is_product: bool = False


@dataclass(frozen=True)
class _IndexEntry:
    canonical_name: str
    text: str
    vector: dict[str, float]
    norm: float
    is_product: bool


class VocabularyEmbeddingLinker:
    """Small deterministic alias linker over the shared food vocabulary.

    This intentionally uses local character n-gram vectors rather than hosted
    embeddings for the first version. The vocabulary is tiny, production behavior
    stays unchanged by default, and the index has no network or API-cost failure
    mode. It still exercises the same nearest-neighbor/cosine fallback shape that
    can later be swapped for a hosted multilingual embedder if quality demands it.
    """

    def __init__(self) -> None:
        vocabulary = load_food_vocabulary()
        self._product_entries = tuple(
            (
                alias,
                product.canonical_product,
                True,
            )
            for product in vocabulary.products
            for alias in product.aliases
        )
        self._food_entries = tuple(
            (
                alias,
                food.name,
                False,
            )
            for food in vocabulary.foods
            for alias in (food.name, *food.aliases)
        )
        self._entries = tuple(
            _IndexEntry(
                canonical_name=canonical_name,
                text=normalize_food_query(text),
                vector=vector,
                norm=_vector_norm(vector),
                is_product=is_product,
            )
            for text, canonical_name, is_product in (*self._product_entries, *self._food_entries)
            if (vector := _embed_text(text))
        )

    def find_mentions(self, text: str, *, threshold: float) -> tuple[LinkedFoodSpan, ...]:
        normalized = normalize_food_query(text)
        if not normalized:
            return ()
        exact = self.find_exact_mentions(normalized)
        if exact:
            return exact
        return self.find_embedding_mentions(normalized, threshold=threshold)

    def find_exact_mentions(self, normalized_text: str) -> tuple[LinkedFoodSpan, ...]:
        candidates: list[LinkedFoodSpan] = []
        candidates.extend(_alias_mentions(normalized_text, self._product_entries, method="exact_alias"))
        for mention in _alias_mentions(normalized_text, self._food_entries, method="exact_alias"):
            if mention.canonical_name == "water" and not is_plain_water_query(normalized_text):
                continue
            candidates.append(mention)
        return _select_non_overlapping(candidates)

    def find_embedding_mentions(
        self,
        normalized_text: str,
        *,
        threshold: float,
    ) -> tuple[LinkedFoodSpan, ...]:
        candidates: list[LinkedFoodSpan] = []
        for span_text, start, end in _candidate_spans(normalized_text):
            link = self.link_span(span_text, threshold=threshold)
            if link is None:
                continue
            if link.canonical_name == "water" and not is_plain_water_query(normalized_text):
                continue
            candidates.append(
                LinkedFoodSpan(
                    canonical_name=link.canonical_name,
                    matched_text=span_text,
                    start=start,
                    end=end,
                    score=link.score,
                    method="embedding",
                    is_product=link.is_product,
                )
            )
        return _select_non_overlapping(candidates)

    def link_span(self, span: str, *, threshold: float) -> LinkedFoodSpan | None:
        normalized = normalize_food_query(span)
        vector = _embed_text(normalized)
        norm = _vector_norm(vector)
        if not vector or norm == 0:
            return None
        best: tuple[float, _IndexEntry] | None = None
        for entry in self._entries:
            score = _cosine(vector, norm, entry)
            if best is None or score > best[0]:
                best = (score, entry)
        if best is None or best[0] < threshold:
            return None
        score, entry = best
        return LinkedFoodSpan(
            canonical_name=entry.canonical_name,
            matched_text=normalized,
            start=0,
            end=len(normalized),
            score=score,
            method="embedding",
            is_product=entry.is_product,
        )


@lru_cache(maxsize=1)
def get_food_linker() -> VocabularyEmbeddingLinker:
    return VocabularyEmbeddingLinker()


def find_embedding_food_mentions(
    text: str,
    *,
    threshold: float,
) -> tuple[LinkedFoodSpan, ...]:
    try:
        return get_food_linker().find_mentions(text, threshold=threshold)
    except Exception as exc:  # pragma: no cover - defensive degradation
        LOGGER.warning("Food embedding linker unavailable; falling back to legacy matcher: %s", exc)
        return ()


def link_food_span(span: str, *, threshold: float) -> LinkedFoodSpan | None:
    try:
        return get_food_linker().link_span(span, threshold=threshold)
    except Exception as exc:  # pragma: no cover - defensive degradation
        LOGGER.warning("Food embedding span link failed; falling back to legacy matcher: %s", exc)
        return None


def record_shadow_disagreement(
    *,
    legacy: tuple[str, ...],
    embedding: tuple[str, ...],
) -> None:
    if legacy == embedding:
        return
    LOGGER.info(
        "Food linker shadow disagreement legacy=%s embedding=%s",
        ",".join(legacy) or "<none>",
        ",".join(embedding) or "<none>",
    )
    try:
        from opentelemetry import trace
    except Exception:  # pragma: no cover - optional tracing dependency
        return
    span = trace.get_current_span()
    if not span or not span.is_recording():
        return
    span.set_attribute("food_linker.shadow.disagreement", True)
    span.set_attribute("food_linker.shadow.legacy", ",".join(legacy))
    span.set_attribute("food_linker.shadow.embedding", ",".join(embedding))


def _alias_mentions(
    normalized_text: str,
    entries: Iterable[tuple[str, str, bool]],
    *,
    method: str,
) -> tuple[LinkedFoodSpan, ...]:
    candidates: list[LinkedFoodSpan] = []
    seen: set[str] = set()
    for alias, canonical_name, is_product in sorted(
        entries,
        key=lambda item: len(normalize_food_query(item[0])),
        reverse=True,
    ):
        if canonical_name in seen:
            continue
        normalized_alias = normalize_food_query(alias)
        match = re.search(rf"\b{re.escape(normalized_alias)}\b", normalized_text)
        if match is None:
            continue
        seen.add(canonical_name)
        candidates.append(
            LinkedFoodSpan(
                canonical_name=canonical_name,
                matched_text=match.group(0),
                start=match.start(),
                end=match.end(),
                score=1.0,
                method=method,
                is_product=is_product,
            )
        )
    return tuple(candidates)


def _select_non_overlapping(candidates: list[LinkedFoodSpan]) -> tuple[LinkedFoodSpan, ...]:
    selected: list[LinkedFoodSpan] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (item.score, item.end - item.start, item.is_product),
        reverse=True,
    ):
        if any(
            candidate.start < current.end and candidate.end > current.start
            for current in selected
        ):
            continue
        if any(current.canonical_name == candidate.canonical_name for current in selected):
            continue
        selected.append(candidate)
    return tuple(sorted(selected, key=lambda item: item.start))


def _candidate_spans(normalized_text: str, *, max_tokens: int = 4) -> tuple[tuple[str, int, int], ...]:
    token_matches = tuple(re.finditer(r"[a-zа-я0-9]+", normalized_text))
    spans: list[tuple[str, int, int]] = []
    for start_index in range(len(token_matches)):
        for end_index in range(start_index + 1, min(len(token_matches), start_index + max_tokens) + 1):
            start = token_matches[start_index].start()
            end = token_matches[end_index - 1].end()
            text = normalized_text[start:end]
            if len(text) < 3 or text in _STOP_WORDS:
                continue
            spans.append((text, start, end))
    return tuple(spans)


def _embed_text(text: str) -> dict[str, float]:
    normalized = normalize_food_query(text)
    if not normalized:
        return {}
    compact = f" {normalized} "
    counts: Counter[str] = Counter()
    for ngram_size in (2, 3, 4):
        if len(compact) < ngram_size:
            continue
        for index in range(len(compact) - ngram_size + 1):
            counts[f"{ngram_size}:{compact[index:index + ngram_size]}"] += 1
    return {key: float(value) for key, value in counts.items()}


def _vector_norm(vector: dict[str, float]) -> float:
    return math.sqrt(sum(value * value for value in vector.values()))


def _cosine(vector: dict[str, float], norm: float, entry: _IndexEntry) -> float:
    if norm == 0 or entry.norm == 0:
        return 0.0
    dot = sum(value * entry.vector.get(key, 0.0) for key, value in vector.items())
    return dot / (norm * entry.norm)


_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "calorie",
    "calories",
    "for",
    "how",
    "in",
    "is",
    "kcal",
    "many",
    "much",
    "of",
    "the",
    "what",
    "бжу",
    "в",
    "и",
    "калории",
    "калорий",
    "ккал",
    "примерно",
    "сколько",
}
