"""Every library walker skips `_moonglade/` (3.20.0, "the move", item 3).

The library's own records (its JSON, jobs, logs, runs.db, reports) now sit in one folder at
the library's top. A walker that descended into it could catalogue a record as a picture,
count it on Health, flag it as a stray, move it in an --organize or quarantine it in a
--dedup. `_moonglade` is in the shared exclusion every walker is handed (QUARANTINE_EXCLUDE
and therefore QUARANTINE_EXCLUDE_ANYWHERE, IMPORT_EXCLUDE and HEALTH_EXCLUDE), and the two
walkers that bring their own list -- the disk count and the file-name lookup -- skip it too.

The library here holds a real picture in images/ and, in _moonglade/, a .png named exactly
like a catalogued picture and a .db: neither may ever be seen as part of the library.
"""
from types import SimpleNamespace

import pytest

from moonglade import backup as core
from moonglade import gallery as g
from moonglade import integrity
from moonglade import paths

# moonglade.similar imports numpy and pixeltable at module level, and CI installs a curated list
# without them (it ignores dev/tests/test_similar.py for the same reason), so only the test that
# needs it skips. It is imported here, at collection, as dev/tests/test_similar.py does: its
# import chain reads the registry, which the autouse guard refuses once a test is running.
try:
    from moonglade import similar as ps
except ImportError:
    ps = None

REC = paths.LIBRARY_APP_DIRNAME


@pytest.fixture
def library(tmp_path):
    lib = tmp_path / "lib"
    (lib / "images").mkdir(parents=True)
    (lib / "images" / "real_100.png").write_bytes(b"PNG-REAL")
    rec = lib / REC
    (rec / "logs").mkdir(parents=True)
    (rec / "a_999.png").write_bytes(b"PNG-IN-RECORDS")          # named like a picture
    (rec / "logs" / "deep_998.png").write_bytes(b"PNG-DEEPER")
    (rec / "runs.db").write_bytes(b"SQLite format 3\x00")
    row = {f: "" for f in g.CATALOG_FIELDS}
    g.save_catalog(lib / "catalog.db", [
        row | {"media_id": "100", "filename": "images/real_100.png",
               "created_at": "2025-01-01T00:00:00", "prompt_preview": "real"},
        row | {"media_id": "999", "filename": "a_999.png",
               "created_at": "2025-02-01T00:00:00", "prompt_preview": "named"}])
    return lib


def _rels(entries):
    return {str(e.rel).replace("\\", "/") for e in entries}


def test_every_shared_exclusion_names_it():
    for name, excl in (("QUARANTINE_EXCLUDE", g.QUARANTINE_EXCLUDE),
                       ("IMPORT_EXCLUDE", g.IMPORT_EXCLUDE),
                       ("HEALTH_EXCLUDE", g.HEALTH_EXCLUDE)):
        assert REC in excl, name
    assert "**/" + REC in g.QUARANTINE_EXCLUDE_ANYWHERE


@pytest.mark.parametrize("exclude", ["QUARANTINE_EXCLUDE", "QUARANTINE_EXCLUDE_ANYWHERE",
                                     "IMPORT_EXCLUDE", "HEALTH_EXCLUDE"])
def test_the_scan_never_enters_it(library, exclude):
    got = _rels(g.scan_library(library, kinds=("image", "video"),
                               exclude=getattr(g, exclude)))
    assert got == {"images/real_100.png"}


def test_the_default_scan_never_enters_it(library):
    assert _rels(g.scan_library(library)) == {"images/real_100.png"}


def test_a_picture_lookup_never_answers_from_it(library):
    assert g.files_for(library, "999") == []
    assert g.find_files_for_media_id(library, "999") == []
    assert g.find_files_for_media_id(library, "999", include_gallery=True) == []
    assert g.find_image_file(library, "999", "a_999.png") is None
    assert g.find_image_file(library, "100", "real_100.png") == library / "images" / "real_100.png"


def test_the_audit_and_dedup_never_see_it(library):
    seen = {str(rel).replace("\\", "/") for _, rel, _, _ in core._scan_media_files(library)}
    assert seen == {"images/real_100.png"}
    assert g.duplicate_groups(library) == []                     # the MCP's and the browser's


def test_the_disk_count_never_counts_it(library):
    n, b, thumbs = core._count_backup_images(library)
    assert (n, b, thumbs) == (1, len(b"PNG-REAL"), 0)


def test_health_never_counts_it_or_calls_it_a_stray(library):
    h = g.collection_health(library, library / "catalog.db")
    assert h["total_files"] == 1
    assert h["uncataloged"] == 0


def test_the_integrity_check_never_flags_it(library):
    summary = integrity.verify_library(library, library / "catalog.db")
    paths_seen = [ln[2] for ln in summary["lines"]]
    assert not [p for p in paths_seen if p.startswith(REC + "/")], paths_seen
    assert summary["files"] == 1


def test_the_similar_index_never_embeds_it(library):
    if ps is None:
        pytest.skip("moonglade.similar needs numpy and pixeltable")
    assert [m for m, _ in ps.scan_dir(library)] == ["100"]


def test_organize_never_moves_it(library):
    """Catalog row 999 has no picture of its own -- only the record named like it. An
    --organize must leave the records folder exactly as it was."""
    before = sorted(p.relative_to(library) for p in (library / REC).rglob("*"))
    args = SimpleNamespace(out=str(library), name_length=60, name_sep="_", convert=None,
                           dry_run=False, embed_metadata=False, jpeg_quality=92,
                           jpeg_bg="white", keep_webp=False, progress=None)
    core.cmd_organize(args, library, library / "images", library / "catalog.db")
    after = sorted(p.relative_to(library) for p in (library / REC).rglob("*"))
    assert set(before) <= set(after)          # (its own undo list now lands in reports/)
    assert (library / REC / "a_999.png").read_bytes() == b"PNG-IN-RECORDS"
    assert not list(library.glob("2025-02/*999*"))           # nothing was organized out of it
    assert list(library.glob("2025-01/*100.png"))             # ...while the real one was


def test_an_internal_import_never_brings_it_in(library):
    got = _rels(g.scan_library(library, kinds=("image", "video"), exclude=g.IMPORT_EXCLUDE))
    assert not [r for r in got if r.startswith(REC + "/")]
