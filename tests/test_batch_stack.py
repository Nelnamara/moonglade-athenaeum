"""GET /api/batch/<task_id> -- a BATCH stack's struct, in the SAME shape
/api/series/<sid> returns.

Owner ruling, 2026-09-07: a batch card opens in the series modal now, "separately
tagged so you know what you're looking at, batch or series", instead of re-loading
the whole library as the ?batch= drill-down. One modal wants one payload shape, so a
batch answers as a series of ONE run. Pins:
  * the struct: sid/task_id, a derived title, count_tasks == 1, count_images ==
    surviving rows, a one-entry `steps` list labelled "one generation";
  * order: #33's batch_index when EVERY row carries one, else media_id ascending
    (batch_member_order, the rule compute_series already applies to a series member);
  * 404 for an unknown id, for a blank id, and for a LONE image -- one survivor is
    not a batch, and the grid never draws a stack for it;
  * the route and the pictures listing the modal fetches next
    (/api/next/library?batch=) agree on the count, because both read through the same
    `(batch = ? OR task_id = ?)` predicate;
  * the route is a pure catalog read: no network, and it does not answer for a
    deleted-file row (the catalog's `filename != ''` survivor rule).
"""
import moonglade_gallery as G
from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_test_client


def _seed(tmp_path, rows):
    """Save rows to tmp_path/catalog.db. Every row gets a non-empty filename unless it
    names one itself (a blank filename is the catalog's 'gone' marker), but NO file is
    written -- this route is a pure catalog read."""
    full = [{f: "" for f in CATALOG_FIELDS}
            | {"filename": "pic_%s.png" % r["media_id"]} | r for r in rows]
    save_catalog(tmp_path / "catalog.db", full)
    return tmp_path / "catalog.db"


def _client(tmp_path):
    return login_test_client(create_app(tmp_path))


_P = "frost queen, glacial crown, aurora sky"


def _rows():
    """One 3-output batch (T1, batch_index 0/1/2 seeded out of order), one lone
    image (T2), and a 2-output batch with NO batch_index (T3)."""
    out = [
        {"media_id": "m30", "task_id": "T1", "batch_index": "2", "batch_size": "3",
         "prompt_full": _P, "created_at": "2026-08-20T10:00:02Z",
         "model_id": "M1", "model_name": "Model One"},
        {"media_id": "m10", "task_id": "T1", "batch_index": "0", "batch_size": "3",
         "prompt_full": _P, "created_at": "2026-08-20T10:00:00Z",
         "model_id": "M1", "model_name": "Model One"},
        {"media_id": "m20", "task_id": "T1", "batch_index": "1", "batch_size": "3",
         "prompt_full": _P, "created_at": "2026-08-20T10:00:01Z",
         "model_id": "M1", "model_name": "Model One"},
        {"media_id": "s1", "task_id": "T2", "prompt_full": "a lone output only",
         "created_at": "2026-08-20T09:00:00Z", "model_id": "M2", "model_name": "Two"},
        {"media_id": "b2", "task_id": "T3", "prompt_full": "unnumbered pair here",
         "created_at": "2026-08-20T08:00:00Z", "model_id": "M3", "model_name": "Three"},
        {"media_id": "b1", "task_id": "T3", "prompt_full": "unnumbered pair here",
         "created_at": "2026-08-20T08:00:00Z", "model_id": "M3", "model_name": "Three"},
    ]
    return out


# ---- the struct ---------------------------------------------------------------------

def test_batch_route_answers_the_series_shape(tmp_path):
    _seed(tmp_path, _rows())
    d = _client(tmp_path).get("/api/batch/T1").get_json()
    # every key the modal reads off a series struct is present and honest
    assert d["sid"] == "T1" and d["task_id"] == "T1"
    assert d["count_tasks"] == 1
    assert d["count_images"] == 3
    assert d["model"] == "Model One"
    assert d["title"] == "Frost queen"          # the same rule a series' title uses
    assert d["span"] == ["2026-08-20T10:00:00Z", "2026-08-20T10:00:02Z"]
    # ONE run, labelled as a generation rather than a dial-in delta
    assert len(d["steps"]) == 1
    step = d["steps"][0]
    assert step == {"task_id": "T1", "v": 1, "reroll": False,
                    "label": "one generation", "first_media_id": "m10", "n": 3}


