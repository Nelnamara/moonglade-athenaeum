"""Shared fixtures for the pixai-gallery-backup test suite."""
import json
import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

from moonglade import assets as moonglade_assets
from moonglade import backup as core
from moonglade import container as _mc
from moonglade import gallery
from moonglade import migrate as moonglade_migrate
from moonglade import paths as moonglade_paths

# The sealed achievement-definitions donor (private companion repo). The roster no longer
# lives in source, so roster tests need a container built from this.
_SEALED_DONOR = (Path(__file__).resolve().parents[1].parent
                 / "moonglade-internal" / "achievements_folio_donor.json")

# The checkout this suite tests, and the code folder the app's modules live in (since 3.20).
REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_PACKAGE = "moonglade"
_NOT_FIRST_PARTY = frozenset({"tests", "node_modules", ".git", "__pycache__"})


def first_party_sources(root=None, suffixes=(".py", ".pyw")):
    """Every first-party Python source of the app, sorted: the modules at the repo root, and
    every one at any depth under a `moonglade/` code folder if one exists. Never tests/,
    node_modules/, .git/ or __pycache__/.

    THE one collector for every guard that reads the app's own code -- the spoiler and
    pack-name guards, and the path lints. They used to glob the root flat (`moonglade_*.py`,
    `*.py`), which would keep passing after the code moves into `moonglade/` while checking
    nothing at all. tests/test_first_party_sources.py holds that it finds every module there
    is today, so it can never silently find nothing."""
    root = Path(root) if root is not None else REPO_ROOT
    found = sorted(p for p in root.iterdir() if p.is_file() and p.suffix in suffixes)
    package = root / CODE_PACKAGE
    if package.is_dir():
        for dirpath, dirnames, filenames in os.walk(package):
            dirnames[:] = sorted(d for d in dirnames if d not in _NOT_FIRST_PARTY)
            found += [Path(dirpath) / f for f in sorted(filenames)
                      if Path(f).suffix in suffixes]
    return found


def stub_code_module(monkeypatch, name, module):
    """Stand `module` in for `moonglade.<name>` for one test. The app imports its own modules
    as `from moonglade import <name>`, which reads the PACKAGE's attribute first and falls
    back to sys.modules only when that is absent -- so a sys.modules entry alone (the way the
    flat `moonglade_<name>` modules were stubbed before 3.20) is silently ignored once the
    real module has been imported anywhere in the session. Both are set; both are undone."""
    import moonglade
    monkeypatch.setitem(sys.modules, "moonglade." + name, module)
    monkeypatch.setattr(moonglade, name, module, raising=False)


@pytest.fixture()
def pack_art():
    """{(slot, key): bytes} of the pack's nine role images (login companion, tracker mascots, reward
    icons, power poses), read from the folder the MOONGLADE_PACK_ART environment variable names. The
    folder holds the pack's art in its public layout (login_nel.webp, nel_spinner.png or
    system/nel_spinner.png, mascots/trk_done.png, rewards/claim.png ...). Skipped when the variable is
    unset or the folder lacks any of them, so a checkout without the art runs everything else. A
    test never reads the checkout's own pack (see the hermeticity rule at the top of this file)."""
    folder = os.environ.get("MOONGLADE_PACK_ART", "").strip()
    if not folder:
        pytest.skip("MOONGLADE_PACK_ART is unset (the folder holding the pack's role art)")
    root, out, missing = Path(folder), {}, []
    for slot, role in gallery.ROLE_SLOTS.items():
        for key, img in role["images"].items():
            public = img["public"]
            hit = next((p for p in (root / public, root / "system" / public) if p.is_file()), None)
            if hit is None:
                missing.append(public)
            else:
                out[(slot, key)] = hit.read_bytes()
    if missing:
        pytest.skip("MOONGLADE_PACK_ART lacks: %s" % ", ".join(missing))
    return out


