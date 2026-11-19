"""
moonglade/updater.py
====================
The auto-updater: the release check against GitHub (numeric version tuples, real vX.Y.Z tags
only), the hourly announcement tick, and the one-click apply (a fast-forward to the announced release
tag, a requirements install when they changed, a restart). Notify and apply, never silent. Moved verbatim out of
moonglade/gallery.py in the 3.21.0 split (phase 2).

The one name it needs from the gallery (the Windows no-console-window flag) is imported from
moonglade.gallery inside each function that uses it, never at the top, so importing this module
never imports the gallery.
"""
import re
import sys
import threading
import time

from moonglade import paths as _paths


# ---------------------------------------------------------------------------
# The auto-updater (P4, owner-approved 2026-08-09; scope recovered 2026-09-01).
# Notify + one-click apply, NEVER silent. Git-based, because that is what this
# app already is on every machine that runs it: a checkout, with dist committed,
# so a code update is a pull and a restart -- no build step, no installer.
#
# Why the release LIST and not /releases/latest: the asset packs ship as their
# own full releases (assets-*), and GitHub's "latest" is whichever release is
# newest, not whichever is a version. Asking for `latest` would have offered an
# asset pack as an app update. The list is filtered to real vX.Y.Z tags instead.
#
# Versions compare as NUMERIC TUPLES, never as strings: "3.10.0" < "3.9.0" is
# true alphabetically and catastrophic here -- it would tell a 3.9 user they are
# current forever, and a 3.10 user they are behind forever.
# ---------------------------------------------------------------------------
GITHUB_RELEASES_URL = ("https://api.github.com/repos/Nelnamara/moonglade-athenaeum"
                       "/releases?per_page=15")
UPDATE_CHECK_TTL = 1800          # 30 min: GitHub's unauthenticated budget is 60/hr and the
                                 # check is on-demand (Panel open), so this is generous
# A FAILED check is memoized too, but briefly. Not caching it at all meant a machine with
# no network paid a full connect timeout on every Panel open; caching it for the long TTL
# would hide a real update for half an hour after one blip. 90s splits the difference: the
# next Panel open is instant, and the one after that tries again.
UPDATE_FAILURE_TTL = 90
UPDATE_RESTART_DELAY = 2.0       # see run_update: the modal polls at 1.5s and must be able
                                 # to SEE "restarting" before the server stops answering
UPDATE_FETCH_TIMEOUT = 60        # the apply route's pre-check fetch: it happens INSIDE a
                                 # request, so it gets a shorter leash than _git's 180s
                                 # default -- a stalled network must not hold the browser
_VERSION_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
_update_cache = {"at": 0.0, "payload": None, "ttl": UPDATE_CHECK_TTL}
_update_state = {"phase": "idle", "error": "", "at": 0.0, "backup": ""}
_update_lock = threading.Lock()


def version_tuple(text):
    """(major, minor, patch) for a `vX.Y.Z` tag or a bare `X.Y.Z` version, else None.
    The ONE parser both sides of the comparison go through, so a tag and a __version__
    can never be measured differently."""
    s = str(text or "").strip()
    m = _VERSION_TAG_RE.match(s if s.startswith("v") else "v" + s)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def pick_latest_release(releases):
    """The HIGHEST-VERSIONED real app release in the list, or None.

    Three filters, each load-bearing:
      * the tag must be exactly vX.Y.Z -- which is what keeps the asset packs
        (assets-2026-08-21 and friends) out of the answer. They are full releases and
        can easily be the newest thing in the repo, so this is the whole correctness of
        the check, not a tidy-up;
      * drafts are not pullable by anyone;
      * prereleases are not what "update me" means.

    And the winner is the MAXIMUM version, not the first one listed. GitHub orders by
    creation date, so a hotfix cut on an old line AFTER a newer release (v3.5.1 created
    after v3.6.0) lists first -- and first-listed would then quietly offer a 3.6.0
    install a "newer" 3.5.1, or tell it it was current when it was not."""
    best, best_v = None, None
    for r in releases or []:
        if not isinstance(r, dict) or r.get("draft") or r.get("prerelease"):
            continue
        tag = str(r.get("tag_name") or "")
        v = version_tuple(tag) if _VERSION_TAG_RE.match(tag) else None
        if v and (best_v is None or v > best_v):
            best, best_v = r, v
    return best


