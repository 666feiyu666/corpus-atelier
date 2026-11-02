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
        self.edit_masks = []
        self.generate_calls = 0

    def edit(self, *, image, mask=None, **request):
        self.edit_files = [item.name for item in image]
        self.edit_masks = [mask.name] if mask is not None else []
        return SimpleNamespace(
            data=[SimpleNamespace(b64_json=self.encoded_png, revised_prompt=None)],
            usage=None, _request_id="image-edit-test",
        )

    def generate(self, **request):
        self.generate_calls += 1
        return SimpleNamespace(
            data=[SimpleNamespace(b64_json=self.encoded_png, revised_prompt=None)],
            usage=None, _request_id="image-gen-test",
        )


class _Fixture:
    def __init__(self):
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.rendered = self.root / "rendered.png"
        Image.new("RGB", (8, 8), "white").save(self.rendered)
        self.encoded = base64.b64encode(self.rendered.read_bytes()).decode("ascii")
        self.client = SimpleNamespace(images=_FakeImages(self.encoded))
        self.provider = OpenAIImageProvider(client=self.client)

    def image(self, name: str, color: str = "gold") -> Path:
        path = self.root / name
        Image.new("RGB", (8, 8), color).save(path)
        return path

    def mask(self, name: str = "mask.png") -> Path:
        path = self.root / name
        Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(path)
        return path

    def close(self):
        self.directory.cleanup()


class ImageProviderTests(unittest.TestCase):
    def test_reference_generation_uses_edit_with_selected_images(self):
        fixture = _Fixture()
        try:
            reference = fixture.image("reference.jpg")
            output = fixture.root / "output"
            output.mkdir()
            preview = fixture.provider.describe_request(
                "Create a new poster.", size="1024x1536",
                reference_paths=[reference],
            )
            response = fixture.provider.generate(
                "Create a new poster.", size="1024x1536", output=output,
                reference_paths=[reference],
            )
            self.assertEqual(fixture.client.images.edit_files, [str(reference)])
            self.assertEqual(fixture.client.images.generate_calls, 0)
            self.assertEqual(response["status"], "generated")
            request = json.loads(
                (output / "request.json").read_text(encoding="utf-8"))
            self.assertEqual(request, preview)
            self.assertEqual(request["operation"], "reference_generation")
            self.assertEqual(len(request["references"]), 1)
        finally:
            fixture.close()

    def test_multi_reference_edit(self):
        fixture = _Fixture()
        try:
            first = fixture.image("first.jpg", "red")
            second = fixture.image("second.jpg", "blue")
            output = fixture.root / "output"
            output.mkdir()
            preview = fixture.provider.describe_request(
                "Combine both.", size="1024x1536",
                reference_paths=[first, second],
            )
            fixture.provider.generate(
                "Combine both.", size="1024x1536", output=output,
                reference_paths=[first, second],
            )
            self.assertEqual(
                fixture.client.images.edit_files, [str(first), str(second)],
            )
            self.assertEqual(preview["operation"], "reference_generation")
            self.assertEqual(len(preview["references"]), 2)
        finally:
            fixture.close()

    def test_mask_inpainting_uses_edit_with_mask(self):
        fixture = _Fixture()
        try:
            photo = fixture.image("photo.jpg")
            mask = fixture.mask()
            output = fixture.root / "output"
            output.mkdir()
            preview = fixture.provider.describe_request(
                "Replace the sky.", size="1024x1536",
                reference_paths=[photo], mask_path=mask,
            )
            fixture.provider.generate(
                "Replace the sky.", size="1024x1536", output=output,
                reference_paths=[photo], mask_path=mask,
            )
            self.assertEqual(fixture.client.images.edit_files, [str(photo)])
            self.assertEqual(fixture.client.images.edit_masks, [str(mask)])
            self.assertEqual(preview["operation"], "mask_edit")
            self.assertEqual(preview["mask"]["file"], "mask.png")
            self.assertEqual(len(preview["mask"]["sha256"]), 64)
        finally:
            fixture.close()

    def test_mask_requires_exactly_one_reference(self):
        fixture = _Fixture()
        try:
            with self.assertRaises(ValueError):
                fixture.provider.describe_request(
                    "p", size="1024x1536", mask_path=fixture.mask(),
                )
            with self.assertRaises(ValueError):
                fixture.provider.describe_request(
                    "p", size="1024x1536",
                    reference_paths=[fixture.image("a.jpg"), fixture.image("b.jpg")],
                    mask_path=fixture.mask(),
                )
        finally:
            fixture.close()

    def test_more_than_three_references_rejected(self):
        fixture = _Fixture()
        try:
            refs = [fixture.image(f"{i}.jpg") for i in range(4)]
            with self.assertRaises(ValueError):
                fixture.provider.describe_request(
                    "p", size="1024x1536", reference_paths=refs,
                )
        finally:
            fixture.close()

    def test_format_and_background_are_persisted(self):
        fixture = _Fixture()
        try:
            provider = OpenAIImageProvider(
                client=fixture.client, format="webp", background="transparent",
            )
            output = fixture.root / "output"
            output.mkdir()
            provider.generate("p", size="1024x1536", output=output)
            request = json.loads(
                (output / "request.json").read_text(encoding="utf-8"))
            self.assertEqual(request["output_format"], "webp")
            self.assertEqual(request["background"], "transparent")
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main()
