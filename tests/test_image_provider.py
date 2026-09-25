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
        self.edit_calls = 0
        self.generate_calls = 0

    def edit(self, *, image, **request):
        self.edit_calls += 1
        raise AssertionError("The generation provider must not receive reference images.")

    def generate(self, **request):
        self.generate_calls += 1
        return SimpleNamespace(
            data=[SimpleNamespace(b64_json=self.encoded_png, revised_prompt=None)],
            usage=None, _request_id="image-generation-test",
        )


class ImageProviderTests(unittest.TestCase):
    def test_generation_provider_uses_text_only_generate_endpoint(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            rendered = root / "rendered.png"
            Image.new("RGB", (8, 8), "white").save(rendered)
            encoded = base64.b64encode(rendered.read_bytes()).decode("ascii")
            images = _FakeImages(encoded)
            client = SimpleNamespace(images=images)
            output = root / "output"
            output.mkdir()

            provider = OpenAIImageProvider(client=client)
            preview = provider.describe_request(
                "Create a new poster.", size="1024x1536",
            )
            response = provider.generate(
                "Create a new poster.", size="1024x1536", output=output,
            )

            self.assertEqual(images.edit_calls, 0)
            self.assertEqual(images.generate_calls, 1)
            self.assertEqual(response["status"], "generated")
            request = json.loads(
                (output / "request.json").read_text(encoding="utf-8"))
            self.assertEqual(request, preview)
            self.assertEqual(request["operation"], "generation")
            self.assertNotIn("references", request)


if __name__ == "__main__":
    unittest.main()
