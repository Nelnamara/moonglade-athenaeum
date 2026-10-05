"""The one collector of the app's own code: tests/conftest.py::first_party_sources().

The spoiler guard, the pack-name guard and the path lints all read the app's modules. They
used to glob the repo root flat, so once the code moves into a `moonglade/` folder they would
have kept passing while reading nothing. They share this collector now, which looks at the
root AND inside `moonglade/`; this file holds that it finds every module there is, that it
never wanders into tests/ or node_modules/, and that each guard really uses it.
"""
from tests.conftest import CODE_PACKAGE, REPO_ROOT, first_party_sources

# Every first-party module today. The move into moonglade/ renames them, and this list moves
# with them -- which is the point: a collector that stops finding the code fails HERE, instead
# of every guard that trusts it passing over nothing.
_TODAY = (
    "Serve Gallery.pyw",
    "moonglade_assets.py", "moonglade_backup.py", "moonglade_bonjour.py",
    "moonglade_container.py", "moonglade_contest_wins.py", "moonglade_curation_io.py",
    "moonglade_gallery.py", "moonglade_inbox.py", "moonglade_integrity.py",
    "moonglade_logging.py", "moonglade_mcp.py", "moonglade_narrator.py",
    "moonglade_paths.py", "moonglade_recipes.py", "moonglade_runs.py",
    "moonglade_similar.py",
)


def test_it_finds_every_module_there_is_today():
    names = {p.name for p in first_party_sources()}
    missing = [n for n in _TODAY if n not in names]
    assert not missing, "the collector no longer finds: " + ", ".join(missing)


def test_it_finds_only_the_app():
    for p in first_party_sources():
        parts = p.relative_to(REPO_ROOT).parts
        assert len(parts) == 1 or parts[0] == CODE_PACKAGE, p
        assert not {"tests", "node_modules", ".git", "__pycache__"} & set(parts), p


def test_it_looks_inside_a_code_folder(tmp_path):
    def touch(rel):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x = 1\n", encoding="utf-8")

    for rel in ("a.py", "launcher.pyw", "notes.md",
                "moonglade/__init__.py", "moonglade/gallery.py", "moonglade/server/routes.py",
                "moonglade/__pycache__/gallery.cpython-314.py",
                "moonglade/node_modules/dep.py", "moonglade/tests/test_x.py",
                "tests/test_y.py", "tools/build.py", "node_modules/z.py", ".git/hooks/h.py"):
        touch(rel)
    got = [p.relative_to(tmp_path).as_posix() for p in first_party_sources(tmp_path)]
    assert got == ["a.py", "launcher.pyw",
                   "moonglade/__init__.py", "moonglade/gallery.py", "moonglade/server/routes.py"]


def test_without_a_code_folder_it_is_the_root_alone(tmp_path):
    (tmp_path / "a.py").write_text("", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("", encoding="utf-8")
    assert first_party_sources(tmp_path) == [tmp_path / "a.py"]


# Each guard that reads the app's code, and the flat root globs it must no longer use.
_GUARDS = ("test_no_spoiler_leak.py", "test_moment_serve.py", "test_pack_file_name.py",
           "test_app_paths.py", "test_config_path_routing.py", "test_state_paths.py")
_FLAT_GLOBS = ('_REPO.glob("*.py")', '_REPO.glob("*.pyw")', '"moonglade_*.py"',
               '"*.py", "*.pyw"')


def test_every_code_guard_uses_the_collector():
    for name in _GUARDS:
        src = (REPO_ROOT / "tests" / name).read_text(encoding="utf-8")
        assert "first_party_sources(" in src, name + " does not use the shared collector"
        flat = [g for g in _FLAT_GLOBS if g in src]
        assert not flat, "%s still globs the root flat: %s" % (name, flat)
