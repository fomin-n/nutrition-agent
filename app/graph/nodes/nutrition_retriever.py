import logging

from app.graph.state import NutritionGraphState
from app.schemas.nutrition import IngredientEstimate, IngredientNutrition, NutritionCandidate
from app.tools.food_query import normalize_food_description
from app.tools.nutrition_tools import (
    NutritionSourceRouter,
    generic_fallback_candidate,
    get_default_router,
)

LOGGER = logging.getLogger(__name__)


class NutritionRetriever:
    def __init__(self, router: NutritionSourceRouter | None = None) -> None:
        self.router = router or get_default_router()

    def lookup(
        self,
        ingredient: IngredientEstimate,
        *,
        source_route: str | None = None,
        language: str | None = None,
    ) -> IngredientNutrition:
        query = normalize_food_description(
            ingredient.name,
            language=language,
            source_route=source_route,
        )
        selected = self.router.best_candidate(query)
        warning: str | None = None
        if selected is None:
            selected = generic_fallback_candidate(ingredient.name)
            warning = f"No database match for {ingredient.name}; used generic mixed-food fallback."
            LOGGER.info("Nutrition retrieval fallback reason=no_source_result query=%r", ingredient.name)

        per_100g = selected.to_per_100g()
        if per_100g is None:
            selected = generic_fallback_candidate(ingredient.name)
            per_100g = selected.to_per_100g()
            warning = f"No usable per-100g nutrition for {ingredient.name}; used generic mixed-food fallback."

        LOGGER.info(
            "Nutrition selected ingredient=%r canonical=%r source=%s source_id=%s score=%s",
            ingredient.name,
            query.canonical_query,
            selected.source,
            selected.source_id,
            selected.match_score,
        )
        return IngredientNutrition(
            ingredient_name=ingredient.name,
            matched_food_name=per_100g.food_name,
            grams_min=ingredient.grams_min,
            grams_max=ingredient.grams_max,
            per_100g=per_100g,
            source=per_100g.source,
            warning=warning,
            candidate=_public_candidate_debug(selected),
        )


def retrieve_nutrition(state: NutritionGraphState) -> NutritionGraphState:
    meal = state.get("meal")
    if meal is None:
        return {"ingredient_nutrition": []}

    scope = state.get("scope_decision")
    normalized = state.get("normalized_input")
    source_route = scope.route if scope else None
    language = normalized.language if normalized else None
    retriever = NutritionRetriever()
    items = [
        retriever.lookup(
            ingredient,
            source_route=source_route,
            language=language,
        )
        for ingredient in meal.ingredients
    ]
    return {"ingredient_nutrition": items}


def _public_candidate_debug(candidate: NutritionCandidate) -> NutritionCandidate:
    return candidate.model_copy(
        update={
            "metadata": {
                key: value
                for key, value in candidate.metadata.items()
                if key in {"data_type", "food_category", "quantity", "categories", "publication_date"}
            }
        }
    )