def fetch_releases(opener=None, url=GITHUB_RELEASES_URL, timeout=8):
    """The release list from GitHub, unauthenticated. `opener` is the seam every test
    substitutes -- nothing in the suite touches the network."""
    import json as _json
    import urllib.request
    opener = opener or urllib.request.urlopen
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "moonglade-athenaeum-updater",
    })
    with opener(req, timeout=timeout) as resp:
        return _json.loads(resp.read().decode("utf-8"))


def check_for_update(current, opener=None, now=None, force=False):
    """Is a newer release out? Returns the check payload, cached for UPDATE_CHECK_TTL.

    A network failure is NOT an error state here: it answers `behind: False` with the
    reason attached, because the Control Panel opening while the machine is offline must
    show a Panel, not a stack trace. The failure is deliberately NOT cached -- a blip
    would otherwise hide a real update for half an hour."""
    now = time.time() if now is None else now
    cached = _update_cache.get("payload")
    ttl = _update_cache.get("ttl", UPDATE_CHECK_TTL)
    if (not force and cached and (now - _update_cache.get("at", 0)) < ttl):
        return cached
    payload = {"current": current, "latest": "", "behind": False,
               "title": "", "notes_url": "", "checked_at": now}
    try:
        rel = pick_latest_release(fetch_releases(opener=opener))
    except Exception as e:                       # noqa: BLE001 -- offline is not a failure here
        payload["error"] = "%s: %s" % (type(e).__name__, str(e)[:160])
        _update_cache.update(at=now, payload=payload, ttl=UPDATE_FAILURE_TTL)
        return payload
    if not rel:
        payload["error"] = "no versioned release found"
        _update_cache.update(at=now, payload=payload, ttl=UPDATE_FAILURE_TTL)
        return payload
    cur_v, new_v = version_tuple(current), version_tuple(rel.get("tag_name"))
    payload.update({
        "latest": str(rel.get("tag_name") or ""),
        "behind": bool(cur_v and new_v and new_v > cur_v),
        "title": str(rel.get("name") or "")[:200],
        "notes_url": str(rel.get("html_url") or ""),
    })
    _update_cache.update(at=now, payload=payload, ttl=UPDATE_CHECK_TTL)
    return payload


# ---------------------------------------------------------------------------
# The background cadence (owner ruling 2026-09-04, REVERSING 2026-09-01's "no
# background tick anywhere" -- ../moonglade-internal/DECISIONS.md, "The updater
# checks in the background").
#
# CHECK AND ANNOUNCE, NEVER APPLY. The running app asks GitHub roughly hourly
# whether a newer release is out and SAYS SO wherever the user is; applying one
# is still and only the person clicking Update in the Control Panel and
# confirming. The owner read "full background" as the app updating itself and
# said "I don't want that" -- auto-apply is explicitly rejected and no future
# scope may add it under this label. Nothing in this section, and nothing the
# scheduler tick below reaches, may touch run_update or /api/update/apply;
# dev/tests/test_updater.py pins that by walking the source.
# ---------------------------------------------------------------------------
UPDATE_TICK_SECONDS = 3600       # ~1 GitHub request an hour from the tick -- 24 a day,
                                 # against an unauthenticated budget of 60 an HOUR
UPDATE_PANEL_FLOOR = 60          # a Panel open gets a FRESH answer (it bypasses the
                                 # 30-minute TTL every other caller reads) but no oftener
                                 # than this, so opening and closing the Panel ten times
                                 # in a minute still costs GitHub one request
_update_tick = {"at": 0.0}       # when the hourly background check last ran
_update_floor = {"at": 0.0}      # when a Panel-open check last actually went to GitHub
# THE ANNOUNCEMENT: the newest version this server has discovered, and a counter that moves
# only on a TRANSITION -- the first time a given version is seen. Every hourly tick returns
# the same answer once a release is out; only a CHANGE is an event, which is what keeps the
# client's one-toast-per-version promise a property of the server rather than of luck.
_update_notice = {"version": "", "seq": 0, "at": 0.0, "payload": None}


