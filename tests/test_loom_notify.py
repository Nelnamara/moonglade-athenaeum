"""The Loom shell must load the shared mg-notify.js (Ach/Toast/Jobs/JobsCard) and carry the
two DOM anchors JobsCard needs to render the activity tray -- a cheap regression guard against
this shell edit being silently reverted (the achievement-toast path needs no anchor at all,
see mg-notify.js's own top-of-file comment; only the visible Job Tracker card does)."""
from pixai_gallery import create_app


def test_loom_shell_loads_shared_notify_script_and_anchors(tmp_path):
    cli = create_app(tmp_path).test_client()
    body = cli.get("/loom").get_data(as_text=True)
    assert '<script src="/static/mg-notify.js"></script>' in body
    assert 'id="jobs-fab"' in body
    assert 'id="jobs-tray"' in body
