"""Shared type definitions for Delta-Bridge IoE protocol."""

from __future__ import annotations
from typing import Any, TypedDict, NotRequired


class BaseRequest(TypedDict):
    id: str
    user_id: NotRequired[str]


class CmdRequest(BaseRequest):
    cmd: str
    url: NotRequired[str]
    query: NotRequired[str]


class HttpProxyRequest(BaseRequest):
    type: str
    method: str
    url: str
    extract: NotRequired[bool]
    body: NotRequired[str | dict[str, Any]]
    session_id: NotRequired[str]


class TelegramRequest(BaseRequest):
    type: str
    service: str
    action: str
    phone: NotRequired[str]
    code: NotRequired[str]
    password: NotRequired[str]
    chat_id: NotRequired[str | int]
    text: NotRequired[str]
    limit: NotRequired[str]
    offset_id: NotRequired[str]
    reply_to_id: NotRequired[str]
    message_id: NotRequired[str]
    folder: NotRequired[str]
    query: NotRequired[str]


class ClaudeChatRequest(BaseRequest):
    type: str
    action: str
    text: str
    model: NotRequired[str]
    session_id: NotRequired[str]


class BrowserRequest(BaseRequest):
    type: str
    url: str
    actions: list[str]


class ClaudeProxyRequest(BaseRequest):
    type: str
    http_request: dict[str, object]


class BaseResponse(TypedDict):
    id: str
    status: NotRequired[int]
    error: NotRequired[str]
    user_id: NotRequired[str]


class SearchResult(TypedDict):
    title: str
    href: str
    snippet: str


class SmartExtractResult(TypedDict):
    format: str
    type: str
    title: str
    body: str
    domain: str
    word_count: int


class HttpProxyResponse(BaseResponse):
    type: str
    status_code: int
    headers: dict[str, str]
    body: str
    url: str
    extracted: NotRequired[SmartExtractResult]


class ClaudeChatResponse(TypedDict):
    response: NotRequired[str]
    error: NotRequired[str]
    exit_code: NotRequired[int]
    session_id: NotRequired[str]
    model: NotRequired[str]
    input_tokens: NotRequired[int]
    output_tokens: NotRequired[int]


class NotificationData(TypedDict):
    type: str
    service: str
    user_id: str
    chat_id: int
    sender: str
    chat_name: str
    text: str
    timestamp: str


class SessionData(TypedDict):
    user_id: str
    created: float
    last_seen: float


class OTPEntry(TypedDict):
    code: str
    created: float
    ip: str | None


class WhitelistEntry(TypedDict):
    password: str
    email: NotRequired[str]


Whitelist = dict[str, WhitelistEntry]
SessionStore = dict[str, SessionData]
RateStore = dict[str, list[float]]
PendingStore = dict[tuple[str, str], BaseResponse]


class TelegramAuthState(TypedDict):
    phone_hash: NotRequired[str]
    status: NotRequired[str]
