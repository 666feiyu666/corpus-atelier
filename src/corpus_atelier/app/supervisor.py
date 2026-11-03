"""Process-local supervision for durable background task execution."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
import logging
from threading import Lock


LOGGER = logging.getLogger(__name__)


class TaskSupervisor:
    """Run each task at most once within the current application process."""

    def __init__(self, *, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="corpus-atelier-task",
        )
        self._futures: dict[str, Future[None]] = {}
        self._lock = Lock()

    def submit(self, run_id: str, operation: Callable[[], None]) -> bool:
        """Submit an operation unless the same task is already running."""
        with self._lock:
            existing = self._futures.get(run_id)
            if existing is not None and not existing.done():
                return False
            future = self._executor.submit(operation)
            self._futures[run_id] = future
        future.add_done_callback(
            lambda completed, task_id=run_id: self._finish(
                task_id, completed
            )
        )
        return True

    def _finish(self, run_id: str, future: Future[None]) -> None:
        with self._lock:
            if self._futures.get(run_id) is future:
                self._futures.pop(run_id, None)
        try:
            future.result()
        except BaseException:
            LOGGER.exception("Background task %s stopped unexpectedly.", run_id)

    def is_running(self, run_id: str) -> bool:
        with self._lock:
            future = self._futures.get(run_id)
            return future is not None and not future.done()

    def running_ids(self) -> set[str]:
        with self._lock:
            return {
                run_id
                for run_id, future in self._futures.items()
                if not future.done()
            }

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)
