"""UI-neutral application service for one approval-gated generation experiment."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt

from .artifacts.hashing import digest_file, digest_json
from .artifacts.records import write_json
from .artifacts.store import ArtifactStore, validate_case_id, validate_run_id
from .design.presentation import render
from .design.canvas import resolve_canvas
from .design.rendering import normalize_canvas
from .design.synthesis import synthesize
from .design.validation import validate, validate_image_spec, validate_proposal
from .graphs import build_graph
from .image_prompt import compile_generation_prompt, synthesize_image_spec
from .intake import compile_intake_prompt
from .materials import build_reference_package, load_snapshot
from .providers import OpenAIImageProvider, OpenAITextProvider
from .required_assets import (
    build_composition_plan,
    compose_required_assets,
    ingest_required_images,
    validate_required_asset_integrity,
    validate_required_images,
)
from .registry import get_profile
from .state import DesignJob, NaturalLanguageDesignJob, RunResult, RunSummary


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
        prompt = compile_intake_prompt(
            profile,
            state["user_request"],
            state.get("required_assets", []),
        )
        request = {
            "model": getattr(
                self.text_provider, "model", type(self.text_provider).__name__,
            ),
            "profile": profile.name,
            "schema": profile.brief_schema,
            "required_assets": [
                {
                    "asset_id": item["asset_id"],
                    "original_filename": item["original_filename"],
                    "prepared_sha256": item["prepared_sha256"],
                }
                for item in state.get("required_assets", [])
            ],
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
            return {"brief": brief, "status": "preparing_inputs"}
        except Exception as exc:
            self.store.json(run_dir, "intake/response.json", {
                "status": "failed",
                "error_type": type(exc).__name__,
                "message": str(exc),
            })
            self.store.register(run_dir, intake_response="intake/response.json")
            raise

    def prepare_inputs(self, state):
        run_dir = self._dir(state)
        self.store.update(run_dir, "preparing_inputs")
        if state["generation_mode"] == "without_corpus":
            return {
                "reference_package": None,
                "reference_image_paths": [],
                "status": "designing",
            }

        self.store.update(run_dir, "loading_reference")
        package, path = build_reference_package(
            Path(state["snapshot"]), state["reference_selection"],
        )
        self.store.json(run_dir, "reference/selection.json", state["reference_selection"])
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
    def _generation_binding(
        state, *, proposal, image_spec, prompt, request, composition_plan=None,
    ):
        binding = {
            "generation_mode": state["generation_mode"],
            "prompt": prompt,
            "request": request,
            "proposal": proposal,
            "image_spec": image_spec,
            "generation_size": state["generation_size"],
            "output_ratio": list(state["output_ratio"]),
            "canvas": state["canvas"],
            "required_assets": state.get("required_assets", []),
            "composition_plan": (
                state.get("composition_plan", {})
                if composition_plan is None else composition_plan
            ),
        }
        if state["generation_mode"] == "with_corpus":
            binding.update(
                reference=state["reference_package"],
            )
        return binding

    def design(self, state):
        run_dir = self._dir(state)
        profile = get_profile(state["profile"])
        self.store.update(run_dir, "designing")
        prompt = ""
        try:
            if profile.deliverable == "graphic-design.v1":
                generation_size, output_ratio, canvas = resolve_canvas(state["brief"])
            else:
                generation_size = profile.default_size
                output_ratio = profile.output_ratio
                canvas = {
                    "size": generation_size,
                    "ratio": list(output_ratio),
                    "mode": "profile_default",
                }
            self.store.json(run_dir, "generation/canvas.json", canvas)
            required_paths = [
                Path(path) for path in state.get("required_asset_paths", [])
            ]
            corpus_paths = [
                Path(path) for path in state.get("reference_image_paths", [])
            ]
            visual_inputs = [
                {
                    "input_index": index,
                    "role": "required_exact_image",
                    "asset_id": record["asset_id"],
                    "prepared_size": record["prepared_size"],
                    "instruction": (
                        "This image must appear unchanged in the final composition. "
                        "Reserve a suitable region; deterministic post-processing will place it."
                    ),
                }
                for index, record in enumerate(
                    state.get("required_assets", []), start=1,
                )
            ]
            if corpus_paths:
                visual_inputs.append({
                    "input_index": len(visual_inputs) + 1,
                    "role": "corpus_reference",
                    "instruction": (
                        "Use only as optional visual knowledge; it is not required content."
                    ),
                })
            prompt, proposal, response = synthesize(
                profile,
                state["brief"],
                self.text_provider,
                required_paths + corpus_paths,
                canvas=canvas,
                visual_inputs=visual_inputs,
            )
            request = {
                "model": getattr(self.text_provider, "model", type(self.text_provider).__name__),
                "profile": profile.name,
                "schema": profile.proposal_schema,
                "references": state.get("reference_package"),
                "visual_inputs": visual_inputs,
            }
            self.store.json(run_dir, "design/request.json", request)
            self.store.text(run_dir, "design/prompt.md", prompt)
            self.store.json(run_dir, "design/response.json", response)
            self.store.json(run_dir, "design/proposal.json", proposal)
            proposal = validate_proposal(proposal, profile.proposal_schema)
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
            self.store.register(
                run_dir,
                canvas="generation/canvas.json",
            )
            return {
                "design_prompt": prompt,
                "proposal": proposal,
                "generation_size": generation_size,
                "output_ratio": output_ratio,
                "canvas": canvas,
                "status": "compiling_image_spec",
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

    def compile_image_spec(self, state):
        run_dir = self._dir(state)
        target_model = getattr(
            self.image_provider, "model", type(self.image_provider).__name__,
        )
        self.store.update(run_dir, "compiling_image_spec")
        prompt = ""
        try:
            prompt, image_spec, response = synthesize_image_spec(
                state["proposal"],
                brief=state["brief"],
                canvas=state["canvas"],
                provider_profile=target_model,
                provider=self.text_provider,
                required_assets=state.get("required_assets", []),
            )
            image_spec = validate_image_spec(
                image_spec, state["brief"].get("exact_copy", []),
                [item["asset_id"] for item in state.get("required_assets", [])],
            )
            composition_plan = build_composition_plan(
                image_spec, state.get("required_assets", []),
            )
            request = {
                "model": getattr(
                    self.text_provider, "model", type(self.text_provider).__name__,
                ),
                "target_image_model": target_model,
                "schema": "image-spec.schema.json",
            }
            self.store.json(run_dir, "image-spec/request.json", request)
            self.store.text(run_dir, "image-spec/prompt.md", prompt)
            self.store.json(run_dir, "image-spec/response.json", response)
            self.store.json(run_dir, "image-spec/image-spec.json", image_spec)
            generation_prompt = compile_generation_prompt(image_spec)
            self.store.text(run_dir, "generation/prompt.md", generation_prompt)
            self.store.json(
                run_dir, "generation/composition-preview.json", composition_plan,
            )
            generation_request = self.image_provider.describe_request(
                generation_prompt,
                size=state["generation_size"],
                reference_paths=[
                    Path(path) for path in state.get("reference_image_paths", [])
                ],
            )
            self.store.json(
                run_dir, "generation/request-preview.json", generation_request,
            )
            self.store.register(
                run_dir,
                image_prompt_request="image-spec/request.json",
                image_prompt="image-spec/prompt.md",
                image_prompt_response="image-spec/response.json",
                image_spec="image-spec/image-spec.json",
                generation_prompt="generation/prompt.md",
                generation_request_preview="generation/request-preview.json",
                composition_preview="generation/composition-preview.json",
            )
            digest = digest_json(self._generation_binding(
                state,
                proposal=state["proposal"],
                image_spec=image_spec,
                prompt=generation_prompt,
                request=generation_request,
                composition_plan=composition_plan,
            ))
            return {
                "image_prompt": prompt,
                "image_spec": image_spec,
                "generation_prompt": generation_prompt,
                "generation_request": generation_request,
                "composition_plan": composition_plan,
                "generation_digest": digest,
                "status": "awaiting_approval",
            }
        except Exception as exc:
            if prompt:
                self.store.text(run_dir, "image-spec/prompt.md", prompt)
            error_path = (
                "image-spec/error.json"
                if (run_dir / "image-spec/response.json").exists()
                else "image-spec/response.json"
            )
            self.store.json(run_dir, error_path, {
                "status": "failed",
                "error_type": type(exc).__name__,
                "message": str(exc),
            })
            self.store.register(run_dir, image_prompt_error=error_path)
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
                "image_spec": str((run_dir / "image-spec/image-spec.json").resolve()),
                "generation_prompt": str((run_dir / "generation/prompt.md").resolve()),
                "generation_request_preview": str(
                    (run_dir / "generation/request-preview.json").resolve()
                ),
                "canvas": str((run_dir / "generation/canvas.json").resolve()),
                "composition_preview": str(
                    (run_dir / "generation/composition-preview.json").resolve()
                ),
            },
        }
        for record in state.get("required_assets", []):
            key = record["asset_id"].replace("-", "_")
            root = run_dir / "input" / "required-assets" / record["asset_id"]
            payload["artifacts"].update({
                f"{key}_preview": str((root / record["preview_file"]).resolve()),
                f"{key}_metadata": str((root / "asset.json").resolve()),
            })
        if state["generation_mode"] == "with_corpus":
            payload["artifacts"].update({
                "reference_selection": str((run_dir / "reference/selection.json").resolve()),
                "reference_package": str((run_dir / "reference/package.json").resolve()),
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
        saved_image_spec = json.loads(
            (run_dir / "image-spec/image-spec.json").read_text(encoding="utf-8")
        )
        saved_canvas = json.loads(
            (run_dir / "generation/canvas.json").read_text(encoding="utf-8")
        )
        saved_request = json.loads(
            (run_dir / "generation/request-preview.json").read_text(encoding="utf-8")
        )
        saved_composition = json.loads(
            (run_dir / "generation/composition-preview.json").read_text(
                encoding="utf-8"
            )
        )
        validate_required_asset_integrity(
            state.get("required_assets", []),
            state.get("required_asset_paths", []),
        )
        current_request = self.image_provider.describe_request(
            state["generation_prompt"],
            size=state["generation_size"],
            reference_paths=[
                Path(path) for path in state.get("reference_image_paths", [])
            ],
        )
        if (
            saved_prompt != state["generation_prompt"]
            or saved_proposal != state["proposal"]
            or saved_image_spec != state["image_spec"]
            or saved_canvas != state["canvas"]
            or saved_request != state["generation_request"]
            or current_request != state["generation_request"]
            or saved_composition != state.get("composition_plan", {})
        ):
            raise ValueError("Approved generation artifacts changed after preview.")
        if state["generation_mode"] == "with_corpus":
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
            load_snapshot(Path(state["snapshot"]))
        actual = digest_json(self._generation_binding(
            state,
            proposal=state["proposal"],
            image_spec=state["image_spec"],
            prompt=state["generation_prompt"],
            request=state["generation_request"],
        ))
        if actual != state["generation_digest"]:
            raise ValueError("Approved generation content changed.")
        if state["approval"].get("generation_digest") != actual:
            raise ValueError("Approval does not bind to the current generation content.")

        self.store.update(run_dir, "generating")
        attempt = self.store.next_attempt(run_dir, "generation")
        write_json(attempt / "image-spec.json", state["image_spec"])
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
        composition_record = None
        if state.get("required_assets"):
            image_path, composition_record = compose_required_assets(
                image_path,
                state["required_assets"],
                state["required_asset_paths"],
                state["composition_plan"]["placements"],
            )
            if render_record.get("source_file") == "image.png":
                render_record["source_file"] = "background.png"
            if render_record.get("output_file") == "image.png":
                render_record["output_file"] = "background.png"
            write_json(attempt / "render.json", render_record)
        response.update(
            file=image_path.name,
            sha256=digest_file(image_path),
            render=render_record,
        )
        if composition_record is not None:
            response["composition"] = composition_record
        write_json(attempt / "response.json", response)
        relative = attempt.relative_to(run_dir).as_posix()
        self.store.register(
            run_dir,
            generation_request=f"{relative}/request.json",
            generation_response=f"{relative}/response.json",
            render=f"{relative}/render.json",
            image=f"{relative}/image.png",
        )
        if composition_record is not None:
            self.store.register(
                run_dir,
                generation_background=f"{relative}/background.png",
                composition=f"{relative}/composition.json",
            )
        self.store.update(
            run_dir,
            "completed",
            latest_image=str(image_path),
            image_sha256=digest_file(image_path),
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        return {"image_path": str(image_path), "status": "completed"}


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

    @staticmethod
    def _corpus_inputs(generation_mode, snapshot, reference):
        if generation_mode not in {"without_corpus", "with_corpus"}:
            raise ValueError(f"Unsupported generation mode: {generation_mode!r}.")
        if generation_mode == "without_corpus":
            if snapshot is not None or reference is not None:
                raise ValueError("Without-corpus runs cannot include a snapshot or reference.")
            return None, None
        if snapshot is None or reference is None:
            raise ValueError("With-corpus runs require a snapshot and reference selection.")
        validate(reference, "reference-selection.schema.json")
        return Path(snapshot).resolve(strict=True), reference

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

    def _ingest_required_images(self, run_dir: Path, uploads) -> tuple[list[dict], list[str]]:
        try:
            records, paths, artifacts = ingest_required_images(run_dir, uploads)
            if artifacts:
                self.store.register(run_dir, **artifacts)
                self.store.update(run_dir, "created", required_assets=records)
            return records, paths
        except Exception as exc:
            self.store.update(
                run_dir, "failed", error_type=type(exc).__name__, error=str(exc),
            )
            raise

    def start(self, job: DesignJob) -> RunResult:
        profile = get_profile(job.profile)
        validate(job.brief, profile.brief_schema)
        snapshot, reference = self._corpus_inputs(
            job.generation_mode, job.snapshot, job.reference,
        )
        uploads = validate_required_images(job.required_images)
        run_id, run_dir = self.store.create(
            case_id=job.case_id,
            brief=job.brief,
            profile=profile,
            generation_mode=job.generation_mode,
            snapshot=snapshot,
        )
        required_assets, required_paths = self._ingest_required_images(
            run_dir, uploads,
        )
        state = {
            "case_id": job.case_id,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "profile": profile.name,
            "generation_mode": job.generation_mode,
            "brief": job.brief,
            "required_assets": required_assets,
            "required_asset_paths": required_paths,
            "status": "created",
        }
        if snapshot is not None and reference is not None:
            state.update(
                snapshot=str(snapshot),
                reference_selection=reference,
            )
        return self._invoke_start(run_id, run_dir, state)

    def start_request(self, job: NaturalLanguageDesignJob) -> RunResult:
        if not isinstance(job.request, str) or not job.request.strip():
            raise ValueError("Natural-language design request must not be empty.")
        profile = get_profile(job.profile)
        snapshot, reference = self._corpus_inputs(
            job.generation_mode, job.snapshot, job.reference,
        )
        uploads = validate_required_images(job.required_images)
        run_id, run_dir = self.store.create(
            case_id=job.case_id,
            request=job.request,
            profile=profile,
            generation_mode=job.generation_mode,
            snapshot=snapshot,
        )
        required_assets, required_paths = self._ingest_required_images(
            run_dir, uploads,
        )
        state = {
            "case_id": job.case_id,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "profile": profile.name,
            "user_request": job.request,
            "required_assets": required_assets,
            "required_asset_paths": required_paths,
            "generation_mode": job.generation_mode,
            "status": "created",
        }
        if snapshot is not None and reference is not None:
            state.update(
                snapshot=str(snapshot),
                reference_selection=reference,
            )
        return self._invoke_start(run_id, run_dir, state)

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
            raise
        result = self._result(run_id)
        if result.status in {"completed", "rejected", "failed"}:
            self._active.pop(run_id, None)
        return result

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
        for name in (
            "reference_selection",
            "reference_package",
            "reference_prompt",
            "reference_plan",
        ):
            if name in registered:
                paths[name] = summary.run_dir / registered[name]

        # Keep every registered artifact from archived workflow versions inspectable.
        for name, relative in registered.items():
            paths.setdefault(name, summary.run_dir / relative)

        package_path = paths.get("reference_package") or paths.get("materials_package")
        if package_path and package_path.is_file():
            package = json.loads(package_path.read_text(encoding="utf-8"))
            snapshot = Path(summary.manifest["atlas_snapshot"])
            if "reference" in package:
                paths["reference_image"] = snapshot / package["reference"]["file"]
            else:
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
