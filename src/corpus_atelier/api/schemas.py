"""Request bodies for the HTTP boundary.

Validation here is about *shape*; every value judgement (prompt length, upload
limits, role membership, expected revision) is left to the application service,
so there is exactly one place that decides what a valid session action is.
"""

from __future__ import annotations

import base64
import binascii
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from ..prompt_session.attempts import REFERENCE_ROLES
from ..prompt_session.uploads import MAX_REFERENCES


# Canvas ratios the interface offers; mirrors the Streamlit control.
RATIO_OPTIONS: tuple[tuple[int, int], ...] = (
    (1, 1), (16, 9), (9, 16), (4, 3), (3, 4), (3, 2), (2, 3),
)

ALLOWED_SESSION_SETTINGS = frozenset({"image_quality", "aspect_ratio"})

ROLE_VALUES = REFERENCE_ROLES
# The upload roles the service accepts (`prompt_session/uploads.py`).
UPLOAD_ROLE_VALUES = ("reference", "mask", "discussion", "source_image")


class Upload(BaseModel):
    """One inline image; the API keeps only bytes and a display name."""

    name: str = Field(min_length=1, max_length=255)
    data_base64: str = Field(min_length=1)


class ModelChoice(BaseModel):
    """Optional per-task model selection; missing fields fall back to defaults."""

    text_model: str | None = None
    reasoning_effort: str | None = None
    image_model: str | None = None
    image_quality: str | None = None


class TaskCreate(BaseModel):
    entry_mode: Literal["prompt", "image"]
    prompt_text: str | None = None
    image: Upload | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    references: list[Upload] = Field(default_factory=list)
    submit_generate: bool = False
    models: ModelChoice | None = None

    @model_validator(mode="after")
    def _shape(self) -> "TaskCreate":
        if self.entry_mode == "prompt" and not (self.prompt_text or "").strip():
            raise ValueError("prompt_text is required when entry_mode is 'prompt'.")
        if self.entry_mode == "image" and self.image is None:
            raise ValueError("image is required when entry_mode is 'image'.")
        if self.entry_mode == "image" and self.references:
            raise ValueError("A source image is uploaded as image, not as a reference.")
        if len(self.references) > MAX_REFERENCES:
            raise ValueError(f"At most {MAX_REFERENCES} reference images may be attached.")
        unknown = set(self.settings) - ALLOWED_SESSION_SETTINGS
        if unknown:
            raise ValueError(
                "Unsupported session settings: " + ", ".join(sorted(unknown)) + "."
            )
        ratio = self.settings.get("aspect_ratio")
        if ratio is not None:
            if (
                not isinstance(ratio, (list, tuple))
                or len(ratio) != 2
                or tuple(int(value) for value in ratio) not in RATIO_OPTIONS
            ):
                raise ValueError(
                    "aspect_ratio must be one of "
                    + ", ".join(f"{w}:{h}" for w, h in RATIO_OPTIONS)
                    + "."
                )
        return self


class PromptRevisionCreate(BaseModel):
    prompt_text: str
    expected_revision: str | None = None


class PromptRestore(BaseModel):
    expected_revision: str | None = None


class PromptProposalCreate(BaseModel):
    kind: Literal["generate", "edit"] = "generate"
    edit_instruction: str | None = None

    @model_validator(mode="after")
    def _instruction(self) -> "PromptProposalCreate":
        if self.kind == "edit" and not (self.edit_instruction or "").strip():
            raise ValueError("edit_instruction is required for an edit proposal.")
        return self


class ProposalAdopt(BaseModel):
    expected_revision: str | None = None


class CanvasUpdate(BaseModel):
    ratio: list[int] | None = None

    @model_validator(mode="after")
    def _ratio(self) -> "CanvasUpdate":
        if self.ratio is not None:
            if len(self.ratio) != 2 or tuple(self.ratio) not in RATIO_OPTIONS:
                raise ValueError(
                    "ratio must be one of "
                    + ", ".join(f"{w}:{h}" for w, h in RATIO_OPTIONS)
                    + ", or null to restore the source canvas."
                )
        return self


class MessageCreate(BaseModel):
    text: str = ""
    attachments: list[Upload] = Field(default_factory=list)

    @model_validator(mode="after")
    def _content(self) -> "MessageCreate":
        if not self.text.strip() and not self.attachments:
            raise ValueError("Send a message or attach an image.")
        if len(self.attachments) > MAX_REFERENCES:
            raise ValueError(f"Attach at most {MAX_REFERENCES} images per message.")
        return self


class RefineCreate(BaseModel):
    result_image_id: str
    base_image_id: str | None = None


class AttemptPrepare(BaseModel):
    action: Literal["generate", "edit"]
    source_image_id: str | None = None
    edit_instruction: str | None = None
    reference_image_ids: list[str] = Field(default_factory=list)
    reference_roles: dict[str, str] = Field(default_factory=dict)
    mask_image_id: str | None = None
    expected_revision: str | None = None

    @model_validator(mode="after")
    def _roles(self) -> "AttemptPrepare":
        for image_id, role in self.reference_roles.items():
            if role not in ROLE_VALUES:
                raise ValueError(
                    "A reference role must be one of: " + ", ".join(ROLE_VALUES) + "."
                )
            if image_id not in self.reference_image_ids:
                raise ValueError("A reference role must name one of the selected references.")
        return self


class AttemptSubmit(BaseModel):
    expected_digest: str = Field(min_length=1)


class ArchiveCreate(BaseModel):
    tags: list[str] = Field(default_factory=list)
    image_id: str | None = None
    source_note: str | None = None


class CredentialUpdate(BaseModel):
    api_key: str = Field(min_length=1)
    remember: bool = False


class CredentialTest(BaseModel):
    api_key: str | None = None


class LanguageUpdate(BaseModel):
    language: str = Field(min_length=2, max_length=16)


def decode_upload(upload: Upload) -> tuple[str, bytes]:
    """Decode one inline image, rejecting anything that is not base64 bytes."""
    try:
        data = base64.b64decode(upload.data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"{upload.name}: the image data is not valid base64.") from exc
    if not data:
        raise ValueError(f"{upload.name}: the image data is empty.")
    return upload.name, data


__all__ = [
    "ArchiveCreate",
    "AttemptPrepare",
    "AttemptSubmit",
    "CanvasUpdate",
    "CredentialTest",
    "CredentialUpdate",
    "MessageCreate",
    "ModelChoice",
    "ProposalAdopt",
    "PromptProposalCreate",
    "PromptRestore",
    "PromptRevisionCreate",
    "RATIO_OPTIONS",
    "RefineCreate",
    "TaskCreate",
    "UPLOAD_ROLE_VALUES",
    "Upload",
    "decode_upload",
]
