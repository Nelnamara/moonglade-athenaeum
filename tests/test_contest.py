"""Contest plumbing: the three REST verbs, the always-confirm entry route, the publish-time
entry hook, the background detection sweep, and the two metrics they all feed.

Everything here asks one question in different accents -- did this path add the right KEY,
exactly once? -- because the design answers the ladder rule with a single dedupe SET per
metric rather than a counter per call site: +1 per successful entry, the same artwork in the
same contest never counted twice no matter which path saw it, a failed submit counted never.
A set IS that rule, so these tests measure the set.

Nothing here spends anything or enters a real contest. Every network verb is answered by the
transport fake (the `pixai` fixture) or monkeypatched on core; the one test that names
READ_ONLY proves the POST never fires at all.

Self-computing and sealed by construction: no achievement name, threshold, id or hidden flag
appears anywhere below. `contest_entries` / `contest_wins` are metric names -- shipped
convention, not roster content -- and the only thing asserted about them is arithmetic.
"""
import datetime as _dt

import pytest

import moonglade_backup as core
import moonglade_gallery as g
from moonglade_gallery import CATALOG_FIELDS, save_catalog

from tests.conftest import login_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _iso(days_ago):
    """A PixAI-shaped UTC timestamp `days_ago` days in the past (negative = the future)."""
    t = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days_ago)
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _contest(cid, slug, active=False, result_at="", end_at=""):
    """One row shaped like list_contests' own output -- only the fields the sweep reads."""
    return {"id": cid, "slug": slug, "active": active,
            "result_at": result_at, "end_at": end_at}


def _entry_keys(out_dir):
    """The raw dedupe set, straight from the store -- the thing the metric counts."""
    return g.load_telemetry(out_dir)["sets"].get("contest_entry_keys") or []


def _entries(out_dir):
    return g.telemetry_metrics(out_dir)["contest_entries"]


def _client(tmp_path, rows=()):
    save_catalog(tmp_path / "catalog.db", list(rows))
    return login_client(tmp_path)


def _csrf(cli):
    """The live session token, from the response that already rides it along to the
    publish-capable overlays."""
    return cli.get("/api/myart/items").get_json()["csrf"]


# ---- the core REST verbs ----------------------------------------------------

class TestContestRestVerbs:
    """The read verbs normalize and raise upward; the write verb is guarded and
    single-attempt."""

    def test_my_entries_accepts_either_payload_shape(self, pixai):
        """Only the sibling listing endpoint's envelope was ever seen live, so both the
        documented bare array and a /contest/list-style {data:[...]} envelope are handled --
        neither shape is a guess the caller has to live with. Nested echoes are dropped."""
        pixai.on("/contest/s1/artwork/u-test",
                 [{"id": "e1", "authorId": "u-test", "mediaId": "m1", "title": "T",
                   "contest": {"id": "c1", "slug": "s1"}}])
        assert core.contest_my_entries(pixai, "s1", "u-test") == [
            {"id": "e1", "authorId": "u-test", "mediaId": "m1", "title": "T"}]
        pixai.on("/contest/s2/artwork/u-test", {"data": [{"id": "e2"}], "totalPage": 1})
        assert core.contest_my_entries(pixai, "s2", "u-test") == [{"id": "e2"}]
        assert core.contest_my_entries(pixai, "s2", "u-test") is not None

    def test_winners_is_empty_while_running_and_keeps_the_rank_field(self, pixai):
        """A running contest answers with an empty array rather than an error -- "not
        decided yet", not "call failed". Whatever upstream calls the rank field rides
        along untouched, since its name was never verified."""
        pixai.on("/contest/s1/winners", [])
        assert core.contest_winners(pixai, "s1") == []
        pixai.on("/contest/s2/winners", [{"id": "a1", "authorId": "u-9", "rank": 2}])
        assert core.contest_winners(pixai, "s2") == [
            {"id": "a1", "authorId": "u-9", "rank": 2}]

    def test_read_verbs_raise_upward(self, pixai):
        """Failure handling belongs to the caller (each one is a poll with its own idea of
        what to do about it), so these do not swallow."""
        pixai.fail("/contest/s1/winners", core.PixAIError("REST GET /contest -> 500"))
        pixai.fail("/contest/s1/artwork/u-test", core.PixAIError("REST GET /contest -> 500"))
        with pytest.raises(core.PixAIError):
            core.contest_winners(pixai, "s1")
        with pytest.raises(core.PixAIError):
            core.contest_my_entries(pixai, "s1", "u-test")


