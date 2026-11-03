"""Upload validation and archival for the images a session keeps."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from ..artifacts.hashing import digest_file
from ..app.locking import serialized_run as serialized_session
from ..app.state import RunResult
from .records import PromptSessionRecord, new_id, now

UPLOAD_LIMIT_BYTES = 10 * 1024 * 1024
UPLOAD_MAX_PIXELS = 20_000_000
UPLOAD_FORMATS = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}
MAX_REFERENCES = 3


def validate_upload(name: str, data: bytes) -> tuple[str, int, int]:
    """Validate one upload and return its archived suffix and pixel size."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError("The uploaded image is empty.")
    if len(data) > UPLOAD_LIMIT_BYTES:
        raise ValueError("Each image must be at most 10 MB.")
    try:
        with Image.open(BytesIO(data)) as image:
            suffix = UPLOAD_FORMATS.get(image.format or "")
            if suffix is None:
                raise ValueError("Images must be PNG, JPEG, or WebP.")
            if image.width * image.height > UPLOAD_MAX_PIXELS:
                raise ValueError("Images must be at most 20 megapixels.")
            width, height = image.size
            image.load()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("The uploaded file is not a readable image.") from exc
    return suffix, width, height


class UploadMixin:
    """Archive the images a user explicitly attached to one session."""


    @serialized_session
    def attach_session_upload(
            self, run_id: str, image: tuple[str, bytes], *, role: str = "reference",
        ) -> RunResult:
            """Archive one explicitly uploaded image for a later explicit selection."""
            root, session, _ = self._prompt_session(run_id)
            if role not in {"reference", "mask", "discussion", "source_image"}:
                raise ValueError("An upload role must be reference, mask, discussion, or source_image.")
            self._archive_upload(root, session, image[0], image[1], role=role)
            self._save(root, session)
            return self._result(run_id)


    def _archive_upload(
            self, root: Path, session: PromptSessionRecord, name: str, data: bytes, *, role: str,
        ) -> dict[str, Any]:
            suffix, width, height = validate_upload(name, data)
            image_id = new_id("img")
            relative = f"sources/{image_id}.{suffix}"
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bytes(data))
            record = {
                "id": image_id,
                "name": Path(name).name or "image",
                "path": relative,
                "sha256": digest_file(target),
                "width": width,
                "height": height,
                "role": role,
                "created_at": now(),
            }
            session["uploads"].append(record)
            return record
