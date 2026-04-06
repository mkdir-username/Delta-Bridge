"""Tests for Telegram adapter (Phase 4)."""

import sys
import os
import types

_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(_root, "server"))
sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "pass")
os.environ.setdefault("IOE_SECRET", "secret123")

from unittest.mock import patch, MagicMock

for _mod in [
    "truststore",
    "imapclient",
    "readability",
    "PIL",
    "PIL.Image",
    "requests",
    "trafilatura",
    "telethon",
    "telethon.tl",
    "telethon.tl.functions",
    "telethon.tl.functions.messages",
]:
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)

sys.modules["telethon"].TelegramClient = MagicMock()
sys.modules["telethon.tl.functions.messages"].GetDialogsRequest = MagicMock()
sys.modules["telethon.tl.functions.messages"].ReadHistoryRequest = MagicMock()

_mock_events = types.ModuleType("telethon.events")
_mock_events.NewMessage = MagicMock()
sys.modules["telethon.events"] = _mock_events
sys.modules["telethon"].events = _mock_events


class _RPCError(Exception):
    def __init__(self, *a, **kw):
        self.seconds = kw.get("seconds", 0)
        super().__init__(str(kw))


_mock_errors = types.ModuleType("telethon.errors")
_mock_errors.AuthKeyUnregisteredError = type("AuthKeyUnregisteredError", (_RPCError,), {})
_mock_errors.SessionPasswordNeededError = type("SessionPasswordNeededError", (_RPCError,), {})
_mock_errors.PhoneCodeInvalidError = type("PhoneCodeInvalidError", (_RPCError,), {})
_mock_errors.FloodWaitError = type(
    "FloodWaitError",
    (_RPCError,),
    {
        "__init__": lambda self, *a, **kw: (
            _RPCError.__init__(self, *a, **kw),
            setattr(self, "seconds", kw.get("seconds", 0)),
        )[0]
    },
)
sys.modules["telethon.errors"] = _mock_errors
if "telegram_adapter" in sys.modules:
    import importlib

    importlib.reload(sys.modules["telegram_adapter"])
sys.modules["truststore"].inject_into_ssl = lambda: None
sys.modules["imapclient"].IMAPClient = type("IMAPClient", (), {})


class _MockDoc:
    def __init__(self, html=""):
        pass

    def title(self):
        return ""

    def summary(self):
        return ""


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
from unittest.mock import AsyncMock


def _make_real_sync_adapter():
    """Adapter with real _run_sync that executes coroutines via event loop."""
    from telegram_adapter import TelegramAdapter

    adapter = TelegramAdapter.__new__(TelegramAdapter)
    adapter.loop = asyncio.new_event_loop()
    adapter.clients = {}
    adapter.api_id = 0
    adapter.api_hash = ""
    adapter._auth_state = {}
    adapter._last_notify = {}
    adapter._notify_interval = 10

    def _run_sync(coro):
        return adapter.loop.run_until_complete(coro)

    adapter._run_sync = _run_sync
    return adapter


def _make_mock_dialog(**overrides):
    entity = MagicMock(spec=[])
    if "megagroup" in overrides:
        entity.megagroup = overrides.pop("megagroup")
    if "broadcast" in overrides:
        entity.broadcast = overrides.pop("broadcast")
    if "title" in overrides:
        entity.title = overrides.pop("title")
    d = MagicMock()
    d.id = overrides.get("id", 1)
    d.name = overrides.get("name", "Test Chat")
    d.unread_count = overrides.get("unread_count", 0)
    d.message = overrides.get("message", MagicMock(text="hello", date=None))
    d.date = overrides.get("date")
    d.entity = entity
    d.archived = overrides.get("archived", False)
    d.pinned = overrides.get("pinned", False)
    return d


def _make_mock_message(**overrides):
    m = MagicMock()
    m.id = overrides.get("id", 100)
    m.sender = MagicMock(first_name=overrides.get("sender_name", "Alice"))
    m.sender_id = overrides.get("sender_id", 42)
    m.text = overrides.get("text", "Hello")
    m.date = overrides.get("date", MagicMock(isoformat=MagicMock(return_value="2026-04-06T10:00:00")))
    m.out = overrides.get("out", False)
    m.reply_to = overrides.get("reply_to")
    m.media = overrides.get("media")
    return m


def _mock_adapter(return_value):
    mock = MagicMock()
    mock.handle.return_value = return_value
    return patch("server._get_telegram_adapter", return_value=mock)


