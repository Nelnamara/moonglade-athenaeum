"""Which delete PixAI accepts for one image, decided before anything is sent.

The gallery's single-image "Delete from PixAI" always sent `deleteBatchMedia`. PixAI accepts
that mutation ONLY for an image that is one of several still-live members of a task's
`outputs.batch[]`. For a task that made a single image (no `batch` key at all -- the picture
is `outputs.mediaId`), and for the LAST live member of a batch, PixAI answers 403 "task
outputs does not include any media with mediaId"; their own site sends `deleteGenerationTask`
for those two cases instead. Wrong since v2.5.0, and not a change on their side.

`route_image_delete` is the decision on its own: a task record in, a plan out, no session, no
network, nothing deleted. Every row below is one shape the live read can come back as. The
shapes are synthetic (fake ids) but their KEYS are the ones real payloads carry, read off the
owner's own tasks during the read-only probes on 2026-09-06:

  * a batch member is `{extra, mediaId, seed}`, and gains `deletedAt` (an ISO string) once it
    is deleted -- untouched members carry no such key at all;
  * `outputs.mediaId` on a batch task is the combined preview picture, NOT one of the batch's
    images (two disjoint sets);
  * a single-image task has no `batch`, and a chat/edit task's outputs are
    `{mediaId, modelResponse}`;
  * a video task's clips hang off `outputs.videos[]`.

The task's `updatedAt` does NOT move when one image of a batch is deleted, so nothing here
may key on it.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import moonglade_backup as core  # noqa: E402

DELETED_AT = "2026-09-06T11:22:33.000Z"


def _member(mid, deleted=False):
    entry = {"extra": {}, "mediaId": mid, "seed": "111"}
    if deleted:
        entry["deletedAt"] = DELETED_AT
    return entry


def _batch_task(*flags):
    """A batch task whose members are m0..mN. `flags` says which are already deleted."""
    return {
        "id": "TASK-BATCH",
        "status": "completed",
        "outputs": {
            "mediaId": "GRID-COMBINED",          # the combined preview, not a member
            "seed": "111",
            "width": 1024, "height": 1536,
            "batch": [_member("m{}".format(i), d) for i, d in enumerate(flags)],
        },
    }


def _lone_task():
    return {"id": "TASK-LONE", "status": "completed",
            "outputs": {"mediaId": "solo1", "seed": "222", "width": 768, "height": 1152}}


def _chat_task():
    """An edit/chat task: one output plus the model's reply, and no batch array."""
    return {"id": "TASK-CHAT", "status": "completed",
            "outputs": {"mediaId": "edited1", "modelResponse": [{"text": "here you go"}]}}


def _video_task():
    return {"id": "TASK-VIDEO", "status": "completed",
            "outputs": {"baseMediaId": "poster1", "mediaId": "poster1",
                        "width": 720, "height": 1280,
                        "videos": [{"extra": {}, "mediaId": "clip1", "seed": "333"}]}}


# ---------------------------------------------------------------------------
# The two plans PixAI actually accepts
# ---------------------------------------------------------------------------

def test_a_live_member_with_live_siblings_goes_per_image():
    """The only case `deleteBatchMedia` was ever right for: after this delete the task still
    has outputs, so PixAI keeps the record and drops one image out of it."""
    plan, reason, live_siblings, entry = core.route_image_delete(
        _batch_task(False, False, False, False), "m1")
    assert plan == "per-image"
    assert live_siblings == 3, "the three untouched siblings were miscounted"
    assert entry["mediaId"] == "m1", "the wrong batch entry came back"
    assert reason


def test_the_last_live_member_goes_whole_task():
    """Three of four already deleted: deleting the fourth would leave the task with no
    outputs at all, which is the 403 case. PixAI's own site sends the whole-task mutation
    here, and so must this."""
    plan, reason, live_siblings, entry = core.route_image_delete(
        _batch_task(True, True, False, True), "m2")
    assert plan == "whole-task"
    assert live_siblings == 0, "it thought a sibling would survive this delete"
    assert entry["mediaId"] == "m2"


def test_it_counts_live_members_not_array_positions():
    """The trap this whole fix exists to avoid. `outputs.batch` keeps its deleted members --
    they stay in the array with a `deletedAt` -- so array length and array position say
    nothing about how many images are still there. Position 0 of a four-entry array is the
    LAST live image here."""
    plan, _reason, live_siblings, _entry = core.route_image_delete(
        _batch_task(False, True, True, True), "m0")
    assert (plan, live_siblings) == ("whole-task", 0), (
        "routed off the array rather than off how many images are still live")


def test_a_task_that_made_one_image_goes_whole_task():
    """No `batch` key at all: the picture IS `outputs.mediaId`, and `deleteBatchMedia` has no
    batch to delete from -- PixAI answers 403."""
    plan, reason, live_siblings, entry = core.route_image_delete(_lone_task(), "solo1")
    assert plan == "whole-task"
    assert live_siblings == 0
    assert entry is None, "a task with no batch has no batch entry to report"
    assert reason


