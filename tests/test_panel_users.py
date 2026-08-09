"""Users management: list/add/remove gallery web-login accounts from the browser
instead of the CLI (see moonglade_gallery.py's api_panel_summary()/api_users_add()/
api_users_remove()/api_users_password(), and moonglade_backup.py's list_web_users/
add_or_update_web_user/remove_web_user). Companion to tests/test_web_auth.py's
bootstrap tests -- this file covers the OTHER half of browser-first account
management: managing accounts once you're already past the front door.

Since the classic cut (2026-08-08) the /panel PAGE is gone: the surviving surface
is the React Control Panel overlay (gallery/src/components/ControlPanelOverlay.jsx's
UsersSubOverlay) driven by /api/panel/summary + the /api/users/* JSON routes, which
all survived unchanged. The session CSRF token is fetched off /api/panel/summary's
JSON (the field the React overlay itself uses) instead of scraped from the dead
page's inline `var CSRF = "..."`.
"""
import moonglade_backup as core
from moonglade_gallery import create_app

from tests.conftest import login_client

LAN = "203.0.113.5"      # TEST-NET-3 -- the "some other device on the LAN" stand-in,
                         # same address tests/test_route_tiers.py uses.


def _session_csrf(cli):
    """The logged-in session's CSRF token, via /api/panel/summary -- the JSON twin
    that replaced scraping it off the deleted /panel page (classic cut, 2026-08-08).
    Same token the React UsersSubOverlay posts back as `summary.csrf`."""
    r = cli.get("/api/panel/summary")
    assert r.status_code == 200, "summary not reachable for a logged-in session"
    d = r.get_json()
    assert d and d.get("csrf"), "summary did not include a csrf token"
    return d["csrf"]


def test_summary_lists_existing_accounts_without_hashes(tmp_path):
    """Ported from the classic /panel Users-tab render (dead page): the account
    LIST now reaches the browser as /api/panel/summary's web_users, and the
    original's real invariant -- usernames only, never a password hash leaking
    into what the browser receives -- holds for the JSON payload the same way it
    had to hold for the rendered HTML."""
    core.add_or_update_web_user("archivist", "pw-a")
    cli = login_client(tmp_path, username="tester", password="a-real-test-password-1")
    r = cli.get("/api/panel/summary")
    assert r.status_code == 200
    d = r.get_json()
    names = {u["username"] for u in d["web_users"]}
    assert {"archivist", "tester"} <= names
    # Only usernames -- never a password hash leaking into the payload.
    raw = r.get_data(as_text=True)
    cfg = core._load_config()
    assert cfg.get("AUTH_USERS"), "expected real accounts in the isolated config"
    for u in cfg.get("AUTH_USERS", []):
        assert u["password_hash"] not in raw


def test_add_user_end_to_end_real_post_real_hash(tmp_path):
    cli = login_client(tmp_path)
    csrf = _session_csrf(cli)
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
    csrf = _session_csrf(cli)
    r = cli.post("/api/users/add", json={
        "username": "tester", "password": "brand-new-pw", "confirm": "brand-new-pw",
        "csrf": csrf})
    assert r.status_code == 400
    assert "already exists" in r.get_json()["error"]
    # The original account's password must be untouched.
    assert core.verify_web_user("tester", "a-real-test-password-1")


def test_add_user_validates_password_length_and_confirm(tmp_path):
    cli = login_client(tmp_path)
    csrf = _session_csrf(cli)
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
    csrf = _session_csrf(cli)
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


