"""The app's three data routes carry plain names, and the old `/next` names are gone.

`/next` was the React app's pilot codename. #51 retired the page route and left the JSON
namespace; the rename of that namespace ran in two phases:

  * Phase 1 gave the app's three data routes their plain names, `/api/library`,
    `/api/detail/<media_id>` and `/api/history`, and kept `/api/next/library`,
    `/api/next/detail/<media_id>` and `/api/next/history` registered for ONE release on the
    same view functions, so a tab still running an older cached bundle kept working;
  * Phase 2 (this state) removed the old rules. Each view now has exactly one route.

The `/next/assets/` static prefix is a different thing and is NOT retired: installed phone
apps read their icons from it through the web manifest, so it answers for good, to a caller
with no session.

The "gone" test is the #51 one: it probes with a REAL logged-in session, because anonymously
every unrouted path redirects to /login, which would pass just as happily against a live alias.
"""
import pytest

from moonglade.gallery import CATALOG_FIELDS, PUBLIC, create_app, route_tier, save_catalog

from tests.conftest import login_test_client


# (the one rule, the one endpoint it resolves to)
ROUTES = [
    ("/api/library", "api_library"),
    ("/api/detail/<media_id>", "api_detail"),
    ("/api/history", "api_history"),
]

# The retired paths, each with a query the live route would have answered.
RETIRED = [
    "/api/next/library",
    "/api/next/library?page=1&page_size=2&sort=newest",
    "/api/next/detail/m2",
    "/api/next/detail/m2?sort=oldest&rating_min=3",
    "/api/next/history",
    "/api/next/history?days=7&tz=-420&before=2026-08-18",
]


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


@pytest.fixture()
def app(tmp_path):
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="m%d" % n, filename="m%d.png" % n, task_id="T%d" % n,
             created_at="2026-08-1%dT10:00:00.000Z" % (n + 3),
             prompt_preview="elf" if n % 2 else "orc", rating=str(n))
        for n in range(1, 5)
    ])
    return create_app(tmp_path)


def _rules(app):
    return {str(r): r for r in app.url_map.iter_rules()}


def test_each_data_route_has_one_plain_rule_and_no_alias(app):
    rules = _rules(app)
    for rule, endpoint in ROUTES:
        assert rule in rules, "the plain name %s is not routed" % rule
        assert rules[rule].endpoint == endpoint, rule
        assert (rules[rule].methods or set()) - {"HEAD", "OPTIONS"} == {"GET"}, rule
        on_view = [str(r) for r in app.url_map.iter_rules() if r.endpoint == endpoint]
        assert on_view == [rule], ("%s answers on more than one path: %s -- the old /api/next/ "
                                   "aliases are retired" % (endpoint, on_view))


def test_no_rule_is_left_under_the_old_namespace(app):
    left = sorted(r for r in _rules(app) if r.startswith("/api/next"))
    assert left == [], "the pilot codename is back in the url_map: %s" % left


@pytest.mark.parametrize("path", RETIRED)
def test_the_old_paths_404_for_a_logged_in_session(app, path):
    cli = login_test_client(app)
    assert cli.get("/api/library").status_code == 200, (
        "the plain route stopped answering -- this test would be measuring nothing")
    assert cli.get(path).status_code == 404, (
        "%s answers again. The /api/next/ aliases were retired after their one release of "
        "grace; the app reads the plain names." % path)


def test_the_fixture_reaches_real_rows(app):
    """The plain routes answer with the catalog's content, not an empty shell."""
    cli = login_test_client(app)
    assert cli.get("/api/library").get_json()["total"] == 4
    assert cli.get("/api/detail/m2").get_json()["row"]["media_id"] == "m2"
    days = cli.get("/api/history?days=7&tz=-420&before=2026-08-18").get_json()["days"]
    assert sum(len(d["rows"]) for d in days) == 4


def test_the_assets_prefix_stays_and_stays_public(app):
    """`/next/assets/` is NOT part of the retirement: installed phone apps read their icons
    from it through the web manifest, with no session, from the LAN."""
    rules = _rules(app)
    rule = "/next/assets/<path:fname>"
    assert rule in rules, "the assets prefix is gone -- installed phone apps lose their icons"
    assert route_tier(app.view_functions[rules[rule].endpoint], "GET") == PUBLIC
    lan = {"REMOTE_ADDR": "192.168.1.50"}
    anon = app.test_client()
    manifest = anon.get("/next/assets/manifest.json", environ_overrides=lan)
    assert manifest.status_code == 200
    assert "/next/assets/icon-192.png" in manifest.get_data(as_text=True)
    icon = anon.get("/next/assets/icon-192.png", environ_overrides=lan)
    assert icon.status_code == 200
    assert icon.headers["Content-Type"] == "image/png"
