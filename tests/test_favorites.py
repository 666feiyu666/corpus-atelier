"""Favorites keep a conversation and its prompts usable after the source is gone."""

import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.artifacts.hashing import digest_file
from corpus_atelier.artifacts.records import write_json
from corpus_atelier.favorites import FavoriteStore


CONVERSATION_ID = "20261003T013436Z_20f25936"
FIRST_ROUND = "20261003T020000Z_aaaaaaaa"
SECOND_ROUND = "20261003T030000Z_bbbbbbbb"
SINGLE_TASK = "20261003T040000Z_cccccccc"
NOW = "2026-10-03T01:34:36+00:00"
TEXT_MODEL = "gpt-5.6-luna"
IMAGE_MODEL = "gpt-image-2"


def _brief() -> dict:
    return {
        "content_language": "zh-CN",
        "deliverable": "国庆花艺海报",
        "purpose": "传递节日祝福。",
        "audience": "海报观看者。",
        "use_context": "节日宣传。",
        "exact_copy": ["欢度国庆"],
        "constraints": [],
        "preferences": ["东方审美"],
        "user_requirements": ["花篮必须有提手。"],
        "canvas": {"aspect_ratio": {"width": 2, "height": 3}},
    }


def _models() -> dict:
    return {
        "text": {
            "adapter": "test.TextProvider",
            "model": TEXT_MODEL,
            "reasoning_effort": "medium",
        },
        "image": {
            "adapter": "test.ImageProvider",
            "model": IMAGE_MODEL,
            "quality": "medium",
        },
    }


def _write_round(tasks: Path, run_id: str, *, revision: int, parent_id: str,
                 selected: str) -> None:
    run_dir = tasks / "natural-language" / run_id
    run_dir.mkdir(parents=True)
    write_json(run_dir / "brief.json", _brief())
    write_json(run_dir / "profile.json", {
        "name": "art-graphic", "objective": "art-led", "description": "",
    })
    candidates = []
    for index, candidate_id in enumerate(("c01", "c02"), 1):
        image_path = (
            run_dir / "candidates" / candidate_id
            / "generation" / "attempt_01" / "image.png"
        )
        image_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (120, 180), (20 * index, 40, 60)).save(
            image_path, format="PNG",
        )
        candidates.append({
            "candidate_id": candidate_id,
            "status": "generated",
            "direction_seed": {"label": f"设计方向 {index}"},
            "proposal": {
                "chosen_direction": f"第 {index} 个方向",
                "design_description": f"第 {index} 个视觉描述",
                "design_rationale": f"第 {index} 个理由",
            },
            "generation_prompt": (
                f"Render candidate {candidate_id} at revision {revision}."
            ),
            "generation_request": {
                "model": IMAGE_MODEL, "quality": "medium", "size": "1024x1536",
            },
            "image_path": str(image_path.resolve()),
            "image_sha256": digest_file(image_path),
        })
    write_json(run_dir / "candidates" / "index.json", candidates)
    write_json(run_dir / "selection" / "decision.json", {
        "selected_candidate_id": selected,
    })
    write_json(run_dir / "manifest.json", {
        "format_version": 2,
        "workflow_version": 18,
        "case_id": "natural-language",
        "run_id": run_id,
        "title": "国庆花艺海报",
        "created_at": NOW,
        "updated_at": NOW,
        "status": "completed",
        "conversation_parent_id": parent_id,
        "conversation_revision": revision,
        "artifacts": {
            "candidate_index": "candidates/index.json",
            "selection": "selection/decision.json",
            "brief": "brief.json",
        },
    })


def _write_conversation(tasks: Path) -> str:
    run_dir = tasks / "natural-language" / CONVERSATION_ID
    run_dir.mkdir(parents=True)
    brief = _brief()
    write_json(run_dir / "input" / "request.txt", "设计一张国庆花艺海报")
    write_json(run_dir / "brief.json", brief)
    write_json(run_dir / "conversation.json", {
        "format_version": 8,
        "profile": "art-graphic",
        "content_language": "zh-CN",
        "discussion_language": "zh-CN",
        "language_source_request": "设计一张国庆花艺海报",
        "messages": [
            {"id": "m1", "role": "user", "text": "设计一张国庆花艺海报",
             "attachments": [], "created_at": NOW},
            {"id": "m2", "role": "assistant", "text": "好的，先确认用途。",
             "attachments": [], "created_at": NOW},
        ],
        "effective_request": (
            "User-confirmed design brief:\n"
            + json.dumps(brief, ensure_ascii=False)
        ),
        "open_questions": [],
        "revision": 2,
        "discussion_revision": 0,
        "rounds": [
            {"run_id": FIRST_ROUND, "revision": 1, "created_at": NOW},
            {"run_id": SECOND_ROUND, "revision": 2, "created_at": NOW},
        ],
        "pending": None,
        "user_requirements": ["花篮必须有提手。"],
        "design_brief": brief,
        "brief_revision": 2,
        "brief_history": [
            {"revision": 1, "brief": brief, "origin": "user",
             "based_on": 0, "created_at": NOW},
            {"revision": 2, "brief": brief, "origin": "user",
             "based_on": 1, "created_at": NOW},
        ],
    })
    write_json(run_dir / "manifest.json", {
        "format_version": 2,
        "workflow_version": 18,
        "case_id": "natural-language",
        "run_id": CONVERSATION_ID,
        "title": "国庆花艺海报",
        "created_at": NOW,
        "updated_at": NOW,
        "status": "discussing",
        "is_conversation": True,
        "models": _models(),
        "candidate_limit": 2,
        "content_language": "zh-CN",
        "artifacts": {
            "user_request": "input/request.txt",
            "conversation": "conversation.json",
            "brief": "brief.json",
        },
    })
    _write_round(tasks, FIRST_ROUND, revision=1,
                 parent_id=CONVERSATION_ID, selected="c01")
    _write_round(tasks, SECOND_ROUND, revision=2,
                 parent_id=CONVERSATION_ID, selected="c02")
    return CONVERSATION_ID


