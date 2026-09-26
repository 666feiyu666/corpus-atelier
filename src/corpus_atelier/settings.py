"""Local, non-task product preferences and credential configuration."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Mapping

from dotenv import dotenv_values

from .i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES


OPENAI_API_KEY = "OPENAI_API_KEY"
_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?OPENAI_API_KEY\s*=")


@dataclass(frozen=True)
class ApiCredential:
    value: str
    source: str


def load_preferences(path: Path) -> dict[str, str]:
    """Load validated product preferences without exposing task data."""
    if not path.is_file():
        return {"language": DEFAULT_LANGUAGE}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"language": DEFAULT_LANGUAGE}
    language = value.get("language", DEFAULT_LANGUAGE)
    if language not in SUPPORTED_LANGUAGES:
        language = DEFAULT_LANGUAGE
    return {"language": language}


def save_preferences(path: Path, preferences: Mapping[str, str]) -> None:
    """Atomically save validated non-secret product preferences."""
    language = preferences.get("language", DEFAULT_LANGUAGE)
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported interface language: {language}")
    _atomic_write(path, json.dumps(
        {"language": language}, ensure_ascii=False, indent=2,
    ) + "\n")


def local_openai_api_key(path: Path) -> str | None:
    """Read the OpenAI key from the product's local dotenv file."""
    if not path.is_file():
        return None
    value = dotenv_values(path).get(OPENAI_API_KEY)
    return value.strip() if isinstance(value, str) and value.strip() else None


def resolve_openai_api_key(
    session_value: str | None,
    *,
    env_path: Path,
    environment: Mapping[str, str] | None = None,
) -> ApiCredential | None:
    """Resolve a credential without mutating the process environment."""
    if session_value and session_value.strip():
        return ApiCredential(session_value.strip(), "session")
    local_value = local_openai_api_key(env_path)
    if local_value:
        return ApiCredential(local_value, "local")
    process_value = (environment or os.environ).get(OPENAI_API_KEY, "").strip()
    if process_value:
        return ApiCredential(process_value, "environment")
    return None


def update_local_openai_api_key(path: Path, value: str | None) -> None:
    """Set or remove OPENAI_API_KEY while preserving unrelated dotenv lines."""
    normalized = value.strip() if value else None
    if normalized and any(character in normalized for character in "\r\n"):
        raise ValueError("API keys cannot contain line breaks.")

    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    output: list[str] = []
    replaced = False
    for line in lines:
        if _ASSIGNMENT.match(line):
            if normalized and not replaced:
                output.append(f'{OPENAI_API_KEY}="{_escape_dotenv(normalized)}"')
                replaced = True
            continue
        output.append(line)
    if normalized and not replaced:
        output.append(f'{OPENAI_API_KEY}="{_escape_dotenv(normalized)}"')

    if output:
        _atomic_write(path, "\n".join(output).rstrip() + "\n")
    elif path.exists():
        _atomic_write(path, "")


def mask_api_key(value: str) -> str:
    """Return a non-sensitive credential hint for the settings UI."""
    suffix = value[-4:] if len(value) >= 4 else "••••"
    return f"••••{suffix}"


def _escape_dotenv(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary_name = temporary.name
        os.replace(temporary_name, path)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
