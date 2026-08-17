"""GET /api/next/history -- the Generate dock's History feed.

Catalog rows bucketed into LOCAL calendar days (empty days included), newest first,
with the live job log (jobs.jsonl) merged on top and deduped by task_id, plus a
`before=` paging cursor that skips runs of empty days. Pure local read: one indexed
created_at range query + core.read_jobs(); never /api/jobs's reconcile/compact path.

Fixed frame used below unless a test says otherwise: tz=-420 (UTC-7) and
before=2026-08-18, so the 7-day window is local 08-11..08-17, i.e. UTC
[2026-08-11T07:00Z, 2026-08-18T07:00Z).
"""
import calendar
import time
from urllib.parse import urlencode

import moonglade_backup as core
from moonglade_gallery import CATALOG_FIELDS, save_catalog

from tests.conftest import login_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _seed(tmp_path, rows):
    save_catalog(tmp_path / "catalog.db", rows)


def _get(cli, **params):
    r = cli.get("/api/next/history?" + urlencode(params))
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _flat(d):
    """Every row of every day, in feed order (newest day first, newest row first)."""
    return [row for day in d["days"] for row in day["rows"]]


def _by_date(d):
    return {day["date"]: day["rows"] for day in d["days"]}


FRAME = dict(tz=-420, before="2026-08-18")


# ---------------------------------------------------------------- day buckets

def test_exactly_days_buckets_newest_first(tmp_path):
    _seed(tmp_path, [_row(media_id="m1", filename="a.png", created_at="2026-08-17T10:00:00.000Z")])
    d = _get(login_client(tmp_path), days=3, **FRAME)
    assert [x["date"] for x in d["days"]] == ["2026-08-17", "2026-08-16", "2026-08-15"]
    assert d["tz"] == -420
    assert all(x["label_hint"] is None for x in d["days"])


def test_days_param_defaults_to_seven_and_clamps(tmp_path):
    _seed(tmp_path, [])
    cli = login_client(tmp_path)
    assert len(_get(cli, **FRAME)["days"]) == 7
    assert len(_get(cli, days=0, **FRAME)["days"]) == 1
    assert len(_get(cli, days=99, **FRAME)["days"]) == 31
    assert len(_get(cli, days="junk", **FRAME)["days"]) == 7


def test_rows_newest_first_inside_a_day(tmp_path):
    _seed(tmp_path, [
        _row(media_id="early", filename="a.png", created_at="2026-08-17T10:00:00.000Z"),
        _row(media_id="late", filename="b.png", created_at="2026-08-17T12:00:00.000Z"),
    ])
    d = _get(login_client(tmp_path), **FRAME)
    assert [r["media_id"] for r in _by_date(d)["2026-08-17"]] == ["late", "early"]


def test_empty_day_is_present_as_empty_list(tmp_path):
    _seed(tmp_path, [
        _row(media_id="a", filename="a.png", created_at="2026-08-17T10:00:00.000Z"),
        _row(media_id="b", filename="b.png", created_at="2026-08-15T10:00:00.000Z"),
    ])
    by = _by_date(_get(login_client(tmp_path), **FRAME))
    assert by["2026-08-16"] == []
    assert [r["media_id"] for r in by["2026-08-17"]] == ["a"]
    assert [r["media_id"] for r in by["2026-08-15"]] == ["b"]


def test_local_day_boundary_for_a_negative_tz(tmp_path):
    """06:30Z on the 17th is 23:30 on the 16th at UTC-7; 07:30Z is 00:30 on the 17th."""
    _seed(tmp_path, [
        _row(media_id="night", filename="a.png", created_at="2026-08-17T06:30:00.000Z"),
        _row(media_id="dawn", filename="b.png", created_at="2026-08-17T07:30:00.000Z"),
    ])
    by = _by_date(_get(login_client(tmp_path), **FRAME))
    assert [r["media_id"] for r in by["2026-08-16"]] == ["night"]
    assert [r["media_id"] for r in by["2026-08-17"]] == ["dawn"]


