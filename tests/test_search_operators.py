"""Search field operators (key:value tokens in the search box) + the zero-regression
guarantee for plain free-text search.

Grammar under test (parsed by _build_where via _operator_clause):
  * text fields      -> substring, case-insensitive, * / ? wildcards (model:, lora:,
                        tag:, title:, sampler:, filename:, batch:, status:, negative:,
                        natural:, prompt:)
  * numeric fields   -> key:N exact, key:>N / key:<N / key:>=N / key:<=N
                        (width, height, rating, steps, cfg, aes, likes, comments,
                        clip_skip, duration)
  * ids              -> exact match (task:, media:, artwork:, model_id:, seed:)
  * booleans         -> 1/true/yes/on vs 0/false/no/off (video:, published:, nsfw:)
  * dates            -> created:2026-07 prefix style, plus </>/<=/>= prefix compares
  * specials         -> collection: (exact token, mirroring the dropdown),
                        source: (online/api/local/deleted, mirroring the dropdown)
  * quoted values    -> model:"Ether Real"
  * unknown keys     -> the whole token is searched as plain prompt text (search-engine
                        behavior), never an error
Free text with no operator present must build the EXACT same SQL as before the
feature existed -- pinned at the WHERE-clause level below.
"""
import pytest

from pixai_gallery import CATALOG_FIELDS, save_catalog, query_catalog, _build_where


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "catalog.db"
    save_catalog(p, [
        _row(media_id="100000001", task_id="900000001", filename="a_100000001.png",
             prompt_preview="night elf druid",
             prompt_full="night elf druid, moonlit grove",
             negative_prompt="blurry, extra fingers",
             model_name="Ether Real Mix", model_id="777", sampler="Euler a",
             seed="123456789", steps="28", cfg_scale="6.5", clip_skip="2",
             width="1024", height="1536", rating="4", aes_score="7.2",
             liked_count="12", comment_count="3",
             created_at="2026-07-04T12:00:00", batch="B1", status="completed",
             is_published="1", is_nsfw="", art_tags="ContestX, elf",
             loras="Detail Tweaker:0.7", title="Moonlit Grove",
             artwork_id="A1", collections="Elf Portraits,Favorites", source="api"),
        _row(media_id="100000002", task_id="900000002", filename="b_100000002.png",
             prompt_preview="city street at dawn",
             prompt_full="city street at dawn, score:high style",
             model_name="Tsubaki v3", model_id="888", sampler="DPM++ 2M",
             seed="42", steps="20", cfg_scale="4",
             width="768", height="768", rating="", aes_score="5.1",
             liked_count="0", comment_count="0",
             created_at="2025-12-31T23:59:59", status="completed",
             is_nsfw="1", art_tags="cityscape", source=""),
        _row(media_id="100000003", task_id="900000003",
             filename="videos/c_100000003.mp4", prompt_preview="dancing",
             prompt_full="dancing", is_video="1", video_duration="10",
             created_at="2026-01-15T08:00:00", source="local", deleted_remote="1"),
    ])
    return p


# ---- zero-regression: free text with no operator builds the legacy SQL -----

# the exact per-term clause _build_where has always emitted for a text term
_LIKE_PAIR = ("(LOWER(COALESCE(prompt_full,'')) LIKE ? ESCAPE '\\' "
              "OR LOWER(COALESCE(prompt_preview,'')) LIKE ? ESCAPE '\\')")


def test_no_operator_query_builds_the_legacy_where_shape():
    """THE regression pin: a plain multi-word wildcard query (no key:value token)
    must compile to byte-identical SQL and params as before operators existed --
    one AND-ed LIKE pair per whitespace term, wildcards via _like_pattern."""
    where, params = _build_where("night* elf", "", "", "")
    assert where == "filename != '' AND {0} AND {0}".format(_LIKE_PAIR)
    assert params == ["%night%", "%night%", "%elf%", "%elf%"]


def test_no_operator_long_digit_id_still_matches_exactly():
    where, params = _build_where("744376191043610002", "", "", "")
    assert where == "filename != '' AND (task_id = ? OR media_id = ?)"
    assert params == ["744376191043610002", "744376191043610002"]


def test_no_operator_short_digit_stays_prompt_only():
    where, params = _build_where("88", "", "", "")
    assert where == "filename != '' AND " + _LIKE_PAIR
    assert params == ["%88%", "%88%"]


def test_no_operator_results_unchanged(db):
    # behavior-level spot checks mirroring the long-standing tests
    assert query_catalog(db, q="night")[1] == 1
    assert query_catalog(db, q="night* elf")[1] == 1
    assert query_catalog(db, q="night dawn")[1] == 0          # multi-word AND
    assert query_catalog(db, q="900000002")[1] == 1            # long digit id


