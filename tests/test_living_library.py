"""The living library (2026-09-06) -- the job list, the published-artwork sweep, and the
two cadences the owner set by hand.

    "I would love to get away from all these manual action button pushes in the control
    panel. These tasks are an annoyance now that the app is the way it is. It's not just a
    backup dump. It's a living library that should update itself and its data without my
    need to clicky click."

EVERY CADENCE HERE IS TESTED ON A MOCK CLOCK. `living_due` and `artworks_page_needed` are
pure functions of (state, now) precisely so that a fifteen-minute sweep, a forty-eight-hour
like-count tier and a SIXTY-DAY staleness backstop can each be proven at both edges without
a single real sleep -- the sixty-day one being the obvious reason: there is no other way to
test it at all.

NO REAL PIXAI. The sweep talks to the transport seam, so it is driven here by a FakePixAI
answering `listArtworks`, exactly as tests/test_pixai_client.py drives the real client.
"""
import inspect
import io
import json
import time
import unittest.mock as _mock
from pathlib import Path
from types import SimpleNamespace

import pytest

import moonglade_gallery as g
import moonglade_backup as core
from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog, load_catalog

from tests.conftest import login_test_client
from tests.fake_pixai import FakePixAI

SRC = Path(__file__).resolve().parents[1]
DAY = 86400.0
# The mock clock's "now". Deliberately AFTER the fixture rows' own created_at dates: the
# 90-day tier is an age test, so a `now` in the past would make every row read as young and
# a short-circuit test would pass for entirely the wrong reason.
NOW = 1_800_000_000.0            # 2027-01-15


