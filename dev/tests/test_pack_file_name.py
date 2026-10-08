"""The art pack's file name (pack v7): `moonglade.mgpack`, beside the program.

One function names the pack's path, `_container_path()`, and every code path asks it: the
reader, the downloader, the boot check, About and the builder's default output. The version
marker beside the pack is derived from it, so it follows the name. The pack's old name is
named by exactly one line of code, the one-time rename's own constant
(moonglade_assets.LEGACY_NAME): anything else that still spelled it would be reading or
writing a file the app no longer looks at."""
from pathlib import Path

from moonglade import assets as ma
from moonglade import gallery as g
from moonglade import paths as moonglade_paths
from tests.conftest import first_party_sources

_REPO = Path(__file__).resolve().parents[2]

# Spelled in two halves so this file cannot be its own match (tests are not scanned anyway).
_OLD = "moonglade" + ".dat"

# The code: every Python and JavaScript source the app, its tools and its two front ends are
# built from. Not tests/ (fixtures may name anything), not the built bundles (integration
# rebuilds them), not the docs (CHANGELOG history keeps the old name on purpose). The app's
# own modules come from the shared collector: the repo root and the moonglade/ code folder.
_CODE_GLOBS = [
    "dev/tools/**/*.py",
    "gallery/src/**/*.js", "gallery/src/**/*.jsx",
    "loom/src/**/*.js", "loom/src/**/*.jsx", "loom/scripts/*.mjs", "loom/scripts/*.js",
]


def _code_files():
    seen = set(first_party_sources())
    yield from sorted(seen)
    for pat in _CODE_GLOBS:
        for p in _REPO.glob(pat):
            if p.is_file() and p not in seen and "node_modules" not in p.parts:
                seen.add(p)
                yield p


def test_the_pack_is_moonglade_mgpack_beside_the_program():
    p = g._container_path()
    assert p.name == "moonglade.mgpack"
    assert p == moonglade_paths.local_path("moonglade.mgpack")    # a machine file


def test_the_version_marker_follows_the_pack_name():
    assert ma._version_marker_path(g._container_path()).name == "moonglade.mgpack.version"


def test_the_asset_check_asks_about_the_new_name(tmp_path):
    """needs_download keyed on the new name: a pack present only under the old name is not a
    pack (the one-time rename at start is what carries it across)."""
    ma.write_manifest("7", "ab" * 32, 4, ["https://example.invalid/moonglade.mgpack"])
    app = tmp_path / "app"
    app.mkdir()
    (app / _OLD).write_bytes(b"old!")
    assert ma.needs_download(app / "moonglade.mgpack") is True


def test_gitignore_keeps_every_pack_name_and_marker_out():
    lines = {ln.strip() for ln in (_REPO / ".gitignore").read_text(encoding="utf-8").splitlines()}
    for name in ("/moonglade.mgpack", "/moonglade.mgpack.version",
                 "/" + _OLD, "/" + _OLD + ".version"):
        assert name in lines, name + " is not git-ignored"


def test_no_code_path_but_the_rename_names_the_old_file():
    hits = []
    for path in _code_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        if _OLD not in text:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if _OLD in line:
                hits.append((path.relative_to(_REPO).as_posix(), n, line.strip()))
    allowed = [h for h in hits
               if h[0] == "moonglade/assets.py" and h[2].startswith("LEGACY_NAME = ")]
    stray = [h for h in hits if h not in allowed]
    assert not stray, "code still names the old pack file:\n" + "\n".join(
        "  %s:%d  %s" % h for h in stray)
    assert len(allowed) <= 1


def _main_calls():
    """main()'s calls in source order, as (name, node). Read off its source rather than by
    running it: main() parses argv, binds a port and blocks."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(g.main)))
    calls = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
            calls.append((n.lineno, n.col_offset, name, n))
    return [(name, n) for _, _, name, n in sorted(calls, key=lambda c: c[:2])]


def test_a_real_start_renames_an_old_pack_before_anything_reads_it():
    """The rename's only production road is the move every entry point runs first
    (moonglade.setup.prepare -> moonglade.migrate's install half, which renames a pack still
    under its pre-v7 name at the old place, then moves it into local/). In main() it runs
    before anything reads a setting -- the port check included (B2) -- and so before
    create_app(): every check after it (the page's "is my pack current", About, the fetch job
    bound at app build) sees the pack where it now is. A second server refused on a busy port
    moves nothing: the running one's start already finished the move, and the journal says
    so."""
    import inspect

    from moonglade import migrate as mig
    calls = _main_calls()
    names = [c[0] for c in calls]
    assert "prepare" in names, "main() no longer runs the move"
    i = names.index("prepare")
    assert i < names.index("port_owner") < names.index("create_app")
    assert "migrate_legacy_name" in inspect.getsource(mig._install_half)