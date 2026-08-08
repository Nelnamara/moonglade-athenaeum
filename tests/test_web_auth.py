"""Session-based web-gallery login auth: the auth pass that gates EVERY request
behind a login, including from the server's own machine -- there is no
localhost bypass (see moonglade_gallery.py's _is_authorized_request(), GET /login,
POST /api/login and POST /api/logout, and moonglade_backup.py's
get_or_create_secret_key/add_or_update_web_user/remove_web_user/verify_web_user/
list_web_users).

Since the classic-UI cut (2026-08-08) the ONLY sign-in surface is GET /login
(the React shell; csrf rides in window.MG_BOOT) + POST /api/login (JSON).
tests/test_api_login.py owns that endpoint's core contract (generic-error
parity, lockout incl. the 5th-try report and the shared counter, csrf rotation
incl. the returned-token flow, bootstrap policy and the local-only refusal).
This file keeps everything that ISN'T duplicated there: the core/CLI account
helpers, the GET /login boot flags, the front-door route matrix, session
revocation, and the unique regressions ported off the dead form route
(next-sanitizer bypasses, lockout-clears-on-success, the lockout race,
incidental-GET csrf setdefault, blank-remote_addr fail-closed).

NOT about PIXAI_API_KEY auth -- that's tests/test_auth.py. This file is about
the *web session* login that gates the gallery itself."""
import re
import sys

import pytest

import moonglade_backup as core
from moonglade_gallery import create_app
from tests.conftest import login_existing_client


def _client(tmp_path):
    return create_app(tmp_path)


def _csrf(html):
    # The React shell's window.MG_BOOT JSON blob (the only login page since the
    # classic cut, 2026-08-08). The classic hidden-input pattern is kept in the
    # regex purely so a regression that resurrects it still extracts + fails
    # loudly at the POST step rather than silently here.
    m = re.search(r'name="csrf" value="([^"]+)"|"csrf":\s*"([^"]+)"', html)
    assert m, "login page did not render a csrf token in MG_BOOT"
    return m.group(1) or m.group(2)


def _is_react_login_shell(html):
    """True when GET /login served LoginPage.jsx's shell (the only login surface
    since the classic cut). The actual <input name="username"> only exists in
    client-rendered DOM, not this raw server response, so tests check the boot
    payload's own authenticated:false marker instead of form-field text that
    isn't there server-side."""
    return re.search(r'"authenticated":\s*false', html) is not None


def _session_csrf(cli):
    """The token straight out of the live session -- for request shapes where
    the rendered page carries none, and for /api/logout (whose caller holds the
    token in JS, not in a form)."""
    with cli.session_transaction() as sess:
        return sess.get("csrf", "")


_NO_OVERRIDE = object()


def _api_login(cli, payload, remote_addr=_NO_OVERRIDE):
    """One JSON POST to /api/login the way LoginPage.jsx makes it: GET /login
    first (that's what mounts the React page and stashes session['csrf'] --
    setdefault, so repeat GETs reuse the same token), then POST the body with
    the csrf folded in. Returns the parsed JSON response. remote_addr may be
    "" or None to exercise the blank-remote_addr fail-closed path."""
    env = {} if remote_addr is _NO_OVERRIDE else {"REMOTE_ADDR": remote_addr}
    cli.get("/login", environ_overrides=env)
    body = dict(payload)
    body.setdefault("csrf", _session_csrf(cli))
    r = cli.post("/api/login", json=body, environ_overrides=env)
    assert r.status_code == 200   # this route's contract: always 200, ok/error in the body
    return r.get_json()


def _logout(cli):
    """Sign out the way the React app does: POST /api/logout carrying this
    session's csrf token. The default scope is the GLOBAL revoke (it bumps the
    per-user sess_epoch), which is what any test about REVOKING OTHER SESSIONS
    needs -- scope="this-device" is the opt-out, not the default."""
    return cli.post("/api/logout", json={"csrf": _session_csrf(cli)})


LAN = "203.0.113.5"          # TEST-NET-3 -- a "some other device on the LAN" stand-in
LAN2 = "203.0.113.9"


def test_every_response_carries_the_server_marker(tmp_path):
    """The `Serve Gallery` launcher decides "one of our servers is already on this port"
    by the X-Moonglade response header, NOT a 200 status: /api/ping now sits behind the
    login gate, so its unauthenticated probe gets a 401, and urllib raises on that. The
    marker therefore has to ride EVERY response, including the front door's 401 -- which
    is returned straight from the before_request hook and runs no view. If the header were
    set in the ping view instead, the 401 would lack it and the launcher would mistake a
    gated-but-live server for a dead port and start a second one (the original bug).

    Bite: move the header into api_ping()'s body and the 401 assertion here fails."""
    cli = _client(tmp_path).test_client()
    r200 = cli.get("/login")                       # public page, a real view runs
    assert r200.status_code == 200
    assert r200.headers.get("X-Moonglade") == "1"
    r401 = cli.get("/api/ping")                     # gated -> 401 from the hook, no view
    assert r401.status_code == 401
    assert r401.headers.get("X-Moonglade") == "1"


