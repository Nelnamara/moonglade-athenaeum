"""The TV's pairing and its bearer token (Apple TV plan §S1; spec SPEC_2026-11-23 §4, §8 R1 and
R3-R9), and HEAD never taking a write branch (R1).

A TV asks for a code (POST /api/pair/start), a signed-in person approves it (POST /api/pair/approve),
and the TV's next poll (GET /api/pair/poll) is the one handout of its token -- the moment its
record is made. The token reaches a named list of view routes and POST /api/rate/<id>, nothing
else: never a LOCALHOST route (even from 127.0.0.1), never a cookie, never HEAD.
"""
import hashlib
import secrets
import time

import pytest

from moonglade import settings as settings_mod
from moonglade import web_devices
from moonglade.gallery import create_app
from moonglade.web_tiers import LOGIN, route_tier, tier
from tests.conftest import login_test_client, with_csrf

LAN = "203.0.113.5"
TV_ADDR = "203.0.113.9"
HTTPS = "https://localhost"


def _tv(app, addr=TV_ADDR):
    """A TV on the home network, over HTTPS."""
    cli = app.test_client()
    env = {"REMOTE_ADDR": addr}

    def call(method, path, token=None, **kw):
        headers = dict(kw.pop("headers", {}) or {})
        if token:
            headers["Authorization"] = "Bearer " + token
        return cli.open(path, method=method, base_url=HTTPS, environ_overrides=env,
                        headers=headers, **kw)
    return call


@pytest.fixture()
def app(tmp_path):
    return create_app(tmp_path)


@pytest.fixture()
def owner(app):
    return login_test_client(app, username="alice", password="a-real-test-password-1")


def _pair(app, owner, tv=None, label="Living room"):
    tv = tv or _tv(app)
    start = tv("POST", "/api/pair/start").get_json()
    assert set(start) == {"pair_id", "code", "expires_in"} and start["expires_in"] == 600
    r = owner.post("/api/pair/approve",
                   json=with_csrf(owner, {"code": start["code"].lower(), "label": label}))
    assert r.get_json() == {"ok": True, "label": label}, r.get_json()
    got = tv("GET", "/api/pair/poll?pair_id=" + start["pair_id"]).get_json()
    assert got["status"] == "approved" and got["token"]
    return tv, got["token"], start


def test_the_happy_path_and_the_token_is_handed_out_once(app, owner):
    tv = _tv(app)
    start = tv("POST", "/api/pair/start").get_json()
    code = start["code"]
    assert len(code) == 6 and set(code) <= set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
    poll = "/api/pair/poll?pair_id=" + start["pair_id"]
    assert tv("GET", poll).get_json() == {"status": "waiting"}
    owner.post("/api/pair/approve", json=with_csrf(owner, {"code": code.lower(), "label": "Den"}))
    assert web_devices.list_all() == [], "the record is made at the handout, not at approve (R8)"
    got = tv("GET", poll).get_json()
    assert got["status"] == "approved"
    assert tv("GET", poll).get_json() == {"status": "expired"}
    recs = web_devices.list_all()
    assert len(recs) == 1 and recs[0]["kind"] == "tv" and recs[0]["label"] == "Den"
    assert recs[0]["token_hash"] == hashlib.sha256(got["token"].encode()).hexdigest()
    assert tv("GET", "/api/gallery-images", token=got["token"]).status_code == 200
    devices = owner.get("/api/devices").get_json()["users"][0]["devices"]
    assert [(d["kind"], d["label"]) for d in devices] == [("tv", "Den")]
    # an approve is single-use
    again = owner.post("/api/pair/approve", json=with_csrf(owner, {"code": code}))
    assert again.status_code == 400