class TestContestEnterIsGuarded:
    """Entering is account-mutating: it puts the artwork in front of everyone and PixAI
    offers no way back. So it obeys the same contract as every other mutation here -- the
    READ_ONLY guard fires BEFORE the network call, and the call happens exactly once."""

    def test_guard_runs_before_the_post(self, mock_session, monkeypatch):
        order = []
        monkeypatch.setattr(core, "_check_read_only", lambda action: order.append("guard"))
        monkeypatch.setattr(core, "_rest_post",
                            lambda s, p, b, **k: order.append(("post", p, b)) or {"success": True})
        assert core.contest_enter(mock_session, "slug1", 42) == {"success": True}
        assert order[0] == "guard", "the guard must run first, not merely somewhere"
        assert order[1] == ("post", "/contest/slug1/artwork", {"artworkId": "42"})
        assert len(order) == 2, "one POST, no retry loop -- a re-POST would enter twice"

    def test_read_only_refuses_before_any_network(self, mock_session, monkeypatch):
        monkeypatch.setattr(core, "READ_ONLY", True)
        with pytest.raises(core.PixAIError, match="READ_ONLY"):
            core.contest_enter(mock_session, "slug1", "art1")
        mock_session.post.assert_not_called()


# ---- POST /api/contest/enter ------------------------------------------------

