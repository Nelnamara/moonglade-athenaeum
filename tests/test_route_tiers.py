"""url_map-driven CATCH-ALL auth-tier coverage: it must be structurally impossible
for a route to escape its auth tier unnoticed.

WHY THIS FILE EXISTS
--------------------
tests/test_web_auth.py hand-maintains four lists of paths
(_PREVIOUSLY_UNGATED_JSON_GET / _JSON_POST / _HTML_GET / _HTML_POST). A
hand-maintained list is precisely what the front-door refactor
(moonglade_gallery.py's _enforce_front_door()) was undertaken to eliminate, and those
lists had ALREADY drifted: every credit-spending route -- /api/generate,
/api/edit, /api/fix, /api/loom/generate -- appears in none of them. They are
gated today, but nothing in the suite said so, and nothing would have noticed
if they stopped being.

This file does not enumerate paths. It enumerates `app.url_map` -- the single
source of truth for what is actually routable -- and asserts that EVERY
registered (endpoint, method) pair both DECLARES a tier and has that tier
ENFORCED against a live request.

THE TIER IS NOT DECLARED HERE ANY MORE (2026-08-23)
---------------------------------------------------
It used to be. This file carried a literal (endpoint, method) -> tier table that
mirrored every @app.route registration in moonglade_gallery.py, which made the
tier -- a property OF THE ROUTE -- live in the test instead of on the route, and
made every route addition a two-file edit. It also made this file the third
most-churned test artefact in the repo.

The tier now rides the route as `@tier(LOGIN)` / `@tier(LOCALHOST)` /
`@tier(PUBLIC)` (moonglade_gallery.tier), _enforce_front_door() reads it off
app.view_functions at request time, and create_app() refuses to return an app in
which any registered rule declares nothing -- so an undeclared route now fails at
app creation rather than waiting for CI.

What this file kept is everything that was ever load-bearing:
  * it still ENUMERATES app.url_map rather than a list of paths;
  * it still fails, by name, on a route with no tier -- and additionally proves
    the app-creation assertion really fires (test_undeclared_route_fails_at_app_creation);
  * it still proves all three tiers against a LIVE REQUEST, including the one
    assertion whose absence let three gate regressions ship in a single week:
    a LOCALHOST route must refuse an AUTHENTICATED NON-LOCAL session;
  * and it adds TIER_SNAPSHOT below, a generated golden list, so that CHANGING a
    route's tier is a visible diff in review rather than a silent one-word edit
    somewhere in a 13,000-line module.

WHY (endpoint, method) AND NOT THE RULE STRING
----------------------------------------------
Two real shapes in this app defeat a dict keyed on the rule string:
  * /api/jobs is ONE rule string mapping to TWO endpoints (GET api_jobs, POST
    api_jobs_register). Keyed on "/api/jobs", one of them silently vanishes.
  * /api/panel/schedule is ONE endpoint whose tier DIFFERS BY METHOD (GET is
    login-only so a LAN Panel can render its settings; POST is localhost-only).
    Keyed on the endpoint alone, the two tiers collapse into one and the weaker
    one wins.
(endpoint, method) is the smallest key that separates both. The declaration
carries that split natively -- `@tier(LOGIN, POST=LOCALHOST)`.

WHAT THIS FILE DELIBERATELY DOES NOT DO
---------------------------------------
It never asserts that an authorized request SUCCEEDS. Proving a route is
reachable means executing its handler, and these handlers spend the owner's
credits, delete from their real PixAI account, and move files on disk. This file
proves REFUSAL only -- that is the security-relevant direction, and it is the one
that can be proven without side effects. Per-route success paths belong in the
per-feature test files that already own them. (The one exception at the bottom is
deliberate and narrow: /api/panel/status is read with a real session because what
it must NOT hand a LAN caller is only observable past the gate, and reading job
state spends, deletes and moves nothing.)
"""
import re

import pytest

import moonglade_gallery
import moonglade_backup as core
from moonglade_gallery import (
    LOCALHOST,
    LOGIN,
    PUBLIC,
    TIERS,
    create_app,
    route_tier,
    assert_every_route_declares_a_tier,
)


LAN = "203.0.113.5"      # TEST-NET-3 -- the "some other device on the LAN" stand-in
                         # used throughout tests/test_web_auth.py.

# The tier names themselves are imported, not restated: PUBLIC (reachable with no
# session at all), LOGIN (any logged-in session, local or LAN), LOCALHOST (a
# logged-in session AND a loopback remote_addr). Restating them here is how the
# test and the app drift apart one rename at a time.

# The two refusal shapes the front door emits (see _enforce_front_door()). Routes
# whose historical contract is JSON get a parseable 401; everything else gets a
# redirect to the login page.
_JSON_GATE_PREFIXES = ("/api/",)
_AUTH_REQUIRED_BODY = {"error": "authentication required"}
_REDIRECT_CODES = (301, 302, 303, 307, 308)


