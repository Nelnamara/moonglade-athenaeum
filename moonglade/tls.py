"""
moonglade/tls.py
================
HTTPS on the home network: one self-signed certificate, made once and kept, and a server that
answers HTTPS and plain HTTP on the same port.

THE CERTIFICATE. local/tls_cert.pem and local/tls_key.pem, made the first time a server start
needs them (ensure_certificate) and reused on every start after, so a phone or a Mac shows its
certificate warning once and its SHA-256 fingerprint never changes under it. The key is written
for this user's account only (moonglade.secure_files). It is replaced only when it is missing,
unreadable, or within CERT_RENEW_BEFORE_DAYS of the end of its CERT_LIFETIME_DAYS (Apple's
devices refuse a server certificate that claims longer). Making one needs the `cryptography`
package (requirements.txt); reading the fingerprint needs nothing but the standard library.

ONE PORT, BOTH PROTOCOLS. ProtocolSniffingServer peeks at the first byte of each new
connection, in that connection's own thread: a TLS handshake starts with 0x16, and only then is
the connection wrapped in TLS; anything else is served as plain HTTP. So the address, the port,
the firewall rule and the Bonjour record stay what they were, and only the scheme in front of
the address changes. What a plain request is ALLOWED to do is not decided here but by the app's
request gate (moonglade.gallery's _send_plain_lan_visits_to_https), which reads the TLS mode
this module's names describe:

  TLS_OFF  -- nothing is encrypted (a server bound to this PC only, or no `cryptography`);
  TLS_LAN  -- the default for a home-network bind: another device must use https://, this PC's
              own loopback may keep plain http:// (its traffic never leaves the PC, and a
              localhost page is already a secure context to the browser);
  TLS_ALL  -- the --https switch: every client, this PC's included, uses https://.
"""
import datetime
import hashlib
import os
import socket
import ssl

from werkzeug.serving import ThreadedWSGIServer, WSGIRequestHandler

from moonglade import paths as _paths
from moonglade import secure_files as _secure

TLS_OFF, TLS_LAN, TLS_ALL = "off", "lan", "all"

# Apple's ceiling for a TLS server certificate is 825 days; a longer one is refused outright.
CERT_LIFETIME_DAYS = 825
# A certificate this close to its end is replaced at the next start (a new fingerprint, said so
# in the Control Panel's LAN card like any other).
CERT_RENEW_BEFORE_DAYS = 30
# How long a new connection may sit silent before its first byte (the protocol sniff) or its
# TLS handshake finishes. The wait happens in the connection's own thread, never the accept loop.
TLS_SNIFF_TIMEOUT_S = 10.0
_TLS_HANDSHAKE_BYTE = 0x16


class TLSUnavailable(RuntimeError):
    """The certificate could not be made or loaded; the message is a plain sentence."""


def cert_path():
    return _paths.local_path(_paths.TLS_CERT_NAME)


def key_path():
    return _paths.local_path(_paths.TLS_KEY_NAME)


def can_make_certificates():
    """True when the `cryptography` package is installed."""
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


def _load_cert(path):
    """The x509 certificate at `path`, or None when it is absent or unreadable."""
    try:
        from cryptography import x509
        return x509.load_pem_x509_certificate(path.read_bytes())
    except Exception:                                   # noqa: BLE001
        return None


def _not_after(cert):
    try:
        return cert.not_valid_after_utc
    except AttributeError:                              # cryptography < 42
        return cert.not_valid_after.replace(tzinfo=datetime.timezone.utc)


def _usable(cert_p, key_p, now):
    """The stored pair is there, parses, and has more than CERT_RENEW_BEFORE_DAYS left."""
    if not (cert_p.is_file() and key_p.is_file()):
        return False
    cert = _load_cert(cert_p)
    if cert is None:
        return False
    try:
        from cryptography.hazmat.primitives import serialization
        serialization.load_pem_private_key(key_p.read_bytes(), password=None)
    except Exception:                                   # noqa: BLE001
        return False
    return _not_after(cert) - now > datetime.timedelta(days=CERT_RENEW_BEFORE_DAYS)


