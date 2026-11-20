"""
moonglade/cloud_delete.py
=========================
Deleting from the account: the per-image delete router (`route_image_delete`, read then route),
its plan and confirm (`plan_image_delete`, `delete_image_routed`), the per-image mutation
(`delete_batch_media_gql`) and the whole-task delete (`delete_task`, POST /v2/task/{id}/delete),
with the task-id rule and the delete path. Moved verbatim out of moonglade/backup.py in the 3.22
split (phase 5).

It reads the task through `_task_reads.task_detail_gql` and the transport through
`_pixai_client`, the way the engine did once they moved out. The names it reads from the engine
(the READ_ONLY gate `_check_read_only`, `gql_mutate`, the error classes, `_ssl_help`, `vlog`) are
imported from moonglade.backup inside each function that uses them, at call time, so a test's
patch of backup's binding still reaches them and importing this module never imports the engine.
"""
import re
import sys
import time
from collections import namedtuple

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run:  pip install requests")

from moonglade import pixai_client as _pixai_client
from moonglade import task_reads as _task_reads


# The whole-generation delete (#92): POST /v2/task/{id}/delete on the API key, the route
# pixai.art's own task menu calls (task.deleteTask). It only ever touches YOUR OWN tasks,
# and the destructive path is independently gated by explicit confirmation (the preview
# then confirm, and the typed "DELETE" in the gallery, which are the only roads to it).
# A task id is digits in practice; the rule is the narrowest that still cannot leave the
# path segment (no "/", "?", "#", "%", "." or space).
_TASK_ID_RE = re.compile(r"^[0-9A-Za-z_-]{1,64}$")
TASK_DELETE_PATH = "/task/{}/delete"


# ---------------------------------------------------------------------------
# DELETING ONE IMAGE -- read the task, then pick the mutation PixAI will accept
#
# There are two deletes and they are not interchangeable:
#
#   deleteBatchMedia (inside updateGenerationTask)  drops ONE member out of a task's
#       outputs.batch[]. PixAI accepts it only while the task would still have an output
#       left afterwards.
#   POST /v2/task/{id}/delete (delete_task)         removes the whole generation record.
#       (Until #92 this was the saved GraphQL request the site no longer sends.)
#
# From v2.5.0 until 2026-09-06 the gallery's single-image "Delete from PixAI" sent the
# first one every time. For a task that made ONE image (no `batch` key -- the picture is
# outputs.mediaId) and for the LAST live member of a batch, PixAI answers 403 "task outputs
# does not include any media with mediaId". Their own site routes those two cases to the
# whole-task mutation. Nothing changed on their side; the app was wrong from the start.
#
# What a read-only probe of the owner's own tasks established on 2026-09-06, and what this
# code is therefore allowed to rely on:
#   * a deleted batch member KEEPS its place in outputs.batch[] and gains `deletedAt`
#     (an ISO string). Untouched members carry no such key. So the array's LENGTH and a
#     member's POSITION say nothing about how many images are still live.
#   * outputs.mediaId on a batch task is the combined preview picture PixAI renders of the
#     whole batch. It is never one of outputs.batch[]; the two sets are disjoint.
#   * the task's `updatedAt` does NOT move on a per-image delete -- nothing may key on it.
#   * getTaskById still resolves a whole-task-deleted task, so it cannot be used to ask
#     whether a task is gone.
# ---------------------------------------------------------------------------

#: What `route_image_delete` decided: which mutation to send ("per-image" / "whole-task"),
#: or "refuse" to send anything; a plain-words `reason`; how many OTHER images of the batch
#: would still be live on PixAI afterwards; and the target's own outputs.batch[] entry (None
#: when the task has no batch, or does not list this image at all).
ImageDeleteRoute = namedtuple("ImageDeleteRoute", "plan reason live_siblings entry")


def batch_entry(batch, media_id):
    """One media's own entry in a task's `outputs.batch` array, or None.

    The single place that decides which array entry belongs to which image, so the router,
    the output enumerator and the per-row batch position cannot drift on it."""
    if not isinstance(batch, list):
        return None
    mid = str(media_id or "")
    if not mid:
        return None
    for entry in batch:
        if isinstance(entry, dict) and str(entry.get("mediaId") or "") == mid:
            return entry
    return None


