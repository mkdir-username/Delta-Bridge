"""Latency telemetry for Delta-Bridge IoE transport."""

from __future__ import annotations

import time
import threading
from collections import deque
from typing import Any


class Timer:
    """Context manager for timing code blocks."""

    def __init__(self) -> None:
        self._start: float = 0.0
        self.elapsed_ms: float = 0.0

    def __enter__(self) -> Timer:
        self._start = time.monotonic()
        return self

    def __exit__(self, *_: object) -> None:
        self.elapsed_ms = (time.monotonic() - self._start) * 1000


class RequestTiming:
    """Structured timing for a single request lifecycle."""

    def __init__(self, req_id: str) -> None:
        self.req_id = req_id
        self.phases: dict[str, float] = {}
        self._start = time.monotonic()

    def record(self, phase: str, ms: float) -> None:
        self.phases[phase] = ms

    @property
    def total_ms(self) -> float:
        return (time.monotonic() - self._start) * 1000

    def summary(self) -> dict[str, Any]:
        return {
            "req_id": self.req_id,
            "total_ms": round(self.total_ms, 1),
            "phases": {k: round(v, 1) for k, v in self.phases.items()},
        }


class TelemetryCollector:
    """Rolling average collector for latency metrics."""

    def __init__(self, max_entries: int = 100) -> None:
        self._entries: deque[dict[str, Any]] = deque(maxlen=max_entries)
        self._lock = threading.Lock()

    def record(self, timing: RequestTiming) -> None:
        with self._lock:
            self._entries.append(timing.summary())

    def stats(self) -> dict[str, Any]:
        with self._lock:
            if not self._entries:
                return {"count": 0, "avg_ms": 0.0, "phases": {}}
            count = len(self._entries)
            totals = [e["total_ms"] for e in self._entries]
            phase_sums: dict[str, list[float]] = {}
            for entry in self._entries:
                for phase, ms in entry["phases"].items():
                    phase_sums.setdefault(phase, []).append(ms)
            return {
                "count": count,
                "avg_ms": round(sum(totals) / count, 1),
                "phases": {k: round(sum(v) / len(v), 1) for k, v in phase_sums.items()},
            }


collector = TelemetryCollector()
