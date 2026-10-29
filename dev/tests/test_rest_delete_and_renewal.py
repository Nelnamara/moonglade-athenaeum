"""The whole-generation delete and the Mirror's session renewal ride PixAI's REST routes (#92).

The app still sent three saved (hash-only) requests that PixAI's site no longer sends: the
whole-generation delete, the Mirror's session renewal and the Bookmarked tab's fallback.
PixAI's servers were still answering them from a cache, and two other saved requests began to
be refused this month (#88, #89). The delete now goes where pixai.art's own task menu sends
it, `POST /v2/task/{id}/delete` on the API key (`delete_task`); the renewal goes where the
site renews itself, `POST /v2/auth/refresh-token` with no body on the Mirror's own JWT
(`refresh_jwt`); the bookmarks fallback is gone, and with it the whole saved-request road
(`PixAIClient.persisted`).

What is pinned:

  * the delete fires ONCE or not at all: exactly one POST through `rest_post`, body `{}`, to
    the task's own path; only exactly `{"success": true}` counts as deleted -- every other
    2xx, a 2xx that is not JSON, any non-2xx and a network error is a PixAIError that says
    the task was not deleted; an id that could leave its path segment sends nothing;
    READ_ONLY refuses before the id check and before anything is sent; both gallery roads
    hand it the API-key client (`_make_session(None)`), and a refusal keeps the local copy;
  * the renewal rides ONLY the stored JWT: one body-less POST to the REST route, the JWT as a
    per-call Bearer that wins over any session default, never the API key (refused before
    anything is sent), nothing at all without a live JWT; the body token first and the
    `token` header as the fallback, each a fresh `iss=pixai` JWT; a fresh token for another
    account (`sub`) is discarded; the session's cookie jar is empty afterwards; the road is
    recorded ("jwt") and `--mirror-check` says it; an expired stored JWT is still left for
    Connect;
  * no token or cookie value reaches a log record, stdout/stderr, `_refresh_last`,
    `_mirror_renewal` or a returned dict, on success or failure;
  * the bookmarks read is ad-hoc only: a refusal propagates, and no second road is tried;
  * the retired names are gone from the module, the client, the fake and config.example.json.

NO REAL PIXAI: a FakePixAI answers the verbs, and the wire tests drive the real client or a
real requests.Session against a recording stand-in (a transport adapter that never opens a
socket). The JWTs are synthetic (unsigned, made here), and the API key is a placeholder
written into this test's own isolated config.json.
"""
import base64
import inspect
import json
import logging
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from moonglade import backup as core
from moonglade.gallery import CATALOG_FIELDS, save_catalog

from tests.conftest import login_client
from tests.fake_pixai import FakePixAI

REPO = Path(__file__).resolve().parents[2]
TID = "2065852033099888102"
DELETE_PATH = "/task/{}/delete".format(TID)
RENEW_URL = core.REST_API_BASE + "/auth/refresh-token"
APIKEY = "test-api-key-not-a-credential-0123456789"
DAY = 86400


def _b64(d):
    return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")


def _jwt(days, sub="S-main", iss="pixai", salt=""):
    """A structurally-real, unsigned JWT expiring `days` from the real clock."""
    claims = {"exp": int(time.time() + days * DAY), "sub": sub, "iss": iss}
    if salt:
        claims["n"] = salt
    return _b64({"alg": "HS256", "typ": "JWT"}) + "." + _b64(claims) + ".sig"


# ---------------------------------------------------------------------------
# Recording stand-ins: nothing here opens a socket
# ---------------------------------------------------------------------------

class _Resp:
    """The parts of a requests.Response the two roads read."""

    def __init__(self, status=200, body=None, text=None, headers=None, json_exc=None):
        self.status_code = status
        self._body = body
        self._json_exc = json_exc
        self.text = text if text is not None else (json.dumps(body) if body is not None else "")
        self.headers = dict(headers or {})
        self.content = self.text.encode()

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        if self._body is None:
            raise ValueError("no json")
        return self._body


