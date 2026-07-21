"""Session-based web-gallery login auth: the auth pass that gates every
network-originated (non-localhost) request behind a login (see
pixai_gallery.py's _is_authorized_request() and /login /logout, and
pixai_gallery_backup.py's get_or_create_secret_key/add_or_update_web_user/
remove_web_user/verify_web_user/list_web_users).

NOT about PIXAI_API_KEY auth -- that's tests/test_auth.py. This file is about
the *web session* login that gates the gallery itself."""
import re
import sys

import pytest

import pixai_gallery_backup as core
from pixai_gallery import create_app


def _client(tmp_path):
    return create_app(tmp_path)


def _csrf(html):
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    assert m, "login page did not render a csrf hidden field"
    return m.group(1)


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
    monkeypatch.setattr(sys, "argv", ["pixai_gallery_backup.py", "--add-web-user"])
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
    monkeypatch.setattr(sys, "argv", ["pixai_gallery_backup.py", "--add-web-user"])
    import pytest
    with pytest.raises(SystemExit):
        core.main()
    assert core.list_web_users() == []


def test_cli_add_web_user_enforces_the_same_password_policy(tmp_path, monkeypatch):
    """The CLI is the documented recovery path, not a back door around the rules
    the web forms enforce -- a weak password must be refused here too."""
    monkeypatch.setattr("builtins.input", lambda prompt="": "alice")
    monkeypatch.setattr(core.getpass, "getpass", lambda prompt="": "1111")
    monkeypatch.setattr(sys, "argv", ["pixai_gallery_backup.py", "--add-web-user"])
    import pytest
    with pytest.raises(SystemExit):
        core.main()
    assert core.list_web_users() == []


def test_cli_remove_web_user_flag(tmp_path, monkeypatch):
    core.add_or_update_web_user("alice", "pw-a")
    core.add_or_update_web_user("bob", "pw-b")
    monkeypatch.setattr(sys, "argv",
                        ["pixai_gallery_backup.py", "--remove-web-user", "alice"])
    core.main()
    assert {u["username"] for u in core.list_web_users()} == {"bob"}


def test_cli_list_web_users_flag_runs_without_error(tmp_path, monkeypatch, capsys):
    core.add_or_update_web_user("alice", "pw-a")
    monkeypatch.setattr(sys, "argv", ["pixai_gallery_backup.py", "--list-web-users"])
    core.main()
    out = capsys.readouterr().out
    assert "alice" in out


# ---------------------------------------------------------------------------
# /login /logout routes
# ---------------------------------------------------------------------------

def test_login_page_renders_form_with_csrf(tmp_path):
    cli = _client(tmp_path).test_client()
    html = cli.get("/login").get_data(as_text=True)
    assert 'name="username"' in html and 'name="password"' in html
    assert _csrf(html)   # a token is present


def test_login_page_shows_bootstrap_form_locally_until_an_account_exists(tmp_path):
    """With zero AUTH_USERS configured (the fresh-clone default), a LOCAL request to
    /login gets a real, functional account-creation form (owner directive
    2026-07-19: "NO CLI first login bullshit... its why I built a fucking login
    screen in figma" -- design at static/_mockup_login_panel.html) -- never a
    banner pointing at --add-web-user. The bootstrap form (with its extra confirm
    field) disappears -- and the ordinary two-field sign-in form takes its place --
    the moment a real account exists."""
    cli = _client(tmp_path).test_client()
    html = cli.get("/login").get_data(as_text=True)
    assert "--add-web-user" not in html
    assert 'name="username"' in html and 'name="password"' in html
    assert 'name="confirm"' in html                          # bootstrap-only field
    assert 'name="mode" value="create"' in html
    core.add_or_update_web_user("alice", "hunter2")
    html2 = cli.get("/login").get_data(as_text=True)
    assert "--add-web-user" not in html2
    assert 'name="username"' in html2 and 'name="password"' in html2
    assert 'name="confirm"' not in html2                      # ordinary sign-in form now
    assert 'name="mode" value="create"' not in html2


