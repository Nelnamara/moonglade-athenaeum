"""The session-wide fixture hermeticity invariant, asserted where it cannot be gated away.

`tests/conftest.py` pins `branding_root()` for the whole SESSION so that a fixture of any
scope -- including a module-scoped one, which pytest sets up BEFORE the function-scoped
autouse isolation -- lands in a tmp dir instead of the checkout's own coded tree and the
real pack beside it (2026-09-10: the render harness's server read whatever `moonglade.dat`
happened to sit next to the checkout, so its achievement state was a property of the
machine, full roster on a dev box and empty on CI).

This file exists SEPARATELY from tests/test_render_harness.py, where this test first lived,
and the separation is the whole point. Over there it sat under a module-level
`pytest.importorskip("playwright.sync_api")` and a `pytestmark = pytest.mark.render` --
so on a checkout without playwright, or under the `-m "not render"` invocation pytest.ini
itself advertises, the only assertion pinning a conftest-level, suite-wide invariant was
silently absent, and deleting the session pin would have produced a green run. The check
needs no browser and no server: it resolves two paths. It belongs where every run sees it.

`_real_coded_tree_untouched` (conftest) remains the backstop for WRITES. It cannot see a
read -- on a checkout that already holds the discovery folders an un-pinned `create_app()`
writes nothing new -- which is why the prevention below is the thing that has to hold.

Three invariants live here, and they are different claims. One: no module-scoped fixture can
reach the real tree or the real pack (the session pin holds). Two: each harness server
fixture that needs to pin and seed for ITSELF still does -- which the session pin now masks,
since a harness that lost its pin would land in the session's tmp root and look fine. Three:
no harness server takes an achievement mark from the wall clock; every one of them settles
that mark in its own ledger first. The first is measured live; the other two are read off
the harness's source, because measuring them is exactly what the floors beneath them made
impossible.
"""
import ast
from pathlib import Path

import pytest

_HARNESS = Path(__file__).resolve().parent / "test_render_harness.py"

# Every fixture in the harness that starts a server. Each must settle the clock-driven
# achievement mark; the two that are NOT covered by conftest's function-scoped autouse
# isolation must also pin their own coded tree and seed their own pack.
_SERVER_FIXTURES = ("render_server", "fresh_install_server", "paged_library_server")
_PINS_ITS_OWN_TREE = ("render_server", "fresh_install_server")


def _fixture_body(path, name):
    """The AST body of the module-level `def name(...)` in `path`.

    Source-level on purpose: tests/test_render_harness.py sits under a module-level
    `pytest.importorskip("playwright.sync_api")`, so importing it to introspect the
    fixture object would make this test skip on exactly the checkouts where the harness
    is not running -- i.e. it would inherit the gateability this file exists to escape.
    Reading the file needs neither playwright nor a browser."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("{} no longer defines a module-level `def {}`".format(path, name))


def _calls_in(fixture_name):
    """Every `ast.Call` inside the harness's module-level `def fixture_name(...)`."""
    return [n for n in ast.walk(_fixture_body(_HARNESS, fixture_name))
            if isinstance(n, ast.Call)]


def _calls_by_name(calls, name):
    """True when any of `calls` calls a plain `name(...)` or an `x.name(...)`."""
    return any((c.func.id if isinstance(c.func, ast.Name)
                else getattr(c.func, "attr", None)) == name
               for c in calls)


@pytest.mark.parametrize("fixture_name", _PINS_ITS_OWN_TREE)
def test_a_harness_server_fixture_pins_its_own_root_and_pack(fixture_name):
    """`render_server` and `fresh_install_server` must pin branding_root() and seed their
    own container THEMSELVES.

    Since conftest gained the session-scoped `_real_coded_tree_pinned_away`, the
    experiment that used to discriminate this no longer can: with or without a fixture's
    own pin, a pack-present run and a pack-absent run now look identical, because the
    session pin already put every unpinned resolution in a session tmp dir. That is the
    floor working as designed -- and it is also a mask. Delete the pin inside either
    fixture today and nothing goes red: it would quietly fall back to the session root and
    the session's seeded container, sharing one tree and one pack with whatever else
    forgot, instead of writing and reading its own.

    So the pin is asserted directly, at the only level that survives the mask: the
    fixture's own source must (a) setattr `branding_root` and (b) call conftest's
    `seed_sealed_container`. Both, because either alone is a half-pin -- a pinned root
    with no seeded pack points `_container_path()` at a `moonglade.dat` nobody wrote,
    and a seeded pack with no pinned root writes it beside the checkout.

    `paged_library_server` is deliberately NOT in this list: it is function-scoped, so
    conftest's autouse `_isolated_branding` and `_sealed_roster_container` have already
    pinned and seeded a per-test tmp dir before it runs. The two named here cannot rely on
    that -- `render_server` is module-scoped and is set up BEFORE the autouse fixtures of
    the narrower scope (the 2026-09-10 bug), and `fresh_install_server` pins so that its
    guarantee survives a later change of scope."""
    calls = _calls_in(fixture_name)
    pins_root = any(
        isinstance(c.func, ast.Attribute) and c.func.attr == "setattr"
        and any(isinstance(a, ast.Constant) and a.value == "branding_root" for a in c.args)
        for c in calls)
    assert pins_root, (
        "tests/test_render_harness.py::{} no longer pins branding_root() -- it would "
        "resolve to conftest's session-wide fallback root, shared with every other fixture "
        "that forgot, instead of its own".format(fixture_name))
    assert _calls_by_name(calls, "seed_sealed_container"), (
        "tests/test_render_harness.py::{} no longer calls seed_sealed_container() -- its "
        "achievement state would come from a container this fixture never wrote"
        .format(fixture_name))


