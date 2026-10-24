"""mTLS-authenticated control API for starting/stopping decoder runs.

Transport: TLS 1.3 (Python `ssl`), client certificates REQUIRED and verified against the project CA;
the client certificate CN must be in an allow-list. Application layer: run configurations and stop
requests must be Ed25519-signed envelopes (infra.signing) from a trusted operator key, with a fresh
nonce (replay protection). Endpoints:
    POST /runs              body: signed {"action":"start","graph":..,"trace":..,"nonce":..}
    POST /runs/<id>/stop    body: signed {"action":"stop","run_id":..,"nonce":..}
    GET  /runs/<id>
"""

from __future__ import annotations

import json
import re
import ssl
import subprocess
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from infra.signing import VerificationError, verify_obj

NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def server_context(certs: dict) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(certs["server"].with_suffix(".crt"), certs["server"].with_suffix(".key"))
    ctx.load_verify_locations(certs["ca"].with_suffix(".crt"))
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def client_context(ca: Path, cert: Path | None) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_verify_locations(ca.with_suffix(".crt"))
    if cert is not None:
        ctx.load_cert_chain(cert.with_suffix(".crt"), cert.with_suffix(".key"))
    return ctx


class Runner:
    """Runs build/qsx_decode on whitelisted files inside data_dir."""

    def __init__(self, data_dir: Path, decoder: Path):
        self.data_dir = Path(data_dir)
        self.decoder = Path(decoder)
        self.runs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def start(self, graph: str, trace: str) -> str:
        for n in (graph, trace):
            if not NAME_RE.match(n) or not (self.data_dir / n).is_file():
                raise ValueError(f"bad file name {n!r}")
        rid = uuid.uuid4().hex[:12]
        proc = subprocess.Popen([str(self.decoder), "--graph", str(self.data_dir / graph), "--dets",
                                 str(self.data_dir / trace)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True)
        with self.lock:
            self.runs[rid] = {"proc": proc, "state": "running", "result": None}
        threading.Thread(target=self._wait, args=(rid,), daemon=True).start()
        return rid

    def _wait(self, rid: str) -> None:
        r = self.runs[rid]
        out, _ = r["proc"].communicate()
        with self.lock:
            if r["state"] == "running":
                r["state"] = "done" if r["proc"].returncode == 0 else "failed"
                try:
                    r["result"] = json.loads(out.strip().splitlines()[-1])
                except Exception:
                    r["result"] = None

    def stop(self, rid: str) -> bool:
        with self.lock:
            r = self.runs.get(rid)
            if r is None:
                return False
            if r["state"] == "running":
                r["state"] = "stopped"
                r["proc"].kill()
            return True

    def status(self, rid: str) -> dict | None:
        with self.lock:
            r = self.runs.get(rid)
            return None if r is None else {"state": r["state"], "result": r["result"]}


def make_server(addr: tuple[str, int], certs: dict, trusted_keys: dict, allowed_cns: set[str],
                runner: Runner, tls: bool = True) -> ThreadingHTTPServer:
    """tls=False exists only to measure the transport overhead baseline (bench/m8_overhead.py)."""
    seen_nonces: set[str] = set()
    nonce_lock = threading.Lock()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, code: int, obj: dict) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authz(self) -> bool:
            if not tls:
                return True
            cert = self.connection.getpeercert()
            cn = dict(x[0] for x in cert.get("subject", ())).get("commonName") if cert else None
            if cn not in allowed_cns:
                self._send(403, {"error": "client not authorised"})
                return False
            return True

        def _signed_body(self, action: str) -> dict | None:
            n = int(self.headers.get("Content-Length", "0"))
            if n > 65536:
                self._send(413, {"error": "too large"})
                return None
            try:
                env = json.loads(self.rfile.read(n))
                p = verify_obj(env, trusted_keys)
            except (VerificationError, json.JSONDecodeError, KeyError, TypeError) as e:
                self._send(403, {"error": f"unsigned or invalid config: {e}"})
                return None
            if p.get("action") != action or not isinstance(p.get("nonce"), str):
                self._send(400, {"error": "bad payload"})
                return None
            with nonce_lock:
                if p["nonce"] in seen_nonces:
                    self._send(409, {"error": "replayed nonce"})
                    return None
                seen_nonces.add(p["nonce"])
            return p

        def do_POST(self):  # noqa: N802
            if not self._authz():
                return
            m = re.fullmatch(r"/runs/([0-9a-f]{12})/stop", self.path)
            if self.path == "/runs":
                p = self._signed_body("start")
                if p is None:
                    return
                try:
                    rid = runner.start(str(p.get("graph")), str(p.get("trace")))
                except ValueError as e:
                    self._send(400, {"error": str(e)})
                    return
                self._send(201, {"run_id": rid})
            elif m:
                p = self._signed_body("stop")
                if p is None:
                    return
                if p.get("run_id") != m.group(1):
                    self._send(400, {"error": "run id mismatch"})
                    return
                self._send(200 if runner.stop(m.group(1)) else 404, {"run_id": m.group(1)})
            else:
                self._send(404, {"error": "not found"})

        def do_GET(self):  # noqa: N802
            if not self._authz():
                return
            m = re.fullmatch(r"/runs/([0-9a-f]{12})", self.path)
            st = runner.status(m.group(1)) if m else None
            self._send(200 if st else 404, st or {"error": "not found"})

    srv = ThreadingHTTPServer(addr, H)
    if tls:
        srv.socket = server_context(certs).wrap_socket(srv.socket, server_side=True)
    return srv
