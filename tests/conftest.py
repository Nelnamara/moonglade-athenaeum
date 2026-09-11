"""Shared fixtures for the pixai-gallery-backup test suite."""
import json
import os
import re
from pathlib import Path

import pytest

import moonglade_assets
import moonglade_backup as core
import moonglade_container as _mc
import moonglade_gallery as gallery

# The sealed achievement-definitions donor (private companion repo). The roster no longer
# lives in source, so roster tests need a container built from this.
_SEALED_DONOR = (Path(__file__).resolve().parents[1].parent
                 / "moonglade-internal" / "achievements_folio_donor.json")


def clear_sealed_caches():
    """Reset the three module-level caches that would otherwise answer one install's
    question with another install's roster.

    `_sealed_cache` (the parsed definitions), `_container_cache` (the opened box) and
    `_earned_ids_cache` (a 5s-TTL memo keyed on NOTHING -- out_dir is not part of the key)
    are process globals, so they outlive whichever tmp_path wrote them. Every place that
    re-points `_container_path()` at a different file has to clear all three on both sides
    of the swap, and this is that one place."""
    gallery._sealed_cache.update(path=None, mtime=None, defs=None)
    gallery._container_cache.update(path=None, mtime=None, box=None)
    gallery._earned_ids_cache.update(t=0.0, ids=frozenset())


def seed_sealed_container(container_path):
    """Write the sealed achievement roster to `container_path`, from the private donor.

    The ONE implementation of "give this install the real roster", shared by the autouse
    per-test fixture below and by tests/test_render_harness.py's module-scoped server
    fixture. The harness needs it because a module-scoped fixture is set up BEFORE the
    function-scoped autouse ones: without seeding its own container first, its achievement
    state at setup came from whatever pack happened to be sitting beside the checkout --
    a full roster on a dev box, an empty one on CI, and therefore a different pre-seeded
    `seen`/`earned_at` per machine (2026-09-10).

    Donor absent (public CI, no companion repo): nothing is written, `_sealed_defs()` falls
    through to its free-skins fallback, the roster is empty and donor-gated tests skip.
    That is the behaviour every caller wants there, and pinning it HERE -- rather than
    letting the filesystem beside the checkout decide -- is what makes a dev box and CI
    agree on which tests run."""
    container_path = Path(container_path)
    if _SEALED_DONOR.is_file():
        defs = json.loads(_SEALED_DONOR.read_text(encoding="utf-8"))
        _mc.write_container(container_path, {"_seed.txt": b"x"},
                            {"achievements": json.dumps(defs, separators=(",", ":")).encode("utf-8")})
    clear_sealed_caches()


# The REAL coded goods tree, resolved at conftest IMPORT time -- earlier than any fixture
# can run, so no monkeypatch of branding_root() has had a chance to redirect it yet. The
# guard below compares against this Path object instead of re-calling the resolver, so a
# test that leaves the resolver patched cannot point the guard at a decoy.
_REAL_CODED_ROOT = gallery.branding_root()


def _snapshot_coded_tree():
    """A read-only census of the real coded tree: {relpath: (size, mtime_ns) | "dir"}.

    Returns None for "the folder is not there", which is its own fact worth guarding: a
    test that CREATES it is as much of a violation as one that edits it (create_app()
    calls ensure_branding_discovery_tree(), so an un-pinned server fixture builds the
    tree in the checkout just by starting). Never creates and never writes -- a bare
    exists() check, then walk and stat.

    FOLDERS are recorded as well as files, and that is not tidiness. The side effect this
    guard was written for is `ensure_branding_discovery_tree()`, which mkdirs the discovery
    slots and writes the breadcrumb README only `if not readme.exists()`
    (moonglade_gallery.py:3156-3161) -- on a checkout with no tree at all it creates six
    FOLDERS and one file, and a file-only census would report the folders as nothing at
    all."""
    if not _REAL_CODED_ROOT.exists():
        return None
    out = {}
    for dirpath, dirnames, filenames in os.walk(_REAL_CODED_ROOT):
        for name in dirnames:
            path = Path(dirpath) / name
            out[str(path.relative_to(_REAL_CODED_ROOT)) + os.sep] = "dir"
        for name in filenames:
            path = Path(dirpath) / name
            try:
                st = path.stat()
            except OSError:                    # vanished mid-walk; the diff will say so
                continue
            out[str(path.relative_to(_REAL_CODED_ROOT))] = (st.st_size, st.st_mtime_ns)
    return out


