"""Direct-generation route, corpus reference slice, and editing inputs."""

import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from corpus_atelier.app.service import CorpusAtelierApplication
from corpus_atelier.corpus.index import CorpusStore
from corpus_atelier.corpus.records import new_record
from corpus_atelier.app.state import HumanDecision, NaturalLanguageDesignJob
from tests.fakes import FakeImageProvider, FakeTextProvider


REQUEST = "设计一张桌面壁纸，用轻松的方式提醒同事离开工位时锁屏。"
COPY = ["都看到这里了，就顺手帮我锁个屏吧"]
ARCHIVED = "Lock screen wallpaper with gentle workplace humor and a poster layout."


def png_bytes(mode="RGB", color=(10, 20, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, (8, 8), color).save(buffer, format="PNG")
    return buffer.getvalue()


class RoutedTextProvider(FakeTextProvider):
    """Writes an explicit route and corpus-friendly wording into the brief."""

    def __init__(self, route=None):
        super().__init__()
        self.route = route

    def propose(self, prompt, *, schema_name, reference_paths=None):
        value, response = super().propose(
            prompt, schema_name=schema_name, reference_paths=reference_paths,
        )
        if schema_name.endswith("-brief.schema.json"):
            if "deliverable" in value:
                value.update(
                    deliverable="Lock screen wallpaper",
                    preferences=["gentle workplace humor"],
                )
            if self.route:
                value.update(
                    execution_route=self.route,
                    route_reason="Route chosen by the test fixture.",
                )
        return value, response


class GenerationRouteTests(unittest.TestCase):
    def app(self, directory, text=None, image=None, corpus_db_path=None):
        return CorpusAtelierApplication(
            runs_root=Path(directory) / "tasks",
            checkpoint_path=":memory:",
            text_provider=text or FakeTextProvider(),
            image_provider=image or FakeImageProvider(),
            corpus_db_path=corpus_db_path,
        )

    @staticmethod
    def candidates(result):
        return json.loads(
            Path(result.artifacts["candidate_index"]).read_text(encoding="utf-8")
        )

    def test_direct_mode_skips_direction_and_proposal(self):
        with TemporaryDirectory() as directory:
            text = FakeTextProvider()
            with self.app(directory, text=text) as app:
                result = app.start_request(NaturalLanguageDesignJob(
                    case_id="direct", profile="rhetoric-graphic",
                    request=REQUEST, generation_mode="direct",
                ))
                self.assertEqual(result.status, "awaiting_approval")
                self.assertEqual(
                    [call["schema_name"] for call in text.design_calls],
                    ["graphic-design-brief.schema.json", "image-prompt.schema.json"],
                )
                self.assertNotIn("proposal", result.artifacts)
                self.assertIn("image_prompt", result.artifacts)
                candidate = self.candidates(result)[0]
                self.assertIsNone(candidate["proposal"])
                self.assertEqual(candidate["image_prompt"]["exact_copy"], COPY)
                self.assertTrue(candidate["image_prompt"]["visual_qa"])
                prompt = Path(result.artifacts["generation_prompt"]).read_text(encoding="utf-8")
                self.assertNotIn("Negative prompt", prompt)
                self.assertNotIn("{", prompt)

                result = app.resume(result.run_id, HumanDecision(True))
                self.assertEqual(result.status, "awaiting_selection")

    def test_auto_mode_follows_a_direct_brief_route(self):
        with TemporaryDirectory() as directory:
            text = RoutedTextProvider(route="direct")
            with self.app(directory, text=text) as app:
                result = app.start_request(NaturalLanguageDesignJob(
                    case_id="auto-direct", profile="rhetoric-graphic", request=REQUEST,
                ))
                self.assertEqual(result.status, "awaiting_approval")
                self.assertEqual(
                    [call["schema_name"] for call in text.design_calls],
                    ["graphic-design-brief.schema.json", "image-prompt.schema.json"],
                )
                self.assertIsNone(self.candidates(result)[0]["proposal"])

    def test_explicit_staged_mode_overrides_a_direct_brief_route(self):
        with TemporaryDirectory() as directory:
            text = RoutedTextProvider(route="direct")
            with self.app(directory, text=text) as app:
                result = app.start_request(NaturalLanguageDesignJob(
                    case_id="staged", profile="rhetoric-graphic",
                    request=REQUEST, generation_mode="staged",
                ))
                self.assertEqual(result.status, "awaiting_approval")
                self.assertIn(
                    "design-direction-plan.schema.json",
                    [call["schema_name"] for call in text.design_calls],
                )
                self.assertIsNotNone(self.candidates(result)[0]["proposal"])

    def test_brief_without_a_route_stays_staged(self):
        with TemporaryDirectory() as directory:
            text = FakeTextProvider()
            with self.app(directory, text=text) as app:
                result = app.start_request(NaturalLanguageDesignJob(
                    case_id="auto-staged", profile="rhetoric-graphic", request=REQUEST,
                ))
                self.assertEqual(result.status, "awaiting_approval")
                self.assertIn(
                    "design-direction-plan.schema.json",
                    [call["schema_name"] for call in text.design_calls],
                )

    def test_archived_prompts_are_injected_as_advisory_references(self):
        with TemporaryDirectory() as directory:
            db = Path(directory) / "corpus.sqlite3"
            store = CorpusStore(db)
            try:
                record = new_record(
                    prompt=ARCHIVED, tags=["poster"], source_kind="manual",
                )
                store.add(record)
            finally:
                store.close()
            text = RoutedTextProvider()
            with self.app(directory, text=text, corpus_db_path=db) as app:
                result = app.start_request(NaturalLanguageDesignJob(
                    case_id="corpus-reference", profile="rhetoric-graphic",
                    request=REQUEST,
                ))
                self.assertEqual(result.status, "awaiting_approval")
                candidate = self.candidates(result)[0]
                self.assertEqual(candidate["corpus_references"], [record["id"]])
                self.assertTrue(
                    (result.run_dir / "candidates/c01/image-prompt/references.json").is_file()
                )
                compiler_prompt = next(
                    call["prompt"] for call in text.design_calls
                    if call["schema_name"] == "image-prompt.schema.json"
                )
                self.assertIn("# Reference gallery slice", compiler_prompt)
                self.assertIn(ARCHIVED, compiler_prompt)

    def test_empty_corpus_leaves_the_prompt_unchanged(self):
        with TemporaryDirectory() as directory:
            db = Path(directory) / "corpus.sqlite3"
            CorpusStore(db).close()
            text = RoutedTextProvider()
            with self.app(directory, text=text, corpus_db_path=db) as app:
                result = app.start_request(NaturalLanguageDesignJob(
                    case_id="empty-corpus", profile="rhetoric-graphic", request=REQUEST,
                ))
                self.assertEqual(self.candidates(result)[0]["corpus_references"], [])
                compiler_prompt = next(
                    call["prompt"] for call in text.design_calls
                    if call["schema_name"] == "image-prompt.schema.json"
                )
                self.assertNotIn("# Reference gallery slice", compiler_prompt)

    def test_reference_image_and_mask_reach_the_provider(self):
        with TemporaryDirectory() as directory:
            image = FakeImageProvider()
            text = FakeTextProvider()
            with self.app(directory, text=text, image=image) as app:
                result = app.start_request(NaturalLanguageDesignJob(
                    case_id="edit", profile="rhetoric-graphic", request=REQUEST,
                    reference_images=(("base.png", png_bytes()),),
                    mask=("mask.png", png_bytes("RGBA", (0, 0, 0, 255))),
                ))
                self.assertEqual(result.status, "awaiting_approval")
                preview = json.loads(Path(
                    result.artifacts["generation_request_preview"]
                ).read_text(encoding="utf-8"))
                self.assertEqual(preview["operation"], "mask_edit")
                self.assertEqual(preview["references"][0]["file"], "1.png")
                self.assertEqual(preview["mask"]["file"], "mask.png")
                compiler_prompt = next(
                    call["prompt"] for call in text.design_calls
                    if call["schema_name"] == "image-prompt.schema.json"
                )
                self.assertIn("# Edit and inpaint invariants", compiler_prompt)

                result = app.resume(result.run_id, HumanDecision(True))
                self.assertEqual(result.status, "awaiting_selection")
                self.assertIsNotNone(image.mask_path)
                self.assertEqual(len(image.reference_paths), 1)

    def test_mask_requires_exactly_one_reference_image(self):
        with TemporaryDirectory() as directory:
            with self.app(directory) as app:
                with self.assertRaisesRegex(ValueError, "exactly one reference"):
                    app.create_request(NaturalLanguageDesignJob(
                        case_id="bad-mask", profile="rhetoric-graphic", request=REQUEST,
                        reference_images=(("a.png", png_bytes()), ("b.png", png_bytes())),
                        mask=("mask.png", png_bytes("RGBA", (0, 0, 0, 255))),
                    ))
                with self.assertRaisesRegex(ValueError, "exactly one reference"):
                    app.create_request(NaturalLanguageDesignJob(
                        case_id="bad-mask-2", profile="rhetoric-graphic", request=REQUEST,
                        mask=("mask.png", png_bytes("RGBA", (0, 0, 0, 255))),
                    ))

    def test_mask_must_be_a_png_with_alpha(self):
        with TemporaryDirectory() as directory:
            with self.app(directory) as app:
                with self.assertRaisesRegex(ValueError, "alpha channel"):
                    app.create_request(NaturalLanguageDesignJob(
                        case_id="bad-mask-format", profile="rhetoric-graphic",
                        request=REQUEST,
                        reference_images=(("a.png", png_bytes()),),
                        mask=("mask.png", png_bytes()),
                    ))

    def test_at_most_three_reference_images(self):
        with TemporaryDirectory() as directory:
            with self.app(directory) as app:
                with self.assertRaisesRegex(ValueError, "at most three"):
                    app.create_request(NaturalLanguageDesignJob(
                        case_id="too-many", profile="rhetoric-graphic", request=REQUEST,
                        reference_images=tuple(
                            (f"{index}.png", png_bytes()) for index in range(4)
                        ),
                    ))


if __name__ == "__main__":
    unittest.main()
