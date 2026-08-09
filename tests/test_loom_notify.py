"""The Loom shell and the shared notify system (Ach/Toast/Jobs/Activity) -- a cheap
regression guard on the contract between them. Ported 2026-08-08 (no-vanilla campaign,
component 6): static/mg-notify.js is DELETED; the notify system now lives in React at
gallery/src/notify/ and rides the Loom's own bundle (loom/dist/master-storyboard.bundle.js
+ .css), so the shell must NOT load the old script or ship the old anchor divs.

RE-PORT 2026-08-09 (Claude Design handoff, drift item 39): the floating #jobs-fab/#jobs-tray
(portaled to body by <ActivityTray>, same ids on both hosts, needing the shell's own Loom-
scoped z-index/bottom !important overrides to clear .lv-overlay) is retired entirely.
<ActivityTray>.jsx is deleted; the Activity control is now inline in each host's own header
(gallery/src/components/SeparatorBar.jsx's `.mgx-act-wrap`, the Loom toolbar's
`.lv-top-act-wrap` in master-storyboard.jsx) -- a normal DOM descendant on the Loom, not a
body-level sibling, so it needs none of the old !important reconciliation at all."""
import re
from pathlib import Path

import moonglade_gallery
from tests.conftest import login_client


def test_loom_shell_loads_shared_notify_script_and_anchors(tmp_path):
    # Port note 2026-08-08: this test used to assert the OPPOSITE -- that the shell loads
    # /static/mg-notify.js and carries the #jobs-fab/#jobs-tray anchor divs. Both are gone
    # on purpose (the bundle carries notify; React renders the anchors), so the guard now
    # points the other way: a reappearing script tag or anchor div means the shell edit
    # was reverted to the vanilla wiring.
    #
    # Re-port 2026-08-09: the ids themselves are retired now (drift item 39) -- the Activity
    # control lives inline in the toolbar, not portaled to body -- so there is no longer a
    # z-index override for the shell to carry for them at all; asserting their absence covers
    # both "reverted to vanilla" and "reverted to the 2026-08-08 floating-tray shape".
    cli = login_client(tmp_path)
    body = cli.get("/loom").get_data(as_text=True)
    assert "/static/mg-notify.js" not in body, (
        "the Loom shell references the deleted mg-notify.js -- the React bundle carries "
        "the notify system now")
    assert 'id="jobs-fab"' not in body and 'id="jobs-tray"' not in body, (
        "the shell ships its own anchor divs, or the retired floating Activity tray's ids "
        "reappeared -- the Activity control is inline in the toolbar now, not body-portaled")
    assert "z-index: 401 !important" not in body and "z-index: 402 !important" not in body, (
        "a Loom-scoped z-index override for the old floating tray reappeared -- the inline "
        "Activity control (.lv-top-act-wrap) is a normal .lv-overlay descendant and needs none")


def test_loom_shell_lifts_help_widget_above_the_overlay(tmp_path):
    """LoomV2's .lv-overlay (z-index:400, opaque) buried the ? help FAB (#eb-help-btn, z300)
    so it was invisible on /loom though the wiki documents it as usable there. The shell
    lifts it just above 400 (401/402), Loom-scoped.

    Re-port note 2026-08-09 (Claude Design handoff, drift item 39): this test used to also
    cover the Activity chip (#jobs-fab, same 401/402 lift) -- that control is retired, and
    its replacement never needed the lift in the first place (it's an inline .lv-overlay
    descendant now, not a body-portaled sibling racing the same z-index). This test now
    covers only what's still real: the help FAB, which is unrelated to the Activity control
    and was never part of that retirement.
    """
    cli = login_client(tmp_path)
    body = cli.get("/loom").get_data(as_text=True)
    # the shell-only help FAB + its modal clear .lv-overlay(400) via 401/402 (not the old 300/301)
    assert "right:18px;z-index:401;width:38px" in body                # #eb-help-btn
    assert "inset:0;z-index:402;background:rgba(6,4,16,.72)" in body   # #eb-help modal
    # notify.css no longer ships a base 234/235 at all -- there is no floating tray left to
    # lift, on either host.
    css = _notify_css()
    assert "z-index:234" not in css and "z-index:235" not in css


# ---------------------------------------------------------------------------
# Deep Focus owns the base prompt too
# ---------------------------------------------------------------------------

def _jsx():
    return (Path(__file__).resolve().parents[1] / "loom" / "master-storyboard.jsx").read_text(encoding="utf-8")


