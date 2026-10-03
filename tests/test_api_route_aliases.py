"""The app's three data routes carry plain names, and the old `/next` names answer as aliases.

`/next` was the React app's pilot codename. #51 retired the page route and left the JSON
namespace; this is that separate change, Phase 1:

  * `/api/library`, `/api/detail/<media_id>` and `/api/history` are the names the app reads;
  * `/api/next/library`, `/api/next/detail/<media_id>` and `/api/next/history` stay registered
    for ONE release, on the SAME view function, so a tab still running an older cached bundle
    against an updated server keeps working. Two rules on one view: the answers are identical
    by construction, and there is no second handler to drift.

Phase 2 (a later release) removes the old rules; its test is the #51 one -- the old paths 404
for a real logged-in session, because anonymously every unrouted path redirects to /login.
"""
import pytest

from moonglade_gallery import CATALOG_FIELDS, LOGIN, create_app, route_tier, save_catalog

from tests.conftest import login_test_client


# (new rule, old rule, the one endpoint both resolve to)
PAIRS = [
    ("/api/library", "/api/next/library", "api_library"),
    ("/api/detail/<media_id>", "/api/next/detail/<media_id>", "api_detail"),
    ("/api/history", "/api/next/history", "api_history"),
]

# The same request on both paths. Every query is fixed (history's `before` and `tz` too), so
# the answer cannot move between the two calls.
REQUESTS = [
    ("/api/library", "/api/next/library", ""),
    ("/api/library", "/api/next/library", "?page=1&page_size=2&sort=newest"),
    ("/api/library", "/api/next/library", "?group=series&page_size=50"),
    ("/api/library", "/api/next/library", "?q=elf&rating_min=3"),
    ("/api/detail/m2", "/api/next/detail/m2", ""),
    ("/api/detail/m2", "/api/next/detail/m2", "?sort=oldest&rating_min=3"),
    ("/api/detail/nope", "/api/next/detail/nope", ""),                      # the 404 answer too
    ("/api/history", "/api/next/history", "?days=7&tz=-420&before=2026-08-18"),
    ("/api/history", "/api/next/history", "?before=yesterday"),             # the 400 answer too
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


def test_each_new_name_and_its_alias_are_two_rules_on_one_view(app):
    rules = _rules(app)
    for new, old, endpoint in PAIRS:
        assert new in rules, "the plain name %s is not routed" % new
        assert old in rules, ("the alias %s is gone: Phase 1 keeps it for one release so an "
                              "older cached bundle keeps working" % old)
        assert rules[new].endpoint == rules[old].endpoint == endpoint, (new, old)
        for r in (rules[new], rules[old]):
            assert (r.methods or set()) - {"HEAD", "OPTIONS"} == {"GET"}, str(r)


def test_both_paths_share_one_tier(app):
    for new, old, endpoint in PAIRS:
        view = app.view_functions[endpoint]
        assert route_tier(view, "GET") == LOGIN, endpoint


@pytest.mark.parametrize("new,old,query", REQUESTS)
def test_the_alias_answers_byte_for_byte_what_the_new_name_answers(app, new, old, query):
    cli = login_test_client(app)
    a = cli.get(new + query)
    b = cli.get(old + query)
    assert a.status_code == b.status_code, (new + query, a.status_code, b.status_code)
    assert a.get_data() == b.get_data(), new + query
    assert a.status_code in (200, 400, 404)


def test_the_fixture_reaches_real_rows(app):
    """The parity above would pass on two empty answers; this proves it compared content."""
    cli = login_test_client(app)
    assert cli.get("/api/library").get_json()["total"] == 4
    assert cli.get("/api/detail/m2").get_json()["row"]["media_id"] == "m2"
    days = cli.get("/api/history?days=7&tz=-420&before=2026-08-18").get_json()["days"]
    assert sum(len(d["rows"]) for d in days) == 4


@pytest.mark.parametrize("path", ["/api/library", "/api/detail/m2", "/api/history",
                                  "/api/next/library", "/api/next/detail/m2", "/api/next/history"])
def test_both_paths_refuse_an_anonymous_lan_caller(app, path):
    r = app.test_client().get(path, environ_overrides={"REMOTE_ADDR": "192.168.1.50"})
    assert r.status_code == 401
