"""Guard rails for splitting the two megamodules (3.21.0, item 9 of the library-cluster scope).

`moonglade/backup.py` and `moonglade/gallery.py` are being lifted apart seam by seam, verbatim.
One map drives every check here: SEAMS, new module -> the old module it came from and the names
it now owns. Phase 0 moves nothing, so the map is EMPTY and every check passes trivially; each
check is proven to fire by a synthetic case further down. A move adds one entry to SEAMS (and
runs `py dev/tools/retarget_patches.py` to move the patches with it).

What a move must satisfy:
  1. Every mapped name is DEFINED in the new module (not just imported there).
  2. The old module does NOT re-export a moved name. The one exception: a name some other
     PRODUCTION module (moonglade/*.py, the launcher) reaches through the old module -- that
     re-export must be the identical object (`is`). Why so strict: without a re-export, a stale
     `monkeypatch.setattr(core, "name", ...)` raises AttributeError at once; with one, it
     silently patches a binding nobody calls. So the old module reaches a moved name as
     `_newmod.name`, never through `from moonglade.newmod import name`.
  3. A new module imports moonglade.backup / moonglade.gallery only INSIDE functions (the
     existing lazy idiom), never at import time, so no import cycle can form.
  4. THE PATCH-TARGET LINT: no file under dev/tests patches a moved name through its old module
     (setattr / delattr / mock.patch / patch.object / plain `alias.name = ...`), and no patch of
     a moved name sits on a receiver the scanner cannot resolve. The scanner lives in
     dev/tools/retarget_patches.py so the lint and the codemod can never disagree.
  5. The tests that read a megamodule's SOURCE (inspect.getsource, opening the file by path,
     AST walks of create_app) are a known set, SOURCE_READERS. A move that touches what one of
     them reads must be acknowledged in SOURCE_READERS_REVIEWED after someone looked.

SEAMS must stay a plain literal: the codemod reads it with ast.literal_eval, without importing
this file.
"""
import ast
import importlib
import importlib.util
import inspect
import re
import types
from pathlib import Path

import pytest

DEV = Path(__file__).resolve().parents[1]
REPO = DEV.parent

_TOOL = DEV / "tools" / "retarget_patches.py"
_spec = importlib.util.spec_from_file_location("retarget_patches", _TOOL)
rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rp)

OLD_MODULES = rp.OLD_MODULES

# new module -> {"from": old module, "names": [names it owns]}. EMPTY in Phase 0.
SEAMS = {}

