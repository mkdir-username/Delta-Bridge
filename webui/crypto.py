"""IoE E2E encryption: AES-256-GCM with shared secret."""
from __future__ import annotations

import base64
import hashlib
import os

from Crypto.Cipher import AES

NONCE_SIZE = 12
TAG_SIZE = 16


def derive_key(secret: str) -> bytes:
    return hashlib.sha256(secret.encode("utf-8")).digest()


def encrypt(key: bytes, plaintext: str) -> str:
    nonce = os.urandom(NONCE_SIZE)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext.encode("utf-8"))
    return base64.b64encode(nonce + ciphertext + tag).decode("ascii")


def decrypt(key: bytes, b64_blob: str) -> str:
    raw = base64.b64decode(b64_blob)
    nonce = raw[:NONCE_SIZE]
    ciphertext = raw[NONCE_SIZE:-TAG_SIZE]
    tag = raw[-TAG_SIZE:]
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    plaintext = cipher.decrypt_and_verify(ciphertext, tag)
    return plaintext.decode("utf-8")
