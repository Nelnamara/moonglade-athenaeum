"""
moonglade/tls.py
================
HTTPS on the home network: a small certificate authority of this PC's own, the server
certificate it signs, and a server that answers HTTPS and plain HTTP on the same port.

THE CERTIFICATES. Two pairs in local\\, each key written for this user's account only
(moonglade.secure_files), made the first time a server start needs them (ensure_certificate):

  tls_ca_cert.pem / tls_ca_key.pem  -- "Moonglade (this PC)", a certificate authority made ONCE
      and kept for CA_LIFETIME_DAYS. It may only vouch for this machine's own names: it carries
      a critical Name Constraints extension permitting localhost, *.local, this PC's own name
      and the loopback and private home-network address ranges, so even its key could not
      vouch for any website. Installing ITS certificate on a phone, tablet or Mac once (the
      Control Panel's LAN card links it and shows its SHA-256 fingerprint to check) is what
      stops the browser's warning for good.
  tls_cert.pem / tls_key.pem        -- the server certificate, signed by that authority, for the
      names the PC answers on (localhost, its name, its .local names, its home-network
      address). It is re-made whenever it is missing, unreadable, does not match its key, was
      not signed by the authority (an install that ran an earlier build of this module kept a
      self-signed one: the first start after it is migrated this way), lacks a name the PC now
      answers on (the router gave it a new address), or is within CERT_RENEW_BEFORE_DAYS of its
      CERT_LIFETIME_DAYS (Apple's ceiling for a server certificate). A device that installed the
      authority never notices; one that did not sees a new warning.

Any failure making them -- a missing `cryptography` package, an unwritable folder, a PC name
the certificate format cannot carry -- is a TLSUnavailable with a plain sentence, and the
server then serves plain HTTP and says so. Reading a fingerprint needs only the standard library.

ONE PORT, BOTH PROTOCOLS. ProtocolSniffingServer peeks at the first byte of each new
connection, in that connection's own thread: a TLS handshake starts with 0x16, and only then is
the connection wrapped in TLS; anything else is served as plain HTTP. So the address, the port,
the firewall rule and the Bonjour record stay what they were, and only the scheme in front of
the address changes. What a plain request is ALLOWED to do is not decided here but by the app's
request gate (moonglade.gallery's _send_plain_lan_visits_to_https), which reads the TLS mode
this module's names describe:

  TLS_OFF  -- nothing is encrypted (a server bound to this PC only, or no certificate);
  TLS_LAN  -- the default for a home-network bind: another device must use https://, this PC's
              own loopback may keep plain http:// (its traffic never leaves the PC, and a
              localhost page is already a secure context to the browser);
  TLS_ALL  -- the --https switch: every client, this PC's included, uses https://.
"""
import datetime
import hashlib
import ipaddress
import os
import re
import socket
import ssl

from werkzeug.serving import ThreadedWSGIServer, WSGIRequestHandler

from moonglade import paths as _paths
from moonglade import secure_files as _secure

TLS_OFF, TLS_LAN, TLS_ALL = "off", "lan", "all"

# The authority lives ten years: it is what a device installs, so it should not move.
CA_LIFETIME_DAYS = 3650
# Apple's ceiling for a TLS server certificate is 825 days; a longer one is refused outright.
CERT_LIFETIME_DAYS = 825
# A certificate this close to its end is replaced at the next start.
CERT_RENEW_BEFORE_DAYS = 30
# What the authority may vouch for (its Name Constraints, besides this PC's own name): the
# loopback names and every .local name, and the loopback and private address ranges -- so a new
# home-network address from the router is still inside, and no public name or address ever is.
CA_PERMITTED_DNS = ("localhost", "local")
CA_PERMITTED_NETS = ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                     "169.254.0.0/16", "::1/128", "fc00::/7", "fe80::/10")
# How long a new connection may sit silent before its first byte (the protocol sniff) or its
# TLS handshake finishes. The wait happens in the connection's own thread, never the accept loop.
TLS_SNIFF_TIMEOUT_S = 10.0
_TLS_HANDSHAKE_BYTE = 0x16
# A DNS name a certificate can carry: ASCII letters, digits and hyphens in dot-separated labels
# of 1-63 characters. A PC named with any other letter (DESKTOP-JOSÉ) is simply left out of the
# certificate -- its .local name is, too -- and the address and localhost still are in it.
_DNS_LABEL_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


class TLSUnavailable(RuntimeError):
    """The certificate could not be made or loaded; the message is a plain sentence."""


