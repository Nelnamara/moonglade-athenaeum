"""The market is browsed as the website (core.present_as_web), 2026-09-07.

Owner's walk: a LoRA search for "cum" that fills pages on pixai.art came back "No LoRAs match"
in the drawer -- "it's like it's browsing the mobile side of things and showing censored
selections." Measured the same night, counts only: the same API key and the same meilisearch
query returned 0 rows presenting as `pixai-personal-backup/1.0` and 24 rows presenting the
website's identity, identical to the browser-token session. PixAI applies its content policy by
the client it believes it is talking to, not by the credential; the app's own identity gets the
stricter mobile-app tier. So the picker's search, its bookmark tab and a picked model's versions
present as the website. The credential is never touched by that -- Authorization stays as built.
"""
import moonglade_backup as core
from tests.conftest import login_client


class _Stub:
    """What _make_session hands the route, reduced to the one thing this cares about."""
    _is_pixai_client = True

    def __init__(self):
        self.headers = {"Authorization": "Bearer not-a-real-key",
                        "User-Agent": "pixai-personal-backup/1.0"}


def test_present_as_web_sets_the_website_identity_and_keeps_the_credential():
    s = _Stub()
    assert core.present_as_web(s) is s, "the same object comes back -- callers rebind, not copy"
    assert s.headers["User-Agent"] == core.MIRROR_WEB_USER_AGENT
    assert s.headers["Origin"] == core.MIRROR_WEB_ORIGIN
    assert s.headers["Referer"] == core.MIRROR_WEB_ORIGIN + "/"
    assert s.headers["Authorization"] == "Bearer not-a-real-key", "the identity changes, the key does not"
    assert set(core.WEB_IDENTITY_HEADERS) == {"User-Agent", "Origin", "Referer"}, \
        "the identity is exactly the three headers the mirror session presents -- nothing else"


def test_present_as_web_leaves_a_headerless_stand_in_alone():
    o = object()
    assert core.present_as_web(o) is o


def test_model_search_route_browses_the_market_as_the_website(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: _Stub())

    def fake_market(session, **kw):
        seen["headers"] = dict(session.headers)
        seen["keyword"] = kw.get("keyword")
        return {"results": [], "has_more": False, "next_cursor": ""}
    monkeypatch.setattr(core, "model_search_market_gql", fake_market)
    cli = login_client(tmp_path)
    d = cli.get("/api/model-search?kind=lora&size=24&q=cum&src=market&sort=liked").get_json()
    assert not d.get("error"), d
    assert seen["keyword"] == "cum"
    assert seen["headers"]["User-Agent"] == core.MIRROR_WEB_USER_AGENT
    assert seen["headers"]["Origin"] == core.MIRROR_WEB_ORIGIN
    assert seen["headers"]["Authorization"] == "Bearer not-a-real-key"


def test_bookmark_tab_browses_as_the_website_too(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: _Stub())

    def fake_bookmarks(session, **kw):
        seen["headers"] = dict(session.headers)
        return {"results": [], "has_more": False, "next_cursor": ""}
    monkeypatch.setattr(core, "model_bookmarks_gql", fake_bookmarks)
    cli = login_client(tmp_path)
    d = cli.get("/api/model-search?kind=lora&size=24&q=&src=bookmark").get_json()
    assert not d.get("error"), d
    assert seen["headers"]["User-Agent"] == core.MIRROR_WEB_USER_AGENT


def test_model_version_route_reads_versions_as_the_website(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: _Stub())

    def fake_versions(session, mid):
        seen["headers"] = dict(session.headers)
        seen["mid"] = mid
        return []
    monkeypatch.setattr(core, "list_model_versions", fake_versions)
    cli = login_client(tmp_path)
    d = cli.get("/api/model-version?model_id=123&all=1").get_json()
    assert d.get("versions") == [], d
    assert seen["mid"] == "123"
    assert seen["headers"]["User-Agent"] == core.MIRROR_WEB_USER_AGENT
    assert seen["headers"]["Authorization"] == "Bearer not-a-real-key"