def test_login_page_shows_safe_message_for_lan_request_when_no_accounts(tmp_path):
    """The exact same zero-accounts state, but requested from a LAN address, must
    NEVER show (or accept) the bootstrap form -- only a plain message with no CLI
    mention and no way to submit credentials. This is the race-condition guard's
    visible half; test_lan_direct_post_cannot_create_first_account below is the
    server-side enforcement half."""
    cli = _client(tmp_path).test_client()
    html = cli.get("/login", environ_overrides={"REMOTE_ADDR": LAN}).get_data(as_text=True)
    assert "--add-web-user" not in html
    assert 'name="username"' not in html and 'name="password"' not in html
    assert "No account has been set up yet" in html
    normalized = " ".join(html.lower().split())
    assert "create the first account from the server machine" in normalized
    # Once an account exists, a LAN request goes right back to the ordinary form.
    core.add_or_update_web_user("alice", "hunter2")
    html2 = cli.get("/login", environ_overrides={"REMOTE_ADDR": LAN}).get_data(as_text=True)
    assert 'name="username"' in html2 and 'name="password"' in html2
    assert "No account has been set up yet" not in html2


def test_bootstrap_treats_empty_or_missing_remote_addr_as_not_local(tmp_path):
    """Adversarial-review regression: _is_local_request() used to treat a
    missing/empty remote_addr as local (`ra in (..., "")`) -- a fail-OPEN
    default in a function that gates the first-account bootstrap form (and
    destructive Panel actions). It must now fail CLOSED: an empty or None
    remote_addr is refused exactly like a real LAN address in the
    zero-accounts state -- no account-creation form, no CLI mention, and a
    hand-crafted mode=create POST under the same condition is still refused
    server-side."""
    cli = _client(tmp_path).test_client()
    for blank in ("", None):
        html = cli.get("/login", environ_overrides={"REMOTE_ADDR": blank}).get_data(as_text=True)
        # The "no accounts, non-local" state renders NO form at all (see
        # LOGIN_HTML's {% elif no_accounts %} branch) -- so there is no
        # hidden csrf input to scrape; pull the one GET already stashed in
        # the session instead, same as test_lan_direct_post_cannot_create_first_account.
        assert 'name="mode" value="create"' not in html
        assert 'name="username"' not in html   # no ordinary sign-in form either
        assert "No account has been set up yet" in html
        with cli.session_transaction() as sess:
            csrf = sess["csrf"]
        r = cli.post("/login", environ_overrides={"REMOTE_ADDR": blank},
                     data={"username": "mallory", "password": "pw123456",
                           "confirm": "pw123456", "mode": "create", "csrf": csrf})
        assert "No account has been set up yet" in r.get_data(as_text=True)
    assert core.list_web_users() == []


def test_bootstrap_form_creates_account_and_logs_in_immediately(tmp_path):
    """The local bootstrap POST must both create the account AND establish a
    session in one step (redirect straight past a second login) -- the same
    session-setting path a normal /login POST uses (_establish_session)."""
    cli = _client(tmp_path).test_client()
    html = cli.get("/login").get_data(as_text=True)
    r = cli.post("/login", data={"username": "alice", "password": "hunter22",
                                 "confirm": "hunter22", "mode": "create",
                                 "csrf": _csrf(html)})
    assert r.status_code in (301, 302, 303, 307, 308)
    assert core.verify_web_user("alice", "hunter22")
    # The session this redirect set really did authenticate -- a LAN request
    # against the SAME client now succeeds.
    assert cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 200
    # And logging out + back in with the same credentials works normally --
    # bootstrap didn't leave the account in some special state.
    cli.get("/logout")
    assert cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 401
    html2 = cli.get("/login").get_data(as_text=True)
    r2 = cli.post("/login", data={"username": "alice", "password": "hunter22",
                                  "csrf": _csrf(html2)})
    assert r2.status_code in (301, 302, 303, 307, 308)
    assert cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 200