def clear_sealed_caches():
    """Reset the three module-level caches that would otherwise answer one install's
    question with another install's roster (and the moments' clip cache beside them).

    `_sealed_cache` (the parsed definitions), `_container_cache` (the opened box) and
    `_earned_ids_cache` (a 5s-TTL memo keyed on NOTHING -- out_dir is not part of the key)
    are process globals, so they outlive whichever tmp_path wrote them. Every place that
    re-points `_container_path()` at a different file has to clear all three on both sides
    of the swap, and this is that one place."""
    gallery._sealed_cache.update(path=None, mtime=None, defs=None)
    gallery._container_cache.update(path=None, mtime=None, box=None)
    gallery._earned_ids_cache.update(t=0.0, ids=frozenset())
    # The moments' verified-clip cache is keyed on content, not on an install, so it
    # cannot answer with the wrong bytes -- but a test that corrupts a pack must see
    # the pack, not a clip an earlier test left verified in memory.
    with gallery._moment_clip_cache_lock:
        gallery._moment_clip_cache.clear()


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
        _mc.write_container(container_path, _seed_assets(),
                            {"achievements": json.dumps(defs, separators=(",", ":")).encode("utf-8")})
    clear_sealed_caches()


# A tiny PUBLIC H.264 clip (2 s, 320x180, silent colour bars, made with ffmpeg) that stands
# in for every bespoke moment's clip in a test container. The real clips are sealed art and
# live only in the pack; no test may read the pack, so the moments are exercised on this.
MOMENT_FIXTURE_CLIP = Path(__file__).resolve().parent / "fixtures" / "moment_fixture.mp4"


def donor_feat(**flags):
    """The sealed roster's achievement id carrying every given flag (e.g.
    `donor_feat(unlocks="branding_tab")`), or None without the donor. A test names a hidden
    feat by its roster flags, never by an id literal: the ids are not public source (pack v5,
    DECISIONS 2026-09-11 "Hidden-feat ids are keys, not spoilers")."""
    if not _SEALED_DONOR.is_file():
        return None
    roster = json.loads(_SEALED_DONOR.read_text(encoding="utf-8")).get("roster") or []
    for a in roster:
        if isinstance(a, dict) and all(a.get(k) == v for k, v in flags.items()):
            return a.get("id")
    return None


def moment_clip_keys():
    """The container keys (CODED rels) every moment's clip is seeded under -- derived from
    the app's own map and translation, never retyped, so a moved bucket moves the seed too."""
    return sorted(gallery._public_rel_to_coded(name) for name in gallery._MOMENT_CLIPS.values())


def _seed_assets():
    """The assets a seeded test container carries: the placeholder, plus the fixture clip
    under each moment clip's key. Only written with the donor (the caller's gate): without a
    roster no moment can be earned, so its clip could never be served anyway."""
    clip = MOMENT_FIXTURE_CLIP.read_bytes()
    assets = {"_seed.txt": b"x"}
    for key in moment_clip_keys():
        assets[key] = clip
    return assets


# The instant every server fixture's install is pinned to: 13:00 on a Wednesday. Any
# daytime weekday reading would do -- what matters is that it never moves, and that it is
# outside the narrow window in which a collected generation stamps `session_hour`
# (moonglade_gallery.stamp_session_hour, 2 <= hour < 4). Documentation only: nothing constructs a datetime from it, because
# the value a pinned clock produces is what the pin below reproduces, not the clock object.
PINNED_INSTANT = "13:00, Wednesday 2025-06-11, local"

# The one telemetry flag whose write is decided by the hour of the run. Public because
# tests/test_fixture_hermeticity.py measures the pin against it rather than re-spelling it.
HOUR_DRIVEN_FLAG = "session_hour"