# ---------------------------------------------------------------------------
# config.json helpers (secret key + account lifecycle)
# ---------------------------------------------------------------------------

def test_get_or_create_secret_key_persists_across_reload(tmp_path):
    key1 = core.get_or_create_secret_key()
    # A second, independent _load_config() call (not the cached one) must see the
    # SAME key -- this is what makes sessions survive a server restart.
    cfg = core._load_config()
    assert cfg["AUTH_SECRET_KEY"] == key1
    key2 = core.get_or_create_secret_key()
    assert key2 == key1


def test_add_or_update_web_user_never_stores_plaintext(tmp_path):
    core.add_or_update_web_user("alice", "hunter2")
    cfg = core._load_config()
    users = cfg["AUTH_USERS"]
    assert len(users) == 1
    assert users[0]["username"] == "alice"
    stored = users[0]["password_hash"]
    assert "hunter2" not in stored                 # never the raw password
    assert stored.startswith("scrypt:")            # werkzeug's modern default hash
    from werkzeug.security import check_password_hash
    assert check_password_hash(stored, "hunter2")
    assert not check_password_hash(stored, "wrong-password")


def test_add_or_update_web_user_reports_new_vs_replaced(tmp_path):
    assert core.add_or_update_web_user("alice", "first-pw") is False    # new account
    assert core.add_or_update_web_user("alice", "second-pw") is True    # replaced
    from werkzeug.security import check_password_hash
    cfg = core._load_config()
    stored = cfg["AUTH_USERS"][0]["password_hash"]
    assert check_password_hash(stored, "second-pw")
    assert not check_password_hash(stored, "first-pw")


def test_remove_web_user_removes_only_named_user(tmp_path):
    core.add_or_update_web_user("alice", "pw-a")
    core.add_or_update_web_user("bob", "pw-b")
    assert core.remove_web_user("alice") is True
    assert core.remove_web_user("alice") is False   # already gone -- nothing to remove
    remaining = {u["username"] for u in core.list_web_users()}
    assert remaining == {"bob"}


def test_list_web_users_never_exposes_hashes(tmp_path):
    core.add_or_update_web_user("alice", "pw-a")
    users = core.list_web_users()
    assert users == [{"username": "alice"}]
    assert not any("hash" in k or "password" in k for u in users for k in u)


def test_verify_web_user_checks_hash(tmp_path):
    core.add_or_update_web_user("alice", "hunter2")
    assert core.verify_web_user("alice", "hunter2") is True
    assert core.verify_web_user("alice", "wrong") is False
    assert core.verify_web_user("nobody", "hunter2") is False


# ---------------------------------------------------------------------------
# CLI flags
# ---------------------------------------------------------------------------

def test_cli_add_web_user_prompts_hashes_and_persists(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "alice")
    monkeypatch.setattr(core.getpass, "getpass", lambda prompt="": "hunter2-valid-pw")
    monkeypatch.setattr(sys, "argv", ["moonglade_backup.py", "--add-web-user"])
    core.main()
    users = core.list_web_users()
    assert users == [{"username": "alice"}]
    assert core.verify_web_user("alice", "hunter2-valid-pw") is True


def test_cli_add_web_user_rejects_mismatched_confirmation(tmp_path, monkeypatch):
    # Both entries must CLEAR the password policy, otherwise this exits on the
    # policy check and silently stops testing the mismatch path it names.
    monkeypatch.setattr("builtins.input", lambda prompt="": "alice")
    passwords = iter(["hunter2-valid-pw", "totally-different"])
    monkeypatch.setattr(core.getpass, "getpass", lambda prompt="": next(passwords))
    monkeypatch.setattr(sys, "argv", ["moonglade_backup.py", "--add-web-user"])
    with pytest.raises(SystemExit):
        core.main()
    assert core.list_web_users() == []


def test_cli_add_web_user_enforces_the_same_password_policy(tmp_path, monkeypatch):
    """The CLI is the documented recovery path, not a back door around the rules
    the web sign-in enforces -- a weak password must be refused here too."""
    monkeypatch.setattr("builtins.input", lambda prompt="": "alice")
    monkeypatch.setattr(core.getpass, "getpass", lambda prompt="": "1111")
    monkeypatch.setattr(sys, "argv", ["moonglade_backup.py", "--add-web-user"])
    with pytest.raises(SystemExit):
        core.main()
    assert core.list_web_users() == []