def test_bootstrap_form_validates_like_the_mock(tmp_path):
    """Mirror static/_mockup_login_panel.html's client-side validation, now enforced
    server-side: empty username, too-short password, mismatched confirm."""
    cli = _client(tmp_path).test_client()
    html = cli.get("/login").get_data(as_text=True)
    csrf = _csrf(html)
    r = cli.post("/login", data={"username": "", "password": "hunter22",
                                 "confirm": "hunter22", "mode": "create", "csrf": csrf})
    assert "Username is required" in r.get_data(as_text=True)
    html = cli.get("/login").get_data(as_text=True)
    r = cli.post("/login", data={"username": "alice", "password": "ab",
                                 "confirm": "ab", "mode": "create", "csrf": _csrf(html)})
    assert "at least 8 characters" in r.get_data(as_text=True)
    html = cli.get("/login").get_data(as_text=True)
    r = cli.post("/login", data={"username": "alice", "password": "hunter22",
                                 "confirm": "totally-different", "mode": "create",
                                 "csrf": _csrf(html)})
    assert "Passwords do not match" in r.get_data(as_text=True)
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
    bootstrap form, since that is the path a first-run owner actually uses."""
    cli = _client(tmp_path).test_client()
    html = cli.get("/login").get_data(as_text=True)
    r = cli.post("/login", data={"username": "alice", "password": password,
                                 "confirm": password, "mode": "create",
                                 "csrf": _csrf(html)})
    assert expected in r.get_data(as_text=True)
    assert core.list_web_users() == []   # nothing was created


def test_password_policy_is_shared_by_login_and_users_tab(tmp_path):
    """Regression guard for the duplication that used to exist: the 4-character
    rule was written out separately in login() and api_users_add(), so tightening
    it in one place would silently leave the other weak. Both must now refuse the
    same password via the same core.password_problem()."""
    weak = "11111111"
    assert core.password_problem(weak)                    # the shared helper refuses it
    assert core.password_problem("a-valid-password") is None
    cli = _client(tmp_path).test_client()
    html = cli.get("/login").get_data(as_text=True)
    r = cli.post("/login", data={"username": "alice", "password": weak,
                                 "confirm": weak, "mode": "create",
                                 "csrf": _csrf(html)})
    assert "one character repeated" in r.get_data(as_text=True)
    assert core.list_web_users() == []


def test_bootstrap_form_missing_confirm_field_does_not_crash(tmp_path):
    """A malformed/short-circuited POST (e.g. a client that dropped the confirm
    field entirely, not just sent it empty) must be handled as a validation
    failure, never a 500."""
    cli = _client(tmp_path).test_client()
    html = cli.get("/login").get_data(as_text=True)
    r = cli.post("/login", data={"username": "alice", "password": "hunter22",
                                 "mode": "create", "csrf": _csrf(html)})
    assert r.status_code == 200
    assert "Passwords do not match" in r.get_data(as_text=True)
    assert core.list_web_users() == []


def test_lan_direct_post_cannot_create_first_account(tmp_path):
    """Defense in depth for the race guard: a hand-crafted mode=create POST from a
    LAN address must be refused even though it carries a technically-valid csrf
    token for ITS OWN session (nothing stops a LAN device from GETting /login and
    receiving one) -- the real gate is `bootstrap_mode` (no_accounts AND
    is_local), not csrf validity."""
    cli = _client(tmp_path).test_client()
    html = cli.get("/login", environ_overrides={"REMOTE_ADDR": LAN}).get_data(as_text=True)
    with cli.session_transaction() as sess:
        csrf = sess["csrf"]
    r = cli.post("/login", environ_overrides={"REMOTE_ADDR": LAN},
                 data={"username": "mallory", "password": "pw123456",
                       "confirm": "pw123456", "mode": "create", "csrf": csrf})
    assert r.status_code == 200
    assert "No account has been set up yet" in r.get_data(as_text=True)
    assert core.list_web_users() == []
    # And still refused with a session already logged in from elsewhere? No --
    # simpler and sufficient: confirm no account was ever created and the LAN
    # request never got authorized.
    assert cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 401


def test_direct_post_create_mode_ignored_once_an_account_exists(tmp_path):
    """A mode=create POST that arrives after the first account already exists
    (whether from local or LAN) must never be treated as account creation --
    bootstrap_mode is false the moment ANY account exists, from ANY path."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    html = cli.get("/login").get_data(as_text=True)
    r = cli.post("/login", data={"username": "mallory", "password": "pw123456",
                                 "confirm": "pw123456", "mode": "create",
                                 "csrf": _csrf(html)})
    assert "Invalid username or password" in r.get_data(as_text=True)
    assert {u["username"] for u in core.list_web_users()} == {"alice"}


def test_concurrent_add_or_update_web_user_does_not_lose_either_account(tmp_path, monkeypatch):
    """TOCTOU/lost-update regression: add_or_update_web_user() used to do an
    unlocked _load_config() -> mutate -> _save_config() -- two concurrent calls
    for DIFFERENT usernames could both read the pre-write state, so the second
    write would silently clobber the first's on disk (adversarial review,
    2026-07-19: reproduced live via two concurrent local /login bootstrap
    POSTs that both returned a 302 "success" redirect to their own browser,
    while only one of the two usernames actually ended up in AUTH_USERS).
    Force the interleaving with a real delay + real threads (not just
    sequential calls, which would never expose the race) and confirm
    _accounts_lock now serializes the two full read-modify-write cycles --
    BOTH accounts survive, regardless of which thread's write lands first."""
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


