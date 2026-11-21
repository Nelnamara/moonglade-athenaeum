"""The explicit CSRF token on state-changing routes: the three per-account stores that
lacked it, and a guard that makes every other gap visible.

THE THREE STORES. `POST /api/view-presets` (saved views), `POST /api/snippets` (prompt
snippets) and `POST /api/presets` (banked Toolbox presets) each write a per-account file,
and `/api/presets` also reaches PixAI with the owner's key. They checked no token, unlike
the other per-account writes (`/api/account/prefs`, the user-admin routes). They now refuse
a POST without the session's token -- 400 with the same "reload" wording, BEFORE any read,
write or network call -- and GET is untouched.

THE FRONT DOOR (app security review 2026-11-19, finding 2). Every POST / PUT / PATCH / DELETE
now passes one origin check in the request gate (gallery.py's `_refuse_cross_origin_writes`,
the rule in `same_origin_write`) before any route reads its body: it must come from this
server's own origin. That closes the old CSRF debt -- 58 state-changing routes without the
explicit token, 14 of them reachable by any same-site page, a page on another port of this PC
above all -- in one place, so `CSRF_KNOWN_DEBT` is empty and stays empty.
`test_the_front_door_covers_every_state_changing_route` proves it the only way that counts:
for EVERY state-changing (rule, method) the app registers, a signed-in request from another
port of this PC is refused 403 before its handler runs, and the same request from the app's
own origin reaches the handler. The handlers are swapped for a recorder first, so nothing that
spends or deletes ever runs here (the stance dev/tests/test_route_tiers.py documents).

THE TOKEN WALK, kept: `_walk` decides from each handler's own syntax tree whether it calls
`_check_csrf` -- directly or through a helper that does (`_train_csrf_body`,
`_recipe_write_body`) -- and the lane routes below must, with zero exceptions. The explicit
token stays a second lock where routes have it; the front door is the one every route has.
"""
import ast
import inspect
import json
import textwrap
from pathlib import Path

import pytest

from moonglade import backup as core
from moonglade import paths
from moonglade.gallery import create_app
from moonglade.account_prefs import _account_key
from tests.conftest import login_test_client, session_csrf, with_csrf
from moonglade import task_reads as task_reads_mod

_GALLERY = Path(__file__).resolve().parents[2] / "moonglade" / "gallery.py"
# Where routes are defined: gallery.create_app, and the families split out of it (phase 4).
_ROUTE_SOURCES = (_GALLERY, _GALLERY.with_name("routes_generate.py"),
                  _GALLERY.with_name("web_loom_store.py"), _GALLERY.with_name("routes_loom.py"),
                  _GALLERY.with_name("routes_gate.py"), _GALLERY.with_name("routes_panel.py"))
_STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}
_REFUSAL = "Your session expired. Reload the page and try again."

# THE KNOWN DEBT -- empty since the front door's origin check (2026-11-19) covers every
# state-changing route. It stays named so the old shape cannot quietly come back: a route
# listed here would be a route the front door is assumed NOT to cover, and there is none.
CSRF_KNOWN_DEBT = {}

# The two origins the sweep below uses: the app's own, and a page on another port of the
# same PC (the D: install's 5757 against this one's 5057 -- same-site, so the Lax cookie
# rides its requests).
_OWN = "http://localhost:5057"
_CROSS_PORT = "http://localhost:5757"


# ---------------------------------------------------------------------------
# The walk
# ---------------------------------------------------------------------------

def _called_names(node):
    """Every bare `name(...)` called inside `node`'s own body. Nested function definitions
    are skipped: a helper defined inside a handler and never called checks nothing."""
    out, stack = set(), list(ast.iter_child_nodes(node))
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            out.add(n.func.id)
        stack.extend(ast.iter_child_nodes(n))
    return out