def pin_daytime_clock(mp):
    """Make an install answer as it would at `PINNED_INSTANT`, for every wall-clock read an
    achievement metric can reach, for the lifetime of `mp` (the caller's own MonkeyPatch).

    THE SURVEY, re-run 2026-09-11 over both modules (`datetime.now()` / `date.today()` /
    `.hour` / weekday arithmetic) and amended 2026-10-02. Three reads can reach an
    achievement metric: in `/api/achievements`, `date.today()` into the distinct-days ledger
    (`days_used` and the streak metrics) and again for the `earned_at` stamps, which no metric
    reads; and the collect path's clock (`stamp_session_hour`, via `_utc_now`), which sets the
    `session_hour` flag for a generation made in its window. (Until 2026-10-02 a bare page
    load read `datetime.now().hour` for that flag; it no longer does.) Everything else is not a
    metric input -- a printed date string in the collection-print payload, the timezone
    offset the activity chart is bucketed by, a search filter's date window -- and
    `moonglade_backup.py`'s one age comparison (`old_piece_backed_up`, 730 days) lives in
    the download loop, which no server runs. No metric reads a weekday at all.

    WHAT THE PIN DOES, read against those three:
      * The hour. At 13:00 the window is closed, so the flag is never written. The wrapper
        below drops exactly that key and passes every other flag through untouched, which is
        the same answer the collect path itself gives at the pinned hour.
      * The day. At a single instant the ledger records one day, once. Left alone, a run
        that crosses local midnight records a second, and `days_used` steps up mid-run. The
        wrapper marks each ledger once per install and drops the repeat. The date string it
        records is still today's -- no metric reads the string, only the count and the
        streaks over it, and both are pinned by there being exactly one entry.
      * The stamps. `earned_at` values are dates in the install's own state file; no
        threshold is computed from them.

    WHY NOT THE CLOCK ITSELF. The route reads the clock through a function-local
    `import datetime`, so the only lever that reaches it is substituting `datetime.datetime`
    process-wide (the `mock.patch("datetime.datetime", _FixedNoon)` idiom this suite already
    uses around single test-client calls). That idiom cannot be held open for a server
    fixture's lifetime here: the render harness answers on werkzeug request threads whose
    routes import heavy libraries lazily (the similar route pulls pandas, which pulls
    dateutil.tz), and with `datetime.datetime` substituted that import chain ends in a
    Windows stack overflow that takes the interpreter down mid-module -- reproduced three
    times end to end against a baseline that runs the file green, then isolated (a subclass
    whose `now()` returns the REAL time crashes identically, so it is the substitution and
    not the frozen value). So the pin is applied at the two seams the clock feeds instead of
    at the clock, and lands on the same install state a frozen daytime clock would.

    Effects are asserted, not assumed: tests/test_fixture_hermeticity.py drives the real
    route at 03:00 with and without this pin.
    """
    real_flag = gallery.telem_flag
    real_mark_day = gallery.telem_mark_day
    marked = set()

    def _flag_at_the_pinned_instant(key, out_dir=None):
        if key == HOUR_DRIVEN_FLAG:
            return
        return real_flag(key, out_dir=out_dir)

    def _mark_day_at_the_pinned_instant(out_dir=None, keys=None):
        # Dedupe per LEDGER, not per call shape: the legacy flat list (keys=None) and
        # every named per-key list each record one day for the run, whichever call
        # shape reaches them first, so a run crossing local midnight cannot move
        # days_used, active_days or a streak metric through a second call shape.
        ledgers = ("days",) if keys is None else tuple(keys)
        fresh = [k for k in ledgers if (str(out_dir), k) not in marked]
        if not fresh:
            return
        marked.update((str(out_dir), k) for k in fresh)
        return real_mark_day(out_dir=out_dir, keys=None if keys is None else fresh)

    mp.setattr(gallery, "telem_flag", _flag_at_the_pinned_instant)
    mp.setattr(gallery, "telem_mark_day", _mark_day_at_the_pinned_instant)


# The REAL coded goods tree, resolved at conftest IMPORT time -- earlier than any fixture
# can run, so no monkeypatch of branding_root() has had a chance to redirect it yet. The
# guard below compares against this Path object instead of re-calling the resolver, so a
# test that leaves the resolver patched cannot point the guard at a decoy.
_REAL_CODED_ROOT = gallery.branding_root()
# The real machine files' folder and the real pack, resolved the same way and for the same
# reason: the pack and settings.json are local/ files (moonglade.paths), NOT the coded tree's
# siblings, so pinning branding_root() alone no longer keeps a test away from them.
_REAL_LOCAL_PACK = moonglade_paths.local_path("moonglade.mgpack")
# The machine files' real folder (local/), the real old places the move brings them across
# from (the app folder itself), and the checkout's own default library -- whose records the
# move brings into its _moonglade/. Resolved at import, before any pin, for
# _real_machine_files_untouched.
_REAL_LOCAL_DIR = moonglade_paths.local_dir()
_REAL_APP_ROOT = moonglade_paths.APP_ROOT
_REAL_DEFAULT_LIBRARY = moonglade_paths.default_library_path()
# The empty folder, under each test's own tmp_path, that stands in for the app folder of an
# install before this layout (moonglade.migrate.old_app_root), which the move brings the
# machine files across FROM.
_OLD_APP_ROOT_NAME = "app-before-the-move"


