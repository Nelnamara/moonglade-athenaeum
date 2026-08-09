"""Batch K: four server-side defects in moonglade_gallery.py's routes.

Each test here pins a promise the code was making but not keeping:

* **M20** -- `_gen_args_from_payload`'s docstring said "Clamped to safe ranges" while only
  `count` was clamped. width/height/steps/cfg went straight into a real paid submit, and
  the drawer is LOGIN-tier: any signed-in LAN device can POST to /api/generate directly.
  The clamp then had a defect of its own: it rewrote a request and charged for the rewrite
  without a word, so every clamp that fires now comes back in the response as `adjusted`.
* **M21** -- /api/fix was the last spend route that never called `_log_gen_failure`, and it
  is the ONE drawer action no free card ever covers, so every failure there is money gone.
* **M30** -- one resolver answers "is this clip on disk": `_find_local_video_file`
  (catalog filename, then the shared media-id matcher, quarantine excluded, library-bound).
  The classic detail page that used to share it is gone (React shell now), so /video-file
  is the surviving caller and these tests pin the resolver's behavior through it.
* **M32** -- /export-csv counted matching rows, then fetched exactly that many in a second,
  later query, so a concurrent catalog write silently truncated the download.

All mocked -- no network, no spend.
"""
import logging

import moonglade_backup as core
import moonglade_gallery
from moonglade_gallery import CATALOG_FIELDS, create_app, query_catalog, save_catalog

from tests.conftest import login_client, login_test_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


# ---------------------------------------------------------------------------
# M20 -- the Generate drawer's JSON really is clamped now
# ---------------------------------------------------------------------------

def _generate_capture(tmp_path, monkeypatch, payload, out=None):
    """POST `payload` to /api/generate with only the network stubbed, so the REAL
    core._gen_parameters builds the submit shape this returns.

    `out` is an optional dict the response body is copied into, for the tests that care
    what the CALLER was told as well as what PixAI was sent."""
    seen = {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "_apply_kaisuuken", lambda *a, **k: None)
    monkeypatch.setattr(core, "submit_generation",
                        lambda s, params: seen.update(params=params) or "t1")
    client = login_client(tmp_path)
    r = client.post("/api/generate", json=payload)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json().get("task_id") == "t1", r.get_json()
    if out is not None:
        out.update(r.get_json())
    return seen["params"]


def test_absurd_dimensions_steps_and_cfg_never_reach_a_paid_submit(tmp_path, monkeypatch):
    """The finding's own reproduction: a hand-rolled POST asking for a nine-digit canvas.

    core._gen_parameters only FLOORS width/height (its `_dim` is max(64, v//8*8)) and caps
    nothing, so before the clamp these arrived at PixAI verbatim -- 999999992x999999992 at
    999999 steps -- to be priced and charged at whatever that produces.
    """
    params = _generate_capture(tmp_path, monkeypatch, {
        "version_id": "V1", "prompt": "a night elf druid",
        "width": 999999999, "height": 999999999, "steps": 999999, "cfg": 4242,
        "count": 99})
    # Ceilings are the drawer's own controls: #gen-cw/#gen-ch max=4096, #gen-steps max=150,
    # #gen-cfg max=30, #gen-count's four options.
    assert params["width"] == 4096
    assert params["height"] == 4096
    assert params["samplingSteps"] == 150
    assert params["cfgScale"] == 30
    assert params["batchSize"] == 4


def test_below_range_values_are_raised_to_the_drawer_floor(tmp_path, monkeypatch):
    """The other half of "clamped": zero/negative steps and a 0 cfg are just as much a
    malformed submit as a nine-digit one, and _dim's 64px floor only ever covered w/h."""
    params = _generate_capture(tmp_path, monkeypatch, {
        "version_id": "V1", "prompt": "x",
        "width": -50, "height": 0, "steps": 0, "cfg": -3, "count": 0})
    assert params["width"] == 64
    assert params["height"] == 64
    assert params["samplingSteps"] == 1
    assert params["cfgScale"] == 1
    assert params["batchSize"] == 1