def test_enter_route_requires_csrf(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(core, "contest_enter",
                        lambda *a, **k: calls.append(a) or {"success": True})
    cli = _client(tmp_path)
    r = cli.post("/api/contest/enter", json={"slug": "s1", "contest_id": "c1",
                                             "artwork_id": "a1", "confirm": True})
    assert r.status_code == 400
    assert not calls and not _entry_keys(tmp_path)


def test_enter_route_previews_without_touching_the_network(tmp_path, monkeypatch):
    """Always-confirm: without `confirm` the route does NO network at all. `spends_credits`
    is None -- the entry fee is unmeasured, and False on a screen read before an
    irreversible action would be a promise the code cannot keep."""
    calls = []
    monkeypatch.setattr(core, "contest_enter",
                        lambda *a, **k: calls.append(a) or {"success": True})
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    cli = _client(tmp_path)
    d = cli.post("/api/contest/enter", json={"slug": "s1", "contest_id": "c1",
                                             "artwork_id": "a1",
                                             "csrf": _csrf(cli)}).get_json()
    assert d["preview"] is True and d["irreversible"] is True
    assert "spends_credits" in d and d["spends_credits"] is None
    assert not calls, "a preview must not enter anything"
    assert not _entry_keys(tmp_path)
    # a missing target is refused at the door, confirmed or not
    assert cli.post("/api/contest/enter",
                    json={"slug": "s1", "contest_id": "c1", "confirm": True,
                          "csrf": _csrf(cli)}).status_code == 400
    assert not calls


def test_enter_route_confirm_enters_once_then_dedupes(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(core, "contest_enter",
                        lambda s, slug, aid: calls.append((slug, aid)) or {"success": True})
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    cli = _client(tmp_path)
    body = {"slug": "s1", "contest_id": "c1", "artwork_id": "a1", "confirm": True}
    d = cli.post("/api/contest/enter", json=dict(body, csrf=_csrf(cli))).get_json()
    assert d["entered"] is True and d["artwork_id"] == "a1"
    assert calls == [("s1", "a1")]
    assert _entries(tmp_path) == 1
    # the same artwork into the same contest again: PixAI stays the authority on whether a
    # repeat submit is allowed (the call fires), but the ladder does not move.
    cli.post("/api/contest/enter", json=dict(body, csrf=_csrf(cli)))
    assert len(calls) == 2
    assert _entries(tmp_path) == 1


def test_enter_route_core_failure_is_502_and_records_nothing(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise core.PixAIError("NOT_ELIGIBLE")
    monkeypatch.setattr(core, "contest_enter", _boom)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    cli = _client(tmp_path)
    r = cli.post("/api/contest/enter",
                 json={"slug": "s1", "contest_id": "c1", "artwork_id": "a1",
                       "confirm": True, "csrf": _csrf(cli)})
    assert r.status_code == 502 and r.get_json()["error"]
    assert not _entry_keys(tmp_path) and _entries(tmp_path) == 0


# ---- the publish-time hook --------------------------------------------------

def _publish_client(tmp_path, monkeypatch, artwork_id="newart1", fail=False):
    """A logged-in client over one unpublished row, with the publish mutation stubbed."""
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "resolve_tack_ids", lambda s, tags: ([], []))
    monkeypatch.setattr(core, "task_media_index", lambda s, t, m: 0)

    def _publish(session, task_id, **kw):
        if fail:
            raise core.PixAIError("upstream refused the publish")
        return {"id": artwork_id}
    monkeypatch.setattr(core, "publish_artwork_from_task", _publish)
    return _client(tmp_path, [_row(media_id="m1", task_id="t1", filename="x_m1.png",
                                   created_at="2026-07-01T00:00:00")])


def _publish(cli, **extra):
    return cli.post("/api/myart/publish",
                    json=dict({"action": "publish", "media_id": "m1", "confirm": True,
                               "csrf": _csrf(cli)}, **extra))


def test_publish_with_a_challenge_records_the_entry(tmp_path, monkeypatch):
    """Publishing WITH a contest attached is the entry path that already shipped, so the
    hook lives server-side where every client funnels through. The key pairs the contest
    with the artwork id the mutation actually returned."""
    cli = _publish_client(tmp_path, monkeypatch)
    d = _publish(cli, challenge="c7").get_json()
    assert d["published"] is True
    assert _entry_keys(tmp_path) == ["c7:newart1"]
    assert _entries(tmp_path) == 1


def test_publish_without_a_challenge_records_nothing(tmp_path, monkeypatch):
    cli = _publish_client(tmp_path, monkeypatch)
    assert _publish(cli).get_json()["published"] is True
    assert _entries(tmp_path) == 0


def test_failed_publish_records_nothing(tmp_path, monkeypatch):
    """A publish that raised entered no contest -- and the hook sits outside that try, so
    it is never reached AND could never turn a real publish into a 502 either."""
    cli = _publish_client(tmp_path, monkeypatch, fail=True)
    assert _publish(cli, challenge="c7").status_code == 502
    assert _entries(tmp_path) == 0


# ---- the detection sweep ----------------------------------------------------

def _no_pause(monkeypatch):
    """Drop the politeness pause for the tests. The pacing itself is a constant, asserted
    once below rather than waited on in every sweep test."""
    monkeypatch.setattr(g, "_CONTEST_SYNC_PAUSE", 0)


def test_sweep_is_paced():
    assert g._CONTEST_SYNC_PAUSE > 0        # paced: be polite to their servers
    assert g._CONTEST_SYNC_MAX > 0          # and bounded


def test_sweep_records_entries_and_only_decided_wins(tmp_path, monkeypatch, pixai):
    """Entries land for every kept contest; winners are polled ONLY once a contest's result
    date has passed (before that the endpoint answers an empty array -- asking early is a
    request that cannot inform anything), and a win is the owner's own authorId."""
    seen = []
    _no_pause(monkeypatch)
    monkeypatch.setattr(core, "list_contests", lambda s, **k: [
        _contest("c1", "s1", active=True),
        _contest("c2", "s2", result_at=_iso(1)),
    ])
    monkeypatch.setattr(core, "contest_my_entries",
                        lambda s, slug, uid: seen.append(("entries", slug, uid))
                        or [{"id": "e-" + slug}])
    monkeypatch.setattr(core, "contest_winners",
                        lambda s, slug: seen.append(("winners", slug))
                        or [{"authorId": pixai.user_id, "rank": 1}])
    g._contest_detection_sync(tmp_path)
    m = g.telemetry_metrics(tmp_path)
    assert m["contest_entries"] == 2
    assert m["contest_wins"] == 1
    assert [c for c in seen if c[0] == "winners"] == [("winners", "s2")]
    assert all(c[2] == pixai.user_id for c in seen if c[0] == "entries")
    # re-sweeping is free: the same rows produce the same keys, which the set already holds
    g._contest_detection_sync(tmp_path)
    m2 = g.telemetry_metrics(tmp_path)
    assert (m2["contest_entries"], m2["contest_wins"]) == (2, 1)


def test_sweep_ignores_someone_elses_win(tmp_path, monkeypatch, pixai):
    _no_pause(monkeypatch)
    monkeypatch.setattr(core, "list_contests",
                        lambda s, **k: [_contest("c2", "s2", result_at=_iso(1))])
    monkeypatch.setattr(core, "contest_my_entries", lambda s, slug, uid: [])
    monkeypatch.setattr(core, "contest_winners",
                        lambda s, slug: [{"authorId": "somebody-else"}])
    g._contest_detection_sync(tmp_path)
    m = g.telemetry_metrics(tmp_path)
    assert m["contest_wins"] == 0 and m["contest_entries"] == 0


def test_sweep_skips_contests_outside_the_window(tmp_path, monkeypatch, pixai):
    """Long-finished contests and undated ones are not polled: their result cannot change,
    and falling back to "poll everything" would be a request storm for nothing."""
    seen = []
    _no_pause(monkeypatch)
    monkeypatch.setattr(core, "list_contests", lambda s, **k: [
        _contest("c1", "s1", result_at=_iso(g._CONTEST_SYNC_RECENT_DAYS + 10)),
        _contest("c2", "s2"),                                   # ended, no dates at all
        _contest("c3", "s3", end_at="not-a-date"),
        _contest("c4", "s4", end_at=_iso(1)),                   # ended, but recently
    ])
    monkeypatch.setattr(core, "contest_my_entries",
                        lambda s, slug, uid: seen.append(slug) or [{"id": "e-" + slug}])
    monkeypatch.setattr(core, "contest_winners", lambda s, slug: [])
    g._contest_detection_sync(tmp_path)
    assert seen == ["s4"]
    assert g.telemetry_metrics(tmp_path)["contest_entries"] == 1


def test_sweep_survives_one_bad_contest(tmp_path, monkeypatch, pixai):
    _no_pause(monkeypatch)
    monkeypatch.setattr(core, "list_contests", lambda s, **k: [
        _contest("c1", "s1", active=True), _contest("c2", "s2", active=True),
        _contest("c3", "s3", active=True)])

    def _my_entries(s, slug, uid):
        if slug == "s2":
            raise core.PixAIError("REST GET /contest -> 500")
        return [{"id": "e-" + slug}]
    monkeypatch.setattr(core, "contest_my_entries", _my_entries)
    monkeypatch.setattr(core, "contest_winners", lambda s, slug: [])
    g._contest_detection_sync(tmp_path)
    assert g.telemetry_metrics(tmp_path)["contest_entries"] == 2   # the sweep carried on


def test_sweep_never_raises(tmp_path, monkeypatch, pixai):
    """A background poll that can raise is a poll that can break the thing it observes."""
    _no_pause(monkeypatch)

    def _boom(*a, **k):
        raise core.PixAIError("the board is unreachable")
    monkeypatch.setattr(core, "list_contests", _boom)
    g._contest_detection_sync(tmp_path)                # no exception escapes
    assert g.telemetry_metrics(tmp_path)["contest_entries"] == 0


def test_sweep_without_an_account_id_does_nothing(tmp_path, monkeypatch, pixai):
    seen = []
    _no_pause(monkeypatch)
    pixai.user_id = ""
    monkeypatch.setattr(core, "list_contests",
                        lambda s, **k: seen.append("board") or [])
    g._contest_detection_sync(tmp_path)
    assert not seen                                    # nothing to look up, so nothing asked


# ---- POST /api/contest/sync -------------------------------------------------

def test_sync_route_reports_counts_only(tmp_path, monkeypatch, pixai):
    """Ints, never contents: which contest and which artwork stay in the store."""
    _no_pause(monkeypatch)
    monkeypatch.setattr(core, "list_contests",
                        lambda s, **k: [_contest("c1", "s1", active=True)])
    monkeypatch.setattr(core, "contest_my_entries",
                        lambda s, slug, uid: [{"id": "e1"}, {"id": "e2"}])
    monkeypatch.setattr(core, "contest_winners", lambda s, slug: [])
    cli = _client(tmp_path)
    d = cli.post("/api/contest/sync").get_json()
    assert d == {"synced": True, "contest_entries": 2, "contest_wins": 0}


def test_sync_route_refuses_a_concurrent_sweep(tmp_path):
    """Single-flight, the same busy shape the other long jobs use."""
    cli = _client(tmp_path)
    assert g._contest_sync_lock.acquire(False)
    try:
        r = cli.post("/api/contest/sync")
        assert r.status_code == 409 and r.get_json()["error"]
    finally:
        g._contest_sync_lock.release()


# ---- the metrics ------------------------------------------------------------

def test_metrics_are_the_set_cardinalities(tmp_path):
    assert g.telemetry_metrics(tmp_path)["contest_entries"] == 0
    for key in ("c1:a1", "c1:a1", "c1:a2", "c2:a1"):      # one repeat, deduped
        g.telem_set_add("contest_entry_keys", key, out_dir=tmp_path)
    for key in ("c1", "c1", "c2"):
        g.telem_set_add("contest_win_keys", key, out_dir=tmp_path)
    m = g.telemetry_metrics(tmp_path)
    assert (m["contest_entries"], m["contest_wins"]) == (3, 2)
    assert isinstance(m["contest_entries"], int) and isinstance(m["contest_wins"], int)
