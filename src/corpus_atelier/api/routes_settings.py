"""Settings: interface language, model catalog, and the write-only credential."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from ..config.languages import LANGUAGE_LABELS, SUPPORTED_LANGUAGES
from ..config.models import (
    IMAGE_MODEL_PROFILES,
    IMAGE_QUALITIES,
    TEXT_MODEL_PROFILES,
)
from ..config.settings import (
    load_preferences,
    mask_api_key,
    save_preferences,
    update_local_openai_api_key,
)
from .deps import RuntimeDep
from .errors import invalid
from .schemas import CredentialTest, CredentialUpdate, LanguageUpdate
from .schemas import RATIO_OPTIONS


LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


def _credential_view(runtime: RuntimeDep) -> dict:
    credential = runtime.credential()
    if credential is None:
        return {"configured": False, "masked": None, "source": None}
    return {
        "configured": True,
        "masked": mask_api_key(credential.value),
        "source": credential.source,
    }


def _settings_view(runtime: RuntimeDep) -> dict:
    language = load_preferences(runtime.paths.preferences_path)["language"]
    return {
        "language": language,
        "languages": [
            {"id": code, "label": LANGUAGE_LABELS[code]} for code in SUPPORTED_LANGUAGES
        ],
        "credential": _credential_view(runtime),
        "text_models": [
            {
                "model": profile.model,
                "label": profile.label,
                "description": profile.description,
                "reasoning_efforts": list(profile.reasoning_efforts),
                "default_reasoning_effort": profile.default_reasoning_effort,
            }
            for profile in TEXT_MODEL_PROFILES
        ],
        "image_models": [
            {
                "model": profile.model,
                "label": profile.label,
                "description": profile.description,
                "supports_max_quality": profile.supports_max_quality,
                "supports_transparency": profile.supports_transparency,
            }
            for profile in IMAGE_MODEL_PROFILES
        ],
        "qualities": list(IMAGE_QUALITIES),
        "ratios": [list(ratio) for ratio in RATIO_OPTIONS],
    }


@router.get("")
def read_settings(runtime: RuntimeDep) -> dict:
    return _settings_view(runtime)


@router.put("/language")
def update_language(body: LanguageUpdate, runtime: RuntimeDep) -> dict:
    if body.language not in SUPPORTED_LANGUAGES:
        raise invalid(f"Unsupported interface language: {body.language!r}.")
    save_preferences(runtime.paths.preferences_path, {"language": body.language})
    return _settings_view(runtime)


@router.put("/credential")
def update_credential(body: CredentialUpdate, runtime: RuntimeDep) -> dict:
    """Store the key server-side; the value is never echoed back."""
    if body.remember:
        update_local_openai_api_key(runtime.paths.env_path, body.api_key)
    runtime.set_session_key(body.api_key)
    return {"credential": _credential_view(runtime)}


@router.delete("/credential")
def clear_credential(runtime: RuntimeDep) -> dict:
    runtime.set_session_key(None)
    update_local_openai_api_key(runtime.paths.env_path, None)
    return {"credential": _credential_view(runtime)}


def _test_connection(api_key: str) -> bool:
    """Check the credential without exposing provider details."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key, max_retries=0, timeout=20.0)
    try:
        client.models.list()
        return True
    except Exception:
        LOGGER.info("Credential test failed.", exc_info=True)
        return False
    finally:
        client.close()


@router.post("/credential/test")
def test_credential(body: CredentialTest, runtime: RuntimeDep) -> dict:
    candidate = (body.api_key or "").strip()
    if not candidate:
        configured = runtime.credential()
        if configured is None:
            raise invalid("Enter an API key or configure one first.")
        candidate = configured.value
    return {"ok": _test_connection(candidate)}
