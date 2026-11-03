"""Language contracts survive mixed sources, refreshes, rounds, and recovery."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from corpus_atelier.app.service import CorpusAtelierApplication
from corpus_atelier.artifacts.records import read_json, write_json
from corpus_atelier.language import validate_content_language
from corpus_atelier.app.state import HumanDecision, NaturalLanguageDesignJob
from tests.fakes import FakeImageProvider, FakeTextProvider


COPY = ["欢度国庆", "1949-2026", "Happy National Day"]
def prompt_language(prompt):
    policy = prompt.split("# Task content language\n\n", 1)[1]
    start = policy.index('{\n  "content_language"')
    return json.JSONDecoder().raw_decode(policy[start:])[0]


class LanguageTextProvider(FakeTextProvider):
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
        if schema_name.endswith("-brief.schema.json"):
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
        elif chinese and schema_name == "image-prompt.schema.json":
            value.update(
                asset_kind="国庆海报。",
                canvas_statement="竖版国庆海报，花篮居中，右下角留白。",
                prompt="写实摄影质感的藤编花篮位于画面中央，花材错落有致，右下角保持留白，标题清晰可读。",
                avoid=["不增加其他文字。"],
                visual_qa=["标题文字逐字正确。", "右下角保持留白。"],
            )
        return value, response


class LanguageTests(unittest.TestCase):
    def app(self, directory, text):
        return CorpusAtelierApplication(runs_root=directory, text_provider=text, image_provider=FakeImageProvider())

    def job(self, request="设计一张国庆花篮海报，文案包含 Happy National Day。", **kwargs):
        return NaturalLanguageDesignJob("language-test", "rhetoric-graphic", request, **kwargs)

    def test_single_round_infers_and_persists_language_before_downstream_calls(self):
        with TemporaryDirectory() as directory:
            text = LanguageTextProvider()
            with self.app(directory, text) as app:
                result = app.start_request(self.job())
                self.assertEqual(app.inspect_task(result.run_id).manifest["content_language"], "zh-CN")
                self.assertIsNone(prompt_language(text.design_calls[0]["prompt"])["content_language"])
                for call in text.design_calls[1:]:
                    self.assertEqual(prompt_language(call["prompt"])["content_language"], "zh-CN")

    def test_invalid_initial_language_tag_is_rejected(self):
        with TemporaryDirectory() as directory, self.app(directory, LanguageTextProvider()) as app:
            with self.assertRaises(ValueError):
                app.start_request(self.job(content_language="English"))