def test_ordinary_drawer_values_pass_through_untouched(tmp_path, monkeypatch):
    """A clamp that quietly rewrites legitimate settings would be a worse bug than the one
    it fixes: everything the drawer's own controls can emit must survive unchanged."""
    body = {}
    params = _generate_capture(tmp_path, monkeypatch, {
        "version_id": "V1", "prompt": "x",
        "width": 1024, "height": 1536, "steps": 25, "cfg": 7.5, "count": 3}, out=body)
    assert params["width"] == 1024
    assert params["height"] == 1536
    assert params["samplingSteps"] == 25
    assert params["cfgScale"] == 7.5
    assert params["batchSize"] == 3
    assert "adjusted" not in body, (
        "a submit that was NOT rewritten must carry no receipt -- a key on every response "
        "is a key the client learns to ignore")


def test_a_clamp_that_fires_is_named_in_the_response(tmp_path, monkeypatch):
    """The defect the clamp itself introduced. Clamping is SUBSTITUTION on a paid path: the
    caller asked for 200 sampling steps, PixAI rendered and billed 150, and the response was
    a bare {"task_id": ...} -- nothing in it, in the log, or on screen said the request had
    been rewritten. That is worse than the absurd value the clamp exists to refuse, because
    the money is gone either way and only this version tells you what it bought.

    This is reachable in practice, not only from a hand-rolled POST: `restrictions` is live
    PixAI data and gateField() applies it verbatim, so a model publishing
    samplingSteps.max = 200 widens the drawer's own #gen-steps to match and the drawer
    itself will send it (pinned in tests/test_med_gallery_ui.py).
    """
    body = {}
    params = _generate_capture(tmp_path, monkeypatch, {
        "version_id": "V1", "prompt": "a night elf druid",
        "steps": 200, "cfg": 44, "width": 8192}, out=body)
    assert params["samplingSteps"] == 150        # what was actually submitted and billed
    by_field = {a["field"]: a for a in body["adjusted"]}
    assert set(by_field) == {"steps", "cfg", "width"}, body["adjusted"]
    assert by_field["steps"] == {"field": "steps", "asked": 200, "used": 150}
    assert by_field["cfg"]["asked"] == 44 and by_field["cfg"]["used"] == 30
    assert by_field["width"]["asked"] == 8192 and by_field["width"]["used"] == 4096


def test_the_receipt_records_the_asked_for_value_not_the_defaulted_one(tmp_path, monkeypatch):
    """A missing or unparseable field falls back to num()'s default and is NOT a
    substitution -- nobody asked for anything, so there is nothing to report. Only a value
    the caller really sent and the clamp really moved counts."""
    body = {}
    _generate_capture(tmp_path, monkeypatch, {
        "version_id": "V1", "prompt": "x", "steps": "not a number", "count": 9}, out=body)
    assert [a["field"] for a in body["adjusted"]] == ["count"], (
        "an unparseable steps became the default 25, which is not a clamp firing")


# ---------------------------------------------------------------------------
# M21 -- a failed Fix leaves a trail, like every other spend route
# ---------------------------------------------------------------------------