@pytest.fixture(scope="session", autouse=True)
def _real_coded_tree_pinned_away(tmp_path_factory):
    """PREVENTION: nothing in this session can resolve the checkout's own coded tree.

    `_isolated_branding` below pins `branding_root()` per TEST, and that is too late for a
    fixture of any wider scope: pytest sets a module- or session-scoped fixture up BEFORE
    the function-scoped autouse ones, so until 2026-09-10 the render harness's module server
    read whatever `moonglade.dat` happened to sit beside the checkout -- a full roster on the
    owner's dev box, an empty one on CI, two different fixtures from one piece of code.
    Every such fixture must still pin its own root (the harness does, and its own test
    asserts it), but a rule that only holds while every future author remembers it is not a
    rule. This is the floor under it: the resolver is pinned for the whole session, so a
    fixture that forgets lands in a session tmp dir instead of the owner's real tree and the
    real 802MB pack -- wrong, but wrong the same way on every machine.

    A sealed container is seeded beside it from the private donor, so the session-wide
    default matches the per-test default (`_sealed_roster_container`) rather than being a
    third kind of roster; donor absent, nothing is written and the roster is empty exactly
    as on public CI.

    `_real_coded_tree_untouched` below stays as the backstop this cannot be: it watches the
    tree itself, so code that builds a path some other way than through the resolver is
    still caught."""
    mp = pytest.MonkeyPatch()
    root = tmp_path_factory.mktemp("session-branding")
    mp.setattr(gallery, "branding_root", lambda: root / "branding")
    seed_sealed_container(root / "moonglade.dat")
    try:
        yield root
    finally:
        mp.undo()
        clear_sealed_caches()


@pytest.fixture(scope="session", autouse=True)
def _real_coded_tree_untouched():
    """No test reads or writes the checkout's own coded tree -- and this watches the tree.

    Every fixture that needs a branding tree or a sealed pack pins its own (the autouse
    `_isolated_branding` per test, `seed_sealed_container` above for the module-scoped
    harness server), and `_real_coded_tree_pinned_away` above makes that the default even
    when one forgets. This is the independent check on all of it: snapshot at session start,
    re-snapshot at session end, fail on any difference -- files, folders, or the tree coming
    into existence where there was none, which is how the machine-dependent harness announced
    itself on 2026-09-10.

    What it cannot see, and why the pin above exists: a READ leaves no trace, and on a
    checkout that already holds the discovery folders and the breadcrumb (the owner's own --
    the machine CLAUDE.md names for the pre-merge run) an un-pinned `create_app()` writes
    nothing new, so this guard would pass in silence on the one machine where the 2026-09-10
    bug actually lived. A watcher cannot be the whole answer to a read; prevention is.

    Session scope and autouse so it brackets the whole run: it is set up before any
    module- or function-scoped fixture of the first test, and torn down after the last."""
    before = _snapshot_coded_tree()
    yield
    after = _snapshot_coded_tree()
    if before == after:
        return
    if before is None:
        pytest.fail("a test CREATED the real coded tree at {} -- every fixture that needs "
                    "one must pin its own branding_root(). Now there (a trailing separator "
                    "marks a folder): {}".format(_REAL_CODED_ROOT, sorted(after)))
    if after is None:
        pytest.fail("a test REMOVED the real coded tree at {} -- it held {} entr(ies) at "
                    "session start.".format(_REAL_CODED_ROOT, len(before)))
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    modified = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    pytest.fail("the real coded tree at {} changed during this run -- no test may read or "
                "write it; pin your own branding_root(). added={} removed={} modified={}"
                .format(_REAL_CODED_ROOT, added, removed, modified))


