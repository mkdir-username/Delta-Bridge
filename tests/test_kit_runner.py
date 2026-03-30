import sys, os

_root = os.path.dirname(os.path.dirname(__file__))
if os.path.join(_root, "client") not in sys.path:
    sys.path.append(os.path.join(_root, "client"))

import json
from kit_runner import KitRunner

class TestKitRunnerBasic:
    def test_unknown_action(self):
        runner = KitRunner(lambda r: {})
        result = runner.run({"actions": {}}, "nonexistent")
        assert "error" in result

    def test_http_step_calls_proxy(self):
        calls = []
        def mock_proxy(req):
            calls.append(req)
            return {"status_code": 200, "body": "ok"}
        runner = KitRunner(mock_proxy)
        kit = {"actions": {"test": {"steps": [{"type": "http", "method": "GET", "url": "https://example.com"}]}}}
        runner.run(kit, "test")
        assert len(calls) == 1
        assert calls[0]["url"] == "https://example.com"

    def test_interpolation(self):
        runner = KitRunner(lambda r: {})
        runner.variables = {"id": "123"}
        assert runner._interpolate("https://api.com/item/{id}") == "https://api.com/item/123"

    def test_extract_json_slice(self):
        runner = KitRunner(lambda r: {"body": json.dumps([1,2,3,4,5])})
        kit = {"actions": {"t": {"steps": [
            {"type": "http", "method": "GET", "url": "https://x.com"},
            {"type": "extract", "source": "body", "path": "$[:3]", "as": "items"}
        ]}}}
        result = runner.run(kit, "t")
        assert result["variables"]["items"] == [1, 2, 3]

    def test_params_as_variables(self):
        calls = []
        runner = KitRunner(lambda r: (calls.append(r), {"body": "{}"})[1])
        kit = {"actions": {"d": {"steps": [{"type": "http", "method": "GET", "url": "https://api.com/{id}"}]}}}
        runner.run(kit, "d", params={"id": "42"})
        assert calls[0]["url"] == "https://api.com/42"

    def test_extract_field(self):
        runner = KitRunner(lambda r: {"body": json.dumps({"title": "Hello"})})
        kit = {"actions": {"t": {"steps": [
            {"type": "http", "method": "GET", "url": "https://x.com"},
            {"type": "extract", "source": "body", "path": "$.title", "as": "name"}
        ]}}}
        assert runner.run(kit, "t")["variables"]["name"] == "Hello"

class TestKitRunnerLoop:
    def test_loop_iterates(self):
        n = [0]
        runner = KitRunner(lambda r: (n.__setitem__(0, n[0]+1), {"body": "{}"})[1])
        runner.variables = {"ids": [10, 20, 30]}
        kit = {"actions": {"a": {"steps": [{"type": "loop", "over": "{ids}", "as": "id", "steps": [
            {"type": "http", "method": "GET", "url": "https://api.com/{id}"}
        ]}]}}}
        runner.run(kit, "a")
        assert n[0] == 3

class TestHackerNewsKit:
    def test_kit_loads(self):
        kit_path = os.path.join(os.path.dirname(__file__), "..", "kits", "hackernews.json")
        kit = KitRunner(lambda r: {}).load_kit(kit_path)
        assert kit["service"] == "hackernews"
        assert "top_stories" in kit["actions"]
        assert "story_detail" in kit["actions"]

    def test_auth_template_loads(self):
        kit_path = os.path.join(os.path.dirname(__file__), "..", "kits", "_template_auth.json")
        kit = KitRunner(lambda r: {}).load_kit(kit_path)
        assert kit["auth"] == "cookie"
        assert "login" in kit["actions"]