def test_a_failed_fix_is_logged_with_its_request_shape(tmp_path, monkeypatch, caplog):
    """Fix ALWAYS spends -- no free card covers a fixer task -- so an unlogged failure here
    is credits gone with nothing written down anywhere.

    /api/generate and /api/edit have called _log_gen_failure since the 2026-07-26
    undiagnosable decline; /api/fix returned the redacted text to the browser (where
    friendlyGenErr() replaces it with a guess) and logged nothing at all. Asserts the
    request shape is recorded too, per _log_gen_failure's own contract: which image, which
    boxes IS the diagnosis for a moderation decline vs a rejected box.
    """
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())

    def boom(session, media_id, boxes):
        raise core.PixAIError("content moderation declined this fix")
    monkeypatch.setattr(core, "submit_fixer", boom)

    client = login_client(tmp_path)
    with caplog.at_level(logging.ERROR):
        r = client.post("/api/fix", json={
            "source": "733917871331404290",
            "boxes": [{"x": 10, "y": 20, "width": 30, "height": 40, "tag": "hand"}]})

    # The browser contract is unchanged: still 200 + {"error": ...}.
    assert r.status_code == 200
    assert "content moderation" in r.get_json()["error"]

    logged = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "/api/fix" in logged, "the failing route was not named"
    assert "content moderation declined this fix" in logged, "the raw error was not recorded"
    assert "733917871331404290" in logged, "the source media id was not recorded"
    assert "boxes" in logged and "hand" in logged, (
        "the box shape was not recorded -- it IS the diagnosis for a fixer decline")


def test_a_fix_that_fails_before_the_shape_exists_still_logs(tmp_path, monkeypatch, caplog):
    """Not every failure gets as far as building the submit body -- an unreachable session
    dies in _gen_session(), before `fix_params` is ever bound. That is why the handler reads
    it through locals().get(), exactly as /api/generate and /api/edit read theirs: a route
    that raised NameError inside its own except block would turn a diagnosable error into a
    500 with no message at all."""
    def no_session(*a, **k):
        raise core.PixAIError("No API key found.")
    monkeypatch.setattr(core, "_make_session", no_session)

    client = login_client(tmp_path)
    with caplog.at_level(logging.ERROR):
        r = client.post("/api/fix", json={"source": "555", "boxes": [{"tag": "face"}]})
    assert r.status_code == 200
    assert "No API key found." in r.get_json()["error"]
    assert any("/api/fix" in rec.getMessage() for rec in caplog.records)


# ---------------------------------------------------------------------------
# M30 -- /video-file answers through the one resolver, _find_local_video_file
# (the classic /image/<id> detail page that shared it was cut; the React shell
# is the page now, so the serving route is where the resolver's promises live)
# ---------------------------------------------------------------------------

def _video_app(tmp_path, rows):
    save_catalog(tmp_path / "catalog.db", rows)
    return login_test_client(create_app(tmp_path))


def test_video_file_serves_a_clip_that_is_on_disk(tmp_path):
    """The everyday path: catalog filename is right, the file is there, bytes come back."""
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / "dance_HERE.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42FAKE")
    cli = _video_app(tmp_path, [_row(media_id="HERE", filename="videos/dance_HERE.mp4",
                                     is_video="1", prompt_preview="a real clip")])
    served = cli.get("/video-file/HERE")
    assert served.status_code == 200
    assert served.data.endswith(b"FAKE")


def test_an_imported_m4v_counts_as_present(tmp_path):
    """_find_local_video_file's hand-written extension tuple was missing .m4v, which
    core.run_import_local copies in and catalogs as is_video='1'. The resolver reads
    core._VIDEO_EXTS now; without that, a perfectly present imported clip 404s here."""
    (tmp_path / "imported").mkdir()
    (tmp_path / "imported" / "home_M4V.m4v").write_bytes(b"\x00\x00\x00\x18ftypM4V ")
    cli = _video_app(tmp_path, [_row(media_id="M4V", filename="imported/home_M4V.m4v",
                                     is_video="1", source="local", prompt_preview="import")])
    served = cli.get("/video-file/M4V")
    assert served.status_code == 200


def test_a_stale_catalog_filename_still_resolves_and_serves(tmp_path):
    """The reviewer's reproduction, and the reason the first repair did not close M30.

    Row says the clip is at 2024-01/moved_STALE.mp4 (an `--organize` move, or a re-download
    under a new name); the real file is at videos/shot_STALE.mp4. /video-file used to serve
    row["filename"] and nothing else, so this 404'd even though the shared media-id
    fallback finds the clip fine. Both callers ask the one resolver now, so a stale column
    must not cost the download.
    """
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / "shot_STALE.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42REAL")
    cli = _video_app(tmp_path, [_row(media_id="STALE", filename="2024-01/moved_STALE.mp4",
                                     is_video="1", prompt_preview="a moved clip")])
    served = cli.get("/video-file/STALE")
    assert served.status_code == 200, (
        "the resolver's media-id fallback found the clip but the route returned {} -- the "
        "existence check and the serving route are asking different questions again".format(
            served.status_code))
    assert served.data.endswith(b"REAL")


