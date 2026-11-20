"""The app security review of 2026-11-19 (moonglade-internal/reviews/SECURITY_REVIEW_2026-11-19.md),
fixed: HTTPS on the home network (finding 1), protective headers on the app's own pages (4),
secrets at rest (5), sessions that really end (6), the Mirror's Disconnect (7) and size caps (9).
The front door's origin check (2) is pinned in test_csrf_coverage.py, the update-to-the-tag
change (10) in test_updater.py and test_updater_git.py.

Everything here stays on this machine: the HTTPS server test binds 127.0.0.1 and talks to
itself. The certificate tests need the `cryptography` package (requirements.txt); CI's curated
install leaves it out, so those skip there and run on every machine the app is installed on.
"""
import datetime
import io
import json
import logging
import os
import re
import ssl
import threading
import time
import zipfile

import pytest

from moonglade import backup as core
from moonglade import gallery as g
from moonglade import mirror as mirror_mod
from moonglade import paths as moonglade_paths
from moonglade import secure_files
from moonglade import web_sessions
from moonglade.gallery import create_app
from tests.conftest import _do_login, login_client, login_test_client, with_csrf

LAN = "192.168.1.20"


# ---------------------------------------------------------------------------
# Finding 4: the app's own pages
# ---------------------------------------------------------------------------

_PAGES = ["/login", "/", "/loom", "/mirror/connect", "/contact-sheet"]


def _script_tags(html):
    return re.findall(r"<script\b[^>]*>", html, flags=re.I)


@pytest.mark.parametrize("path", _PAGES)
def test_every_page_carries_the_policy_its_inline_scripts_were_written_for(tmp_path, path):
    cli = login_client(tmp_path)
    r = cli.get(path)
    assert r.status_code == 200, path
    csp = r.headers["Content-Security-Policy"]
    m = re.search(r"script-src 'self' 'nonce-([A-Za-z0-9_-]+)'", csp)
    assert m, csp
    nonce = m.group(1)
    for word in ("'unsafe-inline'", "'unsafe-eval'"):
        assert word not in csp.split("script-src", 1)[1].split(";", 1)[0], csp
    for part in ("object-src 'none'", "base-uri 'none'", "frame-ancestors 'self'"):
        assert part in csp
    html = r.get_data(as_text=True)
    assert g.CSP_NONCE_MARK not in html, "a page went out with its nonce mark unfilled"
    tags = _script_tags(html)
    assert tags, path
    for tag in tags:
        if "src=" in tag:
            continue                                    # a file from this origin: 'self'
        assert 'nonce="%s"' % nonce in tag or "nonce='%s'" % nonce in tag, (path, tag)
    # no inline event handler anywhere: the policy would refuse it, and it would be dead
    assert not re.search(r"<[a-z][^>]*\son[a-z]+\s*=", html, flags=re.I), path
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "SAMEORIGIN"


def test_the_nonce_is_fresh_on_every_response(tmp_path):
    cli = login_client(tmp_path)
    a = cli.get("/").headers["Content-Security-Policy"]
    b = cli.get("/").headers["Content-Security-Policy"]
    assert a != b


def test_a_value_from_the_request_can_never_carry_the_nonce(tmp_path):
    """The nonce is filled into the TEMPLATE before Jinja renders anything a request supplied:
    a `next` that spells the mark comes back as the mark, not as the nonce."""
    cli = login_client(tmp_path)
    r = cli.get("/login?next=/" + g.CSP_NONCE_MARK)
    nonce = re.search(r"'nonce-([^']+)'", r.headers["Content-Security-Policy"]).group(1)
    body = r.get_data(as_text=True)
    assert g.CSP_NONCE_MARK in body
    assert body.count(nonce) == len([t for t in _script_tags(body) if "src=" not in t])


def test_json_and_redirects_carry_the_two_headers_too_and_files_keep_their_sandbox(tmp_path):
    cli = login_client(tmp_path)
    for r in (cli.get("/api/ping"), create_app(tmp_path).test_client().get("/")):
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "SAMEORIGIN"
        assert r.headers["Referrer-Policy"] == "same-origin"
    assert "Content-Security-Policy" not in cli.get("/api/ping").headers
    # the connect page keeps its own stricter Referrer-Policy
    assert cli.get("/mirror/connect").headers["Referrer-Policy"] == "no-referrer"
    # a served branding file keeps harden_file_response's sandbox, not the page policy
    r = cli.get("/branding/logo.png")
    if r.status_code == 200:
        assert r.headers["Content-Security-Policy"] == g.FILE_RESPONSE_CSP


# ---------------------------------------------------------------------------
# Finding 1: HTTPS on the home network -- the request rules
# ---------------------------------------------------------------------------

def _app_in(tmp_path, mode):
    app = create_app(tmp_path)
    app.config["MG_TLS_MODE"] = mode
    return app


