"""Control Panel "Users" tab: list/add/remove gallery web-login accounts from the
browser instead of the CLI (see pixai_gallery.py's panel()/api_users_add()/
api_users_remove(), and pixai_gallery_backup.py's list_web_users/
add_or_update_web_user/remove_web_user). Companion to tests/test_web_auth.py's
bootstrap-form tests -- this file covers the OTHER half of "NO CLI first login
bullshit": managing accounts once you're already past the front door.
"""
import re

import pixai_gallery_backup as core
from pixai_gallery import create_app

from tests.conftest import login_client, login_test_client


def _panel_csrf(html):
    m = re.search(r'var CSRF = "([^"]+)";', html)
    assert m, "panel page did not embed a CSRF token"
    return m.group(1)


def test_users_tab_lists_existing_accounts(tmp_path):
    core.add_or_update_web_user("archivist", "pw-a")
    cli = login_client(tmp_path, username="tester", password="a-real-test-password-1")
    html = cli.get("/panel").get_data(as_text=True)
    assert 'data-tab="users"' in html          # the new tab button is present
    assert 'data-username="archivist"' in html
    assert 'data-username="tester"' in html
    # Only usernames -- never a password hash leaking into the rendered page.
    cfg = core._load_config()
    for u in cfg.get("AUTH_USERS", []):
        assert u["password_hash"] not in html


def test_add_user_end_to_end_real_post_real_hash(tmp_path):
    cli = login_client(tmp_path)
    html = cli.get("/panel").get_data(as_text=True)
    csrf = _panel_csrf(html)
    r = cli.post("/api/users/add", json={
        "username": "newperson", "password": "hunter2222", "confirm": "hunter2222",
        "csrf": csrf})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert core.verify_web_user("newperson", "hunter2222")
    # Never plaintext anywhere in config.json.
    cfg = core._load_config()
    raw = str(cfg)
    assert "hunter2222" not in raw
    row = next(u for u in cfg["AUTH_USERS"] if u["username"] == "newperson")
    assert row["password_hash"].startswith("scrypt:")


def test_add_user_rejects_duplicate_username(tmp_path):
    cli = login_client(tmp_path, username="tester", password="a-real-test-password-1")
    html = cli.get("/panel").get_data(as_text=True)
    csrf = _panel_csrf(html)
    r = cli.post("/api/users/add", json={
        "username": "tester", "password": "brand-new-pw", "confirm": "brand-new-pw",
        "csrf": csrf})
    assert r.status_code == 400
    assert "already exists" in r.get_json()["error"]
    # The original account's password must be untouched.
    assert core.verify_web_user("tester", "a-real-test-password-1")


def test_add_user_validates_password_length_and_confirm(tmp_path):
    cli = login_client(tmp_path)
    html = cli.get("/panel").get_data(as_text=True)
    csrf = _panel_csrf(html)
    r = cli.post("/api/users/add", json={
        "username": "short", "password": "ab", "confirm": "ab", "csrf": csrf})
    assert "at least 8 characters" in r.get_json()["error"]
    # The mismatch case needs a password that CLEARS the policy, or it would trip
    # the length check first and never reach the confirm comparison this asserts.
    r = cli.post("/api/users/add", json={
        "username": "mismatch", "password": "a-valid-password", "confirm": "different",
        "csrf": csrf})
    assert "do not match" in r.get_json()["error"]
    assert core.list_web_users() == [{"username": "tester"}]


def test_add_user_requires_valid_csrf(tmp_path):
    cli = login_client(tmp_path)
    cli.get("/panel")  # establishes the session; deliberately ignore its real csrf
    r = cli.post("/api/users/add", json={
        "username": "newperson", "password": "hunter2222", "confirm": "hunter2222",
        "csrf": "forged-token-not-in-session"})
    assert r.status_code == 400
    assert "expired" in r.get_json()["error"].lower()
    assert core.list_web_users() == [{"username": "tester"}]


