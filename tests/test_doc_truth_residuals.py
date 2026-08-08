"""Doc/comment/docstring-only regression tests for a batch of 2026-07-21 audit residuals
(docs/AUDIT_2026-07-21.md: P3, P6 "doc half only", P7 invariant claims, and a few smaller
doc-truth items). Every test below checks TEXT -- a comment, a docstring, a wiki/doc
paragraph -- against behavior independently re-verified from the current source, never
taken on the audit's word alone. None of these exercise new application behavior: this
whole pass is comments/docstrings/docs only, so there is nothing else to test.
"""
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def _read(relpath):
    return (_REPO / relpath).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# P3 residual: the hardcoded is_local=True and the Import control.
# /api/import-local IS correctly re-checked server-side as LOCALHOST-tier (no real
# security hole) -- originally, the classic header's comments justifying the
# is_local=True hardcode never mentioned Import's stricter tier, so a signed-in LAN
# session saw a working-looking Import button that always 403'd (comment fix
# 2026-07-23 e36976d; visibility gated on the real check 2026-07-24, P3/S5-3).
# PORTED 2026-08-08, the classic-UI cut: BASE_HTML/INDEX_HTML (the head-nav block,
# ImportUI, and both classic comments these tests used to scrape) are deleted. The
# same enforcement now lives in the React shell: next_gallery()'s boot payload
# ships the hardcoded `"is_local": True` PAIRED with the real
# `"is_true_local": _is_local_request()`, and the surviving Import control
# (gallery/src/components/NavSpine.jsx) is marked localOnly and withheld unless
# boot.is_true_local -- with ImportOverlay.jsx's header documenting the route as
# localhost-only. The two tests below pin that ported shape: the UI source that
# renders Import must keep saying (and doing) the LOCALHOST-tier exception, and
# the hardcode must never ship without the real check beside it.
# ---------------------------------------------------------------------------

def test_navspine_gates_and_documents_import_as_the_localhost_exception():
    """The React nav (the surviving home of the Import control) must (a) mark the
    Import item localOnly, (b) actually withhold localOnly items unless the REAL
    boot.is_true_local flag is set -- never the hardcoded boot.is_local -- and
    (c) carry commentary naming /api/import-local so a reader knows why Import is
    gated differently from its neighbors (Generate-tier surfaces are LOGIN-tier;
    Import writes to the server's own filesystem)."""
    src = _read("gallery/src/components/NavSpine.jsx")
    item_start = src.index('label: "Import"')
    item_end = src.index("label:", item_start + 1)
    item = src[item_start:item_end]
    assert "localOnly: true" in item, (
        "NavSpine's Import item is no longer marked localOnly -- a LAN session would "
        "see a working-looking Import control that always 403s (the original P3 bug)")
    assert re.search(r"localOnly\s*&&\s*!boot\.is_true_local", src), (
        "NavSpine no longer withholds localOnly items on the REAL is_true_local check; "
        "gating on the hardcoded is_local flag would resurrect the P3 bug")
    comment_window = src[max(0, item_start - 400):item_start]
    assert re.search(r"import-local|localhost|LOCALHOST", comment_window), (
        "the comment above NavSpine's Import item no longer names /api/import-local or "
        "its localhost tier -- the doc half of the P3 fix")


def test_is_local_hardcode_ships_with_the_real_check_and_the_route_backs_the_doc():
    """The `is_local: True` hardcode survives in next_gallery()'s boot payload. It is
    only safe because the REAL `_is_local_request()` verdict ships right beside it as
    `is_true_local` (what the Import control gates on), and because /api/import-local
    re-checks localhost server-side regardless of what any client renders --
    which is also exactly what ImportOverlay.jsx's header comment claims
    ('/api/import-local ... is localhost-only'). Pin all three so the doc claim,
    the boot payload, and the route can't drift apart."""
    src = _read("moonglade_gallery.py")
    start = src.index('"is_local": True')
    window = src[start:start + 200]
    assert re.search(r'"is_true_local":\s*_is_local_request\(\)', window), (
        "the boot payload hardcodes is_local=True without shipping the real "
        "_is_local_request() verdict beside it as is_true_local -- the client would "
        "have no way to gate Import correctly")
    route_start = src.index('@app.route("/api/import-local"')
    route_body = src[route_start:route_start + 2500]
    assert "_is_local_request()" in route_body, (
        "/api/import-local no longer re-checks _is_local_request() server-side -- "
        "client-side gating alone is not a tier")
    assert re.search(r"[Ll]ocalhost-only", route_body), (
        "/api/import-local's docstring no longer states its localhost-only tier")
    overlay = _read("gallery/src/components/ImportOverlay.jsx")
    assert re.search(r"import-local[\s\S]{0,120}localhost-only", overlay), (
        "ImportOverlay.jsx's header no longer documents /api/import-local as "
        "localhost-only -- the surviving doc half of the P3 fix")


