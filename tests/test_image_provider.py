import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from PIL import Image

from corpus_atelier.providers.image import OpenAIImageProvider


class _FakeImages:
    def __init__(self, encoded_png: str):
        self.encoded_png = encoded_png
        self.edit_files = []
        self.generate_calls = 0

    def edit(self, *, image, **request):
        self.edit_files = [item.name for item in image]
        return SimpleNamespace(
            data=[SimpleNamespace(b64_json=self.encoded_png, revised_prompt=None)],
            usage=None, _request_id="image-edit-test",
        )

    def generate(self, **request):
        self.generate_calls += 1
        raise AssertionError("Reference generation must use images.edit.")


class ImageProviderTests(unittest.TestCase):
    def test_reference_generation_uses_edit_with_selected_images(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.jpg"
            Image.new("RGB", (8, 8), "gold").save(reference)
            rendered = root / "rendered.png"
            Image.new("RGB", (8, 8), "white").save(rendered)
            encoded = base64.b64encode(rendered.read_bytes()).decode("ascii")
            images = _FakeImages(encoded)
            client = SimpleNamespace(images=images)
            output = root / "output"
            output.mkdir()

            response = OpenAIImageProvider(client=client).generate(
                "Create a new poster.", size="1024x1536", output=output,
                reference_paths=[reference],
            )

            self.assertEqual(images.edit_files, [str(reference)])
            self.assertEqual(images.generate_calls, 0)
            self.assertEqual(response["status"], "generated")
            request = json.loads(
                (output / "request.json").read_text(encoding="utf-8"))
            self.assertEqual(request["operation"], "reference_generation")
            self.assertEqual(len(request["references"]), 1)


if __name__ == "__main__":
    unittest.main()
