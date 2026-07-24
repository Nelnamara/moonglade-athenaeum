"""url_map-driven CATCH-ALL auth-tier coverage: it must be structurally impossible
for a route to escape its auth tier unnoticed.

WHY THIS FILE EXISTS
--------------------
tests/test_web_auth.py hand-maintains four lists of paths
(_PREVIOUSLY_UNGATED_JSON_GET / _JSON_POST / _HTML_GET / _HTML_POST). A
hand-maintained list is precisely what the front-door refactor
(pixai_gallery.py's _enforce_front_door()) was undertaken to eliminate, and those
lists had ALREADY drifted: five credit-spending routes -- /api/generate,
/api/edit, /api/enhance, /api/fix, /api/loom/generate -- appear in none of them.
They are gated today, but nothing in the suite said so, and nothing would have
noticed if they stopped being.

This file does not enumerate paths. It enumerates `app.url_map` -- the single
source of truth for what is actually routable -- and asserts that EVERY
registered (endpoint, method) pair both DECLARES a tier below and has that tier
ENFORCED against a live request. Add a route and forget to declare it: the first
test in this file fails and names your route.

WHY (endpoint, method) AND NOT THE RULE STRING
----------------------------------------------
Two real shapes in this app defeat a dict keyed on the rule string:
  * /api/jobs is ONE rule string mapping to TWO endpoints (GET api_jobs, POST
    api_jobs_register). Keyed on "/api/jobs", one of them silently vanishes.
  * /api/panel/schedule is ONE endpoint whose tier DIFFERS BY METHOD (GET is
    login-only so a LAN Panel can render its settings; POST is localhost-only).
    Keyed on the endpoint alone, the two tiers collapse into one and the weaker
    one wins.
(endpoint, method) is the smallest key that separates both.

WHAT THIS FILE DELIBERATELY DOES NOT DO
---------------------------------------
It never asserts that an authorized request SUCCEEDS. Proving a route is
reachable means executing its handler, and these handlers spend the owner's
credits, delete from their real PixAI account, and move files on disk. This file
proves REFUSAL only -- that is the security-relevant direction, and it is the one
that can be proven without side effects. Per-route success paths belong in the
per-feature test files that already own them.
"""
import re

import pytest

import pixai_gallery
import pixai_gallery_backup as core
from pixai_gallery import create_app


LAN = "203.0.113.5"      # TEST-NET-3 -- the "some other device on the LAN" stand-in
                         # used throughout tests/test_web_auth.py.

# ---------------------------------------------------------------------------
# The tiers
# ---------------------------------------------------------------------------
PUBLIC = "PUBLIC"        # reachable with no session at all (the login surface itself)
LOGIN = "LOGIN"          # any logged-in session, local or LAN
LOCALHOST = "LOCALHOST"  # a logged-in session AND a loopback remote_addr

# The two refusal shapes the front door emits (see _enforce_front_door()). Routes
# whose historical contract is JSON get a parseable 401; everything else gets a
# redirect to the login page.
_JSON_GATE_PREFIXES = ("/api/", "/rate/", "/edit-prompt/")
_AUTH_REQUIRED_BODY = {"error": "authentication required"}
_REDIRECT_CODES = (301, 302, 303, 307, 308)


