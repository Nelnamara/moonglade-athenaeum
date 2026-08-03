"""The destructive half of Duplicate Review: POST /api/duplicates/resolve and
POST /api/duplicates/undo (2026-08-02). GET /api/duplicates itself (read-only)
is covered by tests/test_duplicates_api.py -- this file covers the quarantine/
undo mechanics (quarantine_duplicate_file, restore_quarantined_duplicate,
_validate_duplicate_pair) and the two routes: QUARANTINE ONLY (never hard-
delete), READ_ONLY gating, CSRF, the server-side keep-count-0 refusal, and a
real undo round trip. Route-tier declaration itself (LOGIN, anonymous
refusal) is covered structurally by tests/test_route_tiers.py.

Every test here uses tmp_path as BOTH out_dir and catalog.db location -- never
the real pixai_backup/ or config.json (see tests/conftest.py's autouse
_isolated_auth_config, which redirects core._config_path() for every test in
this suite)."""
import json
import re
from pathlib import Path

import moonglade_backup as core
from moonglade_gallery import (CATALOG_FIELDS, load_catalog, save_catalog,
                               quarantine_duplicate_file, restore_quarantined_duplicate,
                               _validate_duplicate_pair)

from tests.conftest import login_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _csrf(cli):
    """The session's real csrf token, off /panel's embedded `var CSRF = "...";`
    -- the same extraction tests/test_panel_users.py uses for every
    _check_csrf()-protected route in this app."""
    html = cli.get("/panel").get_data(as_text=True)
    m = re.search(r'var CSRF = "([^"]+)";', html)
    assert m, "panel page did not embed a CSRF token"
    return m.group(1)


def _exists_with_bytes(p, b):
    return p.exists() and p.read_bytes() == b


# ---------------------------------------------------------------------------
# quarantine_duplicate_file() / restore_quarantined_duplicate() -- pure
# function tests, no Flask involved
# ---------------------------------------------------------------------------

def test_quarantine_moves_file_and_deletes_row_when_no_survivor(tmp_path):
    """identical_file/same_seed/near_duplicate shape: the loser's media_id has
    exactly one live file, so quarantining it is the row's only copy going
    away -- same situation as a trash purge."""
    images = tmp_path / "images"; images.mkdir()
    (images / "p_t1_222.webp").write_bytes(b"KEEPER")
    (images / "p_t2_333.webp").write_bytes(b"LOSER-BYTES")
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="222", filename="p_t1_222.webp"),
                      _row(media_id="333", filename="p_t2_333.webp", rating="4")])
    thumb = tmp_path / "gallery" / "thumbs"; thumb.mkdir(parents=True)
    (thumb / "333.jpg").write_bytes(b"thumb")

    res = quarantine_duplicate_file(tmp_path, thumb, db, "333", "images/p_t2_333.webp",
                                    "identical_file:deadbeef")

    assert res["ok"] is True
    assert res["media_id"] == "333"
    assert res["row_deleted"] is True
    assert res["quarantine_path"] == "_duplicates/images/p_t2_333.webp"
    assert not (images / "p_t2_333.webp").exists()
    assert (tmp_path / "_duplicates" / "images" / "p_t2_333.webp").read_bytes() == b"LOSER-BYTES"
    assert not (thumb / "333.jpg").exists()             # thumb cleaned up, mirrors purge_media_local
    rows = {r["media_id"]: r for r in load_catalog(db)}
    assert set(rows) == {"222"}                          # loser's row is gone, keeper's untouched

    meta_path = tmp_path / "_duplicates" / "images" / "p_t2_333.webp.undo.json"
    assert meta_path.exists()
    sidecar = json.loads(meta_path.read_text(encoding="utf-8"))
    assert sidecar["original_path"] == "images/p_t2_333.webp"
    assert sidecar["row_deleted"] is True
    assert sidecar["catalog_row"]["rating"] == "4"        # full row snapshotted for undo


