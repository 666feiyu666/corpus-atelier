"""Public application records and the LangGraph state contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

RunStatus = Literal[
    "created", "interpreting_request", "designing",
    "compiling_image_spec",
    "awaiting_approval", "rejected", "generating", "completed", "failed",
]


@dataclass(frozen=True)
class DesignJob:
    case_id: str
    profile: str
    brief: dict[str, Any]


@dataclass(frozen=True)
class NaturalLanguageDesignJob:
    case_id: str
    profile: str
    request: str


@dataclass(frozen=True)
class HumanDecision:
    approved: bool
    reviewer: str = "cli-user"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


class AtelierState(TypedDict, total=False):
    case_id: str
    run_id: str
    run_dir: str
    profile: str
    user_request: str
    brief: dict[str, Any]
    design_prompt: str
    proposal: dict[str, Any]
    image_prompt: str
    image_spec: dict[str, Any]
    generation_prompt: str
    generation_request: dict[str, Any]
    generation_size: str
    output_ratio: tuple[int, int]
    canvas: dict[str, Any]
    generation_digest: str
    approval: dict[str, Any]
    image_path: str
    status: RunStatus
    error: str
