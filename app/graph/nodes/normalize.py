from app.graph.state import NutritionGraphState
from app.i18n import detect_language
from app.schemas.inputs import NormalizedInput, UserInput
from app.tools.image_utils import guess_image_mime_type


def normalize_input(state: NutritionGraphState) -> NutritionGraphState:
    raw_input = state.get("user_input", {})
    user_input = raw_input if isinstance(raw_input, UserInput) else UserInput.model_validate(raw_input)

    normalized = NormalizedInput(
        text=user_input.text,
        image_path=user_input.image_path,
        image_mime_type=user_input.image_mime_type
        or (guess_image_mime_type(user_input.image_path) if user_input.image_path else None),
        has_text=bool(user_input.text),
        has_image=bool(user_input.image_path),
        language=detect_language(user_input.text, has_image=bool(user_input.image_path)),
    )
    return {"user_input": user_input, "normalized_input": normalized}
