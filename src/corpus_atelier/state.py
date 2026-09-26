"""Public application records and the LangGraph state contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

RunStatus = Literal[
    "created", "interpreting_request", "designing",
    "designing_directions", "implementing_designs", "compiling_candidates",
    "awaiting_approval", "rejected", "generating_candidates",
    "awaiting_selection", "completed", "failed",
]

@dataclass(frozen=True)
class DesignJob:
    case_id: str
    profile: str
    brief: dict[str, Any]
    candidate_count: int = 1  # Maximum number of meaningful directions.


@dataclass(frozen=True)
class NaturalLanguageDesignJob:
    case_id: str
    profile: str
    request: str
    candidate_count: int = 1  # Maximum number of meaningful directions.


@dataclass(frozen=True)
class HumanDecision:
    approved: bool
    reviewer: str = "cli-user"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateSelection:
    selected_candidate_id: str | None
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
    candidate_limit: int
    candidate_count: int
    direction_plan: dict[str, Any]
    candidates: list[dict[str, Any]]
    generation_size: str
    output_ratio: tuple[int, int]
    canvas: dict[str, Any]
    batch_digest: str
    approval: dict[str, Any]
    selection: dict[str, Any]
    image_path: str
    status: RunStatus
    error: str