# ---------------------------------------------------------------------------
# THE DECLARATION TABLE -- keyed (endpoint, method)
# ---------------------------------------------------------------------------
# Adding a route to pixai_gallery.py? Add it here too, or
# test_every_registered_route_declares_a_tier fails and names it. Pick the tier
# by what the handler can DO, not by what feels convenient:
#   LOGIN     -- browse the library, spend the owner's credits, manage your OWN
#                account. Managing OTHER accounts (adding one, removing one that
#                isn't yours) is LOCALHOST -- see api_users_add/_remove.
#   LOCALHOST -- irreversible cloud deletion, writes to config.json (which holds
#                PIXAI_API_KEY / AUTH_SECRET_KEY / AUTH_USERS), file-moving
#                maintenance, or shelling out on the SERVER machine. A logged-in
#                LAN session must NOT reach these; the handler needs its own
#                `if not _is_local_request(): return ..., 403` on top of the
#                front door, because the front door alone will let it through.
#   PUBLIC    -- the login surface and the static art it renders. Nothing else.
#                Marking a route PUBLIC also requires declaring its expected
#                anonymous status in PUBLIC_EXPECTED_STATUS below; that friction
#                is intentional, so PUBLIC cannot be used as a quiet way to mute
#                this file.
ROUTE_TIERS = {
    # -- the login surface: the only genuinely public tier -------------------
    ("login", "GET"): PUBLIC,
    ("login", "POST"): PUBLIC,
    ("logout", "GET"): PUBLIC,        # local sign-out only -- writes no server state
    ("logout", "POST"): PUBLIC,       # + the global revoke, gated on the session csrf
    ("branding", "GET"): PUBLIC,

    # -- LOCALHOST-ONLY: a logged-in LAN session is NOT enough ---------------
    # Every one of these had its localhost check silently dropped or never
    # written at some point (see each handler's docstring); three of them were
    # only caught by a 2026-07-19 route-gating audit.
    ("api_branding_shortcut", "POST"): LOCALHOST,   # shells out to host PowerShell/COM
    ("api_panel_cancel", "POST"): LOCALHOST,        # terminates a file-moving job mid-run
    ("api_panel_run", "POST"): LOCALHOST,           # destructive actions only -- see PROBE_BODIES
    ("api_panel_schedule", "POST"): LOCALHOST,      # writes the schedule + global workers count
    ("api_setup_save_key", "POST"): LOCALHOST,      # rewrites config.json
    ("delete_tasks_bulk", "POST"): LOCALHOST,       # irreversible cloud deletion
    ("api_import_local", "POST"): LOCALHOST,         # writes files into the backup + shells thumbnails
    ("api_users_add", "POST"): LOCALHOST,           # mints a new persistent login (2026-07-22)
    ("api_trash_delete_forever", "POST"): LOCALHOST,  # irreversible local file deletion (2026-07-24)
    ("api_trash_empty", "POST"): LOCALHOST,           # irreversible local file deletion (2026-07-24)

    # -- LOGIN: any authorized session ---------------------------------------
    ("index", "GET"): LOGIN,
    ("detail", "GET"): LOGIN,
    ("health", "GET"): LOGIN,
    ("panel", "GET"): LOGIN,
    ("duplicates", "GET"): LOGIN,
    ("loom", "GET"): LOGIN,
    ("contact_sheet", "GET"): LOGIN,
    # The manifest body is a compile-time constant (no user data, no install paths), and
    # the browser fetches it unprompted from the public login page -- gating it only bought
    # a self-inflicted redirect. /sw.js is the same CLASS of asset but is NOT bundled in
    # with it: serving the worker script is a separate question from what the worker
    # caches, and the cache-survives-sign-out concern has to be settled on its own.
    ("manifest", "GET"): PUBLIC,
    ("service_worker", "GET"): LOGIN,
    # Flask's own static endpoint is NOT special-cased away here on purpose.
    # `if rule.endpoint == "static": continue` is the single most common way a
    # catch-all route test grows a hole; /static/ is gated by the front door
    # like everything else, so it is declared like everything else.
    ("static", "GET"): LOGIN,

    # raw asset / media routes
    ("thumb", "GET"): LOGIN,
    ("serve_image", "GET"): LOGIN,
    ("full_image", "GET"): LOGIN,
    ("video_file", "GET"): LOGIN,
    ("badge_thumb", "GET"): LOGIN,
    ("loom_dist", "GET"): LOGIN,
    ("loom_vendor", "GET"): LOGIN,

    # library mutation (local only in effect, but LAN-authorized by design)
    ("rate", "POST"): LOGIN,
    ("edit_prompt", "POST"): LOGIN,
    ("delete_one", "POST"): LOGIN,
    ("delete_bulk", "POST"): LOGIN,
    ("bulk_replace", "POST"): LOGIN,
    ("collection_add", "POST"): LOGIN,
    ("collection_remove", "POST"): LOGIN,
    ("export_zip", "POST"): LOGIN,
    ("export_csv_download", "GET"): LOGIN,

    # trash / quarantine panel (2026-07-24) -- restore is LOGIN (recovering
    # something is not the same trust question as destroying it forever); see
    # api_trash_delete_forever/api_trash_empty above in the LOCALHOST section.
    ("api_trash_list", "GET"): LOGIN,
    ("api_trash_restore", "POST"): LOGIN,

    # credit-spending generation surface -- the five routes the hand-maintained
    # lists in test_web_auth.py never covered.
    ("api_generate", "POST"): LOGIN,
    ("api_edit", "POST"): LOGIN,
    ("api_enhance", "POST"): LOGIN,
    ("api_fix", "POST"): LOGIN,
    ("loom_generate", "POST"): LOGIN,
    ("api_upload", "POST"): LOGIN,
    ("api_price", "POST"): LOGIN,
    ("api_claim", "POST"): LOGIN,
    ("api_import_task", "POST"): LOGIN,

    # read-only API surface
    ("api_account", "GET"): LOGIN,
    ("api_achievements", "GET"): LOGIN,
    ("api_artwork_views", "GET"): LOGIN,
    ("api_collections", "GET"): LOGIN,
    ("api_contests", "GET"): LOGIN,
    ("api_gallery_images", "GET"): LOGIN,
    ("api_model_search", "GET"): LOGIN,
    ("api_model_version", "GET"): LOGIN,
    ("api_ping", "GET"): LOGIN,
    ("api_similar", "GET"): LOGIN,
    ("api_suggest_prompt", "GET"): LOGIN,
    ("api_tag_suggest", "GET"): LOGIN,
    ("api_task_status", "GET"): LOGIN,
    ("api_watch_status", "GET"): LOGIN,
    ("api_workflows", "GET"): LOGIN,
    ("api_your_art", "GET"): LOGIN,

    # jobs -- ONE rule string, TWO endpoints (the case a rule-keyed dict drops)
    ("api_jobs", "GET"): LOGIN,
    ("api_jobs_register", "POST"): LOGIN,
    ("api_jobs_dismiss", "POST"): LOGIN,

    # Loom
    ("loom_get", "GET"): LOGIN,
    ("loom_list", "GET"): LOGIN,
    ("loom_set", "POST"): LOGIN,
    ("loom_delete", "POST"): LOGIN,
    ("loom_handoff", "POST"): LOGIN,
    ("loom_video_duration", "GET"): LOGIN,
    ("api_loom_export", "POST"): LOGIN,
    ("api_loom_export_bundle", "POST"): LOGIN,
    ("api_loom_export_cancel", "POST"): LOGIN,
    ("api_loom_export_file", "GET"): LOGIN,
    ("api_loom_export_status", "GET"): LOGIN,
    ("api_loom_import_bundle", "POST"): LOGIN,

    # panel / settings / accounts
    ("api_panel_status", "GET"): LOGIN,
    ("api_panel_schedule", "GET"): LOGIN,   # GET login-only, POST localhost -- see above
    ("api_presets", "GET"): LOGIN,
    ("api_presets", "POST"): LOGIN,
    ("api_view_presets", "GET"): LOGIN,    # saved views roam desktop<->tablet: that IS the login tier
    ("api_view_presets", "POST"): LOGIN,   # small cosmetic json in out_dir, same trust as api_skin
    ("api_snippets", "GET"): LOGIN,
    ("api_snippets", "POST"): LOGIN,
    ("api_branding", "GET"): LOGIN,
    ("api_branding", "POST"): LOGIN,
    ("api_skin", "POST"): LOGIN,
    ("api_ach_event", "POST"): LOGIN,
    # api_users_remove is LOGIN, not LOCALHOST, because it is genuinely reachable
    # for a LAN session -- but ONLY to remove its OWN account; removing anyone
    # else is refused with the same 403 a LOCALHOST route would give, enforced
    # inside the handler on the submitted username vs session["user"], not by
    # tier. The two generic tier tests below can't express "reachable, but only
    # for this one argument value" -- see tests/test_panel_users.py for the
    # LAN-self-succeeds / LAN-other-refused pair that actually covers it.
    ("api_users_remove", "POST"): LOGIN,

    # RESOLVED (owner decision 2026-07-19, see CHANGELOG): api_server_stop /
    # api_server_restart stay in the broader "any logged-in LAN session" tier
    # on purpose, not LOCALHOST. Their docstrings were updated to say "Login
    # required" to match, closing the docstring-says-localhost /
    # code-says-nothing gap the route-gating audit had flagged. LOGIN here is
    # the intended, current design, not a stand-in for an unresolved decision.
    ("api_server_stop", "POST"): LOGIN,
    ("api_server_restart", "POST"): LOGIN,
}

