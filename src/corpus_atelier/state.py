"""Public application records and the LangGraph state contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

RunStatus = Literal[
    "created", "loading_materials", "planning_references", "designing",
    "awaiting_approval", "rejected", "generating", "reviewing",
    "awaiting_final_decision", "completed", "discarded", "failed",
]


@dataclass(frozen=True)
class DesignJob:
    profile: str
    brief: dict[str, Any]
    snapshot: Path
    materials: dict[str, Any]


@dataclass(frozen=True)
class HumanDecision:
    approved: bool
    reviewer: str = "cli-user"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FinalDecision:
    action: Literal["accept", "discard"]
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
    run_id: str
    run_dir: str
    profile: str
    brief: dict[str, Any]
    snapshot: str
    materials_selection: dict[str, Any]
    materials_package: dict[str, Any]
    reference_image_paths: list[str]
    reference_plan_prompt: str
    reference_plan: dict[str, Any]
    design_prompt: str
    proposal: dict[str, Any]
    generation_prompt: str
    generation_digest: str
    approval: dict[str, Any]
    image_path: str
    review: dict[str, Any]
    final_action: str
    status: RunStatus
    error: str
