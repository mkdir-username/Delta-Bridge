"""Тесты ioe_telemetry: latency tracking."""

from __future__ import annotations

import time
from unittest.mock import patch

from ioe_telemetry import RequestTiming, TelemetryCollector, Timer


class TestTimer:
    def test_measures_elapsed(self) -> None:
        times = [0.0, 0.05]
        with patch("ioe_telemetry.time.monotonic", side_effect=times), Timer() as t:
            pass
        assert 49 < t.elapsed_ms < 51

    def test_zero_duration(self) -> None:
        with patch("ioe_telemetry.time.monotonic", side_effect=[1.0, 1.0]), Timer() as t:
            pass
        assert t.elapsed_ms == 0.0


class TestRequestTiming:
    def test_record_phases(self) -> None:
        rt = RequestTiming("req-1")
        rt.record("connect", 120.5)
        rt.record("append", 45.3)
        assert rt.phases == {"connect": 120.5, "append": 45.3}

    def test_summary_includes_all_fields(self) -> None:
        rt = RequestTiming("req-2")
        rt.record("fetch", 10.0)
        s = rt.summary()
        assert s["req_id"] == "req-2"
        assert "total_ms" in s
        assert s["phases"]["fetch"] == 10.0

    def test_total_ms_increases(self) -> None:
        rt = RequestTiming("req-3")
        time.sleep(0.01)
        assert rt.total_ms > 0


class TestTelemetryCollector:
    def test_empty_stats(self) -> None:
        tc = TelemetryCollector()
        s = tc.stats()
        assert s["count"] == 0
        assert s["avg_ms"] == 0.0

    def test_records_and_averages(self) -> None:
        tc = TelemetryCollector()
        for i in range(3):
            rt = RequestTiming(f"r-{i}")
            rt.record("connect", 100.0 + i * 10)
            rt.record("append", 50.0)
            tc.record(rt)
        s = tc.stats()
        assert s["count"] == 3
        assert s["phases"]["connect"] == 110.0
        assert s["phases"]["append"] == 50.0

    def test_max_entries_eviction(self) -> None:
        tc = TelemetryCollector(max_entries=5)
        for i in range(10):
            rt = RequestTiming(f"r-{i}")
            rt.record("x", float(i))
            tc.record(rt)
        s = tc.stats()
        assert s["count"] == 5

    def test_thread_safe(self) -> None:
        import threading

        tc = TelemetryCollector()
        errors: list[Exception] = []

        def writer() -> None:
            try:
                for i in range(50):
                    rt = RequestTiming(f"t-{i}")
                    rt.record("a", 1.0)
                    tc.record(rt)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert tc.stats()["count"] <= 100