def test_lan_mode_sends_another_devices_plain_visit_to_https(tmp_path):
    app = _app_in(tmp_path, "lan")
    cli = app.test_client()
    r = cli.get("/?page=2", base_url="http://192.168.1.5:5057",
                environ_base={"REMOTE_ADDR": LAN})
    assert r.status_code == 307
    assert r.headers["Location"] == "https://192.168.1.5:5057/?page=2"
    r = cli.post("/api/login", base_url="http://192.168.1.5:5057", json={},
                 environ_base={"REMOTE_ADDR": LAN})
    assert r.status_code == 403
    assert "https://192.168.1.5:5057/" in r.get_json()["error"]


def test_lan_mode_lets_this_pc_keep_plain_http_and_https_through(tmp_path):
    app = _app_in(tmp_path, "lan")
    cli = app.test_client()
    assert cli.get("/login").status_code == 200                       # 127.0.0.1, http
    assert cli.get("/login", base_url="https://192.168.1.5:5057",
                   environ_base={"REMOTE_ADDR": LAN}).status_code == 200


def test_all_mode_sends_this_pc_too_and_off_mode_sends_nobody(tmp_path):
    r = _app_in(tmp_path, "all").test_client().get("/login", base_url="http://localhost:5057")
    assert r.status_code == 307 and r.headers["Location"] == "https://localhost:5057/login"
    r = _app_in(tmp_path, "off").test_client().get(
        "/login", environ_base={"REMOTE_ADDR": LAN})
    assert r.status_code == 200


def test_the_session_cookie_is_secure_over_https_only(tmp_path):
    core.add_or_update_web_user("alice", "a-real-test-password-1")
    app = create_app(tmp_path)
    for base, secure in (("https://localhost", True), ("http://localhost", False)):
        cli = app.test_client()
        html = cli.get("/login", base_url=base).get_data(as_text=True)
        from tests.conftest import extract_login_csrf
        r = cli.post("/api/login", base_url=base, json={
            "username": "alice", "password": "a-real-test-password-1",
            "csrf": extract_login_csrf(html)})
        assert r.get_json().get("ok") is True
        cookie = [h for h in r.headers.getlist("Set-Cookie") if h.startswith("session=")][-1]
        assert ("; Secure" in cookie) is secure, cookie


def test_the_lan_card_reports_the_mode_and_the_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setitem(g._SERVER_CONTROL, "bonjour", None)
    monkeypatch.setitem(g._SERVER_CONTROL, "serving", None)
    app = create_app(tmp_path)
    app.config.update(MG_TLS_MODE="lan", MG_TLS_FINGERPRINT="AB:CD")
    d = login_test_client(app).get("/api/bonjour/status").get_json()
    assert d["tls"] == "lan" and d["tls_fingerprint"] == "AB:CD"


def test_the_lan_card_shows_the_fingerprint_as_text_in_the_existing_card():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "gallery" / "src" / "components"
           / "BonjourCard.jsx").read_text(encoding="utf-8")
    assert "st.tls_fingerprint" in src and 'className="mgcp-tilenote"' in src


# ---------------------------------------------------------------------------
# Finding 1: the certificate and the one-port server
# ---------------------------------------------------------------------------

def _x509():
    pytest.importorskip("cryptography", reason="making the certificate needs cryptography")
    from cryptography import x509
    return x509


def _certs(path):
    return _x509().load_pem_x509_certificates(path.read_bytes())


def test_the_authority_is_made_once_and_signs_the_server_certificate(tmp_path, monkeypatch):
    x509 = _x509()
    from moonglade import tls
    restricted = []
    monkeypatch.setattr(secure_files, "restrict_to_owner",
                        lambda p: restricted.append(os.path.basename(str(p))) or True)
    cert, key = tls.ensure_certificate(dns_names=["mypc", "mypc.local"],
                                       ip_addresses=["192.168.1.5"])
    assert cert == tmp_path / moonglade_paths.TLS_CERT_NAME
    assert key == tmp_path / moonglade_paths.TLS_KEY_NAME
    ca_p = tmp_path / moonglade_paths.TLS_CA_CERT_NAME
    for secret in (moonglade_paths.TLS_KEY_NAME, moonglade_paths.TLS_CA_KEY_NAME):
        assert secret in restricted, secret + " was not limited to this user"
    fp = tls.fingerprint()
    assert re.fullmatch(r"([0-9A-F]{2}:){31}[0-9A-F]{2}", fp) and fp == tls.fingerprint(ca_p)
    leaf, chain_ca = _certs(cert)
    ca = _certs(ca_p)[0]
    assert chain_ca == ca, "the server sends its authority after its certificate"
    leaf.verify_directly_issued_by(ca)
    bc = ca.extensions.get_extension_for_class(x509.BasicConstraints)
    assert bc.critical and bc.value.ca and bc.value.path_length == 0
    nc = ca.extensions.get_extension_for_class(x509.NameConstraints)
    assert nc.critical
    permitted = {getattr(n.value, "compressed", n.value) for n in nc.value.permitted_subtrees}
    assert {"localhost", "local", "192.168.0.0/16"} <= {str(p) for p in permitted}
    # A letters-only PC name could be a public top-level domain, so the authority never
    # permits it (test_tls_ca_names.py); the leaf still carries the .local name.
    assert "mypc" not in {str(p) for p in permitted}
    names = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "mypc.local" in names.get_values_for_type(x509.DNSName)
    # Apple counts NotBefore to NotAfter: 826 days is refused even under a trusted authority
    life = leaf.not_valid_after_utc - leaf.not_valid_before_utc
    assert life <= datetime.timedelta(days=tls.CERT_LIFETIME_DAYS) and tls.within_apple_ceiling(leaf)
    # a restart reuses both; a new home address re-issues the server certificate only
    first = cert.read_bytes()
    tls.ensure_certificate(dns_names=["mypc", "mypc.local"], ip_addresses=["192.168.1.5"])
    assert cert.read_bytes() == first
    tls.ensure_certificate(dns_names=["mypc", "mypc.local"], ip_addresses=["192.168.1.77"])
    assert cert.read_bytes() != first and tls.fingerprint() == fp, (
        "a new address must not move the authority a device installed")


