"""/api/account/prefs and the store behind it: one JSON document per app login account.

The store is generic plumbing for later waves (first-run guide state, "what's new" seen,
per-feat flags, generate defaults per base family) -- so these pin the CONTRACT, not any
consumer: the account comes from the session and nothing else, each account has its own
file, keys and values are validated at the write boundary with a plain 400, the two size
caps hold, a corrupt file reads as empty and is kept rather than overwritten, and a write
is atomic under a lock. Tier enforcement (LOGIN) is asserted by tests/test_route_tiers.py.
"""
import json
import os
import threading
import time

import pytest

from moonglade import backup as core
from moonglade import gallery as g
from moonglade import paths
from moonglade.gallery import (
    ACCOUNT_LOCAL,
    ACCOUNT_PREF_VALUE_MAX,
    ACCOUNT_PREFS_DOC_MAX,
    AccountPrefsBusy,
    AccountPrefsError,
    _account_key,
    account_prefs_get,
    account_prefs_path,
    account_prefs_update,
    create_app,
)
from tests.conftest import login_client, login_test_client

URL = "/api/account/prefs"


def _prefs_file(tmp_path, user="tester"):
    return paths.state_path(tmp_path, "account_prefs") / (_account_key(user) + ".json")


def _csrf(cli):
    return cli.get(URL).get_json()["csrf"]


def _post(cli, body, csrf=None):
    body = dict(body)
    body.setdefault("csrf", _csrf(cli) if csrf is None else csrf)
    return cli.post(URL, json=body)


# ---------------------------------------------------------------------------
# Own-account read / write
# ---------------------------------------------------------------------------

def test_get_starts_empty_and_hands_out_the_session_token(tmp_path):
    cli = login_client(tmp_path)
    r = cli.get(URL)
    assert r.status_code == 200
    d = r.get_json()
    assert d["prefs"] == {}
    assert d["csrf"], "the hook's first write needs the token the GET hands out"
    # a read never creates a file
    assert not _prefs_file(tmp_path).exists()


def test_set_roundtrip_lands_in_the_accounts_own_file(tmp_path):
    cli = login_client(tmp_path)
    r = _post(cli, {"set": {"guide.library": {"step": 2, "done": False},
                            "seen.whatsnew": "3.15.0", "unleash": True}})
    assert r.status_code == 200
    want = {"guide.library": {"step": 2, "done": False},
            "seen.whatsnew": "3.15.0", "unleash": True}
    assert r.get_json() == {"prefs": want}
    assert cli.get(URL).get_json()["prefs"] == want
    # on disk under the digest key, never the raw username, as valid JSON
    p = _prefs_file(tmp_path)
    assert json.loads(p.read_text(encoding="utf-8")) == want
    assert not (paths.state_path(tmp_path, "account_prefs") / "tester.json").exists()
    assert [x.name for x in p.parent.iterdir()] == [p.name], (
        "a temp file or lockfile was left behind: {}".format(list(p.parent.iterdir())))


def test_unset_removes_and_unset_of_an_absent_key_is_a_noop(tmp_path):
    cli = login_client(tmp_path)
    _post(cli, {"set": {"keep": 1, "drop": 2}})
    r = _post(cli, {"unset": ["drop", "never-existed"]})
    assert r.status_code == 200
    assert r.get_json()["prefs"] == {"keep": 1}


def test_set_and_unset_in_one_change(tmp_path):
    cli = login_client(tmp_path)
    _post(cli, {"set": {"a": 1, "b": 2}})
    r = _post(cli, {"set": {"c": [1, 2]}, "unset": ["a"]})
    assert r.get_json()["prefs"] == {"b": 2, "c": [1, 2]}


def test_set_overwrites_and_null_is_a_real_value(tmp_path):
    cli = login_client(tmp_path)
    _post(cli, {"set": {"goal.pinned": "a"}})
    r = _post(cli, {"set": {"goal.pinned": None}})
    assert r.get_json()["prefs"] == {"goal.pinned": None}


def test_a_change_that_alters_nothing_writes_nothing(tmp_path):
    cli = login_client(tmp_path)
    r = _post(cli, {"unset": ["not-there"]})
    assert r.status_code == 200 and r.get_json()["prefs"] == {}
    assert not _prefs_file(tmp_path).exists()