def test_quarantine_preserves_row_when_a_survivor_remains(tmp_path):
    """same_media shape: keeper and loser SHARE one media_id. Quarantining the
    loser copy must NOT delete the row -- the media_id is still alive via the
    keeper -- only reconcile filename/batch if the row pointed at the moved file."""
    images = tmp_path / "images"; images.mkdir()
    (tmp_path / "2024-03").mkdir()
    (images / "p_t1_111.webp").write_bytes(b"DUPE-COPY")          # the loser
    (tmp_path / "2024-03" / "111.webp").write_bytes(b"DUPE-COPY")  # the keeper (organized)
    db = tmp_path / "catalog.db"
    # Catalog row happens to point at the loser's exact filename before quarantine.
    save_catalog(db, [_row(media_id="111", filename="p_t1_111.webp", rating="5")])
    thumb = tmp_path / "gallery" / "thumbs"; thumb.mkdir(parents=True)
    (thumb / "111.jpg").write_bytes(b"thumb")

    res = quarantine_duplicate_file(tmp_path, thumb, db, "111", "images/p_t1_111.webp",
                                    "same_media:111")

    assert res["ok"] is True
    assert res["row_deleted"] is False
    assert not (images / "p_t1_111.webp").exists()
    assert (tmp_path / "2024-03" / "111.webp").exists()   # the keeper: untouched
    assert (thumb / "111.jpg").exists()                   # NOT cleaned up -- media_id still lives
    rows = load_catalog(db)
    assert len(rows) == 1 and rows[0]["media_id"] == "111"
    assert rows[0]["filename"] == "111.webp"               # reconciled onto the surviving copy
    assert rows[0]["rating"] == "5"                        # rest of the row untouched


def test_quarantine_avoids_collision_with_an_earlier_quarantine(tmp_path):
    images = tmp_path / "images"; images.mkdir()
    (images / "a.webp").write_bytes(b"FIRST")
    dupdir = tmp_path / "_duplicates" / "images"; dupdir.mkdir(parents=True)
    (dupdir / "a.webp").write_bytes(b"ALREADY THERE")
    db = tmp_path / "catalog.db"
    save_catalog(db, [])

    res = quarantine_duplicate_file(tmp_path, tmp_path / "t", db, "999", "images/a.webp", "g:1")

    assert res["ok"] is True
    assert res["quarantine_path"] != "_duplicates/images/a.webp"
    assert (dupdir / "a.webp").read_bytes() == b"ALREADY THERE"   # untouched
    assert _exists_with_bytes(tmp_path / res["quarantine_path"], b"FIRST")


def test_quarantine_rejects_path_traversal(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [])
    res = quarantine_duplicate_file(tmp_path, tmp_path / "t", db, "1", "../outside.webp", "g:1")
    assert res == {"ok": False, "error": "invalid path"}


def test_quarantine_missing_file_is_a_clean_error(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [])
    res = quarantine_duplicate_file(tmp_path, tmp_path / "t", db, "1", "images/nope.webp", "g:1")
    assert res["ok"] is False
    assert "not found" in res["error"]


def test_quarantine_blocked_when_read_only(tmp_path, monkeypatch):
    images = tmp_path / "images"; images.mkdir()
    (images / "a_1.webp").write_bytes(b"X")
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="1", filename="a_1.webp")])
    monkeypatch.setattr(core, "READ_ONLY", True)

    res = quarantine_duplicate_file(tmp_path, tmp_path / "t", db, "1", "images/a_1.webp", "g:1")

    assert res["ok"] is False
    assert "READ_ONLY" in res["error"]
    assert (images / "a_1.webp").exists(), "it moved the file on a blocked request"
    assert load_catalog(db)[0]["media_id"] == "1"          # row untouched too


def test_restore_moves_file_back_and_reinserts_deleted_row(tmp_path):
    images = tmp_path / "images"; images.mkdir()
    (images / "p_t2_333.webp").write_bytes(b"LOSER-BYTES")
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="333", filename="p_t2_333.webp", rating="4",
                           prompt_full="a stormy sea")])
    thumb = tmp_path / "gallery" / "thumbs"; thumb.mkdir(parents=True)
    q = quarantine_duplicate_file(tmp_path, thumb, db, "333", "images/p_t2_333.webp", "g:1")
    assert q["ok"] is True
    assert load_catalog(db) == []                          # sanity: really removed first

    res = restore_quarantined_duplicate(tmp_path, thumb, db, q["quarantine_path"])

    assert res == {"ok": True, "media_id": "333", "restored_path": "images/p_t2_333.webp"}
    assert (images / "p_t2_333.webp").read_bytes() == b"LOSER-BYTES"
    assert not (tmp_path / "_duplicates" / "images" / "p_t2_333.webp").exists()
    assert not (tmp_path / "_duplicates" / "images" / "p_t2_333.webp.undo.json").exists()
    rows = load_catalog(db)
    assert len(rows) == 1
    assert rows[0]["rating"] == "4" and rows[0]["prompt_full"] == "a stormy sea"


