"""
moonglade/web_accounts.py
=========================
The web gallery's login accounts: the session secret, password and username rules, adding,
changing and removing a login (with the guarded forms the Panel's Users tab uses), the session
epochs that sign a login out everywhere, the timing-safe check, and the command line's
--add-web-user / --remove-web-user / --list-web-users runners. Moved verbatim out of
moonglade/backup.py in the 3.22 split (phase 4).

`_accounts_lock` stays in the engine, so every writer of AUTH_USERS (these, the gallery's key
save and the migration) serializes on one lock: it is imported from moonglade.backup inside
each function that takes it, at call time, as are `_load_config` and `_save_config`, so a
test's patch of backup's binding still reaches them and importing this module never imports
the engine.
"""
import getpass
import secrets
import sys

from moonglade import paths as _paths
# ---------------------------------------------------------------------------
# Web gallery login accounts -- session-based auth for moonglade/gallery.py's Flask
# app (gates EVERY request, local or remote -- there is no localhost bypass; see
# _is_authorized_request() there).
# Stored in config.json (the existing convention for secrets -- it already holds
# PIXAI_API_KEY): AUTH_SECRET_KEY signs the Flask session cookie, AUTH_USERS is a
# list of {"username", "password_hash"} (werkzeug.security -- scrypt as of modern
# werkzeug, timing-safe compare built in; no new pip install, werkzeug already
# ships with Flask). Account lifecycle used to be CLI-only; as of the web-based
# bootstrap + Panel Users tab (2026-07-19) it's also reachable from the browser
# (see moonglade/gallery.py's /login bootstrap POST and /api/users/add|remove) --
# --add-web-user / --remove-web-user / --list-web-users remain a valid recovery
# path. If AUTH_USERS is empty, logging in from the LAN is simply impossible --
# there is no default/backdoor account, ever.
#

# How every NEW web-login password hash is made (werkzeug's generate_password_hash method):
# scrypt at werkzeug's own default cost. A module-level name for one reason: the test suite
# swaps it for a token scrypt cost on its throwaway accounts (dev/tests/conftest.py), since a
# real hash takes about a tenth of a second per account made and per sign-in checked, and most
# of the suite signs in. check_password_hash reads the cost back out of each stored hash, so
# this decides only how new hashes are made. Never lower it here:
# dev/tests/test_web_auth.py holds the shipped value to full strength.
WEB_PASSWORD_HASH_METHOD = "scrypt"

def get_or_create_secret_key():
    """Return config.json's AUTH_SECRET_KEY, generating + persisting a fresh
    secrets.token_hex(32) the first time this ever runs. Persisting it is what lets
    Flask sessions (and therefore logins) survive a server restart -- without this,
    every restart would silently log everyone out, which is a usability bug, not
    just a security nitpick."""
    from moonglade.backup import _load_config, _save_config
    cfg = _load_config()
    key = (cfg.get("AUTH_SECRET_KEY") or "").strip()
    if key:
        return key
    key = secrets.token_hex(32)
    cfg["AUTH_SECRET_KEY"] = key
    try:
        _save_config(cfg)
    except OSError as e:
        print("Warning: could not persist AUTH_SECRET_KEY to config.json: {}. "
              "Sessions will not survive a restart this run.".format(e))
    return key


def _find_web_user(cfg, username):
    for u in (cfg.get("AUTH_USERS") or []):
        if isinstance(u, dict) and u.get("username") == username:
            return u
    return None


_EPOCH_SEQ_KEY = "AUTH_EPOCH_SEQ"
# Applied ONCE, when config.json has never carried AUTH_EPOCH_SEQ. See below -- this
# constant is the fix, not a tuning knob.
_EPOCH_LEGACY_MARGIN = 1_000_000


