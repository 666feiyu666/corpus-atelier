"""Shared setup for the HTTP contract tests: a real app over a temporary store."""

from __future__ import annotations

import base64
from io import BytesIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from corpus_atelier.api import TaskRuntime, create_app
from corpus_atelier.config.paths import ProductPaths
from tests.fakes import FakeImageProvider
from tests.test_prompt_session import PromptTextProvider


TEXT_MODEL = "gpt-5.6-luna"
IMAGE_MODEL = "gpt-image-2"


class ApiTextProvider(PromptTextProvider):
    """The recording text fake, under a model name the catalog accepts."""

    model = TEXT_MODEL


class ApiImageProvider(FakeImageProvider):
    model = IMAGE_MODEL
    quality = "medium"


def png_bytes(size=(64, 48), color=(30, 70, 110)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def upload_payload(name="source.png", data: bytes | None = None) -> dict:
    return {
        "name": name,
        "data_base64": base64.b64encode(data if data is not None else png_bytes()).decode(),
    }


class ApiTestCase(unittest.TestCase):
    """One app, one temporary task store, offline providers, per test."""

    def setUp(self):
        self._directory = TemporaryDirectory()
        root = Path(self._directory.name)
        self.root = root
        self.paths = ProductPaths(
            tasks_root=root / "tasks",
            env_path=root / ".env",
            preferences_path=root / "settings.json",
            corpus_db_path=root / "corpus.sqlite3",
            corpus_media_root=root / "corpus-media",
        )
        # Provider calls must never leave the test process: a dummy key in the
        # runtime, and no ambient key that a real adapter could pick up.
        self._environment = patch.dict(os.environ, {"OPENAI_API_KEY": ""})
        self._environment.start()
        self.addCleanup(self._environment.stop)
        self.text_provider = ApiTextProvider()
        self.image_provider = ApiImageProvider()
        self.runtime = TaskRuntime(paths=self.paths, providers=self._providers)
        self.runtime.set_session_key("sk-contract-test-key")
        self.app = create_app(runtime=self.runtime, resume=False, origins=[])
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.client.__enter__()

    def _providers(self, selection, api_key):
        return self.text_provider, self.image_provider

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.runtime.shutdown()
        self._directory.cleanup()

    # --- helpers --------------------------------------------------------

    def create_task(self, prompt: str = "A quiet poster of a paper lantern.", **extra) -> str:
        body = {"entry_mode": "prompt", "prompt_text": prompt}
        body.update(extra)
        response = self.client.post("/api/v1/tasks", json=body)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["task"]["run_id"]

    def task_payload(self, run_id: str) -> dict:
        response = self.client.get(f"/api/v1/tasks/{run_id}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def wait_status(self, run_id: str, status: str, timeout: float = 15.0) -> dict:
        deadline = time.time() + timeout
        payload = self.task_payload(run_id)
        while time.time() < deadline:
            payload = self.task_payload(run_id)
            if payload["task"]["status"] == status:
                return payload
            time.sleep(0.05)
        self.fail(f"task {run_id} stayed {payload['task']['status']!r}, wanted {status!r}")

    def wait_for_results(self, run_id: str, count: int = 1, timeout: float = 15.0) -> dict:
        """Wait for a completed image call.

        The task status alone is not enough: it is already ``prompt_ready`` before
        a submission starts, so a status check can return before the result exists.
        """
        deadline = time.time() + timeout
        payload = self.task_payload(run_id)
        while time.time() < deadline:
            payload = self.task_payload(run_id)
            if len(payload["session"]["image_results"]) >= count:
                return payload
            time.sleep(0.05)
        self.fail(
            f"task {run_id} produced "
            f"{len(payload['session']['image_results'])} result(s), wanted {count}"
        )

    def wait_idle(self, run_id: str, timeout: float = 15.0) -> dict:
        """Wait until the runtime has no in-flight work for this task."""
        deadline = time.time() + timeout
        payload = self.task_payload(run_id)
        while time.time() < deadline:
            payload = self.task_payload(run_id)
            if not payload["task"]["running"]:
                return payload
            time.sleep(0.05)
        self.fail(f"task {run_id} stayed running for more than {timeout}s")

    def prepare_attempt(self, run_id: str, **extra) -> dict:
        revision = self.task_payload(run_id)["session"]["current_prompt_revision_id"]
        body = {"action": "generate", "expected_revision": revision}
        body.update(extra)
        response = self.client.post(f"/api/v1/tasks/{run_id}/image-attempts", json=body)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["attempt"]

    @staticmethod
    def error_code(response) -> str:
        return response.json()["error"]["code"]
