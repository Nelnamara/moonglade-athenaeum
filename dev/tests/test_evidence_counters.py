"""Achievement counts that rest on evidence rather than on a bump anyone can replay
(owner rulings, 2026-10-02).

The "need" counters lived in telemetry.json and moved on a bare request: an accepted
submit, a page load, a client-registered job row. Each one here now reads something that
leaves independent evidence:

  * `session_hour` arms only on a NEW in-app generation that PixAI itself timestamped in
    its local hour window, stamped when this server collects it -- never on a page load, and
    never for a generation made before the rule (no retroactive credit);
  * `edits`, `lora_used`, `lora_stacked`, `lora_distinct`, `gen_streak` are counted from the
    catalog's own rows for in-app generations (source api/local), so a recount on upgrade
    can raise them -- the owner accepted that an upgrade re-fires their toasts;
  * `loras_trained` counts training runs PixAI reports as finished (read when Runs is
    listed), so a failed run, a retry and a replayed submit add nothing;
  * `culled` counts each removed picture once (a delete, restore and delete again is one),
    on top of the count kept before this change;
  * `jobs_concurrent` counts only jobs this server has seen PixAI report as running, never
    rows a client registered;
  * `skin_changed_runs` moves only when the mark or animation really changed.

Feats are referred to by metric key only.
"""
import datetime as _dt
import inspect
import json

from moonglade import backup as core
from moonglade import gallery as g
from moonglade.gallery import CATALOG_FIELDS, save_catalog
from tests.conftest import login_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _utc_iso(local_dt):
    """A naive LOCAL wall-clock time as the catalog stores PixAI's stamp: ISO UTC with Z.
    Built through astimezone so it holds on any machine's zone (and on Windows, which has
    no time.tzset to pin one)."""
    return local_dt.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _local_today(h, m=0):
    d = _dt.date.today()
    return _dt.datetime(d.year, d.month, d.day, h, m)


def _aware(local_dt):
    return local_dt.astimezone(_dt.timezone.utc)


# ---------------------------------------------------------------------------
# session_hour: a NEW generation made in the window, never a page load
# ---------------------------------------------------------------------------

def test_the_window_rule_on_one_timestamp():
    made = _local_today(2, 30)
    assert g.session_hour_generation(_utc_iso(made), now=_aware(made) + _dt.timedelta(minutes=8))
    late = _local_today(3, 59)
    assert g.session_hour_generation(_utc_iso(late), now=_aware(late) + _dt.timedelta(hours=1))
    # outside the window, either side
    for h, m in ((4, 0), (1, 59), (13, 0)):
        t = _local_today(h, m)
        assert not g.session_hour_generation(_utc_iso(t), now=_aware(t)), (h, m)
    # an OLD generation from the window is not new: no retroactive credit
    assert not g.session_hour_generation(_utc_iso(made), now=_aware(made) + _dt.timedelta(days=2))
    # garbage never raises
    for junk in ("", None, "yesterday", "2026-13-40T99:00:00Z"):
        assert not g.session_hour_generation(junk)


def _collect_app(tmp_path, monkeypatch, rows):
    """An app whose task-status poll 'collects' by writing `rows` into the catalog, the way
    core.collect_generation does for a finished generation."""
    save_catalog(tmp_path / "catalog.db", [])
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "generation_status",
                        lambda s, tid: {"phase": "done", "paid_credit": 0})

    def _collect(session, tid, out, **k):
        save_catalog(tmp_path / "catalog.db", rows)
        return {"media_ids": [r["media_id"] for r in rows], "saved": len(rows),
                "is_video": False}
    monkeypatch.setattr(core, "collect_generation", _collect)
    return login_client(tmp_path)


def test_a_new_in_app_generation_made_in_the_window_arms_it(tmp_path, monkeypatch):
    made = _local_today(3, 10)
    cli = _collect_app(tmp_path, monkeypatch, [_row(
        media_id="N1", filename="n1.png", task_id="T1", source="api",
        created_at=_utc_iso(made))])
    monkeypatch.setattr(g, "_utc_now", lambda: _aware(made) + _dt.timedelta(minutes=4))
    cli.get("/api/task-status", query_string={"task_id": "T1"})
    assert g.load_telemetry(tmp_path)["flags"].get("session_hour") == 1
    assert g.telemetry_metrics(tmp_path)["session_hour"] == 1


def test_an_old_generation_collected_now_does_not_arm_it(tmp_path, monkeypatch):
    """Importing or collecting a task made in the window long ago is not a new generation."""
    made = _local_today(3, 10) - _dt.timedelta(days=30)
    cli = _collect_app(tmp_path, monkeypatch, [_row(
        media_id="O1", filename="o1.png", task_id="T2", source="api",
        created_at=_utc_iso(made))])
    cli.get("/api/task-status", query_string={"task_id": "T2"})
    assert "session_hour" not in g.load_telemetry(tmp_path)["flags"]