def _iso(days_ago):
    """A catalog created_at that many days before NOW, in the shape rows really carry."""
    import datetime as _dt
    return _dt.datetime.fromtimestamp(NOW - days_ago * DAY, _dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _client(tmp_path, rows=()):
    save_catalog(tmp_path / "catalog.db",
                 list(rows) or [_row(media_id="1", filename="a_1.png",
                                     created_at="2025-01-01T00:00:00")])
    return login_test_client(create_app(tmp_path))


@pytest.fixture(autouse=True)
def _fresh_sweep_state():
    """The sweep's recency and 48h-tier stamps are module-level (the same shape the contest
    sweep's _contest_sync_last_ok has, and for the same reason: they belong to the process,
    not to one create_app). Reset around every test so one test's sweep cannot buy the
    next one fifteen minutes of silence."""
    before = dict(g._artworks_state)
    g._artworks_state.update({"at": 0.0, "deep_at": 0.0, "changed": 0, "pages": 0})
    yield
    g._artworks_state.update(before)


# =====================================================================================
# 1. THE JOB LIST -- one cadence per job, each proven at both edges of its own timer
# =====================================================================================

def _jobs(**overrides):
    """The shipped default list, with per-action overrides -- so a cadence test states
    only what it is testing and inherits the real shipped defaults for everything else."""
    rows = g.living_defaults()
    for row in rows:
        row.update(overrides.get(row["action"], {}))
    return rows


def test_the_shipped_list_is_the_scopes_own_list():
    """Owner call 1 was "a LIST of jobs, each on its own timer" -- and this is the list.
    Named here so a job silently disappearing (or a cadence silently drifting off the
    owner's own answers) fails by name rather than by nobody noticing."""
    by_action = {j["action"]: j for j in g.LIVING_ALL}
    assert by_action["artworks-sweep"]["interval_s"] == 900          # call 3: 15 minutes
    assert by_action["sync"]["interval_s"] == 6 * 3600
    assert by_action["sync"]["then"] == "backfill-phash"             # "after each Sync"
    assert by_action["sync-videos"]["interval_s"] == 24 * 3600       # nightly
    assert by_action["reconcile-deleted"]["interval_s"] == 7 * DAY   # weekly
    assert by_action["sync-similar"]["needs"] == "torch"
    # call 5: the three full-cost jobs, and ONLY those three, on the staleness backstop
    assert {j["action"] for j in g.LIVING_STALE_JOBS} == {
        "resync-full", "rebuild-similar", "rebuild-thumbs"}
    assert all(j["interval_s"] == 60 * DAY for j in g.LIVING_STALE_JOBS)


@pytest.mark.parametrize("action,interval", [
    ("artworks-sweep", 900.0),
    ("sync", 6 * 3600.0),
    ("sync-videos", 24 * 3600.0),
    ("reconcile-deleted", 7 * DAY),
    ("sync-similar", 24 * 3600.0),
])
def test_each_job_fires_on_its_own_timer_and_not_a_second_early(action, interval):
    """THE CADENCE, on a mock clock: one second before its interval a job is not due, and
    at its interval it is. Per job, because the whole point of owner call 1 is that these
    are separate timers -- the old scheduler could hold exactly one."""
    t0 = 1_000_000.0
    jobs = _jobs(**{a: {"enabled": a == action, "last_run": t0}
                    for a in [j["action"] for j in g.LIVING_ALL]})
    due, _ = living_due_all(jobs, t0 + interval - 1)
    assert action not in due, "%s fired a second early" % action
    due, _ = living_due_all(jobs, t0 + interval)
    assert due == [action]


def living_due_all(jobs, now):
    """living_due with the gates a test does not care about held open: torch present, and
    every action runnable. The refusals themselves are tested on their own below."""
    return g.living_due(jobs, now, torch=True, is_runnable=lambda a: True)


def test_a_disabled_job_never_becomes_due_no_matter_how_long_it_waits():
    t0 = 1_000_000.0
    jobs = _jobs(**{j["action"]: {"enabled": False, "last_run": t0} for j in g.LIVING_ALL})
    due, baselined = living_due_all(jobs, t0 + 400 * DAY)
    assert due == [] and baselined == []


def test_a_job_that_has_never_run_is_due_at_once_but_a_staleness_job_is_not():
    """The asymmetry that keeps a fresh install from opening with a storm.

    An ordinary job with no recorded run is due immediately -- that is what "keep the
    library current" means on a machine that just installed. A STALENESS job with no
    recorded run is NOT: it is baselined to now and fires sixty days later, because
    otherwise every fresh install would begin by re-walking its whole history, re-embedding
    every image and rebuilding every thumbnail."""
    t0 = 1_000_000.0
    due, baselined = living_due_all(_jobs(), t0)
    assert "sync" in due and "artworks-sweep" in due
    assert set(baselined) == {"resync-full", "rebuild-similar", "rebuild-thumbs"}
    assert not (set(baselined) & set(due)), "a baselined job must not also fire"


def test_the_sixty_day_staleness_backstop_holds_for_fifty_nine_days_and_then_fires():
    """Owner call 5, at both edges. There is no way to test a sixty-day timer except on a
    clock you hold, which is exactly why living_due takes `now`."""
    t0 = 1_000_000.0
    jobs = _jobs(**{j["action"]: {"enabled": False} for j in g.LIVING_JOBS})
    for row in jobs:
        if row["action"] in {"resync-full", "rebuild-similar", "rebuild-thumbs"}:
            row["last_run"] = t0
    due, baselined = living_due_all(jobs, t0 + 59 * DAY)
    assert due == [] and baselined == []
    due, _ = living_due_all(jobs, t0 + 60 * DAY)
    assert due == ["resync-full", "rebuild-similar", "rebuild-thumbs"]


def test_similar_jobs_stay_asleep_when_the_ml_stack_is_absent():
    """"Top up Similar nightly WHEN TORCH IS PRESENT" -- a nightly job that cannot run is
    not a job, it is a nightly failure in the Activity ledger."""
    t0 = 1_000_000.0
    jobs = _jobs(**{j["action"]: {"enabled": True, "last_run": t0} for j in g.LIVING_ALL})
    due, _ = g.living_due(jobs, t0 + 400 * DAY, torch=False, is_runnable=lambda a: True)
    assert "sync-similar" not in due and "rebuild-similar" not in due
    due, _ = g.living_due(jobs, t0 + 400 * DAY, torch=True, is_runnable=lambda a: True)
    assert "sync-similar" in due and "rebuild-similar" in due


def test_an_unknown_action_in_the_saved_file_is_dropped_not_run():
    """living_merge is the file's only door. A hand-edited (or downgraded, or malicious)
    schedule.json naming something this build does not ship must not be able to name work
    the automation will then start."""
    merged = g.living_merge([{"action": "dedup-delete", "enabled": True, "interval_s": 60},
                             {"action": "artworks-sweep", "enabled": False}])
    assert "dedup-delete" not in {r["action"] for r in merged}
    assert [r["action"] for r in merged] == [j["action"] for j in g.LIVING_ALL]
    assert next(r for r in merged if r["action"] == "artworks-sweep")["enabled"] is False


def test_living_merge_clamps_a_silly_interval_and_survives_junk():
    merged = g.living_merge([{"action": "sync", "interval_s": 0.5},
                             {"action": "sync-videos", "interval_s": "nonsense"},
                             "not-a-dict", None])
    by = {r["action"]: r for r in merged}
    assert by["sync"]["interval_s"] == g.LIVING_MIN_INTERVAL_S
    assert by["sync-videos"]["interval_s"] == 24 * 3600.0     # fell back to the default
    merged = g.living_merge([{"action": "sync", "interval_s": 10 ** 9}])
    assert next(r for r in merged if r["action"] == "sync")["interval_s"] \
        == g.LIVING_MAX_INTERVAL_S


# =====================================================================================
# 2. NOTHING DESTRUCTIVE IS EVER AUTOMATIC
# =====================================================================================

def _runnable(tmp_path):
    """The real _living_runnable closure out of a real create_app -- the one place the
    automation policy lives, reached the way the loop reaches it."""
    app = create_app(tmp_path)
    src = inspect.getsource(g.create_app)
    assert "def _living_runnable(action):" in src
    return app


def test_the_automation_policy_refuses_every_must_stay_manual_job(tmp_path):
    """The scope's "must stay manual" row -- organize, undo organize, dedup
    quarantine/delete, restore orphans -- can never be started by the automation, and the
    set that CAN is a literal in the module, not anything a route or a file can name."""
    _runnable(tmp_path)
    src = inspect.getsource(g.create_app)
    body = src[src.index("def _living_runnable(action):"):]
    body = body[:body.index("def _living_run(")]
    # The refusal it inherits from the single-job scheduler, still stated in code
    assert 'spec["destructive"]' in body and 'spec.get("advanced")' in body
    # and the widening is a closed, hard-coded set -- never a client-supplied one
    stale = inspect.getsource(g).split("LIVING_STALE_JOBS = (")[1].split("\n)")[0]
    for manual in ("organize", "undo-organize", "dedup-apply", "dedup-delete",
                   "restore-orphans"):
        assert '"%s"' % manual not in stale, \
            "%s must never be reachable by the staleness backstop" % manual


def test_no_must_stay_manual_job_is_even_in_the_shipped_list(tmp_path):
    """Belt and braces. The list itself is the first gate: a job the automation could
    start has to BE in LIVING_ALL, and the four the scope's audit puts in "must stay
    manual" -- plus dedup's delete variant -- are simply not there. The Panel's own
    action table is asked through the real summary route rather than a copy of it."""
    cli = _client(tmp_path)
    summary = cli.get("/api/panel/summary").get_json()
    table = {a["action"]: a for a in (summary.get("all_actions") or summary["actions"])}
    for action in ("organize", "undo-organize", "dedup-apply", "dedup-delete",
                   "restore-orphans"):
        assert table[action]["destructive"] is True, "%s stopped being destructive" % action
        assert action not in {j["action"] for j in g.LIVING_ALL}


# =====================================================================================
# 3. THE ARTWORKS SWEEP -- the short-circuit and the owner's like-count tier
# =====================================================================================

def _node(mid, artwork_id="a1", likes=0, video_mid=None):
    n = {"mediaId": mid, "id": artwork_id, "title": "t", "visibility": "PUBLIC",
         "likedCount": likes, "commentCount": 0, "aesScore": "", "tacks": [],
         "isNsfw": False, "isSensitive": False, "extra": {}}
    if video_mid:
        n["videoMediaId"] = video_mid
    return n


def test_a_page_of_works_we_already_know_and_that_are_old_is_spent():
    """artworks_page_needed IS the short-circuit and the tier in one predicate."""
    now = NOW
    old = now - 200 * DAY
    index = {"m1": ("a1", old), "m2": ("a2", old)}
    page = [_node("m1"), _node("m2")]
    assert g.artworks_page_needed(page, index, now, deep=False) is False


def test_a_never_seen_work_always_keeps_the_sweep_walking():
    now = NOW
    index = {"m1": ("a1", now - 200 * DAY)}
    assert g.artworks_page_needed([_node("m1"), _node("m9")], index, now, deep=False) is True


def test_works_younger_than_ninety_days_ride_every_sweep():
    """Owner call 4, the near half: "younger works ride every sweep"."""
    now = NOW
    young = {"m1": ("a1", now - 89 * DAY)}
    old = {"m1": ("a1", now - 91 * DAY)}
    assert g.artworks_page_needed([_node("m1")], young, now, deep=False) is True
    assert g.artworks_page_needed([_node("m1")], old, now, deep=False) is False


def test_older_works_come_back_into_the_sweep_once_the_forty_eight_hours_are_up():
    """Owner call 4, the far half: "works older than 90 days refresh their like-counts at
    most once every 48 hours". Expressed as the deep pass, because the sweep always starts
    at the newest end -- one stamp says the same thing as 36k per-row timestamps."""
    now = NOW
    index = {"m1": ("a1", now - 200 * DAY)}
    assert g.artworks_page_needed([_node("m1")], index, now, deep=False) is False
    assert g.artworks_page_needed([_node("m1")], index, now, deep=True) is True
    assert g.ARTWORKS_DEEP_S == 48 * 3600
    assert g.ARTWORKS_YOUNG_DAYS == 90


def test_a_published_work_whose_image_was_never_downloaded_does_not_hold_the_walk_open():
    """THE SHORT-CIRCUIT COULD NOT CONVERGE past a run of published works with no local
    image. Such a work has no catalog row at all, so it is not in the artwork index and
    read as "never merged" -- NEEDED -- on every single sweep, forever. Any account with
    undownloaded published works before a stable tail had every fifteen-minute sweep walk
    through all of them, which is not the "one or two pages" the wiki promises.

    A node the sweep can never write is not a reason to keep paying for pages: apply_
    artwork_meta only UPDATEs rows that exist, so a media_id with no local row is a
    confirmed miss, not a maybe. `local` -- every media_id the catalog holds -- is what
    tells the two apart:
      * a row exists but claims no artwork yet -> newly published, NEEDED
      * no row at all -> confirmed unmatched, counts as spent
    """
    now = NOW
    old = now - 200 * DAY
    index = {"m1": ("a1", old)}
    local = {"m1"}
    page = [_node("m1"), _node("gone1"), _node("gone2")]
    # without the local set the old answer stands, and it never converges
    assert g.artworks_page_needed(page, index, now, deep=False) is True
    # with it, the two undownloaded works are the misses they are, and the page is spent
    assert g.artworks_page_needed(page, index, now, deep=False, local=local) is False
    # a work that IS downloaded but has never been merged is still the reason to walk
    assert g.artworks_page_needed(
        [_node("m2")], index, now, deep=False, local={"m1", "m2"}) is True
    # an animation is matched by either of its two ids, exactly as the index lookup is
    assert g.artworks_page_needed(
        [_node("p1", video_mid="v1")], index, now, deep=False, local={"v1"}) is True


def test_the_sweep_stops_after_two_spent_pages_of_undownloaded_works(tmp_path, monkeypatch):
    """The same fix, driven through the real sweep: a library whose published works are
    mostly undownloaded must still reach the grace stop instead of walking every page."""
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="m1", filename="a_m1.png", artwork_id="a1",
                           created_at=_iso(200))])
    pages = [[_node("m1", "a1")] + [_node("gone%d-%d" % (p, i)) for i in range(5)]
             for p in range(6)]
    feed = _sweep_env(monkeypatch, pages)
    g._artworks_state["deep_at"] = NOW                # a deep pass happened just now
    res = g.artworks_sweep(tmp_path, db, force=True, now=NOW)
    assert res["deep"] is False
    assert feed.fetched == g.ARTWORKS_GRACE, \
        "a run of never-downloaded works must not defeat the two-page grace stop"