def test_username_inputs_carry_a_maxlength():
    """Client-side belt to the server's braces: the account-creation and login username
    fields cap input at the same 64, so the UI can't even submit an over-long name.

    Both halves are now JSX "source-presence assertions" (the pattern
    loom/test/loom-image-job-register.test.js established for JSX this suite has no
    browser harness to render -- tests/test_render_harness.py exists but is
    Playwright-only and skips without a chromium binary; this check must not skip):
    the login half checks LoginPage.jsx as before, and the classic /panel HTML half
    (the dead page's id="new-username" input) is ported to its surviving successor,
    ControlPanelOverlay.jsx's UsersSubOverlay add-user username input."""
    import pathlib
    src = pathlib.Path("gallery/src/components/LoginPage.jsx").read_text(encoding="utf-8")
    assert 'name="username"' in src and "maxLength={64}" in src
    # The Users overlay's add-user username input -- the classic panel input's
    # replacement -- must carry the same cap.
    cp = pathlib.Path("gallery/src/components/ControlPanelOverlay.jsx").read_text(encoding="utf-8")
    import re
    # Whole self-closing tag: `[^>]*` alone would stop at the `>` inside an
    # onChange arrow function, hiding an attribute written after it.
    m = re.search(r'<input[^>]*placeholder="username".*?/>', cp, re.S)
    assert m, "UsersSubOverlay no longer renders an add-user username input"
    assert "maxLength={64}" in m.group(0), (
        "UsersSubOverlay's add-user username input lost the maxLength=64 client-side cap "
        "the classic panel's id=new-username input carried")


def test_add_user_requires_valid_csrf(tmp_path):
    cli = login_client(tmp_path)   # login minted the session csrf; deliberately ignore it
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
    csrf = _session_csrf(cli)
    r = cli.post("/api/users/add", environ_overrides={"REMOTE_ADDR": LAN}, json={
        "username": "intruder", "password": "hunter2222", "confirm": "hunter2222",
        "csrf": csrf})
    assert r.status_code == 403
    assert "localhost-only" in r.get_json()["error"]
    assert core.list_web_users() == [{"username": "tester"}]   # nothing was created


def test_remove_user_end_to_end(tmp_path):
    core.add_or_update_web_user("doomed", "pw-doomed")
    cli = login_client(tmp_path, username="tester", password="a-real-test-password-1")
    csrf = _session_csrf(cli)
    r = cli.post("/api/users/remove", json={"username": "doomed", "csrf": csrf})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert {u["username"] for u in core.list_web_users()} == {"tester"}


def test_remove_user_requires_valid_csrf(tmp_path):
    core.add_or_update_web_user("doomed", "pw-doomed")
    cli = login_client(tmp_path, username="tester", password="a-real-test-password-1")
    r = cli.post("/api/users/remove", json={"username": "doomed", "csrf": "bogus"})
    assert r.status_code == 400
    assert "expired" in r.get_json()["error"].lower()
    # Nothing removed -- both accounts still present.
    assert {u["username"] for u in core.list_web_users()} == {"tester", "doomed"}


def test_remove_last_account_is_refused(tmp_path):
    cli = login_client(tmp_path, username="onlyone", password="a-real-test-password-1")
    csrf = _session_csrf(cli)
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
    csrf = _session_csrf(cli)
    r = cli.post("/api/users/remove", environ_overrides={"REMOTE_ADDR": LAN},
                 json={"username": "victim", "csrf": csrf})
    assert r.status_code == 403
    assert "localhost-only" in r.get_json()["error"]
    assert {u["username"] for u in core.list_web_users()} == {"tester", "victim"}


def test_remove_user_allows_a_lan_session_removing_itself(tmp_path):
    """Self-removal is the deliberate carve-out: it can only harm the caller, so
    it stays reachable from a LAN session even though removing anyone else does
    not -- a deliberate scoping choice for this fix."""
    core.add_or_update_web_user("other", "pw-other-account")
    cli = login_client(tmp_path, username="tester", password="a-real-test-password-1")
    csrf = _session_csrf(cli)
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
    csrf = _session_csrf(cli)
    r = cli.post("/api/users/remove", environ_overrides={"REMOTE_ADDR": LAN},
                 json={"username": "tester", "csrf": csrf})
    assert r.status_code == 200
    # The dead /panel page can no longer be the probe; the front door treats any
    # page GET the same way, so the app shell at / stands in: bounced to /login,
    # not served.
    r2 = cli.get("/")
    assert r2.status_code in (301, 302, 303, 307, 308)
    # And the JSON tier agrees: the summary the Panel overlay would fetch is a 401.
    assert cli.get("/api/panel/summary").status_code == 401


