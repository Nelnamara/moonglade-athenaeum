"""A deliberately-narrow CSS cascade resolver, for tests that must assert which
declaration actually WINS.

Why this exists
---------------
pixai_gallery.py ships its CSS as several inline <style> blocks inside one document,
so rules for the same element live thousands of lines apart. An override written in
an EARLIER block silently loses to an equal-specificity base rule in a LATER one --
media queries add no specificity, so at equal specificity document order decides.

That is not hypothetical. The Generate drawer's entire portrait-mobile pass was dead
exactly that way: `#gen-drawer{width:100%}` inside `@media (max-width:480px)` sat
~1,500 lines ABOVE `#gen-drawer{width:420px}`, so the phone layout never applied. The
test that was supposed to guard it asserted only that the rule's TEXT was present --
which it was, correct and dead -- so it passed throughout. See
tests/test_web_pick.py::test_portrait_mobile_pass.

A substring assertion structurally cannot catch this. What has to be asserted is the
winner. This module computes it the way a browser does: (!important, specificity,
document order).

Relationship to tests/test_render_harness.py
--------------------------------------------
The rendering harness is the stronger instrument and the primary guard: a real chromium
measuring real layout, which catches this bug class and others (stacking, dead space)
that no static analysis can see. This module does NOT replace it and must never be used
to argue a rendering test is unnecessary.

It exists because of one gap. The harness is gated on `pytest.importorskip("playwright")`
plus a chromium binary, and `.github/workflows/tests.yml` installs neither -- so it SKIPS
in CI, by design. A cascade regression on a `push` would therefore reach master unseen.
This module is pure stdlib, needs no browser, and runs everywhere the suite runs, so the
specific "an override lost the cascade" failure stays guarded in CI too. Two layers,
different reach: the harness proves the pixels, this proves the winner.

Scope
-----
It understands the CSS this app actually writes: flat rules, one level of @media,
descendant combinators, ids, classes, and type selectors. It does NOT try to be a
browser. Anything it cannot model is skipped -- EXCEPT when that unmodelable selector
could plausibly touch the element being resolved AND declares the property being
resolved, in which case it raises rather than quietly returning a wrong winner. A
test that can't be answered honestly should fail loudly, not pass.
"""
import re

__all__ = ["css_rules", "element", "winning", "Winner", "UnmodelableSelector"]


class UnmodelableSelector(Exception):
    """A selector that could affect the answer is beyond this resolver's grammar."""


class Winner:
    """The declaration that wins for one (element, property) pair."""

    def __init__(self, value, important, specificity, order, selector, media):
        self.value = value
        self.important = important
        self.specificity = specificity
        self.order = order
        self.selector = selector
        self.media = media

    def __repr__(self):                                     # pragma: no cover - debug aid
        return "<Winner {!r} from {!r} @media {!r} spec={} order={}>".format(
            self.value, self.selector, self.media, self.specificity, self.order)


# --------------------------------------------------------------------------- parsing

_STYLE_BLOCK = re.compile(r"<style>(.*?)</style>", re.S | re.I)
_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def css_rules(html):
    """Flatten every rule in `html`'s inline <style> blocks into document order.

    Returns a list of (order, media, selector_text, {prop: (value, important)}).
    `media` is None for unconditional rules, else the raw condition text.
    """
    css = "\n".join(_COMMENT.sub("", block) for block in _STYLE_BLOCK.findall(html))
    out = []
    _parse_block(css, None, out)
    return out


def _parse_block(css, media, out):
    i = 0
    while i < len(css):
        brace = css.find("{", i)
        if brace == -1:
            break
        prelude = css[i:brace].strip()
        depth, j = 1, brace + 1
        while j < len(css) and depth:
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
            j += 1
        body = css[brace + 1:j - 1]
        if prelude.lower().startswith("@media"):
            cond = prelude[len("@media"):].strip()
            _parse_block(body, cond if media is None else media + " and " + cond, out)
        elif prelude.startswith("@"):
            pass                        # @keyframes / @font-face / @supports -- not needed
        elif prelude:
            decls = {}
            for decl in body.split(";"):
                prop, sep, value = decl.partition(":")
                if not sep:
                    continue
                prop, value = prop.strip().lower(), value.strip()
                important = value.lower().endswith("!important")
                if important:
                    value = value[:-len("!important")].rstrip().rstrip("!").strip()
                if prop and "{" not in prop:
                    decls[prop] = (value, important)
            if decls:
                out.append((len(out), media, prelude, decls))
        i = j


# -------------------------------------------------------------------------- elements

