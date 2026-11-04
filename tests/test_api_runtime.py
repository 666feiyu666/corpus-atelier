"""Contract tests for the task runtime: resume, single scheduling, credentials."""

from __future__ import annotations

import threading

from corpus_atelier.app.service import CorpusAtelierApplication
from tests.api_support import ApiTestCase, png_bytes


class RuntimeContractTests(ApiTestCase):
    def test_an_interrupted_extraction_resumes_after_startup(self):
        app = CorpusAtelierApplication(
            runs_root=self.paths.tasks_root,
            text_provider=self.text_provider,
            image_provider=self.image_provider,
        )
        try:
            result = app.start_from_image(
                ("source.png", png_bytes()), case_id="natural-language",
            )
            run_id = result.run_id
        finally:
            app.close()
        self.assertEqual(self.task_payload(run_id)["task"]["status"], "extracting")

        self.assertEqual(self.runtime.resume_recoverable(), 1)
        payload = self.wait_status(run_id, "prompt_ready")
        self.assertTrue(payload["session"]["prompt_revisions"][0]["prompt_text"])
        self.assertEqual(len(self.text_provider.extraction_calls), 1)

    def test_the_same_run_is_never_scheduled_twice(self):
        run_id = self.create_task()
        started = threading.Event()
        release = threading.Event()

        def work(_app):
            started.set()
            release.wait(5)

        try:
            self.assertTrue(self.runtime.schedule(run_id, work, api_key="sk-test"))
            self.assertTrue(started.wait(5))
            self.assertFalse(self.runtime.schedule(run_id, work, api_key="sk-test"))
        finally:
            release.set()

    def test_no_recoverable_work_is_scheduled_without_a_credential(self):
        app = CorpusAtelierApplication(
            runs_root=self.paths.tasks_root,
            text_provider=self.text_provider,
            image_provider=self.image_provider,
        )
        try:
            run_id = app.start_from_image(
                ("source.png", png_bytes()), case_id="natural-language",
            ).run_id
        finally:
            app.close()
        self.runtime.set_session_key(None)
        self.assertEqual(self.runtime.resume_recoverable(), 0)
        self.assertEqual(self.task_payload(run_id)["task"]["status"], "extracting")

    def test_the_credential_prefers_the_runtime_key_over_the_environment(self):
        self.runtime.set_session_key("sk-from-settings")
        credential = self.runtime.credential()
        self.assertIsNotNone(credential)
        self.assertEqual(credential.source, "session")
        self.assertEqual(credential.value, "sk-from-settings")