def note_update_transition(payload, now=None):
    """Record a check's answer as the standing announcement. True only if it is NEW.

    An hourly tick that finds the release it already found an hour ago is not an event.
    An answer that is no longer `behind` (the update was applied, or the release was
    pulled) CLEARS the announcement, so the stamp stops offering an update that is not
    there any more.

    A FAILED check says nothing at all. check_for_update answers `behind: False` with a
    reason attached when GitHub is unreachable (an offline Panel must show a Panel, not a
    stack trace) -- but that is the absence of an answer, not the answer "you are current".
    Treating it as one meant a single network blip pulled the standing banner off every
    open tab and bumped the seq, and the next good tick an hour later re-announced the SAME
    version as if it were new: a second toast for one release, which is exactly the promise
    the background cadence was built to keep. A blip now leaves the announcement untouched.

    Announce-only by construction: this records a version string and a payload the client
    reads. It has no call into run_update or the apply route, and cannot acquire one
    without failing the guard test."""
    now = time.time() if now is None else now
    payload = payload or {}
    if payload.get("error"):
        return False
    latest = str(payload.get("latest") or "")
    if not payload.get("behind"):
        if _update_notice["version"]:
            _update_notice.update(version="", at=now, payload=None)
            _update_notice["seq"] += 1
        return False
    if latest == _update_notice["version"]:
        _update_notice["at"] = now
        return False
    _update_notice.update(version=latest, at=now, payload=dict(payload))
    _update_notice["seq"] += 1
    return True


def update_notice():
    """The standing announcement for the live-events payload, or None when nothing is
    out. READ ONLY -- it reports what the last check already found and never fetches, so
    riding it on the /api/jobs poll every open tab already runs costs GitHub nothing."""
    if not _update_notice.get("version"):
        return None
    p = dict(_update_notice.get("payload") or {})
    p["seq"] = _update_notice.get("seq", 0)
    return p


def run_update_tick(current, opener=None, now=None):
    """The background check. Returns the payload if it RAN, None if an hour has not passed.

    Deliberately NOT forced: check_for_update's own 30-minute TTL still applies, so a Panel
    open five minutes ago is reused rather than re-fetched. An hourly cadence against a
    half-hour cache settles at one GitHub request an hour, which is the whole budget this
    feature is allowed to spend.

    It checks and announces. It does not apply -- see this section's header."""
    now = time.time() if now is None else now
    if (now - _update_tick.get("at", 0)) < UPDATE_TICK_SECONDS:
        return None
    _update_tick["at"] = now
    payload = check_for_update(current, opener=opener, now=now)
    note_update_transition(payload, now=now)
    return payload


def check_for_update_fresh(current, opener=None, now=None):
    """A Control Panel open: a FRESH answer, floored.

    The Panel is where a person goes to ask, so it is the one caller that bypasses the
    30-minute cache -- but not oftener than UPDATE_PANEL_FLOOR seconds, so opening and
    closing it repeatedly cannot become a way to spend the hourly GitHub budget. Inside
    the floor it falls back to exactly what every other caller reads: the cache."""
    now = time.time() if now is None else now
    force = (now - _update_floor.get("at", 0)) >= UPDATE_PANEL_FLOOR
    if force:
        _update_floor["at"] = now
    payload = check_for_update(current, opener=opener, now=now, force=force)
    note_update_transition(payload, now=now)
    return payload


def _git(args, timeout=180):
    """Run one git command in THIS checkout (the app's own directory, never a cwd the
    request could influence). Returns (returncode, combined output). Never raises: a
    missing git is a refusal with a reason, not a 500."""
    from moonglade.gallery import _NO_WINDOW
    import subprocess
    try:
        p = subprocess.run(["git"] + list(args), cwd=str(_paths.APP_ROOT),
                           capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace",
                           creationflags=_NO_WINDOW)
        return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()
    except Exception as e:                       # noqa: BLE001
        return 1, "%s: %s" % (type(e).__name__, str(e)[:200])


def update_state():
    """The apply phase, as the modal polls it."""
    with _update_lock:
        return dict(_update_state)


def _set_update_state(phase, error=""):
    with _update_lock:
        _update_state.update(phase=phase, error=error, at=time.time())


# ---------------------------------------------------------------------------
# The catalog backup before every update (owner, 2026-11-18: "We used to do this when the
# catalog was a csv...."). An update can carry a schema step that runs at the next start, and
# the catalog is the one file in the library that cannot be fetched again from PixAI (ratings,
# collections, notes). So before the pull, a dated copy is made beside it and the last few are
# kept. The copy goes through SQLite's online backup API, never a file copy: the server (and a
# Panel job) may be writing the database at that moment, and a byte copy of a live database
# with its -wal beside it can be a torn file that opens as corrupt.
# ---------------------------------------------------------------------------
CATALOG_BACKUP_KEEP = 3
CATALOG_BACKUP_PREFIX = "catalog-before-update-"
_CATALOG_BACKUP_RE = re.compile(r"^catalog-before-update-\d{4}-\d{2}-\d{2}-\d{6}\.db$")