# ---------------------------------------------------------------------------
# P6, doc half only: _task_detail_query's docstring overclaims fallback coverage.
# Its only real caller is collect_generation (the --task-id/--dump-params recovery
# path). run_backfill_full_meta and run_download's --full-meta branch both call
# task_detail_gql directly, bypassing this function's ad-hoc fallback entirely.
# ---------------------------------------------------------------------------

def test_task_detail_query_docstring_names_its_real_caller_and_the_two_that_bypass_it():
    """Verified independently against current source: run_backfill_full_meta raises
    PixAIError itself when TASK_DETAIL_HASH is empty (its own guard, unconditional --
    proof it never reaches this function's fallback), and both call sites in
    run_download's --full-meta branch (parallel and serial) call task_detail_gql
    directly. collect_generation is the only real caller of _task_detail_query."""
    import moonglade_backup as core
    doc = core._task_detail_query.__doc__ or ""
    assert "collect_generation" in doc, (
        "docstring doesn't name its one real caller (collect_generation)")
    assert "run_backfill_full_meta" in doc, (
        "docstring doesn't name run_backfill_full_meta as a function that bypasses it")
    assert "run_download" in doc, (
        "docstring doesn't name run_download's --full-meta branch as bypassing it")
    assert "no longer HARD-FAIL" not in doc, (
        "docstring still makes the disproven claim that --full-meta/--backfill-full-meta "
        "benefit from this function's ad-hoc fallback")


# ---------------------------------------------------------------------------
# P7 residual: false INVARIANT claims in docs/architecture.md and CONTRIBUTING.md.
# ---------------------------------------------------------------------------

def test_invariant_1_media_id_of_is_not_documented_as_a_single_source():
    """media_id_of() is re-implemented inline elsewhere instead of being called --
    verified by grep: moonglade_gallery.py's own backfill_batches() and moonglade_similar.py's
    scan_dir both do a bare `stem.split("_")[-1]` rather than calling the shared
    function. The module table's "single source" claim is false."""
    arch = _read("docs/architecture.md")
    idx = arch.index("`media_id_of()`")
    row = arch[idx:arch.index("\n", idx)]
    assert "Invariant 1, single source" not in row, (
        "media_id_of()'s module-table row still claims to be a 'single source' "
        "unqualified, which is false (see backfill_batches/scan_dir duplicates)")
    assert "backfill_batches" in row and "scan_dir" in row, (
        "media_id_of()'s module-table row doesn't name the known inline duplicates "
        "(backfill_batches in this module, moonglade_similar.py's scan_dir)")


def test_invariant_2_resume_ordering_caveats_full_meta_and_sync():
    """Verified directly in run_download: under --full-meta (and --sync, which is
    '--update --full-meta' under the hood), task_detail_gql + model_name_gql +
    resolve_loras all fire for a task BEFORE the per-media on_disk_by_mid resume check,
    in both the parallel and serial code paths. Invariant 2 as flatly stated
    ('checked before any network call') is false in that mode."""
    arch = _read("docs/architecture.md")
    inv_section = arch[arch.index("## Invariants"):arch.index("## The web suite")]
    assert "--full-meta" in inv_section, (
        "Invariant 2 doesn't mention the --full-meta/--sync exception at all")
    assert not re.search(
        r"\*\*Resume is keyed on media id, checked before any network call\.\*\*\s*\n\d",
        inv_section), (
        "Invariant 2 still states the unconditional claim with nothing qualifying it")


