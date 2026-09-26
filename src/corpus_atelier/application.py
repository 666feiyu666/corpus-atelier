"""UI-neutral application service for durable, approval-gated design tasks."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver
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
from .providers import OpenAIImageProvider, OpenAITextProvider
from .registry import get_profile
from .state import (
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
            return {"brief": brief, "status": "designing"}
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
    def __init__(
        self,
        *,
        runs_root: Path | str = ".atelier/tasks",
        checkpoint_path: Path | str | None = None,
        text_provider=None,
        image_provider=None,
    ):
        self.store = ArtifactStore(runs_root)
        self.store.root.mkdir(parents=True, exist_ok=True)
        self.runtime = _Runtime(
            self.store,
            text_provider or OpenAITextProvider(),
            image_provider or OpenAIImageProvider(),
        )
        if checkpoint_path is None:
            checkpoint_path = self.store.root / "_system" / "checkpoints.sqlite3"
        if str(checkpoint_path) == ":memory:":
            checkpoint_target = ":memory:"
        else:
            checkpoint_path = Path(checkpoint_path).resolve()
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            checkpoint_target = str(checkpoint_path)
        self._checkpoint_connection = sqlite3.connect(
            checkpoint_target,
            check_same_thread=False,
        )
        self.checkpointer = SqliteSaver(self._checkpoint_connection)
        self.checkpointer.setup()
        self.graph = build_graph(self.runtime, self.checkpointer)

    @staticmethod
    def _provider_record(provider, *, fields: tuple[str, ...]) -> dict:
        record = {
            "adapter": f"{type(provider).__module__}.{type(provider).__name__}",
        }
        for field in fields:
            value = getattr(provider, field, None)
            if value is not None:
                record[field] = value
        return record

    def _models(self) -> dict:
        return {
            "text": self._provider_record(
                self.runtime.text_provider,
                fields=("model", "reasoning_effort"),
            ),
            "image": self._provider_record(
                self.runtime.image_provider,
                fields=("model", "quality"),
            ),
        }

    def close(self) -> None:
        connection = getattr(self, "_checkpoint_connection", None)
        if connection is not None:
            connection.close()
            self._checkpoint_connection = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _invoke_start(self, run_id: str, run_dir: Path, state: dict) -> RunResult:
        config = {"configurable": {"thread_id": run_id}}
        try:
            self.graph.invoke(state, config=config)
        except Exception as exc:
            self.store.update(
                run_dir,
                "failed",
                error_type=type(exc).__name__,
                error=str(exc),
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
    def _task_title(request: str) -> str:
        title = " ".join(request.split())
        return title if len(title) <= 56 else f"{title[:55]}…"

    def start(self, job: DesignJob) -> RunResult:
        profile = get_profile(job.profile)
        candidate_count = self._validate_candidate_count(job.candidate_count)
        validate(job.brief, profile.brief_schema)
        run_id, run_dir = self.store.create(
            case_id=job.case_id,
            brief=job.brief,
            profile=profile,
            title=job.case_id,
            models=self._models(),
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
            title=self._task_title(job.request),
            models=self._models(),
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

    def _assert_model_binding(self, run_dir: Path) -> None:
        expected = self.store.manifest(run_dir).get("models")
        if expected is not None and expected != self._models():
            raise ValueError(
                "Configured models changed after this task was created."
            )

    def resume(self, run_id: str, decision: object) -> RunResult:
        run_dir = self.store.find_run(run_id)
        manifest = self.store.manifest(run_dir)
        if manifest["status"] not in {"awaiting_approval", "awaiting_selection"}:
            raise ValueError("This task is not waiting for a user decision.")
        self._assert_model_binding(run_dir)
        if not hasattr(decision, "to_dict"):
            raise TypeError("A resumable decision must provide to_dict().")
        config = {"configurable": {"thread_id": run_id}}
        try:
            self.graph.invoke(
                Command(resume=decision.to_dict()),
                config=config,
            )
        except Exception as exc:
            self.store.update(
                run_dir,
                "failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise
        return self._result(run_id)

    def list_tasks(self) -> list[RunSummary]:
        return [
            RunSummary(
                run_id=manifest["run_id"],
                status=manifest["status"],
                run_dir=run_dir,
                manifest=manifest,
            )
            for run_dir, manifest in self.store.list_runs()
        ]

    def inspect_task(self, run_id: str) -> RunSummary:
        run_dir = self.store.find_run(run_id)
        manifest = self.store.manifest(run_dir)
        return RunSummary(
            run_id=run_id,
            status=manifest["status"],
            run_dir=run_dir,
            manifest=manifest,
        )

    def inspect(self, case_id: str, run_id: str) -> RunSummary:
        case_id = validate_case_id(case_id)
        run_id = validate_run_id(run_id)
        run_dir = (self.store.root / case_id / run_id).resolve(strict=True)
        if self.store.root not in run_dir.parents:
            raise ValueError("Run id escapes the task store.")
        manifest = self.store.manifest(run_dir)
        return RunSummary(
            run_id=run_id,
            status=manifest["status"],
            run_dir=run_dir,
            manifest=manifest,
        )

    def open_task(self, run_id: str) -> RunResult:
        return self._result(run_id)

    def _result(self, run_id: str) -> RunResult:
        run_dir = self.store.find_run(run_id)
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
            "review": (
                summary.run_dir
                / registered.get("review", "review/review.json")
            ),
        }
        for name, relative in registered.items():
            paths[name] = summary.run_dir / relative

        artifacts = {
            name: str(path.resolve())
            for name, path in paths.items()
            if str(path) and path.is_file()
        }
        messages = {
            "awaiting_approval": (
                "Review the saved design proposals and exact image requests."
            ),
            "awaiting_selection": (
                "Review the generated candidates and select one or discard all."
            ),
            "rejected": "Image generation was cancelled; the task remains saved.",
            "completed": "The task completed and its artifacts were saved.",
            "failed": "The task failed; inspect its saved attempts and error record.",
        }
        return RunResult(
            run_id=run_id,
            status=summary.status,
            run_dir=summary.run_dir,
            message=messages.get(summary.status, summary.status),
            artifacts=artifacts,
        )