# Every file under dev/ (the suite and the tools) that reads an old module's source, and which
# old module(s). Kept exact: a new reader, or one that stops reading, fails
# test_source_readers_are_the_known_set.
SOURCE_READERS = {
    "tests/test_app_paths.py": ("moonglade.gallery",),
    "tests/test_artworks_adhoc.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_bonjour.py": ("moonglade.gallery",),
    "tests/test_branding.py": ("moonglade.gallery",),
    "tests/test_branding_tree_rules.py": ("moonglade.gallery",),
    "tests/test_catalog_verbs.py": ("moonglade.gallery",),
    "tests/test_catchup_query.py": ("moonglade.gallery",),
    "tests/test_cli_doc_coverage.py": ("moonglade.backup",),
    "tests/test_community_surface.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_config_path_routing.py": ("moonglade.backup",),
    "tests/test_contest_wins.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_csrf_coverage.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_delete_routing.py": ("moonglade.backup",),
    "tests/test_design_kit_sync.py": ("moonglade.gallery",),
    "tests/test_doc_truth_residuals.py": ("moonglade.gallery",),
    "tests/test_edit_upload.py": ("moonglade.backup",),
    "tests/test_enhance.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_evidence_counters.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_first_party_sources.py": ("moonglade.gallery",),
    "tests/test_gen_surface.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_history_feed_document.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_jwt.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_library_dir.py": ("moonglade.gallery",),
    "tests/test_living_library.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_logging.py": ("moonglade.gallery",),
    "tests/test_loom_generate_guard.py": ("moonglade.gallery",),
    "tests/test_loom_notify.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_loom_p_routes.py": ("moonglade.gallery",),
    "tests/test_media_tools.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_move_edges.py": ("moonglade.gallery",),
    "tests/test_network.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_outside_notice.py": ("moonglade.gallery",),
    "tests/test_pack_file_name.py": ("moonglade.gallery",),
    "tests/test_pack_file_type.py": ("moonglade.gallery",),
    "tests/test_panel.py": ("moonglade.gallery",),
    "tests/test_pixai_client.py": ("moonglade.backup",),
    "tests/test_read_only.py": ("moonglade.backup",),
    "tests/test_rest_delete_and_renewal.py": ("moonglade.gallery",),
    "tests/test_server_stop_record.py": ("moonglade.gallery",),
    "tests/test_settings_store.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_setup_prepare.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_spend_no_retry.py": ("moonglade.backup",),
    "tests/test_task_model_detail_document.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_telemetry.py": ("moonglade.gallery",),
    "tests/test_training_advanced.py": ("moonglade.backup",),
    "tests/test_training_parity.py": ("moonglade.backup",),
    "tests/test_tsubaki3_image_gate.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_updater.py": ("moonglade.gallery",),
    "tests/test_video_tsubaki.py": ("moonglade.backup",),
    "tests/test_watch.py": ("moonglade.gallery",),
    "tests/test_web_auth.py": ("moonglade.backup",),
    "tools/export_design_kit.py": ("moonglade.gallery",),     # reads DESIGN_TOKENS_CSS by path
}

# (reader file, new module) pairs someone has checked after a move touched what the reader
# reads (see check_source_readers_reviewed). Empty while SEAMS is.
SOURCE_READERS_REVIEWED = set()


def production_files():
    """The modules whose imports from an old module justify a re-export."""
    files = sorted((REPO / "moonglade").glob("*.py"))
    return files + [REPO / "Moonglade Launcher.pyw"]


def module_file(modname):
    return REPO / Path(*modname.split(".")).with_suffix(".py")


# ---------------------------------------------------------------------------------------------
# The checks. Each returns a list of problems (empty = fine) and takes its world as arguments,
# so the synthetic cases below can prove it fires.
# ---------------------------------------------------------------------------------------------

