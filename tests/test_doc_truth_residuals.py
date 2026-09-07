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
# same enforcement now lives in the React shell: app_page()'s boot payload
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
    """The `is_local: True` hardcode survives in app_page()'s boot payload. It is
    only safe because the REAL `_is_local_request()` verdict ships right beside it as
    `is_true_local` (what the Import control gates on), and because /api/import-local
    is LOCALHOST-tier server-side regardless of what any client renders --
    which is also exactly what ImportOverlay.jsx's header comment claims
    ('/api/import-local ... is localhost-only'). Pin all three so the doc claim,
    the boot payload, and the route can't drift apart.

    The route's half of that moved on 2026-08-23: the check used to be a
    hand-written `if not _is_local_request(): return ..., 403` as the handler's
    first statement, and is now the route's own `@tier(LOCALHOST)` declaration,
    enforced for every LOCALHOST route in one place by _enforce_front_door().
    Same server-side refusal, same 403, same wording (carried on the declaration
    as `message=`) -- so what this pins is the DECLARATION, not the old
    statement. tests/test_route_tiers.py proves the enforcement itself against a
    live authenticated LAN request."""
    src = _read("moonglade_gallery.py")
    start = src.index('"is_local": True')
    window = src[start:start + 200]
    assert re.search(r'"is_true_local":\s*_is_local_request\(\)', window), (
        "the boot payload hardcodes is_local=True without shipping the real "
        "_is_local_request() verdict beside it as is_true_local -- the client would "
        "have no way to gate Import correctly")
    route_start = src.index('@app.route("/api/import-local"')
    route_body = src[route_start:route_start + 2500]
    assert re.search(r"@tier\(\s*LOCALHOST", route_body), (
        "/api/import-local no longer declares @tier(LOCALHOST) -- the server-side "
        "localhost requirement is gone and client-side gating alone is not a tier")
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
# P7 residual: the four architecture.md invariant-claim tests were retired on
# 2026-08-14 -- docs/architecture.md moved to the private companion repo
# (../moonglade-internal), which CI does not clone, so they can no longer read
# their subject. The corrected claims they pinned live on in that file.
# ---------------------------------------------------------------------------

def test_contributing_md_does_not_harden_the_false_single_matcher_claim():
    """CONTRIBUTING.md said resolution 'goes through find_files_for_media_id() ... never
    a new ad-hoc glob' as a flat statement of current fact -- false, per Invariant 7
    above. It also pointed at 'the INVARIANTS section of CLAUDE.md', which no longer
    holds the list itself (CLAUDE.md now delegates to docs/architecture.md)."""
    contrib = _read("CONTRIBUTING.md")
    assert "never a new" not in contrib, (
        "CONTRIBUTING.md still states as flat fact that every lookup goes through "
        "find_files_for_media_id() with never a new ad-hoc glob -- false")
    # (The companion assertion that CONTRIBUTING points at docs/architecture.md was
    # dropped 2026-08-14: that file moved to the private companion repo, and
    # CONTRIBUTING now points contributors at the wiki instead.)


# ---------------------------------------------------------------------------
# Smaller items (still open, verified against current source).
# ---------------------------------------------------------------------------