def test_login_success_sets_session_and_redirects(tmp_path):
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    html = cli.get("/login").get_data(as_text=True)
    r = cli.post("/login", data={"username": "alice", "password": "hunter2",
                                 "csrf": _csrf(html)})
    assert r.status_code in (301, 302, 303, 307, 308)
    # The session this redirect set now authorizes a LAN request that would
    # otherwise be refused -- proves session["user"] really got set, not just
    # that we got redirected.
    r2 = cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN})
    assert r2.status_code == 200


def test_login_failure_same_message_bad_user_and_bad_password(tmp_path):
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()

    html = cli.get("/login").get_data(as_text=True)
    r1 = cli.post("/login", data={"username": "alice", "password": "wrong-pw",
                                  "csrf": _csrf(html)})
    body1 = r1.get_data(as_text=True)

    html2 = cli.get("/login").get_data(as_text=True)
    r2 = cli.post("/login", data={"username": "nobody-at-all", "password": "hunter2",
                                  "csrf": _csrf(html2)})
    body2 = r2.get_data(as_text=True)

    assert "Invalid username or password" in body1
    assert "Invalid username or password" in body2
    # Never a field-specific hint like "no such user" / "wrong password" -- the
    # two failure modes (bad username vs. bad password) must be indistinguishable.
    for leaky in ("no such user", "unknown user", "user not found", "wrong password",
                  "incorrect password"):
        assert leaky not in body1.lower()
        assert leaky not in body2.lower()


def test_login_csrf_mismatch_rejected(tmp_path):
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    cli.get("/login")   # establishes a session + a real csrf token, which we deliberately ignore
    r = cli.post("/login", data={"username": "alice", "password": "hunter2",
                                 "csrf": "forged-token-not-in-session"})
    assert r.status_code == 200   # re-renders the form, does not log in
    assert "expired" in r.get_data(as_text=True).lower()
    # Confirm it truly did NOT log in: a LAN request is still refused.
    r2 = cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN})
    assert r2.status_code == 401


def test_incidental_get_does_not_invalidate_pending_csrf_token(tmp_path):
    """Real regression, reported directly by the owner: "CANT CREATE ACCOUNT --
    Stuck on Session Expired" even after clearing cookies and restarting the
    server. Root cause: the front door (_enforce_front_door()) redirects EVERY
    unauthenticated request to /login?next=<path> -- including background
    requests a browser fires the instant the page loads (favicon.ico, sw.js,
    manifest.webmanifest, /branding/* images before that route went public).
    Each of those landed on login()'s own GET branch, which used to
    unconditionally mint a FRESH session["csrf"] on every GET -- silently
    orphaning the token already rendered into the hidden input of whatever
    real, visible login/bootstrap form the human had open. The very next real
    submit then failed with "Your session expired," deterministically, no
    matter how many times cookies were cleared or the server restarted (the
    race re-fires on the very next page load). Reproduce exactly that
    sequence -- grab a token, let unrelated GETs land on /login in between
    (simulating the front door redirecting incidental asset requests here),
    then submit the ORIGINAL token -- and confirm it still works."""
    cli = _client(tmp_path).test_client()
    html = cli.get("/login").get_data(as_text=True)
    original_csrf = _csrf(html)
    # Simulate the front door redirecting a handful of incidental background
    # requests here (what favicon.ico/sw.js/manifest.webmanifest actually do)
    # before the human ever touches the visible form.
    cli.get("/login", query_string={"next": "/favicon.ico"})
    cli.get("/login", query_string={"next": "/sw.js"})
    cli.get("/login", query_string={"next": "/manifest.webmanifest"})
    r = cli.post("/login", data={
        "username": "nel", "password": "pw123456", "confirm": "pw123456",
        "mode": "create", "csrf": original_csrf})
    assert r.status_code == 302   # succeeds and redirects, not a re-rendered error form
    assert core.list_web_users() == [{"username": "nel"}]


