"""POST /api/login -- the JSON sign-in/bootstrap endpoint the React LoginPage
actually submits to (2026-08-02). It reimplements classic login()'s POST branch
(JSON body instead of a form) and PROMISES parity in its docstring: same lockout
counter (_login_seconds_locked/_login_try_acquire), same server-side bootstrap
gate (no_accounts AND _is_local_request, re-checked per request), and the exact
same deliberately-generic error strings so the JSON endpoint and the classic
form are never distinguishable to an attacker probing for accounts.

This file is that promise's direct coverage. tests/test_web_auth.py owns the
classic /login form route; the parity tests at the bottom POST BOTH routes and
compare, so a future edit that lets the two drift apart fails here by name.
Until this file existed, the live auth path's only test was an anonymous
empty-body probe in tests/test_route_tiers.py."""
import re

import moonglade_backup as core
from moonglade_gallery import create_app


def _client(tmp_path):
    return create_app(tmp_path)


def _csrf(html):
    # Same extraction test_web_auth.py uses: the classic hidden input
    # (bootstrap_mode) or the React shell's window.MG_BOOT JSON blob.
    m = re.search(r'name="csrf" value="([^"]+)"|"csrf":\s*"([^"]+)"', html)
    assert m, "login page did not render a csrf token (classic hidden field or MG_BOOT)"
    return m.group(1) or m.group(2)


def _session_csrf(cli):
    """The token straight out of the live session -- for request shapes where the
    rendered page carries none (the LAN + no-accounts safety message renders NO
    form at all), same as test_web_auth.py's LAN bootstrap tests do."""
    with cli.session_transaction() as sess:
        return sess.get("csrf", "")


def _api_login(cli, payload, remote_addr=None):
    """One JSON POST to /api/login the way LoginPage.jsx makes it: GET /login
    first (that's what mounts the React page and stashes session['csrf'] --
    setdefault, so repeat GETs reuse the same token), then POST the body with
    the csrf folded in. Returns the parsed JSON response."""
    env = {"REMOTE_ADDR": remote_addr} if remote_addr is not None else {}
    cli.get("/login", environ_overrides=env)
    body = dict(payload)
    body.setdefault("csrf", _session_csrf(cli))
    r = cli.post("/api/login", json=body, environ_overrides=env)
    assert r.status_code == 200   # this route's contract: always 200, ok/error in the body
    return r.get_json()


LAN = "203.0.113.5"          # TEST-NET-3 -- a "some other device on the LAN" stand-in


# ---------------------------------------------------------------------------
# Plain JSON sign-in
# ---------------------------------------------------------------------------

def test_api_login_success_sets_session_and_returns_ok_next(tmp_path):
    """The success shape is {"ok": True, "next": <target>} -- LoginPage.jsx does a
    CLIENT-SIDE navigate off `next`, so both keys are load-bearing. And the
    session must really be established, not just claimed: a follow-up LAN
    request (which the front door refuses for anyone anonymous) now passes."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    body = _api_login(cli, {"username": "alice", "password": "hunter2"})
    assert body == {"ok": True, "next": "/"}
    assert cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 200


def test_api_login_wrong_password_generic_error_and_no_session(tmp_path):
    """A bad password gets the one generic string -- never which field was wrong --
    and leaves the caller exactly as anonymous as before."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    body = _api_login(cli, {"username": "alice", "password": "wrong-pw"})
    assert body["error"] == "Invalid username or password."
    assert body.get("csrf"), "failed POST must return the rotated csrf token"
    assert cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 401


def test_api_login_unknown_user_same_error_as_wrong_password(tmp_path):
    """Anti-enumeration: bad username and bad password must be INDISTINGUISHABLE.
    Asserts actual equality of the two error strings (not just that each looks
    generic) so a future edit that reworks one message without the other fails
    loudly, plus the same leaky-phrase screen test_web_auth.py runs on the form."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    wrong_pw = _api_login(cli, {"username": "alice", "password": "wrong-pw"})
    unknown_user = _api_login(cli, {"username": "nobody-at-all", "password": "hunter2"})
    assert wrong_pw["error"] == unknown_user["error"]
    for leaky in ("no such user", "unknown user", "user not found", "wrong password",
                  "incorrect password"):
        assert leaky not in wrong_pw["error"].lower()
        assert leaky not in unknown_user["error"].lower()
    assert cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 401


def test_api_login_forged_csrf_rejected(tmp_path):
    """The JSON endpoint enforces the same session-bound CSRF token the classic
    form does (shared _check_csrf) -- a forged token gets the same 'expired'
    message and no session, so /api/login is not a lesser-checked side door."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    cli.get("/login")   # establishes a session + a real token we deliberately ignore
    r = cli.post("/api/login", json={"username": "alice", "password": "hunter2",
                                     "csrf": "forged-token-not-in-session"})
    assert "expired" in r.get_json()["error"].lower()
    assert cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 401


