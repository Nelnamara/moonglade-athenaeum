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

LAN = "203.0.113.5"      # TEST-NET-3 -- the "some other device on the LAN" stand-in,
                         # same address tests/test_route_tiers.py uses.


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


def test_username_problem_policy():
    """The one policy every entry point shares. Empty / over-length / control chars are
    rejected with a rendered-verbatim reason; an ordinary name passes."""
    cap = core.MAX_WEB_USERNAME_LEN
    assert core.username_problem("") == "Username is required."
    assert core.username_problem("   ") == "Username is required."      # strips first
    assert "at most" in core.username_problem("x" * (cap + 1))
    assert core.username_problem("x" * cap) is None                      # exactly at the cap is fine
    assert "control characters" in core.username_problem("bad\x00name")
    assert "control characters" in core.username_problem("tab\tname")
    assert core.username_problem("Nel'namara 42") is None                # spaces/punctuation/unicode ok


def test_add_user_rejects_overlong_username(tmp_path):
    """The 300-char-username row-break bug: a name past the cap is refused with a friendly
    message, and nothing is written."""
    cli = login_client(tmp_path)
    csrf = _panel_csrf(cli.get("/panel").get_data(as_text=True))
    long_name = "z" * (core.MAX_WEB_USERNAME_LEN + 50)
    r = cli.post("/api/users/add", json={
        "username": long_name, "password": "a-valid-password", "confirm": "a-valid-password",
        "csrf": csrf})
    assert r.status_code == 400
    assert "at most" in r.get_json()["error"]
    assert core.list_web_users() == [{"username": "tester"}]             # not written


def test_writers_reject_overlong_username_as_a_backstop(tmp_path):
    """The hard backstop at the one place an account is written -- so even the
    --add-web-user CLI path (which never calls username_problem) can't persist an
    over-long name."""
    import pytest
    over = "q" * (core.MAX_WEB_USERNAME_LEN + 1)
    with pytest.raises(ValueError):
        core.add_or_update_web_user(over, "a-valid-password")
    with pytest.raises(ValueError):
        core.add_web_user_if_new(over, "a-valid-password")
    # a name exactly at the cap writes fine
    assert core.add_web_user_if_new("y" * core.MAX_WEB_USERNAME_LEN, "a-valid-password") is True


def test_username_inputs_carry_a_maxlength(tmp_path):
    """Client-side belt to the server's braces: the account-creation and login username
    fields cap input at the same 64, so the UI can't even submit an over-long name."""
    cli = login_client(tmp_path)
    panel = cli.get("/panel").get_data(as_text=True)
    assert 'id="new-username"' in panel and 'maxlength="64"' in panel
    # login page from a FRESH unauthenticated client -- an authed GET /login may redirect
    login = create_app(tmp_path).test_client().get("/login").get_data(as_text=True)
    assert 'name="username"' in login and 'maxlength="64"' in login


def test_add_user_requires_valid_csrf(tmp_path):
    cli = login_client(tmp_path)
    cli.get("/panel")  # establishes the session; deliberately ignore its real csrf
    r = cli.post("/api/users/add", json={
        "username": "newperson", "password": "hunter2222", "confirm": "hunter2222",
        "csrf": "forged-token-not-in-session"})
    assert r.status_code == 400
    assert "expired" in r.get_json()["error"].lower()
    assert core.list_web_users() == [{"username": "tester"}]


def test_add_user_refuses_a_lan_session(tmp_path):
    """api_users_add is LOCALHOST-only as of 2026-07-22: a LAN session can no longer
    mint a new, persistent account for itself -- half of the fix for STATE.md's
    "evict the owner, then register a new one for itself" finding. The other half
    is api_users_remove refusing a LAN session that tries to remove anyone but
    itself -- see test_remove_user_refuses_a_lan_session_removing_someone_else."""
    cli = login_client(tmp_path)
    csrf = _panel_csrf(cli.get("/panel").get_data(as_text=True))
    r = cli.post("/api/users/add", environ_overrides={"REMOTE_ADDR": LAN}, json={
        "username": "intruder", "password": "hunter2222", "confirm": "hunter2222",
        "csrf": csrf})
    assert r.status_code == 403
    assert "localhost-only" in r.get_json()["error"]
    assert core.list_web_users() == [{"username": "tester"}]   # nothing was created


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


def test_remove_user_refuses_a_lan_session_removing_someone_else(tmp_path):
    """The other half of the same fix: a LAN session can no longer remove ANY
    other account by name -- previously the only guard was "not the last account
    left," which let a borrowed-tablet guest evict the owner specifically."""
    core.add_or_update_web_user("victim", "pw-victim-account")
    cli = login_client(tmp_path, username="tester", password="a-real-test-password-1")
    csrf = _panel_csrf(cli.get("/panel").get_data(as_text=True))
    r = cli.post("/api/users/remove", environ_overrides={"REMOTE_ADDR": LAN},
                 json={"username": "victim", "csrf": csrf})
    assert r.status_code == 403
    assert "localhost-only" in r.get_json()["error"]
    assert {u["username"] for u in core.list_web_users()} == {"tester", "victim"}


def test_remove_user_allows_a_lan_session_removing_itself(tmp_path):
    """Self-removal is the deliberate carve-out: it can only harm the caller, so
    it stays reachable from a LAN session even though removing anyone else does
    not -- the owner's explicit choice when this fix was scoped, 2026-07-22."""
    core.add_or_update_web_user("other", "pw-other-account")
    cli = login_client(tmp_path, username="tester", password="a-real-test-password-1")
    csrf = _panel_csrf(cli.get("/panel").get_data(as_text=True))
    r = cli.post("/api/users/remove", environ_overrides={"REMOTE_ADDR": LAN},
                 json={"username": "tester", "csrf": csrf})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert {u["username"] for u in core.list_web_users()} == {"other"}


