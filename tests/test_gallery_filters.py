"""Tests for gallery search/filter logic: wildcard search, multi-word AND,
year dropdowns, and per-page (via query_catalog)."""
import pytest

from moonglade_gallery import (CATALOG_FIELDS, init_db, save_catalog, query_catalog,
                           catalog_years, _like_pattern, collection_health, _role_dir)


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "catalog.db"
    save_catalog(p, [
        _row(media_id="1", filename="a_1.png", prompt_preview="night elf druid",
             created_at="2024-03-10T00:00:00", model_name="ModelA", task_id="744376191043610001"),
        _row(media_id="2", filename="b_2.png", prompt_preview="nighttime city",
             created_at="2025-07-01T00:00:00", model_name="ModelB", task_id="744376191043610002"),
        _row(media_id="3", filename="c_3.png", prompt_preview="bright morning",
             created_at="2026-01-05T00:00:00", model_name="ModelA", task_id="744376191043610003"),
    ])
    return p


# ---- _like_pattern ---------------------------------------------------------

def test_like_plain_word_is_substring():
    assert _like_pattern("elf") == "%elf%"


def test_like_star_becomes_percent():
    # A trailing star collapses into the substring wrap rather than anchoring the
    # pattern to the start of the whole prompt. This assertion is the inverse of
    # what it used to be ("night%") -- see _like_pattern's docstring: the old
    # prefix semantics meant adding a wildcard could EMPTY a working search.
    assert _like_pattern("night*") == "%night%"
    assert _like_pattern("*night") == "%night%"


def test_like_interior_wildcards_still_constrain():
    """Wildcards keep their power in the middle, which is where they're useful."""
    assert _like_pattern("moon*light") == "%moon%light%"
    assert _like_pattern("a?c") == "%a_c%"


def test_like_escapes_literal_percent():
    # a literal % the user types must be escaped, not treated as wildcard
    assert _like_pattern("50%") == "%50\\%%"


# ---- search behavior -------------------------------------------------------

def test_substring_search_matches_both_night(db):
    rows, total = query_catalog(db, q="night")
    assert total == 2  # "night elf" and "nighttime"


def test_wildcard_search_matches_substring(db):
    rows, total = query_catalog(db, q="night*")
    assert total == 2


def test_a_wildcard_never_narrows_a_search(db):
    """THE invariant, and the one that was violated. Users expect a wildcard to
    broaden a search or leave it alone -- never to shrink it. Previously a
    wildcard turned the term into the whole pattern, anchored to the start of the
    prompt, so `sample` matched 24 rows in the crawl fixture while `sampl*`
    matched 0. Property-checked rather than spot-checked so a future change to
    the pattern builder has to preserve it for every one of these shapes."""
    for bare, wild in [("night", "night*"), ("night", "*night"), ("night", "nigh?"),
                       ("elf", "elf*"), ("druid", "*druid*")]:
        _, bare_total = query_catalog(db, q=bare)
        _, wild_total = query_catalog(db, q=wild)
        assert wild_total >= bare_total, (
            "'{}' returned {} rows but '{}' returned only {} -- a wildcard must "
            "never narrow a search".format(bare, bare_total, wild, wild_total))


def test_multiword_is_anded(db):
    rows, total = query_catalog(db, q="night druid")
    assert total == 1  # only "night elf druid" has both


def test_multiword_no_match(db):
    rows, total = query_catalog(db, q="night morning")
    assert total == 0


def test_search_matches_long_task_id_exactly(db):
    rows, total = query_catalog(db, q="744376191043610002")
    assert total == 1
    assert rows[0]["media_id"] == "2"


def test_search_matches_media_id_exactly(db):
    rows, total = query_catalog(db, q="12345678")
    assert total == 0  # no fixture row has this id -- confirms it's an exact match, not substring


def test_short_numeric_term_does_not_id_match(db):
    # A short digit term (under the length gate) must NOT substring-match ids by chance --
    # it should only ever search prompt text. None of the fixture prompts contain "3".
    rows, total = query_catalog(db, q="3")
    assert total == 0


