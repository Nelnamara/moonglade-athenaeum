"""One check, deliberately narrow (same spirit as test_docs_dont_hardcode_counts.py): every
top-level dependency a shipped module imports unconditionally must be declared in
requirements.txt, or a clean install on a machine that doesn't already have it transitively
via some other package can break. AUDIT_2026-07-21.md `state-owner-defects`: numpy is
imported at module scope by moonglade_similar.py (`import numpy as np`, used unconditionally,
not lazily like torch/transformers/pixeltable) but was never listed. This does not check
every import in the repo -- only the one the audit named -- to avoid growing into a linter.

requirements.txt is what the launcher offers to install on a first start (moonglade/deps.py,
issue #87), so it holds only what the app needs at run time; the test tools are in
requirements-dev.txt, which brings requirements.txt in with a `-r` line."""
from pathlib import Path

from moonglade import deps

_REPO = Path(__file__).resolve().parents[2]

_TEST_TOOLS = {"pytest", "pytest-mock", "pytest-cov", "pytest-xdist"}


def _declared_packages():
    """Package names declared in requirements.txt, stripped of version pins / environment
    markers / inline comments -- matches the file's own unpinned, bare-name convention."""
    return {name.lower() for name in deps.requirements(_REPO / "requirements.txt")}


def test_numpy_is_a_declared_dependency():
    """moonglade_similar.py imports numpy unconditionally at module scope -- it must be
    declared in requirements.txt, not left to arrive as some other package's transitive
    pull (which a clean install cannot rely on)."""
    assert "numpy" in _declared_packages(), (
        "moonglade_similar.py does `import numpy as np` at module scope, but 'numpy' is "
        "missing from requirements.txt -- add it so a clean install doesn't silently "
        "depend on another package pulling it in transitively.")


def test_flask_is_a_declared_dependency():
    """The gallery server needs flask to start at all (issue #87: a first start died with
    'Flask is required for the gallery server'), so the launcher's check must see it."""
    assert "flask" in _declared_packages()


def test_the_test_tools_are_not_run_time_requirements():
    """requirements.txt is installed on a person's machine by the launcher and by the update;
    pytest and its plugins belong to requirements-dev.txt."""
    leaked = _TEST_TOOLS & _declared_packages()
    assert not leaked, "test tools in requirements.txt (move them to requirements-dev.txt): " \
        + ", ".join(sorted(leaked))


def test_the_dev_requirements_bring_in_the_run_time_ones_and_add_the_test_tools():
    path = _REPO / "requirements-dev.txt"
    lines = [ln.split("#", 1)[0].strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    lines = [ln for ln in lines if ln]
    assert lines[0] == "-r requirements.txt", "requirements-dev.txt must start by including it"
    assert _TEST_TOOLS <= {name.lower() for name in deps.requirements(path)}