def element(tag=None, id=None, classes=(), ancestors=()):
    """Describe an element as a list of levels, outermost first, self last.

    `ancestors` is a sequence of dicts accepted by this same function's kwargs,
    e.g. element(id="model-flyout", ancestors=[dict(id="gen-drawer",
                                                    classes={"open", "dock-top"})]).
    """
    levels = []
    for anc in ancestors:
        levels.append((anc.get("tag"), anc.get("id"), frozenset(anc.get("classes", ()))))
    levels.append((tag, id, frozenset(classes)))
    return levels


_COMPOUND = re.compile(
    r"^(?P<tag>[a-zA-Z][\w-]*)?(?P<id>#[\w-]+)?(?P<cls>(?:\.[\w-]+)*)$")


def _parse_compound(part):
    m = _COMPOUND.match(part)
    if not m or not part:
        return None
    tag = m.group("tag").lower() if m.group("tag") else None
    el_id = m.group("id")[1:] if m.group("id") else None
    classes = frozenset(c for c in m.group("cls").split(".") if c)
    if tag is None and el_id is None and not classes:
        return None
    return (tag, el_id, classes)


def _parse_selector(sel):
    """Split a selector into descendant compounds, or None if beyond the grammar."""
    if re.search(r"[>+~\[\]*]|::|:", sel):
        return None                     # combinators, attributes, universal, pseudos
    compounds = [_parse_compound(p) for p in sel.split()]
    if not compounds or any(c is None for c in compounds):
        return None
    return compounds


def _compound_matches(compound, level):
    tag, el_id, classes = compound
    l_tag, l_id, l_classes = level
    if tag is not None and tag != l_tag:
        return False
    if el_id is not None and el_id != l_id:
        return False
    return classes <= l_classes


def _matches(compounds, levels):
    if not _compound_matches(compounds[-1], levels[-1]):
        return False
    ci, li = len(compounds) - 2, len(levels) - 2
    while ci >= 0:
        while li >= 0 and not _compound_matches(compounds[ci], levels[li]):
            li -= 1
        if li < 0:
            return False
        ci -= 1
        li -= 1
    return True


def _specificity(compounds):
    ids = sum(1 for c in compounds if c[1])
    classes = sum(len(c[2]) for c in compounds)
    types = sum(1 for c in compounds if c[0])
    return (ids, classes, types)


def _might_touch(sel, levels):
    """Cheap over-approximation: could this unmodelable selector hit our element?"""
    names = set()
    for tag, el_id, classes in levels:
        if tag:
            names.add(tag)
        if el_id:
            names.add("#" + el_id)
        names.update("." + c for c in classes)
    return any(n in sel for n in names)


# --------------------------------------------------------------------------- cascade

_MEDIA_TERM = re.compile(r"\(\s*(max|min)-width\s*:\s*(\d+(?:\.\d+)?)px\s*\)")

# The non-width conditions this app ships, and what a default screen viewport does
# with them. Both are modelling CHOICES, stated here rather than buried: we resolve
# the on-screen rendering for a user who has not asked for reduced motion. Anything
# NOT listed raises, so a newly-introduced condition can't be silently mis-evaluated.
_MEDIA_NEVER = ("print", "(prefers-reduced-motion: reduce)", "(prefers-reduced-motion:reduce)")
_MEDIA_ALWAYS = ("screen",)


def _media_applies(media, width):
    if media is None:
        return True
    rest = media
    for token in _MEDIA_NEVER:
        if token in rest:
            return False
    for token in _MEDIA_ALWAYS:
        rest = rest.replace(token, "")
    terms = _MEDIA_TERM.findall(rest)
    leftover = _MEDIA_TERM.sub("", rest).replace("and", "").strip()
    if not terms or leftover:
        raise UnmodelableSelector("unsupported @media condition: {!r}".format(media))
    for kind, px in terms:
        px = float(px)
        if kind == "max" and not width <= px:
            return False
        if kind == "min" and not width >= px:
            return False
    return True


def winning(rules, levels, prop, width):
    """Resolve which declaration of `prop` wins on `levels` at viewport `width`.

    Returns a Winner, or None when nothing declares the property.
    """
    prop = prop.lower()
    best = None
    for order, media, selector_text, decls in rules:
        if prop not in decls:
            continue
        if not _media_applies(media, width):
            continue
        spec = None
        for part in selector_text.split(","):
            part = " ".join(part.split())
            if not part:
                continue
            compounds = _parse_selector(part)
            if compounds is None:
                if _might_touch(part, levels):
                    raise UnmodelableSelector(
                        "selector {!r} declares {!r} and may match the element under "
                        "test, but this resolver cannot model it".format(part, prop))
                continue
            if _matches(compounds, levels):
                s = _specificity(compounds)
                if spec is None or s > spec:
                    spec = s
        if spec is None:
            continue
        value, important = decls[prop]
        key = (important, spec, order)
        if best is None or key > (best.important, best.specificity, best.order):
            best = Winner(value, important, spec, order, selector_text, media)
    return best