# ---------------------------------------------------------------------------
# THE GOLDEN SNAPSHOT -- generated, never hand-authored
# ---------------------------------------------------------------------------
# One line per (rule, method), "<rule> [<METHOD>] <TIER>", sorted. This is NOT the
# old declaration table wearing a new hat, and the difference is the whole point:
#   * it declares nothing -- moonglade_gallery.py's @tier decorators do that, and
#     this list is generated FROM them (the failure message below prints the
#     replacement to paste);
#   * a NEW route therefore needs a judgement call in exactly one place (which
#     @tier to put on it) plus a mechanical paste here;
#   * but CHANGING an existing route's tier -- the edit that actually matters and
#     the one a 13,000-line diff can hide -- shows up here as a one-line diff with
#     the old tier and the new one side by side in review.
# Do not "fix" a failure here by editing the line to match. Read the diff first:
# if the tier moved and you did not mean it to, the bug is in the decorator.
TIER_SNAPSHOT = [
    "/ [GET] LOGIN",
    "/api/account [GET] LOGIN",
    "/api/account/card-history [GET] LOGIN",
    "/api/account/coupons [GET] LOGIN",
    "/api/account/credit-log [GET] LOGIN",
    "/api/ach-event [POST] LOCALHOST",
    "/api/achievements [GET] LOGIN",
    "/api/artwork-views [GET] LOGIN",
    "/api/assets/fetch [POST] LOGIN",
    "/api/assets/status [GET] LOGIN",
    "/api/bonjour/settings [POST] LOCALHOST",
    "/api/bonjour/status [GET] LOGIN",
    "/api/branding [GET] LOGIN",
    "/api/branding [POST] LOGIN",
    "/api/branding/banner/earned [POST] LOGIN",
    "/api/branding/banners/earned [GET] LOGIN",
    "/api/branding/mark/custom [POST] LOGIN",
    "/api/branding/mark/custom/remove [POST] LOGIN",
    "/api/branding/shortcut [POST] LOCALHOST",
    "/api/branding/slot [POST] LOGIN",
    "/api/branding/slot/active [POST] LOGIN",
    "/api/branding/slot/crop [POST] LOGIN",
    "/api/claim [POST] LOGIN",
    "/api/collection [POST] LOGIN",
    "/api/collections [GET] LOGIN",
    "/api/contact-sheet [GET] LOGIN",
    "/api/contests [GET] LOGIN",
    "/api/delete-image [POST] LOCALHOST",
    "/api/delete-local [POST] LOGIN",
    "/api/delete-preview [POST] LOCALHOST",
    "/api/delete-tasks [POST] LOCALHOST",
    "/api/duplicates [GET] LOGIN",
    "/api/duplicates/resolve [POST] LOGIN",
    "/api/duplicates/undo [POST] LOGIN",
    "/api/edit [POST] LOGIN",
    "/api/edit-prompt/<media_id> [POST] LOGIN",
    "/api/enhance [POST] LOGIN",
    "/api/enhance/emotions [GET] LOGIN",
    "/api/enhance/presets [GET] LOGIN",
    "/api/fix [POST] LOGIN",
    "/api/gallery-images [GET] LOGIN",
    "/api/generate [POST] LOGIN",
    "/api/health [GET] LOGIN",
    "/api/image-meta/<media_id> [GET] LOGIN",
    "/api/import-local [POST] LOCALHOST",
    "/api/import-task [POST] LOGIN",
    "/api/jobs [GET] LOGIN",
    "/api/jobs [POST] LOGIN",
    "/api/jobs/dismiss [POST] LOGIN",
    "/api/library-path [GET] LOGIN",
    "/api/library-path [POST] LOCALHOST",
    "/api/lineage/<media_id> [GET] LOGIN",
    "/api/login [POST] PUBLIC",
    "/api/logout [POST] PUBLIC",
    "/api/loom/delete [POST] LOGIN",
    "/api/loom/export [POST] LOGIN",
    "/api/loom/export-bundle [POST] LOGIN",
    "/api/loom/export-cancel [POST] LOGIN",
    "/api/loom/export-file [GET] LOGIN",
    "/api/loom/export-status [GET] LOGIN",
    "/api/loom/generate [POST] LOGIN",
    "/api/loom/get [GET] LOGIN",
    "/api/loom/handoff [POST] LOGIN",
    "/api/loom/import-bundle [POST] LOGIN",
    "/api/loom/import-frames [POST] LOGIN",
    "/api/loom/list [GET] LOGIN",
    "/api/loom/set [POST] LOGIN",
    "/api/loom/video-duration [GET] LOGIN",
    "/api/mirror/connect [POST] LOGIN",
    "/api/mirror/enable [POST] LOCALHOST",
    "/api/mirror/status [GET] LOGIN",
    "/api/model-search [GET] LOGIN",
    "/api/model-version [GET] LOGIN",
    "/api/myart/items [GET] LOGIN",
    "/api/myart/publish [POST] LOGIN",
    "/api/next/detail/<media_id> [GET] LOGIN",
    "/api/next/history [GET] LOGIN",
    "/api/next/library [GET] LOGIN",
    "/api/panel/cancel [POST] LOCALHOST",
    "/api/panel/run [POST] LOGIN",
    "/api/panel/schedule [GET] LOGIN",
    "/api/panel/schedule [POST] LOCALHOST",
    "/api/panel/status [GET] LOGIN",
    "/api/panel/summary [GET] LOGIN",
    "/api/ping [GET] LOGIN",
    "/api/pixai-cdn/thumb [GET] LOGIN",
    "/api/presets [GET] LOGIN",
    "/api/presets [POST] LOGIN",
    "/api/price [POST] LOGIN",
    "/api/rate/<media_id> [POST] LOGIN",
    "/api/rebuild-poster/<media_id> [POST] LOGIN",
    "/api/replace-prompts [POST] LOGIN",
    "/api/scene [POST] LOGIN",
    "/api/scenes [GET] LOGIN",
    "/api/series [POST] LOGIN",
    "/api/series/<sid> [GET] LOGIN",
    "/api/server/restart [POST] LOGIN",
    "/api/server/stop [POST] LOGIN",
    "/api/setup/save-key [POST] LOCALHOST",
    "/api/siblings [POST] LOGIN",
    "/api/similar/<media_id> [GET] LOGIN",
    "/api/skin [POST] LOGIN",
    "/api/snippets [GET] LOGIN",
    "/api/snippets [POST] LOGIN",
    "/api/stats [GET] LOGIN",
    "/api/suggest-prompt [GET] LOGIN",
    "/api/tag-suggest [GET] LOGIN",
    "/api/task-params/<task_id> [GET] LOGIN",
    "/api/task-status [GET] LOGIN",
    "/api/train/cover [GET] LOGIN",
    "/api/train/models [GET] LOGIN",
    "/api/train/quota [GET] LOGIN",
    "/api/train/recent-tasks [GET] LOGIN",
    "/api/train/submit [POST] LOGIN",
    "/api/trash/delete-forever [POST] LOCALHOST",
    "/api/trash/empty [POST] LOCALHOST",
    "/api/trash/list [GET] LOGIN",
    "/api/trash/restore [POST] LOGIN",
    "/api/update/apply [POST] LOGIN",
    "/api/update/check [GET] LOGIN",
    "/api/update/status [GET] LOGIN",
    "/api/upload [POST] LOGIN",
    "/api/users/add [POST] LOCALHOST",
    "/api/users/password [POST] LOGIN",
    "/api/users/remove [POST] LOGIN",
    "/api/video-task-params/<task_id> [GET] LOGIN",
    "/api/view-presets [GET] LOGIN",
    "/api/view-presets [POST] LOGIN",
    "/api/watch/status [GET] LOGIN",
    "/api/workflows [GET] LOGIN",
    "/api/your-art [GET] LOGIN",
    "/badge-thumb/<aid>.png [GET] LOGIN",
    "/branding/<path:fname> [GET] PUBLIC",
    "/contact-sheet [GET] LOGIN",
    "/export-csv [GET] LOGIN",
    "/export-zip [POST] LOGIN",
    "/full/<media_id> [GET] LOGIN",
    "/login [GET] PUBLIC",
    "/loom [GET] LOGIN",
    "/loom/dist/<path:fname> [GET] LOGIN",
    "/loom/vendor/<path:fname> [GET] LOGIN",
    "/next [GET] LOGIN",
    "/next/assets/<path:fname> [GET] PUBLIC",
    "/static/<path:filename> [GET] LOGIN",
    "/thumbs/<media_id>.jpg [GET] LOGIN",
    "/video-file/<media_id> [GET] LOGIN",
]


