import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
from unittest.mock import MagicMock, patch
import importlib

def make_adapter():
    with patch.dict("sys.modules", {
        "telethon": MagicMock(), "telethon.tl": MagicMock(),
        "telethon.tl.functions": MagicMock(),
        "telethon.tl.functions.messages": MagicMock(),
        "telethon.errors": MagicMock(),
    }):
        import telegram_adapter
        importlib.reload(telegram_adapter)
        a = telegram_adapter.TelegramAdapter(api_id=1, api_hash="t")
        a.loop = MagicMock()
        return a

def _mock():
    return patch("asyncio.run_coroutine_threadsafe",
                 return_value=MagicMock(result=MagicMock(return_value=None)))

def test_auth_logout_removes_client():
    a = make_adapter()
    a.clients["+7"] = MagicMock()
    a._auth_state["+7"] = {"phone": "+7"}
    with _mock():
        r = a.handle("auth_logout", {"user_id": "+7"})
    assert r["status"] == 200
    assert r["auth_status"] == "logged_out"
    assert "+7" not in a.clients

def test_auth_logout_handles_error():
    a = make_adapter()
    a.clients["u"] = MagicMock()
    f = MagicMock(); f.result.side_effect = Exception("fail")
    with patch("asyncio.run_coroutine_threadsafe", return_value=f):
        r = a.handle("auth_logout", {"user_id": "u"})
    assert r["auth_status"] == "logged_out"
    assert "u" not in a.clients

def test_auth_logout_unknown():
    a = make_adapter()
    with patch.object(a, "_get_client", return_value=MagicMock()):
        with _mock():
            r = a.handle("auth_logout", {"user_id": "x"})
    assert r["auth_status"] == "logged_out"