def test_an_undateable_row_is_treated_as_young_rather_than_silently_abandoned():
    """A row whose created_at will not parse must not become a work the sweep quietly
    stops refreshing forever."""
    now = NOW
    assert g.artworks_page_needed([_node("m1")], {"m1": ("a1", None)}, now, deep=False) is True


class _Pages:
    """A fake listArtworks: newest-first pages, walked by the `before` cursor exactly as
    PixAI's own Relay connection is."""

    def __init__(self, pages):
        self.pages = pages
        self.fetched = 0

    def __call__(self, call):
        before = (call.variables or {}).get("before")
        i = 0 if before is None else int(before)
        self.fetched += 1
        if i >= len(self.pages):
            return {"artworks": {"edges": [], "pageInfo": {}}}
        return {"artworks": {
            "edges": [{"node": n} for n in self.pages[i]],
            "pageInfo": {"hasPreviousPage": i + 1 < len(self.pages),
                         "startCursor": str(i + 1)}}}


def _sweep_env(monkeypatch, pages):
    feed = _Pages(pages)
    fake = FakePixAI(user_id="u-test").on("listArtworks", feed)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: fake)
    monkeypatch.setattr(g.time, "sleep", lambda *_a, **_k: None)   # no real pacing waits
    return feed


def test_the_quiet_sweep_stops_after_two_known_pages_instead_of_walking_it_all(
        tmp_path, monkeypatch):
    """The whole reason a fifteen-minute sweep is affordable. The full --sync-artworks is a
    re-walk of every published work, 50 a page, always to the last page; this mirrors
    run_download --update's own two-consecutive-known-pages stop (`update_grace`)."""
    now = NOW
    old_iso = _iso(400)               # comfortably past the 90-day young window
    rows = [_row(media_id="m%d" % i, artwork_id="a%d" % i, is_published="1",
                 created_at=old_iso, filename="f%d.png" % i) for i in range(1, 61)]
    save_catalog(tmp_path / "catalog.db", rows)
    pages = [[_node("m%d" % i, "a%d" % i) for i in range(1 + p * 10, 11 + p * 10)]
             for p in range(6)]
    feed = _sweep_env(monkeypatch, pages)
    g._artworks_state["deep_at"] = now                # a deep pass happened just now
    res = g.artworks_sweep(tmp_path, tmp_path / "catalog.db", force=True, now=now)
    assert res is not None
    assert feed.fetched == g.ARTWORKS_GRACE, \
        "a quiet sweep must cost one or two pages, not the whole walk (got %d)" % feed.fetched
    assert res["deep"] is False


def test_the_very_first_sweep_walks_everything_and_then_goes_quiet(tmp_path, monkeypatch):
    """An install that has never swept has no idea what it holds, so its FIRST sweep is a
    deep one -- there is nothing else it could honestly be. What matters is that it does
    not repeat: the 48-hour stamp it leaves is what makes every sweep after it cost one or
    two pages, and that stamp is persisted (schedule.json's artworks_deep_at) so a restart
    is not a fresh install."""
    now = NOW
    old_iso = _iso(400)               # comfortably past the 90-day young window
    rows = [_row(media_id="m%d" % i, artwork_id="a%d" % i, is_published="1",
                 created_at=old_iso, filename="f%d.png" % i) for i in range(1, 41)]
    save_catalog(tmp_path / "catalog.db", rows)
    pages = [[_node("m%d" % i, "a%d" % i) for i in range(1 + p * 10, 11 + p * 10)]
             for p in range(4)]
    feed = _sweep_env(monkeypatch, pages)
    assert g._artworks_state["deep_at"] == 0.0
    first = g.artworks_sweep(tmp_path, tmp_path / "catalog.db", force=True, now=now)
    assert first["deep"] is True and feed.fetched == len(pages)
    feed.fetched = 0
    second = g.artworks_sweep(tmp_path, tmp_path / "catalog.db", force=True, now=now + 900)
    assert second["deep"] is False and feed.fetched == g.ARTWORKS_GRACE
    assert "artworks_deep_at" in inspect.getsource(g.create_app)


def test_the_forty_eight_hour_deep_pass_walks_the_whole_history(tmp_path, monkeypatch):
    """The other side of the tier: once the 48 hours are up, every age is in scope again,
    so the sweep walks to the end -- which is what refreshes an old work's like count."""
    now = NOW
    old_iso = _iso(400)               # comfortably past the 90-day young window
    rows = [_row(media_id="m%d" % i, artwork_id="a%d" % i, is_published="1",
                 created_at=old_iso, filename="f%d.png" % i) for i in range(1, 41)]
    save_catalog(tmp_path / "catalog.db", rows)
    pages = [[_node("m%d" % i, "a%d" % i) for i in range(1 + p * 10, 11 + p * 10)]
             for p in range(4)]
    feed = _sweep_env(monkeypatch, pages)
    g._artworks_state["deep_at"] = now - 49 * 3600          # 48h have passed
    res = g.artworks_sweep(tmp_path, tmp_path / "catalog.db", force=True, now=now)
    assert res["deep"] is True
    assert feed.fetched == len(pages), "a deep pass must reach the last page"
    # ...and it remembers, so the very next sweep is quiet again
    assert g._artworks_state["deep_at"] >= now - 1


def test_the_sweep_refuses_to_run_again_inside_its_own_fifteen_minutes(tmp_path, monkeypatch):
    """The "ran recently" guard the contest sweep has, at the interval the owner chose.
    `force` (the publish kick, Run now) goes straight past it -- that is its whole job."""
    _sweep_env(monkeypatch, [[]])
    now = NOW
    assert g.artworks_sweep(tmp_path, tmp_path / "catalog.db", now=now) is not None
    g._artworks_state["at"] = now                            # pretend it just finished
    assert g.artworks_sweep(tmp_path, tmp_path / "catalog.db", now=now + 899) is None
    assert g.artworks_sweep(tmp_path, tmp_path / "catalog.db", now=now + 900) is not None
    g._artworks_state["at"] = now + 900
    assert g.artworks_sweep(tmp_path, tmp_path / "catalog.db",
                            force=True, now=now + 901) is not None


def test_a_second_sweep_cannot_start_while_one_is_running(tmp_path):
    """Single-flight, the contest sweep's own lock discipline: four triggers, one sweep."""
    assert g._artworks_lock.acquire(False)
    try:
        assert g.artworks_sweep_kick(tmp_path, tmp_path / "catalog.db", force=True) is None
    finally:
        g._artworks_lock.release()


def test_the_sweep_announces_only_when_it_actually_changed_something(tmp_path, monkeypatch):
    """Item 6, the announce half: a completion reaches the owner through the Activity
    ledger -- and a fifteen-minute heartbeat that logged a row on EVERY tick would bury
    the events that matter under its own noise."""
    now = NOW
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="m1", artwork_id="a1", is_published="1",
                       filename="f1.png", created_at=_iso(400))])
    events = []
    _sweep_env(monkeypatch, [[_node("m1", "a1", likes=7)]])
    res = g.artworks_sweep(tmp_path, tmp_path / "catalog.db", force=True, now=now,
                           log_event=lambda jid, **f: events.append((jid, f)))
    assert res["changed"] == 1 and len(events) == 1
    assert events[0][1]["action"] == "artworks-sweep"
    assert events[0][1]["status"] == "done"

    # nothing to write -> nothing announced
    events.clear()
    g._artworks_state["at"] = 0.0
    _sweep_env(monkeypatch, [[]])
    g.artworks_sweep(tmp_path, tmp_path / "catalog.db", force=True, now=now,
                     log_event=lambda jid, **f: events.append((jid, f)))
    assert events == []