def live_batch_media(batch):
    """The media ids of a task's batch that PixAI still has, newest-first order kept.

    A member with a `deletedAt` is not one of them -- it is a tombstone PixAI leaves in
    place, which is why counting the array itself overcounts."""
    if not isinstance(batch, list):
        return []
    return [str(e.get("mediaId") or "") for e in batch
            if isinstance(e, dict) and e.get("mediaId") and not e.get("deletedAt")]


def deleted_batch_media(batch):
    """The mirror of `live_batch_media`: members PixAI has already dropped (they carry a
    `deletedAt`). The local copies of these are the only ones left anywhere, so a whole-task
    delete must leave their catalog rows and their files alone."""
    if not isinstance(batch, list):
        return []
    return [str(e.get("mediaId") or "") for e in batch
            if isinstance(e, dict) and e.get("mediaId") and e.get("deletedAt")]


def route_image_delete(task, media_id):
    """Decide, from a task record PixAI just answered with, which delete to send for ONE
    image -- or that nothing may be sent. Returns an `ImageDeleteRoute`.

    Pure: a record in, a decision out. It reads nothing live and deletes nothing, so every
    shape below is exercisable offline (dev/tests/test_delete_routing.py).

    The rows, in the order they are checked:

      refuse      the record is missing -- the read failed. The fail-safe direction is
                  ALWAYS refuse: answering "I could not look" with the whole-task mutation
                  would delete a whole generation off a dropped packet.
      refuse      a video task (its clips hang off outputs.videos). Out of scope; guessing a
                  destructive mutation is not an option.
      refuse      the id is the batch's combined preview picture, not one of its images.
      refuse      the task does not list this image at all -- a stale row or a rotated id.
      refuse      this image's own entry already carries `deletedAt`.
      per-image   the image is a batch member and at least one OTHER member is still live,
                  so the task keeps an output and PixAI accepts deleteBatchMedia.
      whole-task  the image is the last live member of its batch, or the task has no batch
                  and this image IS its output. Either way the delete would leave the task
                  with nothing, which is the case PixAI's own site sends its whole-task
                  delete (task.deleteTask) for.
    """
    mid = str(media_id or "").strip()
    if not mid:
        return ImageDeleteRoute(
            "refuse", "There is no image id to delete; nothing was deleted.", 0, None)
    if not isinstance(task, dict) or not task:
        return ImageDeleteRoute(
            "refuse",
            "Couldn't read the task from PixAI; nothing was deleted, try again.", 0, None)

    outputs = task.get("outputs") or {}
    videos = outputs.get("videos")
    if isinstance(videos, list) and videos:
        # Checked BEFORE the lone-image row on purpose: a video task also carries an
        # outputs.mediaId (its poster still), so the lone-image rule would happily route it
        # into a whole-task delete.
        return ImageDeleteRoute(
            "refuse", "Video clips are deleted from the task's page on PixAI.", 0, None)

    batch = outputs.get("batch")
    if isinstance(batch, list) and batch:
        entry = batch_entry(batch, mid)
        if entry is None:
            if str(outputs.get("mediaId") or "") == mid:
                return ImageDeleteRoute(
                    "refuse",
                    "That is the combined preview picture PixAI makes for a batch, not one "
                    "of the images in it.", len(live_batch_media(batch)), None)
            return ImageDeleteRoute(
                "refuse", "PixAI's copy of this task no longer lists this image.", 0, None)
        if entry.get("deletedAt"):
            return ImageDeleteRoute(
                "refuse", "This image is already deleted on PixAI.",
                len(live_batch_media(batch)), entry)
        others = [m for m in live_batch_media(batch) if m != mid]
        if others:
            return ImageDeleteRoute(
                "per-image",
                "{} other image{} in this batch stay on PixAI.".format(
                    len(others), "" if len(others) == 1 else "s"),
                len(others), entry)
        return ImageDeleteRoute(
            "whole-task",
            "This is the last image of its generation still on PixAI, so PixAI removes the "
            "whole generation record.", 0, entry)

    if str(outputs.get("mediaId") or "") == mid:
        return ImageDeleteRoute(
            "whole-task",
            "This generation made only this one image, so PixAI removes the whole "
            "generation record.", 0, None)
    return ImageDeleteRoute(
        "refuse", "PixAI's copy of this task no longer lists this image.", 0, None)


