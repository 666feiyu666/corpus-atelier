import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.state import CandidateSelection, DesignJob, HumanDecision
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


if __name__ == "__main__":
    unittest.main()
