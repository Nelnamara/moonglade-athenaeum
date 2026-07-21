"""/api/view-presets: the saved-view roaming store.

Saved views used to be localStorage-only -- one private set per browser, so a view
saved at the desktop simply didn't exist on the tablet (the 2026-07-19 crawl's
defect list). These pin the server half of the fix: the roundtrip, the one-time
legacy-localStorage merge (server names win ties), delete, fail-soft loading, and
the '?'-prefix guard -- the client navigates a loaded preset via
location.href = '/' + query, where a stored '//host' would resolve
protocol-relative and turn a saved view into an off-site redirect.
Tier enforcement (login-required) is asserted by tests/test_route_tiers.py.
"""
import json

from pixai_gallery import create_app
from tests.conftest import login_client


def _presets_file(tmp_path):
    return tmp_path / "view_presets.json"


def test_get_starts_empty(tmp_path):
    cli = login_client(tmp_path)
    r = cli.get("/api/view-presets")
    assert r.status_code == 200
    assert r.get_json() == {"presets": {}}


def test_save_roundtrip_and_atomic_file(tmp_path):
    cli = login_client(tmp_path)
    r = cli.post("/api/view-presets", json={"name": "wallpapers", "query": "?q=wallpaper&sort=rating"})
    assert r.status_code == 200
    assert r.get_json()["presets"] == {"wallpapers": "?q=wallpaper&sort=rating"}
    # a fresh GET reads the same thing back
    assert cli.get("/api/view-presets").get_json()["presets"]["wallpapers"] == "?q=wallpaper&sort=rating"
    # ...and it is really on disk as valid JSON, with no .tmp left behind
    on_disk = json.loads(_presets_file(tmp_path).read_text(encoding="utf-8"))
    assert on_disk == {"wallpapers": "?q=wallpaper&sort=rating"}
    assert not _presets_file(tmp_path).with_suffix(".tmp").exists()


def test_save_overwrites_same_name(tmp_path):
    cli = login_client(tmp_path)
    cli.post("/api/view-presets", json={"name": "n", "query": "?a=1"})
    cli.post("/api/view-presets", json={"name": "n", "query": "?b=2"})
    assert cli.get("/api/view-presets").get_json()["presets"] == {"n": "?b=2"}


def test_save_requires_name_and_query_shape(tmp_path):
    cli = login_client(tmp_path)
    assert cli.post("/api/view-presets", json={"query": "?a=1"}).status_code == 400
    assert cli.post("/api/view-presets", json={"name": "  ", "query": "?a=1"}).status_code == 400
    # no leading '?': not what savePreset stores, refused
    assert cli.post("/api/view-presets", json={"name": "n", "query": "a=1"}).status_code == 400
    # the redirect vector the guard exists for: '/' + '//evil.example' is protocol-relative
    assert cli.post("/api/view-presets", json={"name": "n", "query": "//evil.example"}).status_code == 400
    assert cli.get("/api/view-presets").get_json()["presets"] == {}


def test_delete_removes_and_unknown_delete_is_a_noop(tmp_path):
    cli = login_client(tmp_path)
    cli.post("/api/view-presets", json={"name": "keep", "query": "?k=1"})
    cli.post("/api/view-presets", json={"name": "drop", "query": "?d=1"})
    r = cli.post("/api/view-presets", json={"delete": "drop"})
    assert r.status_code == 200
    assert r.get_json()["presets"] == {"keep": "?k=1"}
    # deleting a name that isn't there changes nothing and doesn't error
    r = cli.post("/api/view-presets", json={"delete": "never-existed"})
    assert r.status_code == 200
    assert r.get_json()["presets"] == {"keep": "?k=1"}


def test_merge_imports_legacy_without_clobbering(tmp_path):
    """The one-time localStorage migration: new names come in, but a name the server
    already has KEEPS the server's value -- two browsers migrating in sequence must
    not fight over whose stale copy wins."""
    cli = login_client(tmp_path)
    cli.post("/api/view-presets", json={"name": "shared", "query": "?server=1"})
    r = cli.post("/api/view-presets", json={"merge": {
        "shared": "?browser=1",          # collision: server's value must survive
        "browser-only": "?b=1",          # new: comes in
        "bad": "//evil.example",         # fails the query guard: silently skipped
        "  ": "?blank=1",                # blank name: skipped
    }})
    assert r.status_code == 200
    assert r.get_json()["presets"] == {"shared": "?server=1", "browser-only": "?b=1"}


def test_corrupt_store_fails_soft_to_empty(tmp_path):
    cli = login_client(tmp_path)
    _presets_file(tmp_path).write_text("{not json", encoding="utf-8")
    assert cli.get("/api/view-presets").get_json() == {"presets": {}}
    # and a save from that state simply starts a fresh, valid store
    cli.post("/api/view-presets", json={"name": "n", "query": "?a=1"})
    assert json.loads(_presets_file(tmp_path).read_text(encoding="utf-8")) == {"n": "?a=1"}


def test_non_string_values_in_store_are_dropped_on_load(tmp_path):
    cli = login_client(tmp_path)
    _presets_file(tmp_path).write_text(json.dumps({"ok": "?a=1", "bad": 7}), encoding="utf-8")
    assert cli.get("/api/view-presets").get_json()["presets"] == {"ok": "?a=1"}


def test_anonymous_request_is_refused(tmp_path):
    """Belt-and-braces beside test_route_tiers: the roaming store must sit behind
    the front door like everything else."""
    cli = create_app(tmp_path).test_client()
    r = cli.get("/api/view-presets")
    assert r.status_code in (301, 302, 303, 401, 403)
