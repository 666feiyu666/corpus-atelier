"""Render approved candidates and record the human selection."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from langgraph.types import interrupt
from ...artifacts.hashing import digest_file
from ...artifacts.records import write_json
from ...design_support.rendering import normalize_canvas
from ..state import AtelierState

class GenerationMixin:
    """Render approved candidates and record the human selection."""

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
            write_json(attempt / "image-prompt.json", candidate["image_prompt"])
            try:
                references, mask = self._candidate_input_paths(candidate)
                response = self.image_provider.generate(
                    candidate["generation_prompt"],
                    size=state["generation_size"],
                    output=attempt,
                    reference_paths=references or None,
                    mask_path=mask,
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
