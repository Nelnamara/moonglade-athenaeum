"""Remember this device (spec scopes/SPEC_2026-11-23_remember-device-and-pairing.md §§1-3, §8).

A ticked sign-in is a browser record in local/remembered_devices.json (moonglade.web_devices): it
lives 90 days, its cookie expires with it, and it ends the moment its record goes -- Revoke, Log
Out, sign out everywhere, a password change, the account's removal, or the record's own expiry or
an older epoch. An unticked sign-in is exactly what it was. A session from another device lists
and revokes only its own account's devices.
"""
import json
import re
import time
from datetime import datetime, timedelta, timezone

from moonglade import paths as moonglade_paths
from moonglade import web_accounts as web_accounts_mod
from moonglade import web_devices
from moonglade.gallery import create_app
from moonglade.web_policy import REMEMBER_DEVICE_LIFETIME_S
from tests.conftest import extract_login_csrf, session_csrf, with_csrf

LAN = "203.0.113.5"
ALICE = ("alice", "a-real-test-password-1")
BOB = ("bob", "a-real-test-password-2")
SAFARI = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
          "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")


def _sign_in(app, who=ALICE, remember=False, addr="127.0.0.1"):
    """A real sign-in. The account is made only the first time: re-saving it would bump its
    epoch and end every device the test is holding."""
    if web_accounts_mod.get_web_user_session_epoch(who[0]) is None:
        web_accounts_mod.add_or_update_web_user(*who)
    cli = app.test_client()
    env = {"REMOTE_ADDR": addr}
    csrf = extract_login_csrf(cli.get("/login", environ_overrides=env).get_data(as_text=True))
    body = {"username": who[0], "password": who[1], "csrf": csrf}
    if remember:
        body["remember"] = True
    d = cli.post("/api/login", json=body, environ_overrides=env,
                 headers={"User-Agent": SAFARI}).get_json()
    assert d and d.get("ok"), d
    if remember:
        assert d.get("remembered") is True
    return cli


def _ok(cli, addr="127.0.0.1"):
    return cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": addr}).status_code == 200


def _dev(cli):
    with cli.session_transaction() as s:
        return s.get("dev")


def _boot(cli):
    html = cli.get("/login").get_data(as_text=True)
    m = re.search(r"window\.MG_BOOT = (\{.*?\});</script>", html)
    assert m, "no boot payload on /login"
    return json.loads(m.group(1))


def _devices_file(tmp_path):
    return tmp_path / moonglade_paths.REMEMBERED_DEVICES_NAME


def test_remember_makes_a_record_and_a_90_day_cookie(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    cli = _sign_in(app, remember=True)
    recs = web_devices.list_for("alice")
    assert len(recs) == 1 and recs[0]["kind"] == "browser"
    assert recs[0]["label"] == "iPhone · Safari"
    assert recs[0]["id"] == _dev(cli)
    assert recs[0]["expires"] - recs[0]["created"] == REMEMBER_DEVICE_LIFETIME_S
    with cli.session_transaction() as s:
        assert recs[0]["sid"] == s["sid"]
    cookie = cli.get_cookie("session")
    assert cookie.expires > datetime.now(timezone.utc) + timedelta(days=85)
    assert _ok(cli)
    # still past 30 idle days: the signature is read up to 90 days (R2)
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 45 * 86400)
    assert _ok(cli)


def test_an_unticked_sign_in_is_unchanged(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    cli = _sign_in(app)
    assert web_devices.list_all() == [] and _dev(cli) is None
    cookie = cli.get_cookie("session")
    assert cookie.expires < datetime.now(timezone.utc) + timedelta(days=31)
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 31 * 86400)
    assert not _ok(cli)


def test_revoke_ends_the_session_on_its_next_request_and_login_says_so_once(tmp_path):
    app = create_app(tmp_path)
    phone = _sign_in(app, remember=True)
    desk = _sign_in(app)
    dev = _dev(phone)
    listed = desk.get("/api/devices").get_json()
    assert listed["users"][0]["devices"][0]["id"] == dev
    assert listed["users"][0]["devices"][0]["this_device"] is False
    assert "sid" not in json.dumps(listed) and "token" not in json.dumps(listed)
    assert desk.post("/api/devices/revoke", json=with_csrf(desk, {"id": dev})).get_json() == {"ok": True}
    assert web_devices.list_all() == []
    assert phone.get("/api/jobs").status_code == 401
    assert _boot(phone)["ended"] is True
    assert _boot(phone)["ended"] is False          # one-shot
    assert _ok(desk)
    assert _boot(app.test_client())["ended"] is False


def test_log_out_deletes_the_record(tmp_path):
    app = create_app(tmp_path)
    cli = _sign_in(app, remember=True)
    sid = cli.get_cookie("session").value
    assert cli.post("/api/logout", json={"csrf": session_csrf(cli)}).get_json() == {"ok": True}
    assert web_devices.list_all() == []
    copy = app.test_client()
    copy.set_cookie("session", sid)
    assert copy.get("/api/jobs").status_code == 401


