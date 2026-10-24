"""Ed25519-signed syndrome traces, result manifests and run configurations.

Only standard primitives from `cryptography` are used (rule 5: no custom cryptography). A manifest
binds artefact files by SHA-256; the signature covers the canonical JSON encoding of the manifest
(sorted keys, compact separators, UTF-8).
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


class VerificationError(Exception):
    pass


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def key_id(pub: Ed25519PublicKey) -> str:
    raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:16]


def generate_key(path: Path | None = None) -> Ed25519PrivateKey:
    k = Ed25519PrivateKey.generate()
    if path is not None:
        path.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
        path.chmod(0o600)
    return k


def load_private(path: Path) -> Ed25519PrivateKey:
    k = serialization.load_pem_private_key(path.read_bytes(), password=None)
    assert isinstance(k, Ed25519PrivateKey)
    return k


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sign_obj(obj: dict, key: Ed25519PrivateKey) -> dict:
    """Return {"payload": obj, "sig": b64, "kid": key id}."""
    sig = key.sign(canonical(obj))
    return {"payload": obj, "sig": base64.b64encode(sig).decode(), "kid": key_id(key.public_key())}


def verify_obj(env: dict, trusted: dict[str, Ed25519PublicKey]) -> dict:
    if not isinstance(env, dict) or set(env) != {"payload", "sig", "kid"}:
        raise VerificationError("not a signed envelope")
    pub = trusted.get(env["kid"])
    if pub is None:
        raise VerificationError("untrusted key id")
    try:
        pub.verify(base64.b64decode(env["sig"], validate=True), canonical(env["payload"]))
    except (InvalidSignature, ValueError) as e:
        raise VerificationError("bad signature") from e
    return env["payload"]


def sign_manifest(files: list[Path], meta: dict, key: Ed25519PrivateKey, out: Path) -> dict:
    manifest = {"version": 1, "meta": meta,
                "files": [{"name": p.name, "size": p.stat().st_size, "sha256": sha256_file(p)} for p in files]}
    env = sign_obj(manifest, key)
    out.write_text(json.dumps(env, indent=1))
    return env


def verify_manifest(manifest_path: Path, trusted: dict[str, Ed25519PublicKey], base: Path | None = None) -> dict:
    env = json.loads(manifest_path.read_text())
    m = verify_obj(env, trusted)
    base = base or manifest_path.parent
    for f in m["files"]:
        p = base / f["name"]
        if not p.exists() or p.stat().st_size != f["size"] or sha256_file(p) != f["sha256"]:
            raise VerificationError(f"file {f['name']} does not match manifest")
    return m