def test_generating_wiki_documents_the_video_model_roster_and_duration_gating():
    """Verified directly against gallery/src/gen/videoDrawerCore.js's MODELS/MODEL_VMODES/
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


# ---------------------------------------------------------------------------
# wiki/Glossary.md (new 2026-09-07) names controls, so every name in it is a claim
# about the current UI. The red-team round found three that were not: the Fixer
# described as a live control on the dock's Edit tab (removed from the desktop
# 2026-08-18, a "coming next" placeholder on the phone), a "LAN session" chip in
# the header (deleted with the classic UI and never rebuilt in the React shell),
# and Activity placed at the bottom-left (it lives at an end of the separator bar
# in the sticky header). Each test below re-derives the truth from the source
# rather than trusting the entry -- the glossary exists so a user can name a
# screen and a control in a bug report, and an entry that names a control that
# is not there defeats exactly that.
# ---------------------------------------------------------------------------

def _glossary_entry(term):
    """One Glossary bullet, term line plus its wrapped continuation lines."""
    lines = _read("wiki/Glossary.md").splitlines()
    for i, line in enumerate(lines):
        if line.startswith("- **" + term + "**"):
            out = [line]
            for nxt in lines[i + 1:]:
                if nxt.startswith("- ") or not nxt.strip():
                    break
                out.append(nxt)
            return "\n".join(out)
    raise AssertionError("wiki/Glossary.md has no entry for " + term)


def test_glossary_does_not_sell_the_fixer_as_a_control_you_can_reach():
    """Desktop: EditTab's SOURCE sub-tab strip is the literal [["edit"],["enhance"]] and
    nothing ever sets the dock's `sub` to "fixer", so FixTab is unreachable. Phone:
    CreateMobile's fixer sub-tab renders a `cm-soon` placeholder. So the entry must not
    read as a live control; it must say it is not built and where the placeholder is."""
    edit_tab = _read("gallery/src/components/EditTab.jsx")
    assert '["enhance", "Enhance"]' in edit_tab and '"fixer"' not in edit_tab, (
        "EditTab's sub-tab strip changed -- if the desktop Fixer is back, the Glossary "
        "entry this test guards should be rewritten to say so")
    drawer = _read("gallery/src/components/GenerateDrawer.jsx")
    assert not re.search(r'setSub\(\s*"fixer"', drawer), (
        "something now navigates the dock to the Fixer sub-tab -- re-check the Glossary")
    phone = _read("gallery/src/components/CreateMobile.jsx")
    assert "cm-soon" in phone and "coming next" in phone, (
        "the phone's Fixer placeholder changed -- re-check the Glossary entry")

    entry = _glossary_entry("the Fixer")
    assert re.search(r"not\s+built", entry, re.I), (
        "wiki/Glossary.md still presents the Fixer as something you can use; the desktop "
        "dock has no Fixer and the phone's is a 'coming next' placeholder")
    assert "placeholder" in entry.lower(), (
        "the Fixer entry no longer says where the placeholder sits, so a reader cannot "
        "tell the difference between 'missing' and 'not built yet'")


def test_glossary_does_not_promise_a_lan_session_chip_the_shell_never_renders():
    """The classic UI's "LAN session · local-only tools hidden" chip went with the classic
    cut and was never rebuilt: there is no globe glyph anywhere in gallery/src, and nothing
    renders a LAN badge. What a LAN session actually meets is withheld controls (NavSpine
    drops localOnly items unless boot.is_true_local)."""
    src = []
    for path in (_REPO / "gallery" / "src").rglob("*"):
        if path.suffix in (".jsx", ".js"):
            src.append(path.read_text(encoding="utf-8"))
    joined = "\n".join(src)
    assert "\U0001f310" not in joined, (
        "a globe glyph is back in the React shell -- if the LAN chip was rebuilt, the "
        "Glossary entry this test guards should name it again")
    navspine = _read("gallery/src/components/NavSpine.jsx")
    assert re.search(r"localOnly\s*&&\s*!boot\.is_true_local", navspine), (
        "NavSpine no longer withholds local-only items, which is what the corrected "
        "Glossary entry describes a LAN session by")

    entry = _glossary_entry("LAN session")
    assert "\U0001f310" not in entry and "chip" not in entry.lower(), (
        "wiki/Glossary.md still tells the reader to look for a LAN session chip in the "
        "header; nothing in the React shell draws one")


def test_glossary_puts_activity_where_the_shell_actually_mounts_it():
    """ActivityChip mounts in SeparatorBar -- the sticky header bar under the banner -- at
    whichever outer edge act.edge names, and again in the Loom's top bar. It is not, and
    has never been in the React shell, a bottom-left button."""
    sep = _read("gallery/src/components/SeparatorBar.jsx")
    assert "<ActivityChip" in sep, (
        "the Activity chip no longer mounts in the separator bar -- re-check the Glossary")
    loom = _read("loom/master-storyboard.jsx")
    assert "<ActivityChip" in loom, "the Loom no longer mounts the Activity chip"

    entry = _glossary_entry("Activity")
    assert "bottom-left" not in entry, (
        "wiki/Glossary.md still sends the reader to the bottom-left of the gallery for "
        "Activity; it sits at an end of the bar under the banner")
    assert "banner" in entry and "Loom" in entry, (
        "the Activity entry no longer says where the button is on either host")


# ---------------------------------------------------------------------------
# The Identity strip and the ✦ Branding tab are EITHER/OR states of one install,
# not two places that both exist: ControlPanelOverlay renders one or the other on
# a single brandingUnlocked ternary, and hides the tab button entirely while it is
# locked. Glossary entries that name either as a fixed location are therefore
# wrong for whichever state the reader's install is in -- on any given install at
# least two of them pointed at a screen that is not there (red team 2026-09-07).
# The wiki's own Control-Panel.md always carried the condition; the Glossary lost
# it. These pin both halves: the code's exclusivity, and the entries stating it.
# ---------------------------------------------------------------------------

def test_the_branding_tab_and_the_identity_strip_are_still_mutually_exclusive():
    """If this ever stops being one either/or, the Glossary wording below is the thing
    to revisit -- so the guard starts at the code, not at the prose."""
    cp = _read("gallery/src/components/ControlPanelOverlay.jsx")
    assert re.search(r"brandingUnlocked\s*&&\s*\(", cp), (
        "the ✦ Branding tab button is no longer gated on brandingUnlocked")
    assert re.search(r"brandingUnlocked\s*\?[\s\S]{0,900}<IdentityStrip", cp), (
        "the Identity strip is no longer the ELSE of a brandingUnlocked ternary -- if the "
        "strip and the tab can now coexist, the Glossary entries should say so instead")
    assert re.search(r'tab === "brand"\s*&&\s*brandingUnlocked', cp), (
        "the ✦ Branding tab body is no longer gated on brandingUnlocked")


def test_every_glossary_entry_about_branding_says_which_state_it_belongs_to():
    """Four entries locate controls in the Identity strip or the ✦ Branding tab (plus the
    Control Panel entry, which used to name Maintenance as the only tab). Each must carry
    the earned/unearned condition, or it is false for half the installs that read it."""
    for term in ("the banner", "the Control Panel", "the Identity strip", "the mark", "skin"):
        entry = _glossary_entry(term)
        assert "Under the Hood" in entry, (
            "wiki/Glossary.md's \"" + term + "\" entry locates a branding control without "
            "saying whether it means an install that has earned Under the Hood or one that "
            "has not -- the strip and the ✦ Branding tab never both exist")

    strip = _glossary_entry("the Identity strip")
    assert re.search(r"replaced by", strip), (
        "the Identity strip entry no longer says the ✦ Branding tab replaces it, so a reader "
        "who has earned Under the Hood will still go looking for the strip")