def test_remove_last_account_is_refused_even_as_lan_self_removal(tmp_path):
    """The last-account guard applies to LAN self-removal too -- self-removal
    being allowed for a LAN session doesn't bypass "never leave zero accounts.\""""
    cli = login_client(tmp_path, username="onlyone", password="a-real-test-password-1")
    csrf = _session_csrf(cli)
    r = cli.post("/api/users/remove", environ_overrides={"REMOTE_ADDR": LAN},
                 json={"username": "onlyone", "csrf": csrf})
    assert r.status_code == 400
    assert "last remaining account" in r.get_json()["error"]
    assert core.list_web_users() == [{"username": "onlyone"}]


def test_remove_nonexistent_user_404s(tmp_path):
    cli = login_client(tmp_path)
    csrf = _session_csrf(cli)
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
    csrf = _session_csrf(cli)

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


# ---------------------------------------------------------------------------
# The classic /panel page's Users-tab RENDER tests (add-user form hidden/shown by
# address, per-row Remove-button visibility, the self-vs-other confirm-dialog JS)
# died with the template in the classic cut (2026-08-08): their subject was the
# deleted page's inline HTML/JS, not the surviving routes. The ENFORCEMENT they
# shadowed lives on above (test_add_user_refuses_a_lan_session,
# test_remove_user_refuses_a_lan_session_removing_someone_else,
# test_remove_user_allows_a_lan_session_removing_itself); the replacement UI is
# React (ControlPanelOverlay.jsx's UsersSubOverlay), outside this suite's reach.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# /api/users/password -- the last CLI-only account operation.
#
# Until 2026-07-26 a forgotten gallery password could only be reset by running
# --add-web-user on the server machine. Owner decision: change your OWN from
# anywhere, change anyone else's only from the owner machine. That reduces to one
# rule, and both halves of it are load-bearing:
#
#     LOCALHOST     may set ANY password without proving the current one
#     non-local     may set only its OWN, and must prove the current one
#
# Drop the first half and the forgotten-password case is not fixed at all. Drop
# the second and an unlocked tablet on the LAN can silently change the owner's
# password using nothing but an open tab.
# ---------------------------------------------------------------------------

def test_lan_session_changes_its_own_password_with_the_current_one(tmp_path):
    """The everyday case: a signed-in user rotating their own password remotely."""
    cli = login_client(tmp_path, username="tester", password="a-real-test-password-1")
    csrf = _session_csrf(cli)
    r = cli.post("/api/users/password", environ_overrides={"REMOTE_ADDR": LAN},
                 json={"current_password": "a-real-test-password-1",
                       "new_password": "a-brand-new-password-2", "csrf": csrf})
    assert r.status_code == 200, r.get_json()
    assert core.verify_web_user("tester", "a-brand-new-password-2")
    assert not core.verify_web_user("tester", "a-real-test-password-1")


def test_lan_session_cannot_change_its_own_password_without_the_current_one(tmp_path):
    """The unlocked-tablet attack. An already-authenticated session is NOT enough:
    without the old password it cannot replace the password, so a borrowed device
    cannot lock the owner out of his own account."""
    cli = login_client(tmp_path, username="tester", password="a-real-test-password-1")
    csrf = _session_csrf(cli)
    r = cli.post("/api/users/password", environ_overrides={"REMOTE_ADDR": LAN},
                 json={"new_password": "attacker-chosen-pw-9", "csrf": csrf})
    assert r.status_code == 400
    r2 = cli.post("/api/users/password", environ_overrides={"REMOTE_ADDR": LAN},
                  json={"current_password": "not-the-right-one",
                        "new_password": "attacker-chosen-pw-9", "csrf": csrf})
    assert r2.status_code == 403
    # The original password still works, both times.
    assert core.verify_web_user("tester", "a-real-test-password-1")
    assert not core.verify_web_user("tester", "attacker-chosen-pw-9")


