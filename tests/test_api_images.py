"""Contract tests: frozen requests, single execution, and media containment."""

from __future__ import annotations

from io import BytesIO

from PIL import Image

from tests.api_support import ApiTestCase, png_bytes, upload_payload


def mask_png(size=(64, 48)) -> bytes:
    """A mask with a fully transparent left half: opaque kept, transparent redone."""
    buffer = BytesIO()
    image = Image.new("RGBA", size, (0, 0, 0, 255))
    for x in range(size[0] // 2):
        for y in range(size[1]):
            image.putpixel((x, y), (0, 0, 0, 0))
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class ImageContractTests(ApiTestCase):
    def submit(self, run_id: str, attempt: dict, digest: str | None = None):
        return self.client.post(
            f"/api/v1/tasks/{run_id}/image-attempts/{attempt['id']}/submit",
            json={"expected_digest": digest or attempt["request_digest"]},
        )

    def test_prepare_then_submit_calls_the_provider_once(self):
        run_id = self.create_task()
        attempt = self.prepare_attempt(run_id)
        self.assertEqual(attempt["status"], "prepared")
        self.assertTrue(attempt["request_text"])
        self.assertEqual(attempt["source_image_id"], None)

        response = self.submit(run_id, attempt)
        self.assertEqual(response.status_code, 202, response.text)
        payload = self.wait_status(run_id, "prompt_ready")
        self.assertEqual(len(payload["session"]["image_results"]), 1)
        self.assertEqual(self.image_provider.calls, 1)
        result = payload["session"]["image_results"][0]
        self.assertEqual(result["request_text"], attempt["request_text"])

    def test_a_second_submit_is_a_conflict_and_never_reaches_the_provider(self):
        run_id = self.create_task()
        attempt = self.prepare_attempt(run_id)
        self.assertEqual(self.submit(run_id, attempt).status_code, 202)
        self.wait_status(run_id, "prompt_ready")

        second = self.submit(run_id, attempt)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(self.error_code(second), "conflict")
        self.assertEqual(self.image_provider.calls, 1)

    def test_a_digest_mismatch_is_refused_before_any_call(self):
        run_id = self.create_task()
        attempt = self.prepare_attempt(run_id)
        response = self.submit(run_id, attempt, digest="0" * 64)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.image_provider.calls, 0)

    def test_the_frozen_request_does_not_follow_later_revisions(self):
        run_id = self.create_task()
        attempt = self.prepare_attempt(run_id)
        frozen_text = attempt["request_text"]
        frozen_digest = attempt["request_digest"]
        self.assertEqual(self.submit(run_id, attempt).status_code, 202)
        self.wait_status(run_id, "prompt_ready")

        revision = self.task_payload(run_id)["session"]["current_prompt_revision_id"]
        edited = self.client.post(
            f"/api/v1/tasks/{run_id}/prompt-revisions",
            json={"prompt_text": "A completely different prompt.", "expected_revision": revision},
        )
        self.assertEqual(edited.status_code, 200, edited.text)

        payload = self.task_payload(run_id)
        stored = next(
            item for item in payload["session"]["image_attempts"]
            if item["id"] == attempt["id"]
        )
        self.assertEqual(stored["request_text"], frozen_text)
        self.assertEqual(stored["request_digest"], frozen_digest)
        self.assertEqual(
            payload["session"]["image_results"][0]["request_text"], frozen_text,
        )

    def test_preparing_against_a_stale_revision_is_a_conflict(self):
        run_id = self.create_task()
        response = self.client.post(
            f"/api/v1/tasks/{run_id}/image-attempts",
            json={"action": "generate", "expected_revision": "rev_missing"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.error_code(response), "conflict")

    def test_an_edit_requires_a_source_and_an_instruction(self):
        run_id = self.create_task()
        revision = self.task_payload(run_id)["session"]["current_prompt_revision_id"]
        no_source = self.client.post(
            f"/api/v1/tasks/{run_id}/image-attempts",
            json={
                "action": "edit",
                "edit_instruction": "Warm the lantern light.",
                "expected_revision": revision,
            },
        )
        self.assertEqual(no_source.status_code, 400)
        self.assertEqual(self.error_code(no_source), "invalid_request")

    def test_an_unknown_reference_role_is_rejected(self):
        run_id = self.create_task()
        revision = self.task_payload(run_id)["session"]["current_prompt_revision_id"]
        response = self.client.post(
            f"/api/v1/tasks/{run_id}/image-attempts",
            json={
                "action": "generate",
                "reference_image_ids": ["img_missing"],
                "reference_roles": {"img_missing": "mood"},
                "expected_revision": revision,
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_the_media_route_serves_bytes_and_checks_the_digest(self):
        run_id = self.create_task()
        uploaded = self.client.post(
            f"/api/v1/tasks/{run_id}/uploads",
            json={**upload_payload(), "role": "reference"},
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        image = uploaded.json()["session"]["uploads"][0]
        media = self.client.get(image["media_url"])
        self.assertEqual(media.status_code, 200)
        self.assertEqual(media.headers["content-type"], "image/png")
        self.assertEqual(media.content, png_bytes())

        session = self.runtime.session(run_id)
        target = self.runtime.run_dir(run_id) / session["uploads"][0]["path"]
        target.write_bytes(b"changed after it was archived")
        self.assertEqual(self.client.get(image["media_url"]).status_code, 404)

    def test_the_media_route_rejects_an_unknown_image(self):
        run_id = self.create_task()
        response = self.client.get(f"/api/v1/tasks/{run_id}/media/img_unknown")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.error_code(response), "not_found")

    def test_an_upload_must_be_a_readable_image(self):
        run_id = self.create_task()
        response = self.client.post(
            f"/api/v1/tasks/{run_id}/uploads",
            json={"name": "notes.txt", "data_base64": "aGVsbG8=", "role": "reference"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.error_code(response), "invalid_request")

    def test_a_mask_preview_is_composited_over_its_source(self):
        run_id = self.create_task()
        uploaded = self.client.post(
            f"/api/v1/tasks/{run_id}/uploads",
            json={**upload_payload("source.png"), "role": "source_image"},
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        mask = self.client.post(
            f"/api/v1/tasks/{run_id}/uploads",
            json={**upload_payload("mask.png", mask_png()), "role": "mask"},
        )
        self.assertEqual(mask.status_code, 201, mask.text)
        uploads = mask.json()["session"]["uploads"]
        source_id = next(item["id"] for item in uploads if item["role"] == "source_image")
        mask_id = next(item["id"] for item in uploads if item["role"] == "mask")

        preview = self.client.get(
            f"/api/v1/tasks/{run_id}/mask-preview",
            params={"mask_id": mask_id, "source_id": source_id},
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.headers["content-type"], "image/png")

    def test_selecting_a_result_marks_it_active(self):
        run_id = self.create_task()
        attempt = self.prepare_attempt(run_id)
        self.assertEqual(self.submit(run_id, attempt).status_code, 202)
        payload = self.wait_status(run_id, "prompt_ready")
        result = payload["session"]["image_results"][0]
        self.assertTrue(result["is_active"])

        response = self.client.post(
            f"/api/v1/tasks/{run_id}/results/{result['id']}/select",
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["session"]["image_results"][0]["is_active"])

    def test_discarding_a_prepared_attempt_never_calls_the_provider(self):
        run_id = self.create_task()
        attempt = self.prepare_attempt(run_id)
        response = self.client.delete(
            f"/api/v1/tasks/{run_id}/image-attempts/{attempt['id']}",
        )
        self.assertEqual(response.status_code, 200, response.text)
        stored = response.json()["session"]["image_attempts"][0]
        self.assertEqual(stored["status"], "discarded")
        self.assertEqual(self.image_provider.calls, 0)

    def test_archiving_needs_a_label_and_copies_its_media(self):
        run_id = self.create_task()
        attempt = self.prepare_attempt(run_id)
        self.assertEqual(self.submit(run_id, attempt).status_code, 202)
        self.wait_status(run_id, "prompt_ready")
        # The first read seeds the packaged gallery; record the baseline.
        before = self.client.get("/api/v1/corpus/search").json()["total"]

        refused = self.client.post(f"/api/v1/tasks/{run_id}/archive", json={"tags": []})
        self.assertEqual(refused.status_code, 400)

        archived = self.client.post(
            f"/api/v1/tasks/{run_id}/archive", json={"tags": ["typographic"]},
        )
        self.assertEqual(archived.status_code, 201, archived.text)
        record = archived.json()["record"]
        self.assertEqual(record["source"]["kind"], "atelier")
        self.assertNotIn("path", record["image"])
        self.assertEqual(
            self.client.get(record["image"]["media_url"]).status_code, 200,
        )
        after = self.client.get("/api/v1/corpus/search").json()
        self.assertEqual(after["total"], before + 1)
        self.assertIn(record["id"], [item["id"] for item in after["records"]])