def _top_level_defines(source):
    """Names a module's source DEFINES at the top level (def, class, assignment), not imports."""
    names = set()
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                for sub in ast.walk(t):
                    if isinstance(sub, ast.Name):
                        names.add(sub.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def check_defined_in(seams, load, source_of):
    problems = []
    for new_mod, entry in seams.items():
        try:
            mod = load(new_mod)
        except ImportError as exc:
            problems.append("%s does not import: %s" % (new_mod, exc))
            continue
        defined = _top_level_defines(source_of(new_mod))
        for name in entry["names"]:
            if not hasattr(mod, name):
                problems.append("%s.%s does not exist" % (new_mod, name))
                continue
            obj = getattr(mod, name)
            if (inspect.isfunction(obj) or inspect.isclass(obj)) and obj.__module__ != new_mod:
                problems.append("%s.%s is defined in %s" % (new_mod, name, obj.__module__))
            elif name not in defined:
                problems.append("%s.%s is imported there, not defined" % (new_mod, name))
    return problems


def check_reexports(seams, load, production_refs):
    """production_refs: {(old_module, name)} that production code reaches through old_module."""
    problems = []
    for new_mod, entry in seams.items():
        old_name = entry["from"]
        old, new = load(old_name), load(new_mod)
        for name in entry["names"]:
            wanted = (old_name, name) in production_refs
            if hasattr(old, name):
                if not wanted:
                    problems.append("%s re-exports %s, which moved to %s and no production "
                                    "module imports from %s" % (old_name, name, new_mod, old_name))
                elif hasattr(new, name) and getattr(old, name) is not getattr(new, name):
                    problems.append("%s.%s is not the identical object as %s.%s"
                                    % (old_name, name, new_mod, name))
            elif wanted:
                problems.append("production code reaches %s.%s, which moved to %s: re-export it "
                                "or retarget the importer" % (old_name, name, new_mod))
    return problems


def _import_time_imports(tree):
    """Import nodes (and import_module calls) that run when the module is imported: everything
    outside a def/lambda body (class bodies, if/try blocks at top level DO run)."""
    stack = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            stack.extend(node.decorator_list)
            stack.extend(node.args.defaults)
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
        elif isinstance(node, ast.Call) and rp._import_module_target(node):
            yield node
        stack.extend(ast.iter_child_nodes(node))


def _imported_modules(node, package="moonglade"):
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    if isinstance(node, ast.ImportFrom):
        base = node.module or ""
        if node.level:
            base = package + ("." + base if base else "")
        return [base] + [base + "." + a.name for a in node.names]
    return [rp._import_module_target(node)]


def check_lazy_imports(seams, source_of):
    problems = []
    old_set = set(OLD_MODULES) | {e["from"] for e in seams.values()}
    for new_mod in seams:
        tree = ast.parse(source_of(new_mod))
        for node in _import_time_imports(tree):
            hit = sorted(set(_imported_modules(node)) & old_set)
            if hit:
                problems.append("%s line %d imports %s at import time; import it inside the "
                                "function that needs it" % (new_mod, node.lineno, hit[0]))
    return problems


def lint_patches(seams, files):
    """files: {path: text}. -> (stale, unresolved) as 'path:line ...' strings."""
    stale, unresolved = [], []
    for path, text in sorted(files.items()):
        edits, unres, _ = rp.plan_file(path, text, seams)
        stale += ["%s:%d %s (moved to %s)" % (path, e.site.line, e.old_target, e.new_module)
                  for e in edits]
        unresolved += ["%s:%d %s" % (path, line, msg) for line, msg in unres]
    return stale, unresolved


def detect_source_readers(files):
    """{path: text} -> {path: (old modules whose source it reads)}."""
    out = {}
    for path, text in files.items():
        scan = rp.scan_text(path, text)
        if scan.reads_source:
            out[path] = tuple(sorted(scan.reads_source))
    return out


def check_source_readers_reviewed(seams, files, readers, reviewed):
    """A reader of a seam's old module is TOUCHED by the move if it reads the old module whole
    (its text, getsource(module), something untraceable) or names one of the moved symbols."""
    problems = []
    for new_mod, entry in seams.items():
        words = re.compile(r"\b(%s)\b" % "|".join(map(re.escape, entry["names"])))
        for path, mods in sorted(readers.items()):
            if entry["from"] not in mods or (path, new_mod) in reviewed:
                continue
            kind = rp.scan_text(path, files[path]).reads_source.get(entry["from"])
            if kind in ("whole", "indirect") or words.search(files[path]):
                problems.append("%s reads %s's source and the move to %s touches it: check what "
                                "it reads, then add (%r, %r) to SOURCE_READERS_REVIEWED"
                                % (path, entry["from"], new_mod, path, new_mod))
    return problems


# ---------------------------------------------------------------------------------------------
# The real tree
# ---------------------------------------------------------------------------------------------

def _source_of(modname):
    return module_file(modname).read_text(encoding="utf-8")


def _test_files(folder="tests"):
    root = DEV / folder if folder else DEV
    return {p.relative_to(DEV).as_posix(): p.read_text(encoding="utf-8")
            for p in rp.iter_test_files(root)}


def _production_refs():
    refs = set()
    for p in production_files():
        own = "moonglade." + p.stem
        refs |= {r for r in rp.scan_references(p.read_text(encoding="utf-8")) if r[0] != own}
    return refs


def test_seams_map_is_one_readable_literal():
    assert rp.load_seams(Path(__file__)) == SEAMS
    owners = {}
    for new_mod, entry in SEAMS.items():
        assert set(entry) == {"from", "names"}, new_mod
        assert entry["from"] in OLD_MODULES, new_mod
        assert new_mod.startswith("moonglade.") and new_mod not in OLD_MODULES, new_mod
        for name in entry["names"]:
            assert (entry["from"], name) not in owners, (name, owners.get((entry["from"], name)))
            owners[(entry["from"], name)] = new_mod


def test_every_mapped_symbol_is_defined_in_its_new_module():
    assert check_defined_in(SEAMS, importlib.import_module, _source_of) == []


def test_old_modules_reexport_only_what_production_imports():
    assert check_reexports(SEAMS, importlib.import_module, _production_refs()) == []


def test_new_modules_import_the_old_ones_lazily():
    assert check_lazy_imports(SEAMS, _source_of) == []


def test_no_test_patches_a_moved_name_through_its_old_module():
    stale, unresolved = lint_patches(SEAMS, _test_files())
    assert stale == [], ("patches still aimed at the old module -- run "
                         "`py dev/tools/retarget_patches.py`:\n" + "\n".join(stale))
    assert unresolved == [], "patches of moved names to check by hand:\n" + "\n".join(unresolved)


def test_the_scanner_sees_the_suites_patches():
    """The lint is only as good as its scanner: it must keep finding the suite's patches through
    its usual aliases (a scanner that silently finds nothing passes every move)."""
    scans = rp.scan_tree(DEV / "tests")
    assert not [s.path for s in scans if s.error]
    aliases = {(name, mod) for s in scans for name, mod in s.aliases}
    for pair in [("core", "moonglade.backup"), ("g", "moonglade.gallery")]:
        assert pair in aliases
    by_mod = {m: sum(1 for s in scans for x in s.sites if x.module == m) for m in OLD_MODULES}
    assert all(by_mod.values()), by_mod


def test_source_readers_are_the_known_set():
    assert detect_source_readers(_test_files(folder=None)) == SOURCE_READERS


def test_source_readers_touched_by_a_move_were_reviewed():
    files = _test_files(folder=None)
    assert check_source_readers_reviewed(SEAMS, files, SOURCE_READERS,
                                         SOURCE_READERS_REVIEWED) == []


# ---------------------------------------------------------------------------------------------
# Each check fires: synthetic worlds
# ---------------------------------------------------------------------------------------------

def _module(name, source):
    mod = types.ModuleType(name)
    exec(compile(source, name, "exec"), mod.__dict__)
    return mod


@pytest.fixture
def world():
    """A fake old module and a fake new one: `moved` lives in new; `copied` was copied, not
    moved; `imported` is only imported into new; `kept` stayed home."""
    old_src = "def kept():\n    pass\n\ndef copied():\n    pass\n"
    new_src = ("def moved():\n    pass\n\ndef copied():\n    pass\n\n"
               "LIMIT = 3\n")
    old = _module("fake.old", old_src)
    new = _module("fake.new", new_src)
    new.imported = old.kept                    # `from fake.old import kept as imported`
    new_src += "from fake.old import kept as imported\n"
    mods = {"fake.old": old, "fake.new": new}
    sources = {"fake.old": old_src, "fake.new": new_src}
    return mods, sources


def test_defined_in_check_fires(world):
    mods, sources = world
    ok = {"fake.new": {"from": "fake.old", "names": ["moved", "LIMIT"]}}
    assert check_defined_in(ok, mods.__getitem__, sources.__getitem__) == []
    bad = {"fake.new": {"from": "fake.old", "names": ["imported", "missing"]}}
    problems = check_defined_in(bad, mods.__getitem__, sources.__getitem__)
    assert any("fake.new.imported is defined in fake.old" in p for p in problems), problems
    assert any("fake.new.missing does not exist" in p for p in problems), problems
    # a constant can only be checked by source: imported there, not defined
    mods["fake.new"].ALIAS_CONST = 5
    bad = {"fake.new": {"from": "fake.old", "names": ["ALIAS_CONST"]}}
    assert check_defined_in(bad, mods.__getitem__, sources.__getitem__) == [
        "fake.new.ALIAS_CONST is imported there, not defined"]
    gone = {"fake.nowhere": {"from": "fake.old", "names": ["x"]}}

    def load(name):
        raise ImportError(name)
    assert "does not import" in check_defined_in(gone, load, sources.__getitem__)[0]


def test_reexport_check_fires(world):
    mods, _ = world
    load = mods.__getitem__
    seams = {"fake.new": {"from": "fake.old", "names": ["moved"]}}
    assert check_reexports(seams, load, set()) == []                       # moved cleanly
    # an internal re-export: the old module still answers to the moved name
    mods["fake.old"].moved = mods["fake.new"].moved
    assert "re-exports moved" in check_reexports(seams, load, set())[0]
    # ... allowed when production imports it from there, and it is the same object
    assert check_reexports(seams, load, {("fake.old", "moved")}) == []
    # ... but not when it is a different object (a copy left behind)
    seams = {"fake.new": {"from": "fake.old", "names": ["copied"]}}
    assert "not the identical object" in check_reexports(seams, load, {("fake.old", "copied")})[0]
    # production still reaches the old home of a name nobody re-exported
    seams = {"fake.new": {"from": "fake.old", "names": ["LIMIT"]}}
    assert "retarget the importer" in check_reexports(seams, load, {("fake.old", "LIMIT")})[0]


def test_lazy_import_check_fires():
    seams = {"moonglade.fake_seam": {"from": "moonglade.gallery", "names": ["x"]}}
    lazy = ("import os\n\ndef x():\n    from moonglade import gallery as g\n"
            "    import moonglade.backup\n    return g\n")
    assert check_lazy_imports(seams, lambda _: lazy) == []
    for eager in ("from moonglade import gallery as g\n",
                  "import moonglade.backup as core\n",
                  "from moonglade.gallery import scan_library\n",
                  "from . import backup\n",
                  "try:\n    from moonglade import backup\nexcept ImportError:\n    pass\n",
                  "class C:\n    from moonglade import gallery\n",
                  "import importlib\ncore = importlib.import_module('moonglade.backup')\n"):
        problems = check_lazy_imports(seams, lambda _, s=eager: s)
        assert problems and "at import time" in problems[0], eager


SYNTH_SEAMS = {"moonglade.fake_seam": {"from": "moonglade.gallery",
                                       "names": ["scan_library", "Walker"]}}

SYNTH_TEST = '''\
import importlib
from unittest import mock
from unittest.mock import patch

import moonglade.gallery
from moonglade import gallery as gg
from moonglade import backup as core

g2 = gg
mg = importlib.import_module("moonglade.gallery")


def test_a(monkeypatch):
    monkeypatch.setattr(gg, "scan_library", lambda *a: [])            # line 14: stale
    monkeypatch.setattr(gg, "load_catalog", lambda *a: [])            # not moved
    monkeypatch.setattr(core, "scan_library", lambda *a: [])          # other module: not moved
    monkeypatch.setattr("moonglade.gallery.scan_library", None)       # line 17: stale string
    gg.scan_library = None                                            # line 18: stale assign
    monkeypatch.setattr(gg.Walker, "walk", None)                      # line 19: stale receiver


@mock.patch("moonglade.gallery.scan_library")                         # line 22: stale decorator
def test_b(m):
    with patch.object(g2, "scan_library"):                            # line 24: stale via copy
        pass
    moonglade.gallery.scan_library = None                             # line 26: dotted import
    mg.Walker.depth = 3                                               # line 27: import_module


def test_c(monkeypatch):
    from moonglade import gallery as local_g
    monkeypatch.setattr(local_g, "scan_library", None)                # line 32: local alias


def test_d(monkeypatch, gg):
    monkeypatch.setattr(gg, "scan_library", None)                     # line 36: shadowed, unresolved
    setattr(core, name_of(), None)                                    # computed name, other module
    setattr(mg, name_of(), None)                                      # line 38: computed, unresolved
'''


def test_patch_lint_passes_an_empty_map_and_flags_a_synthetic_move():
    files = {"tests/test_synth.py": SYNTH_TEST}
    assert lint_patches({}, files) == ([], [])
    stale, unresolved = lint_patches(SYNTH_SEAMS, files)
    lines = sorted(int(s.split(":")[1].split()[0]) for s in stale)
    assert lines == [14, 17, 18, 19, 22, 24, 26, 27, 32], stale
    assert sorted(int(u.split(":")[1].split()[0]) for u in unresolved) == [36, 38], unresolved
    assert any("gg.scan_library (moved to moonglade.fake_seam)" in s for s in stale)
    assert any('"moonglade.gallery.scan_library"' in s for s in stale)


def test_patch_lint_on_the_real_suite_flags_a_synthetic_move():
    """Against today's suite: a pretend move of a heavily patched name lights the lint up."""
    files = _test_files()
    stale, _ = lint_patches({"moonglade.fake_seam": {"from": "moonglade.backup",
                                                     "names": ["_make_session"]}}, files)
    assert len(stale) > 10


def test_scan_references_sees_production_reach():
    src = ("from moonglade.gallery import (a, b)\n"
           "from moonglade import backup as core\n"
           "def f():\n    from moonglade import gallery as _mg\n"
           "    return core.c() + _mg.d + getattr(core, 'e')\n")
    assert rp.scan_references(src) == {("moonglade.gallery", "a"), ("moonglade.gallery", "b"),
                                       ("moonglade.backup", "c"), ("moonglade.gallery", "d"),
                                       ("moonglade.backup", "e")}


def test_source_reader_detection_and_review_fire():
    files = {
        "tests/test_getsource.py": ("import inspect\nfrom moonglade import gallery as g\n"
                                    "def test():\n    inspect.getsource(g.scan_library)\n"),
        "tests/test_whole.py": ("import inspect\nfrom moonglade import backup as core\n"
                                "def test():\n    inspect.getsource(core)\n"),
        "tests/test_by_path.py": ("from pathlib import Path\nROOT = Path('.')\n"
                                  "def test():\n    (ROOT / 'moonglade' / 'gallery.py').read_text()\n"),
        "tests/test_create_app.py": ("import ast, inspect, textwrap\n"
                                     "from moonglade import gallery as G\n"
                                     "def test():\n    ast.parse(textwrap.dedent("
                                     "inspect.getsource(G.create_app)))\n"),
        "tests/test_argv_only.py": ("import sys\ndef test(monkeypatch):\n"
                                    "    monkeypatch.setattr(sys, 'argv', ['moonglade/backup.py'])\n"),
        "tests/test_plain.py": "from moonglade import gallery as g\ndef test():\n    g.x()\n",
    }
    readers = detect_source_readers(files)
    assert readers == {"tests/test_getsource.py": ("moonglade.gallery",),
                       "tests/test_whole.py": ("moonglade.backup",),
                       "tests/test_by_path.py": ("moonglade.gallery",),
                       "tests/test_create_app.py": ("moonglade.gallery",)}
    problems = check_source_readers_reviewed(SYNTH_SEAMS, files, readers, set())
    touched = sorted(p.split()[0] for p in problems)
    # names scan_library / whole file by path; the create_app reader names neither
    assert touched == ["tests/test_by_path.py", "tests/test_getsource.py"], problems
    reviewed = {("tests/test_by_path.py", "moonglade.fake_seam"),
                ("tests/test_getsource.py", "moonglade.fake_seam")}
    assert check_source_readers_reviewed(SYNTH_SEAMS, files, readers, reviewed) == []