def _write_single_task(tasks: Path) -> str:
    run_dir = tasks / "natural-language" / SINGLE_TASK
    run_dir.mkdir(parents=True)
    write_json(run_dir / "brief.json", _brief())
    write_json(run_dir / "input" / "request.txt", "设计一张国庆花艺海报")
    write_json(run_dir / "manifest.json", {
        "format_version": 2,
        "workflow_version": 18,
        "case_id": "natural-language",
        "run_id": SINGLE_TASK,
        "title": "国庆花艺海报",
        "created_at": NOW,
        "updated_at": NOW,
        "status": "completed",
        "models": _models(),
        "artifacts": {"brief": "brief.json", "user_request": "input/request.txt"},
    })
    return SINGLE_TASK


class FavoriteSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.tasks = self.root / "tasks"
        self.favorites = self.root / "favorites"
        self.run_id = _write_conversation(self.tasks)
        self.app = CorpusAtelierApplication(
            runs_root=self.tasks,
            favorites_root=self.favorites,
        )

    def tearDown(self):
        self.app.close()
        self.temporary.cleanup()

    def test_capture_freezes_messages_rounds_prompts_and_cover(self):
        record = self.app.favorite_conversation(self.run_id)
        self.assertEqual(record["source_run_id"], self.run_id)
        self.assertEqual(record["brief"], _brief())
        self.assertEqual(
            [message["role"] for message in record["messages"]],
            ["user", "assistant"],
        )
        self.assertEqual(len(record["rounds"]), 2)
        self.assertEqual(record["rounds"][0]["selected_candidate_id"], "c01")
        self.assertEqual(record["rounds"][1]["selected_candidate_id"], "c02")
        prompts = [
            candidate["generation_prompt"]
            for round_ in record["rounds"]
            for candidate in round_["candidates"]
        ]
        self.assertEqual(len(prompts), 4)
        self.assertTrue(all(prompt.startswith("Render candidate") for prompt in prompts))
        self.assertEqual(record["cover_image"], "cover.png")
        directory = self.favorites / record["favorite_id"]
        self.assertTrue((directory / "cover.png").is_file())
        selected_image = (
            self.tasks / "natural-language" / SECOND_ROUND / "candidates"
            / "c02" / "generation" / "attempt_01" / "image.png"
        )
        self.assertEqual(record["cover_sha256"], digest_file(selected_image))

    def test_favorite_survives_removal_of_the_source_tasks(self):
        record = self.app.favorite_conversation(self.run_id)
        self.app.close()
        shutil.rmtree(self.tasks)
        store = FavoriteStore(self.favorites)
        loaded = store.read(record["favorite_id"])
        self.assertEqual(loaded["brief"], _brief())
        self.assertEqual(len(store.list()), 1)
        self.assertIsNotNone(store.list()[0].cover_path)

    def test_repeated_favorite_updates_one_snapshot(self):
        first = self.app.favorite_conversation(self.run_id, note="第一次收藏")
        second = self.app.favorite_conversation(self.run_id)
        self.assertEqual(first["favorite_id"], second["favorite_id"])
        self.assertEqual(second["note"], "第一次收藏")
        self.assertEqual(second["created_at"], first["created_at"])
        self.assertEqual(len(self.app.favorites()), 1)

    def test_invalid_ids_and_corrupt_records_are_rejected(self):
        with self.assertRaises(ValueError):
            self.app.open_favorite("../../outside")
        with self.assertRaises(ValueError):
            self.app.remove_favorite("not-an-id")
        corrupt = self.favorites / ("a" * 32) / "favorite.json"
        corrupt.parent.mkdir(parents=True)
        corrupt.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.app.favorites(), [])

    def test_start_from_favorite_preloads_request_and_brief(self):
        record = self.app.favorite_conversation(self.run_id)
        result = self.app.create_conversation_from_favorite(
            record["favorite_id"], candidate_count=2,
        )
        summary = self.app.inspect_task(result.run_id)
        conversation = self.app.conversation(result.run_id)
        self.assertTrue(summary.manifest.get("is_conversation"))
        self.assertEqual(summary.manifest["title"], "国庆花艺海报")
        self.assertEqual(conversation["revision"], 1)
        self.assertEqual(conversation["brief_revision"], 1)
        self.assertEqual(conversation["design_brief"], _brief())
        self.assertEqual(conversation["user_requirements"], ["花篮必须有提手。"])
        self.assertIsNone(conversation["pending"])
        self.assertEqual(conversation["rounds"], [])
        self.assertEqual(
            [message["role"] for message in conversation["messages"]],
            ["user"],
        )
        self.assertEqual(
            conversation["messages"][0]["text"], "设计一张国庆花艺海报",
        )
        self.assertTrue((summary.run_dir / "brief.json").is_file())

    def test_single_round_task_is_not_a_favorite_source(self):
        single = _write_single_task(self.tasks)
        with self.assertRaises(ValueError):
            self.app.favorite_conversation(single)
