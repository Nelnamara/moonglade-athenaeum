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