# Marking something PUBLIC costs you a second, explicit statement of what an
# anonymous caller actually gets. /logout is why this is not just "assert not
# redirected to /login": an anonymous GET /logout is a harmless no-op that
# redirects to /login all by itself, which is indistinguishable from the front
# door intercepting it unless the expectation is spelled out per route.
#
# This survived the move of the tiers onto the routes on purpose. The friction is
# the feature: @tier(PUBLIC) is one word and exempts a route from
# test_no_route_is_reachable_without_a_session, so it must cost a second,
# deliberate statement made in the test rather than beside the decorator.
PUBLIC_EXPECTED_STATUS = {
    ("login", "GET"): {200},
    # a 200 page now, not a redirect -- it has to run script client-side to purge
    # Cache Storage before navigating on to /login, which a 3xx can't do (see
    # test_session_revocation.py's test_logout_purges_cache_storage_client_side)
    ("api_login", "POST"): {200},   # success {"ok":true} or {"error":...} -- never a redirect
    ("api_logout", "POST"): {200},  # anonymous: authorized is False, csrf is never checked
    ("next_assets", "GET"): {404}, # missing bundle file 404s; it must never redirect to /login
    ("branding", "GET"): {404},    # missing art 404s; it must never redirect to /login
}

# A few routes only reach a meaningful decision with a meaningful payload.
# api_panel_run's own conditional check is `if spec["destructive"] and not
# _is_local_request()`, so an empty body stops at "unknown action" (400) and
# proves nothing.
PROBE_BODIES = {
    ("api_panel_run", "POST"): {"json": {"action": "organize", "confirm": True}},
}

# Not every localhost refusal is a 403. A form POST that refuses by redirecting
# back to the gallery with an error query string would be declared here, because
# a 403 JSON blob is a dead end in a browser flow. Empty today -- every
# LOCALHOST-tier route is /api/-prefixed and refuses with the 403 JSON the front
# door emits. Declared, not guessed -- and asserted just as strictly.
LOCALHOST_REFUSAL_IS_REDIRECT = {
}

# One dummy per converter TYPE, so a future /api/thing/<int:n> needs no edit here.
# An unknown converter raises rather than being skipped -- silently skipping a
# route it could not build a URL for is exactly the hole this file closes.
_DUMMY_BY_CONVERTER = {
    "UnicodeConverter": "probe-does-not-exist",
    "PathConverter": "probe/does-not-exist",
    "IntegerConverter": "1",
    "FloatConverter": "1.0",
    "UUIDConverter": "00000000-0000-0000-0000-000000000000",
    "NumberConverter": "1",
}


