"""Session-epoch revocation: the state model, the authorization, and the concurrency.

Three separate defects were found in this one mechanism -- by two independent
reviews plus a cloud pass -- and they were fixed as ONE change, because
spot-patching each in isolation is how you end up with a fourth. This file pins
all three. See pixai_gallery_backup._next_sess_epoch()'s docstring for the design.

  D1  The epoch lived only in the account record, so deleting an account destroyed
      the counter and re-creating the username reset it to 0 -- the exact value
      stale cookies already carry. The gate compared 0 == 0 and ALLOWED. That
      matters because remove-and-re-add is precisely the recovery an owner performs
      after a suspected cookie theft: the recovery step handed the cookie back.

  D2  /logout is public (the front door never runs on it) and app.secret_key
      persists, so an already-revoked cookie still DESERIALIZES. Without an auth
      check it stayed a valid "log this identity out" token forever -- replayed in
      a loop it kicked the real user off the instant they signed back in.

  D3  bump_web_user_session_epoch was the one AUTH_USERS writer doing its
      read-modify-write outside _accounts_lock -- a lost update in both directions.

THE REPLAY TRAP, which bit an earlier proof-of-concept and is worth reading before
touching anything here: _is_authorized_request() calls session.clear() on the stale
path, and logout() calls it unconditionally. Flask's test client PERSISTS the
resulting session-clearing Set-Cookie, so a client reused across replays stops
sending the stolen value after the first hit and the test passes for the WRONG
reason. Every replay below therefore uses a FRESH client seeded with the raw saved
cookie string.
"""
import re
import threading

import pixai_gallery_backup as core
from pixai_gallery import create_app

LAN = "203.0.113.5"


def _client(tmp_path):
    return create_app(tmp_path)


def _csrf(html):
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    assert m, "login page did not render a csrf hidden field"
    return m.group(1)


def _login(app, username="alice", password="hunter2"):
    cli = app.test_client()
    html = cli.get("/login").get_data(as_text=True)
    r = cli.post("/login", data={"username": username, "password": password,
                                 "csrf": _csrf(html)})
    assert r.status_code in (301, 302, 303, 307, 308), "login helper failed to authenticate"
    return cli


def _steal(cli):
    """Capture the raw session cookie value -- call BEFORE any logout."""
    c = cli.get_cookie("session")
    assert c is not None, "expected a session cookie to steal"
    return c.value


def _replay(app, stolen, path="/api/jobs"):
    cli = app.test_client()                 # FRESH client -- see the trap above
    cli.set_cookie("session", stolen)       # raw saved value, not a live cookie
    return cli.get(path, environ_overrides={"REMOTE_ADDR": LAN})


def _logout(cli, **extra):
    """Sign out the way the header's form does: a POST carrying this session's csrf
    token. Since the CSRF-able-GET fix, /logout's GET is a LOCAL sign-out only (it
    clears this client's cookie and writes nothing server-side), so every test in
    this file that is about REVOCATION has to use the POST or it asserts nothing.
    The token comes from the live session rather than a scraped page because
    _establish_session mints a FRESH one at login -- the token on the login page is
    already stale by the time the client is authenticated."""
    with cli.session_transaction() as sess:
        token = sess.get("csrf", "")
    return cli.post("/logout", data=dict({"csrf": token}, **extra))


def _replay_logout(app, stolen, token):
    """Replay a stolen cookie at /logout the way an attacker actually would: a POST
    carrying the csrf token that was baked into that same cookie. Flask's session
    cookie is signed but NOT encrypted, so a thief holding the cookie also holds its
    token -- the csrf field is no defence against this and was never meant to be.
    The _is_authorized_request() check inside logout() is (defect D2 above)."""
    cli = app.test_client()                 # FRESH client -- see the trap above
    cli.set_cookie("session", stolen)       # raw saved value, not a live cookie
    return cli.post("/logout", data={"csrf": token},
                    environ_overrides={"REMOTE_ADDR": LAN})


# --- D1: the epoch must never rewind ---------------------------------------

def test_recreated_account_does_not_resurrect_an_old_cookie(tmp_path):
    """The headline defect, on the CLI / add_or_update_web_user path."""
    core.add_or_update_web_user("alice", "hunter2")
    app = _client(tmp_path)
    victim = _login(app)
    stolen = _steal(victim)
    assert _replay(app, stolen).status_code == 200          # live
    _logout(victim)
    assert _replay(app, stolen).status_code == 401          # revoked
    core.remove_web_user("alice")                            # the exact owner
    core.add_or_update_web_user("alice", "hunter2")          # recovery action
    assert _replay(app, stolen).status_code == 401           # STAYS revoked