# ---- date range (YYYY-MM comparison) --------------------------------------

def test_date_from_filters(db):
    rows, total = query_catalog(db, date_from="2025-01")
    assert total == 2  # 2025 and 2026


def test_date_range_inclusive(db):
    rows, total = query_catalog(db, date_from="2024-01", date_to="2024-12")
    assert total == 1


def test_catalog_years_descending(db):
    assert catalog_years(db) == [2026, 2025, 2024]


# ---- per-page (page_size) --------------------------------------------------

def test_page_size_limits_rows(db):
    rows, total = query_catalog(db, page_size=2, page=1)
    assert len(rows) == 2 and total == 3


def test_page_size_second_page(db):
    rows, total = query_catalog(db, page_size=2, page=2)
    assert len(rows) == 1 and total == 3


# ---- rating filter + new sorts --------------------------------------------

def test_rating_min_filters(tmp_path):
    p = tmp_path / "catalog.db"
    save_catalog(p, [
        _row(media_id="1", filename="a_1.png", rating="5", created_at="2024-01-01"),
        _row(media_id="2", filename="b_2.png", rating="2", created_at="2024-01-02"),
        _row(media_id="3", filename="c_3.png", rating="",  created_at="2024-01-03"),
    ])
    assert query_catalog(p, rating_min=3)[1] == 1
    assert query_catalog(p, rating_min=1)[1] == 2
    assert query_catalog(p, rating_min=0)[1] == 3


def test_sort_pixels_orders_by_area(tmp_path):
    p = tmp_path / "catalog.db"
    save_catalog(p, [
        _row(media_id="small", filename="s_small.png", width="100", height="100"),
        _row(media_id="big",   filename="b_big.png",   width="800", height="800"),
    ])
    rows, _ = query_catalog(p, sort="pixels")
    assert rows[0]["media_id"] == "big"


def test_sort_aesthetic_and_likes(tmp_path):
    p = tmp_path / "catalog.db"
    save_catalog(p, [
        _row(media_id="lo", filename="lo.png", aes_score="3.2", liked_count="1"),
        _row(media_id="hi", filename="hi.png", aes_score="8.9", liked_count="50"),
    ])
    assert query_catalog(p, sort="aes_desc")[0][0]["media_id"] == "hi"
    assert query_catalog(p, sort="aes_asc")[0][0]["media_id"] == "lo"
    assert query_catalog(p, sort="likes")[0][0]["media_id"] == "hi"


# ---- collection_health -----------------------------------------------------

def test_collection_health_counts_and_missing(tmp_path):
    db = tmp_path / "catalog.db"
    # one row whose file exists, one whose file is missing on disk
    save_catalog(db, [
        _row(media_id="111", filename="111.webp", prompt_full="a full prompt",
             created_at="2024-03-01", model_name="ModelA", rating="4"),
        _row(media_id="222", filename="b_222.webp", created_at="2024-03-02",
             model_name="ModelA"),
    ])
    (tmp_path / "2024-03").mkdir()
    (tmp_path / "2024-03" / "111.webp").write_bytes(b"data")
    h = collection_health(tmp_path, db)
    assert h["total_files"] == 1
    assert h["catalog_rows"] == 2
    assert h["with_full_meta"] == 1
    assert h["rated"] == 1
    assert h["missing"] == 1          # row 222 has no file on disk
    assert h["per_bucket"].get("month") == 1


