"""The shared task-poll helper (_poll_task_status) used by generate / video / edit.
Mocked -- no live network, no sleeping (completed/failed return or raise before any
sleep; timeout=0 never enters the loop)."""
import pytest

import pixai_gallery_backup as core


def _one_poll_then_timeout(monkeypatch, task):
    """Let _poll_task_status observe `task` exactly once, then hit its deadline.

    A bare timeout=0 never enters the loop at all, so the poller observes NOTHING -- which
    is a different case from 'observed it queued and unstarted' and must not be conflated
    (see _never_dispatched). The fake clock yields start, one in-loop check, then a value
    past the deadline. Nothing sleeps."""
    monkeypatch.setattr(core, "gql_adhoc", lambda *a, **k: {"task": task})
    monkeypatch.setattr(core.time, "sleep", lambda *_a, **_k: None)
    ticks = iter([0, 0])
    monkeypatch.setattr(core.time, "time", lambda: next(ticks, 10_000))


def test_poll_returns_paid_credit_and_prints_cost(monkeypatch, capsys):
    monkeypatch.setattr(core, "gql_adhoc",
                        lambda *a, **k: {"task": {"status": "completed", "paidCredit": 27500}})
    paid = core._poll_task_status(object(), "t1", 300, label="video", fail_noun="video generation")
    assert paid == 27500
    assert "actual cost: 27,500 credits" in capsys.readouterr().out


def test_poll_completed_without_cost_returns_none(monkeypatch, capsys):
    monkeypatch.setattr(core, "gql_adhoc", lambda *a, **k: {"task": {"status": "succeeded"}})
    paid = core._poll_task_status(object(), "t2", 300, label="generate", fail_noun="generation")
    assert paid is None
    assert "actual cost" not in capsys.readouterr().out


def test_poll_raises_on_failure_with_noun(monkeypatch):
    monkeypatch.setattr(core, "gql_adhoc", lambda *a, **k: {"task": {"status": "failed"}})
    with pytest.raises(core.PixAIError) as e:
        core._poll_task_status(object(), "t3", 300, label="edit", fail_noun="edit")
    assert "edit ended with status: failed" in str(e.value)


def test_poll_raises_on_timeout(monkeypatch):
    """Timeout must NOT read as task failure: the task keeps running on PixAI, so the
    message says so and gives the free --task-id recovery path."""
    monkeypatch.setattr(core, "gql_adhoc", lambda *a, **k: {"task": {"status": "running"}})
    with pytest.raises(core.PixAIError) as e:
        core._poll_task_status(object(), "t4", 0, label="generate", fail_noun="generation")
    msg = str(e.value)
    assert "STILL RUNNING" in msg and "--task-id t4" in msg


# ---- the silent-death bug: a task PixAI accepts, never starts, and reaps at ~60 min ----

def test_status_query_asks_for_startedAt_and_outputs():
    """The two fields that tell a never-dispatched task apart from a running one, and
    carry PixAI's own cancellation reason. Without them in the query, every guard below
    is dead code that can only ever see status."""
    assert "startedAt" in core._GEN_STATUS, "_GEN_STATUS must select startedAt"
    assert "outputs" in core._GEN_STATUS, "_GEN_STATUS must select outputs"


def test_poll_cancelled_surfaces_pixai_own_reason(monkeypatch):
    """PixAI reaps an undispatched task with outputs={"reason": "waiting timeout"}. The
    owner hit this five times across four days and never once saw that string -- the
    error said only 'cancelled', which reads like HE cancelled something."""
    monkeypatch.setattr(core, "gql_adhoc", lambda *a, **k: {"task": {
        "status": "cancelled", "startedAt": None, "outputs": {"reason": "waiting timeout"}}})
    with pytest.raises(core.PixAIError) as e:
        core._poll_task_status(object(), "t5", 300, label="enhance", fail_noun="enhance")
    msg = str(e.value)
    assert "waiting timeout" in msg, "PixAI's own reason must reach the user: " + msg


def test_poll_timeout_on_never_started_task_does_not_claim_it_is_running(monkeypatch):
    """THE bug. A task sitting in `waiting` with startedAt=None was never dispatched, so
    'the task is STILL RUNNING on PixAI' is false, and '--task-id' recovery will never
    produce anything. Telling the owner to wait for a task no worker ever picked up is
    what let five failures pass unnoticed across four days."""
    _one_poll_then_timeout(monkeypatch, {"status": "waiting", "startedAt": None})
    with pytest.raises(core.PixAIError) as e:
        core._poll_task_status(object(), "t6", 60, label="enhance", fail_noun="enhance")
    msg = str(e.value)
    assert "STILL RUNNING" not in msg, "claimed a never-started task is running: " + msg
    assert "never started" in msg.lower(), "must say it was never dispatched: " + msg
    assert "refund" in msg.lower(), "must mention the ~60min reap+refund: " + msg