def _deep_focus_block(src):
    """The Deep Focus render, from its veil to the frames row."""
    start = src.index('className="lv-df-veil"')
    end = src.index('className="lv-df-frames"', start)
    return src[start:end]


def test_deep_focus_has_a_prompt_field_writing_the_base_prompt():
    """Deep Focus gives base-prompt editing a real home, rather than letting every
    hand-typed prompt become a frozen override.

    It must write `prompt` (the base string shotText() keeps recomposing from), NOT
    promptOverrideText -- writing the override from here would be the very outcome the
    field was held back to avoid.
    """
    block = _deep_focus_block(_jsx())
    # The exact value-binding, not a bare "c.prompt" substring -- that also matches
    # inside the identifier c.promptOverride (a different field entirely) and inside
    # a nearby comment's prose ("a second surface writing c.prompt"), so the old check
    # passed even with the real textarea's value binding deleted.
    assert "value={c.prompt " in block, "Deep Focus renders no base-prompt field bound to value={c.prompt ...}"
    assert "clearPromptOverride" in block, (
        "the Deep Focus prompt field does not clear an active override -- typing a base "
        "prompt while an override is live would leave the override silently winning")
    assert "setPromptOverride" not in block, (
        "Deep Focus is writing promptOverrideText. It must write the composable base "
        "`prompt`; the frozen override belongs to the drawer alone.")


def test_deep_focus_prompt_edit_is_not_silent_about_destroying_an_override():
    """The panel's own override-cleared notice renders inside the right panel, which sits
    BEHIND .lv-df-veil (z-450) while Deep Focus is open. So Deep Focus needs its own copy,
    or editing here destroys an override with no visible signal -- reintroducing exactly the
    silent-until-you-notice hazard that flash was added to prevent.

    Bite: delete the lv-overrideflash line from the Deep Focus block and this fails.
    """
    block = _deep_focus_block(_jsx())
    assert "setOverrideClearedFlash" in block, (
        "Deep Focus clears overrides without flashing the notice")
    # The real rendered element, not a bare "lv-overrideflash" substring -- a nearby
    # comment ("renders at .lv-overrideflash inside the right panel...") contains that
    # same substring, so deleting only the real render line used to leave this passing.
    assert '<div className="lv-overrideflash">' in block, (
        "Deep Focus fires the flash but never renders it -- the panel's copy is behind the "
        "veil, so the user sees nothing")


# ---------------------------------------------------------------------------
# The activity card shows words, not internal identifiers
# ---------------------------------------------------------------------------
# Port note 2026-08-08: these read static/mg-notify.js until the React port. The kind
# mapping now lives in gallery/src/notify/format.js (pure, exported) and the row render
# in gallery/src/notify/ActivityTray.jsx; the injected-CSS block became
# gallery/src/styles/notify.css. Same assertions, retargeted.

def _notify_dir():
    return Path(__file__).resolve().parents[1] / "gallery" / "src" / "notify"


def _format_js():
    return (_notify_dir() / "format.js").read_text(encoding="utf-8")


def _tray_jsx():
    # Re-port note 2026-08-09: ActivityTray.jsx (the floating tray) is deleted; the row
    # render it used to own lives in ActivityRow.jsx now (one row per host's own dropdown).
    return (_notify_dir() / "ActivityRow.jsx").read_text(encoding="utf-8")


def _notify_css():
    """notify.css with its comments stripped -- RULES only. The file's own header narrates
    the Loom shell's `#jobs-fab{z-index:401}` override in prose, so matching against the
    raw text finds the comment before the real rule (bit this port's first run)."""
    raw = (Path(__file__).resolve().parents[1] / "gallery" / "src" / "styles" / "notify.css").read_text(encoding="utf-8")
    return re.sub(r"/\*.*?\*/", "", raw, flags=re.S)


def test_activity_rows_translate_the_job_type_instead_of_printing_the_enum():
    """`j.type` is an internal enum ('cli', 'panel', 'generate', 'delete', 'import') and the
    row's sub-line used to print it raw under `.jt-kind{text-transform:capitalize}` -- which
    rendered the non-word "Cli" under every terminal-run job.

    Bite: put `j.type` back in the sub-line raw and this fails.
    """
    # The render half: the sub-line goes through kindLabel, not the raw enum.
    assert "kindLabel(j.type)" in _tray_jsx(), "the sub-line still prints the raw job type enum"
    # The mapping half: format.js owns KIND_LABEL (double-quoted strings there, so the old
    # single-quote probe is updated with it).
    js = _format_js()
    assert 'cli: "Terminal"' in js, "no display name for the 'cli' job type"
    # Every type any writer actually emits needs a mapping, or it leaks through capitalized.
    for kind in ("cli", "panel", "generate", "delete", "import"):
        assert ("%s:" % kind) in js or ("'%s':" % kind) in js, (
            "job type %r has no display name in KIND_LABEL" % kind)