# ---- text operators --------------------------------------------------------

def test_model_operator_substring_case_insensitive(db):
    assert query_catalog(db, q="model:ether")[1] == 1
    assert query_catalog(db, q="model:tsubaki")[1] == 1
    assert query_catalog(db, q="model:nope")[1] == 0


def test_quoted_value_with_spaces(db):
    assert query_catalog(db, q='model:"Ether Real"')[1] == 1
    assert query_catalog(db, q='title:"Moonlit Grove"')[1] == 1


def test_wildcards_work_inside_operator_values(db):
    assert query_catalog(db, q="model:eth*mix")[1] == 1
    assert query_catalog(db, q="sampler:e?ler")[1] == 1


def test_negative_prompt_operator(db):
    assert query_catalog(db, q="negative:blurry")[1] == 1
    assert query_catalog(db, q="negative:crowd")[1] == 0


def test_more_text_operators(db):
    assert query_catalog(db, q="lora:detail")[1] == 1
    assert query_catalog(db, q="tag:elf")[1] == 1
    assert query_catalog(db, q="sampler:euler")[1] == 1
    assert query_catalog(db, q="title:moonlit")[1] == 1
    assert query_catalog(db, q="batch:b1")[1] == 1
    assert query_catalog(db, q="status:completed")[1] == 2
    assert query_catalog(db, q="filename:mp4")[1] == 1


def test_prompt_operator_phrase(db):
    assert query_catalog(db, q='prompt:"elf druid"')[1] == 1
    assert query_catalog(db, q='prompt:"druid elf"')[1] == 0


# ---- numeric operators -----------------------------------------------------

def test_width_height_comparisons(db):
    assert query_catalog(db, q="width:>800")[1] == 1     # 1024; blank row excluded
    assert query_catalog(db, q="width:<800")[1] == 1     # 768
    assert query_catalog(db, q="width:768")[1] == 1      # exact
    assert query_catalog(db, q="height:>=1536")[1] == 1


def test_blank_numeric_column_never_matches_a_comparison(db):
    # the video row has width='' -- it must not be swept in by any comparison
    assert query_catalog(db, q="width:<99999")[1] == 2


def test_aes_likes_steps_cfg_duration(db):
    assert query_catalog(db, q="aes:>6")[1] == 1
    assert query_catalog(db, q="aes:<6")[1] == 1
    assert query_catalog(db, q="likes:>0")[1] == 1
    assert query_catalog(db, q="likes:0")[1] == 1        # blank-likes video row excluded
    assert query_catalog(db, q="steps:>25")[1] == 1
    assert query_catalog(db, q="cfg:<5")[1] == 1
    assert query_catalog(db, q="cfg:6.5")[1] == 1        # float exact
    assert query_catalog(db, q="duration:>5")[1] == 1


def test_rating_treats_unrated_as_zero_like_the_dropdown(db):
    assert query_catalog(db, q="rating:>=3")[1] == 1
    assert query_catalog(db, q="rating:0")[1] == 2       # unrated rows count as 0


# ---- exact-id operators ----------------------------------------------------

def test_seed_is_exact_not_substring(db):
    assert query_catalog(db, q="seed:42")[1] == 1
    assert query_catalog(db, q="seed:4")[1] == 0         # not a substring match


def test_id_operators(db):
    assert query_catalog(db, q="task:900000002")[1] == 1
    assert query_catalog(db, q="media:100000003")[1] == 1
    assert query_catalog(db, q="artwork:A1")[1] == 1
    assert query_catalog(db, q="model_id:777")[1] == 1


# ---- boolean operators -----------------------------------------------------

def test_boolean_operators(db):
    assert query_catalog(db, q="video:1")[1] == 1
    assert query_catalog(db, q="video:0")[1] == 2
    assert query_catalog(db, q="video:true")[1] == 1
    assert query_catalog(db, q="published:1")[1] == 1
    assert query_catalog(db, q="nsfw:1")[1] == 1
    assert query_catalog(db, q="nsfw:0")[1] == 2


# ---- date operators --------------------------------------------------------

def test_created_prefix_and_compares(db):
    assert query_catalog(db, q="created:2026-07")[1] == 1
    assert query_catalog(db, q="created:2026")[1] == 2
    assert query_catalog(db, q="created:2026-07-04")[1] == 1
    assert query_catalog(db, q="created:<2026")[1] == 1
    assert query_catalog(db, q="created:>=2026-07")[1] == 1
    assert query_catalog(db, q="created:>2026-01")[1] == 1   # strictly after Jan
    assert query_catalog(db, q="date:2025")[1] == 1          # alias


