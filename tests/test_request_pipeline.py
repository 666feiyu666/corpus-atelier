"""Offline integration checks for assembly, manual handoff, and durable attempts."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
from fixtures import proposal, image_spec, designer_client
from graphic_design_helper import prompt_files
from graphic_design_helper.prompt_builder import build_designer_request, build_image_prompt, render_template, request_token
from graphic_design_helper.proposal_schema import validate_proposal
from graphic_design_helper.records import start_run
from graphic_design_helper.workflow import design_round, generate_round, review_token, load_rounds


class PipelineTests(unittest.TestCase):
    def test_initial_and_review_templates_are_independent(self):
        from graphic_design_helper.prompt_builder import build_designer_prompt
        with TemporaryDirectory() as tmp:
            templates = Path(tmp) / "templates"
            shutil.copytree(prompt_files.TEMPLATE_DIR, templates)
            with patch.object(prompt_files, "TEMPLATE_DIR", templates):
                initial = build_designer_prompt({"purpose": "Pause"})
                review = build_designer_prompt({"purpose": "Pause"}, {"previous_prompt": "PRIOR POSTER"})
                self.assertNotIn("Previous design and review context", initial)
                self.assertNotIn("Current stage", initial)
                self.assertNotIn("User-supplied brief", initial)
                self.assertIn("PRIOR POSTER", review)
                path = templates / "designer-review-input-template.md"
                path.write_text(path.read_text() + "\nREVIEW CHANGE\n")
                self.assertEqual(initial, build_designer_prompt({"purpose": "Pause"}))
                self.assertIn("REVIEW CHANGE", build_designer_prompt({"purpose": "Pause"}, {}))
                path = templates / "designer-input-template.md"
                path.write_text(path.read_text() + "\nINITIAL CHANGE\n")
                self.assertIn("INITIAL CHANGE", build_designer_prompt({"purpose": "Pause"}))
                self.assertNotIn("INITIAL CHANGE", build_designer_prompt({"purpose": "Pause"}, {}))

    def test_requirement_formatting_preserves_supplied_content(self):
        from graphic_design_helper.prompt_builder import build_designer_prompt
        requirements = {"purpose": "Pause {{literal}}", "exact_copy": "Line one\nLine two",
                        "audience": "Provisional audience", "sources": None,
                        "custom_requirement": {"wording": ["Keep punctuation!", "Keep order?"]}}
        original = deepcopy(requirements)
        prompt = build_designer_prompt(requirements)
        for wording in ("Pause {{literal}}", "Line one\nLine two", "Provisional audience",
                        "Keep punctuation!", "Keep order?"):
            self.assertIn(wording, prompt)
        self.assertIn("## Required sources\n\nNot specified.", prompt)
        self.assertLess(prompt.index("Keep punctuation!"), prompt.index("Keep order?"))
        self.assertEqual(requirements, original)

    def test_complete_handoff_and_self_review(self):
        with TemporaryDirectory() as tmp:
            brief = {"purpose": "Invite a pause"}
            original = "Make a poster: {{keep my words}}"
            run = start_run(brief, original_user_request=original, output_dir=tmp)
            request = build_designer_request(brief, original_user_request=original)
            calls = []
            result = proposal()
            result["design_rationale"] = "PRIVATE RATIONALE"
            result["sign_relationships"] = "### Headline\nSymbolic relationship: HUMAN SIGN ANALYSIS"
            result["graphic_decisions"] = "HUMAN DESIGN LINK: the spacing supports the intended pause."
            history = []
            record = design_round(request, approved_token=request_token(request), run_dir=run,
                                  history=history, client=designer_client(result, calls))
            self.assertEqual(history, [])
            attempt = Path(record["folder"])
            self.assertEqual(attempt.parent, run / "rounds/01/designer")
            self.assertEqual((attempt / "prompt.md").read_text(), calls[0]["input"])
            saved_request = json.loads((attempt / "request.json").read_text())
            self.assertEqual(saved_request["response_schema"], calls[0]["text"]["format"]["schema"])
            self.assertIn(original, calls[0]["input"])
            self.assertEqual(json.loads((attempt / "proposal.json").read_text()), result)
            explanation = (attempt / "design-rationale.md").read_text(encoding="utf-8")
            self.assertIn(result["sign_relationships"], explanation)
            self.assertIn(result["graphic_decisions"], explanation)
            self.assertIn(result["design_rationale"], explanation)
            spec = deepcopy(result["image_spec"])
            spec["visible_copy"] = ["Take a breath."]
            research = {"brief": brief, "proposal": result, "designer_record": record}
            preview = build_image_prompt(spec)
            self.assertNotIn("PRIVATE RATIONALE", preview)
            self.assertNotIn("HUMAN SIGN ANALYSIS", preview)
            self.assertNotIn("HUMAN DESIGN LINK", preview)
            settings = {"model": "mock-image", "size": "1024x1536", "quality": "medium"}
            fixture = Path(tmp) / "fixture.png"
            Image.new("RGB", (4, 4), "white").save(fixture)
            image_calls = []
            def generate(**kwargs):
                image_calls.append(kwargs)
                requests = list((run / "rounds/01/image").glob("*/request.json"))
                self.assertEqual(len(requests), 1)
                self.assertEqual(json.loads(requests[0].read_text()), kwargs)
                return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(fixture.read_bytes()).decode())])
            entry = generate_round(spec, research, settings,
                                   approved_token=review_token(spec, research, settings, image_prompt=preview),
                                   history=history, revision={}, client=SimpleNamespace(images=SimpleNamespace(generate=generate)))
            self.assertEqual(entry["image_prompt"], preview)
            self.assertEqual(image_calls[0]["prompt"], preview)
            image_attempt = Path(entry["image_path"]).parent
            self.assertEqual(json.loads((image_attempt / "image-spec.json").read_text()), spec)
            self.assertEqual(json.loads((attempt / "proposal.json").read_text()), result)
            self.assertEqual(load_rounds(run), history)
            revision = {"parent_folder": entry["folder"], "previous_proposal": result,
                        "previous_image_spec": spec, "previous_prompt": preview}
            review = build_designer_request(brief, revision, original_user_request=original, image_path=entry["image_path"])
            reviewed = design_round(review, approved_token=request_token(review), run_dir=run,
                                    history=history, client=designer_client(result, calls))
            self.assertTrue((Path(reviewed["folder"]) / "design-rationale.md").is_file())
            content = calls[-1]["input"][0]["content"]
            self.assertEqual(base64.b64decode(content[1]["image_url"].split(",")[1]), fixture.read_bytes())
            self.assertEqual(Path(reviewed["folder"]).parent, run / "rounds/02/designer")
            self.assertEqual((Path(reviewed["folder"]) / "input.png").read_bytes(), fixture.read_bytes())
            self.assertEqual(load_rounds(run), history)
            with self.assertRaises(ValueError):
                design_round(request, approved_token=request_token(request), run_dir=run, history=[],
                             client=designer_client(result, calls))
            self.assertEqual(len(calls), 2)

    def test_clarification_and_sources_stop_generation_and_preserve_attempts(self):
        with TemporaryDirectory() as tmp:
            run = start_run({}, output_dir=tmp)
            request = build_designer_request({})
            calls = []
            ready = proposal()
            first = design_round(request, approved_token=request_token(request), run_dir=run, history=[],
                                 client=designer_client(ready, calls))
            for status, field in [("needs_clarification", "clarification_questions"), ("needs_sources", "source_requirements")]:
                value = {**proposal(), "status": status, "image_spec": None, field: ["Required information"]}
                validate_proposal(value)
                record = design_round(request, approved_token=request_token(request), run_dir=run, history=[],
                                      client=designer_client(value, calls))
                with self.assertRaises(ValueError):
                    review_token(image_spec(), {"proposal": value}, {})
                self.assertEqual(json.loads((run / "run.json").read_text())["status"], status)
                rationale = (Path(record["folder"]) / "design-rationale.md").read_text()
                self.assertIn(status, rationale)
                self.assertIn("Required information", rationale)
            self.assertEqual(len(list((run / "rounds/01/designer").glob("*/request.json"))), 3)
            self.assertFalse((run / "rounds/01/image").exists())
            research = {"proposal": ready, "designer_record": first}
            spec = image_spec()
            with self.assertRaises(ValueError):
                generate_round(spec, research, {}, approved_token=review_token(spec, research, {}),
                               history=[], revision={})

    def test_failed_calls_are_saved_without_retry(self):
        with TemporaryDirectory() as tmp:
            run = start_run({}, output_dir=tmp)
            request = build_designer_request({})
            calls = []
            def fail(**kwargs):
                calls.append(kwargs)
                self.assertTrue(list(run.glob("rounds/01/designer/*/request.json")))
                raise RuntimeError("SENSITIVE FAILURE BODY")
            with self.assertRaises(RuntimeError):
                design_round(request, approved_token=request_token(request), run_dir=run, history=[],
                             client=SimpleNamespace(responses=SimpleNamespace(create=fail)))
            response = next(run.glob("rounds/01/designer/*/response.json"))
            self.assertEqual(json.loads(response.read_text())["status"], "failed")
            self.assertNotIn("SENSITIVE FAILURE BODY", response.read_text())
            self.assertEqual(len(calls), 1)
            value = proposal()
            record = design_round(request, approved_token=request_token(request), run_dir=run, history=[],
                                  client=designer_client(value, []))
            research = {"proposal": value, "designer_record": record}
            spec = image_spec()
            history = []
            def fail_image(**kwargs):
                raise RuntimeError("SENSITIVE IMAGE BODY")
            with self.assertRaises(RuntimeError):
                generate_round(spec, research, {}, approved_token=review_token(spec, research, {}),
                               history=history, revision={},
                               client=SimpleNamespace(images=SimpleNamespace(generate=fail_image)))
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["status"], "failed")
            self.assertEqual(load_rounds(run), history)
            self.assertEqual(json.loads((run / "run.json").read_text())["status"], "image_failed")
            response = next(run.glob("rounds/01/image/*/response.json"))
            self.assertNotIn("SENSITIVE IMAGE BODY", response.read_text())

    def test_schema_and_templates_are_part_of_designer_preview(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp) / "prompts"
            shutil.copytree(prompt_files.PROMPT_DIR, folder)
            templates = Path(tmp) / "templates"
            shutil.copytree(prompt_files.TEMPLATE_DIR, templates)
            with patch.object(prompt_files, "PROMPT_DIR", folder), \
                 patch.object(prompt_files, "TEMPLATE_DIR", templates):
                run = start_run({}, output_dir=tmp)
                request = build_designer_request({})
                token = request_token(request)
                for filename in ["designer-input-template.md", "designer.md", "designer-response.schema.json"]:
                    path = (templates if filename.endswith("-template.md") else folder) / filename
                    original = path.read_text()
                    if filename.endswith(".json"):
                        value = json.loads(original)
                        value["properties"]["status"]["description"] += " Updated."
                        path.write_text(json.dumps(value))
                    else:
                        path.write_text(original + "\nUpdated instructions.\n")
                    with self.assertRaises(ValueError):
                        design_round(request, approved_token=token, run_dir=run, history=[],
                                     client=designer_client(proposal(), []))
                    path.write_text(original)
                self.assertFalse((run / "rounds").exists())
                with self.assertRaises(ValueError):
                    render_template("image-generation-input-template.md", {})
                no_text = {**image_spec(), "visible_copy": []}
                self.assertIn("# Exact visible text\n\n[]", build_image_prompt(no_text))
                with self.assertRaises(ValueError):
                    build_designer_request({}, {})


if __name__ == "__main__":
    unittest.main()
