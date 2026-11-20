"""
moonglade/task_reads.py
=======================
Reading a task back from PixAI: the task-detail document and its reader (`task_detail_gql`),
the status read (`_GEN_STATUS`, the terminal-status sets, `generation_status`,
`_poll_task_status`) and the failure words (`_task_failure_reason`, `describe_failure`,
`_pixai_reason_suffix`, `_never_dispatched`). Moved verbatim out of moonglade/backup.py in the
3.22 split (phase 5).

The names it reads from the engine (gql_adhoc, PixAIError, vlog) are imported from
moonglade.backup inside each function that uses them, at call time, so a test's patch of
backup's binding still reaches them and importing this module never imports the engine.
"""
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run:  pip install requests")


# Task detail as a full document: every field the saved request's answer carried, so every
# reader of a task -- extract_full_meta, the delete plan, the video sync, the Fix and lineage
# readers, --backfill-full-meta's media read -- finds what it always found. `parameters` and
# `outputs` are JSON scalars, so everything nested in them rides whole (as _GEN_STATUS
# proves). It needs no saved copy on PixAI's side. The one it replaced (getTaskById's hash) is
# no longer sent by PixAI's own site, whose current document changed, and its servers were
# answering it from a cache (#91; PROBE_2026-10-26_task-model-detail: six tasks read both
# ways, the same answer but for __typename, which nothing reads). Named, so the fake PixAI
# keys it by its own name and never by _GEN_STATUS's anonymous root field `task`.
_TASK_DETAIL_DOC = (
    "query TaskDetail($id: ID!) { task(id: $id) { id userId parameters outputs status "
    "priority runnerId startedAt endAt createdAt updatedAt retryCount paidCredit "
    "cancelability moderationAction { promptsModerationAction } enrolledExperiment "
    "detectPromptHelperResult { needToEnable enableReasonCode } favoritedAt artworkId "
    "artworkIds artworks { createdAt hidePrompts id isNsfw isSensitive visibility mediaId "
    "title updatedAt flag { shouldBlur } } mediaId media { id type width height "
    "urls { variant url } imageType fileUrl duration thumbnailUrl hlsUrl size "
    "flag { shouldBlur } } stages { id } } }")


def task_detail_gql(session, task_id, retries=3, timeout=60, rest_fallback=False):
    """Read one task back from PixAI: `_TASK_DETAIL_DOC` POSTed through `gql_adhoc`, a query.
    Returns the task dict or None on failure.

    `timeout` is the per-attempt socket timeout, handed straight to the transport. A
    caller under a wall-clock ceiling passes the time it has left rather than letting a
    stalled read run out the transport's own 60s (the delete preview's live check does
    exactly that -- moonglade/gallery.py's DELETE_PREVIEW_LIVE_BUDGET_S).

    RETRIED with backoff -- the same 3-retry shape `gql_adhoc` gives any query -- because a
    single blip here is read downstream as a LOST GENERATION. The moment that matters is the
    tail of a create path: the task has already completed and already been CHARGED, and a
    `None` here reaches `_outputs_or_raise` as "task completed but no media ids found",
    which says "your images are gone" when the task, its images and the credits are all
    exactly where PixAI left them. One timeout should not produce that sentence.

    Retrying is safe HERE specifically because this is a read-only QUERY. The rule that
    forbids a silent retry (see `gql_mutate`) is about a re-POST paying for a second
    generation; a repeated task read cannot spend, delete or change anything.

    A genuine failure now says so, instead of leaving the caller to describe an outage as
    an empty result. That includes an answer with no `task` field in it: a body that is not
    GraphQL at all (an edge's or a stale credential's own JSON) comes back from the ad-hoc
    POST as {}, which answered nothing about the task."""
    from moonglade.backup import gql_adhoc, PixAIError
    # The 3-retry count is passed straight through -- a blip here is read downstream as a
    # LOST GENERATION -- and `timeout` reaches the socket on every attempt. Still fails SOFT:
    # this path must return None and never raise, so a single outage is not reported as
    # "your images are gone" -- the raise is caught here and turned back into None.
    try:
        data = gql_adhoc(session, _TASK_DETAIL_DOC, {"id": str(task_id)}, retries=retries,
                         timeout=timeout)
        if not isinstance(data, dict) or "task" not in data:
            raise PixAIError("PixAI answered, but with no task in it")
    except (PixAIError, requests.RequestException) as e:
        # 3.22 S3-poll (DESIGN_3.22 2.8): the REST read with its stored parameters, before
        # giving up -- ONLY for a caller that asks (`rest_fallback=True`). The fallback is a
        # DEGRADED record (no deletedAt tombstones, no video outputs, no artworkIds, no
        # per-image seeds; marked `_rest_fallback`), so only a reader of `parameters` alone may
        # take it; every delete, catalog write and outputs-shape branch keeps None, the
        # fail-safe answer (security review of 67310d6b).
        fallback = _rest_detail_fallback(session, task_id) if rest_fallback else None
        if fallback is not None:
            return fallback
        print("  could not read task {} back from PixAI ({}). Nothing was spent and nothing "
              "is lost -- this call only READS a task, so the generation and its credits are "
              "exactly as PixAI left them. Try again in a moment.".format(task_id, e))
        return None
    return data.get("task")