# ---------------------------------------------------------------------------
# Isolation: which account, and only that account
# ---------------------------------------------------------------------------

def test_one_account_cannot_see_or_clobber_anothers_prefs(tmp_path):
    app = create_app(tmp_path)
    alice = login_test_client(app, username="alice", password="a-real-test-password-1")
    bob = login_test_client(app, username="bob", password="a-real-test-password-2")

    assert _post(alice, {"set": {"guide.library": "alice"}}).status_code == 200
    assert bob.get(URL).get_json()["prefs"] == {}, "bob can read alice's document"

    _post(bob, {"set": {"guide.library": "bob"}})
    assert alice.get(URL).get_json()["prefs"] == {"guide.library": "alice"}, (
        "bob's same-named write overwrote alice's")
    assert bob.get(URL).get_json()["prefs"] == {"guide.library": "bob"}
    assert _prefs_file(tmp_path, "alice") != _prefs_file(tmp_path, "bob")


def test_the_body_can_never_name_an_account(tmp_path):
    """The account comes from the session. A body field naming one is refused outright
    rather than ignored, so a client can't even believe it worked."""
    app = create_app(tmp_path)
    alice = login_test_client(app, username="alice", password="a-real-test-password-1")
    bob = login_test_client(app, username="bob", password="a-real-test-password-2")
    _post(alice, {"set": {"x": "alice"}})
    for field in ("account", "user", "username"):
        r = _post(bob, {field: "alice", "set": {"x": "bob"}})
        assert r.status_code == 400, field
        assert "Unknown field" in r.get_json()["error"]
    assert alice.get(URL).get_json()["prefs"] == {"x": "alice"}
    assert bob.get(URL).get_json()["prefs"] == {}


def test_case_distinct_usernames_get_distinct_files(tmp_path):
    """Account identity is case-sensitive; NTFS is not. The digest key keeps "Nel" and
    "nel" apart on every filesystem (the B14 residual every per-account store shares)."""
    account_prefs_update(tmp_path, "Nel", set_={"k": "upper"})
    account_prefs_update(tmp_path, "nel", set_={"k": "lower"})
    assert account_prefs_get(tmp_path, "Nel") == {"k": "upper"}
    assert account_prefs_get(tmp_path, "nel") == {"k": "lower"}


# ---------------------------------------------------------------------------
# No web accounts configured / no session
# ---------------------------------------------------------------------------

def test_no_accounts_install_refuses_both_methods_and_writes_nothing(tmp_path):
    """With no web accounts, nothing past /login is reachable -- from loopback too (there
    is no localhost bypass). So the route never runs without a real session["user"]."""
    assert core.list_web_users() == []
    cli = create_app(tmp_path).test_client()
    r = cli.get(URL)
    assert r.status_code == 401 and r.get_json() == {"error": "authentication required"}
    r = cli.post(URL, json={"set": {"a": 1}})
    assert r.status_code == 401
    assert not (paths.state_path(tmp_path, "account_prefs")).exists()


def test_account_local_is_the_one_stable_key_for_a_sessionless_caller(tmp_path):
    p = account_prefs_path(tmp_path, ACCOUNT_LOCAL)
    assert p == paths.state_path(tmp_path, "account_prefs") / "_local.json"
    account_prefs_update(tmp_path, ACCOUNT_LOCAL, set_={"unleash": True})
    assert account_prefs_get(tmp_path, ACCOUNT_LOCAL) == {"unleash": True}
    assert json.loads(p.read_text(encoding="utf-8")) == {"unleash": True}


def test_a_user_named_local_does_not_reach_the_local_document(tmp_path):
    account_prefs_update(tmp_path, ACCOUNT_LOCAL, set_={"who": "local"})
    assert account_prefs_path(tmp_path, "_local") != account_prefs_path(tmp_path, ACCOUNT_LOCAL)
    assert account_prefs_get(tmp_path, "_local") == {}


