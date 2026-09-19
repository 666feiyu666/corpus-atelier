"""Build the pinned CC0 starter snapshot from verified CMA Open Access records."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image

API = "https://openaccess-api.clevelandart.org/api/artworks/"
LICENSE_URL = "https://www.clevelandart.org/open-access"
SELECTION = {
    144596: ["floral", "ornament", "poppies", "pink", "green", "花卉", "装饰"],
    144595: ["floral", "ornament", "poppies", "cream", "teal", "花卉", "装饰"],
    147115: ["figure", "poster", "border", "olive", "gold", "人物", "海报"],
    144597: ["floral", "ornament", "sweet peas", "blue", "pink", "花卉", "装饰"],
    144598: ["floral", "ornament", "pattern", "purple", "green", "花卉", "图案"],
    156752: ["floral", "ornament", "panel", "pink", "blue", "花卉", "装饰"],
    148901: ["figure", "illustration", "border", "gold", "人物", "插画"],
}


def _fetch(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "corpus-atelier/0.2"})
    with urlopen(request, timeout=45) as response:
        return response.read()


def build(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    image_dir = root / "images"
    image_dir.mkdir(exist_ok=True)
    rows = []
    for artwork_id, tags in SELECTION.items():
        record = json.loads(_fetch(API + str(artwork_id)))["data"]
        creators = " ".join(row.get("description", "") for row in record.get("creators", []))
        if record.get("share_license_status") != "CC0" or "Mucha" not in creators:
            raise ValueError(f"Artwork {artwork_id} no longer has the expected provenance.")
        image = record.get("images", {}).get("web", {})
        target = image_dir / f"{record['accession_number']}.jpg"
        if not target.exists():
            temporary = target.with_suffix(".download")
            temporary.write_bytes(_fetch(image["url"]))
            with Image.open(temporary) as opened:
                opened.verify()
            temporary.replace(target)
        rows.append({
            "id": str(artwork_id), "title": record["title"], "text": "",
            "tags": tags, "artist": "Alphonse Mucha",
            "accession_number": record["accession_number"],
            "file": f"images/{target.name}",
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "source_url": record["url"], "license": "CC0", "license_url": LICENSE_URL,
        })
    text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
    (root / "references.jsonl").write_text(text, encoding="utf-8")
    manifest = {
        "format_version": 1, "snapshot_id": "mucha-cma-cc0-" + datetime.now(timezone.utc).strftime("%Y%m%d"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "name": "Corpus Atelier starter Atlas snapshot",
        "knowledge_file": "knowledge.jsonl", "references_file": "references.jsonl",
        "source": "Cleveland Museum of Art Open Access", "license": "CC0",
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