def test_invariant_4_catalog_source_of_truth_reconciled_with_filesystem_truth_dedup():
    """audit_collection()'s own module-table entry calls it a 'Filesystem-truth
    duplicate audit' -- independent of catalog.db. Invariant 4's blanket 'catalog.db is
    the source of truth for organize and friends' contradicts that if dedup/audit count
    as 'friends'. Reconcile: catalog.db governs organize/resume/lookup; dedup/audit are
    deliberately filesystem-truth and don't consult it."""
    arch = _read("docs/architecture.md")
    inv_section = arch[arch.index("## Invariants"):arch.index("## The web suite")]
    assert "for organize and friends." not in inv_section, (
        "Invariant 4 still makes the unqualified 'organize and friends' claim that "
        "contradicts audit_collection()'s own filesystem-truth description")
    assert re.search(r"audit_collection|filesystem-truth", inv_section, re.I), (
        "Invariant 4 doesn't reconcile with audit_collection()'s filesystem-truth nature")


def test_invariant_7_names_more_than_just_resume_and_audit():
    """Same underlying fact as batch 2's B11 fix in this sweep: there isn't 'one shared
    matcher' with two exceptions (resume, audit) -- cmd_organize, run_import_local,
    duplicate_groups, and the Loom's last-frame resolver each walk the tree
    independently too. Verified directly via grep for .rglob(/os.walk( call sites and
    mapping each to its enclosing function."""
    arch = _read("docs/architecture.md")
    inv_section = arch[arch.index("## Invariants"):arch.index("## The web suite")]
    named = ("cmd_organize", "run_import_local", "duplicate_groups")
    missing = [n for n in named if n not in inv_section]
    assert not missing, (
        "Invariant 7 still only names resume+audit as non-callers of "
        "find_files_for_media_id; missing: {}".format(missing))


def test_contributing_md_does_not_harden_the_false_single_matcher_claim():
    """CONTRIBUTING.md said resolution 'goes through find_files_for_media_id() ... never
    a new ad-hoc glob' as a flat statement of current fact -- false, per Invariant 7
    above. It also pointed at 'the INVARIANTS section of CLAUDE.md', which no longer
    holds the list itself (CLAUDE.md now delegates to docs/architecture.md)."""
    contrib = _read("CONTRIBUTING.md")
    assert "never a new" not in contrib, (
        "CONTRIBUTING.md still states as flat fact that every lookup goes through "
        "find_files_for_media_id() with never a new ad-hoc glob -- false")
    assert "docs/architecture.md" in contrib, (
        "CONTRIBUTING.md's media_id guidance should point at docs/architecture.md "
        "(where the Invariants section actually lives now), not just CLAUDE.md")


# ---------------------------------------------------------------------------
# Smaller items (still open, verified against current source).
# ---------------------------------------------------------------------------

def test_generating_wiki_documents_the_video_model_roster_and_duration_gating():
    """Verified directly against static/mg-generate-drawer.js's MODELS/MODEL_VMODES/
    MODEL_MAXDUR tables: seven selectable video engines, a 6s duration that's real but
    was never mentioned anywhere user-facing, two models (V3.0 Flash, V2.7) that no free
    card ever covers, and per-model gating of which Shot modes are offered."""
    gen = _read("wiki/Generating.md")
    for label in ("V4.0 Preview", "V4.0 Lite Preview", "V3.2", "V3.0 Lite",
                  "V3.0 (High Consistency)", "V3.0 Flash", "V2.7"):
        assert label in gen, "video model roster doc is missing {}".format(label)
    assert re.search(r"\b6\b.*second|duration.*\b6\b|5,\s*6,\s*10", gen, re.I), (
        "the real 6-second duration option is still never mentioned")
    assert re.search(r"no card", gen, re.I), (
        "doesn't document that V3.0 Flash/V2.7 are never covered by a free card")
    assert re.search(r"Multi-Reference|R2V", gen), (
        "doesn't document that Multi-Reference/R2V is gated to the V4.0 pair only")


def test_collections_wiki_documents_remove_from_collection_and_actions_menu():
    """The v2.2.0 bulk-bar consolidation moved every bulk action (including the shipped
    '- Remove from <collection>' action, gated on a collection filter being active)
    behind a single Actions dropdown -- verified directly against the bulk-bar template
    (id="actions-btn"/"actions-menu", the {% if collection %}-gated remove button)."""
    coll = _read("wiki/Collections.md")
    assert re.search(r"Remove from", coll), (
        "wiki/Collections.md still doesn't mention the Remove-from-collection action")
    assert re.search(r"Actions", coll), (
        "wiki/Collections.md doesn't mention the Actions menu these bulk actions now "
        "live behind")