def test_restore_moves_file_back_without_touching_an_untouched_row(tmp_path):
    """same_media case: the row was never deleted at quarantine time, so undo
    must not fabricate/duplicate anything -- just the file comes back."""
    images = tmp_path / "images"; images.mkdir()
    (tmp_path / "2024-03").mkdir()
    (images / "p_t1_111.webp").write_bytes(b"DUPE")
    (tmp_path / "2024-03" / "111.webp").write_bytes(b"DUPE")
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="111", filename="p_t1_111.webp")])
    thumb = tmp_path / "gallery" / "thumbs"; thumb.mkdir(parents=True)
    q = quarantine_duplicate_file(tmp_path, thumb, db, "111", "images/p_t1_111.webp", "same_media:111")
    assert q["row_deleted"] is False

    res = restore_quarantined_duplicate(tmp_path, thumb, db, q["quarantine_path"])

    assert res["ok"] is True
    assert (images / "p_t1_111.webp").exists()
    rows = load_catalog(db)
    assert len(rows) == 1 and rows[0]["media_id"] == "111"


def test_restore_refuses_when_original_location_is_occupied(tmp_path):
    images = tmp_path / "images"; images.mkdir()
    (images / "p_t2_333.webp").write_bytes(b"LOSER-BYTES")
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="333", filename="p_t2_333.webp")])
    thumb = tmp_path / "t"
    q = quarantine_duplicate_file(tmp_path, thumb, db, "333", "images/p_t2_333.webp", "g:1")

    # Something else now sits at the original path (a re-download, a re-import).
    (images / "p_t2_333.webp").write_bytes(b"SOMETHING ELSE ENTIRELY")

    res = restore_quarantined_duplicate(tmp_path, thumb, db, q["quarantine_path"])

    assert res["ok"] is False
    assert "occupied" in res["error"]
    assert (images / "p_t2_333.webp").read_bytes() == b"SOMETHING ELSE ENTIRELY"  # not clobbered
    assert (tmp_path / "_duplicates" / "images" / "p_t2_333.webp").exists()       # still quarantined


def test_restore_missing_or_stale_record_fails_honestly(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [])
    res = restore_quarantined_duplicate(tmp_path, tmp_path / "t", db, "_duplicates/images/ghost.webp")
    assert res["ok"] is False
    assert "no undo record" in res["error"]


def test_restore_rejects_a_path_outside_duplicates_dir(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "live.webp").write_bytes(b"X")
    db = tmp_path / "catalog.db"
    save_catalog(db, [])
    res = restore_quarantined_duplicate(tmp_path, tmp_path / "t", db, "images/live.webp")
    assert res["ok"] is False
    assert (tmp_path / "images" / "live.webp").exists()


def test_restore_blocked_when_read_only(tmp_path, monkeypatch):
    images = tmp_path / "images"; images.mkdir()
    (images / "a_1.webp").write_bytes(b"X")
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="1", filename="a_1.webp")])
    q = quarantine_duplicate_file(tmp_path, tmp_path / "t", db, "1", "images/a_1.webp", "g:1")
    assert q["ok"] is True

    monkeypatch.setattr(core, "READ_ONLY", True)
    res = restore_quarantined_duplicate(tmp_path, tmp_path / "t", db, q["quarantine_path"])

    assert res["ok"] is False
    assert "READ_ONLY" in res["error"]
    assert (tmp_path / "_duplicates" / "images" / "a_1.webp").exists()  # nothing moved back


# ---------------------------------------------------------------------------
# _validate_duplicate_pair() -- the anti-forgery relationship check
# ---------------------------------------------------------------------------