def test_a_failed_page_does_not_buy_the_sweep_fifteen_minutes_of_silence(tmp_path,
                                                                        monkeypatch):
    """artwork_list_gql fails SOFT to None. An incomplete sweep still writes what it got --
    that data is real -- but the fifteen-minute guard measures COMPLETED sweeps, exactly as
    the contest sweep's does, and a broken run must not stamp the 48-hour tier either: that
    would tell two days' worth of sweeps that old works had been refreshed when they had
    not."""
    monkeypatch.setattr(core, "artwork_list_gql", lambda *a, **k: None)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: FakePixAI(user_id="u"))
    now = NOW
    res = g.artworks_sweep(tmp_path, tmp_path / "catalog.db", force=True, now=now)
    assert res["pages"] == 0 and res["changed"] == 0 and res["incomplete"] is True
    assert g._artworks_state["at"] == 0.0, "a failed sweep bought itself the recent-guard"
    assert g._artworks_state["deep_at"] == 0.0, "a failed sweep stamped the 48-hour tier"
    # ...so the very next attempt is allowed straight away rather than waiting 15 minutes
    assert g.artworks_sweep(tmp_path, tmp_path / "catalog.db", now=now + 1) is not None


# =====================================================================================
# 4. THE WRITE -- narrow, and it cannot lose the owner's own columns
# =====================================================================================

def test_apply_artwork_meta_writes_eleven_columns_and_touches_nothing_else(tmp_path):
    """The 2026-09-03 data-loss class, closed here by construction rather than by a carry
    helper: this UPDATEs eleven named PixAI-owned columns on rows that already exist. A
    rating, a collection, a filename, a prompt cannot be reached by it at all."""
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="m1", filename="keep.png", rating="5",
                           collections="Favourites", prompt_full="a wolf",
                           created_at="2026-01-01T00:00:00Z")])
    changed = g.apply_artwork_meta(db, [{
        "media_id": "m1", "artwork_id": "aX", "title": "Wolf", "is_published": "1",
        "is_nsfw": "0", "is_sensitive": "0", "liked_count": "12", "comment_count": "3",
        "aes_score": "6.1", "art_tags": "wolf, night", "blurhash": "L1", "nsfw_scores": "{}"}])
    assert changed == 1
    row = load_catalog(db)[0]
    assert row["rating"] == "5" and row["collections"] == "Favourites"
    assert row["filename"] == "keep.png" and row["prompt_full"] == "a wolf"
    assert row["artwork_id"] == "aX" and row["liked_count"] == "12"
    assert row["title"] == "Wolf" and row["art_tags"] == "wolf, night"


def test_apply_artwork_meta_never_invents_a_row(tmp_path):
    """"Unmatched artworks have no downloaded image" -- the full sync's own rule. A sweep
    that created rows would fabricate library entries for images that are not on disk."""
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="m1", filename="a.png")])
    assert g.apply_artwork_meta(db, [{"media_id": "ghost", "artwork_id": "a9"}]) == 0
    assert len(load_catalog(db)) == 1


def test_an_animations_own_row_is_tagged_through_its_video_media_id(tmp_path, monkeypatch):
    """Issue #20's shape, kept alive by the sweep: an animation's catalog row is keyed by
    its MP4's media_id, not the poster's, so both keys want the metadata."""
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="poster1", filename="p.png",
                           created_at=_iso(400)),
                      _row(media_id="vid1", filename="v.mp4", is_video="1",
                           created_at=_iso(400))])
    _sweep_env(monkeypatch, [[_node("poster1", "aV", video_mid="vid1")]])
    g.artworks_sweep(tmp_path, db, force=True, now=NOW)
    rows = {r["media_id"]: r for r in load_catalog(db)}
    assert rows["poster1"]["artwork_id"] == "aV"
    assert rows["vid1"]["artwork_id"] == "aV"


# =====================================================================================
# 5. THE TRIGGERS -- boot, tick, publish, Run now
# =====================================================================================

def test_the_sweep_has_all_four_triggers_wired(tmp_path):
    """Owner call 2 was "BOTH the publish-kick and the periodic sweep"; the scope adds the
    boot kick and Run now. All four go through the one single-flight wrapper."""
    src = inspect.getsource(g.create_app)
    assert "_artworks_sync_startup" in src and "ARTWORKS_STARTUP_DELAY" in src
    assert "threading.Thread(target=_artworks_sync_startup" in src
    # the publish kick: forced, and it lives in the My Art publish route
    publish = src[src.index("def api_myart_publish():"):]
    publish = publish[:publish.index("def _lineage_card(")]
    assert "_artworks_kick(force=True)" in publish, \
        "publishing must re-read PixAI at once -- that is the incident this was scoped from"
    # the periodic tick, and Run now
    assert "_living_tick()" in src and "def api_panel_sweep():" in src


def test_the_publish_kick_fires_for_unpublish_and_retag_too(tmp_path):
    """"publish/unpublish/retag" -- each changes what listArtworks returns, so each is a
    reason to read it back. The kick sits AFTER the whole if/else, not inside the publish
    branch."""
    src = inspect.getsource(g.create_app)
    publish = src[src.index("def api_myart_publish():"):]
    publish = publish[:publish.index("def _lineage_card(")]
    kick = publish.index("_artworks_kick(force=True)")
    mirror = publish.index("publish_state(db_path, mid, **changed)")
    assert kick > mirror
    # at the route's own body indent (8 spaces), i.e. outside the action branches
    assert "\n        try:\n            _artworks_kick(force=True)" in publish


def test_the_living_tick_rides_the_existing_sixty_second_loop_and_adds_no_thread():
    """The standing rule -- "web surfaces register jobs, they never add a second poll loop"
    (DECISIONS.md 2026-07-24). This process has ONE periodic tick; the job list joins it,
    exactly as the release check already does, and for the same reason it must sit OUTSIDE
    the schedule's own try/continue chain: that chain's first `continue` is "no standing
    order", which is the default on every install."""
    src = inspect.getsource(g.create_app)
    loop = src[src.index("def _scheduler_loop():"):]
    loop = loop[:loop.index("def ", 40)]
    body = loop[:loop.index("threading.Thread(target=_scheduler_loop")]
    assert "\n            _living_tick()" in body
    assert body.index("_living_tick()") < body.index("            try:")
    assert "threading.Timer" not in body and body.count("threading.Thread") == 0


def test_the_tick_starts_at_most_one_job_and_never_doubles_the_standing_order():
    """One Panel slot. A tick that started four things would spawn one and silently drop
    three -- and the legacy standing order still owns whatever action it names, so the list
    never takes turns losing the slot to it."""
    src = inspect.getsource(g.create_app)
    tick = src[src.index("def _living_tick():"):]
    tick = tick[:tick.index("def _scheduler_loop():")]
    assert "return                      # one job per tick" in tick
    assert "if action == standing:" in tick
    assert "if _update_busy():" in tick, "an update mid-flight must hold the list off"


def test_the_backfill_chain_is_a_property_of_the_action_not_of_who_started_it(tmp_path):
    """The wiki states the chain as a plain fact about Sync now: "the one-shot refresh,
    then a perceptual-hash backfill straight after it". It was true only when the living
    library's own tick started the job. A manual Run now click passed no follow-on, and
    neither did the legacy standing-order scheduler -- and an owner who already had the
    standing order set to "sync" (the schedule's own default action) got that path
    forever, with the list's own "sync" row permanently deferred to it.

    All three trigger paths now look the follow-on up from the same table."""
    create_app(tmp_path)
    src = inspect.getsource(g.create_app)
    lookup = 'then=LIVING_BY_ACTION.get(action, {}).get("then")'
    run_route = src[src.index("def api_panel_run():"):]
    run_route = run_route[:run_route.index("def _close_orphan_if_resolved(")]
    assert lookup in run_route, "a manual Run now must chain what the tick chains"
    loop = src[src.index("def _scheduler_loop():"):]
    loop = loop[:loop.index("threading.Thread(target=_scheduler_loop")]
    assert lookup in loop, "the legacy standing order must chain it too"
    living = src[src.index("def _living_run(action):"):]
    living = living[:living.index("_bg_release_check = ")]
    assert lookup in living


