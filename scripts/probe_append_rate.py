#!/usr/bin/env python3
"""Probe Yandex IMAP APPEND rate limits empirically.

Usage: EMAIL=... IMAP_PASSWORD=... python scripts/probe_append_rate.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from imapclient import IMAPClient

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from ioe_crypto import compress_encrypt, derive_key

EMAIL = os.environ["EMAIL"]
PASSWORD = os.environ["IMAP_PASSWORD"]
KEY = derive_key(os.environ.get("IOE_SECRET", "probe"))
HOST = "imap.yandex.ru"
FOLDER = "IoE-Probe"


def make_probe_msg(seq: int) -> bytes:
    payload = compress_encrypt(KEY, json.dumps({"probe": seq})).encode("ascii")
    msg = MIMEMultipart()
    msg["Subject"] = f"probe {seq}"
    msg["From"] = EMAIL
    msg["To"] = EMAIL
    msg.attach(MIMEText(payload, "plain"))
    return msg.as_bytes()


def probe(client: IMAPClient, rate_per_min: float, count: int = 10) -> list[dict[str, object]]:
    interval = 60.0 / rate_per_min
    results: list[dict[str, object]] = []

    for i in range(count):
        t0 = time.monotonic()
        try:
            client.append(FOLDER, make_probe_msg(i))
            elapsed = (time.monotonic() - t0) * 1000
            results.append({"seq": i, "status": "OK", "ms": round(elapsed, 1)})
            print(f"  [{i + 1}/{count}] OK  {elapsed:.0f}ms")
        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            results.append({"seq": i, "status": "ERROR", "error": str(e), "ms": round(elapsed, 1)})
            print(f"  [{i + 1}/{count}] ERR {e} ({elapsed:.0f}ms)")
            break
        if i < count - 1:
            remaining = interval - (time.monotonic() - t0)
            if remaining > 0:
                time.sleep(remaining)

    try:
        msgs = client.search(["ALL"])
        if msgs:
            client.delete_messages(msgs)
            client.expunge()
            print(f"  cleanup: deleted {len(msgs)} probe messages")
    except Exception as e:
        print(f"  cleanup failed: {e}")

    return results


def main() -> None:
    rates = [1, 6, 12, 30, 60, 120]
    print(f"Probing IMAP APPEND rate limits on {HOST}")
    print(f"Account: {EMAIL}")
    print(f"Folder: {FOLDER}")
    print()

    client = IMAPClient(HOST, ssl=True)
    client.login(EMAIL, PASSWORD)
    try:
        client.create_folder(FOLDER)
        print(f"Created folder {FOLDER}")
    except Exception:
        pass
    client.select_folder(FOLDER)

    all_results: dict[str, list[dict[str, object]]] = {}
    for rate in rates:
        print(f"--- {rate}/min (interval {60 / rate:.1f}s) ---")
        results = probe(client, rate, count=10)
        all_results[f"{rate}/min"] = results
        errors = [r for r in results if r["status"] == "ERROR"]
        if errors:
            print(f"  STOPPED: errors at rate {rate}/min")
            break
        avg_ms = sum(float(r["ms"]) for r in results) / len(results)
        print(f"  avg: {avg_ms:.0f}ms")
        time.sleep(5)

    client.logout()

    print("\n=== RESULTS ===")
    for rate_label, results in all_results.items():
        ok = sum(1 for r in results if r["status"] == "OK")
        avg = sum(float(r["ms"]) for r in results if r["status"] == "OK") / max(ok, 1)
        print(f"{rate_label}: {ok}/{len(results)} OK, avg {avg:.0f}ms")


if __name__ == "__main__":
    main()