def _dummy_for(name, converter, endpoint):
    kind = type(converter).__name__
    if kind == "AnyConverter":                      # /<any(a,b):x>
        return str(converter.items[0])
    try:
        return _DUMMY_BY_CONVERTER[kind]
    except KeyError:
        raise AssertionError(
            "tests/test_route_tiers.py cannot build a probe URL for route "
            "{!r}: URL parameter <{}> uses converter {} and no dummy value is "
            "declared for it.\n"
            "FIX: add {!r} to _DUMMY_BY_CONVERTER in this file, with a value "
            "that is syntactically valid but refers to nothing that exists "
            "(the probe must never resolve to real data)."
            .format(endpoint, name, kind, kind))


def _probe_url(rule):
    """Concrete, deliberately-nonexistent URL for a rule, params filled in."""
    values = {n: _dummy_for(n, c, rule.endpoint) for n, c in rule._converters.items()}
    return rule.build(values, append_unknown=False)[1]


def _registered_pairs(app):
    """Every (endpoint, method) pair the app will actually route.

    HEAD and OPTIONS are dropped deliberately, not carelessly. Werkzeug adds HEAD
    automatically alongside GET and dispatches it to the SAME view through the
    SAME before_request chain, so the GET assertion already covers it. OPTIONS is
    answered by Werkzeug's automatic-options handler and never reaches a view
    function at all, so there is no handler body to protect. Every other method
    is a distinct dispatch and is checked.
    """
    pairs = {}
    for rule in app.url_map.iter_rules():
        for method in (rule.methods or set()) - {"HEAD", "OPTIONS"}:
            pairs[(rule.endpoint, method)] = rule
    return pairs


def _declared_tier(app, endpoint, method):
    """The tier the ROUTE declares for this method -- read exactly the way
    _enforce_front_door() reads it, off app.view_functions, so this file cannot
    pass while the gate is looking somewhere else."""
    return route_tier(app.view_functions.get(endpoint), method)


def _snapshot_lines(app):
    """The generated golden list: one "<rule> [<METHOD>] <TIER>" per routable pair.

    Keyed on (rule, method) rather than (endpoint, method) because this list is
    read by humans in a diff, and the URL is what a reviewer recognises. Both
    shapes that defeat a rule-keyed DICT are still distinct LINES here: /api/jobs
    appears twice (GET and POST, different endpoints), and so does
    /api/panel/schedule (GET LOGIN, POST LOCALHOST).
    """
    lines = []
    for rule in app.url_map.iter_rules():
        view = app.view_functions[rule.endpoint]
        for method in sorted((rule.methods or set()) - {"HEAD", "OPTIONS"}):
            lines.append("{} [{}] {}".format(rule, method, route_tier(view, method)))
    return sorted(lines)


@pytest.fixture()
def app(tmp_path):
    return create_app(tmp_path)


@pytest.fixture()
def armed(monkeypatch):
    """Make it SAFE to probe a route that turns out to be wrongly open.

    This is the uncomfortable part of any catch-all gate test and it deserves to
    be stated plainly rather than hand-waved. Asserting 401/403 asserts the
    request was refused BEFORE the handler body ran -- which is true exactly when
    the code is correct. The whole point of this file is to catch the case where
    it ISN'T, and in that case the probe really does execute the handler:
    /api/server/stop would kill the pytest process, a destructive /api/panel/run
    would spawn a real maintenance subprocess, /api/generate would spend real
    credits. A test that only behaves when the code is already right is not a
    safety net.

    Four layers, and note that the third one makes safety and detection the same
    mechanism rather than trading one against the other:

    1. The app under test is already sandboxed by tests/conftest.py's autouse
       fixtures: _config_path is redirected into tmp_path (so there is no real
       PIXAI_API_KEY to spend and no real config.json to overwrite), _rest_get /
       _rest_post raise, and MOONGLADE_DISABLE_WATCH stops the live socket.
       out_dir is an empty tmp_path, so "the owner's files" are not present.

    2. This fixture additionally severs every primitive by which a wrongly-open
       handler could reach outside that sandbox: process exit, subprocess spawn,
       outbound HTTP, and core's spend/delete calls. Nothing destructive can
       physically happen even on a total gate failure.

    3. Each severed primitive raises instead of no-op'ing, so a handler that
       wrongly runs 500s -- and 500 is not in this file's accepted refusal set,
       so the route FAILS LOUDLY and by name. Silencing the side effect does not
       silence the finding; it converts it into one.

    4. Probe URLs address only nonexistent ids (_DUMMY_BY_CONVERTER) and probe
       bodies are inert, so even the reachable-but-harmless paths touch nothing
       real. This is the weakest layer and is treated as a bonus, never the
       guarantee -- which is why the refusal set below accepts ONLY 401/redirect
       (and 403 for LOCALHOST). A wrongly-open handler that happens to answer
       400 "missing parameter" must not be mistaken for a refusal.
    """
    import subprocess

    def blocked(what):
        def _fire(*a, **k):
            raise AssertionError(
                "SAFETY TRIPWIRE: a route probe reached {} -- meaning a handler "
                "body actually executed instead of being refused at the gate. "
                "The offending route is named in the failing assertion above."
                .format(what))
        return _fire

    monkeypatch.setattr(moonglade_gallery, "_schedule_server_exit", blocked("process exit"))
    for name in ("Popen", "run", "call", "check_output", "check_call"):
        monkeypatch.setattr(subprocess, name, blocked("subprocess." + name),
                            raising=False)
    for name in ("gql_adhoc", "submit_generation", "submit_fixer",
                 "delete_task_gql", "claim_reward"):
        monkeypatch.setattr(core, name, blocked("core." + name), raising=False)
    import requests
    monkeypatch.setattr(requests.Session, "request", blocked("outbound HTTP"),
                        raising=False)
    return True


