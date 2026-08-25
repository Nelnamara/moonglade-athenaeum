"""moonglade_bonjour.py -- optional mDNS / DNS-SD (Bonjour) LAN advertising for the gallery
server.

Registers an `_http._tcp` service plus a `<name>.local` host record via python-zeroconf, so a
phone, tablet, or Bonjour-aware browser can DISCOVER "Moonglade" on the network and tap it,
instead of the owner typing `http://<pc-name>.local:<port>`. The app also owns its advertised
name (`moonglade.local`) rather than borrowing the PC's.

REACHABILITY ONLY, NEVER TRUST. This changes nothing about authorization: the gallery's login
gate (`moonglade_gallery._is_authorized_request`) has no loopback bypass, so a device that
discovers `moonglade.local` still has to sign in. mDNS only makes the server easier to find.

EVERYTHING HERE IS FAIL-SOFT. `zeroconf` may be absent (it is an optional dependency), the
machine may have no LAN address, a registration may error -- none of that may stop the server.
The import is guarded and every public entry point is wrapped; the worst case is "no broadcast",
never "no gallery".
"""

from __future__ import annotations

import re
import socket

try:
    from zeroconf import ServiceInfo, Zeroconf
    _HAVE_ZEROCONF = True
except Exception:                       # noqa: BLE001 -- optional dependency, guarded on purpose
    _HAVE_ZEROCONF = False


def zeroconf_available():
    """Whether python-zeroconf imported. Exposed so the status route can explain a
    can't-broadcast state ('pip install zeroconf') rather than silently showing nothing."""
    return _HAVE_ZEROCONF


def lan_ip():
    """This machine's primary LAN IPv4 as a string, or None if there is no real LAN route.

    The UDP-connect trick: opening a datagram socket toward a public address makes the OS pick
    the default-route interface and bind a local address to it -- but no packet is ever sent and
    nothing has to be reachable, so it works offline and costs nothing. A loopback result
    (127.x, no real route) is treated as 'no LAN'."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:                   # noqa: BLE001
        return None
    finally:
        s.close()
    return ip if ip and not ip.startswith("127.") else None


def is_lan_bind(host):
    """True when binding `host` actually exposes the server to other devices: 0.0.0.0 / :: (all
    interfaces) or an explicit non-loopback address. A loopback-only bind reaches nothing
    off-box, so advertising it would announce a dead end -- the register guard skips it."""
    h = (host or "").strip()
    if h in ("0.0.0.0", "::", ""):
        return True
    return h not in ("127.0.0.1", "::1", "localhost")


def hostname_label(name):
    """A DNS-label-safe host stem from a display name: lowercase, runs of space/underscore -> a
    single hyphen, then drop anything outside [a-z0-9-]. 'Moonglade Athenaeum' ->
    'moonglade-athenaeum'. Falls back to 'moonglade' if nothing survives."""
    slug = re.sub(r"[^a-z0-9-]", "", re.sub(r"[\s_]+", "-", (name or "").strip().lower()))
    return slug.strip("-") or "moonglade"


class BonjourAdvertiser:
    """Holds one live mDNS registration so it can be torn down (goodbye packet) on shutdown or
    re-pointed live when the name changes. One per server process. Every method is fail-soft and
    idempotent; none raises."""

    def __init__(self):
        self._zc = None
        self._info = None
        self.active = False
        self.hostname = None            # e.g. "moonglade.local" (no trailing dot, for display)
        self.ip = None
        self.name = None                # the human-facing service name, e.g. "Moonglade"

    def start(self, name, port, scheme="http"):
        """Advertise `name` on the LAN as an `_http._tcp` (or `_https._tcp`) service plus a
        `<label>.local` host record pointing at this machine's LAN IPv4. Returns True on success,
        False (a no-op) if already active, zeroconf is missing, or there is no LAN address.
        Never raises."""
        if self.active or not _HAVE_ZEROCONF:
            return False
        ip = lan_ip()
        if not ip:
            return False
        try:
            label = hostname_label(name)
            server = label + ".local."
            stype = "_https._tcp.local." if scheme == "https" else "_http._tcp.local."
            instance = (str(name).strip() or label)
            info = ServiceInfo(
                stype,
                "{}.{}".format(instance, stype),
                addresses=[socket.inet_aton(ip)],
                port=int(port),
                # Minimal TXT, mirroring the fixed `X-Moonglade: 1` header's disclosure
                # philosophy (moonglade_gallery.py): identity + the entry path only, never the
                # version or the library path -- this is a public-repo app on a shared LAN.
                properties={"app": "moonglade", "path": "/"},
                server=server,
            )
            zc = Zeroconf()
            zc.register_service(info)
            self._zc, self._info = zc, info
            self.active = True
            self.hostname = label + ".local"
            self.ip = ip
            self.name = instance
            return True
        except Exception:               # noqa: BLE001 -- advertising must never break serving
            self.stop()
            return False

    def stop(self):
        """Unregister the service (sends the mDNS goodbye so devices drop it promptly) and close
        the Zeroconf socket. Idempotent; never raises."""
        zc, info = self._zc, self._info
        self._zc = self._info = None
        self.active = False
        self.hostname = self.ip = self.name = None
        if zc is not None:
            try:
                if info is not None:
                    zc.unregister_service(info)
            except Exception:           # noqa: BLE001
                pass
            try:
                zc.close()
            except Exception:           # noqa: BLE001
                pass