def catalog_backups(db_path):
    """This library's update backups, oldest first (only files with our exact name shape)."""
    from pathlib import Path
    folder = Path(db_path).parent
    try:
        names = sorted(n.name for n in folder.iterdir()
                       if n.is_file() and _CATALOG_BACKUP_RE.match(n.name))
    except OSError:
        return []
    return [folder / n for n in names]


def backup_catalog(db_path, keep=CATALOG_BACKUP_KEEP, now=None):
    """Copy the catalog at `db_path` to `catalog-before-update-YYYY-MM-DD-HHMMSS.db` beside it
    through SQLite's backup API, then delete all but the newest `keep` such copies. Returns the
    new file's name, or "" when there is no catalog yet (nothing to keep). Raises on a failed
    copy, and the half-written temp is removed -- the update must not go ahead on a backup
    that did not happen."""
    import os
    import sqlite3
    from pathlib import Path
    db = Path(db_path)
    if not db.is_file():
        return ""
    stamp = time.strftime("%Y-%m-%d-%H%M%S",
                          time.localtime(now if now is not None else time.time()))
    final = db.with_name(CATALOG_BACKUP_PREFIX + stamp + ".db")
    tmp = final.with_name(final.name + ".partial")
    try:
        src = sqlite3.connect(str(db))
        try:
            dst = sqlite3.connect(str(tmp))
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        os.replace(str(tmp), str(final))
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    for old in catalog_backups(db)[:-max(1, int(keep))]:
        try:
            old.unlink()
        except OSError:
            pass                                 # an old copy we cannot delete is only clutter
    return final.name


def _requirements_changed(old_head, new_head):
    """Did requirements.txt move between these two commits? The pip step is skipped
    otherwise -- a dependency install is slow, and running one on every code update
    would make the common case (no dep change at all) the expensive one."""
    if not old_head or old_head == new_head:
        return False
    rc, out = _git(["diff", "--name-only", old_head, new_head])
    if rc != 0:
        return True          # can't tell -> install, because guessing "no" can break the app
    return any(line.strip() == "requirements.txt" for line in out.splitlines())


def split_porcelain(dirty):
    """`git status --porcelain` output -> (tracked, untracked), each a list of paths.

    The split is the whole point. A modified TRACKED file is genuinely endangered by a
    pull -- the update owns that path and is about to write it. An UNTRACKED file is only
    in the way if the update actually needs that path, and real installs accumulate stray
    ones: a scratch folder, a note, a launcher somebody keeps beside the app. Refusing on
    all of them refuses most real machines forever, which is exactly what happened on the
    first live apply (a personal `boop/` the release had never heard of).

    Untracked entries keep porcelain's own shape INCLUDING the trailing slash git puts on
    a directory it is summarising as one line -- that slash is load-bearing below."""
    tracked, untracked = [], []
    for ln in (dirty or "").splitlines():
        if not ln.strip():
            continue
        (untracked if ln[:2] == "??" else tracked).append(ln[3:].strip())
    return tracked, untracked


def announced_release():
    """The release tag the update modal offered (vX.Y.Z), or "" when none is known. Read from
    what the last check already found -- the standing announcement, else the cached check --
    and NEVER fetched here: the apply moves to exactly the release that was announced, so
    "what was offered" and "what ran" are the same thing (app security review 2026-11-19,
    finding 10)."""
    for p in ((_update_notice.get("payload") or {}), (_update_cache.get("payload") or {})):
        tag = str(p.get("latest") or "")
        if p.get("behind") and _VERSION_TAG_RE.match(tag):
            return tag
    return ""