def test_collection_health_excludes_deleted_and_branding(tmp_path):
    # _deleted/ (purge_media_local's recoverable trash) and the branding tree (UI art
    # assets, not user content) both used to be tallied into "Images on disk", inflating
    # it far past the Panel's catalog-row count — see the Health-vs-Panel discrepancy fix.
    # Re-pinned for bundle-v2: marks now live in their CODED dir (seeded via _role_dir,
    # never a retyped hex path). collection_health prunes the literal out_dir/"branding"
    # (kept for legacy installs), which covers the coded tree here because conftest's
    # _isolated_branding redirects branding_root() to tmp_path/"branding".
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="111", filename="111.webp", created_at="2024-03-01", model_name="ModelA"),
    ])
    (tmp_path / "2024-03").mkdir()
    (tmp_path / "2024-03" / "111.webp").write_bytes(b"data")
    (tmp_path / "_deleted").mkdir()
    (tmp_path / "_deleted" / "999.webp").write_bytes(b"data")
    _role_dir("marks").mkdir(parents=True)
    (_role_dir("marks") / "logo.png").write_bytes(b"data")
    h = collection_health(tmp_path, db)
    assert h["total_files"] == 1   # only the real, non-deleted, non-branding image counts


def test_collection_health_uncataloged_is_disk_minus_catalog(tmp_path):
    """Integrity job (audit 2026-07-21, Curator #9): uncataloged =
    on_disk_ids - catalog_ids, exactly. Fixture is built so the four candidate
    computations -- correct difference, the reverse difference, the union, and
    the intersection -- all land on DIFFERENT counts, so a directional bug
    (reporting catalog-not-on-disk, or a union/intersection instead of the
    disk-not-in-catalog difference) can't accidentally still pass:
      shared (on disk AND cataloged):      111            (1 id)
      disk-only (should BE 'uncataloged'): 999, 888       (2 ids)
      catalog-only (the OTHER direction,
        already covered by 'missing'):     222, 333, 444  (3 ids)
    correct answer (disk - catalog) = 2; reverse (catalog - disk) = 3;
    union = 6; intersection = 1 -- all distinct from each other."""
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="111", filename="111.webp", created_at="2024-03-01", model_name="ModelA"),
        _row(media_id="222", filename="222.webp", created_at="2024-03-01", model_name="ModelA"),
        _row(media_id="333", filename="333.webp", created_at="2024-03-01", model_name="ModelA"),
        _row(media_id="444", filename="444.webp", created_at="2024-03-01", model_name="ModelA"),
    ])
    (tmp_path / "2024-03").mkdir()
    (tmp_path / "2024-03" / "111.webp").write_bytes(b"data")   # shared: cataloged + on disk
    (tmp_path / "2024-03" / "999.webp").write_bytes(b"data")   # disk-only: on disk, no catalog row
    (tmp_path / "2024-03" / "888.webp").write_bytes(b"data")   # disk-only: on disk, no catalog row
    # 222/333/444 stay catalog-only: a row + filename, but no file ever placed on disk.
    h = collection_health(tmp_path, db)
    assert h["uncataloged"] == 2          # {999, 888} -- disk files with no catalog row
    assert h["missing"] == 3              # {222, 333, 444} -- the reverse direction, unaffected


def test_published_and_tag_filters(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="1", filename="a_1.png", is_published="1", art_tags="ContestX, elf"),
        _row(media_id="2", filename="b_2.png", is_published="1", art_tags="cityscape"),
        _row(media_id="3", filename="c_3.png", is_published="0", art_tags=""),
    ])
    assert query_catalog(db, published_only=True)[1] == 2
    assert query_catalog(db, art_tag="elf")[1] == 1
    assert query_catalog(db, art_tag="contestx")[1] == 1   # case-insensitive
    assert query_catalog(db, published_only=True, art_tag="city")[1] == 1


def test_media_type_filter(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="i1", filename="a.png"),
        _row(media_id="i2", filename="b.png"),
        _row(media_id="v1", filename="videos/x_v1.mp4", is_video="1"),
    ])
    assert query_catalog(db, media_type="video")[1] == 1
    assert query_catalog(db, media_type="image")[1] == 2
    assert query_catalog(db, media_type="")[1] == 3  # all


