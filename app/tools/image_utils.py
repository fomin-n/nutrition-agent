import base64
import mimetypes
from pathlib import Path


def guess_image_mime_type(path: str | Path) -> str:
    mime_type, _ = mimetypes.guess_type(str(path))
    return mime_type or "image/jpeg"


def encode_image_data_url(path: str | Path, mime_type: str | None = None) -> str:
    image_path = Path(path)
    image_bytes = image_path.read_bytes()
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type or guess_image_mime_type(image_path)};base64,{encoded}"

