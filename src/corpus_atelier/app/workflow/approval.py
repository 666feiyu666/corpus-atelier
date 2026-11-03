"""Pause for human approval and apply prompt overrides."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from langgraph.types import interrupt
from ...artifacts.hashing import digest_json
from ...artifacts.records import read_json
from ..registry import get_profile
from ..state import AtelierState
from .routing import resolve_execution_route

class ApprovalMixin:
    """Pause for human approval and apply prompt overrides."""

    def _auto_approval_applies(self, state: AtelierState, failed: list[str]) -> bool:
        """A fast-path round renders without confirmation only when nothing is at stake.

        The route must already be direct (no design exploration) and every candidate
        must have compiled, so the pause would only repeat what the user asked for.
        """
        return (
            state.get("approval_policy") == "auto"
            and resolve_execution_route(state) == "direct"
            and not failed
        )

    def approval(self, state: AtelierState) -> AtelierState:
        run_dir = self._dir(state)
        profile = get_profile(state["profile"])
        ready = [candidate for candidate in state["candidates"] if candidate["status"] == "ready"]
        failed_candidates = [
            candidate["candidate_id"]
            for candidate in state["candidates"]
            if candidate["status"] == "failed"
        ]
        payload = {
            "run_id": state["run_id"],
            "profile": profile.name,
            "candidate_count": state["candidate_count"],
            "generation_call_count": len(ready),
            "batch_digest": state["batch_digest"],
            "candidates": [
                {
                    "candidate_id": candidate["candidate_id"],
                    "label": candidate["direction_seed"]["label"],
                    "generation_digest": candidate["generation_digest"],
                    "proposal": self._artifact_path(
                        run_dir, candidate["candidate_id"],
                        "design-implementation/proposal.json",
                    ),
                    "image_prompt": self._artifact_path(
                        run_dir, candidate["candidate_id"],
                        "image-prompt/image-prompt.json",
                    ),
                    "generation_prompt": str((
                        self._candidate_dir(run_dir, candidate["candidate_id"])
                        / "generation/prompt.md"
                    ).resolve()),
                    "generation_request_preview": str((
                        self._candidate_dir(run_dir, candidate["candidate_id"])
                        / "generation/request-preview.json"
                    ).resolve()),
                }
                for candidate in ready
            ],
            "failed_candidates": failed_candidates,
        }
        self.store.update(run_dir, "awaiting_approval", approval_request=payload)
        if self._auto_approval_applies(state, failed_candidates):
            # The fast path records the same decision a user would have made, so the
            # audit trail stays complete without an extra click.
            record = {
                "approved": True,
                "reviewer": "fast-path",
                "auto": True,
                "decided_at": datetime.now(timezone.utc).isoformat(),
                "batch_digest": state["batch_digest"],
            }
            self.store.json(run_dir, "approval/decision.json", record)
            self.store.register(run_dir, approval="approval/decision.json")
            return {
                "approval": record,
                "status": "generating_candidates",
            }
        decision = interrupt(payload)
        if not isinstance(decision, dict) or not isinstance(decision.get("approved"), bool):
            raise ValueError("Human approval must be an explicit boolean decision.")
        if not decision["approved"]:
            record = {
                **{key: value for key, value in decision.items() if key != "prompt_overrides"},
                "decided_at": datetime.now(timezone.utc).isoformat(),
                "batch_digest": state["batch_digest"],
            }
            self.store.json(run_dir, "approval/decision.json", record)
            self.store.register(run_dir, approval="approval/decision.json")
            self.store.update(run_dir, "rejected", approval=record)
            return {"approval": record, "status": "rejected"}
        candidates, batch_digest, applied = self._apply_prompt_overrides(
            state, decision.get("prompt_overrides"),
        )
        record = {
            **{key: value for key, value in decision.items() if key != "prompt_overrides"},
            "decided_at": datetime.now(timezone.utc).isoformat(),
            "batch_digest": batch_digest,
        }
        if applied:
            record["prompt_overrides"] = applied
        self.store.json(run_dir, "approval/decision.json", record)
        self.store.register(run_dir, approval="approval/decision.json")
        return {
            "approval": record,
            "candidates": candidates,
            "batch_digest": batch_digest,
            "status": "generating_candidates",
        }

    def _apply_prompt_overrides(
        self, state: AtelierState, overrides: dict | None,
    ) -> tuple[list[dict[str, Any]], str, dict[str, dict[str, Any]]]:
        """Apply user-edited prompts before generation and rebind the batch digest."""
        if overrides is None:
            return state["candidates"], state["batch_digest"], {}
        if not isinstance(overrides, dict):
            raise ValueError("Edited generation prompts must be a candidate-to-text mapping.")
        candidates = [dict(candidate) for candidate in state["candidates"]]
        by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
        applied: dict[str, dict[str, Any]] = {}
        for candidate_id, text in overrides.items():
            candidate = by_id.get(candidate_id)
            if candidate is None or candidate["status"] != "ready":
                raise ValueError(f"Cannot edit the prompt of candidate {candidate_id!r}.")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("An edited generation prompt must not be empty.")
            prompt = text.strip()
            if len(prompt) > self.MAX_EDITABLE_PROMPT_CHARS:
                raise ValueError(
                    f"An edited generation prompt must stay under "
                    f"{self.MAX_EDITABLE_PROMPT_CHARS} characters."
                )
            if prompt == candidate["generation_prompt"]:
                continue
            root = self._candidate_dir(self._dir(state), candidate_id)
            candidate["generation_prompt"] = prompt
            self.store.text(root, "generation/prompt.md", prompt)
            candidate["generation_request"] = self._describe_generation_request(state, candidate)
            self.store.json(
                root, "generation/request-preview.json", candidate["generation_request"],
            )
            candidate["generation_digest"] = digest_json(
                self._generation_binding(state, candidate)
            )
            applied[candidate_id] = {
                "sha256": digest_json({"prompt": prompt}),
                "chars": len(prompt),
            }
        if not applied:
            return state["candidates"], state["batch_digest"], {}
        batch_digest = self._batch_digest(candidates)
        self.store.json(self._dir(state), "candidates/index.json", candidates)
        return candidates, batch_digest, applied

    def _validate_candidate_preview(self, state: AtelierState, candidate: dict[str, Any]) -> str:
        run_dir = self._dir(state)
        root = self._candidate_dir(run_dir, candidate["candidate_id"])
        saved_prompt = (root / "generation/prompt.md").read_text(encoding="utf-8")
        proposal_path = root / "design-implementation/proposal.json"
        saved_proposal = read_json(proposal_path) if proposal_path.is_file() else None
        saved_image_prompt = read_json(root / "image-prompt/image-prompt.json")
        saved_request = read_json(root / "generation/request-preview.json")
        current_request = self._describe_generation_request(state, candidate)
        if (
            saved_prompt != candidate["generation_prompt"]
            or saved_proposal != candidate.get("proposal")
            or saved_image_prompt != candidate.get("image_prompt")
            or saved_request != candidate["generation_request"]
            or current_request != candidate["generation_request"]
        ):
            raise ValueError("Approved generation artifacts changed after preview.")
        actual = digest_json(self._generation_binding(state, candidate))
        if actual != candidate["generation_digest"]:
            raise ValueError("Approved generation content changed.")
        return actual
