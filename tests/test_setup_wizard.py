"""The first-run wizard: the gallery's home page banner that guides someone from a fresh
clone (no key, no catalog) to a working gallery, without a manual config.json edit.

/api/setup/save-key validates the submitted key with a real account_info call BEFORE
writing anything to config.json -- it deliberately does NOT go through core._make_session()/
load_token(), which prefer the module-cached core._cfg over a fresh config.json read (so a
running process doesn't need a restart to keep using its already-loaded key). That caching
is exactly right for normal operation, but it means "validate the same way normal calls
authenticate" would silently validate a freshly-pasted key against whatever was cached at
process start instead -- confirmed live during development, where a garbage key was reported
as verified because the real cached key answered instead. This suite locks in the fix:
build a session from the submitted key alone, and never write to disk until that call
actually succeeds."""
import json
import re

import pytest

import moonglade_backup as core
from moonglade_gallery import CATALOG_FIELDS, save_catalog

from tests.conftest import login_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _authed_client(tmp_path, rows=()):
    """Like _client(), but logged in for real. Used by EVERY test below, including
    test_localhost_only -- an anonymous client cannot test a localhost gate, because the
    front door refuses it first and the handler never runs. See that test's docstring."""
    if rows:
        save_catalog(tmp_path / "catalog.db", list(rows))
    return login_client(tmp_path)


def _redirect_config_to(monkeypatch, tmp_path):
    """core.__file__'s directory is where config.json is read/written. Point it at a
    throwaway tmp_path directory so a test can never touch the real one."""
    fake_module_file = tmp_path / "moonglade_backup.py"
    monkeypatch.setattr(core, "__file__", str(fake_module_file))


class TestSaveKeyEndpoint:
    def test_rejects_empty_key(self, tmp_path):
        cli = _authed_client(tmp_path)
        r = cli.post("/api/setup/save-key", data=json.dumps({"api_key": "  "}),
                     content_type="application/json")
        assert r.status_code == 400

    def test_localhost_only(self, tmp_path):
        """AUTHENTICATED but non-local. The front door admits this request (the login is
        genuinely valid), so a 403 here can ONLY come from the handler's own
        _is_local_request() check -- which is the thing this test claims to cover.

        It previously drove an ANONYMOUS client and asserted 401. That 401 is answered by
        _enforce_front_door() before the handler body ever runs, so the test passed
        identically whether or not the localhost check existed. It did not exist: a
        route-gating audit on 2026-07-19 found this route had never had one, while this
        very docstring's route claimed 'Localhost-only', and reproduced a LAN session
        overwriting PIXAI_API_KEY in the same config.json that holds AUTH_SECRET_KEY and
        AUTH_USERS. Anonymous refusal is still covered, by the front-door suite in
        tests/test_web_auth.py -- it does not need to be re-asserted here."""
        cli = _authed_client(tmp_path)
        r = cli.post("/api/setup/save-key", data=json.dumps({"api_key": "sk-real"}),
                     content_type="application/json",
                     environ_overrides={"REMOTE_ADDR": "192.168.1.50"})
        assert r.status_code == 403
        assert "localhost" in r.get_json()["error"]

    def test_writes_config_only_after_successful_validation(self, tmp_path, monkeypatch):
        _redirect_config_to(monkeypatch, tmp_path)
        cfg_path = tmp_path / "config.json"
        monkeypatch.setattr(core, "account_info", lambda session, raise_on_error=False: {"quotaAmount": 500})
        cli = _authed_client(tmp_path)
        r = cli.post("/api/setup/save-key", data=json.dumps({"api_key": "sk-real-key"}),
                     content_type="application/json")
        d = r.get_json()
        assert d == {"ok": True, "credits": 500}
        assert json.loads(cfg_path.read_text())["PIXAI_API_KEY"] == "sk-real-key"

    def test_does_not_write_config_when_validation_fails(self, tmp_path, monkeypatch):
        """The property that actually matters: a bad key must never even land on disk --
        not written-then-rolled-back, never written at all. (config.json itself may now
        exist by this point -- create_app() persists a session AUTH_SECRET_KEY into it on
        startup, unrelated to this endpoint -- so the real assertion is that PIXAI_API_KEY
        specifically was never added, not that the file is absent.)"""
        _redirect_config_to(monkeypatch, tmp_path)
        cfg_path = tmp_path / "config.json"

        def _reject(session, raise_on_error=False):
            raise core.PixAIError("HTTP 401 Unauthorized")
        monkeypatch.setattr(core, "account_info", _reject)
        cli = _authed_client(tmp_path)
        r = cli.post("/api/setup/save-key", data=json.dumps({"api_key": "totally-bogus"}),
                     content_type="application/json")
        d = r.get_json()
        assert "error" in d
        assert "rejected" in d["error"].lower()
        cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
        assert "PIXAI_API_KEY" not in cfg

    def test_validates_the_submitted_key_not_a_cached_one(self, tmp_path, monkeypatch):
        """Regression test for the exact live bug: core._cfg (module-cached at import time)
        must never be consulted for validation -- only the key in THIS request's body."""
        _redirect_config_to(monkeypatch, tmp_path)
        # Simulate a process that already has a DIFFERENT, real-looking key cached from
        # server startup -- this is the state that fooled the original implementation.
        monkeypatch.setattr(core, "_cfg", {"PIXAI_API_KEY": "sk-old-cached-key"})
        seen_auth = []

        def _capture(session, raise_on_error=False):
            seen_auth.append(session.headers.get("Authorization"))
            raise core.PixAIError("401 Unauthorized")  # the NEW key is bogus; must be rejected
        monkeypatch.setattr(core, "account_info", _capture)
        cli = _authed_client(tmp_path)
        r = cli.post("/api/setup/save-key", data=json.dumps({"api_key": "brand-new-bogus-key"}),
                     content_type="application/json")
        assert "error" in r.get_json()
        assert seen_auth == ["Bearer brand-new-bogus-key"]  # never the cached old key
        # config.json may now exist (create_app() persists a session AUTH_SECRET_KEY on
        # startup, unrelated to this endpoint) -- what must never happen is the bogus key
        # landing in it.
        cfg_path = tmp_path / "config.json"
        cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
        assert "PIXAI_API_KEY" not in cfg

    def test_preserves_other_config_fields(self, tmp_path, monkeypatch):
        _redirect_config_to(monkeypatch, tmp_path)
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({"READ_ONLY": True, "USER_ID": "123"}))
        monkeypatch.setattr(core, "account_info", lambda session, raise_on_error=False: {"quotaAmount": 0})
        cli = _authed_client(tmp_path)
        cli.post("/api/setup/save-key", data=json.dumps({"api_key": "sk-new"}),
                 content_type="application/json")
        cfg = json.loads(cfg_path.read_text())
        assert cfg["PIXAI_API_KEY"] == "sk-new"
        assert cfg["READ_ONLY"] is True
        assert cfg["USER_ID"] == "123"

    def test_config_write_failure_redacts_the_host_path(self, tmp_path, monkeypatch):
        """This route's two config.json read/write failure messages build their error
        text with .format(e) rather than a bare str(e) -- caught by adversarial review
        as a real gap in the mechanical str(e)-wrapping sweep (docs/AUDIT_2026-07-21.md's
        S3 re-spin): a text-matching sweep for the literal substring "str(e)" is blind to
        a caught exception referenced any other way. tmp_path (used as both out_dir and,
        via _redirect_config_to, the directory config.json lives in) stands in for the
        host path that must not reach the response.

        Bite: revert either .format(e) call back to a bare str(e) (no
        _redact_host_paths wrapper) and this fails."""
        _redirect_config_to(monkeypatch, tmp_path)
        monkeypatch.setattr(core, "account_info", lambda session, raise_on_error=False: {"quotaAmount": 500})
        from pathlib import Path as RealPath
        orig_write_text = RealPath.write_text

        def boom_write(self, *a, **k):
            if self.name == "config.json":
                raise OSError("[Errno 13] Permission denied: '{}'".format(self))
            return orig_write_text(self, *a, **k)
        monkeypatch.setattr(RealPath, "write_text", boom_write)

        cli = _authed_client(tmp_path)
        r = cli.post("/api/setup/save-key", data=json.dumps({"api_key": "sk-real-key"}),
                     content_type="application/json")
        body = r.get_data(as_text=True)
        assert str(tmp_path) not in body
        assert "<host-path>" in body