def test_failed_post_still_rotates_csrf_token(tmp_path):
    """The fix must not throw out the OTHER half of the token lifecycle: a
    token that was just used in a failed POST (wrong password, bad create
    input, etc.) must still be rotated out from under a follow-up attempt --
    otherwise a consumed/known-bad token would stay silently resubmittable
    forever. Only GETs became "reuse the existing token"; a POST that falls
    through to any error must keep unconditionally minting a fresh one."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    html = cli.get("/login").get_data(as_text=True)
    csrf = _csrf(html)
    r1 = cli.post("/login", data={"username": "alice", "password": "wrong", "csrf": csrf})
    assert "Invalid username or password" in r1.get_data(as_text=True)
    # Reusing that SAME (now-stale) token again must be rejected as expired,
    # not silently accepted a second time.
    r2 = cli.post("/login", data={"username": "alice", "password": "hunter2", "csrf": csrf})
    assert "expired" in r2.get_data(as_text=True).lower()


def test_login_rate_limit_locks_out_after_five_failures(tmp_path):
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    for attempt in range(1, 6):
        html = cli.get("/login", environ_overrides={"REMOTE_ADDR": LAN}).get_data(as_text=True)
        r = cli.post("/login", environ_overrides={"REMOTE_ADDR": LAN},
                     data={"username": "alice", "password": "wrong",
                           "csrf": _csrf(html)})
        body = r.get_data(as_text=True)
        if attempt < 5:
            assert "Invalid username or password" in body
            assert "too many failed attempts" not in body.lower()
        else:
            # The 5th failure is the one that TRIPS the lock. It used to render the
            # ordinary "invalid password" text, so the user was locked out without
            # being told -- their next attempt looked like the same rejection for no
            # stated reason. The attempt itself is still spent (five real tries), only
            # the message changes.
            assert "too many failed attempts" in body.lower()
    # 6th attempt from the SAME address, even with the CORRECT password, is refused.
    html = cli.get("/login", environ_overrides={"REMOTE_ADDR": LAN}).get_data(as_text=True)
    r = cli.post("/login", environ_overrides={"REMOTE_ADDR": LAN},
                 data={"username": "alice", "password": "hunter2", "csrf": _csrf(html)})
    body = r.get_data(as_text=True)
    assert "too many failed attempts" in body.lower()
    r2 = cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN})
    assert r2.status_code == 401   # correct password during lockout still does not authorize


def test_lockout_applies_uniformly_to_mode_create_requests(tmp_path):
    """Adversarial-review regression: mode=create used to be checked BEFORE the
    lockout/CSRF gates, so a crafted mode=create POST from an already-locked-out
    address sailed through with neither the lockout message nor any CSRF
    requirement -- a mode=create POST is not a lesser-checked request shape.
    Lock out an address via 5 failed ORDINARY logins (an account already
    exists, so bootstrap_mode is false throughout -- mode=create can never
    succeed here regardless), then confirm a 6th request carrying mode=create
    from that SAME address gets the lockout message, not the create-specific
    "invalid" text."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    for _ in range(5):
        html = cli.get("/login", environ_overrides={"REMOTE_ADDR": LAN}).get_data(as_text=True)
        cli.post("/login", environ_overrides={"REMOTE_ADDR": LAN},
                 data={"username": "alice", "password": "wrong", "csrf": _csrf(html)})
    html = cli.get("/login", environ_overrides={"REMOTE_ADDR": LAN}).get_data(as_text=True)
    r = cli.post("/login", environ_overrides={"REMOTE_ADDR": LAN},
                 data={"username": "mallory", "password": "pw123456",
                       "confirm": "pw123456", "mode": "create", "csrf": _csrf(html)})
    assert "too many failed attempts" in r.get_data(as_text=True).lower()
    assert core.list_web_users() == [{"username": "alice"}]   # still refused, nothing created


