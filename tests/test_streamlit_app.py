import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image
from streamlit.testing.v1 import AppTest

from corpus_atelier.streamlit_app import (
    build_general_brief, load_case, parse_brief, review_points,
)
from corpus_atelier.state import RunResult


ROOT = Path(__file__).resolve().parents[1]


class FakeUiApplication:
    """Small session-state fake used to exercise Streamlit page transitions."""

    def __init__(self, run_dir: Path, artifacts: dict[str, str]):
        self.run_dir = run_dir
        self.artifacts = artifacts

    def resume(self, run_id, decision):
        if hasattr(decision, "approved"):
            status = "awaiting_final_decision" if decision.approved else "rejected"
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

    def test_general_brief_keeps_delivery_context_open(self):
        brief = build_general_brief(
            deliverable="展览导览卡",
            purpose="帮助观众识别展区",
            audience="现场观众",
            use_context="手持阅读并可能低照度观看",
            exact_copy="第一展区\n夜间开放",
            constraints="不可使用荧光色",
            preferences="克制",
            canvas_mode="auto",
        )
        self.assertEqual(brief["deliverable"], "展览导览卡")
        self.assertEqual(brief["exact_copy"], ["第一展区", "夜间开放"])
        self.assertEqual(brief["canvas"], {"mode": "auto"})

    def test_streamlit_source_does_not_expose_protocol_details(self):
        source = ROOT / "src/corpus_atelier/streamlit_app.py"
        text = source.read_text(encoding="utf-8")
        for term in ("generation_digest", "revision_text", "forbidden_changes"):
            self.assertNotIn(term, text)

    def test_initial_page_renders_and_switches_examples(self):
        app = AppTest.from_file(
            str(ROOT / "src/corpus_atelier/streamlit_app.py"), default_timeout=10,
        ).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.title[0].value, "Corpus Atelier")
        self.assertEqual(
            app.segmented_control(key="new_generation_mode").value,
            "无语料库生成",
        )
        self.assertEqual(len(app.multiselect), 0)
        app.segmented_control(key="new_generation_mode").set_value("有语料库生成").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.multiselect), 2)
        app.segmented_control(key="start_mode").set_value("使用示例").run()
        app.selectbox(key="case_label").select("文章封面").run()
        self.assertFalse(app.exception)
        self.assertIn("从语料到视觉修辞", app.text_area[0].value)

    def test_reference_example_uses_explicit_material_selection(self):
        app = AppTest.from_file(
            str(ROOT / "src/corpus_atelier/streamlit_app.py"), default_timeout=10,
        ).run()
        app.segmented_control(key="start_mode").set_value("使用示例").run()
        app.selectbox(key="case_label").select("慕夏风格女士手表广告").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.multiselect), 2)
        self.assertEqual(
            app.multiselect[1].value, ["mucha-poster-124474277"],
        )

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
            self.assertEqual(app.subheader[0].value, "查看实验结果")

            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.subheader[0].value, "实验结果已接受")
