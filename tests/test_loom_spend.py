"""POST /api/loom/spend -- the per-project spend ledger's one server call.

The route is the JOIN and nothing else: media_ids in, catalog `paid_credit` out. All the
arithmetic (dedup by task, the four buckets, the wording) lives in loom/src/loom-core.js
under `node --test` (loom/test/loom-spend-ledger.test.js). What these tests pin is the
CONTRACT the client's honesty depends on -- that the three states stay distinguishable:

    an int      -> a real charge
    None        -> the row exists, PixAI never reported a charge  ("unpriced")
    key absent  -> no catalog row at all                          ("missing")

Collapse any two of those and the ledger starts reporting deleted files as free work.
"""
import json

from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_test_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _authed_client(tmp_path, rows=()):
    if rows:
        save_catalog(tmp_path / "catalog.db", list(rows))
    return login_test_client(create_app(tmp_path))


def _spend(cli, media_ids):
    return cli.post("/api/loom/spend", data=json.dumps({"media_ids": media_ids}),
                    content_type="application/json")


def test_returns_the_real_charge_per_media_id(tmp_path):
    cli = _authed_client(tmp_path, [
        _row(media_id="1", filename="a_1.mp4", paid_credit="120", task_id="t1"),
        _row(media_id="2", filename="b_2.mp4", paid_credit="80", task_id="t2"),
    ])
    rows = _spend(cli, ["1", "2"]).get_json()["rows"]
    assert rows["1"] == {"paid_credit": 120, "task_id": "t1"}
    assert rows["2"] == {"paid_credit": 80, "task_id": "t2"}


def test_blank_paid_credit_is_none_not_zero(tmp_path):
    """'' means PixAI never told us. Reporting it as 0 would book an unknown charge as
    free work -- the exact lie the ledger's honesty rules exist to prevent."""
    cli = _authed_client(tmp_path, [
        _row(media_id="1", filename="a_1.mp4", paid_credit="", task_id="t1"),
    ])
    assert _spend(cli, ["1"]).get_json()["rows"]["1"]["paid_credit"] is None


def test_genuine_zero_stays_zero(tmp_path):
    """'0' is a real, settled answer -- a free-card-covered shot -- and must NOT come back
    as None, or a genuinely free project would render as 'unpriced' forever."""
    cli = _authed_client(tmp_path, [
        _row(media_id="1", filename="a_1.mp4", paid_credit="0", task_id="t1"),
    ])
    assert _spend(cli, ["1"]).get_json()["rows"]["1"]["paid_credit"] == 0


def test_unknown_media_id_is_absent_not_null(tmp_path):
    """A deleted local file / unresolved id has NO key. The client counts absent keys as
    'missing' and null values as 'unpriced' -- two different facts, one fixable."""
    cli = _authed_client(tmp_path, [
        _row(media_id="1", filename="a_1.mp4", paid_credit="", task_id="t1"),
    ])
    rows = _spend(cli, ["1", "does-not-exist"]).get_json()["rows"]
    assert "does-not-exist" not in rows
    assert rows["1"]["paid_credit"] is None


def test_task_id_rides_along_for_the_client_side_dedup(tmp_path):
    """paid_credit is TASK-level: two media from one task carry the same charge, and the
    client dedups on task_id rather than summing both."""
    cli = _authed_client(tmp_path, [
        _row(media_id="1", filename="a_1.png", paid_credit="50", task_id="shared"),
        _row(media_id="2", filename="a_2.png", paid_credit="50", task_id="shared"),
    ])
    rows = _spend(cli, ["1", "2"]).get_json()["rows"]
    assert rows["1"]["task_id"] == rows["2"]["task_id"] == "shared"


def test_float_like_credit_reads_as_an_int(tmp_path):
    cli = _authed_client(tmp_path, [
        _row(media_id="1", filename="a_1.mp4", paid_credit="12.0", task_id="t1"),
    ])
    assert _spend(cli, ["1"]).get_json()["rows"]["1"]["paid_credit"] == 12


def test_junk_credit_is_unknown_not_zero(tmp_path):
    cli = _authed_client(tmp_path, [
        _row(media_id="1", filename="a_1.mp4", paid_credit="n/a", task_id="t1"),
    ])
    assert _spend(cli, ["1"]).get_json()["rows"]["1"]["paid_credit"] is None


def test_empty_list_is_a_valid_empty_answer(tmp_path):
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.mp4")])
    assert _spend(cli, []).get_json() == {"rows": {}}


def test_blank_and_duplicate_ids_are_dropped_before_the_query(tmp_path):
    cli = _authed_client(tmp_path, [
        _row(media_id="1", filename="a_1.mp4", paid_credit="7", task_id="t1"),
    ])
    rows = _spend(cli, ["1", "1", "", "   ", None]).get_json()["rows"]
    assert rows == {"1": {"paid_credit": 7, "task_id": "t1"}}


def test_non_list_body_is_rejected(tmp_path):
    cli = _authed_client(tmp_path)
    assert _spend(cli, "1,2").status_code == 400
    assert cli.post("/api/loom/spend", data="{}",
                    content_type="application/json").status_code == 400


def test_absurd_id_count_is_rejected_rather_than_queried(tmp_path):
    cli = _authed_client(tmp_path)
    r = _spend(cli, [str(i) for i in range(2001)])
    assert r.status_code == 400
    assert "too many" in r.get_json()["error"]


def test_one_unreadable_row_degrades_to_unpriced_instead_of_500ing_the_batch(tmp_path):
    """A paid_credit that is a number Python cannot make an int of took down the WHOLE read.

    as_int caught ValueError from int(float(s)) -- but int(float("Infinity")) raises
    OverflowError, so one such row answered the request with a 500 and every other media id
    in the batch lost its number too. The three states this route exists to keep apart mean
    nothing if one bad row can delete all of them at once.

    "Unpriced" is the honest answer for a value that is not a charge: the row exists, and
    nothing usable was reported for it."""
    cli = _authed_client(tmp_path, [
        _row(media_id="1", filename="a_1.mp4", paid_credit="Infinity", task_id="t1"),
        _row(media_id="2", filename="b_2.mp4", paid_credit="-inf", task_id="t2"),
        _row(media_id="3", filename="c_3.mp4", paid_credit="nan", task_id="t3"),
        _row(media_id="4", filename="d_4.mp4", paid_credit="1e400", task_id="t4"),
        _row(media_id="5", filename="e_5.mp4", paid_credit="90", task_id="t5"),
    ])
    r = _spend(cli, ["1", "2", "3", "4", "5"])
    assert r.status_code == 200
    rows = r.get_json()["rows"]
    for bad in ("1", "2", "3", "4"):
        assert rows[bad]["paid_credit"] is None, bad
    assert rows["5"]["paid_credit"] == 90, "one bad row must not cost the good ones"


def test_login_required(tmp_path):
    """Anonymous callers get the same gate every other /api/loom/* route has -- this reads
    real catalog rows off disk."""
    cli = create_app(tmp_path).test_client()
    assert _spend(cli, ["1"]).status_code in (401, 403)


def test_route_writes_nothing_and_needs_no_pixai_session(tmp_path):
    """Read-only by construction: the catalog is untouched and the answer is identical
    when the same ids are asked for twice."""
    cli = _authed_client(tmp_path, [
        _row(media_id="1", filename="a_1.mp4", paid_credit="33", task_id="t1"),
    ])
    first = _spend(cli, ["1"]).get_json()
    second = _spend(cli, ["1"]).get_json()
    assert first == second == {"rows": {"1": {"paid_credit": 33, "task_id": "t1"}}}
