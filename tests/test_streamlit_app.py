import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image
from streamlit.testing.v1 import AppTest

from corpus_atelier.streamlit_app import load_case, parse_brief, review_points
from corpus_atelier.state import RunResult


ROOT = Path(__file__).resolve().parents[1]


class FakeUiApplication:
    """Small session-state fake used to exercise Streamlit page transitions."""

    def __init__(self, run_dir: Path, artifacts: dict[str, str]):
        self.run_dir = run_dir
        self.artifacts = artifacts

    def resume(self, run_id, decision):
        if hasattr(decision, "approved"):
            status = "awaiting_revision" if decision.approved else "rejected"
        else:
            status = "completed" if decision.action == "accept" else "discarded"
        return RunResult(
            run_id=run_id, status=status, run_dir=self.run_dir,
            message=status, artifacts=self.artifacts,
        )


class StreamlitAppTests(unittest.TestCase):
    def test_bundled_cases_are_available_to_the_page(self):
        poster = load_case("工作坊海报")
        cover = load_case("文章封面")
        self.assertEqual(poster["topic"], "Corpus Atelier")
        self.assertEqual(cover["article_title"], "从语料到视觉修辞")

    def test_brief_editor_requires_a_json_object(self):
        self.assertEqual(parse_brief('{"topic": "x"}'), {"topic": "x"})
        with self.assertRaisesRegex(ValueError, "JSON 对象"):
            parse_brief("[]")

    def test_review_points_hide_internal_review_structure(self):
        review = {
            "observations": ["Title is legible."],
            "priority_actions": ["Increase spacing."],
            "interpretations": ["Internal interpretation."],
        }
        self.assertEqual(
            review_points(review), ["Title is legible.", "Increase spacing."],
        )

    def test_streamlit_source_does_not_expose_protocol_details(self):
        source = ROOT / "src/corpus_atelier/streamlit_app.py"
        text = source.read_text(encoding="utf-8")
        for term in ("generation_digest", "max_revisions", "forbidden_changes"):
            self.assertNotIn(term, text)

    def test_initial_page_renders_and_switches_examples(self):
        app = AppTest.from_file(
            str(ROOT / "src/corpus_atelier/streamlit_app.py"), default_timeout=10,
        ).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.title[0].value, "Corpus Atelier")
        app.selectbox[0].select("文章封面").run()
        self.assertFalse(app.exception)
        self.assertIn("从语料到视觉修辞", app.text_area[0].value)

    def test_reference_example_defaults_to_one_and_offers_up_to_three(self):
        app = AppTest.from_file(
            str(ROOT / "src/corpus_atelier/streamlit_app.py"), default_timeout=10,
        ).run()
        app.selectbox[0].select("慕夏风格女士手表广告").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.segmented_control), 1)
        self.assertEqual(app.segmented_control[0].value, 1)
        self.assertEqual(app.segmented_control[0].options, ["1", "2", "3"])

    def test_approval_acceptance_flow_renders_each_page_state(self):
        with TemporaryDirectory() as directory:
            run_dir = Path(directory)
            proposal = run_dir / "proposal.json"
            proposal.write_text(json.dumps({
                "chosen_direction": "A restrained editorial composition.",
                "design_rationale": "Clear hierarchy for a small screen.",
            }), encoding="utf-8")
            review = run_dir / "review.json"
            review.write_text(json.dumps({
                "verdict": "accept", "observations": ["The title is legible."],
                "priority_actions": [],
            }), encoding="utf-8")
            image = run_dir / "image.png"
            Image.new("RGB", (12, 18), "white").save(image)
            artifacts = {
                "proposal": str(proposal), "review": str(review), "image": str(image),
            }
            result = RunResult(
                run_id="ui-test", status="awaiting_approval", run_dir=run_dir,
                message="awaiting approval", artifacts=artifacts,
            )
            app = AppTest.from_file(
                str(ROOT / "src/corpus_atelier/streamlit_app.py"), default_timeout=10,
            )
            app.session_state["atelier_app"] = FakeUiApplication(run_dir, artifacts)
            app.session_state["result"] = result
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(app.subheader[0].value, "设计方案")

            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.subheader[0].value, "查看设计")

            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.subheader[0].value, "当前设计已接受")