@pytest.mark.parametrize("fixture_name", _SERVER_FIXTURES)
def test_every_harness_server_settles_the_clock_driven_mark(fixture_name):
    """A harness result must never be a property of the hour the run started in.

    `/api/achievements` reads the hour off the wall clock and, for part of the day, writes
    the `session_hour` telemetry flag into the install's own ledger. An achievement reads
    that flag, so it can arrive as newly earned mid-test and put the full-screen celebration
    overlay over whatever was being measured. A downstream lane lost a run to exactly that,
    purely because it started in the small hours.

    Every fixture that starts a server therefore writes that mark itself, before it works
    out what is already `seen`. Same mask as the root/pack pin above, and worse: for most of
    the day a fixture that leaves it to the clock looks perfect, so this cannot be measured
    by watching a passing run. It is asserted at the source level, as a call to
    `settle_the_time_of_day` in the fixture's own body.

    (The other lever -- replacing `datetime.datetime` for the fixture's lifetime -- was
    built and measured and cannot be used; `settle_the_time_of_day`'s own docstring carries
    what it did and how that was isolated.)"""
    assert _calls_by_name(_calls_in(fixture_name), "settle_the_time_of_day"), (
        "tests/test_render_harness.py::{} starts a server without settling the clock-driven "
        "achievement mark -- whether its install carries that flag, and so whether an "
        "achievement lands mid-test, would be decided by the hour the suite happened to "
        "start".format(fixture_name))


@pytest.fixture(scope="module")
def unpinned_module_view():
    """What a module-scoped fixture that pins NOTHING sees when it resolves the coded tree.

    Deliberately the careless fixture: no MonkeyPatch, no `branding_root` pin, set up at
    module scope -- i.e. before conftest's function-scoped `_isolated_branding` has run.
    That is exactly the shape `render_server` had until 2026-09-10, and the reading it takes
    here is the reading that used to be the checkout's own tree and the real pack beside it.
    """
    from types import SimpleNamespace

    import moonglade_gallery as _g
    return SimpleNamespace(root=_g.branding_root(), container=_g._container_path())


def test_a_module_scoped_fixture_can_never_reach_the_real_coded_tree(unpinned_module_view):
    """The machine-dependence itself, asserted -- not the symptom it produced.

    conftest's `_real_coded_tree_untouched` watches the real tree for WRITES, and a read
    leaves nothing for it to see: on a checkout that already holds the discovery folders
    (the owner's does) an un-pinned `create_app()` writes nothing new, yet `_container_path()`
    quietly names the real pack and the fixture's achievement state becomes a property of the
    machine. So the rule is enforced by prevention -- conftest's session-scoped
    `_real_coded_tree_pinned_away` -- and this is the test that the prevention holds at the
    scope where it matters.

    Fails loudly if a future change unpins it: the next symptom would again be a fixture that
    behaves one way on a dev box and another on CI, which is not a failure anyone reads as
    "the resolver was not pinned"."""
    from tests.conftest import _REAL_CODED_ROOT

    real_pack = _REAL_CODED_ROOT.parent / "moonglade.dat"
    assert unpinned_module_view.root != _REAL_CODED_ROOT, (
        "a module-scoped fixture resolved branding_root() to the checkout's own coded tree "
        "at {}".format(_REAL_CODED_ROOT))
    assert _REAL_CODED_ROOT not in unpinned_module_view.root.parents
    assert unpinned_module_view.container != real_pack, (
        "a module-scoped fixture resolved _container_path() to the pack beside the checkout "
        "at {} -- its achievement state would be whatever that file happens to hold on this "
        "machine".format(real_pack))
