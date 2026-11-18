"""dev/tools/retarget_patches.py -- the codemod that moves test patches after a split move.

Proven on synthetic fixtures in a tmp folder only: Phase 0 of the 3.21.0 split never runs it
on the real suite (test_module_seams.py runs its scanner there, read-only)."""
import ast
import importlib.util
import io
from pathlib import Path

DEV = Path(__file__).resolve().parents[1]
_TOOL = DEV / "tools" / "retarget_patches.py"
_spec = importlib.util.spec_from_file_location("retarget_patches", _TOOL)
rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rp)

SEAMS = {"moonglade.scan": {"from": "moonglade.gallery", "names": ["scan_library"]}}

BEFORE = '''\
"""Doc."""
from moonglade import gallery as gg


def test_a(monkeypatch):
    s = "café"; monkeypatch.setattr(gg, "scan_library", None)
    monkeypatch.setattr(gg, "load_catalog", None)
    monkeypatch.setattr("moonglade.gallery.scan_library", None)
    gg.scan_library = 1


def test_b(monkeypatch, gg):
    monkeypatch.setattr(gg, "scan_library", None)
'''

AFTER = '''\
"""Doc."""
from moonglade import gallery as gg
from moonglade import scan as scan_mod


def test_a(monkeypatch):
    s = "café"; monkeypatch.setattr(scan_mod, "scan_library", None)
    monkeypatch.setattr(gg, "load_catalog", None)
    monkeypatch.setattr("moonglade.scan.scan_library", None)
    scan_mod.scan_library = 1


def test_b(monkeypatch, gg):
    monkeypatch.setattr(gg, "scan_library", None)
'''

DRY_LINES = [
    "test_synth.py:6 gg.scan_library -> scan_mod.scan_library",
    'test_synth.py:8 "moonglade.gallery.scan_library" -> "moonglade.scan.scan_library"',
    "test_synth.py:9 gg.scan_library -> scan_mod.scan_library",
    "test_synth.py:13 UNRESOLVED setattr of 'scan_library' on a receiver that does not resolve "
    "to a module (unknown): check by hand",
    "3 site(s) to change, 1 unresolved",
]


def _fixture(tmp_path, text=BEFORE, name="test_synth.py", newline="\n"):
    tests = tmp_path / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    path = tests / name
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))
    return tests, path


def _run(tests, apply, seams=SEAMS, aliases=None):
    out = io.StringIO()
    counts = rp.run(seams, tests, apply=apply, aliases=aliases, out=out)
    return counts, out.getvalue().splitlines()


def test_load_seams_reads_the_literal_without_importing(tmp_path):
    src = tmp_path / "seams_holder.py"
    src.write_text("import a_module_that_does_not_exist\n"
                   "SEAMS = {'moonglade.scan': {'from': 'moonglade.gallery', "
                   "'names': ['scan_library']}}\n", encoding="utf-8")
    assert rp.load_seams(src) == SEAMS
    real = rp.load_seams(DEV / "tests" / "test_module_seams.py")
    assert isinstance(real, dict) and all(set(e) == {"from", "names"} for e in real.values())


def test_dry_run_prints_every_site_and_writes_nothing(tmp_path):
    tests, path = _fixture(tmp_path)
    counts, lines = _run(tests, apply=False)
    assert counts == (3, 1)
    assert lines == DRY_LINES
    assert path.read_text(encoding="utf-8") == BEFORE


def test_apply_rewrites_the_sites_and_adds_the_import(tmp_path):
    tests, path = _fixture(tmp_path)
    counts, lines = _run(tests, apply=True)
    assert counts == (3, 1)
    assert lines[-1] == "3 site(s) rewritten, 1 unresolved"
    after = path.read_text(encoding="utf-8")
    assert after == AFTER
    ast.parse(after)
    # idempotent: nothing left to move, the unresolved site is still only reported
    assert _run(tests, apply=False)[0] == (0, 1)


