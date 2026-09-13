"""Offline checks for editable prompt resources and exact request approval."""
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fixtures import image_spec
import shutil

from graphic_design_helper import prompt_files
from graphic_design_helper.designer_prompts import designer_prompt
from graphic_design_helper.proposal_schema import validate_proposal, TEXT_FIELDS, LIST_FIELDS
from graphic_design_helper.workflow import compose_prompt, review_token, generate_round


class PromptTests(unittest.TestCase):
    def test_stage_selection_and_live_file_edits(self):
        with TemporaryDirectory() as tmp:
            for source in prompt_files.PROMPT_DIR.iterdir():
                shutil.copy2(source, Path(tmp) / source.name)
            self.enterContext(patch.object(prompt_files, "PROMPT_DIR", Path(tmp)))
            folder = Path(tmp)
            for name, text in [("designer.md", "SHARED"),
                               ("designer-proposal.md", "PROPOSAL"),
                               ("designer-review.md", "REVIEW")]:
                (folder / name).write_text(text, encoding="utf-8")
            initial = designer_prompt({"purpose": "Pause"})
            self.assertIn("SHARED", initial)
            self.assertIn("PROPOSAL", initial)
            self.assertNotIn("REVIEW", initial)
            revised = designer_prompt({"purpose": "Pause"}, {})
            self.assertIn("REVIEW", revised)
            self.assertNotIn("PROPOSAL", revised)
            (folder / "designer.md").write_text("UPDATED SHARED", encoding="utf-8")
            (folder / "designer-proposal.md").write_text("UPDATED PROPOSAL", encoding="utf-8")
            self.assertIn("UPDATED SHARED", designer_prompt({}))
            self.assertIn("UPDATED PROPOSAL", designer_prompt({}))
            (folder / "designer-review.md").write_text("UPDATED REVIEW", encoding="utf-8")
            self.assertIn("UPDATED REVIEW", designer_prompt({}, {}))
            (folder / "designer.md").write_text(" ", encoding="utf-8")
            with self.assertRaises(ValueError):
                designer_prompt({})

    def test_image_file_edit_requires_new_preview_and_approval(self):
        with TemporaryDirectory() as tmp:
            for source in prompt_files.PROMPT_DIR.iterdir():
                shutil.copy2(source, Path(tmp) / source.name)
            self.enterContext(patch.object(prompt_files, "PROMPT_DIR", Path(tmp)))
            folder = Path(tmp)
            instructions = folder / "image-generation.md"
            instructions.write_text("FIRST RENDER INSTRUCTIONS", encoding="utf-8")
            authored = image_spec()
            research = {"rationale": "PRIVATE RESEARCH"}
            settings = {"model": "mock-image"}
            preview = compose_prompt(authored)
            token = review_token(authored, research, settings, image_prompt=preview)
            instructions.write_text("SECOND RENDER INSTRUCTIONS", encoding="utf-8")
            calls = []
            def generate(**kwargs):
                calls.append(kwargs)
                # An edit after request preparation must not change the approved request.
                instructions.write_text("THIRD RENDER INSTRUCTIONS", encoding="utf-8")
                return SimpleNamespace(data=[SimpleNamespace(
                    b64_json=base64.b64encode(b"\x89PNG\r\n\x1a\nfixture").decode())])
            client = SimpleNamespace(images=SimpleNamespace(generate=generate))
            history = []
            args = dict(history=history, revision={}, output_dir=folder / "runs", client=client)
            with self.assertRaises(ValueError):
                review_token(authored, research, settings, image_prompt=preview)
            with self.assertRaises(ValueError):
                generate_round(authored, research, settings, approved_token=token, **args)
            self.assertEqual(calls, [])
            self.assertEqual(history, [])
            self.assertFalse((folder / "runs").exists())
            preview = compose_prompt(authored)
            token = review_token(authored, research, settings, image_prompt=preview)
            entry = generate_round(authored, research, settings, approved_token=token, **args)
            self.assertEqual(calls[0]["prompt"], preview)
            self.assertNotIn("PRIVATE RESEARCH", preview)
            self.assertEqual(entry["image_spec"], authored)
            self.assertEqual(entry["image_prompt"], preview)
            generation = json.loads(next(Path(entry["folder"]).glob("image/*/response.json")).read_text())
            saved = json.loads((Path(entry["folder"]) / "round.json").read_text())
            self.assertEqual(generation["prompt"], preview)
            self.assertEqual(saved["image_prompt"], preview)
            self.assertNotEqual(review_token(authored, research, settings), token)

    def test_schema_remains_strict_after_extraction(self):
        proposal = {**{key: "Explanation" for key in TEXT_FIELDS},
                    **{key: [] for key in LIST_FIELDS}, "status": "ready", "image_spec": image_spec()}
        self.assertEqual(validate_proposal(proposal), proposal)
        for changed in [{**proposal, "extra": "unexpected"},
                        {**proposal, "status": "unknown"},
                        {**proposal, "assumptions": [1]},
                        {**proposal, "image_spec": None}]:
            with self.assertRaises(ValueError):
                validate_proposal(changed)
        source_dependent = {**proposal, "status": "needs_sources",
                            "image_spec": None, "source_requirements": ["Original source"]}
        self.assertEqual(validate_proposal(source_dependent), source_dependent)


if __name__ == "__main__":
    unittest.main()
