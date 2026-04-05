import os
import sys
import json
from unittest.mock import patch, MagicMock

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_root, "server"))


class TestClaudeChatSendMessage:
    def test_send_message_returns_response(self):
        from claude_chat import ClaudeChat

        fake_output = json.dumps(
            {
                "type": "result",
                "result": "Hello! How can I help?",
                "session_id": "sess-abc-123",
                "total_cost_usd": 0.05,
                "duration_ms": 2000,
                "modelUsage": {"claude-sonnet-4-6": {"costUSD": 0.05}},
            }
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=fake_output, stderr="")
            chat = ClaudeChat()
            result = chat.send_message("user1", "hello")

        assert result["response"] == "Hello! How can I help?"
        assert result["session_id"] == "sess-abc-123"
        assert result["cost"] == 0.05
        assert result["model"] == "claude-sonnet-4-6"
        assert result["duration"] == 2000

    def test_send_message_passes_resume_flag(self):
        from claude_chat import ClaudeChat

        fake_output = json.dumps(
            {
                "type": "result",
                "result": "yes",
                "session_id": "sess-abc-123",
                "total_cost_usd": 0.01,
                "duration_ms": 500,
                "modelUsage": {},
            }
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=fake_output, stderr="")
            chat = ClaudeChat()
            chat._sessions["user1"] = "prev-session-id"
            chat.send_message("user1", "continue")

        cmd = mock_run.call_args[0][0]
        assert "--resume" in cmd
        assert "prev-session-id" in cmd

    def test_send_message_timeout(self):
        import subprocess
        from claude_chat import ClaudeChat

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 300)):
            chat = ClaudeChat()
            result = chat.send_message("user1", "hello")

        assert "error" in result
        assert "timeout" in result["error"].lower()

    def test_send_message_cli_not_found(self):
        from claude_chat import ClaudeChat

        with patch("subprocess.run", side_effect=FileNotFoundError):
            chat = ClaudeChat()
            result = chat.send_message("user1", "hello")

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_send_message_cli_error(self):
        from claude_chat import ClaudeChat

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not authenticated")
            chat = ClaudeChat()
            result = chat.send_message("user1", "hello")

        assert "error" in result
        assert result["exit_code"] == 1


class TestClaudeChatAuth:
    def test_check_auth_authorized(self):
        from claude_chat import ClaudeChat

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"loggedIn": true, "email": "test@example.com", "subscriptionType": "max"}',
                stderr="",
            )
            chat = ClaudeChat()
            result = chat.check_auth()

        assert result["status"] == "authorized"
        assert result["email"] == "test@example.com"
        cmd = mock_run.call_args[0][0]
        assert cmd == ["claude", "auth", "status"]

    def test_check_auth_not_authorized(self):
        from claude_chat import ClaudeChat

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not logged in")
            chat = ClaudeChat()
            result = chat.check_auth()

        assert result["status"] == "not_authorized"


class TestClaudeChatSession:
    def test_new_conversation_clears_session(self):
        from claude_chat import ClaudeChat

        chat = ClaudeChat()
        chat._sessions["user1"] = "some-session"
        result = chat.new_conversation("user1")

        assert result["status"] == "ok"
        assert "user1" not in chat._sessions

    def test_session_persists_after_send(self):
        from claude_chat import ClaudeChat

        fake_output = json.dumps(
            {
                "type": "result",
                "result": "hi",
                "session_id": "new-sess-456",
                "total_cost_usd": 0.01,
                "duration_ms": 100,
                "modelUsage": {},
            }
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=fake_output, stderr="")
            chat = ClaudeChat()
            chat.send_message("user1", "hello")

        assert chat._sessions["user1"] == "new-sess-456"
