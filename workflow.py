"""One reviewed generation at a time, with durable round provenance."""
from copy import deepcopy
import json

from design import compose_prompt, review_token
from generation import generate_image
from records import save_experiment


def generate_round(prompt, research, settings, *, approved_token, history,
                   revision, output_dir="outputs", client=None):
    if approved_token != review_token(prompt, research, settings):
        raise ValueError("Draft changed or is unreviewed. Preview and review it again.")
    if len(history) >= 3:
        raise ValueError("This experiment is limited to one initial attempt and two revisions.")
    if history and (not history[-1].get("self_review") or not revision.get("reason", "").strip()):
        raise ValueError("Have the designer examine the previous image and document the revision first.")
    entry = deepcopy({"round": len(history) + 1, "status": "requested",
                      "parent": history[-1].get("folder") if history else None,
                      "research": research, "production_prompt": prompt,
                      "settings": settings, "reviewed_token": approved_token,
                      "revision": revision})
    folder = save_experiment(entry, output_dir=output_dir)
    entry["folder"] = str(folder.resolve())
    history.append(entry)  # Count attempts, including an uncertain/failed paid request.
    try:
        path, record = generate_image(compose_prompt(prompt), **settings,
                                      output_dir=folder, client=client)
        entry.update(status="generated", image_path=str(path.resolve()), generation=record)
    except Exception as exc:
        entry.update(status="failed", error_type=type(exc).__name__)
        raise
    finally:
        save_round(entry)
    return entry


def save_round(entry):
    from pathlib import Path
    (Path(entry["folder"]) / "round.json").write_text(
        json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