class _Recorder:
    """A requests.Session stand-in that records every call's kwargs and answers in order."""

    def __init__(self, *answers):
        self.answers = list(answers) or [_Resp(body={})]
        self.calls = []
        self.headers = {}
        self.cookies = requests.cookies.RequestsCookieJar()

    def _answer(self, verb, url, kwargs):
        self.calls.append((verb, url, kwargs))
        a = self.answers[min(len(self.calls) - 1, len(self.answers) - 1)]
        if isinstance(a, BaseException):
            raise a
        return a

    def post(self, url, **kwargs):
        return self._answer("POST", url, kwargs)

    def get(self, url, **kwargs):
        return self._answer("GET", url, kwargs)


class _Wire(requests.adapters.BaseAdapter):
    """A transport adapter mounted on a REAL requests.Session: it records the PreparedRequest
    the session would have put on the wire (headers merged exactly as requests merges them)
    and answers without a socket. `set_cookie` plays PixAI writing a cookie back."""

    def __init__(self, session, status=200, body=None, headers=None, exc=None,
                 set_cookie=None):
        super().__init__()
        self.session, self.sent = session, []
        self.status, self.body, self.headers, self.exc = status, body, headers or {}, exc
        self.set_cookie = set_cookie

    def send(self, request, **kwargs):
        self.sent.append(request)
        if self.exc is not None:
            raise self.exc
        if self.set_cookie:
            self.session.cookies.set(*self.set_cookie, domain="api.pixai.art")
        r = requests.Response()
        r.status_code = self.status
        r._content = (json.dumps(self.body).encode() if not isinstance(self.body, bytes)
                      else self.body) if self.body is not None else b""
        r.headers.update(self.headers)
        r.url, r.request, r.encoding = request.url, request, "utf-8"
        return r

    def close(self):
        pass


def _wired(session=None, **kw):
    s = session if session is not None else requests.Session()
    wire = _Wire(s, **kw)
    s.mount("https://", wire)
    return s, wire


@pytest.fixture
def no_read_only(monkeypatch):
    monkeypatch.setattr(core, "READ_ONLY", False)
    monkeypatch.setattr(core, "_read_only_now", lambda: False)


# =====================================================================================
# A. THE WHOLE-GENERATION DELETE
# =====================================================================================

