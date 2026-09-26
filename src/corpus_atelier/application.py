"""UI-neutral application service for one approval-gated generation experiment."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt

from .artifacts.hashing import digest_file, digest_json
from .artifacts.records import write_json
from .artifacts.store import ArtifactStore, validate_case_id, validate_run_id
from .design_direction import (
    load_historical_cards,
    synthesize_design_directions,
    validate_design_direction_plan,
)
from .design_implementation.presentation import render
from .design_implementation.synthesis import synthesize_design_implementation
from .design_support.canvas import resolve_canvas
from .design_support.rendering import normalize_canvas
from .design_support.validation import validate, validate_image_spec, validate_proposal
from .graphs import build_graph
from .image_prompt import compile_generation_prompt, synthesize_image_spec
from .intake import compile_intake_prompt
from .materials import build_reference_package, load_snapshot
from .providers import OpenAIImageProvider, OpenAITextProvider
from .registry import get_profile
from .state import (
    ComparisonResult,
    CorpusComparisonJob,
    CorpusExperimentJob,
    DesignJob,
    NaturalLanguageDesignJob,
    RunResult,
    RunSummary,
)


class _Runtime:
    def __init__(self, store, text_provider, image_provider):
        self.store = store
        self.text_provider = text_provider
        self.image_provider = image_provider

    @staticmethod
    def _dir(state):
        return Path(state["run_dir"])

    def interpret_request(self, state):
        run_dir = self._dir(state)
        profile = get_profile(state["profile"])
        self.store.update(run_dir, "interpreting_request")
        prompt = compile_intake_prompt(profile, state["user_request"])
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
            brief = validate(brief, profile.brief_schema)
            self.store.json(run_dir, "intake/response.json", response)
            self.store.json(run_dir, "brief.json", brief)
            self.store.register(
                run_dir,
                intake_response="intake/response.json",
                brief="brief.json",
            )
            result = {"brief": brief, "status": "designing"}
            if state.get("experiment") is not None:
                experiment = {
                    **state["experiment"],
                    "shared_brief_sha256": digest_json(brief),
                }
                self.store.update(run_dir, "designing", experiment=experiment)
                result["experiment"] = experiment
            return result
        except Exception as exc:
            self.store.json(run_dir, "intake/response.json", {
                "status": "failed",
                "error_type": type(exc).__name__,
                "message": str(exc),
            })
            self.store.register(run_dir, intake_response="intake/response.json")
            raise

    def prepare_corpus(self, state):
        """Resolve the immutable corpus only for the explicit experimental arm."""
        run_dir = self._dir(state)
        self.store.update(run_dir, "preparing_corpus")
        package, path = build_reference_package(
            Path(state["snapshot"]), state["reference_selection"],
        )
        self.store.json(
            run_dir, "reference/selection.json", state["reference_selection"],
        )
        self.store.json(run_dir, "reference/package.json", package)
        self.store.register(
            run_dir,
            reference_selection="reference/selection.json",
            reference_package="reference/package.json",
        )
        return {
            "reference_package": package,
            "reference_image_paths": [str(path)],
            "status": "designing",
        }

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
    def _generation_binding(state, candidate):
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
        if state.get("experiment") is not None:
            binding["experiment"] = state["experiment"]
        if state.get("reference_package") is not None:
            binding["reference"] = state["reference_package"]
        return binding

    @staticmethod
    def _candidate_dir(run_dir: Path, candidate_id: str) -> Path:
        return run_dir / "candidates" / candidate_id

    def design_directions(self, state):
        run_dir = self._dir(state)
        profile = get_profile(state["profile"])
        candidate_limit = state.get("candidate_limit", 1)
        if isinstance(candidate_limit, bool) or candidate_limit not in {1, 2, 3}:
            raise ValueError("Candidate limit must be 1, 2, or 3.")
        generation_size, output_ratio, canvas = self._resolve_canvas(
            profile, state["brief"],
        )
        self.store.update(
            run_dir, "designing_directions", candidate_limit=candidate_limit,
        )
        prompt = ""
        try:
            prompt, raw_plan, response = synthesize_design_directions(
                profile,
                state["brief"],
                self.text_provider,
                canvas=canvas,
                candidate_limit=candidate_limit,
                design_knowledge=(state.get("reference_package") or {}).get("reference"),
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

    def implement_designs(self, state):
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
                    [Path(path) for path in state.get("reference_image_paths", [])],
                    design_knowledge=(state.get("reference_package") or {}).get("reference"),
                    canvas=state["canvas"],
                    direction_seed=seed,
                    historical_knowledge=load_historical_cards(
                        profile.objective, seed["movement_references"],
                    ),
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
                if state.get("reference_package") is not None:
                    request["references"] = state["reference_package"]
                self.store.json(root, "design-implementation/request.json", request)
                self.store.text(root, "design-implementation/prompt.md", prompt)
                self.store.json(root, "design-implementation/response.json", response)
                self.store.json(root, "design-implementation/proposal.json", proposal)
                self.store.text(
                    root, "design-implementation/presentation.md", render(proposal),
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

    def compile_candidates(self, state):
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
                generation_prompt = compile_generation_prompt(image_spec)
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
        batch_digest = digest_json([
            {
                "candidate_id": candidate["candidate_id"],
                "status": candidate["status"],
                "generation_digest": candidate.get("generation_digest"),
            }
            for candidate in candidates
        ])
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

    def approval(self, state):
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
        if state.get("experiment") is not None:
            payload["experiment"] = state["experiment"]
        if state.get("reference_package") is not None:
            payload["reference_artifacts"] = {
                "reference_selection": str(
                    (run_dir / "reference/selection.json").resolve()
                ),
                "reference_package": str(
                    (run_dir / "reference/package.json").resolve()
                ),
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

    def _validate_candidate_preview(self, state, candidate):
        run_dir = self._dir(state)
        root = self._candidate_dir(run_dir, candidate["candidate_id"])
        saved_prompt = (root / "generation/prompt.md").read_text(encoding="utf-8")
        saved_proposal = json.loads((
            root / "design-implementation/proposal.json"
        ).read_text(encoding="utf-8"))
        saved_image_spec = json.loads((root / "image-spec/image-spec.json").read_text(encoding="utf-8"))
        saved_request = json.loads((root / "generation/request-preview.json").read_text(encoding="utf-8"))
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

    def generate_candidates(self, state):
        run_dir = self._dir(state)
        if state.get("reference_package") is not None:
            saved_selection = json.loads(
                (run_dir / "reference/selection.json").read_text(encoding="utf-8")
            )
            saved_reference = json.loads(
                (run_dir / "reference/package.json").read_text(encoding="utf-8")
            )
            if (
                saved_selection != state["reference_selection"]
                or saved_reference != state["reference_package"]
            ):
                raise ValueError("Approved generation artifacts changed after preview.")
            current_reference, _ = build_reference_package(
                Path(state["snapshot"]), state["reference_selection"],
            )
            if current_reference != state["reference_package"]:
                raise ValueError("Approved corpus evidence changed after preview.")
        if state["approval"].get("batch_digest") != state["batch_digest"]:
            raise ValueError("Approval does not bind to the current candidate batch.")

        ready = [candidate for candidate in state["candidates"] if candidate["status"] == "ready"]
        current_batch = digest_json([
            {
                "candidate_id": candidate["candidate_id"],
                "status": candidate["status"],
                "generation_digest": candidate.get("generation_digest"),
            }
            for candidate in state["candidates"]
        ])
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

        if state.get("experiment") is not None:
            selected = successful[0]
            self.store.register(
                run_dir,
                generation_request=selected["generation_artifacts"]["request"],
                generation_response=selected["generation_artifacts"]["response"],
                render=selected["generation_artifacts"]["render"],
                image=selected["generation_artifacts"]["image"],
            )
            self.store.update(
                run_dir,
                "completed",
                latest_image=selected["image_path"],
                image_sha256=selected["image_sha256"],
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            return {"candidates": candidates, "image_path": selected["image_path"], "status": "completed"}

        self.store.update(run_dir, "awaiting_selection")
        return {"candidates": candidates, "status": "awaiting_selection"}

    def selection(self, state):
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


class CorpusAtelierApplication:
    def __init__(self, *, runs_root: Path | str = "experiments/runs",
                 text_provider=None, image_provider=None):
        self.store = ArtifactStore(runs_root)
        self.runtime = _Runtime(
            self.store,
            text_provider or OpenAITextProvider(),
            image_provider or OpenAIImageProvider(),
        )
        self.checkpointer = InMemorySaver()
        self.graph = build_graph(self.runtime, self.checkpointer)
        self._active: dict[str, dict] = {}

    def _update_comparison_group(self, run_dir: Path) -> None:
        manifest = self.store.manifest(run_dir)
        experiment = manifest.get("experiment", {})
        group_id = experiment.get("group_id")
        if not group_id:
            return
        group_dir = self.store.root / "_comparisons" / manifest["case_id"] / group_id
        group_manifest = self.store.manifest(group_dir)
        arms = group_manifest.get("arms", {})
        statuses = {}
        for condition, arm_run_id in arms.items():
            arm_dir = self.store.root / manifest["case_id"] / arm_run_id
            statuses[condition] = self.store.manifest(arm_dir)["status"]
        terminal = {"completed", "rejected", "failed"}
        if "failed" in statuses.values():
            group_status = "failed"
        elif statuses and all(status in terminal for status in statuses.values()):
            group_status = "completed"
        else:
            group_status = "awaiting_approval"
        self.store.update(group_dir, group_status, arm_statuses=statuses)

    def _invoke_start(self, run_id: str, run_dir: Path, state: dict) -> RunResult:
        config = {"configurable": {"thread_id": run_id}}
        self._active[run_id] = {"config": config, "run_dir": run_dir}
        try:
            self.graph.invoke(state, config=config)
        except Exception as exc:
            self.store.update(
                run_dir, "failed", error_type=type(exc).__name__, error=str(exc),
            )
            raise
        return self._result(run_id)

    @staticmethod
    def _validate_request(request: str) -> str:
        if not isinstance(request, str) or not request.strip():
            raise ValueError("Natural-language design request must not be empty.")
        return request

    @staticmethod
    def _validate_candidate_count(candidate_count: int) -> int:
        if isinstance(candidate_count, bool) or candidate_count not in {1, 2, 3}:
            raise ValueError("Candidate limit must be 1, 2, or 3.")
        return candidate_count

    @staticmethod
    def _corpus_inputs(condition: str, snapshot, reference) -> tuple[Path | None, dict | None]:
        if condition not in {
            "baseline_no_explicit_corpus", "explicit_corpus",
        }:
            raise ValueError(f"Unsupported corpus experiment condition: {condition!r}.")
        if condition == "baseline_no_explicit_corpus":
            if snapshot is not None or reference is not None:
                raise ValueError(
                    "The no-explicit-corpus baseline cannot include corpus inputs."
                )
            return None, None
        if snapshot is None or reference is None:
            raise ValueError(
                "The explicit-corpus condition requires a snapshot and reference selection."
            )
        validate(reference, "reference-selection.schema.json")
        resolved = Path(snapshot).resolve(strict=True)
        load_snapshot(resolved)
        return resolved, reference

    @staticmethod
    def _experiment_record(
        *, condition: str, snapshot: Path | None = None,
        reference: dict | None = None, group_id: str | None = None,
        shared_brief_sha256: str | None = None,
    ) -> dict:
        record = {
            "kind": (
                "corpus_generation_comparison"
                if group_id is not None else
                "corpus_generation_experiment"
            ),
            "status": "experimental",
            "condition": condition,
        }
        if group_id is not None:
            record["group_id"] = group_id
        if shared_brief_sha256 is not None:
            record["shared_brief_sha256"] = shared_brief_sha256
        if snapshot is not None and reference is not None:
            snapshot_manifest, _ = load_snapshot(snapshot)
            record["corpus"] = {
                "snapshot_id": snapshot_manifest["snapshot_id"],
                "snapshot_path": str(snapshot),
                "reference_id": reference["reference_id"],
            }
        return record

    def _prepare_experiment_arm(
        self, *, case_id: str, profile, brief: dict, experiment: dict,
        snapshot: Path | None = None, reference: dict | None = None,
        original_request: str | None = None,
    ) -> tuple[str, Path, dict]:
        run_id, run_dir = self.store.create(
            case_id=case_id,
            brief=brief,
            profile=profile,
            experiment=experiment,
        )
        if original_request is not None:
            self.store.text(run_dir, "input/original-request.txt", original_request)
            self.store.json(run_dir, "input/shared-intake.json", {
                "group_id": experiment.get("group_id"),
                "shared_brief_sha256": experiment["shared_brief_sha256"],
            })
            self.store.register(
                run_dir,
                original_request="input/original-request.txt",
                shared_intake="input/shared-intake.json",
            )
        state = {
            "case_id": case_id,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "profile": profile.name,
            "brief": brief,
            "experiment": experiment,
            "candidate_limit": 1,
            "status": "created",
        }
        if snapshot is not None and reference is not None:
            state.update(
                snapshot=str(snapshot),
                reference_selection=reference,
            )
        return run_id, run_dir, state

    def start(self, job: DesignJob) -> RunResult:
        profile = get_profile(job.profile)
        candidate_count = self._validate_candidate_count(job.candidate_count)
        validate(job.brief, profile.brief_schema)
        run_id, run_dir = self.store.create(
            case_id=job.case_id,
            brief=job.brief,
            profile=profile,
        )
        state = {
            "case_id": job.case_id,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "profile": profile.name,
            "brief": job.brief,
            "candidate_limit": candidate_count,
            "status": "created",
        }
        return self._invoke_start(run_id, run_dir, state)

    def start_request(self, job: NaturalLanguageDesignJob) -> RunResult:
        self._validate_request(job.request)
        candidate_count = self._validate_candidate_count(job.candidate_count)
        profile = get_profile(job.profile)
        run_id, run_dir = self.store.create(
            case_id=job.case_id,
            request=job.request,
            profile=profile,
        )
        state = {
            "case_id": job.case_id,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "profile": profile.name,
            "user_request": job.request,
            "candidate_limit": candidate_count,
            "status": "created",
        }
        return self._invoke_start(run_id, run_dir, state)

    def start_experiment(self, job: CorpusExperimentJob) -> RunResult:
        """Start one explicitly labelled corpus-comparison condition."""
        self._validate_request(job.request)
        profile = get_profile(job.profile)
        snapshot, reference = self._corpus_inputs(
            job.condition, job.snapshot, job.reference,
        )
        experiment = self._experiment_record(
            condition=job.condition,
            snapshot=snapshot,
            reference=reference,
        )
        run_id, run_dir = self.store.create(
            case_id=job.case_id,
            request=job.request,
            profile=profile,
            experiment=experiment,
        )
        state = {
            "case_id": job.case_id,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "profile": profile.name,
            "user_request": job.request,
            "experiment": experiment,
            "candidate_limit": 1,
            "status": "created",
        }
        if snapshot is not None and reference is not None:
            state.update(
                snapshot=str(snapshot),
                reference_selection=reference,
            )
        return self._invoke_start(run_id, run_dir, state)

    def start_comparison(self, job: CorpusComparisonJob) -> ComparisonResult:
        """Interpret one request once, then start two approval-gated experiment arms."""
        self._validate_request(job.request)
        profile = get_profile(job.profile)
        snapshot, reference = self._corpus_inputs(
            "explicit_corpus", job.snapshot, job.reference,
        )
        group_id, group_dir = self.store.create_comparison(
            case_id=job.case_id,
            profile=profile,
            request=job.request,
        )
        prompt = compile_intake_prompt(profile, job.request)
        request_record = {
            "model": getattr(
                self.runtime.text_provider,
                "model",
                type(self.runtime.text_provider).__name__,
            ),
            "profile": profile.name,
            "schema": profile.brief_schema,
        }
        self.store.update(group_dir, "interpreting_request")
        self.store.json(group_dir, "intake/request.json", request_record)
        self.store.text(group_dir, "intake/prompt.md", prompt)
        self.store.register(
            group_dir,
            intake_request="intake/request.json",
            intake_prompt="intake/prompt.md",
        )
        try:
            brief, response = self.runtime.text_provider.propose(
                prompt,
                schema_name=profile.brief_schema,
            )
            brief = validate(brief, profile.brief_schema)
            self.store.json(group_dir, "intake/response.json", response)
            self.store.json(group_dir, "brief.json", brief)
            self.store.register(
                group_dir,
                intake_response="intake/response.json",
                brief="brief.json",
            )
        except Exception as exc:
            self.store.json(group_dir, "intake/response.json", {
                "status": "failed",
                "error_type": type(exc).__name__,
                "message": str(exc),
            })
            self.store.register(group_dir, intake_response="intake/response.json")
            self.store.update(
                group_dir, "failed", error_type=type(exc).__name__, error=str(exc),
            )
            raise

        brief_sha256 = digest_json(brief)
        baseline_experiment = self._experiment_record(
            condition="baseline_no_explicit_corpus",
            group_id=group_id,
            shared_brief_sha256=brief_sha256,
        )
        corpus_experiment = self._experiment_record(
            condition="explicit_corpus",
            snapshot=snapshot,
            reference=reference,
            group_id=group_id,
            shared_brief_sha256=brief_sha256,
        )
        baseline_start = self._prepare_experiment_arm(
            case_id=job.case_id,
            profile=profile,
            brief=brief,
            experiment=baseline_experiment,
            original_request=job.request,
        )
        corpus_start = self._prepare_experiment_arm(
            case_id=job.case_id,
            profile=profile,
            brief=brief,
            experiment=corpus_experiment,
            snapshot=snapshot,
            reference=reference,
            original_request=job.request,
        )
        starts = [baseline_start, corpus_start]
        conditions = [
            "baseline_no_explicit_corpus",
            "explicit_corpus",
        ]
        arms = {
            condition: start[0]
            for condition, start in zip(conditions, starts, strict=True)
        }
        self.store.update(
            group_dir,
            "designing",
            shared_brief_sha256=brief_sha256,
            arms=arms,
            arm_statuses={condition: "created" for condition in conditions},
        )

        configs = []
        for run_id, run_dir, _ in starts:
            config = {
                "configurable": {"thread_id": run_id},
                "max_concurrency": 2,
            }
            self._active[run_id] = {"config": config, "run_dir": run_dir}
            configs.append(config)

        try:
            outcomes = self.graph.batch(
                [state for _, _, state in starts],
                config=configs,
                return_exceptions=True,
            )
        except Exception as exc:
            statuses = {
                condition: self.store.manifest(run_dir)["status"]
                for condition, (_, run_dir, _) in zip(
                    conditions, starts, strict=True,
                )
            }
            self.store.update(
                group_dir,
                "failed",
                arm_statuses=statuses,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise

        failures = []
        for (_, run_dir, _), outcome in zip(starts, outcomes, strict=True):
            if isinstance(outcome, Exception):
                self.store.update(
                    run_dir,
                    "failed",
                    error_type=type(outcome).__name__,
                    error=str(outcome),
                )
                failures.append(outcome)

        results = [self._result(run_id) for run_id, _, _ in starts]
        baseline, corpus = results
        arm_statuses = {
            condition: result.status
            for condition, result in zip(conditions, results, strict=True)
        }
        if failures:
            failure = failures[0]
            self.store.update(
                group_dir,
                "failed",
                arm_statuses=arm_statuses,
                error_type=type(failure).__name__,
                error=str(failure),
            )
            raise failure
        self.store.update(
            group_dir,
            "awaiting_approval",
            shared_brief_sha256=brief_sha256,
            arms=arms,
            arm_statuses=arm_statuses,
        )
        return ComparisonResult(
            group_id=group_id,
            group_dir=group_dir,
            brief=brief,
            baseline=baseline,
            corpus=corpus,
        )

    def resume(self, run_id: str, decision: object) -> RunResult:
        if run_id not in self._active:
            raise ValueError("This process has no resumable checkpoint for the run.")
        active = self._active[run_id]
        run_dir = Path(active["run_dir"])
        try:
            if not hasattr(decision, "to_dict"):
                raise TypeError("A resumable decision must provide to_dict().")
            self.graph.invoke(
                Command(resume=decision.to_dict()), config=active["config"],
            )
        except Exception as exc:
            self.store.update(
                run_dir, "failed", error_type=type(exc).__name__, error=str(exc),
            )
            self._update_comparison_group(run_dir)
            raise
        result = self._result(run_id)
        self._update_comparison_group(run_dir)
        if result.status in {"completed", "rejected", "failed"}:
            self._active.pop(run_id, None)
        return result

    def resume_comparison(
        self, comparison: ComparisonResult, decision: object,
    ) -> ComparisonResult:
        """Apply one human decision to both arms and resume them concurrently."""
        if not hasattr(decision, "to_dict"):
            raise TypeError("A resumable decision must provide to_dict().")
        decision_payload = decision.to_dict()
        if not isinstance(decision_payload, dict):
            raise TypeError("A resumable decision must serialize to a dictionary.")

        arm_records = []
        for arm, condition in (
            ("baseline", "baseline_no_explicit_corpus"),
            ("corpus", "explicit_corpus"),
        ):
            result = getattr(comparison, arm)
            if result.run_id not in self._active:
                raise ValueError(
                    f"This process has no resumable checkpoint for the {arm} arm."
                )
            active = self._active[result.run_id]
            run_dir = Path(active["run_dir"])
            manifest = self.store.manifest(run_dir)
            experiment = manifest.get("experiment", {})
            if (
                experiment.get("group_id") != comparison.group_id
                or experiment.get("condition") != condition
            ):
                raise ValueError(
                    "Comparison approval does not match the active experiment arms."
                )
            if manifest["status"] != "awaiting_approval":
                raise ValueError(
                    f"The {arm} arm is not awaiting approval."
                )
            arm_records.append((arm, result.run_id, run_dir, active["config"]))

        try:
            outcomes = self.graph.batch(
                [
                    Command(resume=dict(decision_payload))
                    for _ in arm_records
                ],
                config=[record[3] for record in arm_records],
                return_exceptions=True,
            )
        except Exception as exc:
            for _, _, run_dir, _ in arm_records:
                status = self.store.manifest(run_dir)["status"]
                if status not in {"completed", "rejected", "failed"}:
                    self.store.update(
                        run_dir,
                        "failed",
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
            self._update_comparison_group(arm_records[0][2])
            raise

        for (_, _, run_dir, _), outcome in zip(
            arm_records, outcomes, strict=True,
        ):
            if isinstance(outcome, Exception):
                self.store.update(
                    run_dir,
                    "failed",
                    error_type=type(outcome).__name__,
                    error=str(outcome),
                )

        updated = {
            arm: self._result(run_id)
            for arm, run_id, _, _ in arm_records
        }
        self._update_comparison_group(arm_records[0][2])
        for result in updated.values():
            if result.status in {"completed", "rejected", "failed"}:
                self._active.pop(result.run_id, None)
        return ComparisonResult(
            group_id=comparison.group_id,
            group_dir=comparison.group_dir,
            brief=comparison.brief,
            baseline=updated["baseline"],
            corpus=updated["corpus"],
        )

    def inspect(self, case_id: str, run_id: str) -> RunSummary:
        case_id = validate_case_id(case_id)
        run_id = validate_run_id(run_id)
        run_dir = (self.store.root / case_id / run_id).resolve(strict=True)
        if self.store.root not in run_dir.parents:
            raise ValueError("Run id escapes the run store.")
        manifest = self.store.manifest(run_dir)
        return RunSummary(
            run_id=run_id,
            status=manifest["status"],
            run_dir=run_dir,
            manifest=manifest,
        )

    def _result(self, run_id: str) -> RunResult:
        active = self._active[run_id]
        run_dir = Path(active["run_dir"]).resolve(strict=True)
        manifest = self.store.manifest(run_dir)
        summary = RunSummary(
            run_id=run_id,
            status=manifest["status"],
            run_dir=run_dir,
            manifest=manifest,
        )
        registered = summary.manifest.get("artifacts", {})
        paths = {
            "manifest": summary.run_dir / "manifest.json",
            "proposal": summary.run_dir / "design/proposal.json",
            "presentation": summary.run_dir / "design/presentation.md",
            "generation_prompt": summary.run_dir / "generation/prompt.md",
            "image": Path(summary.manifest.get("latest_image", "")),
            "review": summary.run_dir / registered.get("review", "review/review.json"),
        }
        # Keep every registered artifact from archived workflow versions inspectable.
        for name, relative in registered.items():
            paths[name] = summary.run_dir / relative
        corpus = summary.manifest.get("experiment", {}).get("corpus")
        package_path = paths.get("reference_package")
        if corpus and package_path and package_path.is_file():
            package = json.loads(package_path.read_text(encoding="utf-8"))
            paths["reference_image"] = (
                Path(corpus["snapshot_path"]) / package["reference"]["file"]
            )

        artifacts = {
            name: str(path.resolve())
            for name, path in paths.items()
            if str(path) and path.is_file()
        }
        messages = {
            "awaiting_approval": "Review the saved proposal and generation prompt.",
            "awaiting_selection": "Review the generated candidates and select one or discard all.",
            "rejected": "Image generation was rejected; the experiment remains recorded.",
            "completed": "Image generation completed and artifacts were saved.",
            "failed": "The experiment failed; inspect its manifest and saved attempts.",
        }
        return RunResult(
            run_id=run_id,
            status=summary.status,
            run_dir=summary.run_dir,
            message=messages.get(summary.status, summary.status),
            artifacts=artifacts,
        )
