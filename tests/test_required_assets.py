from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image, ImageDraw

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.artifacts.hashing import digest_file
from corpus_atelier.state import DesignJob, HumanDecision, RequiredImage
from tests.fakes import FakeImageProvider, FakeTextProvider


BRIEF = {
    "deliverable": "中秋祝贺海报",
    "purpose": "向研究会成员和公众传达中秋祝福。",
    "audience": "研究会成员、花艺爱好者与公众。",
    "use_context": "在移动社交媒体中观看。",
    "exact_copy": ["中秋快乐"],
    "constraints": ["必须包含上传的研究会 Logo。"],
    "preferences": ["使用广式插花花艺元素。"],
    "canvas": {"aspect_ratio": {"width": 4, "height": 5}},
}


def logo_upload() -> RequiredImage:
    image = Image.new("RGBA", (160, 100), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 25, 129, 74), fill=(12, 112, 74, 255))
    draw.rectangle((55, 38, 104, 61), fill=(240, 196, 72, 255))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return RequiredImage("association-logo.png", buffer.getvalue())


class RequiredAssetTests(unittest.TestCase):
    def _start(self, *, with_corpus=False):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        text = FakeTextProvider()
        image = FakeImageProvider()
        app = CorpusAtelierApplication(
            runs_root=temporary.name, text_provider=text, image_provider=image,
        )
        kwargs = {}
        if with_corpus:
            root = Path(__file__).resolve().parents[1]
            kwargs.update(
                snapshot=root / "experiments/atlas-snapshot/mucha-commercial",
                reference={
                    "format_version": 1,
                    "reference_id": "mucha-poster-124474277",
                },
            )
        result = app.start(DesignJob(
            case_id="required-image",
            profile="rhetoric-graphic",
            brief=BRIEF,
            generation_mode="with_corpus" if with_corpus else "without_corpus",
            required_images=(logo_upload(),),
            **kwargs,
        ))
        return app, text, image, result

    def test_required_image_is_archived_and_planned_before_approval(self):
        _, text, image, result = self._start()
        self.assertEqual(result.status, "awaiting_approval")
        self.assertEqual(image.calls, 0)
        manifest = json.loads(Path(result.artifacts["manifest"]).read_text(encoding="utf-8"))
        asset = manifest["required_assets"][0]
        self.assertEqual(asset["asset_id"], "required-01")
        self.assertEqual(asset["original_filename"], "association-logo.png")
        original = Path(result.artifacts["required_01_original"])
        prepared = Path(result.artifacts["required_01_prepared"])
        self.assertEqual(original.read_bytes(), logo_upload().content)
        self.assertEqual(digest_file(prepared), asset["prepared_sha256"])
        self.assertLess(asset["prepared_size"][0], asset["original_size"][0])
        self.assertIn('"role": "required_exact_image"', text.design_calls[0]["prompt"])
        self.assertEqual(text.design_calls[0]["reference_paths"], [prepared])
        spec = json.loads(Path(result.artifacts["image_spec"]).read_text(encoding="utf-8"))
        self.assertEqual(
            [item["asset_id"] for item in spec["required_asset_placements"]],
            ["required-01"],
        )

    def test_required_image_is_composited_without_being_sent_to_renderer(self):
        app, _, image, result = self._start()
        result = app.resume(result.run_id, HumanDecision(True, reviewer="test"))
        self.assertEqual(result.status, "completed")
        self.assertEqual(image.reference_paths, [])
        self.assertIn("generation_background", result.artifacts)
        self.assertIn("composition", result.artifacts)
        with Image.open(result.artifacts["generation_background"]) as background:
            background_colors = set(background.convert("RGB").get_flattened_data())
        with Image.open(result.artifacts["image"]) as final:
            final_colors = set(final.convert("RGB").get_flattened_data())
        self.assertNotIn((12, 112, 74), background_colors)
        self.assertTrue(any(red < 100 and green > 100 for red, green, _ in final_colors))
        composition = json.loads(
            Path(result.artifacts["composition"]).read_text(encoding="utf-8")
        )
        self.assertEqual(composition["placements"][0]["asset_id"], "required-01")
        self.assertEqual(composition["output_sha256"], digest_file(Path(result.artifacts["image"])))

    def test_corpus_reference_and_required_image_keep_distinct_roles(self):
        app, text, image, result = self._start(with_corpus=True)
        self.assertEqual(len(text.design_calls[0]["reference_paths"]), 2)
        prompt = text.design_calls[0]["prompt"]
        self.assertIn('"role": "required_exact_image"', prompt)
        self.assertIn('"role": "corpus_reference"', prompt)
        result = app.resume(result.run_id, HumanDecision(True, reviewer="test"))
        self.assertEqual(len(image.reference_paths), 1)
        self.assertEqual(
            image.reference_paths[0].resolve(),
            Path(result.artifacts["reference_image"]).resolve(),
        )

    def test_changed_prepared_image_invalidates_approval(self):
        app, _, image, result = self._start()
        prepared = Path(result.artifacts["required_01_prepared"])
        prepared.write_bytes(prepared.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "required image changed"):
            app.resume(result.run_id, HumanDecision(True, reviewer="test"))
        self.assertEqual(image.calls, 0)

    def test_invalid_upload_is_rejected_before_a_run_is_created(self):
        with TemporaryDirectory() as directory:
            app = CorpusAtelierApplication(
                runs_root=directory,
                text_provider=FakeTextProvider(),
                image_provider=FakeImageProvider(),
            )
            with self.assertRaisesRegex(ValueError, "not a valid supported image"):
                app.start(DesignJob(
                    case_id="required-image",
                    profile="rhetoric-graphic",
                    brief=BRIEF,
                    generation_mode="without_corpus",
                    required_images=(RequiredImage("fake.png", b"not an image"),),
                ))
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
