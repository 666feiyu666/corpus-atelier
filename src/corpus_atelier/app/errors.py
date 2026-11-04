"""Errors that adapters can classify without reading message text.

The service layer signals a rejected *state* with :class:`TaskConflict`: the
request was well formed, but it arrived against a version of the task that no
longer allows it (a stale revision, an attempt that was already submitted, a
pending turn, or a running image request). Every other ``ValueError`` from the
service is a validation failure of the request itself.
"""

from __future__ import annotations


class TaskConflict(ValueError):
    """The request is valid but conflicts with the task's current state."""
