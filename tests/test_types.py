def test_types_importable():
    from ioe_types import BaseRequest, BaseResponse, SessionData, OTPEntry
    from ioe_types import HttpProxyRequest, TelegramRequest, ClaudeChatRequest
    from ioe_types import SearchResult, SmartExtractResult, WhitelistEntry


def test_typed_dict_construction():
    from ioe_types import SessionData, SearchResult
    s: SessionData = {"user_id": "+7999", "created": 1.0, "last_seen": 2.0}
    r: SearchResult = {"title": "t", "href": "h", "snippet": "s"}
    assert s["user_id"] == "+7999"
    assert r["title"] == "t"
