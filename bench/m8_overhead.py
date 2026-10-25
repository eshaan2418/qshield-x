"""M8: overhead of signing, encryption and mTLS (wall-clock, this host, single thread)."""

from __future__ import annotations

import http.client
import os
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench.provenance import write_result  # noqa: E402
from infra.control_api import Runner, client_context, make_server  # noqa: E402
from infra.pki import make_test_pki  # noqa: E402
from infra.signing import generate_key, key_id, sign_manifest, verify_manifest  # noqa: E402
from infra.storage import EncryptedStore  # noqa: E402


def timeit(f, reps=5):
    ts = []
    for _ in range(reps):
        t0 = time.perf_counter()
        f()
        ts.append(time.perf_counter() - t0)
    return statistics.median(ts)


def main() -> None:
    out = {"sign_verify": [], "aes_gcm": [], "control_api": {}}
    tmp = Path(tempfile.mkdtemp())
    k = generate_key()
    trusted = {key_id(k.public_key()): k.public_key()}
    for mb in (1, 16, 64):
        f = tmp / f"t{mb}.b8"
        f.write_bytes(os.urandom(mb << 20))
        ts = timeit(lambda f=f, mb=mb: sign_manifest([f], {"mb": mb}, k, tmp / "m.json"))
        tv = timeit(lambda: verify_manifest(tmp / "m.json", trusted))
        out["sign_verify"].append({"mb": mb, "sign_s": ts, "verify_s": tv, "verify_mb_per_s": mb / tv})
        s = EncryptedStore(tmp / "store", EncryptedStore.new_key())
        data = f.read_bytes()
        te = timeit(lambda s=s, data=data: s.put("x", data))
        td = timeit(lambda s=s: s.get("x"))
        out["aes_gcm"].append({"mb": mb, "encrypt_s": te, "decrypt_s": td, "encrypt_mb_per_s": mb / te,
                               "decrypt_mb_per_s": mb / td})
    certs = make_test_pki(tmp / "pki")
    runner = Runner(tmp, ROOT / "build/qsx_decode")
    for tls in (False, True):
        srv = make_server(("127.0.0.1", 0), certs, trusted, {"operator-1"}, runner, tls=tls)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]
        lat = []
        for _ in range(300):
            t0 = time.perf_counter()
            conn = (http.client.HTTPSConnection("127.0.0.1", port, context=client_context(certs["ca"], certs["client"]))
                    if tls else http.client.HTTPConnection("127.0.0.1", port))
            conn.request("GET", "/runs/000000000000")
            conn.getresponse().read()
            conn.close()
            lat.append(time.perf_counter() - t0)
        srv.shutdown()
        lat = sorted(lat[20:])
        out["control_api"]["mtls" if tls else "plain_http"] = {
            "requests": len(lat), "new_connection_per_request": True,
            "p50_ms": 1e3 * lat[len(lat) // 2], "p99_ms": 1e3 * lat[int(0.99 * len(lat))]}
    for r in out["sign_verify"]:
        print(f"sign/verify {r['mb']:3d} MB: sign {r['sign_s']*1e3:8.1f} ms verify {r['verify_s']*1e3:8.1f} ms")
    for r in out["aes_gcm"]:
        print(f"AES-GCM {r['mb']:3d} MB: enc {r['encrypt_mb_per_s']:7.0f} MB/s dec {r['decrypt_mb_per_s']:7.0f} MB/s")
    print(out["control_api"])
    dst = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "results/M8/overhead.json"
    write_result(dst, out, {"reps": 5}, None,
                 extra_tools={"cryptography": __import__("cryptography").__version__,
                              "openssl": __import__("ssl").OPENSSL_VERSION})


if __name__ == "__main__":
    main()
