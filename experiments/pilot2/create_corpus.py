"""Create the local-only Mucha reference corpus from verified CMA CC0 records."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image


ROOT = Path(__file__).resolve().parent / "corpus"
API = "https://openaccess-api.clevelandart.org/api/artworks/"
LICENSE_URL = "https://www.clevelandart.org/open-access"

# Pinned records keep the pilot curated rather than turning it into a crawler.
SELECTION = {
    144596: ["floral", "ornament", "poppies", "pink", "green", "花卉", "装饰"],
    144595: ["floral", "ornament", "poppies", "cream", "teal", "花卉", "装饰"],
    147115: ["figure", "poster", "border", "olive", "gold", "人物", "海报"],
    144597: ["floral", "ornament", "sweet peas", "blue", "pink", "花卉", "装饰"],
    144598: ["floral", "ornament", "pattern", "purple", "green", "花卉", "图案"],
    156752: ["floral", "ornament", "panel", "pink", "blue", "花卉", "装饰"],
    148901: ["figure", "illustration", "border", "gold", "人物", "插画"],
}


def fetch(url):
    request = Request(url, headers={"User-Agent": "graphic-design-helper-pilot2/0.1"})
    with urlopen(request, timeout=45) as response:
        return response.read()


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    image_dir = ROOT / "images"
    image_dir.mkdir(exist_ok=True)
    items = []
    for artwork_id, tags in SELECTION.items():
        record = json.loads(fetch(API + str(artwork_id)))["data"]
        creators = " ".join(row.get("description", "") for row in record.get("creators", []))
        if record.get("share_license_status") != "CC0" or "Mucha" not in creators:
            raise ValueError(f"Artwork {artwork_id} no longer has the expected artist and CC0 status.")
        image = record.get("images", {}).get("web")
        if not image or not image.get("url"):
            raise ValueError(f"Artwork {artwork_id} has no open-access image.")
        target = image_dir / f"{record['accession_number']}.jpg"
        if not target.exists():
            temporary = target.with_suffix(".download")
            try:
                temporary.write_bytes(fetch(image["url"]))
                with Image.open(temporary) as opened:
                    opened.verify()
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        with Image.open(target) as opened:
            opened.verify()
        items.append({
            "id": str(artwork_id), "title": record["title"],
            "artist": "Alphonse Mucha", "accession_number": record["accession_number"],
            "file": f"images/{target.name}", "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "source_url": record["url"], "image_url": image["url"],
            "license": "CC0", "license_url": LICENSE_URL, "tags": tags,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        })
        print(f"Verified {record['accession_number']}: {record['title']}")
    manifest = {"version": 1, "name": "Mucha pilot2 local corpus", "items": items}
    temporary = ROOT / "manifest.tmp"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(ROOT / "manifest.json")
    print(f"Saved {len(items)} local references to {ROOT}")


if __name__ == "__main__":
    main()