_DELETE_BATCH_MEDIA_MUT = """
mutation($id: ID!, $input: UpdateGenerationTaskInput!) {
  updateGenerationTask(id: $id, input: $input) { id }
}
"""


def delete_batch_media_gql(session, task_id, media_id):
    """Delete ONE image out of a task's batch, leaving the task and its siblings alone.

    The finer-grained counterpart to `delete_task`, which is task-level: deleting any
    one image there takes the whole batch with it. DELETES from your PixAI account and is
    irreversible on their side.

    Signature discovered by validation-error probing (nothing executed): the mutation is
    `updateGenerationTask(id: ID!, input: UpdateGenerationTaskInput!)` and the delete rides
    in as `{deleteBatchMedia: {mediaId}}`. It goes over the ad-hoc POST path (`gql_mutate`),
    so it needs NO saved hash and cannot break when one rotates.

    Two properties shared deliberately with `delete_task`, because both are safety
    rather than style:
      - `_check_read_only` fires BEFORE the network call. READ_ONLY is a promise the Trust
        & Safety page makes about every account-mutating path; a new destructive path that
        skipped it would be a silent hole in that promise.
      - SINGLE ATTEMPT, no retry/backoff. A flaky network must never be able to fire a
        destructive delete twice."""
    from moonglade.backup import _check_read_only, gql_mutate, PixAIError
    task_id, media_id = str(task_id or "").strip(), str(media_id or "").strip()
    if not task_id or not media_id:
        raise PixAIError(
            "per-image delete needs BOTH a task id and a media id (got task={!r}, media={!r}) "
            "-- a blank media id would be an update with nothing to delete, and a blank task "
            "id has no batch to delete from.".format(task_id, media_id))
    _check_read_only("delete one image from a task on your PixAI account")
    # gql_mutate is the SINGLE-ATTEMPT promise above, made real: it hard-codes retries=0,
    # where a re-POST on a RequestException or a 429/5xx could re-fire a destructive
    # mutation against a batch that has already changed underneath it (a read timeout can
    # arrive AFTER PixAI processed the delete). delete_task gets the same guarantee from
    # rest_post, which has no retry loop either.
    return gql_mutate(session, _DELETE_BATCH_MEDIA_MUT,
                      {"id": task_id, "input": {"deleteBatchMedia": {"mediaId": media_id}}})


