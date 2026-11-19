"""moonglade/hostcheck.py -- the Host-header check (the DNS-rebinding guard).

THE ATTACK. A web page on some other site can point its own name at 127.0.0.1 (or the PC's
LAN address) a moment after the page loads -- "DNS rebinding". The browser then treats this
server as the same origin as that page and lets its scripts read the answers. Nothing else
here looks at the name the browser asked for, so on a fresh install with no account yet such
a page could reach /login's first-account form from the owner's own browser.

THE CURE is the one every local server uses: answer only to names that are this machine's
own. A rebinding page always reaches us under ITS name (the browser sends that name in the
Host header and cannot be made to send another), so a name we do not know is refused before
any route runs.

What counts as ours (`allowed`):
  * any IP literal -- 127.0.0.1, [::1], the PC's LAN address a phone or the Mac types, a VPN
    address. A page whose origin is an IP literal cannot be a rebinding page: the attack needs
    a NAME the attacker controls, so every address the machine owns is safe without listing
    them (and a DHCP change can never lock a phone out);
  * `localhost` and any `*.localhost` (browsers resolve those to loopback themselves);
  * this PC's own hostname, bare and as `<hostname>.local`;
  * the Bonjour name the server advertises (`<label>.local`, from the Control Panel's name);
  * every name in settings.json's `allowed_hosts` list (a router's `pc.lan`, a reverse
    proxy's name) -- the configured-host escape hatch.
A request with no Host header at all is let through: browsers always send one, so it cannot
be a page's request (an HTTP/1.0 script, a health probe).

Pure functions plus one cached name set; nothing here opens a socket or does a DNS lookup
(`socket.getfqdn()` would, so it is not used).
"""
from __future__ import annotations

import ipaddress
import socket

REFUSED_STATUS = 421
REFUSED_WORDS = ("This Moonglade answers only to this computer's own names and addresses. "
                 "Open it by its address (for example http://localhost:<port>/ or the PC's "
                 "LAN address), or add the name to allowed_hosts in local\\settings.json.")


def host_name(header):
    """The name part of a Host header, lowercased, port and trailing dot removed; '' for an
    absent header, None for one that does not parse. '[::1]:5000' -> '::1'."""
    h = str(header or "").strip()
    if not h:
        return ""
    if h.startswith("["):
        end = h.find("]")
        if end < 0:
            return None
        name, rest = h[1:end], h[end + 1:]
        if rest and not (rest.startswith(":") and rest[1:].isdigit()):
            return None
    else:
        name, sep, port = h.rpartition(":")
        if not sep:
            name = h
        elif not port.isdigit() or ":" in name:
            # a bare IPv6 literal without brackets is not a valid Host header
            return None
    name = name.strip().rstrip(".").lower()
    if not name or any(c.isspace() or c in "/\\@?#" for c in name):
        return None
    return name


def is_ip_literal(name):
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


def machine_names():
    """This PC's own names: its hostname bare and with `.local`. No lookup is made."""
    out = set()
    try:
        hn = (socket.gethostname() or "").strip().rstrip(".").lower()
    except Exception:                    # noqa: BLE001 -- a name we cannot read is a name we skip
        hn = ""
    if hn:
        out.add(hn)
        stem = hn.split(".", 1)[0]
        out.add(stem)
        out.add(stem + ".local")
    return out


def allowed(header, extra_names=()):
    """Is a request carrying this Host header one we answer? See the module docstring."""
    name = host_name(header)
    if name == "":
        return True
    if name is None:
        return False
    if is_ip_literal(name):
        return True
    if name == "localhost" or name.endswith(".localhost"):
        return True
    if name in machine_names():
        return True
    return name in {str(n).strip().rstrip(".").lower() for n in extra_names if n}