def _boot(cli):
    """Parse the window.MG_BOOT JSON blob out of the React shell GET / serves. The
    boot script is written with Jinja's |tojson, which escapes `<` -- so the first
    `;</script>` after the assignment is guaranteed to be the real end of the blob."""
    html = cli.get("/").get_data(as_text=True)
    m = re.search(r"window\.MG_BOOT = (.+?);</script>", html)
    assert m, "GET / did not render a window.MG_BOOT boot blob"
    return json.loads(m.group(1))


class TestWizardBootGating:
    """PORTED from the /classic server-rendered banner (cut 2026-08-08 with
    INDEX_HTML): the banner itself is a React surface now, but the SERVER still owns
    the gating -- app_page() computes needs_key/catalog_empty from a FRESH
    config.json read (never the module-cached core._cfg, same as classic's index()
    did, so a key pasted via the wizard flips the state on the very next load) and
    ships them in window.MG_BOOT. These tests lock in that computation.

    The old test_no_banner_for_lan_requests_even_with_no_key is deliberately NOT
    ported: the cut removed the LAN suppression on purpose -- a signed-in LAN
    session sees the same boot flags an owner does, and the localhost-only
    enforcement lives where the writes happen (/api/setup/save-key, covered by
    test_localhost_only above; anonymous LAN refusal is the front-door suite's,
    tests/test_web_auth.py)."""

    def test_needs_key_when_no_key_configured(self, tmp_path):
        boot = _boot(_authed_client(tmp_path))
        assert boot["needs_key"] is True
        assert boot["catalog_empty"] is False

    def test_catalog_empty_when_key_present_but_no_rows(self, tmp_path):
        cli = _authed_client(tmp_path)  # zero rows
        cfg_path = tmp_path / "config.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["PIXAI_API_KEY"] = "sk-x"
        cfg_path.write_text(json.dumps(cfg))
        boot = _boot(cli)
        assert boot["needs_key"] is False
        assert boot["catalog_empty"] is True

    def test_no_wizard_state_once_catalog_has_rows(self, tmp_path):
        cli = _authed_client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                             created_at="2025-01-01T00:00:00")])
        cfg_path = tmp_path / "config.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["PIXAI_API_KEY"] = "sk-x"
        cfg_path.write_text(json.dumps(cfg))
        boot = _boot(cli)
        assert boot["needs_key"] is False
        assert boot["catalog_empty"] is False