def test_lan_self_removal_kills_the_callers_own_session_immediately(tmp_path):
    """Removing your own account revokes your own session on the very next
    request -- get_web_user_session_epoch() returns None once the account is
    gone, and _is_authorized_request() re-checks that on every call. Confirms
    the caller can't keep acting as a user that no longer exists."""
    core.add_or_update_web_user("other", "pw-other-account")
    cli = login_client(tmp_path, username="tester", password="a-real-test-password-1")
    csrf = _panel_csrf(cli.get("/panel").get_data(as_text=True))
    r = cli.post("/api/users/remove", environ_overrides={"REMOTE_ADDR": LAN},
                 json={"username": "tester", "csrf": csrf})
    assert r.status_code == 200
    r2 = cli.get("/panel")
    assert r2.status_code in (301, 302, 303, 307, 308)   # bounced to /login, not served


def test_remove_last_account_is_refused_even_as_lan_self_removal(tmp_path):
    """The last-account guard applies to LAN self-removal too -- self-removal
    being allowed for a LAN session doesn't bypass "never leave zero accounts.\""""
    cli = login_client(tmp_path, username="onlyone", password="a-real-test-password-1")
    csrf = _panel_csrf(cli.get("/panel").get_data(as_text=True))
    r = cli.post("/api/users/remove", environ_overrides={"REMOTE_ADDR": LAN},
                 json={"username": "onlyone", "csrf": csrf})
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
    """Both routes need a valid session before anything else -- the SAME front-door
    gate as every other /api/ route, no special-casing. This is a lower bar than
    either route's own LOCALHOST-flavored check (see test_add_user_refuses_a_lan_session
    and test_remove_user_refuses_a_lan_session_removing_someone_else): a session-less
    caller gets refused here regardless of address, before those checks ever run."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = create_app(tmp_path).test_client()
    r = cli.post("/api/users/add", environ_overrides={"REMOTE_ADDR": LAN},
                 json={"username": "x", "password": "pw123456", "confirm": "pw123456"})
    assert r.status_code == 401
    r2 = cli.post("/api/users/remove", environ_overrides={"REMOTE_ADDR": LAN},
                  json={"username": "alice"})
    assert r2.status_code == 401


def _row_html(html, username):
    """Slice out one <div class="u-row">...</div> block. Safe as non-greedy .*?
    because a row never nests another <div> inside it (just a <span> and maybe a
    <button>) -- the first </div> reached IS the row's own closing tag."""
    m = re.search(r'<div class="u-row" data-username="{}">.*?</div>'.format(re.escape(username)),
                  html, re.S)
    assert m, "no row rendered for username {!r}".format(username)
    return m.group(0)


def test_add_user_form_hidden_for_a_lan_session(tmp_path):
    """Would-always-fail controls are hidden rather than shown-then-403'd -- the
    server-side gate in api_users_add is what actually enforces this; this test
    is about not walking a LAN user into a dead-end confirm dialog."""
    cli = login_client(tmp_path)
    html = cli.get("/panel", environ_overrides={"REMOTE_ADDR": LAN}).get_data(as_text=True)
    assert 'id="add-user-form"' not in html
    assert "Only the machine running the gallery can add new accounts" in html


def test_add_user_form_shown_for_a_local_session(tmp_path):
    cli = login_client(tmp_path)
    html = cli.get("/panel").get_data(as_text=True)   # loopback by default
    assert 'id="add-user-form"' in html
    assert "restricted to the machine running the gallery" in html


def test_remove_button_hidden_on_other_rows_for_a_lan_session(tmp_path):
    """A LAN session can still remove its OWN row (see
    test_remove_user_allows_a_lan_session_removing_itself) -- only OTHER rows'
    Remove buttons are withheld, matching what api_users_remove will actually
    accept from that same session."""
    core.add_or_update_web_user("other", "pw-other-account")
    cli = login_client(tmp_path, username="tester", password="a-real-test-password-1")
    html = cli.get("/panel", environ_overrides={"REMOTE_ADDR": LAN}).get_data(as_text=True)
    assert "removeUser(this)" in _row_html(html, "tester")
    assert "removeUser(this)" not in _row_html(html, "other")


def test_remove_button_shown_on_every_row_for_a_local_session(tmp_path):
    core.add_or_update_web_user("other", "pw-other-account")
    cli = login_client(tmp_path, username="tester", password="a-real-test-password-1")
    html = cli.get("/panel").get_data(as_text=True)   # loopback by default
    assert "removeUser(this)" in _row_html(html, "tester")
    assert "removeUser(this)" in _row_html(html, "other")


def test_remove_user_js_distinguishes_self_from_other(tmp_path):
    """The confirm-dialog wording (and the redirect-to-/login after success) only
    make sense read as "you" for a self-removal -- checked as the exact source
    strings, not a vague substring, since generic wording like "signed out" would
    still be present even if this branch were reverted."""
    cli = login_client(tmp_path)
    html = cli.get("/panel").get_data(as_text=True)
    assert "var isSelf = !!row.querySelector('.u-you');" in html
    assert "You will be signed out immediately, on every device." in html
    assert "if(isSelf){ location.href='/login'; return; }" in html
