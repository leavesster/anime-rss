import base64
import os
from pathlib import Path
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecretCipher(Protocol):
    def encrypt(self, plaintext: bytes, *, purpose: str) -> bytes: ...

    def decrypt(self, envelope: bytes, *, purpose: str) -> bytes: ...


class AesGcmSecretCipher:
    _VERSION = b"ARS1"

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("master key must contain exactly 32 bytes")
        self._cipher = AESGCM(key)

    def encrypt(self, plaintext: bytes, *, purpose: str) -> bytes:
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(nonce, plaintext, purpose.encode("utf-8"))
        return self._VERSION + base64.urlsafe_b64encode(nonce + ciphertext)

    def decrypt(self, envelope: bytes, *, purpose: str) -> bytes:
        if not envelope.startswith(self._VERSION):
            raise ValueError("unsupported secret envelope version")
        payload = base64.urlsafe_b64decode(envelope[len(self._VERSION) :])
        if len(payload) < 13:
            raise ValueError("invalid secret envelope")
        return self._cipher.decrypt(payload[:12], payload[12:], purpose.encode("utf-8"))


class FileSecretCipher(AesGcmSecretCipher):
    @classmethod
    def load_or_create(cls, path: Path) -> "FileSecretCipher":
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            key = path.read_bytes()
        else:
            key = os.urandom(32)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(key)
                handle.flush()
                os.fsync(handle.fileno())

        if len(key) != 32:
            raise ValueError(f"master key at {path} must contain exactly 32 bytes")
        return cls(key)
