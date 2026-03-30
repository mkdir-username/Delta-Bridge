"""Telegram adapter: Telethon wrapper for IoE commands."""
import os
import asyncio
import logging
import threading
import time
from datetime import datetime

log = logging.getLogger("ioe.telegram")

try:
    from telethon import TelegramClient
    from telethon.tl.functions.messages import GetDialogsRequest, ReadHistoryRequest
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False


class TelegramAdapter:
    def __init__(self, api_id=None, api_hash=None, session_path=None):
        if not TELETHON_AVAILABLE:
            raise ImportError("telethon not installed")
        self.api_id = api_id or int(os.environ.get("TG_API_ID", "0"))
        self.api_hash = api_hash or os.environ.get("TG_API_HASH", "")
        self.session_path = session_path or os.environ.get("TG_SESSION", "ioe_telegram")
        self.clients = {}
        self.client = None
        self.loop = None
        self._thread = None
        self._auth_state = {}
        self._last_notify = {}
        self._notify_interval = 10

    def start(self):
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        log.info("Telegram event loop started")

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _run_sync(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout=30)

    def _get_client(self, user_id):
        if user_id not in self.clients:
            session_path = "ioe_telegram_{}".format(user_id)
            client = TelegramClient(session_path, self.api_id, self.api_hash, loop=self.loop)
            self._run_sync(client.connect())
            self.clients[user_id] = client
        return self.clients[user_id]

    def is_authorized(self, user_id="default"):
        if user_id not in self.clients:
            return False
        client = self.clients[user_id]
        return self._run_sync(client.is_user_authorized())

    def handle(self, action, params):
        actions = {
            "get_dialogs": self._get_dialogs,
            "get_messages": self._get_messages,
            "send_message": self._send_message,
            "reply": self._reply,
            "mark_read": self._mark_read,
            "get_unread": self._get_unread,
            "edit_message": self._edit_message,
            "search": self._search,
            "auth_start": self._auth_start,
            "auth_code": self._auth_code,
        }
        handler = actions.get(action)
        if not handler:
            return {"status": 400, "error": f"unknown telegram action: {action}"}
        try:
            user_id = params.get("user_id", "default")
            client = self._get_client(user_id)
            result = handler(client, params)
            return {"status": 200, **result}
        except Exception as e:
            log.error("Telegram action %s failed: %s", action, e)
            return {"status": 500, "error": str(e)}

    def start_listener(self, user_id, notify_callback):
        client = self._get_client(user_id)
        if not self._run_sync(client.is_user_authorized()):
            return

        def _rate_limited_callback(notification):
            now = time.time()
            uid = notification.get("user_id", "default")
            if now - self._last_notify.get(uid, 0) < self._notify_interval:
                return
            self._last_notify[uid] = now
            notify_callback(notification)

        async def _on_new_message(event):
            sender = await event.get_sender()
            sender_name = getattr(sender, 'first_name', '') or str(getattr(sender, 'id', ''))
            chat = await event.get_chat()
            chat_name = getattr(chat, 'title', '') or getattr(chat, 'first_name', '') or str(chat.id)
            notification = {
                "type": "notification",
                "service": "telegram",
                "user_id": user_id,
                "chat_id": chat.id,
                "sender": sender_name,
                "chat_name": chat_name,
                "text": (event.text or "")[:200],
                "timestamp": event.date.isoformat() if event.date else "",
            }
            _rate_limited_callback(notification)

        from telethon import events
        client.add_event_handler(_on_new_message, events.NewMessage(incoming=True))
        log.info("Telegram listener started for user_id=%s", user_id)

    def _get_dialogs(self, client, params):
        limit = params.get("limit", 20)

        async def _fetch():
            dialogs = await client.get_dialogs(limit=limit)
            result = []
            for d in dialogs:
                entity = d.entity
                dtype = "user"
                if hasattr(entity, 'megagroup') and entity.megagroup:
                    dtype = "group"
                elif hasattr(entity, 'broadcast') and entity.broadcast:
                    dtype = "channel"
                elif hasattr(entity, 'title'):
                    dtype = "group"
                result.append({
                    "id": d.id,
                    "name": d.name or "",
                    "unread": d.unread_count,
                    "last_message": d.message.text if d.message else "",
                    "date": d.date.isoformat() if d.date else "",
                    "type": dtype,
                    "archived": d.archived,
                    "pinned": d.pinned,
                })
            return result

        dialogs = self._run_sync(_fetch())
        return {"dialogs": dialogs}

    def _get_unread(self, client, params):
        limit = params.get("limit", 50)

        async def _fetch():
            dialogs = await client.get_dialogs(limit=limit)
            return [
                {"id": d.id, "name": d.name or "", "unread": d.unread_count}
                for d in dialogs if d.unread_count > 0
            ]

        unread = self._run_sync(_fetch())
        return {"unread_chats": unread}

    def _get_messages(self, client, params):
        chat_id = params.get("chat_id")
        limit = params.get("limit", 20)

        async def _fetch():
            messages = await client.get_messages(chat_id, limit=limit)
            result = []
            for m in messages:
                msg = {
                    "id": m.id,
                    "sender": getattr(m.sender, "first_name", "") or str(m.sender_id or ""),
                    "text": m.text or "",
                    "date": m.date.isoformat() if m.date else "",
                    "out": m.out,
                }
                if m.reply_to:
                    msg["reply_to_id"] = m.reply_to.reply_to_msg_id
                if m.media:
                    msg["has_media"] = True
                result.append(msg)
            return result

        messages = self._run_sync(_fetch())
        return {"messages": messages}

    def _send_message(self, client, params):
        chat_id = params.get("chat_id")
        text = params.get("text", "")

        async def _send():
            msg = await client.send_message(chat_id, text)
            return msg.id

        msg_id = self._run_sync(_send())
        return {"message_id": msg_id}

    def _reply(self, client, params):
        chat_id = params.get("chat_id")
        reply_to = params.get("reply_to_id")
        text = params.get("text", "")

        async def _send():
            msg = await client.send_message(chat_id, text, reply_to=reply_to)
            return msg.id

        msg_id = self._run_sync(_send())
        return {"message_id": msg_id}

    def _mark_read(self, client, params):
        chat_id = params.get("chat_id")

        async def _mark():
            await client.send_read_acknowledge(chat_id)

        self._run_sync(_mark())
        return {}

    def _edit_message(self, client, params):
        chat_id = params.get("chat_id")
        message_id = params.get("message_id")
        text = params.get("text", "")

        async def _edit():
            msg = await client.edit_message(chat_id, message_id, text)
            return msg.id

        msg_id = self._run_sync(_edit())
        return {"message_id": msg_id}

    def _search(self, client, params):
        chat_id = params.get("chat_id")
        query = params.get("query", "")
        limit = params.get("limit", 10)

        async def _do_search():
            messages = await client.get_messages(chat_id, search=query, limit=limit)
            return [
                {"id": m.id, "text": m.text or "", "date": m.date.isoformat() if m.date else ""}
                for m in messages
            ]

        results = self._run_sync(_do_search())
        return {"results": results}

    def _auth_start(self, client, params):
        phone = params.get("phone", "")
        user_id = params.get("user_id", "default")

        async def _start():
            result = await client.send_code_request(phone)
            return result

        sent = self._run_sync(_start())
        self._auth_state[user_id] = {"phone": phone, "hash": sent.phone_code_hash}
        return {"auth_status": "code_required"}

    def _auth_code(self, client, params):
        code = params.get("code", "")
        password = params.get("password")
        user_id = params.get("user_id", "default")
        state = self._auth_state.get(user_id, {})
        phone = state.get("phone", params.get("phone", ""))
        phone_code_hash = state.get("hash", "")

        async def _complete():
            try:
                await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
            except Exception:
                if password:
                    await client.sign_in(password=password)
                else:
                    raise

        self._run_sync(_complete())
        return {"auth_status": "authorized"}