def _login(app, username="tier-probe", password="a-real-test-password-1"):
    """A real, fully-authenticated client -- used ONLY to prove that being logged
    in is still not enough for a LOCALHOST route."""
    core.add_or_update_web_user(username, password)
    cli = app.test_client()
    html = cli.get("/login").get_data(as_text=True)
    # The React shell's window.MG_BOOT JSON blob (the ONLY login page since the
    # classic cut, 2026-08-08); sign-in is the JSON POST the real app makes.
    m = re.search(r'"csrf":\s*"([^"]+)"', html)
    assert m, "login page did not render a csrf token in MG_BOOT"
    d = cli.post("/api/login", json={"username": username, "password": password,
                                     "csrf": m.group(1)}).get_json()
    assert d and d.get("ok"), "probe login failed to authenticate: {!r}".format(d)
    return cli


def _describe_refusal(resp):
    return "status={} location={!r} body={!r}".format(
        resp.status_code, resp.headers.get("Location"),
        resp.get_data(as_text=True)[:120])


def _anonymous_refusal_problem(path, resp):
    """None if `resp` is a genuine front-door refusal, else why it isn't.

    The accepted set is exact and short on purpose. Any 4xx is NOT acceptable: a
    route that is wrongly wide open will frequently answer 400 for a missing
    parameter, and treating that as "refused" would let this entire file pass
    while the gate is gone.
    """
    if path.startswith(_JSON_GATE_PREFIXES):
        if resp.status_code != 401:
            return "expected 401 (JSON contract), got {}".format(_describe_refusal(resp))
        if resp.get_json(silent=True) != _AUTH_REQUIRED_BODY:
            return "expected body {!r}, got {}".format(_AUTH_REQUIRED_BODY,
                                                       _describe_refusal(resp))
        return None
    if resp.status_code not in _REDIRECT_CODES:
        return "expected a redirect to /login, got {}".format(_describe_refusal(resp))
    if not (resp.headers.get("Location") or "").startswith("/login"):
        return "expected Location to start with /login, got {}".format(_describe_refusal(resp))
    return None


# ---------------------------------------------------------------------------
# 1. Completeness: no route may exist without a declared tier
# ---------------------------------------------------------------------------

def test_every_registered_route_declares_a_tier(app):
    """The tier is read back off the ROUTE, exactly where the gate reads it.

    create_app() already refuses to build an app that fails this (see
    test_undeclared_route_fails_at_app_creation below), so reaching this
    assertion at all means something got past that -- a view function replaced
    after registration, an endpoint added to app.view_functions by hand, a
    blueprint registered late. It stays because "the constructor checks it" and
    "the suite checks it" fail in different ways.
    """
    undeclared = sorted(
        (endpoint, method) for (endpoint, method) in _registered_pairs(app)
        if _declared_tier(app, endpoint, method) is None)

    assert not undeclared, (
        "{} route(s) are registered in app.url_map but declare NO auth tier:\n"
        "{}\n"
        "\n"
        "FIX: put the tier ON the route in moonglade_gallery.py, under its\n"
        "@app.route(...):\n"
        "    @app.route(\"/api/thing\", methods=[\"POST\"])\n"
        "    @tier(LOGIN)\n"
        "    def api_thing():\n"
        "choosing the tier by what the handler can DO:\n"
        "  LOGIN     - browse the library, spend the owner's credits, manage your\n"
        "              OWN account. A signed-in LAN device is NOT read-only.\n"
        "  LOCALHOST - irreversible cloud deletion, config.json writes, file-moving\n"
        "              maintenance, or shelling out on the server machine. The front\n"
        "              door enforces this for you; do NOT also hand-write\n"
        "              `if not _is_local_request(): return ..., 403` in the handler.\n"
        "  PUBLIC    - the login surface only; also requires an entry in\n"
        "              PUBLIC_EXPECTED_STATUS in this file.\n"
        "This failure is not bureaucracy: every credit-spending route\n"
        "(/api/generate, /api/edit, /api/fix, /api/loom/generate) was\n"
        "missing from the hand-maintained lists in tests/test_web_auth.py\n"
        "for exactly this reason, and nothing noticed."
        .format(len(undeclared),
                "\n".join("    (\"{}\", \"{}\")".format(e, m) for e, m in undeclared)))