def _next_sess_epoch(cfg):
    """Return the next install-wide session-epoch ticket, stamping it into `cfg`.

    MUST be called with `_accounts_lock` ALREADY HELD, and with `cfg` a config dict
    the caller is about to _save_config(). It deliberately takes NO lock and does NO
    I/O of its own -- precisely so its callers, every one of which already holds the
    NON-REENTRANT _accounts_lock, cannot self-deadlock. A new caller must already
    hold the lock.

    WHY THE COUNTER IS INSTALL-WIDE AND NOT PER-ACCOUNT: a counter stored in the
    account record dies with the account. Removing and re-creating a username reset
    sess_epoch to 0 -- the exact value stale cookies already carry -- so
    _is_authorized_request() compared 0 == 0 and ALLOWED. Remove-and-re-add is
    precisely the recovery an owner performs after a suspected cookie theft, which
    made the recovery step itself un-revoke every cookie ever issued to that name.

    WHY THE MARGIN (do NOT "simplify" this away -- removing it silently re-opens the
    defect): on a config written by the previous code there is no AUTH_EPOCH_SEQ, and
    the max-scan below can only see accounts that STILL EXIST. If the owner removed
    the compromised account and THEN upgraded -- the likely ordering, since the
    upgrade is the response to the incident -- that account's epoch history is gone,
    the scan returns only the survivors' small values, and the first tickets walk
    1, 2, 3... straight back through the stale cookies' range. Jumping clear of the
    whole legacy range on first mint closes that without needing to see the deleted
    account. Live legacy cookies carry small ints, so the jump logs nobody out.

    The max-scan is kept too, and is self-healing: if config.json is hand-edited so a
    user's sess_epoch exceeds the counter, the next ticket still clears it."""
    seeded = _EPOCH_SEQ_KEY in cfg
    try:
        highest = int(cfg.get(_EPOCH_SEQ_KEY, 0) or 0)
    except (TypeError, ValueError):
        highest = 0
        seeded = False
    if not seeded:
        highest = max(highest, _EPOCH_LEGACY_MARGIN)
    for u in (cfg.get("AUTH_USERS") or []):
        if isinstance(u, dict):
            try:
                highest = max(highest, int(u.get("sess_epoch", 0)))
            except (TypeError, ValueError):
                pass          # hand-edited garbage -> ignore, never crash a login
    nxt = highest + 1
    cfg[_EPOCH_SEQ_KEY] = nxt
    return nxt


def list_web_users():
    """Return [{"username": ...}, ...] from config.json's AUTH_USERS -- USERNAMES
    ONLY, never password hashes. Used by --list-web-users."""
    from moonglade.backup import _accounts_lock, _load_config
    with _accounts_lock:
        cfg = _load_config()
        return [{"username": u["username"]} for u in (cfg.get("AUTH_USERS") or [])
                if isinstance(u, dict) and u.get("username")]


# --- Web-login password policy -------------------------------------------
# ONE source of truth, called by every path that can create an account: the
# first-run bootstrap form on /login, the Control Panel's Users tab, and the
# --add-web-user CLI recovery flag. It lives here, next to the account model,
# rather than in the web layer specifically so those three can't drift apart --
# the previous 4-character rule was duplicated across two call sites and would
# have had to be corrected in both.
#
# Deliberately shaped after NIST SP 800-63B: LENGTH is the control that matters,
# and composition rules ("must contain a symbol") are NOT enforced, because they
# measurably push people toward predictable mutations like "P@ssw0rd1" instead
# of toward real entropy. What we DO reject is the small set of passwords that
# stay trivially guessable at any length: one repeated character, a straight run
# off the keyboard, and the perennial favourites.
MIN_WEB_PASSWORD_LEN = 8

# Usernames are bounded so a pathological one can't wreck the account-list layout
# (a 300-char name pushed a live Remove button ~980px outside its card) or bloat
# config.json. 64 is generous for a display name yet safely short; the account row
# also truncates in CSS as a second line of defence for any legacy over-long name.
MAX_WEB_USERNAME_LEN = 64

_COMMON_PASSWORDS = frozenset({
    "password", "password1", "passw0rd", "12345678", "123456789", "1234567890",
    "qwertyui", "qwerty123", "letmein1", "welcome1", "iloveyou", "admin123",
    "administrator", "changeme", "trustno1", "sunshine", "princess", "football",
    "baseball", "superman", "dragon123", "monkey123", "abc12345", "starwars",
})


