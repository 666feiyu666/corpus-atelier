"""GPT Image generation with an automatically saved request record."""
import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from .prompt_files import load_prompt


def compose_prompt(production_prompt):
    """Prepare the complete image input for preview, approval, and generation."""
    if not isinstance(production_prompt, str) or not production_prompt.strip():
        raise ValueError("Write and review a non-empty production prompt first.")
    return load_prompt("image-generation.md") + "\n# Production prompt\n\n" + production_prompt


def generate_image(prompt, *, model="gpt-image-2", size="1024x1536", quality="medium", output_dir="outputs", client=None):
    """Send the exact assembled, reviewed prompt and record it alongside one PNG.

    If client is omitted, the OpenAI SDK reads OPENAI_API_KEY from the environment.
    Exceptions propagate; there is no automatic retry of a potentially billable call.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Provide a non-empty prompt")
    if quality not in {"auto", "low", "medium", "high"}:
        raise ValueError("quality must be auto, low, medium, or high")
    settings = {"model": model, "size": size, "quality": quality, "output_format": "png", "n": 1}
    stamp = datetime.now(timezone.utc)
    run = Path(output_dir) / (stamp.strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    run.mkdir(parents=True, exist_ok=False)
    record = {"status": "requested", "requested_at": stamp.isoformat(), "prompt": prompt, "settings": settings}
    record_path = run / "generation.json"
    def save():
        record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    save()
    owned_client = client is None
    try:
        if owned_client:
            from openai import OpenAI
            client = OpenAI(max_retries=0, timeout=600.0)
        response = client.images.generate(prompt=prompt, **settings)
        if not response.data or not response.data[0].b64_json:
            raise ValueError("The API returned no base64 image")
        image_bytes = base64.b64decode(response.data[0].b64_json, validate=True)
        if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("The API did not return the requested PNG format")
        target = run / "image.png"
        target.write_bytes(image_bytes)
        usage = getattr(response, "usage", None)
        record.update({
            "status": "generated", "file": target.name,
            "sha256": hashlib.sha256(image_bytes).hexdigest(),
            "request_id": getattr(response, "_request_id", None),
            "usage": usage.model_dump(mode="json") if usage is not None else None,
            "revised_prompt": getattr(response.data[0], "revised_prompt", None),
        })
        save()
        return target, record
    except Exception as exc:
        # Do not persist exception bodies, which may contain sensitive request details.
        record.update({"status": "failed", "error_type": type(exc).__name__})
        save()
        raise
    finally:
        if owned_client and client is not None:
            client.close()
