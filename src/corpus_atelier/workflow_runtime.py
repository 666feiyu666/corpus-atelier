"""LangGraph node execution for approval-gated design and generation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.types import interrupt

from .artifacts.hashing import digest_file, digest_json
from .artifacts.records import read_json, write_json
from .artifacts.store import ArtifactStore
from .design_direction import (
    load_historical_cards,
    synthesize_design_directions,
    validate_design_direction_plan,
)
from .design_implementation.presentation import render
from .design_implementation.synthesis import synthesize_design_implementation
from .design_support.canvas import resolve_canvas
from .design_support.rendering import normalize_canvas
from .design_support.validation import validate, validate_candidate_count, validate_image_spec, validate_proposal
from .image_prompt import compile_generation_prompt, synthesize_image_spec
from .intake import compile_intake_prompt
from .language import bind_brief_language
from .providers.image import ImageProvider
from .providers.text import TextProvider
from .registry import get_profile
from .state import AtelierState


class WorkflowRuntime:
    """Execute workflow stages; the application owns task and checkpoint lifecycle."""

    def __init__(self, store: ArtifactStore, text_provider: TextProvider,
                 image_provider: ImageProvider) -> None:
        self.store = store
        self.text_provider = text_provider
        self.image_provider = image_provider

    @staticmethod
    def _dir(state: AtelierState) -> Path:
        return Path(state["run_dir"])

    def interpret_request(self, state: AtelierState) -> AtelierState:
        run_dir = self._dir(state)
        profile = get_profile(state["profile"])
        self.store.update(run_dir, "interpreting_request")
        prompt = compile_intake_prompt(
            profile, state["user_request"],
            user_requirements=state.get("user_requirements"),
            superseded_user_requirements=state.get("superseded_user_requirements"),
            content_language=state.get("content_language"),
        )
        request = {
            "model": getattr(
                self.text_provider, "model", type(self.text_provider).__name__,
            ),
            "profile": profile.name,
            "schema": profile.brief_schema,
        }
        self.store.json(run_dir, "intake/request.json", request)
        self.store.text(run_dir, "intake/prompt.md", prompt)
        self.store.register(
            run_dir,
            intake_request="intake/request.json",
            intake_prompt="intake/prompt.md",
        )
        try:
            brief, response = self.text_provider.propose(
                prompt,
                schema_name=profile.brief_schema,
            )
            if "user_requirements" in state:
                brief = {**brief, "user_requirements": list(state["user_requirements"])}
            brief = validate(bind_brief_language(brief, state.get("content_language")), profile.brief_schema)
            self.store.json(run_dir, "intake/response.json", response)
            self.store.json(run_dir, "brief.json", brief)
            self.store.register(
                run_dir,
                intake_response="intake/response.json",
                brief="brief.json",
            )
            return {"brief": brief, "content_language": brief.get("content_language"), "status": "designing"}
        except Exception as exc:
            self.store.json(run_dir, "intake/response.json", {
                "status": "failed",
                "error_type": type(exc).__name__,
                "message": str(exc),
            })
            self.store.register(run_dir, intake_response="intake/response.json")
            raise

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

    @staticmethod
    def _generation_binding(state: AtelierState, candidate: dict[str, Any]) -> dict[str, Any]:
        binding = {
            "candidate_id": candidate["candidate_id"],
            "direction_seed": candidate["direction_seed"],
            "prompt": candidate["generation_prompt"],
            "request": candidate["generation_request"],
            "proposal": candidate["proposal"],
            "image_spec": candidate["image_spec"],
            "generation_size": state["generation_size"],
            "output_ratio": list(state["output_ratio"]),
            "canvas": state["canvas"],
        }
        return binding

    @staticmethod
    def _candidate_dir(run_dir: Path, candidate_id: str) -> Path:
        return run_dir / "candidates" / candidate_id

    @staticmethod
    def _batch_digest(candidates: list[dict[str, Any]]) -> str:
        """Bind approval to candidate availability and each exact generation request."""
        return digest_json([
            {"candidate_id": candidate["candidate_id"], "status": candidate["status"],
             "generation_digest": candidate.get("generation_digest")}
            for candidate in candidates
        ])

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
                    historical_knowledge=load_historical_cards(
                        profile.objective, seed["movement_references"],
                    ),
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

    def compile_candidates(self, state: AtelierState) -> AtelierState:
        run_dir = self._dir(state)
        target_model = getattr(
            self.image_provider, "model", type(self.image_provider).__name__,
        )
        self.store.update(run_dir, "compiling_candidates")

        def compile_one(candidate):
            if candidate["status"] != "implemented":
                return candidate
            candidate_id = candidate["candidate_id"]
            root = self._candidate_dir(run_dir, candidate_id)
            prompt = ""
            try:
                prompt, image_spec, response = synthesize_image_spec(
                    candidate["proposal"],
                    brief=state["brief"],
                    canvas=state["canvas"],
                    provider_profile=target_model,
                    provider=self.text_provider,
                    content_language=state.get("content_language"),
                )
                image_spec = validate_image_spec(
                    image_spec, state["brief"].get("exact_copy", []),
                )
                request = {
                    "model": getattr(
                        self.text_provider, "model", type(self.text_provider).__name__,
                    ),
                    "target_image_model": target_model,
                    "schema": "image-spec.schema.json",
                    "candidate_id": candidate_id,
                }
                self.store.json(root, "image-spec/request.json", request)
                self.store.text(root, "image-spec/prompt.md", prompt)
                self.store.json(root, "image-spec/response.json", response)
                self.store.json(root, "image-spec/image-spec.json", image_spec)
                generation_prompt = compile_generation_prompt(
                    image_spec, user_requirements=state["brief"].get("user_requirements", []),
                )
                self.store.text(root, "generation/prompt.md", generation_prompt)
                generation_request = self.image_provider.describe_request(
                    generation_prompt, size=state["generation_size"],
                )
                self.store.json(
                    root, "generation/request-preview.json", generation_request,
                )
                prepared = {
                    **candidate,
                    "image_spec": image_spec,
                    "generation_prompt": generation_prompt,
                    "generation_request": generation_request,
                    "status": "ready",
                }
                prepared["generation_digest"] = digest_json(
                    self._generation_binding(state, prepared)
                )
                return prepared
            except Exception as exc:
                if prompt:
                    self.store.text(root, "image-spec/prompt.md", prompt)
                self.store.json(root, "image-spec/error.json", {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                })
                return {
                    **candidate,
                    "status": "failed",
                    "error": {"stage": "image_spec", "type": type(exc).__name__, "message": str(exc)},
                }

        with ThreadPoolExecutor(max_workers=len(state["candidates"])) as executor:
            candidates = list(executor.map(compile_one, state["candidates"]))
        candidates.sort(key=lambda item: item["candidate_id"])
        ready = [candidate for candidate in candidates if candidate["status"] == "ready"]
        if not ready:
            self.store.json(run_dir, "candidates/index.json", candidates)
            raise ValueError("No candidate reached generation preview.")
        batch_digest = self._batch_digest(candidates)
        self.store.json(run_dir, "candidates/index.json", candidates)
        first = ready[0]["candidate_id"]
        self.store.register(
            run_dir,
            candidate_index="candidates/index.json",
            proposal=f"candidates/{first}/design-implementation/proposal.json",
            presentation=f"candidates/{first}/design-implementation/presentation.md",
            design_prompt=f"candidates/{first}/design-implementation/prompt.md",
            design_implementation_prompt=(
                f"candidates/{first}/design-implementation/prompt.md"
            ),
            image_spec=f"candidates/{first}/image-spec/image-spec.json",
            generation_prompt=f"candidates/{first}/generation/prompt.md",
            generation_request_preview=f"candidates/{first}/generation/request-preview.json",
        )
        return {
            "candidates": candidates,
            "batch_digest": batch_digest,
            "status": "awaiting_approval",
        }

    def approval(self, state: AtelierState) -> AtelierState:
        run_dir = self._dir(state)
        profile = get_profile(state["profile"])
        ready = [candidate for candidate in state["candidates"] if candidate["status"] == "ready"]
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
                    "proposal": str((
                        self._candidate_dir(run_dir, candidate["candidate_id"])
                        / "design-implementation/proposal.json"
                    ).resolve()),
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
            "failed_candidates": [
                candidate["candidate_id"]
                for candidate in state["candidates"]
                if candidate["status"] == "failed"
            ],
        }
        self.store.update(run_dir, "awaiting_approval", approval_request=payload)
        decision = interrupt(payload)
        if not isinstance(decision, dict) or not isinstance(decision.get("approved"), bool):
            raise ValueError("Human approval must be an explicit boolean decision.")
        record = {
            **decision,
            "decided_at": datetime.now(timezone.utc).isoformat(),
            "batch_digest": state["batch_digest"],
        }
        self.store.json(run_dir, "approval/decision.json", record)
        self.store.register(run_dir, approval="approval/decision.json")
        if not decision["approved"]:
            self.store.update(run_dir, "rejected", approval=record)
            return {"approval": record, "status": "rejected"}
        return {"approval": record, "status": "generating_candidates"}

    def _validate_candidate_preview(self, state: AtelierState, candidate: dict[str, Any]) -> str:
        run_dir = self._dir(state)
        root = self._candidate_dir(run_dir, candidate["candidate_id"])
        saved_prompt = (root / "generation/prompt.md").read_text(encoding="utf-8")
        saved_proposal = read_json(root / "design-implementation/proposal.json")
        saved_image_spec = read_json(root / "image-spec/image-spec.json")
        saved_request = read_json(root / "generation/request-preview.json")
        current_request = self.image_provider.describe_request(
            candidate["generation_prompt"], size=state["generation_size"],
        )
        if (
            saved_prompt != candidate["generation_prompt"]
            or saved_proposal != candidate["proposal"]
            or saved_image_spec != candidate["image_spec"]
            or saved_request != candidate["generation_request"]
            or current_request != candidate["generation_request"]
        ):
            raise ValueError("Approved generation artifacts changed after preview.")
        actual = digest_json(self._generation_binding(state, candidate))
        if actual != candidate["generation_digest"]:
            raise ValueError("Approved generation content changed.")
        return actual

    def generate_candidates(self, state: AtelierState) -> AtelierState:
        run_dir = self._dir(state)
        if state["approval"].get("batch_digest") != state["batch_digest"]:
            raise ValueError("Approval does not bind to the current candidate batch.")

        ready = [candidate for candidate in state["candidates"] if candidate["status"] == "ready"]
        current_batch = self._batch_digest(state["candidates"])
        if current_batch != state["batch_digest"]:
            raise ValueError("Approved candidate batch changed.")
        for candidate in ready:
            self._validate_candidate_preview(state, candidate)

        self.store.update(run_dir, "generating_candidates")

        def generate_one(candidate):
            candidate_id = candidate["candidate_id"]
            root = self._candidate_dir(run_dir, candidate_id)
            attempt = self.store.next_attempt(root, "generation")
            write_json(attempt / "image-spec.json", candidate["image_spec"])
            try:
                response = self.image_provider.generate(
                    candidate["generation_prompt"],
                    size=state["generation_size"],
                    output=attempt,
                )
                image_path = (attempt / response["file"]).resolve()
                image_path, render_record = normalize_canvas(
                    image_path, tuple(state["output_ratio"]),
                )
                response.update(
                    file=image_path.name,
                    sha256=digest_file(image_path),
                    render=render_record,
                )
                write_json(attempt / "response.json", response)
                relative = attempt.relative_to(run_dir).as_posix()
                return {
                    **candidate,
                    "status": "generated",
                    "image_path": str(image_path),
                    "image_sha256": digest_file(image_path),
                    "generation_artifacts": {
                        "request": f"{relative}/request.json",
                        "response": f"{relative}/response.json",
                        "render": f"{relative}/render.json",
                        "image": f"{relative}/image.png",
                    },
                }
            except Exception as exc:
                return {
                    **candidate,
                    "status": "failed",
                    "error": {"stage": "generation", "type": type(exc).__name__, "message": str(exc)},
                }

        with ThreadPoolExecutor(max_workers=len(ready)) as executor:
            generated = list(executor.map(generate_one, ready))
        updates = {candidate["candidate_id"]: candidate for candidate in generated}
        candidates = [updates.get(candidate["candidate_id"], candidate) for candidate in state["candidates"]]
        successful = [candidate for candidate in candidates if candidate["status"] == "generated"]
        self.store.json(run_dir, "candidates/index.json", candidates)
        if not successful:
            self.store.update(run_dir, "failed", error="All candidate generations failed.")
            raise RuntimeError("All candidate generations failed.")

        self.store.update(run_dir, "awaiting_selection")
        return {"candidates": candidates, "status": "awaiting_selection"}

    def selection(self, state: AtelierState) -> AtelierState:
        run_dir = self._dir(state)
        successful = [candidate for candidate in state["candidates"] if candidate["status"] == "generated"]
        payload = {
            "run_id": state["run_id"],
            "candidates": [
                {
                    "candidate_id": candidate["candidate_id"],
                    "label": candidate["direction_seed"]["label"],
                    "image_path": candidate["image_path"],
                    "image_sha256": candidate["image_sha256"],
                }
                for candidate in successful
            ],
        }
        self.store.update(run_dir, "awaiting_selection", selection_request=payload)
        decision = interrupt(payload)
        if not isinstance(decision, dict):
            raise ValueError("Candidate selection must be a dictionary.")
        selected_id = decision.get("selected_candidate_id")
        if selected_id is not None and not isinstance(selected_id, str):
            raise ValueError("Selected candidate id must be a string or null.")
        selected = next(
            (candidate for candidate in successful if candidate["candidate_id"] == selected_id),
            None,
        )
        if selected_id is not None and selected is None:
            raise ValueError("Cannot select a missing or failed candidate.")
        if selected is not None and digest_file(Path(selected["image_path"])) != selected["image_sha256"]:
            raise ValueError("Selected candidate image changed after generation.")
        record = {
            **decision,
            "selected_image_sha256": selected["image_sha256"] if selected else None,
            "decided_at": datetime.now(timezone.utc).isoformat(),
        }
        self.store.json(run_dir, "selection/decision.json", record)
        self.store.register(run_dir, selection="selection/decision.json")
        details = {
            "selection": record,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        if selected is not None:
            details.update(
                latest_image=selected["image_path"],
                image_sha256=selected["image_sha256"],
            )
            self.store.register(
                run_dir,
                generation_request=selected["generation_artifacts"]["request"],
                generation_response=selected["generation_artifacts"]["response"],
                render=selected["generation_artifacts"]["render"],
                image=selected["generation_artifacts"]["image"],
            )
        self.store.update(run_dir, "completed", **details)
        return {
            "selection": record,
            "image_path": selected["image_path"] if selected else "",
            "status": "completed",
        }
