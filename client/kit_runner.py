from __future__ import annotations
from typing import Any, Callable

import json
import re


class KitRunner:
    def __init__(self, proxy_func: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self.proxy_func: Callable[[dict[str, Any]], dict[str, Any]] = proxy_func
        self.variables: dict[str, Any] = {}

    def load_kit(self, kit_path: str) -> dict[str, Any]:
        with open(kit_path) as f:
            result: dict[str, Any] = json.load(f)
            return result

    def run(self, kit: dict[str, Any], action_name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.variables.update(params or {})
        action = kit.get("actions", {}).get(action_name)
        if not action:
            return {"error": "unknown action: {}".format(action_name)}
        return self._execute_steps(action.get("steps", []))

    def _execute_steps(self, steps: list[dict[str, Any]]) -> dict[str, Any]:
        last_response: dict[str, Any] | None = None
        for step in steps:
            t = step.get("type")
            if t == "http":
                last_response = self._step_http(step)
            elif t == "extract":
                self._step_extract(step, last_response)
            elif t == "loop":
                last_response = {"results": self._step_loop(step)}
        return {"variables": dict(self.variables), "last_response": last_response}

    def _interpolate(self, text: str) -> str:
        return re.sub(r'\{(\w+)\}', lambda m: str(self.variables.get(m.group(1), m.group(0))), text)

    def _step_http(self, step: dict[str, Any]) -> dict[str, Any]:
        req: dict[str, Any] = {"type": "http", "method": step.get("method", "GET"), "url": self._interpolate(step.get("url", "")), "extract": False}
        if step.get("headers"):
            req["headers"] = step["headers"]
        if step.get("body"):
            req["body"] = step["body"]
        return self.proxy_func(req)

    def _step_extract(self, step: dict[str, Any], response: dict[str, Any] | None) -> None:
        if not response:
            return
        body: Any = response.get("body", response.get("raw_body", ""))
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                pass
        self.variables[step.get("as", "result")] = self._jsonpath(body, step.get("path", "$"))

    def _step_loop(self, step: dict[str, Any]) -> list[dict[str, Any]]:
        items = self.variables.get(step.get("over", "").strip("{}"), [])
        var = step.get("as", "item")
        results: list[dict[str, Any]] = []
        for item in items:
            self.variables[var] = item
            results.append(self._execute_steps(step.get("steps", [])))
        return results

    def _jsonpath(self, data: Any, path: str) -> Any:
        if path == "$":
            return data
        if path.startswith("$[:") and path.endswith("]"):
            return data[:int(path[3:-1])] if isinstance(data, list) else data
        if path.startswith("$."):
            return data.get(path[2:]) if isinstance(data, dict) else data
        return data