def test_undeclared_route_fails_at_app_creation(app):
    """The completeness check is enforced at APP CREATION, not just in CI.

    This is the half of the old declaration table that could never be a test.
    While the tier lived here, a route with no tier was a red CI run; now it is a
    server that refuses to start, which is the earliest and loudest moment
    available. Proven the only honest way -- by registering a route that declares
    nothing on a real app and calling the very function create_app() calls.
    """
    app.add_url_rule("/probe/undeclared", "probe_undeclared", lambda: "")

    with pytest.raises(AssertionError) as excinfo:
        assert_every_route_declares_a_tier(app)

    message = str(excinfo.value)
    assert "/probe/undeclared" in message, (
        "the app-creation assertion fired but did not NAME the offending route; a\n"
        "failure that makes you go looking is most of a failure that gets ignored.\n"
        "Got: {}".format(message))
    assert "@tier(" in message, (
        "the app-creation assertion did not tell the reader how to fix it. Got: "
        "{}".format(message))


def test_declared_tiers_are_known_values(app):
    """The tiers themselves stay meaningful.

    tier() rejects an unknown name at decoration time, so this is belt-and-braces
    against a declaration reaching the gate some other way -- and it is cheap.
    Inventing a fourth tier without teaching _enforce_front_door() to enforce it
    produces a declaration that asserts nothing.
    """
    bad = {(e, m): _declared_tier(app, e, m)
           for (e, m) in _registered_pairs(app)
           if _declared_tier(app, e, m) not in TIERS}
    assert not bad, (
        "unknown tier value(s) declared on route(s): {}\n"
        "Only {} exist.".format(bad, ", ".join(TIERS)))


# ---------------------------------------------------------------------------
# 2. The golden snapshot: a tier CHANGE is a visible diff
# ---------------------------------------------------------------------------

def test_tier_snapshot_matches_the_declarations(app):
    current = _snapshot_lines(app)
    if current == list(TIER_SNAPSHOT):
        return

    expected = set(TIER_SNAPSHOT)
    added = [l for l in current if l not in expected]
    removed = [l for l in TIER_SNAPSHOT if l not in set(current)]

    # A route whose TIER moved appears once in each list at the same rule+method.
    def _key(line):
        return line.rsplit(" ", 1)[0]
    moved_keys = {_key(l) for l in added} & {_key(l) for l in removed}
    moved = sorted(
        "  {}: {} -> {}".format(k,
                                next(l.rsplit(" ", 1)[1] for l in removed if _key(l) == k),
                                next(l.rsplit(" ", 1)[1] for l in added if _key(l) == k))
        for k in moved_keys)

    parts = []
    if moved:
        parts.append("{} route(s) CHANGED TIER -- read these before anything else:\n{}"
                     .format(len(moved), "\n".join(moved)))
    new_routes = [l for l in added if _key(l) not in moved_keys]
    gone_routes = [l for l in removed if _key(l) not in moved_keys]
    if new_routes:
        parts.append("{} new route(s):\n{}".format(
            len(new_routes), "\n".join("  " + l for l in new_routes)))
    if gone_routes:
        parts.append("{} route(s) no longer registered:\n{}".format(
            len(gone_routes), "\n".join("  " + l for l in gone_routes)))

    parts.append(
        "TIER_SNAPSHOT in this file is GENERATED from the @tier declarations in\n"
        "moonglade_gallery.py -- it never declares anything itself. If the change\n"
        "above is intended, replace TIER_SNAPSHOT with exactly this:\n\n"
        "TIER_SNAPSHOT = [\n{}\n]\n\n"
        "If a tier moved and you did not mean it to, fix the @tier decorator --\n"
        "not this list. That is the entire reason this list exists."
        .format("\n".join('    "{}",'.format(l) for l in current)))

    assert False, "\n\n".join(parts)


# ---------------------------------------------------------------------------
# 3. Enforcement, anonymous: everything non-PUBLIC refuses a session-less caller
# ---------------------------------------------------------------------------

def test_no_route_is_reachable_without_a_session(app, armed):
    """Every LOGIN and LOCALHOST route, probed with no cookie at all, from a LAN
    address and again from loopback -- localhost is not a trusted tier, so both
    must refuse identically."""
    cli = app.test_client()
    failures = []
    for (endpoint, method), rule in sorted(_registered_pairs(app).items()):
        if _declared_tier(app, endpoint, method) == PUBLIC:
            continue
        path = _probe_url(rule)
        body = PROBE_BODIES.get((endpoint, method), {})
        for addr in (LAN, "127.0.0.1"):
            resp = cli.open(path, method=method,
                            environ_overrides={"REMOTE_ADDR": addr}, **body)
            problem = _anonymous_refusal_problem(path, resp)
            if problem:
                failures.append("  {} {} ({}) from {}: {}".format(
                    method, path, endpoint, addr, problem))

    assert not failures, (
        "{} route probe(s) were NOT refused for an anonymous caller.\n"
        "Each line below is a route reachable with no credentials whatsoever:\n"
        "{}\n\n"
        "FIX: routes are gated centrally by _enforce_front_door() in\n"
        "moonglade_gallery.py -- if one of these got through, either it declares\n"
        "@tier(PUBLIC) (revert that unless it is genuinely part of the login\n"
        "surface) or the hook itself regressed, which would be a whole-app\n"
        "authentication bypass and should be treated as such."
        .format(len(failures), "\n".join(failures)))


# ---------------------------------------------------------------------------
# 4. Enforcement, LOCALHOST: being logged in is NOT enough
# ---------------------------------------------------------------------------

