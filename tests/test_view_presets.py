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

from pixai_gallery import _account_key, create_app
from tests.conftest import login_client


def _presets_file(tmp_path, user="tester"):
    """One account's own store. Saved views are PER-ACCOUNT: a saved view is a stored
    search (names + queries that say what someone looks for in their library), not a
    theme, so it does not get the install-wide treatment /api/skin gets.

    Keyed through the same _account_key() the app itself uses (B14 residual: a bare
    username here would silently pass on a case-insensitive filesystem even after a
    regression, since "tester" happens to need no encoding either way)."""
    return tmp_path / "view_presets" / (_account_key(user) + ".json")


def _legacy_presets_file(tmp_path):
    """The pre-split shared store. Still READ as a fallback for an account that has no
    file of its own yet, so nothing vanishes on upgrade; never written back to."""
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
    _presets_file(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    _presets_file(tmp_path).write_text("{not json", encoding="utf-8")
    assert cli.get("/api/view-presets").get_json() == {"presets": {}}
    # and a save from that state simply starts a fresh, valid store
    cli.post("/api/view-presets", json={"name": "n", "query": "?a=1"})
    assert json.loads(_presets_file(tmp_path).read_text(encoding="utf-8")) == {"n": "?a=1"}


def test_non_string_values_in_store_are_dropped_on_load(tmp_path):
    cli = login_client(tmp_path)
    _presets_file(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    _presets_file(tmp_path).write_text(json.dumps({"ok": "?a=1", "bad": 7}), encoding="utf-8")
    assert cli.get("/api/view-presets").get_json()["presets"] == {"ok": "?a=1"}


def test_one_account_cannot_see_or_clobber_anothers_saved_views(tmp_path):
    """The whole point of the per-account split, pinned.

    Saved views shipped install-wide (a single out_dir/view_presets.json) by analogy with
    /api/skin. That is the right analogy for a THEME and the wrong one here: a saved view
    is a stored SEARCH -- a name and a query that say what someone looks for in their own
    library. Moonglade is explicitly not single-user, so install-wide meant every account
    could read, overwrite and delete every other account's saved searches.

    Bite: point _view_presets_path() back at one shared file and both halves fail --
    bob sees alice's view, and bob's same-named save overwrites hers.
    """
    from pixai_gallery import create_app
    from tests.conftest import login_test_client
    app = create_app(tmp_path)

    alice = login_test_client(app, username="alice", password="a-real-test-password-1")
    alice.post("/api/view-presets", json={"name": "mine", "query": "?q=alice-only"})

    bob = login_test_client(app, username="bob", password="a-real-test-password-2")
    assert bob.get("/api/view-presets").get_json()["presets"] == {}, (
        "bob can see alice's saved searches -- the store is not per-account")

    # bob saving the SAME name must not touch alice's entry
    bob.post("/api/view-presets", json={"name": "mine", "query": "?q=bob-only"})
    assert bob.get("/api/view-presets").get_json()["presets"] == {"mine": "?q=bob-only"}
    assert alice.get("/api/view-presets").get_json()["presets"] == {"mine": "?q=alice-only"}, (
        "bob's save overwrote alice's identically-named view")

    # ...and bob's delete must not reach into alice's set either
    bob.post("/api/view-presets", json={"delete": "mine"})
    assert alice.get("/api/view-presets").get_json()["presets"] == {"mine": "?q=alice-only"}


def test_saved_views_are_independent_for_accounts_differing_only_by_case(tmp_path):
    """B14 residual: the per-account key was quote(username, safe=""), which is
    case-PRESERVING -- it produces two DIFFERENT strings for "Nel" and "nel" ("Nel"
    and "nel" themselves, neither has characters quote() escapes). Those two
    different strings name the SAME file on NTFS (case-insensitive-but-preserving),
    even though account identity itself is case-SENSITIVE: _find_web_user compares
    the raw username with ==, so "Nel" and "nel" are two separate AUTH_USERS rows,
    same as "alice"/"bob" above -- just unlucky enough to collide on disk. FAILS
    before the fix on this filesystem: nel's read/save clobbers Nel's, exactly like
    the alice/bob test above would if _view_presets_path() were reverted to a
    shared file."""
    from pixai_gallery import create_app
    from tests.conftest import login_test_client
    app = create_app(tmp_path)

    upper = login_test_client(app, username="Nel", password="a-real-test-password-1")
    upper.post("/api/view-presets", json={"name": "mine", "query": "?q=Nel-only"})

    lower = login_test_client(app, username="nel", password="a-real-test-password-2")
    assert lower.get("/api/view-presets").get_json()["presets"] == {}, (
        "nel can see Nel's saved views -- case-differing usernames collide on disk")

    lower.post("/api/view-presets", json={"name": "mine", "query": "?q=nel-only"})
    assert lower.get("/api/view-presets").get_json()["presets"] == {"mine": "?q=nel-only"}
    assert upper.get("/api/view-presets").get_json()["presets"] == {"mine": "?q=Nel-only"}, (
        "nel's save overwrote Nel's identically-named view -- case-collision on disk")


def test_an_account_without_its_own_file_still_sees_the_legacy_shared_set(tmp_path):
    """Upgrade path: nothing disappears the moment the store goes per-account.

    An account with no file of its own falls back to reading the old shared
    out_dir/view_presets.json -- exactly what it saw before the split. The fallback is
    read-only and needs no migration flag: the first save writes the account's own file
    and it diverges from then on. That avoids the first-loader-claims-everything race a
    migration flag would have introduced.
    """
    cli = login_client(tmp_path)
    _legacy_presets_file(tmp_path).write_text(
        json.dumps({"from-before": "?q=legacy"}), encoding="utf-8")

    assert cli.get("/api/view-presets").get_json()["presets"] == {"from-before": "?q=legacy"}

    # First save takes ownership: the account's own file appears, carrying the inherited
    # entry plus the new one, and the legacy file is left untouched for other accounts.
    cli.post("/api/view-presets", json={"name": "new-one", "query": "?q=new"})
    own = json.loads(_presets_file(tmp_path).read_text(encoding="utf-8"))
    assert own == {"from-before": "?q=legacy", "new-one": "?q=new"}
    assert json.loads(_legacy_presets_file(tmp_path).read_text(encoding="utf-8")) == {
        "from-before": "?q=legacy"}


def test_anonymous_request_is_refused(tmp_path):
    """Belt-and-braces beside test_route_tiers: the roaming store must sit behind
    the front door like everything else."""
    cli = create_app(tmp_path).test_client()
    r = cli.get("/api/view-presets")
    assert r.status_code in (301, 302, 303, 401, 403)
