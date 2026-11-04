"""Port admission for the local boundary.

Corpus Atelier binds loopback ports that a developer machine also uses for other
projects. A port that is already taken is therefore never reused, borrowed, or
quietly stepped over: the process names the port it cannot have and stops. Both
alternatives are worse than an error.

- Binding over an existing listener (Windows lets ``SO_REUSEADDR`` do that) would
  put this interface in front of another project's server.
- Moving to the next free port would leave the interface and the documented URL
  pointing at different numbers, and a request could reach the wrong service.

The probe is deliberately the strictest one available: connect first, then bind
a socket without ``SO_REUSEADDR``. Only a port that nothing answers on and that
this process could really bind counts as free.
"""

from __future__ import annotations

import os
import socket

CONNECT_TIMEOUT_SECONDS = 0.25

# One command per platform that names the process holding a port.
_HOLDER_COMMANDS = {
    "nt": 'netstat -ano | findstr :{port}',
    "posix": "lsof -nP -iTCP:{port} -sTCP:LISTEN",
}


class PortUnavailable(RuntimeError):
    """A requested port cannot be taken, so the caller must not start."""

    def __init__(self, host: str, port: int, purpose: str) -> None:
        self.host = host
        self.port = port
        self.purpose = purpose
        super().__init__(self._message())

    def _message(self) -> str:
        command = _HOLDER_COMMANDS["nt" if os.name == "nt" else "posix"]
        return (
            f"Port {self.port} on {self.host} is already in use, so {self.purpose} "
            "cannot start.\n"
            "Corpus Atelier does not take over a port another program is using and "
            "does not move to another one by itself: either would point this "
            "interface at a service that is not ours.\n"
            f"Stop the process holding the port ({command.format(port=self.port)}) "
            f"or choose another one explicitly, for example --port {self.port + 10}."
        )


def is_listening(host: str, port: int) -> bool:
    """Whether something already accepts connections on the port."""
    try:
        with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT_SECONDS):
            return True
    except OSError:
        return False


def can_bind(host: str, port: int) -> bool:
    """Whether this process could really bind the port.

    No ``SO_REUSEADDR``: on Windows that would report a port another process is
    listening on as available, which is exactly the mistake to avoid.
    """
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return False
    for family, kind, protocol, _, address in addresses:
        probe = socket.socket(family, kind, protocol)
        try:
            probe.bind(address)
        except OSError:
            return False
        finally:
            probe.close()
    return True


def port_available(host: str, port: int) -> bool:
    """Whether the port is free for this process. Port 0 means "let the OS pick"."""
    if port == 0:
        return True
    return not is_listening(host, port) and can_bind(host, port)


def require_available(host: str, port: int, *, purpose: str) -> None:
    """Fail loudly instead of sharing or skipping a port that is taken."""
    if not port_available(host, port):
        raise PortUnavailable(host, port, purpose)