def test_catalog_model_options_most_used_first(tmp_path):
    from moonglade_gallery import catalog_model_options
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="1", filename="a.png", model_name="Tsubaki", model_id="111"),
        _row(media_id="2", filename="b.png", model_name="Tsubaki", model_id="111"),
        _row(media_id="3", filename="c.png", model_name="Dreamix", model_id="222"),
    ])
    opts = catalog_model_options(db)
    assert opts[0] == ("Tsubaki", "111")           # most-used first
    assert ("Dreamix", "222") in opts


def test_source_surfaced_per_item_in_library_api(tmp_path):
    """Ported from the classic grid's source badges (classic cut 2026-08-08):
    the per-row `source` the "sbadge gen/loc" markup rendered from must still
    reach the client -- it now rides each /api/next/library item, where the
    React grid draws its badge from."""
    from tests.conftest import login_client
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="g1", filename="a.png", source="api"),
        _row(media_id="l1", filename="b.png", source="local"),
    ])
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "a.png").write_bytes(b"x")
    (tmp_path / "images" / "b.png").write_bytes(b"x")
    d = login_client(tmp_path).get("/api/next/library").get_json()
    by = {i["media_id"]: i["source"] for i in d["items"]}
    assert by == {"g1": "api", "l1": "local"}


def test_source_filter(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="h1", filename="a.png"),                       # online (blank)
        _row(media_id="h2", filename="b.png", source="online"),      # explicit online
        _row(media_id="g1", filename="c.png", source="api"),         # generated
        _row(media_id="l1", filename="d.png", source="local"),       # imported
    ])
    assert query_catalog(db, source="online")[1] == 2   # blank + 'online'
    assert query_catalog(db, source="api")[1] == 1
    assert query_catalog(db, source="local")[1] == 1
    assert query_catalog(db, source="")[1] == 4         # all


def test_collections_add_remove_filter(tmp_path):
    from moonglade_gallery import (add_to_collection, remove_from_collection,
                               unique_collections)
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id=m, filename=m + ".png") for m in ("a", "b", "c")])
    assert add_to_collection(db, ["a", "b"], "Elf Portraits") == 2
    assert add_to_collection(db, ["a"], "Elf Portraits") == 0      # already in -> no-op
    assert add_to_collection(db, ["a"], "Favorites") == 1          # multiple per image
    assert unique_collections(db) == ["Elf Portraits", "Favorites"]
    assert query_catalog(db, collection="Elf Portraits")[1] == 2
    assert query_catalog(db, collection="Favorites")[1] == 1
    # exact-token match: "Elf" must NOT match "Elf Portraits"
    assert query_catalog(db, collection="Elf")[1] == 0
    assert remove_from_collection(db, ["a"], "Elf Portraits") == 1
    assert query_catalog(db, collection="Elf Portraits")[1] == 1


def test_collection_add_route(tmp_path):
    from moonglade_gallery import load_catalog
    from tests.conftest import login_client
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="m1", filename="a.png"), _row(media_id="m2", filename="b.png")])
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "a.png").write_bytes(b"x")
    (tmp_path / "images" / "b.png").write_bytes(b"x")
    client = login_client(tmp_path)
    r = client.post("/api/collection", json={"action": "add", "collection": "Moonlit",
                                             "media_ids": ["m1", "m2"]})
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True and d["count"] == 2
    by = {x["media_id"]: x for x in load_catalog(db)}
    assert by["m1"]["collections"] == "Moonlit"


def test_collection_remove_route(tmp_path):
    """The remove path (classic cut 2026-08-08 -- the filter-bar button and its
    /collection-remove form route died with the classic page; /api/collection
    action=remove is the one remove surface now): the route drops the label
    without touching the row, and never bleeds onto the other member."""
    from moonglade_gallery import load_catalog, add_to_collection
    from tests.conftest import login_client
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="m1", filename="a.png"), _row(media_id="m2", filename="b.png")])
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "a.png").write_bytes(b"x")
    (tmp_path / "images" / "b.png").write_bytes(b"x")
    add_to_collection(db, ["m1", "m2"], "Moonlit")
    client = login_client(tmp_path)

    r = client.post("/api/collection", json={"action": "remove", "collection": "Moonlit",
                                             "media_ids": ["m1"]})
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "count": 1}
    by = {x["media_id"]: x for x in load_catalog(db)}
    assert by["m1"]["collections"] == ""      # label gone
    assert by["m2"]["collections"] == "Moonlit"   # untouched
    assert query_catalog(db, collection="Moonlit")[1] == 1


