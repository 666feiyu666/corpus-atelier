"""Save an experiment's reasoning and locally supplied images together."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from shutil import copy2
from uuid import uuid4

def save_experiment(record, image_paths=(), output_dir="outputs"):
    """Create a fresh folder; never overwrite a previous experiment.

    Pass only research notes and non-secret generation settings, never a client,
    environment dictionary, API key, or request headers.
    """
    sources = [Path(path).resolve(strict=True) for path in image_paths]
    if any(not path.is_file() for path in sources):
        raise ValueError("Each image path must refer to a file")
    # Validate notes before creating an output directory.
    notes = json.loads(json.dumps(record, ensure_ascii=False, allow_nan=False))
    now = datetime.now(timezone.utc)
    run = Path(output_dir) / (now.strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    run.mkdir(parents=True, exist_ok=False)
    images = []
    for index, source in enumerate(sources, start=1):
        target = run / f"{index:02d}_{source.name}"
        copy2(source, target)
        images.append({"file": target.name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    payload = {"saved_at": now.isoformat(), "notes": notes, "images": images}
    (run / "record.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return run


def write_json(path, value):
    """Replace a record atomically after serializing its non-secret contents."""
    path = Path(path)
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def start_run(brief, *, original_user_request=None, output_dir="outputs"):
    snapshot = {"original_user_request": original_user_request, "brief": brief}
    json.dumps(snapshot, allow_nan=False)
    now = datetime.now(timezone.utc)
    folder = Path(output_dir).resolve() / (now.strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    write_json(folder / "brief.json", snapshot)
    write_json(folder / "run.json", {"format_version": 2, "created_at": now.isoformat(),
                                     "status": "planning", "rounds": "rounds"})
    return folder


def update_run(folder, status, **details):
    path = Path(folder) / "run.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record.update(status=status, **details)
    write_json(path, record)


def new_attempt(output_dir):
    """Never overwrite an earlier request, including an uncertain failed call."""
    now = datetime.now(timezone.utc)
    path = Path(output_dir).resolve() / ("attempt_" + now.strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    path.mkdir(parents=True, exist_ok=False)
    return path
