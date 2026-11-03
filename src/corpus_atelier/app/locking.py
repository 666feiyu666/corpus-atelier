"""Per-task mutation locks shared by the application mixins."""

from __future__ import annotations

from functools import wraps
from threading import Lock, RLock
from weakref import WeakValueDictionary


_LOCKS = WeakValueDictionary()
_LOCKS_GUARD = Lock()


def serialized_run(method):
    """Serialize mutations of one task directory across application instances."""
    @wraps(method)
    def wrapped(self, run_id, *args, **kwargs):
        key = str(self.store.find_run(run_id))
        with _LOCKS_GUARD:
            lock = _LOCKS.get(key)
            if lock is None:
                lock = RLock()
                _LOCKS[key] = lock
        with lock:
            return method(self, run_id, *args, **kwargs)
    return wrapped