def test_recreated_account_via_panel_api_does_not_resurrect(tmp_path):
    """The same defect through add_web_user_if_new -- the path the Panel's Users
    tab actually uses. Fixing only the CLI writer leaves this fully live through
    the UI, and a suite covering just the other one looks entirely green."""
    # The account must be CREATED through add_web_user_if_new, not just re-created
    # through it. Seeding with add_or_update_web_user instead makes this test
    # decorative: that writer mints a high ticket, so the stolen cookie carries a
    # large value, and the bug's hardcoded 0 cannot collide with it. Verified by
    # re-introducing the defect and watching this test pass anyway.
    assert core.add_web_user_if_new("alice", "hunter2") is True
    app = _client(tmp_path)
    victim = _login(app)
    stolen = _steal(victim)
    _logout(victim)
    assert _replay(app, stolen).status_code == 401
    core.remove_web_user("alice")
    assert core.add_web_user_if_new("alice", "hunter2") is True
    assert _replay(app, stolen).status_code == 401


def test_legacy_config_remove_then_readd_under_new_code(tmp_path):
    """Pins Change 5's ORDERING. Fails if _next_sess_epoch() is called AFTER
    cfg["AUTH_USERS"] = new_users, because it scans that same list -- minting
    after the reassignment cannot see the departing account and loses its
    high-water mark. One of the three original design proposals had exactly that
    bug, and only reading its code caught it.

    The counter must ALREADY EXIST here and the departing account must sit ABOVE
    it. A legacy config (no counter) makes this test decorative, because the
    legacy margin then dominates: minting after the filter still returns ~1e6,
    which satisfies any 'greater than the old epoch' assertion and hides the
    ordering entirely. Verified by re-introducing the defect and watching the
    legacy-shaped version of this test pass anyway."""
    core.add_or_update_web_user("alice", "hunter2")
    cfg = core._load_config()
    cfg["AUTH_EPOCH_SEQ"] = 10                  # counter present -> no margin
    cfg["AUTH_USERS"][0]["sess_epoch"] = 500    # ... and alice sits well above it
    core._save_config(cfg)

    core.remove_web_user("alice")
    seq = core._load_config().get("AUTH_EPOCH_SEQ")
    # Correct: the scan sees alice's 500 while she is still in the list -> 501.
    # Buggy:   the scan runs after the filter, sees nobody -> 11, and every
    #          cookie alice ever held between 11 and 500 is resurrectable.
    assert seq is not None and seq > 500, \
        "removal must fold the departing epoch in BEFORE the record is dropped"

    core.add_or_update_web_user("alice", "hunter2")
    assert core.get_web_user_session_epoch("alice") > 500


def test_first_ticket_clears_the_legacy_range(tmp_path):
    """Guards the margin specifically -- deleting it is the single most likely
    'simplification' that silently re-opens D1, and it is the correction to the
    flaw ALL THREE original proposals shared.

    On a config written by the old code there is no counter, and a max-scan can
    only see accounts that STILL EXIST. If the compromised account was removed
    BEFORE the upgrade -- the likely ordering, since the upgrade IS the incident
    response -- its history is unrecoverable and tickets would walk 1, 2, 3...
    straight back through the range live stale cookies occupy."""
    cfg = core._load_config()
    cfg["AUTH_USERS"] = [{"username": "alice", "password_hash": "x", "sess_epoch": 7}]
    cfg.pop("AUTH_EPOCH_SEQ", None)
    core._save_config(cfg)
    core.add_or_update_web_user("bob", "hunter2-pw")
    assert core.get_web_user_session_epoch("bob") >= core._EPOCH_LEGACY_MARGIN


def test_epochs_are_unique_across_accounts(tmp_path):
    """Ticket semantics: epochs come from ONE install-wide counter, never a
    per-account one. Pins it so a future 'optimization' back to a record-local
    counter trips a test instead of silently reopening D1."""
    core.add_or_update_web_user("alice", "hunter2-pw")
    core.add_or_update_web_user("bob", "hunter2-pw")
    assert core.get_web_user_session_epoch("alice") != core.get_web_user_session_epoch("bob")


# --- D2: a revoked cookie must not retain the power to revoke ---------------

