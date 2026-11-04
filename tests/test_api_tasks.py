"""Contract tests: validation, conflicts, credential handling, and preferences."""

from __future__ import annotations

import json
from unittest.mock import patch

from corpus_atelier.artifacts.records import read_json, write_json
from corpus_atelier.prompt_session.records import SESSION_FILE
from tests.api_support import ApiTestCase, upload_payload


class TaskContractTests(ApiTestCase):
    def test_a_blank_prompt_is_rejected_with_one_error_shape(self):
        response = self.client.post(
            "/api/v1/tasks", json={"entry_mode": "prompt", "prompt_text": "   "},
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(set(payload), {"error"})
        self.assertEqual(payload["error"]["code"], "invalid_request")
        self.assertIsNone(payload["error"]["details"])

    def test_an_unsupported_ratio_is_rejected(self):
        response = self.client.post(
            "/api/v1/tasks",
            json={
                "entry_mode": "prompt",
                "prompt_text": "A poster.",
                "settings": {"aspect_ratio": [7, 3]},
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.error_code(response), "invalid_request")

    def test_an_unknown_task_is_not_found(self):
        response = self.client.get("/api/v1/tasks/20260101T000000Z_deadbeef")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.error_code(response), "not_found")

    def test_a_stale_revision_is_a_conflict(self):
        run_id = self.create_task()
        response = self.client.post(
            f"/api/v1/tasks/{run_id}/prompt-revisions",
            json={"prompt_text": "A newer prompt.", "expected_revision": "rev_missing"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.error_code(response), "conflict")

    def test_a_new_revision_becomes_current(self):
        run_id = self.create_task()
        revision = self.task_payload(run_id)["session"]["current_prompt_revision_id"]
        response = self.client.post(
            f"/api/v1/tasks/{run_id}/prompt-revisions",
            json={"prompt_text": "A calmer poster.", "expected_revision": revision},
        )
        self.assertEqual(response.status_code, 200, response.text)
        session = response.json()["session"]
        self.assertEqual(len(session["prompt_revisions"]), 2)
        self.assertEqual(session["prompt_revisions"][-1]["origin"], "manual_edit")
        self.assertNotEqual(session["current_prompt_revision_id"], revision)

    def test_the_credential_is_write_only(self):
        secret = "sk-contract-test-1234"
        with patch(
            "corpus_atelier.api.routes_settings._test_connection", return_value=False,
        ):
            saved = self.client.put(
                "/api/v1/settings/credential",
                json={"api_key": secret, "remember": True},
            )
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertNotIn(secret, saved.text)
            self.assertEqual(saved.json()["credential"]["masked"], "••••1234")

            settings = self.client.get("/api/v1/settings")
            self.assertNotIn(secret, settings.text)
            self.assertTrue(settings.json()["credential"]["configured"])

            tested = self.client.post(
                "/api/v1/settings/credential/test", json={"api_key": secret},
            )
            self.assertEqual(tested.status_code, 200)
            self.assertEqual(tested.json(), {"ok": False})
            self.assertNotIn(secret, tested.text)

        self.assertIn(secret, self.paths.env_path.read_text(encoding="utf-8"))

    def test_clearing_the_credential_leaves_nothing_behind(self):
        with patch("corpus_atelier.api.routes_settings._test_connection", return_value=True):
            self.client.put(
                "/api/v1/settings/credential",
                json={"api_key": "sk-to-be-removed", "remember": True},
            )
        response = self.client.delete("/api/v1/settings/credential")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["credential"]["configured"])
        self.assertNotIn("sk-to-be-removed", self.paths.env_path.read_text(encoding="utf-8"))

    def test_settings_describe_the_catalog_the_interface_needs(self):
        payload = self.client.get("/api/v1/settings").json()
        self.assertIn("gpt-image-2", [item["model"] for item in payload["image_models"]])
        self.assertIn([16, 9], payload["ratios"])
        self.assertEqual(
            {item["id"] for item in payload["languages"]}, {"en", "zh-CN"},
        )
        self.assertTrue(payload["text_models"][0]["reasoning_efforts"])

    def test_a_language_switch_leaves_stored_prompts_alone(self):
        run_id = self.create_task("A quiet poster of a paper lantern.")
        before = self.task_payload(run_id)["session"]["prompt_revisions"][0]
        response = self.client.put(
            "/api/v1/settings/language", json={"language": "zh-CN"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["language"], "zh-CN")
        after = self.task_payload(run_id)["session"]["prompt_revisions"][0]
        self.assertEqual(before["prompt_text"], after["prompt_text"])
        self.assertEqual(json.loads(self.paths.preferences_path.read_text("utf-8")), {
            "language": "zh-CN",
        })

    def test_an_unsupported_language_is_rejected(self):
        response = self.client.put(
            "/api/v1/settings/language", json={"language": "fr"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.error_code(response), "invalid_request")

    def test_an_interrupted_image_run_reports_an_unknown_outcome(self):
        run_id = self.create_task()
        self.prepare_attempt(run_id)
        run_dir = self.runtime.run_dir(run_id)
        session = read_json(run_dir / SESSION_FILE)
        session["image_attempts"][0]["status"] = "outcome_unknown"
        session["image_attempts"][0]["outcome_unknown"] = True
        write_json(run_dir / SESSION_FILE, session)
        manifest = read_json(run_dir / "manifest.json")
        manifest["status"] = "generating_image"
        write_json(run_dir / "manifest.json", manifest)

        payload = self.task_payload(run_id)
        self.assertEqual(payload["task"]["status"], "outcome_unknown")
        self.assertTrue(payload["session"]["image_attempts"][0]["outcome_unknown"])

    def test_an_upload_is_accepted_as_base64_and_never_returns_a_path(self):
        run_id = self.create_task()
        response = self.client.post(
            f"/api/v1/tasks/{run_id}/uploads",
            json={**upload_payload(), "role": "reference"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        upload = response.json()["session"]["uploads"][0]
        self.assertNotIn("path", upload)
        self.assertTrue(upload["media_url"].startswith("/api/v1/tasks/"))

    def test_deleting_a_task_removes_its_workspace(self):
        run_id = self.create_task()
        response = self.client.delete(f"/api/v1/tasks/{run_id}")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            self.client.get(f"/api/v1/tasks/{run_id}").status_code, 404,
        )
