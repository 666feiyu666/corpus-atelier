"""Send one prepared design request and preserve the exact input and response."""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from .records import new_attempt, write_json
from .proposal_schema import load_proposal_schema, validate_proposal


def propose_design(prompt, *, model="gpt-5.6-luna", reasoning_effort="medium",
                   output_dir="outputs", image_path=None, client=None):
    """Accept a prepared request (preferred) or a legacy text prompt. Never retry."""
    request = deepcopy(prompt) if isinstance(prompt, dict) else {
        "prompt": prompt, "model": model, "reasoning_effort": reasoning_effort,
        "response_schema": load_proposal_schema()}
    if not isinstance(request["prompt"], str) or not request["prompt"].strip():
        raise ValueError("Provide a reviewed designer prompt.")
    if not request["model"].strip():
        raise ValueError("Provide a designer model.")
    image_path = request.get("image_path", image_path)
    image_bytes = None
    if image_path is not None:
        image_bytes = Path(image_path).read_bytes()
        if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Designer self-review expects the generated PNG.")
        digest = hashlib.sha256(image_bytes).hexdigest()
        if request.get("image_sha256", digest) != digest:
            raise ValueError("Poster changed since preview. Preview again.")
        request["image_sha256"] = digest
    request_input = request["prompt"]
    folder = new_attempt(output_dir)
    if image_bytes is not None:
        (folder / "input.png").write_bytes(image_bytes)
        request["image_path"] = "input.png"
        request_input = [{"role": "user", "content": [
            {"type": "input_text", "text": request["prompt"]},
            {"type": "input_image", "image_url": "data:image/png;base64," +
             base64.b64encode(image_bytes).decode("ascii")},
        ]}]
    write_json(folder / "request.json", {**request, "store": False})
    (folder / "prompt.md").write_text(request["prompt"], encoding="utf-8")
    record = {**request, "status": "requested", "folder": str(folder),
              "kind": "designer_self_review" if image_bytes is not None else "design_proposal"}
    write_json(folder / "response.json", record)
    owned = client is None
    try:
        if owned:
            from openai import OpenAI
            client = OpenAI(max_retries=0, timeout=600.0)
        response = client.responses.create(
            model=request["model"], reasoning={"effort": request["reasoning_effort"]}, store=False,
            input=request_input, text={"format": {"type": "json_schema", "name": "design_proposal",
                                          "strict": True, "schema": request["response_schema"]}},
        )
        record["raw_output"] = response.output_text
        record["response_id"] = getattr(response, "id", None)
        record["request_id"] = getattr(response, "_request_id", None)
        record["api_status"] = getattr(response, "status", None)
        usage = getattr(response, "usage", None)
        record["usage"] = usage.model_dump(mode="json") if usage else None
        if record["api_status"] != "completed" or not response.output_text:
            raise ValueError("Designer did not return a completed proposal.")
        proposal = validate_proposal(json.loads(response.output_text), request["response_schema"])
        write_json(folder / "proposal.json", proposal)
        record.update(status="completed", proposal=proposal)
        write_json(folder / "response.json", record)
        return record
    except Exception as exc:
        record.update(status="failed", error_type=type(exc).__name__)
        write_json(folder / "response.json", record)
        raise
    finally:
        if owned and client is not None:
            client.close()
