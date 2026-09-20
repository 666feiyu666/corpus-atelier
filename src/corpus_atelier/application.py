"""UI-neutral application service and workflow runtime."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt

from .artifacts.hashing import digest_file, digest_json
from .artifacts.records import write_json
from .artifacts.store import ArtifactStore
from .design.presentation import render
from .design.prompt_compiler import (
    compile_generation_prompt, compile_review_prompt, compile_revision_plan_prompt,
    compile_reference_plan_prompt, compile_revision_prompt, compile_revision_review_prompt,
)
from .design.rendering import normalize_canvas
from .design.synthesis import synthesize
from .design.validation import (
    validate, validate_proposal, validate_reference_plan, validate_revision_review,
)
from .graphs import build_graph
from .providers import OpenAIImageProvider, OpenAITextProvider
from .rag import build_reference_package, retrieve
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

    def prepare_references(self, state):
        run_dir = self._dir(state)
        self.store.update(run_dir, "preparing_references")
        package, paths = build_reference_package(
            Path(state["snapshot"]), scope=state["brief"]["reference_scope"],
        )
        self.store.json(run_dir, "reference/package.json", package)
        self.store.register(run_dir, reference_package="reference/package.json")
        return {
            "reference_package": package,
            "reference_image_paths": [str(path) for path in paths],
            "status": "planning_references",
        }

    def plan_references(self, state, *, expected_mode):
        mode = state["brief"].get("reference_mode")
        if mode != expected_mode:
            raise ValueError("Reference mode reached the wrong planning branch.")
        run_dir = self._dir(state)
        self.store.update(run_dir, "planning_references")
        schema = {
            "style_grounded": "style-grounded-plan.schema.json",
            "style_inspired": "style-inspired-plan.schema.json",
        }[mode]
        prompt = compile_reference_plan_prompt(
            mode=mode, brief=state["brief"], bundle=state["retrieval_bundle"],
            package=state["reference_package"],
        )
        request = {
            "model": getattr(self.text_provider, "model", type(self.text_provider).__name__),
            "schema": schema,
            "reference_mode": mode,
            "references": [{"id": row["id"], "sha256": row["sha256"]}
                           for row in state["reference_package"]["references"]],
        }
        self.store.json(run_dir, "reference/request.json", request)
        self.store.text(run_dir, "reference/prompt.md", prompt)
        plan, response = self.text_provider.plan_references(
            prompt, [Path(path) for path in state["reference_image_paths"]],
            schema_name=schema,
        )
        self.store.json(run_dir, "reference/response.json", response)
        self.store.json(run_dir, "reference/plan.json", plan)
        available = {
            row["id"]
            for kind in ("references", "knowledge")
            for row in state["reference_package"][kind]
        }
        validate_reference_plan(
            plan, schema_name=schema, mode=mode, available_ids=available,
        )
        self.store.register(
            run_dir, reference_request="reference/request.json",
            reference_prompt="reference/prompt.md",
            reference_response="reference/response.json", reference_plan="reference/plan.json",
        )
        return {"reference_plan_prompt": prompt, "reference_plan": plan,
                "status": "designing"}

    @staticmethod
    def _generation_binding(state, *, proposal, prompt):
        binding = {"prompt": prompt, "proposal": proposal}
        if state.get("reference_plan") is not None:
            binding.update(
                reference_mode=state["brief"]["reference_mode"],
                reference_package=state["reference_package"],
                reference_plan=state["reference_plan"],
            )
        return binding

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
                state.get("reference_plan"),
            )
            request = {"model": getattr(self.text_provider, "model", type(self.text_provider).__name__),
                       "profile": profile.name, "schema": profile.proposal_schema}
            self.store.json(run_dir, "design/request.json", request)
            self.store.text(run_dir, "design/prompt.md", prompt)
            self.store.json(run_dir, "design/response.json", response)
            self.store.json(run_dir, "design/proposal.json", proposal)
            proposal = validate_proposal(proposal, profile.proposal_schema)
            if state.get("reference_plan") is not None:
                available_ids = {
                    row["id"] for row in state["reference_package"]["references"]
                } | {
                    row["id"] for row in state["reference_package"]["knowledge"]
                }
                unknown = sorted(set(proposal["evidence_ids"]) - available_ids)
                if unknown:
                    raise ValueError(f"Design proposal cites unavailable evidence IDs: {unknown}.")
            self.store.text(run_dir, "design/presentation.md", render(proposal))
            self.store.register(
                run_dir, design_request="design/request.json", design_prompt="design/prompt.md",
                design_response="design/response.json", proposal="design/proposal.json",
                presentation="design/presentation.md",
            )
            if proposal["status"] != "ready":
                self.store.update(run_dir, proposal["status"])
                raise ValueError(f"Design proposal is blocked: {proposal['status']}.")
            generation_prompt = compile_generation_prompt(
                proposal, state.get("reference_plan"),
            )
            self.store.text(run_dir, "generation/prompt.md", generation_prompt)
            self.store.register(run_dir, generation_prompt="generation/prompt.md")
            digest = digest_json(self._generation_binding(
                state, proposal=proposal, prompt=generation_prompt,
            ))
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
        if state.get("reference_plan") is not None:
            payload["reference_mode"] = state["brief"]["reference_mode"]
            payload["artifacts"].update({
                "reference_package": str((run_dir / "reference/package.json").resolve()),
                "reference_plan": str((run_dir / "reference/plan.json").resolve()),
                "reference_prompt": str((run_dir / "reference/prompt.md").resolve()),
            })
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
        if state.get("reference_plan") is not None:
            saved_package = json.loads(
                (run_dir / "reference/package.json").read_text(encoding="utf-8"))
            saved_plan = json.loads((run_dir / "reference/plan.json").read_text(encoding="utf-8"))
            if saved_package != state["reference_package"] or saved_plan != state["reference_plan"]:
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
        self.store.update(run_dir, "reviewed")
        return {"review": review, "status": "reviewed"}

    def revision_gate(self, state):
        run_dir = self._dir(state)
        revision_count = state.get("iteration", 1) - 1
        payload = {
            "run_id": state["run_id"], "image": state["image_path"],
            "review": state["review"], "revision_count": revision_count,
        }
        self.store.update(run_dir, "awaiting_revision", revision_request=payload)
        decision = interrupt(payload)
        if not isinstance(decision, dict) or decision.get("action") not in {
            "accept", "revise", "discard",
        }:
            raise ValueError("Revision decision must explicitly accept, revise, or discard.")
        action = decision["action"]
        if action == "revise":
            instruction = decision.get("instruction", "").strip()
            if not instruction:
                raise ValueError("A revision decision requires a non-empty instruction.")
            attempt = self.store.next_attempt(run_dir, "revision")
            record = {
                **decision, "instruction": instruction,
                "decided_at": datetime.now(timezone.utc).isoformat(),
                "base_image": state["image_path"],
                "base_image_sha256": digest_file(Path(state["image_path"])),
            }
            write_json(attempt / "request.json", record)
            relative = attempt.relative_to(run_dir).as_posix()
            self.store.register(run_dir, revision_request=f"{relative}/request.json")
            return {
                "revision_action": action, "revision_request": record,
                "revision_dir": str(attempt), "base_image_path": state["image_path"],
                "status": "planning_revision",
            }
        record = {**decision, "decided_at": datetime.now(timezone.utc).isoformat()}
        terminal = "completed" if action == "accept" else "discarded"
        self.store.update(
            run_dir, terminal, final_decision=record,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        return {"revision_action": action, "status": terminal}

    def plan_revision(self, state):
        run_dir = self._dir(state)
        attempt = Path(state["revision_dir"])
        self.store.update(run_dir, "planning_revision")
        prompt = compile_revision_plan_prompt(
            brief=state["brief"], proposal=state["proposal"], review=state["review"],
            instruction=state["revision_request"]["instruction"],
        )
        plan, response = self.text_provider.propose(
            prompt, schema_name="revision-plan.schema.json",
        )
        validate(plan, "revision-plan.schema.json")
        revision_prompt = compile_revision_prompt(state["proposal"], plan)
        (attempt / "plan-prompt.md").write_text(prompt, encoding="utf-8")
        write_json(attempt / "plan-response.json", response)
        write_json(attempt / "plan.json", plan)
        (attempt / "prompt.md").write_text(revision_prompt, encoding="utf-8")
        digest = digest_json({
            "base_image_sha256": digest_file(Path(state["base_image_path"])),
            "request": state["revision_request"], "plan": plan,
            "prompt": revision_prompt,
        })
        relative = attempt.relative_to(run_dir).as_posix()
        self.store.register(
            run_dir, revision_plan=f"{relative}/plan.json",
            revision_prompt=f"{relative}/prompt.md",
        )
        return {
            "revision_plan": plan, "revision_prompt": revision_prompt,
            "revision_digest": digest, "status": "awaiting_revision_approval",
        }

    def revision_approval(self, state):
        run_dir = self._dir(state)
        attempt = Path(state["revision_dir"])
        payload = {
            "run_id": state["run_id"], "revision_digest": state["revision_digest"],
            "base_image": state["base_image_path"],
            "artifacts": {
                "request": str((attempt / "request.json").resolve()),
                "plan": str((attempt / "plan.json").resolve()),
                "prompt": str((attempt / "prompt.md").resolve()),
            },
        }
        self.store.update(run_dir, "awaiting_revision_approval",
                          revision_approval_request=payload)
        decision = interrupt(payload)
        if not isinstance(decision, dict) or not isinstance(decision.get("approved"), bool):
            raise ValueError("Revision approval must be an explicit boolean decision.")
        record = {
            **decision, "decided_at": datetime.now(timezone.utc).isoformat(),
            "revision_digest": state["revision_digest"],
        }
        write_json(attempt / "approval.json", record)
        relative = attempt.relative_to(run_dir).as_posix()
        self.store.register(run_dir, revision_approval=f"{relative}/approval.json")
        status = "revising" if record["approved"] else "awaiting_revision"
        return {"revision_approval": record, "status": status}

    def edit_image(self, state):
        run_dir = self._dir(state)
        attempt = Path(state["revision_dir"])
        saved_prompt = (attempt / "prompt.md").read_text(encoding="utf-8")
        saved_plan = json.loads((attempt / "plan.json").read_text(encoding="utf-8"))
        if saved_prompt != state["revision_prompt"] or saved_plan != state["revision_plan"]:
            raise ValueError("Reviewed revision artifacts changed after preview.")
        actual = digest_json({
            "base_image_sha256": digest_file(Path(state["base_image_path"])),
            "request": state["revision_request"], "plan": state["revision_plan"],
            "prompt": state["revision_prompt"],
        })
        if actual != state["revision_digest"]:
            raise ValueError("Approved revision content changed.")
        if state["revision_approval"].get("revision_digest") != actual:
            raise ValueError("Revision approval does not bind to the current edit.")
        self.store.update(run_dir, "revising")
        source = attempt / "source.png"
        shutil.copy2(Path(state["base_image_path"]), source)
        response = self.image_provider.edit(
            source, state["revision_prompt"],
            size=get_profile(state["profile"]).default_size, output=attempt,
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
        iteration = state.get("iteration", 1) + 1
        self.store.register(
            run_dir, revision_source=f"{relative}/source.png",
            revision_response=f"{relative}/response.json", image=f"{relative}/image.png",
        )
        self.store.update(
            run_dir, "revision_reviewing", iteration=iteration,
            latest_image=str(image_path), image_sha256=digest_file(image_path),
        )
        return {"image_path": str(image_path), "iteration": iteration,
                "status": "revision_reviewing"}

    def review_revision(self, state):
        run_dir = self._dir(state)
        attempt = Path(state["revision_dir"])
        prompt = compile_revision_review_prompt(
            proposal=state["proposal"], plan=state["revision_plan"],
        )
        (attempt / "review-prompt.md").write_text(prompt, encoding="utf-8")
        write_json(attempt / "review-request.json", {
            "schema": "revision-review.schema.json",
            "baseline_image": state["base_image_path"],
            "baseline_sha256": digest_file(Path(state["base_image_path"])),
            "edited_image": state["image_path"],
            "edited_sha256": digest_file(Path(state["image_path"])),
        })
        review, response = self.text_provider.review_revision(
            Path(state["base_image_path"]), Path(state["image_path"]), prompt,
            schema_name="revision-review.schema.json",
        )
        validate_revision_review(review, state["revision_plan"])
        write_json(attempt / "review-response.json", response)
        write_json(attempt / "review.json", review)
        relative = attempt.relative_to(run_dir).as_posix()
        self.store.register(run_dir, review=f"{relative}/review.json")
        self.store.update(run_dir, "reviewed")
        return {"review": review, "revision_review": review, "status": "reviewed"}


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
            "evidence_mode": job.evidence_mode, "status": "created", "iteration": 1,
        }
        try:
            self.graph.invoke(state, config=config)
        except Exception as exc:
            self.store.update(run_dir, "failed", error_type=type(exc).__name__, error=str(exc))
            raise
        return self._result(run_id)

    def resume(self, run_id: str, decision: object) -> RunResult:
        if run_id not in self._active:
            raise ValueError("This process has no resumable checkpoint for the run.")
        run_dir = self.store.root / run_id
        try:
            if not hasattr(decision, "to_dict"):
                raise TypeError("A resumable decision must provide to_dict().")
            self.graph.invoke(Command(resume=decision.to_dict()), config=self._active[run_id])
        except Exception as exc:
            self.store.update(run_dir, "failed", error_type=type(exc).__name__, error=str(exc))
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
        return RunSummary(run_id=run_id, status=manifest["status"],
                          run_dir=run_dir, manifest=manifest)

    def _result(self, run_id: str) -> RunResult:
        summary = self.inspect(run_id)
        registered = summary.manifest.get("artifacts", {})
        paths = {
            "manifest": summary.run_dir / "manifest.json",
            "retrieval_bundle": summary.run_dir / "retrieval/bundle.json",
            "proposal": summary.run_dir / "design/proposal.json",
            "presentation": summary.run_dir / "design/presentation.md",
            "generation_prompt": summary.run_dir / "generation/prompt.md",
            "image": Path(summary.manifest.get("latest_image", "")),
            "review": summary.run_dir / registered.get("review", "review/review.json"),
        }
        for name in ("reference_package", "reference_prompt", "reference_plan"):
            if name in registered:
                paths[name] = summary.run_dir / registered[name]
        package_path = paths.get("reference_package")
        if package_path and package_path.is_file():
            package = json.loads(package_path.read_text(encoding="utf-8"))
            snapshot = Path(summary.manifest["atlas_snapshot"])
            for index, row in enumerate(package["references"], start=1):
                paths[f"reference_image_{index:02d}"] = snapshot / row["file"]
        for name in (
            "revision_request", "revision_plan", "revision_prompt",
            "revision_approval", "revision_source", "revision_response",
        ):
            if name in registered:
                paths[name] = summary.run_dir / registered[name]
        artifacts = {name: str(path.resolve()) for name, path in paths.items()
                     if str(path) and path.is_file()}
        messages = {
            "awaiting_approval": "Review the saved proposal and generation prompt.",
            "rejected": "Image generation was rejected; the experiment remains recorded.",
            "awaiting_revision": "Review the image and either accept, revise, or discard it.",
            "awaiting_revision_approval": "Review and approve the exact image-edit request.",
            "completed": "The reviewer accepted the generated image.",
            "discarded": "The reviewer discarded the generated image.",
            "failed": "The experiment failed; inspect its manifest and saved attempts.",
        }
        return RunResult(run_id=run_id, status=summary.status, run_dir=summary.run_dir,
                         message=messages.get(summary.status, summary.status), artifacts=artifacts)
