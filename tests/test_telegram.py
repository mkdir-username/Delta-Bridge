"""Tests for Telegram adapter (Phase 4)."""
import json
import sys
import os
import types

_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(_root, "server"))
sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "pass")
os.environ.setdefault("IOE_SECRET", "secret123")

from unittest.mock import patch, MagicMock, AsyncMock

for _mod in ["truststore", "imapclient", "readability", "PIL", "PIL.Image", "requests", "trafilatura", "telethon"]:
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)
sys.modules["truststore"].inject_into_ssl = lambda: None
sys.modules["imapclient"].IMAPClient = type("IMAPClient", (), {})

class _MockDoc:
    def __init__(self, html=""): pass
    def title(self): return ""
    def summary(self): return ""
sys.modules["readability"].Document = _MockDoc

_mock_img = MagicMock()
sys.modules["PIL"].Image = _mock_img
sys.modules["PIL.Image"] = _mock_img

_mock_requests = types.ModuleType("requests")
_mock_requests.get = MagicMock()
_mock_requests.request = MagicMock()
_mock_requests.Session = MagicMock
sys.modules["requests"] = _mock_requests

sys.modules["trafilatura"].extract = MagicMock(return_value="")
import asyncio


def _mock_adapter(return_value):
    mock = MagicMock()
    mock.handle.return_value = return_value
    return patch("server._get_telegram_adapter", return_value=mock)


class TestDispatchTelegram:
    def test_command_telegram_routes_to_adapter(self):
        from server import dispatch_request
        with _mock_adapter({"status": 200, "dialogs": []}) as p:
            result = dispatch_request({
                "type": "command",
                "service": "telegram",
                "action": "get_dialogs",
            })
        assert result["status"] == 200
        p.return_value.handle.assert_called_once()

    def test_command_unknown_service_returns_error(self):
        from server import dispatch_request
        result = dispatch_request({
            "type": "command",
            "service": "unknown_service",
            "action": "test",
        })
        assert result.get("status") == 400
        assert "error" in result

    def test_command_telegram_get_dialogs(self):
        from server import dispatch_request
        with _mock_adapter({
            "status": 200,
            "dialogs": [
                {"id": 1, "name": "Test Chat", "unread": 5},
                {"id": 2, "name": "Another", "unread": 0},
            ],
        }):
            result = dispatch_request({
                "type": "command",
                "service": "telegram",
                "action": "get_dialogs",
            })
        assert result["status"] == 200
        assert len(result["dialogs"]) == 2
        assert result["dialogs"][0]["unread"] == 5

    def test_command_telegram_get_messages(self):
        from server import dispatch_request
        with _mock_adapter({
            "status": 200,
            "messages": [
                {"id": 100, "sender": "Alice", "text": "Hello", "date": "2026-03-30T10:00:00"},
            ],
        }):
            result = dispatch_request({
                "type": "command",
                "service": "telegram",
                "action": "get_messages",
                "chat_id": 1,
                "limit": 20,
            })
        assert result["status"] == 200
        assert len(result["messages"]) == 1

    def test_command_telegram_send_message(self):
        from server import dispatch_request
        with _mock_adapter({"status": 200, "message_id": 101}):
            result = dispatch_request({
                "type": "command",
                "service": "telegram",
                "action": "send_message",
                "chat_id": 1,
                "text": "Hello from IoE",
            })
        assert result["status"] == 200
        assert result["message_id"] == 101

    def test_command_telegram_mark_read(self):
        from server import dispatch_request
        with _mock_adapter({"status": 200}):
            result = dispatch_request({
                "type": "command",
                "service": "telegram",
                "action": "mark_read",
                "chat_id": 1,
            })
        assert result["status"] == 200

    def test_telegram_not_available(self):
        from server import dispatch_request
        with patch("server._get_telegram_adapter", return_value=None):
            result = dispatch_request({
                "type": "command",
                "service": "telegram",
                "action": "get_dialogs",
            })
        assert result["status"] == 503


class TestTelegramAdapter:
    def test_handle_dispatches_action(self):
        from telegram_adapter import TelegramAdapter
        adapter = TelegramAdapter.__new__(TelegramAdapter)
        adapter.client = MagicMock()
        adapter.loop = MagicMock()
        adapter._run_sync = MagicMock(return_value=[
            {"id": 1, "name": "Chat", "unread": 0}
        ])
        result = adapter.handle("get_dialogs", {})
        assert result["status"] == 200

    def test_handle_unknown_action(self):
        from telegram_adapter import TelegramAdapter
        adapter = TelegramAdapter.__new__(TelegramAdapter)
        adapter.client = MagicMock()
        adapter.loop = MagicMock()
        result = adapter.handle("nonexistent_action", {})
        assert result["status"] == 400
        assert "error" in result

    def test_handle_send_message(self):
        from telegram_adapter import TelegramAdapter
        adapter = TelegramAdapter.__new__(TelegramAdapter)
        adapter.client = MagicMock()
        adapter.loop = MagicMock()
        adapter._run_sync = MagicMock(return_value=42)
        result = adapter.handle("send_message", {"chat_id": 1, "text": "hi"})
        assert result["status"] == 200
        assert result["message_id"] == 42

    def test_handle_reply(self):
        from telegram_adapter import TelegramAdapter
        adapter = TelegramAdapter.__new__(TelegramAdapter)
        adapter.client = MagicMock()
        adapter.loop = MagicMock()
        adapter._run_sync = MagicMock(return_value=43)
        result = adapter.handle("reply", {"chat_id": 1, "reply_to_id": 10, "text": "reply"})
        assert result["status"] == 200
        assert result["message_id"] == 43