def test_window_edges_are_exclusive_end_inclusive_start(tmp_path):
    """The window is UTC [08-11T07:00Z, 08-18T07:00Z): a row AT the start belongs to the
    oldest day; a row at the end (local midnight of `before`) is out; a 19-char naive
    legacy row is read as UTC."""
    _seed(tmp_path, [
        _row(media_id="at_start", filename="a.png", created_at="2026-08-11T07:00:00.000Z"),
        _row(media_id="just_before", filename="b.png", created_at="2026-08-11T06:59:59.000Z"),
        _row(media_id="at_end", filename="c.png", created_at="2026-08-18T07:00:00.000Z"),
        _row(media_id="naive", filename="d.png", created_at="2026-08-12T20:00:00"),
    ])
    d = _get(login_client(tmp_path), **FRAME)
    by = _by_date(d)
    assert [r["media_id"] for r in by["2026-08-11"]] == ["at_start"]
    assert [r["media_id"] for r in by["2026-08-12"]] == ["naive"]
    ids = {r["media_id"] for r in _flat(d)}
    assert "at_end" not in ids and "just_before" not in ids


def test_without_before_today_is_the_first_bucket(tmp_path):
    now = time.time()
    _seed(tmp_path, [_row(media_id="now", filename="a.png",
                          created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)))])
    d = _get(login_client(tmp_path), tz=0)
    assert d["days"][0]["date"] == time.strftime("%Y-%m-%d", time.gmtime(now))
    assert [r["media_id"] for r in d["days"][0]["rows"]] == ["now"]
    assert d["tz"] == 0


def test_bad_before_is_a_400(tmp_path):
    _seed(tmp_path, [])
    r = login_client(tmp_path).get("/api/next/history?before=yesterday")
    assert r.status_code == 400 and "error" in r.get_json()


# ---------------------------------------------------------------- paging

def test_next_before_skips_empty_days_to_the_newest_older_row(tmp_path):
    _seed(tmp_path, [
        _row(media_id="in", filename="a.png", created_at="2026-08-17T10:00:00.000Z"),
        # nothing 08-06..08-10; the newest OLDER row is local 08-05 -> cursor 08-06
        _row(media_id="old", filename="b.png", created_at="2026-08-05T20:00:00.000Z"),
    ])
    d = _get(login_client(tmp_path), **FRAME)
    assert d["has_more"] is True
    assert d["next_before"] == "2026-08-06"


def test_no_older_rows_means_no_more(tmp_path):
    _seed(tmp_path, [_row(media_id="in", filename="a.png", created_at="2026-08-17T10:00:00.000Z")])
    d = _get(login_client(tmp_path), **FRAME)
    assert d["has_more"] is False and d["next_before"] is None and d["older_days"] == 0


def test_older_days_counts_only_days_with_rows_in_the_next_window(tmp_path):
    """Cursor 08-06 -> next window is local [07-30, 08-06): rows on 08-05 and 08-03
    (twice) = 2 days; 07-29 is outside that window and does not count."""
    _seed(tmp_path, [
        _row(media_id="in", filename="a.png", created_at="2026-08-17T10:00:00.000Z"),
        _row(media_id="o1", filename="b.png", created_at="2026-08-05T20:00:00.000Z"),
        _row(media_id="o2", filename="c.png", created_at="2026-08-03T20:00:00.000Z"),
        _row(media_id="o3", filename="d.png", created_at="2026-08-03T21:00:00.000Z"),
        _row(media_id="o4", filename="e.png", created_at="2026-07-29T20:00:00.000Z"),
    ])
    d = _get(login_client(tmp_path), **FRAME)
    assert d["next_before"] == "2026-08-06"
    assert d["older_days"] == 2


def test_before_paging_returns_strictly_older_days(tmp_path):
    _seed(tmp_path, [
        _row(media_id="in", filename="a.png", created_at="2026-08-17T10:00:00.000Z"),
        _row(media_id="o1", filename="b.png", created_at="2026-08-05T20:00:00.000Z"),
        _row(media_id="o2", filename="c.png", created_at="2026-08-03T20:00:00.000Z"),
    ])
    cli = login_client(tmp_path)
    first = _get(cli, **FRAME)
    second = _get(cli, tz=-420, before=first["next_before"])
    dates = [x["date"] for x in second["days"]]
    assert dates == ["2026-08-05", "2026-08-04", "2026-08-03", "2026-08-02",
                     "2026-08-01", "2026-07-31", "2026-07-30"]
    assert all(dt < "2026-08-06" for dt in dates)
    assert [r["media_id"] for r in _flat(second)] == ["o1", "o2"]
    assert "in" not in {r["media_id"] for r in _flat(second)}
    assert second["has_more"] is False


