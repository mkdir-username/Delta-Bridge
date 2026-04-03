import os
import sys
import socket
import pytest

_root = os.path.dirname(os.path.dirname(__file__))


@pytest.fixture(autouse=True, scope="session")
def env_vars():
    os.environ.setdefault("EMAIL", "test@test.com")
    os.environ.setdefault("IMAP_PASSWORD", "test")
    os.environ.setdefault("IOE_SECRET", "test-secret-key")


@pytest.fixture
def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port
