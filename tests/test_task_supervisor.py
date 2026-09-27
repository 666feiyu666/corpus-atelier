from threading import Event
import time
import unittest

from corpus_atelier.task_supervisor import TaskSupervisor


class TaskSupervisorTests(unittest.TestCase):
    def test_immediately_completed_operation_does_not_deadlock_submission(self):
        supervisor = TaskSupervisor(max_workers=1)
        completed = Event()
        try:
            self.assertTrue(
                supervisor.submit("task-1", lambda: completed.set())
            )
            self.assertTrue(completed.wait(timeout=1))
        finally:
            supervisor.shutdown()

    def test_duplicate_submission_does_not_start_the_same_task_twice(self):
        supervisor = TaskSupervisor(max_workers=1)
        started = Event()
        release = Event()
        calls = []

        def operation():
            calls.append("started")
            started.set()
            release.wait(timeout=2)

        try:
            self.assertTrue(supervisor.submit("task-1", operation))
            self.assertTrue(started.wait(timeout=1))
            self.assertTrue(supervisor.is_running("task-1"))
            self.assertFalse(supervisor.submit("task-1", operation))
            self.assertEqual(calls, ["started"])

            release.set()
            deadline = time.monotonic() + 1
            while supervisor.is_running("task-1") and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertFalse(supervisor.is_running("task-1"))
        finally:
            release.set()
            supervisor.shutdown()


if __name__ == "__main__":
    unittest.main()
