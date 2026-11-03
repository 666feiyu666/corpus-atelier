"""Compile renderer prompts for each candidate and persist their bindings."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from ...artifacts.hashing import digest_json
from ...design_support.validation import validate_image_prompt
from ...atelier.image_prompt import compile_generation_prompt, synthesize_image_prompt
from ...config.models import get_image_model_profile
from ..registry import get_profile
from ..state import AtelierState
from .references import text_references

class CandidatesMixin:
    """Compile renderer prompts for each candidate and persist their bindings."""

    @staticmethod
    def _generation_binding(state: AtelierState, candidate: dict[str, Any]) -> dict[str, Any]:
        binding = {
            "candidate_id": candidate["candidate_id"],
            "direction_seed": candidate["direction_seed"],
            "prompt": candidate["generation_prompt"],
            "request": candidate["generation_request"],
            "proposal": candidate.get("proposal"),
            "image_prompt": candidate.get("image_prompt"),
            "generation_size": state["generation_size"],
            "output_ratio": list(state["output_ratio"]),
            "canvas": state["canvas"],
        }
        return binding

    @staticmethod
    def _candidate_dir(run_dir: Path, candidate_id: str) -> Path:
        return run_dir / "candidates" / candidate_id

    @classmethod
    def _artifact_path(cls, run_dir: Path, candidate_id: str, relative: str) -> str | None:
        path = cls._candidate_dir(run_dir, candidate_id) / relative
        return str(path.resolve()) if path.is_file() else None

    @staticmethod
    def _batch_digest(candidates: list[dict[str, Any]]) -> str:
        """Bind approval to candidate availability and each exact generation request."""
        return digest_json([
            {"candidate_id": candidate["candidate_id"], "status": candidate["status"],
             "generation_digest": candidate.get("generation_digest")}
            for candidate in candidates
        ])

    def _image_model_family(self) -> str:
        model = getattr(self.image_provider, "model", "")
        try:
            return get_image_model_profile(model).family
        except ValueError:
            return "gpt-image-2"

    def _generation_inputs(self, state: AtelierState) -> tuple[list[Path], Path | None, str]:
        references = [Path(path) for path in state.get("reference_paths") or []]
        mask = Path(state["mask_path"]) if state.get("mask_path") else None
        operation = (
            "mask_edit" if mask is not None
            else "reference_generation" if references else "generation"
        )
        return references, mask, operation

    @staticmethod
    def _candidate_input_paths(candidate: dict[str, Any]) -> tuple[list[Path], Path | None]:
        """Turn the persisted string paths back into filesystem paths."""
        references = [Path(path) for path in candidate.get("reference_paths") or []]
        mask = Path(candidate["mask_path"]) if candidate.get("mask_path") else None
        return references, mask

    def _describe_generation_request(self, state: AtelierState, candidate: dict[str, Any]) -> dict:
        references, mask = self._candidate_input_paths(candidate)
        return self.image_provider.describe_request(
            candidate["generation_prompt"],
            size=state["generation_size"],
            reference_paths=references or None,
            mask_path=mask,
        )

    def _compile_candidate(self, state: AtelierState, candidate: dict[str, Any], *,
                           design: dict | None,
                           references: list[dict[str, Any]]) -> dict[str, Any]:
        """Write one renderer prompt for a candidate and bind it to its exact request."""
        run_dir = self._dir(state)
        target_model = getattr(
            self.image_provider, "model", type(self.image_provider).__name__,
        )
        candidate_id = candidate["candidate_id"]
        root = self._candidate_dir(run_dir, candidate_id)
        reference_paths, mask_path, operation = self._generation_inputs(state)
        prompt = ""
        try:
            prompt, image_prompt, response = synthesize_image_prompt(
                brief=state["brief"],
                canvas=state["canvas"],
                provider_profile=target_model,
                model_family=self._image_model_family(),
                provider=self.text_provider,
                design=design,
                operation=operation,
                reference_paths=reference_paths or None,
                corpus_references=references,
                content_language=state.get("content_language"),
            )
            image_prompt = validate_image_prompt(
                image_prompt, state["brief"].get("exact_copy", []),
            )
            request = {
                "model": getattr(
                    self.text_provider, "model", type(self.text_provider).__name__,
                ),
                "target_image_model": target_model,
                "model_family": self._image_model_family(),
                "operation": operation,
                "schema": "image-prompt.schema.json",
                "candidate_id": candidate_id,
                "corpus_references": [item["id"] for item in references],
            }
            self.store.json(root, "image-prompt/request.json", request)
            self.store.text(root, "image-prompt/prompt.md", prompt)
            self.store.json(root, "image-prompt/response.json", response)
            self.store.json(root, "image-prompt/image-prompt.json", image_prompt)
            if references:
                self.store.json(root, "image-prompt/references.json", references)
            generation_prompt = compile_generation_prompt(
                image_prompt,
                exact_copy=state["brief"].get("exact_copy", []),
                user_requirements=state["brief"].get("user_requirements", []),
            )
            self.store.text(root, "generation/prompt.md", generation_prompt)
            prepared = {
                **candidate,
                "image_prompt": image_prompt,
                "corpus_references": [item["id"] for item in references],
                "reference_paths": [str(path) for path in reference_paths],
                "mask_path": str(mask_path) if mask_path is not None else None,
                "generation_prompt": generation_prompt,
                "status": "ready",
            }
            prepared["generation_request"] = self._describe_generation_request(state, prepared)
            self.store.json(
                root, "generation/request-preview.json", prepared["generation_request"],
            )
            prepared["generation_digest"] = digest_json(
                self._generation_binding(state, prepared)
            )
            return prepared
        except Exception as exc:
            if prompt:
                self.store.text(root, "image-prompt/prompt.md", prompt)
            self.store.json(root, "image-prompt/error.json", {
                "status": "failed",
                "error_type": type(exc).__name__,
                "message": str(exc),
            })
            return {
                **candidate,
                "status": "failed",
                "error": {"stage": "image_prompt", "type": type(exc).__name__, "message": str(exc)},
            }

    def compile_candidates(self, state: AtelierState) -> AtelierState:
        run_dir = self._dir(state)
        self.store.update(run_dir, "compiling_candidates")
        references = text_references(self._corpus_references(state))

        def compile_one(candidate):
            if candidate["status"] != "implemented":
                return candidate
            return self._compile_candidate(
                state, candidate, design=candidate.get("proposal"), references=references,
            )

        with ThreadPoolExecutor(max_workers=len(state["candidates"])) as executor:
            candidates = list(executor.map(compile_one, state["candidates"]))
        return self._finish_compilation(state, candidates)

    def _finish_compilation(self, state: AtelierState,
                            candidates: list[dict[str, Any]]) -> AtelierState:
        """Bind the batch digest and publish the first ready candidate's artifacts."""
        run_dir = self._dir(state)
        candidates.sort(key=lambda item: item["candidate_id"])
        ready = [candidate for candidate in candidates if candidate["status"] == "ready"]
        if not ready:
            self.store.json(run_dir, "candidates/index.json", candidates)
            raise ValueError("No candidate reached generation preview.")
        batch_digest = self._batch_digest(candidates)
        self.store.json(run_dir, "candidates/index.json", candidates)
        first = ready[0]["candidate_id"]
        artifacts: dict[str, str] = {
            "candidate_index": "candidates/index.json",
            "image_prompt": f"candidates/{first}/image-prompt/image-prompt.json",
            "generation_prompt": f"candidates/{first}/generation/prompt.md",
            "generation_request_preview": f"candidates/{first}/generation/request-preview.json",
        }
        if (run_dir / f"candidates/{first}/design-implementation/proposal.json").is_file():
            artifacts.update({
                "proposal": f"candidates/{first}/design-implementation/proposal.json",
                "presentation": f"candidates/{first}/design-implementation/presentation.md",
                "design_prompt": f"candidates/{first}/design-implementation/prompt.md",
                "design_implementation_prompt": (
                    f"candidates/{first}/design-implementation/prompt.md"
                ),
            })
        self.store.register(run_dir, **artifacts)
        return {
            "candidates": candidates,
            "batch_digest": batch_digest,
            "status": "awaiting_approval",
        }

    def compile_direct_candidates(self, state: AtelierState) -> AtelierState:
        """Build one renderer prompt straight from the reviewed brief, without design stages."""
        run_dir = self._dir(state)
        profile = get_profile(state["profile"])
        generation_size, output_ratio, canvas = self._resolve_canvas(profile, state["brief"])
        self.store.update(run_dir, "compiling_candidates", candidate_count=1)
        brief = state["brief"]
        label = next(
            (str(brief[key]) for key in ("topic", "article_title", "deliverable")
             if brief.get(key)),
            "Direct generation",
        )
        candidate = {
            "candidate_id": "c01",
            "direction_seed": {
                "label": label if len(label) <= 60 else f"{label[:59]}…",
                "design_thesis": "Render the reviewed brief directly.",
                "objective_strategy": "Preserve the brief's stated requirement.",
                "direction_decisions": [],
                "implementation_freedom": [],
                "portfolio_role": "direct",
            },
            "proposal": None,
            "status": "implemented",
            "error": None,
        }
        compiled = self._compile_candidate(
            {**state, "generation_size": generation_size,
             "output_ratio": output_ratio, "canvas": canvas},
            candidate, design=brief,
            references=text_references(self._corpus_references(state)),
        )
        result = self._finish_compilation(
            {**state, "generation_size": generation_size,
             "output_ratio": output_ratio, "canvas": canvas},
            [compiled],
        )
        return {
            **result,
            "candidate_count": 1,
            "generation_size": generation_size,
            "output_ratio": output_ratio,
            "canvas": canvas,
        }