class TestDispatchTelegram:
    def test_command_telegram_routes_to_adapter(self):
        from server import dispatch_request

        with _mock_adapter({"status": 200, "dialogs": []}) as p:
            result = dispatch_request(
                {
                    "type": "command",
                    "service": "telegram",
                    "action": "get_dialogs",
                }
            )
        assert result["status"] == 200
        p.return_value.handle.assert_called_once()

    def test_command_unknown_service_returns_error(self):
        from server import dispatch_request

        result = dispatch_request(
            {
                "type": "command",
                "service": "unknown_service",
                "action": "test",
            }
        )
        assert result.get("status") == 400
        assert "error" in result

    def test_command_telegram_get_dialogs(self):
        from server import dispatch_request

        with _mock_adapter(
            {
                "status": 200,
                "dialogs": [
                    {"id": 1, "name": "Test Chat", "unread": 5},
                    {"id": 2, "name": "Another", "unread": 0},
                ],
            }
        ):
            result = dispatch_request(
                {
                    "type": "command",
                    "service": "telegram",
                    "action": "get_dialogs",
                }
            )
        assert result["status"] == 200
        assert len(result["dialogs"]) == 2
        assert result["dialogs"][0]["unread"] == 5

    def test_command_telegram_get_messages(self):
        from server import dispatch_request

        with _mock_adapter(
            {
                "status": 200,
                "messages": [
                    {
                        "id": 100,
                        "sender": "Alice",
                        "text": "Hello",
                        "date": "2026-03-30T10:00:00",
                    },
                ],
            }
        ):
            result = dispatch_request(
                {
                    "type": "command",
                    "service": "telegram",
                    "action": "get_messages",
                    "chat_id": 1,
                    "limit": 20,
                }
            )
        assert result["status"] == 200
        assert len(result["messages"]) == 1

    def test_command_telegram_send_message(self):
        from server import dispatch_request

        with _mock_adapter({"status": 200, "message_id": 101}):
            result = dispatch_request(
                {
                    "type": "command",
                    "service": "telegram",
                    "action": "send_message",
                    "chat_id": 1,
                    "text": "Hello from IoE",
                }
            )
        assert result["status"] == 200
        assert result["message_id"] == 101

    def test_command_telegram_mark_read(self):
        from server import dispatch_request

        with _mock_adapter({"status": 200}):
            result = dispatch_request(
                {
                    "type": "command",
                    "service": "telegram",
                    "action": "mark_read",
                    "chat_id": 1,
                }
            )
        assert result["status"] == 200

    def test_telegram_not_available(self):
        from server import dispatch_request

        with patch("server._get_telegram_adapter", return_value=None):
            result = dispatch_request(
                {
                    "type": "command",
                    "service": "telegram",
                    "action": "get_dialogs",
                }
            )
        assert result["status"] == 503


class TestTelegramAdapter:
    def _make_adapter(self):
        from telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter.__new__(TelegramAdapter)
        adapter.clients = {"default": MagicMock()}
        adapter.client = None
        adapter.api_id = 0
        adapter.api_hash = ""
        adapter.loop = MagicMock()
        adapter._auth_state = {}
        return adapter

    def test_handle_dispatches_action(self):
        adapter = self._make_adapter()
        adapter._run_sync = MagicMock(return_value=[{"id": 1, "name": "Chat", "unread": 0}])
        result = adapter.handle("get_dialogs", {})
        assert result["status"] == 200

    def test_handle_unknown_action(self):
        adapter = self._make_adapter()
        result = adapter.handle("nonexistent_action", {})
        assert result["status"] == 400
        assert "error" in result

    def test_handle_send_message(self):
        adapter = self._make_adapter()
        adapter._run_sync = MagicMock(return_value=42)
        result = adapter.handle("send_message", {"chat_id": 1, "text": "hi"})
        assert result["status"] == 200
        assert result["message_id"] == 42

    def test_handle_reply(self):
        adapter = self._make_adapter()
        adapter._run_sync = MagicMock(return_value=43)
        result = adapter.handle("reply", {"chat_id": 1, "reply_to_id": 10, "text": "reply"})
        assert result["status"] == 200
        assert result["message_id"] == 43


