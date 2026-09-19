"""Public application records and the LangGraph state contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

RunStatus = Literal[
    "created", "retrieving", "designing", "awaiting_approval", "rejected",
    "generating", "reviewing", "completed", "failed",
]


@dataclass(frozen=True)
class DesignJob:
    profile: str
    brief: dict[str, Any]
    snapshot: Path
    evidence_mode: str = "hybrid-rag"


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
    run_id: str
    run_dir: str
    profile: str
    brief: dict[str, Any]
    snapshot: str
    evidence_mode: str
    retrieval_query: dict[str, Any]
    retrieval_candidates: list[dict[str, Any]]
    retrieval_bundle: dict[str, Any]
    design_prompt: str
    proposal: dict[str, Any]
    generation_prompt: str
    generation_digest: str
    approval: dict[str, Any]
    image_path: str
    review: dict[str, Any]
    status: RunStatus
    error: str
