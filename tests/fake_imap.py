"""FakeIMAPClient — drop-in for imapclient.IMAPClient in e2e tests."""

from __future__ import annotations

import imaplib
from typing import Any


class FakeIMAPClient:
    """State machine mimicking imapclient.IMAPClient used by server.main()."""

    MODES = ("normal", "zombie", "timeout", "disconnected")

    def __init__(self, host: str = "", ssl: bool = True) -> None:
        self._messages: dict[int, bytes] = {}
        self._mode = "normal"
        self._zombie_after: int | None = None
        self._appended: list[tuple[str, bytes]] = []
        self._deleted: list[int] = []
        self._selected_folder: str | None = None
        self._connected = True
        self.noop_count = 0
        self.search_count = 0

    # --- test helpers ---

    def inject_message(self, uid: int, raw_bytes: bytes) -> None:
        self._messages[uid] = raw_bytes

    def set_mode(self, mode: str) -> None:
        assert mode in self.MODES, f"unknown mode: {mode}"
        self._mode = mode

    def set_zombie_after(self, ticks: int) -> None:
        """Auto-switch to zombie mode after N noop() calls."""
        self._zombie_after = ticks

    # --- context manager ---

    def __enter__(self) -> FakeIMAPClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self._connected = False

    # --- IMAP interface ---

    def login(self, user: str, password: str) -> None:
        self._assert_connected()

    def select_folder(self, folder: str) -> None:
        self._assert_connected()
        self._selected_folder = folder

    def noop(self) -> None:
        self._assert_connected()
        self.noop_count += 1
        if self._zombie_after is not None and self.noop_count >= self._zombie_after:
            self._mode = "zombie"
        if self._mode == "timeout":
            raise TimeoutError("fake timeout")
        if self._mode == "disconnected":
            raise imaplib.IMAP4.abort("fake disconnect")

    def search(self, criteria: list[str]) -> list[int]:
        self._assert_connected()
        self.search_count += 1
        if self._mode == "zombie":
            return []
        if self._mode == "timeout":
            raise TimeoutError("fake timeout on search")
        return list(self._messages.keys())

    def fetch(self, uids: list[int], data: list[str]) -> dict[int, dict[bytes, bytes]]:
        self._assert_connected()
        return {uid: {b"RFC822": self._messages[uid]} for uid in uids if uid in self._messages}

    def delete_messages(self, uids: list[int]) -> None:
        self._assert_connected()
        for uid in uids:
            self._deleted.append(uid)
            self._messages.pop(uid, None)

    def expunge(self) -> None:
        self._assert_connected()

    def append(self, folder: str, raw_bytes: bytes) -> None:
        self._appended.append((folder, raw_bytes))

    def logout(self) -> None:
        self._connected = False

    def _assert_connected(self) -> None:
        if not self._connected:
            raise imaplib.IMAP4.abort("not connected")