# ---------------------------------------------------------------- live jobs merge

def _now_row(**kw):
    return _row(created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **kw)


def test_running_job_becomes_one_synthetic_row_with_count(tmp_path):
    _seed(tmp_path, [])
    core.append_job_event(tmp_path, "9001", status="running", type="generate",
                          label="Generated", count=2)
    d = _get(login_client(tmp_path), tz=0)
    rows = _flat(d)
    assert len(rows) == 1
    j = rows[0]
    assert j["state"] == "running" and j["count"] == 2
    assert j["job_id"] == "9001" and j["task_id"] == "9001"
    assert j["media_id"] is None and j["kind"] == "image" and j["label"] == "Generated"
    assert j["thumb"] is None and j["prompt"] is None and j["paid_credit"] is None
    assert d["days"][0]["rows"] == rows           # in today's bucket


def test_failed_and_stale_jobs_are_synthetic_rows_too(tmp_path):
    _seed(tmp_path, [])
    core.append_job_event(tmp_path, "9003", status="failed", type="generate", error="boom")
    core.append_job_event(tmp_path, "9004", status="stale", type="generate", is_video=True)
    by_id = {r["job_id"]: r for r in _flat(_get(login_client(tmp_path), tz=0))}
    assert by_id["9003"]["state"] == "failed" and by_id["9003"]["error"] == "boom"
    assert by_id["9004"]["state"] == "stale" and by_id["9004"]["kind"] == "video"


def test_done_job_is_not_duplicated(tmp_path):
    _seed(tmp_path, [_now_row(media_id="mid42", filename="a.png", task_id="t7")])
    core.append_job_event(tmp_path, "t7", status="running", type="generate", label="Nightsong")
    core.append_job_event(tmp_path, "t7", status="done", media_ids=["mid42"])
    rows = _flat(_get(login_client(tmp_path), tz=0))
    assert [(r["task_id"], r["state"]) for r in rows] == [("t7", "done")]
    assert rows[0]["media_id"] == "mid42"


def test_running_job_whose_task_already_has_rows_is_dropped(tmp_path):
    _seed(tmp_path, [_now_row(media_id="m1", filename="a.png", task_id="9002")])
    core.append_job_event(tmp_path, "9002", status="running", type="generate", count=4)
    rows = _flat(_get(login_client(tmp_path), tz=0))
    assert len(rows) == 1 and rows[0]["state"] == "done" and rows[0]["media_id"] == "m1"


def test_non_generate_jobs_are_ignored(tmp_path):
    _seed(tmp_path, [])
    core.append_job_event(tmp_path, "panel-abc", status="running", type="panel", label="Sync")
    core.append_job_event(tmp_path, "cli-abc", status="running", type="cli", label="Update")
    core.append_job_event(tmp_path, "untyped", status="running", label="???")
    assert _flat(_get(login_client(tmp_path), tz=0)) == []


def test_running_job_sorts_by_time_among_catalog_rows(tmp_path):
    """A job that started AFTER the newest catalog row leads the day (newest first)."""
    old = time.time() - 3600
    _seed(tmp_path, [_row(media_id="m1", filename="a.png", task_id="t1",
                          created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(old)))])
    core.append_job_event(tmp_path, "9005", status="running", type="generate")
    ids = [r.get("media_id") or r.get("job_id") for r in _flat(_get(login_client(tmp_path), tz=0))]
    # the catalog row may fall on yesterday's bucket right after midnight UTC; either
    # way the running job is first in feed order
    assert ids[0] == "9005" and "m1" in ids


# ---------------------------------------------------------------- filters

