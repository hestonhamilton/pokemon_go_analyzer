"""Keep all regression tests offline, including accidental transport fallthrough."""

import socket

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("tests must not open network connections")

    monkeypatch.setattr(socket, "create_connection", blocked)