def cert_path():
    return _paths.local_path(_paths.TLS_CERT_NAME)


def key_path():
    return _paths.local_path(_paths.TLS_KEY_NAME)


def ca_cert_path():
    return _paths.local_path(_paths.TLS_CA_CERT_NAME)


def ca_key_path():
    return _paths.local_path(_paths.TLS_CA_KEY_NAME)


def can_make_certificates():
    """True when the `cryptography` package is installed."""
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


def certificate_dns_names(names):
    """The names from `names` a certificate can carry, lower-cased, in order, without repeats:
    ASCII host names only (_DNS_LABEL_RE). Pure."""
    out = []
    for n in names or ():
        n = str(n or "").strip().rstrip(".").lower()
        if (n and n.isascii() and len(n) <= 253 and n not in out
                and all(_DNS_LABEL_RE.match(label) for label in n.split("."))):
            out.append(n)
    return out


def _load_first_cert(path):
    """The first certificate in the PEM file at `path`, or None when absent or unreadable."""
    try:
        from cryptography import x509
        return x509.load_pem_x509_certificates(path.read_bytes())[0]
    except Exception:                                   # noqa: BLE001
        return None


def _load_key(path):
    try:
        from cryptography.hazmat.primitives import serialization
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    except Exception:                                   # noqa: BLE001
        return None


def _not_after(cert):
    try:
        return cert.not_valid_after_utc
    except AttributeError:                              # cryptography < 42
        return cert.not_valid_after.replace(tzinfo=datetime.timezone.utc)


def _spki(public_key):
    from cryptography.hazmat.primitives import serialization
    return public_key.public_bytes(serialization.Encoding.DER,
                                   serialization.PublicFormat.SubjectPublicKeyInfo)


def pair_matches(cert, key):
    """The certificate was made for this private key (same public key). Pure."""
    try:
        return _spki(cert.public_key()) == _spki(key.public_key())
    except Exception:                                   # noqa: BLE001
        return False


def _fresh(cert, now):
    return _not_after(cert) - now > datetime.timedelta(days=CERT_RENEW_BEFORE_DAYS)


def _write_pair(cert_p, key_p, cert_pem, key_pem):
    """Both files, each through a temp file moved into place (the key's temp owner-only before
    a byte of it is written). The key goes first; a stop between the two leaves a pair that
    does not match, which the next start sees (pair_matches) and makes again."""
    for p, data, secret in ((key_p, key_pem, True), (cert_p, cert_pem, False)):
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp-{}".format(os.getpid()))
        try:
            if secret:
                _secure.write_private(tmp, data)
            else:
                tmp.write_bytes(data)
            os.replace(tmp, p)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
    _secure.restrict_to_owner(key_p)


def _ec_key():
    from cryptography.hazmat.primitives.asymmetric import ec
    return ec.generate_private_key(ec.SECP256R1())


def _pem(cert, key):
    from cryptography.hazmat.primitives import serialization
    return (cert.public_bytes(serialization.Encoding.PEM),
            key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                              serialization.NoEncryption()))


def _ensure_ca(own_names, now):
    """(ca_cert, ca_key): the stored authority when it is whole, matching and not near its end;
    else a new one, written before it is returned."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.x509.oid import NameOID
    c_p, k_p = ca_cert_path(), ca_key_path()
    cert, key = _load_first_cert(c_p), _load_key(k_p)
    if cert is not None and key is not None and pair_matches(cert, key) and _fresh(cert, now):
        try:
            if cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
                _secure.restrict_to_owner(k_p)
                return cert, key
        except x509.ExtensionNotFound:
            pass
    key = _ec_key()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Moonglade (this PC)"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Moonglade Athenaeum")])
    permitted = [x509.DNSName(n) for n in certificate_dns_names(CA_PERMITTED_DNS + tuple(
        own_names))]
    permitted += [x509.IPAddress(ipaddress.ip_network(n)) for n in CA_PERMITTED_NETS]
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=CA_LIFETIME_DAYS))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, key_cert_sign=True,
                                         crl_sign=True, encipher_only=False,
                                         decipher_only=False), critical=True)
            .add_extension(x509.NameConstraints(permitted_subtrees=permitted,
                                                excluded_subtrees=None), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
                           critical=False)
            .sign(key, hashes.SHA256()))
    _write_pair(c_p, k_p, *_pem(cert, key))
    return cert, key


def _permitted_by(ca, dns, ips):
    """The names and addresses of `dns` / `ips` that `ca`'s Name Constraints allow."""
    from cryptography import x509
    try:
        nc = ca.extensions.get_extension_for_class(x509.NameConstraints).value
    except x509.ExtensionNotFound:
        return list(dns), list(ips)
    p_dns = [g.value for g in nc.permitted_subtrees or () if isinstance(g, x509.DNSName)]
    p_net = [g.value for g in nc.permitted_subtrees or () if isinstance(g, x509.IPAddress)]
    ok_dns = [n for n in dns if any(n == d or n.endswith("." + d) for d in p_dns)]
    ok_ips = [a for a in ips if any(a.version == net.version and a in net for net in p_net)]
    return ok_dns, ok_ips


