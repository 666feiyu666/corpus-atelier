"""A port another program holds must stop startup, never be borrowed or skipped."""

from __future__ import annotations

import socket
import unittest
from contextlib import contextmanager

from corpus_atelier.cli import main
from corpus_atelier.config.ports import (
    PortUnavailable,
    port_available,
    require_available,
)

HOST = "127.0.0.1"


@contextmanager
def occupied_port():
    """A real listener, so the probe is tested against the OS rather than a mock."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((HOST, 0))
        listener.listen(1)
        yield listener.getsockname()[1]


def released_port() -> int:
    """A port the OS just handed out and that is not listening anywhere."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((HOST, 0))
        return probe.getsockname()[1]


class PortAvailabilityTests(unittest.TestCase):
    def test_a_listening_port_is_not_available(self):
        with occupied_port() as port:
            self.assertFalse(port_available(HOST, port))

    def test_a_released_port_is_available(self):
        self.assertTrue(port_available(HOST, released_port()))

    def test_port_zero_is_left_to_the_operating_system(self):
        self.assertTrue(port_available(HOST, 0))

    def test_a_taken_port_raises_with_the_port_and_the_subject(self):
        with occupied_port() as port:
            with self.assertRaises(PortUnavailable) as caught:
                require_available(HOST, port, purpose="the API")
        message = str(caught.exception)
        self.assertIn(str(port), message)
        self.assertIn("the API", message)
        self.assertIn("already in use", message)

    def test_a_free_port_passes(self):
        require_available(HOST, released_port(), purpose="the API")


class CliPortAdmissionTests(unittest.TestCase):
    def test_start_refuses_a_port_another_program_holds(self):
        with occupied_port() as port:
            with self.assertRaises(SystemExit) as caught:
                main(["start", "--port", str(port)])
        message = str(caught.exception.code)
        self.assertIn(str(port), message)
        self.assertIn("already in use", message)

    def test_the_api_command_refuses_a_port_another_program_holds(self):
        with occupied_port() as port:
            with self.assertRaises(SystemExit) as caught:
                main(["api", "--port", str(port)])
        self.assertIn(str(port), str(caught.exception.code))

    def test_the_error_never_suggests_reusing_the_port(self):
        with occupied_port() as port:
            with self.assertRaises(SystemExit) as caught:
                main(["start", "--port", str(port)])
        message = str(caught.exception.code)
        self.assertIn(f"--port {port + 10}", message)


if __name__ == "__main__":
    unittest.main()