@pytest.mark.parametrize("who", [None, "", "   ", 7, b"tester"])
def test_a_missing_account_never_falls_back_to_a_shared_file(tmp_path, who):
    with pytest.raises(ValueError):
        account_prefs_path(tmp_path, who)
    with pytest.raises(ValueError):
        account_prefs_get(tmp_path, who)
    with pytest.raises(ValueError):
        account_prefs_update(tmp_path, who, set_={"a": 1})
    assert not (paths.state_path(tmp_path, "account_prefs")).exists()


# ---------------------------------------------------------------------------
# CSRF (explicit-token class)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("token", ["", "not-the-token"])
def test_post_without_the_session_token_is_refused(tmp_path, token):
    cli = login_client(tmp_path)
    cli.get(URL)
    r = cli.post(URL, json={"set": {"a": 1}, "csrf": token})
    assert r.status_code == 400
    assert "session expired" in r.get_json()["error"]
    assert not _prefs_file(tmp_path).exists()


def test_post_with_no_token_field_is_refused(tmp_path):
    cli = login_client(tmp_path)
    r = cli.post(URL, json={"set": {"a": 1}})
    assert r.status_code == 400
    assert not _prefs_file(tmp_path).exists()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", [
    "Guide", "guide.Library", "1guide", "_guide", "guide..library", "guide.",
    ".guide", "guide library", "guide/../x", "gu:ide", "é", "a" * 65, "",
])
def test_bad_keys_are_refused_with_a_plain_message(tmp_path, key):
    cli = login_client(tmp_path)
    for body in ({"set": {key: 1}}, {"unset": [key]}):
        r = _post(cli, body)
        assert r.status_code == 400, (key, body)
        assert r.get_json()["error"]
    assert not _prefs_file(tmp_path).exists()


@pytest.mark.parametrize("key", ["a", "unleash", "guide.library", "seen.whatsnew",
                                 "seen.feat.great_library", "seen.feat.12",
                                 "gen.defaults.sdxl-1", "a" * 64])
def test_good_keys_are_accepted(tmp_path, key):
    cli = login_client(tmp_path)
    r = _post(cli, {"set": {key: True}})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["prefs"] == {key: True}


def test_non_string_unset_entries_are_refused(tmp_path):
    cli = login_client(tmp_path)
    assert _post(cli, {"unset": [1]}).status_code == 400


def test_one_bad_entry_refuses_the_whole_change(tmp_path):
    cli = login_client(tmp_path)
    _post(cli, {"set": {"keep": 1}})
    r = _post(cli, {"set": {"new": 2, "Bad": 3}})
    assert r.status_code == 400
    assert cli.get(URL).get_json()["prefs"] == {"keep": 1}


def test_nan_and_infinity_are_not_json(tmp_path):
    """Python's json parser accepts NaN; the browser's JSON.parse does not -- a stored NaN
    would break every later read of the document in the page."""
    cli = login_client(tmp_path)
    tok = _csrf(cli)
    for raw in ('{"csrf": "%s", "set": {"a": NaN}}' % tok,
                '{"csrf": "%s", "set": {"a": [1, Infinity]}}' % tok):
        r = cli.post(URL, data=raw, content_type="application/json")
        assert r.status_code == 400, raw
        assert "not plain JSON" in r.get_json()["error"]
    assert not _prefs_file(tmp_path).exists()


def test_accessor_refuses_values_that_are_not_json(tmp_path):
    for v in (object(), {1, 2}, float("nan"), b"bytes"):
        with pytest.raises(AccountPrefsError):
            account_prefs_update(tmp_path, "tester", set_={"a": v})


def test_accessor_stores_values_exactly_as_json_will(tmp_path):
    out = account_prefs_update(tmp_path, "tester", set_={"t": (1, 2), "n": {"x": [None]}})
    assert out == {"t": [1, 2], "n": {"x": [None]}}
    assert account_prefs_get(tmp_path, "tester") == out


@pytest.mark.parametrize("body", [
    {"set": {"a": 1}, "extra": 1},
    {},
    {"set": None},
    {"set": [["a", 1]]},
    {"set": "a"},
    {"unset": "a"},
    {"unset": {"a": 1}},
    {"set": {"a": 1}, "unset": ["a"]},
])
def test_unknown_or_malformed_shapes_are_refused(tmp_path, body):
    cli = login_client(tmp_path)
    r = _post(cli, body)
    assert r.status_code == 400, body
    assert r.get_json()["error"]
    assert not _prefs_file(tmp_path).exists()


