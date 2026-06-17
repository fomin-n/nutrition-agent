from functools import lru_cache
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.graph.nodes.calculator import calculate_macros
from app.graph.nodes.coordinator import route, route_from_scope, scope_classifier
from app.graph.nodes.critic import critic, route_after_critic
from app.graph.nodes.image_recognizer import combine_text_and_image, recognize_dish_photo
from app.graph.nodes.normalize import normalize_input
from app.graph.nodes.nutrition_retriever import retrieve_nutrition
from app.graph.nodes.output_guard import output_moderation
from app.graph.nodes.packaging_recognizer import recognize_packaging
from app.graph.nodes.safety_gate import ask_clarification, input_moderation, refuse
from app.graph.nodes.synthesizer import synthesize_answer
from app.graph.nodes.text_parser import parse_text_meal
from app.graph.state import NutritionGraphState
from app.i18n import detect_language
from app.llm.client import get_settings
from app.memory.service import MemoryService, get_memory_service
from app.observability.phoenix import configure_phoenix_tracing, phoenix_trace_context
from app.schemas.inputs import UserInput

APP_VERSION = "0.1.0"
GRAPH_VERSION = "nutrition-graph-v1"


def build_graph():
    workflow = StateGraph(NutritionGraphState)

    workflow.add_node("normalize_input", normalize_input)
    workflow.add_node("input_moderation", input_moderation)
    workflow.add_node("scope_classifier", scope_classifier)
    workflow.add_node("route", route)
    workflow.add_node("refuse", refuse)
    workflow.add_node("ask_clarification", ask_clarification)
    workflow.add_node("parse_text_meal", parse_text_meal)
    workflow.add_node("recognize_dish_photo", recognize_dish_photo)
    workflow.add_node("combine_text_and_image", combine_text_and_image)
    workflow.add_node("recognize_packaging", recognize_packaging)
    workflow.add_node("retrieve_nutrition", retrieve_nutrition)
    workflow.add_node("calculate_macros", calculate_macros)
    workflow.add_node("synthesize_answer", synthesize_answer)
    workflow.add_node("critic", critic)
    workflow.add_node("output_moderation", output_moderation)

    workflow.add_edge(START, "normalize_input")
    workflow.add_edge("normalize_input", "input_moderation")
    workflow.add_edge("input_moderation", "scope_classifier")
    workflow.add_edge("scope_classifier", "route")
    workflow.add_conditional_edges(
        "route",
        route_from_scope,
        {
            "off_topic": "refuse",
            "unsafe": "refuse",
            "needs_clarification": "ask_clarification",
            "text_meal": "parse_text_meal",
            "dish_photo": "recognize_dish_photo",
            "image_with_text": "combine_text_and_image",
            "packaged_food": "recognize_packaging",
        },
    )

    for node in (
        "parse_text_meal",
        "recognize_dish_photo",
        "combine_text_and_image",
        "recognize_packaging",
    ):
        workflow.add_edge(node, "retrieve_nutrition")

    workflow.add_edge("retrieve_nutrition", "calculate_macros")
    workflow.add_edge("calculate_macros", "synthesize_answer")
    workflow.add_edge("synthesize_answer", "critic")
    workflow.add_conditional_edges(
        "critic",
        route_after_critic,
        {
            "ask_clarification": "ask_clarification",
            "refuse": "refuse",
            "output_moderation": "output_moderation",
        },
    )
    workflow.add_edge("ask_clarification", "output_moderation")
    workflow.add_edge("refuse", "output_moderation")
    workflow.add_edge("output_moderation", END)

    return workflow.compile()


@lru_cache(maxsize=1)
def get_compiled_graph():
    return build_graph()


def process_request(
    *,
    text: str | None = None,
    image_path: str | None = None,
    image_mime_type: str | None = None,
    source: str = "telegram",
    use_llm: bool = True,
    user_id: str | int | None = None,
    session_id: str | int | None = None,
    trace_metadata: dict[str, str | int | float | bool | None] | None = None,
    memory_service: MemoryService | None = None,
) -> str:
    settings = get_settings()
    configure_phoenix_tracing(settings)
    graph = get_compiled_graph()
    memory_context = None
    prepared_memory_input = None
    effective_text = text
    conversation_id = session_id if session_id is not None else user_id
    request_id = str(uuid4())
    if user_id is not None and conversation_id is not None:
        memory_service = memory_service or get_memory_service()
        memory_context = memory_service.load_context(user_id, conversation_id)
        prepared_memory_input = memory_service.prepare_input(text, memory_context)
        effective_text = prepared_memory_input.effective_text

    metadata = _trace_metadata(
        text=effective_text,
        image_path=image_path,
        source=source,
        use_llm=use_llm,
        settings=settings,
        extra=trace_metadata,
    )
    metadata["request_id"] = request_id
    with phoenix_trace_context(user_id=user_id, session_id=session_id, metadata=metadata):
        result = graph.invoke(
            {
                "user_input": UserInput(
                    text=effective_text,
                    image_path=image_path,
                    image_mime_type=image_mime_type,
                    source=source,  # type: ignore[arg-type]
                ),
                "use_llm": use_llm,
                "memory_context": memory_context.model_dump() if memory_context else {},
                "request_id": request_id,
            }
        )
    final = result.get("final_estimate")
    answer = final.text if final else "I couldn’t generate a response."
    if user_id is not None and conversation_id is not None and memory_service is not None:
        memory_service.record_turn(
            user_id=user_id,
            conversation_id=conversation_id,
            user_text=text,
            assistant_text=answer,
            effective_text=effective_text,
            final_state=result,
            prepared_task=prepared_memory_input.unresolved_task if prepared_memory_input else None,
        )
    return answer


def _trace_metadata(
    *,
    text: str | None,
    image_path: str | None,
    source: str,
    use_llm: bool,
    settings,
    extra: dict[str, str | int | float | bool | None] | None,
) -> dict[str, str | int | float | bool | None]:
    has_text = bool(text)
    has_image = bool(image_path)
    request_type = "mixed" if has_text and has_image else "photo" if has_image else "text"
    metadata: dict[str, str | int | float | bool | None] = {
        "app_version": APP_VERSION,
        "graph_version": GRAPH_VERSION,
        "source": source,
        "request_type": request_type,
        "request_language": detect_language(text, has_image=has_image),
        "use_llm": use_llm,
        "openai_text_model": settings.openai_text_model,
        "openai_vision_model": settings.openai_vision_model,
        "openai_critic_model": settings.openai_critic_model,
    }
    if extra:
        metadata.update(extra)
    return metadata