def test_source_api_filter(tmp_path):
    _seed(tmp_path, [
        _row(media_id="h1", filename="a.png", created_at="2026-08-17T10:00:00.000Z"),
        _row(media_id="h2", filename="b.png", created_at="2026-08-17T10:01:00.000Z", source="online"),
        _row(media_id="g1", filename="c.png", created_at="2026-08-17T10:02:00.000Z", source="api"),
        _row(media_id="l1", filename="d.png", created_at="2026-08-17T10:03:00.000Z", source="local"),
    ])
    cli = login_client(tmp_path)
    assert [r["media_id"] for r in _flat(_get(cli, source="api", **FRAME))] == ["g1"]
    assert {r["media_id"] for r in _flat(_get(cli, source="online", **FRAME))} == {"h1", "h2"}
    assert [r["media_id"] for r in _flat(_get(cli, source="local", **FRAME))] == ["l1"]
    assert len(_flat(_get(cli, **FRAME))) == 4
    assert _flat(_get(cli, source="api", **FRAME))[0]["source"] == "api"


def test_media_video_filter_and_video_row_shape(tmp_path):
    _seed(tmp_path, [
        _row(media_id="img", filename="a.png", created_at="2026-08-17T10:00:00.000Z"),
        _row(media_id="vid", filename="v.mp4", created_at="2026-08-17T10:01:00.000Z",
             is_video="1", video_duration="10", width="1280", height="720"),
    ])
    cli = login_client(tmp_path)
    rows = _flat(_get(cli, media="video", **FRAME))
    assert [r["media_id"] for r in rows] == ["vid"]
    v = rows[0]
    assert v["kind"] == "video" and v["media_url"] == "/video-file/vid"
    assert v["thumb"] == "/thumbs/vid.jpg" and v["duration"] == 10.0
    assert v["w"] == 1280 and v["h"] == 720
    assert [r["media_id"] for r in _flat(_get(cli, media="image", **FRAME))] == ["img"]


def test_rows_without_a_filename_are_never_listed(tmp_path):
    _seed(tmp_path, [
        _row(media_id="ok", filename="a.png", created_at="2026-08-17T10:00:00.000Z"),
        _row(media_id="nofile", filename="", created_at="2026-08-17T10:01:00.000Z"),
    ])
    assert [r["media_id"] for r in _flat(_get(login_client(tmp_path), **FRAME))] == ["ok"]


# ---------------------------------------------------------------- row fields

def test_image_row_shape(tmp_path):
    _seed(tmp_path, [_row(media_id="m1", filename="a.png", task_id="t1", source="api",
                          created_at="2026-08-17T10:00:00.545Z", width="832", height="1216",
                          model_id="ver1", model_name="Tsubaki", prompt_full="a moon elf")])
    r = _flat(_get(login_client(tmp_path), **FRAME))[0]
    assert r["media_id"] == "m1" and r["task_id"] == "t1" and r["kind"] == "image"
    assert r["state"] == "done" and r["created_at"] == "2026-08-17T10:00:00.545Z"
    assert abs(r["ts"] - (calendar.timegm((2026, 8, 17, 10, 0, 0)) + 0.545)) < 1e-3
    assert r["w"] == 832 and r["h"] == 1216
    assert r["thumb"] == "/thumbs/m1.jpg" and r["media_url"] == "/full/m1"
    assert r["model"] == "Tsubaki" and r["model_id"] == "ver1"
    assert r["prompt"] == "a moon elf" and r["duration"] is None
    assert r["paid_credit"] is None and r["source"] == "api" and r["count_in_task"] == 1


def test_blank_dims_are_null(tmp_path):
    _seed(tmp_path, [_row(media_id="m1", filename="a.png", created_at="2026-08-17T10:00:00.000Z")])
    r = _flat(_get(login_client(tmp_path), **FRAME))[0]
    assert r["w"] is None and r["h"] is None


def test_prompt_is_capped_at_300_and_falls_back_to_preview(tmp_path):
    _seed(tmp_path, [
        _row(media_id="long", filename="a.png", created_at="2026-08-17T10:00:00.000Z",
             prompt_full="x" * 500, prompt_preview="x" * 100),
        _row(media_id="prev", filename="b.png", created_at="2026-08-17T10:01:00.000Z",
             prompt_full="", prompt_preview="only the preview"),
    ])
    by = {r["media_id"]: r["prompt"] for r in _flat(_get(login_client(tmp_path), **FRAME))}
    assert len(by["long"]) == 300
    assert by["prev"] == "only the preview"