def test_an_expired_code_is_one_generic_refusal(app, owner, monkeypatch):
    tv = _tv(app)
    start = tv("POST", "/api/pair/start").get_json()
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 601)
    r = owner.post("/api/pair/approve", json=with_csrf(owner, {"code": start["code"]}))
    unknown = owner.post("/api/pair/approve", json=with_csrf(owner, {"code": "ZZZZZZ"}))
    assert r.status_code == unknown.status_code == 400
    assert r.get_json() == unknown.get_json()
    assert tv("GET", "/api/pair/poll?pair_id=" + start["pair_id"]).get_json() == {"status": "expired"}


def test_a_poll_from_another_address_learns_nothing(app, owner):
    tv = _tv(app)
    start = tv("POST", "/api/pair/start").get_json()
    owner.post("/api/pair/approve", json=with_csrf(owner, {"code": start["code"]}))
    other = _tv(app, addr="203.0.113.77")
    assert other("GET", "/api/pair/poll?pair_id=" + start["pair_id"]).get_json() == {"status": "expired"}
    assert tv("GET", "/api/pair/poll?pair_id=" + start["pair_id"]).get_json()["status"] == "approved"


def test_a_head_poll_hands_out_nothing(app, owner):
    tv = _tv(app)
    start = tv("POST", "/api/pair/start").get_json()
    owner.post("/api/pair/approve", json=with_csrf(owner, {"code": start["code"]}))
    poll = "/api/pair/poll?pair_id=" + start["pair_id"]
    r = tv("HEAD", poll)
    assert r.status_code == 200 and web_devices.list_all() == []
    got = tv("GET", poll).get_json()
    assert got["status"] == "approved" and got["token"]


def test_an_unreadable_config_is_a_503_for_a_bearer_never_a_401(app, owner):
    from moonglade import backup as core
    tv, token, _ = _pair(app, owner)
    p = core._config_path()
    good = p.read_bytes()
    p.write_text("{not json", encoding="utf-8")
    try:
        r = tv("GET", "/api/ping", token=token)
        assert r.status_code == 503 and r.is_json
    finally:
        p.write_bytes(good)
    assert tv("GET", "/api/ping", token=token).status_code == 200


def test_a_revoked_token_is_refused(app, owner):
    tv, token, _ = _pair(app, owner)
    assert tv("GET", "/api/collections", token=token).status_code == 200
    dev = web_devices.list_all()[0]["id"]
    assert owner.post("/api/devices/revoke", json=with_csrf(owner, {"id": dev})).get_json() == {"ok": True}
    r = tv("GET", "/api/collections", token=token)
    assert r.status_code == 401 and r.get_json() == {"error": "authentication required"}
    # and on an asset path too: a 401, never a redirect to the sign-in page
    assert tv("GET", "/thumbs/1.jpg", token=token).status_code == 401


def test_sign_out_everywhere_ends_the_tv_too(app, owner):
    tv, token, _ = _pair(app, owner)
    owner.post("/api/logout", json=with_csrf(owner, {"scope": "everywhere"}))
    assert tv("GET", "/api/ping", token=token).status_code == 401


def test_localhost_refuses_a_bearer_even_from_127_0_0_1(tmp_path, monkeypatch):
    """The gate's own `level == LOCALHOST` clause, alone: a LOCALHOST GET route that IS on the
    allowlist (widened for this test) still refuses a bearer from this PC's loopback, while a
    LOGIN twin on the same widened list lets it through -- so nothing else is doing the refusing."""
    from flask import jsonify
    from moonglade import routes_gate
    from moonglade.web_tiers import LOCALHOST, tier
    app = create_app(tmp_path)

    @app.route("/api/probe-localhost-get")
    @tier(LOCALHOST)
    def probe_localhost_get():
        return jsonify({"ok": True})

    @app.route("/api/probe-login-get")
    @tier(LOGIN)
    def probe_login_get():
        return jsonify({"ok": True})

    monkeypatch.setattr(routes_gate, "BEARER_READS", routes_gate.BEARER_READS | {
        "probe_localhost_get", "probe_login_get"})
    owner = login_test_client(app, username="alice", password="a-real-test-password-1")
    _tv_unused, token, _ = _pair(app, owner)
    here = _tv(app, addr="127.0.0.1")
    assert owner.get("/api/probe-localhost-get").status_code == 200       # the route works
    assert here("GET", "/api/probe-login-get", token=token).status_code == 200
    r = here("GET", "/api/probe-localhost-get", token=token)
    assert r.status_code == 401 and r.get_json() == {"error": "authentication required"}
    r = here("POST", "/api/delete-tasks", token=token, json={"confirm": "DELETE"})
    assert r.status_code == 401