def test_lan_session_cannot_change_anyone_elses_password(tmp_path):
    """Even knowing the victim's current password. The username check refuses first,
    exactly as api_users_remove does, so a LAN caller can never aim this at the owner."""
    core.add_or_update_web_user("victim", "pw-victim-account")
    cli = login_client(tmp_path, username="tester", password="a-real-test-password-1")
    csrf = _session_csrf(cli)
    r = cli.post("/api/users/password", environ_overrides={"REMOTE_ADDR": LAN},
                 json={"username": "victim", "current_password": "pw-victim-account",
                       "new_password": "stolen-account-pw-3", "csrf": csrf})
    assert r.status_code == 403
    assert "localhost-only" in r.get_json()["error"]
    assert core.verify_web_user("victim", "pw-victim-account")   # untouched


def test_local_session_resets_another_account_without_its_password(tmp_path):
    """THE recovery path, and the whole point of the item: at the machine, the owner
    can reset a forgotten password without knowing the old one."""
    core.add_or_update_web_user("forgetful", "the-password-nobody-recalls")
    cli = login_client(tmp_path, username="tester", password="a-real-test-password-1")
    csrf = _session_csrf(cli)
    r = cli.post("/api/users/password",
                 json={"username": "forgetful", "new_password": "a-fresh-start-pw-4",
                       "csrf": csrf})
    assert r.status_code == 200, r.get_json()
    assert core.verify_web_user("forgetful", "a-fresh-start-pw-4")


def test_local_session_resets_its_own_password_without_the_current_one(tmp_path):
    """Requiring the old password at the machine would protect nothing -- anyone
    sitting there can edit config.json directly -- and would leave the owner's OWN
    forgotten password unrecoverable, which is the case the item is about."""
    cli = login_client(tmp_path, username="tester", password="a-real-test-password-1")
    csrf = _session_csrf(cli)
    r = cli.post("/api/users/password",
                 json={"new_password": "recovered-locally-pw-5", "csrf": csrf})
    assert r.status_code == 200, r.get_json()
    assert core.verify_web_user("tester", "recovered-locally-pw-5")


def test_changing_your_own_password_keeps_you_signed_in_here(tmp_path):
    """The write bumps sess_epoch, which invalidates every cookie issued under the old
    password -- correct on other devices, rude on this one. The route re-issues the
    caller's own epoch, so the browser in front of you survives and the Panel still
    loads immediately afterwards."""
    cli = login_client(tmp_path, username="tester", password="a-real-test-password-1")
    csrf = _session_csrf(cli)
    r = cli.post("/api/users/password", environ_overrides={"REMOTE_ADDR": LAN},
                 json={"current_password": "a-real-test-password-1",
                       "new_password": "still-here-after-pw-6", "csrf": csrf})
    assert r.status_code == 200
    # The Panel's own summary fetch still 200s -- the session in front of you survived.
    assert cli.get("/api/panel/summary").status_code == 200


def test_password_reset_refuses_an_unknown_account(tmp_path):
    """Unlike --add-web-user, whose add-or-update semantics doubled as the reset, this
    REFUSES a name that does not exist rather than minting it. A reset for a
    non-existent user is a typo to report, not an invitation."""
    cli = login_client(tmp_path, username="tester", password="a-real-test-password-1")
    csrf = _session_csrf(cli)
    r = cli.post("/api/users/password",
                 json={"username": "ghost", "new_password": "should-not-exist-7",
                       "csrf": csrf})
    assert r.status_code == 404
    assert {u["username"] for u in core.list_web_users()} == {"tester"}


def test_password_reset_reuses_the_add_user_password_policy(tmp_path):
    """One policy, one place. A password too weak to REGISTER must be too weak to SET,
    or the Users tab would enforce a rule this route quietly undercuts."""
    cli = login_client(tmp_path, username="tester", password="a-real-test-password-1")
    csrf = _session_csrf(cli)
    r = cli.post("/api/users/password",
                 json={"new_password": "x", "csrf": csrf})
    assert r.status_code == 400
    assert core.verify_web_user("tester", "a-real-test-password-1")   # unchanged


def test_password_change_requires_csrf(tmp_path):
    """Same guard every other Panel mutation carries."""
    cli = login_client(tmp_path, username="tester", password="a-real-test-password-1")
    r = cli.post("/api/users/password",
                 json={"new_password": "no-token-supplied-8"})
    assert r.status_code == 400
    assert core.verify_web_user("tester", "a-real-test-password-1")
