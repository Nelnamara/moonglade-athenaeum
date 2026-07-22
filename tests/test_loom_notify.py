"""The Loom shell must load the shared mg-notify.js (Ach/Toast/Jobs/JobsCard) and carry the
two DOM anchors JobsCard needs to render the activity tray -- a cheap regression guard against
this shell edit being silently reverted (the achievement-toast path needs no anchor at all,
see mg-notify.js's own top-of-file comment; only the visible Job Tracker card does)."""
from pathlib import Path

import pixai_gallery
from tests.conftest import login_client


def test_loom_shell_loads_shared_notify_script_and_anchors(tmp_path):
    cli = login_client(tmp_path)
    body = cli.get("/loom").get_data(as_text=True)
    assert '<script src="/static/mg-notify.js"></script>' in body
    assert 'id="jobs-fab"' in body
    assert 'id="jobs-tray"' in body


def test_loom_shell_lifts_activity_and_help_widgets_above_the_overlay(tmp_path):
    """LoomV2's .lv-overlay (z-index:400, opaque) buried the Activity chip (#jobs-fab, z234
    from mg-notify.js) and the ? help FAB (#eb-help-btn, z300) so both were invisible on /loom
    though the wiki documents them as usable there. The shell now lifts them just above 400
    (401/402), Loom-scoped -- mg-notify.js keeps its base 234 so the gallery is untouched."""
    cli = login_client(tmp_path)
    body = cli.get("/loom").get_data(as_text=True)
    # the Loom-only <style> override lifts the shared jobs widgets over .lv-overlay(400)
    assert "#jobs-fab  { z-index: 401 !important; }" in body
    assert "#jobs-tray { z-index: 402 !important; }" in body
    # the shell-only help FAB + its modal clear it too (401/402, not the old 300/301)
    assert "right:18px;z-index:401;width:38px" in body                # #eb-help-btn
    assert "inset:0;z-index:402;background:rgba(6,4,16,.72)" in body   # #eb-help modal
    # the raise is Loom-scoped: mg-notify.js still ships the base 234 (gallery unaffected)
    notify = (Path(pixai_gallery.__file__).parent / "static" / "mg-notify.js").read_text(encoding="utf-8")
    assert "z-index:234" in notify
    assert "z-index:401" not in notify and "z-index:402" not in notify


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
    """Option 2 of the decision the owner left open (docs/STATE.md, "The Prompt textarea is
    the one piece deliberately held back"): give base-prompt editing a home in Deep Focus,
    rather than let every hand-typed prompt become a frozen override.

    It must write `prompt` (the base string shotText() keeps recomposing from), NOT
    promptOverrideText -- writing the override from here would be the very outcome the
    field was held back to avoid.
    """
    block = _deep_focus_block(_jsx())
    assert "c.prompt" in block, "Deep Focus renders no base-prompt field"
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
    assert "lv-overrideflash" in block, (
        "Deep Focus fires the flash but never renders it -- the panel's copy is behind the "
        "veil, so the user sees nothing")