# Marking something PUBLIC costs you a second, explicit statement of what an
# anonymous caller actually gets. /logout is why this is not just "assert not
# redirected to /login": an anonymous GET /logout is a harmless no-op that
# redirects to /login all by itself, which is indistinguishable from the front
# door intercepting it unless the expectation is spelled out per route.
PUBLIC_EXPECTED_STATUS = {
    ("login", "GET"): {200},
    ("login", "POST"): {200},      # re-renders the form (no csrf) -- never a redirect
    # a 200 page now, not a redirect -- it has to run script client-side to purge
    # Cache Storage before navigating on to /login, which a 3xx can't do (see
    # test_session_revocation.py's test_logout_purges_cache_storage_client_side)
    ("logout", "GET"): {200},
    ("logout", "POST"): {200},     # anonymous: nothing to revoke, so no csrf is demanded
    ("branding", "GET"): {404},    # missing art 404s; it must never redirect to /login
    ("manifest", "GET"): {200},    # a constant body -- anonymous callers get the real thing
}

# A few routes only reach their localhost gate with a meaningful payload.
# api_panel_run's check is `if spec["destructive"] and not _is_local_request()`,
# so an empty body stops at "unknown action" (400) and proves nothing.
PROBE_BODIES = {
    ("api_panel_run", "POST"): {"json": {"action": "organize", "confirm": True}},
}