# ---------------------------------------------------------------------------
# THE REST TASK READ (3.22 S3-poll, DESIGN_3.22 1.4 and 2.8)
# ---------------------------------------------------------------------------
# GET /v2/task/{id} on the API key: status, startedAt, paidQuota (GraphQL's paidCredit, equal on
# every task P1 read) and REST's own `outputs` ({mediaIds, mediaUrls, videoMediaId, ...};
# mediaIds is exactly the LIVE set, never the composite). It carries no per-image seed and, on
# the failed and cancelled tasks P1 read, no reason -- so a terminal failure's reason is still
# read from GraphQL task(id), best effort. The rich read (task_detail_gql) stays on GraphQL.
def _rest_task(session, task_id, with_parameters=False):
    """GET /v2/task/{id} -> the REST task (a dict carrying `id` and `status`). Raises
    LocalRefusal (a PixAIError) for an id that could leave its path segment (nothing is sent),
    PixAIError for an answer that is not a task. Read-only."""
    from moonglade.backup import PixAIError, LocalRefusal, _rest_get
    from moonglade.cloud_delete import _TASK_ID_RE
    tid = str(task_id or "").strip()
    if not _TASK_ID_RE.match(tid):
        raise LocalRefusal("not a PixAI task id: {!r}; nothing was read".format(tid[:64]))
    data = _rest_get(session, "/task/" + tid,
                     params={"with_parameters": "true"} if with_parameters else None)
    if not isinstance(data, dict) or "status" not in data or not data.get("id"):
        raise PixAIError("PixAI answered, but with no task in it")
    return data


def _rest_reason(task):
    """PixAI's reason off a REST task, when it gives one (P1 found none on a failed or a
    cancelled task, so this is read first and GraphQL is asked only when it is empty)."""
    msg = task.get("taskStatusMsgI18n")
    if isinstance(msg, dict):
        msg = msg.get("en") or next((v for v in msg.values() if isinstance(v, str)), "")
    if isinstance(msg, str) and msg.strip():
        return msg.strip()
    out = task.get("outputs") if isinstance(task.get("outputs"), dict) else {}
    why = out.get("chatEditFailureReason")
    return why.strip() if isinstance(why, str) and why.strip() else ""


def _graphql_reason_of(session, task_id):
    """The failure reason from GraphQL task(id) (outputs.reason and kin), best effort: '' on
    any failure. Read-only."""
    from moonglade.backup import gql_adhoc
    try:
        t = ((gql_adhoc(session, _GEN_STATUS, {"id": str(task_id)}) or {}).get("task") or {})
        return _task_failure_reason(t.get("outputs"))
    except Exception:                                       # noqa: BLE001 -- best effort
        return ""


#: The status read's own retries (3.22 review F1). Before 3.22 the poll rode gql_adhoc, which
#: retried a query 3 times with a doubling 2 s backoff; the REST GET (rest_get) is one attempt,
#: so this read carries the same count itself. Safe because it is a read-only GET: a repeated
#: status read cannot spend, delete or change anything. No POST is ever retried here.
STATUS_READ_RETRIES = 3
STATUS_READ_BACKOFF_S = 2.0


def _read_retryable(e):
    """True for a status-read failure a second attempt may get past: a dropped connection, a
    timeout, a body that was not JSON, a 429 or a 5xx -- the set gql_adhoc retried. Not an SSL
    failure, a refused id or any other 4xx (a retry repeats those exactly)."""
    from moonglade.backup import PixAIRestError
    if isinstance(e, requests.exceptions.SSLError):
        return False
    if isinstance(e, (requests.RequestException, ValueError)):
        return True
    if isinstance(e, PixAIRestError):
        st = getattr(e, "status", None)
        return isinstance(st, int) and (st == 429 or st >= 500)
    return False


