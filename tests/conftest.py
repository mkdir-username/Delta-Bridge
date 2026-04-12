from __future__ import annotations

import os
import sys
import socket
import pytest

_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, _root)


@pytest.fixture(autouse=True, scope="session")
def env_vars() -> None:
    os.environ.setdefault("EMAIL", "test@test.com")
    os.environ.setdefault("IMAP_PASSWORD", "test")
    os.environ.setdefault("IOE_SECRET", "test-secret-key")


@pytest.fixture(autouse=True)
def _reset_demo_mode() -> None:
    import importlib

    mod = importlib.import_module("ioe_web") if "ioe_web" in sys.modules else None
    if mod:
        mod.DEMO_MODE = False


@pytest.fixture
def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port