def test_poll_timeout_on_a_genuinely_running_task_still_says_running(monkeypatch):
    """The honest-timeout path must survive the fix: a task that really is running keeps
    the reassuring 'nothing is lost, recover it free' message."""
    _one_poll_then_timeout(monkeypatch, {"status": "running",
                                        "startedAt": "2026-07-25T05:00:00.000Z"})
    with pytest.raises(core.PixAIError) as e:
        core._poll_task_status(object(), "t7", 60, label="generate", fail_noun="generation")
    msg = str(e.value)
    assert "STILL RUNNING" in msg and "--task-id t7" in msg


def test_poll_timeout_without_ever_observing_the_task_stays_reassuring(monkeypatch):
    """'Never observed' is NOT 'never dispatched'. With a zero timeout the loop never
    runs, so the poller has no evidence either way -- it must fall back to the reassuring
    recover-it-free message rather than confidently declaring a task dead it never looked
    at. This is the same class of error as the message the fix above removes, so it gets
    its own guard."""
    monkeypatch.setattr(core, "gql_adhoc", lambda *a, **k: {"task": {"status": "running"}})
    with pytest.raises(core.PixAIError) as e:
        core._poll_task_status(object(), "t8", 0, label="generate", fail_noun="generation")
    msg = str(e.value)
    assert "STILL RUNNING" in msg and "never started" not in msg.lower()


# ---- PixAI states a failure under several different keys, not just `reason` ----

def test_failure_reason_is_read_from_every_key_pixai_actually_uses(monkeypatch):
    """Owner's three hand-fix failures 2026-07-25 reported "failed" with no explanation, and
    the diagnosis was written up as model flakiness. Both were wrong: PixAI HAD explained
    itself, under keys we never read. The real GraphQL outputs were
    {"finish_reason": "ERROR", "modelResponse": [], "failureMessage": "Provider refused to
    answer", "failure_reason": "PROVIDER_REFUSE_ANSWER"} -- a CONTENT REFUSAL, which is
    fixable by rewording, and completely different advice from "their model errored."

    We looked only for `outputs.reason`, which a *cancelled* task uses ("waiting timeout"),
    so a genuinely explained failure read as unexplained. Prefer the human-readable message,
    fall back to the enum, and keep `reason` working."""
    outs = {"finish_reason": "ERROR", "modelResponse": [],
            "failureMessage": "Provider refused to answer",
            "failure_reason": "PROVIDER_REFUSE_ANSWER"}
    got = core._task_failure_reason(outs)
    assert got, "no reason extracted from a payload that plainly contains one"
    assert "refused" in got.lower(), "did not surface the human message: {!r}".format(got)

    # the cancelled-task shape must keep working
    assert core._task_failure_reason({"reason": "waiting timeout"}) == "waiting timeout"
    # and a genuinely empty payload stays empty rather than inventing something
    assert core._task_failure_reason({"mediaIds": [], "mediaUrls": []}) == ""
    assert core._task_failure_reason(None) == ""


def test_a_content_refusal_tells_the_user_what_to_do_about_it(monkeypatch):
    """PROVIDER_REFUSE_ANSWER is the moderator declining the content. That is not a bug to
    debug, it is a prompt to reword -- and saying so turns a dead end into a next step."""
    msg = core.describe_failure("failed", "Provider refused to answer", started=True)
    assert "refused" in msg.lower()
    low = msg.lower()
    assert "word" in low or "prompt" in low, \
        "a refusal should point at rewording rather than looking like a system fault: " + msg


def test_generation_status_surfaces_a_provider_refusal(monkeypatch):
    """End of the chain: the status dict every caller reads must carry it."""
    monkeypatch.setattr(core, "gql_adhoc", lambda *a, **k: {"task": {
        "status": "failed", "startedAt": "2026-07-25T15:44:53Z",
        "outputs": {"failureMessage": "Provider refused to answer",
                    "failure_reason": "PROVIDER_REFUSE_ANSWER"}}})
    st = core.generation_status(object(), "t9")
    assert st["phase"] == "failed"
    assert "refused" in (st.get("reason") or "").lower(), \
        "generation_status dropped the refusal: {!r}".format(st)


