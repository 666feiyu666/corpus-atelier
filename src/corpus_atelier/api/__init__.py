"""The HTTP boundary: a thin adapter over the existing application services.

Nothing here decides prompt versions, image roles, or provider payloads. Routes
validate the request, resolve the credential, call ``CorpusAtelierApplication``,
and project the result for a browser: no absolute paths and no API keys ever
leave this package.
"""

from __future__ import annotations

from .app import create_app
from .runtime import TaskRuntime

__all__ = ["TaskRuntime", "create_app"]