def test_csrf_applies_uniformly_to_mode_create_requests(tmp_path):
    """Companion to the lockout regression above: a mode=create POST carrying a
    forged/stale CSRF token must get the same "session expired" message an
    ordinary login POST would, not skip straight to the create-specific
    "invalid" text."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    cli.get("/login", environ_overrides={"REMOTE_ADDR": LAN})   # establishes a session/csrf we ignore
    r = cli.post("/login", environ_overrides={"REMOTE_ADDR": LAN},
                 data={"username": "mallory", "password": "pw123456",
                       "confirm": "pw123456", "mode": "create",
                       "csrf": "forged-token-not-in-session"})
    assert "expired" in r.get_data(as_text=True).lower()
    assert core.list_web_users() == [{"username": "alice"}]


def test_login_rate_limit_clears_on_success(tmp_path):
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    # 4 failures -- under the 5-fail threshold, so not locked out yet.
    for _ in range(4):
        html = cli.get("/login", environ_overrides={"REMOTE_ADDR": LAN2}).get_data(as_text=True)
        cli.post("/login", environ_overrides={"REMOTE_ADDR": LAN2},
                 data={"username": "alice", "password": "wrong", "csrf": _csrf(html)})
    # A correct login clears this address's counter.
    html = cli.get("/login", environ_overrides={"REMOTE_ADDR": LAN2}).get_data(as_text=True)
    r = cli.post("/login", environ_overrides={"REMOTE_ADDR": LAN2},
                 data={"username": "alice", "password": "hunter2", "csrf": _csrf(html)})
    assert r.status_code in (301, 302, 303, 307, 308)
    # Two MORE wrong attempts from the same address: if the counter had NOT been
    # cleared, the 4 old fails + these would cross the 5-fail threshold partway
    # through and the 2nd of these would show the lockout message instead of the
    # normal invalid-credentials one.
    for _ in range(2):
        html = cli.get("/login", environ_overrides={"REMOTE_ADDR": LAN2}).get_data(as_text=True)
        r = cli.post("/login", environ_overrides={"REMOTE_ADDR": LAN2},
                     data={"username": "alice", "password": "wrong", "csrf": _csrf(html)})
        body = r.get_data(as_text=True)
        assert "too many failed attempts" not in body.lower()
        assert "Invalid username or password" in body


# ---------------------------------------------------------------------------
# _safe_next() open-redirect guard (the /login ?next= parameter)
# ---------------------------------------------------------------------------
# Adversarial-review regression (2026-07-19): _safe_next() blocked a literal
# leading "//" (scheme-relative) and a literal backslash, but not an embedded
# TAB/CR/LF. Werkzeug's own Response.get_wsgi_headers() strips those control
# characters back out of a Location header value (via iri_to_uri) before it
# hits the socket -- so "/\t/evil.example" sailed past the "//" check here,
# yet Werkzeug itself rewrote it into a literal "//evil.example" scheme-
# relative redirect handed to a user who just entered real credentials. The
# \r/\n variants didn't even reach a response: redirect() raised an
# unhandled ValueError ("Header values must not contain newline characters"),
# turning a real login into a 500. Both confirmed against the real /login
# flow before the fix; these assert neither happens now.

def test_login_next_tab_bypass_no_longer_open_redirects(tmp_path):
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    next_url = "/\t/evil.example.com"
    html = cli.get("/login", query_string={"next": next_url}).get_data(as_text=True)
    r = cli.post("/login", query_string={"next": next_url},
                 data={"username": "alice", "password": "hunter2", "csrf": _csrf(html)})
    assert r.status_code in (301, 302, 303, 307, 308)
    location = r.headers.get("Location") or ""
    assert not location.startswith("//"), (
        "open redirect: tab-smuggled //-prefixed next was honored: {!r}".format(location))


def test_login_next_newline_bypass_no_longer_500s(tmp_path):
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    for smuggled in ("/\n/evil.example.com", "/\r/evil.example.com"):
        html = cli.get("/login", query_string={"next": smuggled}).get_data(as_text=True)
        r = cli.post("/login", query_string={"next": smuggled},
                     data={"username": "alice", "password": "hunter2", "csrf": _csrf(html)})
        assert r.status_code in (301, 302, 303, 307, 308), (
            "next={!r} must redirect safely, not crash: got {}".format(smuggled, r.status_code))
        location = r.headers.get("Location") or ""
        assert not location.startswith("//"), (
            "open redirect: newline-smuggled //-prefixed next was honored: {!r}".format(location))


def test_login_next_plain_scheme_relative_still_blocked(tmp_path):
    """Baseline the reviews confirmed already worked -- guard against a future
    regression on the case that was never broken."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    next_url = "//evil.example.com"
    html = cli.get("/login", query_string={"next": next_url}).get_data(as_text=True)
    r = cli.post("/login", query_string={"next": next_url},
                 data={"username": "alice", "password": "hunter2", "csrf": _csrf(html)})
    assert r.status_code in (301, 302, 303, 307, 308)
    assert not (r.headers.get("Location") or "").startswith("//")


def test_login_next_normal_path_still_honored(tmp_path):
    """The fix must not collateral-damage the one real shape every caller
    actually produces: redirect(url_for('login', next=request.path))."""
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    html = cli.get("/login", query_string={"next": "/loom"}).get_data(as_text=True)
    r = cli.post("/login", query_string={"next": "/loom"},
                 data={"username": "alice", "password": "hunter2", "csrf": _csrf(html)})
    assert r.status_code in (301, 302, 303, 307, 308)
    assert r.headers.get("Location") == "/loom"


def test_logout_clears_session(tmp_path):
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    html = cli.get("/login").get_data(as_text=True)
    cli.post("/login", data={"username": "alice", "password": "hunter2", "csrf": _csrf(html)})
    assert cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 200
    cli.get("/logout")
    assert cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 401