def test_everywhere_password_change_and_removal_end_it(tmp_path):
    app = create_app(tmp_path)
    # sign out everywhere, from another device
    phone, desk = _sign_in(app, remember=True), _sign_in(app)
    desk.post("/api/logout", json={"csrf": session_csrf(desk), "scope": "everywhere"})
    assert web_devices.list_all() == [] and phone.get("/api/jobs").status_code == 401
    # a password change from another device ends it
    phone, desk = _sign_in(app, remember=True), _sign_in(app)
    r = desk.post("/api/users/password", json=with_csrf(desk, {
        "new_password": "another-real-password-9"}))
    assert r.get_json()["ok"] is True
    assert web_devices.list_all() == [] and phone.get("/api/jobs").status_code == 401
    # removal ends bob's
    bob = _sign_in(app, BOB, remember=True)
    assert web_devices.list_for("bob")
    desk = _sign_in(app, ("alice", "another-real-password-9"))
    assert desk.post("/api/users/remove", json=with_csrf(desk, {"username": "bob"})).get_json()["ok"]
    assert web_devices.list_for("bob") == [] and bob.get("/api/jobs").status_code == 401


def test_your_own_password_change_keeps_this_device(tmp_path):
    app = create_app(tmp_path)
    phone = _sign_in(app, remember=True)
    other = _sign_in(app, remember=True)
    r = phone.post("/api/users/password", json=with_csrf(phone, {
        "new_password": "another-real-password-9"}))
    assert r.get_json()["still_signed_in_here"] is True
    assert [d["id"] for d in web_devices.list_all()] == [_dev(phone)]
    assert _ok(phone) and other.get("/api/jobs").status_code == 401
    assert web_devices.get(_dev(phone))["epoch"] == web_accounts_mod.get_web_user_session_epoch("alice")


def test_an_expired_record_is_refused(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    cli = _sign_in(app, remember=True)
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + REMEMBER_DEVICE_LIFETIME_S + 60)
    assert cli.get("/api/jobs").status_code == 401


def test_a_stale_epoch_record_is_refused(tmp_path):
    app = create_app(tmp_path)
    cli = _sign_in(app, remember=True)
    p = _devices_file(tmp_path)
    doc = json.loads(p.read_text(encoding="utf-8"))
    for rec in doc["devices"].values():
        rec["epoch"] -= 1                  # the session's own epoch still matches the account
    p.write_text(json.dumps(doc), encoding="utf-8")
    assert cli.get("/api/jobs").status_code == 401


def test_an_unreadable_devices_file_is_a_503_never_a_sign_out(tmp_path):
    app = create_app(tmp_path)
    cli = _sign_in(app, remember=True)
    p = _devices_file(tmp_path)
    good = p.read_text(encoding="utf-8")
    p.write_text("{not json", encoding="utf-8")
    assert cli.get("/api/jobs").status_code == 503
    assert p.read_text(encoding="utf-8") == "{not json"      # never overwritten as empty
    p.write_text(good, encoding="utf-8")
    assert _ok(cli)


def test_a_lan_session_cannot_list_or_revoke_another_accounts_device(tmp_path):
    app = create_app(tmp_path)
    alice = _sign_in(app, remember=True)
    bob = _sign_in(app, BOB, addr=LAN)
    env = {"REMOTE_ADDR": LAN}
    seen = bob.get("/api/devices", environ_overrides=env).get_json()
    assert [u["user"] for u in seen["users"]] == ["bob"]
    r = bob.post("/api/devices/revoke", json=with_csrf(bob, {"id": _dev(alice)}),
                 environ_overrides=env)
    assert r.status_code == 403 and len(web_devices.list_all()) == 1
    # this PC sees every account, and may revoke another's
    local = _sign_in(app, BOB)
    assert {u["user"] for u in local.get("/api/devices").get_json()["users"]} == {"alice", "bob"}
    assert local.post("/api/devices/revoke",
                      json=with_csrf(local, {"id": _dev(alice)})).get_json() == {"ok": True}


def test_revoking_your_own_current_device_is_refused(tmp_path):
    app = create_app(tmp_path)
    cli = _sign_in(app, remember=True)
    r = cli.post("/api/devices/revoke", json=with_csrf(cli, {"id": _dev(cli)}))
    assert r.status_code == 400 and r.get_json() == {"error": "Use Log out on this device."}
    assert len(web_devices.list_all()) == 1 and _ok(cli)


def test_no_address_in_the_file(tmp_path):
    app = create_app(tmp_path)
    _sign_in(app, remember=True)
    _sign_in(app, BOB, remember=True, addr=LAN)
    text = _devices_file(tmp_path).read_text(encoding="utf-8")
    assert "127.0.0.1" not in text and LAN not in text
    for rec in json.loads(text)["devices"].values():
        assert set(rec) <= {"id", "user", "kind", "label", "created", "last_seen", "expires",
                            "epoch", "sid", "token_hash"}


def test_this_pc_signs_out_another_account_everywhere_and_stays_signed_in(tmp_path):
    app = create_app(tmp_path)
    bob = _sign_in(app, BOB, remember=True)
    lan = _sign_in(app, addr=LAN)
    r = lan.post("/api/logout", json={"csrf": session_csrf(lan), "scope": "everywhere",
                                      "username": "bob"}, environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code == 403 and _ok(bob) and _ok(lan, LAN)
    local = _sign_in(app)
    r = local.post("/api/logout", json={"csrf": session_csrf(local), "scope": "everywhere",
                                        "username": "bob"})
    assert r.get_json() == {"ok": True}
    assert web_devices.list_for("bob") == [] and bob.get("/api/jobs").status_code == 401
    assert _ok(local) and _ok(lan, LAN)