def delete_task(session, task_id):
    """Delete ONE whole generation (task) from your PixAI account: `POST /v2/task/{id}/delete`.

    DELETES the generation from your PixAI account -- irreversible. This is the route
    pixai.art's own task menu calls (`task.deleteTask({id})` through its oRPC client; route
    table `"deleteTask": {"method": "POST", "path": "/task/{id}/delete"}`), sent the way that
    client sends it: the id in the path, the rest of the input (`{}`) as the JSON body, the
    API key as the Bearer like every other /v2 route this app uses (#92). PixAI's 09-26
    contract describes it: "Soft-deletes a task owned by the current user: the task stops
    being listed, its linked artwork is deleted, and a task that has not finished is
    cancelled first." Its declared output is `{"success": true}`; its declared errors are 401
    "Authentication required" and 403 "Not authorized".

    SUCCESS IS EXACTLY `{"success": true}`. Anything else -- a 2xx without that, a body that
    is not JSON, any non-2xx, a network error -- raises PixAIError, and a caller treats the
    task as NOT deleted (its local copy stays). Refuse rather than guess.

    IDEMPOTENT, so success proves nothing about existence. The same contract says
    "Idempotent -- deleting a task that is already deleted, or one that does not exist, also
    succeeds." A `True` here means only "PixAI holds no live copy now"; it does not prove the
    task existed, and no caller may treat it as an existence check (none does: the bulk
    path's keep-set comes from its own task read, not from this answer).

    The task id must look like a PixAI task id (`_TASK_ID_RE`: letters, digits, `_`, `-`,
    1-64 characters) or nothing is sent, so an id can never step out of its path segment
    into another route.

    READ_ONLY is checked FIRST, before the id check and before anything is sent. SINGLE
    ATTEMPT: exactly one POST through `rest_post`, which has no retry loop (and the session
    mounts no urllib3 Retry adapter), so a flaky network can never fire a delete twice.
    Pinned by dev/tests/test_spend_no_retry.py and dev/tests/test_rest_delete_and_renewal.py.
    Returns True on success."""
    from moonglade.backup import (_check_read_only, PixAIAuthError, PixAIError, PixAIRestError,
                                  _ssl_help, vlog)
    _check_read_only("delete a task from your PixAI account")      # FIRST, before anything
    tid = str(task_id or "").strip()
    if not _TASK_ID_RE.match(tid):
        raise PixAIError(
            "refusing to delete task {!r}: not a PixAI task id. Nothing was sent.".format(tid))
    _t = time.monotonic()
    try:
        answer = _pixai_client._client_of(session).rest_post(TASK_DELETE_PATH.format(tid), {})
    except requests.exceptions.SSLError:
        raise PixAIError(_ssl_help())
    except PixAIRestError as e:
        if e.status == 401:
            raise PixAIAuthError("401 Unauthorized -- PixAI refused the API key; task {} was "
                                 "not deleted.".format(tid))
        if e.status == 403:
            raise PixAIError("PixAI says task {} is not yours to delete (403); nothing was "
                             "deleted.".format(tid))
        raise PixAIError("HTTP {} deleting task {}: {}".format(e.status, tid, str(e)[:400]))
    except ValueError as e:
        # A 2xx that is not JSON: rest_post's r.json() raised. Caught BEFORE RequestException,
        # because requests' JSONDecodeError is both. A ValueError that requests raised before
        # sending anything (a malformed URL) is a RequestException too and is not an answer.
        if isinstance(e, requests.RequestException) and not isinstance(
                e, getattr(requests.exceptions, "JSONDecodeError", ())):
            raise PixAIError("network error deleting task {}: {}".format(tid, e))
        raise PixAIError("PixAI answered the delete of task {} with something that is not "
                         "JSON; it is treated as not deleted and its local copy "
                         "stays.".format(tid))
    except requests.exceptions.ReadTimeout as e:
        # The request went out and no answer came back: PixAI may or may not have deleted
        # it. Treated as not deleted (fail-safe), and the route is idempotent, so a retry by
        # the user is safe -- never by this function.
        raise PixAIError("network error deleting task {}: {}. PixAI may or may not have "
                         "deleted it; it is treated as not deleted and its local copy stays. "
                         "Deleting it again is safe.".format(tid, e))
    except requests.RequestException as e:
        raise PixAIError("network error deleting task {}: {}".format(tid, e))
    if not (isinstance(answer, dict) and answer.get("success") is True):
        raise PixAIError("PixAI answered the delete of task {} without confirming it; it is "
                         "treated as not deleted and its local copy stays.".format(tid))
    vlog("task delete {} -> ok in {:.2f}s".format(tid, time.monotonic() - _t))
    return True


#: What one routed image delete decided and did. `plan` is the branch that FIRED --
#: "per-image", "whole-task", or "refuse" when nothing was sent -- so a caller never has to
#: work the branch out again from its own catalog. `keep_media` names the task's images PixAI
#: had ALREADY deleted before this call; their local copies are the only ones left anywhere,
#: so a whole-task purge must leave them alone. `cloud_deleted_at` is the target's own
#: deletedAt stamp when it turned out to be one of those. `keep_media_deleted_at` carries WHEN
#: PixAI deleted each of `keep_media`, as (media_id, deletedAt) pairs -- so a caller holding a
#: catalog can record the fact off the read this plan already made, rather than making a
#: second one (moonglade.gallery's /api/delete-image does exactly that). `artwork_ids` is the
#: task's published artworks off that same read (getTaskById's `artworkIds`), or None when the
#: read did not carry the field -- None is "not known", never "not published". PixAI's own
#: contract says its task delete also deletes the task's linked artwork, so the whole-task
#: branch's dialog names them (SCOPE_2026-09-26 E5).
ImageDeletePlan = namedtuple(
    "ImageDeletePlan",
    "plan reason live_siblings keep_media cloud_deleted_at keep_media_deleted_at artwork_ids",
    defaults=(None,))


