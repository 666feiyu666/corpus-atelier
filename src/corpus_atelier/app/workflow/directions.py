"""Produce the direction portfolio and implement the approved direction."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from ...artifacts.hashing import digest_json
from ...atelier.design_direction import (
    synthesize_design_directions,
    validate_design_direction_plan,
)
from ...atelier.design_implementation.presentation import render
from ...atelier.design_implementation.synthesis import synthesize_design_implementation
from ...design_support.canvas import resolve_canvas
from ...design_support.validation import validate_candidate_count, validate_proposal
from ..registry import get_profile
from ..state import AtelierState

class DirectionsMixin:
    """Produce the direction portfolio and implement the approved direction."""

    def design_directions(self, state: AtelierState) -> AtelierState:
        run_dir = self._dir(state)
        profile = get_profile(state["profile"])
        candidate_limit = validate_candidate_count(state.get("candidate_limit", 1))
        generation_size, output_ratio, canvas = self._resolve_canvas(
            profile, state["brief"],
        )
        self.store.update(
            run_dir, "designing_directions", candidate_limit=candidate_limit,
            content_language=state.get("content_language") or state["brief"].get("content_language"),
        )
        prompt = ""
        try:
            prompt, raw_plan, response = synthesize_design_directions(
                profile,
                state["brief"],
                self.text_provider,
                canvas=canvas,
                candidate_limit=candidate_limit,
                content_language=state.get("content_language"),
            )
            raw_plan = validate_design_direction_plan(
                raw_plan, candidate_limit, objective=profile.objective,
                asset_category=state["brief"].get("asset_category"),
            )
            directions = [
                {"candidate_id": f"c{index:02d}", **direction}
                for index, direction in enumerate(raw_plan["directions"], start=1)
            ]
            candidate_count = len(directions)
            plan = {
                "planning_mode": raw_plan["planning_mode"],
                "requested_candidate_limit": candidate_limit,
                "actual_candidate_count": candidate_count,
                "brief_sha256": digest_json(state["brief"]),
                "objective": profile.objective,
                "shared_invariants": {
                    "exact_copy": state["brief"].get("exact_copy", []),
                    "constraints": state["brief"].get("constraints", []),
                    "user_requirements": state["brief"].get("user_requirements", []),
                    "canvas": canvas,
                },
                "directions": directions,
            }
            request = {
                "model": getattr(
                    self.text_provider, "model", type(self.text_provider).__name__,
                ),
                "schema": "design-direction-plan.schema.json",
                "candidate_limit": candidate_limit,
                "objective": profile.objective,
            }
            self.store.json(run_dir, "design-direction/request.json", request)
            self.store.text(run_dir, "design-direction/prompt.md", prompt)
            self.store.json(run_dir, "design-direction/response.json", response)
            self.store.json(run_dir, "design-direction/plan.json", plan)
            self.store.json(run_dir, "generation/canvas.json", canvas)
            self.store.register(
                run_dir,
                design_direction_request="design-direction/request.json",
                design_direction_prompt="design-direction/prompt.md",
                design_direction_response="design-direction/response.json",
                direction_plan="design-direction/plan.json",
                canvas="generation/canvas.json",
            )
            return {
                "direction_plan": plan,
                "candidate_count": candidate_count,
                "generation_size": generation_size,
                "output_ratio": output_ratio,
                "canvas": canvas,
                "status": "implementing_designs",
            }
        except Exception as exc:
            if prompt:
                self.store.text(run_dir, "design-direction/prompt.md", prompt)
            self.store.json(run_dir, "design-direction/error.json", {
                "status": "failed",
                "error_type": type(exc).__name__,
                "message": str(exc),
            })
            self.store.register(
                run_dir, design_direction_error="design-direction/error.json",
            )
            raise

    def implement_designs(self, state: AtelierState) -> AtelierState:
        run_dir = self._dir(state)
        profile = get_profile(state["profile"])
        self.store.update(run_dir, "implementing_designs")

        def implement_one(seed):
            candidate_id = seed["candidate_id"]
            root = self._candidate_dir(run_dir, candidate_id)
            prompt = ""
            try:
                prompt, proposal, response = synthesize_design_implementation(
                    profile,
                    state["brief"],
                    self.text_provider,
                    canvas=state["canvas"],
                    direction_seed=seed,
                    content_language=state.get("content_language"),
                )
                proposal = validate_proposal(
                    proposal, profile.proposal_schema, candidate_id=candidate_id,
                )
                request = {
                    "model": getattr(
                        self.text_provider, "model", type(self.text_provider).__name__,
                    ),
                    "profile": profile.name,
                    "schema": profile.proposal_schema,
                    "candidate_id": candidate_id,
                }
                self.store.json(root, "design-implementation/request.json", request)
                self.store.text(root, "design-implementation/prompt.md", prompt)
                self.store.json(root, "design-implementation/response.json", response)
                self.store.json(root, "design-implementation/proposal.json", proposal)
                self.store.text(
                    root, "design-implementation/presentation.md",
                    render(proposal, content_language=state.get("content_language")),
                )
                return {
                    "candidate_id": candidate_id,
                    "direction_seed": seed,
                    "proposal": proposal,
                    "status": "implemented",
                    "error": None,
                }
            except Exception as exc:
                if prompt:
                    self.store.text(root, "design-implementation/prompt.md", prompt)
                self.store.json(root, "design-implementation/error.json", {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                })
                return {
                    "candidate_id": candidate_id,
                    "direction_seed": seed,
                    "status": "failed",
                    "error": {
                        "stage": "design_implementation",
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                    "_exception": exc,
                }

        directions = state["direction_plan"]["directions"]
        with ThreadPoolExecutor(max_workers=len(directions)) as executor:
            candidates = list(executor.map(implement_one, directions))
        candidates.sort(key=lambda item: item["candidate_id"])
        first_exception = next(
            (candidate.get("_exception") for candidate in candidates if candidate.get("_exception")),
            None,
        )
        for candidate in candidates:
            candidate.pop("_exception", None)
        self.store.json(run_dir, "candidates/index.json", candidates)
        if not any(candidate["status"] == "implemented" for candidate in candidates):
            raise first_exception or ValueError("All design implementations failed.")
        return {"candidates": candidates, "status": "compiling_candidates"}

    @staticmethod
    def _resolve_canvas(profile, brief):
        if profile.canvas_mode == "brief":
            return resolve_canvas(brief)
        generation_size = profile.default_size
        output_ratio = profile.output_ratio
        return generation_size, output_ratio, {
            "size": generation_size,
            "ratio": list(output_ratio),
            "mode": "profile_default",
        }
