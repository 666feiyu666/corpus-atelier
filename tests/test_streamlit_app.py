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
        self.comparison_resume_calls = 0

    def resume(self, run_id, decision):
        if hasattr(decision, "approved"):
            status = "awaiting_selection" if decision.approved else "rejected"
            if decision.approved and self.artifacts.get("candidate_index"):
                path = Path(self.artifacts["candidate_index"])
                candidates = json.loads(path.read_text(encoding="utf-8"))
                for candidate in candidates:
                    if candidate.get("status") == "ready":
                        candidate.update(
                            status="generated",
                            image_path=self.artifacts["image"],
                            image_sha256="test-sha",
                        )
                path.write_text(json.dumps(candidates), encoding="utf-8")
        else:
            status = "completed"
        return RunResult(
            run_id=run_id, status=status, run_dir=self.run_dir,
            message=status, artifacts=self.artifacts,
        )

    def resume_comparison(self, comparison, decision):
        self.comparison_resume_calls += 1
        status = "completed" if decision.approved else "rejected"

        def update(result):
            return RunResult(
                run_id=result.run_id,
                status=status,
                run_dir=self.run_dir,
                message=status,
                artifacts=self.artifacts,
            )

        return ComparisonResult(
            group_id=comparison.group_id,
            group_dir=comparison.group_dir,
            brief=comparison.brief,
            baseline=update(comparison.baseline),
            corpus=update(comparison.corpus),
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
        self.assertEqual(app.subheader[0].value, "创建设计")
        self.assertEqual(app.text_area(key="design_request").value, "")
        self.assertEqual(
            app.segmented_control(key="design_method").value,
            "修辞导向",
        )
        candidate_limit = app.segmented_control(key="design_candidate_count")
        self.assertEqual(candidate_limit.label, "方案数量上限")
        self.assertEqual(candidate_limit.value, 3)
        self.assertEqual(len(app.segmented_control), 2)
        self.assertEqual(app.button(key="start_design").label, "生成设计方案")
        self.assertEqual(len(app.selectbox), 0)
        self.assertEqual(len(app.get("file_uploader")), 0)
        self.assertEqual(len(app.text_input), 0)
        self.assertEqual(len(app.multiselect), 0)

    def test_corpus_controls_are_isolated_on_the_experiment_page(self):
        app = AppTest.from_file(
            str(ROOT / "src/corpus_atelier/streamlit_app.py"), default_timeout=10,
        ).run()
        app.switch_page("app_pages/corpus_experiment.py").run()

        self.assertEqual(app.subheader[0].value, "语料对比实验")
        self.assertEqual(app.text_area(key="experiment_request").value, "")
        mode = app.segmented_control(key="experiment_mode")
        self.assertEqual(
            mode.options,
            ["成对比较", "无显式语料", "有显式语料"],
        )
        self.assertEqual(mode.value, "成对比较")
        source = (ROOT / "src/corpus_atelier/streamlit_app.py").read_text(
            encoding="utf-8",
        )
        self.assertIn('st.badge("实验性"', source)

        mode.set_value("有显式语料").run()
        self.assertEqual(app.button(key="start_experiment").label, "开始实验")

    def test_model_failure_is_not_reported_as_invalid_user_input(self):
        with patch(
            "corpus_atelier.streamlit_app.CorpusAtelierApplication",
            FailingStartApplication,
        ):
            app = AppTest.from_file(
                str(ROOT / "src/corpus_atelier/streamlit_app.py"),
                default_timeout=10,
            ).run()
            app.text_area(key="design_request").set_value(
                "请做一张超现实主义电脑壁纸。"
            ).run()
            app.button(key="start_design").click().run()

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
            candidate_index = run_dir / "candidates.json"
            candidate_index.write_text(json.dumps([{
                "candidate_id": "c01",
                "status": "ready",
                "direction_seed": {
                    "label": "Quiet hierarchy",
                    "direction_decisions": [{
                        "axis": "composition",
                        "decision": "Use one restrained editorial hierarchy.",
                    }],
                },
                "proposal": {
                    "chosen_direction": "A restrained editorial composition.",
                    "design_rationale": "Clear hierarchy for a small screen.",
                },
                "generation_request": json.loads(request_preview.read_text()),
                "generation_prompt": generation_prompt,
            }]), encoding="utf-8")
            artifacts = {
                "proposal": str(proposal),
                "generation_prompt": str(prompt),
                "generation_request_preview": str(request_preview),
                "image": str(image),
                "candidate_index": str(candidate_index),
            }
            result = RunResult(
                run_id="ui-test", status="awaiting_approval", run_dir=run_dir,
                message="awaiting approval", artifacts=artifacts,
            )
            app = AppTest.from_file(
                str(ROOT / "src/corpus_atelier/streamlit_app.py"), default_timeout=10,
            )
            app.session_state["design_app"] = FakeUiApplication(run_dir, artifacts)
            app.session_state["design_result"] = result
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(app.subheader[0].value, "图像模型输入预览")
            self.assertIn("尚未发送", app.info[0].value)
            self.assertEqual(app.code[0].value, generation_prompt)
            self.assertEqual(
                app.button(key="design_send_generation").label,
                "发送并生成 1 张图片",
            )
            self.assertEqual(
                app.button(key="design_cancel_generation").label,
                "取消本次生成",
            )

            app.button(key="design_send_generation").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.subheader[0].value, "选择设计")
            app.button(key="select_c01").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.subheader[0].value, "生成完成")
            self.assertEqual([button.label for button in app.button], ["创建新设计"])

    def test_paired_experiment_uses_two_columns_and_one_shared_approval(self):
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
            app.run()
            app.session_state["experiment_app"] = FakeUiApplication(run_dir, {})
            app.session_state["comparison_result"] = comparison
            app.session_state["experiment_result"] = None
            app.switch_page("app_pages/corpus_experiment.py").run()

            self.assertFalse(app.exception)
            self.assertEqual(app.subheader[0].value, "有／无显式语料对比实验")
            self.assertEqual(
                len(app.get("column")),
                4,
            )
            self.assertEqual(
                app.button(key="experiment_generate_comparison").label,
                "确认并生成两张图片",
            )
            self.assertEqual(
                app.button(key="experiment_cancel_comparison").label,
                "取消本次对比",
            )
            self.assertEqual(len(app.button), 2)

            app.button(key="experiment_generate_comparison").click().run()
            updated = app.session_state["comparison_result"]
            self.assertEqual(updated.baseline.status, "completed")
            self.assertEqual(updated.corpus.status, "completed")
            self.assertEqual(
                app.session_state["experiment_app"].comparison_resume_calls,
                1,
            )
            self.assertEqual([button.label for button in app.button], ["开始新实验"])