def test_cli_jobs_are_labelled_in_words_not_command_slugs():
    """The activity row's title is `j.label`, and _cli_job_finish never relabels -- so a
    label set at start is what the user reads forever. Passing the bare command name put
    "generate-video" in a list beside real sentences, and the notify system's completion
    toast is built as `label + " — done"`, so it also popped "generate-video — done".

    Noun phrases on purpose: the same string has to read correctly while running, when done,
    and inside that toast.
    """
    src = (Path(__file__).resolve().parents[1] / "moonglade_backup.py").read_text(encoding="utf-8")
    # Checked as exact call forms rather than by scanning the argument text: the download
    # site reads `"Incremental update" if getattr(args, "update", False) else "Full backup"`,
    # and a naive search for the slug "update" matches that getattr's ATTRIBUTE NAME, which
    # is correct code. (Cost me one red test to notice.)
    banned = ['_cli_job_start(out, "generate")',
              '_cli_job_start(out, "generate-video")',
              '_cli_job_start(out, "sync")',
              '_cli_job_start(out, "update" if']
    for call in banned:
        assert call not in src, (
            "CLI job still labelled with a raw command slug: %s -- the activity card and "
            "its completion toast both render this verbatim" % call)
    for label in ('"Image generation"', '"Video render"', '"Library sync"',
                  '"Incremental update"', '"Full backup"'):
        assert label in src, "expected human CLI job label %s is missing" % label


def test_notify_components_do_not_inherit_their_font_from_the_host_page():
    """The same Activity card rendered in two different typefaces depending on the page.

    #jobs-fab / #jobs-tray / #mg-toasts set font-SIZE but used to inherit font-FAMILY, and
    the two hosts disagree: the gallery's BASE_HTML body declares `system-ui, sans-serif`,
    while _LOOM_SHELL's body set only background and margin. Those three were siblings of
    #root in that shell, so on /loom they inherited nothing and fell back to the browser
    default. The notify system is host-neutral by design, so the component owns this.

    The original 2026-07-21 fix covered only those three roots; the achievement celebration
    (.ach-m2) had the exact same gap and got the same fix afterward.

    Port note 2026-08-08: retargeted from mg-notify.js's injected CSS to
    gallery/src/styles/notify.css. #ach-modal (the Folio of Honors / Trophy Hall subtree)
    is DROPPED from the list -- that modal's machinery was retired as dead code in the
    React port (no served page carries the #ach-modal skeleton; the React Folio replaced
    it) and notify.css deliberately did not carry its rules forward.

    Re-port note 2026-08-09 (Claude Design handoff, drift item 39): #jobs-fab/#jobs-tray ->
    .at-chip/.at-panel (the Activity control's new trigger + dropdown). Both are now inline
    in each host's own header, no longer body-level siblings of #root -- but the self-
    declared font-family stays on principle (the component is still host-neutral by design,
    and a future change could re-portal or relocate either piece without anyone remembering
    to re-add this).

    Bite: drop font-family from any of the four roots and this fails, naming it.
    """
    css = _notify_css()
    for sel in (".at-chip{", ".at-panel{", "#mg-toasts{", ".ach-m2{"):
        i = css.index(sel)
        rule = css[i:css.index("}", i)]
        assert "font-family" in rule, (
            "%s does not state its own font-family -- it will inherit the host page's, and "
            "the gallery and the Loom shell do not agree" % sel.rstrip("{"))


def test_loom_shell_body_declares_a_font_for_what_mounts_outside_root():
    """The shell mounts the Activity chip/tray, the toasts and the ? FAB outside #root, so
    they inherit from body, not from .sb-root's own font-family. Belt to notify.css's braces
    (mg-notify's, pre-port): the shell should not hand anything an unstyled baseline."""
    src = (Path(__file__).resolve().parents[1] / "moonglade_gallery.py").read_text(encoding="utf-8")
    shell = src[src.index("_LOOM_SHELL = r"):]
    body_rule = shell[shell.index("body {"):shell.index("}", shell.index("body {"))]
    assert "font-family" in body_rule, (
        "_LOOM_SHELL's body has no font-family; anything mounted outside #root falls back "
        "to the browser default")