def test_remove_user_end_to_end(tmp_path):
    core.add_or_update_web_user("doomed", "pw-doomed")
    cli = login_client(tmp_path, username="tester", password="a-real-test-password-1")
    html = cli.get("/panel").get_data(as_text=True)
    csrf = _panel_csrf(html)
    r = cli.post("/api/users/remove", json={"username": "doomed", "csrf": csrf})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert {u["username"] for u in core.list_web_users()} == {"tester"}


def test_remove_user_requires_valid_csrf(tmp_path):
    core.add_or_update_web_user("doomed", "pw-doomed")
    cli = login_client(tmp_path, username="tester", password="a-real-test-password-1")
    cli.get("/panel")
    r = cli.post("/api/users/remove", json={"username": "doomed", "csrf": "bogus"})
    assert r.status_code == 400
    assert "expired" in r.get_json()["error"].lower()
    # Nothing removed -- both accounts still present.
    assert {u["username"] for u in core.list_web_users()} == {"tester", "doomed"}


def test_remove_last_account_is_refused(tmp_path):
    cli = login_client(tmp_path, username="onlyone", password="a-real-test-password-1")
    html = cli.get("/panel").get_data(as_text=True)
    csrf = _panel_csrf(html)
    r = cli.post("/api/users/remove", json={"username": "onlyone", "csrf": csrf})
    assert r.status_code == 400
    assert "last remaining account" in r.get_json()["error"]
    assert core.list_web_users() == [{"username": "onlyone"}]


def test_remove_nonexistent_user_404s(tmp_path):
    cli = login_client(tmp_path)
    html = cli.get("/panel").get_data(as_text=True)
    csrf = _panel_csrf(html)
    r = cli.post("/api/users/remove", json={"username": "ghost", "csrf": csrf})
    assert r.status_code == 404


def test_concurrent_remove_of_two_different_accounts_cannot_empty_the_list(tmp_path, monkeypatch):
    """TOCTOU regression: /api/users/remove used to read list_web_users() (a
    snapshot of how many accounts exist), THEN separately call
    remove_web_user() to mutate -- with exactly 2 accounts, two concurrent
    removes of two DIFFERENT usernames could each observe "2 accounts, safe to
    proceed" off their own stale snapshot before either write landed, and both
    writes would go through, leaving AUTH_USERS EMPTY (adversarial review,
    2026-07-19, reproduced live against the real Flask route). Force the
    interleaving with a real delay + real threads (not just sequential calls,
    which would never expose the race) and confirm
    core.remove_web_user_guarded()'s single-lock check-and-mutate now refuses
    one of the two -- at least one account always survives."""
    import threading
    import time as _time

    core.add_or_update_web_user("bob", "pw-bob-account")
    cli = login_client(tmp_path, username="alice", password="a-real-test-password-1")
    assert {u["username"] for u in core.list_web_users()} == {"alice", "bob"}
    html = cli.get("/panel").get_data(as_text=True)
    csrf = _panel_csrf(html)

    real_save = core._save_config

    def slow_save(cfg):
        _time.sleep(0.1)
        real_save(cfg)
    monkeypatch.setattr(core, "_save_config", slow_save)

    results = {}

    def remove(username):
        r = cli.post("/api/users/remove", json={"username": username, "csrf": csrf})
        results[username] = r.get_json()

    t1 = threading.Thread(target=remove, args=("alice",))
    t2 = threading.Thread(target=remove, args=("bob",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    remaining = {u["username"] for u in core.list_web_users()}
    assert len(remaining) == 1                     # never emptied, never both survived
    refused = [v for v in results.values() if "error" in v]
    assert len(refused) == 1                       # exactly one of the two was turned away
    assert "last remaining account" in refused[0]["error"]


def test_users_endpoints_require_login(tmp_path):
    """Same front-door gate as every other /api/ route -- no special-casing needed
    here (per the design brief: every account has equal trust, no admin tier)."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = create_app(tmp_path).test_client()
    LAN = "203.0.113.5"
    r = cli.post("/api/users/add", environ_overrides={"REMOTE_ADDR": LAN},
                 json={"username": "x", "password": "pw123456", "confirm": "pw123456"})
    assert r.status_code == 401
    r2 = cli.post("/api/users/remove", environ_overrides={"REMOTE_ADDR": LAN},
                  json={"username": "alice"})
    assert r2.status_code == 401