def test_deleted_remote_filter(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="a", filename="a.png", deleted_remote="1"),
        _row(media_id="b", filename="b.png"),
    ])
    assert query_catalog(db, source="deleted")[1] == 1   # only the flagged one


def test_lora_filter(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="1", filename="a.png", loras="Detail Tweaker:0.7, Anime:0.5"),
        _row(media_id="2", filename="b.png", loras="Anime:0.6"),
        _row(media_id="3", filename="c.png", loras=""),
    ])
    assert query_catalog(db, lora="anime")[1] == 2
    assert query_catalog(db, lora="detail")[1] == 1


def test_full_image_and_export_zip_routes(tmp_path):
    import io
    import zipfile
    from tests.conftest import login_client
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="111", filename="a_111.png", prompt_preview="p")])
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "a_111.png").write_bytes(b"\x89PNG\r\n\x1a\nfakeimage")
    client = login_client(tmp_path)

    r = client.get("/full/111")
    assert r.status_code == 200
    assert r.headers.get("Cache-Control") == "public, max-age=31536000, immutable"
    assert client.get("/full/nope").status_code == 404

    z = client.post("/export-zip", data={"media_ids": "111"})
    assert z.status_code == 200 and z.headers["Content-Type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(z.data)).namelist()
    assert names == ["a_111.png"]
    assert client.post("/export-zip", data={"media_ids": "ghost"}).status_code == 404


def test_export_zip_converts_format_without_touching_the_original(tmp_path):
    """Convert-and-download: fmt=jpeg re-encodes into the ZIP only. THE decided-shape
    guarantee -- the original file on disk is byte-for-byte unchanged and no converted copy
    lands in the archive, so a download transform never re-enters the catalog."""
    import io
    import zipfile
    pytest.importorskip("PIL")
    from PIL import Image
    from tests.conftest import login_client
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="111", filename="a_111.png", prompt_preview="a moonlit grove")])
    (tmp_path / "images").mkdir()
    src = tmp_path / "images" / "a_111.png"
    Image.new("RGB", (8, 8), (120, 90, 200)).save(src, "PNG")
    before = src.read_bytes()
    client = login_client(tmp_path)

    z = client.post("/export-zip", data={"media_ids": "111", "fmt": "jpeg"})
    assert z.status_code == 200
    assert zipfile.ZipFile(io.BytesIO(z.data)).namelist() == ["a_111.jpg"]   # converted in the ZIP
    assert src.exists() and src.read_bytes() == before                       # original untouched
    assert not (tmp_path / "images" / "a_111.jpg").exists()                  # no converted copy left on disk


def test_export_zip_embeds_metadata_on_a_copy(tmp_path):
    """fmt=png + embed writes the prompt/ids into the DOWNLOADED file's PNG text chunks --
    on the temp copy, never the archived original."""
    import io
    import zipfile
    pytest.importorskip("PIL")
    from PIL import Image
    from tests.conftest import login_client
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="222", filename="b_222.png", prompt_preview="silver stag")])
    (tmp_path / "images").mkdir()
    src = tmp_path / "images" / "b_222.png"
    Image.new("RGB", (8, 8), (30, 40, 60)).save(src, "PNG")
    before = src.read_bytes()
    client = login_client(tmp_path)

    z = client.post("/export-zip", data={"media_ids": "222", "fmt": "png", "embed": "1"})
    assert z.status_code == 200
    data = zipfile.ZipFile(io.BytesIO(z.data)).read("b_222.png")
    im = Image.open(io.BytesIO(data))
    assert im.text.get("media_id") == "222"          # metadata embedded in the downloaded copy
    assert src.read_bytes() == before                # original untouched (no text chunks added)