def test_apply_keeps_crlf_and_reuses_an_existing_alias(tmp_path):
    text = BEFORE.replace("from moonglade import gallery as gg\n",
                          "from moonglade import gallery as gg\nfrom moonglade import scan as sc\n")
    tests, path = _fixture(tmp_path, text=text, newline="\r\n")
    _run(tests, apply=True)
    raw = path.read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    after = raw.decode("utf-8")
    assert "monkeypatch.setattr(sc, \"scan_library\", None)" in after
    assert "sc.scan_library = 1" in after
    assert "scan_mod" not in after                      # no second import of the same module


def test_an_alias_name_already_in_use_is_reported_not_guessed(tmp_path):
    text = BEFORE + "\n\ndef scan_mod():\n    pass\n"
    tests, path = _fixture(tmp_path, text=text)
    counts, lines = _run(tests, apply=True)
    assert any("alias 'scan_mod' for moonglade.scan is already a name" in ln for ln in lines)
    after = path.read_text(encoding="utf-8")
    assert "monkeypatch.setattr(gg, \"scan_library\", None)" in after.splitlines()[5]
    # a chosen alias goes through
    tests2, path2 = _fixture(tmp_path / "two", text=text)
    _run(tests2, apply=True, aliases={"moonglade.scan": "scan_seam"})
    assert "scan_seam.scan_library = 1" in path2.read_text(encoding="utf-8")


def test_patch_forms_and_aliases_are_all_rewritten(tmp_path):
    text = '''\
import importlib
from unittest import mock
from unittest.mock import patch

import moonglade.gallery

G = importlib.import_module("moonglade.gallery")


@mock.patch("moonglade.gallery.scan_library")
def test_x(m):
    from moonglade import gallery as local_g
    with patch.object(local_g, "scan_library"):
        pass
    moonglade.gallery.scan_library = None
    setattr(G, "scan_library", None)
    del G.scan_library
'''
    tests, path = _fixture(tmp_path, text=text)
    counts, _ = _run(tests, apply=True)
    assert counts == (5, 0)
    after = path.read_text(encoding="utf-8")
    ast.parse(after)
    for want in ('@mock.patch("moonglade.scan.scan_library")',
                 'with patch.object(scan_mod, "scan_library"):',
                 "scan_mod.scan_library = None",
                 'setattr(scan_mod, "scan_library", None)',
                 "del scan_mod.scan_library",
                 "import moonglade.gallery\nfrom moonglade import scan as scan_mod\n"):
        assert want in after, want


def test_main_exit_code_and_flags(tmp_path, capsys):
    tests, path = _fixture(tmp_path)
    seams_file = tmp_path / "seams.py"
    seams_file.write_text("SEAMS = %r\n" % (SEAMS,), encoding="utf-8")
    argv = ["--seams", str(seams_file), "--tests", str(tests)]
    assert rp.main(argv) == 1                              # one unresolved site
    assert path.read_text(encoding="utf-8") == BEFORE      # dry run is the default
    assert capsys.readouterr().out.splitlines() == DRY_LINES
    clean = BEFORE.split("\n\ndef test_b")[0] + "\n"
    path.write_text(clean, encoding="utf-8")
    assert rp.main(argv + ["--apply", "--alias", "moonglade.scan=scan_x"]) == 0
    assert "scan_x.scan_library = 1" in path.read_text(encoding="utf-8")


def test_a_loop_over_literal_names_is_checked_against_them(tmp_path):
    """`for name in ("a", "b"): setattr(core, name, ...)` names its targets in the loop: it is
    reported only when one of them moved, and a name the loop cannot pin stays a question."""
    text = '''\
from moonglade import gallery as gg


def test_loops(monkeypatch, names):
    for name in ("load_catalog", "save_catalog"):
        monkeypatch.setattr(gg, name, None)
    for name in ["load_catalog", "scan_library"]:
        monkeypatch.setattr(gg, name, None)
    for name in names:
        monkeypatch.setattr(gg, name, None)
'''
    edits, unresolved, _ = rp.plan_file("test_loops.py", text, SEAMS)
    assert edits == []
    assert [line for line, _ in unresolved] == [8, 10], unresolved
    assert "includes moved scan_library" in unresolved[0][1]
    assert "computed name: check by hand" in unresolved[1][1]
    edits, unresolved, _ = rp.plan_file("test_loops.py", text, {})
    assert (edits, unresolved) == ([], [])