class TestTheDeleteFiresOnce:
    def test_one_rest_post_with_an_empty_body(self, no_read_only):
        fake = FakePixAI().on(DELETE_PATH, {"success": True})
        assert core.delete_task(fake, TID) is True
        assert [(c.verb, c.path, c.body) for c in fake.calls] == [
            ("rest_post", DELETE_PATH, {})]
        assert not [c for c in fake.calls if c.verb in ("query", "mutate")]

    def test_the_wire_is_one_post_to_the_task_route(self, no_read_only):
        s = _Recorder(_Resp(body={"success": True}))
        assert core.delete_task(core.PixAIClient(s), TID) is True
        (verb, url, kwargs), = s.calls
        assert verb == "POST" and url == core.REST_API_BASE + DELETE_PATH
        assert kwargs["json"] == {}

    def test_it_rides_the_api_key_the_session_carries(self, no_read_only):
        """The delete adds no credential of its own: on the wire the Authorization is the one
        the API-key session carries."""
        base = requests.Session()
        base.headers["Authorization"] = "Bearer " + APIKEY
        s, wire = _wired(base, body={"success": True})
        assert core.delete_task(core.PixAIClient(s), TID) is True
        (req,) = wire.sent
        assert req.method == "POST" and req.url == core.REST_API_BASE + DELETE_PATH
        assert req.headers["Authorization"] == "Bearer " + APIKEY
        assert json.loads(req.body) == {}

    @pytest.mark.parametrize("answer", [{}, {"success": False}, [], None, {"success": "true"},
                                        {"success": 1}, {"ok": True}])
    def test_anything_but_exactly_success_true_is_not_a_delete(self, no_read_only, answer):
        fake = FakePixAI().on(DELETE_PATH, answer)
        with pytest.raises(core.PixAIError, match="not deleted"):
            core.delete_task(fake, TID)
        assert len(fake.calls) == 1

    @pytest.mark.parametrize("exc", [ValueError("Expecting value"),
                                     requests.exceptions.JSONDecodeError("Expecting value",
                                                                         "<html>", 0)])
    def test_a_200_that_is_not_json_is_not_a_delete_and_not_a_network_error(
            self, no_read_only, exc):
        """rest_post's r.json() raises a ValueError; requests' own JSONDecodeError is a
        RequestException too, so the order of the except clauses is what decides this."""
        s = _Recorder(_Resp(status=200, text="<html>ok</html>", json_exc=exc))
        with pytest.raises(core.PixAIError) as ei:
            core.delete_task(core.PixAIClient(s), TID)
        assert "not deleted" in str(ei.value) and "network error" not in str(ei.value)
        assert len(s.calls) == 1

    @pytest.mark.parametrize("status, words", [(401, "401"), (403, "403"), (404, "HTTP 404"),
                                               (500, "HTTP 500")])
    def test_a_non_2xx_names_its_status(self, no_read_only, status, words):
        fake = FakePixAI().fail(DELETE_PATH, core.PixAIRestError(
            "REST POST {} -> {}: x".format(DELETE_PATH, status), status=status))
        with pytest.raises(core.PixAIError) as ei:
            core.delete_task(fake, TID)
        assert words in str(ei.value)
        assert len(fake.calls) == 1

    def test_a_500_on_the_wire_is_one_post(self, no_read_only):
        s = _Recorder(_Resp(status=500, text="Internal Server Error"))
        with pytest.raises(core.PixAIError, match="HTTP 500"):
            core.delete_task(core.PixAIClient(s), TID)
        assert len(s.calls) == 1

    def test_a_network_error_is_one_post(self, no_read_only):
        s = _Recorder(requests.ConnectionError("connection dropped"))
        with pytest.raises(core.PixAIError, match="network error deleting task " + TID):
            core.delete_task(core.PixAIClient(s), TID)
        assert len(s.calls) == 1

    @pytest.mark.parametrize("bad", ["", "  ", "1/2", "../x", "1?a=1", "a b", "1#x", "%2e%2e",
                                     "x" * 65, None])
    def test_a_bad_id_sends_nothing(self, no_read_only, bad):
        fake = FakePixAI()
        with pytest.raises(core.PixAIError, match="Nothing was sent"):
            core.delete_task(fake, bad)
        assert fake.calls == []

    def test_read_only_refuses_before_the_id_check_and_before_any_call(self, monkeypatch):
        monkeypatch.setattr(core, "READ_ONLY", True)
        fake = FakePixAI()
        for tid in (TID, "../x"):
            with pytest.raises(core.PixAIError, match="READ_ONLY"):
                core.delete_task(fake, tid)
        assert fake.calls == []

    def test_the_live_read_only_switch_refuses_too(self, monkeypatch):
        monkeypatch.setattr(core, "READ_ONLY", False)
        monkeypatch.setattr(core, "_read_only_now", lambda: True)
        fake = FakePixAI()
        with pytest.raises(core.PixAIError, match="READ_ONLY"):
            core.delete_task(fake, TID)
        assert fake.calls == []


# ---- both gallery roads hand it the API-key client, and a refusal keeps the local copy ----

