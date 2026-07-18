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

import pytest

import pixai_gallery_backup as core
from pixai_gallery import CATALOG_FIELDS, create_app, save_catalog


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _client(tmp_path, rows=()):
    if rows:
        save_catalog(tmp_path / "catalog.db", list(rows))
    return create_app(tmp_path).test_client()


def _redirect_config_to(monkeypatch, tmp_path):
    """core.__file__'s directory is where config.json is read/written. Point it at a
    throwaway tmp_path directory so a test can never touch the real one."""
    fake_module_file = tmp_path / "pixai_gallery_backup.py"
    monkeypatch.setattr(core, "__file__", str(fake_module_file))


class TestSaveKeyEndpoint:
    def test_rejects_empty_key(self, tmp_path):
        cli = _client(tmp_path)
        r = cli.post("/api/setup/save-key", data=json.dumps({"api_key": "  "}),
                     content_type="application/json")
        assert r.status_code == 400

    def test_localhost_only(self, tmp_path):
        cli = _client(tmp_path)
        r = cli.post("/api/setup/save-key", data=json.dumps({"api_key": "sk-real"}),
                     content_type="application/json",
                     environ_overrides={"REMOTE_ADDR": "192.168.1.50"})
        assert r.status_code == 403

    def test_writes_config_only_after_successful_validation(self, tmp_path, monkeypatch):
        _redirect_config_to(monkeypatch, tmp_path)
        cfg_path = tmp_path / "config.json"
        monkeypatch.setattr(core, "account_info", lambda session, raise_on_error=False: {"quotaAmount": 500})
        cli = _client(tmp_path)
        r = cli.post("/api/setup/save-key", data=json.dumps({"api_key": "sk-real-key"}),
                     content_type="application/json")
        d = r.get_json()
        assert d == {"ok": True, "credits": 500}
        assert json.loads(cfg_path.read_text())["PIXAI_API_KEY"] == "sk-real-key"

    def test_does_not_write_config_when_validation_fails(self, tmp_path, monkeypatch):
        """The property that actually matters: a bad key must never even land on disk --
        not written-then-rolled-back, never written at all."""
        _redirect_config_to(monkeypatch, tmp_path)
        cfg_path = tmp_path / "config.json"

        def _reject(session, raise_on_error=False):
            raise core.PixAIError("HTTP 401 Unauthorized")
        monkeypatch.setattr(core, "account_info", _reject)
        cli = _client(tmp_path)
        r = cli.post("/api/setup/save-key", data=json.dumps({"api_key": "totally-bogus"}),
                     content_type="application/json")
        d = r.get_json()
        assert "error" in d
        assert "rejected" in d["error"].lower()
        assert not cfg_path.exists()

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
        cli = _client(tmp_path)
        r = cli.post("/api/setup/save-key", data=json.dumps({"api_key": "brand-new-bogus-key"}),
                     content_type="application/json")
        assert "error" in r.get_json()
        assert seen_auth == ["Bearer brand-new-bogus-key"]  # never the cached old key
        assert not (tmp_path / "config.json").exists()

    def test_preserves_other_config_fields(self, tmp_path, monkeypatch):
        _redirect_config_to(monkeypatch, tmp_path)
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({"READ_ONLY": True, "USER_ID": "123"}))
        monkeypatch.setattr(core, "account_info", lambda session, raise_on_error=False: {"quotaAmount": 0})
        cli = _client(tmp_path)
        cli.post("/api/setup/save-key", data=json.dumps({"api_key": "sk-new"}),
                 content_type="application/json")
        cfg = json.loads(cfg_path.read_text())
        assert cfg["PIXAI_API_KEY"] == "sk-new"
        assert cfg["READ_ONLY"] is True
        assert cfg["USER_ID"] == "123"


class TestWizardBannerGating:
    def test_needs_key_banner_when_no_key_configured(self, tmp_path, monkeypatch):
        monkeypatch.setattr(core, "_load_config", lambda: {})
        cli = _client(tmp_path)
        html = cli.get("/").get_data(as_text=True)
        assert 'id="setup-wizard"' in html
        assert "Paste your PixAI API key" in html
        assert "Run your first sync" not in html

    def test_catalog_empty_banner_when_key_present_but_no_rows(self, tmp_path, monkeypatch):
        monkeypatch.setattr(core, "_load_config", lambda: {"PIXAI_API_KEY": "sk-x"})
        cli = _client(tmp_path)  # zero rows
        html = cli.get("/").get_data(as_text=True)
        assert "Run your first sync" in html
        assert "Paste your PixAI API key" not in html

    def test_no_banner_once_catalog_has_rows(self, tmp_path, monkeypatch):
        monkeypatch.setattr(core, "_load_config", lambda: {"PIXAI_API_KEY": "sk-x"})
        cli = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                       created_at="2025-01-01T00:00:00")])
        html = cli.get("/").get_data(as_text=True)
        assert 'id="setup-wizard"' not in html

    def test_no_banner_for_lan_requests_even_with_no_key(self, tmp_path, monkeypatch):
        """The wizard is an owner-only action (writes credentials, triggers a sync) --
        a LAN browser must never be invited to paste a key into someone else's machine."""
        monkeypatch.setattr(core, "_load_config", lambda: {})
        cli = _client(tmp_path)
        html = cli.get("/", environ_overrides={"REMOTE_ADDR": "192.168.1.50"}).get_data(as_text=True)
        assert 'id="setup-wizard"' not in html