def test_export_zip_passes_videos_through_untransformed(tmp_path):
    """A video in the selection is shipped as-is even with fmt set -- Pillow can't transform
    an mp4, and the guard skips it rather than corrupting or dropping it."""
    import io
    import zipfile
    from tests.conftest import login_client
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="v1", filename="videos/clip_v1.mp4", is_video="1")])
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / "clip_v1.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42fake")
    client = login_client(tmp_path)

    z = client.post("/export-zip", data={"media_ids": "v1", "fmt": "jpeg", "embed": "1"})
    assert z.status_code == 200
    assert zipfile.ZipFile(io.BytesIO(z.data)).namelist() == ["clip_v1.mp4"]   # untouched extension


def test_full_image_dl_forces_a_save_with_real_filename(tmp_path):
    """The detail page's plain Download hits /full/<id>?dl=1 -> Content-Disposition attachment
    with the real filename (browser saves it). Without ?dl it stays inline so the lightbox can
    display it -- same file, two dispositions."""
    from tests.conftest import login_client
    save_catalog(tmp_path / "catalog.db", [_row(media_id="1", filename="a_1.png")])
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "a_1.png").write_bytes(b"\x89PNG\r\n\x1a\nx")
    cli = login_client(tmp_path)
    assert "attachment" not in (cli.get("/full/1").headers.get("Content-Disposition") or "")
    cd = cli.get("/full/1?dl=1").headers.get("Content-Disposition") or ""
    assert "attachment" in cd and "a_1.png" in cd


def test_export_zip_by_collection_resolves_full_membership(tmp_path):
    """'Download collection' zips EVERY item in the named collection (resolved in SQL, all
    pages), not the rendered selection -- and excludes non-members. No media_ids are sent."""
    import io
    import zipfile
    from tests.conftest import login_client
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", collections="Trip"),
        _row(media_id="2", filename="b_2.png", collections="Trip"),
        _row(media_id="3", filename="c_3.png", collections="Other")])
    (tmp_path / "images").mkdir()
    for n in ("a_1.png", "b_2.png", "c_3.png"):
        (tmp_path / "images" / n).write_bytes(b"\x89PNG\r\n\x1a\nx")
    cli = login_client(tmp_path)
    z = cli.post("/export-zip", data={"collection": "Trip"})
    assert z.status_code == 200
    names = set(zipfile.ZipFile(io.BytesIO(z.data)).namelist())
    assert names == {"a_1.png", "b_2.png"}     # both Trip members; the Other one excluded


def test_contact_sheet_resolves_a_collection_serverside(tmp_path):
    """What survives of O5 (audit 2026-07-21) after the classic cut 2026-08-08:
    the filter-bar entry point (contactSheetCollection() and its button) died
    with classic's inline JS, but /contact-sheet?collection=<name> itself is a
    live route the React gallery links to. Keep the server-side contract: the
    sheet resolves the named collection's OWN membership in SQL -- members in,
    non-members out -- rather than whatever ids a client happened to pass."""
    from tests.conftest import login_client
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a.png", collections="Moonlit"),
        _row(media_id="2", filename="b.png", collections="Other")])
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "a.png").write_bytes(b"x")
    (tmp_path / "images" / "b.png").write_bytes(b"x")
    client = login_client(tmp_path)

    html = client.get("/contact-sheet?collection=Moonlit").get_data(as_text=True)
    assert "Collection: Moonlit" in html
    assert "/thumbs/1.jpg" in html          # the member is on the sheet
    assert "/thumbs/2.jpg" not in html      # the non-member is excluded