def _snapshot_coded_tree():
    """A read-only census of the real coded tree: {relpath: (size, mtime_ns) | "dir"}.

    Returns None for "the folder is not there", which is its own fact worth guarding: a
    test that CREATES it is as much of a violation as one that edits it (create_app()
    calls ensure_branding_discovery_tree(), so an un-pinned server fixture builds the
    tree in the checkout just by starting). Never creates and never writes -- a bare
    exists() check, then walk and stat.

    FOLDERS are recorded as well as files, and that is not tidiness. The side effect this
    guard was written for is `ensure_branding_discovery_tree()`, which mkdirs every
    slot in `_BRANDING_DISCOVERY_SLOTS` and writes its placeholder README only
    `if not readme.exists()` (moonglade_gallery.py:3156-3161). On a checkout with no tree
    at all that is a set of FOLDERS and a single file -- and the folders are the bulk of
    it, because each slot's coded rel is itself nested (`ROLE_CODE`), so `parents=True`
    materializes the intermediate levels too. A file-only census would report all of that
    as nothing at all."""
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
    real pack -- wrong, but wrong the same way on every machine.

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
    # ...and the machine files (the pack among them), which no longer derive from the tree --
    # their folder, and the old app folder the move brings them across from
    # (moonglade.migrate.old_app_root), so a fixture that runs a real start moves nothing of
    # the checkout's own.
    mp.setattr(moonglade_paths, "local_path", lambda name: root / name)
    mp.setattr(moonglade_paths, "local_dir", lambda: root)
    mp.setattr(moonglade_migrate, "old_app_root", lambda: root / _OLD_APP_ROOT_NAME)
    # ...and the folder a relative library (the default one among them) is anchored to, so a
    # start with no --out opens a library of the session's own, never the checkout's.
    mp.setattr(moonglade_paths, "library_anchor", lambda: root)
    seed_sealed_container(gallery._container_path())
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
    checkout where that tree already exists (the owner's own -- the machine CLAUDE.md names
    for the pre-merge run) an un-pinned `create_app()` writes
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


def _stamp(p):
    """(size, mtime_ns) of a file, "dir" for a folder, None when nothing is there."""
    try:
        if p.is_dir():
            return "dir"
        st = p.stat()
        return (st.st_size, st.st_mtime_ns)
    except OSError:
        return None


def _snapshot_machine_files():
    """A read-only census of what a start's move would touch in the REAL checkout: the
    machine files' folder, its journal and its settings.json, the old places the pack, its
    marker, the mirror token, the settings files and the icon cache move FROM (a move makes
    them vanish), and the default library's app folder and its journal. Never creates, never
    writes.

    Sizes and times are deliberately NOT compared: on the owner's machine a running server
    may rewrite the mirror token or settings.json mid-run. A move's footprint is presence --
    a folder appearing, a file vanishing -- and the two journals, which only the move writes."""
    from moonglade import assets as _ma
    app = _REAL_DEFAULT_LIBRARY / moonglade_paths.LIBRARY_APP_DIRNAME
    out = {
        "local/": _stamp(_REAL_LOCAL_DIR) == "dir",
        "local/.journal.json": _stamp(_REAL_LOCAL_DIR / moonglade_paths.JOURNAL_NAME),
        "local/.lock": _stamp(_REAL_LOCAL_DIR / moonglade_paths.LOCK_NAME) is not None,
        "library/_moonglade/": _stamp(app) == "dir",
        "library/_moonglade/.journal.json": _stamp(app / moonglade_paths.JOURNAL_NAME),
    }
    for name in ("moonglade.mgpack", "moonglade.mgpack.version", _ma.LEGACY_NAME,
                 moonglade_paths.MIRROR_SESSION_NAME, moonglade_migrate.OLD_ICON_CACHE,
                 "serve.txt", "branding.json", "branding_slots.json"):
        out[name] = _stamp(_REAL_APP_ROOT / name) is not None
    return out