# ---------------------------------------------------------------------------
# _is_authorized_request() gate itself
# ---------------------------------------------------------------------------

def test_local_request_without_session_is_now_denied_too(tmp_path):
    """Owner directive 2026-07-19: "I would expect to require login via any path with
    this new setup whether localhost hostname or IP." Local (127.0.0.1) is NO LONGER
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
    # The global front-door hook (pixai_gallery.py's _enforce_front_door()) now denies
    # this before api_jobs()'s own body ever runs, with ONE standard JSON shape for
    # every /api/* route rather than api_jobs()'s old bespoke {"jobs": []} fallback --
    # see that hook's docstring for why a single shape replaced 43 bespoke ones.
    assert r.status_code == 401
    assert r.get_json() == {"error": "authentication required"}


def test_nonlocal_request_with_logged_in_session_is_authorized(tmp_path):
    core.add_or_update_web_user("alice", "hunter2")
    cli = _client(tmp_path).test_client()
    html = cli.get("/login").get_data(as_text=True)
    cli.post("/login", data={"username": "alice", "password": "hunter2", "csrf": _csrf(html)})
    r = cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code == 200


def test_logout_revokes_a_stolen_cookie_on_another_client(tmp_path):
    """A session cookie is a stateless, client-side signed value -- copying it to
    a second client (a network capture off plain-HTTP LAN traffic, a shared
    machine) must stop working the moment the real owner signs out, not just on
    the browser that clicked logout. Regression test for the adversarial-review
    finding that /logout only ever called session.clear() (which can only ever
    affect the ONE client making that request) with nothing server-side to
    revoke the cookie itself -- fixed via a per-user sess_epoch, bumped on
    logout and re-checked by _is_authorized_request() on every request."""
    core.add_or_update_web_user("alice", "hunter2")
    app = _client(tmp_path)
    victim = app.test_client()
    html = victim.get("/login").get_data(as_text=True)
    victim.post("/login", data={"username": "alice", "password": "hunter2", "csrf": _csrf(html)})
    attacker = app.test_client()
    attacker.set_cookie("session", victim.get_cookie("session").value)
    assert attacker.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 200
    victim.get("/logout")
    r = attacker.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code == 401


def test_removed_user_loses_access_via_old_session(tmp_path):
    """--remove-web-user must invalidate any session already issued to that
    username immediately -- not just block future logins. Regression test for
    the adversarial-review finding that _is_authorized_request() only checked
    `session.get("user") is not None`, never re-validating that user against
    AUTH_USERS, so a session opened before removal kept full access forever."""
    core.add_or_update_web_user("mallory", "hunter2")
    cli = _client(tmp_path).test_client()
    html = cli.get("/login").get_data(as_text=True)
    cli.post("/login", data={"username": "mallory", "password": "hunter2", "csrf": _csrf(html)})
    assert cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 200
    core.remove_web_user("mallory")
    r = cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code == 401


def test_password_change_revokes_old_session(tmp_path):
    """Changing a password (re-running --add-web-user for an existing username)
    must also invalidate sessions issued under the old password."""
    core.add_or_update_web_user("alice", "old-pw")
    cli = _client(tmp_path).test_client()
    html = cli.get("/login").get_data(as_text=True)
    cli.post("/login", data={"username": "alice", "password": "old-pw", "csrf": _csrf(html)})
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
    # A single shared test client is NOT thread-safe: 10 concurrent GET+POST pairs on
    # one session race on the CSRF cookie, so some POSTs land with a token a sibling
    # already rotated and come back "session expired" -- neither Invalid nor locked,
    # which broke the `== N` count intermittently (green locally, red on CI's timing).
    # The rate limiter is keyed by IP, not session, so separate sessions from the same
    # REMOTE_ADDR still share the counter -- the concurrency race under test is intact;
    # only the incidental CSRF cross-talk is removed.
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
        html = cli.get("/login", environ_overrides={"REMOTE_ADDR": LAN}).get_data(as_text=True)
        r = cli.post("/login", environ_overrides={"REMOTE_ADDR": LAN},
                     data={"username": "alice", "password": "wrong-{}".format(i),
                           "csrf": _csrf(html)})
        results[i] = r.get_data(as_text=True)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # However the burst interleaves, no more than 5 of these N concurrent guesses
    # may ever have been evaluated as "Invalid" -- the rest must observe the
    # lockout message once 5 failures land, even though every one of them started
    # before any single one finished.
    invalid_count = sum(1 for body in results if "Invalid username or password" in body)
    locked_count = sum(1 for body in results if "too many failed attempts" in body.lower())
    assert invalid_count <= 5
    assert invalid_count + locked_count == N


def test_empty_auth_users_makes_lan_login_impossible(tmp_path):
    """No AUTH_USERS configured (the default) -- there is no backdoor account, so a
    LAN login attempt always fails, with any username/password."""
    cli = _client(tmp_path).test_client()
    html = cli.get("/login").get_data(as_text=True)
    r = cli.post("/login", data={"username": "admin", "password": "admin",
                                 "csrf": _csrf(html)})
    assert "Invalid username or password" in r.get_data(as_text=True)
    assert cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 401


# ---------------------------------------------------------------------------
# Front-door coverage: every route a prior adversarial review found reachable
# with ZERO auth check of any kind (see _enforce_front_door()'s docstring in
# pixai_gallery.py for the full list) must now be denied for an unauthenticated,
# non-local request. This is the direct proof that the global gate (replacing 43
# scattered per-route checks, and closing these routes that had never had one at
# all) actually did what it was built for -- not just architectural confidence.
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
    "/rate/does-not-exist",
    "/edit-prompt/does-not-exist",
    "/api/skin",
    "/api/ach-event",
]

# Routes whose contract is an HTML page or a raw asset: the front door redirects
# to /login?next=<path> instead (see _enforce_front_door()).
_PREVIOUSLY_UNGATED_HTML_GET = [
    "/",
    "/image/does-not-exist",
    "/panel",
    "/duplicates",
    "/health",
    "/contact-sheet",
    "/thumbs/does-not-exist.jpg",
    "/img/does-not-exist.png",
    "/video-file/does-not-exist",
    "/full/does-not-exist",
    "/badge-thumb/does-not-exist.png",
    # /manifest.webmanifest left this list on 2026-07-21 -- it went public, like
    # /branding/ before it, and has its own carve-out test below. /sw.js stays:
    # serving the worker script is a separate decision from serving the manifest,
    # because the worker CACHES, and cache-survives-sign-out is unsettled.
    "/sw.js",
]
_PREVIOUSLY_UNGATED_HTML_POST = [
    "/delete/does-not-exist",
    "/delete-bulk",
    "/collection-add",
    "/collection-remove",
    "/bulk-replace-prompt",
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
    """Owner directive 2026-07-19 retired the loopback bypass entirely -- localhost is
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