def test_the_authority_cannot_vouch_for_a_website(tmp_path):
    """Its Name Constraints, checked by a real path validator: a certificate it signs for a
    public name is rejected, the PC's own is accepted."""
    x509 = _x509()
    import datetime
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.verification import PolicyBuilder, Store, VerificationError
    from moonglade import tls
    cert_p, _ = tls.ensure_certificate(dns_names=["mypc", "mypc.local"])
    ca = _certs(tmp_path / moonglade_paths.TLS_CA_CERT_NAME)[0]
    ca_key = serialization.load_pem_private_key(
        (tmp_path / moonglade_paths.TLS_CA_KEY_NAME).read_bytes(), None)
    when = datetime.datetime.now(datetime.timezone.utc)
    verifier = lambda name: PolicyBuilder().store(Store([ca])).time(when) \
        .build_server_verifier(x509.DNSName(name))
    verifier("mypc.local").verify(_certs(cert_p)[0], [])
    k = ec.generate_private_key(ec.SECP256R1())
    forged = (x509.CertificateBuilder()
              .subject_name(x509.Name([])).issuer_name(ca.subject).public_key(k.public_key())
              .serial_number(1).not_valid_before(when - datetime.timedelta(days=1))
              .not_valid_after(when + datetime.timedelta(days=30))
              .add_extension(x509.SubjectAlternativeName([x509.DNSName("pixai.art")]), False)
              .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
              .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
                             False)
              .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(
                  ca_key.public_key()), False)
              .sign(ca_key, hashes.SHA256()))
    with pytest.raises(VerificationError):
        verifier("pixai.art").verify(forged, [])


def test_a_non_ascii_pc_name_still_gets_https(tmp_path):
    """Review must-fix: DESKTOP-JOSÉ crashed a LAN start (the certificate format cannot carry
    the É). The name is left out of the certificate and the server starts on HTTPS."""
    _x509()
    from moonglade import tls
    mode, ctx, fp, problem = g.prepare_tls("0.0.0.0", False, "Moonglade",
                                           hostname="DESKTOP-JOSÉ", lan_ip="192.168.1.5")
    assert (mode, problem) == (tls.TLS_LAN, "") and ctx is not None and fp
    assert tls.certificate_dns_names(["DESKTOP-JOSÉ", "desktop-josé.local", "Mypc",
                                      "-bad", "ok.local", "ok.local"]) == ["mypc", "ok.local"]


def test_any_certificate_failure_means_plain_http_never_a_crash(tmp_path, monkeypatch,
                                                                capsys):
    _x509()
    from moonglade import tls

    def _boom(*a, **k):
        raise ValueError("something the builder did not expect")
    monkeypatch.setattr(tls, "_ensure", _boom)
    mode, ctx, fp, problem = g.prepare_tls("0.0.0.0", False, "Moonglade", hostname="pc",
                                           lan_ip="192.168.1.5")
    assert (mode, ctx, fp) == (tls.TLS_OFF, None, "")
    assert "couldn't make its HTTPS certificate" in problem
    assert "Serving plain HTTP" in capsys.readouterr().out
    monkeypatch.setattr(tls, "server_context", _boom)
    monkeypatch.undo()
    monkeypatch.setattr(tls, "server_context", _boom)
    assert g.prepare_tls("0.0.0.0", False, "Moonglade", hostname="pc",
                         lan_ip="192.168.1.5")[0] == tls.TLS_OFF
    assert g.prepare_tls("127.0.0.1", False, "Moonglade")[0] == tls.TLS_OFF   # no LAN, no TLS