@pytest.fixture(scope="session", autouse=True)
def _real_machine_files_untouched():
    """No test runs a real start's tidy against the checkout itself -- and this watches.

    The pins above (local_dir, local_path, moonglade.migrate.old_app_root) are the prevention:
    a test that runs main() or prepare() brings nothing across but its own tmp folders. This is
    the backstop, for the machine where it would matter most -- the owner's, where the real
    pack (several hundred MB) and his mirror login sit beside the checkout: a tidy that ran
    for real would move them into a local/ folder this checkout never had."""
    before = _snapshot_machine_files()
    yield
    after = _snapshot_machine_files()
    if before != after:
        changed = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
        pytest.fail("a test brought the checkout's own machine files or library records "
                    "across (moonglade.migrate) -- pin local_dir / migrate.old_app_root, or run "
                    "the migration on a tmp folder. Changed (before, after): {}"
                    .format(changed))


def is_a_real_panel_job(args):
    """True for the command line the Control Panel's job runner starts (moonglade.gallery's
    _panel_run): this interpreter, `-m moonglade`, and an explicit `--out`."""
    try:
        argv = [str(a) for a in args] if not isinstance(args, (str, bytes)) else [str(args)]
    except TypeError:
        return False
    return (len(argv) >= 3 and argv[1:3] == ["-m", "moonglade"] and "--out" in argv)


class _NoRealPanelJob(subprocess.Popen):
    """subprocess.Popen, except that it refuses to start a real Control Panel job."""

    def __init__(self, args, *a, **k):
        if is_a_real_panel_job(args):
            raise OSError("the test suite never starts a real Control Panel job")
        super().__init__(args, *a, **k)


@pytest.fixture(scope="session", autouse=True)
def _no_real_panel_jobs():
    """PREVENTION: no test starts a real Control Panel job.

    The job runner (moonglade.gallery's _panel_run) starts `python -m moonglade --out <library>`
    from the app folder, as its own process -- which none of this suite's pins reach. Tests that
    drive it stand in their own Popen, but a job's follow-on (`then`) is started by its reader
    thread once the job ends, which can be after the test's stand-in is gone. A real child then
    ran the command line against the test's library with the checkout's real config.json, and
    since the rebuilt move it would also run moonglade.setup.prepare("cli") in the checkout's
    own local/ -- on the owner's machine a real install. So the process's Popen refuses that
    one command line for the whole session (a refused start is the job runner's ordinary
    "could not start the job"); a test's own stand-in still replaces it while it runs, and every
    other subprocess -- `-m moonglade --version`, the MCP server run from a copied app folder,
    git, ffmpeg -- starts as normal. _real_machine_files_untouched stays as the backstop."""
    mp = pytest.MonkeyPatch()
    mp.setattr(subprocess, "Popen", _NoRealPanelJob)
    try:
        yield
    finally:
        mp.undo()


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
    than a second, conflicting source of truth.

    moonglade_paths.config_path() (the rule core._config_path() delegates to) is pinned to
    the same file, so a caller that asks the rule directly cannot reach the real one either."""
    monkeypatch.setattr(core, "_config_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr(moonglade_paths, "config_path", lambda: tmp_path / "config.json")


class _RealRegistryRefused(OSError):
    """What a test meets when it reaches the real Windows registry."""


class _NoRealRegistry(types.ModuleType):
    """Stands in for `winreg` while a test runs: every name refuses with _RealRegistryRefused
    (an OSError, so code that already tolerates a missing key degrades the same way)."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise _RealRegistryRefused(
            "a test reached the real Windows registry (winreg.%s); pass a fake winreg" % name)