def release_commit(tag):
    """(commit sha, "") for release tag `tag` in this checkout, or (None, why-not).

    Only a real vX.Y.Z tag is ever looked up (nothing else reaches a git command line). The
    tag usually arrives with the fetch (git follows tags on the branch it fetches); when it
    did not, it is fetched by its own exact name once."""
    if not _VERSION_TAG_RE.match(str(tag or "")):
        return None, "not a release tag: %r" % (str(tag or "")[:40],)
    ref = "refs/tags/%s^{commit}" % tag
    rc, out = _git(["rev-parse", "--verify", "--quiet", ref])
    if rc != 0 or not out.strip():
        rc, fout = _git(["fetch", "--quiet", "origin",
                         "refs/tags/%s:refs/tags/%s" % (tag, tag)], timeout=UPDATE_FETCH_TIMEOUT)
        if rc != 0:
            return None, fout or ("the release tag %s isn't on GitHub" % tag)
        rc, out = _git(["rev-parse", "--verify", "--quiet", ref])
        if rc != 0 or not out.strip():
            return None, "the release tag %s isn't in this checkout" % tag
    return out.strip().splitlines()[-1].strip(), ""


def incoming_paths(tag=None):
    """The paths the pending update would write: (set, "") or (None, why-not).

    Measured against the SAME commit the apply will move to -- release tag `tag`'s commit
    (run_update), or the branch's upstream `@{u}` when no tag is named -- and only after
    FETCHING, because an un-fetched ref is a picture of whenever this checkout last looked.
    Reading a stale one would answer "nothing is incoming" and make the untracked check below
    silently permissive; a pre-check that exists to give a better answer than git's own
    error has to be right about what is actually in the way.

    The fetch writes nothing but remote-tracking refs and tags -- precisely what the apply is
    about to fetch anyway, one round trip earlier -- so it cannot change this install."""
    rc, out = _git(["fetch", "--quiet"], timeout=UPDATE_FETCH_TIMEOUT)
    if rc != 0:
        return None, out
    target = "@{u}"
    if tag:
        target, why = release_commit(tag)
        if target is None:
            return None, why
    rc, out = _git(["diff", "--name-only", "HEAD.." + target])
    if rc != 0:
        return None, out
    return {p.strip() for p in out.splitlines() if p.strip()}, ""


def untracked_in_the_way(untracked, incoming):
    """Which of `untracked` sit where the update needs to write.

    Three shapes, and each is git's OWN rule restated rather than a stricter invention:
    this pre-check exists to say it in better words than `git pull` would, so it must
    never wave through something git will then refuse.
      * an untracked FILE at an incoming path -- the checkout would overwrite it;
      * an untracked DIRECTORY containing one -- porcelain prints `d/` as a single line
        standing for everything beneath it, so an incoming `d/x.py` lands inside it and
        git refuses on the directory it never tracked;
      * an untracked FILE where the update needs a DIRECTORY (`d` here, `d/x.py` coming).
    Anything else -- the scratch folder, the note, the personal launcher -- is not a path
    this update touches, and so is none of the update's business."""
    hits = []
    for p in untracked:
        if not p:
            continue
        if p.endswith("/"):
            bare = p.rstrip("/")
            if any(inc == bare or inc.startswith(p) for inc in incoming):
                hits.append(p)
        elif p in incoming or any(inc.startswith(p + "/") for inc in incoming):
            hits.append(p)
    return hits


