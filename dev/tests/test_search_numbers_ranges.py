"""Search by number and by date range: `lora:Name>0.7` (weight comparisons), and `created:`
quarters (2026Q3), inclusive ranges (2026-08..2026-10, open ended too) and day compares."""
import pytest

from moonglade.gallery import CATALOG_FIELDS, save_catalog, query_catalog


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


ROWS = [
    ("1", "Detail Tweaker:0.7, Moon Style:1.2", "2026-07-04T12:00:00"),
    ("2", "Detail Tweaker:0.4", "2026-08-31T23:59:59"),
    ("3", "Moon Style:0.5", "2026-09-15T08:00:00"),
    ("4", "", "2026-10-31T23:00:00"),
    ("5", "Detail Tweaker:0.9", "2026-11-01T00:00:00"),
    ("6", "Detail Tweaker:0.7", "2025-12-31T23:59:59"),
]


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "catalog.db"
    save_catalog(p, [_row(media_id=m, task_id="9" + m, filename="f%s.png" % m,
                          prompt_full="x", loras=lo, created_at=ts)
                     for m, lo, ts in ROWS])
    return p


def ids(db, q):
    rows, total = query_catalog(db, q=q, page_size=None)
    assert total == len(rows)
    return sorted(r["media_id"] for r in rows)


@pytest.mark.parametrize("q,want", [
    ("lora:detail>0.7", ["5"]),
    ("lora:detail>=0.7", ["1", "5", "6"]),
    ("lora:detail<0.5", ["2"]),
    ("lora:detail<=0.4", ["2"]),
    ("lora:detail=0.7", ["1", "6"]),
    ("lora:*>=0.5", ["1", "3", "5", "6"]),
    ("lora:>1", ["1"]),
    ('lora:"Moon Style">1', ["1"]),
    ('lora:"Moon Style"<1', ["3"]),
    ("lora:moon*>0.4", ["1", "3"]),
    # the name matches the SAME entry the weight is read from
    ("lora:moon>0.9 lora:detail<0.5", []),
    ("-lora:detail>0.5", ["2", "3", "4"]),
    # the old substring forms are untouched
    ("lora:detail", ["1", "2", "5", "6"]),
    ("lora:Tweaker:0.7", ["1", "6"]),
])
def test_lora_weight(db, q, want):
    assert ids(db, q) == want


@pytest.mark.parametrize("q,want", [
    ("created:2026Q3", ["1", "2", "3"]),
    ("created:2026q4", ["4", "5"]),
    ("created:2026Q1", []),
    ("created:>=2026Q4", ["4", "5"]),
    ("created:>2026Q3", ["4", "5"]),
    ("created:<2026Q3", ["6"]),
    ("created:<=2026Q3", ["1", "2", "3", "6"]),
    ("created:2026-08..2026-10", ["2", "3", "4"]),
    ("created:2026-08..2026-10-31", ["2", "3", "4"]),
    ("created:2026-08..2026-10-30", ["2", "3"]),
    ("created:2026-09-15..", ["3", "4", "5"]),
    ("created:..2026-08", ["1", "2", "6"]),
    ("created:2025..2026Q2", ["6"]),
    ("created:2026Q3..2026Q4", ["1", "2", "3", "4", "5"]),
    ("created:>=2026-09-15", ["3", "4", "5"]),
    ("created:>2026-09-15", ["4", "5"]),
    ("created:<=2026-08-31", ["1", "2", "6"]),
    # the old prefix forms are untouched
    ("created:2026-07", ["1"]),
    ("created:2026", ["1", "2", "3", "4", "5"]),
    ("created:<2026", ["6"]),
])
def test_created_ranges(db, q, want):
    assert ids(db, q) == want


@pytest.mark.parametrize("bad", [
    "created:2026Q5", "created:2026-13..2026-14", "created:2026-02-30..", "created:..",
])
def test_bad_dates_fall_back_to_text(db, bad):
    # a value that is not a date is searched as prompt text (nothing matches), never an error
    assert ids(db, bad) == []