def test_collection_health_resolves_video_and_local_by_filename(tmp_path):
    """A video / imported row's media_id is synthetic (or a video id the image-only
    walk never sees), so 'missing' must resolve by filename too -- not over-report."""
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="vid123", filename="videos/x_vid123.mp4", is_video="1"),
        _row(media_id="local_abc", filename="videos/MyClip.mp4", is_video="1", source="local"),
        _row(media_id="gone", filename="images/not_here.png"),   # genuinely missing
    ])
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / "x_vid123.mp4").write_bytes(b"v")
    (tmp_path / "videos" / "MyClip.mp4").write_bytes(b"v")
    h = collection_health(tmp_path, db)
    assert h["missing"] == 1          # only the truly-absent image, not the videos


def test_collection_health_detects_duplicate(tmp_path):
    db = tmp_path / "catalog.db"
    init_db(db)
    (tmp_path / "images").mkdir()
    (tmp_path / "2024-03").mkdir()
    (tmp_path / "images" / "p_t1_111.webp").write_bytes(b"data")
    (tmp_path / "2024-03" / "111.webp").write_bytes(b"data")
    h = collection_health(tmp_path, db)
    assert h["dup_redundant"] == 1


def test_duplicate_groups_finds_cross_folder_copies(tmp_path):
    from moonglade_gallery import duplicate_groups
    (tmp_path / "images").mkdir()
    (tmp_path / "2024-03").mkdir()
    # 111 lives in two buckets -> a group; 222 lives only in images -> not a group
    (tmp_path / "images" / "p_t1_111.webp").write_bytes(b"data")
    (tmp_path / "2024-03" / "111.webp").write_bytes(b"data")
    (tmp_path / "images" / "x_222.webp").write_bytes(b"solo")
    groups = duplicate_groups(tmp_path)
    assert len(groups) == 1
    g = groups[0]
    assert g["media_id"] == "111"
    # most-organized copy (month) is the keeper over flat images/
    assert g["keeper"].replace("\\", "/") == "2024-03/111.webp"
    assert len(g["copies"]) == 2


def test_duplicate_groups_ignores_gallery_and_quarantine(tmp_path):
    from moonglade_gallery import duplicate_groups
    (tmp_path / "images").mkdir()
    (tmp_path / "gallery" / "thumbs").mkdir(parents=True)
    (tmp_path / "_duplicates").mkdir()
    (tmp_path / "images" / "a_111.webp").write_bytes(b"d")
    (tmp_path / "gallery" / "thumbs" / "111.jpg").write_bytes(b"d")
    (tmp_path / "_duplicates" / "111.webp").write_bytes(b"d")
    # only the images/ copy counts -> not a cross-bucket duplicate
    assert duplicate_groups(tmp_path) == []


def test_duplicate_groups_ignores_deleted(tmp_path):
    """B11 (audit 2026-07-21): duplicate_groups (the gallery review browser's Class-A
    view) excluded gallery/ and _duplicates/ but never _deleted/ -- so a locally
    purged image is reported as a live cross-bucket duplicate of its own quarantined
    self."""
    from moonglade_gallery import duplicate_groups, DELETED_DIRNAME
    (tmp_path / "images").mkdir()
    (tmp_path / DELETED_DIRNAME).mkdir()
    (tmp_path / "images" / "a_111.webp").write_bytes(b"d")
    (tmp_path / DELETED_DIRNAME / "111.webp").write_bytes(b"d")
    # only the images/ copy counts -> not a cross-bucket duplicate
    assert duplicate_groups(tmp_path) == []