# Not every localhost refusal is a 403. delete_tasks_bulk is a form POST that
# refuses by redirecting back to the gallery with ?delerr=..., because a 403 JSON
# blob would be a dead end in the browser flow it belongs to. Declared, not
# guessed -- and asserted just as strictly.
LOCALHOST_REFUSAL_IS_REDIRECT = {
    ("delete_tasks_bulk", "POST"): "localhost-only",   # substring required in Location
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

    monkeypatch.setattr(pixai_gallery, "_schedule_server_exit", blocked("process exit"))
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
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    assert m, "login page did not render a csrf hidden field"
    r = cli.post("/login", data={"username": username, "password": password,
                                 "csrf": m.group(1)})
    assert r.status_code in _REDIRECT_CODES, "probe login failed to authenticate"
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
    registered = set(_registered_pairs(app))
    declared = set(ROUTE_TIERS)

    undeclared = sorted(registered - declared)
    stale = sorted(declared - registered)

    problems = []
    if undeclared:
        problems.append(
            "{} route(s) are registered in app.url_map but declare NO auth tier:\n"
            "{}\n"
            "\n"
            "FIX: add each one to ROUTE_TIERS in tests/test_route_tiers.py, as\n"
            "    (\"<endpoint>\", \"<METHOD>\"): LOGIN,\n"
            "choosing the tier by what the handler can DO:\n"
            "  LOGIN     - browse the library, spend the owner's credits, manage accounts.\n"
            "  LOCALHOST - irreversible cloud deletion, config.json writes, file-moving\n"
            "              maintenance, or shelling out on the server machine. This tier\n"
            "              is NOT free: the front door does not enforce it, so the handler\n"
            "              itself must start with\n"
            "                  if not _is_local_request():\n"
            "                      return jsonify({{\"error\": \"localhost-only\"}}), 403\n"
            "  PUBLIC    - the login surface only; also requires an entry in\n"
            "              PUBLIC_EXPECTED_STATUS.\n"
            "This failure is not bureaucracy: five credit-spending routes\n"
            "(/api/generate, /api/edit, /api/enhance, /api/fix, /api/loom/generate)\n"
            "were missing from the hand-maintained lists in tests/test_web_auth.py\n"
            "for exactly this reason, and nothing noticed."
            .format(len(undeclared),
                    "\n".join("    (\"{}\", \"{}\")".format(e, m) for e, m in undeclared)))
    if stale:
        problems.append(
            "{} declaration(s) in ROUTE_TIERS no longer match any registered route:\n"
            "{}\n"
            "FIX: delete them. A stale declaration is a tier assertion that silently\n"
            "stopped running -- the same rot this file exists to prevent."
            .format(len(stale),
                    "\n".join("    (\"{}\", \"{}\")".format(e, m) for e, m in stale)))

    assert not problems, "\n\n".join(problems)


# ---------------------------------------------------------------------------
# 2. Enforcement, anonymous: everything non-PUBLIC refuses a session-less caller
# ---------------------------------------------------------------------------

def test_no_route_is_reachable_without_a_session(app, armed):
    """Every LOGIN and LOCALHOST route, probed with no cookie at all, from a LAN
    address and again from loopback -- localhost is not a trusted tier, so both
    must refuse identically."""
    cli = app.test_client()
    failures = []
    for (endpoint, method), rule in sorted(_registered_pairs(app).items()):
        if ROUTE_TIERS.get((endpoint, method)) == PUBLIC:
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
        "pixai_gallery.py -- if one of these got through, either it was added to\n"
        "_PUBLIC_PATHS/_PUBLIC_PREFIXES (revert that unless it is genuinely part\n"
        "of the login surface) or the hook itself regressed, which would be a\n"
        "whole-app authentication bypass and should be treated as such."
        .format(len(failures), "\n".join(failures)))