def test_the_manual_click_really_starts_the_follow_on_job(tmp_path):
    """Behavioural, not a source read: drive /api/panel/run through the real Flask app with
    the subprocess seam faked, and watch the second job actually start after the first
    reports done."""
    cli = _client(tmp_path)
    started = []

    class _FakeProc:
        def __init__(self):
            self.stdout = io.StringIO("")

        def wait(self):
            return 0

    def _popen(argv, **kw):
        # Only the Panel's own spawns: its argv always carries --workers. (create_app also
        # runs `git rev-parse` through Popen to read the build's own version.)
        if "--workers" in argv:
            started.append([a for a in argv if a.startswith("--")
                            and a not in ("--out", "--workers")])
        return _FakeProc()

    import subprocess as _sp
    with _mock.patch.object(_sp, "Popen", _popen):
        assert cli.post("/api/panel/run", json={"action": "sync"}).status_code == 200
        for _ in range(200):
            if len(started) >= 2:
                break
            time.sleep(0.02)
    assert started[0] == ["--sync"]
    assert started[1] == ["--backfill-phash"], \
        "Sync now must be followed by the perceptual-hash backfill, however it was started"


def test_the_backfill_chain_only_follows_a_sync_that_actually_succeeded():
    """"Backfill phash after each Sync". After -- and only after a clean finish: chaining
    onto a failed sync is just a second failure."""
    src = inspect.getsource(g.create_app)
    reader = src[src.index("def _panel_reader(proc, then=None):"):]
    reader = reader[:reader.index("def _panel_run(")]
    assert 'if then and status == "done":' in reader
    assert g.LIVING_BY_ACTION["sync"]["then"] == "backfill-phash"


# =====================================================================================
# 6. THE SETTINGS SURFACE
# =====================================================================================

def test_the_job_list_round_trips_through_the_schedule_endpoint(tmp_path):
    """One endpoint, one file: the list rides /api/panel/schedule beside the legacy
    standing order rather than inventing a second settings surface -- so the localhost-only
    write gate and the merge semantics are the ones already proven there."""
    cli = _client(tmp_path)
    d = cli.get("/api/panel/schedule").get_json()
    assert [r["action"] for r in d["jobs"]] == [j["action"] for j in g.LIVING_ALL]
    assert {c["action"] for c in d["catalog"]} == {j["action"] for j in g.LIVING_ALL}
    d = cli.post("/api/panel/schedule",
                 json={"jobs": [{"action": "artworks-sweep", "interval_s": 1800},
                                {"action": "sync", "enabled": False}]}).get_json()
    by = {r["action"]: r for r in d["jobs"]}
    assert by["artworks-sweep"]["interval_s"] == 1800
    assert by["sync"]["enabled"] is False
    assert by["sync-videos"]["enabled"] is True, "a patch must not wipe the other rows"
    # it persisted, and the legacy quartet is untouched
    again = cli.get("/api/panel/schedule").get_json()
    assert {r["action"]: r["interval_s"] for r in again["jobs"]}["artworks-sweep"] == 1800
    assert again["action"] == "sync" and again["enabled"] is False


def test_a_client_can_never_write_a_jobs_last_run(tmp_path):
    """A client that could write last_run could make a sixty-day staleness job -- a full
    re-walk, a Similar rebuild, every thumbnail -- fire on demand."""
    cli = _client(tmp_path)
    cli.post("/api/panel/schedule",
             json={"jobs": [{"action": "resync-full", "last_run": 0, "enabled": True}]})
    by = {r["action"]: r for r in cli.get("/api/panel/schedule").get_json()["jobs"]}
    assert by["resync-full"]["last_run"] is None
    assert by["resync-full"]["enabled"] is True     # the field it MAY set still landed


def test_the_schedule_endpoint_still_answers_the_legacy_shape(tmp_path):
    """A schema change, not a redesign: an older client (and the phone's read-only ledger)
    keeps getting exactly the fields it always got."""
    cli = _client(tmp_path)
    cli.post("/api/panel/schedule",
             json={"enabled": True, "action": "sync-videos", "interval_hours": 12})
    d = cli.get("/api/panel/schedule").get_json()
    assert d["enabled"] is True and d["action"] == "sync-videos"
    assert d["interval_hours"] == 12 and d["workers"] == 4


def test_run_now_for_the_sweep_is_localhost_only(tmp_path):
    """Same gate as /api/panel/schedule's writes, for the same reason: this starts real
    PixAI traffic on the owner's credentials."""
    cli = _client(tmp_path)
    lan = {"REMOTE_ADDR": "192.168.1.50"}
    assert cli.post("/api/panel/sweep", json={}, environ_overrides=lan).status_code == 403
    r = cli.post("/api/panel/sweep", json={})
    assert r.status_code == 200 and r.get_json()["action"] == "artworks-sweep"


# =====================================================================================
# 7. THE LIBRARY STANDS STILL
# =====================================================================================

def test_no_living_job_path_can_reach_the_librarys_own_loaders():
    """DECISIONS.md, 2026-09-05: "the library stands still -- nothing moves the owner's
    view except his own hands", which names living-library jobs as an inheritor BY NAME.

    Server side, the guard is that no job path calls the loaders that build the visible
    page. query_catalog is the grid's own query; load_catalog/save_catalog are the
    whole-catalog read and rewrite. The sweep does neither: it reads a two-column index and
    writes narrow UPDATEs, so there is no code path from a background job to the list the
    owner is looking at."""
    banned = ("query_catalog(", "load_catalog(", "save_catalog(", "catalog_counts(")
    for fn in (g.artworks_sweep, g.artworks_sweep_kick, g.apply_artwork_meta,
               g.published_index, g.living_due, g.living_merge,
               g.artworks_page_needed):
        src = inspect.getsource(fn)
        for name in banned:
            assert name not in src, "%s reaches for %s" % (fn.__name__, name)
    app_src = inspect.getsource(g.create_app)
    for start, end in (("def _living_tick():", "def _scheduler_loop():"),
                       ("def _artworks_kick(force=False):", "def _living_run(action):"),
                       ("def _living_run(action):", "# Read ONCE, here")):
        body = app_src[app_src.index(start):]
        body = body[:body.index(end)]
        for name in banned:
            assert name not in body, "%s..%s reaches for %s" % (start, end, name)


def test_the_panels_runs_itself_block_never_reloads_the_gallery():
    """The browser half of the same rule. A Run now, a toggle or a cadence change must not
    restack the grid under the owner: it starts work and the Activity tray reports it."""
    banned = ("load(", "userLoad(", "setItems(", "location.reload", "window.location")
    hook = (SRC / "gallery/src/hooks/useControlPanel.js").read_text(encoding="utf-8")
    living = hook[hook.index("const saveLivingJob"):]
    living = living[:living.index("const fetchAchievements")]
    for name in banned:
        assert name not in living, "the living-library hook reaches for %s" % name
    jsx = (SRC / "gallery/src/components/ControlPanelOverlay.jsx").read_text(encoding="utf-8")
    block = jsx[jsx.index("---- RUNS ITSELF: the living library"):]
    block = block[:block.index('<div className="mgcp-grid">')]
    for name in banned:
        assert name not in block, "the Runs-itself block reaches for %s" % name
    # and it is drawn with the vocabulary that already existed -- no new visual language
    assert "mgcp-standing" in block and "mgcp-run" in block and "mgcp-grp" in block


# =====================================================================================
# 8. THE FULL --sync-artworks WALK -- narrow now too, so nothing round-trips the table
# =====================================================================================

def _sync_fake():
    """The transport a full --sync-artworks run talks to here.

    Beyond the listing (monkeypatched per test), the run makes ONE other read: the ad-hoc
    bulk `artworks(authorId, first:N)` views sweep, which is keyed by the fake under
    `artworks`. It answers with an empty page -- these tests are about the WRITE SHAPE of
    the merge, not about views -- and registering it is what keeps the fake's refuse-by-name
    contract honest rather than letting an unregistered operation stand in for one."""
    return FakePixAI(user_id="u").on(
        "artworks", {"artworks": {"edges": [], "pageInfo": {"hasNextPage": False}}})