def test_video_row_flagged_and_serves(tmp_path):
    """Ported from the classic grid/detail render (classic cut 2026-08-08): the
    play badge and the <video> element are the React client's to draw now, but
    the signals it draws them FROM are still this server's contract -- is_video
    on the library item, the full row on the detail API, and /video-file
    actually serving the mp4 (and refusing a non-video id)."""
    from tests.conftest import login_client
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="VID", filename="videos/dance_VID.mp4", is_video="1",
             poster_media_id="POSTER", prompt_preview="night elf dance",
             prompt_full="night elf dance", video_duration="10"),
        _row(media_id="POSTER", filename="images/p_POSTER.png", prompt_preview="still"),
    ])
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / "dance_VID.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42FAKEMP4")
    (tmp_path / "gallery" / "thumbs").mkdir(parents=True)
    (tmp_path / "gallery" / "thumbs" / "POSTER.jpg").write_bytes(b"\xff\xd8\xff\xe0jpegposter")
    client = login_client(tmp_path)

    # grid data: the video row is flagged so the client can badge it
    items = client.get("/api/next/library").get_json()["items"]
    by = {i["media_id"]: i for i in items}
    assert by["VID"]["is_video"] is True
    assert by["POSTER"]["is_video"] is False

    # detail data: the full row (incl. is_video) backs the Details view's player decision
    d = client.get("/api/next/detail/VID")
    assert d.status_code == 200
    assert d.get_json()["row"]["is_video"] == "1"

    # the mp4 is actually served
    v = client.get("/video-file/VID")
    assert v.status_code == 200
    assert v.data == b"\x00\x00\x00\x18ftypmp42FAKEMP4"

    # a non-video media id is rejected by the video route
    assert client.get("/video-file/POSTER").status_code == 404


def test_delete_tasks_bulk_purges_whole_task_cloud_and_local(tmp_path, monkeypatch, pixai):
    import moonglade_backup as core
    from moonglade_gallery import load_catalog
    from tests.conftest import login_client
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="m1", filename="images/a_m1.png", task_id="T1"),
        _row(media_id="m2", filename="images/b_m2.png", task_id="T1"),   # same task (batch)
        _row(media_id="loc", filename="videos/c.mp4", task_id="", source="local", is_video="1"),
    ])
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "a_m1.png").write_bytes(b"x")
    (tmp_path / "images" / "b_m2.png").write_bytes(b"x")
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / "c.mp4").write_bytes(b"v")

    calls = []
    monkeypatch.setattr(core, "delete_task_gql", lambda s, tid: calls.append(tid))
    client = login_client(tmp_path)

    # select ONE image of task T1, plus the local-only import
    r = client.post("/api/delete-tasks", json={"media_ids": ["m1", "loc"]})
    assert r.status_code == 200
    d = r.get_json()   # async: kicked off, reports to the Activity card
    assert d["ok"] is True and d["tasks"] == 1 and d["local_only"] == 1

    import time
    for _ in range(200):                                # wait for the background delete thread
        if not load_catalog(db):
            break
        time.sleep(0.02)

    assert calls == ["T1"]                       # cloud delete fired once for the task
    remaining = {x["media_id"] for x in load_catalog(db)}
    assert remaining == set()                    # whole task (m1+m2) + import all purged
    assert not (tmp_path / "images" / "b_m2.png").exists()   # batch sibling gone too


def test_edit_prompt_and_bulk_replace_routes(tmp_path):
    from moonglade_gallery import load_catalog
    from tests.conftest import login_client
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="m1", filename="a_m1.png", prompt_full="red cat"),
        _row(media_id="m2", filename="b_m2.png", prompt_full="red dog"),
    ])
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "a_m1.png").write_bytes(b"x")
    (tmp_path / "images" / "b_m2.png").write_bytes(b"x")
    client = login_client(tmp_path)

    r = client.post("/api/edit-prompt/m1", json={"prompt": "blue cat"})
    assert r.status_code == 200 and r.get_json()["ok"] is True

    r2 = client.post("/api/replace-prompts",
                     json={"media_ids": ["m1", "m2"], "find": "cat", "replace": "lion"})
    assert r2.status_code == 200
    assert r2.get_json() == {"ok": True, "changed": 1}
    by_id = {x["media_id"]: x["prompt_full"] for x in load_catalog(db)}
    assert by_id["m1"] == "blue lion" and by_id["m2"] == "red dog"
