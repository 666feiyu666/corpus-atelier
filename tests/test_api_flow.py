"""Contract tests for the session flows the first pass left uncovered.

Image-started extraction, canvas changes, revision restore, proposal adoption,
and refinement against a source. All offline: the same fake providers run behind
the real application services.
"""

from __future__ import annotations

from tests.api_support import ApiTestCase, png_bytes, upload_payload


class FlowContractTests(ApiTestCase):
    def create_image_task(self) -> str:
        response = self.client.post(
            "/api/v1/tasks",
            json={
                "entry_mode": "image",
                "image": upload_payload("source.png", png_bytes()),
                "settings": {"image_quality": "medium"},
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        run_id = response.json()["task"]["run_id"]
        self.wait_status(run_id, "prompt_ready")
        return run_id

    def generate_one_result(self, run_id: str) -> dict:
        attempt = self.prepare_attempt(run_id)
        submitted = self.client.post(
            f"/api/v1/tasks/{run_id}/image-attempts/{attempt['id']}/submit",
            json={"expected_digest": attempt["request_digest"]},
        )
        self.assertEqual(submitted.status_code, 202, submitted.text)
        payload = self.wait_for_results(run_id, 1)
        # The result exists before the worker fully settles; a following call must
        # not race the runtime's running flag.
        self.wait_idle(run_id)
        return payload["session"]["image_results"][-1]

    def test_an_image_started_task_extracts_a_prompt(self):
        run_id = self.create_image_task()
        payload = self.task_payload(run_id)
        self.assertEqual(payload["session"]["entry_mode"], "image")
        revision = payload["session"]["prompt_revisions"][0]
        self.assertEqual(revision["origin"], "vision_extraction")
        self.assertTrue(revision["prompt_text"])
        self.assertTrue(revision["negative_prompt"] or revision["uncertainties"])
        # The source keeps its own canvas; no image call has happened yet.
        self.assertEqual(self.image_provider.calls, 0)
        self.assertEqual(payload["session"]["image_results"], [])
        self.assertEqual(payload["session"]["settings"]["canvas_origin"], "source")

    def test_the_canvas_can_be_changed_and_restored(self):
        run_id = self.create_image_task()
        changed = self.client.post(
            f"/api/v1/tasks/{run_id}/canvas", json={"ratio": [9, 16]},
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        settings = changed.json()["session"]["settings"]
        self.assertEqual(settings["aspect_ratio"], [9, 16])
        self.assertEqual(settings["canvas_origin"], "user")

        restored = self.client.post(
            f"/api/v1/tasks/{run_id}/canvas", json={"ratio": None},
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()["session"]["settings"]["canvas_origin"], "source")

    def test_an_unsupported_ratio_is_rejected(self):
        run_id = self.create_image_task()
        response = self.client.post(
            f"/api/v1/tasks/{run_id}/canvas", json={"ratio": [5, 7]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.error_code(response), "invalid_request")

    def test_a_revision_can_be_restored_as_a_new_revision(self):
        run_id = self.create_task()
        first = self.task_payload(run_id)["session"]["current_prompt_revision_id"]
        edited = self.client.post(
            f"/api/v1/tasks/{run_id}/prompt-revisions",
            json={"prompt_text": "A calmer second revision.", "expected_revision": first},
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        current = edited.json()["session"]["current_prompt_revision_id"]
        self.assertNotEqual(current, first)

        restored = self.client.post(
            f"/api/v1/tasks/{run_id}/prompt-revisions/{first}/restore",
            json={"expected_revision": current},
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        session = restored.json()["session"]
        newest = session["prompt_revisions"][-1]
        self.assertEqual(newest["origin"], "manual_edit")
        self.assertEqual(newest["restored_from"], first)
        self.assertEqual(session["current_prompt_revision_id"], newest["id"])
        self.assertEqual(len(session["prompt_revisions"]), 3)

    def test_a_proposal_is_adopted_only_against_its_base_revision(self):
        run_id = self.create_task()
        created = self.client.post(
            f"/api/v1/tasks/{run_id}/prompt-proposals", json={"kind": "generate"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        proposal = created.json()["proposal"]
        self.assertEqual(proposal["kind"], "generate")
        self.assertTrue(proposal["prompt_text"])
        # Preparing a proposal applies nothing.
        self.assertEqual(
            created.json()["session"]["current_prompt_revision_id"],
            proposal["base_revision_id"],
        )

        stale = self.client.post(
            f"/api/v1/tasks/{run_id}/prompt-proposals/{proposal['id']}/adopt",
            json={"expected_revision": "rev_missing"},
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(self.error_code(stale), "conflict")

        adopted = self.client.post(
            f"/api/v1/tasks/{run_id}/prompt-proposals/{proposal['id']}/adopt",
            json={"expected_revision": proposal["base_revision_id"]},
        )
        self.assertEqual(adopted.status_code, 200, adopted.text)
        session = adopted.json()["session"]
        newest = session["prompt_revisions"][-1]
        self.assertEqual(newest["origin"], "assistant_revision")
        self.assertEqual(newest["prompt_text"], proposal["prompt_text"])
        self.assertTrue(
            next(
                item for item in session["prompt_proposals"]
                if item["id"] == proposal["id"]
            )["adopted_revision_id"]
        )

    def test_an_edit_proposal_requires_an_instruction(self):
        run_id = self.create_task()
        response = self.client.post(
            f"/api/v1/tasks/{run_id}/prompt-proposals", json={"kind": "edit"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.error_code(response), "invalid_request")

    def test_refining_a_result_proposes_a_revision(self):
        run_id = self.create_image_task()
        result = self.generate_one_result(run_id)
        before = self.task_payload(run_id)["session"]["current_prompt_revision_id"]

        queued = self.client.post(
            f"/api/v1/tasks/{run_id}/refine-turns",
            json={"result_image_id": result["id"]},
        )
        self.assertEqual(queued.status_code, 202, queued.text)
        payload = self.wait_status(run_id, "prompt_ready")
        session = payload["session"]
        newest = session["prompt_revisions"][-1]
        self.assertNotEqual(newest["id"], before)
        self.assertEqual(newest["origin"], "assistant_revision")
        # The refinement reply is visible in the conversation, with its differences.
        message = session["messages"][-1]
        self.assertEqual(message["role"], "assistant")
        self.assertTrue(message["discrepancies"])
        self.assertEqual(len(self.text_provider.refine_calls), 1)

    def test_refining_a_prompt_started_task_is_refused(self):
        run_id = self.create_task()
        result = self.generate_one_result(run_id)
        response = self.client.post(
            f"/api/v1/tasks/{run_id}/refine-turns",
            json={"result_image_id": result["id"]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.error_code(response), "invalid_request")

    def test_a_mask_can_be_attached_and_used_in_a_request(self):
        run_id = self.create_task()
        source = self.client.post(
            f"/api/v1/tasks/{run_id}/uploads",
            json={**upload_payload("source.png"), "role": "reference"},
        )
        self.assertEqual(source.status_code, 201, source.text)
        mask = self.client.post(
            f"/api/v1/tasks/{run_id}/uploads",
            json={**upload_payload("mask.png", self.mask_bytes()), "role": "mask"},
        )
        self.assertEqual(mask.status_code, 201, mask.text)
        uploads = mask.json()["session"]["uploads"]
        source_id = next(item["id"] for item in uploads if item["role"] == "reference")
        mask_id = next(item["id"] for item in uploads if item["role"] == "mask")

        revision = self.task_payload(run_id)["session"]["current_prompt_revision_id"]
        prepared = self.client.post(
            f"/api/v1/tasks/{run_id}/image-attempts",
            json={
                "action": "edit",
                "source_image_id": source_id,
                "edit_instruction": "Warm only the lantern light.",
                "mask_image_id": mask_id,
                "expected_revision": revision,
            },
        )
        self.assertEqual(prepared.status_code, 201, prepared.text)
        attempt = prepared.json()["attempt"]
        self.assertEqual(attempt["action"], "edit")
        self.assertEqual(attempt["mask_image_id"], mask_id)
        self.assertTrue(attempt["mask_media_url"])
        self.assertEqual(attempt["reference_image_ids"][0], source_id)

    @staticmethod
    def mask_bytes(size=(64, 48)) -> bytes:
        from io import BytesIO

        from PIL import Image

        buffer = BytesIO()
        image = Image.new("RGBA", size, (0, 0, 0, 255))
        for x in range(size[0] // 2):
            for y in range(size[1]):
                image.putpixel((x, y), (0, 0, 0, 0))
        image.save(buffer, format="PNG")
        return buffer.getvalue()