def test_the_full_sync_cannot_revert_a_write_that_lands_while_it_is_running(
        tmp_path, monkeypatch):
    """THE LOST-UPDATE RACE, closed at the root (adversarial review, 2026-09-06).

    run_sync_artworks used to persist by `load_catalog -> merge in memory -> save_catalog`:
    read the whole table, then upsert EVERY column of EVERY row from a snapshot taken after
    a walk that can run for minutes. Correct while this was the library's only writer, and a
    silent revert the moment it was not -- and this branch makes it not, by construction: the
    artworks sweep writes these same rows every fifteen minutes, on every publish and at
    boot, and the owner's ratings and collections land from the browser at any time.

    Writer A here is exactly that kind of writer -- one narrow UPDATE, the shape
    apply_artwork_meta, publish_state and the rating route all use -- and it fires from two
    places: mid-walk, and inside the read->save window the OLD shape had (through the
    load_catalog seam that shape used, which this one no longer calls at all). It touches
      * an owner-authored column on a row the sync really does merge (a rating), and
      * a row the sync NEVER SAW -- the collateral only a whole-table rewrite can cause.
    Both must survive. Under the old shape neither did."""
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="m1", filename="one.png", rating="1", created_at=_iso(10)),
        _row(media_id="untouched", filename="two.png", rating="4",
             collections="Favourites", liked_count="7", created_at=_iso(10)),
    ])
    writer = {"n": 0}

    def writer_a():
        """The living library's own writer, in miniature: narrow UPDATEs of rows it names.

        Each call writes a DIFFERENT value, so "the last write wins" is a real assertion
        rather than one two identical writes would satisfy by accident."""
        writer["n"] += 1
        n = writer["n"]
        with g.catalog(db) as con:
            con.execute("UPDATE catalog SET rating=? WHERE media_id='m1'", (str(n),))
            con.execute("UPDATE catalog SET liked_count=?, collections=?"
                        " WHERE media_id='untouched'", (str(90 + n), "Keepers%d" % n))
            con.commit()

    page = {"edges": [{"node": _node("m1", "aw1", likes=3)}],
            "pageInfo": {"hasPreviousPage": False}}

    def _list(*_a, **_k):
        writer_a()                       # a writer landing DURING the walk
        return page

    monkeypatch.setattr(core, "artwork_list_gql", _list)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: _sync_fake())
    # The old shape's window was everything between its whole-table read and its
    # whole-table save, so put a writer there too. Wrapping the REAL load and the REAL
    # save (never stubbing them) is what makes this test bite: if the round trip ever
    # comes back, it really runs, and it really reverts.
    real_load, real_save = core.load_catalog, core.save_catalog
    saved = []

    def _load_then_write(path, *a, **k):
        rows = real_load(path, *a, **k)
        writer_a()
        return rows

    def _record_save(path, rows, *a, **k):
        saved.append(len(rows))
        return real_save(path, rows, *a, **k)

    monkeypatch.setattr(core, "load_catalog", _load_then_write)
    monkeypatch.setattr(core, "save_catalog", _record_save)

    res = core.run_sync_artworks(SimpleNamespace(out=str(tmp_path), token=None, delay=0))

    last = writer["n"]
    assert last >= 1, "writer A never ran -- this test would pass vacuously"
    rows = {r["media_id"]: r for r in load_catalog(db)}
    assert rows["m1"]["rating"] == str(last), \
        "the walk reverted a rating written while it was running"
    assert rows["untouched"]["liked_count"] == str(90 + last), \
        "the walk rewrote a row it never even saw"
    assert rows["untouched"]["collections"] == "Keepers%d" % last
    # ...and it still did its own job: the eleven PixAI-owned columns landed
    assert res["matched"] == 1
    assert rows["m1"]["artwork_id"] == "aw1" and rows["m1"]["liked_count"] == "3"
    # THE ROUND TRIP ITSELF IS GONE -- no whole-table read, no whole-table save
    assert saved == [], "run_sync_artworks still upserts the whole catalog"
    src = inspect.getsource(core.run_sync_artworks)
    assert "save_catalog(" not in src and "load_catalog(" not in src
    assert "apply_artwork_meta(" in src


def test_the_full_sync_still_tags_an_animation_through_its_video_media_id(
        tmp_path, monkeypatch):
    """#20 survives the narrow rework: an animation's row is keyed by its MP4's media_id,
    not the poster `mediaId` the node carries, so the meta has to be re-keyed rather than
    merged onto whatever row happens to match. Kept here beside the rework because that
    re-keying is the one thing the old in-memory merge got for free."""
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="vid1", filename="v.mp4", is_video="1"),
                      _row(media_id="poster1", filename="p.png")])
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: _sync_fake())
    monkeypatch.setattr(core, "artwork_list_gql", lambda *a, **k: {
        "edges": [{"node": _node("poster1", "aw9", video_mid="vid1")}],
        "pageInfo": {"hasPreviousPage": False}})
    res = core.run_sync_artworks(SimpleNamespace(out=str(tmp_path), token=None, delay=0))
    rows = {r["media_id"]: r for r in load_catalog(db)}
    assert res["matched"] == 2
    assert rows["vid1"]["artwork_id"] == "aw9" and rows["vid1"]["is_video"] == "1"
    assert rows["poster1"]["artwork_id"] == "aw9"


def test_the_sweep_defers_to_a_catalog_writing_panel_job(tmp_path):
    """BELT AND BRACES around the one thing the sweep's own lock cannot see: a SUBPROCESS.

    _artworks_lock is a threading.Lock in the server process, and every Panel action runs as
    its own interpreter (_panel_run -> subprocess.Popen of the CLI) with its own SQLite
    connection. So a sweep and a `--sync` can write the same rows at the same moment and
    neither lock will ever notice -- SQLite serialises the two STATEMENTS, which is a much
    weaker promise than serialising the two JOBS. The sweep therefore reads the one piece of
    state that does cross the boundary: the Panel's single job slot."""
    cli = _client(tmp_path)
    slot = cli.application.extensions["mg_panel_job"]
    # a catalog-writing job in the slot: the sweep stands down, and says which job did it
    slot.update(status="running", action="sync", label="Sync now")
    d = cli.post("/api/panel/sweep", json={}).get_json()
    assert d["deferred"] == "sync" and d["ok"] is False
    # a job that writes no catalog rows is no reason to wait
    slot.update(status="running", action="audit", label="Duplicate audit")
    assert cli.post("/api/panel/sweep", json={}).get_json()["deferred"] == ""
    slot.update(status="idle", action="", label="")
    assert cli.post("/api/panel/sweep", json={}).get_json()["deferred"] == ""
    # the set is the writers, and nothing destructive is (or can become) one
    assert {"sync", "resync-full", "test-pull", "sync-videos",
            "sync-artworks"} == set(g.ARTWORKS_TOUCHING_ACTIONS)
    assert not (g.ARTWORKS_TOUCHING_ACTIONS
                & {"organize", "undo-organize", "dedup-apply", "dedup-delete",
                   "restore-orphans", "rebuild-thumbs"})
    # every trigger defers, the publish kick included -- the gate is in the shared kick
    src = inspect.getsource(g.create_app)
    kick = src[src.index("def _artworks_kick(force=False):"):]
    kick = kick[:kick.index("def _living_run(action):")]
    assert "if _artworks_job_busy():\n            return False" in kick
    tick = src[src.index("def _living_tick():"):]
    tick = tick[:tick.index("def _scheduler_loop():")]
    assert "if _artworks_job_busy():\n                        continue" in tick, \
        "a deferred tick must skip and retry, never stamp last_run and go quiet"