def test_cli_remove_web_user_flag(tmp_path, monkeypatch):
    core.add_or_update_web_user("alice", "pw-a")
    core.add_or_update_web_user("bob", "pw-b")
    monkeypatch.setattr(sys, "argv",
                        ["moonglade_backup.py", "--remove-web-user", "alice"])
    core.main()
    assert {u["username"] for u in core.list_web_users()} == {"bob"}


def test_cli_list_web_users_flag_runs_without_error(tmp_path, monkeypatch, capsys):
    core.add_or_update_web_user("alice", "pw-a")
    monkeypatch.setattr(sys, "argv", ["moonglade_backup.py", "--list-web-users"])
    core.main()
    out = capsys.readouterr().out
    assert "alice" in out


# ---------------------------------------------------------------------------
# GET /login (React shell + boot flags)
# ---------------------------------------------------------------------------

def test_login_page_renders_shell_with_csrf(tmp_path):
    cli = _client(tmp_path).test_client()
    html = cli.get("/login").get_data(as_text=True)
    # Every state (create/sign-in/LAN-safety) is the React shell now; the actual
    # <input> only exists in client-rendered DOM.
    assert _is_react_login_shell(html)
    assert _csrf(html)   # a token is present


def _boot_field(html, field):
    """Pull a boolean field out of the React shell's window.MG_BOOT blob."""
    m = re.search(r'"' + field + r'":\s*(true|false)', html)
    return m is not None and m.group(1) == "true"


def test_login_page_no_accounts_flag_flips_once_a_real_account_exists(tmp_path):
    """With zero AUTH_USERS configured (the fresh-clone default), a LOCAL request to
    /login gets the React shell with boot.no_accounts:true -- LoginPage.jsx reads
    that client-side to default into its create-account mode (design:
    design_handoff/request-bootstrap-account-creation.md) -- first-run setup
    happens in the browser, never the CLI, so classic's --add-web-user hint must
    never leak into the response either way. The flag flips to false -- and
    LoginPage.jsx switches to its ordinary sign-in mode -- the moment a real
    account exists."""
    cli = _client(tmp_path).test_client()
    html = cli.get("/login").get_data(as_text=True)
    assert "--add-web-user" not in html
    assert _is_react_login_shell(html)
    assert _boot_field(html, "no_accounts") is True
    core.add_or_update_web_user("alice", "hunter2")
    html2 = cli.get("/login").get_data(as_text=True)
    assert "--add-web-user" not in html2
    assert _is_react_login_shell(html2)
    assert _boot_field(html2, "no_accounts") is False


def test_login_page_shows_safe_message_for_lan_request_when_no_accounts(tmp_path):
    """The exact same zero-accounts state, but requested from a LAN address, must NEVER
    offer the bootstrap form. The boot carries no_accounts:true AND is_local:false, which
    LoginPage.jsx reads to render the "no account set up yet -- do it from the server
    machine" message (client-side) instead of a create form a remote caller could never
    use. --add-web-user must never leak. The server-side enforcement half is
    tests/test_api_login.py's test_api_login_bootstrap_refused_from_lan_address."""
    cli = _client(tmp_path).test_client()
    html = cli.get("/login", environ_overrides={"REMOTE_ADDR": LAN}).get_data(as_text=True)
    assert "--add-web-user" not in html
    assert _is_react_login_shell(html)
    assert _boot_field(html, "no_accounts") is True
    assert _boot_field(html, "is_local") is False   # -> LoginPage shows the safe message
    # Once an account exists, a LAN request goes to the ordinary sign-in shell.
    core.add_or_update_web_user("alice", "hunter2")
    html2 = cli.get("/login", environ_overrides={"REMOTE_ADDR": LAN}).get_data(as_text=True)
    assert _is_react_login_shell(html2)
    assert _boot_field(html2, "no_accounts") is False


def test_bootstrap_treats_empty_or_missing_remote_addr_as_not_local(tmp_path):
    """Adversarial-review regression: _is_local_request() used to treat a
    missing/empty remote_addr as local (`ra in (..., "")`) -- a fail-OPEN
    default in a function that gates the first-account bootstrap (and
    destructive Panel actions). It must now fail CLOSED: an empty or None
    remote_addr is refused exactly like a real LAN address in the
    zero-accounts state -- boot.is_local:false so LoginPage never offers the
    create form, and a hand-crafted mode=create POST to /api/login under the
    same condition is still refused server-side."""
    cli = _client(tmp_path).test_client()
    for blank in ("", None):
        html = cli.get("/login", environ_overrides={"REMOTE_ADDR": blank}).get_data(as_text=True)
        assert _is_react_login_shell(html)
        assert _boot_field(html, "no_accounts") is True
        assert _boot_field(html, "is_local") is False
        body = _api_login(cli, {"username": "mallory", "password": "pw123456",
                                "confirm": "pw123456", "mode": "create"},
                          remote_addr=blank)
        assert "No account has been set up yet" in body["error"]
    assert core.list_web_users() == []