def _write_secret(path, data):
    """Write `data` beside `path` and move it into place, owner-only before and after the move."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-{}".format(os.getpid()))
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        _secure.restrict_to_owner(tmp)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    _secure.restrict_to_owner(path)


def ensure_certificate(dns_names=(), ip_addresses=(), now=None):
    """(cert_path, key_path) for the home-network certificate, making it first when there is no
    usable one. `dns_names` / `ip_addresses` are the names it is made for (this PC's name, its
    .local name, its home-network address); localhost and the loopback addresses are always in.
    A certificate that already exists is reused as it is -- its names are not re-checked, so
    its fingerprint stays the one a device was told. Raises TLSUnavailable with a plain sentence."""
    import ipaddress
    now = now or datetime.datetime.now(datetime.timezone.utc)
    cert_p, key_p = cert_path(), key_path()
    if not can_make_certificates():
        if cert_p.is_file() and key_p.is_file():
            _secure.restrict_to_owner(key_p)
            return cert_p, key_p                   # made earlier; ssl can load it without us
        raise TLSUnavailable("HTTPS needs the 'cryptography' package to make its certificate "
                             "(pip install cryptography).")
    if _usable(cert_p, key_p, now):
        _secure.restrict_to_owner(key_p)
        return cert_p, key_p
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Moonglade Athenaeum"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Moonglade (this PC)")])
    dns, seen = [], set()
    for n in ("localhost",) + tuple(dns_names or ()):
        n = str(n or "").strip().rstrip(".").lower()
        if n and n not in seen and all(c.isalnum() or c in "-." for c in n):
            seen.add(n)
            dns.append(x509.DNSName(n))
    ips, seen_ip = [], set()
    for a in ("127.0.0.1", "::1") + tuple(ip_addresses or ()):
        try:
            ip = ipaddress.ip_address(str(a or "").strip())
        except ValueError:
            continue
        if ip not in seen_ip:
            seen_ip.add(ip)
            ips.append(x509.IPAddress(ip))
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=CERT_LIFETIME_DAYS))
            .add_extension(x509.SubjectAlternativeName(dns + ips), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False,
                                         decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
                           critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
                           critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(
                key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    try:
        _write_secret(key_p, key.private_bytes(serialization.Encoding.PEM,
                                               serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
        cert_p.parent.mkdir(parents=True, exist_ok=True)
        tmp = cert_p.with_name(cert_p.name + ".tmp-{}".format(os.getpid()))
        tmp.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        os.replace(tmp, cert_p)
    except OSError as e:
        raise TLSUnavailable("Moonglade couldn't save its HTTPS certificate in {} ({})."
                             .format(cert_p.parent.name, e.strerror or e)) from e
    return cert_p, key_p


def fingerprint(path=None):
    """The certificate's SHA-256 fingerprint as browsers show it (AB:CD:...), or "" when there
    is no readable certificate. Standard library only."""
    p = path or cert_path()
    try:
        der = ssl.PEM_cert_to_DER_cert(p.read_text(encoding="ascii"))
    except (OSError, ValueError):
        return ""
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def _stdlib_context_class():
    """The standard library's own ssl.SSLContext class.

    Not simply `ssl.SSLContext`: moonglade.backup calls truststore.inject_into_ssl() at import
    (corporate and antivirus HTTPS interception, CLAUDE.md), which swaps that name for
    truststore's client-side context -- and truststore's wrap_socket checks the PEER's
    certificate against the OS store even on the server side, where a browser presents none, so
    every handshake would be dropped. A server context must be the real one, found as the
    stdlib's own subclass of the C base class rather than through truststore's private names."""
    import _ssl
    for cls in _ssl._SSLContext.__subclasses__():
        if cls.__module__ == "ssl" and cls.__name__ == "SSLContext":
            return cls
    return ssl.SSLContext


def server_context(cert_p, key_p):
    """A server-side TLS context on the stored pair (TLS 1.2 and up)."""
    import _ssl
    ctx = _stdlib_context_class()(ssl.PROTOCOL_TLS_SERVER)
    # Through the C base's own descriptor: the stdlib class's Python setter names the global
    # ssl.SSLContext, which is truststore's while it is injected (see _stdlib_context_class).
    _ssl._SSLContext.minimum_version.__set__(ctx, ssl.TLSVersion.TLSv1_2)
    try:
        ctx.load_cert_chain(str(cert_p), str(key_p))
    except (OSError, ssl.SSLError) as e:
        raise TLSUnavailable("Moonglade couldn't load its HTTPS certificate ({}).".format(e)) from e
    return ctx


class TLSAwareRequestHandler(WSGIRequestHandler):
    """Werkzeug's handler, with the scheme read off THIS connection (TLS or not) rather than
    off the server, since one server speaks both."""

    def make_environ(self):
        environ = super().make_environ()
        environ["wsgi.url_scheme"] = ("https" if isinstance(self.connection, ssl.SSLSocket)
                                      else "http")
        return environ

    def handle(self):
        try:
            super().handle()
        except ssl.SSLError as e:                       # a client that broke off mid-TLS
            self.connection_dropped(e)


class ProtocolSniffingServer(ThreadedWSGIServer):
    """A threaded Werkzeug server that answers TLS and plain HTTP on one port (see the module
    docstring). `tls_context` None makes it an ordinary plain-HTTP server."""

    def __init__(self, host, port, app, tls_context=None, passthrough_errors=False):
        super().__init__(host, port, app, handler=TLSAwareRequestHandler,
                         passthrough_errors=passthrough_errors)
        self.tls_context = tls_context

    def finish_request(self, request, client_address):
        conn = request
        if self.tls_context is not None:
            try:
                request.settimeout(TLS_SNIFF_TIMEOUT_S)
                first = request.recv(1, socket.MSG_PEEK)
                if not first:
                    return                              # closed before saying anything
                if first[0] == _TLS_HANDSHAKE_BYTE:
                    conn = self.tls_context.wrap_socket(request, server_side=True)
                conn.settimeout(None)
            except (OSError, ssl.SSLError):
                if conn is not request:
                    _close_quietly(conn)
                return
        try:
            self.RequestHandlerClass(conn, client_address, self)
        finally:
            if conn is not request:                     # the TLS wrapper took the socket over
                _close_quietly(conn)

    def log_startup(self):                              # main() prints its own address line
        pass


def _close_quietly(sock):
    try:
        sock.close()
    except OSError:
        pass


def make_server(host, port, app, tls_context=None):
    """The server main() runs: one ProtocolSniffingServer on (host, port)."""
    return ProtocolSniffingServer(host, port, app, tls_context=tls_context)