# ---------------------------------------------------------------------------
# IP lockout (shared counter with the classic form)
# ---------------------------------------------------------------------------

def test_api_login_rate_limit_locks_out_after_five_failures(tmp_path):
    """Mirror of test_web_auth.py's classic lockout test, through the JSON path:
    failures 1-4 get the ordinary generic error, the 5th -- the one that TRIPS
    the lock -- must SAY so (the classic route grew that report after users got
    locked without being told; api_login carries the same just-locked re-check),
    and a 6th attempt with the CORRECT password is still refused."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    for attempt in range(1, 6):
        body = _api_login(cli, {"username": "alice", "password": "wrong"},
                          remote_addr=LAN)
        if attempt < 5:
            assert body["error"] == "Invalid username or password."
            assert body.get("csrf"), "failed POST must return the rotated csrf token"
        else:
            assert "too many failed attempts" in body["error"].lower()
    body = _api_login(cli, {"username": "alice", "password": "hunter2"},
                      remote_addr=LAN)
    assert "too many failed attempts" in body["error"].lower()
    # Correct password during lockout still bought nothing.
    assert cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 401


def test_api_login_lockout_is_shared_with_the_classic_form(tmp_path):
    """The docstring's 'one IP-keyed counter for both modes' claim, proven: an
    address locked out via classic /login form failures is locked out of
    /api/login too. If api_login ever grew its own counter, an attacker could
    double the guess budget just by alternating endpoints."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    for _ in range(5):
        html = cli.get("/login", environ_overrides={"REMOTE_ADDR": LAN}).get_data(as_text=True)
        cli.post("/login", environ_overrides={"REMOTE_ADDR": LAN},
                 data={"username": "alice", "password": "wrong", "csrf": _csrf(html)})
    body = _api_login(cli, {"username": "alice", "password": "hunter2"},
                      remote_addr=LAN)
    assert "too many failed attempts" in body["error"].lower()


def test_api_login_lockout_applies_uniformly_to_mode_create_requests(tmp_path):
    """Same adversarial-review lesson the classic route already learned (see
    test_web_auth.py's twin): a mode=create POST from a locked-out address must
    get the lockout message, never sail through to the create-specific branch.
    api_login checks lockout FIRST, before the bootstrap gate -- keep it so."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    for _ in range(5):
        _api_login(cli, {"username": "alice", "password": "wrong"}, remote_addr=LAN)
    body = _api_login(cli, {"username": "mallory", "password": "pw123456",
                            "confirm": "pw123456", "mode": "create"},
                      remote_addr=LAN)
    assert "too many failed attempts" in body["error"].lower()
    assert core.list_web_users() == [{"username": "alice"}]   # nothing created


# ---------------------------------------------------------------------------
# mode=create first-run bootstrap
# ---------------------------------------------------------------------------

def test_api_login_bootstrap_creates_account_and_signs_in(tmp_path):
    """The React first-run flow: zero accounts + a LOCAL request (default
    test-client REMOTE_ADDR is 127.0.0.1) may create the first account, and the
    same POST both creates it AND establishes the session -- one step, exactly
    like classic bootstrap (_establish_session is shared, so no second login)."""
    cli = _client(tmp_path).test_client()
    assert core.list_web_users() == []
    body = _api_login(cli, {"username": "alice", "password": "hunter22",
                            "confirm": "hunter22", "mode": "create"})
    assert body == {"ok": True, "next": "/"}
    assert core.verify_web_user("alice", "hunter22")
    assert cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 200


def test_api_login_bootstrap_refused_once_an_account_exists(tmp_path):
    """bootstrap_mode is false the moment ANY account exists -- a mode=create
    POST after that point (even a local one carrying a valid csrf) must be
    treated as an ordinary failed login, with the generic error, never as
    account creation."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    body = _api_login(cli, {"username": "mallory", "password": "pw123456",
                            "confirm": "pw123456", "mode": "create"})
    assert body["error"] == "Invalid username or password."
    assert body.get("csrf"), "failed POST must return the rotated csrf token"
    assert {u["username"] for u in core.list_web_users()} == {"alice"}


