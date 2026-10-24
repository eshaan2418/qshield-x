"""Test PKI for the mTLS control API (X.509 via `cryptography`): CA, server and client certificates."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "QShield-X test PKI"),
                      x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _write(path: Path, key, cert) -> None:
    path.with_suffix(".key").write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                                           serialization.PrivateFormat.PKCS8,
                                                           serialization.NoEncryption()))
    path.with_suffix(".key").chmod(0o600)
    path.with_suffix(".crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def make_ca(path: Path, cn: str = "qsx-ca"):
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.UTC)
    cert = (x509.CertificateBuilder().subject_name(_name(cn)).issuer_name(_name(cn)).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=1))
            .not_valid_after(now + dt.timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                         content_commitment=False, key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
            .sign(key, hashes.SHA256()))
    _write(path, key, cert)
    return key, cert


def make_leaf(path: Path, ca_key, ca_cert, cn: str, server: bool):
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.UTC)
    b = (x509.CertificateBuilder().subject_name(_name(cn)).issuer_name(ca_cert.subject).public_key(key.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=1))
         .not_valid_after(now + dt.timedelta(days=7))
         .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
         .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH if server
                                               else ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False))
    if server:
        b = b.add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),
                                                         x509.IPAddress(__import__("ipaddress").ip_address("127.0.0.1"))]),
                            critical=False)
    cert = b.sign(ca_key, hashes.SHA256())
    _write(path, key, cert)
    return key, cert


def make_test_pki(d: Path) -> dict:
    d.mkdir(parents=True, exist_ok=True)
    ca_k, ca_c = make_ca(d / "ca")
    make_leaf(d / "server", ca_k, ca_c, "localhost", server=True)
    make_leaf(d / "client", ca_k, ca_c, "operator-1", server=False)
    rk, rc = make_ca(d / "rogue_ca", "rogue-ca")
    make_leaf(d / "rogue_client", rk, rc, "intruder", server=False)
    return {k: d / k for k in ("ca", "server", "client", "rogue_client")}