def _is_single_run(s):
    """True if `s` is one unbroken ascending or descending character run
    ("12345678", "abcdefgh", "87654321") -- a keyboard-walk shape long enough to
    sail past a length check while carrying almost no entropy."""
    if len(s) < 3:
        return False
    deltas = {ord(b) - ord(a) for a, b in zip(s, s[1:])}
    return deltas == {1} or deltas == {-1}


def password_problem(password):
    """Return a human-readable reason `password` is unacceptable for a web-login
    account, or None if it passes. Every caller renders the returned string to
    the user verbatim, so each one names what to do next, not just what's wrong."""
    pw = password or ""
    if len(pw) < MIN_WEB_PASSWORD_LEN:
        return "Password must be at least {} characters.".format(MIN_WEB_PASSWORD_LEN)
    if pw.lower() in _COMMON_PASSWORDS:
        return "That password is too common to be safe. Pick something less guessable."
    if len(set(pw)) == 1:
        return "Password can't be one character repeated. Pick something less guessable."
    if _is_single_run(pw.lower()):
        return ("Password can't be a single run of sequential characters. "
                "Pick something less guessable.")
    return None


def username_problem(username):
    """Return a human-readable reason `username` is unacceptable for a web-login
    account, or None if it passes. Mirrors password_problem(): one policy, rendered
    verbatim at every entry point (the /login bootstrap form, the Panel's
    /api/users/add, and --add-web-user), so the rule can't drift between them.
    Callers strip first; this assumes an already-stripped value but tolerates one."""
    u = (username or "").strip()
    if not u:
        return "Username is required."
    if len(u) > MAX_WEB_USERNAME_LEN:
        return "Username must be at most {} characters.".format(MAX_WEB_USERNAME_LEN)
    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in u):
        return "Username can't contain control characters."
    return None


def add_or_update_web_user(username, password):
    """Hash `password` (werkzeug, scrypt) and add/update `username` in config.json's
    AUTH_USERS. Only the hash ever touches disk -- the plaintext password passed in
    here is never written anywhere. Returns True if this replaced an existing
    account's password, False if the account is new.

    Also stamps/bumps `sess_epoch` -- see get_web_user_session_epoch()'s docstring
    for why: a password change must invalidate any session cookie issued under the
    old password immediately, not just future ones.

    The whole read-modify-write runs under `_accounts_lock` -- see that lock's
    docstring for the concurrent-bootstrap lost-update it closes."""
    from moonglade.backup import _accounts_lock, _load_config, _save_config
    from werkzeug.security import generate_password_hash
    username = (username or "").strip()
    if not username:
        raise ValueError("username must not be empty")
    # Hard backstop for EVERY writer, including the --add-web-user CLI path that
    # doesn't go through username_problem() -- length is enforced at the one place
    # the account actually gets written, so nothing can persist an over-long name.
    if len(username) > MAX_WEB_USERNAME_LEN:
        raise ValueError("username must be at most {} characters".format(MAX_WEB_USERNAME_LEN))
    if not password:
        raise ValueError("password must not be empty")
    with _accounts_lock:
        cfg = _load_config()
        users = cfg.get("AUTH_USERS") or []
        existing = _find_web_user(cfg, username)
        replaced = existing is not None
        # Ticket from the install-wide counter, never a per-account increment: see
        # _next_sess_epoch()'s docstring for why a record-local counter was the bug.
        next_epoch = _next_sess_epoch(cfg)
        new_users = [u for u in users if not (isinstance(u, dict) and u.get("username") == username)]
        new_users.append({"username": username,
                          "password_hash": generate_password_hash(
                              password, method=WEB_PASSWORD_HASH_METHOD),
                          "sess_epoch": next_epoch})
        cfg["AUTH_USERS"] = new_users
        _save_config(cfg)
        return replaced


