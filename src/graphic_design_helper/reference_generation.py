"""Local-reference image generation for the practical second pilot."""

import base64
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from PIL import Image

from .records import new_attempt, write_json


ALLOWED_ROLES = {"cover", "illustration"}
ALLOWED_QUALITIES = {"low", "medium", "high", "auto"}
PRESETS = {
    "cover": (1280, 544),
    "illustration": (1024, 1024),
}


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_corpus(root):
    """Load only locally present, verified CC0 reference images."""
    root = Path(root).resolve()
    manifest = root / "manifest.json"
    if not manifest.is_file():
        raise FileNotFoundError(f"Corpus manifest missing: {manifest}")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("items"), list):
        raise ValueError("Unsupported corpus manifest.")
    items = []
    seen = set()
    for raw in data["items"]:
        item = deepcopy(raw)
        if item.get("id") in seen or not item.get("id"):
            raise ValueError("Corpus IDs must be unique and non-empty.")
        seen.add(item["id"])
        if item.get("license") != "CC0" or not item.get("source_url") or not item.get("license_url"):
            raise ValueError(f"Corpus item {item['id']} needs verified CC0 provenance.")
        relative = Path(item.get("file", ""))
        image_path = (root / relative).resolve()
        if relative.is_absolute() or image_path == root or root not in image_path.parents:
            raise ValueError(f"Corpus item {item['id']} has an unsafe image path.")
        if not image_path.is_file() or _sha256(image_path) != item.get("sha256"):
            raise ValueError(f"Corpus item {item['id']} is missing or changed.")
        with Image.open(image_path) as image:
            image.verify()
        if not isinstance(item.get("tags"), list) or not all(isinstance(t, str) for t in item["tags"]):
            raise ValueError(f"Corpus item {item['id']} needs text tags.")
        item["path"] = str(image_path)
        items.append(item)
    return items


def search_corpus(items, query="", selected_tags=(), limit=None):
    """Rank a small curated corpus by explicit visual words, without article analysis."""
    query = query.strip().casefold()
    selected = {tag.casefold() for tag in selected_tags}
    scored = []
    for item in items:
        tags = [tag.casefold() for tag in item["tags"]]
        if selected and not selected.issubset(set(tags)):
            continue
        haystack = " ".join([item["title"], *item["tags"]]).casefold()
        score = sum(4 for tag in tags if query and query in tag)
        score += sum(1 for word in query.split() if word in haystack)
        if query and score == 0:
            continue
        scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["title"], pair[1]["id"]))
    return [item for _, item in scored[:limit]]


def build_request(items, selected_ids, *, role, mood="", palette="", motifs="",
                  extra="", quality="medium", model="gpt-image-2"):
    """Prepare an inspectable request. No API call happens here."""
    if role not in ALLOWED_ROLES:
        raise ValueError("Choose cover or illustration.")
    if quality not in ALLOWED_QUALITIES or not model.strip():
        raise ValueError("Choose a valid model and quality.")
    selected_ids = list(selected_ids)
    if not 1 <= len(selected_ids) <= 3 or len(set(selected_ids)) != len(selected_ids):
        raise ValueError("Choose one to three distinct references.")
    lookup = {item["id"]: item for item in items}
    if any(item_id not in lookup for item_id in selected_ids):
        raise ValueError("A selected reference is absent from this corpus.")
    selected = [lookup[item_id] for item_id in selected_ids]
    width, height = PRESETS[role]
    references = [{key: item[key] for key in
                   ("id", "title", "artist", "file", "path", "sha256", "source_url",
                    "license", "license_url", "tags")} for item in selected]
    reference_notes = "\n".join(
        f"- Reference {index}: {item['title']}; visual features: {', '.join(item['tags'])}."
        for index, item in enumerate(selected, start=1)
    )
    prompt = (
        f"Create a new, visually appealing {role} image at {width}x{height}. "
        "This is an aesthetic image for a WeChat article; it does not need to depict or explain the article text.\n\n"
        "Use the attached historical images as visual references for line rhythm, ornament, "
        "palette, and composition. Create a distinct new arrangement. Do not reproduce a "
        "reference image, its lettering, signature, brand name, or exact figure. "
        "Do not include any visible text, logos, watermarks, or borders from the source images.\n\n"
        f"Reference notes:\n{reference_notes}\n\n"
        f"Desired mood: {mood.strip() or 'elegant and inviting'}\n"
        f"Palette: {palette.strip() or 'harmonious muted colors'}\n"
        f"Preferred motifs: {motifs.strip() or 'floral curves and decorative linework'}\n"
        f"Additional direction: {extra.strip() or 'none'}\n"
        "Keep the image attractive at thumbnail size and leave enough visual breathing room."
    )
    request = {
        "pilot": "pilot2", "role": role, "prompt": prompt,
        "settings": {"model": model, "size": f"{width}x{height}",
                     "quality": quality, "output_format": "png", "n": 1},
        "references": references,
    }
    request["review_token"] = hashlib.sha256(
        json.dumps(request, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return request


def generate_from_references(request, *, approved_token, output_dir, client=None):
    """Make one approved image edit call and retain its provenance and status."""
    current = deepcopy({key: value for key, value in request.items() if key != "review_token"})
    token = hashlib.sha256(json.dumps(current, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    if token != approved_token or request.get("review_token") != token:
        raise ValueError("The request changed after preview. Review it again.")
    for item in request["references"]:
        if _sha256(item["path"]) != item["sha256"]:
            raise ValueError("A reference changed after preview. Review the request again.")
    folder = new_attempt(output_dir)
    write_json(folder / "request.json", request)
    (folder / "prompt.md").write_text(request["prompt"], encoding="utf-8")
    record = {"status": "requested", "request": "request.json", "folder": str(folder)}
    write_json(folder / "response.json", record)
    owned = client is None
    try:
        if owned:
            from openai import OpenAI
            client = OpenAI(max_retries=0, timeout=600.0)
        with ExitStack() as stack:
            images = [stack.enter_context(open(item["path"], "rb")) for item in request["references"]]
            response = client.images.edit(image=images, prompt=request["prompt"], **request["settings"])
        if not response.data or not response.data[0].b64_json:
            raise ValueError("The image API returned no image.")
        image_bytes = base64.b64decode(response.data[0].b64_json, validate=True)
        if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("The image API did not return a PNG.")
        image_path = folder / "image.png"
        image_path.write_bytes(image_bytes)
        usage = getattr(response, "usage", None)
        record.update(status="generated", image_path=str(image_path.resolve()),
                      sha256=hashlib.sha256(image_bytes).hexdigest(),
                      request_id=getattr(response, "_request_id", None),
                      usage=usage.model_dump(mode="json") if usage else None)
        write_json(folder / "response.json", record)
        return record
    except KeyboardInterrupt:
        record.update(status="interrupted", error_type="KeyboardInterrupt", remote_outcome="unknown")
        write_json(folder / "response.json", record)
        raise
    except Exception as exc:
        record.update(status="failed", error_type=type(exc).__name__)
        write_json(folder / "response.json", record)
        raise
    finally:
        if owned and client is not None:
            client.close()
