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
from .providers import OpenAIImageProvider, OpenAITextProvider
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
    def _generation_binding(state, *, proposal, image_spec, prompt, request):
        return {
            "prompt": prompt,
            "request": request,
            "proposal": proposal,
            "image_spec": image_spec,
            "generation_size": state["generation_size"],
            "output_ratio": list(state["output_ratio"]),
            "canvas": state["canvas"],
        }

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
            prompt, proposal, response = synthesize(
                profile,
                state["brief"],
                self.text_provider,
                canvas=canvas,
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
            }
            self.store.json(run_dir, "image-spec/request.json", request)
            self.store.text(run_dir, "image-spec/prompt.md", prompt)
            self.store.json(run_dir, "image-spec/response.json", response)
            self.store.json(run_dir, "image-spec/image-spec.json", image_spec)
            generation_prompt = compile_generation_prompt(image_spec)
            self.store.text(run_dir, "generation/prompt.md", generation_prompt)
            generation_request = self.image_provider.describe_request(
                generation_prompt,
                size=state["generation_size"],
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
            )
            digest = digest_json(self._generation_binding(
                state,
                proposal=state["proposal"],
                image_spec=image_spec,
                prompt=generation_prompt,
                request=generation_request,
            ))
            return {
                "image_prompt": prompt,
                "image_spec": image_spec,
                "generation_prompt": generation_prompt,
                "generation_request": generation_request,
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
            },
        }
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
        current_request = self.image_provider.describe_request(
            state["generation_prompt"],
            size=state["generation_size"],
        )
        if (
            saved_prompt != state["generation_prompt"]
            or saved_proposal != state["proposal"]
            or saved_image_spec != state["image_spec"]
            or saved_canvas != state["canvas"]
            or saved_request != state["generation_request"]
            or current_request != state["generation_request"]
        ):
            raise ValueError("Approved generation artifacts changed after preview.")
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

    def start(self, job: DesignJob) -> RunResult:
        profile = get_profile(job.profile)
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
            "status": "created",
        }
        return self._invoke_start(run_id, run_dir, state)

    def start_request(self, job: NaturalLanguageDesignJob) -> RunResult:
        if not isinstance(job.request, str) or not job.request.strip():
            raise ValueError("Natural-language design request must not be empty.")
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
            "status": "created",
        }
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
        # Keep every registered artifact from archived workflow versions inspectable.
        for name, relative in registered.items():
            paths.setdefault(name, summary.run_dir / relative)

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
