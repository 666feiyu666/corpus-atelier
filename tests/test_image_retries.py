"""Interrupted image calls remain traceable and require explicit same-round retries."""
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from fixtures import proposal, designer_client
from graphic_design_helper.records import start_run
from graphic_design_helper.prompt_builder import build_designer_request, request_token
from graphic_design_helper.workflow import design_round, generate_round, review_token, load_rounds


class ImageRetryTests(unittest.TestCase):
    def setup_run(self, tmp):
        run = start_run({}, output_dir=tmp)
        request = build_designer_request({})
        value = proposal()
        record = design_round(request, approved_token=request_token(request), run_dir=run,
                              history=[], client=designer_client(value, []))
        return run, value["image_spec"], {"proposal": value, "designer_record": record}

    def test_interrupt_and_explicit_retry_preserve_attempt_and_round(self):
        with TemporaryDirectory() as tmp:
            run, spec, research = self.setup_run(tmp)
            history, calls = [], []
            token = review_token(spec, research, {})
            def stop(**kwargs):
                calls.append(kwargs)
                raise KeyboardInterrupt()
            with self.assertRaises(KeyboardInterrupt):
                generate_round(spec, research, {}, approved_token=token, history=history,
                               revision={}, client=SimpleNamespace(images=SimpleNamespace(generate=stop)))
            self.assertEqual(len(calls), 1)
            self.assertEqual(history[0]["status"], "interrupted")
            self.assertEqual(history[0]["remote_outcome"], "unknown")
            self.assertEqual(json.loads((run / "run.json").read_text())["status"], "image_interrupted")
            old = run / "rounds/01/image/attempt_01/response.json"
            old_bytes = old.read_bytes()
            self.assertEqual(json.loads(old_bytes)["status"], "interrupted")
            history = load_rounds(run)
            for extras in ({}, {"retry": True}, {"retry": True, "retry_reason": "Retry"}):
                changed = {**spec, "composition": "Changed"} if extras.get("retry_reason") else spec
                with self.assertRaises(ValueError):
                    generate_round(changed, research, {}, approved_token=review_token(changed, research, {}),
                                   history=history, revision={}, **extras)
            def success(**kwargs):
                calls.append(kwargs)
                return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(
                    b"\x89PNG\r\n\x1a\nfixture").decode())])
            result = generate_round(spec, research, {}, approved_token=token, history=history,
                                    revision={}, retry=True, retry_reason="Explicitly resend after interruption",
                                    client=SimpleNamespace(images=SimpleNamespace(generate=success)))
            self.assertEqual(len(calls), 2)
            self.assertEqual(len(history), 1)
            self.assertEqual(result["round"], 1)
            self.assertEqual(result["status"], "generated")
            self.assertEqual(Path(result["image_path"]).parent.name, "attempt_02")
            self.assertEqual(result["previous_attempts"][0]["status"], "interrupted")
            self.assertEqual(old.read_bytes(), old_bytes)
            self.assertEqual(load_rounds(run), history)
            with self.assertRaises(ValueError):
                generate_round(spec, research, {}, approved_token=token, history=history,
                               revision={}, retry=True, retry_reason="Duplicate")

    def test_failed_retries_count_toward_call_limit(self):
        with TemporaryDirectory() as tmp:
            run, spec, research = self.setup_run(tmp)
            history, calls = [], []
            def fail(**kwargs):
                calls.append(kwargs)
                raise RuntimeError("Do not save sensitive exception text")
            for i in range(3):
                with self.assertRaises(RuntimeError):
                    generate_round(spec, research, {}, approved_token=review_token(spec, research, {}),
                                   history=history, revision={}, retry=i > 0, retry_reason="Explicit retry",
                                   client=SimpleNamespace(images=SimpleNamespace(generate=fail)))
            self.assertEqual(len(calls), 3)
            self.assertEqual(len(history), 1)
            self.assertEqual(len(history[0]["previous_attempts"]), 2)
            self.assertEqual(len(list((run / "rounds/01/image").glob("attempt_*"))), 3)
            with self.assertRaises(ValueError):
                generate_round(spec, research, {}, approved_token=review_token(spec, research, {}),
                               history=history, revision={}, retry=True, retry_reason="Fourth call")
            self.assertNotIn("Do not save sensitive", (run / "rounds/01/round.json").read_text())
