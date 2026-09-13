"""Send the exact approved image prompt and save one PNG without automatic retries."""
import base64
import hashlib
from .prompt_builder import build_image_prompt as compose_prompt
from .records import new_attempt, write_json


def generate_image(prompt, *, model="gpt-image-2", size="1024x1536", quality="medium",
                   output_dir="outputs", client=None, image_spec=None):
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Provide a non-empty prompt")
    if not model.strip() or quality not in {"auto", "low", "medium", "high"}:
        raise ValueError("Provide a model and valid quality.")
    settings = {"model": model, "size": size, "quality": quality, "output_format": "png", "n": 1}
    folder = new_attempt(output_dir)
    record = {"status": "requested", "prompt": prompt, "settings": settings, "folder": str(folder)}
    write_json(folder / "request.json", {"prompt": prompt, **settings})
    (folder / "prompt.md").write_text(prompt, encoding="utf-8")
    if image_spec is not None:
        write_json(folder / "image-spec.json", image_spec)
    write_json(folder / "response.json", record)
    owned = client is None
    try:
        if owned:
            from openai import OpenAI
            client = OpenAI(max_retries=0, timeout=600.0)
        response = client.images.generate(prompt=prompt, **settings)
        if not response.data or not response.data[0].b64_json:
            raise ValueError("The API returned no base64 image")
        data = base64.b64decode(response.data[0].b64_json, validate=True)
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("The API did not return the requested PNG format")
        target = folder / "image.png"
        target.write_bytes(data)
        usage = getattr(response, "usage", None)
        record.update(status="generated", file=target.name, sha256=hashlib.sha256(data).hexdigest(),
                      request_id=getattr(response, "_request_id", None),
                      usage=usage.model_dump(mode="json") if usage else None,
                      revised_prompt=getattr(response.data[0], "revised_prompt", None))
        write_json(folder / "response.json", record)
        return target, record
    except Exception as exc:
        record.update(status="failed", error_type=type(exc).__name__)
        write_json(folder / "response.json", record)
        raise
    finally:
        if owned and client is not None:
            client.close()