def test_validate_same_media_requires_equal_media_id(tmp_path):
    images = tmp_path / "images"; images.mkdir()
    (images / "a_111.webp").write_bytes(b"X")
    (images / "b_222.webp").write_bytes(b"X")
    db = tmp_path / "catalog.db"
    ok, why = _validate_duplicate_pair(
        tmp_path, db, "same_media",
        {"media_id": "111", "path": "images/a_111.webp"},
        [{"media_id": "222", "path": "images/b_222.webp"}])
    assert ok is False
    assert "SAME media_id" in why


def test_validate_identical_file_rejects_when_bytes_differ(tmp_path):
    images = tmp_path / "images"; images.mkdir()
    (images / "a_1.webp").write_bytes(b"ONE THING")
    (images / "b_2.webp").write_bytes(b"A DIFFERENT THING")
    db = tmp_path / "catalog.db"
    ok, why = _validate_duplicate_pair(
        tmp_path, db, "identical_file",
        {"media_id": "1", "path": "images/a_1.webp"},
        [{"media_id": "2", "path": "images/b_2.webp"}])
    assert ok is False
    assert "byte-identical" in why


def test_validate_rejects_media_id_that_does_not_match_the_files_own_name(tmp_path):
    """The anti-forgery check: a client claiming media_id '999' for a file whose
    real, parsed media_id is '111' must be refused -- this is what stops a
    crafted request from pairing a real duplicate's metadata with an unrelated
    file to quarantine it."""
    images = tmp_path / "images"; images.mkdir()
    (images / "a_111.webp").write_bytes(b"X")
    (images / "b_222.webp").write_bytes(b"X")
    db = tmp_path / "catalog.db"
    ok, why = _validate_duplicate_pair(
        tmp_path, db, "same_media",
        {"media_id": "111", "path": "images/a_111.webp"},
        [{"media_id": "999", "path": "images/b_222.webp"}])   # 999 != what b_222.webp encodes
    assert ok is False


def test_validate_same_seed_requires_matching_seed_and_prompt(tmp_path):
    images = tmp_path / "images"; images.mkdir()
    (images / "a_1.webp").write_bytes(b"X")
    (images / "b_2.webp").write_bytes(b"Y")
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="1", filename="a_1.webp", seed="42", prompt_full="a cat"),
        _row(media_id="2", filename="b_2.webp", seed="42", prompt_full="a DIFFERENT cat"),
    ])
    ok, why = _validate_duplicate_pair(
        tmp_path, db, "same_seed",
        {"media_id": "1", "path": "images/a_1.webp"},
        [{"media_id": "2", "path": "images/b_2.webp"}])
    assert ok is False
    assert "seed" in why


def test_validate_same_seed_accepts_a_real_match(tmp_path):
    images = tmp_path / "images"; images.mkdir()
    (images / "a_1.webp").write_bytes(b"X")
    (images / "b_2.webp").write_bytes(b"Y")
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="1", filename="a_1.webp", seed="42", prompt_full="a cat"),
        _row(media_id="2", filename="b_2.webp", seed="42", prompt_full="a cat"),
    ])
    ok, why = _validate_duplicate_pair(
        tmp_path, db, "same_seed",
        {"media_id": "1", "path": "images/a_1.webp"},
        [{"media_id": "2", "path": "images/b_2.webp"}])
    assert ok is True


def test_validate_near_duplicate_checks_hamming_distance(tmp_path):
    images = tmp_path / "images"; images.mkdir()
    (images / "a_1.webp").write_bytes(b"X")
    (images / "b_2.webp").write_bytes(b"Y")
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="1", filename="a_1.webp", phash="0000000000000000"),
        # Hamming distance from all-zero is 32 (half the bits) -- well over threshold (10).
        _row(media_id="2", filename="b_2.webp", phash="ffffffff00000000"),
    ])
    ok, why = _validate_duplicate_pair(
        tmp_path, db, "near_duplicate",
        {"media_id": "1", "path": "images/a_1.webp"},
        [{"media_id": "2", "path": "images/b_2.webp"}])
    assert ok is False
    assert "threshold" in why


def test_validate_unknown_match_type_is_refused(tmp_path):
    images = tmp_path / "images"; images.mkdir()
    (images / "a_1.webp").write_bytes(b"X")
    (images / "b_2.webp").write_bytes(b"X")
    db = tmp_path / "catalog.db"
    ok, why = _validate_duplicate_pair(
        tmp_path, db, "made_up_tier",
        {"media_id": "1", "path": "images/a_1.webp"},
        [{"media_id": "2", "path": "images/b_2.webp"}])
    assert ok is False
    assert "unknown group type" in why


