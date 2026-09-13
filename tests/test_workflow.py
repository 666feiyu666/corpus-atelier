"""Offline checks of prompt boundaries, actual image input, and saved lineage."""
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from PIL import Image
from graphic_design_helper.workflow import review_token
from graphic_design_helper.review import BLIND_REVIEW_PROMPT, comparison_prompt, review_image
from graphic_design_helper.workflow import generate_round, compose_prompt
from graphic_design_helper.designer_prompts import designer_prompt
from graphic_design_helper.designer import propose_design
from graphic_design_helper.proposal_schema import TEXT_FIELDS, LIST_FIELDS


class WorkflowTests(unittest.TestCase):
    def test_macro_brief_proposal_and_source_gate(self):
        with TemporaryDirectory() as tmp:
            proposal = {**{k: "Explanation" for k in TEXT_FIELDS},
                        **{k: [] for k in LIST_FIELDS}, "status": "ready"}
            proposal["production_prompt"] = "Only this goes to GPT Image."
            calls = []
            def create(**kwargs):
                calls.append(kwargs)
                return SimpleNamespace(status="completed", output_text=json.dumps(proposal))
            client = SimpleNamespace(responses=SimpleNamespace(create=create))
            prompt = designer_prompt({"purpose": "Invite a pause", "setting": "An office"})
            record = propose_design(prompt, client=client, output_dir=tmp)
            self.assertEqual(calls[0]["input"], prompt)
            self.assertEqual(calls[0]["model"], "gpt-5.6-luna")
            self.assertNotIn("previous_response_id", calls[0])
            self.assertEqual(record["proposal"]["production_prompt"], proposal["production_prompt"])
            self.assertTrue((Path(record["folder"]) / "proposal.json").exists())
            proposal.update(status="needs_sources", source_requirements=["Real source required"],
                            production_prompt="")
            with self.assertRaises(ValueError):
                review_token("Manually bypass blank prompt", {"proposal": proposal}, {})
            proposal["status"] = "ready"
            with self.assertRaises(ValueError):
                propose_design(prompt, client=client, output_dir=tmp)
            statuses = [json.loads(p.read_text())["status"] for p in Path(tmp).glob("*/proposal.json")]
            self.assertIn("failed", statuses)

    def test_reviewed_request_and_revision_boundary(self):
        with TemporaryDirectory() as tmp:
            image = Path(tmp) / "fixture.png"
            Image.new("RGB", (4, 4), "white").save(image)
            calls = []
            def generate(**kwargs):
                calls.append(kwargs)
                return SimpleNamespace(data=[SimpleNamespace(
                    b64_json=base64.b64encode(image.read_bytes()).decode())])
            client = SimpleNamespace(images=SimpleNamespace(generate=generate))
            research = {"rationale": "PRIVATE RESEARCH", "sign_strategies": []}
            settings = {"model": "mock-image", "size": "1024x1536", "quality": "medium"}
            prompt = "Exact production text.\n"
            token = review_token(prompt, research, settings)
            history = []
            args = dict(approved_token=token, history=history, revision={},
                        output_dir=tmp, client=client)
            with self.assertRaises(ValueError):
                generate_round(prompt + "changed", research, settings, **args)
            with self.assertRaises(ValueError):
                generate_round(prompt, {**research, "rationale": "changed"}, settings, **args)
            self.assertEqual(calls, [])
            entry = generate_round(prompt, research, settings, **args)
            self.assertEqual(calls[0]["prompt"], compose_prompt(prompt))
            self.assertEqual(entry["image_prompt"], calls[0]["prompt"])
            self.assertEqual(entry["generation"]["prompt"], calls[0]["prompt"])
            self.assertNotIn("PRIVATE RESEARCH", json.dumps(calls))
            research["rationale"] = "later edit"
            self.assertEqual(entry["research"]["rationale"], "PRIVATE RESEARCH")
            self.assertTrue((Path(entry["folder"]) / "round.json").is_file())
            research["rationale"] = "PRIVATE RESEARCH"
            with self.assertRaises(ValueError):
                generate_round(prompt, research, settings, **args)
            for _ in range(2):
                history[-1]["self_review"] = {"text": "Needs revision"}
                args["revision"] = {"reason": "Change spacing"}
                generate_round(prompt, research, settings, **args)
            with self.assertRaises(ValueError):
                generate_round(prompt, research, settings, **args)
            self.assertEqual(len(calls), 3)

    def test_independent_vision_requests_and_records(self):
        with TemporaryDirectory() as tmp:
            image = Path(tmp) / "fixture.png"
            Image.new("RGB", (4, 4), "white").save(image)
            calls = []
            def create(**kwargs):
                calls.append(kwargs)
                return SimpleNamespace(output_text="Candidate reading", status="completed")
            client = SimpleNamespace(responses=SimpleNamespace(create=create))
            first = review_image(image, BLIND_REVIEW_PROMPT, model="mock-vision",
                                 output_dir=tmp, client=client)
            second_prompt = comparison_prompt({"rationale": "PRIVATE RESEARCH"},
                                              "Production text", first["text"])
            review_image(image, second_prompt, model="mock-vision", output_dir=tmp, client=client)
            self.assertNotIn("PRIVATE RESEARCH", json.dumps(calls[0]))
            self.assertIn("PRIVATE RESEARCH", json.dumps(calls[1]))
            for call in calls:
                self.assertNotIn("previous_response_id", call)
                content = call["input"][0]["content"]
                self.assertEqual(base64.b64decode(content[1]["image_url"].split(",")[1]),
                                 image.read_bytes())
            self.assertEqual(len(list(Path(tmp).glob("*/review.json"))), 2)

    def test_designer_self_review_sees_poster_and_macro_brief(self):
        with TemporaryDirectory() as tmp:
            image = Path(tmp) / "poster.png"
            Image.new("RGB", (4, 4), "blue").save(image)
            proposal = {**{k: "Revised explanation" for k in TEXT_FIELDS},
                        **{k: [] for k in LIST_FIELDS}, "status": "ready"}
            calls = []
            def create(**kwargs):
                calls.append(kwargs)
                return SimpleNamespace(status="completed", output_text=json.dumps(proposal))
            client = SimpleNamespace(responses=SimpleNamespace(create=create))
            prompt = designer_prompt({"purpose": "Permission to pause"},
                                     {"previous_prompt": "Old poster prompt"})
            record = propose_design(prompt, image_path=image, client=client, output_dir=tmp)
            content = calls[0]["input"][0]["content"]
            self.assertEqual(content[0]["text"], prompt)
            self.assertIn("Permission to pause", content[0]["text"])
            self.assertEqual(base64.b64decode(content[1]["image_url"].split(",")[1]),
                             image.read_bytes())
            self.assertEqual(record["kind"], "designer_self_review")
            self.assertIn("image_sha256", record)
            self.assertEqual(record["proposal"], proposal)
            image.write_bytes(b"invalid")
            with self.assertRaises(ValueError):
                propose_design(prompt, image_path=image, client=client, output_dir=tmp)
            self.assertEqual(len(calls), 1)

    def test_source_composition_is_blocked(self):
        with self.assertRaises(ValueError):
            review_token("Poster", {"sign_strategies": [{"selected": True,
                         "production": "compose_from_source"}]}, {})


if __name__ == "__main__":
    unittest.main()