def test_first_media_id_is_batch_index_order_not_row_order(tmp_path):
    """m10 is batch_index 0 but the SECOND row seeded; the struct must name it first."""
    _seed(tmp_path, _rows())
    d = _client(tmp_path).get("/api/batch/T1").get_json()
    assert d["steps"][0]["first_media_id"] == "m10"


def test_unnumbered_batch_falls_back_to_media_id(tmp_path):
    _seed(tmp_path, _rows())
    d = _client(tmp_path).get("/api/batch/T3").get_json()
    assert d["count_images"] == 2
    assert d["steps"][0]["first_media_id"] == "b1"


# ---- the 404s -----------------------------------------------------------------------

def test_unknown_task_404s(tmp_path):
    _seed(tmp_path, _rows())
    assert _client(tmp_path).get("/api/batch/NOPE").status_code == 404


def test_a_lone_image_is_not_a_batch(tmp_path):
    """One surviving row carries NO batch marker in the grouped grid, so no card can
    open it -- answering 200 would invent a stack the library never draws."""
    _seed(tmp_path, _rows())
    assert _client(tmp_path).get("/api/batch/T2").status_code == 404


def test_a_batch_whose_files_are_gone_404s(tmp_path):
    """`filename != ''` is the catalog's survivor rule; the listing applies it, so this
    must too, or the header would count rows the grid cannot show."""
    _seed(tmp_path, [
        {"media_id": "g1", "task_id": "G1", "filename": "", "prompt_full": _P},
        {"media_id": "g2", "task_id": "G1", "filename": "", "prompt_full": _P},
    ])
    assert _client(tmp_path).get("/api/batch/G1").status_code == 404


# ---- the two halves agree -----------------------------------------------------------

def test_the_struct_and_the_pictures_listing_count_the_same_rows(tmp_path):
    """The modal asks this route for the runs and ?batch= for the pictures. Both go
    through query_catalog's `(batch = ? OR task_id = ?)` predicate, so their counts
    cannot disagree."""
    _seed(tmp_path, _rows())
    cli = _client(tmp_path)
    meta = cli.get("/api/batch/T1").get_json()
    lib = cli.get("/api/next/library?batch=T1").get_json()
    assert meta["count_images"] == meta["steps"][0]["n"] == lib["total"] == 3
    assert {i["media_id"] for i in lib["items"]} == {"m10", "m20", "m30"}


def test_a_legacy_folder_batch_resolves_through_the_same_param(tmp_path):
    """--organize blanks task_id-era `batch` values into folder names; the ?batch=
    predicate has always matched either column, and this route rides it."""
    _seed(tmp_path, [
        {"media_id": "L1", "task_id": "", "batch": "legacy-folder", "prompt_full": _P},
        {"media_id": "L2", "task_id": "", "batch": "legacy-folder", "prompt_full": _P},
    ])
    d = _client(tmp_path).get("/api/batch/legacy-folder").get_json()
    assert d["count_images"] == 2 and d["steps"][0]["n"] == 2


# ---- the ordering helper, driven directly -------------------------------------------

def test_batch_member_order_prefers_batch_index_when_every_row_has_one():
    rows = [{"media_id": "c", "batch_index": "1"},
            {"media_id": "a", "batch_index": "2"},
            {"media_id": "b", "batch_index": "0"}]
    assert [r["media_id"] for r in G.batch_member_order(rows)] == ["b", "c", "a"]


def test_batch_member_order_falls_back_to_media_id_when_any_row_lacks_one():
    """All-or-nothing, exactly like compute_series: a partly-numbered task would
    otherwise interleave numbered and unnumbered rows."""
    rows = [{"media_id": "c", "batch_index": "1"},
            {"media_id": "a", "batch_index": ""},
            {"media_id": "b", "batch_index": "0"}]
    assert [r["media_id"] for r in G.batch_member_order(rows)] == ["a", "b", "c"]
    assert G.batch_member_order([]) == []