def test_paid_credit_mapping(tmp_path):
    _seed(tmp_path, [
        _row(media_id="unknown", filename="a.png", created_at="2026-08-17T10:00:00.000Z", paid_credit=""),
        _row(media_id="free", filename="b.png", created_at="2026-08-17T10:01:00.000Z", paid_credit="0"),
        _row(media_id="paid", filename="c.png", created_at="2026-08-17T10:02:00.000Z", paid_credit="1200"),
    ])
    by = {r["media_id"]: r["paid_credit"] for r in _flat(_get(login_client(tmp_path), **FRAME))}
    assert by == {"unknown": None, "free": 0, "paid": 1200}


def test_model_coalesces_name_then_video_model_then_id(tmp_path):
    _seed(tmp_path, [
        _row(media_id="named", filename="a.png", created_at="2026-08-17T10:00:00.000Z",
             model_name="Tsubaki", model_id="111", video_model="v4.0.1"),
        _row(media_id="video", filename="v.mp4", created_at="2026-08-17T10:01:00.000Z",
             is_video="1", model_name="", model_id="v4.0.1", video_model="v4.0.1"),
        _row(media_id="idonly", filename="b.png", created_at="2026-08-17T10:02:00.000Z",
             model_name="", model_id="222"),
        _row(media_id="none", filename="c.png", created_at="2026-08-17T10:03:00.000Z"),
    ])
    by = {r["media_id"]: r["model"] for r in _flat(_get(login_client(tmp_path), **FRAME))}
    assert by == {"named": "Tsubaki", "video": "v4.0.1", "idonly": "222", "none": ""}


def test_duration_parse(tmp_path):
    _seed(tmp_path, [
        _row(media_id="v10", filename="a.mp4", created_at="2026-08-17T10:00:00.000Z",
             is_video="1", video_duration="10"),
        _row(media_id="v5h", filename="b.mp4", created_at="2026-08-17T10:01:00.000Z",
             is_video="1", video_duration="5.5"),
        _row(media_id="vblank", filename="c.mp4", created_at="2026-08-17T10:02:00.000Z",
             is_video="1", video_duration=""),
        _row(media_id="vjunk", filename="d.mp4", created_at="2026-08-17T10:03:00.000Z",
             is_video="1", video_duration="n/a"),
        _row(media_id="img", filename="e.png", created_at="2026-08-17T10:04:00.000Z",
             video_duration="10"),           # not a video: duration is a video field
    ])
    by = {r["media_id"]: r["duration"] for r in _flat(_get(login_client(tmp_path), **FRAME))}
    assert by == {"v10": 10.0, "v5h": 5.5, "vblank": None, "vjunk": None, "img": None}


def test_count_in_task_counts_siblings_inside_the_window(tmp_path):
    _seed(tmp_path, [
        _row(media_id="a1", filename="a.png", task_id="tA", created_at="2026-08-17T10:00:00.000Z"),
        _row(media_id="a2", filename="b.png", task_id="tA", created_at="2026-08-17T10:00:01.000Z"),
        _row(media_id="a3", filename="c.png", task_id="tA", created_at="2026-08-01T10:00:00.000Z"),  # outside
        _row(media_id="b1", filename="d.png", task_id="tB", created_at="2026-08-16T10:00:00.000Z"),
        _row(media_id="l1", filename="e.png", task_id="", created_at="2026-08-16T11:00:00.000Z"),
    ])
    by = {r["media_id"]: r["count_in_task"] for r in _flat(_get(login_client(tmp_path), **FRAME))}
    assert by == {"a1": 2, "a2": 2, "b1": 1, "l1": 1}


# ---------------------------------------------------------------- auth

def test_history_requires_login(tmp_path):
    from moonglade_gallery import create_app
    _seed(tmp_path, [])
    r = create_app(tmp_path).test_client().get("/api/next/history")
    assert r.status_code == 401
    assert r.get_json() == {"error": "authentication required"}
