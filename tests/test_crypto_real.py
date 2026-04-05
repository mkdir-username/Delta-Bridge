import os

pytest = __import__("pytest")
_root = os.path.dirname(os.path.dirname(__file__))
Crypto = pytest.importorskip("Crypto")

from ioe_crypto import derive_key, encrypt, decrypt


class TestCryptoReal:
    def test_derive_key_deterministic_32_bytes(self):
        key = derive_key("test-secret")
        assert isinstance(key, bytes)
        assert len(key) == 32
        assert derive_key("test-secret") == key

    def test_encrypt_decrypt_roundtrip(self):
        key = derive_key("secret123")
        plaintext = "Привет, мир!"
        encrypted = encrypt(key, plaintext)
        assert decrypt(key, encrypted) == plaintext

    def test_wrong_key_raises_valueerror(self):
        right_key = derive_key("right")
        wrong_key = derive_key("wrong")
        encrypted = encrypt(right_key, "secret data")
        with pytest.raises(ValueError):
            decrypt(wrong_key, encrypted)

    def test_tampered_ciphertext_raises(self):
        import base64

        key = derive_key("key")
        encrypted = encrypt(key, "data")
        raw = bytearray(base64.b64decode(encrypted))
        raw[15] ^= 0xFF
        tampered = base64.b64encode(bytes(raw)).decode("ascii")
        with pytest.raises(ValueError):
            decrypt(key, tampered)

    def test_nonce_uniqueness(self):
        key = derive_key("key")
        a = encrypt(key, "same")
        b = encrypt(key, "same")
        assert a != b