def test_a_daytime_generation_does_not_arm_it(tmp_path, monkeypatch):
    made = _local_today(14, 0)
    cli = _collect_app(tmp_path, monkeypatch, [_row(
        media_id="D1", filename="d1.png", task_id="T3", source="api",
        created_at=_utc_iso(made))])
    monkeypatch.setattr(g, "_utc_now", lambda: _aware(made) + _dt.timedelta(minutes=4))
    cli.get("/api/task-status", query_string={"task_id": "T3"})
    assert "session_hour" not in g.load_telemetry(tmp_path)["flags"]


def test_only_in_app_rows_count(tmp_path):
    made = _local_today(2, 45)
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="W1", filename="w1.png", source="", created_at=_utc_iso(made))])
    now = _aware(made) + _dt.timedelta(minutes=5)
    assert g.stamp_session_hour(tmp_path / "catalog.db", ["W1"], tmp_path, now=now) is False
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="A1", filename="a1.png", source="api", created_at=_utc_iso(made))])
    assert g.stamp_session_hour(tmp_path / "catalog.db", ["A1"], tmp_path, now=now) is True


def test_a_flag_earned_before_stays_earned(tmp_path):
    """Nobody loses the feat: an existing flag still reads as the metric, and earned_at
    pins it either way."""
    g.telem_flag("session_hour", out_dir=tmp_path)
    assert g.telemetry_metrics(tmp_path)["session_hour"] == 1


def test_the_achievements_route_no_longer_reads_the_hour():
    src = inspect.getsource(g.create_app)
    i = src.index("def api_achievements(")
    body = src[i:src.index("@app.route", i)]
    assert 'telem_flag("session_hour"' not in body and "now().hour" not in body


# ---------------------------------------------------------------------------
# The catalog-derived counts
# ---------------------------------------------------------------------------

def test_edits_count_in_app_edit_generations_from_the_catalog(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="1", filename="1.png", task_id="E1", derive_kind="edit", source="api"),
        _row(media_id="2", filename="2.png", task_id="E1", derive_kind="edit", source="api"),
        _row(media_id="3", filename="3.png", task_id="E2", derive_kind="edit", source="api"),
        # an edit made on the website and pulled in by a backup: not made in the app
        _row(media_id="4", filename="4.png", task_id="E3", derive_kind="edit", source=""),
        _row(media_id="5", filename="5.png", task_id="G1", derive_kind="", source="api"),
    ])
    assert g.achievement_metrics(db, use_cache=False)["edits"] == 2


def test_lora_counts_come_from_in_app_rows(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="1", filename="1.png", task_id="L1", source="api",
             loras="Glade:0.7, Moonwell:0.5"),
        _row(media_id="2", filename="2.png", task_id="L1", source="api",
             loras="Glade:0.7, Moonwell:0.5"),
        _row(media_id="3", filename="3.png", task_id="L2", source="api", loras="Glade:1"),
        _row(media_id="4", filename="4.png", task_id="L3", source="",
             loras="Web:1, Web2:1, Web3:1"),
        _row(media_id="5", filename="5.png", task_id="L4", source="api", loras=""),
    ])
    m = g.achievement_metrics(db, use_cache=False)
    assert m["lora_used"] == 2             # distinct in-app generations that used one
    assert m["lora_stacked"] == 2          # most on one in-app generation
    assert m["lora_distinct"] == 2         # Glade, Moonwell
    assert m["loras_distinct"] == 5        # the library-wide count is unchanged in meaning


def test_the_generation_streak_comes_from_in_app_rows(tmp_path):
    db = tmp_path / "catalog.db"
    base = _dt.datetime(2026, 2, 1, 12, 0)
    rows = [_row(media_id=str(i), filename="%d.png" % i, source="api",
                 created_at=_utc_iso(base + _dt.timedelta(days=i))) for i in range(3)]
    rows.append(_row(media_id="9", filename="9.png", source="",
                     created_at=_utc_iso(base + _dt.timedelta(days=3))))
    save_catalog(db, rows)
    assert g.achievement_metrics(db, use_cache=False)["gen_streak"] == 3


def test_old_counters_in_telemetry_no_longer_shadow_the_catalog(tmp_path):
    """The merge is catalog then telemetry, and a counter of the same name used to win.
    The retired counters are dropped from the flatten, so a stale or hand-edited
    telemetry.json cannot speak for them any more."""
    g._telemetry_path(tmp_path).write_text(json.dumps({
        "counters": {"edits": 999, "lora_used": 999, "lora_distinct": 999, "gen_streak": 999},
        "maxima": {"lora_stacked": 999}, "sets": {"loras": ["a", "b"]}, "flags": {},
        "days": [], "day_lists": {"gen_days": ["2026-01-01", "2026-01-02"]}}),
        encoding="utf-8")
    m = g.telemetry_metrics(tmp_path)
    for k in ("edits", "lora_used", "lora_stacked", "lora_distinct", "gen_streak"):
        assert k not in m, k


