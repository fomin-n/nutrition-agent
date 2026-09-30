import base64
import mimetypes
from pathlib import Path

from app.llm.client import get_settings


def guess_image_mime_type(path: str | Path) -> str:
    mime_type, _ = mimetypes.guess_type(str(path))
    return mime_type or "image/jpeg"


def encode_image_data_url(path: str | Path, mime_type: str | None = None) -> str:
    image_path = Path(path)
    limit = get_settings().max_image_bytes
    if image_path.stat().st_size > limit:
        raise ValueError("image exceeds configured byte limit")
    with image_path.open("rb") as stream:
        image_bytes = stream.read(limit + 1)
    if len(image_bytes) > limit:
        raise ValueError("image exceeds configured byte limit")
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type or guess_image_mime_type(image_path)};base64,{encoded}"