def test_localhost_only_routes_refuse_an_authenticated_lan_session(app, armed):
    """THE assertion whose absence let three real regressions ship.

    A valid session is not a local one. The gate must additionally require
    loopback for these routes, and only an AUTHENTICATED, NON-LOCAL probe reaches
    that decision at all -- an anonymous probe is refused for unrelated reasons
    and never gets near it. That is exactly how the original bugs hid: the
    localhost check was silently deleted from api_panel_cancel and
    api_panel_schedule (commit 0fd8cee) and never written at all in
    api_setup_save_key, while all three docstrings went on claiming
    "localhost-only".

    The check used to live in each handler body, one hand-written `if not
    _is_local_request()` at a time, with nothing structural keeping it there.
    Since 2026-08-23 it is the front door reading the route's own @tier(LOCALHOST)
    -- but this assertion is unchanged and is the reason that move is safe to
    make: it proves the enforcement from the outside, against a live request, and
    does not care where the check lives.
    """
    cli = _login(app)
    pairs = _registered_pairs(app)
    declared = sorted((e, m) for (e, m) in pairs
                      if _declared_tier(app, e, m) == LOCALHOST)
    assert declared, (
        "no LOCALHOST routes are declared anywhere in the app -- either every one "
        "of them lost its @tier(LOCALHOST), or this test stopped finding them. "
        "Both are emergencies.")

    failures = []
    for (endpoint, method) in declared:
        rule = pairs[(endpoint, method)]
        path = _probe_url(rule)
        body = PROBE_BODIES.get((endpoint, method), {})
        resp = cli.open(path, method=method,
                        environ_overrides={"REMOTE_ADDR": LAN}, **body)

        marker = LOCALHOST_REFUSAL_IS_REDIRECT.get((endpoint, method))
        if marker is not None:
            location = resp.headers.get("Location") or ""
            if resp.status_code not in _REDIRECT_CODES or marker not in location:
                failures.append("  {} {} ({}): expected a redirect whose Location "
                                "carries {!r}, got {}".format(
                                    method, path, endpoint, marker,
                                    _describe_refusal(resp)))
            continue

        if resp.status_code != 403:
            failures.append("  {} {} ({}): expected 403, got {}".format(
                method, path, endpoint, _describe_refusal(resp)))

    assert not failures, (
        "{} LOCALHOST-only route(s) accepted an AUTHENTICATED request from a "
        "non-local address ({}):\n{}\n\n"
        "FIX: the route declares @tier(LOCALHOST) and the front door is supposed\n"
        "to enforce it -- a failure here is the GATE regressing, not one handler\n"
        "forgetting a check, and every LOCALHOST route in the app is affected at\n"
        "once. Look at _enforce_front_door()'s LOCALHOST arm first.\n"
        "If the route is genuinely fine for a logged-in LAN device, change its\n"
        "declaration to @tier(LOGIN) and say why in its docstring -- do not leave\n"
        "the declaration and the code disagreeing, which is the exact state\n"
        "api_panel_cancel / api_panel_schedule / api_setup_save_key were found in."
        .format(len(failures), LAN, "\n".join(failures)))


def test_localhost_refusal_body_is_the_declared_one(app, armed):
    """The 403's wording is a contract, not a detail.

    The front end reads `error` off these responses, and three routes say
    something more specific than "localhost-only" (deleting from PixAI; importing
    onto the server's machine) -- wording that used to be written into each
    handler's own guard and now rides the declaration as `message=`. Moving where
    a string is produced is exactly the kind of refactor that silently rewords it.
    """
    cli = _login(app)
    pairs = _registered_pairs(app)
    failures = []
    for (endpoint, method) in sorted(pairs):
        if _declared_tier(app, endpoint, method) != LOCALHOST:
            continue
        if (endpoint, method) in LOCALHOST_REFUSAL_IS_REDIRECT:
            continue
        resp = cli.open(_probe_url(pairs[(endpoint, method)]), method=method,
                        environ_overrides={"REMOTE_ADDR": LAN},
                        **PROBE_BODIES.get((endpoint, method), {}))
        body = resp.get_json(silent=True)
        expected = moonglade_gallery.route_tier_message(app.view_functions[endpoint])
        if body != {"error": expected}:
            failures.append("  {} ({}): expected {!r}, got {!r}".format(
                method, endpoint, {"error": expected}, body))

    assert not failures, (
        "{} LOCALHOST refusal(s) did not carry the declared message:\n{}\n\n"
        "FIX: the message comes from the route's own @tier(..., message=...); the\n"
        "front door must emit it verbatim."
        .format(len(failures), "\n".join(failures)))


# ---------------------------------------------------------------------------
# 5. The PUBLIC tier is real, and is not a mute button
# ---------------------------------------------------------------------------