def test_api_login_bootstrap_refused_from_lan_address(tmp_path):
    """The race-condition guard's server-side half, JSON edition: zero accounts
    but a NON-local requester. A LAN device can legitimately GET /login and
    hold a valid csrf token for its own session -- csrf validity must never be
    read as 'this create is allowed'; _is_local_request() is re-checked
    server-side per request. The refusal message is the same safety text the
    classic route serves in this state."""
    cli = _client(tmp_path).test_client()
    body = _api_login(cli, {"username": "mallory", "password": "pw123456",
                            "confirm": "pw123456", "mode": "create"},
                      remote_addr=LAN)
    assert "No account has been set up yet" in body["error"]
    assert core.list_web_users() == []
    assert cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 401


def test_api_login_bootstrap_enforces_password_policy_server_side(tmp_path):
    """The create branch runs the same core.username_problem/password_problem
    checks classic bootstrap does -- client-side validation in LoginPage.jsx is
    a convenience, not the gate. One weak password and one mismatched confirm
    prove both server-side rejections leave zero accounts behind."""
    cli = _client(tmp_path).test_client()
    body = _api_login(cli, {"username": "alice", "password": "11111111",
                            "confirm": "11111111", "mode": "create"})
    assert "one character repeated" in body["error"]
    body = _api_login(cli, {"username": "alice", "password": "hunter22",
                            "confirm": "totally-different", "mode": "create"})
    assert body["error"] == "Passwords do not match."
    assert body.get("csrf"), "failed POST must return the rotated csrf token"
    assert core.list_web_users() == []


# ---------------------------------------------------------------------------
# Error-string parity with the classic /login form
# ---------------------------------------------------------------------------

def test_api_login_wrong_password_error_text_identical_to_classic_form(tmp_path):
    """api_login's docstring promises its errors are 'the identical generic
    strings login() gives' so the two routes are never distinguishable by error
    text. Enforce it end-to-end for the wrong-password case: POST both routes
    with the same bad credentials and require the JSON error to appear VERBATIM
    in the form's re-rendered page. A rewording of either side breaks this."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()

    api_error = _api_login(cli, {"username": "alice", "password": "wrong-pw"})["error"]

    html = cli.get("/login").get_data(as_text=True)
    classic_body = cli.post("/login", data={"username": "alice", "password": "wrong-pw",
                                            "csrf": _csrf(html)}).get_data(as_text=True)
    assert api_error == "Invalid username or password."
    assert api_error in classic_body


def test_api_login_lockout_error_text_identical_to_classic_form(tmp_path):
    """Parity for the lockout message too -- the counter is shared, so an
    attacker alternating endpoints sees the same text with the same wording
    (including the same rounded minutes figure) from both."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    for _ in range(5):
        _api_login(cli, {"username": "alice", "password": "wrong"}, remote_addr=LAN)
    api_error = _api_login(cli, {"username": "alice", "password": "hunter2"},
                           remote_addr=LAN)["error"]
    assert "Too many failed attempts from this address." in api_error

    html = cli.get("/login", environ_overrides={"REMOTE_ADDR": LAN}).get_data(as_text=True)
    classic_body = cli.post("/login", environ_overrides={"REMOTE_ADDR": LAN},
                            data={"username": "alice", "password": "hunter2",
                                  "csrf": _csrf(html)}).get_data(as_text=True)
    assert api_error in classic_body


def test_api_failed_post_rotates_csrf_and_returned_token_works(tmp_path):
    """Parity with classic login()'s tested guarantee ("a consumed/known-bad token
    must never stay silently resubmittable"): a failed /api/login POST rotates
    session['csrf'], the OLD token is dead afterwards, and the fresh token the
    error payload hands back is the one the next attempt must use (that's how a
    SPA -- which can't re-render a hidden field -- stays retryable; LoginPage.jsx
    and useLogin.js adopt d.csrf). Gap found by the 2026-08-07 test port;
    rotation added same day."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    cli.get("/login", environ_overrides={"REMOTE_ADDR": LAN})
    old = _session_csrf(cli)
    body = _api_login(cli, {"username": "alice", "password": "wrong", "csrf": old},
                      remote_addr=LAN)
    assert body["error"] == "Invalid username or password."
    new = body.get("csrf")
    assert new and new != old, "failed POST must rotate the session token"
    assert _session_csrf(cli) == new, "returned token must BE the new session token"
    # The old token is dead: replaying it reads as an expired session...
    body2 = _api_login(cli, {"username": "alice", "password": "hunter2", "csrf": old},
                       remote_addr=LAN)
    assert body2["error"] == "Your session expired. Reload the page and try again."
    # ...and the token that failure handed back signs in fine.
    body3 = _api_login(cli, {"username": "alice", "password": "hunter2",
                             "csrf": body2["csrf"]}, remote_addr=LAN)
    assert body3 == {"ok": True, "next": "/"}
