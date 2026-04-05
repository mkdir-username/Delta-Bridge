"""Тесты ioe_crypto: AES-256-GCM + gzip compression."""

from __future__ import annotations

import base64

import pytest

from ioe_crypto import compress_encrypt, decrypt, decrypt_decompress, derive_key, encrypt


class TestDeriveKey:
    def test_длина_32_байта(self) -> None:
        assert len(derive_key("secret")) == 32

    def test_детерминированность(self) -> None:
        assert derive_key("abc") == derive_key("abc")

    def test_разные_входы(self) -> None:
        assert derive_key("a") != derive_key("b")


class TestEncryptDecrypt:
    def test_roundtrip(self) -> None:
        key = derive_key("k")
        assert decrypt(key, encrypt(key, "hello")) == "hello"

    def test_unicode(self) -> None:
        key = derive_key("k")
        text = "Привет 🌍 日本語"
        assert decrypt(key, encrypt(key, text)) == text

    def test_base64_output(self) -> None:
        key = derive_key("k")
        base64.b64decode(encrypt(key, "data"))

    def test_nonce_уникальность(self) -> None:
        key = derive_key("k")
        assert encrypt(key, "same") != encrypt(key, "same")

    def test_wrong_key(self) -> None:
        k1, k2 = derive_key("right"), derive_key("wrong")
        with pytest.raises(ValueError, match="MAC"):
            decrypt(k2, encrypt(k1, "secret"))

    def test_tampered(self) -> None:
        key = derive_key("k")
        raw = bytearray(base64.b64decode(encrypt(key, "data")))
        raw[15] ^= 0xFF
        with pytest.raises(ValueError, match="MAC"):
            decrypt(key, base64.b64encode(bytes(raw)).decode())


class TestCompressEncrypt:
    def test_roundtrip(self) -> None:
        key = derive_key("k")
        text = "hello " * 1000
        assert decrypt_decompress(key, compress_encrypt(key, text)) == text

    def test_меньше_чем_plain(self) -> None:
        key = derive_key("k")
        text = "a" * 10000
        assert len(compress_encrypt(key, text)) < len(encrypt(key, text))

    def test_backward_compat(self) -> None:
        key = derive_key("k")
        assert decrypt_decompress(key, encrypt(key, "short")) == "short"

    def test_пустая_строка(self) -> None:
        key = derive_key("k")
        assert decrypt_decompress(key, compress_encrypt(key, "")) == ""
