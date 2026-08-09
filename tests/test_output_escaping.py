"""Server-rendered output must never concatenate server- or user-provided free text into
HTML unescaped. A reflected query value or a catalog field rendered raw is an injection
sink -- the value is not markup and must not be parsed as markup.

History (classic cut, 2026-08-08): the original tests here pinned the escH2 escaper on the
classic Control Panel and detail pages. Those templates (and escH2 with them) were deleted
when the classic UI was cut -- the React shell renders those surfaces now. What SURVIVES is
/contact-sheet: the print view is assembled with str.format(), NOT render_template_string,
so it gets NONE of Jinja's autoescaping -- every catalog/query value interpolated into it
is escaped by hand with markupsafe.escape. These are the CI-safe regression guards for that
surface: they fetch the actual served bytes with a crafted payload and pin that it comes
back as inert entities, so a future edit that drops an escape() call fails here.
"""
from moonglade_gallery import CATALOG_FIELDS, save_catalog
from tests.conftest import login_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _seed(tmp_path, **kw):
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="55", filename="a_55.png",
                       created_at="2025-01-01T00:00:00", **kw)])


def test_contact_sheet_neutralises_reflected_collection_name(tmp_path):
    """?collection= is reflected into the sheet's <title> and header bar. The page is
    str.format()-built (no autoescaping), so a crafted collection name must come back
    as entities -- visible text -- never as live markup in the logged-in session."""
    _seed(tmp_path)
    payload = "<script>alert(1)</script><img src=x onerror=alert(2)>"
    html = login_client(tmp_path).get(
        "/contact-sheet", query_string={"collection": payload}
    ).get_data(as_text=True)

    # the raw payload must not appear anywhere in the served bytes...
    assert "<script>alert(1)</script>" not in html
    assert "<img src=x onerror=alert(2)>" not in html
    # ...only its escaped, inert form does
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_contact_sheet_escapes_media_id_in_attributes(tmp_path):
    """media_id is interpolated into single-quoted src='...' attributes on the grid
    (/thumbs/) and photo (/full/) formats. markupsafe.escape covers ' and " -- which
    these attributes depend on -- so a hostile catalog value can't break out of the
    attribute and plant an onerror handler."""
    evil = "55' onerror='alert(1)"
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id=evil, filename="a_55.png",
                       created_at="2025-01-01T00:00:00")])
    cli = login_client(tmp_path)

    for fmt in ("letter", "photo"):
        html = cli.get("/contact-sheet",
                       query_string={"ids": evil, "format": fmt}
                       ).get_data(as_text=True)
        # the quote must never survive raw inside the attribute...
        assert "' onerror='" not in html, "unescaped attribute breakout ({})".format(fmt)
        # ...it is entity-escaped in place, keeping the whole value inside src='...'
        assert "55&#39; onerror=&#39;alert(1)" in html, \
            "escaped media_id missing from served bytes ({})".format(fmt)


def test_contact_sheet_escapes_caption_date(tmp_path):
    """The grid captions render created_at[:10] from the catalog. Ten characters is
    still enough for markup-significant text -- pin that it goes through escape()."""
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="55", filename="a_55.png",
                       created_at="<b>&\"'x</b>ignored")])
    html = login_client(tmp_path).get(
        "/contact-sheet", query_string={"ids": "55", "captions": "1"}
    ).get_data(as_text=True)

    assert "<div class='cap'><b>" not in html          # raw sink gone
    assert "&lt;b&gt;&amp;&#34;&#39;x" in html         # entity-escaped caption