def test_a_blank_catalog_filename_still_resolves_and_serves(tmp_path):
    """The other half of the same divergence: an older row (or one written before the
    download settled on a name) has an empty `filename`, so the old /video-file 404'd on
    the column check alone while the resolver's media-id fallback found the file fine."""
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / "shot_BLANK.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42HERE")
    cli = _video_app(tmp_path, [_row(media_id="BLANK", filename="", is_video="1",
                                     prompt_preview="a nameless row")])
    served = cli.get("/video-file/BLANK")
    assert served.status_code == 200
    assert served.data.endswith(b"HERE")


def test_a_clip_missing_from_disk_is_refused(tmp_path):
    """The negative direction: when nothing is on disk the route refuses -- the resolver
    must not have been widened into serving something that is not there."""
    cli = _video_app(tmp_path, [_row(media_id="NONE", filename="videos/none_NONE.mp4",
                                     is_video="1", prompt_preview="gone")])
    served = cli.get("/video-file/NONE")
    assert served.status_code == 404


def test_a_quarantined_copy_is_not_served_as_the_live_clip(tmp_path):
    """Sharing the resolver means sharing its exclusions. The media-id fallback skips
    _deleted/ and _duplicates/, so a quarantined copy cannot be resolved back and served
    as the live clip. (Only the fallback is exercised here, because that is the branch a
    blank filename takes; a live catalog row still pointing INTO the Trash is not a state
    the purge leaves behind, since it removes the row.)"""
    (tmp_path / "_deleted").mkdir()
    (tmp_path / "_deleted" / "shot_TRASH.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42OLD")
    cli = _video_app(tmp_path, [_row(media_id="TRASH", filename="", is_video="1",
                                     prompt_preview="quarantined")])
    served = cli.get("/video-file/TRASH")
    assert served.status_code == 404


# ---------------------------------------------------------------------------
# M32 -- the filtered CSV export is a single consistent read
# ---------------------------------------------------------------------------

def test_unpaginated_query_returns_every_row_and_an_honest_total(tmp_path):
    """page_size=None is the whole point of the fix: one statement, and a `total` that
    cannot disagree with the rows beside it (it IS len(rows))."""
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id=str(i), filename="2025-01/a_%d.png" % i,
                           prompt_preview="druid", created_at="2026-01-%02dT00:00:00Z" % (i + 1))
                      for i in range(7)])
    rows, total = query_catalog(db, q="druid", page_size=None)
    assert len(rows) == 7
    assert total == 7
    # Pagination itself is untouched.
    page, paged_total = query_catalog(db, q="druid", page=1, page_size=3)
    assert len(page) == 3 and paged_total == 7


def _csv_media_ids(response):
    import csv
    import io
    body = response.get_data(as_text=True)
    return [r["media_id"] for r in csv.DictReader(io.StringIO(body))]