def test_a_catalog_writing_panel_job_refuses_to_start_while_a_sweep_is_in_flight(tmp_path):
    """THE OTHER DIRECTION, and the one that was missing. The sweep already stood down for
    a Panel job in the slot; nothing stopped a Panel job starting while the sweep was
    already mid-flight in this process -- and run_download's per-page save rebuilds each
    row from a snapshot taken when the job STARTED, so every column the sweep wrote after
    that snapshot was silently reverted.

    One shared piece of state answers both directions now: the sweep's own lock. Held ->
    a catalog-writing job refuses, by name, instead of spawning a subprocess into the
    rows the sweep is writing."""
    cli = _client(tmp_path)
    slot = cli.application.extensions["mg_panel_job"]
    assert g._artworks_lock.acquire(False), "the sweep's lock must be free at test start"
    try:
        assert g.artworks_sweep_in_flight() is True
        r = cli.post("/api/panel/run", json={"action": "sync"})
        assert r.status_code == 409
        assert "published-artwork sweep" in r.get_json()["error"]
        # and nothing was spawned: the slot is untouched
        assert slot["status"] != "running"
        # a job that writes none of the sweep's rows is no reason to refuse -- it is the
        # same ARTWORKS_TOUCHING_ACTIONS set the sweep's own deferral reads
        assert "audit" not in g.ARTWORKS_TOUCHING_ACTIONS
    finally:
        g._artworks_lock.release()
    assert g.artworks_sweep_in_flight() is False


def test_the_scheduled_paths_defer_the_same_way_the_manual_click_does(tmp_path):
    """The refusal lives in _panel_run itself -- the one choke point _living_tick, the
    legacy standing-order loop and the Run now click all reach the subprocess through --
    so a deferral is a property of the ACTION, not of which of the three started it. A
    False from _panel_run is already "the slot was taken, try again next tick" to both
    schedulers, so they retry rather than stamp last_run and go quiet."""
    create_app(tmp_path)
    src = inspect.getsource(g.create_app)
    run = src[src.index("def _panel_run(action"):]
    run = run[:run.index("def _update_busy():")]
    assert ("if action in ARTWORKS_TOUCHING_ACTIONS and artworks_sweep_in_flight():\n"
            "                return False") in run, \
        "the second direction must be claimed under the SAME lock that claims the slot"
    # the two schedulers both treat a False as "not started": no stamp, retry next tick
    tick = src[src.index("def _living_tick():"):src.index("def _scheduler_loop():")]
    assert "if _living_run(action):\n                    _living_stamp(action, now)" in tick
    loop = src[src.index("def _scheduler_loop():"):]
    assert "if not _panel_run(action" in loop and "continue                   # panel busy" in loop


def test_the_sweep_re_checks_the_panel_slot_after_taking_its_own_lock(tmp_path):
    """The mirror image, so the pair cannot both slip through at once. The sweep used to
    read the Panel's slot BEFORE it took its own lock, which left a window where a job
    could claim the slot in between. It now re-checks INSIDE the lock, which is the same
    instant _panel_run's own probe would find the lock held -- so whichever of the two
    gets there first, the other one stands down."""
    called = []
    res = g.artworks_sweep_kick(tmp_path, tmp_path / "catalog.db", force=True,
                                busy=lambda: "sync")
    assert res is None and called == []
    assert g.artworks_sweep_in_flight() is False, "the lock must be released on a stand-down"


def test_the_ticks_first_kick_does_not_repeat_the_boot_sweep():
    """The boot kick fires 25s after start; the first tick lands 35s after THAT with the
    sweep row's last_run still unset -- so it read as due, and a forced kick re-ran the
    whole first-boot deep walk twice inside a minute. Freshness, not force."""
    now = NOW
    g._artworks_state["at"] = now - 30.0             # the boot kick just finished
    assert g.artworks_sweep_fresh(g.ARTWORKS_SWEEP_S, now) is True
    assert g.artworks_sweep_fresh(g.ARTWORKS_SWEEP_S, now + 900) is False
    # a shorter cadence the owner set is honoured -- freshness reads the ROW's interval,
    # not the sweep's own fifteen-minute recent-guard
    g._artworks_state["at"] = now - 301.0
    assert g.artworks_sweep_fresh(300, now) is False
    # only a CLEAN finish stamps `at`, so a run of failing sweeps can never read as fresh
    g._artworks_state["at"] = 0.0
    assert g.artworks_sweep_fresh(g.ARTWORKS_SWEEP_S, now) is False
    tick = inspect.getsource(g.create_app)
    tick = tick[tick.index("def _living_tick():"):]
    tick = tick[:tick.index("def _scheduler_loop():")]
    # ...and it SKIPS rather than stamps: last_run must keep meaning "when this job last
    # ran", so a deferred tick retries in sixty seconds instead of buying a whole cadence
    # of silence. _living_stamp is only ever reached through a _living_run that returned.
    assert ('if artworks_sweep_fresh((row or {}).get("interval_s"), now):\n'
            "                        continue") in tick


def test_one_malformed_artwork_node_is_skipped_not_the_whole_sweep(tmp_path, monkeypatch):
    """extract_artwork_meta reads a dict PixAI sent, in a shape this app does not control
    and has already watched change (isSensitive and the nsfwPredict block both arrived
    unannounced). One node raising used to abort the walk through artworks_sweep_kick's
    catch-all -- throwing away every meta collected before it AND leaving the run unstamped,
    which means it did that again fifteen minutes later, forever."""
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="good1", filename="a.png", created_at=_iso(400)),
                      _row(media_id="good2", filename="b.png", created_at=_iso(400))])
    real = core.extract_artwork_meta

    def _extract(node):
        if node.get("mediaId") == "bad":
            raise TypeError("a shape this build has never seen")
        return real(node)

    monkeypatch.setattr(core, "extract_artwork_meta", _extract)
    _sweep_env(monkeypatch, [[_node("good1", "aG1"), _node("bad", "aBad"),
                              _node("good2", "aG2")]])
    res = g.artworks_sweep(tmp_path, db, force=True, now=NOW)
    assert res["changed"] == 2, "one bad node threw away everything the run had gathered"
    assert res["incomplete"] is False           # a skipped row is not a broken walk
    rows = {r["media_id"]: r for r in load_catalog(db)}
    assert rows["good1"]["artwork_id"] == "aG1" and rows["good2"]["artwork_id"] == "aG2"


def test_an_interrupted_thumbnail_never_lands_on_the_real_name(tmp_path, monkeypatch):
    """make_thumbnail saved straight onto the final path, so a kill, a crash or a full disk
    part-way through left a TRUNCATED .jpg at the real name -- and every "is it built yet?"
    check in this app is thumb_path.exists(), which reads that as done. Survivable while a
    thumbnail pass was a button someone watched; not survivable now that --rebuild-thumbs
    is on the sixty-day staleness backstop and starts by itself. Sixty days is how long a
    corrupt thumbnail would have sat there."""
    PILImage = pytest.importorskip("PIL.Image")
    src = tmp_path / "src.png"
    PILImage.new("RGB", (40, 30), "red").save(src)
    thumb = tmp_path / "thumbs" / "m1.jpg"
    assert g.make_thumbnail(src, thumb) is True
    good = thumb.read_bytes()

    real_save = PILImage.Image.save

    def _torn_save(self, fp, *a, **k):
        """A write that dies part-way: bytes on disk, then the failure."""
        real_save(self, fp, *a, **k)
        with open(fp, "r+b") as fh:
            fh.truncate(12)
        raise OSError("No space left on device")

    monkeypatch.setattr(PILImage.Image, "save", _torn_save)
    assert g.make_thumbnail(src, thumb) is False
    assert thumb.read_bytes() == good, \
        "an interrupted rebuild overwrote the live thumbnail with a torn file"
    # no debris, and nothing --rebuild-thumbs' orphan sweep (glob '*.jpg') could confuse
    assert [p.name for p in thumb.parent.iterdir()] == ["m1.jpg"]
    assert "_atomic_replace" in inspect.getsource(g.make_thumbnail)
    # ...and the docstring that promised "overwritten in place" is now true
    assert "os.replace" in (inspect.getdoc(core.run_rebuild_thumbs) or "")