# ---------------------------------------------------------------------------
# Unique bootstrap/validation coverage ported off the dead form route to
# POST /api/login (the surviving sign-in endpoint). The endpoint's own core
# contract lives in tests/test_api_login.py -- these are the regressions and
# policy matrices that file does NOT carry.
# ---------------------------------------------------------------------------

def test_bootstrap_validates_username_and_password_rules(tmp_path):
    """The bootstrap validation rules are enforced server-side, not just in
    LoginPage.jsx: empty username, too-short password, mismatched confirm."""
    cli = _client(tmp_path).test_client()
    body = _api_login(cli, {"username": "", "password": "hunter22",
                            "confirm": "hunter22", "mode": "create"})
    assert "Username is required" in body["error"]
    body = _api_login(cli, {"username": "alice", "password": "ab",
                            "confirm": "ab", "mode": "create"})
    assert "at least 8 characters" in body["error"]
    body = _api_login(cli, {"username": "alice", "password": "hunter22",
                            "confirm": "totally-different", "mode": "create"})
    assert body["error"] == "Passwords do not match."
    assert core.list_web_users() == []


@pytest.mark.parametrize("password, expected", [
    ("short1", "at least 8 characters"),          # under the length floor
    ("11111111", "one character repeated"),       # the exact "everyone will use 1111" case
    ("aaaaaaaaaa", "one character repeated"),
    ("12345678", "too common"),                   # in the common list AND a run; common wins
    ("abcdefgh", "sequential characters"),        # long enough, but a straight keyboard walk
    ("87654321", "sequential characters"),        # descending counts too
    ("password", "too common"),
    ("PASSWORD", "too common"),                   # the common check is case-insensitive
])
def test_bootstrap_rejects_weak_passwords(tmp_path, password, expected):
    """Length alone is not the policy: a password can clear 8 characters and still
    be trivially guessable. Guards core.password_problem() through the real
    bootstrap path (/api/login mode=create), since that is the path a first-run
    owner actually uses."""
    cli = _client(tmp_path).test_client()
    body = _api_login(cli, {"username": "alice", "password": password,
                            "confirm": password, "mode": "create"})
    assert expected in body["error"]
    assert core.list_web_users() == []   # nothing was created


def test_password_policy_is_shared_by_login_and_users_tab(tmp_path):
    """Regression guard for the duplication that used to exist: the 4-character
    rule was written out separately in the login path and api_users_add(), so
    tightening it in one place would silently leave the other weak. Both must
    refuse the same password via the same core.password_problem()."""
    weak = "11111111"
    assert core.password_problem(weak)                    # the shared helper refuses it
    assert core.password_problem("a-valid-password") is None
    cli = _client(tmp_path).test_client()
    body = _api_login(cli, {"username": "alice", "password": weak,
                            "confirm": weak, "mode": "create"})
    assert "one character repeated" in body["error"]
    assert core.list_web_users() == []


def test_bootstrap_missing_confirm_field_does_not_crash(tmp_path):
    """A malformed/short-circuited POST (e.g. a client that dropped the confirm
    field entirely, not just sent it empty) must be handled as a validation
    failure, never a 500. The 200-with-error contract is asserted inside
    _api_login."""
    cli = _client(tmp_path).test_client()
    body = _api_login(cli, {"username": "alice", "password": "hunter22",
                            "mode": "create"})
    assert body["error"] == "Passwords do not match."
    assert core.list_web_users() == []