def _token_checkers():
    """`_check_csrf` plus every function in the route sources that calls it, directly or
    through another such function -- resolved to a fixed point, so a helper of a helper
    counts. A name defined more than once counts only when EVERY definition checks."""
    defs = {}
    for src_path in _ROUTE_SOURCES:
        tree = ast.parse(src_path.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defs.setdefault(n.name, []).append(n)
    checkers = {"_check_csrf"}
    grew = True
    while grew:
        grew = False
        for name, nodes in defs.items():
            if name not in checkers and all(_called_names(d) & checkers for d in nodes):
                checkers.add(name)
                grew = True
    return checkers


def _walk(app):
    """{"<rule> [<METHOD>]": checks_token} for every state-changing (rule, method)."""
    checkers = _token_checkers()
    out = {}
    for rule in app.url_map.iter_rules():
        methods = sorted((rule.methods or set()) & _STATE_CHANGING)
        if not methods:
            continue
        view = app.view_functions[rule.endpoint]
        fn = ast.parse(textwrap.dedent(inspect.getsource(view))).body[0]
        checks = bool(_called_names(fn) & checkers)
        for m in methods:
            out["{} [{}]".format(rule.rule, m)] = checks
    return out


@pytest.fixture()
def app(tmp_path):
    return create_app(tmp_path)


def _concrete_path(rule):
    """A real URL for a rule: every <converter:name> filled with a value it accepts."""
    import re as _re
    return _re.sub(r"<(?:(\w+)(?:\([^)]*\))?:)?(\w+)>",
                   lambda m: "1" if m.group(1) in ("int",) else "x1", rule.rule)


def _sweep(app, origin, extra_headers=None):
    """Every state-changing (rule, method), sent by a signed-in session on this PC with
    `origin`. Each handler is swapped for a recorder first, so none of them really runs.
    Returns {"<rule> [<METHOD>]": (status, reached_handler)}."""
    reached = set()

    def _recorder(endpoint):
        def _view(*a, **k):
            reached.add(endpoint)
            return "recorded"
        return _view
    cli = login_test_client(app)
    for ep in list(app.view_functions):
        if ep != "static":
            app.view_functions[ep] = _recorder(ep)
    out = {}
    for rule in app.url_map.iter_rules():
        for m in sorted((rule.methods or set()) & _STATE_CHANGING):
            reached.discard(rule.endpoint)
            headers = dict(extra_headers or {})
            if origin is not None:
                headers["Origin"] = origin
            r = cli.open(_concrete_path(rule), method=m, headers=headers,
                         base_url=_OWN, json={})
            out["{} [{}]".format(rule.rule, m)] = (r.status_code, rule.endpoint in reached,
                                                   r.get_data(as_text=True))
    return out


def test_the_front_door_covers_every_state_changing_route(app):
    """The headline: EVERY POST/PUT/PATCH/DELETE the app registers -- the 58 that once had no
    token among them -- is refused for a page on another port of this PC, before its handler
    runs, with the plain sentence; and the same request from the app's own origin goes
    through to the handler (so the refusal is the origin, not something else)."""
    from moonglade.gallery import CROSS_ORIGIN_REFUSED
    cross = _sweep(app, _CROSS_PORT)
    assert len(cross) > 100, "the sweep found too few state-changing routes to mean anything"
    leaked = sorted(k for k, (status, ran, _body) in cross.items() if ran or status != 403)
    assert not leaked, "a cross-port page reached these handlers: %s" % leaked
    assert all(CROSS_ORIGIN_REFUSED in body for _s, _r, body in cross.values())


def test_the_apps_own_pages_still_reach_every_route(tmp_path):
    """The other half: the app's own origin (and a client that sends no origin at all, the
    test client and curl) is NOT refused -- every handler is reached."""
    own = _sweep(create_app(tmp_path), _OWN)
    blocked = sorted(k for k, (status, ran, _b) in own.items() if not ran)
    assert not blocked, "the app's own origin was refused at: %s" % blocked


def test_no_origin_header_at_all_reaches_the_handlers(tmp_path):
    bare = _sweep(create_app(tmp_path), None)
    assert all(ran for _s, ran, _b in bare.values())


@pytest.mark.parametrize("headers", [
    {"Origin": _CROSS_PORT},                                  # another port of this PC
    {"Origin": "http://127.0.0.1:5057"},                      # same port, another name
    {"Origin": "https://localhost:5057"},                     # same host, another scheme
    {"Origin": "null"},                                       # a sandboxed or no-referrer page
    {"Origin": ""},
    {"Referer": _CROSS_PORT + "/branding/x.html"},            # no Origin: the Referer decides
    {"Sec-Fetch-Site": "same-site"},                          # the browser says so outright
    {"Sec-Fetch-Site": "cross-site", "Origin": _OWN},         # contradicting itself: refused
    {"Sec-Fetch-Site": "none"},
])
def test_the_review_scenario_a_cross_port_page_cannot_import_or_stop(tmp_path, headers):
    """Finding 2's own scenario, end to end with the real handlers: a page on localhost:5757
    sends a multipart POST to /api/import-local (LOCALHOST tier -- the browser IS on this PC)
    and a bare POST to /api/server/stop. Both are refused 403 and nothing happens."""
    import io
    from moonglade.gallery import CROSS_ORIGIN_REFUSED
    app = create_app(tmp_path)
    cli = login_test_client(app)
    r = cli.post("/api/import-local", base_url=_OWN, headers=headers,
                 data={"files": (io.BytesIO(b"\x89PNG\r\n\x1a\nplanted"), "x.png")},
                 content_type="multipart/form-data")
    assert r.status_code == 403 and r.get_json() == {"error": CROSS_ORIGIN_REFUSED}
    assert not (tmp_path / "imported").exists()
    r = cli.post("/api/server/stop", base_url=_OWN, headers=headers)
    assert r.status_code == 403


@pytest.mark.parametrize("headers", [
    {"Origin": _OWN}, {"Origin": _OWN + "/"}, {"Referer": _OWN + "/?page=2"},
    {"Sec-Fetch-Site": "same-origin", "Origin": _OWN}, {"Sec-Fetch-Site": "same-origin"},
])
def test_the_apps_own_page_passes(tmp_path, headers):
    app = create_app(tmp_path)
    cli = login_test_client(app)
    r = cli.post("/api/view-presets", base_url=_OWN, headers=headers,
                 json=with_csrf(cli, {"name": "mine", "query": "?q=1"}))
    assert r.status_code == 200, r.get_json()


def test_the_rule_itself():
    from moonglade.gallery import same_origin_write as ok
    assert ok("http://localhost:5057", None, None, "http", "localhost:5057")
    assert ok("http://LOCALHOST:5057", None, "same-origin", "http", "localhost:5057")
    assert ok("https://192.168.1.5:5057", None, None, "https", "192.168.1.5:5057")
    assert ok("https://moonglade.local", None, None, "https", "moonglade.local:443")
    assert ok("http://[::1]:5057", None, None, "http", "[::1]:5057")
    assert ok(None, None, None, "http", "localhost:5057")          # not a browser
    assert not ok("http://localhost:5757", None, None, "http", "localhost:5057")
    assert not ok("http://192.168.1.5:5057", None, None, "https", "192.168.1.5:5057")
    assert not ok("null", None, None, "http", "localhost:5057")
    assert not ok(None, "http://evil.example/x", None, "http", "localhost:5057")
    assert not ok(None, None, "same-site", "http", "localhost:5057")
    assert not ok("http://localhost:5057", None, None, "http", "")
    assert not ok("http://localhost:99999", None, None, "http", "localhost:5057")


def test_the_known_debt_list_is_empty_for_good():
    assert CSRF_KNOWN_DEBT == {}


def test_the_walk_sees_the_checks_it_claims_to(app):
    """The walk is not vacuous: routes known to check the token are found checking it,
    including the ones that only do so through a helper, and a route whose only mention
    of the helper would be in prose is not."""
    walked = _walk(app)
    assert walked["/api/account/prefs [POST]"] is True
    assert walked["/api/users/add [POST]"] is True
    assert walked["/api/train/submit [POST]"] is True          # through _train_csrf_body
    assert walked["/api/generate [POST]"] is False
    assert "_train_csrf_body" in _token_checkers()
    assert "_recipe_write_body" in _token_checkers()


def test_the_three_account_stores_check_the_token(app):
    walked = _walk(app)
    for key in ("/api/view-presets [POST]", "/api/snippets [POST]", "/api/presets [POST]"):
        assert walked[key] is True, key


# The wave 2 and wave 3 lanes' own POST families (recipes, Train a LoRA, the account store
# Help and the recipe drafts share, the narrator's poke) each check the session's CSRF token
# before they act. Older POSTs predate the rule and are in CSRF_KNOWN_DEBT; a NEW route under
# one of these prefixes that forgets the check fails by name. The walk above cannot say "no
# lane route may ever be listed as debt" about its own list, so this test does.
_LANE_PREFIXES = ("/api/recipes", "/api/train", "/api/help", "/api/account/prefs",
                  "/api/narrator",
                  # wave 5, Session N: bulk curation and the collections manager
                  "/api/curate", "/api/collections/manage",
                  # wave 5, Session P: the Loom's new local routes
                  "/api/loom/submit-abandon",
                  # Session P, Stage B1: the music bed, the EDL export, the manual order
                  "/api/loom/bed", "/api/loom/beds", "/api/loom/export-edl", "/api/collections/order",
                  # GitHub #62: the Loom fills a missing frame thumbnail
                  "/api/loom/frame-thumbs")


def test_every_lane_post_checks_the_token_with_zero_debt(app):
    walked = _walk(app)
    lane = {k: checks for k, checks in walked.items()
            if k.endswith(" [POST]") and k.startswith(_LANE_PREFIXES)}
    missing = sorted(k for k, checks in lane.items() if not checks)
    assert not missing, "lane POST routes with no CSRF check: %s" % missing
    debt = sorted(k for k in CSRF_KNOWN_DEBT if k.startswith(_LANE_PREFIXES))
    assert not debt, (
        "a lane route is listed as CSRF debt: {}. Lane routes check the token; give the "
        "handler `_check_csrf(body)` instead of listing it.".format(debt))
    # the families are really there (a renamed prefix would make this vacuous)
    checked = set(lane)
    assert any(k.startswith("/api/train") for k in checked), sorted(checked)
    assert any(k.startswith("/api/recipes") for k in checked), sorted(checked)
    assert "/api/account/prefs [POST]" in checked, sorted(checked)
    assert "/api/narrator/poke [POST]" in checked, sorted(checked)
    assert {"/api/curate [POST]", "/api/curate/restore [POST]",
            "/api/collections/manage [POST]"} <= checked, sorted(checked)
    assert {"/api/loom/bed [POST]", "/api/loom/beds/sweep [POST]",
            "/api/loom/export-edl [POST]", "/api/collections/order [POST]",
            "/api/loom/frame-thumbs [POST]"} <= checked, sorted(checked)


# ---------------------------------------------------------------------------
# The three stores, end to end
# ---------------------------------------------------------------------------

def _two_sessions(tmp_path):
    app = create_app(tmp_path)
    alice = login_test_client(app, username="alice", password="a-real-test-password-1")
    bob = login_test_client(app, username="bob", password="a-real-test-password-2")
    return alice, bob


def _store_file(tmp_path, folder, user):
    name = {"view_presets": "views.json", "prompt_snippets": "snippets.json",
            "toolbox_presets": "presets.json"}[folder]
    return paths.account_dir(tmp_path, user) / name


_STORES = [
    ("/api/view-presets", {"name": "mine", "query": "?q=1"}, "view_presets"),
    ("/api/snippets", {"snippets": ["masterpiece"]}, "prompt_snippets"),
]


@pytest.mark.parametrize("url,body,folder", _STORES)
def test_a_store_post_without_the_token_is_refused_and_writes_nothing(tmp_path, url, body,
                                                                      folder):
    alice, _bob = _two_sessions(tmp_path)
    for bad in (dict(body), dict(body, csrf=""), dict(body, csrf="not-this-sessions")):
        r = alice.post(url, json=bad)
        assert r.status_code == 400, (url, bad)
        assert r.get_json() == {"error": _REFUSAL}
    assert not _store_file(tmp_path, folder, "alice").exists(), (
        "a refused POST wrote the store anyway")


@pytest.mark.parametrize("url,body,folder", _STORES)
def test_a_store_post_with_the_token_saves(tmp_path, url, body, folder):
    alice, _bob = _two_sessions(tmp_path)
    r = alice.post(url, json=with_csrf(alice, body))
    assert r.status_code == 200, r.get_json()
    assert _store_file(tmp_path, folder, "alice").exists()


@pytest.mark.parametrize("url,body,folder", _STORES)
def test_one_sessions_token_does_not_work_for_another(tmp_path, url, body, folder):
    alice, bob = _two_sessions(tmp_path)
    r = bob.post(url, json=dict(body, csrf=session_csrf(alice)))
    assert r.status_code == 400
    assert not _store_file(tmp_path, folder, "bob").exists()


@pytest.mark.parametrize("url,body,folder", _STORES)
def test_a_store_get_needs_no_token(tmp_path, url, body, folder):
    alice, _bob = _two_sessions(tmp_path)
    assert alice.get(url).status_code == 200


def test_a_preset_import_without_the_token_never_reaches_pixai(tmp_path, monkeypatch, pixai):
    """/api/presets reads the task from PixAI with the owner's key: a refused POST must
    stop before that read, not after it."""
    seen = []
    monkeypatch.setattr(task_reads_mod, "task_detail_gql",
                        lambda s, tid: seen.append(tid) or {
                            "parameters": {"sceneId": "a-scene",
                                           "chat": {"prompts": "P", "modelId": "1"}}})
    alice, bob = _two_sessions(tmp_path)
    for client, bad in ((alice, {"task_id": "111"}),
                        (alice, {"task_id": "111", "csrf": "wrong"}),
                        (bob, {"task_id": "111", "csrf": session_csrf(alice)})):
        r = client.post("/api/presets", json=bad)
        assert r.status_code == 400 and r.get_json() == {"error": _REFUSAL}
    assert seen == [], "a refused preset import still read the task from PixAI"
    assert not _store_file(tmp_path, "toolbox_presets", "alice").exists()
    d = alice.post("/api/presets", json=with_csrf(alice, {"task_id": "111"})).get_json()
    assert d.get("imported") == "a-scene" and seen == ["111"]
    assert alice.get("/api/presets").status_code == 200


# ---------------------------------------------------------------------------
# The client half: the three callers send the page's token
# ---------------------------------------------------------------------------

_SRC = Path(__file__).resolve().parents[2] / "gallery" / "src"


@pytest.mark.parametrize("rel,route", [
    ("App.jsx", "/api/view-presets"),
    ("components/GenerateDrawer.jsx", "/api/snippets"),
    ("components/EditTab.jsx", "/api/presets"),
])
def test_each_client_caller_sends_the_token(rel, route):
    src = (_SRC / rel).read_text(encoding="utf-8")
    posts = [ln for ln in src.splitlines() if 'apiPost("%s"' % route in ln]
    assert posts, "{} no longer posts to {}".format(rel, route)
    for ln in posts:
        assert "csrf" in ln, "{} posts to {} without the page's token: {}".format(
            rel, route, ln.strip())


def test_the_presets_store_file_is_where_this_test_looks(tmp_path, monkeypatch, pixai):
    """Keeps the 'writes nothing' assertions above honest: a successful import really
    does land in toolbox_presets/<account>.json, so its absence after a refusal means
    something."""
    monkeypatch.setattr(task_reads_mod, "task_detail_gql", lambda s, tid: {
        "parameters": {"sceneId": "s", "chat": {"prompts": "P", "modelId": "1"}}})
    alice, _bob = _two_sessions(tmp_path)
    alice.post("/api/presets", json=with_csrf(alice, {"task_id": "9"}))
    assert json.loads(_store_file(tmp_path, "toolbox_presets", "alice")
                      .read_text(encoding="utf-8"))["s"]["from_task"] == "9"