def _rest_task_read(session, task_id):
    """`_rest_task` with STATUS_READ_RETRIES bounded retries on a retryable failure (a GET, so
    a retry is free). The last failure is raised as it came."""
    delay = STATUS_READ_BACKOFF_S
    for attempt in range(STATUS_READ_RETRIES + 1):
        try:
            return _rest_task(session, task_id)
        except Exception as e:                              # noqa: BLE001 -- sorted below
            if attempt == STATUS_READ_RETRIES or not _read_retryable(e):
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def _status_read(session, task_id):
    """One status read on the REST route, in _GEN_STATUS's names: {status, paidCredit,
    startedAt, outputs, reason}. The reason is read only for a terminal failure. The GET is
    retried on a passing failure (`_rest_task_read`)."""
    t = _rest_task_read(session, task_id)
    status = str(t.get("status") or "")
    reason = ""
    if status.lower() in _GEN_FAIL:
        reason = _rest_reason(t) or _graphql_reason_of(session, task_id)
    return {"status": status, "paidCredit": t.get("paidQuota"), "startedAt": t.get("startedAt"),
            "outputs": t.get("outputs") or {}, "reason": reason}


def _rest_detail_fallback(session, task_id):
    """The rich read's fallback when GraphQL task(id) could not be read (DESIGN_3.22 2.8): REST
    getById with its stored parameters, in task_detail_gql's shape -- `parameters`, and
    `outputs` rebuilt from the LIVE media ids (one id: outputs.mediaId; more: outputs.batch, one
    entry per live image). It is DEGRADED and says so (`_rest_fallback`): no deletedAt
    tombstones, no video outputs, no artworkIds, no per-image seeds. Only a caller that reads
    `parameters` alone takes it (task_detail_gql(..., rest_fallback=True)), and
    cloud_delete.route_image_delete refuses it outright. None on any failure. A read."""
    try:
        t = _rest_task(session, task_id, with_parameters=True)
    except Exception:                                       # noqa: BLE001 -- None, as before
        return None
    out = t.get("outputs") if isinstance(t.get("outputs"), dict) else {}
    mids = [str(m) for m in (out.get("mediaIds") or []) if m]
    outputs = {}
    if len(mids) == 1:
        outputs["mediaId"] = mids[0]
    elif mids:
        outputs["batch"] = [{"mediaId": m} for m in mids]
    if out.get("videoMediaId"):
        outputs["videoMediaId"] = str(out["videoMediaId"])
    return {"id": str(t.get("id")), "status": t.get("status"),
            "parameters": t.get("parameters") if isinstance(t.get("parameters"), dict) else {},
            "outputs": outputs, "paidCredit": t.get("paidQuota"),
            "startedAt": t.get("startedAt"), "endAt": t.get("endAt"),
            "createdAt": t.get("createdAt"), "updatedAt": t.get("updatedAt"),
            "_rest_fallback": True}


_GEN_STATUS = ("query($id: ID!) { task(id: $id) "
               "{ id status paidCredit startedAt outputs } }")