def test_the_sixty_day_floor_is_enforced_by_the_server_not_by_a_missing_selector(tmp_path):
    """The Panel renders no cadence selector for a staleness job -- but that is a drawing
    decision, not an enforcement. schedule.json is a plain file the owner can open and
    /api/panel/schedule takes a jobs patch; either could ask for a full re-walk, every
    embedding and every thumbnail on a ONE-MINUTE timer, and before this the server wrote
    it down and the tick obeyed."""
    cli = _client(tmp_path)
    d = cli.post("/api/panel/schedule", json={"jobs": [
        {"action": "rebuild-thumbs", "interval_s": 60},
        {"action": "resync-full", "interval_s": 3600},
        {"action": "rebuild-similar", "interval_s": 0},
    ]}).get_json()
    by = {r["action"]: r for r in d["jobs"]}
    for action in ("rebuild-thumbs", "resync-full", "rebuild-similar"):
        assert by[action]["interval_s"] == g.STALE_BACKSTOP_S, \
            "%s took a cadence below the sixty-day floor" % action
    # answered clamped AND persisted clamped -- a re-read is the tick's own source
    again = {r["action"]: r for r in cli.get("/api/panel/schedule").get_json()["jobs"]}
    assert again["rebuild-thumbs"]["interval_s"] == g.STALE_BACKSTOP_S
    # the floor is a floor, not a pin: a LONGER interval is still the owner's to set
    d = cli.post("/api/panel/schedule",
                 json={"jobs": [{"action": "resync-full", "interval_s": 90 * DAY}]}).get_json()
    assert {r["action"]: r for r in d["jobs"]}["resync-full"]["interval_s"] == 90 * DAY
    # and a job that is NOT on the backstop keeps its own, much lower floor
    d = cli.post("/api/panel/schedule",
                 json={"jobs": [{"action": "artworks-sweep", "interval_s": 300}]}).get_json()
    assert {r["action"]: r for r in d["jobs"]}["artworks-sweep"]["interval_s"] == 300


def test_a_hand_edited_schedule_cannot_lower_the_floor_either(tmp_path):
    """The other way in. living_merge normalizes whatever is in the file on EVERY read, so
    the floor has to live there too -- a file that says sixty seconds must not become a
    sixty-second full re-walk just because nobody went through the route."""
    (tmp_path / "schedule.json").write_text(json.dumps({
        "enabled": False, "action": "sync", "interval_hours": 6, "workers": 4,
        "jobs": [{"action": "resync-full", "enabled": True, "interval_s": 60,
                  "last_run": 1000.0}]}), encoding="utf-8")
    cli = _client(tmp_path)
    by = {r["action"]: r for r in cli.get("/api/panel/schedule").get_json()["jobs"]}
    assert by["resync-full"]["interval_s"] == g.STALE_BACKSTOP_S
    # ...and the cadence function agrees: not due a minute later, due after sixty days
    jobs = g.living_merge([{"action": "resync-full", "enabled": True,
                            "interval_s": 60, "last_run": 1000.0}])
    due, _ = living_due_all(jobs, 1000.0 + 61)
    assert "resync-full" not in due
    due, _ = living_due_all(jobs, 1000.0 + g.STALE_BACKSTOP_S)
    assert "resync-full" in due


def test_an_advanced_action_cannot_be_saved_as_the_legacy_standing_order(tmp_path):
    """A job that BOTH schedulers refuse is a job that never runs again.

    The legacy scheduler's own tick has always skipped an `advanced` action (a full
    re-walk on a six-hour timer is a foot-gun), but the save route never checked -- so
    POST /api/panel/schedule {"action": "resync-full"} was accepted and written down.
    With that saved, _living_tick then deferred the 60-day staleness row to a standing
    order that refuses to run it, and the Panel told the owner "the standing order below
    runs this one" about a job neither path would ever start.

    The save-time check now mirrors the tick's own guard, so the two agree."""
    cli = _client(tmp_path)
    r = cli.post("/api/panel/schedule", json={"enabled": True, "action": "resync-full"})
    assert r.status_code == 400
    assert "advanced" in r.get_json()["error"] or "by hand" in r.get_json()["error"]
    # nothing was written: the standing order is still the default
    assert cli.get("/api/panel/schedule").get_json()["action"] != "resync-full"
    # and the staleness row is not deferred to a path that cannot run it
    cat = {c["action"]: c for c in cli.get("/api/panel/schedule").get_json()["catalog"]}
    assert cat["resync-full"]["deferred"] is False
    # every advanced action is refused, not just this one -- the same set the scheduler
    # tick has always skipped, asked through the Panel's own action table
    table = cli.get("/api/panel/summary").get_json()["all_actions"]
    advanced = [a["action"] for a in table if a["advanced"] and not a["destructive"]]
    assert "resync-full" in advanced and "test-pull" in advanced
    for action in advanced:
        assert cli.post("/api/panel/schedule",
                        json={"enabled": True, "action": action}).status_code == 400


def test_the_defer_check_confirms_the_standing_order_can_actually_run_the_job(tmp_path):
    """Belt and braces for a schedule.json written by an older build (or by hand), where
    the save-time check above never ran. _living_tick only steps aside for a standing
    order that CAN execute the named action -- an advanced one falls through to the
    living library's own path instead of vanishing from both."""
    (tmp_path / "schedule.json").write_text(json.dumps({
        "enabled": True, "action": "resync-full", "interval_hours": 6, "workers": 4,
    }), encoding="utf-8")
    cli = _client(tmp_path)
    cat = {c["action"]: c for c in cli.get("/api/panel/schedule").get_json()["catalog"]}
    assert cat["resync-full"]["deferred"] is False, \
        "a standing order that refuses the job must not be shown as running it"
    src = inspect.getsource(g.create_app)
    tick = src[src.index("def _living_tick():"):src.index("def _scheduler_loop():")]
    assert "_standing_action(s)" in tick, \
        "the tick must ask whether the standing order can run the job, not only its name"


def test_a_row_the_standing_order_owns_says_so_instead_of_a_cadence_it_is_not_running(
        tmp_path):
    """_living_tick has always skipped the action the legacy standing order names -- rightly,
    since two paths starting one job would just take turns losing the single Panel slot. But
    the row went on drawing its own cadence and its own "next in 3h", which is a schedule it
    is not running and the owner has no way to catch. The skip stays; the row now says why."""
    cli = _client(tmp_path)
    assert all(c["deferred"] is False
               for c in cli.get("/api/panel/schedule").get_json()["catalog"])
    cli.post("/api/panel/schedule",
             json={"enabled": True, "action": "sync", "interval_hours": 6})
    cat = {c["action"]: c for c in cli.get("/api/panel/schedule").get_json()["catalog"]}
    assert cat["sync"]["deferred"] is True
    assert cat["sync-videos"]["deferred"] is False
    # a DISABLED standing order owns nothing -- the flag is the tick's own condition
    cli.post("/api/panel/schedule", json={"enabled": False})
    cat = {c["action"]: c for c in cli.get("/api/panel/schedule").get_json()["catalog"]}
    assert cat["sync"]["deferred"] is False
    tick = inspect.getsource(g.create_app)
    tick = tick[tick.index("def _living_tick():"):]
    tick = tick[:tick.index("def _scheduler_loop():")]
    assert "standing = _standing_action(s)" in tick
    assert "if action == standing:" in tick, "the skip itself must not change"
    # the browser half: the row's own note line, in the vocabulary already there
    jsx = (SRC / "gallery/src/components/ControlPanelOverlay.jsx").read_text(encoding="utf-8")
    block = jsx[jsx.index("---- RUNS ITSELF: the living library"):]
    block = block[:block.index('<div className="mgcp-grid">')]
    assert "c.deferred" in block
    assert "the standing order below runs this one" in block
    assert "{c.deferred ? \"\" : fmtNextRun(row)}" in block, \
        "a deferred row must not show a next-run it is not going to keep"


def test_the_built_bundle_carries_the_runs_itself_surface():
    """The Panel the owner actually opens is gallery/dist/app.js. A source-only change here
    would be invisible on his screen -- which is the exact failure this repo rebuilds
    bundles in the same commit to avoid."""
    dist = (SRC / "gallery/dist/app.js").read_text(encoding="utf-8", errors="replace")
    assert "Runs itself" in dist
    assert "/api/panel/sweep" in dist
