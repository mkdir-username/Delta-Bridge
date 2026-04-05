def test_types_importable():
    pass


def test_typed_dict_construction():
    from ioe_types import SessionData, SearchResult

    s: SessionData = {"user_id": "+7999", "created": 1.0, "last_seen": 2.0}
    r: SearchResult = {"title": "t", "href": "h", "snippet": "s"}
    assert s["user_id"] == "+7999"
    assert r["title"] == "t"