# ---------------------------------------------------------------------------
# 3. Enforcement, LOCALHOST: being logged in is NOT enough
# ---------------------------------------------------------------------------

def test_localhost_only_routes_refuse_an_authenticated_lan_session(app, armed):
    """THE assertion whose absence let three real regressions ship.

    The front door only ever asks "is this a valid session?", so it passes a
    logged-in LAN device straight through to these handlers. The localhost check
    lives in the handler body and nothing structural keeps it there: it was
    silently deleted from api_panel_cancel and api_panel_schedule (commit
    0fd8cee), and never written at all in api_setup_save_key, while all three
    docstrings went on claiming "localhost-only". Anonymous probing cannot catch
    that class of bug -- the front door refuses those requests for unrelated
    reasons and the missing check is never reached. Only an AUTHENTICATED,
    NON-LOCAL probe reaches it.
    """
    cli = _login(app)
    declared = [(k, v) for k, v in sorted(ROUTE_TIERS.items()) if v == LOCALHOST]
    assert declared, "no LOCALHOST routes declared -- did the tier table get gutted?"

    pairs = _registered_pairs(app)
    failures = []
    for (endpoint, method), _ in declared:
        rule = pairs[(endpoint, method)]     # completeness test guarantees presence
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
        "FIX: the front door cannot enforce this tier -- it only checks that a\n"
        "session is valid, and this session IS valid. The handler itself must\n"
        "carry the check, as its FIRST action:\n"
        "    if not _is_local_request():\n"
        "        return jsonify({{\"error\": \"localhost-only\"}}), 403\n"
        "If the route is genuinely fine for a logged-in LAN device, move it to\n"
        "LOGIN in ROUTE_TIERS and say why in its docstring -- do not leave the\n"
        "declaration and the code disagreeing, which is the exact state\n"
        "api_panel_cancel / api_panel_schedule / api_setup_save_key were found in."
        .format(len(failures), LAN, "\n".join(failures)))


# ---------------------------------------------------------------------------
# 4. The PUBLIC tier is real, and is not a mute button
# ---------------------------------------------------------------------------

def test_public_routes_are_actually_public(app, armed):
    """Guards the other direction: a PUBLIC declaration exempts a route from
    test 2, so PUBLIC must cost something to claim. Each one has to state the
    status an anonymous caller really gets, and get it right."""
    undeclared = sorted(set(k for k, v in ROUTE_TIERS.items() if v == PUBLIC)
                        - set(PUBLIC_EXPECTED_STATUS))
    assert not undeclared, (
        "route(s) declared PUBLIC without an expected anonymous status: {}\n"
        "FIX: add each to PUBLIC_EXPECTED_STATUS. PUBLIC exempts a route from\n"
        "test_no_route_is_reachable_without_a_session, so it must be spelled out,\n"
        "never inferred.".format(undeclared))

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
        "FIX: if the route became gated, that may be correct -- move it out of\n"
        "PUBLIC in ROUTE_TIERS rather than loosening the expectation here."
        .format(len(failures), "\n".join(failures)))