# startedAt + outputs are load-bearing, not decoration: `startedAt` is the ONLY way to
# tell a task PixAI queued-but-never-dispatched from one that is genuinely running (both
# sit at a non-terminal status), and `outputs.reason` carries PixAI's own explanation for
# a cancellation (e.g. "waiting timeout"). Without them this poller could only ever see
# `status`, which is how five of the owner's generations died silently across four days.
def _poll_task_status(session, task_id, timeout, *, interval=3, label="task",
                      fail_noun="task"):
    """Poll `_GEN_STATUS` until the task completes, fails, or times out. Returns the
    server-authoritative `paidCredit` (or None) and prints it as the actual cost on
    completion. Raises PixAIError on failure/timeout. Shared by the generate / video /
    edit submit paths so their poll behaviour can't drift."""
    from moonglade.backup import PixAIError, LocalRefusal, vlog
    deadline = time.time() + timeout
    paid_credit = None
    started_at, last_status = None, ""
    read_error = None
    while time.time() < deadline:
        # 3.22 S3-poll: the REST read (GET /v2/task/{id}, API key), its reason from GraphQL
        # only on a terminal failure (_status_read).
        try:
            task = _status_read(session, task_id)
        except LocalRefusal:
            raise                       # an id that was never sent: no read will ever work
        except (PixAIError, requests.RequestException, ValueError) as e:
            # 3.22 review F1: a read that failed (after its own retries) says nothing about
            # the task, which was created and may be running or done. It never ends the
            # poll: the next read is tried at the next interval, until the deadline.
            read_error = e
            vlog("{} poll: the status read failed ({}); still waiting".format(label, e))
            time.sleep(interval)
            continue
        read_error = None
        status = str(task.get("status", "")).lower()
        last_status = status or last_status
        started_at = task.get("startedAt") or started_at
        if task.get("paidCredit") is not None:
            paid_credit = task.get("paidCredit")     # server-authoritative actual cost
        vlog("{} poll: {}{}".format(label, status or "(unknown)",
                                    "" if started_at else " (not started yet)"))
        # _GEN_DONE / _GEN_FAIL are this module's single source of truth for a terminal
        # status -- generation_status() and _outputs_or_raise() already read them. This loop
        # used to carry its own hand-copied tuples, and they had drifted out of step: they
        # were missing 'finished' (a real success) and 'rejected' (a real failure, and named
        # as terminal in EmptyOutputsError's own docstring). A rejected generation is
        # already refunded, but the poller went on waiting for it until the timeout expired
        # and then reported it as still running on PixAI.
        if status in _GEN_DONE:
            if paid_credit is not None:
                print("  actual cost: {:,} credits".format(int(paid_credit)))
            return paid_credit
        if status in _GEN_FAIL:
            raise PixAIError("{} ended with status: {}{}".format(
                fail_noun, status,
                " (PixAI's reason: {})".format(task["reason"]) if task.get("reason") else ""))
        time.sleep(interval)
    if read_error is not None:
        raise PixAIError(
            "stopped waiting after {}s: PixAI's status read kept failing ({}), so this could "
            "not see how the task ended. The task MAY STILL BE RUNNING on PixAI, and may "
            "already be charged -- do not send it again (task {}). Recover it free once it "
            "finishes with --task-id {} (or it arrives in your next --update).".format(
                timeout, str(read_error)[:160], task_id, task_id))
    if _never_dispatched(last_status, started_at):
        raise PixAIError(
            "{} was accepted by PixAI but NEVER started. After {}s it is still queued "
            "with no start time, so no worker ever picked it up -- waiting longer will "
            "not help, and --task-id recovery has nothing to fetch. PixAI reaps an "
            "unstarted task at about 60 minutes and issues a refund then, so the credits "
            "should come back on their own; check your credit history if they don't. "
            "(task {})".format(fail_noun, timeout, task_id))
    raise PixAIError(
        "stopped waiting after {}s, but the task is STILL RUNNING on PixAI (task {}). "
        "Nothing is lost: recover it free once it finishes with --task-id {} "
        "(or it arrives in your next --update).".format(timeout, task_id, task_id))


