"""The explicit CSRF token on state-changing routes: the three per-account stores that
lacked it, and a guard that makes every other gap visible.

THE THREE STORES. `POST /api/view-presets` (saved views), `POST /api/snippets` (prompt
snippets) and `POST /api/presets` (banked Toolbox presets) each write a per-account file,
and `/api/presets` also reaches PixAI with the owner's key. They checked no token, unlike
the other per-account writes (`/api/account/prefs`, the user-admin routes). They now refuse
a POST without the session's token -- 400 with the same "reload" wording, BEFORE any read,
write or network call -- and GET is untouched.

THE GUARD. `test_every_state_changing_route_checks_the_token_or_is_known_debt` walks
`app.url_map` for every POST / PUT / PATCH / DELETE rule and decides, from the handler's
own syntax tree, whether it calls `_check_csrf` -- directly or through a helper that does
(`_train_csrf_body`, `_recipe_write_body`). A route that does not must be listed in
`CSRF_KNOWN_DEBT` with a one-word reason. That list is the debt the app security review
takes on (scope 2026-10-02, platform item 1); it is generated, never hand-typed, and it can
only SHRINK: a listed route that gains the token fails here until its line is deleted, so
the list never claims a gap that is closed.

Static on purpose: these handlers spend credits and delete files, so the guard never runs
one (the stance tests/test_route_tiers.py documents).

The reason classes:
  store    -- a per-account or install-wide settings store (skins, branding, the Loom's
              boards, the job log);
  data     -- changes or removes library data, local or on the PixAI account;
  spend    -- reaches PixAI's paid generation path (prices, submits);
  control  -- server control or a long local job (stop/restart, Panel jobs, exports);
  loopback -- LOCALHOST tier: refused to every non-local session by the front door;
  nonce    -- carries its own per-render witness instead (the feat beacon).
Why the debt is not wide open today: the session cookie is SameSite=Lax, and the JSON
routes read `request.get_json(silent=True)`, which ignores a cross-site form post's body.
"""
import ast
import inspect
import json
import textwrap
from pathlib import Path

import pytest

from moonglade import backup as core
from moonglade import paths
from moonglade.gallery import LOCALHOST, _account_key, create_app, route_tier
from tests.conftest import login_test_client, session_csrf, with_csrf

_GALLERY = Path(__file__).resolve().parents[1] / "moonglade" / "gallery.py"
_STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}
_REFUSAL = "Your session expired. Reload the page and try again."

# THE KNOWN DEBT -- generated from the walk below, never hand-authored. One line per
# (rule, method) that changes state without the explicit token. Do NOT add a NEW route
# here to make this test pass: give the route the check (`_check_csrf(body)` after the
# body parse, refusing 400 with the session-expired wording) and send `csrf` from its
# client. This list is for the security review, and it only shrinks.
CSRF_KNOWN_DEBT = {
    "/api/ach-event [POST]": "nonce",
    "/api/assets/fetch [POST]": "data",
    "/api/bonjour/settings [POST]": "control",
    "/api/branding [POST]": "store",
    "/api/branding/banner/earned [POST]": "store",
    "/api/branding/mark/custom [POST]": "store",
    "/api/branding/mark/custom/remove [POST]": "store",
    "/api/branding/shortcut [POST]": "loopback",
    "/api/branding/slot [POST]": "store",
    "/api/branding/slot/active [POST]": "store",
    "/api/branding/slot/crop [POST]": "store",
    "/api/claim [POST]": "data",
    "/api/collection [POST]": "data",
    "/api/delete-image [POST]": "loopback",
    "/api/delete-local [POST]": "data",
    "/api/delete-preview [POST]": "loopback",
    "/api/delete-tasks [POST]": "loopback",
    "/api/edit [POST]": "spend",
    "/api/edit-prompt/<media_id> [POST]": "data",
    "/api/enhance [POST]": "spend",
    "/api/fix [POST]": "spend",
    "/api/generate [POST]": "spend",
    "/api/import-local [POST]": "loopback",
    "/api/import-task [POST]": "data",
    "/api/jobs [POST]": "store",
    "/api/jobs/dismiss [POST]": "store",
    "/api/library-path [POST]": "control",
    "/api/loom/delete [POST]": "store",
    "/api/loom/export [POST]": "control",
    "/api/loom/export-bundle [POST]": "control",
    "/api/loom/export-cancel [POST]": "control",
    "/api/loom/generate [POST]": "spend",
    "/api/loom/handoff [POST]": "store",
    "/api/loom/import-bundle [POST]": "control",
    "/api/loom/import-frames [POST]": "store",
    "/api/loom/set [POST]": "store",
    "/api/loom/spend [POST]": "spend",
    "/api/mirror/connect [POST]": "data",
    "/api/mirror/enable [POST]": "loopback",
    "/api/panel/cancel [POST]": "loopback",
    "/api/panel/run [POST]": "control",
    "/api/panel/schedule [POST]": "control",
    "/api/panel/sweep [POST]": "loopback",
    "/api/price [POST]": "spend",
    "/api/rate/<media_id> [POST]": "data",
    "/api/rebuild-poster/<media_id> [POST]": "data",
    "/api/replace-prompts [POST]": "data",
    "/api/scene [POST]": "spend",
    "/api/series [POST]": "data",
    "/api/server/restart [POST]": "control",
    "/api/server/stop [POST]": "control",
    "/api/setup/save-key [POST]": "loopback",
    "/api/siblings [POST]": "data",
    "/api/skin [POST]": "store",
    "/api/trash/delete-forever [POST]": "loopback",
    "/api/trash/empty [POST]": "loopback",
    "/api/trash/restore [POST]": "data",
    "/api/upload [POST]": "data",
    "/export-zip [POST]": "data",
}
_REASONS = {"store", "data", "spend", "control", "loopback", "nonce"}


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
    """`_check_csrf` plus every function in moonglade_gallery.py that calls it, directly or
    through another such function -- resolved to a fixed point, so a helper of a helper
    counts. A name defined more than once counts only when EVERY definition checks."""
    tree = ast.parse(_GALLERY.read_text(encoding="utf-8"))
    defs = {}
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


