import subprocess
import json
import logging
import threading

log = logging.getLogger("claude-chat")

CLAUDE_BIN = "claude"
CLAUDE_TIMEOUT = 300
DEFAULT_MODEL = "sonnet"
MAX_BUDGET_USD = 1.0


class ClaudeChat:
    def __init__(self):
        self._sessions = {}
        self._lock = threading.Lock()

    def send_message(self, user_id, text, model=None):
        cmd = [
            CLAUDE_BIN, "-p", text,
            "--output-format", "json",
            "--bare",
            "--model", model or DEFAULT_MODEL,
            "--max-budget-usd", str(MAX_BUDGET_USD),
        ]
        with self._lock:
            sid = self._sessions.get(user_id)
        if sid:
            cmd.extend(["--resume", sid])

        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=CLAUDE_TIMEOUT, cwd="/tmp"
            )
            if proc.returncode != 0:
                return {"error": proc.stderr.strip() or "claude exited with error", "exit_code": proc.returncode}

            result = json.loads(proc.stdout)
            new_sid = result.get("session_id", sid)
            if new_sid:
                with self._lock:
                    self._sessions[user_id] = new_sid

            model_usage = result.get("modelUsage", {})
            model_name = next(iter(model_usage), None)

            return {
                "response": result.get("result", ""),
                "session_id": new_sid,
                "cost": result.get("total_cost_usd"),
                "duration": result.get("duration_ms"),
                "model": model_name,
            }
        except subprocess.TimeoutExpired:
            return {"error": "timeout ({}s)".format(CLAUDE_TIMEOUT)}
        except json.JSONDecodeError:
            return {"response": proc.stdout, "session_id": sid}
        except FileNotFoundError:
            return {"error": "claude CLI not found on VPS"}

    def check_auth(self):
        try:
            proc = subprocess.run(
                [CLAUDE_BIN, "auth", "status"],
                capture_output=True, text=True, timeout=10
            )
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                return {
                    "status": "authorized",
                    "email": data.get("email"),
                    "subscription": data.get("subscriptionType"),
                }
            return {"status": "not_authorized"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def new_conversation(self, user_id):
        with self._lock:
            self._sessions.pop(user_id, None)
        return {"status": "ok"}
