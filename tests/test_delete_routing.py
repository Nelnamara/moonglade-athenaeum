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
