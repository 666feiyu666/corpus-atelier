"""UI-neutral application service and workflow runtime."""

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
from .design.prompt_compiler import compile_generation_prompt, compile_review_prompt
from .design.rendering import normalize_canvas
from .design.synthesis import synthesize
from .design.validation import validate, validate_proposal
from .graphs import build_graph
from .providers import OpenAIImageProvider, OpenAITextProvider
from .rag import retrieve
from .rag.atlas_snapshot import load_snapshot
from .registry import get_profile
from .state import DesignJob, HumanDecision, RunResult, RunSummary


class _Runtime:
    def __init__(self, store, text_provider, image_provider):
        self.store = store
        self.text_provider = text_provider
        self.image_provider = image_provider

    @staticmethod
    def _dir(state):
        return Path(state["run_dir"])

    def retrieve(self, state):
        run_dir = self._dir(state)
        self.store.update(run_dir, "retrieving")
        query, candidates, bundle = retrieve(
            state["brief"], state["profile"], Path(state["snapshot"]),
            evidence_mode=state["evidence_mode"],
        )
        self.store.json(run_dir, "retrieval/query.json", query)
        self.store.json(run_dir, "retrieval/candidates.json", candidates)
        self.store.json(run_dir, "retrieval/bundle.json", bundle)
        self.store.register(
            run_dir, retrieval_query="retrieval/query.json",
            retrieval_candidates="retrieval/candidates.json",
            retrieval_bundle="retrieval/bundle.json",
        )
        return {"retrieval_query": query, "retrieval_candidates": candidates,
                "retrieval_bundle": bundle, "status": "designing"}

    def design(self, state, *, expected_profile):
        if state["profile"] != expected_profile:
            raise ValueError("Profile reached the wrong design subgraph.")
        run_dir = self._dir(state)
        profile = get_profile(state["profile"])
        self.store.update(run_dir, "designing")
        prompt = ""
        try:
            prompt, proposal, response = synthesize(
                profile, state["brief"], state["retrieval_bundle"], self.text_provider,
            )
            request = {"model": getattr(self.text_provider, "model", type(self.text_provider).__name__),
                       "profile": profile.name, "schema": profile.proposal_schema}
            self.store.json(run_dir, "design/request.json", request)
            self.store.text(run_dir, "design/prompt.md", prompt)
            self.store.json(run_dir, "design/response.json", response)
            self.store.json(run_dir, "design/proposal.json", proposal)
            proposal = validate_proposal(proposal, profile.proposal_schema)
            self.store.text(run_dir, "design/presentation.md", render(proposal))
            self.store.register(
                run_dir, design_request="design/request.json", design_prompt="design/prompt.md",
                design_response="design/response.json", proposal="design/proposal.json",
                presentation="design/presentation.md",
            )
            if proposal["status"] != "ready":
                self.store.update(run_dir, proposal["status"])
                raise ValueError(f"Design proposal is blocked: {proposal['status']}.")
            generation_prompt = compile_generation_prompt(proposal)
            self.store.text(run_dir, "generation/prompt.md", generation_prompt)
            self.store.register(run_dir, generation_prompt="generation/prompt.md")
            digest = digest_json({"prompt": generation_prompt, "proposal": proposal})
            return {"design_prompt": prompt, "proposal": proposal,
                    "generation_prompt": generation_prompt, "generation_digest": digest}
        except Exception as exc:
            if prompt:
                self.store.text(run_dir, "design/prompt.md", prompt)
            error_path = "design/error.json" if (run_dir / "design/response.json").exists() else "design/response.json"
            self.store.json(run_dir, error_path, {
                "status": "failed", "error_type": type(exc).__name__, "message": str(exc),
            })
            self.store.register(run_dir, design_error=error_path)
            raise

    def approval(self, state):
        run_dir = self._dir(state)
        profile = get_profile(state["profile"])
        payload = {
            "run_id": state["run_id"], "profile": profile.name,
            "generation_digest": state["generation_digest"],
            "artifacts": {
                "retrieval_bundle": str((run_dir / "retrieval/bundle.json").resolve()),
                "proposal": str((run_dir / "design/proposal.json").resolve()),
                "presentation": str((run_dir / "design/presentation.md").resolve()),
                "generation_prompt": str((run_dir / "generation/prompt.md").resolve()),
            },
        }
        self.store.update(run_dir, "awaiting_approval", approval_request=payload)
        decision = interrupt(payload)
        if not isinstance(decision, dict) or not isinstance(decision.get("approved"), bool):
            raise ValueError("Human approval must be an explicit boolean decision.")
        record = {
            **decision, "decided_at": datetime.now(timezone.utc).isoformat(),
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
        saved_proposal = json.loads((run_dir / "design/proposal.json").read_text(encoding="utf-8"))
        if saved_prompt != state["generation_prompt"] or saved_proposal != state["proposal"]:
            raise ValueError("Reviewed generation artifacts changed after preview.")
        load_snapshot(Path(state["snapshot"]))
        actual = digest_json({"prompt": state["generation_prompt"], "proposal": state["proposal"]})
        if actual != state["generation_digest"]:
            raise ValueError("Approved generation content changed.")
        if state["approval"].get("generation_digest") != actual:
            raise ValueError("Approval does not bind to the current generation content.")
        self.store.update(run_dir, "generating")
        attempt = self.store.next_attempt(run_dir, "generation")
        write_json(attempt / "image-spec.json", state["proposal"]["image_spec"])
        response = self.image_provider.generate(
            state["generation_prompt"], size=get_profile(state["profile"]).default_size,
            output=attempt,
        )
        image_path = (attempt / response["file"]).resolve()
        image_path, render_record = normalize_canvas(
            image_path, get_profile(state["profile"]).output_ratio,
        )
        response.update(
            file=image_path.name, sha256=digest_file(image_path), render=render_record,
        )
        write_json(attempt / "response.json", response)
        relative = attempt.relative_to(run_dir).as_posix()
        self.store.register(
            run_dir, generation_request=f"{relative}/request.json",
            generation_response=f"{relative}/response.json",
            render=f"{relative}/render.json", image=f"{relative}/image.png",
        )
        self.store.update(run_dir, "reviewing", latest_image=str(image_path),
                          image_sha256=digest_file(image_path))
        return {"image_path": str(image_path), "status": "reviewing"}

    def review(self, state):
        run_dir = self._dir(state)
        profile = get_profile(state["profile"])
        prompt = compile_review_prompt(profile, state["proposal"])
        self.store.text(run_dir, "review/prompt.md", prompt)
        self.store.json(run_dir, "review/request.json", {
            "schema": profile.review_schema, "image": state["image_path"],
            "image_sha256": digest_file(Path(state["image_path"])),
        })
        review, response = self.text_provider.review(
            Path(state["image_path"]), prompt, schema_name=profile.review_schema,
        )
        validate(review, profile.review_schema)
        self.store.json(run_dir, "review/response.json", response)
        self.store.json(run_dir, "review/review.json", review)
        self.store.register(
            run_dir, review_request="review/request.json", review_prompt="review/prompt.md",
            review_response="review/response.json", review="review/review.json",
        )
        self.store.update(run_dir, "completed", completed_at=datetime.now(timezone.utc).isoformat())
        return {"review": review, "status": "completed"}


class CorpusAtelierApplication:
    def __init__(self, *, runs_root: Path | str = "experiments/runs",
                 text_provider=None, image_provider=None):
        self.store = ArtifactStore(runs_root)
        self.runtime = _Runtime(
            self.store, text_provider or OpenAITextProvider(),
            image_provider or OpenAIImageProvider(),
        )
        self.checkpointer = InMemorySaver()
        self.graph = build_graph(self.runtime, self.checkpointer)
        self._active: dict[str, dict] = {}

    def start(self, job: DesignJob) -> RunResult:
        profile = get_profile(job.profile)
        validate(job.brief, profile.brief_schema)
        snapshot = Path(job.snapshot).resolve(strict=True)
        run_id, run_dir = self.store.create(
            brief=job.brief, profile=profile, evidence_mode=job.evidence_mode,
            snapshot=snapshot,
        )
        config = {"configurable": {"thread_id": run_id}}
        self._active[run_id] = config
        state = {
            "run_id": run_id, "run_dir": str(run_dir), "profile": profile.name,
            "brief": job.brief, "snapshot": str(snapshot),
            "evidence_mode": job.evidence_mode, "status": "created",
        }
        try:
            self.graph.invoke(state, config=config)
        except Exception as exc:
            self.store.update(run_dir, "failed", error_type=type(exc).__name__, error=str(exc))
            raise
        return self._result(run_id)

    def resume(self, run_id: str, decision: HumanDecision) -> RunResult:
        if run_id not in self._active:
            raise ValueError("This process has no resumable checkpoint for the run.")
        run_dir = self.store.root / run_id
        try:
            self.graph.invoke(Command(resume=decision.to_dict()), config=self._active[run_id])
        except Exception as exc:
            self.store.update(run_dir, "failed", error_type=type(exc).__name__, error=str(exc))
            raise
        result = self._result(run_id)
        if result.status in {"completed", "rejected", "failed"}:
            self._active.pop(run_id, None)
        return result

    def inspect(self, run_id: str) -> RunSummary:
        run_dir = (self.store.root / run_id).resolve(strict=True)
        if self.store.root not in run_dir.parents:
            raise ValueError("Run id escapes the run store.")
        manifest = self.store.manifest(run_dir)
        return RunSummary(run_id=run_id, status=manifest["status"],
                          run_dir=run_dir, manifest=manifest)

    def _result(self, run_id: str) -> RunResult:
        summary = self.inspect(run_id)
        paths = {
            "manifest": summary.run_dir / "manifest.json",
            "retrieval_bundle": summary.run_dir / "retrieval/bundle.json",
            "proposal": summary.run_dir / "design/proposal.json",
            "presentation": summary.run_dir / "design/presentation.md",
            "generation_prompt": summary.run_dir / "generation/prompt.md",
            "image": Path(summary.manifest.get("latest_image", "")),
            "review": summary.run_dir / "review/review.json",
        }
        artifacts = {name: str(path.resolve()) for name, path in paths.items()
                     if str(path) and path.is_file()}
        messages = {
            "awaiting_approval": "Review the saved proposal and generation prompt.",
            "rejected": "Image generation was rejected; the experiment remains recorded.",
            "completed": "Image generation and profile-specific review completed.",
            "failed": "The experiment failed; inspect its manifest and saved attempts.",
        }
        return RunResult(run_id=run_id, status=summary.status, run_dir=summary.run_dir,
                         message=messages.get(summary.status, summary.status), artifacts=artifacts)
