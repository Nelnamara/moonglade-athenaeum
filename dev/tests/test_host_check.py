"""The Host-header check (moonglade/hostcheck.py + gallery._refuse_unknown_host): the
DNS-rebinding guard. A page on another site that points its own name at this PC reaches the
server under THAT name, so a Host the machine does not own is refused with 421 before any
route runs -- the first-account form on a fresh install included. Every name a real device
uses (localhost, an IP literal such as a phone or the Mac at the PC's LAN address, the PC's
hostname and .local, the Bonjour name, a configured allowed_hosts entry) still passes."""
import socket

import pytest

from moonglade import backup as core
from moonglade import hostcheck as hc
from moonglade import settings as _settings
from moonglade.gallery import create_app


def _get(cli, host, path="/login", **kw):
    return cli.get(path, base_url="http://%s" % host, **kw)


# ---- the pure rule ----------------------------------------------------------------------------
@pytest.mark.parametrize("header,name", [
    ("localhost:5000", "localhost"), ("LOCALHOST", "localhost"), ("[::1]:5000", "::1"),
    ("192.168.1.20:5000", "192.168.1.20"), ("moonglade.local.", "moonglade.local"), ("", ""),
])
def test_host_name_parses(header, name):
    assert hc.host_name(header) == name


@pytest.mark.parametrize("header", ["[::1", "a b", "::1", "evil:abc", "x@y", "[::1]junk"])
def test_host_name_refuses_garbage(header):
    assert hc.host_name(header) is None
    assert hc.allowed(header) is False


@pytest.mark.parametrize("header", [
    "localhost", "localhost:5057", "127.0.0.1:5000", "[::1]:5000", "192.168.1.20:5000",
    "10.0.0.7", "app.localhost:5000", "",
])
def test_own_addresses_pass(header):
    assert hc.allowed(header) is True


@pytest.mark.parametrize("header", [
    "evil.example", "evil.example:5000", "rebind.attacker.test:5057", "localhost.evil.example",
    "127.0.0.1.nip.io:5000",
])
def test_foreign_names_refused(header):
    assert hc.allowed(header) is False


def test_machine_hostname_and_dot_local_pass(monkeypatch):
    monkeypatch.setattr(hc.socket, "gethostname", lambda: "DESKTOP-ABC")
    assert hc.allowed("desktop-abc:5000")
    assert hc.allowed("DESKTOP-ABC.local:5000")
    assert not hc.allowed("desktop-abcd.local")


def test_extra_names_pass_only_when_listed():
    assert hc.allowed("pc.lan:5000", ["PC.lan"])
    assert not hc.allowed("pc.lan:5000", [])


# ---- the server -------------------------------------------------------------------------------
def test_rebinding_name_cannot_reach_first_account_form(tmp_path):
    """Fresh install, no accounts, a request from 127.0.0.1 (the owner's own browser) carrying a
    foreign Host: every road is refused before routing, and no account appears."""
    assert core.list_web_users() == []
    cli = create_app(tmp_path).test_client()
    for path in ("/login", "/", "/branding/x.png", "/api/ping"):
        r = _get(cli, "evil.example:5000", path)
        assert r.status_code == 421, path
    r = cli.post("/api/login", base_url="http://evil.example:5000",
                 json={"username": "mallory", "password": "pw123456",
                       "confirm": "pw123456", "mode": "create"})
    assert r.status_code == 421
    assert "own names" in r.get_json()["error"]
    assert core.list_web_users() == []


@pytest.mark.parametrize("host", ["localhost:5000", "127.0.0.1:5000", "[::1]:5000",
                                  "192.168.1.20:5000", "moonglade.local:5000"])
def test_real_devices_still_reach_the_server(tmp_path, host):
    cli = create_app(tmp_path).test_client()
    r = _get(cli, host, environ_overrides={"REMOTE_ADDR": "192.168.1.30"})
    assert r.status_code == 200, host


def test_hostname_and_configured_host_reach_the_server(tmp_path, monkeypatch):
    monkeypatch.setattr(hc.socket, "gethostname", lambda: "Gaming-PC")
    cli = create_app(tmp_path).test_client()
    assert _get(cli, "gaming-pc.local:5000").status_code == 200
    assert _get(cli, "gaming-pc:5000").status_code == 200
    assert _get(cli, "pc.lan:5000").status_code == 421
    _settings.set_values(**{_settings.ALLOWED_HOSTS: ["pc.lan"]})
    assert _get(cli, "pc.lan:5000").status_code == 200


def test_bonjour_name_reaches_the_server(tmp_path):
    _settings.set_values(**{_settings.BONJOUR: {"enabled": True, "name": "The Library"}})
    cli = create_app(tmp_path).test_client()
    assert _get(cli, "the-library.local:5000").status_code == 200


def test_the_guard_runs_before_the_front_door(tmp_path):
    """Registered first, so a foreign name gets 421, never the login redirect (which would
    hand the rebinding page a page of ours)."""
    app = create_app(tmp_path)
    hooks = app.before_request_funcs[None]
    names = [f.__name__ for f in hooks]
    assert names.index("_refuse_unknown_host") < names.index("_enforce_front_door")