def test_a_write_during_the_export_cannot_drop_rows_that_were_already_there(tmp_path, monkeypatch):
    """The finding's scenario, made deterministic: a "Sync now" Panel job inserts rows while
    the export runs.

    The old code counted the matches, then asked a SECOND query for exactly that many rows
    with no lock between them. Because the export sorts newest-first, rows inserted in the
    gap sort to the FRONT and push an equal number of pre-existing rows past the stale
    LIMIT -- so the CSV silently lost rows that were present before the download even
    started, with no truncation notice anywhere in the file.

    The hook below inserts three newer rows immediately after the FIRST catalog query
    returns. Against the old two-query code that lands squarely between the count and the
    fetch and OLD-1..OLD-3 vanish from the download; against the single unpaginated read
    there is no gap to land in.
    """
    db = tmp_path / "catalog.db"
    old_ids = ["OLD-%d" % i for i in range(1, 6)]
    save_catalog(db, [_row(media_id=mid, filename="2025-01/o_%s.png" % mid,
                           prompt_preview="druid",
                           created_at="2026-01-%02dT00:00:00Z" % i)
                      for i, mid in enumerate(old_ids, start=1)])

    # Build + log in FIRST: the hook counts catalog queries, and it must count the export's
    # own, not whatever the login flow happens to run on the way past the front door.
    cli = login_test_client(create_app(tmp_path))

    real_query = moonglade_gallery.query_catalog
    state = {"calls": 0}

    def racy_query(*args, **kwargs):
        out = real_query(*args, **kwargs)
        state["calls"] += 1
        if state["calls"] == 1:            # the concurrent sync job commits right here
            save_catalog(db, [_row(media_id="NEW-%d" % i,
                                   filename="2025-01/n_%d.png" % i,
                                   prompt_preview="druid",
                                   created_at="2026-06-%02dT00:00:00Z" % i)
                              for i in range(1, 4)])
        return out

    monkeypatch.setattr(moonglade_gallery, "query_catalog", racy_query)

    r = cli.get("/export-csv?q=druid")
    assert r.status_code == 200
    got = _csv_media_ids(r)
    missing = [mid for mid in old_ids if mid not in got]
    assert not missing, (
        "the export silently dropped {} row(s) that existed before it started: {}".format(
            len(missing), missing))


def test_the_unfiltered_export_is_still_the_whole_catalog(tmp_path):
    """No filter args -> load_catalog, unchanged: query_catalog's `filename != ''` would
    quietly drop rows whose file hasn't landed yet, which a full dump must not do."""
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="A", filename="2025-01/a_A.png"),
                      _row(media_id="B", filename="")])       # not on disk yet
    cli = login_test_client(create_app(tmp_path))
    got = _csv_media_ids(cli.get("/export-csv"))
    assert sorted(got) == ["A", "B"]


def test_a_filtered_export_ships_every_matching_row(tmp_path):
    """The plain, uncontended case -- the filter still filters, and nothing is lost to the
    new single-query path."""
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id=str(i), filename="2025-01/a_%d.png" % i,
                           prompt_preview=("druid" if i < 4 else "mage"),
                           created_at="2026-01-%02dT00:00:00Z" % (i + 1))
                      for i in range(6)])
    cli = login_test_client(create_app(tmp_path))
    got = _csv_media_ids(cli.get("/export-csv?q=druid"))
    assert sorted(got) == ["0", "1", "2", "3"]


def test_a_traversing_catalog_filename_is_refused(tmp_path):
    """The last one-sided divergence, found by the reviewer after the M30 repair landed.

    `filename` is joined onto out_dir, and the resolver's catalog-filename branch used to
    trust the join. /video-file never did -- it adds relative_to(out_dir) on top of
    send_from_directory's own safe_join -- so a row whose filename walks out of the library
    made the resolver and the route disagree. The resolver is library-bound now, so the
    file outside the backup folder is refused, even though it exists.

    Not a hostile-input scenario -- `filename` is written by this app, not by a visitor --
    but "the existence check and the serving route ask the same question" is the entire
    content of M30, and an exception to that is the bug, whoever produced the row.
    """
    outside = tmp_path.parent / "outside_the_library.mp4"
    outside.write_bytes(b"\x00\x00\x00\x18ftypmp42OUTSIDE")
    cli = _video_app(tmp_path, [_row(media_id="TRAV", filename="../outside_the_library.mp4",
                                     is_video="1", prompt_preview="a clip outside the library")])
    served = cli.get("/video-file/TRAV")
    assert served.status_code != 200, "the serving route handed back a file outside the library"