def test_every_state_changing_route_checks_the_token_or_is_known_debt(app):
    walked = _walk(app)
    missing = sorted(k for k, checks in walked.items() if not checks)
    unlisted = [k for k in missing if k not in CSRF_KNOWN_DEBT]
    closed = sorted(k for k in CSRF_KNOWN_DEBT if walked.get(k) is True)
    gone = sorted(k for k in CSRF_KNOWN_DEBT if k not in walked)
    replacement = "\n".join('    "{}": "{}",'.format(k, CSRF_KNOWN_DEBT.get(k, "?"))
                            for k in missing)
    assert not unlisted, (
        "state-changing route(s) with no CSRF token check: {}. Add `_check_csrf(body)` to "
        "the handler (and send `csrf` from its client) -- do not list a new route as "
        "debt.".format(unlisted))
    assert not closed and not gone, (
        "CSRF_KNOWN_DEBT names route(s) that now check the token ({}) or no longer exist "
        "({}). The list only shrinks; replace it with:\n{}".format(closed, gone, replacement))


def test_the_known_debt_list_is_well_formed():
    assert set(CSRF_KNOWN_DEBT.values()) <= _REASONS, CSRF_KNOWN_DEBT
    assert list(CSRF_KNOWN_DEBT) == sorted(CSRF_KNOWN_DEBT), "keep the list sorted"


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


def test_the_lists_classes_match_the_route_tiers(app):
    """`loopback` means the front door already refuses every non-local session, so it is
    only honest on a LOCALHOST route -- and every LOCALHOST debt route says so."""
    by_key = {}
    for rule in app.url_map.iter_rules():
        for m in (rule.methods or set()) & _STATE_CHANGING:
            by_key["{} [{}]".format(rule.rule, m)] = route_tier(
                app.view_functions[rule.endpoint], m)
    for key, reason in CSRF_KNOWN_DEBT.items():
        if key not in by_key:
            continue                     # the shrink test above names it
        if reason == "loopback":
            assert by_key[key] == LOCALHOST, key
        elif by_key[key] == LOCALHOST:
            assert key.split(" [")[0] in ("/api/bonjour/settings", "/api/library-path",
                                          "/api/panel/schedule"), (
                "{} is LOCALHOST: classify it `loopback`".format(key))


# ---------------------------------------------------------------------------
# The three stores, end to end
# ---------------------------------------------------------------------------

def _two_sessions(tmp_path):
    app = create_app(tmp_path)
    alice = login_test_client(app, username="alice", password="a-real-test-password-1")
    bob = login_test_client(app, username="bob", password="a-real-test-password-2")
    return alice, bob


def _store_file(tmp_path, folder, user):
    return paths.state_path(tmp_path, folder) / (_account_key(user) + ".json")


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
    monkeypatch.setattr(core, "task_detail_gql",
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

_SRC = Path(__file__).resolve().parents[1] / "gallery" / "src"


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
    monkeypatch.setattr(core, "task_detail_gql", lambda s, tid: {
        "parameters": {"sceneId": "s", "chat": {"prompts": "P", "modelId": "1"}}})
    alice, _bob = _two_sessions(tmp_path)
    alice.post("/api/presets", json=with_csrf(alice, {"task_id": "9"}))
    assert json.loads(_store_file(tmp_path, "toolbox_presets", "alice")
                      .read_text(encoding="utf-8"))["s"]["from_task"] == "9"