def _leaf_names(cert):
    from cryptography import x509
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return set(), set()
    return (set(san.get_values_for_type(x509.DNSName)),
            set(san.get_values_for_type(x509.IPAddress)))


def _ensure(dns_names, ip_addresses, now):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    own = certificate_dns_names(dns_names)
    ca, ca_key = _ensure_ca([n for n in own if "." not in n], now)
    dns = certificate_dns_names(["localhost"] + own)
    ips = []
    for a in ("127.0.0.1", "::1") + tuple(ip_addresses or ()):
        try:
            ip = ipaddress.ip_address(str(a or "").strip())
        except ValueError:
            continue
        if ip not in ips:
            ips.append(ip)
    dns, ips = _permitted_by(ca, dns, ips)
    cert_p, key_p = cert_path(), key_path()
    leaf, key = _load_first_cert(cert_p), _load_key(key_p)
    if leaf is not None and key is not None and pair_matches(leaf, key) and _fresh(leaf, now):
        try:
            leaf.verify_directly_issued_by(ca)
            have_dns, have_ips = _leaf_names(leaf)
            if set(dns) <= have_dns and set(ips) <= have_ips:
                _secure.restrict_to_owner(key_p)
                return cert_p, key_p
        except Exception:                               # noqa: BLE001 -- not this authority's
            pass
    key = _ec_key()
    leaf = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,
                                                        "Moonglade Athenaeum")]))
            .issuer_name(ca.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(min(now + datetime.timedelta(days=CERT_LIFETIME_DAYS),
                                 _not_after(ca)))
            .add_extension(x509.SubjectAlternativeName(
                [x509.DNSName(n) for n in dns] + [x509.IPAddress(a) for a in ips]),
                critical=False)
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
                ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    leaf_pem, key_pem = _pem(leaf, key)
    ca_pem, _ = _pem(ca, ca_key)
    # The server sends the leaf and the authority above it, so a device's warning shows the
    # authority it can check (and install).
    _write_pair(cert_p, key_p, leaf_pem + ca_pem, key_pem)
    return cert_p, key_p


def ensure_certificate(dns_names=(), ip_addresses=(), now=None):
    """(cert_path, key_path) for the server certificate, making the authority and the
    certificate first when there is no usable pair (see the module docstring). `dns_names` /
    `ip_addresses` are the names the PC answers on (its name, its .local names, its
    home-network address); localhost and the loopback addresses are always in. Raises
    TLSUnavailable with a plain sentence on ANY failure -- the caller serves plain HTTP."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    cert_p, key_p = cert_path(), key_path()
    if not can_make_certificates():
        if cert_p.is_file() and key_p.is_file():
            _secure.restrict_to_owner(key_p)
            return cert_p, key_p                   # made earlier; ssl can load it without us
        raise TLSUnavailable("HTTPS needs the 'cryptography' package to make its certificate "
                             "(pip install cryptography).")
    try:
        return _ensure(dns_names, ip_addresses, now)
    except OSError as e:
        raise TLSUnavailable("Moonglade couldn't save its HTTPS certificate in {} ({})."
                             .format(cert_p.parent.name, e.strerror or e)) from e
    except Exception as e:                              # noqa: BLE001 -- never stop a start
        raise TLSUnavailable("Moonglade couldn't make its HTTPS certificate ({}: {})."
                             .format(type(e).__name__, str(e)[:200])) from e


def fingerprint(path=None):
    """The SHA-256 fingerprint of the first certificate in a PEM file, as browsers and phones
    show it (AB:CD:...), or "" when there is no readable certificate. Defaults to the
    authority's -- the one a device installs and checks. Standard library only."""
    p = path or ca_cert_path()
    try:
        text = p.read_text(encoding="ascii")
        end = "-----END CERTIFICATE-----"
        der = ssl.PEM_cert_to_DER_cert(text[:text.index(end) + len(end)].strip())
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