@pytest.mark.parametrize("remote_addr", [LAN, "127.0.0.1"])
def test_manifest_stays_public_unauthenticated(tmp_path, remote_addr):
    """The second deliberate carve-out, added 2026-07-21 on the same reasoning as
    /branding/ above: the manifest handler returns a compile-time CONSTANT -- app
    name, start_url, two hex colours, an inline data: URI icon. No user data, no
    catalog, no install path, nothing to withhold. And /login is itself public and
    identifies this app far more loudly than a manifest could, so gating it bought
    no secrecy.

    What it DID buy was a self-inflicted bug. The browser requests this file on its
    own the moment the login page loads, and the front door answered with
    302 -> /login?next=/manifest.webmanifest -- the same incidental traffic that
    silently overwrote session["csrf"] and made every login attempt fail with "Your
    session expired" (see login()'s GET branch, which now uses setdefault). Letting
    the self-fired static assets through is what removes that whole category.

    Anonymous, from LAN or localhost, must get the real manifest -- never a redirect.
    """
    cli = _client(tmp_path).test_client()
    r = cli.get("/manifest.webmanifest", environ_overrides={"REMOTE_ADDR": remote_addr})
    assert r.status_code == 200, (
        "anonymous request for the manifest got {} -- if it redirected, the route "
        "fell back off _PUBLIC_PATHS".format(r.status_code))
    assert r.mimetype == "application/manifest+json"
    body = r.get_json(force=True)   # force=: the mimetype is manifest+json, not application/json
    assert body["name"] == "Moonglade Athenaeum"
    # The point of the carve-out is that this body is a CONSTANT. If a future edit
    # starts folding real state into it (a username, the out_dir, a catalog count),
    # the public tier stops being free and this assertion is where that gets caught.
    assert set(body) == {"name", "short_name", "start_url", "display",
                         "background_color", "theme_color", "icons"}, (
        "the manifest grew a new key -- it is served ANONYMOUSLY now, so re-check that "
        "whatever was added carries no user, install or credential detail before "
        "widening this assertion.")