def task_artwork_ids(task):
    """The published-artwork ids a task read carries (`artworkIds`), deduped in order -- or
    None when the read has no such list (a failed read, or a shape without the field), which
    callers must treat as UNKNOWN rather than as "nothing published"."""
    ids = (task or {}).get("artworkIds") if isinstance(task, dict) else None
    if not isinstance(ids, list):
        return None
    return tuple(dict.fromkeys(str(a) for a in ids if a not in (None, "")))


def _image_delete_plan(task, media_id):
    """Turn one routing decision into the plan a caller acts on (pure)."""
    plan, reason, live_siblings, entry = route_image_delete(task, media_id)
    batch = ((task or {}).get("outputs") or {}).get("batch")
    gone = tuple(deleted_batch_media(batch))
    return ImageDeletePlan(plan, reason, live_siblings, gone,
                           str((entry or {}).get("deletedAt") or ""),
                           tuple((m, str((batch_entry(batch, m) or {}).get("deletedAt") or ""))
                                 for m in gone),
                           task_artwork_ids(task))


def plan_image_delete(session, task_id, media_id):
    """What deleting ONE image would do, without deleting anything.

    Reads the task back from PixAI (`task_detail_gql`, read-only, retried, fails SOFT to
    None) and routes it. The read is not optional and cannot be replaced by the local
    catalog: which members of a batch PixAI still has is a fact only PixAI holds, and the
    catalog knows nothing about a sibling deleted from the website.

    This is the half the confirm dialog is worded from, so it must be safe to call on a
    click: no mutation is sent on any road out of here."""
    return _image_delete_plan(_task_reads.task_detail_gql(session, str(task_id or "").strip()), media_id)


NO_CONFIRMED_PLAN = ("This delete did not say which delete you agreed to, so nothing was "
                     "deleted. Open the delete dialog again and confirm from there.")


def delete_image_routed(session, task_id, media_id, confirmed_plan=None):
    """Delete ONE image from PixAI through whichever mutation PixAI accepts for it.

    IRREVERSIBLE on their side. Returns the `ImageDeletePlan` that fired, so the caller
    reads the branch off this answer instead of re-deriving it from its own row counts --
    the local catalog cannot see a sibling deleted from the website, which is exactly how
    the old code came to send the wrong mutation.

    Order, and why:
      1. READ_ONLY first, before even the read. The two primitives below each check it
         too, but checking here means a read-only install makes NO network call at all for
         a delete, rather than quietly reading and then refusing.
      2. Read and route (`plan_image_delete`). A refusal returns here with nothing sent.
      3. `confirmed_plan` is the plan the user was shown, and it is REQUIRED: a delete
         with no plan is refused before the read, with nothing sent. If the fresh route
         disagrees, the task changed underneath the dialog and this refuses rather than
         doing something the user did not agree to. (Until 2026-11-19 a missing plan
         skipped that comparison, so a confirm without one deleted whatever the fresh
         read said, a whole generation included.)
      4. Fire exactly one branch. No loop wraps either call: a destructive mutation
         re-sent after a lost response can fire again against a task that has already
         changed (dev/tests/test_delete_routing.py pins this structurally, and
         dev/tests/test_spend_no_retry.py pins the primitives).
    """
    from moonglade.backup import _check_read_only
    _check_read_only("delete an image from your PixAI account")
    task_id, media_id = str(task_id or "").strip(), str(media_id or "").strip()
    confirmed_plan = str(confirmed_plan or "").strip()
    if not confirmed_plan:
        return ImageDeletePlan(
            "refuse", NO_CONFIRMED_PLAN, 0, [], "", [])
    plan = plan_image_delete(session, task_id, media_id)
    if plan.plan == "refuse":
        return plan
    if confirmed_plan != plan.plan:
        return ImageDeletePlan(
            "refuse",
            "What this delete would do changed while the dialog was open, so nothing was "
            "deleted. Open it again to see where the image stands now.",
            plan.live_siblings, plan.keep_media, plan.cloud_deleted_at,
            plan.keep_media_deleted_at, plan.artwork_ids)
    if plan.plan == "per-image":
        delete_batch_media_gql(session, task_id, media_id)
    else:
        delete_task(session, task_id)
    return plan
