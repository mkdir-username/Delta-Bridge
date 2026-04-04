"""Mock crypto for testing — no real encryption."""
from __future__ import annotations

import base64
import gzip
import hashlib


def derive_key(secret: str) -> bytes:
    return hashlib.sha256(secret.encode("utf-8")).digest()


def encrypt(key: bytes, plaintext: str) -> str:
    return base64.b64encode(plaintext.encode("utf-8")).decode("ascii")


def decrypt(key: bytes, b64_blob: str) -> str:
    return base64.b64decode(b64_blob).decode("utf-8")


def compress_encrypt(key: bytes, plaintext: str) -> str:
    compressed = gzip.compress(plaintext.encode("utf-8"))
    return base64.b64encode(compressed).decode("ascii")


def decrypt_decompress(key: bytes, b64_blob: str) -> str:
    raw = base64.b64decode(b64_blob)
    try:
        decompressed = gzip.decompress(raw)
    except gzip.BadGzipFile:
        decompressed = raw
    return decompressed.decode("utf-8")
