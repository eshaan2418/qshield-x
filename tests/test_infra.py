"""M8 tests: signed traces/manifests, encrypted storage, mTLS control API (positive + negative)."""

from __future__ import annotations

import http.client
import json
import ssl
import threading
import time
import uuid
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from infra.control_api import Runner, client_context, make_server
from infra.pki import make_test_pki
from infra.signing import VerificationError, generate_key, key_id, sign_manifest, sign_obj, verify_manifest, verify_obj
from infra.storage import EncryptedStore

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def keys():
    k = generate_key()
    return k, {key_id(k.public_key()): k.public_key()}


def test_manifest_roundtrip_and_tamper(tmp_path, keys):
    k, trusted = keys
    trace = tmp_path / "trace.b8"
    trace.write_bytes(bytes(range(256)) * 64)
    sign_manifest([trace], {"d": 5, "p": 0.003}, k, tmp_path / "manifest.json")
    assert verify_manifest(tmp_path / "manifest.json", trusted)["meta"]["d"] == 5
    # tampered trace -> rejected
    b = bytearray(trace.read_bytes())
    b[100] ^= 1
    trace.write_bytes(bytes(b))
    with pytest.raises(VerificationError):
        verify_manifest(tmp_path / "manifest.json", trusted)


def test_manifest_tampered_meta_and_wrong_key(tmp_path, keys):
    k, trusted = keys
    f = tmp_path / "r.json"
    f.write_text("{}")
    sign_manifest([f], {"pl": 0.01}, k, tmp_path / "m.json")
    env = json.loads((tmp_path / "m.json").read_text())
    env["payload"]["meta"]["pl"] = 0.001  # edit a result number
    (tmp_path / "m2.json").write_text(json.dumps(env))
    with pytest.raises(VerificationError):
        verify_manifest(tmp_path / "m2.json", trusted)
    other = generate_key()
    with pytest.raises(VerificationError):
        verify_manifest(tmp_path / "m.json", {key_id(other.public_key()): other.public_key()})


def test_unsigned_config_rejected(keys):
    _, trusted = keys
    with pytest.raises(VerificationError):
        verify_obj({"payload": {"action": "start"}}, trusted)
    with pytest.raises(VerificationError):
        verify_obj({"payload": {"a": 1}, "sig": "AAAA", "kid": next(iter(trusted))}, trusted)


def test_encrypted_store(tmp_path):
    key = EncryptedStore.new_key()
    s = EncryptedStore(tmp_path, key)
    s.put("run1", b"secret syndrome data")
    assert s.get("run1") == b"secret syndrome data"
    p = tmp_path / "run1.enc"
    blob = bytearray(p.read_bytes())
    blob[-1] ^= 1
    p.write_bytes(bytes(blob))
    with pytest.raises(InvalidTag):
        s.get("run1")
    # swapping object names is detected via associated data
    s.put("a", b"A")
    s.put("b", b"B")
    (tmp_path / "a.enc").write_bytes((tmp_path / "b.enc").read_bytes())
    with pytest.raises(InvalidTag):
        s.get("a")
    with pytest.raises(InvalidTag):
        EncryptedStore(tmp_path, EncryptedStore.new_key()).get("b")


@pytest.fixture()
def api(tmp_path, keys):
    k, trusted = keys
    certs = make_test_pki(tmp_path / "pki")
    data = tmp_path / "data"
    data.mkdir()
    import sys

    sys.path.insert(0, str(ROOT))
    from sim.qsx_graph import build

    c, g = build(3, 0.003)
    g.write(str(data / "g.qsxg"))
    c.compile_detector_sampler(seed=1).sample(2000, bit_packed=True).tofile(data / "t.b8")
    runner = Runner(data, ROOT / "build" / "qsx_decode")
    srv = make_server(("127.0.0.1", 0), certs, trusted, {"operator-1"}, runner)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield srv.server_address[1], certs, k
    srv.shutdown()


def _req(port, certs, cert, method, path, body=None):
    conn = http.client.HTTPSConnection("127.0.0.1", port, context=client_context(certs["ca"], cert), timeout=10)
    conn.request(method, path, body=None if body is None else json.dumps(body))
    r = conn.getresponse()
    out = (r.status, json.loads(r.read() or b"{}"))
    conn.close()
    return out


def test_mtls_start_status_stop(api):
    port, certs, k = api
    cfg = sign_obj({"action": "start", "graph": "g.qsxg", "trace": "t.b8", "nonce": uuid.uuid4().hex}, k)
    code, r = _req(port, certs, certs["client"], "POST", "/runs", cfg)
    assert code == 201
    rid = r["run_id"]
    for _ in range(100):
        code, st = _req(port, certs, certs["client"], "GET", f"/runs/{rid}")
        if st["state"] != "running":
            break
        time.sleep(0.05)
    assert st["state"] == "done" and st["result"]["shots"] == 2000
    stop = sign_obj({"action": "stop", "run_id": rid, "nonce": uuid.uuid4().hex}, k)
    assert _req(port, certs, certs["client"], "POST", f"/runs/{rid}/stop", stop)[0] == 200


def test_mtls_rejects_unsigned_tampered_replayed(api):
    port, certs, k = api
    assert _req(port, certs, certs["client"], "POST", "/runs", {"action": "start", "graph": "g.qsxg",
                                                               "trace": "t.b8", "nonce": "x"})[0] == 403
    env = sign_obj({"action": "start", "graph": "g.qsxg", "trace": "t.b8", "nonce": uuid.uuid4().hex}, k)
    bad = json.loads(json.dumps(env))
    bad["payload"]["trace"] = "../../etc/passwd"
    assert _req(port, certs, certs["client"], "POST", "/runs", bad)[0] == 403
    assert _req(port, certs, certs["client"], "POST", "/runs", env)[0] == 201
    assert _req(port, certs, certs["client"], "POST", "/runs", env)[0] == 409  # replay
    trav = sign_obj({"action": "start", "graph": "../g.qsxg", "trace": "t.b8", "nonce": uuid.uuid4().hex}, k)
    assert _req(port, certs, certs["client"], "POST", "/runs", trav)[0] == 400


def test_mtls_rejects_missing_or_wrong_client_cert(api):
    port, certs, _ = api
    for cert in (None, certs["rogue_client"]):
        with pytest.raises((ssl.SSLError, ConnectionError, OSError)):
            _req(port, certs, cert, "GET", "/runs/000000000000")
