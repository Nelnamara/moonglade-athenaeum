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
    # each key is its own file -> per-project isolation
    assert len(list((tmp_path / "loom" / "kv").glob("*.json"))) == 2
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
    assert [p.name for p in (tmp_path / "loom" / "kv").iterdir()] == ["k.json"]


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