def _task_failure_reason(outputs):
    """PixAI's own explanation for a failure, from whichever key it used this time.

    It does NOT use one key. A task it cancelled says `{"reason": "waiting timeout"}`, while a
    task its model refused says `{"finish_reason": "ERROR", "modelResponse": [],
    "failureMessage": "Provider refused to answer", "failure_reason":
    "PROVIDER_REFUSE_ANSWER"}`. Reading only `reason` made three real, fully-explained
    content refusals look unexplained, and they were written up as model flakiness -- the
    opposite advice from what the payload actually said.

    Preference order is deliberate: the human sentence first, then the enum (still far better
    than nothing), then the cancelled-task key. `finish_reason` is skipped -- "ERROR" is a
    category, not information.

    NOTE the projection trap: this is the GRAPHQL `outputs`. REST `/v2/task/{id}` returns a
    DIFFERENT `outputs` ({mediaIds, mediaUrls}) with no failure detail at all, so a probe
    against REST will report no reason exists when one does."""
    if not isinstance(outputs, dict):
        return ""
    for key in ("failureMessage", "failure_reason", "reason"):
        val = outputs.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def describe_failure(status, reason="", started=True):
    """A failure message a person can act on, from what PixAI actually tells us.

    Their status string for a failed generation is genuinely just "failed", and `outputs`
    frequently comes back empty, so faithfully forwarding their words leaves the user with
    one useless word -- which is exactly what the owner saw on three consecutive hand-fix
    attempts (2026-07-25): status `failed`, error `failed`, nothing else. Forwarding is
    still right when they DO explain themselves; this only fills the silence.

    Three distinct cases, because they send you to three different places:
      - reason given      -> lead with THEIR words; ours must never bury them.
      - never dispatched  -> it did not "fail to render", no worker ever took it. Saying
                             otherwise sends someone off debugging a prompt that was never
                             read. These are reaped and refunded at ~60 minutes.
      - ran, then failed  -> their model errored. Nothing to fix in the request, and the
                             credits come back on their own (observed: charged and refunded
                             within 2-3 seconds), which is the first thing anyone wants to
                             know.

    Their reason and our explanation are ADDITIVE, not either/or. "waiting timeout" is
    their jargon: accurate, and meaningless to anyone who does not already know it means
    no worker ever picked the task up. Lead with their words, then say what happened."""
    status = str(status or "failed").strip() or "failed"
    reason = str(reason or "").strip()
    parts = [status]
    if reason:
        parts.append("PixAI's reason: {}".format(reason))
        # A provider/content refusal is the moderator declining the content, not a system
        # fault. Saying so turns a dead end into a next step -- the fix is rewording, and
        # without this the message reads like something is broken and needs debugging.
        if "refus" in reason.lower() or "policy" in reason.lower():
            parts.append("That is a content refusal, not a fault: rewording the prompt "
                         "usually clears it. Nothing was charged — refused generations "
                         "are refunded.")
    if not started:
        parts.append("It was queued but never started, so nothing rendered — unstarted "
                     "tasks are cancelled and refunded after about an hour.")
    elif not reason:
        parts.append("PixAI ran this and it failed without giving a reason. Failed "
                     "generations are refunded automatically, so the credits come back.")
    return " — ".join(parts)


def _pixai_reason_suffix(task):
    """PixAI's own explanation for a terminal status, from `outputs.reason` (e.g.
    "waiting timeout"). Surfaced because a bare "cancelled" reads as though the USER
    cancelled something -- the owner saw exactly that five times and had no way to know
    PixAI had timed the task out of its own queue."""
    reason = _task_failure_reason((task or {}).get("outputs"))
    return " (PixAI's reason: {})".format(reason) if reason else ""


def _never_dispatched(status, started_at):
    """True when PixAI accepted a task, queued it, and never assigned it a worker.

    Keys on `startedAt` being absent AND a POSITIVE observation of a pre-run status. Two
    deliberate exclusions, both of which would otherwise produce a confident lie:
      - `running` without a `startedAt` has obviously started, so it stays on the
        reassuring "still running, recover it free" timeout path.
      - an EMPTY status means we never actually observed the task (e.g. a zero/expired
        timeout that never entered the poll loop). "Not observed" is not "not dispatched",
        so that also stays on the reassuring path -- claiming a task is dead because we
        never looked at it is the same class of error as the message this fix removes."""
    return not started_at and str(status or "").lower() in ("waiting", "pending", "queued")




_GEN_DONE = ("completed", "success", "succeeded", "done", "finished")
_GEN_FAIL = ("failed", "error", "cancelled", "canceled", "rejected")


def generation_status(session, task_id):
    """One status check for a task -> {status, phase, paid_credit, started, reason}.
    `phase` normalizes the raw status into 'running' | 'done' | 'failed' for the async
    poller. Read-only.

    `started` and `reason` exist because 'what' without 'why' is how five of the owner's
    generations died unnoticed over four days (2026-07-21..24):
      - `started` is False until PixAI actually assigns a worker. A task it accepted,
        queued and never dispatched sits at a NON-TERMINAL status for ~60 minutes before
        being reaped, so on status alone it is indistinguishable from real work and shows
        as an indefinite spinner. This is the only field that tells them apart.
      - `reason` is PixAI's own explanation from `outputs.reason` (e.g. "waiting
        timeout"). Without it a caller can only report "cancelled", which reads as though
        the USER cancelled something they never started.
    Callers that only want the original three keys are unaffected -- those are unchanged."""
    # 3.22 S3-poll (DESIGN_3.22 2.8): the REST read; paidQuota is paid_credit (P1: equal).
    t = _status_read(session, task_id)
    raw = (t.get("status") or "").lower()
    phase = ("done" if raw in _GEN_DONE else
             "failed" if raw in _GEN_FAIL else "running")
    return {"status": t.get("status") or "", "phase": phase, "paid_credit": t.get("paidCredit"),
            "started": bool(t.get("startedAt")), "reason": t.get("reason") or ""}
