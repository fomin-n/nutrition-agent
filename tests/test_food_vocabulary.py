import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.graph.nodes.coordinator import classify_scope_locally
from app.tools import food_linker, food_normalization
from app.tools.fallback_nutrition import FALLBACK_FOODS, fallback_names
from app.tools.food_linker import find_embedding_food_mentions, link_food_span
from app.tools.food_normalization import DEFAULT_PORTIONS_G, find_food_mentions
from app.tools.food_query import PRODUCT_ALIASES
from app.tools.food_vocabulary import load_food_vocabulary


def test_vocabulary_loads_canonical_food_data() -> None:
    vocabulary = load_food_vocabulary()

    assert len(vocabulary.foods) == len(FALLBACK_FOODS)
    assert {food.name for food in vocabulary.foods} == {food.name for food in FALLBACK_FOODS}
    assert fallback_names() == vocabulary.fallback_names
    assert DEFAULT_PORTIONS_G["Coca-Cola"] == (330, 330)
    assert vocabulary.food_roles["cooked buckwheat"] == "starch"
    assert vocabulary.food_roles["chicken breast cooked"] == "protein"
    assert vocabulary.localized_food_names["ru"]["oatmeal cooked"] == "овсянка"
    assert [product.canonical_product for product in PRODUCT_ALIASES][:2] == [
        "Coca-Cola Zero Sugar",
        "Coca-Cola",
    ]


def test_frozen_food_detection_baseline_still_matches() -> None:
    rows = json.loads(Path("tests/fixtures/food_detection_baseline.json").read_text())

    for row in rows:
        mentions = [
            {
                "canonical_name": mention.canonical_name,
                "matched_text": mention.matched_text,
                "start": mention.start,
                "end": mention.end,
                "product": mention.product.canonical_product if mention.product else None,
            }
            for mention in find_food_mentions(row["text"])
        ]
        scope = classify_scope_locally(
            row["text"],
            has_image=False,
            has_text=bool(row["text"]),
            language=row["language"],
        )

        assert mentions == row["mentions"], row["id"]
        assert {
            "route": scope.route,
            "is_food_related": scope.is_food_related,
            "needs_clarification": scope.needs_clarification,
            "confidence": scope.confidence,
        } == row["scope"], row["id"]


@pytest.mark.parametrize(
    ("text", "canonical"),
    [
        ("bananna", "banana"),
        ("куриная грудинка", "chicken breast cooked"),
        ("гречке", "cooked buckwheat"),
    ],
)
def test_embedding_linker_handles_known_en_ru_cases(text: str, canonical: str) -> None:
    link = link_food_span(text, threshold=0.62)

    assert link is not None
    assert link.canonical_name == canonical


def test_embedding_linker_exact_aliases_win_before_nearest_neighbor() -> None:
    mentions = find_embedding_food_mentions("cola zero", threshold=0.62)

    assert len(mentions) == 1
    assert mentions[0].canonical_name == "Coca-Cola Zero Sugar"
    assert mentions[0].method == "exact_alias"


def test_embedding_linker_threshold_blocks_low_similarity_match() -> None:
    assert link_food_span("bananna", threshold=0.9) is None


def test_embedding_linker_gracefully_degrades_when_index_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> object:
        raise RuntimeError("index unavailable")

    monkeypatch.setattr(food_linker, "get_food_linker", fail)

    assert food_linker.find_embedding_food_mentions("bananna", threshold=0.62) == ()
    assert food_linker.link_food_span("bananna", threshold=0.62) is None


def test_food_mentions_shadow_mode_does_not_change_served_legacy_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        food_normalization,
        "get_settings",
        lambda: SimpleNamespace(
            food_linker_shadow_enabled=True,
            food_linker_embeddings_enabled=False,
            food_linker_similarity_threshold=0.62,
        ),
    )

    assert find_food_mentions("bananna") == ()


def test_food_mentions_embedding_primary_flag_can_serve_linker_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        food_normalization,
        "get_settings",
        lambda: SimpleNamespace(
            food_linker_shadow_enabled=False,
            food_linker_embeddings_enabled=True,
            food_linker_similarity_threshold=0.62,
        ),
    )

    mentions = find_food_mentions("bananna")

    assert len(mentions) == 1
    assert mentions[0].canonical_name == "banana"
