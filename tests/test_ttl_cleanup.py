"""TTL-based cleanup для unbounded memory structures."""

from __future__ import annotations

import time
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webui"))


class TestLoginRequestOwnersTTL:
    """_login_request_owners хранит (user_id, timestamp) и чистится по TTL."""

    def test_stores_with_timestamp(self):
        from webui.handler import _login_request_owners

        _login_request_owners.clear()
        _login_request_owners["req1"] = ("user1", time.time())
        assert _login_request_owners["req1"][0] == "user1"
        assert isinstance(_login_request_owners["req1"][1], float)

    def test_cleanup_removes_old_entries(self):
        from webui.handler import _login_request_owners, _cleanup_login_owners

        _login_request_owners.clear()
        old = time.time() - 700
        fresh = time.time()
        _login_request_owners["old"] = ("user_old", old)
        _login_request_owners["fresh"] = ("user_fresh", fresh)

        _cleanup_login_owners()

        assert "old" not in _login_request_owners
        assert "fresh" in _login_request_owners

    def test_get_returns_user_id(self):
        from webui.handler import _login_request_owners

        _login_request_owners.clear()
        _login_request_owners["req1"] = ("user1", time.time())
        entry = _login_request_owners.get("req1")
        assert entry is not None
        assert entry[0] == "user1"

    def test_get_missing_returns_none(self):
        from webui.handler import _login_request_owners

        _login_request_owners.clear()
        assert _login_request_owners.get("missing") is None


class TestSeenNotificationUidsCap:
    """seen_notification_uids очищается при превышении 500."""

    def test_lru_trims_to_limit(self):
        import webui.ioe_web as ioe_web
        from webui.ioe_web import _trim_seen_uids

        ioe_web.seen_notification_uids.clear()
        ioe_web._seen_set.clear()
        for i in range(ioe_web._SEEN_UIDS_MAX + 50):
            uid = str(i)
            ioe_web.seen_notification_uids.append(uid)
            ioe_web._seen_set.add(uid)
            _trim_seen_uids()
        assert len(ioe_web._seen_set) <= ioe_web._SEEN_UIDS_MAX
        assert str(ioe_web._SEEN_UIDS_MAX + 49) in ioe_web._seen_set

    def test_no_trim_under_limit(self):
        import webui.ioe_web as ioe_web
        from webui.ioe_web import _trim_seen_uids

        ioe_web.seen_notification_uids.clear()
        ioe_web._seen_set.clear()
        for i in range(100):
            uid = str(i)
            ioe_web.seen_notification_uids.append(uid)
            ioe_web._seen_set.add(uid)
        _trim_seen_uids()
        assert len(ioe_web._seen_set) == 100


class TestPendingTTL:
    """pending entries очищаются по TTL."""

    def test_cleanup_removes_old_pending(self):
        import webui.ioe_web as ioe_web
        from webui.ioe_web import _cleanup_pending

        with ioe_web.lock:
            ioe_web.pending.clear()
            old_ts = time.time() - 700
            fresh_ts = time.time()
            ioe_web.pending[("user1", "old_req")] = {
                "status": 200,
                "_created": old_ts,
            }
            ioe_web.pending[("user2", "fresh_req")] = {
                "status": 200,
                "_created": fresh_ts,
            }

        _cleanup_pending()

        with ioe_web.lock:
            assert ("user1", "old_req") not in ioe_web.pending
            assert ("user2", "fresh_req") in ioe_web.pending

    def test_no_cleanup_for_fresh(self):
        import webui.ioe_web as ioe_web
        from webui.ioe_web import _cleanup_pending

        with ioe_web.lock:
            ioe_web.pending.clear()
            ioe_web.pending[("u", "r")] = {
                "status": 200,
                "_created": time.time(),
            }

        _cleanup_pending()

        with ioe_web.lock:
            assert ("u", "r") in ioe_web.pending
