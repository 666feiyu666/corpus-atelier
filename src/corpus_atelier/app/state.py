"""Public application records for the prompt-centered workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


RunStatus = Literal[
    "discussing_request",
    "prompt_ready",
    "extracting",
    "generating_image",
    "outcome_unknown",
    "created",
    "failed",
]


@dataclass(frozen=True)
class PromptSessionJob:
    """The minimal request record a prompt session needs at creation time."""

    case_id: str
    request: str


@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: RunStatus
    run_dir: Path
    message: str
    artifacts: dict[str, str]


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    status: str
    run_dir: Path
    manifest: dict[str, Any]