# ---------------------------------------------------------------------------
# 5. The tiers themselves stay meaningful
# ---------------------------------------------------------------------------

def test_declared_tiers_are_known_values():
    bad = {k: v for k, v in ROUTE_TIERS.items() if v not in (PUBLIC, LOGIN, LOCALHOST)}
    assert not bad, (
        "unknown tier value(s) in ROUTE_TIERS: {}\n"
        "Only PUBLIC / LOGIN / LOCALHOST exist. Inventing a fourth tier in the\n"
        "table without teaching this file to enforce it produces a declaration\n"
        "that asserts nothing.".format(bad))


# ---------------------------------------------------------------------------
# 6. Field-level disclosure: a LOGIN route may still withhold part of its body
# ---------------------------------------------------------------------------

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


def test_panel_withholds_the_server_install_path_from_lan(app, tmp_path):
    """`/panel` stays LOGIN-tier -- same reasoning as api_panel_status above -- but must
    not hand a LAN caller the absolute host filesystem path (`out_dir`, e.g.
    'D:\\\\Moonglade Athenaeum\\\\pixai_backup'). It renders as plain HTML ("library at
    <code>{{ out_dir }}</code>"), unconditionally, to every LOGIN caller regardless of
    _is_local_request() -- found by the 2026-07-21 audit as S2, the same shape as the
    api_panel_status leak: a route whose TIER is correct but whose BODY mixes in host
    detail that tier does not justify.

    Deliberately narrower than that fix, though: usernames on this same page (S2's other
    half) are NOT touched here. Reading the roster stays LOGIN-tier on purpose, even
    though WRITING to it no longer is (api_users_add/_remove were tightened 2026-07-22 --
    see their own docstrings): seeing a fellow account's username is a different, much
    smaller question than adding or removing one, and it is not the kind of fact this
    route needs to hide. A host filesystem path is a different kind of fact entirely: it
    identifies the SERVER's machine, not a peer account.
    """
    cli = _login(app)
    resp = cli.get("/panel", environ_overrides={"REMOTE_ADDR": LAN})
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert str(tmp_path) not in html, (
        "the real out_dir path reached a LAN caller's rendered /panel page")
    assert "local to the server" in html


def test_panel_shows_the_real_path_to_localhost(app, tmp_path):
    """The companion to the test above: the owner sitting at the server must still see
    the real path -- it's useful, it's their own machine, and there is nothing to
    withhold from loopback. Without this test, a future 'just always redact it' change
    would pass the LAN test above while quietly breaking the one caller who actually
    needs this information."""
    cli = _login(app)
    html = cli.get("/panel").get_data(as_text=True)   # loopback REMOTE_ADDR by default
    assert str(tmp_path) in html, (
        "the owner's own /panel no longer shows the real library path")


# ---------------------------------------------------------------------------
# 7. Control-level disclosure: three owner-only CONTROLS must not just error, they
# must not even RENDER for a LOGIN-tier LAN session (docs/AUDIT_2026-07-21.md P3 and
# the reachability-lens finding under section 5 -- "which LOCALHOST-gated controls are
# rendered to every LOGIN session?"). Before this fix, all three rendered normally for
# any authorized session and only 403'd server-side after a browser confirm dialog --
# never a security hole (every target route already carried its own correct
# `_is_local_request()` check), but a dead-end UX wart. FIXED 2026-07-24: the owner's
# explicit call was to gate visibility on the real check, not just relabel the gap.
# ---------------------------------------------------------------------------

def test_index_withholds_the_import_button_from_a_lan_session(app):
    """The header's "^ Import" button used to render for ANY logged-in session, local
    or LAN, because its visibility only checked the blanket `is_local` flag (hardcoded
    True for every authorized request reaching index() -- see that route's comment).
    Its real target, /api/import-local, is actually LOCALHOST-tier (it writes files
    onto the server's own machine) -- so a LAN session saw a working-looking Import
    button that always 403'd on click. The button is now nested behind `is_true_local`,
    the real _is_local_request() result -- the same value `can_delete_cloud` ("Delete
    from PixAI") already used."""
    cli = _login(app)
    html = cli.get("/", environ_overrides={"REMOTE_ADDR": LAN}).get_data(as_text=True)
    assert 'onclick="ImportUI.open()"' not in html, (
        "a LAN session's rendered index page still contains the Import button, which "
        "posts to the LOCALHOST-only /api/import-local and would 403 on click")
    # Sibling LOGIN-tier owner controls must still render for LAN -- this fixes ONE
    # control's visibility, not a blanket lockout of the whole owner section.
    assert "Gen.open()" in html and 'href="/loom"' in html