def test_dead_cookie_cannot_bump_epoch_via_logout(tmp_path):
    """Replaying a dead cookie at /logout must do nothing. The second half is the
    user-visible harm: without the fix the attacker kicks the victim off every
    time they sign back in, recoverable only by rotating AUTH_SECRET_KEY."""
    core.add_or_update_web_user("alice", "hunter2")
    app = _client(tmp_path)
    victim = _login(app)
    stolen = _steal(victim)
    with victim.session_transaction() as sess:
        token = sess["csrf"]                # the token baked INTO the stolen cookie
    _logout(victim)
    assert _replay(app, stolen).status_code == 401

    frozen = core.get_web_user_session_epoch("alice")
    for _ in range(5):
        _replay_logout(app, stolen, token)
    assert core.get_web_user_session_epoch("alice") == frozen, \
        "a revoked cookie must not be able to revoke"

    victim2 = _login(app)
    for _ in range(5):
        _replay_logout(app, stolen, token)
    assert victim2.get("/api/jobs").status_code == 200, \
        "the victim must stay signed in while a dead cookie is replayed"


def test_logout_still_revokes_every_outstanding_cookie(tmp_path):
    """The behaviour the auth check must NOT regress: signing out revokes every
    outstanding cookie for that identity, not just the browser that clicked --
    e.g. one captured off plain-HTTP LAN traffic beforehand. This is the entire
    point of the mechanism."""
    core.add_or_update_web_user("alice", "hunter2")
    app = _client(tmp_path)
    victim = _login(app)
    stolen = _steal(victim)
    other = _login(app)                       # a second, independent live session
    assert _replay(app, stolen).status_code == 200
    _logout(other)                            # signing out from ANOTHER browser
    assert _replay(app, stolen).status_code == 401


def test_anonymous_logout_is_still_a_noop(tmp_path):
    """A genuinely anonymous GET /logout stays a harmless response that touches no
    server state -- it must not mint, bump, or rewrite anything. It's a 200 page
    now, not a redirect (see test_logout_purges_cache_storage_client_side), but the
    purge must fire even here -- unconditional, same reasoning as the cookie clear
    it always did: whoever hits /logout should leave with a clean local cache."""
    core.add_or_update_web_user("alice", "hunter2")
    app = _client(tmp_path)
    before_epoch = core.get_web_user_session_epoch("alice")
    before_bytes = core._config_path().read_bytes()
    r = app.test_client().get("/logout")
    assert r.status_code == 200
    assert "caches.delete" in r.get_data(as_text=True)
    assert core.get_web_user_session_epoch("alice") == before_epoch
    assert core._config_path().read_bytes() == before_bytes


# --- D4: a GET must never write server state --------------------------------

def test_get_logout_signs_out_only_this_browser(tmp_path):
    """THE CSRF-able-GET fix. /logout's GET used to bump sess_epoch, so any page that
    got the owner to follow a cross-site link -- or any link-prefetcher walking the
    header -- signed them out on every device. SESSION_COOKIE_SAMESITE="Lax" blocks
    the <img src=".../logout"> version of that (a cross-site subresource carries no
    cookie) but deliberately still sends the cookie on a top-level GET navigation.

    A GET must now clear THIS client's cookie and write nothing server-side.

    Bite: restore the bump on the GET path and both of the last two assertions fail."""
    core.add_or_update_web_user("alice", "hunter2")
    app = _client(tmp_path)
    victim = _login(app)
    other = _login(app)                       # the owner's phone, still signed in
    before_epoch = core.get_web_user_session_epoch("alice")

    r = victim.get("/logout")
    assert r.status_code == 200
    assert victim.get("/api/jobs").status_code == 401     # this browser IS signed out
    assert other.get("/api/jobs").status_code == 200, \
        "a GET /logout must not sign the user out on their other devices"
    assert core.get_web_user_session_epoch("alice") == before_epoch


