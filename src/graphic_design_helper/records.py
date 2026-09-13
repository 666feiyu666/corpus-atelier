"""Save an experiment's reasoning and locally supplied images together."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from shutil import copy2
from uuid import uuid4


def _numbered_directory(output_dir, prefix):
    """Reserve the next number without overwriting existing files or directories."""
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(rf"{re.escape(prefix)}_(\d+)")
    numbers = [int(match.group(1)) for child in root.iterdir()
               if (match := pattern.fullmatch(child.name))]
    number = max(numbers, default=0) + 1
    while True:
        folder = root / f"{prefix}_{number:02d}"
        try:
            folder.mkdir()
            return folder
        except FileExistsError:
            number += 1


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
    run = _numbered_directory(output_dir, "snapshot")
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
    folder = _numbered_directory(output_dir, "run")
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
    return _numbered_directory(output_dir, "attempt")
