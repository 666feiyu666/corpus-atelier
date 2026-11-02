"""Allow-listed OpenAI model profiles and generation parameter grades."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextModelProfile:
    model: str
    label: str
    description: str
    reasoning_efforts: tuple[str, ...] = ("low", "medium", "high")
    default_reasoning_effort: str = "medium"


@dataclass(frozen=True)
class ImageModelProfile:
    model: str
    label: str
    description: str
    family: str = "gpt-image-2"
    supports_max_quality: bool = False
    supports_transparency: bool = False


TEXT_MODEL_PROFILES = (
    TextModelProfile(
        model="gpt-5.6-luna",
        label="GPT-5.6 Luna",
        description="Fast model for everyday design tasks.",
    ),
    TextModelProfile(
        model="gpt-6-sol",
        label="GPT-6 Sol",
        description="Balanced model for more demanding design work.",
    ),
    TextModelProfile(
        model="gpt-6-astra",
        label="GPT-6 Astra",
        description="Highest-capability option for complex briefs.",
    ),
)

TEXT_MODELS = {profile.model: profile for profile in TEXT_MODEL_PROFILES}

IMAGE_MODEL_PROFILES = (
    ImageModelProfile(
        model="gpt-image-2",
        label="GPT Image 2",
        description="Established high-quality image generation and editing model.",
    ),
    ImageModelProfile(
        model="gpt-image-2.5-sunburst",
        label="GPT Image 2.5 Sunburst",
        description="Highest-capability option for demanding image generation.",
        family="gpt-image-2.5",
        supports_max_quality=True,
        supports_transparency=True,
    ),
    ImageModelProfile(
        model="gpt-image-2.5-flare",
        label="GPT Image 2.5 Flare",
        description="Fast option for everyday high-quality image generation.",
        family="gpt-image-2.5",
        supports_max_quality=True,
        supports_transparency=True,
    ),
)

IMAGE_MODELS = {profile.model: profile for profile in IMAGE_MODEL_PROFILES}

IMAGE_QUALITIES = ("auto", "low", "medium", "high", "xhigh", "max")
IMAGE_FORMATS = ("png", "jpeg", "webp")
IMAGE_BACKGROUNDS = ("auto", "opaque", "transparent")


def get_text_model_profile(model: str) -> TextModelProfile:
    try:
        return TEXT_MODELS[model]
    except KeyError as exc:
        raise ValueError(f"Unsupported OpenAI text model: {model!r}.") from exc


def get_image_model_profile(model: str) -> ImageModelProfile:
    try:
        return IMAGE_MODELS[model]
    except KeyError as exc:
        raise ValueError(f"Unsupported OpenAI image model: {model!r}.") from exc


def validate_reasoning_effort(model: str, effort: str) -> str:
    profile = get_text_model_profile(model)
    if effort not in profile.reasoning_efforts:
        raise ValueError(
            f"Unsupported reasoning effort {effort!r} for {model!r}."
        )
    return effort


def validate_image_quality(model: str, quality: str) -> str:
    profile = get_image_model_profile(model)
    if quality not in IMAGE_QUALITIES:
        raise ValueError(
            f"Unsupported image quality {quality!r}. "
            f"Choose one of: {', '.join(IMAGE_QUALITIES)}"
        )
    if quality in {"xhigh", "max"} and not profile.supports_max_quality:
        raise ValueError(
            f"Quality {quality!r} requires a GPT Image 2.5 model, not {model!r}."
        )
    return quality


def validate_image_format(format: str) -> str:
    if format not in IMAGE_FORMATS:
        raise ValueError(
            f"Unsupported image format {format!r}. "
            f"Choose one of: {', '.join(IMAGE_FORMATS)}"
        )
    return format


def validate_image_background(model: str, background: str, format: str = "png") -> str:
    profile = get_image_model_profile(model)
    if background not in IMAGE_BACKGROUNDS:
        raise ValueError(
            f"Unsupported image background {background!r}. "
            f"Choose one of: {', '.join(IMAGE_BACKGROUNDS)}"
        )
    if background == "transparent":
        if format not in ("png", "webp"):
            raise ValueError("Transparent background requires PNG or WebP output.")
        if not profile.supports_transparency:
            raise ValueError(
                f"Transparent background is not supported by {model!r}."
            )
    return background
