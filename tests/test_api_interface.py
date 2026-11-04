"""Contract tests: one process can serve both the API and the built SPA."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient

from corpus_atelier.api import TaskRuntime, create_app
from corpus_atelier.api.app import SERVICE_HEADER, SERVICE_NAME
from corpus_atelier.config.paths import ProductPaths
from tests.api_support import ApiImageProvider, ApiTextProvider


class InterfaceServingTests(unittest.TestCase):
    def setUp(self):
        self._directory = TemporaryDirectory()
        root = Path(self._directory.name)
        self.public = root / "public"
        (self.public / "_nuxt").mkdir(parents=True)
        (self.public / "index.html").write_text(
            "<!doctype html><title>Atelier shell</title>", encoding="utf-8",
        )
        (self.public / "_nuxt" / "entry.js").write_text(
            "console.log('atelier')", encoding="utf-8",
        )
        self.paths = ProductPaths(
            tasks_root=root / "tasks",
            env_path=root / ".env",
            preferences_path=root / "settings.json",
            corpus_db_path=root / "corpus.sqlite3",
            corpus_media_root=root / "corpus-media",
        )
        self.runtime = TaskRuntime(
            paths=self.paths,
            providers=lambda selection, key: (ApiTextProvider(), ApiImageProvider()),
        )
        self.app = create_app(
            runtime=self.runtime, resume=False, interface_dir=self.public,
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.runtime.shutdown()
        self._directory.cleanup()

    def test_the_root_serves_the_spa_shell(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Atelier shell", response.text)

    def test_an_unknown_client_route_falls_back_to_the_shell(self):
        response = self.client.get("/tasks/20260101T000000Z_deadbeef")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Atelier shell", response.text)

    def test_built_assets_are_served(self):
        response = self.client.get("/_nuxt/entry.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("console.log", response.text)

    def test_the_api_still_wins_over_the_shell(self):
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        response = self.client.get("/api/v1/tasks")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"tasks": []})

    def test_an_unknown_api_path_stays_a_json_error(self):
        response = self.client.get("/api/v1/nope")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "not_found")
        self.assertNotIn("Atelier shell", response.text)

    def test_a_path_traversal_attempt_gets_the_shell_not_the_file(self):
        secret = self.public.parent / "secret.txt"
        secret.write_text("do not serve this", encoding="utf-8")
        response = self.client.get("/../secret.txt")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Atelier shell", response.text)
        self.assertNotIn("do not serve this", response.text)

    def test_without_an_interface_the_api_is_unchanged(self):
        api_only = create_app(runtime=self.runtime, resume=False)
        with TestClient(api_only, raise_server_exceptions=False) as client:
            self.assertEqual(client.get("/").status_code, 404)
            self.assertEqual(client.get("/api/v1/health").status_code, 200)

    def test_health_identifies_the_service_and_its_profile(self):
        response = self.client.get("/api/v1/health")
        payload = response.json()
        self.assertEqual(payload["service"], SERVICE_NAME)
        self.assertEqual(payload["profile"], "daily")
        self.assertEqual(response.headers[SERVICE_HEADER], SERVICE_NAME)

    def test_an_error_response_carries_the_service_header(self):
        response = self.client.get("/api/v1/nope")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.headers[SERVICE_HEADER], SERVICE_NAME)

    def test_a_loopback_origin_on_any_port_may_call_the_api(self):
        origin = "http://127.0.0.1:4545"
        response = self.client.get("/api/v1/health", headers={"Origin": origin})
        self.assertEqual(response.headers.get("access-control-allow-origin"), origin)

    def test_a_non_loopback_origin_is_still_refused(self):
        response = self.client.get(
            "/api/v1/health", headers={"Origin": "http://example.test"},
        )
        self.assertIsNone(response.headers.get("access-control-allow-origin"))