def test_account_query_selects_no_bare_connection_field():
    """SHIPPED BROKEN 2026-07-25 and caught only when the owner noticed his credits chip
    reading 0/0. `roles` was added to _ACCOUNT_QUERY as a bare field, but it is a
    `RoleConnection`, so PixAI rejects the whole document at validation:

        Field "roles" of type "RoleConnection" must have a selection of subfields

    A GraphQL validation error fails the ENTIRE query, so account_info() returned nothing and
    every consumer silently lost its data at once: the credits chip, the membership-derived
    LoRA cap, the --account dashboard, and -- worst -- the first-run setup wizard, which calls
    it with raise_on_error=True and would therefore reject a perfectly valid API key on a
    fresh install.

    Only a live call can prove this query valid, which is exactly how it shipped: it was
    written in a worktree with no credentials, so it was never run once. This guard is the
    cheap standing substitute -- it pins the fields the app actually depends on, and refuses
    a bare `roles` by name.

    Bite: re-add `roles` on its own line and this fails."""
    q = core._ACCOUNT_QUERY
    for needed in ("quotaAmount", "membership", "privilege", "subscription"):
        assert needed in q, "account query no longer requests {!r}".format(needed)
    import re
    # a bare selection = the token alone on its line, with no { ... } subfields
    for line in q.split("\n"):
        bare = line.strip()
        assert bare != "roles", (
            "`roles` is selected bare again. It is a RoleConnection and PixAI rejects the "
            "whole query for it, taking credits, membership, the LoRA cap and the setup "
            "wizard's key validation down together. Query it separately with subfields, or "
            "not at all.")


# ---- per-image cloud delete: deleteBatchMedia via updateGenerationTask ----

def test_delete_one_image_sends_the_right_mutation(monkeypatch):
    """Deletes ONE image from a task's batch, instead of the whole task. Signature was
    discovered by validation-error probing with nothing executed:
    `updateGenerationTask(id: ID!, input: UpdateGenerationTaskInput!)` carrying
    `{deleteBatchMedia: {mediaId}}`."""
    seen = {}
    monkeypatch.setattr(core, "gql_adhoc",
                        lambda s, q, v=None, retries=3: seen.update(q=q, v=v or {},
                                                                    retries=retries) or
                        {"updateGenerationTask": {"id": "T1"}})
    core.delete_batch_media_gql(object(), "T1", "M9")
    # gql_adhoc defaults to retries=3 and re-POSTs on a RequestException or a 429/5xx. A
    # read timeout can arrive AFTER PixAI has processed the delete, so the default would
    # re-fire a destructive mutation against a batch that has already changed. The
    # docstring promised SINGLE ATTEMPT from the day this was written; the call did not
    # pass retries=0 until 2026-07-25, so the promise was prose only.
    assert seen["retries"] == 0, "a destructive mutation must never be retried"
    assert "updateGenerationTask" in seen["q"]
    assert seen["v"]["id"] == "T1"
    assert seen["v"]["input"] == {"deleteBatchMedia": {"mediaId": "M9"}}, \
        "wrong input shape: {!r}".format(seen["v"])
    assert "UpdateGenerationTaskInput" in seen["q"], \
        "the variable must be typed, or the server rejects the document"


def test_delete_one_image_honors_read_only(monkeypatch):
    """READ_ONLY is a contract the Trust & Safety page makes to users: every path that
    mutates the account checks it BEFORE the network call. A new destructive path that
    forgot this would be a silent hole in that promise, which is exactly why the existing
    delete/generate paths each call it."""
    monkeypatch.setattr(core, "_check_read_only",
                        lambda *a, **k: (_ for _ in ()).throw(core.PixAIError("read-only")))
    called = []
    monkeypatch.setattr(core, "gql_adhoc", lambda *a, **k: called.append(1))
    with pytest.raises(core.PixAIError):
        core.delete_batch_media_gql(object(), "T1", "M9")
    assert not called, "the network call fired despite READ_ONLY"


def test_delete_one_image_is_single_attempt(monkeypatch):
    """Deliberately NO retry loop, mirroring delete_task_gql: a flaky network must never be
    able to fire a destructive delete twice."""
    calls = []
    def boom(*a, **k):
        calls.append(1)
        raise core.PixAIError("network blip")
    monkeypatch.setattr(core, "gql_adhoc", boom)
    with pytest.raises(core.PixAIError):
        core.delete_batch_media_gql(object(), "T1", "M9")
    assert len(calls) == 1, "retried a destructive delete {} times".format(len(calls))


def test_delete_one_image_requires_both_ids(monkeypatch):
    """A blank media id would be an update with nothing to delete; a blank task id has no
    batch to delete from. Refuse both rather than sending a malformed destructive call."""
    monkeypatch.setattr(core, "gql_adhoc", lambda *a, **k: {})
    for tid, mid in (("", "M9"), ("T1", ""), ("", "")):
        with pytest.raises(core.PixAIError):
            core.delete_batch_media_gql(object(), tid, mid)