def set_web_user_password_guarded(username, new_password, current_password=None):
    """Change an existing account's password. Returns "ok", "not_found" or "bad_current".

    ONE `_accounts_lock` acquisition covers the existence check, the current-password
    verification and the write. That is not stylistic: `remove_web_user_guarded`'s docstring
    records a TOCTOU race reproduced live against a real route when a read and a write were
    split across two acquisitions, and "verify the old password, then write the new one" is
    the same shape. Between a separate verify and write, a concurrent change could land and
    this call would happily overwrite it having validated against a password that no longer
    existed.

    `current_password=None` means DO NOT CHECK -- reserved for the caller that has already
    established the request came from the server machine. Passing a string means the check is
    mandatory and a mismatch returns "bad_current" without writing. There is deliberately no
    third mode: a caller either proves the old password or proves it is local, and the route
    (`/api/users/password`) is the only place that distinction is made.

    Unlike `add_or_update_web_user`, this REFUSES an unknown username instead of creating the
    account. A password reset for someone who does not exist is a mistake to report, not an
    invitation to mint them -- that update-or-add behaviour stays reserved for the CLI's
    deliberate recovery path.

    Bumps `sess_epoch` through the same install-wide counter every other writer uses, so a
    changed password invalidates session cookies issued under the old one immediately. Callers
    that want the CURRENT session to survive must re-issue its cookie afterwards; see
    /api/users/password, which does exactly that so a user changing their own password is not
    logged out of the browser they are standing in front of."""
    from moonglade.backup import _accounts_lock, _load_config, _save_config
    from werkzeug.security import generate_password_hash, check_password_hash
    username = (username or "").strip()
    if not username:
        raise ValueError("username must not be empty")
    if not new_password:
        raise ValueError("new password must not be empty")
    with _accounts_lock:
        cfg = _load_config()
        existing = _find_web_user(cfg, username)
        if existing is None:
            return "not_found"
        if current_password is not None:
            if not check_password_hash(existing.get("password_hash", ""), current_password or ""):
                return "bad_current"
        users = cfg.get("AUTH_USERS") or []
        next_epoch = _next_sess_epoch(cfg)
        new_users = [u for u in users
                     if not (isinstance(u, dict) and u.get("username") == username)]
        new_users.append({"username": username,
                          "password_hash": generate_password_hash(
                              new_password, method=WEB_PASSWORD_HASH_METHOD),
                          "sess_epoch": next_epoch})
        cfg["AUTH_USERS"] = new_users
        _save_config(cfg)
        return "ok"


def add_web_user_if_new(username, password):
    """Atomic check-and-add: like add_or_update_web_user(), but refuses outright
    (returns False, writes nothing) if `username` already exists, instead of
    resetting a stranger's password -- the whole "does it exist" check and the
    write happen under ONE `_accounts_lock` acquisition, so two concurrent
    requests trying to claim the same brand-new username can never both
    succeed. Used by the Panel's /api/users/add (moonglade/gallery.py); the plain
    add_or_update_web_user()'s update-or-add semantics stay reserved for the
    CLI's --add-web-user recovery case. Returns True if added, False if the
    username was already taken (nothing written)."""
    from moonglade.backup import _accounts_lock, _load_config, _save_config
    from werkzeug.security import generate_password_hash
    username = (username or "").strip()
    if not username:
        raise ValueError("username must not be empty")
    if len(username) > MAX_WEB_USERNAME_LEN:          # same backstop as add_or_update_web_user
        raise ValueError("username must be at most {} characters".format(MAX_WEB_USERNAME_LEN))
    if not password:
        raise ValueError("password must not be empty")
    with _accounts_lock:
        cfg = _load_config()
        if _find_web_user(cfg, username) is not None:
            return False
        users = cfg.get("AUTH_USERS") or []
        users.append({"username": username,
                      "password_hash": generate_password_hash(
                          password, method=WEB_PASSWORD_HASH_METHOD),
                      # The Panel's /api/users/add path -- the one an owner actually
                      # uses from a browser. Hardcoding 0 here left the resurrection
                      # defect fully live through the UI even with the CLI path fixed.
                      "sess_epoch": _next_sess_epoch(cfg)})
        cfg["AUTH_USERS"] = users
        _save_config(cfg)
        return True