def test_concurrent_add_or_update_web_user_does_not_lose_either_account(tmp_path, monkeypatch):
    """TOCTOU/lost-update regression: add_or_update_web_user() used to do an
    unlocked _load_config() -> mutate -> _save_config() -- two concurrent calls
    for DIFFERENT usernames could both read the pre-write state, so the second
    write would silently clobber the first's on disk (adversarial review,
    2026-07-19: reproduced live via two concurrent local bootstrap POSTs that
    both returned success to their own browser, while only one of the two
    usernames actually ended up in AUTH_USERS). Force the interleaving with a
    real delay + real threads (not just sequential calls, which would never
    expose the race) and confirm _accounts_lock now serializes the two full
    read-modify-write cycles -- BOTH accounts survive, regardless of which
    thread's write lands first."""
    import threading
    import time as _time

    real_save = core._save_config

    def slow_save(cfg):
        _time.sleep(0.1)
        real_save(cfg)
    monkeypatch.setattr(core, "_save_config", slow_save)

    def create(name):
        core.add_or_update_web_user(name, "hunter2222")

    t1 = threading.Thread(target=create, args=("alice",))
    t2 = threading.Thread(target=create, args=("bob",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    # Neither write was lost -- both accounts are actually on disk.
    assert {u["username"] for u in core.list_web_users()} == {"alice", "bob"}


def test_incidental_get_does_not_invalidate_pending_csrf_token(tmp_path):
    """Real regression: first-run account creation stuck on "Your session
    expired" no matter what -- even after clearing cookies and restarting the
    server. Root cause: the front door (_enforce_front_door()) redirects EVERY
    unauthenticated request to /login?next=<path> -- including background
    requests a browser fires the instant the page loads (favicon.ico and
    friends). Each of those landed on login()'s GET, which used to
    unconditionally mint a FRESH session["csrf"] on every GET -- silently
    orphaning the token the real, visible login page had already handed the
    human via MG_BOOT. The very next real submit then failed with "Your
    session expired," deterministically. login() now uses
    session.setdefault("csrf", ...) so incidental GETs reuse the token.
    Reproduce exactly that sequence -- grab a token, let unrelated GETs land
    on /login in between, then submit the ORIGINAL token to /api/login -- and
    confirm it still works."""
    cli = _client(tmp_path).test_client()
    html = cli.get("/login").get_data(as_text=True)
    original_csrf = _csrf(html)
    # Simulate the front door redirecting a handful of incidental background
    # requests here before the human ever touches the visible page.
    cli.get("/login", query_string={"next": "/favicon.ico"})
    cli.get("/login", query_string={"next": "/apple-touch-icon.png"})
    cli.get("/login", query_string={"next": "/some-asset.js"})
    r = cli.post("/api/login", json={
        "username": "nel", "password": "pw123456", "confirm": "pw123456",
        "mode": "create", "csrf": original_csrf})
    assert r.get_json() == {"ok": True, "next": "/"}   # not "Your session expired"
    assert core.list_web_users() == [{"username": "nel"}]


def test_csrf_applies_uniformly_to_mode_create_requests(tmp_path):
    """Adversarial-review lesson (learned on the classic route, kept on the JSON
    one): a mode=create POST carrying a forged/stale CSRF token must get the
    same "session expired" message an ordinary login POST would, not skip
    straight to any create-specific text -- mode=create is not a lesser-checked
    request shape."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    cli.get("/login", environ_overrides={"REMOTE_ADDR": LAN})   # establishes a session/csrf we ignore
    r = cli.post("/api/login", environ_overrides={"REMOTE_ADDR": LAN},
                 json={"username": "mallory", "password": "pw123456",
                       "confirm": "pw123456", "mode": "create",
                       "csrf": "forged-token-not-in-session"})
    assert "expired" in r.get_json()["error"].lower()
    assert core.list_web_users() == [{"username": "alice"}]


def test_login_rate_limit_clears_on_success(tmp_path):
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    # 4 failures -- under the 5-fail threshold, so not locked out yet.
    for _ in range(4):
        body = _api_login(cli, {"username": "alice", "password": "wrong"},
                          remote_addr=LAN2)
        assert body["error"] == "Invalid username or password."
    # A correct login clears this address's counter.
    body = _api_login(cli, {"username": "alice", "password": "hunter2"},
                      remote_addr=LAN2)
    assert body == {"ok": True, "next": "/"}
    # Two MORE wrong attempts from the same address: if the counter had NOT been
    # cleared, the 4 old fails + these would cross the 5-fail threshold partway
    # through and the 2nd of these would show the lockout message instead of the
    # normal invalid-credentials one.
    for _ in range(2):
        body = _api_login(cli, {"username": "alice", "password": "wrong"},
                          remote_addr=LAN2)
        assert "too many failed attempts" not in body["error"].lower()
        assert body["error"] == "Invalid username or password."


# ---------------------------------------------------------------------------
# _safe_next() open-redirect guard (the `next` target /api/login echoes back
# for LoginPage.jsx's client-side navigate)
# ---------------------------------------------------------------------------
# Adversarial-review regression (2026-07-19): _safe_next() blocked a literal
# leading "//" (scheme-relative) and a literal backslash, but not an embedded
# TAB/CR/LF. On the classic route those control characters could survive into a
# Location header (Werkzeug's iri_to_uri strips them back out, turning
# "/\t/evil.example" into a literal "//evil.example" scheme-relative redirect;
# the \r/\n variants crashed redirect() into a 500). The JSON route has no
# Location header, but LoginPage.jsx navigates to the returned `next` verbatim
# -- so the exact same smuggled shapes must still be REJECTED server-side
# (fall back to "/"), or /api/login becomes the same open redirect one hop
# later. These assert _safe_next() still screens every shape.

def test_login_next_tab_bypass_no_longer_open_redirects(tmp_path):
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    body = _api_login(cli, {"username": "alice", "password": "hunter2",
                            "next": "/\t/evil.example.com"})
    assert body["ok"] is True
    assert body["next"] == "/", (
        "open redirect: tab-smuggled //-prefixed next was honored: {!r}".format(body["next"]))


def test_login_next_newline_bypass_no_longer_500s(tmp_path):
    core.add_or_update_web_user("alice", "hunter2")
    app = _client(tmp_path)
    for smuggled in ("/\n/evil.example.com", "/\r/evil.example.com"):
        cli = app.test_client()
        # _api_login itself asserts the 200 -- a crash/500 here fails loudly.
        body = _api_login(cli, {"username": "alice", "password": "hunter2",
                                "next": smuggled})
        assert body["ok"] is True, (
            "next={!r} must sign in cleanly, not error: got {!r}".format(smuggled, body))
        assert body["next"] == "/", (
            "open redirect: newline-smuggled //-prefixed next was honored: {!r}".format(body["next"]))


def test_login_next_plain_scheme_relative_still_blocked(tmp_path):
    """Baseline the reviews confirmed already worked -- guard against a future
    regression on the case that was never broken."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    body = _api_login(cli, {"username": "alice", "password": "hunter2",
                            "next": "//evil.example.com"})
    assert body["ok"] is True
    assert body["next"] == "/"


