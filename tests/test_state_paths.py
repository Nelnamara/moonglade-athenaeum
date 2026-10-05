"""The library's own records go through one resolver (Wave 4 groundwork 3.19.0; moved 3.20.0).

moonglade_paths.state_path(out_dir, name) names the app's state files and folders inside a
library; moonglade_paths.reports_path(out_dir, name) names its reports. Since 3.20 they are
`out_dir/_moonglade/name` and `out_dir/_moonglade/reports/name` (a library not yet brought
across is read where it is: tests/test_library_records_folder.py). That only works if no
code builds one of these names off out_dir by hand, which the lint at the foot of this file
holds.

NOT records, and never routed through here: catalog.db, the picture folders, loom/,
gallery/, _deleted/ and _duplicates/ -- they stay where they are.
"""
import ast
from pathlib import Path

import pytest

from moonglade import backup as core
from moonglade import gallery as g
from moonglade import integrity
from moonglade import logs as mlog
from moonglade import paths
from moonglade import runs
from tests.conftest import first_party_sources

_REPO = Path(__file__).resolve().parents[1]

STATE_NAMES = (
    "achievements.json", "telemetry.json", "schedule.json", "train_guard.json",
    "reconcile_stamp.json", "jobs.jsonl", "raw_tasks.jsonl", "runs.db",
    "account_prefs", "account_state", "prompt_snippets", "toolbox_presets",
    "view_presets", "logs",
    # the install-wide files those per-account folders replaced, still read as a fallback for
    # an account with no file of its own (an install can have a live one: D:'s toolbox presets)
    "prompt_snippets.json", "toolbox_presets.json", "view_presets.json",
)
REPORT_NAMES = (
    "integrity_report.csv", "integrity_report.json", "integrity_marks.json",
    "integrity_report.lock", "audit_report.csv", "verify_report.csv",
    "organize_manifest.csv",
)
# Also a report, by a name with a time in it so the lint below cannot list it: the curation
# import's undo file, curation_pre_import_<time>.json (test_the_curation_snapshot_...). The
# CLI's --export-curation default file is NOT a record: it is the export the owner asked for.
# Library contents that are NOT the app's records: they stay put.
NOT_RECORDS = ("catalog.db", "images", "videos", "imported", "loom", "gallery",
               "_deleted", "_duplicates")


@pytest.mark.parametrize("name", STATE_NAMES)
def test_a_state_record_is_in_the_records_folder(tmp_path, name):
    rec = tmp_path / "_moonglade"
    assert paths.state_path(tmp_path, name) == rec / name
    assert paths.state_path(str(tmp_path), name) == rec / name     # str out_dir too


@pytest.mark.parametrize("name", REPORT_NAMES)
def test_a_report_is_in_the_reports_folder(tmp_path, name):
    rep = tmp_path / "_moonglade" / "reports"
    assert paths.reports_path(tmp_path, name) == rep / name
    assert paths.reports_path(str(tmp_path), name) == rep / name


def test_the_app_resolvers_are_in_the_records_folder(tmp_path):
    key = g._account_key("alice")
    rec = tmp_path / "_moonglade"
    assert g._ach_state_path(tmp_path) == rec / "achievements.json"
    assert g._telemetry_path(tmp_path) == rec / "telemetry.json"
    assert core._jobs_path(tmp_path) == rec / "jobs.jsonl"
    assert g.account_prefs_path(tmp_path, "alice") == rec / "account_prefs" / (key + ".json")
    assert g.account_state_path(tmp_path, "alice") == rec / "account_state" / (key + ".json")
    assert mlog.log_path(tmp_path) == rec / "logs" / "moonglade.log"
    assert runs.RunsStore(tmp_path).path == rec / "runs.db"


@pytest.fixture
def moved(monkeypatch):
    """Point both resolvers somewhere else, as the next release will, to prove the app asks
    them rather than building the path itself."""
    monkeypatch.setattr(paths, "state_path", lambda out, name: Path(out) / "_s" / name)
    monkeypatch.setattr(paths, "reports_path", lambda out, name: Path(out) / "_r" / name)


def test_the_app_resolvers_follow_state_path(tmp_path, moved):
    key = g._account_key("alice")
    s = tmp_path / "_s"
    assert g._ach_state_path(tmp_path) == s / "achievements.json"
    assert g._telemetry_path(tmp_path) == s / "telemetry.json"
    assert core._jobs_path(tmp_path) == s / "jobs.jsonl"
    assert g.account_prefs_path(tmp_path, "alice") == s / "account_prefs" / (key + ".json")
    assert g.account_state_path(tmp_path, "alice") == s / "account_state" / (key + ".json")
    assert mlog.log_path(tmp_path) == s / "logs" / "moonglade.log"
    assert runs.RunsStore(tmp_path).path == s / "runs.db"