def remove_web_user(username):
    """Remove `username` from config.json's AUTH_USERS. Returns True if an account
    was actually removed, False if no such username existed. Runs under
    `_accounts_lock` -- see that lock's docstring."""
    from moonglade.backup import _accounts_lock, _load_config, _save_config
    username = (username or "").strip()
    with _accounts_lock:
        cfg = _load_config()
        users = cfg.get("AUTH_USERS") or []
        new_users = [u for u in users if not (isinstance(u, dict) and u.get("username") == username)]
        removed = len(new_users) != len(users)
        if removed:
            # Advance the install-wide counter while the departing account is STILL
            # in cfg["AUTH_USERS"], so its epoch is folded into the high-water mark
            # before the record -- and therefore the evidence -- is destroyed.
            # Calling this AFTER the reassignment below silently re-opens the
            # resurrection defect, because _next_sess_epoch scans that same list.
            _next_sess_epoch(cfg)
            cfg["AUTH_USERS"] = new_users
            _save_config(cfg)
        return removed


def remove_web_user_guarded(username, min_remaining=1):
    """Atomic check-and-remove: refuses to remove `username` if doing so would
    leave fewer than `min_remaining` accounts, checked under the SAME
    `_accounts_lock` acquisition as the mutation itself -- closes a TOCTOU race
    where the Panel's /api/users/remove used to read list_web_users() (a
    "how many accounts are there" snapshot), THEN separately call
    remove_web_user() to mutate, with nothing stopping two concurrent removals
    of two DIFFERENT accounts from each observing "more than one left" via
    their own stale snapshot before either write landed, and both proceeding --
    reproduced live against the real Flask route (adversarial review,
    2026-07-19): exactly 2 accounts, two concurrent removes of two different
    usernames, both return 200 {"ok": true}, AUTH_USERS ends up empty --
    the self-lockout this guard exists to prevent, achieved anyway.

    Returns one of "removed", "not_found", "last_account"."""
    from moonglade.backup import _accounts_lock, _load_config, _save_config
    username = (username or "").strip()
    with _accounts_lock:
        cfg = _load_config()
        users = cfg.get("AUTH_USERS") or []
        if _find_web_user(cfg, username) is None:
            return "not_found"
        if len(users) <= min_remaining:
            return "last_account"
        _next_sess_epoch(cfg)     # BEFORE the filter -- see remove_web_user's comment
        cfg["AUTH_USERS"] = [u for u in users
                              if not (isinstance(u, dict) and u.get("username") == username)]
        _save_config(cfg)
        return "removed"


def get_web_user_session_epoch(username):
    """Current `sess_epoch` for `username`, or None if the account doesn't exist
    (e.g. removed via --remove-web-user). A session's cookie embeds the epoch that
    was current at login time; moonglade/gallery.py's _is_authorized_request()
    re-checks it against this on every request, so:
      - removing the account invalidates any outstanding session for it immediately
        (this returns None -> no epoch can ever match again), and
      - a sign-out everywhere (/api/logout with scope "everywhere") revokes every
        outstanding session for that identity (not just the browser that clicked it)
        by calling bump_web_user_session_epoch() before clearing its own session.
        A plain Log Out signs out only its own browser (#70).
    Without this, a stolen session cookie (plain-HTTP LAN, packet capture) would
    keep working after the legitimate user signs out everywhere or the account is removed,
    since the stock Flask session is a stateless, client-side signed cookie with
    nothing server-side to revoke -- see CHANGELOG.md for the fuller writeup."""
    from moonglade.backup import _load_config
    cfg = _load_config()
    user = _find_web_user(cfg, (username or "").strip())
    if user is None:
        return None
    return int(user.get("sess_epoch", 0))


def bump_web_user_session_epoch(username):
    """Issue `username` a fresh session-epoch ticket, invalidating every outstanding
    session cookie for that identity in one move (used by /api/logout's sign-out
    everywhere). No-op (returns
    False) if the account no longer exists.

    Runs the whole read-modify-write under `_accounts_lock`, like every OTHER
    AUTH_USERS writer. It previously did _load_config -> mutate -> _save_config
    entirely UNLOCKED -- the one writer that didn't -- which interleaved with a
    concurrent /api/users/add is a lost update in BOTH directions: either the newly
    created account is erased from disk, or the epoch bump is lost. A lost bump means
    revocation silently no-ops and the stolen cookie this function exists to kill
    stays live. Found by an independent cloud review, not by any test.

    _find_web_user returns the dict living inside cfg["AUTH_USERS"] (not a copy), so
    mutating it mutates cfg -- the previous implementation relied on this too."""
    from moonglade.backup import _accounts_lock, _load_config, _save_config
    username = (username or "").strip()
    with _accounts_lock:
        cfg = _load_config()
        user = _find_web_user(cfg, username)
        if user is None:
            return False
        user["sess_epoch"] = _next_sess_epoch(cfg)
        _save_config(cfg)
        return True


