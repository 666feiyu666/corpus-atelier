"""Read the brief and image-model input belonging to a discussed design round."""

from pathlib import Path

from .artifacts.paths import task_path, verified_image
from .artifacts.records import read_json
from .state import RunSummary


def _round_brief(summary: RunSummary) -> tuple[dict | None, str | None]:
    artifacts = summary.manifest.get("artifacts", {})
    snapshot_relative = artifacts.get("conversation_snapshot")
    if snapshot_relative and (summary.run_dir / snapshot_relative).is_file():
        snapshot = read_json(task_path(summary.run_dir, snapshot_relative))
        if not isinstance(snapshot, dict):
            raise ValueError("The archived conversation snapshot must be an object.")
        if snapshot.get("design_brief") is not None:
            return snapshot["design_brief"], snapshot_relative
    brief_relative = artifacts.get("brief")
    if brief_relative and (summary.run_dir / brief_relative).is_file():
        return read_json(task_path(summary.run_dir, brief_relative)), brief_relative
    return None, None


def _attempt_request(root: Path, candidate: dict) -> Path | None:
    """Use the selected image's own attempt, or the latest failed generation attempt."""
    relative = candidate.get("generation_artifacts", {}).get("request")
    if relative:
        path = root / relative
        return task_path(root, path) if path.is_file() else None
    if candidate.get("image_path"):
        image = task_path(root, candidate["image_path"])
        path = image.parent / "request.json"
        return task_path(root, path) if path.is_file() else None
    generation = root / "candidates" / candidate["candidate_id"] / "generation"
    if not generation.is_dir():
        return None
    generation = task_path(root, generation)
    attempts = [path for path in generation.glob("attempt_*/request.json")
                if path.parent.name.removeprefix("attempt_").isdigit()]
    if not attempts:
        return None
    latest = max(attempts, key=lambda path: int(path.parent.name.removeprefix("attempt_")))
    return task_path(root, latest)


def _generation_input(root: Path, candidate: dict) -> dict:
    request_path = _attempt_request(root, candidate)
    if request_path is not None:
        request = read_json(request_path)
        prompt = request.get("prompt") if isinstance(request, dict) else None
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("The archived image-model request has no prompt.")
        return {
            "generation_prompt": prompt,
            "prompt_stage": "generation_input",
            "prompt_source": request_path.relative_to(root).as_posix(),
        }
    # An existing result must never be attributed to a later or reconstructed preview.
    if not candidate.get("image_path") and not candidate.get("generation_artifacts"):
        preview = root / "candidates" / candidate["candidate_id"] / "generation/prompt.md"
        if preview.is_file():
            preview = task_path(root, preview)
            return {
                "generation_prompt": preview.read_text(encoding="utf-8"),
                "prompt_stage": "generation_preview",
                "prompt_source": preview.relative_to(root).as_posix(),
            }
    return {"generation_prompt": None, "prompt_stage": "unavailable", "prompt_source": None}


def load_round_context(summary: RunSummary, candidate_id: str | None = None) -> tuple[dict, list[dict[str, str]]]:
    """Capture round-specific evidence when the user queues a discussion message."""
    brief, brief_source = _round_brief(summary)
    context = {
        "run_id": summary.run_id,
        "status": summary.status,
        "brief_revision": summary.manifest.get("conversation_revision", 0),
        "design_brief": brief,
        "brief_source": brief_source,
        "candidates": [],
    }
    relative = summary.manifest.get("artifacts", {}).get("candidate_index")
    if not relative:
        if candidate_id is not None:
            raise ValueError("The feedback candidate does not exist in this round.")
        return context, []
    candidates = read_json(task_path(summary.run_dir, relative))
    if candidate_id is not None and candidate_id not in {candidate["candidate_id"] for candidate in candidates}:
        raise ValueError("The feedback candidate does not exist in this round.")
    images = []
    for candidate in candidates:
        if candidate_id is not None and candidate["candidate_id"] != candidate_id:
            continue
        record = {key: candidate.get(key) for key in ("candidate_id", "proposal", "status")}
        record.update(_generation_input(summary.run_dir, candidate))
        if candidate.get("image_path"):
            image = verified_image(summary.run_dir, candidate["image_path"], candidate.get("image_sha256"))
            images.append({"path": str(image), "sha256": candidate["image_sha256"],
                           "candidate_id": candidate["candidate_id"]})
        context["candidates"].append(record)
    return context, images