def test_the_rate_limits(app, owner):
    tv = _tv(app)
    for _ in range(5):
        assert tv("POST", "/api/pair/start").status_code == 200
    assert tv("POST", "/api/pair/start").status_code == 429
    good = _tv(app, addr="203.0.113.10")("POST", "/api/pair/start").get_json()["code"]
    for _ in range(5):
        assert owner.post("/api/pair/approve",
                          json=with_csrf(owner, {"code": "ZZZZZZ"})).status_code == 400
    r = owner.post("/api/pair/approve", json=with_csrf(owner, {"code": good}))
    assert r.status_code == 429, "past the wrong-code limit even the right code is refused"


def test_a_bearer_cannot_post_anything_but_rate(app, owner):
    tv, token, _ = _pair(app, owner)
    for path in ("/api/collection", "/api/generate", "/api/pair/approve",
                 "/api/devices/revoke", "/api/jobs"):
        assert tv("POST", path, token=token, json={}).status_code == 401, path
    # Log Out is public (a dead cookie sheds itself there); for a bearer it does nothing at all
    assert tv("POST", "/api/logout", token=token, json={"scope": "everywhere"}).status_code == 200
    assert len(web_devices.list_all()) == 1
    assert tv("GET", "/api/ping", token=token).status_code == 200
    r = tv("POST", "/api/rate/123", token=token, json={"rating": 4})
    assert r.status_code == 200 and r.get_json() == {"ok": True, "rating": 4}


def test_a_bearer_get_works_on_its_list_only_and_never_head(app, owner):
    tv, token, _ = _pair(app, owner)
    for path in ("/api/gallery-images", "/api/collections/detail", "/api/achievements",
                 "/api/health", "/api/ping"):
        assert tv("GET", path, token=token).status_code == 200, path
    for path in ("/api/inbox", "/api/devices", "/api/account", "/api/jobs", "/",
                 "/api/achievements?mark=1"):
        assert tv("GET", path, token=token).status_code == 401, path
    assert tv("HEAD", "/api/gallery-images", token=token).status_code == 401


