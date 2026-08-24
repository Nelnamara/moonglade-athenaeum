"""resolve_tack_ids: mapping user-typed tags to PixAI's real 'tack' ids. Its own
docstring promises a tag with no exact match is REPORTED, never silently substituted --
these tests pin that contract directly (not through a route stub, which can't see this
function's internals). Regression coverage for ultrareview 2026-08-06 bug_004: a fuzzy
`edges[0]` fallback used to attach whatever ranked first in PixAI's search (e.g. typing
"moon" silently became "moonlight") with zero signal in the preview or confirm sheet."""
import moonglade_backup as core


def _fake_tacks(pixai, edges_by_query):
    """Register the `listTacks` search on the fake PixAI, keyed on the search query text
    and shaped like the real _LIST_TACKS response:
    {"tacks": {"edges": [{"node": {...}}, ...]}}."""
    def answer(call):
        q = (call.variables or {}).get("q", "")
        return {"tacks": {"edges": edges_by_query.get(q, [])}}
    pixai.on("listTacks", answer)
    return pixai


def test_exact_codename_match_resolves(pixai):
    _fake_tacks(pixai, {
        "elf": [{"node": {"id": "T1", "codeName": "elf", "defaultName": "Elf"}},
                {"node": {"id": "T2", "codeName": "elven", "defaultName": "Elven"}}],
    })
    ids, unmatched = core.resolve_tack_ids(pixai, ["elf"])
    assert ids == ["T1"] and unmatched == []


def test_exact_defaultname_match_resolves_case_insensitively(pixai):
    _fake_tacks(pixai, {
        "Moonlight": [{"node": {"id": "T5", "codeName": "moonlight_tag", "defaultName": "Moonlight"}}],
    })
    ids, unmatched = core.resolve_tack_ids(pixai, ["Moonlight"])
    assert ids == ["T5"] and unmatched == []


def test_no_exact_match_is_reported_unmatched_not_silently_substituted(pixai):
    """THE regression: "moon" has no exact tack, but the search still returns real,
    semantically-close hits ("moonlight" ranks first). The old code took edges[0] as a
    'closest match' and attached it with no signal -- this proves that no longer happens:
    zero ids come back, and "moon" -- not "moonlight" -- lands in unmatched."""
    _fake_tacks(pixai, {
        "moon": [{"node": {"id": "T-moonlight", "codeName": "moonlight", "defaultName": "Moonlight"}},
                 {"node": {"id": "T-moonbeam", "codeName": "moonbeam", "defaultName": "Moonbeam"}}],
    })
    ids, unmatched = core.resolve_tack_ids(pixai, ["moon"])
    assert ids == [], "a fuzzy hit must never be silently attached"
    assert unmatched == ["moon"], "the typed tag, not the fuzzy hit, is what's reported"


def test_genuinely_no_results_is_also_reported_unmatched(pixai):
    _fake_tacks(pixai, {"zzzznotarealtag99": []})
    ids, unmatched = core.resolve_tack_ids(pixai, ["zzzznotarealtag99"])
    assert ids == [] and unmatched == ["zzzznotarealtag99"]


def test_mixed_tags_resolve_and_report_independently(pixai):
    _fake_tacks(pixai, {
        "elf": [{"node": {"id": "T1", "codeName": "elf", "defaultName": "Elf"}}],
        "moon": [{"node": {"id": "T-moonlight", "codeName": "moonlight", "defaultName": "Moonlight"}}],
    })
    ids, unmatched = core.resolve_tack_ids(pixai, ["elf", "moon"])
    assert ids == ["T1"] and unmatched == ["moon"]


def test_leading_hash_and_trailing_whitespace_are_stripped_before_matching(pixai):
    _fake_tacks(pixai, {
        "elf": [{"node": {"id": "T1", "codeName": "elf", "defaultName": "Elf"}}],
    })
    ids, unmatched = core.resolve_tack_ids(pixai, ["#elf  "])
    assert ids == ["T1"] and unmatched == []


def test_blank_tags_are_skipped_entirely(pixai):
    ids, unmatched = core.resolve_tack_ids(pixai, ["", "   ", "#"])
    assert ids == [] and unmatched == []


def test_a_failed_search_reports_unmatched_rather_than_raising(pixai):
    pixai.fail("listTacks", core.PixAIError("transient"))
    ids, unmatched = core.resolve_tack_ids(pixai, ["elf"])
    assert ids == [] and unmatched == ["elf"]