def pytest_sessionstart(session):
    """One loud line when the sealed donor is absent, naming the file and how many tests
    it gates.

    The skip mechanism itself is right -- public CI has no companion repo and those tests
    cannot run there. What was wrong is that a run missing them still PRINTS as green, so
    "all tests pass" could quietly mean "all tests that ran". This does not change what
    runs; it makes the gap impossible to miss in the output."""
    if _SEALED_DONOR.is_file():
        return
    gated = 0
    try:
        for path in Path(__file__).resolve().parent.glob("test_*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            gated += text.count("@needs_donor") + text.count("sealed_donor_present")
    except OSError:
        gated = 0
    line = ("!!! SEALED DONOR MISSING: %s\n"
            "!!! ~%d roster-dependent test(s) will SKIP. A green run here does NOT mean\n"
            "!!! the roster, seal and ladder behaviour were verified."
            % (_SEALED_DONOR, gated))
    print("\n" + "!" * 78 + "\n" + line + "\n" + "!" * 78)
    try:
        session.config.pluginmanager.get_plugin("terminalreporter").write_line(
            line, red=True, bold=True)
    except Exception:                      # noqa: BLE001 -- the print above already carried it
        pass


@pytest.fixture(autouse=True)
def _no_pixai_token(monkeypatch):
    """Remove PIXAI_TOKEN so tests that don't need it don't accidentally call live APIs."""
    monkeypatch.delenv("PIXAI_TOKEN", raising=False)


@pytest.fixture(autouse=True)
def _no_ambient_api_key(monkeypatch):
    """Force core._cfg (the import-time config cache) empty for every test, so a
    developer machine behaves exactly like CI.

    CI has no config.json, so at import core._cfg is {}. A developer machine loads
    the real PIXAI_API_KEY into it, and _make_session() falls back to that cache --
    so any test that reaches _make_session() WITHOUT stubbing it passes locally
    (silently borrowing the developer's key) and fails in CI with "No API key
    found." That gap hid eleven such tests until CI caught them. Making the cache
    empty here means local == CI: a test that needs a session must stub
    core._make_session, which is already this suite's convention (test_claims,
    test_jobs, test_kaisuuken, test_generate_model_id, ...). test_filesystem.py did
    exactly this by hand for the same reason before it was generalized here. The
    delenv stops an exported key from re-opening the same hole."""
    monkeypatch.setattr(core, "_cfg", {})
    monkeypatch.delenv("PIXAI_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def _isolated_auth_config(tmp_path, monkeypatch):
    """Web-login auth (AUTH_SECRET_KEY/AUTH_USERS) lives in config.json.
    moonglade_gallery.create_app() -- called by ~every test in this suite -- now
    generates + PERSISTS a session secret key via get_or_create_secret_key() the
    first time it runs if config.json has none. Without this fixture, that write
    would land in the REAL, git-ignored config.json next to the checkout (the one
    holding the developer's actual PIXAI_API_KEY), the moment any test calls
    create_app(). Redirect _config_path() to THIS test's own tmp_path instead, so
    the whole suite never reads or mutates the real file.

    Deliberately named plain "config.json" (not some other throwaway name): this
    is the SAME path tests/test_filesystem.py's test_load_config_reads_file /
    test_load_config_missing_returns_empty already write to / expect via their own
    tmp_path, so this fixture is a no-op improvement for them (it just replaces
    their __file__-based resolution with an equivalent tmp_path-based one) rather
    than a second, conflicting source of truth."""
    monkeypatch.setattr(core, "_config_path", lambda: tmp_path / "config.json")


@pytest.fixture(autouse=True)
def _isolated_branding(tmp_path, monkeypatch):
    """Branding art moved OUT of the library folder and into the app root on 2026-07-26, so
    branding_root() now resolves from __file__ -- meaning the real checkout, for every test that
    exercises a mark, badge, mascot or banner.

    Same hazard and same remedy as _isolated_auth_config above: without this, a test that writes a
    fake mark would drop PNGs into the developer's actual branding folder, and a test asserting
    "no marks installed" would instead pick up whatever real art is sitting there -- passing or
    failing based on the machine it ran on rather than the code.

    Redirecting the resolver to tmp_path restores exactly the semantics the whole suite was
    already written against (branding under the per-test directory), so every existing branding
    test keeps working unchanged and this is a no-op for them. Note _branding_path() derives
    branding.json as a SIBLING of this, which lands it at tmp_path/branding.json -- the path
    tests/test_branding.py already expects."""
    monkeypatch.setattr(gallery, "branding_root", lambda: tmp_path / "branding")


@pytest.fixture(autouse=True)
def _isolated_asset_manifest(tmp_path, monkeypatch):
    """moonglade_manifest.json (the first-run asset downloader's manifest,
    2026-08-10) resolves from __file__ in moonglade_assets.py -- same hazard,
    same remedy as _isolated_branding above: without this, every test reading
    it would see the REAL checkout's own committed manifest (once one exists),
    passing or failing based on whatever the developer's machine happens to
    have built, not the code under test.

    Redirected to a tmp_path file that does not exist by default, matching
    read_manifest()'s own contract for "nothing here" (None, not an error) --
    tests that need a real manifest write one via moonglade_assets.write_manifest()
    after this fixture has already pointed the resolver at their own tmp_path."""
    monkeypatch.setattr(moonglade_assets, "manifest_path",
                        lambda: tmp_path / "moonglade_manifest.json")


@pytest.fixture(autouse=True)
def _sealed_roster_container(request, tmp_path):
    """Ship the sealed achievement roster to every test. The definitions live in
    moonglade.dat now (not source), so without a container the roster is empty and every
    roster-dependent test fails. _isolated_branding points branding_root() at
    tmp_path/branding, so _container_path() resolves to tmp_path/moonglade.dat -- write a
    sealed container there from the private donor. Skips silently when the donor is absent
    (public CI without the companion repo): roster tests then see the empty fallback and
    are expected to skip, not fail. The sealed-defs cache is cleared around each test so no
    roster leaks between them (and test_build_container, which rebuilds this same path via
    main(), just overwrites the seed).

    EXCEPTION: the asset-downloader tests (test_assets.py) test downloading a container TO
    this exact path and assert on its presence/absence -- pre-seeding it there breaks them,
    so they opt out."""
    if "test_assets" in request.node.nodeid:
        yield
        return
    seed_sealed_container(tmp_path / "moonglade.dat")
    yield
    clear_sealed_caches()


@pytest.fixture()
def sealed_donor_present():
    """Skip a test when the private sealed-definitions donor isn't checked out (public
    CI). Use on tests that assert specific roster content (ids, thresholds, the ladder)."""
    if not _SEALED_DONOR.is_file():
        pytest.skip("sealed-definitions donor (private repo) not present")


@pytest.fixture(autouse=True)
def _fresh_perf_memos():
    """The 2026-09-03 perf pass added three module-level memos -- the achievement-metrics
    cache, the contest-board cache, and the contest sweep's last-successful-run stamp --
    and the 2026-09-04 pass added a fourth, /api/health's own. Module singletons outlive a
    test, so without this one test's cached board (or its "we swept recently", or another
    tmp_path's library walk) answers the next one's request. Same isolation the sealed-defs
    and earned-ids caches above already get, and for the same reason."""
    def _clear():
        gallery._ACH_METRICS_CACHE.clear()
        gallery._contests_cache.clear()
        gallery._contest_sync_last_ok.update(at=0.0)
        gallery._HEALTH_CACHE.update(key=None, payload=None, at=0.0)
        gallery._HEALTH_BUSY["on"] = False
    _clear()
    yield
    _clear()


@pytest.fixture(autouse=True)
def _no_live_watch(monkeypatch):
    """create_app() is called by ~every test in this suite. Without this, its
    live-mirror watcher thread would call _make_session(None), which re-reads THIS
    machine's real config.json (whatever real credentials happen to be there) and open
    a genuine WebSocket to wss://gw.pixai.art -- during every single test run. Skip its
    auto-start entirely in tests; see MOONGLADE_DISABLE_WATCH in moonglade_gallery.py."""
    monkeypatch.setenv("MOONGLADE_DISABLE_WATCH", "1")


@pytest.fixture(autouse=True)
def _clear_profile_cache():
    """_model_profiles caches each version's inference-profile set in core._profile_cache
    (keyed by version_id, with a TTL) so the submit/price gate avoids a network GET on every
    /api/price keystroke. Clear it around every test so one test's profiles can't leak into
    another. Same isolation contract as the gallery cache resets above."""
    core._profile_cache.clear()
    yield
    core._profile_cache.clear()


@pytest.fixture(autouse=True)
def _no_live_card_network(monkeypatch):
    """The card list/match hit PixAI's live /v2 REST API. Keep unit tests offline by
    default: _rest_get/_rest_post raise (so list_kaisuukens -> [] and match_kaisuuken ->
    None) unless a test overrides them, and user-id resolution is stubbed so _make_session
    (now reached from generation previews via the free/paid note) builds no network.
    Exception: match_kaisuuken(raise_on_error=True) -- the spend-time check inside
    _apply_kaisuuken -- deliberately does NOT fail soft here; it propagates this same
    blocked-network error, so any test that reaches _apply_kaisuuken's auto-match path
    must stub match_kaisuuken (or READ_ONLY-gate/--no-card/--kaisuuken-id past it)."""
    def _blocked(*a, **k):
        raise core.PixAIError("live /v2 REST blocked in tests")
    monkeypatch.setattr(core, "_rest_get", _blocked, raising=False)
    monkeypatch.setattr(core, "_rest_post", _blocked, raising=False)
    # Pin USER_ID so _make_session (now reached from generation previews) never triggers a
    # live resolve_user_id lookup. Setting the global -- not stubbing the function -- keeps
    # resolve_user_id itself testable in test_auth.
    monkeypatch.setattr(core, "USER_ID", "0", raising=False)


# Captured at import, before `_no_live_card_network` (below) swaps them for a raising
# stub. The `pixai` fixture puts the real delegates back so a /v2 call reaches the FAKE
# and is refused BY PATH there, rather than dying on a generic "blocked" message.
_REAL_REST_GET = core._rest_get
_REAL_REST_POST = core._rest_post


@pytest.fixture()
def pixai(monkeypatch):
    """The PixAI transport, faked at the seam -- what `_make_session()` (and therefore the
    gallery's `_gen_session()`) hands out for this test.

    This is the road that replaces "patch four private names and hand-roll a stub". The
    fake answers only operations the test registered and refuses everything else by name,
    so a route under test cannot reach the network even by accident, and a call nobody
    anticipated fails with the operation's name instead of a socket error.

        def test_something(pixai, ...):
            pixai.on("me", {"me": {"id": "1", "quotaAmount": 500}})
            ...
            assert pixai.mutations("createGenerationTask") == 1

    `_rest_get`/`_rest_post` are restored to the real delegates here on purpose: they route
    through `_client_of`, which hands the fake straight back, so the /v2 road lands on the
    same registry as the GraphQL one. Offline-ness is not weakened -- it moves from a
    blanket raise to the fake's own refusal."""
    from tests.fake_pixai import FakePixAI
    fake = FakePixAI()
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: fake)
    monkeypatch.setattr(core, "_rest_get", _REAL_REST_GET)
    monkeypatch.setattr(core, "_rest_post", _REAL_REST_POST)
    return fake


@pytest.fixture()
def mock_session(mocker):
    """Return a MagicMock that quacks like a requests.Session.

    The older road, kept working deliberately: a MagicMock is what a test wants when the
    assertion is about the HTTP call itself (`mock_session.post.call_count`), which is
    exactly what tests/test_spend_no_retry.py's network-level checks assert. For a test
    whose stubs are purely "answer this operation with that payload", prefer the `pixai`
    fixture above -- it refuses what it was not told about, where a MagicMock invents a
    truthy answer for anything."""
    session = mocker.MagicMock()
    return session


# ---------------------------------------------------------------------------
# Real-login test helpers
# ---------------------------------------------------------------------------
# moonglade_gallery.py's _is_authorized_request() has NO localhost bypass -- login is
# required via every path, localhost hostname or IP included. It is true only for a request
# carrying a valid logged-in session. Every test that just needs to be past the
# front door (not testing the gate itself) should log in for real through these
# helpers rather than relying on the test client's default REMOTE_ADDR=127.0.0.1,
# which no longer buys anything. Tests whose entire point IS the gate/boundary
# itself (tests/test_web_auth.py, the "refuses authenticated LAN session" tests,
# anything asserting a 401/403/redirect-to-login) should keep hand-rolling an
# unauthenticated (or deliberately-still-anonymous) client instead -- see
# tests/test_branding.py::test_shortcut_refuses_authenticated_lan_session and
# tests/test_panel.py::test_destructive_action_refuses_authenticated_lan_session,
# which already do the same GET-csrf-then-POST dance these helpers wrap.
_TEST_USERNAME = "tester"
_TEST_PASSWORD = "a-real-test-password-1"


def extract_login_csrf(html_or_boot):
    """CSRF token off GET /login's response: the React shell's window.MG_BOOT JSON
    blob (the ONLY login page since the classic cut, 2026-08-08 -- the classic form
    and its hidden input died with LOGIN_HTML; the classic-input pattern is kept in
    the regex purely so a regression that resurrects it still extracts+fails loudly
    at the POST step rather than silently here)."""
    m = re.search(r'name="csrf" value="([^"]+)"|"csrf":\s*"([^"]+)"', html_or_boot)
    return (m.group(1) or m.group(2)) if m else None


def _do_login(cli, username, password):
    """Authenticate `cli` the way the real app does (2026-08-08, classic cut): GET
    /login for the session csrf, then POST /api/login (JSON) -- the one and only
    sign-in path now. Asserts success so callers never continue anonymous on a
    typo/regression."""
    html = cli.get("/login").get_data(as_text=True)
    csrf = extract_login_csrf(html)
    assert csrf, "login page did not render a csrf token in MG_BOOT"
    d = cli.post("/api/login", json={"username": username, "password": password,
                                     "csrf": csrf}).get_json()
    assert d and d.get("ok"), (
        "test login helper failed to authenticate: {!r}".format(d))
    return cli


def login_existing_client(cli, username=_TEST_USERNAME, password=_TEST_PASSWORD):
    """Authenticate an ALREADY-BUILT test client IN PLACE: create a real account (via
    core.add_or_update_web_user) then log `cli` itself in. Use this when a test needs
    to make some calls anonymously first (e.g. to prove an unauthenticated/LAN request
    is refused) and then continue as a logged-in session against the very same client/
    app instance."""
    core.add_or_update_web_user(username, password)
    return _do_login(cli, username, password)


def login_test_client(app, username=_TEST_USERNAME, password=_TEST_PASSWORD):
    """Given an already-built create_app(tmp_path) app (e.g. one a test file's own
    helper seeded with a catalog), create a real account and return a FRESH,
    now-authenticated test_client() for it."""
    core.add_or_update_web_user(username, password)
    return _do_login(app.test_client(), username, password)


def login_client(tmp_path, username=_TEST_USERNAME, password=_TEST_PASSWORD):
    """The common one-liner: build create_app(tmp_path) AND log into it in one call.
    Returns the authenticated test client, ready to use exactly like
    create_app(tmp_path).test_client() used to be before the local-request bypass
    was removed."""
    from moonglade_gallery import create_app
    return login_test_client(create_app(tmp_path), username=username, password=password)


def ach_nonce(cli):
    """A fresh feat-beacon nonce for `cli`'s session. Since the 2026-09-07 nonce ruling
    /api/ach-event refuses a POST that carries none, so a test that just wants the
    counter to move mints one the same way a real page does."""
    return ((cli.get("/api/ach-nonce").get_json() or {}).get("nonce") or "")


def ach_event(cli, event, nonce=None):
    """POST one feat event with a valid nonce -- the shape every real client sends since
    2026-09-07. Tests that are ABOUT the nonce (replay, expiry, foreign session, the
    debounce, the rate limit) post by hand instead; this is for the many tests that only
    need the earn to land."""
    return cli.post("/api/ach-event",
                    json={"event": event, "nonce": nonce if nonce is not None
                          else ach_nonce(cli)})