def test_the_integrity_reports_follow_reports_path(tmp_path, moved):
    """The summary is read, and a mark written and read back, where reports_path() says."""
    import json
    r = tmp_path / "_r"
    r.mkdir()
    doc = {"format": integrity.REPORT_FORMAT, "counts": {},
           "verified_at": "2026-10-04T00:00:00Z"}
    (r / "integrity_report.json").write_text(json.dumps(doc), encoding="utf-8")
    assert integrity.read_summary(tmp_path) == doc
    integrity.set_mark(tmp_path, "m1", integrity.MARKS[0])
    assert (r / "integrity_marks.json").is_file()
    assert set(integrity.read_marks(tmp_path)) == {"m1"}
    assert not (tmp_path / "integrity_marks.json").exists()


def test_the_curation_import_snapshot_follows_reports_path(tmp_path, moved):
    """The undo file a curation import writes before it changes anything is a report, like
    the organize undo list: it goes where reports_path() says, beside nothing else."""
    from moonglade import curation_io as cio
    from moonglade.gallery import CATALOG_FIELDS, save_catalog
    db = tmp_path / "catalog.db"
    save_catalog(db, [{f: "" for f in CATALOG_FIELDS} | {
        "media_id": "m1", "filename": "a_m1.png", "created_at": "2025-01-01T00:00:00"}])
    (tmp_path / "_r").mkdir()
    doc = cio.export_curation(db)
    doc["items"] = [{"media_id": "m1", "rating": 3, "collections": [], "tags": [],
                     "mark": "", "note": ""}]
    rep = cio.import_curation(db, doc, apply=True)
    assert rep["snapshot"].startswith(cio.SNAPSHOT_PREFIX)
    assert (tmp_path / "_r" / rep["snapshot"]).is_file()
    assert not list(tmp_path.glob(cio.SNAPSHOT_PREFIX + "*"))


def test_the_reconcile_stamp_follows_state_path(tmp_path, moved):
    (tmp_path / "_s").mkdir()
    core._stamp_reconcile(tmp_path, 1, 0)
    assert (tmp_path / "_s" / "reconcile_stamp.json").is_file()
    assert not (tmp_path / "reconcile_stamp.json").exists()
    assert integrity.reconciled_at(tmp_path)          # and the reader finds it there


# ---- the lint: no code builds a record's name off out_dir by hand ----------------------

_RECORD_NAMES = set(STATE_NAMES) | set(REPORT_NAMES)


def _modules():
    return first_party_sources()          # the root, and the moonglade/ code folder


def _record_constants(trees):
    """Module-level names bound to a record name (JOBS_LOG_NAME = "jobs.jsonl", ...), from
    every module, so `core.RECONCILE_STAMP` is caught in another module too."""
    out = set()
    for tree in trees:
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                    and node.value.value in _RECORD_NAMES:
                out.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return out


def _names_a_record(node, consts):
    if isinstance(node, ast.Constant):
        return node.value in _RECORD_NAMES
    if isinstance(node, ast.Name):
        return node.id in consts
    if isinstance(node, ast.Attribute):
        return node.attr in consts
    return False


def _hand_built(path, tree, consts):
    lines = path.read_text(encoding="utf-8").splitlines()
    hits = []
    for node in ast.walk(tree):
        parts = []
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            parts = [node.right]
        elif isinstance(node, ast.Call):
            f = node.func
            if (isinstance(f, ast.Attribute) and f.attr in ("joinpath", "join")) or \
                    (isinstance(f, ast.Name) and f.id == "Path"):
                parts = node.args[1:] if isinstance(f, ast.Name) else node.args
                if isinstance(f, ast.Attribute) and f.attr == "join":
                    parts = node.args[1:]                     # os.path.join(out, NAME)
        if any(_names_a_record(p, consts) for p in parts):
            hits.append("%s:%d  %s" % (path.name, node.lineno, lines[node.lineno - 1].strip()))
    return hits


def test_no_code_builds_a_record_path_by_hand():
    modules = _modules()
    trees = {p: ast.parse(p.read_text(encoding="utf-8"), filename=str(p)) for p in modules}
    consts = _record_constants(trees.values())
    assert {"JOBS_LOG_NAME", "RUNS_DB", "REPORT_CSV", "RECONCILE_STAMP"} <= consts, \
        "the lint lost track of the record constants -- it would check nothing"
    stray = [h for p, t in trees.items() if p.relative_to(_REPO).as_posix() != "moonglade/paths.py"
             for h in _hand_built(p, t, consts)]
    assert not stray, ("build a library record's path with moonglade_paths.state_path() / "
                       "reports_path():\n  " + "\n  ".join(stray))


def test_the_lint_sees_a_hand_built_record():
    """The lint's own bite, on a fixture module: each spelling it must catch."""
    src = ("REPORT = 'audit_report.csv'\n"
           "a = out / 'achievements.json'\n"
           "b = Path(out) / REPORT\n"
           "c = os.path.join(out, 'jobs.jsonl')\n"
           "d = out.joinpath('logs')\n"
           "e = out / 'catalog.db'\n")
    tree = ast.parse(src)
    fake = _REPO / "tests" / "_lint_fixture.py"
    consts = _record_constants([tree])

    class _P:
        name = fake.name

        @staticmethod
        def read_text(encoding=None):
            return src
    hits = _hand_built(_P, tree, consts)
    assert [h.split(":")[1].split()[0] for h in hits] == ["2", "3", "4", "5"]