# ---------------------------------------------------------------------------
# POST /api/duplicates/resolve -- the real route
# ---------------------------------------------------------------------------

def test_resolve_single_group_end_to_end(tmp_path):
    images = tmp_path / "images"; images.mkdir()
    (images / "p_t1_222.webp").write_bytes(b"IDENTICAL")
    (images / "p_t2_333.webp").write_bytes(b"IDENTICAL")
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="222", filename="p_t1_222.webp"),
                      _row(media_id="333", filename="p_t2_333.webp")])
    cli = login_client(tmp_path)
    csrf = _csrf(cli)

    r = cli.post("/api/duplicates/resolve", json={
        "csrf": csrf,
        "group_id": "identical_file:deadbeef",
        "keep": {"media_id": "222", "path": "images/p_t1_222.webp"},
        "remove": [{"media_id": "333", "path": "images/p_t2_333.webp"}],
    })

    d = r.get_json()
    assert d["errors"] == []
    assert len(d["quarantined"]) == 1
    q = d["quarantined"][0]
    assert q["media_id"] == "333"
    assert q["kept_media_id"] == "222"
    assert q["quarantine_path"] == "_duplicates/images/p_t2_333.webp"
    assert d["reclaimed_bytes"] == len(b"IDENTICAL")
    assert (images / "p_t1_222.webp").exists()                      # keeper untouched
    assert not (images / "p_t2_333.webp").exists()
    assert (tmp_path / "_duplicates" / "images" / "p_t2_333.webp").exists()


def test_resolve_batch_of_groups_in_one_call(tmp_path):
    images = tmp_path / "images"; images.mkdir()
    (images / "a_1.webp").write_bytes(b"AAAA")
    (images / "b_2.webp").write_bytes(b"AAAA")
    (images / "c_3.webp").write_bytes(b"BBBB")
    (images / "d_4.webp").write_bytes(b"BBBB")
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id=m, filename=f) for m, f in
                      [("1", "a_1.webp"), ("2", "b_2.webp"),
                       ("3", "c_3.webp"), ("4", "d_4.webp")]])
    cli = login_client(tmp_path)
    csrf = _csrf(cli)

    r = cli.post("/api/duplicates/resolve", json={
        "csrf": csrf,
        "resolutions": [
            {"group_id": "identical_file:g1",
             "keep": {"media_id": "1", "path": "images/a_1.webp"},
             "remove": [{"media_id": "2", "path": "images/b_2.webp"}]},
            {"group_id": "identical_file:g2",
             "keep": {"media_id": "3", "path": "images/c_3.webp"},
             "remove": [{"media_id": "4", "path": "images/d_4.webp"}]},
        ],
    })

    d = r.get_json()
    assert d["errors"] == []
    assert {q["media_id"] for q in d["quarantined"]} == {"2", "4"}
    assert not (images / "b_2.webp").exists()
    assert not (images / "d_4.webp").exists()
    assert (images / "a_1.webp").exists() and (images / "c_3.webp").exists()


def test_resolve_refuses_zero_keep_server_side(tmp_path):
    """The disabled-but-not-actually-blocked bug class: even if a client sent a
    request with no keeper (a stale UI, a hand-rolled POST), the SERVER must
    refuse it -- not silently no-op, not quarantine everything."""
    images = tmp_path / "images"; images.mkdir()
    (images / "a_1.webp").write_bytes(b"X")
    (images / "b_2.webp").write_bytes(b"X")
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="1", filename="a_1.webp"),
                      _row(media_id="2", filename="b_2.webp")])
    cli = login_client(tmp_path)
    csrf = _csrf(cli)

    r = cli.post("/api/duplicates/resolve", json={
        "csrf": csrf,
        "group_id": "identical_file:g1",
        "keep": None,
        "remove": [{"media_id": "1", "path": "images/a_1.webp"},
                  {"media_id": "2", "path": "images/b_2.webp"}],
    })

    d = r.get_json()
    assert d["quarantined"] == []
    assert len(d["errors"]) == 1
    assert "keep-count is 0" in d["errors"][0]["error"]
    assert (images / "a_1.webp").exists() and (images / "b_2.webp").exists()  # nothing touched


