import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image
from streamlit.testing.v1 import AppTest

from corpus_atelier.state import ComparisonResult, RunResult


ROOT = Path(__file__).resolve().parents[1]


class FakeUiApplication:
    """Small session-state fake used to exercise Streamlit page transitions."""

    def __init__(self, run_dir: Path, artifacts: dict[str, str]):
        self.run_dir = run_dir
        self.artifacts = artifacts

    def resume(self, run_id, decision):
        status = "completed" if decision.approved else "rejected"
        return RunResult(
            run_id=run_id, status=status, run_dir=self.run_dir,
            message=status, artifacts=self.artifacts,
        )


class FailingStartApplication:
    def __init__(self, **kwargs):
        pass

    def start_request(self, job):
        raise ValueError("Design proposal requested an unavailable source.")


class StreamlitAppTests(unittest.TestCase):
    def test_streamlit_source_does_not_expose_protocol_details(self):
        source = ROOT / "src/corpus_atelier/streamlit_app.py"
        text = source.read_text(encoding="utf-8")
        for term in ("generation_digest", "revision_text", "forbidden_changes"):
            self.assertNotIn(term, text)

    def test_initial_page_uses_one_natural_language_input(self):
        app = AppTest.from_file(
            str(ROOT / "src/corpus_atelier/streamlit_app.py"), default_timeout=10,
        ).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.title[0].value, "Corpus Atelier")
        self.assertEqual(app.text_area(key="natural_request").value, "")
        self.assertEqual(
            app.segmented_control(key="design_method").value,
            "修辞导向",
        )
        self.assertEqual(
            app.segmented_control(key="experiment_mode").value,
            "普通生成",
        )
        self.assertEqual(len(app.segmented_control), 2)
        self.assertEqual(len(app.selectbox), 0)
        self.assertEqual(len(app.get("file_uploader")), 0)
        self.assertEqual(len(app.text_input), 0)
        self.assertEqual(len(app.multiselect), 0)

    def test_corpus_conditions_are_explicitly_labelled_as_experimental(self):
        app = AppTest.from_file(
            str(ROOT / "src/corpus_atelier/streamlit_app.py"), default_timeout=10,
        ).run()
        mode = app.segmented_control(key="experiment_mode")
        self.assertIn("无显式语料基线（实验性）", mode.options)
        self.assertIn("有显式语料（实验性）", mode.options)
        self.assertIn("成对运行两种条件（实验性）", mode.options)

        mode.set_value("有显式语料（实验性）").run()
        self.assertTrue(any(
            "实验功能" in caption.value for caption in app.caption
        ))

    def test_model_failure_is_not_reported_as_invalid_user_input(self):
        with patch(
            "corpus_atelier.application.CorpusAtelierApplication",
            FailingStartApplication,
        ):
            app = AppTest.from_file(
                str(ROOT / "src/corpus_atelier/streamlit_app.py"),
                default_timeout=10,
            ).run()
            app.text_area(key="natural_request").set_value(
                "请做一张超现实主义电脑壁纸。"
            ).run()
            app.button[0].click().run()

        self.assertFalse(app.exception)
        self.assertEqual(
            app.error[0].value,
            "无法生成设计方案：Design proposal requested an unavailable source.",
        )

    def test_generation_preview_flows_directly_to_completed_result(self):
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
            request_preview = run_dir / "generation-request-preview.json"
            request_preview.write_text(json.dumps({
                "prompt": generation_prompt,
                "model": "gpt-image-2",
                "quality": "medium",
                "size": "1024x1536",
                "output_format": "png",
                "n": 1,
                "operation": "generation",
                "references": [],
            }), encoding="utf-8")
            image = run_dir / "image.png"
            Image.new("RGB", (12, 18), "white").save(image)
            artifacts = {
                "proposal": str(proposal),
                "generation_prompt": str(prompt),
                "generation_request_preview": str(request_preview),
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
            self.assertEqual(app.subheader[0].value, "图像模型输入预览")
            self.assertIn("尚未发送", app.info[0].value)
            self.assertEqual(app.code[0].value, generation_prompt)
            self.assertEqual(app.button(key="send_generation").label, "发送并生成图片")
            self.assertEqual(app.button(key="cancel_generation").label, "取消本次生成")

            app.button(key="send_generation").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.subheader[0].value, "生成完成")
            self.assertEqual([button.label for button in app.button], ["开始新实验"])

    def test_paired_experiment_keeps_independent_approval_gates(self):
        with TemporaryDirectory() as directory:
            run_dir = Path(directory)
            baseline = RunResult(
                run_id="baseline-run",
                status="awaiting_approval",
                run_dir=run_dir,
                message="awaiting approval",
                artifacts={},
            )
            corpus = RunResult(
                run_id="corpus-run",
                status="awaiting_approval",
                run_dir=run_dir,
                message="awaiting approval",
                artifacts={},
            )
            comparison = ComparisonResult(
                group_id="comparison-test",
                group_dir=run_dir,
                brief={},
                baseline=baseline,
                corpus=corpus,
            )
            app = AppTest.from_file(
                str(ROOT / "src/corpus_atelier/streamlit_app.py"), default_timeout=10,
            )
            app.session_state["atelier_app"] = FakeUiApplication(run_dir, {})
            app.session_state["comparison_result"] = comparison
            app.session_state["result"] = None
            app.run()

            self.assertFalse(app.exception)
            self.assertEqual(app.subheader[0].value, "有／无显式语料对比实验")
            self.assertEqual(
                app.button(key="baselinesend_generation").label,
                "发送并生成图片",
            )
            self.assertEqual(
                app.button(key="corpussend_generation").label,
                "发送并生成图片",
            )

            app.button(key="baselinesend_generation").click().run()
            updated = app.session_state["comparison_result"]
            self.assertEqual(updated.baseline.status, "completed")
            self.assertEqual(updated.corpus.status, "awaiting_approval")
            self.assertEqual(
                app.button(key="corpussend_generation").label,
                "发送并生成图片",
            )