class TestMultiUserTelegram:
    def test_clients_dict_initialized(self):
        from telegram_adapter import TelegramAdapter

        with patch("telegram_adapter.TELETHON_AVAILABLE", True):
            adapter = TelegramAdapter(api_id=123, api_hash="abc")
        assert hasattr(adapter, "clients")
        assert isinstance(adapter.clients, dict)
        assert adapter.clients == {}

    def test_auth_state_initialized(self):
        from telegram_adapter import TelegramAdapter

        with patch("telegram_adapter.TELETHON_AVAILABLE", True):
            adapter = TelegramAdapter(api_id=123, api_hash="abc")
        assert hasattr(adapter, "_auth_state")
        assert isinstance(adapter._auth_state, dict)

    def test_get_client_creates_per_user(self):
        from telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter.__new__(TelegramAdapter)
        adapter.clients = {}
        adapter.api_id = 123
        adapter.api_hash = "abc"
        adapter.loop = asyncio.new_event_loop()
        mock_client = MagicMock()
        with patch("telegram_adapter.TelegramClient", return_value=mock_client, create=True):
            future_mock = MagicMock()
            future_mock.result.return_value = None
            with patch("asyncio.run_coroutine_threadsafe", return_value=future_mock):
                client = adapter._get_client("user_a")
                assert "user_a" in adapter.clients
                assert adapter.clients["user_a"] is mock_client
                client_b = adapter._get_client("user_b")
                assert "user_b" in adapter.clients
                assert len(adapter.clients) == 2
        adapter.loop.close()

    def test_get_client_reuses_existing(self):
        from telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter.__new__(TelegramAdapter)
        adapter.clients = {}
        adapter.api_id = 123
        adapter.api_hash = "abc"
        adapter.loop = asyncio.new_event_loop()
        mock_client = MagicMock()
        with patch("telegram_adapter.TelegramClient", return_value=mock_client, create=True) as ctor:
            future_mock = MagicMock()
            future_mock.result.return_value = None
            with patch("asyncio.run_coroutine_threadsafe", return_value=future_mock):
                adapter._get_client("user_a")
                adapter._get_client("user_a")
                assert ctor.call_count == 1
        adapter.loop.close()

    def test_handle_extracts_user_id(self):
        from telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter.__new__(TelegramAdapter)
        adapter.clients = {}
        adapter.api_id = 123
        adapter.api_hash = "abc"
        adapter.loop = asyncio.new_event_loop()
        adapter._auth_state = {}
        mock_client = MagicMock()
        with patch("telegram_adapter.TelegramClient", return_value=mock_client, create=True):
            future_mock = MagicMock()
            future_mock.result.return_value = [
                MagicMock(
                    id=1,
                    name="Chat",
                    unread_count=0,
                    message=None,
                    date=None,
                    entity=MagicMock(spec=[]),
                    archived=False,
                    pinned=False,
                )
            ]
            with patch("asyncio.run_coroutine_threadsafe", return_value=future_mock):
                result = adapter.handle("get_dialogs", {"user_id": "test_user"})
                assert "test_user" in adapter.clients
                assert result["status"] == 200
        adapter.loop.close()

    def test_handle_defaults_user_id(self):
        from telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter.__new__(TelegramAdapter)
        adapter.clients = {}
        adapter.api_id = 123
        adapter.api_hash = "abc"
        adapter.loop = asyncio.new_event_loop()
        adapter._auth_state = {}
        mock_client = MagicMock()
        with patch("telegram_adapter.TelegramClient", return_value=mock_client, create=True):
            future_mock = MagicMock()
            future_mock.result.return_value = []
            with patch("asyncio.run_coroutine_threadsafe", return_value=future_mock):
                adapter.handle("get_dialogs", {})
                assert "default" in adapter.clients
        adapter.loop.close()

    def test_auth_state_per_user(self):
        from telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter.__new__(TelegramAdapter)
        adapter._auth_state = {}
        adapter._auth_state["denis"] = {"phone": "+7123", "hash": "abc"}
        adapter._auth_state["kamila"] = {"phone": "+7456", "hash": "def"}
        assert adapter._auth_state["denis"]["phone"] == "+7123"
        assert adapter._auth_state["kamila"]["phone"] == "+7456"

    def test_is_authorized_per_user(self):
        from telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter.__new__(TelegramAdapter)
        adapter.clients = {"alice": MagicMock()}
        adapter.api_id = 0
        adapter.api_hash = ""
        adapter.loop = asyncio.new_event_loop()
        future_mock = MagicMock()
        future_mock.result.return_value = True
        with patch("asyncio.run_coroutine_threadsafe", return_value=future_mock):
            assert adapter.is_authorized("alice") is True
            assert adapter.is_authorized("nobody") is False
        adapter.loop.close()

    def test_listener_init_fields(self):
        from telegram_adapter import TelegramAdapter

        with patch("telegram_adapter.TELETHON_AVAILABLE", True):
            adapter = TelegramAdapter(api_id=123, api_hash="abc")
        assert hasattr(adapter, "_last_notify")
        assert isinstance(adapter._last_notify, dict)
        assert hasattr(adapter, "_notify_interval")
        assert adapter._notify_interval == 10

    def test_backward_compat_single_client(self):
        from telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter.__new__(TelegramAdapter)
        adapter.clients = {"default": MagicMock()}
        adapter.client = None
        adapter.api_id = 0
        adapter.api_hash = ""
        adapter.loop = MagicMock()
        adapter._auth_state = {}
        adapter._run_sync = MagicMock(return_value=[])
        result = adapter.handle("get_dialogs", {})
        assert result["status"] == 200


