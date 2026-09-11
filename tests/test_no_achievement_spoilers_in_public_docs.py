"""Guardrail: no achievement/easter-egg spoilers in the PUBLIC docs.

The HARD RULE (moonglade-internal/DECISIONS.md, 2026-08-09): easter eggs and the
features they unlock get ZERO mention in any public artifact -- not CHANGELOG.md,
ROADMAP.md, docs/, wiki/, README. Forbidden: the hidden trigger mechanics, real achievement
progress numbers, the roster count, specific achievement/feat names, and how-to-earn
thresholds. The .dat seals the roster so discovery takes effort; a doc that lists it
is a no-effort shortcut around the seal (owner, 2026-09-08, after two live leaks --
a mark gate that named a hidden feat, and a release note that stated the feat count).

This pins the committed public docs. It CANNOT itself hardcode the hidden feat names
(that would put the spoiler in the public repo); the specific-name check derives the
names from the SEALED roster at runtime and skips when the private donor is absent.
GitHub Release notes are NOT in git and can't be pinned here -- those stay a
discipline item (see the memory / DECISIONS)."""
import re
from pathlib import Path

import pytest

from tests.conftest import _SEALED_DONOR

ROOT = Path(__file__).resolve().parent.parent
# ROADMAP.md is in the set because it is the DEFAULT home for planned work (CLAUDE.md's
# split rule), so it is where a spoiler is most likely to be written next -- an item about
# an easter-egg-gated surface belongs in the private companion roadmap, and anything said
# here about the area a hidden feat gates has to describe nothing (EASTER_EGGS.md's ceiling).
# It was outside the guard until 2026-09-10, which made "the public roadmap passes the
# spoiler test" a claim about a file the test never opened.
PUBLIC_DOCS = (
    [ROOT / "CHANGELOG.md", ROOT / "README.md", ROOT / "ROADMAP.md"]
    + sorted((ROOT / "docs").glob("*.md"))
    + sorted((ROOT / "wiki").glob("*.md"))
)

# Class patterns -- these never belong in a public doc and name no feat themselves.
# "under the hood:" (sentence case, an internal-changes idiom) is deliberately NOT
# matched; the feat is the title-case proper noun "Under the Hood".
FORBIDDEN = [
    (r"\bhidden feats?\b", "the phrase 'hidden feat(s)'"),
    (r"\beaster egg", "'easter egg'"),
    (r"\bKonami\b", "'Konami'"),
    (r"\bStarfall\b", "'Starfall'"),
    (r"\bUnder the Hood\b", "the feat name 'Under the Hood'"),
    (r"\bsecret feat", "'secret feat'"),
    (r"\b\d+\s+achievements\b", "an achievement COUNT"),
    (r"\b\d+\s+hidden\b", "a hidden COUNT"),
    (r"\b\d+\s+(ladder rung|milestone|master(y|ies)|feat)s?\b", "a roster-composition COUNT"),
    (r"\b\d+-achievement\b", "an achievement COUNT"),
]


def _docs():
    return [(p, p.read_text(encoding="utf-8")) for p in PUBLIC_DOCS if p.is_file()]


@pytest.mark.parametrize("pattern,label", FORBIDDEN)
def test_public_docs_have_no_spoiler_class(pattern, label):
    rx = re.compile(pattern, re.I if "Under the Hood" not in pattern and "Konami" not in pattern
                    and "Starfall" not in pattern else 0)
    hits = []
    for path, text in _docs():
        for m in re.finditer(pattern, text):
            ln = text.count("\n", 0, m.start()) + 1
            hits.append("%s:%d  %r" % (path.name, ln, text[m.start():m.start() + 50]))
    assert not hits, ("public docs leak %s (HARD RULE 2026-08-09):\n  " % label
                      + "\n  ".join(hits))


def test_public_docs_name_no_hidden_feat(sealed_donor_present):
    """Names come from the SEALED roster, never hardcoded here. Skips without the donor."""
    import json
    roster = json.loads(_SEALED_DONOR.read_text(encoding="utf-8"))
    items = roster if isinstance(roster, list) else roster.get("achievements") or roster.get("roster") or []
    names = [str(a.get("name") or "").strip() for a in items
             if isinstance(a, dict) and a.get("hidden") and (a.get("name") or "").strip()]
    # A hidden feat leaks when a doc DELIBERATELY names it -- and a changelog/wiki names a
    # feat by bolding it (**Under the Hood**), the shape the real 2026-09-08 leak took. Match
    # only the bolded span, so incidental English that happens to equal a feat name does NOT
    # trip the guard: the "a library against the Void" tagline (feat "Against the Void"), the
    # eclipse mark's animation (feat "Eclipse"), the verb "triggered" (feat "Triggered"). The
    # literal-name class check above still catches "Under the Hood" bolded or not.
    hits = []
    for path, text in _docs():
        for nm in names:
            for m in re.finditer(r"\*\*\s*" + re.escape(nm) + r"\s*\*\*", text, re.I):
                ln = text.count("\n", 0, m.start()) + 1
                hits.append("%s:%d bolds the hidden feat %r" % (path.name, ln, nm))
    assert not hits, ("public docs name a hidden feat (HARD RULE):\n  " + "\n  ".join(sorted(set(hits))))
