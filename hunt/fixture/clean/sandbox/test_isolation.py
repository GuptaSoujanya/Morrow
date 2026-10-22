"""Isolation proof: passes only when the sandbox blocks sockets (pytest-socket active)."""

import socket

import pytest
import pytest_socket


def test_sockets_are_blocked() -> None:
    with pytest.raises(pytest_socket.SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)
