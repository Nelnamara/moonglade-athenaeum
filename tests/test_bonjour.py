"""Unit tests for moonglade_bonjour -- the optional mDNS/Bonjour LAN advertiser.

The pure helpers are tested directly; the advertiser is tested with zeroconf mocked out (so no
real multicast, no network flakiness), covering both the fail-soft no-ops and the happy path's
ServiceInfo shape. The one live-network property -- that a phone actually sees moonglade.local --
is the owner's real-device pass, not a unit test.
"""

import moonglade_bonjour as mb


def test_is_lan_bind():
    for h in ("0.0.0.0", "::", "", "192.168.1.5", "10.0.0.2"):
        assert mb.is_lan_bind(h) is True, h
    for h in ("127.0.0.1", "::1", "localhost"):
        assert mb.is_lan_bind(h) is False, h


def test_hostname_label_is_dns_safe():
    assert mb.hostname_label("Moonglade") == "moonglade"
    assert mb.hostname_label("Moonglade Athenaeum") == "moonglade-athenaeum"
    assert mb.hostname_label("The Library") == "the-library"
    assert mb.hostname_label("  !!!  ") == "moonglade"     # nothing survives -> fallback
    assert mb.hostname_label("") == "moonglade"


def test_lan_ip_is_none_or_non_loopback():
    ip = mb.lan_ip()
    assert ip is None or (isinstance(ip, str) and not ip.startswith("127."))


def test_start_is_a_no_op_without_zeroconf(monkeypatch):
    monkeypatch.setattr(mb, "_HAVE_ZEROCONF", False)
    adv = mb.BonjourAdvertiser()
    assert adv.start("Moonglade", 5000) is False
    assert adv.active is False
    adv.stop()                                            # idempotent, never raises


def test_start_is_a_no_op_without_a_lan_address(monkeypatch):
    monkeypatch.setattr(mb, "_HAVE_ZEROCONF", True)
    monkeypatch.setattr(mb, "lan_ip", lambda: None)
    adv = mb.BonjourAdvertiser()
    assert adv.start("Moonglade", 5000) is False
    assert adv.active is False


class _FakeZC:
    def __init__(self):
        self.registered, self.unregistered, self.closed = [], [], 0

    def register_service(self, info):
        self.registered.append(info)

    def unregister_service(self, info):
        self.unregistered.append(info)

    def close(self):
        self.closed += 1


def _mock_zeroconf(monkeypatch, ip="192.168.1.42"):
    """Patch zeroconf out; return (captured_serviceinfo_kwargs, zc_instances)."""
    captured, instances = {}, []
    monkeypatch.setattr(mb, "_HAVE_ZEROCONF", True)
    monkeypatch.setattr(mb, "lan_ip", lambda: ip)

    def fake_info(stype, name, addresses=None, port=None, properties=None, server=None):
        captured.update(stype=stype, name=name, addresses=addresses,
                        port=port, properties=properties, server=server)
        return ("INFO", name)

    def fake_zc():
        z = _FakeZC()
        instances.append(z)
        return z

    monkeypatch.setattr(mb, "ServiceInfo", fake_info)
    monkeypatch.setattr(mb, "Zeroconf", fake_zc)
    return captured, instances


def test_advertiser_registers_the_right_service_and_goodbyes(monkeypatch):
    cap, zcs = _mock_zeroconf(monkeypatch)
    adv = mb.BonjourAdvertiser()

    assert adv.start("Moonglade Athenaeum", 5757, scheme="http") is True
    assert adv.active is True
    assert adv.hostname == "moonglade-athenaeum.local"
    assert adv.ip == "192.168.1.42"
    assert cap["stype"] == "_http._tcp.local."
    assert cap["server"] == "moonglade-athenaeum.local."
    assert cap["name"] == "Moonglade Athenaeum._http._tcp.local."
    assert cap["port"] == 5757
    # minimal TXT: identity + path, never the version or the library path
    assert "path" in cap["properties"] and "version" not in cap["properties"]
    assert len(zcs) == 1 and len(zcs[0].registered) == 1

    assert adv.start("Whatever", 1) is False              # no-op while already active
    assert len(zcs) == 1

    adv.stop()
    assert adv.active is False and adv.hostname is None
    assert len(zcs[0].unregistered) == 1 and zcs[0].closed == 1

    adv.stop()                                            # idempotent -- no second goodbye
    assert len(zcs[0].unregistered) == 1


