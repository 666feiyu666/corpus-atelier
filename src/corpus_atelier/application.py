"""UI-neutral application service for one review-gated generation experiment."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt

from .artifacts.hashing import digest_file, digest_json
from .artifacts.records import write_json
from .artifacts.store import ArtifactStore
from .design.presentation import render
from .design.canvas import resolve_canvas
from .design.prompt_compiler import (
    compile_generation_prompt,
    compile_reference_plan_prompt,
    compile_review_prompt,
)
from .design.rendering import normalize_canvas
from .design.synthesis import synthesize
from .design.validation import validate, validate_proposal, validate_reference_plan
from .graphs import build_graph
from .materials import build_material_package, load_snapshot
from .providers import OpenAIImageProvider, OpenAITextProvider
from .registry import get_profile
from .state import DesignJob, RunResult, RunSummary


class _Runtime:
    def __init__(self, store, text_provider, image_provider):
        self.store = store
        self.text_provider = text_provider
        self.image_provider = image_provider

    @staticmethod
    def _dir(state):
        return Path(state["run_dir"])

    def prepare_inputs(self, state):
        run_dir = self._dir(state)
        self.store.update(run_dir, "preparing_inputs")
        if state["generation_mode"] == "without_corpus":
            return {
                "materials_package": None,
                "reference_image_paths": [],
                "status": "designing",
            }

        self.store.update(run_dir, "loading_materials")
        package, paths = build_material_package(
            Path(state["snapshot"]), state["materials_selection"],
        )
        reference_mode = state["brief"].get("reference_mode")
        expected_count = state["brief"].get("reference_count", 0)
        actual_count = len(package["references"])
        if reference_mode and actual_count != expected_count:
            raise ValueError(
                "The explicit reference selection must match brief.reference_count."
            )
        if not reference_mode and actual_count:
            raise ValueError("Reference images require an explicit reference_mode in the brief.")
        self.store.json(run_dir, "materials/selection.json", state["materials_selection"])
        self.store.json(run_dir, "materials/package.json", package)
        self.store.register(
            run_dir,
            materials_selection="materials/selection.json",
            materials_package="materials/package.json",
        )
        return {
            "materials_package": package,
            "reference_image_paths": [str(path) for path in paths],
            "status": "planning_references" if reference_mode else "designing",
        }

    def plan_references(self, state):
        mode = state["brief"].get("reference_mode")
        schemas = {
            "style_grounded": "style-grounded-plan.schema.json",
            "style_inspired": "style-inspired-plan.schema.json",
        }
        if mode not in schemas:
            raise ValueError(f"Unsupported reference mode: {mode!r}.")
        run_dir = self._dir(state)
        self.store.update(run_dir, "planning_references")
        schema = schemas[mode]
        prompt = compile_reference_plan_prompt(
            mode=mode, brief=state["brief"], materials=state["materials_package"],
        )
        request = {
            "model": getattr(self.text_provider, "model", type(self.text_provider).__name__),
            "schema": schema,
            "reference_mode": mode,
            "references": [
                {"id": row["id"], "sha256": row["sha256"]}
                for row in state["materials_package"]["references"]
            ],
        }
        self.store.json(run_dir, "reference/request.json", request)
        self.store.text(run_dir, "reference/prompt.md", prompt)
        plan, response = self.text_provider.plan_references(
            prompt,
            [Path(path) for path in state["reference_image_paths"]],
            schema_name=schema,
        )
        self.store.json(run_dir, "reference/response.json", response)
        self.store.json(run_dir, "reference/plan.json", plan)
        available_ids = {
            row["id"]
            for kind in ("references", "knowledge")
            for row in state["materials_package"][kind]
        }
        validate_reference_plan(
            plan, schema_name=schema, mode=mode, available_ids=available_ids,
        )
        self.store.register(
            run_dir,
            reference_request="reference/request.json",
            reference_prompt="reference/prompt.md",
            reference_response="reference/response.json",
            reference_plan="reference/plan.json",
        )
        return {"reference_plan_prompt": prompt, "reference_plan": plan, "status": "designing"}

    @staticmethod
    def _generation_binding(state, *, proposal, prompt):
        binding = {
            "generation_mode": state["generation_mode"],
            "prompt": prompt,
            "proposal": proposal,
            "generation_size": state["generation_size"],
            "output_ratio": list(state["output_ratio"]),
            "canvas": state["canvas"],
        }
        if state["generation_mode"] == "with_corpus":
            binding["materials"] = state["materials_package"]
        if state.get("reference_plan") is not None:
            binding.update(
                reference_mode=state["brief"]["reference_mode"],
                reference_plan=state["reference_plan"],
            )
        return binding

    def design(self, state):
        run_dir = self._dir(state)
        profile = get_profile(state["profile"])
        self.store.update(run_dir, "designing")
        prompt = ""
        try:
            prompt, proposal, response = synthesize(
                profile,
                state["brief"],
                state["materials_package"],
                self.text_provider,
                state.get("reference_plan"),
            )
            request = {
                "model": getattr(self.text_provider, "model", type(self.text_provider).__name__),
                "profile": profile.name,
                "schema": profile.proposal_schema,
            }
            self.store.json(run_dir, "design/request.json", request)
            self.store.text(run_dir, "design/prompt.md", prompt)
            self.store.json(run_dir, "design/response.json", response)
            self.store.json(run_dir, "design/proposal.json", proposal)
            proposal = validate_proposal(proposal, profile.proposal_schema)
            materials = state.get("materials_package")
            available_ids = {
                row["id"]
                for kind in ("references", "knowledge")
                for row in (materials or {}).get(kind, [])
            }
            if state["generation_mode"] == "without_corpus" and proposal["evidence_ids"]:
                raise ValueError("A without-corpus proposal cannot cite corpus evidence.")
            unknown = sorted(set(proposal["evidence_ids"]) - available_ids)
            if unknown:
                raise ValueError(f"Design proposal cites unavailable evidence IDs: {unknown}.")
            self.store.text(run_dir, "design/presentation.md", render(proposal))
            self.store.register(
                run_dir,
                design_request="design/request.json",
                design_prompt="design/prompt.md",
                design_response="design/response.json",
                proposal="design/proposal.json",
                presentation="design/presentation.md",
            )
            if proposal["status"] != "ready":
                self.store.update(run_dir, proposal["status"])
                raise ValueError(f"Design proposal is blocked: {proposal['status']}.")
            if profile.deliverable == "graphic-design.v1":
                generation_size, output_ratio, canvas = resolve_canvas(
                    proposal["image_spec"], state["brief"],
                )
            else:
                generation_size = profile.default_size
                output_ratio = profile.output_ratio
                canvas = {
                    "size": generation_size,
                    "ratio": list(output_ratio),
                    "mode": "profile_default",
                }
            self.store.json(run_dir, "generation/canvas.json", canvas)
            generation_prompt = compile_generation_prompt(
                proposal, state.get("reference_plan"),
            )
            self.store.text(run_dir, "generation/prompt.md", generation_prompt)
            self.store.register(
                run_dir,
                generation_prompt="generation/prompt.md",
                canvas="generation/canvas.json",
            )
            generation_state = {
                **state,
                "generation_size": generation_size,
                "output_ratio": output_ratio,
                "canvas": canvas,
            }
            digest = digest_json(self._generation_binding(
                generation_state, proposal=proposal, prompt=generation_prompt,
            ))
            return {
                "design_prompt": prompt,
                "proposal": proposal,
                "generation_prompt": generation_prompt,
                "generation_size": generation_size,
                "output_ratio": output_ratio,
                "canvas": canvas,
                "generation_digest": digest,
            }
        except Exception as exc:
            if prompt:
                self.store.text(run_dir, "design/prompt.md", prompt)
            error_path = (
                "design/error.json"
                if (run_dir / "design/response.json").exists()
                else "design/response.json"
            )
            self.store.json(run_dir, error_path, {
                "status": "failed",
                "error_type": type(exc).__name__,
                "message": str(exc),
            })
            self.store.register(run_dir, design_error=error_path)
            raise

    def approval(self, state):
        run_dir = self._dir(state)
        profile = get_profile(state["profile"])
        payload = {
            "run_id": state["run_id"],
            "profile": profile.name,
            "generation_mode": state["generation_mode"],
            "generation_digest": state["generation_digest"],
            "artifacts": {
                "proposal": str((run_dir / "design/proposal.json").resolve()),
                "presentation": str((run_dir / "design/presentation.md").resolve()),
                "generation_prompt": str((run_dir / "generation/prompt.md").resolve()),
                "canvas": str((run_dir / "generation/canvas.json").resolve()),
            },
        }
        if state["generation_mode"] == "with_corpus":
            payload["artifacts"].update({
                "materials_selection": str((run_dir / "materials/selection.json").resolve()),
                "materials_package": str((run_dir / "materials/package.json").resolve()),
            })
        if state.get("reference_plan") is not None:
            payload["reference_mode"] = state["brief"]["reference_mode"]
            payload["artifacts"].update({
                "reference_plan": str((run_dir / "reference/plan.json").resolve()),
                "reference_prompt": str((run_dir / "reference/prompt.md").resolve()),
            })
        self.store.update(run_dir, "awaiting_approval", approval_request=payload)
        decision = interrupt(payload)
        if not isinstance(decision, dict) or not isinstance(decision.get("approved"), bool):
            raise ValueError("Human approval must be an explicit boolean decision.")
        record = {
            **decision,
            "decided_at": datetime.now(timezone.utc).isoformat(),
            "generation_digest": state["generation_digest"],
        }
        self.store.json(run_dir, "generation/approval.json", record)
        self.store.register(run_dir, approval="generation/approval.json")
        if not decision["approved"]:
            self.store.update(run_dir, "rejected", approval=record)
            return {"approval": record, "status": "rejected"}
        return {"approval": record, "status": "generating"}

    def generate(self, state):
        run_dir = self._dir(state)
        saved_prompt = (run_dir / "generation/prompt.md").read_text(encoding="utf-8")
        saved_proposal = json.loads(
            (run_dir / "design/proposal.json").read_text(encoding="utf-8")
        )
        saved_canvas = json.loads(
            (run_dir / "generation/canvas.json").read_text(encoding="utf-8")
        )
        if (
            saved_prompt != state["generation_prompt"]
            or saved_proposal != state["proposal"]
            or saved_canvas != state["canvas"]
        ):
            raise ValueError("Reviewed generation artifacts changed after preview.")
        if state["generation_mode"] == "with_corpus":
            saved_selection = json.loads(
                (run_dir / "materials/selection.json").read_text(encoding="utf-8")
            )
            saved_materials = json.loads(
                (run_dir / "materials/package.json").read_text(encoding="utf-8")
            )
            if (
                saved_selection != state["materials_selection"]
                or saved_materials != state["materials_package"]
            ):
                raise ValueError("Reviewed generation artifacts changed after preview.")
            load_snapshot(Path(state["snapshot"]))
        if state.get("reference_plan") is not None:
            saved_plan = json.loads(
                (run_dir / "reference/plan.json").read_text(encoding="utf-8")
            )
            if saved_plan != state["reference_plan"]:
                raise ValueError("Reviewed reference artifacts changed after preview.")
        actual = digest_json(self._generation_binding(
            state, proposal=state["proposal"], prompt=state["generation_prompt"],
        ))
        if actual != state["generation_digest"]:
            raise ValueError("Approved generation content changed.")
        if state["approval"].get("generation_digest") != actual:
            raise ValueError("Approval does not bind to the current generation content.")

        self.store.update(run_dir, "generating")
        attempt = self.store.next_attempt(run_dir, "generation")
        write_json(attempt / "image-spec.json", state["proposal"]["image_spec"])
        response = self.image_provider.generate(
            state["generation_prompt"],
            size=state["generation_size"],
            output=attempt,
            reference_paths=[Path(path) for path in state.get("reference_image_paths", [])],
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
        self.store.register(
            run_dir,
            generation_request=f"{relative}/request.json",
            generation_response=f"{relative}/response.json",
            render=f"{relative}/render.json",
            image=f"{relative}/image.png",
        )
        self.store.update(
            run_dir,
            "reviewing",
            latest_image=str(image_path),
            image_sha256=digest_file(image_path),
        )
        return {"image_path": str(image_path), "status": "reviewing"}

    def review(self, state):
        run_dir = self._dir(state)
        profile = get_profile(state["profile"])
        prompt = compile_review_prompt(profile, state["proposal"])
        self.store.text(run_dir, "review/prompt.md", prompt)
        self.store.json(run_dir, "review/request.json", {
            "schema": profile.review_schema,
            "image": state["image_path"],
            "image_sha256": digest_file(Path(state["image_path"])),
        })
        review, response = self.text_provider.review(
            Path(state["image_path"]), prompt, schema_name=profile.review_schema,
        )
        validate(review, profile.review_schema)
        self.store.json(run_dir, "review/response.json", response)
        self.store.json(run_dir, "review/review.json", review)
        self.store.register(
            run_dir,
            review_request="review/request.json",
            review_prompt="review/prompt.md",
            review_response="review/response.json",
            review="review/review.json",
        )
        return {"review": review, "status": "awaiting_final_decision"}

    def final_decision(self, state):
        run_dir = self._dir(state)
        payload = {
            "run_id": state["run_id"],
            "image": state["image_path"],
            "review": state["review"],
        }
        self.store.update(run_dir, "awaiting_final_decision", final_decision_request=payload)
        decision = interrupt(payload)
        if not isinstance(decision, dict) or decision.get("action") not in {
            "accept", "discard",
        }:
            raise ValueError("Final decision must explicitly accept or discard the image.")
        action = decision["action"]
        record = {**decision, "decided_at": datetime.now(timezone.utc).isoformat()}
        terminal = "completed" if action == "accept" else "discarded"
        self.store.json(run_dir, "review/final-decision.json", record)
        self.store.register(run_dir, final_decision="review/final-decision.json")
        self.store.update(
            run_dir,
            terminal,
            final_decision=record,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        return {"final_action": action, "status": terminal}


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

    def start(self, job: DesignJob) -> RunResult:
        profile = get_profile(job.profile)
        validate(job.brief, profile.brief_schema)
        if job.generation_mode not in {"without_corpus", "with_corpus"}:
            raise ValueError(f"Unsupported generation mode: {job.generation_mode!r}.")
        if job.generation_mode == "without_corpus":
            if job.snapshot is not None or job.materials is not None:
                raise ValueError("Without-corpus runs cannot include a snapshot or materials.")
            if job.brief.get("reference_mode"):
                raise ValueError("Without-corpus runs cannot include a reference mode.")
            snapshot = None
            materials = None
        else:
            if job.snapshot is None or job.materials is None:
                raise ValueError("With-corpus runs require a snapshot and material selection.")
            validate(job.materials, "material-selection.schema.json")
            if not job.materials["knowledge_ids"] and not job.materials["reference_ids"]:
                raise ValueError("With-corpus runs require at least one selected material.")
            snapshot = Path(job.snapshot).resolve(strict=True)
            materials = job.materials
        run_id, run_dir = self.store.create(
            brief=job.brief,
            profile=profile,
            generation_mode=job.generation_mode,
            snapshot=snapshot,
        )
        config = {"configurable": {"thread_id": run_id}}
        self._active[run_id] = config
        state = {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "profile": profile.name,
            "generation_mode": job.generation_mode,
            "brief": job.brief,
            "status": "created",
        }
        if snapshot is not None and materials is not None:
            state.update(
                snapshot=str(snapshot),
                materials_selection=materials,
            )
        try:
            self.graph.invoke(state, config=config)
        except Exception as exc:
            self.store.update(
                run_dir, "failed", error_type=type(exc).__name__, error=str(exc),
            )
            raise
        return self._result(run_id)

    def resume(self, run_id: str, decision: object) -> RunResult:
        if run_id not in self._active:
            raise ValueError("This process has no resumable checkpoint for the run.")
        run_dir = self.store.root / run_id
        try:
            if not hasattr(decision, "to_dict"):
                raise TypeError("A resumable decision must provide to_dict().")
            self.graph.invoke(
                Command(resume=decision.to_dict()), config=self._active[run_id],
            )
        except Exception as exc:
            self.store.update(
                run_dir, "failed", error_type=type(exc).__name__, error=str(exc),
            )
            raise
        result = self._result(run_id)
        if result.status in {"completed", "rejected", "discarded", "failed"}:
            self._active.pop(run_id, None)
        return result

    def inspect(self, run_id: str) -> RunSummary:
        run_dir = (self.store.root / run_id).resolve(strict=True)
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
        summary = self.inspect(run_id)
        registered = summary.manifest.get("artifacts", {})
        paths = {
            "manifest": summary.run_dir / "manifest.json",
            "proposal": summary.run_dir / "design/proposal.json",
            "presentation": summary.run_dir / "design/presentation.md",
            "generation_prompt": summary.run_dir / "generation/prompt.md",
            "image": Path(summary.manifest.get("latest_image", "")),
            "review": summary.run_dir / registered.get("review", "review/review.json"),
        }
        for name in (
            "materials_selection",
            "materials_package",
            "reference_prompt",
            "reference_plan",
            "final_decision",
        ):
            if name in registered:
                paths[name] = summary.run_dir / registered[name]

        # Keep every registered artifact from archived workflow versions inspectable.
        for name, relative in registered.items():
            paths.setdefault(name, summary.run_dir / relative)

        package_path = paths.get("materials_package") or paths.get("reference_package")
        if package_path and package_path.is_file():
            package = json.loads(package_path.read_text(encoding="utf-8"))
            snapshot = Path(summary.manifest["atlas_snapshot"])
            for index, row in enumerate(package.get("references", []), start=1):
                paths[f"reference_image_{index:02d}"] = snapshot / row["file"]

        artifacts = {
            name: str(path.resolve())
            for name, path in paths.items()
            if str(path) and path.is_file()
        }
        messages = {
            "awaiting_approval": "Review the saved proposal and generation prompt.",
            "rejected": "Image generation was rejected; the experiment remains recorded.",
            "awaiting_final_decision": "Review the generated image and accept or discard it.",
            "completed": "The reviewer accepted the generated image.",
            "discarded": "The reviewer discarded the generated image.",
            "failed": "The experiment failed; inspect its manifest and saved attempts.",
        }
        return RunResult(
            run_id=run_id,
            status=summary.status,
            run_dir=summary.run_dir,
            message=messages.get(summary.status, summary.status),
            artifacts=artifacts,
        )
