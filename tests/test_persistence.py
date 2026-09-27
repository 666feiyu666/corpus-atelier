import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.state import (
    CandidateSelection,
    DesignJob,
    HumanDecision,
    NaturalLanguageDesignJob,
)
from tests.fakes import FakeImageProvider, FakeTextProvider


ROOT = Path(__file__).resolve().parents[1]
BRIEF = json.loads(
    (ROOT / "tests/fixtures/cases/poster-01/brief.json").read_text(
        encoding="utf-8"
    )
)


class PersistenceTests(unittest.TestCase):
    def _app(self, root, *, image=None):
        return CorpusAtelierApplication(
            runs_root=root,
            text_provider=FakeTextProvider(),
            image_provider=image or FakeImageProvider(),
        )

    def test_task_resumes_across_application_restarts(self):
        with TemporaryDirectory() as directory:
            first = self._app(directory)
            started = first.start(DesignJob(
                case_id="poster-01",
                profile="rhetoric-poster",
                brief=BRIEF,
            ))
            self.assertEqual(started.status, "awaiting_approval")
            first.close()

            image = FakeImageProvider()
            second = self._app(directory, image=image)
            reopened = second.open_task(started.run_id)
            self.assertEqual(reopened.status, "awaiting_approval")
            generated = second.resume(
                started.run_id,
                HumanDecision(True, reviewer="restart-test"),
            )
            self.assertEqual(generated.status, "awaiting_selection")
            self.assertEqual(image.calls, 1)
            second.close()

            third = self._app(directory)
            completed = third.resume(
                started.run_id,
                CandidateSelection("c01", reviewer="restart-test"),
            )
            self.assertEqual(completed.status, "completed")
            tasks = third.list_tasks()
            self.assertEqual([task.run_id for task in tasks], [started.run_id])
            self.assertEqual(tasks[0].manifest["workflow_version"], 18)
            self.assertIn("models", tasks[0].manifest)
            third.close()

    def test_model_change_invalidates_a_waiting_task(self):
        with TemporaryDirectory() as directory:
            first = self._app(directory)
            started = first.start(DesignJob(
                case_id="poster-01",
                profile="rhetoric-poster",
                brief=BRIEF,
            ))
            first.close()

            changed = CorpusAtelierApplication(
                runs_root=directory,
                text_provider=FakeTextProvider(),
                image_provider=FakeImageProvider(),
            )
            changed.runtime.text_provider.model = "different-model"
            with self.assertRaisesRegex(ValueError, "models changed"):
                changed.resume(
                    started.run_id,
                    HumanDecision(True, reviewer="restart-test"),
                )
            changed.close()

    def test_natural_language_task_can_be_created_then_run_after_restart(self):
        with TemporaryDirectory() as directory:
            first = self._app(directory)
            created = first.create_request(NaturalLanguageDesignJob(
                case_id="natural-language",
                profile="rhetoric-graphic",
                request="Design a reading-group announcement.",
                candidate_count=3,
            ))
            self.assertEqual(created.status, "created")
            manifest = json.loads(
                Path(created.artifacts["manifest"]).read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["candidate_limit"], 3)
            first.close()

            updates = []
            second = CorpusAtelierApplication(
                runs_root=directory,
                text_provider=FakeTextProvider(),
                image_provider=FakeImageProvider(),
                status_callback=lambda run_id, status: updates.append(
                    (run_id, status)
                ),
            )
            result = second.run_request(created.run_id)

            self.assertEqual(result.status, "awaiting_approval")
            self.assertEqual(
                [status for run_id, status in updates if run_id == created.run_id],
                [
                    "interpreting_request",
                    "designing_directions",
                    "implementing_designs",
                    "compiling_candidates",
                    "awaiting_approval",
                ],
            )
            second.close()

    def test_interrupted_task_continues_from_latest_graph_checkpoint(self):
        class SimulatedProcessExit(BaseException):
            pass

        with TemporaryDirectory() as directory:
            def interrupt_after_status(run_id, status):
                if status == "designing_directions":
                    raise SimulatedProcessExit()

            first = CorpusAtelierApplication(
                runs_root=directory,
                text_provider=FakeTextProvider(),
                image_provider=FakeImageProvider(),
                status_callback=interrupt_after_status,
            )
            created = first.create_request(NaturalLanguageDesignJob(
                case_id="natural-language",
                profile="rhetoric-graphic",
                request="Design a reading-group announcement.",
                candidate_count=1,
            ))
            with self.assertRaises(SimulatedProcessExit):
                first.run_request(created.run_id)
            self.assertEqual(
                first.open_task(created.run_id).status,
                "designing_directions",
            )
            first.close()

            second = self._app(directory)
            resumed = second.continue_task(created.run_id)

            self.assertEqual(resumed.status, "awaiting_approval")
            self.assertIn("brief", resumed.artifacts)
            self.assertIn("candidate_index", resumed.artifacts)
            second.close()


if __name__ == "__main__":
    unittest.main()
