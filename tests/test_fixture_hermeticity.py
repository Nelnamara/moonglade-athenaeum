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
"""
import pytest


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