@pytest.fixture(autouse=True)
def _no_real_registry(monkeypatch):
    """No test may read or write the real Windows registry. The app's one registry write
    (moonglade_gallery.register_pack_file_type) does a plain `import winreg`, so the module
    that import hands back is swapped for a stub that refuses every use; tests that pass a
    fake registry never import it and are untouched. Off Windows there is no real winreg to
    protect, and the stub stands in all the same."""
    monkeypatch.setitem(sys.modules, "winreg", _NoRealRegistry("winreg"))


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
    test keeps working unchanged and this is a no-op for them. (The branding picks live in
    settings.json, under local_dir() -- pinned to this same tmp_path by _isolated_local_files.)"""
    monkeypatch.setattr(gallery, "branding_root", lambda: tmp_path / "branding")


@pytest.fixture(autouse=True)
def _isolated_local_files(tmp_path, monkeypatch):
    """The machine files -- the pack and its .version marker, branding.json,
    branding_slots.json, mirror_session.json, serve.txt, serve.log and the icon cache --
    resolve through moonglade_paths.local_path(), which is the app folder: the real checkout.
    Same hazard and remedy as _isolated_branding above, and the same folder it already gave
    them: they used to be derived as branding_root()'s siblings, so every test was written
    against tmp_path/branding.json and tmp_path/moonglade.mgpack. Pinned separately because
    the art tree and the machine files are separate concepts now (Wave 4): a test that
    re-points one does not move the other.

    They live in local/ (settings.json among them) and a real start's move brings an older
    install's across (moonglade.migrate). The folder it brings them into (local_dir) is this
    same tmp_path, and the old app folder it brings them FROM (migrate.old_app_root) is an
    empty folder of this test's own: a test that runs main() or prepare() can never move the
    checkout's real pack, token or icons, or read its settings."""
    monkeypatch.setattr(moonglade_paths, "local_path", lambda name: tmp_path / name)
    monkeypatch.setattr(moonglade_paths, "local_dir", lambda: tmp_path)
    monkeypatch.setattr(moonglade_migrate, "old_app_root",
                        lambda: tmp_path / _OLD_APP_ROOT_NAME)
    # A relative library -- the default `pixai_backup` among them -- is anchored here, so a
    # start with no --out (main(), prepare()) opens this test's own library, never the
    # checkout's.
    monkeypatch.setattr(moonglade_paths, "library_anchor", lambda: tmp_path)


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
    the art pack now (not source), so without a container the roster is empty and every
    roster-dependent test fails. _isolated_local_files points local_path() at tmp_path, so
    _container_path() resolves to tmp_path/moonglade.mgpack -- write a
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
    seed_sealed_container(tmp_path / gallery._container_path().name)
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
def _fresh_mirror_renewal():
    """#71: the Mirror token's renewal record (core._mirror_renewal -- the failure backoff, the
    6 h success floor, the 15-minute tick, the failed token's exp) is module state that outlives
    a test. Without this, one test's successful renewal would hold the next test's renewal
    behind the 6 h floor, and a failure would leave the next one in backoff."""
    core._mirror_renewal_reset()
    yield
    core._mirror_renewal_reset()


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
def _clear_gate_caches():
    """The SCOPE_2026-09-26 image gate caches the version-keyed /features and /size-config
    reads exactly as _model_profiles caches /inference-profiles (keyed by version_id, with a
    TTL). Same isolation: one test's model rules must never answer another test's gate.
    Both reads go through _rest_get, which _no_live_card_network already blocks. The
    Unlimited Mode status cache (SCOPE_2026-09-26_unlimited-mode) is the same kind of read
    and is cleared with them, and so is Session H's /model-config read (the live context-image
    max)."""
    core._features_cache.clear()
    core._size_config_cache.clear()
    core._unlimited_cache.clear()
    core._model_config_cache.clear()
    yield
    core._features_cache.clear()
    core._size_config_cache.clear()
    core._unlimited_cache.clear()
    core._model_config_cache.clear()


@pytest.fixture(autouse=True)
def _no_live_recipes(monkeypatch):
    """moonglade_recipes rides _rest_get/_rest_post (blocked below) plus one DELETE of its
    own for a recipe set's item -- blocked the same way -- and keeps a module-level read
    cache (categories, a model's capability, market pages) that must not carry one test's
    fake answers into the next."""
    from moonglade import recipes as moonglade_recipes

    def _blocked(*a, **k):
        raise core.PixAIError("live /v2 REST blocked in tests")
    monkeypatch.setattr(moonglade_recipes, "_rest_delete", _blocked, raising=False)
    moonglade_recipes.clear_cache()
    yield
    moonglade_recipes.clear_cache()


from moonglade import inbox as _inbox_mod   # noqa: E402 -- beside the fixture that blocks it

# Captured before _no_live_inbox (below) swaps it, so a test can drive the real public GET
# against a patched requests.get and see exactly what it would send.
_REAL_INBOX_PUBLIC_GET = _inbox_mod._public_get