def test_no_submit_path_bumps_a_retired_counter():
    src = inspect.getsource(g)
    for needle in ('telem_bump("edits"', 'telem_bump("lora_used"', 'telem_max("lora_stacked"',
                   'telem_set_add("loras"', 'telem_bump("loras_trained"', 'telem_bump("culled"'):
        assert needle not in src, needle
    assert 'telem_bump("culled"' not in inspect.getsource(core)


# ---------------------------------------------------------------------------
# culled: each removed picture once
# ---------------------------------------------------------------------------

def test_a_deleted_picture_counts_once_however_often_it_comes_back(tmp_path):
    imgs = tmp_path / "images"
    imgs.mkdir()
    for mid in ("1", "2"):
        (imgs / ("pic_%s.png" % mid)).write_bytes(b"x" + mid.encode())
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="pic_1.png"),
        _row(media_id="2", filename="pic_2.png")])
    g.telem_bump("culled", 5, out_dir=tmp_path)          # the count kept before the change
    cli = login_client(tmp_path)
    assert cli.post("/api/delete-local", json={"media_ids": ["1", "2"]}).get_json()["count"] == 2
    assert g.telemetry_metrics(tmp_path)["culled"] == 7
    assert cli.post("/api/trash/restore", json={"media_ids": ["1"]}).get_json()["restored"] == ["1"]
    assert cli.post("/api/delete-local", json={"media_ids": ["1"]}).get_json()["count"] == 1
    assert g.telemetry_metrics(tmp_path)["culled"] == 7, "a restore and re-delete counted twice"


def test_the_cli_dedup_counts_each_duplicated_picture_once(tmp_path):
    """--dedup --apply keys each swept copy by what it duplicated, so copying the same file
    back and sweeping it again is not a second piece."""
    import types
    from moonglade.gallery import init_db

    def _dup_and_sweep():
        (tmp_path / "images").mkdir(exist_ok=True)
        (tmp_path / "2023-10").mkdir(exist_ok=True)
        (tmp_path / "images" / "a_prompt_t1_111.webp").write_bytes(b"AAAA")
        (tmp_path / "2023-10" / "111.webp").write_bytes(b"AAAA")
        core.cmd_dedup(types.SimpleNamespace(out=None, no_content=True, dedup_delete=True,
                                             apply=True, progress=None),
                       tmp_path, tmp_path / "catalog.db")
    init_db(tmp_path / "catalog.db")
    _dup_and_sweep()
    assert g.telemetry_metrics(tmp_path)["culled"] == 1
    _dup_and_sweep()
    assert not (tmp_path / "images" / "a_prompt_t1_111.webp").exists()
    assert g.telemetry_metrics(tmp_path)["culled"] == 1


def test_culled_is_measured_on_a_fresh_install(tmp_path):
    assert g.telemetry_metrics(tmp_path)["culled"] == 0


# ---------------------------------------------------------------------------
# jobs_concurrent: only jobs PixAI said were running
# ---------------------------------------------------------------------------

def test_registered_job_rows_cannot_raise_the_peak(tmp_path, monkeypatch):
    save_catalog(tmp_path / "catalog.db", [])
    cli = login_client(tmp_path)
    for i in range(50):
        assert cli.post("/api/jobs", json={"job_id": "fake-%d" % i, "status": "running",
                                           "type": "generate"}).get_json()["ok"] is True
    cli.post("/api/jobs", json={"job_id": "9001", "status": "running", "type": "generate"})
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "generation_status",
                        lambda s, t: {"phase": "running", "started": True, "paid_credit": 0})
    cli.get("/api/task-status", query_string={"task_id": "9001"})
    assert g.telemetry_metrics(tmp_path)["jobs_concurrent"] == 1


# ---------------------------------------------------------------------------
# skin_changed_runs: a real change only
# ---------------------------------------------------------------------------

def test_an_unchanged_branding_post_does_not_count_a_change(tmp_path):
    save_catalog(tmp_path / "catalog.db", [])
    cli = login_client(tmp_path)
    cfg = cli.get("/api/branding").get_json()
    cli.post("/api/branding", json={"mark": cfg["mark"], "anim": cfg["anim"]})
    assert g.telemetry_metrics(tmp_path).get("skin_changed_runs", 0) == 0
    other = next(a for a in cfg["anims"] if a != cfg["anim"])
    cli.post("/api/branding", json={"anim": other})
    assert g.telemetry_metrics(tmp_path)["skin_changed_runs"] == 1
