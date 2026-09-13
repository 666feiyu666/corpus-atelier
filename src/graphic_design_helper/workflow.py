"""Manage reviewed model calls, iteration boundaries, and run provenance."""
from copy import deepcopy
import json
from pathlib import Path
from .designer import propose_design
from .image_generator import generate_image
from .prompt_builder import build_designer_request, build_image_prompt as compose_prompt, request_token
from .proposal_schema import validate_proposal
from .records import write_json, update_run


def validate_strategies(sign_strategies):
    for row in sign_strategies:
        if row.get("selected", False):
            if row.get("production") != "generate":
                raise ValueError("Source-based composition is not implemented.")
            if not row.get("relations"):
                raise ValueError("Selected elements need an explained sign relationship.")


def _check_saved_history(run_dir, history):
    saved = load_rounds(run_dir)
    supplied = {entry["folder"]: entry for entry in history}
    for entry in saved:
        if entry["folder"] not in supplied or entry != supplied[entry["folder"]]:
            raise ValueError("Saved rounds differ from memory. Load this run's rounds before continuing.")


def design_round(request, *, approved_token, run_dir, history, client=None):
    """Submit one previewed designer request; never trigger image generation."""
    _check_saved_history(run_dir, history)
    current = build_designer_request(**request["designer_input"],
                                    image_path=request.get("image_path"), model=request["model"],
                                    reasoning_effort=request["reasoning_effort"])
    if request_token(request) != approved_token or request_token(current) != approved_token:
        raise ValueError("Designer inputs changed. Preview and review again.")
    context = request["designer_input"]["revision"]
    if history:
        previous = history[-1]
        if not previous.get("image_path") or not context or context.get("parent_folder") != previous["folder"]:
            raise ValueError("Preview the latest successful poster before self-review.")
        if Path(request["image_path"]).resolve() != Path(previous["image_path"]).resolve():
            raise ValueError("Self-review image does not match the latest poster.")
    elif context is not None:
        raise ValueError("A revision needs previous history.")
    folder = Path(run_dir).resolve() / "rounds" / f"{len(history) + 1:02d}"
    update_run(run_dir, "designer_requested", current_round=len(history) + 1)
    try:
        record = propose_design(request, output_dir=folder / "designer", client=client)
        record.update(run_dir=str(Path(run_dir).resolve()), round_folder=str(folder),
                      round=len(history) + 1)
        write_json(Path(record["folder"]) / "response.json", record)
        if history:
            history[-1]["self_review"] = deepcopy(record)
            # Never rewrite legacy round files outside the new run.
            if history[-1].get("run_dir") == str(Path(run_dir).resolve()):
                save_round(history[-1])
        status = record["proposal"]["status"]
        update_run(run_dir, "awaiting_image_review" if status == "ready" else status,
                   latest_designer_attempt=record["folder"])
        return record
    except Exception:
        update_run(run_dir, "designer_failed")
        raise


def _review_token(image_spec, image_prompt, research, settings):
    validate_strategies(research.get("sign_strategies", []))
    if "proposal" in research:
        validate_proposal(research["proposal"])
        if research["proposal"]["status"] != "ready":
            raise ValueError("Resolve clarification or source requirements before generation.")
    return request_token([image_spec, image_prompt, research, settings])


def review_token(image_spec, research, settings, *, image_prompt=None):
    assembled = compose_prompt(image_spec)
    if image_prompt is not None and image_prompt != assembled:
        raise ValueError("Image instructions or specification changed. Preview again.")
    return _review_token(image_spec, assembled, research, settings)


def generate_round(image_spec, research, settings, *, approved_token, history,
                   revision, output_dir="outputs", client=None):
    image_prompt = compose_prompt(image_spec)
    if approved_token != _review_token(image_spec, image_prompt, research, settings):
        raise ValueError("Draft changed or is unreviewed. Preview and review it again.")
    if len(history) >= 3:
        raise ValueError("This experiment is limited to one initial attempt and two revisions.")
    if history and (not history[-1].get("self_review") or not revision.get("reason", "").strip()):
        raise ValueError("Have the designer examine the previous image and document the revision first.")
    designer = research.get("designer_record", {})
    run_dir = designer.get("run_dir")
    if run_dir:
        _check_saved_history(run_dir, history)
        manifest = json.loads((Path(run_dir) / "run.json").read_text(encoding="utf-8"))
        if manifest.get("latest_designer_attempt") != designer.get("folder"):
            raise ValueError("A newer designer response exists. Review that response first.")
        folder = Path(run_dir) / "rounds" / f"{len(history) + 1:02d}"
        if str(folder) != designer.get("round_folder"):
            raise ValueError("The proposal belongs to a different round.")
        context = designer["designer_input"]["revision"]
        if history and (not context or context.get("parent_folder") != history[-1]["folder"]):
            raise ValueError("The proposal does not review the latest poster.")
    else:
        # Direct callers still receive separate non-overwriting attempts.
        from .records import start_run
        run_dir = history[-1].get("run_dir") if history else None
        run_dir = run_dir or str(start_run(research.get("brief", {}), output_dir=output_dir))
        folder = Path(run_dir) / "rounds" / f"{len(history) + 1:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / "round.json").exists():
        raise ValueError("This round already has an image attempt. Load its record before continuing.")
    entry = deepcopy({"round": len(history) + 1, "status": "requested", "run_dir": run_dir,
                      "folder": str(folder), "parent": history[-1].get("folder") if history else None,
                      "research": research, "image_spec": image_spec, "image_prompt": image_prompt,
                      "settings": settings, "reviewed_token": approved_token, "revision": revision})
    history.append(entry)
    save_round(entry)
    update_run(run_dir, "image_requested", current_round=entry["round"])
    try:
        path, record = generate_image(image_prompt, **settings, image_spec=deepcopy(image_spec),
                                      output_dir=folder / "image", client=client)
        entry.update(status="generated", image_path=str(path.resolve()), generation=record)
        update_run(run_dir, "awaiting_human_decision", latest_image=str(path.resolve()))
    except Exception as exc:
        entry.update(status="failed", error_type=type(exc).__name__)
        update_run(run_dir, "image_failed")
        raise
    finally:
        save_round(entry)
    return entry


def save_round(entry):
    write_json(Path(entry["folder"]) / "round.json", entry)


def load_rounds(run_dir):
    """Read an existing run without rewriting its records."""
    return [json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((Path(run_dir) / "rounds").glob("*/round.json"))]
