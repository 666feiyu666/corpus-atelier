import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image
from streamlit.testing.v1 import AppTest

from corpus_atelier.streamlit_app import (
    CASES, build_general_brief, delivery_ratio, load_case, parse_brief,
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
        watch = load_case("AURELIA 女士手表广告")
        self.assertEqual(list(CASES), [
            "工作坊海报", "文章封面", "AURELIA 女士手表广告",
        ])
        self.assertEqual(poster["topic"], "Corpus Atelier")
        self.assertEqual(cover["article_title"], "从语料到视觉修辞")
        self.assertNotIn("reference_mode", watch)
        self.assertNotIn("corpus", watch["purpose"].lower())

    def test_brief_editor_requires_a_json_object(self):
        self.assertEqual(parse_brief('{"topic": "x"}'), {"topic": "x"})
        with self.assertRaisesRegex(ValueError, "JSON 对象"):
            parse_brief("[]")

    def test_general_brief_keeps_delivery_context_open(self):
        brief = build_general_brief(
            deliverable="展览导览卡",
            purpose="帮助观众识别展区",
            audience="现场观众",
            use_context="手持阅读并可能低照度观看",
            exact_copy="第一展区\n夜间开放",
            constraints="不可使用荧光色",
            preferences="克制",
            ratio_width=4,
            ratio_height=5,
        )
        self.assertEqual(brief["deliverable"], "展览导览卡")
        self.assertEqual(brief["exact_copy"], ["第一展区", "夜间开放"])
        self.assertEqual(
            brief["canvas"], {"aspect_ratio": {"width": 4, "height": 5}},
        )

    def test_known_delivery_contexts_own_their_canvas_ratios(self):
        self.assertEqual(delivery_ratio("手机阅读海报"), (4, 5))
        self.assertEqual(delivery_ratio("张贴或印刷海报"), (2, 3))
        self.assertEqual(delivery_ratio("小红书配图"), (3, 4))
        self.assertEqual(delivery_ratio("文章内插图"), (16, 9))
        self.assertEqual(delivery_ratio("微信公众号封面"), (47, 20))
        self.assertIsNone(delivery_ratio("自定义展览屏幕"))

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
        self.assertEqual(app.text_input(key="new_case_id").value, "")
        self.assertEqual(len(app.multiselect), 0)
        app.segmented_control(key="new_generation_mode").set_value("有语料库生成").run()
        self.assertFalse(app.exception)
        self.assertEqual(
            app.selectbox(key="selected_reference_id").value,
            "mucha-poster-124474229",
        )
        app.segmented_control(key="start_mode").set_value("使用示例").run()
        self.assertEqual(app.selectbox(key="case_label").options, [
            "工作坊海报", "文章封面", "AURELIA 女士手表广告",
        ])
        app.selectbox(key="case_label").select("文章封面").run()
        self.assertFalse(app.exception)
        self.assertIn("从语料到视觉修辞", app.text_area[0].value)

    def test_reference_example_uses_explicit_reference_selection(self):
        app = AppTest.from_file(
            str(ROOT / "src/corpus_atelier/streamlit_app.py"), default_timeout=10,
        ).run()
        app.segmented_control(key="start_mode").set_value("使用示例").run()
        app.selectbox(key="case_label").select("AURELIA 女士手表广告").run()
        self.assertFalse(app.exception)
        self.assertEqual(
            app.selectbox(key="selected_reference_id").value,
            "mucha-poster-124474277",
        )
        self.assertEqual(
            app.selectbox(key="example_reference_mode").value,
            "以共同风格特征为约束",
        )
        brief = json.loads(app.text_area(key="brief_editor").value)
        self.assertNotIn("reference_mode", brief)
        self.assertNotIn("corpus", brief["purpose"].lower())
        app.segmented_control(key="example_generation_mode").set_value(
            "无语料库生成"
        ).run()
        self.assertFalse(app.exception)
        self.assertFalse(any(
            item.key == "selected_reference_id" for item in app.selectbox
        ))
        self.assertFalse(any(
            item.key == "example_reference_mode" for item in app.selectbox
        ))

    def test_approval_acceptance_flow_renders_each_page_state(self):
        with TemporaryDirectory() as directory:
            run_dir = Path(directory)
            proposal = run_dir / "proposal.json"
            proposal.write_text(json.dumps({
                "chosen_direction": "A restrained editorial composition.",
                "design_rationale": "Clear hierarchy for a small screen.",
            }), encoding="utf-8")
            generation_prompt = (
                "# Image rendering instructions\n\n"
                "Render the complete approved image specification."
            )
            prompt = run_dir / "generation-prompt.md"
            prompt.write_text(generation_prompt, encoding="utf-8")
            image = run_dir / "image.png"
            Image.new("RGB", (12, 18), "white").save(image)
            artifacts = {
                "proposal": str(proposal),
                "generation_prompt": str(prompt),
                "image": str(image),
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
            self.assertEqual(app.code[0].value, generation_prompt)

            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.subheader[0].value, "查看实验结果")
            self.assertFalse(any(
                "自动审查" in caption.value for caption in app.caption
            ))

            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.subheader[0].value, "实验结果已接受")