@pytest.fixture(autouse=True)
def _no_live_inbox(monkeypatch):
    """moonglade_inbox (Sessions R + Y) has two roads of its own beside the /v2 transport the
    fixture below blocks: the PUBLIC banner GET (sent with no credential, so it is not the
    session) and the DELETE of the owner's own reply. Both raise here unless a test swaps in an
    answer, and the module's memos (the hour's banners, the five-minute thread cache, the pushed
    notifications) are cleared so one test's PixAI can't answer another's."""
    def _blocked(*a, **k):
        raise core.PixAIError("live PixAI blocked in tests")
    monkeypatch.setattr(_inbox_mod, "_public_get", _blocked)
    monkeypatch.setattr(_inbox_mod, "_rest_delete", _blocked, raising=False)
    _inbox_mod.clear_caches()
    yield
    _inbox_mod.clear_caches()


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
    # The training routes' PUT and PATCH (Session J) ride the same /v2 road.
    monkeypatch.setattr(core, "_rest_put", _blocked, raising=False)
    monkeypatch.setattr(core, "_rest_patch", _blocked, raising=False)
    # Pin USER_ID so _make_session (now reached from generation previews) never triggers a
    # live resolve_user_id lookup. Setting the global -- not stubbing the function -- keeps
    # resolve_user_id itself testable in test_auth.
    monkeypatch.setattr(core, "USER_ID", "0", raising=False)


@pytest.fixture(autouse=True)
def _no_live_config(monkeypatch):
    """PixAI's public dynamic config (GET <api>/config/<key> -- trainLoraModels,
    trainLoraStatus) sits OUTSIDE the /v2 routes `_no_live_card_network` blocks, so it gets
    its own block (SCOPE_2026-09-26 E7): core._config_get is the ONE reader of that road and
    raises here, so every caller falls back exactly as it does when PixAI is unreachable
    (training_config -> the snapshot, training_pause -> open). A test that wants an answer
    patches core._config_get itself. The per-key cache is cleared around every test so one
    test's config cannot answer another's."""
    def _blocked(*a, **k):
        raise core.PixAIError("live /config blocked in tests")
    monkeypatch.setattr(core, "_config_get", _blocked)
    core._config_cache.clear()
    yield
    core._config_cache.clear()


# Captured at import, before `_no_live_card_network` (below) swaps them for a raising
# stub. The `pixai` fixture puts the real delegates back so a /v2 call reaches the FAKE
# and is refused BY PATH there, rather than dying on a generic "blocked" message.
_REAL_REST_GET = core._rest_get
_REAL_REST_POST = core._rest_post
_REAL_REST_PUT = core._rest_put
_REAL_REST_PATCH = core._rest_patch


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
    monkeypatch.setattr(core, "_rest_put", _REAL_REST_PUT)
    monkeypatch.setattr(core, "_rest_patch", _REAL_REST_PATCH)
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
    from moonglade.gallery import create_app
    return login_test_client(create_app(tmp_path), username=username, password=password)


def record_own_sleeps(monkeypatch):
    """Patch time.sleep to RECORD this thread's naps instead of taking them; every other
    thread keeps sleeping for real. Returns the list the naps land in.

    time.sleep is process-wide, and the process is never quiet: every create_app() starts a
    daemon _scheduler_loop that calls time.sleep(60) forever, and a whole run leaves hundreds
    of them alive. One that wakes while a bare `monkeypatch.setattr(time, "sleep",
    naps.append)` is in place calls the patch instead, records 60, and spins on it -- a pacing
    assertion then fails on naps the code under test never took (ci_local, 2026-10-03)."""
    import threading
    import time as _time
    naps, me, real = [], threading.get_ident(), _time.sleep

    def _sleep(seconds):
        if threading.get_ident() == me:
            naps.append(seconds)
        else:
            real(seconds)
    monkeypatch.setattr(_time, "sleep", _sleep)
    return naps


def session_csrf(cli):
    """The CSRF token `cli`'s signed-in session carries -- the one a real page reads out of
    window.MG_BOOT.csrf. Read off the session rather than a scraped page, because the login
    POST mints a fresh token (_establish_session): the login page's token is stale by the
    time the client is authenticated."""
    with cli.session_transaction() as sess:
        return sess.get("csrf", "")


def with_csrf(cli, body=None):
    """`body` plus this session's CSRF token, the shape every token-checking POST expects."""
    return dict(body or {}, csrf=session_csrf(cli))


# The key-sequence moment's beacon event, as moments/starfallTrigger.js posts it to
# /api/ach-event. Neutral on purpose: served JS and the server's whitelist are public, so
# the event name must not describe the gesture.
STARFALL_EVENT = "starfall"


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