def test_advertiser_https_uses_the_https_service_type(monkeypatch):
    cap, _ = _mock_zeroconf(monkeypatch, ip="10.0.0.9")
    adv = mb.BonjourAdvertiser()
    assert adv.start("Moonglade", 8443, scheme="https") is True
    assert cap["stype"] == "_https._tcp.local."
    assert cap["server"] == "moonglade.local."


def test_advertiser_survives_a_registration_error(monkeypatch):
    """A zeroconf blow-up during start must leave the advertiser cleanly inactive, not raise."""
    monkeypatch.setattr(mb, "_HAVE_ZEROCONF", True)
    monkeypatch.setattr(mb, "lan_ip", lambda: "192.168.0.5")
    monkeypatch.setattr(mb, "ServiceInfo", lambda *a, **k: "INFO")

    def boom():
        raise RuntimeError("multicast socket refused")

    monkeypatch.setattr(mb, "Zeroconf", boom)
    adv = mb.BonjourAdvertiser()
    assert adv.start("Moonglade", 5000) is False
    assert adv.active is False and adv.hostname is None


def test_main_wires_bonjour_gated_on_lan_bind_with_a_goodbye():
    """Source-level guard on main()'s wiring (main() blocks, so this is the established
    source-check pattern): register only when enabled AND a real LAN bind, after the socket is
    bound but before serve_forever blocks; unregister (goodbye) in the finally step 1 made run."""
    import pathlib
    src = pathlib.Path("moonglade_gallery.py").read_text(encoding="utf-8")
    assert '_srv["bonjour_enabled"] and moonglade_bonjour.is_lan_bind(args.host)' in src
    assert '_bonjour.start(_srv["bonjour_name"], args.port, scheme)' in src
    assert 'b = _SERVER_CONTROL.get("bonjour")' in src and "b.stop()" in src
    assert src.index("_bonjour.start(") < src.index("srv.serve_forever()"),         "register must happen before the serve loop blocks"
    assert src.index("srv = _make_server(args.host") < src.index("_bonjour = moonglade_bonjour"),         "register must happen after make_server has bound the socket"


def test_bonjour_status_and_settings_routes(tmp_path, monkeypatch):
    """Functional: the chip's two routes. GET status returns the live state; POST settings
    validates + writes config.json. (Tier enforcement -- status LOGIN, settings LOCALHOST -- is
    pinned by test_route_tiers' generated snapshot, not re-tested here.)"""
    from tests.conftest import login_client
    import moonglade_backup as core
    import moonglade_gallery as g
    # no live server in a unit test -> keep the route off the real zeroconf path
    monkeypatch.setitem(g._SERVER_CONTROL, "bonjour", None)
    monkeypatch.setitem(g._SERVER_CONTROL, "serving", None)
    cli = login_client(tmp_path)

    st = cli.get("/api/bonjour/status").get_json()
    assert st["enabled"] is False and st["broadcasting"] is False
    assert st["name"] == "Moonglade"
    assert isinstance(st["zeroconf_available"], bool)
    assert isinstance(st["reachable_urls"], list)

    r = cli.post("/api/bonjour/settings",
                 json={"enabled": True, "name": "The Library", "host": "0.0.0.0", "port": 5757}).get_json()
    assert r["ok"] is True and r["enabled"] is True and r["name"] == "The Library"
    assert r["host"] == "0.0.0.0" and r["port"] == 5757
    cfg = core._load_config() or {}
    assert cfg["BONJOUR_ENABLED"] is True and cfg["BONJOUR_NAME"] == "The Library"
    assert cfg["HOST"] == "0.0.0.0" and cfg["PORT"] == 5757

    for bad in ({"host": "8.8.8.8"}, {"port": 0}, {"port": 70000}, {"port": "nope"}, {"name": "   "}):
        assert "error" in cli.post("/api/bonjour/settings", json=bad).get_json(), bad