def test_a_key_that_does_not_match_its_certificate_is_healed(tmp_path):
    """Review: a stop between writing the key and the certificate left a pair that never
    matched again. The next start sees it and makes a matching pair."""
    _x509()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from moonglade import tls
    cert_p, key_p = tls.ensure_certificate()
    other = ec.generate_private_key(ec.SECP256R1())
    key_p.write_bytes(other.private_bytes(serialization.Encoding.PEM,
                                          serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    tls.ensure_certificate()
    leaf = _certs(cert_p)[0]
    key = serialization.load_pem_private_key(key_p.read_bytes(), None)
    assert tls.pair_matches(leaf, key)
    tls.server_context(cert_p, key_p)                  # and ssl accepts the pair
    # the authority's own pair heals the same way
    ca_key_p = tmp_path / moonglade_paths.TLS_CA_KEY_NAME
    ca_key_p.write_bytes(key_p.read_bytes())
    tls.ensure_certificate()
    ca = _certs(tmp_path / moonglade_paths.TLS_CA_CERT_NAME)[0]
    assert tls.pair_matches(ca, serialization.load_pem_private_key(ca_key_p.read_bytes(), None))
    _certs(cert_p)[0].verify_directly_issued_by(ca)


def test_an_older_self_signed_certificate_is_migrated_once(tmp_path):
    """An install that ran this branch's first build kept a self-signed server certificate and
    no authority. The next start makes the authority and re-issues the server certificate
    under it; the start after that changes nothing."""
    x509 = _x509()
    import datetime
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from moonglade import tls
    k = ec.generate_private_key(ec.SECP256R1())
    now = datetime.datetime.now(datetime.timezone.utc)
    name = x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "Moonglade Athenaeum")])
    old = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
           .public_key(k.public_key()).serial_number(7)
           .not_valid_before(now - datetime.timedelta(days=1))
           .not_valid_after(now + datetime.timedelta(days=800))
           .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), False)
           .sign(k, hashes.SHA256()))
    cert_p, key_p = tls.cert_path(), tls.key_path()
    cert_p.write_bytes(old.public_bytes(serialization.Encoding.PEM))
    key_p.write_bytes(k.private_bytes(serialization.Encoding.PEM,
                                      serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
    tls.ensure_certificate()
    ca = _certs(tmp_path / moonglade_paths.TLS_CA_CERT_NAME)[0]
    leaf = _certs(cert_p)[0]
    assert leaf != old
    leaf.verify_directly_issued_by(ca)
    after = cert_p.read_bytes()
    tls.ensure_certificate()
    assert cert_p.read_bytes() == after


def test_a_certificate_longer_than_apples_ceiling_is_reissued_once(tmp_path):
    """The first builds back-dated the start a day and still added the full 825 days: an
    826-day span, which an iPhone, a Mac and an Apple TV refuse as "not standards compliant"
    (SecTrust, 2026-11-20). The next start re-issues it under the same authority, so the
    fingerprint a device pinned does not move, and the start after that changes nothing."""
    x509 = _x509()
    import datetime
    from cryptography.hazmat.primitives import hashes, serialization
    from moonglade import tls
    cert_p, key_p = tls.ensure_certificate(dns_names=["mypc.local"])
    authority = tls.fingerprint()
    good = _certs(cert_p)[0]
    ca = _certs(tmp_path / moonglade_paths.TLS_CA_CERT_NAME)[0]
    ca_key = serialization.load_pem_private_key(
        (tmp_path / moonglade_paths.TLS_CA_KEY_NAME).read_bytes(), None)
    key = serialization.load_pem_private_key(key_p.read_bytes(), None)
    start = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    builder = (x509.CertificateBuilder().subject_name(good.subject).issuer_name(ca.subject)
               .public_key(key.public_key()).serial_number(9)
               .not_valid_before(start)
               .not_valid_after(start + datetime.timedelta(days=tls.CERT_LIFETIME_DAYS + 1)))
    for ext in good.extensions:
        builder = builder.add_extension(ext.value, ext.critical)
    too_long = builder.sign(ca_key, hashes.SHA256())
    assert not tls.within_apple_ceiling(too_long)
    cert_p.write_bytes(too_long.public_bytes(serialization.Encoding.PEM)
                       + ca.public_bytes(serialization.Encoding.PEM))
    tls.ensure_certificate(dns_names=["mypc.local"])
    leaf = _certs(cert_p)[0]
    assert leaf != too_long and tls.within_apple_ceiling(leaf)
    leaf.verify_directly_issued_by(ca)
    assert tls.fingerprint() == authority, "the authority a device pinned must not move"
    after = cert_p.read_bytes()
    tls.ensure_certificate(dns_names=["mypc.local"])
    assert cert_p.read_bytes() == after


def test_a_certificate_near_its_end_is_replaced(tmp_path):
    _x509()
    import datetime
    from moonglade import tls
    long_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=tls.CERT_LIFETIME_DAYS - tls.CERT_RENEW_BEFORE_DAYS + 2)
    cert, _key = tls.ensure_certificate(now=long_ago)
    old = cert.read_bytes()
    authority = tls.fingerprint()
    tls.ensure_certificate()
    assert cert.read_bytes() != old and tls.fingerprint() == authority


def test_without_cryptography_a_stored_pair_still_serves_and_none_says_why(tmp_path,
                                                                          monkeypatch):
    from moonglade import tls
    monkeypatch.setattr(tls, "can_make_certificates", lambda: False)
    with pytest.raises(tls.TLSUnavailable) as e:
        tls.ensure_certificate()
    assert "cryptography" in str(e.value)
    assert tls.fingerprint() == ""


def test_a_device_can_fetch_the_authority_before_it_signs_in(tmp_path):
    _x509()
    from moonglade import tls
    app = create_app(tmp_path)
    cli = app.test_client()
    assert cli.get("/moonglade-ca.crt").status_code == 404           # no HTTPS this start
    tls.ensure_certificate()
    app.config["MG_TLS_FINGERPRINT"] = tls.fingerprint()
    r = cli.get("/moonglade-ca.crt")                                   # no session at all
    assert r.status_code == 200
    assert r.mimetype == "application/x-x509-ca-cert"
    assert r.get_data() == (tmp_path / moonglade_paths.TLS_CA_CERT_NAME).read_bytes()
    assert b"PRIVATE KEY" not in r.get_data()


def test_a_secret_file_is_private_before_a_byte_is_written(tmp_path, monkeypatch):
    """Review: create, restrict, THEN write -- the temp file of every secret write."""
    seen = []
    real = secure_files.restrict_to_owner

    def _spy(p):
        seen.append((os.path.basename(str(p)), os.path.getsize(p) if os.path.exists(p) else -1))
        return real(p)
    monkeypatch.setattr(secure_files, "restrict_to_owner", _spy)
    core.add_or_update_web_user("alice", "a-real-test-password-1")          # config.json
    mirror_mod.save_mirror_state({"jwt": "a.b.c"})                           # the Mirror
    temps = [(n, size) for n, size in seen if ".tmp-" in n]
    assert any(n.startswith("config.json.tmp-") for n, _ in temps), seen
    assert any(n.startswith(moonglade_paths.MIRROR_SESSION_NAME + ".tmp-") for n, _ in temps)
    assert all(size == 0 for _n, size in temps), "a temp file held its secret before it was " \
        "made private: %s" % temps
    secure_files.write_private(tmp_path / "x.tmp", "secret")
    assert (tmp_path / "x.tmp").read_text() == "secret"

def _serve(app, ctx):
    from moonglade import tls
    srv = tls.make_server("127.0.0.1", 0, app, tls_context=ctx)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def test_one_port_answers_https_and_plain_http(tmp_path):
    pytest.importorskip("cryptography", reason="making the certificate needs cryptography")
    import http.client
    from moonglade import tls
    cert, key = tls.ensure_certificate()
    app = create_app(tmp_path)
    app.config["MG_TLS_MODE"] = "lan"
    srv = _serve(app, tls.server_context(cert, key))
    try:
        port = srv.server_address[1]
        # The check a person makes at the browser's warning, made here: no trust store, the
        # certificate the server presents compared by its SHA-256 fingerprint. (The suite's
        # truststore hook answers for the OS store, which never trusts a self-signed one.)
        client_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        client_ctx.check_hostname = False
        client_ctx.verify_mode = ssl.CERT_NONE
        conn = http.client.HTTPSConnection("127.0.0.1", port, context=client_ctx, timeout=10)
        conn.request("GET", "/login")
        import hashlib
        der = conn.sock.getpeercert(binary_form=True)
        hexd = hashlib.sha256(der).hexdigest().upper()
        assert ":".join(hexd[i:i + 2] for i in range(0, 64, 2)) == tls.fingerprint(cert)
        assert conn.sock.version() in ("TLSv1.2", "TLSv1.3")
        r = conn.getresponse()
        body = r.read()
        assert r.status == 200 and b"MG_BOOT" in body
        # A device that installed the authority: OpenSSL's own path validation (chain, the
        # authority's name constraints, the address in the certificate) accepts the server.
        # The stdlib context class, not truststore's, which only consults the OS store.
        trusting = tls._stdlib_context_class()(ssl.PROTOCOL_TLS_CLIENT)
        trusting.load_verify_locations(cafile=str(tls.ca_cert_path()))
        v = http.client.HTTPSConnection("127.0.0.1", port, context=trusting, timeout=10)
        v.request("GET", "/api/ping")
        assert v.getresponse().status in (200, 401)
        v.close()
        # the session cookie the HTTPS page set is Secure
        assert "Secure" in (r.getheader("Set-Cookie") or "")
        conn.close()
        plain = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        plain.request("GET", "/login")
        r = plain.getresponse()
        r.read()
        assert r.status == 200, "this PC's own plain HTTP must keep working in LAN mode"
        assert "Secure" not in (r.getheader("Set-Cookie") or "")
        plain.close()
        # a client that connects and says nothing is dropped, and the server keeps serving
        import socket
        s = socket.create_connection(("127.0.0.1", port), timeout=5)
        s.close()
        again = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        again.request("GET", "/api/ping")
        assert again.getresponse().status in (200, 401)
        again.close()
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_plain_server_is_what_it_always_was(tmp_path):
    import http.client
    srv = _serve(create_app(tmp_path), None)
    try:
        c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
        c.request("GET", "/login")
        assert c.getresponse().status == 200
        c.close()
    finally:
        srv.shutdown()
        srv.server_close()


# ---------------------------------------------------------------------------
# Finding 5: secrets at rest
# ---------------------------------------------------------------------------

def _icacls(path):
    import subprocess
    out = subprocess.run(["icacls", str(path)], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=30).stdout
    return out


@pytest.mark.skipif(os.name != "nt", reason="the Windows access list")
def test_a_restricted_file_names_only_this_user_and_system_on_windows(tmp_path):
    p = tmp_path / "secret.json"
    p.write_text("{}", encoding="utf-8")
    assert "(I)" in _icacls(p), "the test file should start out inheriting its folder's list"
    assert secure_files.restrict_to_owner(p) is True
    out = _icacls(p)
    assert "(I)" not in out, out                     # nothing inherited any more
    import getpass
    entries = [ln for ln in out.splitlines()[0:] if ":(" in ln]
    joined = "\n".join(entries).lower()
    assert getpass.getuser().lower() in joined and ("system" in joined), out
    assert len(entries) == 2, out
    assert p.read_text(encoding="utf-8") == "{}"    # still ours to read


@pytest.mark.skipif(os.name == "nt", reason="the POSIX mode")
def test_a_restricted_file_is_owner_only_on_posix(tmp_path):
    p = tmp_path / "secret.json"
    p.write_text("{}", encoding="utf-8")
    os.chmod(p, 0o644)
    assert secure_files.restrict_to_owner(p) is True
    assert (os.stat(p).st_mode & 0o777) == 0o600


def test_a_refusal_is_soft_and_says_so_once(tmp_path, monkeypatch, caplog):
    p = tmp_path / "secret.json"
    p.write_text("{}", encoding="utf-8")
    def _no(_path):
        raise PermissionError("denied by the file system")
    monkeypatch.setattr(secure_files, "_restrict_windows", _no)
    monkeypatch.setattr(secure_files.os, "chmod", lambda *a: _no(a))
    caplog.set_level(logging.WARNING)
    assert secure_files.restrict_to_owner(p) is False
    lines = [r for r in caplog.records if "secret.json" in r.getMessage()]
    assert len(lines) == 1 and "{}" not in lines[0].getMessage()
    assert secure_files.restrict_to_owner(tmp_path / "absent.json") is False


def test_every_secret_write_restricts_the_file(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(secure_files, "restrict_to_owner",
                        lambda p: seen.append(os.path.basename(str(p))) or True)
    core.add_or_update_web_user("alice", "a-real-test-password-1")     # config.json
    assert "config.json" in seen
    mirror_mod.save_mirror_state({"jwt": "a.b.c"})                      # the Mirror's sign-in
    assert moonglade_paths.MIRROR_SESSION_NAME in seen


def test_the_startup_sweep_names_every_secret_file(tmp_path):
    names = [os.path.basename(str(p)) for p in secure_files.secret_files()]
    assert names == ["config.json", moonglade_paths.MIRROR_SESSION_NAME,
                     moonglade_paths.TLS_KEY_NAME, moonglade_paths.TLS_CA_KEY_NAME]
    src = open(g.__file__, encoding="utf-8").read()
    main_src = src[src.index("\ndef main():"):]
    assert "_secure_files.restrict_existing_secrets()" in main_src


# ---------------------------------------------------------------------------
# Finding 6: sessions
# ---------------------------------------------------------------------------

def _steal(cli):
    return cli.get_cookie("session").value


def _replay(app, stolen):
    cli = app.test_client()
    cli.set_cookie("session", stolen)
    return cli.get("/api/jobs")


def _logout(cli, **extra):
    from tests.conftest import session_csrf
    return cli.post("/api/logout", json=dict({"csrf": session_csrf(cli)}, **extra))


def test_log_out_ends_a_copied_cookie_too(tmp_path):
    core.add_or_update_web_user("alice", "a-real-test-password-1")
    app = create_app(tmp_path)
    device = _do_login(app.test_client(), "alice", "a-real-test-password-1")
    other = _do_login(app.test_client(), "alice", "a-real-test-password-1")
    stolen = _steal(device)
    assert _replay(app, stolen).status_code == 200
    assert _logout(device).get_json() == {"ok": True}
    assert _replay(app, stolen).status_code == 401, "a copy of a signed-out cookie still works"
    assert other.get("/api/jobs").status_code == 200, "Log Out reached another device"
    # and it holds across a restart: the record is on disk, not in this process
    assert _replay(create_app(tmp_path), stolen).status_code == 401


def test_a_session_ends_at_its_absolute_lifetime_however_often_it_is_used(tmp_path,
                                                                         monkeypatch):
    core.add_or_update_web_user("alice", "a-real-test-password-1")
    app = create_app(tmp_path)
    cli = _do_login(app.test_client(), "alice", "a-real-test-password-1")
    assert cli.get("/api/jobs").status_code == 200
    real = time.time
    monkeypatch.setattr(g.time, "time", lambda: real() + g.SESSION_ABSOLUTE_LIFETIME_S - 60)
    assert cli.get("/api/jobs").status_code == 200
    monkeypatch.setattr(g.time, "time", lambda: real() + g.SESSION_ABSOLUTE_LIFETIME_S + 60)
    assert cli.get("/api/jobs").status_code == 401


def test_a_cookie_from_before_sessions_had_an_id_is_refused(tmp_path):
    core.add_or_update_web_user("alice", "a-real-test-password-1")
    app = create_app(tmp_path)
    cli = _do_login(app.test_client(), "alice", "a-real-test-password-1")
    with cli.session_transaction() as s:
        s.pop("sid")
        s.pop("born")
    assert cli.get("/api/jobs").status_code == 401


def test_the_signed_out_record_drops_what_has_aged_out(tmp_path):
    now = 1_000_000.0
    assert web_sessions.sign_out("old", now - 10_000, 100, now=now)
    assert web_sessions.sign_out("new", now, 100, now=now)
    doc = json.loads((tmp_path / moonglade_paths.SIGNED_OUT_SESSIONS_NAME).read_text())
    assert set(doc["signed_out"]) == {"new"}
    assert web_sessions.is_signed_out("new") and not web_sessions.is_signed_out("old")
    assert not web_sessions.is_signed_out("")


def test_sign_out_all_devices_is_a_text_button_in_the_accounts_window():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "gallery" / "src" / "components"
           / "ControlPanelOverlay.jsx").read_text(encoding="utf-8")
    body = src[src.index("export function UsersSubOverlay"):]
    body = body[:body.index("\nexport function", 10)]
    assert 'scope: "everywhere"' in body and "sign out all devices" in body
    assert 'className="mgcp-useraction"' in body


# ---------------------------------------------------------------------------
# Finding 7: the Mirror's Disconnect
# ---------------------------------------------------------------------------

def _stored_sign_in(tmp_path):
    p = tmp_path / moonglade_paths.MIRROR_SESSION_NAME
    p.write_text(json.dumps({"jwt": "x.y.z"}), encoding="utf-8")
    return p


def test_disconnect_forgets_the_sign_in_stops_renewal_and_disarms(tmp_path):
    from moonglade import settings as settings_mod
    p = _stored_sign_in(tmp_path)
    settings_mod.set_values(**{settings_mod.MIRROR_TO_PIXAI: True})
    mirror_mod._mirror_renewal.update(fails=3, next_try=9e12, failed_exp=1)
    cli = login_client(tmp_path)
    r = cli.post("/api/mirror/disconnect", json=with_csrf(cli))
    assert r.get_json() == {"ok": True, "enabled": False}
    assert not p.exists()
    assert mirror_mod._mirror_renewal["fails"] == 0
    assert settings_mod.mirror_to_pixai() is False
    assert mirror_mod.mirror_renew_tick(now=time.time()) in ("mirror_off", "no_session")
    st = cli.get("/api/mirror/status").get_json()
    assert st["connected"] is False


def test_disconnect_needs_the_token_and_the_home_network(tmp_path):
    p = _stored_sign_in(tmp_path)
    cli = login_client(tmp_path)
    assert cli.post("/api/mirror/disconnect", json={}).status_code == 400
    r = cli.post("/api/mirror/disconnect", json=with_csrf(cli),
                 environ_base={"REMOTE_ADDR": "8.8.8.8"})          # not a home network
    assert r.status_code == 403
    assert p.exists()
    # a device on the home network may disconnect, as it may Connect from PixAI
    r = cli.post("/api/mirror/disconnect", json=with_csrf(cli),
                 environ_base={"REMOTE_ADDR": "10.0.0.68"})
    assert r.get_json() == {"ok": True, "enabled": False}
    assert not p.exists()


def test_the_panel_summary_says_whether_the_viewer_is_on_the_home_network(tmp_path):
    cli = login_client(tmp_path)
    assert cli.get("/api/panel/summary").get_json()["home_network"] is True
    r = cli.get("/api/panel/summary", environ_base={"REMOTE_ADDR": "10.0.0.68"})
    assert r.get_json()["home_network"] is True and r.get_json()["panel_is_local"] is False
    r = cli.get("/api/panel/summary", environ_base={"REMOTE_ADDR": "8.8.8.8"})
    assert r.get_json()["home_network"] is False


def test_the_tile_offers_disconnect_on_the_home_network():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "gallery" / "src" / "components"
           / "ControlPanelOverlay.jsx").read_text(encoding="utf-8")
    start = src.index("function MirrorTile(")
    tile = src[start:src.index("\nexport function", start)]
    assert '"/api/mirror/disconnect"' in tile and "homeNet && st && st.connected" in tile