def test_logout_purges_cache_storage_client_side(tmp_path):
    """A redirect can't run script, so a bare redirect() can never clear Cache
    Storage -- the browser-side cache /sw.js fills under /img/ and /full/, which
    outlives sign-out because nothing else purges it (docs/AUDIT_2026-07-21.md's
    Cache-Storage-survives-sign-out item). /logout must instead serve a real page
    that deletes every cache before navigating on to /login -- proven here for
    both the GET and the real, CSRF-carrying POST path, since either one is a
    genuine completed sign-out.

    Bite: revert to redirect(url_for('login')) and both assertions fail --
    there is no HTML body to search for the purge script in."""
    core.add_or_update_web_user("alice", "hunter2")
    app = _client(tmp_path)

    r_get = app.test_client().get("/logout")
    body_get = r_get.get_data(as_text=True)
    assert "caches.keys()" in body_get and "caches.delete" in body_get
    assert "/login" in body_get, "must still land the browser on /login, same as the old redirect did"
    # A plain, always-visible <a href="/login"> is the escape hatch for a browser
    # whose extension/CSP blocks the inline <script> specifically -- <noscript>
    # alone only engages when scripting is off ENTIRELY, so it does not cover that
    # case. Without this link, that reader is stranded with no purge and no way on.
    assert 'href="/login"' in body_get, \
        "no visible fallback link -- a page whose script gets blocked (but not scripting overall) strands the reader"

    victim = _login(app)
    r_post = _logout(victim)   # the real POST path, csrf token + all
    body_post = r_post.get_data(as_text=True)
    assert r_post.status_code == 200
    assert "caches.delete" in body_post


def test_refused_logout_does_not_purge_the_cache(tmp_path):
    """A bad-CSRF POST leaves the session INTACT (see
    test_post_logout_without_a_valid_csrf_token_revokes_nothing) -- it must not
    purge the browser's cache either, since nothing about the sign-out actually
    happened. Purging here would be a false "you're signed out" signal to a user
    who is, in fact, still signed in."""
    core.add_or_update_web_user("alice", "hunter2")
    app = _client(tmp_path)
    victim = _login(app)
    r = victim.post("/logout", data={"csrf": "forged-token-not-in-session"})
    assert r.status_code == 400
    assert "caches.delete" not in r.get_data(as_text=True)


def test_post_logout_without_a_valid_csrf_token_revokes_nothing(tmp_path):
    """The POST carries the same session-bound token /login's form and the Panel's
    Users tab carry. A bad one is a loud 400 that leaves the session INTACT -- not a
    quiet downgrade to a local sign-out, which is how the global revoke would
    silently disappear if the header form ever stopped emitting the field."""
    core.add_or_update_web_user("alice", "hunter2")
    app = _client(tmp_path)
    victim = _login(app)
    other = _login(app)
    before_epoch = core.get_web_user_session_epoch("alice")

    r = victim.post("/logout", data={"csrf": "forged-token-not-in-session"})
    assert r.status_code == 400
    assert core.get_web_user_session_epoch("alice") == before_epoch
    assert victim.get("/api/jobs").status_code == 200, \
        "a refused logout must leave the user signed in, not half-signed-out"

    # ... and the real, token-carrying POST still revokes globally.
    _logout(victim)
    assert core.get_web_user_session_epoch("alice") != before_epoch
    assert other.get("/api/jobs").status_code == 401


def test_post_logout_scope_this_device_leaves_other_sessions_alone(tmp_path):
    """The split the fix introduces: an explicit scope=this-device POST signs out
    here only. Its ABSENCE means global -- a truncated or hand-built POST has to fail
    toward MORE revocation, never less."""
    core.add_or_update_web_user("alice", "hunter2")
    app = _client(tmp_path)
    victim = _login(app)
    other = _login(app)
    before_epoch = core.get_web_user_session_epoch("alice")

    _logout(victim, scope="this-device")
    assert victim.get("/api/jobs").status_code == 401
    assert other.get("/api/jobs").status_code == 200
    assert core.get_web_user_session_epoch("alice") == before_epoch


# --- D3: the bump must be lock-protected -----------------------------------

def test_concurrent_bump_and_add_do_not_lose_writes(tmp_path):
    """bump_web_user_session_epoch was the ONE AUTH_USERS writer doing its
    read-modify-write outside _accounts_lock. Interleaved with a concurrent
    account create that is a lost update in both directions: either the new
    account is erased from disk, or the epoch bump is lost -- and a lost bump
    means revocation silently no-ops and the stolen cookie stays live."""
    core.add_or_update_web_user("alice", "hunter2")
    n = 12
    start = threading.Barrier(n * 2)
    errors = []

    def bump():
        try:
            start.wait()
            core.bump_web_user_session_epoch("alice")
        except Exception as e:                    # pragma: no cover - diagnostic
            errors.append(e)

    def add(i):
        try:
            start.wait()
            core.add_web_user_if_new("user{}".format(i), "hunter2-pw")
        except Exception as e:                    # pragma: no cover - diagnostic
            errors.append(e)

    threads = ([threading.Thread(target=bump) for _ in range(n)] +
               [threading.Thread(target=add, args=(i,)) for i in range(n)])
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    names = {u["username"] for u in core.list_web_users()}
    missing = {"user{}".format(i) for i in range(n)} - names
    assert not missing, \
        "concurrent adds erased by an unlocked bump: {}".format(sorted(missing))


