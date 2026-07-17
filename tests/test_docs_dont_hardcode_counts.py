"""One check, deliberately narrow: a live doc may not hardcode the test count.

Why this exists, and why it is a test rather than a note in CLAUDE.md:

A 2026-07-16 audit verified 914 documentation claims against the code. The test count was
written in six or more files and was **wrong in every single one** -- a 0% success rate for
a number that `pytest` will tell you for free. The reconciliation pass that day "fixed" it
to 477 by hand-copying; the real number was 478. Hours later, two regression tests landed
and every freshly-corrected doc was stale again.

The failure isn't carelessness, it's structural: a number that changes on its own schedule
cannot be maintained by remembering to update six files. So don't write it -- write the
command. That rule only holds if something enforces it, because the same people who forget
to update the count also forget the rule.

Scope is intentionally minimal, so this is cheap to keep and trivial to delete if it ever
gets in the way:
  - Live prose docs only. `docs/archive/**` is exempt -- frozen records are *supposed* to
    say what was true on their date; that is their entire job.
  - `CHANGELOG.md` is exempt for the same reason: a dated release block saying what was
    green at that release is history, not a claim about now.
  - Only the test count. Not a doc linter. If a second fact ever earns a check, add it
    deliberately -- do not grow this into a framework.
"""
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent

# "478 pytest tests", "478 tests", "480 passing tests"
_PYTEST_COUNT = re.compile(r"\b\d{2,5}\s+(?:pytest\s+|passing\s+|python\s+)?tests?\b", re.I)
# "66 `node --test` cases", "66 node tests"
_NODE_COUNT = re.compile(r"\b\d{2,5}\s+(?:`?node(?:\s+--test)?`?\s+)(?:tests?|cases?)\b", re.I)

_FIX = (
    "Docs must not hardcode the test count -- it changes every time anyone adds a test, and "
    "it has been wrong in every doc that ever stated it. Name the command instead, e.g.\n"
    "    Run `python -m pytest -q` (add --ignore=tests/test_similar.py without pixeltable).\n"
    "If this is a frozen historical record, it belongs in docs/archive/, which is exempt."
)


def _live_docs():
    """Every doc that claims to describe the project as it is NOW."""
    paths = [_REPO / "README.md", _REPO / "CLAUDE.md"]
    paths += sorted((_REPO / "docs").glob("*.md"))      # top level only -- archive/ excluded
    paths += sorted((_REPO / "wiki").glob("*.md"))
    return [p for p in paths if p.is_file()]


@pytest.mark.parametrize("doc", _live_docs(), ids=lambda p: str(p.relative_to(_REPO)).replace("\\", "/"))
def test_live_doc_does_not_hardcode_a_test_count(doc):
    offenders = []
    for n, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
        for pat in (_PYTEST_COUNT, _NODE_COUNT):
            m = pat.search(line)
            if m:
                offenders.append("{}:{}: {}".format(
                    doc.relative_to(_REPO), n, m.group(0).strip()))
    assert not offenders, "{}\n\nFound:\n  {}\n\n{}".format(
        test_live_doc_does_not_hardcode_a_test_count.__doc__ or "", "\n  ".join(offenders), _FIX)


def test_the_check_actually_catches_the_real_historical_mistakes():
    """Guard the guard: these are verbatim phrasings that shipped in real docs and were wrong.
    If a refactor loosens the pattern, this fails instead of the check silently passing."""
    real_mistakes = [
        "477 pytest tests in `tests/` (the count grows with every feature",
        "478 pytest tests in `tests/` (pure functions, filesystem, catalog",
        "has 66 `node --test` cases in `loom/`",
        "All 474 tests green (that day's count)",
        "459 tests green (that day's count; **478** now)",
    ]
    for line in real_mistakes:
        assert _PYTEST_COUNT.search(line) or _NODE_COUNT.search(line), (
            "check no longer catches a phrasing that really shipped: " + line)


def test_known_blind_spot_is_still_blind():
    """An honest limit, asserted so nobody mistakes it for coverage.

    CLAUDE.md really shipped "...; 482 if it's installed and that file runs too" -- a bare
    number whose subject lives in the *previous* sentence. A line-oriented regex cannot tell
    that from any other number in prose, and widening it enough to catch this would fire on
    ordinary counts ("482 images"), which would punish writing docs at all.

    It is tolerable because the clause only exists to qualify a count that this check already
    rejects: delete the count and the dangling qualifier goes with it. Recorded here so a
    future reader knows this case is uncovered by choice, not by oversight.
    """
    dangling = "482 if it's installed and that file runs too"
    assert not (_PYTEST_COUNT.search(dangling) or _NODE_COUNT.search(dangling))


def test_the_check_does_not_fire_on_the_correct_phrasing():
    """The rule is 'name the command'. Those docs must pass, or the check punishes the fix."""
    good = [
        "Run `python -m pytest -q` (add `--ignore=tests/test_similar.py` without pixeltable).",
        "The Loom's pure-logic modules have their own suite -- run `node --test` from `loom/`.",
        "All tests must pass before merging to master.",
        "Tested end-to-end against a running server.",
        "Fixed in 3 cases where the poster was missing.",
    ]
    for line in good:
        assert not _PYTEST_COUNT.search(line) and not _NODE_COUNT.search(line), (
            "check false-positives on correct phrasing, which would punish following the rule: "
            + line)