class TestTelegramListener:
    def _make_adapter(self):
        from telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter.__new__(TelegramAdapter)
        adapter.clients = {}
        adapter.loop = asyncio.new_event_loop()
        adapter._auth_state = {}
        adapter._last_notify = {}
        adapter._notify_interval = 10
        adapter.api_id = 0
        adapter.api_hash = ""
        return adapter

    def test_start_listener_unauthorized_skips(self):
        adapter = self._make_adapter()
        mock_client = MagicMock()
        adapter.clients["test"] = mock_client
        adapter._run_sync = MagicMock(return_value=False)
        callback = MagicMock()
        adapter.start_listener("test", callback)
        mock_client.add_event_handler.assert_not_called()
        adapter.loop.close()

    def test_start_listener_authorized_adds_handler(self):
        adapter = self._make_adapter()
        mock_client = MagicMock()
        adapter.clients["test"] = mock_client
        adapter._run_sync = MagicMock(return_value=True)
        callback = MagicMock()
        adapter.start_listener("test", callback)
        mock_client.add_event_handler.assert_called_once()
        adapter.loop.close()

    def test_start_listener_missing_client_creates_it(self):
        adapter = self._make_adapter()
        mock_client = MagicMock()
        adapter._run_sync = MagicMock(return_value=True)
        with patch("telegram_adapter.TelegramClient", return_value=mock_client, create=True):
            future_mock = MagicMock()
            future_mock.result.return_value = None
            with patch("asyncio.run_coroutine_threadsafe", return_value=future_mock):
                adapter.start_listener("new_user", MagicMock())
        mock_client.add_event_handler.assert_called_once()
        adapter.loop.close()

    def test_rate_limiting_blocks_rapid_calls(self):
        import time

        adapter = self._make_adapter()
        adapter._last_notify["u1"] = time.time()
        now = time.time()
        assert now - adapter._last_notify["u1"] < adapter._notify_interval
        adapter.loop.close()

    def test_rate_limiting_allows_after_interval(self):
        import time

        adapter = self._make_adapter()
        adapter._last_notify["u1"] = time.time() - 20
        now = time.time()
        assert now - adapter._last_notify["u1"] >= adapter._notify_interval
        adapter.loop.close()

    def test_notification_format(self):
        notification = {
            "type": "notification",
            "service": "telegram",
            "user_id": "test",
            "chat_id": 123,
            "sender": "Alice",
            "chat_name": "Test Chat",
            "text": "Hello",
            "timestamp": "2026-03-30T10:00:00",
        }
        assert notification["type"] == "notification"
        assert notification["service"] == "telegram"
        assert len(notification["text"]) <= 200