# ---- special operators (mirror the dropdowns) ------------------------------

def test_collection_operator_is_exact_token(db):
    assert query_catalog(db, q='collection:"Elf Portraits"')[1] == 1
    assert query_catalog(db, q="collection:Favorites")[1] == 1
    assert query_catalog(db, q="collection:Elf")[1] == 0     # no partial-name bleed


def test_source_operator_mirrors_dropdown_semantics(db):
    assert query_catalog(db, q="source:api")[1] == 1
    assert query_catalog(db, q="source:online")[1] == 1      # blank counts as online
    assert query_catalog(db, q="source:local")[1] == 1
    assert query_catalog(db, q="source:deleted")[1] == 1     # deleted_remote flag


# ---- combining, unknown keys, malformed values -----------------------------

def test_operator_and_free_text_are_anded(db):
    assert query_catalog(db, q="model:tsubaki dawn")[1] == 1
    assert query_catalog(db, q="model:tsubaki night")[1] == 0
    assert query_catalog(db, q="model:ether rating:>=3 elf")[1] == 1


def test_unknown_key_is_searched_as_plain_text(db):
    # "score" is not an operator -> the whole token is prompt text, like a search
    # engine; row 2's prompt literally contains "score:high"
    assert query_catalog(db, q="score:high")[1] == 1
    assert query_catalog(db, q="foo:bar")[1] == 0            # no error, just no hits


def test_empty_value_falls_back_to_plain_text(db):
    # "model:" with nothing after it is not a filter -- it's searched literally
    assert query_catalog(db, q="model:")[1] == 0


def test_malformed_numeric_and_date_fall_back_to_plain_text(db):
    assert query_catalog(db, q="width:tall")[1] == 0         # no error
    assert query_catalog(db, q="created:someday")[1] == 0    # no error


# ---- injection safety ------------------------------------------------------

def test_hostile_values_cannot_escape_or_error(db):
    """Everything reaches SQL as a bound parameter; column names and comparison
    operators come only from hardcoded maps. A hostile value -- quotes, semicolons,
    SQL keywords as key names, LIKE wildcards -- must neither error nor over-match."""
    hostile = [
        'title:"x\'; DROP TABLE catalog; --"',
        'prompt:"\'; DELETE FROM catalog; --"',
        "seed:1;DROP TABLE catalog",
        'select:1',                       # SQL keyword as key -> plain text
        'union:select',
        "drop:table",
        'model:%',                        # LIKE wildcards are escaped literals
        'model:_',
        "model:\\",
        "created:2026'; --",
        'collection:"a\\",b\'--"',
    ]
    for q in hostile:
        rows, total = query_catalog(db, q=q)   # must not raise
        assert total == 0, "hostile token {!r} over-matched".format(q)
    # contrast: the escaped-% case really is a literal, not match-everything
    assert query_catalog(db, q="model:e")[1] >= 1
    # and the table survived every attempt
    assert query_catalog(db, q="")[1] == 3


# ---- shared surfaces: picker API + filtered CSV export ---------------------

def test_gallery_images_api_honors_field_operators(tmp_path):
    """/api/gallery-images (the Picker / Generate-drawer / Loom source) passes its q
    straight into query_catalog, so operators work there for free -- prove it."""
    from tests.conftest import login_client
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="m1", filename="a_m1.png", model_name="Tsubaki v3"),
        _row(media_id="m2", filename="b_m2.png", model_name="Ether Real Mix"),
    ])
    cli = login_client(tmp_path)
    data = cli.get("/api/gallery-images?q=model:tsubaki&type=all").get_json()
    assert data["total"] == 1
    assert [i["media_id"] for i in data["images"]] == ["m1"]


def test_export_csv_honors_field_operators(tmp_path):
    """The filtered '/export-csv' link forwards the grid's query string (incl. q)
    through _filters_from_args -> query_catalog, so an operator search exports
    exactly the rows it matched."""
    import csv
    import io
    from tests.conftest import login_client
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="m1", filename="a_m1.png", model_name="Tsubaki v3"),
        _row(media_id="m2", filename="b_m2.png", model_name="Ether Real Mix"),
    ])
    cli = login_client(tmp_path)
    r = cli.get("/export-csv?q=model:ether")
    assert r.status_code == 200
    rows = list(csv.DictReader(io.StringIO(r.get_data(as_text=True))))
    assert [x["media_id"] for x in rows] == ["m2"]