def test_an_edit_or_chat_task_goes_whole_task():
    """Same shape rule, different surface: a chat/edit task's outputs are
    `{mediaId, modelResponse}` -- one image, no batch."""
    plan, _reason, _live, _entry = core.route_image_delete(_chat_task(), "edited1")
    assert plan == "whole-task"


# ---------------------------------------------------------------------------
# The refusals -- every one of these must send NOTHING
# ---------------------------------------------------------------------------

def test_an_already_deleted_member_is_refused():
    """Its entry carries `deletedAt`, so PixAI has already dropped it. Re-sending either
    mutation would either fail or, worse, take the whole task with it."""
    plan, reason, _live, entry = core.route_image_delete(
        _batch_task(True, True, False, True), "m0")
    assert plan == "refuse"
    assert "already deleted" in reason.lower(), reason
    assert entry is not None and entry.get("deletedAt") == DELETED_AT, (
        "the caller needs the deletedAt stamp to mark its own catalog row")


def test_a_video_task_is_refused():
    """Video clips hang off `outputs.videos[]` and neither mutation is known to be the right
    one for them. Refusing beats guessing a destructive call."""
    plan, reason, _live, _entry = core.route_image_delete(_video_task(), "clip1")
    assert plan == "refuse"
    assert "video" in reason.lower(), reason


def test_a_media_id_the_task_does_not_list_is_refused():
    """A stale catalog row, or an id that rotated. Nothing on PixAI's side matches it, so
    there is nothing to aim a delete at."""
    plan, reason, _live, entry = core.route_image_delete(
        _batch_task(False, False, False, False), "not-in-this-task")
    assert plan == "refuse"
    assert "no longer lists" in reason.lower(), reason
    assert entry is None


def test_a_task_that_could_not_be_read_is_refused():
    """The fail-safe direction. `task_detail_gql` fails SOFT to None on a network blip, and
    the answer to "I don't know what this task looks like" must never be the whole-task
    mutation -- that would delete a whole generation off a dropped packet."""
    plan, reason, _live, _entry = core.route_image_delete(None, "m1")
    assert plan == "refuse"
    assert "nothing was deleted" in reason.lower(), reason


def test_the_combined_preview_picture_is_refused():
    """`outputs.mediaId` on a batch task is the combined preview PixAI renders of the whole
    batch; the individual images live in `outputs.batch[]` and the two sets never overlap.
    Treating the preview as "the lone image" would route a four-image batch to the whole-task
    delete."""
    plan, reason, _live, entry = core.route_image_delete(
        _batch_task(False, False, False, False), "GRID-COMBINED")
    assert plan == "refuse"
    assert "preview" in reason.lower(), reason
    assert entry is None


def test_a_blank_media_id_is_refused():
    """A delete with nothing to aim at."""
    assert core.route_image_delete(_lone_task(), "")[0] == "refuse"


# ---------------------------------------------------------------------------
# Properties of the decision itself
# ---------------------------------------------------------------------------

def test_the_router_touches_no_session_and_no_clock():
    """Pure by construction: it takes the task record PixAI already answered with, so it can
    be exercised over every shape above without a socket. A router that fetched anything
    could not be tested against the shapes that matter."""
    import inspect
    src = inspect.getsource(core.route_image_delete)
    for forbidden in ("session", "gql", "requests.", "task_detail_gql"):
        assert forbidden not in src, (
            "route_image_delete reaches for {!r} -- the decision must be pure".format(
                forbidden))


def test_it_never_reads_updated_at():
    """Probed 2026-09-06: a per-image delete does NOT move the task's `updatedAt`. Anything
    keyed on it would silently decide the wrong way."""
    import inspect
    assert "updatedAt" not in inspect.getsource(core.route_image_delete)


# ---------------------------------------------------------------------------
# The delete that USES the decision: read the live task, then fire one branch
# ---------------------------------------------------------------------------

class _Double:
    """Stands in for the PixAI client on both roads a delete can take: `persisted` answers
    the getTaskById read, `mutate` takes the per-image mutation, `post` takes the whole-task
    one (which hand-rolls its own request). Every call is recorded, so "nothing was sent"
    is checkable rather than assumed."""

    _is_pixai_client = True

    def __init__(self, task):
        self.task = task
        self.reads, self.mutations, self.posts = [], [], []

    def persisted(self, op_name, variables=None, sha256=None, retries=4, **kw):
        self.reads.append((op_name, dict(variables or {})))
        return {"task": self.task}

    def mutate(self, document, variables=None):
        self.mutations.append((document, dict(variables or {})))
        return {"updateGenerationTask": {"id": "TASK-BATCH"}}

    def post(self, url, params=None, json=None, timeout=None, **kw):
        self.posts.append(dict(json or {}))

        class _Resp:
            status_code = 200
            text = "{}"

            @staticmethod
            def json():
                return {"data": {"deleteGenerationTask": None}}

        return _Resp()

    def sent(self):
        return len(self.mutations) + len(self.posts)


