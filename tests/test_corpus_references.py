"""Corpus references at the direction stage: prompt wiring, plan record, retrieval."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from corpus_atelier.app.registry import get_profile
from corpus_atelier.app.service import CorpusAtelierApplication
from corpus_atelier.app.state import NaturalLanguageDesignJob
from corpus_atelier.atelier.design_direction.prompt_compiler import (
    compile_design_direction_prompt,
)
from corpus_atelier.atelier.design_direction.synthesis import (
    synthesize_design_directions,
)
from corpus_atelier.corpus.index import CorpusStore
from corpus_atelier.corpus.records import new_record
from tests.fakes import FakeImageProvider, FakeTextProvider


CANVAS = {"size": "1024x1536", "ratio": [2, 3]}
BRIEF = {"topic": "读书会海报", "exact_copy": ["读书会"], "constraints": []}
REFERENCE = {
    "id": "gallery-no-048",
    "prompt": "Teal watercolor poster of a lily pond.",
    "tags": ["gallery-watercolor", "painterly"],
    "note": "No. 48 · Watercolor pond",
    "url": "https://example.com/case",
}


class RecordingProvider:
    """Captures the direction request instead of calling a model."""

    model = "recording"

    def __init__(self):
        self.calls = []

    def propose(self, prompt, *, schema_name, reference_paths=None):
        self.calls.append({
            "prompt": prompt,
            "reference_paths": list(reference_paths or []),
            "schema_name": schema_name,
        })
        return {"planning_mode": "convergent", "directions": []}, {"status": "completed"}


class DirectionPromptTests(unittest.TestCase):
    def setUp(self):
        self.profile = get_profile("rhetoric-graphic")

    def test_prompt_carries_the_reference_slice_and_image_listing(self):
        prompt = compile_design_direction_prompt(
            self.profile, BRIEF, canvas=CANVAS, candidate_limit=2,
            corpus_references=[REFERENCE],
            reference_image_names=["case.png"],
        )
        self.assertIn("# Reference gallery slice", prompt)
        self.assertIn("gallery-no-048", prompt)
        self.assertIn("# Attached reference images", prompt)
        self.assertIn("1. case.png", prompt)

    def test_prompt_without_references_stays_plain(self):
        prompt = compile_design_direction_prompt(
            self.profile, BRIEF, canvas=CANVAS, candidate_limit=1,
        )
        self.assertNotIn("# Reference gallery slice", prompt)
        self.assertNotIn("# Attached reference images", prompt)

    def test_synthesis_attaches_reference_images(self):
        with TemporaryDirectory() as directory:
            image = Path(directory) / "case.png"
            Image.new("RGB", (32, 32), (10, 20, 30)).save(image, format="PNG")
            provider = RecordingProvider()
            synthesize_design_directions(
                self.profile, BRIEF, provider, canvas=CANVAS, candidate_limit=2,
                corpus_references=[REFERENCE], reference_paths=[image],
            )
        call = provider.calls[0]
        self.assertEqual(call["schema_name"], "design-direction-plan.schema.json")
        self.assertEqual(call["reference_paths"], [image])
        self.assertIn("# Reference gallery slice", call["prompt"])


class DirectionPlanRecordTests(unittest.TestCase):
    def test_plan_records_the_cases_and_images_it_used(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "media"
            image_path = media / "case" / "tea-poster.png"
            image_path.parent.mkdir(parents=True)
            Image.new("RGB", (32, 48), (90, 60, 30)).save(image_path, format="PNG")
            db = root / "corpus.sqlite3"
            store = CorpusStore(db)
            try:
                store.add(new_record(
                    prompt="Tea poster case with warm paper and dense copy.",
                    tags=["poster", "warm"],
                    source_kind="import",
                    image={"path": "case/tea-poster.png"},
                    source_note="No. 48 · Tea poster",
                    source_url="https://example.com/case",
                ))
            finally:
                store.close()
            app = CorpusAtelierApplication(
                runs_root=root / "tasks",
                corpus_db_path=db,
                corpus_media_root=media,
                text_provider=FakeTextProvider(),
                image_provider=FakeImageProvider(),
            )
            try:
                result = app.start_request(NaturalLanguageDesignJob(
                    case_id="natural-language", profile="rhetoric-poster",
                    request="设计一张读书会海报。", candidate_count=2,
                ))
                plan = json.loads(
                    (result.run_dir / "design-direction" / "plan.json")
                    .read_text(encoding="utf-8")
                )
            finally:
                app.close()

        self.assertEqual(len(plan["corpus_references"]), 1)
        self.assertEqual(plan["corpus_references"][0]["note"], "No. 48 · Tea poster")
        self.assertEqual(plan["corpus_reference_images"], ["case/tea-poster.png"])
        # The prompt evidence must not carry local filesystem paths.
        self.assertNotIn("case/tea-poster.png", json.dumps(plan["corpus_references"]))


class RetrievalFallbackTests(unittest.TestCase):
    def test_a_too_specific_query_falls_back_to_any_term(self):
        with TemporaryDirectory() as directory:
            store = CorpusStore(Path(directory) / "corpus.sqlite3")
            try:
                store.add(new_record(
                    prompt="Tea poster case with warm paper.",
                    tags=["poster", "warm"],
                    source_kind="import",
                ))
                strict = store.search("A complete poster topic")
                fallback = store.reference_slice("A complete poster topic")
            finally:
                store.close()
        self.assertEqual(strict, [])
        self.assertEqual(len(fallback), 1)


class CollectionBridgeTests(unittest.TestCase):
    def _runtime(self, directory: Path):
        from corpus_atelier.app.workflow.runtime import WorkflowRuntime
        from corpus_atelier.artifacts.store import ArtifactStore

        return WorkflowRuntime(
            ArtifactStore(directory / "tasks"),
            FakeTextProvider(),
            FakeImageProvider(),
            corpus_db_path=directory / "corpus.sqlite3",
            corpus_media_root=directory / "media",
        )

    def test_unknown_categories_have_no_collection(self):
        with TemporaryDirectory() as directory:
            runtime = self._runtime(Path(directory))
        self.assertEqual(
            runtime._gallery_collection("typography-and-posters"),
            "gallery-typography-and-posters",
        )
        self.assertIsNone(runtime._gallery_collection("not-a-category"))
        self.assertIsNone(runtime._gallery_collection(None))

    def test_a_foreign_language_brief_falls_back_to_its_collection(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = CorpusStore(root / "corpus.sqlite3")
            try:
                store.add(new_record(
                    prompt="Swiss grid poster with a single headline.",
                    tags=["gallery-typography-and-posters", "typographic"],
                    source_kind="import",
                    source_note="No. 33 · Swiss poster",
                ))
            finally:
                store.close()
            runtime = self._runtime(root)
            references = runtime._corpus_references({
                "brief": {
                    "deliverable": "国庆花艺海报",
                    "asset_category": "typography-and-posters",
                },
            })
        self.assertEqual(len(references), 1)
        self.assertEqual(references[0]["note"], "No. 33 · Swiss poster")


if __name__ == "__main__":
    unittest.main()