def run_update(restart_fn, tag, pip_fn=None, log_fn=None, backup_fn=None):
    """Back up the catalog, move to release `tag`, install deps if they moved, then restart. Runs on its own
    thread, OFF the panel-job slot, so the restart it asks for is not refused by the job it
    is itself.

    THE TARGET IS THE ANNOUNCED RELEASE TAG (app security review 2026-11-19, finding 10),
    not master's head: fetch, resolve the tag to its commit (release_commit), then
    `git merge --ff-only <that commit>` -- fast-forward ONLY, so a checkout on master behind
    the tag moves exactly to the tagged commit, and one whose history does not lead to it
    (a local commit, a rewritten branch) is refused by git with nothing changed. Master may
    then sit behind origin/master by whatever was merged after the tag; the next update
    fast-forwards from there the same way, and a plain `git pull` still works.

    Every failure stops the sequence and records the tool's own words verbatim -- a git
    or pip failure is the one thing the person watching actually needs to read, and
    paraphrasing it would cost them the fix.

    A FAILED MOVE changes nothing: --ff-only either fast-forwards or refuses. A FAILED
    PIP is the dangerous one, and it ROLLS BACK: the tree was verified free of TRACKED
    edits before the pull (the apply route refuses those), and `reset --hard` does not
    touch untracked files, so `git reset --hard <old head>` loses nothing and returns the
    install to the code whose dependencies are actually installed -- a stray untracked
    file the route allowed past is still sitting there afterwards, unread and unharmed.
    Without the rollback the install sat on new code with old deps -- and worse, a
    "Try again" would have found the pull already applied, seen no requirements diff
    against the new HEAD, skipped pip entirely and declared success on a broken install.
    The rollback is what makes retry mean retry.

    FIRST, before anything is pulled, `backup_fn` copies the catalog (backup_catalog). A
    backup that fails stops the update with nothing changed: the copy is the reason it is
    safe to go on.

    Both outcomes are also written to the activity log (jobs.jsonl), which is the only
    part of this that survives the restart the success path is about to trigger."""
    def _record(status, error=""):
        if not log_fn:
            return
        try:
            log_fn(status, error)
        except Exception:                        # noqa: BLE001 -- logging never breaks the job
            pass

    if backup_fn is not None:
        _set_update_state("backup")
        try:
            name = backup_fn() or ""
        except Exception as e:                   # noqa: BLE001
            msg = ("couldn't back up the catalog before updating, so nothing was changed: "
                   "%s: %s" % (type(e).__name__, str(e)[:300]))
            _set_update_state("failed", msg)
            _record("failed", msg)
            return False
        with _update_lock:
            _update_state["backup"] = name
    rc, head_out = _git(["rev-parse", "HEAD"])
    old_head = head_out.strip() if rc == 0 else ""
    _set_update_state("pulling")
    rc, out = _git(["fetch", "--quiet"], timeout=UPDATE_FETCH_TIMEOUT)
    if rc != 0:
        msg = "git fetch failed:\n" + out[:600]
        _set_update_state("failed", msg)
        _record("failed", msg)
        return False
    commit, why = release_commit(tag)
    if commit is None:
        msg = "couldn't find release %s:\n%s" % (str(tag)[:40], why[:600])
        _set_update_state("failed", msg)
        _record("failed", msg)
        return False
    rc, out = _git(["merge", "--ff-only", commit])
    if rc != 0:
        msg = "git couldn't move this checkout to %s:\n%s" % (tag, out[:600])
        _set_update_state("failed", msg)
        _record("failed", msg)
        return False
    rc, head_out = _git(["rev-parse", "HEAD"])
    new_head = head_out.strip() if rc == 0 else ""
    if _requirements_changed(old_head, new_head):
        _set_update_state("deps")
        rc, out = (pip_fn or _pip_install)()
        if rc != 0:
            msg = "dependency install failed:\n" + out[:600]
            if old_head:
                rrc, rout = _git(["reset", "--hard", old_head])
                msg += ("\n\nRolled back to %s — this install is unchanged."
                        % old_head[:12]) if rrc == 0 else (
                        "\n\nTHE ROLLBACK ALSO FAILED: " + rout[:300]
                        + "\nThis checkout is on the new code with the old dependencies; "
                          "run `git reset --hard %s` by hand." % old_head[:12])
            _set_update_state("failed", msg)
            _record("failed", msg)
            return False
    _set_update_state("restarting")
    _record("done")
    # The modal polls status at 1.5s and hands over to the ping-watch when it SEES
    # "restarting". Exiting immediately raced that poll: the server could stop answering
    # before the phase was ever observed, and the modal sat on "updating..." forever.
    # (The client also hands over on the transport error that follows -- belt and braces,
    # because this sleep is a timing assumption and that one is not.)
    time.sleep(UPDATE_RESTART_DELAY)
    try:
        restart_fn()
    except Exception as e:                       # noqa: BLE001
        msg = "restart failed: %s" % str(e)[:200]
        _set_update_state("failed", msg)
        _record("failed", msg)
        return False
    return True


def _pip_install():
    """pip install -r requirements.txt against THIS interpreter (sys.executable -- never a
    bare `pip`, which on Windows can easily be a different environment's)."""
    from moonglade.gallery import _NO_WINDOW
    import subprocess
    root = _paths.APP_ROOT
    try:
        p = subprocess.run([sys.executable, "-m", "pip", "install", "-r",
                            str(_paths.requirements_path())],
                           cwd=str(root), capture_output=True, text=True, timeout=900,
                           encoding="utf-8", errors="replace",
                           creationflags=_NO_WINDOW)
        return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()
    except Exception as e:                       # noqa: BLE001
        return 1, "%s: %s" % (type(e).__name__, str(e)[:200])