def test_index_shows_the_import_button_to_localhost(app):
    """The companion to the test above: the owner sitting at the server must still see
    a working Import button. Without this test, a future 'just always hide it' change
    would pass the LAN test while quietly breaking the one caller who can actually use
    it."""
    cli = _login(app)
    html = cli.get("/").get_data(as_text=True)   # loopback REMOTE_ADDR by default
    assert 'onclick="ImportUI.open()"' in html, (
        "the owner's own index page no longer shows the Import button")


def test_panel_withholds_set_launcher_icon_and_destructive_buttons_from_lan(app):
    """"Set launcher icon" and every destructive Maintenance action (Organize, Dedup,
    Rebuild thumbnails, ...) used to render for any LOGIN-tier session -- their real
    targets (/api/branding/shortcut, and /api/panel/run's `spec["destructive"]` branch)
    are correctly LOCALHOST-gated server-side, but nothing hid the buttons themselves,
    so a LAN session saw working-looking controls that 403'd after a browser confirm
    dialog. Both now key off `panel_is_local`, the same flag the Users tab's Add/Remove
    UI already used (2026-07-22)."""
    cli = _login(app)
    html = cli.get("/panel", environ_overrides={"REMOTE_ADDR": LAN}).get_data(as_text=True)
    assert 'onclick="setLauncher()"' not in html, (
        "a LAN session's rendered /panel still contains the Set launcher icon button, "
        "which posts to the LOCALHOST-only /api/branding/shortcut and would 403")
    actions_json = html.split("var ACTIONS = ", 1)[1].split(";", 1)[0]
    for destructive in ("organize", "undo-organize", "dedup-apply", "dedup-delete",
                       "restore-orphans", "rebuild-thumbs"):
        assert '"action": "{}"'.format(destructive) not in actions_json, (
            "a LAN session's Maintenance ACTIONS payload still includes the "
            "destructive action {!r}, which posts to the LOCALHOST-only "
            "/api/panel/run and would 403 after a confirm dialog".format(destructive))
    # Safe actions are UNCHANGED: this fix is scoped to destructive-button visibility,
    # not a blanket Maintenance-tab lockout -- a LAN account may still run any of them
    # (see test_panel_status_is_not_blanket_localhost_gated above for the sibling
    # principle on the polling side).
    assert '"action": "sync"' in actions_json
    # The scheduler dropdown's own source (ALL_ACTIONS) is deliberately untouched by
    # this fix: loadSchedule() already excludes every destructive action from the
    # dropdown for everyone, local or LAN, so there was never anything to hide there.
    all_actions_json = html.split("var ALL_ACTIONS = ", 1)[1].split(";", 1)[0]
    assert '"action": "organize"' in all_actions_json


def test_panel_shows_set_launcher_icon_and_destructive_buttons_to_localhost(app):
    """The companion to the test above: the owner sitting at the server must still see
    a working Set-launcher-icon button and every destructive Maintenance action.
    Without this test, a future 'just always hide it' change would pass the LAN test
    above while quietly breaking the one caller who can actually use these."""
    cli = _login(app)
    html = cli.get("/panel").get_data(as_text=True)   # loopback REMOTE_ADDR by default
    assert 'onclick="setLauncher()"' in html, (
        "the owner's own /panel no longer shows the Set launcher icon button")
    actions_json = html.split("var ACTIONS = ", 1)[1].split(";", 1)[0]
    for destructive in ("organize", "undo-organize", "dedup-apply", "dedup-delete",
                       "restore-orphans", "rebuild-thumbs"):
        assert '"action": "{}"'.format(destructive) in actions_json, (
            "the owner's own Maintenance ACTIONS payload is missing the destructive "
            "action {!r}".format(destructive))
