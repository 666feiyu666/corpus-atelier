"""The practical pilot keeps local references traceable and calls opt-in."""

import base64
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from PIL import Image

from graphic_design_helper.reference_generation import (
    build_request, generate_from_references, load_corpus, search_corpus,
)


def png_bytes():
    output = BytesIO()
    Image.new("RGB", (16, 16), "pink").save(output, format="PNG")
    return output.getvalue()


class Pilot2Tests(unittest.TestCase):
    def make_corpus(self, root):
        image_path = Path(root) / "images" / "reference.png"
        image_path.parent.mkdir()
        image_path.write_bytes(png_bytes())
        import hashlib
        item = {"id": "one", "title": "Ornament", "artist": "Alphonse Mucha",
                "file": "images/reference.png", "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                "source_url": "https://example.org/art/one", "license": "CC0",
                "license_url": "https://example.org/rights", "tags": ["floral", "花卉"]}
        (Path(root) / "manifest.json").write_text(
            json.dumps({"version": 1, "items": [item]}), encoding="utf-8")
        return image_path

    def test_local_corpus_verifies_image_and_rights(self):
        with TemporaryDirectory() as root:
            image_path = self.make_corpus(root)
            items = load_corpus(root)
            self.assertEqual([item["id"] for item in search_corpus(items, "花卉")], ["one"])
            image_path.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                load_corpus(root)

    def test_preview_token_and_reference_hash_guard_generation(self):
        with TemporaryDirectory() as root:
            image_path = self.make_corpus(root)
            items = load_corpus(root)
            request = build_request(items, ["one"], role="cover", mood="quiet")
            calls = []

            def edit(**kwargs):
                calls.append(kwargs)
                return SimpleNamespace(data=[SimpleNamespace(
                    b64_json=base64.b64encode(png_bytes()).decode("ascii"))])

            client = SimpleNamespace(images=SimpleNamespace(edit=edit))
            with self.assertRaises(ValueError):
                generate_from_references(request, approved_token="wrong",
                                         output_dir=Path(root) / "outputs", client=client)
            self.assertFalse(calls)
            result = generate_from_references(
                request, approved_token=request["review_token"],
                output_dir=Path(root) / "outputs", client=client)
            self.assertEqual(result["status"], "generated")
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(calls[0]["image"]), 1)
            self.assertEqual(calls[0]["size"], "1280x544")
            self.assertTrue(Path(result["image_path"]).is_file())
            self.assertEqual(json.loads((Path(result["folder"]) / "request.json").read_text())["references"][0]["id"], "one")
            image_path.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                generate_from_references(request, approved_token=request["review_token"],
                                         output_dir=Path(root) / "outputs", client=client)
            self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
