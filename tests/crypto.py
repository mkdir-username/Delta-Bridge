"""Mock crypto for testing — no real encryption."""
import base64
import hashlib


def derive_key(secret):
    return hashlib.sha256(secret.encode("utf-8")).digest()


def encrypt(key, plaintext):
    return base64.b64encode(plaintext.encode("utf-8")).decode("ascii")


def decrypt(key, b64_blob):
    return base64.b64decode(b64_blob).decode("utf-8")