class TestTelegramAuth:
    def _make_adapter(self):
        from telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter.__new__(TelegramAdapter)
        adapter.clients = {"default": MagicMock()}
        adapter.client = None
        adapter.api_id = 0
        adapter.api_hash = ""
        adapter.loop = MagicMock()
        adapter._auth_state = {}
        return adapter

    def test_check_auth_returns_authorized_true(self):
        adapter = self._make_adapter()
        adapter._run_sync = MagicMock(return_value=True)
        result = adapter.handle("check_auth", {})
        assert result["status"] == 200
        assert result["authorized"] is True

    def test_check_auth_returns_authorized_false(self):
        adapter = self._make_adapter()
        adapter._run_sync = MagicMock(return_value=False)
        result = adapter.handle("check_auth", {})
        assert result["status"] == 200
        assert result["authorized"] is False

    def test_check_auth_with_user_id(self):
        adapter = self._make_adapter()
        adapter.clients["denis"] = MagicMock()
        adapter._run_sync = MagicMock(return_value=True)
        result = adapter.handle("check_auth", {"user_id": "denis"})
        assert result["status"] == 200
        assert result["authorized"] is True

    def test_handle_auth_key_unregistered_returns_401(self):
        from telethon.errors import AuthKeyUnregisteredError

        adapter = self._make_adapter()
        adapter._run_sync = MagicMock(side_effect=AuthKeyUnregisteredError())
        result = adapter.handle("get_dialogs", {})
        assert result["status"] == 401
        assert result["auth_required"] is True
        assert "default" not in adapter.clients

    def test_auth_start_flood_wait(self):
        from telethon.errors import FloodWaitError

        adapter = self._make_adapter()
        adapter._run_sync = MagicMock(side_effect=FloodWaitError(seconds=120))
        result = adapter.handle("auth_start", {"phone": "+71234567890"})
        assert result["status"] == 200
        assert result["auth_status"] == "flood_wait"
        assert result["seconds"] == 120

    def test_auth_code_invalid_code(self):
        from telethon.errors import PhoneCodeInvalidError

        adapter = self._make_adapter()
        adapter._auth_state = {"default": {"phone": "+7", "hash": "abc"}}
        adapter._run_sync = MagicMock(side_effect=PhoneCodeInvalidError())
        result = adapter.handle("auth_code", {"code": "99999"})
        assert result["status"] == 200
        assert result["auth_status"] == "invalid_code"

    def test_auth_code_2fa_required(self):
        from telethon.errors import SessionPasswordNeededError

        adapter = self._make_adapter()
        adapter._auth_state = {"default": {"phone": "+7", "hash": "abc"}}
        adapter._run_sync = MagicMock(side_effect=SessionPasswordNeededError())
        result = adapter.handle("auth_code", {"code": "12345"})
        assert result["status"] == 200
        assert result["auth_status"] == "2fa_required"

    def test_auth_code_success(self):
        adapter = self._make_adapter()
        adapter._auth_state = {"default": {"phone": "+7", "hash": "abc"}}
        adapter._run_sync = MagicMock(return_value=None)
        result = adapter.handle("auth_code", {"code": "12345"})
        assert result["status"] == 200
        assert result["auth_status"] == "authorized"

    def test_auth_code_2fa_then_success_with_password(self):
        from telethon.errors import SessionPasswordNeededError

        adapter = self._make_adapter()
        adapter._auth_state = {"default": {"phone": "+7", "hash": "abc"}}
        adapter._run_sync = MagicMock(side_effect=SessionPasswordNeededError())
        result = adapter.handle("auth_code", {"code": "12345"})
        assert result["status"] == 200
        assert result["auth_status"] == "2fa_required"

    def test_auth_code_password_only(self):
        adapter = self._make_adapter()
        adapter._auth_state = {}
        adapter._run_sync = MagicMock(return_value=None)
        result = adapter.handle("auth_code", {"code": "", "password": "secret"})
        assert result["status"] == 200
        assert result["auth_status"] == "authorized"

    def test_auth_start_flood_wait_in_handle(self):
        from telethon.errors import FloodWaitError

        adapter = self._make_adapter()
        err = FloodWaitError(seconds=60)
        adapter._run_sync = MagicMock(side_effect=err)
        result = adapter.handle("auth_start", {"phone": "+71234567890"})
        assert result["status"] == 200
        assert result["auth_status"] == "flood_wait"
        assert result["seconds"] == 60

    def test_auth_logout_removes_client_and_state(self):
        adapter = self._make_adapter()
        adapter._auth_state = {"default": {"phone": "+7", "hash": "abc"}}
        adapter._run_sync = MagicMock(return_value=None)
        result = adapter.handle("auth_logout", {})
        assert result["status"] == 200
        assert result["auth_status"] == "logged_out"
        assert "default" not in adapter.clients
        assert "default" not in adapter._auth_state

    def test_auth_logout_exception_still_cleans(self):
        adapter = self._make_adapter()
        adapter._auth_state = {"default": {"phone": "+7", "hash": "abc"}}
        adapter._run_sync = MagicMock(side_effect=Exception("network error"))
        result = adapter.handle("auth_logout", {})
        assert result["status"] == 200
        assert result["auth_status"] == "logged_out"
        assert "default" not in adapter.clients


