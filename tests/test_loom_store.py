"""The Loom key->value store: per-key ATOMIC files (a crash can't corrupt every
board at once), filesystem-hostile key encoding, and one-time migration off the
legacy single store.json. The React app's window.storage API is unchanged; this
tests the server backend underneath it."""
import json

from tests.conftest import login_client


def _client(tmp_path):
    return login_client(tmp_path)


def test_set_get_roundtrip_and_isolation(tmp_path):
    cli = _client(tmp_path)
    cli.post("/api/loom/set", json={"key": "storyboard:v2:proj:A", "value": {"name": "Alpha"}})
    cli.post("/api/loom/set", json={"key": "storyboard:v2:proj:B", "value": {"name": "Beta"}})
    assert cli.get("/api/loom/get?key=storyboard:v2:proj:A").get_json()["value"] == {"name": "Alpha"}
    # each key is its own file, in the account's own per-account dir (D-7) -> per-project isolation
    assert len(list((tmp_path / "loom" / "kv" / "tester").glob("*.json"))) == 2
    # deleting one leaves the other intact (blast radius contained to one board)
    cli.post("/api/loom/delete", json={"key": "storyboard:v2:proj:A"})
    assert cli.get("/api/loom/get?key=storyboard:v2:proj:A").get_json()["value"] is None
    assert cli.get("/api/loom/get?key=storyboard:v2:proj:B").get_json()["value"] == {"name": "Beta"}


def test_missing_key_reads_none_and_delete_is_idempotent(tmp_path):
    cli = _client(tmp_path)
    assert cli.get("/api/loom/get?key=nope").get_json()["value"] is None
    # deleting a key that was never written must not error
    assert cli.post("/api/loom/delete", json={"key": "nope"}).get_json()["ok"] is True


def test_list_by_prefix_with_hostile_keys(tmp_path):
    cli = _client(tmp_path)
    for k in ("storyboard:v2:proj:1", "storyboard:v2:proj:2", "storyboard:v2:layout"):
        cli.post("/api/loom/set", json={"key": k, "value": 1})
    keys = set(cli.get("/api/loom/list?prefix=storyboard:v2:proj:").get_json()["keys"])
    assert keys == {"storyboard:v2:proj:1", "storyboard:v2:proj:2"}   # colons round-trip through the filename


def test_atomic_write_leaves_no_temp_in_kv_dir(tmp_path):
    cli = _client(tmp_path)
    cli.post("/api/loom/set", json={"key": "k", "value": "v"})
    # only the final file exists; the tmp+os.replace idiom leaks no .tmp-* into the dir
    assert [p.name for p in (tmp_path / "loom" / "kv" / "tester").iterdir()] == ["k.json"]


def test_migrates_legacy_store_json_once(tmp_path):
    loom = tmp_path / "loom"
    loom.mkdir(parents=True)
    (loom / "store.json").write_text(json.dumps({
        "storyboard:v2:proj:old": {"name": "Legacy"},
        "storyboard:v2:active": "old"}), encoding="utf-8")
    cli = _client(tmp_path)
    # first touch migrates: values readable, split into per-key files, legacy preserved
    assert cli.get("/api/loom/get?key=storyboard:v2:proj:old").get_json()["value"] == {"name": "Legacy"}
    assert cli.get("/api/loom/get?key=storyboard:v2:active").get_json()["value"] == "old"
    assert (loom / "store.json.migrated").exists()
    assert not (loom / "store.json").exists()
    assert len(list((loom / "kv").glob("*.json"))) == 2
    # migration is one-shot: a later write doesn't resurrect the legacy file
    cli.post("/api/loom/set", json={"key": "storyboard:v2:proj:new", "value": 1})
    assert not (loom / "store.json").exists()


def test_one_account_cannot_see_or_clobber_or_list_anothers_storyboards(tmp_path):
    """Same split saved views/snippets already got, same reason: Loom storyboards were
    install-wide (one shared out_dir/loom/kv/), so any signed-in account could read AND
    overwrite AND enumerate every other account's boards."""
    from pixai_gallery import create_app
    from tests.conftest import login_test_client
    app = create_app(tmp_path)

    alice = login_test_client(app, username="alice", password="a-real-test-password-1")
    alice.post("/api/loom/set", json={"key": "storyboard:v2:proj:A", "value": {"name": "Alpha"}})

    bob = login_test_client(app, username="bob", password="a-real-test-password-2")
    assert bob.get("/api/loom/get?key=storyboard:v2:proj:A").get_json()["value"] is None, (
        "bob can read alice's storyboard -- the store is not per-account")
    assert bob.get("/api/loom/list?prefix=storyboard:v2:proj:").get_json()["keys"] == [], (
        "bob can list alice's storyboard keys -- the store is not per-account")

    # bob writing the SAME key must not touch alice's board
    bob.post("/api/loom/set", json={"key": "storyboard:v2:proj:A", "value": {"name": "Bob's own A"}})
    assert bob.get("/api/loom/get?key=storyboard:v2:proj:A").get_json()["value"] == {"name": "Bob's own A"}
    assert alice.get("/api/loom/get?key=storyboard:v2:proj:A").get_json()["value"] == {"name": "Alpha"}, (
        "bob's set overwrote alice's storyboard -- the store is not per-account")


def test_account_without_its_own_dir_still_sees_legacy_shared_boards(tmp_path):
    """Upgrade path: nothing disappears the moment the store goes per-account. An
    account with no dir of its own falls back to the old shared out_dir/loom/kv/
    (read-only) -- exactly what it saw before the split -- but writing a DIFFERENT key
    doesn't leak into another account's dir."""
    kv = tmp_path / "loom" / "kv"
    kv.mkdir(parents=True)
    (kv / "storyboard%3Av2%3Aproj%3Aold.json").write_text(
        json.dumps({"name": "Legacy board"}), encoding="utf-8")

    alice = login_client(tmp_path, username="alice", password="a-real-test-password-1")
    assert alice.get("/api/loom/get?key=storyboard:v2:proj:old").get_json()["value"] == {
        "name": "Legacy board"}

    alice.post("/api/loom/set", json={"key": "storyboard:v2:proj:new", "value": 1})
    assert not (kv / "alice" / "storyboard%3Av2%3Aproj%3Aold.json").exists(), (
        "alice's own dir must not gain a copy of a key she never wrote herself")
    assert (kv / "alice" / "storyboard%3Av2%3Aproj%3Anew.json").exists()