def test_a_non_object_body_is_refused(tmp_path):
    cli = login_client(tmp_path)
    for raw in ('[1, 2]', '"set"', 'null', 'not json'):
        r = cli.post(URL, data=raw, content_type="application/json")
        assert r.status_code == 400, raw
        assert r.get_json()["error"]


# ---------------------------------------------------------------------------
# Size caps
# ---------------------------------------------------------------------------

def test_value_cap_is_on_the_values_json_bytes(tmp_path):
    cli = login_client(tmp_path)
    at_limit = "x" * (ACCOUNT_PREF_VALUE_MAX - 2)     # + 2 quote bytes == the limit
    assert _post(cli, {"set": {"big": at_limit}}).status_code == 200
    r = _post(cli, {"set": {"big": at_limit + "x"}})
    assert r.status_code == 400
    assert "too large" in r.get_json()["error"]
    assert cli.get(URL).get_json()["prefs"]["big"] == at_limit


def test_value_cap_counts_utf8_bytes_not_characters(tmp_path):
    with pytest.raises(AccountPrefsError):
        # 3 bytes per character in UTF-8: well under the limit in characters
        account_prefs_update(tmp_path, "tester",
                             set_={"a": "月" * (ACCOUNT_PREF_VALUE_MAX // 3 + 1)})


def test_document_cap_refuses_growth_past_it(tmp_path):
    chunk = "x" * (ACCOUNT_PREF_VALUE_MAX - 100)
    n = 0
    with pytest.raises(AccountPrefsError, match="too large"):
        while n < 100:
            account_prefs_update(tmp_path, "tester", set_={"k%d" % n: chunk})
            n += 1
    assert 10 < n < 100
    p = account_prefs_path(tmp_path, "tester")
    assert p.stat().st_size <= ACCOUNT_PREFS_DOC_MAX
    assert len(account_prefs_get(tmp_path, "tester")) == n, "the refused write changed the file"


def test_an_over_cap_document_can_still_shrink(tmp_path):
    """A hand-edited file past the cap must not wedge the account: a change that only
    removes keys is always accepted."""
    p = account_prefs_path(tmp_path, "tester")
    p.parent.mkdir(parents=True)
    big = {"k%d" % i: "x" * 60000 for i in range(20)}
    p.write_text(json.dumps(big), encoding="utf-8")
    assert p.stat().st_size > ACCOUNT_PREFS_DOC_MAX
    with pytest.raises(AccountPrefsError):
        account_prefs_update(tmp_path, "tester", set_={"one.more": 1})
    out = account_prefs_update(tmp_path, "tester", unset=["k%d" % i for i in range(15)])
    assert sorted(out) == ["k15", "k16", "k17", "k18", "k19"]


def test_an_oversized_request_is_refused_before_parsing(tmp_path):
    cli = login_client(tmp_path)
    tok = _csrf(cli)
    raw = json.dumps({"csrf": tok, "set": {"a": "x" * (2 * ACCOUNT_PREFS_DOC_MAX + 10)}})
    r = cli.post(URL, data=raw, content_type="application/json")
    assert r.status_code == 400
    assert not _prefs_file(tmp_path).exists()


# ---------------------------------------------------------------------------
# Corrupt and unreadable files
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("junk", [b"{not json", b"[1, 2, 3]", b'"a string"',
                                  b"\xff\xfe\x00garbage", b""])
def test_a_corrupt_file_reads_as_empty_and_is_kept_not_overwritten(tmp_path, junk):
    cli = login_client(tmp_path)
    p = _prefs_file(tmp_path)
    p.parent.mkdir(parents=True)
    p.write_bytes(junk)

    assert cli.get(URL).get_json()["prefs"] == {}
    assert p.read_bytes() == junk, "a READ must never touch the file"

    r = _post(cli, {"set": {"a": 1}})
    assert r.status_code == 200
    assert r.get_json()["prefs"] == {"a": 1}
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}
    kept = list(p.parent.glob(p.stem + ".corrupt-*.json"))
    assert len(kept) == 1, "the corrupt file was not set aside"
    assert kept[0].read_bytes() == junk


def test_two_corruptions_in_one_second_keep_both_copies(tmp_path, monkeypatch):
    monkeypatch.setattr(g.time, "strftime", lambda fmt, t=None: "20260928T000000Z")
    p = account_prefs_path(tmp_path, "tester")
    p.parent.mkdir(parents=True)
    for junk in (b"{one", b"{two"):
        p.write_bytes(junk)
        account_prefs_update(tmp_path, "tester", set_={"a": 1})
    kept = sorted(x.read_bytes() for x in p.parent.glob(p.stem + ".corrupt-*.json"))
    assert kept == [b"{one", b"{two"]


def test_an_unreadable_file_reads_empty_but_is_never_written_over(tmp_path, monkeypatch):
    cli = login_client(tmp_path)
    _post(cli, {"set": {"a": 1}})
    p = _prefs_file(tmp_path)
    before = p.read_bytes()
    real = type(p).read_bytes

    def _locked(self):
        if self == p:
            raise PermissionError(13, "sharing violation")
        return real(self)
    monkeypatch.setattr(type(p), "read_bytes", _locked)

    assert cli.get(URL).get_json()["prefs"] == {}
    r = _post(cli, {"set": {"b": 2}})
    assert r.status_code == 500
    assert "Could not save" in r.get_json()["error"]
    monkeypatch.undo()
    assert p.read_bytes() == before


# ---------------------------------------------------------------------------
# Atomicity and locking
# ---------------------------------------------------------------------------

def test_a_failed_replace_leaves_the_old_document_and_no_temp_file(tmp_path, monkeypatch):
    cli = login_client(tmp_path)
    _post(cli, {"set": {"a": 1}})
    p = _prefs_file(tmp_path)
    before = p.read_bytes()

    def _boom(tmp, dest, *a, **k):
        raise PermissionError(32, "the file is in use")
    monkeypatch.setattr(core, "_atomic_replace", _boom)

    r = _post(cli, {"set": {"b": 2}})
    assert r.status_code == 500
    assert p.read_bytes() == before
    assert sorted(x.name for x in p.parent.iterdir()) == [p.name], (
        "a temp file or the lockfile survived the failed write")


def test_concurrent_writers_lose_no_update(tmp_path):
    errors = []

    def _writer(i):
        try:
            for j in range(10):
                account_prefs_update(tmp_path, "tester", set_={"w%d.n%d" % (i, j): j})
        except Exception as e:     # surfaced by the assertion below
            errors.append(e)

    threads = [threading.Thread(target=_writer, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(account_prefs_get(tmp_path, "tester")) == 60


def _short_wait(monkeypatch):
    """The real lockfile, with a wait short enough that a refusal costs no test time."""
    real = g._excl_lockfile
    monkeypatch.setattr(g, "_excl_lockfile",
                        lambda lock, wait_s=2.0, stale_s=10.0: real(lock, 0.05, stale_s))


def test_a_lock_held_by_another_process_refuses_the_write(tmp_path, monkeypatch):
    _short_wait(monkeypatch)
    cli = login_client(tmp_path)
    p = _prefs_file(tmp_path)
    p.parent.mkdir(parents=True)
    lock = p.with_suffix(".lock")
    lock.write_text("", encoding="utf-8")        # a live writer elsewhere

    with pytest.raises(AccountPrefsBusy):
        account_prefs_update(tmp_path, "tester", set_={"a": 1})
    r = _post(cli, {"set": {"a": 1}})
    assert r.status_code == 503
    assert not p.exists()
    assert lock.exists(), "someone else's lock must not be removed"


def test_a_stale_lock_is_taken_over(tmp_path, monkeypatch):
    _short_wait(monkeypatch)
    p = account_prefs_path(tmp_path, "tester")
    p.parent.mkdir(parents=True)
    lock = p.with_suffix(".lock")
    lock.write_text("", encoding="utf-8")
    old = time.time() - 60
    os.utime(lock, (old, old))                   # a crashed writer's

    assert account_prefs_update(tmp_path, "tester", set_={"a": 1}) == {"a": 1}
    assert not lock.exists()