def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _wait_for_delete_job(cli, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        jobs = [j for j in cli.get("/api/jobs").get_json()["jobs"] if j.get("type") == "delete"]
        if jobs and jobs[0]["status"] in ("done", "failed"):
            return jobs[0]
        time.sleep(0.05)
    return None


def _one_task_library(tmp_path):
    save_catalog(tmp_path / "catalog.db", [_row(media_id="m1", task_id="T1", filename="m1.png")])
    (tmp_path / "images").mkdir(exist_ok=True)
    (tmp_path / "images" / "m1.png").write_bytes(b"x")


def _catalog_ids(tmp_path):
    with sqlite3.connect(str(tmp_path / "catalog.db")) as con:
        return sorted(r[0] for r in con.execute("SELECT media_id FROM catalog"))


class TestTheGalleryRoads:
    def test_the_bulk_delete_sends_one_post_on_the_api_key_client(self, tmp_path, pixai,
                                                                  monkeypatch):
        """`pixai` IS what `_make_session(None)` hands back here, so a call recorded on it
        is a call on the API-key client -- and the mirror is never asked for."""
        monkeypatch.setattr(core, "make_mirror_session", lambda *a, **k: pytest.fail(
            "the delete reached for the mirror session"))
        _one_task_library(tmp_path)
        pixai.on("/task/T1/delete", {"success": True})
        cli = login_client(tmp_path)
        d = cli.post("/api/delete-tasks", json={"task_ids": ["T1"],
                                                "purge_local": False}).get_json()
        assert d["ok"] is True
        job = _wait_for_delete_job(cli)
        assert job is not None and job["status"] == "done", job
        assert [(c.verb, c.path, c.body) for c in pixai.calls] == [
            ("rest_post", "/task/T1/delete", {})]

    def test_a_bulk_delete_pixai_did_not_confirm_is_failed_and_keeps_the_rows(
            self, tmp_path, pixai):
        _one_task_library(tmp_path)
        pixai.on("TaskDetail", {"task": {"id": "T1", "outputs": {"mediaId": "m1"}}})
        pixai.on("/task/T1/delete", {"success": False})
        cli = login_client(tmp_path)
        assert cli.post("/api/delete-tasks", json={"task_ids": ["T1"]}).get_json()["ok"]
        job = _wait_for_delete_job(cli)
        assert job is not None and job["status"] == "failed", job
        assert "1 failed" in (job.get("label") or job.get("error") or "")
        assert len([c for c in pixai.calls if c.verb == "rest_post"]) == 1
        assert _catalog_ids(tmp_path) == ["m1"]
        assert (tmp_path / "images" / "m1.png").exists()

    def test_the_image_delete_answers_an_unconfirmed_delete_as_an_error(
            self, tmp_path, pixai, monkeypatch):
        save_catalog(tmp_path / "catalog.db", [_row(media_id="solo", task_id="T1",
                                                    filename="solo.png")])
        (tmp_path / "solo.png").write_bytes(b"x")
        monkeypatch.setattr(core, "task_detail_gql", lambda s, tid, **k: {
            "id": "T1", "status": "completed", "outputs": {"mediaId": "solo"}})
        pixai.on("/task/T1/delete", {"success": False})
        cli = login_client(tmp_path)
        r = cli.post("/api/delete-image", json={"media_id": "solo", "confirm": True,
                                                "plan": "whole-task"})
        d = r.get_json()
        assert d.get("ok") is not True and "not deleted" in (d.get("error") or ""), d
        assert len([c for c in pixai.calls if c.verb == "rest_post"]) == 1
        assert (tmp_path / "solo.png").exists() and _catalog_ids(tmp_path) == ["solo"]

    def test_the_image_delete_rides_the_api_key_client(self, tmp_path, pixai, monkeypatch):
        save_catalog(tmp_path / "catalog.db", [_row(media_id="solo", task_id="T1",
                                                    filename="solo.png")])
        (tmp_path / "solo.png").write_bytes(b"x")
        monkeypatch.setattr(core, "task_detail_gql", lambda s, tid, **k: {
            "id": "T1", "status": "completed", "outputs": {"mediaId": "solo"}})
        monkeypatch.setattr(core, "make_mirror_session", lambda *a, **k: pytest.fail(
            "the delete reached for the mirror session"))
        pixai.on("/task/T1/delete", {"success": True})
        d = login_client(tmp_path).post("/api/delete-image", json={
            "media_id": "solo", "confirm": True, "plan": "whole-task"}).get_json()
        assert d.get("ok") is True, d
        assert [(c.verb, c.path, c.body) for c in pixai.calls] == [
            ("rest_post", "/task/T1/delete", {})]


# =====================================================================================
# B. THE RENEWAL: POST /v2/auth/refresh-token on the stored JWT, and nothing else
# =====================================================================================

@pytest.fixture
def api_key_configured(monkeypatch):
    """A placeholder API key in THIS test's isolated config.json (conftest pins the path to
    tmp_path) and in the import-time snapshot -- never the real file."""
    core._config_path().write_text(json.dumps({"PIXAI_API_KEY": APIKEY}), encoding="utf-8")
    monkeypatch.setattr(core, "_cfg", {"PIXAI_API_KEY": APIKEY})


class TestTheRenewalRoad:
    def test_one_body_less_post_with_the_bearer_and_no_cookie(self):
        cur, fresh = _jwt(2), _jwt(7, salt="new")
        s = _Recorder(_Resp(body={"token": fresh}))
        assert core.refresh_jwt(s, current_jwt=cur) == fresh
        (verb, url, kwargs), = s.calls
        assert verb == "POST" and url == RENEW_URL
        assert "json" not in kwargs and "data" not in kwargs
        assert kwargs["headers"]["Authorization"] == "Bearer " + cur
        assert "Cookie" not in kwargs["headers"]
        assert set(kwargs["headers"]) == {"Authorization"}

    def test_on_the_wire_the_jwt_wins_over_the_sessions_default_api_key(self):
        cur, fresh = _jwt(2), _jwt(7, salt="new")
        base = requests.Session()
        base.headers["Authorization"] = "Bearer " + APIKEY
        s, wire = _wired(base, body={"token": fresh})
        assert core.refresh_jwt(s, current_jwt=cur) == fresh
        (req,) = wire.sent
        assert req.method == "POST" and req.url == RENEW_URL
        assert req.headers["Authorization"] == "Bearer " + cur
        assert APIKEY not in json.dumps(dict(req.headers))
        assert "Cookie" not in req.headers and not req.body
        assert base.headers["Authorization"] == "Bearer " + APIKEY   # defaults untouched

    def test_the_api_key_is_never_sent(self, api_key_configured):
        s = _Recorder(_Resp(body={"token": _jwt(7)}))
        assert core.refresh_jwt(s, current_jwt=APIKEY) is None
        assert core._refresh_last["reason"] == "no_credential" and s.calls == []

    def test_an_api_key_that_looks_like_a_live_jwt_is_still_never_sent(self, monkeypatch):
        jwtish = _jwt(30, sub="key-holder")
        core._config_path().write_text(json.dumps({"PIXAI_API_KEY": jwtish}),
                                       encoding="utf-8")
        s = _Recorder(_Resp(body={"token": _jwt(7)}))
        assert core.refresh_jwt(s, current_jwt=jwtish) is None
        assert core._refresh_last["reason"] == "no_credential" and s.calls == []

    @pytest.mark.parametrize("cur", [None, "", "not-a-jwt", "expired"])
    def test_no_live_jwt_means_no_request(self, cur):
        if cur == "expired":
            cur = _jwt(-1)
        s = _Recorder(_Resp(body={"token": _jwt(7)}))
        assert core.refresh_jwt(s, current_jwt=cur) is None
        assert core._refresh_last["reason"] == "no_credential" and s.calls == []

    def test_the_body_token_wins_over_a_differing_header(self):
        cur, body_tok, head_tok = _jwt(2), _jwt(7, salt="body"), _jwt(7, salt="head")
        s = _Recorder(_Resp(body={"token": body_tok}, headers={"token": head_tok}))
        assert core.refresh_jwt(s, current_jwt=cur) == body_tok

    def test_the_header_is_the_fallback(self):
        cur, head_tok = _jwt(2), _jwt(7, salt="head")
        s = _Recorder(_Resp(body={}, headers={"token": head_tok}))
        assert core.refresh_jwt(s, current_jwt=cur) == head_tok

    def test_the_same_token_back_is_unchanged(self):
        cur = _jwt(2)
        s = _Recorder(_Resp(body={"token": cur}, headers={"token": cur}))
        assert core.refresh_jwt(s, current_jwt=cur) is None
        assert core._refresh_last["reason"] == "unchanged"

    def test_a_token_not_issued_by_pixai_is_unchanged(self):
        cur = _jwt(2)
        s = _Recorder(_Resp(body={"token": _jwt(7, iss="someone-else")}))
        assert core.refresh_jwt(s, current_jwt=cur) is None
        assert core._refresh_last["reason"] == "unchanged"

    def test_a_fresh_token_for_another_account_is_discarded(self):
        cur, other = _jwt(2, sub="S-main"), _jwt(7, sub="S-dev")
        s = _Recorder(_Resp(body={"token": other}))
        assert core.refresh_jwt(s, current_jwt=cur, expected_sub="S-main") is None
        assert core._refresh_last["reason"] == "identity_mismatch"
        mine = _jwt(7, sub="S-main", salt="n")
        s = _Recorder(_Resp(body={"token": mine}))
        assert core.refresh_jwt(s, current_jwt=cur, expected_sub="S-main") == mine

    @pytest.mark.parametrize("status", [401, 404, 500])
    def test_a_non_200_is_http_code_even_with_a_fresh_token(self, status):
        fresh = _jwt(7, salt="x")
        s = _Recorder(_Resp(status=status, body={"token": fresh}, headers={"token": fresh}))
        assert core.refresh_jwt(s, current_jwt=_jwt(2)) is None
        assert core._refresh_last["reason"] == "http_{}".format(status)

    def test_a_body_that_is_not_json_with_no_header_is_none(self):
        s = _Recorder(_Resp(status=200, text="<html>", json_exc=ValueError("x")))
        assert core.refresh_jwt(s, current_jwt=_jwt(2)) is None
        assert core._refresh_last["reason"] == "unchanged"

    def test_a_network_error_is_network(self):
        s = _Recorder(requests.ConnectionError("down"))
        assert core.refresh_jwt(s, current_jwt=_jwt(2)) is None
        assert core._refresh_last["reason"] == "network" and len(s.calls) == 1

    @pytest.mark.parametrize("ok", [True, False])
    def test_the_cookie_jar_is_empty_afterwards(self, ok):
        """PixAI writes its session cookie back on a renewal; no session may keep it."""
        s, wire = _wired(status=200 if ok else 401, body={"token": _jwt(7, salt="c")},
                         set_cookie=("_bsid", "cookie-value-from-pixai"))
        s.cookies.set("_udt", "stale-cookie", domain="api.pixai.art")
        assert len(s.cookies) == 1
        out = core.refresh_jwt(s, current_jwt=_jwt(2))
        assert (out is not None) is ok
        assert len(s.cookies) == 0

    def test_no_cookie_ever_reaches_the_wire(self):
        """Even a cookie already sitting in the session's jar is not sent with the renewal:
        the jar is emptied before the POST as well as after it, so the renewal stays JWT-only
        (Invariant #7) whatever session it is handed."""
        s, wire = _wired(body={"token": _jwt(7, salt="c")})
        s.cookies.set("_bsid", "a-cookie-in-the-jar", domain="api.pixai.art")
        assert core.refresh_jwt(s, current_jwt=_jwt(2)) is not None
        assert "Cookie" not in wire.sent[0].headers


# ---- B3/B4: the road is recorded, and the cadence around it is unchanged ----------------

def _armed(tmp_path, monkeypatch, jwt, enabled=True):
    p = tmp_path / "mirror_session.json"
    monkeypatch.setattr(core, "_mirror_state_path", lambda: p)
    monkeypatch.setattr(core, "mirror_enabled", lambda: enabled)
    monkeypatch.setattr(core, "READ_ONLY", False)
    monkeypatch.setattr(core, "_read_only_now", lambda: False)
    core.save_mirror_state({"jwt": jwt})
    return p


def _transport(monkeypatch, *answers):
    """Fake the transport at the SESSION level: every mirror session refresh_jwt is handed is
    a recorder answering `answers` in order. The function under test is the real one."""
    made = []

    def _from(jwt):
        s = _Recorder(*answers)
        s.headers["Authorization"] = "Bearer " + jwt
        made.append(s)
        return s
    monkeypatch.setattr(core, "_mirror_session_from", _from)
    return made


class TestTheRoadIsRecorded:
    def test_a_jwt_only_renewal_records_its_road_and_the_stored_sub(self, tmp_path,
                                                                    monkeypatch):
        due, fresh = _jwt(2), _jwt(7, salt="f")
        _armed(tmp_path, monkeypatch, due)
        made = _transport(monkeypatch, _Resp(body={"token": fresh}))
        jwt, outcome = core._mirror_try_renew()
        assert (jwt, outcome) == (fresh, "renewed")
        assert core._mirror_renewal["last_road"] == "jwt"
        (verb, url, kw), = made[0].calls
        assert url == RENEW_URL and kw["headers"] == {"Authorization": "Bearer " + due}
        got = json.loads((tmp_path / "mirror_session.json").read_text(encoding="utf-8"))
        assert set(got) == {"jwt", "minted_at"}                     # never a cookie

    def test_a_renewal_that_switches_account_is_not_stored(self, tmp_path, monkeypatch):
        due = _jwt(2, sub="S-main")
        _armed(tmp_path, monkeypatch, due)
        _transport(monkeypatch, _Resp(body={"token": _jwt(7, sub="S-dev")}))
        assert core._mirror_try_renew()[1] == "failed"
        assert core.load_mirror_state()["jwt"] == due
        assert core._mirror_renewal["last_reason"] == "identity_mismatch"
        assert core._mirror_renewal["last_road"] == ""

    def test_the_reset_clears_the_road(self):
        core._mirror_renewal["last_road"] = "jwt"
        core._mirror_renewal_reset()
        assert core._mirror_renewal["last_road"] == ""

    def test_the_check_says_which_road_renewed(self, tmp_path, monkeypatch, capsys):
        _armed(tmp_path, monkeypatch, _jwt(2))
        _transport(monkeypatch, _Resp(body={"token": _jwt(7, salt="f")}))
        res = core.run_mirror_check(SimpleNamespace())
        out = capsys.readouterr().out
        assert res["renewed"] is True and res["road"] == "jwt"
        assert "renewed via jwt" in out and "PixAI renewed the session" in out
        assert "refreshToken" not in out

    def test_an_expired_stored_jwt_is_still_left_for_connect(self, tmp_path, monkeypatch):
        _armed(tmp_path, monkeypatch, _jwt(-1))
        made = _transport(monkeypatch, _Resp(body={"token": _jwt(7)}))
        assert core.mirror_renew_tick() == "expired"
        assert made == []

    def test_the_check_refuses_under_read_only_and_sends_nothing(self, tmp_path, monkeypatch,
                                                                 capsys):
        _armed(tmp_path, monkeypatch, _jwt(2))
        monkeypatch.setattr(core, "READ_ONLY", True)
        made = _transport(monkeypatch, _Resp(body={"token": _jwt(7)}))
        assert core.run_mirror_check(SimpleNamespace())["source"] == "read_only"
        assert "renewing the session changes your account" in capsys.readouterr().out
        assert made == []

    def test_the_backoff_and_the_floor_still_govern_it(self, tmp_path, monkeypatch):
        now = time.time()
        due = _jwt(2)
        _armed(tmp_path, monkeypatch, due)
        made = _transport(monkeypatch, _Resp(status=500, body={}))
        assert core._mirror_try_renew(now=now)[1] == "failed"
        assert core._mirror_try_renew(now=now + 60)[1] == "backoff"
        assert len(made) == 1
        made2 = _transport(monkeypatch, _Resp(body={"token": _jwt(7, salt="f")}))
        assert core._mirror_try_renew(now=now + 601)[1] == "renewed"
        core.save_mirror_state({"jwt": _jwt(2, salt="again")})
        assert core._mirror_try_renew(now=now + 700)[1] == "floor"
        assert len(made2) == 1


# ---- no credential reaches a log line, the terminal, the record or a return --------------

class TestNoCredentialLeaks:
    @pytest.mark.parametrize("case", ["ok", "http_401", "network"])
    def test_the_check_never_emits_a_token(self, tmp_path, monkeypatch, capsys, caplog,
                                           case):
        old, fresh = _jwt(2, salt="old"), _jwt(7, salt="fresh")
        _armed(tmp_path, monkeypatch, old)
        answer = {"ok": _Resp(body={"token": fresh}, headers={"token": fresh},
                              text=json.dumps({"token": fresh})),
                  "http_401": _Resp(status=401, body={"token": fresh},
                                    headers={"token": fresh}, text=json.dumps({"t": fresh})),
                  "network": requests.ConnectionError("down " + "x")}[case]
        _transport(monkeypatch, answer)
        core.set_verbose(True)
        try:
            with caplog.at_level(logging.DEBUG):
                res = core.run_mirror_check(SimpleNamespace())
        finally:
            core.set_verbose(False)
        cap = capsys.readouterr()
        emitted = "\n".join([cap.out, cap.err, caplog.text, json.dumps(res),
                             json.dumps(core._refresh_last),
                             json.dumps(core._mirror_renewal, default=str)])
        for secret in (old, fresh, old.split(".")[1], fresh.split(".")[1]):
            assert secret not in emitted
        if case == "ok":
            assert res["renewed"] is True
        else:
            assert res["renewed"] is False
            assert "(PixAI answered: {})".format(case) in cap.out
            assert res["reason"] == case

    def test_the_tick_log_line_carries_only_the_road_and_the_days(self):
        """The gallery's background line prints a fixed road word and days left -- never the
        token (its arguments are read off the renewal record and jwt_days_left)."""
        from moonglade import gallery as g
        src = inspect.getsource(g.create_app)
        tick = src[src.index("def _mirror_renew_tick():"):]
        tick = tick[:tick.index("\n    def ", 10)]
        assert "via %s" in tick and 'get("last_road")' in tick
        assert "load_mirror_state().get(\"jwt\")" not in tick.split("_log.info(")[1].split(")")[0]


# =====================================================================================
# C. THE BOOKMARKS READ HAS ONE ROAD
# =====================================================================================

def test_a_refused_bookmarks_read_raises_and_tries_no_second_road():
    fake = FakePixAI().fail("me", core.PixAIError("401 Unauthorized -- API key missing/expired."))
    with pytest.raises(core.PixAIError, match="401"):
        core.model_bookmarks_gql(fake, usage="MODEL")
    assert fake.calls and {c.verb for c in fake.calls} == {"query"}


# =====================================================================================
# RETIRED: no saved request is left anywhere
# =====================================================================================

def test_the_retired_names_are_gone():
    for name in ("DELETE_TASK_HASH", "DELETE_OPERATION", "delete_task_gql",
                 "REFRESH_TOKEN_HASH", "BOOKMARKED_MODELS_OP", "BOOKMARKED_MODELS_HASH",
                 "_bookmarks_persisted", "CLIENT_LIBRARY", "PersistedQueryNotRecognized"):
        assert not hasattr(core, name), name
    assert not hasattr(core.PixAIClient, "persisted")
    assert not hasattr(FakePixAI, "persisted")


def test_no_module_sends_a_saved_request():
    for py in sorted((REPO / "moonglade").glob("*.py")):
        assert "persistedQuery" not in py.read_text(encoding="utf-8"), py.name


def test_the_example_config_has_no_hash_key():
    example = json.loads((REPO / "config.example.json").read_text(encoding="utf-8"))
    assert not [k for k in example if k.endswith("_HASH")]
    assert "_comment_hashes" not in example and "_comment_refresh_hash" not in example