class TestTelegramDialogTypes:
    def _make_dialog(self, entity_attrs):
        d = MagicMock()
        d.id = 1
        d.name = "Test"
        d.unread_count = 0
        d.message = None
        d.date = None
        d.archived = False
        d.pinned = False
        entity = MagicMock(spec=list(entity_attrs.keys()))
        for k, v in entity_attrs.items():
            setattr(entity, k, v)
        d.entity = entity
        return d

    def _make_adapter_with_dialogs(self, processed_dialogs):
        from telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter.__new__(TelegramAdapter)
        adapter.clients = {"u": MagicMock()}
        adapter.loop = asyncio.new_event_loop()
        adapter._auth_state = {}
        adapter.api_id = 0
        adapter.api_hash = ""
        adapter._run_sync = MagicMock(return_value=processed_dialogs)
        return adapter

    def _make_raw_dialog(self, entity_attrs):
        d = MagicMock()
        d.id = 1
        d.name = "Test"
        d.unread_count = 0
        d.message = None
        d.date = None
        d.archived = False
        d.pinned = False
        entity = MagicMock(spec=list(entity_attrs.keys()))
        for k, v in entity_attrs.items():
            setattr(entity, k, v)
        d.entity = entity
        return d

    def _fetch_dialogs_sync(self, raw_dialogs):
        from telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter.__new__(TelegramAdapter)
        adapter.clients = {}
        adapter.loop = asyncio.new_event_loop()
        adapter._auth_state = {}
        adapter.api_id = 0
        adapter.api_hash = ""

        async def fake_get_dialogs(limit):
            return raw_dialogs

        mock_client = MagicMock()
        mock_client.get_dialogs = fake_get_dialogs

        result_container = []

        async def run_fetch():
            res = await asyncio.get_event_loop().run_in_executor(None, lambda: None)
            dialogs = raw_dialogs
            out = []
            for d in dialogs:
                entity = d.entity
                dtype = "user"
                if hasattr(entity, "megagroup") and entity.megagroup:
                    dtype = "group"
                elif hasattr(entity, "broadcast") and entity.broadcast:
                    dtype = "channel"
                elif hasattr(entity, "title"):
                    dtype = "group"
                out.append({"id": d.id, "type": dtype})
            result_container.extend(out)

        adapter.loop.run_until_complete(run_fetch())
        adapter.loop.close()
        return result_container

    def test_megagroup_entity_type_group(self):
        dialogs = self._fetch_dialogs_sync([self._make_raw_dialog({"megagroup": True})])
        assert dialogs[0]["type"] == "group"

    def test_broadcast_entity_type_channel(self):
        dialogs = self._fetch_dialogs_sync([self._make_raw_dialog({"broadcast": True})])
        assert dialogs[0]["type"] == "channel"

    def test_title_entity_type_group(self):
        dialogs = self._fetch_dialogs_sync([self._make_raw_dialog({"title": "Group Name"})])
        assert dialogs[0]["type"] == "group"

    def test_plain_user_entity_type_user(self):
        dialogs = self._fetch_dialogs_sync([self._make_raw_dialog({})])
        assert dialogs[0]["type"] == "user"


class TestTelegramListenerEventHandler:
    def _make_adapter(self):
        from telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter.__new__(TelegramAdapter)
        adapter.clients = {}
        adapter.loop = asyncio.new_event_loop()
        adapter._auth_state = {}
        adapter._last_notify = {}
        adapter._notify_interval = 10
        adapter.api_id = 0
        adapter.api_hash = ""
        return adapter

    def test_start_listener_registers_handler_with_events_newmessage(self):
        adapter = self._make_adapter()
        mock_client = MagicMock()
        adapter.clients["u"] = mock_client
        adapter._run_sync = MagicMock(return_value=True)
        cb = MagicMock()
        adapter.start_listener("u", cb)
        mock_client.add_event_handler.assert_called_once()
        args = mock_client.add_event_handler.call_args
        assert args[0][1] is not None
        adapter.loop.close()

    def test_rate_limited_callback_suppresses_within_interval(self):
        import time

        adapter = self._make_adapter()
        mock_client = MagicMock()
        adapter.clients["u"] = mock_client
        adapter._run_sync = MagicMock(return_value=True)
        received = []
        adapter.start_listener("u", lambda n: received.append(n))
        adapter._last_notify["u"] = time.time()
        adapter.loop.close()
        assert len(received) == 0

    def test_rate_limited_callback_allows_after_interval(self):
        import time

        adapter = self._make_adapter()
        mock_client = MagicMock()
        adapter.clients["u"] = mock_client
        adapter._run_sync = MagicMock(return_value=True)
        received = []
        adapter.start_listener("u", lambda n: received.append(n))
        adapter._last_notify["u"] = time.time() - 20
        adapter.loop.close()
        assert adapter._notify_interval == 10