# --- migration + storage ----------------------------------------------------

def test_upgrade_from_legacy_config_does_not_log_anyone_out(tmp_path):
    """An owner pulling this update must not be logged out, and the READ path
    must not write. A legacy config carries a small int sess_epoch and no
    AUTH_EPOCH_SEQ; logging in and browsing has to just work."""
    core.add_or_update_web_user("alice", "hunter2")
    cfg = core._load_config()
    cfg["AUTH_USERS"][0]["sess_epoch"] = 3
    cfg.pop("AUTH_EPOCH_SEQ", None)
    core._save_config(cfg)
    app = _client(tmp_path)
    cli = _login(app)
    assert cli.get("/api/jobs").status_code == 200
    assert "AUTH_EPOCH_SEQ" not in core._load_config(), "the read path must not write"


def test_malformed_epoch_values_do_not_crash(tmp_path):
    """Hand-edited garbage must degrade, never crash a login. A non-int
    sess_epoch is ignored by the scan; a non-int counter re-applies the margin
    rather than falling back to 1, which would land inside the legacy range."""
    core.add_or_update_web_user("alice", "hunter2")
    cfg = core._load_config()
    cfg["AUTH_USERS"][0]["sess_epoch"] = "banana"
    cfg["AUTH_EPOCH_SEQ"] = "banana"
    core._save_config(cfg)
    core.add_or_update_web_user("bob", "hunter2-pw")
    assert core.get_web_user_session_epoch("bob") >= core._EPOCH_LEGACY_MARGIN


def test_unrelated_config_keys_survive_a_mint(tmp_path):
    """A mint rewrites config.json, which also holds the owner's real API key and
    the session signing key. Neither may be disturbed."""
    core.add_or_update_web_user("alice", "hunter2")
    cfg = core._load_config()
    cfg["PIXAI_API_KEY"] = "sk-do-not-touch"
    core._save_config(cfg)
    secret = core.get_or_create_secret_key()
    core.bump_web_user_session_epoch("alice")
    after = core._load_config()
    assert after["PIXAI_API_KEY"] == "sk-do-not-touch"
    assert after["AUTH_SECRET_KEY"] == secret


def test_save_config_leaves_no_temp_files(tmp_path):
    """_save_config is now an atomic tmp-write + os.replace. A successful write
    must leave no .tmp-* debris beside config.json."""
    core.add_or_update_web_user("alice", "hunter2")
    core.bump_web_user_session_epoch("alice")
    strays = list(core._config_path().parent.glob("config.json.tmp-*"))
    assert not strays, "atomic write left temp files behind: {}".format(strays)


def test_the_failure_that_locks_you_out_says_so(tmp_path):
    """Rate-limit off-by-one, found by a browser crawl: _login_try_acquire reserves the
    attempt up front and returns None so it may PROCEED -- correct, since a right
    password on the 5th try must still work -- but that meant the request which crossed
    the threshold rendered the ordinary "invalid username or password" and the user was
    locked WITHOUT BEING TOLD. They then retyped the correct password and were refused
    for 15 minutes with no idea why.

    The previous crawl never saw this because it stopped at four attempts.

    Five attempts remain genuinely available; only the message changes."""
    core.add_or_update_web_user("alice", "hunter2")
    app = _client(tmp_path)
    cli = app.test_client()
    seen = []
    for _ in range(5):
        html = cli.get("/login").get_data(as_text=True)
        r = cli.post("/login", data={"username": "alice", "password": "wrong",
                                     "csrf": _csrf(html)})
        seen.append(r.get_data(as_text=True))
    # first four: the ordinary message, and NOT a lockout claim
    for body in seen[:4]:
        assert "Invalid username or password" in body
        assert "Too many failed attempts" not in body
    # the fifth is the one that locks -- it must say so rather than lying
    assert "Too many failed attempts" in seen[4], (
        "the attempt that triggered the lockout still reported a plain bad password")
