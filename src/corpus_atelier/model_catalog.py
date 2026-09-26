"""Allow-listed OpenAI model profiles exposed by the product UI."""

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
    ),
    ImageModelProfile(
        model="gpt-image-2.5-flare",
        label="GPT Image 2.5 Flare",
        description="Fast option for everyday high-quality image generation.",
    ),
)

IMAGE_MODELS = {profile.model: profile for profile in IMAGE_MODEL_PROFILES}


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