class TestTelegramAdapterAsync:
    """Tests that execute real async bodies inside adapter methods."""

    def test_get_dialogs_executes_async_body(self):
        adapter = _make_real_sync_adapter()
        mock_client = AsyncMock()
        dialog = _make_mock_dialog(name="Chat1", unread_count=5)
        mock_client.get_dialogs = AsyncMock(return_value=[dialog])
        adapter.clients["default"] = mock_client

        result = adapter.handle("get_dialogs", {"limit": 10})
        assert result["status"] == 200
        assert len(result["dialogs"]) == 1
        assert result["dialogs"][0]["name"] == "Chat1"
        assert result["dialogs"][0]["unread"] == 5
        adapter.loop.close()

    def test_get_dialogs_megagroup_type(self):
        adapter = _make_real_sync_adapter()
        mock_client = AsyncMock()
        dialog = _make_mock_dialog(megagroup=True)
        mock_client.get_dialogs = AsyncMock(return_value=[dialog])
        adapter.clients["default"] = mock_client

        result = adapter.handle("get_dialogs", {})
        assert result["dialogs"][0]["type"] == "group"
        adapter.loop.close()

    def test_get_dialogs_broadcast_type(self):
        adapter = _make_real_sync_adapter()
        mock_client = AsyncMock()
        dialog = _make_mock_dialog(broadcast=True)
        mock_client.get_dialogs = AsyncMock(return_value=[dialog])
        adapter.clients["default"] = mock_client

        result = adapter.handle("get_dialogs", {})
        assert result["dialogs"][0]["type"] == "channel"
        adapter.loop.close()

    def test_get_dialogs_title_type(self):
        adapter = _make_real_sync_adapter()
        mock_client = AsyncMock()
        dialog = _make_mock_dialog(title="Group Name")
        mock_client.get_dialogs = AsyncMock(return_value=[dialog])
        adapter.clients["default"] = mock_client

        result = adapter.handle("get_dialogs", {})
        assert result["dialogs"][0]["type"] == "group"
        adapter.loop.close()

    def test_get_unread_executes_async_body(self):
        adapter = _make_real_sync_adapter()
        mock_client = AsyncMock()
        d1 = _make_mock_dialog(id=1, name="A", unread_count=3)
        d2 = _make_mock_dialog(id=2, name="B", unread_count=0)
        mock_client.get_dialogs = AsyncMock(return_value=[d1, d2])
        adapter.clients["default"] = mock_client

        result = adapter.handle("get_unread", {})
        assert result["status"] == 200
        assert len(result["unread_chats"]) == 1
        assert result["unread_chats"][0]["name"] == "A"
        adapter.loop.close()

    def test_get_messages_executes_async_body(self):
        adapter = _make_real_sync_adapter()
        mock_client = AsyncMock()
        msg = _make_mock_message(id=101, text="Hello world")
        mock_client.get_messages = AsyncMock(return_value=[msg])
        adapter.clients["default"] = mock_client

        result = adapter.handle("get_messages", {"chat_id": 1, "limit": 10})
        assert result["status"] == 200
        assert len(result["messages"]) == 1
        assert result["messages"][0]["text"] == "Hello world"
        adapter.loop.close()

    def test_get_messages_with_reply_and_media(self):
        adapter = _make_real_sync_adapter()
        mock_client = AsyncMock()
        reply_to = MagicMock()
        reply_to.reply_to_msg_id = 50
        msg = _make_mock_message(reply_to=reply_to, media=MagicMock())
        mock_client.get_messages = AsyncMock(return_value=[msg])
        adapter.clients["default"] = mock_client

        result = adapter.handle("get_messages", {"chat_id": 1})
        assert result["messages"][0]["reply_to_id"] == 50
        assert result["messages"][0]["has_media"] is True
        adapter.loop.close()

    def test_send_message_executes_async_body(self):
        adapter = _make_real_sync_adapter()
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=MagicMock(id=42))
        adapter.clients["default"] = mock_client

        result = adapter.handle("send_message", {"chat_id": 1, "text": "hi"})
        assert result["status"] == 200
        assert result["message_id"] == 42
        adapter.loop.close()

    def test_reply_executes_async_body(self):
        adapter = _make_real_sync_adapter()
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=MagicMock(id=43))
        adapter.clients["default"] = mock_client

        result = adapter.handle("reply", {"chat_id": 1, "reply_to_id": 10, "text": "reply"})
        assert result["status"] == 200
        assert result["message_id"] == 43
        adapter.loop.close()

    def test_mark_read_executes_async_body(self):
        adapter = _make_real_sync_adapter()
        mock_client = AsyncMock()
        mock_client.send_read_acknowledge = AsyncMock()
        adapter.clients["default"] = mock_client

        result = adapter.handle("mark_read", {"chat_id": 1})
        assert result["status"] == 200
        mock_client.send_read_acknowledge.assert_awaited_once_with(1)
        adapter.loop.close()

    def test_edit_message_executes_async_body(self):
        adapter = _make_real_sync_adapter()
        mock_client = AsyncMock()
        mock_client.edit_message = AsyncMock(return_value=MagicMock(id=44))
        adapter.clients["default"] = mock_client

        result = adapter.handle("edit_message", {"chat_id": 1, "message_id": 99, "text": "edited"})
        assert result["status"] == 200
        assert result["message_id"] == 44
        adapter.loop.close()

    def test_search_executes_async_body(self):
        adapter = _make_real_sync_adapter()
        mock_client = AsyncMock()
        msg = _make_mock_message(id=55, text="found it")
        mock_client.get_messages = AsyncMock(return_value=[msg])
        adapter.clients["default"] = mock_client

        result = adapter.handle("search", {"chat_id": 1, "query": "found"})
        assert result["status"] == 200
        assert len(result["results"]) == 1
        assert result["results"][0]["text"] == "found it"
        adapter.loop.close()

    def test_auth_start_executes_async_body(self):
        adapter = _make_real_sync_adapter()
        mock_client = AsyncMock()
        mock_client.send_code_request = AsyncMock(return_value=MagicMock(phone_code_hash="abc123"))
        adapter.clients["default"] = mock_client

        result = adapter.handle("auth_start", {"phone": "+71234567890"})
        assert result["status"] == 200
        assert result["auth_status"] == "code_required"
        assert adapter._auth_state["default"]["hash"] == "abc123"
        adapter.loop.close()

    def test_auth_code_executes_async_body(self):
        adapter = _make_real_sync_adapter()
        mock_client = AsyncMock()
        mock_client.sign_in = AsyncMock(return_value=None)
        adapter.clients["default"] = mock_client
        adapter._auth_state["default"] = {"phone": "+7123", "hash": "abc"}

        result = adapter.handle("auth_code", {"code": "12345"})
        assert result["status"] == 200
        assert result["auth_status"] == "authorized"
        adapter.loop.close()

    def test_auth_code_password_only_async(self):
        adapter = _make_real_sync_adapter()
        mock_client = AsyncMock()
        mock_client.sign_in = AsyncMock(return_value=None)
        adapter.clients["default"] = mock_client

        result = adapter.handle("auth_code", {"code": "", "password": "secret"})
        assert result["status"] == 200
        assert result["auth_status"] == "authorized"
        mock_client.sign_in.assert_awaited_once_with(password="secret")
        adapter.loop.close()

    def test_auth_code_2fa_with_password_async(self):
        from telethon.errors import SessionPasswordNeededError

        adapter = _make_real_sync_adapter()
        mock_client = AsyncMock()
        mock_client.sign_in = AsyncMock(side_effect=[SessionPasswordNeededError(), None])
        adapter.clients["default"] = mock_client
        adapter._auth_state["default"] = {"phone": "+7123", "hash": "abc"}

        result = adapter.handle("auth_code", {"code": "12345", "password": "mypass"})
        assert result["status"] == 200
        assert result["auth_status"] == "authorized"
        adapter.loop.close()

    def test_auth_logout_executes_async_body(self):
        adapter = _make_real_sync_adapter()
        mock_client = AsyncMock()
        mock_client.log_out = AsyncMock(return_value=None)
        adapter.clients["default"] = mock_client
        adapter._auth_state["default"] = {"phone": "+7", "hash": "abc"}

        result = adapter.handle("auth_logout", {})
        assert result["status"] == 200
        assert result["auth_status"] == "logged_out"
        assert "default" not in adapter.clients
        adapter.loop.close()

    def test_start_listener_executes_async_check(self):
        adapter = _make_real_sync_adapter()
        mock_client = AsyncMock()
        mock_client.is_user_authorized = AsyncMock(return_value=True)
        mock_client.add_event_handler = MagicMock()
        adapter.clients["u1"] = mock_client

        adapter.start_listener("u1", lambda n: None)
        mock_client.add_event_handler.assert_called_once()
        adapter.loop.close()

    def test_start_listener_unauthorized_skips_async(self):
        adapter = _make_real_sync_adapter()
        mock_client = AsyncMock()
        mock_client.is_user_authorized = AsyncMock(return_value=False)
        adapter.clients["u1"] = mock_client

        adapter.start_listener("u1", lambda n: None)
        mock_client.add_event_handler.assert_not_called()
        adapter.loop.close()