def test_a_bearer_never_reads_or_gets_a_cookie(tmp_path, monkeypatch):
    """The handler below WRITES the session, which Flask's stock interface would answer with a
    Set-Cookie; the bearer's never does (should_set_cookie / save_session, review R4)."""
    from flask import jsonify, session
    from moonglade import routes_gate
    app = create_app(tmp_path)

    @app.route("/api/probe-session-write")
    @tier(LOGIN)
    def probe_session_write():
        session["probe"] = secrets.token_hex(4)
        session.setdefault("csrf", secrets.token_hex(16))
        return jsonify({"ok": True})

    monkeypatch.setattr(routes_gate, "BEARER_READS",
                        routes_gate.BEARER_READS | {"probe_session_write"})
    owner = login_test_client(app, username="alice", password="a-real-test-password-1")
    assert "Set-Cookie" in owner.get("/api/probe-session-write").headers   # a cookie caller: yes
    tv, token, _ = _pair(app, owner)
    r = tv("GET", "/api/probe-session-write", token=token)
    assert r.status_code == 200 and "Set-Cookie" not in r.headers
    r = tv("GET", "/api/gallery-images", token=token)
    assert r.status_code == 200 and "Set-Cookie" not in r.headers
    # an Authorization header means bearer-only: the owner's own good cookie does not count
    r = owner.get("/api/jobs", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401 and "Set-Cookie" not in r.headers
    assert owner.get("/api/jobs").status_code == 200


def test_another_device_pairs_and_calls_over_https_only(app, owner):
    tv, token, _ = _pair(app, owner)
    plain = app.test_client()
    env = {"REMOTE_ADDR": TV_ADDR}
    assert plain.post("/api/pair/start", environ_overrides=env).status_code == 403
    r = plain.get("/api/gallery-images", environ_overrides=env,
                  headers={"Authorization": "Bearer " + token})
    assert r.status_code == 403 and "Location" not in r.headers


def test_a_cookie_post_from_a_foreign_origin_is_still_refused(app, owner):
    """The rate route takes no CSRF token on either path: the bearer's token is not ambient, and
    a cookie caller is held by the front door's cross-origin check. A bearer POST with no Origin
    passes; a cookie POST from another origin does not."""
    from moonglade.web_policy import CROSS_ORIGIN_REFUSED
    tv, token, _ = _pair(app, owner)
    assert tv("POST", "/api/rate/123", token=token, json={"rating": 2}).status_code == 200
    r = owner.post("/api/rate/123", json={"rating": 5}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403 and r.get_json() == {"error": CROSS_ORIGIN_REFUSED}
    r = owner.post("/api/rate/123", json={"rating": 5},
                   headers={"Origin": "http://localhost:5757"}, base_url="http://localhost:5057")
    assert r.status_code == 403


# ---------------------------------------------------------------------------------------------
# R1: HEAD is the GET it stands for, and never takes a write branch
# ---------------------------------------------------------------------------------------------

def _tree(root):
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def test_head_never_writes_on_any_get_and_post_route(tmp_path, app):
    cli = login_test_client(app)
    rules = sorted((r for r in app.url_map.iter_rules() if {"GET", "POST"} <= set(r.methods)),
                   key=lambda r: r.rule)
    assert any(r.rule == "/api/library-path" for r in rules) and len(rules) >= 5
    elsewhere = tmp_path / "head-made-this"
    body = with_csrf(cli, {
        "path": str(elsewhere), "create": True,                       # library path
        "anim": "pulse", "mark": "logo",                              # branding
        "set": {"head.probe": 1},                                     # account prefs
        "task_id": "1", "label": "probe",                             # presets
        "snippets": ["probe"], "name": "probe", "query": "?q=probe",  # snippets, saved views
        "enabled": True, "time": "03:00", "action": "organize"})      # schedule
    env = {"REMOTE_ADDR": LAN}
    for rule in rules:
        view = app.view_functions[rule.endpoint]
        assert route_tier(view, "HEAD") == route_tier(view, "GET"), rule.rule
        cli.get(rule.rule, environ_overrides=env)                     # the GET's own side effects
        before = _tree(tmp_path)
        r = cli.open(rule.rule, method="HEAD", json=body, environ_overrides=env)
        assert r.status_code < 500, (rule.rule, r.status_code)
        assert _tree(tmp_path) == before, "HEAD %s changed files" % rule.rule
    assert not elsewhere.exists()


def test_head_cannot_set_the_library_path_from_another_device(tmp_path, app):
    cli = login_test_client(app)
    target = tmp_path / "another-library"
    body = with_csrf(cli, {"path": str(target), "create": True})
    view = app.view_functions["api_library_path"]
    assert route_tier(view, "HEAD") == LOGIN
    before = settings_mod.library_dir()
    r = cli.open("/api/library-path", method="HEAD", json=body,
                 environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code == 200
    assert settings_mod.library_dir() == before and not target.exists()
    # the same body by POST from another device is the LOCALHOST refusal...
    assert cli.post("/api/library-path", json=body,
                    environ_overrides={"REMOTE_ADDR": LAN}).status_code == 403
    # ...and from this PC it really writes, so the HEAD above proved something
    assert cli.post("/api/library-path", json=body).get_json()["ok"] is True
    assert target.exists()