def test_resolve_never_exposes_hard_delete(tmp_path):
    """No body field of any kind reaches --dedup-delete's hard-delete behavior
    -- the file must land in _duplicates/, never be unlinked."""
    images = tmp_path / "images"; images.mkdir()
    (images / "a_1.webp").write_bytes(b"X")
    (images / "b_2.webp").write_bytes(b"X")
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="1", filename="a_1.webp"),
                      _row(media_id="2", filename="b_2.webp")])
    cli = login_client(tmp_path)
    csrf = _csrf(cli)

    r = cli.post("/api/duplicates/resolve", json={
        "csrf": csrf,
        "group_id": "identical_file:g1",
        "keep": {"media_id": "1", "path": "images/a_1.webp"},
        "remove": [{"media_id": "2", "path": "images/b_2.webp"}],
        # Attempted smuggling of the CLI's hard-delete flag through the JSON body.
        "dedup_delete": True, "delete": True, "hard_delete": True,
    })

    d = r.get_json()
    assert d["errors"] == []
    assert (tmp_path / "_duplicates" / "images" / "b_2.webp").exists(), \
        "the file must be quarantined, not vanished"


def test_resolve_rejects_a_forged_duplicate_pair(tmp_path):
    """Two files that are NOT actually duplicates of each other, submitted as
    if they were -- the server must catch this even though the client-supplied
    group_id/keep/remove shape looks well-formed."""
    images = tmp_path / "images"; images.mkdir()
    (images / "a_1.webp").write_bytes(b"COMPLETELY DIFFERENT CONTENT A")
    (images / "b_2.webp").write_bytes(b"TOTALLY UNRELATED CONTENT B")
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="1", filename="a_1.webp"),
                      _row(media_id="2", filename="b_2.webp")])
    cli = login_client(tmp_path)
    csrf = _csrf(cli)

    r = cli.post("/api/duplicates/resolve", json={
        "csrf": csrf,
        "group_id": "identical_file:forged",
        "keep": {"media_id": "1", "path": "images/a_1.webp"},
        "remove": [{"media_id": "2", "path": "images/b_2.webp"}],
    })

    d = r.get_json()
    assert d["quarantined"] == []
    assert len(d["errors"]) == 1
    assert (images / "a_1.webp").exists() and (images / "b_2.webp").exists()


def test_resolve_requires_valid_csrf(tmp_path):
    images = tmp_path / "images"; images.mkdir()
    (images / "a_1.webp").write_bytes(b"X")
    (images / "b_2.webp").write_bytes(b"X")
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="1", filename="a_1.webp"),
                      _row(media_id="2", filename="b_2.webp")])
    cli = login_client(tmp_path)
    cli.get("/panel")  # establishes the session; deliberately ignore its real csrf

    r = cli.post("/api/duplicates/resolve", json={
        "csrf": "forged-token-not-in-session",
        "group_id": "identical_file:g1",
        "keep": {"media_id": "1", "path": "images/a_1.webp"},
        "remove": [{"media_id": "2", "path": "images/b_2.webp"}],
    })

    assert r.status_code == 400
    assert (images / "a_1.webp").exists() and (images / "b_2.webp").exists()


def test_resolve_blocked_when_read_only(tmp_path, monkeypatch):
    images = tmp_path / "images"; images.mkdir()
    (images / "a_1.webp").write_bytes(b"X")
    (images / "b_2.webp").write_bytes(b"X")
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="1", filename="a_1.webp"),
                      _row(media_id="2", filename="b_2.webp")])
    cli = login_client(tmp_path)
    csrf = _csrf(cli)
    monkeypatch.setattr(core, "READ_ONLY", True)

    r = cli.post("/api/duplicates/resolve", json={
        "csrf": csrf,
        "group_id": "identical_file:g1",
        "keep": {"media_id": "1", "path": "images/a_1.webp"},
        "remove": [{"media_id": "2", "path": "images/b_2.webp"}],
    })

    d = r.get_json()
    assert d["quarantined"] == []
    assert "READ_ONLY" in d["errors"][0]["error"]
    assert (images / "b_2.webp").exists(), "it moved the file on a blocked request"


