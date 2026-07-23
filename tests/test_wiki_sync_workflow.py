"""The wiki push used to be a manual `git clone` + copy + commit + push, done by hand
tonight (a74b0d1) after the published wiki silently drifted 4 releases / 6 days stale.
Owner decision D-10: automate it so that can't happen a second time. This doesn't (can't)
exercise a real push to the wiki repo -- that's only provable by a real Actions run -- but
it locks in the pieces that must exist for the automation to have any chance of working,
so a future edit can't silently strip the trigger or the permissions line without a test
noticing."""
from pathlib import Path

_WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "wiki-sync.yml"


def test_wiki_sync_workflow_exists_and_is_wired_up():
    text = _WORKFLOW.read_text(encoding="utf-8")
    assert "tags:" in text and "v*" in text            # fires on release tags
    assert "contents: write" in text                    # or the push silently no-ops (default is read-only)
    assert ".wiki.git" in text                          # actually targets the wiki repo, not the main one
    assert "wiki/*.md" in text or "wiki-repo/*.md" in text   # actually copies the real source dir
    assert "workflow_dispatch" in text                  # can be smoke-tested without waiting for a real tag
