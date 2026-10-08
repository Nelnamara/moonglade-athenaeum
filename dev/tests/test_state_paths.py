"""The library's own records go through named resolvers (SPEC_3.20_REBUILD.md, Lane D).

In a library everything of the app's is in its _moonglade/ folder, one home each:
  * moonglade_paths.records_path(out_dir, name)    _moonglade/records/name
  * moonglade_paths.decisions_path(out_dir, name)  _moonglade/decisions/name
  * moonglade_paths.account_dir(out_dir, login)    _moonglade/accounts/<login key>/
  * moonglade_paths.loom_root(out_dir)             _moonglade/loom/
and the app's log is this install's (local/logs/), never a library's. Nothing reads an old
place: only the move (moonglade.migrate) names one, which is why the lint at the foot of this
file exempts it beside moonglade/paths.py.

NOT records, and never routed through here: catalog.db, the picture folders, gallery/,
_deleted/ and _duplicates/ -- they stay where they are.
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

_REPO = Path(__file__).resolve().parents[2]

RECORD_NAMES = (
    "achievements.json", "telemetry.json", "schedule.json", "train_guard.json",
    "reconcile_stamp.json", "jobs.jsonl", "raw_tasks.jsonl", "runs.db",
    "integrity_report.csv", "integrity_report.json", "integrity_report.lock",
    "audit_report.csv", "verify_report.csv",
)
DECISION_NAMES = ("integrity_marks.json", "organize_manifest.csv")
# The per-login folders and the legacy shared files of older layouts, which only the move
# may name now (the lint below holds every other module away from them).
OLD_LAYOUT_NAMES = ("account_prefs", "account_state", "prompt_snippets", "toolbox_presets",
                    "view_presets", "logs", "prompt_snippets.json", "toolbox_presets.json",
                    "view_presets.json")
NOT_RECORDS = ("catalog.db", "images", "videos", "imported", "gallery", "_deleted",
               "_duplicates")


@pytest.mark.parametrize("name", RECORD_NAMES)
def test_a_record_is_in_the_records_folder(tmp_path, name):
    rec = tmp_path / "_moonglade" / "records"
    assert paths.records_path(tmp_path, name) == rec / name
    assert paths.records_path(str(tmp_path), name) == rec / name     # str out_dir too


@pytest.mark.parametrize("name", DECISION_NAMES)
def test_a_decision_is_in_the_decisions_folder(tmp_path, name):
    dec = tmp_path / "_moonglade" / "decisions"
    assert paths.decisions_path(tmp_path, name) == dec / name
    assert paths.decisions_path(str(tmp_path), name) == dec / name


def test_asking_never_makes_a_folder_outside_a_library(tmp_path):
    """A first write must land, so asking makes the folder -- but only inside a library that
    exists, and never with make=False."""
    nowhere = tmp_path / "not-a-library"
    paths.records_path(nowhere, "runs.db")
    assert not nowhere.exists()
    paths.records_path(tmp_path, "runs.db", make=False)
    assert not (tmp_path / "_moonglade").exists()
    paths.records_path(tmp_path, "runs.db")
    assert (tmp_path / "_moonglade" / "records").is_dir()


def test_the_app_resolvers_are_in_the_new_homes(tmp_path):
    key = g._account_key("alice")
    app = tmp_path / "_moonglade"
    assert g._ach_state_path(tmp_path) == app / "records" / "achievements.json"
    assert g._telemetry_path(tmp_path) == app / "records" / "telemetry.json"
    assert core._jobs_path(tmp_path) == app / "records" / "jobs.jsonl"
    assert g.account_prefs_path(tmp_path, "alice") == app / "accounts" / key / "prefs.json"
    assert g.account_prefs_path(tmp_path, g.ACCOUNT_LOCAL) == \
        app / "accounts" / "_local" / "prefs.json"
    assert g.account_state_path(tmp_path, "alice") == app / "accounts" / key / "state.json"
    assert runs.RunsStore(tmp_path).path == app / "records" / "runs.db"
    assert mlog.log_path() == paths.logs_dir() / "moonglade.log"     # the install's, not a library's


def test_the_account_key_is_the_paths_rule():
    assert g._account_key("Nel") == paths.account_key("Nel") != paths.account_key("nel")
    assert len(paths.account_key("Nel")) == 16


@pytest.fixture
def moved(monkeypatch):
    """Point the resolvers somewhere else, to prove the app asks them rather than building
    the path itself."""
    monkeypatch.setattr(paths, "records_path",
                        lambda out, name, make=True: Path(out) / "_r" / name)
    monkeypatch.setattr(paths, "decisions_path",
                        lambda out, name, make=True: Path(out) / "_d" / name)


def test_the_app_resolvers_follow_records_path(tmp_path, moved):
    r = tmp_path / "_r"
    assert g._ach_state_path(tmp_path) == r / "achievements.json"
    assert g._telemetry_path(tmp_path) == r / "telemetry.json"
    assert core._jobs_path(tmp_path) == r / "jobs.jsonl"
    assert runs.RunsStore(tmp_path).path == r / "runs.db"


def test_the_integrity_reports_and_marks_follow_their_resolvers(tmp_path, moved):
    """The summary is read where records_path() says; a mark is written and read back where
    decisions_path() says."""
    import json
    r = tmp_path / "_r"
    r.mkdir()
    (tmp_path / "_d").mkdir()
    doc = {"format": integrity.REPORT_FORMAT, "counts": {},
           "verified_at": "2026-10-04T00:00:00Z"}
    (r / "integrity_report.json").write_text(json.dumps(doc), encoding="utf-8")
    assert integrity.read_summary(tmp_path) == doc
    integrity.set_mark(tmp_path, "m1", integrity.MARKS[0])
    assert (tmp_path / "_d" / "integrity_marks.json").is_file()
    assert set(integrity.read_marks(tmp_path)) == {"m1"}
    assert not (tmp_path / "integrity_marks.json").exists()


def test_the_curation_import_snapshot_is_a_decision(tmp_path, moved):
    """The undo file a curation import writes before it changes anything is an owner decision
    that cannot be made again, like the organize undo list: it goes where decisions_path()
    says, beside nothing else."""
    from moonglade import curation_io as cio
    from moonglade.gallery import CATALOG_FIELDS, save_catalog
    db = tmp_path / "catalog.db"
    save_catalog(db, [{f: "" for f in CATALOG_FIELDS} | {
        "media_id": "m1", "filename": "a_m1.png", "created_at": "2025-01-01T00:00:00"}])
    (tmp_path / "_d").mkdir()
    doc = cio.export_curation(db)
    doc["items"] = [{"media_id": "m1", "rating": 3, "collections": [], "tags": [],
                     "mark": "", "note": ""}]
    rep = cio.import_curation(db, doc, apply=True)
    assert rep["snapshot"].startswith(cio.SNAPSHOT_PREFIX)
    assert (tmp_path / "_d" / rep["snapshot"]).is_file()
    assert not list(tmp_path.glob(cio.SNAPSHOT_PREFIX + "*"))


def test_the_reconcile_stamp_follows_records_path(tmp_path, moved):
    (tmp_path / "_r").mkdir()
    core._stamp_reconcile(tmp_path, 1, 0)
    assert (tmp_path / "_r" / "reconcile_stamp.json").is_file()
    assert not (tmp_path / "reconcile_stamp.json").exists()
    assert integrity.reconciled_at(tmp_path)          # and the reader finds it there


def test_the_loom_lives_in_the_app_folder(tmp_path):
    """The Loom's whole folder is under _moonglade/, which every walker prunes -- so its
    frames and cuts are never counted as pictures."""
    assert paths.loom_root(tmp_path) == tmp_path / "_moonglade" / "loom"
    assert paths.LIBRARY_APP_DIRNAME in g.QUARANTINE_EXCLUDE


# ---- the lint: no code builds a record's name off out_dir by hand ----------------------

_RECORD_NAMES = set(RECORD_NAMES) | set(DECISION_NAMES) | set(OLD_LAYOUT_NAMES)


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
    # The move itself is the one module that names an older layout's places.
    exempt = {"moonglade/paths.py", "moonglade/migrate.py"}
    stray = [h for p, t in trees.items() if p.relative_to(_REPO).as_posix() not in exempt
             for h in _hand_built(p, t, consts)]
    assert not stray, ("build a library record's path with moonglade_paths.records_path() / "
                       "decisions_path() / account_dir():\n  " + "\n  ".join(stray))


def test_the_lint_sees_a_hand_built_record():
    """The lint's own bite, on a fixture module: each spelling it must catch."""
    src = ("REPORT = 'audit_report.csv'\n"
           "a = out / 'achievements.json'\n"
           "b = Path(out) / REPORT\n"
           "c = os.path.join(out, 'jobs.jsonl')\n"
           "d = out.joinpath('logs')\n"
           "e = out / 'catalog.db'\n")
    tree = ast.parse(src)
    fake = _REPO / "dev" / "tests" / "_lint_fixture.py"
    consts = _record_constants([tree])

    class _P:
        name = fake.name

        @staticmethod
        def read_text(encoding=None):
            return src
    hits = _hand_built(_P, tree, consts)
    assert [h.split(":")[1].split()[0] for h in hits] == ["2", "3", "4", "5"]