def test_resolve_requires_login(tmp_path):
    from moonglade_gallery import create_app
    images = tmp_path / "images"; images.mkdir()
    (images / "a_1.webp").write_bytes(b"X")
    (images / "b_2.webp").write_bytes(b"X")
    save_catalog(tmp_path / "catalog.db", [_row(media_id="1", filename="a_1.webp"),
                                           _row(media_id="2", filename="b_2.webp")])
    cli = create_app(tmp_path).test_client()
    r = cli.post("/api/duplicates/resolve", json={
        "group_id": "identical_file:g1",
        "keep": {"media_id": "1", "path": "images/a_1.webp"},
        "remove": [{"media_id": "2", "path": "images/b_2.webp"}],
    }, environ_overrides={"REMOTE_ADDR": "203.0.113.5"})
    assert r.status_code == 401
    assert (images / "b_2.webp").exists()


# ---------------------------------------------------------------------------
# POST /api/duplicates/undo -- the real route
# ---------------------------------------------------------------------------

def test_undo_round_trip_through_the_real_routes(tmp_path):
    images = tmp_path / "images"; images.mkdir()
    (images / "p_t1_222.webp").write_bytes(b"IDENTICAL")
    (images / "p_t2_333.webp").write_bytes(b"IDENTICAL")
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="222", filename="p_t1_222.webp"),
                      _row(media_id="333", filename="p_t2_333.webp", rating="3")])
    cli = login_client(tmp_path)
    csrf = _csrf(cli)

    resolve_d = cli.post("/api/duplicates/resolve", json={
        "csrf": csrf, "group_id": "identical_file:g1",
        "keep": {"media_id": "222", "path": "images/p_t1_222.webp"},
        "remove": [{"media_id": "333", "path": "images/p_t2_333.webp"}],
    }).get_json()
    qpath = resolve_d["quarantined"][0]["quarantine_path"]
    assert not (images / "p_t2_333.webp").exists()
    assert {r["media_id"] for r in load_catalog(db)} == {"222"}   # loser's row gone, sanity check

    undo_r = cli.post("/api/duplicates/undo", json={"csrf": csrf, "quarantine_path": qpath})
    undo_d = undo_r.get_json()

    assert undo_d == {"ok": True, "media_id": "333", "restored_path": "images/p_t2_333.webp"}
    assert (images / "p_t2_333.webp").read_bytes() == b"IDENTICAL"
    rows = {r["media_id"]: r for r in load_catalog(db)}
    assert set(rows) == {"222", "333"}
    assert rows["333"]["rating"] == "3"


def test_undo_requires_valid_csrf(tmp_path):
    images = tmp_path / "images"; images.mkdir()
    (images / "a_1.webp").write_bytes(b"X")
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="1", filename="a_1.webp")])
    thumb = tmp_path / "t"
    q = quarantine_duplicate_file(tmp_path, thumb, db, "1", "images/a_1.webp", "g:1")
    assert q["ok"] is True

    cli = login_client(tmp_path)
    cli.get("/panel")
    r = cli.post("/api/duplicates/undo", json={
        "csrf": "forged-token-not-in-session", "quarantine_path": q["quarantine_path"]})

    assert r.status_code == 400
    assert (tmp_path / q["quarantine_path"]).exists()   # nothing moved back


def test_undo_missing_record_returns_a_clear_error(tmp_path):
    save_catalog(tmp_path / "catalog.db", [])
    cli = login_client(tmp_path)
    csrf = _csrf(cli)
    r = cli.post("/api/duplicates/undo", json={
        "csrf": csrf, "quarantine_path": "_duplicates/images/ghost.webp"})
    d = r.get_json()
    assert d["ok"] is False
    assert "no undo record" in d["error"]


def test_undo_requires_login(tmp_path):
    from moonglade_gallery import create_app
    save_catalog(tmp_path / "catalog.db", [])
    cli = create_app(tmp_path).test_client()
    r = cli.post("/api/duplicates/undo",
                json={"quarantine_path": "_duplicates/images/x.webp"},
                environ_overrides={"REMOTE_ADDR": "203.0.113.5"})
    assert r.status_code == 401
