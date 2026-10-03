"""Language contracts survive mixed sources, refreshes, rounds, and recovery."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.artifacts.records import read_json, write_json
from corpus_atelier.language import validate_content_language
from corpus_atelier.state import HumanDecision, NaturalLanguageDesignJob
from tests.fakes import FakeImageProvider
from tests.test_conversation import ConversationTextProvider, seed_brief


COPY = ["欢度国庆", "1949-2026", "Happy National Day"]
REQUIREMENT = "Use a dark-brown woven basket with an arched handle."


def prompt_language(prompt):
    policy = prompt.split("# Task content language\n\n", 1)[1]
    start = policy.index('{\n  "content_language"')
    return json.JSONDecoder().raw_decode(policy[start:])[0]


class LanguageTextProvider(ConversationTextProvider):
    """Bilingual fixtures isolate language propagation from model nondeterminism."""

    def __init__(self, initial_language="zh-CN"):
        super().__init__()
        self.initial_language = initial_language
        self.change_language = None
        self.change_quote = None

    def propose(self, prompt, *, schema_name, reference_paths=None):
        language = self.change_language or prompt_language(prompt)["content_language"] or self.initial_language
        value, response = super().propose(prompt, schema_name=schema_name, reference_paths=reference_paths)
        chinese = language.startswith("zh")
        if schema_name == "design-assistant.schema.json":
            value.update(content_language=self.change_language or language, language_change_quote=self.change_quote)
        elif schema_name.endswith("-brief.schema.json"):
            value.update(
                content_language=language, exact_copy=list(COPY),
                purpose="以写实广式插花传递国庆祝福。" if chinese else "Convey a National Day greeting through photorealistic Guang-style floral arranging.",
                audience="国庆海报的观看者。" if chinese else "Viewers of the National Day poster.",
                constraints=["大花蕙兰（Cymbidium）清晰可辨，右下角保持留白。" if chinese else "Keep Cymbidium orchids (大花蕙兰) recognizable and the lower-right area clear."],
            )
            if "deliverable" in value:
                value.update(
                    deliverable="竖版国庆庆祝海报。" if chinese else "Vertical National Day celebration poster.",
                    use_context="右下角预留后续添加标志的区域。" if chinese else "Reserve the lower-right area for a logo added later.",
                    preferences=["采用多色花材。" if chinese else "Use multicolored flowers."],
                    canvas={"aspect_ratio": {"width": 2, "height": 3}},
                )
            elif "topic" in value:
                value.update(topic="国庆花篮" if chinese else "National Day flower basket", setting="节庆展示" if chinese else "Celebration display")
            else:
                value.update(article_title="国庆花篮 · National Day", article_summary=value["purpose"], art_direction="写实插花" if chinese else "Photorealistic floral arranging")
        elif chinese and schema_name == "design-direction-plan.schema.json":
            for direction in value["directions"]:
                direction.update(label="花篮国庆祝福", design_thesis="以花篮作为视觉中心。", objective_strategy="清晰传递节庆祝福。", implementation_freedom=["调整花材的层次和间距。"], portfolio_role="直接呈现节庆主题。")
                for decision in direction["direction_decisions"]:
                    decision["decision"] = "保留花篮提手并让右下角留白。"
        elif chinese and schema_name.endswith("-proposal.schema.json"):
            value.update(brief_interpretation="国庆花篮海报。", chosen_direction="花篮作为画面主体。", design_description="写实藤编花篮，花材错落有致，右下角留白。", design_rationale="花材层次与标题共同传递节庆氛围。", review_criteria=["保留原始文案。", "花篮提手可见，右下角保持留白。"])
        elif chinese and schema_name == "image-spec.schema.json":
            value.update(communication_objective="传递国庆祝福。", audience_and_context="节庆海报的观看者。", composition="花篮居中，右下角留白。", typography="标题清晰可读。", visual_treatment="写实摄影质感。", allowed_variation=["调整花材层次。"], exclusions=["不增加其他文字。"])
        return value, response


class LanguageTests(unittest.TestCase):
    def app(self, directory, text):
        return CorpusAtelierApplication(runs_root=directory, text_provider=text, image_provider=FakeImageProvider())

    def job(self, request="设计一张国庆花篮海报，文案包含 Happy National Day。", **kwargs):
        return NaturalLanguageDesignJob("language-test", "rhetoric-graphic", request, **kwargs)

    def test_chinese_and_english_tasks_keep_mixed_source_copy_through_generation(self):
        for language, request in (
            ("zh-CN", "设计一张国庆花篮海报，文案包含 Happy National Day。"),
            ("en", 'Design a flower basket poster with exact copy "欢度国庆" and "1949-2026".'),
        ):
            with self.subTest(language=language), TemporaryDirectory() as directory:
                text = LanguageTextProvider(language)
                with self.app(directory, text) as app:
                    parent = app.create_conversation(self.job(request))
                    app.continue_task(parent.run_id)
                    seed_brief(app, parent.run_id)
                    initial = app.conversation(parent.run_id)
                    app.save_conversation_brief(parent.run_id, {**initial["design_brief"], "user_requirements": [REQUIREMENT]}, expected_revision=initial["revision"])
                    saved = app.conversation(parent.run_id)
                    self.assertEqual(saved["content_language"], language)
                    self.assertEqual(saved["design_brief"]["content_language"], language)
                    self.assertEqual(saved["design_brief"]["exact_copy"], COPY)
                    child = app.create_conversation_round(parent.run_id)
                    result = app.run_request(child.run_id)
                    self.assertEqual(result.status, "awaiting_approval")
                    self.assertEqual(read_json(Path(result.artifacts["brief"])), saved["design_brief"])
                    candidates = read_json(Path(result.artifacts["candidate_index"]))
                    self.assertEqual(candidates[0]["image_spec"]["visible_copy"], COPY)
                    self.assertIn(REQUIREMENT, candidates[0]["generation_prompt"])
                    if language == "zh-CN":
                        self.assertEqual(candidates[0]["direction_seed"]["label"], "花篮国庆祝福")
                        self.assertEqual(candidates[0]["proposal"]["design_description"], "写实藤编花篮，花材错落有致，右下角留白。")
                        self.assertEqual(candidates[0]["image_spec"]["composition"], "花篮居中，右下角留白。")
                    for call in text.chat_calls + text.design_calls:
                        self.assertEqual(prompt_language(call["prompt"])["content_language"], language if call != text.chat_calls[0] else None)
                    result = app.resume(child.run_id, HumanDecision(True))
                    self.assertEqual(result.status, "awaiting_selection")
                    self.assertEqual(app.runtime.image_provider.calls, 1)

    def test_single_round_infers_and_persists_language_before_downstream_calls(self):
        with TemporaryDirectory() as directory:
            text = LanguageTextProvider()
            with self.app(directory, text) as app:
                result = app.start_request(self.job())
                self.assertEqual(app.inspect_task(result.run_id).manifest["content_language"], "zh-CN")
                self.assertIsNone(prompt_language(text.design_calls[0]["prompt"])["content_language"])
                for call in text.design_calls[1:]:
                    self.assertEqual(prompt_language(call["prompt"])["content_language"], "zh-CN")

    def test_explicit_initial_language_and_restart_remain_stable_with_other_language_feedback(self):
        with TemporaryDirectory() as directory:
            text = LanguageTextProvider()
            with self.app(directory, text) as app:
                parent = app.create_conversation(self.job(content_language="en"))
                app.continue_task(parent.run_id)
            with self.app(directory, text) as reopened:
                reopened.queue_conversation_message(parent.run_id, "让花篮更突出一点。")
                reopened.continue_task(parent.run_id)
                self.assertEqual(reopened.conversation(parent.run_id)["content_language"], "en")
                self.assertEqual(prompt_language(text.chat_calls[-1]["prompt"])["content_language"], "en")

    def test_reply_language_changes_do_not_change_the_brief_language(self):
        with TemporaryDirectory() as directory:
            text = LanguageTextProvider()
            with self.app(directory, text) as app:
                task = app.create_conversation(self.job(content_language="zh-CN"))
                app.continue_task(task.run_id)
                seed_brief(app, task.run_id)
                original = app.conversation(task.run_id)["design_brief"]
                text.change_language = "en"
                text.change_quote = "Please reply in English."
                app.queue_conversation_message(task.run_id, text.change_quote)
                app.continue_task(task.run_id)
                saved = app.conversation(task.run_id)
                self.assertEqual(saved["discussion_language"], "en")
                self.assertEqual(saved["content_language"], "zh-CN")
                self.assertEqual(saved["design_brief"], original)

    def test_invalid_initial_language_tag_is_rejected(self):
        with TemporaryDirectory() as directory, self.app(directory, LanguageTextProvider()) as app:
            with self.assertRaises(ValueError):
                app.create_conversation(self.job(content_language="English"))
