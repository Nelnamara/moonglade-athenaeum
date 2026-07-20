"""Server-rendered pages must never concatenate server- or user-provided free text into
innerHTML unescaped. An upstream exception string (the API handlers return str(e)[:200]) or
a job label reflected raw into innerHTML is an injection sink -- the value is not markup and
must not be parsed as markup.

These are the CI-safe regression guards: they fetch the actual served bytes and pin the
escaper (or textContent) at each sink, so a future edit that drops it fails here. The
belt-and-suspenders proof that a crafted payload does NOT execute is a Playwright pass, which
can't run in CI (no browser); it lives in the verification harness instead.
"""
from pixai_gallery import CATALOG_FIELDS, create_app, save_catalog
from tests.conftest import login_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _seed(tmp_path, **kw):
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="55", filename="a_55.png",
                       created_at="2025-01-01T00:00:00", **kw)])


def test_panel_escapes_job_error_and_label(tmp_path):
    """The Control Panel's job-status line renders d.error and d.label from the server.
    Both must go through escH2 (the page's HTML escaper), not raw concatenation."""
    _seed(tmp_path)
    html = login_client(tmp_path).get("/panel").get_data(as_text=True)

    # The escaper is applied at every dynamic sink...
    assert "escH2(d.error)" in html
    assert "escH2(d.label" in html
    # ...and the exact raw concatenations that used to be here are gone. `+d.error+`
    # (a bare +, not the `(d.error)` escH2 wraps it in) is the tell of an unescaped sink.
    assert "+d.error+'</span>'" not in html
    assert "running: '+d.label+'" not in html
    assert "'\\u2713 '+(d.label||'job')+'" not in html   # done-line label, now escH2-wrapped


def test_detail_suggest_prompt_error_is_text_not_html(tmp_path):
    """The image detail page's "Suggest prompt" error path builds a TEXT node -- the page
    has no escaper in scope, so it must not use innerHTML for the server's error string."""
    _seed(tmp_path)
    html = login_client(tmp_path).get("/image/55").get_data(as_text=True)

    assert "em.textContent = d.error" in html
    # the old raw innerHTML sink must be gone
    assert "(d.error || 'No suggestion returned.') + '</span>'" not in html


def test_a_crafted_error_would_be_neutralised_as_literal_text(tmp_path):
    """Documents the property the guards above defend, without a browser: escH2 turns the
    markup-significant characters of a crafted payload into entities, so it can only ever
    render as visible text, never as a live <img onerror> / <script>."""
    import re
    _seed(tmp_path)
    html = login_client(tmp_path).get("/panel").get_data(as_text=True)
    m = re.search(r"function escH2\(s\)\{(.+?)\}", html)
    assert m, "escH2 escaper not found on the panel page"
    body = m.group(1)
    for pair in ("&/g,'&amp;'", "</g,'&lt;'", ">/g,'&gt;'", '"/g,\'&quot;\''):
        assert pair in body, "escH2 no longer escapes {}".format(pair)