def test_the_plan_reads_the_live_task_and_sends_nothing():
    """The preview half of the two-phase delete. It has to READ -- the local catalog cannot
    know which of a batch's members PixAI still has -- and it must send no mutation at all,
    because the dialog it feeds has not been agreed to yet."""
    dbl = _Double(_batch_task(False, True, False, False))
    plan = core.plan_image_delete(dbl, "TASK-BATCH", "m0")
    assert plan.plan == "per-image"
    assert plan.live_siblings == 2, "the deleted member was counted as a survivor"
    assert dbl.reads and dbl.reads[0][0] == "getTaskById"
    assert dbl.sent() == 0, "the preview sent a mutation"


def test_the_plan_reports_what_pixai_already_deleted():
    """The whole-task branch purges the task's local rows, and the local copy of a member
    PixAI already dropped is the only copy left anywhere -- so the plan has to name those
    rows before anything is quarantined."""
    dbl = _Double(_batch_task(True, True, False, True))
    plan = core.plan_image_delete(dbl, "TASK-BATCH", "m2")
    assert plan.plan == "whole-task"
    assert sorted(plan.keep_media) == ["m0", "m1", "m3"]


def test_the_plan_carries_the_deleted_stamp_of_an_already_deleted_image():
    """So the caller can mark its own catalog row with the date PixAI dropped it, instead of
    leaving a row that looks live forever."""
    plan = core.plan_image_delete(_Double(_batch_task(True, False)), "TASK-BATCH", "m0")
    assert plan.plan == "refuse"
    assert plan.cloud_deleted_at == DELETED_AT


def test_a_read_that_fails_plans_a_refusal_and_sends_nothing(monkeypatch):
    """task_detail_gql fails SOFT to None on a network blip. The delete must come to a stop
    there and say so -- never fall through to a mutation on a task it could not see."""
    monkeypatch.setattr(core, "task_detail_gql", lambda *a, **k: None)
    monkeypatch.setattr(core, "READ_ONLY", False)
    dbl = _Double(None)
    plan = core.delete_image_routed(dbl, "TASK-BATCH", "m0")
    assert plan.plan == "refuse"
    assert "nothing was deleted" in plan.reason.lower()
    assert dbl.sent() == 0, "it deleted something after a failed read"


def test_the_per_image_branch_sends_delete_batch_media(monkeypatch):
    monkeypatch.setattr(core, "READ_ONLY", False)
    dbl = _Double(_batch_task(False, False, False))
    plan = core.delete_image_routed(dbl, "TASK-BATCH", "m1")
    assert plan.plan == "per-image"
    assert len(dbl.mutations) == 1 and not dbl.posts
    doc, variables = dbl.mutations[0]
    assert "updateGenerationTask" in doc
    assert variables["input"] == {"deleteBatchMedia": {"mediaId": "m1"}}


def test_the_whole_task_branch_sends_delete_generation_task(monkeypatch):
    """The case that was broken: a task that made one image. The old code sent
    deleteBatchMedia here and PixAI answered 403."""
    monkeypatch.setattr(core, "READ_ONLY", False)
    dbl = _Double(_lone_task())
    plan = core.delete_image_routed(dbl, "TASK-LONE", "solo1")
    assert plan.plan == "whole-task"
    assert len(dbl.posts) == 1 and not dbl.mutations, "the per-image mutation fired anyway"
    assert dbl.posts[0]["variables"] == {"taskId": "TASK-LONE"}


def test_a_stale_confirmed_plan_is_refused(monkeypatch):
    """The dialog said one thing, the task changed underneath it, and the confirm arrives for
    a plan that is no longer true. Sending the old plan would delete a whole generation the
    user was told would keep three images."""
    monkeypatch.setattr(core, "READ_ONLY", False)
    dbl = _Double(_batch_task(True, False, True, True))     # only m1 is live now
    plan = core.delete_image_routed(dbl, "TASK-BATCH", "m1", confirmed_plan="per-image")
    assert plan.plan == "refuse"
    assert "changed" in plan.reason.lower(), plan.reason
    assert dbl.sent() == 0, "it deleted on a plan the user never agreed to"


def test_a_matching_confirmed_plan_goes_through(monkeypatch):
    monkeypatch.setattr(core, "READ_ONLY", False)
    dbl = _Double(_batch_task(False, False))
    plan = core.delete_image_routed(dbl, "TASK-BATCH", "m0", confirmed_plan="per-image")
    assert plan.plan == "per-image"
    assert len(dbl.mutations) == 1


def test_the_routed_delete_fires_at_most_one_mutation():
    """Structural, so a branch nobody drove is covered too: no loop may wrap the delete.
    A destructive mutation retried after a lost response can fire twice against a task that
    has already changed. delete_task_gql hand-rolls a single post and delete_batch_media_gql
    rides gql_mutate; the function that picks between them must not put a loop around
    either."""
    import ast
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(core.delete_image_routed)))
    loops = [n for n in ast.walk(tree)
             if isinstance(n, (ast.For, ast.AsyncFor, ast.While, ast.ListComp,
                               ast.SetComp, ast.DictComp, ast.GeneratorExp))]
    assert not loops, (
        "delete_image_routed grew a loop around a destructive delete -- it must fire once")