# ---------------------------------------------------------------------------
# Finding 9: size caps
# ---------------------------------------------------------------------------

def test_a_body_over_the_app_wide_cap_is_refused_in_words(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    assert app.config["MAX_CONTENT_LENGTH"] == g.REQUEST_MAX_BYTES
    app.config["MAX_CONTENT_LENGTH"] = 1024
    cli = login_test_client(app)
    r = cli.post("/api/view-presets", json=with_csrf(cli, {"name": "x" * 4096}))
    assert r.status_code == 413
    assert "more than Moonglade takes in one go" in r.get_json()["error"]


def _zip_bytes(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members:
            z.writestr(name, data)
    return buf.getvalue()


def _import(cli, blob, name="pack.zip"):
    return cli.post("/api/import-local", data={"files": (io.BytesIO(blob), name)},
                    content_type="multipart/form-data")


def test_a_zip_with_too_many_files_is_refused_before_anything_is_written(tmp_path,
                                                                        monkeypatch):
    monkeypatch.setattr(g, "ZIP_MAX_MEMBERS", 3)
    cli = login_client(tmp_path)
    r = _import(cli, _zip_bytes([("a%d.png" % i, b"x") for i in range(5)]))
    assert r.status_code == 413 and "more than" in r.get_json()["error"]
    assert not (tmp_path / "imported").exists()


def test_a_zip_bomb_stops_at_the_byte_budget(tmp_path, monkeypatch):
    """The bytes are counted as they are written: a member that LIES small in its header is
    still stopped. Here the budget is shrunk; the zip unpacks far past it."""
    monkeypatch.setattr(g, "ZIP_MAX_TOTAL_BYTES", 64 * 1024)
    cli = login_client(tmp_path)
    r = _import(cli, _zip_bytes([("big.png", b"\0" * (4 * 1024 * 1024))]))
    assert r.status_code == 413 and "unpacks to more than" in r.get_json()["error"]
    assert not (tmp_path / "imported").exists()


def test_one_huge_file_in_a_zip_stops_at_the_per_file_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "ZIP_MAX_MEMBER_BYTES", 32 * 1024)
    cli = login_client(tmp_path)
    r = _import(cli, _zip_bytes([("small.png", b"x" * 1024), ("big.mp4", b"\0" * 200_000)]))
    assert r.status_code == 413
    err = r.get_json()["error"]
    assert "A file in that zip" in err and "--import-local" in err, err
    assert not (tmp_path / "imported").exists()


def test_the_limits_fit_a_whole_library_and_name_the_command_line_import():
    """Review: a 5 GB library zip, one video over 2 GB and a zip unpacking past 8 GB were all
    refused. The limits now fit a library; every refusal names the CLI import."""
    gb = 1024 ** 3
    assert g.IMPORT_REQUEST_MAX_BYTES >= 50 * gb and g.ZIP_MAX_TOTAL_BYTES >= 50 * gb
    assert g.ZIP_MAX_MEMBER_BYTES >= 8 * gb and g.UPLOAD_MAX_BYTES >= 8 * gb
    assert g.LOOM_BUNDLE_REQUEST_MAX_BYTES >= 50 * gb and g.ZIP_MAX_MEMBERS >= 100000
    for msg in (g.ZIP_TOO_BIG, g.ZIP_TOO_MANY_MEMBERS, g.ZIP_MEMBER_TOO_BIG,
                g._too_large_sentence(g.IMPORT_REQUEST_MAX_BYTES)):
        assert "python -m moonglade --import-local" in msg, msg


def test_the_extractor_counts_what_it_writes_not_what_the_zip_claims(tmp_path):
    app = create_app(tmp_path)
    src = tmp_path / "in.zip"
    src.write_bytes(_zip_bytes([("a.bin", b"\1" * 300_000), ("b.bin", b"\2" * 300_000)]))
    out = tmp_path / "out"
    out.mkdir()
    # reach the closure through the route's module-level twin of its rule
    extract = None
    for cell in (app.view_functions["api_import_local"].__closure__ or ()):
        if getattr(cell.cell_contents, "__name__", "") == "_safe_extract_zip":
            extract = cell.cell_contents
    assert extract is not None
    with pytest.raises(g.ZipTooBig):
        extract(str(src), str(out), max_total=400_000)
    assert extract(str(src), str(out)) == 600_000


def test_a_loom_bundle_with_too_many_entries_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "ZIP_MAX_MEMBERS", 2)
    cli = login_client(tmp_path)
    blob = _zip_bytes([("project.json", json.dumps({"project": {"n": 1}}))] +
                      [("media/%d.png" % i, b"x") for i in range(4)])
    r = cli.post("/api/loom/import-bundle", data={"file": (io.BytesIO(blob), "b.zip")},
                 content_type="multipart/form-data")
    assert r.status_code == 413


def test_the_upload_routes_raise_their_own_caps_in_named_constants():
    src = open(g.__file__, encoding="utf-8").read()
    for route, const in (("def api_upload(", "UPLOAD_MAX_BYTES"),
                         ("def api_import_local(", "IMPORT_REQUEST_MAX_BYTES"),
                         ("def api_loom_import_bundle(", "LOOM_BUNDLE_REQUEST_MAX_BYTES")):
        body = src[src.index(route):]
        body = body[:body.index("\n    @app.route")]
        assert "request.max_content_length = " + const in body, route
