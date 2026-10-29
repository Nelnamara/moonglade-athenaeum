"""Auth simplification: no operation needs a saved hash and USER_ID auto-resolves from the
API key, so setup needs only PIXAI_API_KEY."""
from moonglade import backup as core


def test_no_saved_hash_is_left_to_configure():
    # Every op we rely on works without any config.json. (The history feed has no saved hash
    # since #89, task detail and model detail since #91, the whole-task delete and the Mirror's
    # renewal since #92: each is a full document or a /v2 REST route.)
    for retired in ("PERSISTED_QUERY_HASH", "TASK_DETAIL_HASH", "MODEL_DETAIL_HASH",
                    "DELETE_TASK_HASH", "REFRESH_TOKEN_HASH"):
        assert not hasattr(core, retired), retired


def test_resolve_user_id_from_me(monkeypatch):
    monkeypatch.setattr(core, "gql_adhoc",
                        lambda sess, q, v=None: {"me": {"id": "999"}})
    assert core.resolve_user_id(object()) == "999"


def test_resolve_user_id_raises_when_no_id(monkeypatch):
    monkeypatch.setattr(core, "gql_adhoc", lambda sess, q, v=None: {"me": {}})
    try:
        core.resolve_user_id(object())
    except core.PixAIError:
        return
    assert False, "expected PixAIError when me returns no id"