def test_login_next_normal_path_still_honored(tmp_path):
    """The guard must not collateral-damage the one real shape every caller
    actually produces: the front door's redirect(url_for('login',
    next=request.path)), which LoginPage.jsx folds into the POST body."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    body = _api_login(cli, {"username": "alice", "password": "hunter2",
                            "next": "/loom"})
    assert body == {"ok": True, "next": "/loom"}


def test_logout_clears_session(tmp_path):
    cli = _client(tmp_path).test_client()
    login_existing_client(cli, "alice", "hunter2")
    assert cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 200
    r = _logout(cli)
    assert r.get_json() == {"ok": True}
    assert cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 401


# ---------------------------------------------------------------------------
# _is_authorized_request() gate itself
# ---------------------------------------------------------------------------

def test_local_request_without_session_is_now_denied_too(tmp_path):
    """Login is required via every path, localhost hostname or IP included.
    Local (127.0.0.1) is NO LONGER
    trusted by default -- this is the direct behavioral flip of the old
    _is_local_request() bypass this test used to assert (see
    test_nonlocal_request_without_session_is_denied for the LAN-side twin of this
    same rule, which never changed)."""
    cli = _client(tmp_path).test_client()
    r = cli.get("/api/jobs")   # default test-client REMOTE_ADDR is 127.0.0.1
    assert r.status_code == 401
    assert r.get_json() == {"error": "authentication required"}


def test_nonlocal_request_without_session_is_denied(tmp_path):
    cli = _client(tmp_path).test_client()
    r = cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN})
    # The global front-door hook (moonglade_gallery.py's _enforce_front_door()) now denies
    # this before api_jobs()'s own body ever runs, with ONE standard JSON shape for
    # every /api/* route rather than api_jobs()'s old bespoke {"jobs": []} fallback --
    # see that hook's docstring for why a single shape replaced 43 bespoke ones.
    assert r.status_code == 401
    assert r.get_json() == {"error": "authentication required"}


def test_nonlocal_request_with_logged_in_session_is_authorized(tmp_path):
    cli = _client(tmp_path).test_client()
    login_existing_client(cli, "alice", "hunter2")
    r = cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code == 200


def test_logout_revokes_a_stolen_cookie_on_another_client(tmp_path):
    """A session cookie is a stateless, client-side signed value -- copying it to
    a second client (a network capture off plain-HTTP LAN traffic, a shared
    machine) must stop working the moment the real owner signs out, not just on
    the browser that clicked logout. Regression test for the adversarial-review
    finding that logout only ever called session.clear() (which can only ever
    affect the ONE client making that request) with nothing server-side to
    revoke the cookie itself -- fixed via a per-user sess_epoch, bumped on
    logout (POST /api/logout's default global scope) and re-checked by
    _is_authorized_request() on every request."""
    app = _client(tmp_path)
    victim = app.test_client()
    login_existing_client(victim, "alice", "hunter2")
    attacker = app.test_client()
    attacker.set_cookie("session", victim.get_cookie("session").value)
    assert attacker.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 200
    _logout(victim)
    r = attacker.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code == 401


def test_removed_user_loses_access_via_old_session(tmp_path):
    """--remove-web-user must invalidate any session already issued to that
    username immediately -- not just block future logins. Regression test for
    the adversarial-review finding that _is_authorized_request() only checked
    `session.get("user") is not None`, never re-validating that user against
    AUTH_USERS, so a session opened before removal kept full access forever."""
    cli = _client(tmp_path).test_client()
    login_existing_client(cli, "mallory", "hunter2")
    assert cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 200
    core.remove_web_user("mallory")
    r = cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code == 401


def test_password_change_revokes_old_session(tmp_path):
    """Changing a password (re-running --add-web-user for an existing username)
    must also invalidate sessions issued under the old password."""
    cli = _client(tmp_path).test_client()
    login_existing_client(cli, "alice", "old-pw")
    assert cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 200
    core.add_or_update_web_user("alice", "new-pw")
    r = cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code == 401


def test_login_rate_limit_race_does_not_grant_extra_guesses(tmp_path, monkeypatch):
    """TOCTOU regression: the old code read the lockout state, THEN ran the slow
    (unlocked) verify_web_user() call, THEN recorded the failure -- so N
    concurrent requests from one IP could all read 'not locked yet' while each
    was still inside its own slow verify call, buying N free guesses per lockout
    cycle instead of 5. Simulate the slow call with a real delay + real threads
    (not just sequential calls, which would never have exposed the race) and
    confirm the lockout still engages at the 5th failure, not later."""
    import threading
    import time as _time

    core.add_or_update_web_user("alice", "hunter2")
    # Each thread gets its OWN client (own session/cookie jar) from the SAME app.
    # A single shared test client is NOT thread-safe: concurrent GET+POST pairs on
    # one session race on the CSRF cookie, so some POSTs land with a token a sibling
    # already rotated and come back "session expired" -- neither Invalid nor locked,
    # which broke the count intermittently. The rate limiter is keyed by IP, not
    # session, so separate sessions from the same REMOTE_ADDR still share the
    # counter -- the concurrency race under test is intact; only the incidental
    # CSRF cross-talk is removed.
    app = _client(tmp_path)
    real_verify = core.verify_web_user

    def slow_verify(username, password):
        _time.sleep(0.15)
        return real_verify(username, password)
    monkeypatch.setattr(core, "verify_web_user", slow_verify)

    N = 10
    results = [None] * N

    def attempt(i):
        cli = app.test_client()
        body = _api_login(cli, {"username": "alice", "password": "wrong-{}".format(i)},
                          remote_addr=LAN)
        results[i] = body.get("error", "")

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # However the burst interleaves, no more than 5 of these N concurrent guesses
    # may ever have been evaluated as "Invalid" -- the rest must observe the
    # lockout message once 5 failures land, even though every one of them started
    # before any single one finished.
    invalid_count = sum(1 for err in results if err and "Invalid username or password" in err)
    locked_count = sum(1 for err in results if err and "too many failed attempts" in err.lower())
    assert invalid_count <= 5
    assert invalid_count + locked_count == N


def test_empty_auth_users_makes_lan_login_impossible(tmp_path):
    """No AUTH_USERS configured (the default) -- there is no backdoor account, so a
    plain (non-create) sign-in attempt always fails, with any username/password."""
    cli = _client(tmp_path).test_client()
    body = _api_login(cli, {"username": "admin", "password": "admin"})
    assert body["error"] == "Invalid username or password."
    assert cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 401


# ---------------------------------------------------------------------------
# Front-door coverage: every route a prior adversarial review found reachable
# with ZERO auth check of any kind (see _enforce_front_door()'s docstring in
# moonglade_gallery.py) must be denied for an unauthenticated, non-local
# request. This is the direct proof that the global gate (replacing 43
# scattered per-route checks, and closing these routes that had never had one at
# all) actually did what it was built for -- not just architectural confidence.
# Classic cut, 2026-08-08: the dead classic pages/form routes left these lists;
# where a form route's SUBJECT moved to a surviving JSON route (/rate ->
# /api/rate, /delete-bulk -> /api/delete-local, /collection-add|remove ->
# /api/collection, /bulk-replace-prompt -> /api/replace-prompts, /delete/<id> ->
# /api/delete-image), the gate coverage moved with it.
#
# /api/gallery-images has its own, more thorough test in test_web_pick.py
# (test_gallery_images_requires_login_over_lan_but_then_works) since it also
# proves the LAN request works again once logged in -- not duplicated here.
# ---------------------------------------------------------------------------

# Routes whose contract is JSON: the front door answers 401 + the standard
# {"error": "authentication required"} body (see _enforce_front_door()).
_PREVIOUSLY_UNGATED_JSON_GET = [
    "/api/similar/does-not-exist",
    "/api/collections",
    "/api/contests",
    "/api/achievements",
    "/api/your-art",
    "/api/loom/export-status",
    "/api/loom/export-file",
    "/api/ping",
]
_PREVIOUSLY_UNGATED_JSON_POST = [
    "/api/rate/does-not-exist",
    "/api/edit-prompt/does-not-exist",
    "/api/skin",
    "/api/ach-event",
    # The surviving JSON counterparts of the cut classic form routes -- the
    # subjects (delete/collect/replace) moved here, so the gate proof does too.
    "/api/delete-image",
    "/api/delete-local",
    "/api/delete-tasks",
    "/api/collection",
    "/api/replace-prompts",
]

# Routes whose contract is an HTML page or a raw asset: the front door redirects
# to /login?next=<path> instead (see _enforce_front_door()).
_PREVIOUSLY_UNGATED_HTML_GET = [
    "/",
    "/contact-sheet",
    "/thumbs/does-not-exist.jpg",
    "/video-file/does-not-exist",
    "/full/does-not-exist",
    "/badge-thumb/does-not-exist.png",
]
_PREVIOUSLY_UNGATED_HTML_POST = [
    "/export-zip",
]


@pytest.mark.parametrize("path", _PREVIOUSLY_UNGATED_JSON_GET)
def test_previously_ungated_json_get_route_now_denied(tmp_path, path):
    cli = _client(tmp_path).test_client()
    r = cli.get(path, environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code == 401
    assert r.get_json() == {"error": "authentication required"}


@pytest.mark.parametrize("path", _PREVIOUSLY_UNGATED_JSON_POST)
def test_previously_ungated_json_post_route_now_denied(tmp_path, path):
    cli = _client(tmp_path).test_client()
    r = cli.post(path, environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code == 401
    assert r.get_json() == {"error": "authentication required"}


@pytest.mark.parametrize("path", _PREVIOUSLY_UNGATED_HTML_GET)
def test_previously_ungated_html_get_route_now_redirects_to_login(tmp_path, path):
    cli = _client(tmp_path).test_client()
    r = cli.get(path, environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code in (301, 302, 303, 307, 308)
    assert r.headers["Location"].startswith("/login")


@pytest.mark.parametrize("path", _PREVIOUSLY_UNGATED_HTML_POST)
def test_previously_ungated_html_post_route_now_redirects_to_login(tmp_path, path):
    cli = _client(tmp_path).test_client()
    r = cli.post(path, environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code in (301, 302, 303, 307, 308)
    assert r.headers["Location"].startswith("/login")


@pytest.mark.parametrize("path", _PREVIOUSLY_UNGATED_JSON_GET + _PREVIOUSLY_UNGATED_HTML_GET)
def test_previously_ungated_get_route_now_denied_from_localhost_too(tmp_path, path):
    """The loopback bypass is retired entirely -- localhost is
    NOT special anymore, so every one of these previously-fully-ungated routes must
    deny an anonymous LOCAL request (default test-client REMOTE_ADDR=127.0.0.1)
    exactly the same as the LAN-address versions above
    (test_previously_ungated_json_get_route_now_denied /
    test_previously_ungated_html_get_route_now_redirects_to_login). This is the
    direct behavioral flip of what this test used to assert (that localhost was
    always exempt) -- proving the bypass's removal actually took effect everywhere,
    not just for routes exercised via an explicit LAN REMOTE_ADDR override."""
    cli = _client(tmp_path).test_client()
    r = cli.get(path)   # default test-client REMOTE_ADDR is 127.0.0.1 -- deliberately no override
    if path in _PREVIOUSLY_UNGATED_JSON_GET:
        assert r.status_code == 401
        assert r.get_json() == {"error": "authentication required"}
    else:
        assert r.status_code in (301, 302, 303, 307, 308)
        assert r.headers["Location"].startswith("/login")


@pytest.mark.parametrize("remote_addr", [LAN, "127.0.0.1"])
def test_branding_stays_public_unauthenticated(tmp_path, remote_addr):
    """Unlike every other previously-ungated route above, /branding/ was
    deliberately put back on the public allowlist (see _PUBLIC_PREFIXES in
    _enforce_front_door()): it's static cosmetic art, not gallery content, and
    the login page itself needs it to render for a not-yet-authenticated
    visitor. A missing file still 404s (never redirects to /login) from LAN
    or localhost, with or without a session."""
    cli = _client(tmp_path).test_client()
    r = cli.get("/branding/does-not-exist.png", environ_overrides={"REMOTE_ADDR": remote_addr})
    assert r.status_code == 404
