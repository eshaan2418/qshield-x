"""AES-256-GCM encrypted experiment storage (cryptography.hazmat AESGCM).

Object file format: b"QSXE" | version(1) | nonce(12) | ciphertext||tag. The associated data binds the
object name and format version, so renaming or swapping objects is detected.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"QSXE"
VERSION = 1


class EncryptedStore:
    def __init__(self, root: Path, key: bytes):
        if len(key) != 32:
            raise ValueError("AES-256 key required")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._aead = AESGCM(key)

    @staticmethod
    def new_key() -> bytes:
        return AESGCM.generate_key(bit_length=256)

    def _aad(self, name: str) -> bytes:
        return MAGIC + bytes([VERSION]) + name.encode()

    def put(self, name: str, data: bytes) -> Path:
        if "/" in name or name.startswith("."):
            raise ValueError("bad object name")
        nonce = os.urandom(12)
        ct = self._aead.encrypt(nonce, data, self._aad(name))
        p = self.root / f"{name}.enc"
        p.write_bytes(MAGIC + bytes([VERSION]) + nonce + ct)
        return p

    def get(self, name: str) -> bytes:
        blob = (self.root / f"{name}.enc").read_bytes()
        if blob[:4] != MAGIC or blob[4] != VERSION:
            raise ValueError("bad header")
        return self._aead.decrypt(blob[5:17], blob[17:], self._aad(name))  # raises InvalidTag