_dummy_hash_cache = {}


def _dummy_password_hash():
    """A real (valid-format) werkzeug hash of a password nobody will ever type,
    computed lazily and cached for this process. verify_web_user() runs a check
    against this for an UNKNOWN username so an unknown-username login takes about
    the same time as a known-username-wrong-password one -- no username enumeration
    via response timing. Lazy + cached so a plain CLI run that never touches web
    auth never pays scrypt's cost, and a running server pays it at most once. Made with
    WEB_PASSWORD_HASH_METHOD and cached per method, so it always costs what a real account's
    check costs."""
    method = WEB_PASSWORD_HASH_METHOD
    if method not in _dummy_hash_cache:
        from werkzeug.security import generate_password_hash
        _dummy_hash_cache[method] = generate_password_hash(
            "no-such-account-#dummy-timing-guard", method=method)
    return _dummy_hash_cache[method]


def verify_web_user(username, password):
    """Check username/password against config.json's AUTH_USERS. True only on an
    exact match against a KNOWN username, via werkzeug's timing-safe
    check_password_hash. An unknown username still runs a (dummy) hash check
    instead of returning immediately, so response timing doesn't leak which
    usernames exist."""
    from moonglade.backup import _load_config
    from werkzeug.security import check_password_hash
    cfg = _load_config()
    user = _find_web_user(cfg, (username or "").strip())
    if user is None:
        check_password_hash(_dummy_password_hash(), password or "")
        return False
    return check_password_hash(user.get("password_hash", ""), password or "")


# ---------------------------------------------------------------------------
# Web gallery login account management (CLI-only -- see the module note above
# get_or_create_secret_key). Deliberately interactive-only (no --password flag):
# a password never belongs in shell history, a saved script, or a process list.
# ---------------------------------------------------------------------------

def run_add_web_user(args):
    """CLI: add or update one gallery web-login account. Prompts for username
    (plain input -- not secret) and password (getpass.getpass -- never echoed to
    the terminal, never printed, never logged), then hashes and persists it via
    add_or_update_web_user. Refuses to save on a blank entry or a confirmation
    mismatch."""
    username = input("Username: ").strip()
    if not username:
        sys.exit("Username must not be empty. Nothing was saved.")
    password = getpass.getpass("Password: ")
    if not password:
        sys.exit("Password must not be empty. Nothing was saved.")
    problem = password_problem(password)
    if problem:
        # Same policy the web forms enforce -- this is the recovery path, not a
        # back door around the rules the Users tab applies.
        sys.exit("{} Nothing was saved.".format(problem))
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        sys.exit("Passwords did not match. Nothing was saved.")
    replaced = add_or_update_web_user(username, password)
    print("{} web-login account '{}'.".format("Updated" if replaced else "Added", username))


def run_remove_web_user(args):
    """CLI: remove one gallery web-login account by username, and its per-login folder in the
    library (S10: a removed login's preferences, presets and snippets go with it)."""
    username = args.remove_web_user
    if remove_web_user(username):
        remove_login_files(getattr(args, "out", None), username)
        print("Removed web-login account '{}'.".format(username))
    else:
        print("No web-login account named '{}'.".format(username))


def remove_login_files(out_dir, username):
    """Delete `username`'s per-login folder (moonglade.paths.account_dir) in the library
    `out_dir`, once the login itself is gone. Best effort: True when it was removed."""
    if not out_dir or not str(username or "").strip():
        return False
    import shutil
    folder = _paths.account_dir(out_dir, username)
    try:
        if folder.is_dir():
            shutil.rmtree(folder)
            return True
    except OSError:
        pass
    return False


def run_list_web_users(args):
    """CLI: list gallery web-login USERNAMES only -- never prints password hashes."""
    users = list_web_users()
    if not users:
        print("No web-login accounts yet. Add one with --add-web-user.")
        return
    print("Web-login accounts ({}):".format(len(users)))
    for u in users:
        print("  " + u["username"])