def test_public_routes_are_actually_public(app, armed):
    """Guards the other direction: a PUBLIC declaration exempts a route from
    test 3, so PUBLIC must cost something to claim. Each one has to state the
    status an anonymous caller really gets, and get it right."""
    public_routes = sorted((e, m) for (e, m) in _registered_pairs(app)
                           if _declared_tier(app, e, m) == PUBLIC)
    undeclared = sorted(set(public_routes) - set(PUBLIC_EXPECTED_STATUS))
    assert not undeclared, (
        "route(s) declared @tier(PUBLIC) without an expected anonymous status: {}\n"
        "FIX: add each to PUBLIC_EXPECTED_STATUS in this file. PUBLIC exempts a\n"
        "route from test_no_route_is_reachable_without_a_session, so it must be\n"
        "spelled out here, never inferred from the decorator alone."
        .format(undeclared))

    stale = sorted(set(PUBLIC_EXPECTED_STATUS) - set(public_routes))
    assert not stale, (
        "PUBLIC_EXPECTED_STATUS entr(ies) no longer name a PUBLIC route: {}\n"
        "FIX: delete them. A stale expectation is an assertion that silently\n"
        "stopped running.".format(stale))

    cli = app.test_client()
    pairs = _registered_pairs(app)
    failures = []
    for (endpoint, method), expected in sorted(PUBLIC_EXPECTED_STATUS.items()):
        rule = pairs[(endpoint, method)]
        path = _probe_url(rule)
        resp = cli.open(path, method=method, environ_overrides={"REMOTE_ADDR": LAN})
        if resp.status_code not in expected:
            failures.append("  {} {} ({}): expected status in {}, got {}".format(
                method, path, endpoint, sorted(expected), _describe_refusal(resp)))

    assert not failures, (
        "{} PUBLIC route(s) did not answer anonymously as declared:\n{}\n\n"
        "FIX: if the route became gated, that may be correct -- change its\n"
        "declaration away from @tier(PUBLIC) rather than loosening the\n"
        "expectation here."
        .format(len(failures), "\n".join(failures)))


# ---------------------------------------------------------------------------
# 6. Routes whose localhost requirement is NOT a tier
# ---------------------------------------------------------------------------
# Two shapes here are deliberately NOT expressible as a tier, and both are
# LOGIN-tier routes that narrow themselves further inside the handler:
#   * a LOGIN route may withhold part of its BODY from a LAN caller
#     (/api/panel/status);
#   * a LOGIN route may refuse one ARGUMENT to a LAN caller (/api/panel/run's
#     destructive actions; /api/users/remove and /api/users/password for an
#     account that is not the caller's own -- those two are covered by
#     tests/test_panel_users.py).
# Forcing any of them to @tier(LOCALHOST) would refuse the LAN caller the
# perfectly legitimate rest of the route, which is the "LAN = read-only" framing
# docs/DECISIONS.md explicitly rejects.

_PANEL_REDACTION = "(job output is shown only on the server's own screen)"


def test_panel_status_withholds_job_stdout_from_lan(app):
    """`/api/panel/status` stays LOGIN-tier but must not hand its `lines` to a LAN caller.

    `lines` is the maintenance subprocess's OWN stdout -- absolute paths out of the
    owner's install, catalog internals, whatever a CLI traceback prints. Starting a
    destructive job required loopback and cancelling one required loopback, but READING
    the output was a bare `@app.route` with no check at all until 2026-07-21. Moonglade
    is explicitly not single-user, so a logged-in account on the network could poll the
    owner's job stdout.

    This asserts the LAN caller gets the redaction marker instead of the real buffer.
    """
    cli = _login(app)
    resp = cli.get("/api/panel/status", environ_overrides={"REMOTE_ADDR": LAN})
    assert resp.status_code == 200, (
        "a LAN account is still entitled to job STATE -- see the companion test below; "
        "got {}".format(resp.status_code))
    assert resp.get_json()["lines"] == [_PANEL_REDACTION], (
        "LAN caller received the real `lines` buffer instead of the redaction marker.\n"
        "FIX: keep the loopback check in api_panel_status -- do NOT widen `lines` back\n"
        "to every logged-in caller.")


def test_panel_status_is_not_blanket_localhost_gated(app):
    """The companion to the test above, and the reason this one exists at all.

    The obvious-looking fix for the leak is `if not _is_local_request(): return 403` on
    the whole route. That is WRONG here: 14 of the 20 PANEL_ACTIONS are non-destructive
    and a LAN account may run every one of them (api_panel_run only demands loopback when
    `spec["destructive"]`). Whole-route gating would let that account start a job and then
    watch a progress UI that never moves, in all three pollers.

    So this pins the other side: job STATE must keep reaching a LAN caller. Without this
    test, a future 'tighten the panel routes' sweep silently breaks LAN progress and every
    remaining test still passes.
    """
    cli = _login(app)
    body = cli.get("/api/panel/status",
                   environ_overrides={"REMOTE_ADDR": LAN}).get_json()
    for field in ("status", "action", "label", "rc", "progress"):
        assert field in body, (
            "`{}` vanished from the LAN payload -- the route was probably blanket "
            "localhost-gated instead of having only its one leaky field fixed.".format(field))


# /api/panel/run's destructive-action refusal from an AUTHENTICATED LAN session is
# proven in tests/test_panel.py::test_destructive_action_refuses_authenticated_lan_session,
# which also proves the same account succeeds from loopback and that nothing was
# spawned in the refused case -- more than the generic sweep in this file could say.
# It is named here because while the tiers lived in this file, api_panel_run was
# declared LOCALHOST and PROBE_BODIES fed the generic sweep a destructive action, so
# that refusal was ALSO proven here as a side effect. The declaration was never quite
# true -- a blanket LOCALHOST gate would refuse the 14 non-destructive PANEL_ACTIONS a
# LAN account is entitled to run -- so the route now declares the floor the gate can
# actually enforce, @tier(LOGIN), and keeps its own `spec["destructive"] and not
# _is_local_request()` check. Nothing was lost in that correction; this comment exists
# so the next reader can confirm it rather than assume it.
