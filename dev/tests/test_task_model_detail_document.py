"""Task detail and model detail are read as full query documents (issue #91).

The sync's fill-metadata step, `--backfill-full-meta`, `--sync-videos`, the delete preview's
live check, the Lightbox's task reads, the poll's tail, the model-name fixer and the Runs-reel
reuse read a task or a model version through two saved (hash-only) requests. PixAI's own site
no longer sends either copy -- the task one changed in the site's current build, the model one
never matched a document the site sends -- and its servers were answering both from a cache,
the same cache that refused the history feed part of the time (#89). `task_detail_gql` now
POSTs `_TASK_DETAIL_DOC` through `gql_adhoc`; the three model readers share
`_model_version_gql`, which POSTs `_MODEL_VERSION_DOC`.

What is pinned:

  * each read is one ad-hoc POST of its document, never a saved GET, and both documents are
    the text the read-only probe of 2026-10-26 validated against PixAI; the task document
    selects every top-level key the saved request's answer carried;
  * task_detail_gql keeps its failure semantics: None (never a raise) with its sentence on a
    GraphQL refusal, a network error, a 5xx after its three retries or an answer with no task
    in it; its `timeout` reaches every attempt;
  * every reader of a task reads PixAI's recorded document answer as it read the recorded
    saved answer (extract_full_meta and the rest), the delete plan routes the recorded batch
    both ways, and the video sync and --backfill-full-meta read through the documents;
  * model_name_gql keeps the M18 matrix through the document (an errors array, a reply
    without the field and a body that is not GraphQL are FAILURES, memoised as such; null is
    the real "removed" answer; strict raises; the cache answers repeats), and the reuse reader
    and the preset reader fail soft; all three ask once (retries=0);
  * the two retired saved requests leave nothing behind.

NO REAL PIXAI: a FakePixAI answers the documents by their names (`TaskDetail`,
`ModelVersion`), and the wire tests drive the real client against a recording session. The
answers are PixAI's own, recorded by the probe and scrubbed (dev/tests/fixtures/
task_model_detail.json says how).
"""
import copy
import inspect
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from moonglade import backup as core
from moonglade import gallery as g
from moonglade.gallery import CATALOG_FIELDS, load_catalog, save_catalog

from tests.fake_pixai import FakePixAI, UnregisteredOperation, operation_name

REPO = Path(__file__).resolve().parents[2]
RECORDED = json.loads((Path(__file__).resolve().parent / "fixtures" /
                       "task_model_detail.json").read_text(encoding="utf-8"))
TASKS = RECORDED["tasks"]
MODELS = RECORDED["models"]
KINDS = sorted(TASKS)

TASK_DETAIL = operation_name(core._TASK_DETAIL_DOC)        # what the fake keys it by
MODEL_VERSION = operation_name(core._MODEL_VERSION_DOC)

# The fixed part of task_detail_gql's sentence (the task id and PixAI's error sit in front).
SENTENCE = ("Nothing was spent and nothing is lost -- this call only READS a task, so the "
            "generation and its credits are exactly as PixAI left them. Try again in a "
            "moment.")


def _saved(kind):
    return copy.deepcopy(TASKS[kind]["saved"])


def _document(kind):
    return copy.deepcopy(TASKS[kind]["document"])


def _without_typename(o):
    if isinstance(o, dict):
        return {k: _without_typename(v) for k, v in o.items() if k != "__typename"}
    if isinstance(o, list):
        return [_without_typename(v) for v in o]
    return o


def _top_fields(doc, root):
    """The field names selected directly under `root(...)` in `doc`, one level deep."""
    text = " ".join(doc.split())
    i = text.index("{", text.index(root + "(")) + 1
    depth, fields = 0, []
    for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]*|[{}]", text[i:]):
        if tok == "{":
            depth += 1
        elif tok == "}":
            if depth == 0:
                break
            depth -= 1
        elif depth == 0:
            fields.append(tok)
    return fields


def _refusal(message, code="GRAPHQL_VALIDATION_FAILED"):
    """What the real client raises for a GraphQL answer (PixAIClient._graphql_post)."""
    errors = [{"message": message, "extensions": {"code": code}}]
    err = core.PixAIError("GraphQL error: " + json.dumps(errors))
    err.graphql_errors = errors
    return err


class _Response:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status
        self.text = json.dumps(body)
        self.content = self.text.encode()

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("HTTP {}".format(self.status_code))


class _Session:
    """A requests.Session for the real client: POSTs are answered from `answers` in order
    (the last one repeats; an exception is raised) and recorded; a GET is a saved request,
    which nothing here may send."""
    headers, cookies = {}, {}

    def __init__(self, *answers):
        self.answers = list(answers)
        self.posts = []

    def post(self, url, **kw):
        self.posts.append(SimpleNamespace(url=url, **kw))
        a = self.answers[min(len(self.posts), len(self.answers)) - 1]
        if isinstance(a, BaseException):
            raise a
        return a

    def get(self, url, **kw):
        raise AssertionError("a saved-request GET was sent: {!r}".format(kw.get("params")))


@pytest.fixture()
def no_backoff(monkeypatch):
    """Retries are counted, never waited for."""
    monkeypatch.setattr(core.time, "sleep", lambda s: None)


@pytest.fixture()
def fresh_model_caches():
    """model_name_gql and _resolve_model_preset memoise into module-level default dicts, and
    other tests use the same public version ids: start these tests empty, put them back
    after."""
    caches = [core.model_name_gql.__defaults__[0], core._resolve_model_preset.__defaults__[0]]
    kept = [dict(c) for c in caches]
    for c in caches:
        c.clear()
    yield caches[0]
    for c, k in zip(caches, kept):
        c.clear()
        c.update(k)


# =====================================================================================
# 1. THE DOCUMENTS -- named queries, the text the probe validated
# =====================================================================================

def test_the_task_document_is_the_query_the_probe_validated():
    doc = " ".join(core._TASK_DETAIL_DOC.split())
    assert doc == RECORDED["documents"]["TaskDetail"]
    assert core._is_mutation_document(doc) is False
    assert TASK_DETAIL == "TaskDetail"


@pytest.mark.parametrize("kind", KINDS)
def test_the_task_document_selects_every_key_the_saved_answer_carried(kind):
    """The saved request's answer is the reference: every top-level key it carried (bar
    __typename, which nothing reads) is selected, and nothing else."""
    selected = _top_fields(core._TASK_DETAIL_DOC, "task")
    assert len(selected) == len(set(selected))
    assert set(selected) == set(_saved(kind)) - {"__typename"}
    # and PixAI answered the document with the saved answer, less __typename (the probe)
    assert _document(kind) == _without_typename(_saved(kind))


def test_the_model_document_is_the_query_the_probe_validated():
    doc = " ".join(core._MODEL_VERSION_DOC.split())
    assert doc == RECORDED["documents"]["ModelVersion"]
    assert core._is_mutation_document(doc) is False
    assert MODEL_VERSION == "ModelVersion"
    assert {"name", "extra", "model"} <= set(_top_fields(doc, "generationModelVersion"))


def test_neither_document_keys_like_the_generation_poll():
    """The poll's own small document is anonymous and keys by its root field, `task`; both
    detail documents are named, so the fake can never hand one's answer to the other."""
    assert operation_name(core._GEN_STATUS) == "task"
    assert len({operation_name(core._GEN_STATUS), TASK_DETAIL, MODEL_VERSION}) == 3


# =====================================================================================
# 2. TASK DETAIL -- the road and its failure semantics
# =====================================================================================

def test_a_task_read_is_one_post_of_the_full_document_never_a_saved_get():
    """The mutation proof for the task road: with task_detail_gql back on the saved
    request, the GET below raises and this fails."""
    s = _Session(_Response({"data": {"task": _document("lone")}}))
    task = core.task_detail_gql(core.PixAIClient(s), "T1")
    assert task == _document("lone")
    [post] = s.posts
    assert post.url == core.API_URL
    assert post.json == {"query": core._TASK_DETAIL_DOC, "variables": {"id": "T1"}}
    assert post.timeout == 60                                  # task_detail_gql's default


def test_through_the_fake_it_is_a_query_of_the_named_document(pixai):
    pixai.on(TASK_DETAIL, {"task": _document("batch")})
    assert core.task_detail_gql(pixai, 1934) == _document("batch")
    [call] = pixai.calls
    assert (call.verb, call.op, call.variables) == ("query", "TaskDetail", {"id": "1934"})
    assert call.document == core._TASK_DETAIL_DOC
    assert (call.retries, call.timeout) == (3, 60)


def test_the_timeout_reaches_every_attempt(no_backoff):
    """The delete preview hands its remaining budget down; every attempt gets it."""
    s = _Session(requests.ConnectionError("reset"), _Response({"data": {"task": {"id": "T1"}}}))
    assert core.task_detail_gql(core.PixAIClient(s), "T1", retries=1,
                                timeout=2.5) == {"id": "T1"}
    assert [p.timeout for p in s.posts] == [2.5, 2.5]


def test_the_delete_preview_s_budget_reaches_the_read(pixai):
    pixai.on(TASK_DETAIL, {"task": {"id": "T1"}})
    core.task_detail_gql(pixai, "T1", retries=1, timeout=0.75)
    assert (pixai.calls[0].retries, pixai.calls[0].timeout) == (1, 0.75)


def test_a_5xx_is_asked_three_more_times_then_fails_soft(no_backoff, capsys):
    s = _Session(_Response({"message": "bad gateway"}, status=502))
    assert core.task_detail_gql(core.PixAIClient(s), "T5") is None
    assert len(s.posts) == 4                                  # the original + 3 retries
    out = capsys.readouterr().out
    assert "could not read task T5 back from PixAI" in out and SENTENCE in out


def test_a_5xx_that_passes_is_read_on_the_retry(no_backoff):
    s = _Session(_Response({}, status=503), _Response({"data": {"task": {"id": "T5"}}}))
    assert core.task_detail_gql(core.PixAIClient(s), "T5") == {"id": "T5"}
    assert len(s.posts) == 2


@pytest.mark.parametrize("error", [
    _refusal("Cannot query field \"stages\" on type \"Task\"."),
    core.PixAIError("401 Unauthorized -- API key missing/expired."),
    requests.ConnectionError("connection reset"),
], ids=["graphql-refusal", "401", "network"])
def test_a_failed_read_is_none_with_the_sentence_never_a_raise(pixai, capsys, error):
    pixai.fail(TASK_DETAIL, error)
    assert core.task_detail_gql(pixai, "T6") is None
    out = capsys.readouterr().out
    assert "could not read task T6 back from PixAI" in out and SENTENCE in out


def test_a_graphql_refusal_on_the_wire_is_not_retried_and_fails_soft(capsys):
    s = _Session(_Response({"errors": [{"message": "Cannot query field \"x\" on \"Task\"."}],
                            "data": None}))
    assert core.task_detail_gql(core.PixAIClient(s), "T7") is None
    assert len(s.posts) == 1
    assert SENTENCE in capsys.readouterr().out


@pytest.mark.parametrize("status", [200, 400, 403])
def test_an_answer_that_is_not_graphql_is_a_failed_read_not_a_task(status, capsys):
    """`{"message": "Forbidden"}` -- an edge's or a stale credential's own JSON -- comes back
    from the ad-hoc POST as {}. The saved road raised on it, and so does this one: None, with
    the sentence."""
    s = _Session(_Response({"message": "Forbidden"}, status=status))
    assert core.task_detail_gql(core.PixAIClient(s), "T8") is None
    assert len(s.posts) == 1
    out = capsys.readouterr().out
    assert "no task in it" in out and SENTENCE in out


def test_a_task_pixai_does_not_have_is_none_without_the_sentence(pixai, capsys):
    """`task: null` is PixAI's answer, not a failed read."""
    pixai.on(TASK_DETAIL, {"task": None})
    assert core.task_detail_gql(pixai, "T9") is None
    assert SENTENCE not in capsys.readouterr().out


def test_an_unregistered_read_is_never_swallowed_into_none():
    with pytest.raises(UnregisteredOperation, match="TaskDetail"):
        core.task_detail_gql(FakePixAI(), "T9")


# =====================================================================================
# 3. THE READERS -- PixAI's recorded document answers read as the saved answers were
# =====================================================================================

@pytest.mark.parametrize("kind", KINDS)
def test_extract_full_meta_reads_the_document_answer_as_it_read_the_saved_one(pixai, kind):
    doc, saved = _document(kind), _saved(kind)
    pixai.on(TASK_DETAIL, {"task": doc})
    task = core.task_detail_gql(pixai, doc["id"])
    assert core.extract_full_meta(task) == core.extract_full_meta(saved)
    assert core.extract_full_meta(task)["paid_credit"] == str(saved["paidCredit"])


@pytest.mark.parametrize("kind", KINDS)
def test_every_other_reader_of_a_task_reads_it_the_same(pixai, kind):
    doc, saved = _document(kind), _saved(kind)
    pixai.on(TASK_DETAIL, {"task": doc})
    task = core.task_detail_gql(pixai, doc["id"])
    for reader in (core.video_outputs, core.source_media_of_task, core.fixer_block,
                   core.task_artwork_ids, core._paid_credit_str):
        assert reader(task) == reader(saved), reader.__name__
    assert core._task_image_media(task["outputs"]) == core._task_image_media(saved["outputs"])
    assert core._prompt_helper_label(task["parameters"], task) == \
        core._prompt_helper_label(saved["parameters"], saved)
    for mid in {doc["mediaId"], *(b["mediaId"] for b in doc["outputs"].get("batch") or [])}:
        assert core._image_delete_plan(task, mid) == core._image_delete_plan(saved, mid)


def test_the_recorded_answers_exercise_what_the_readers_read():
    """So the equalities above are not equalities of empty values."""
    fm = {k: core.extract_full_meta(_document(k)) for k in KINDS}
    assert fm["batch"]["prompt_full"] and fm["batch"]["seed"]
    assert fm["lone"]["prompt_helper"] == "on (user-want-to-enable)"
    assert fm["lone"]["moderation"] == "PASS"
    assert (fm["i2v"]["derive_kind"], fm["i2v"]["video_model"]) == ("video", "v4.0.1")
    assert fm["edit"]["derive_kind"] == "edit" and fm["edit"]["model_name"] == "Edit Pro"
    assert core.video_outputs(_document("video2"))[0][0]["poster_media_id"]
    assert core.task_artwork_ids(_document("published")) == tuple(
        _document("published")["artworkIds"]) != ()
    assert len(_document("batch")["outputs"]["batch"]) == 4


def test_a_fix_reads_the_same_through_the_document(pixai):
    """No hand/face Fix existed in the probe's catalog, so this one is built by hand: the
    recorded edit with the `parameters.chat.fixer` block a Fix carries."""
    fixer = {"boxes": [{"x": 10, "y": 20, "width": 30, "height": 40, "tag": "hand"}]}
    doc, saved = _document("edit"), _saved("edit")
    doc["parameters"]["chat"]["fixer"] = copy.deepcopy(fixer)
    saved["parameters"]["chat"]["fixer"] = copy.deepcopy(fixer)
    pixai.on(TASK_DETAIL, {"task": doc})
    task = core.task_detail_gql(pixai, doc["id"])
    assert core.fixer_block(task) == fixer == core.fixer_block(saved)
    assert core.extract_full_meta(task) == core.extract_full_meta(saved)


def _batch_with_deleted(*positions):
    doc = _document("batch")
    for i in positions:
        doc["outputs"]["batch"][i]["deletedAt"] = "2026-10-26T00:00:00.000Z"
    return doc


def test_the_delete_plan_routes_the_recorded_batch_per_image(pixai):
    doc = _document("batch")
    member = doc["outputs"]["batch"][0]["mediaId"]
    pixai.on(TASK_DETAIL, {"task": doc})
    plan = core.plan_image_delete(pixai, doc["id"], member)
    assert plan.plan == "per-image" and plan.live_siblings == 3
    assert [c.verb for c in pixai.calls] == ["query"] and pixai.mutations() == 0
    assert pixai.calls[0].variables == {"id": doc["id"]}


def test_the_delete_plan_routes_the_last_live_member_whole_task(pixai):
    doc = _batch_with_deleted(1, 2, 3)
    member = doc["outputs"]["batch"][0]["mediaId"]
    pixai.on(TASK_DETAIL, {"task": doc})
    plan = core.plan_image_delete(pixai, doc["id"], member)
    assert plan.plan == "whole-task" and plan.live_siblings == 0
    assert sorted(plan.keep_media) == sorted(
        b["mediaId"] for b in doc["outputs"]["batch"][1:])
    assert pixai.mutations() == 0


def test_the_delete_plan_routes_the_recorded_lone_image_whole_task(pixai):
    doc = _document("lone")
    pixai.on(TASK_DETAIL, {"task": doc})
    assert core.plan_image_delete(pixai, doc["id"], doc["mediaId"]).plan == "whole-task"


def test_a_failed_read_plans_a_refusal(pixai):
    pixai.fail(TASK_DETAIL, requests.ConnectionError("reset"))
    plan = core.plan_image_delete(pixai, "T1", "m1")
    assert plan.plan == "refuse" and pixai.mutations() == 0


def _feed(nodes):
    return {"user": {"id": "u-test", "taskSummaries": {
        "pageInfo": {"hasNextPage": False, "hasPreviousPage": False, "endCursor": "e",
                     "startCursor": "s"},
        "edges": [{"node": n} for n in nodes]}}}


def test_the_video_sync_reads_its_task_through_the_document(pixai, tmp_path, monkeypatch):
    doc = _document("i2v")
    [out], shared = core.video_outputs(doc)
    vmid = out["video_media_id"]
    save_catalog(tmp_path / "catalog.db", [{f: "" for f in CATALOG_FIELDS} | {
        "media_id": "seed-row", "filename": "a.png"}])
    pixai.on(operation_name(core._HISTORY_PAGE_DOC), _feed([{
        "id": doc["id"], "status": "completed", "mediaId": doc["mediaId"],
        "batchMediaIds": [], "createdAt": doc["createdAt"], "promptsPreview": "p",
        "i2vProModel": "v4.0.1"}]))
    pixai.on(TASK_DETAIL, {"task": doc})
    pixai.on("media", {"media": {"id": vmid, "type": "VIDEO",
                                 "fileUrl": "https://cdn.example.invalid/v.mp4"}})

    def fake_download(session, url, stem, **kw):
        dest = stem.with_suffix(".mp4")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"mp4")
        return "ok", dest
    monkeypatch.setattr(core, "download", fake_download)
    monkeypatch.setattr(core, "resolve_media", lambda s, m: ("", {}))
    monkeypatch.setattr(core, "video_poster_thumb", lambda *a, **k: None)
    monkeypatch.setattr(core, "video_faststart", lambda p: None)
    monkeypatch.setattr(g, "make_thumbnail", lambda *a, **k: None)

    res = core.run_sync_videos(SimpleNamespace(out=str(tmp_path), token=None, page_size=250,
                                               workers=1, delay=0))
    assert res["i2v_tasks"] == 1
    assert [c.variables for c in pixai.calls_for(TASK_DETAIL)] == [{"id": doc["id"]}]
    row = {r["media_id"]: r for r in load_catalog(tmp_path / "catalog.db")}[vmid]
    assert row["paid_credit"] == str(doc["paidCredit"])
    assert row["video_model"] == "v4.0.1" and row["prompt_full"] == shared["prompt"]
    assert row["source_media_id"] == core.source_media_of_task(doc)[0]


def test_backfill_full_meta_reads_both_documents(pixai, tmp_path, fresh_model_caches):
    """--backfill-full-meta (the sync's fill-metadata step): the task document fills the row,
    the model version document names its model and fills its preset steps, and the task's
    media object fills url/width/height."""
    doc = _document("lone")
    tsubaki = MODELS["tsubaki"]
    assert doc["parameters"]["modelId"] == tsubaki["version_id"]
    db = tmp_path / "catalog.db"
    save_catalog(db, [{f: "" for f in CATALOG_FIELDS} | {
        "media_id": doc["mediaId"], "task_id": doc["id"], "filename": "a.webp"}])
    pixai.on(TASK_DETAIL, {"task": doc})
    pixai.on(MODEL_VERSION, tsubaki["document"])

    core.run_backfill_full_meta(SimpleNamespace(
        out=str(tmp_path), token=None, workers=1, delay=0.0, progress=None,
        with_loras=False, with_credit=False, with_surface=False))
    row = load_catalog(db)[0]
    assert row["prompt_full"] == doc["parameters"]["prompts"]
    assert row["model_name"] == tsubaki["name"] == "Tsubaki.2 v1"
    assert row["steps"] == "16"                     # the version's preset (issue #18)
    assert row["moderation"] == "PASS" and row["paid_credit"] == str(doc["paidCredit"])
    public = [u["url"] for u in doc["media"]["urls"] if u["variant"] == "PUBLIC"]
    assert row["url"] == public[0]
    assert (row["width"], row["height"]) == (str(doc["media"]["width"]),
                                             str(doc["media"]["height"]))
    assert {c.op for c in pixai.calls} == {TASK_DETAIL, MODEL_VERSION}
    assert all(c.verb == "query" for c in pixai.calls)


# =====================================================================================
# 4. MODEL DETAIL -- the document, and each reader's own failure semantics
# =====================================================================================

def test_a_model_read_is_one_post_of_the_full_document_never_a_saved_get(fresh_model_caches):
    """The mutation proof for the model road: with model_name_gql back on the saved request,
    the GET below raises, the lookup is a failure, and the name is not this one."""
    t = MODELS["tsubaki"]
    s = _Session(_Response({"data": t["document"]}))
    assert core.model_name_gql(core.PixAIClient(s), t["version_id"]) == "Tsubaki.2 v1"
    [post] = s.posts
    assert post.json == {"query": core._MODEL_VERSION_DOC,
                         "variables": {"id": t["version_id"]}}


@pytest.mark.parametrize("kind", ["sd", "tsubaki", "edit"])
def test_each_recorded_model_reads_as_the_saved_request_read_it(pixai, kind,
                                                                fresh_model_caches):
    m = MODELS[kind]
    pixai.on(MODEL_VERSION, m["document"])
    assert core.model_name_gql(pixai, m["version_id"], strict=True) == m["name"]
    assert core.resolve_model_base_id(pixai, m["version_id"]) == \
        m["document"]["generationModelVersion"]["model"]["id"]
    assert [(c.op, c.variables, c.retries) for c in pixai.calls] == [
        (MODEL_VERSION, {"id": m["version_id"]}, 0)] * 2


def test_the_model_ids_are_the_probe_s():
    assert [MODELS[k]["document"]["generationModelVersion"]["model"]["id"]
            for k in ("sd", "tsubaki", "edit")] == [
        "1646526355153540141", "1982880136609467518", "2006468692900798466"]


@pytest.mark.parametrize("kind,preset", [
    ("sd", {"steps": "", "sampler": "", "cfg_scale": ""}),
    ("tsubaki", {"steps": "16", "sampler": "", "cfg_scale": ""}),
    ("edit", {"steps": "", "sampler": "", "cfg_scale": ""}),
])
def test_the_preset_reads_the_recorded_extra(pixai, kind, preset, fresh_model_caches):
    m = MODELS[kind]
    pixai.on(MODEL_VERSION, m["document"])
    assert core._resolve_model_preset(pixai, m["version_id"]) == preset
    assert pixai.calls[0].retries == 0


# -- the M18 matrix, through the document on the wire ---------------------------------------

@pytest.mark.parametrize("body,what", [
    ({"errors": [{"message": "Not authenticated"}], "data": None},
     "a refusal PixAI answers at HTTP 200"),
    ({"errors": [{"message": "Internal server error"}], "data": None},
     "PixAI's passing internal error"),
    ({"data": {}}, "a reply that never carried the field asked about"),
    ({"message": "Forbidden"}, "a body that is not GraphQL at all"),
])
def test_a_lookup_that_answered_nothing_is_a_failure_memoised_as_one(body, what,
                                                                     fresh_model_caches):
    vid = "918273645591000001"
    s = _Session(_Response(body))
    client = core.PixAIClient(s)
    assert core.model_name_gql(client, vid) == vid, what        # a soft caller: the label
    assert fresh_model_caches[vid] is core._MODEL_LOOKUP_FAILED, what
    with pytest.raises(core.PixAIError, match="failed earlier this run"):
        core.model_name_gql(client, vid, strict=True)
    assert len(s.posts) == 1                                    # memoised, not re-asked


def test_strict_raises_on_a_failed_lookup(fresh_model_caches):
    s = _Session(_Response({"errors": [{"message": "nope"}], "data": None}))
    with pytest.raises(core.PixAIError, match="lookup failed"):
        core.model_name_gql(core.PixAIClient(s), "918273645591000002", strict=True)


def test_a_network_error_is_a_failure_asked_once(fresh_model_caches):
    s = _Session(requests.ConnectionError("reset"))
    vid = "918273645591000003"
    with pytest.raises(core.PixAIError, match="lookup failed"):
        core.model_name_gql(core.PixAIClient(s), vid, strict=True)
    assert len(s.posts) == 1 and fresh_model_caches[vid] is core._MODEL_LOOKUP_FAILED


def test_an_unknown_version_is_the_removed_answer_not_a_failure(pixai, fresh_model_caches):
    """What PixAI answered the probe for an id it does not have: null, HTTP 200, no errors.
    That is the one answer --relabel-removed may act on."""
    u = MODELS["unknown"]
    assert u["document"] == {"generationModelVersion": None}
    pixai.on(MODEL_VERSION, u["document"])
    assert core.model_name_gql(pixai, u["version_id"], strict=True) == u["version_id"]
    assert fresh_model_caches[u["version_id"]] == u["version_id"]


def test_the_cache_answers_a_repeat_without_asking(pixai, fresh_model_caches):
    t = MODELS["tsubaki"]
    pixai.on(MODEL_VERSION, t["document"])
    assert core.model_name_gql(pixai, t["version_id"]) == "Tsubaki.2 v1"
    assert core.model_name_gql(pixai, t["version_id"], strict=True) == "Tsubaki.2 v1"
    assert len(pixai.calls) == 1


def test_relabel_removed_acts_on_a_removed_model_and_not_on_a_failed_lookup(
        pixai, tmp_path, fresh_model_caches):
    gone, failing = "918273645591000004", "918273645591000005"
    db = tmp_path / "catalog.db"
    save_catalog(db, [{f: "" for f in CATALOG_FIELDS} | {
        "media_id": m, "filename": m + ".png", "model_id": v, "model_name": v}
        for m, v in (("m1", gone), ("m2", failing))])

    def answer(call):
        if call.variables["id"] == failing:
            raise _refusal("Not authenticated", "UNAUTHENTICATED")
        return {"generationModelVersion": None}
    pixai.on(MODEL_VERSION, answer)
    res = core.run_fix_models(SimpleNamespace(out=str(tmp_path), token=None, delay=0,
                                              relabel_removed=True))
    rows = {r["media_id"]: r for r in load_catalog(db)}
    assert rows["m1"]["model_name"] == "Unknown or removed model"
    assert rows["m2"]["model_name"] == failing
    assert res["relabeled"] == 1 and res["lookup_failed"] == 1


# -- the two soft readers ----------------------------------------------------------------------

@pytest.mark.parametrize("answer", [
    _refusal("nope"), requests.ConnectionError("reset"), RuntimeError("boom"), {},
    {"generationModelVersion": None},
], ids=["refusal", "network", "anything", "not-graphql", "removed"])
def test_the_reuse_reader_and_the_preset_fail_soft(pixai, answer, fresh_model_caches):
    if isinstance(answer, BaseException):
        pixai.fail(MODEL_VERSION, answer)
    else:
        pixai.on(MODEL_VERSION, answer)
    assert core.resolve_model_base_id(pixai, "918273645591000006") == ""
    assert core._resolve_model_preset(pixai, "918273645591000007") in (
        {}, {"steps": "", "sampler": "", "cfg_scale": ""})
    assert not core._resolve_model_preset(pixai, "918273645591000007").get("steps")


@pytest.mark.parametrize("read", [
    lambda c: core.model_name_gql(c, "918273645591000008"),
    lambda c: core.resolve_model_base_id(c, "918273645591000009"),
    lambda c: core._resolve_model_preset(c, "918273645591000010"),
], ids=["model_name_gql", "resolve_model_base_id", "_resolve_model_preset"])
def test_each_model_reader_asks_once_on_a_5xx(read, fresh_model_caches, no_backoff):
    """retries=0 for all three, as on the saved road: a name lookup drives no backoff loop."""
    s = _Session(_Response({}, status=502))
    read(core.PixAIClient(s))
    assert len(s.posts) == 1


# =====================================================================================
# 5. THE RETIRED SAVED REQUESTS -- nothing is left behind
# =====================================================================================

def test_the_retired_saved_requests_leave_nothing_behind():
    for name in ("TASK_DETAIL_HASH", "MODEL_DETAIL_HASH"):
        assert not hasattr(core, name), name
    saved_reads = re.compile(
        r"TASK_DETAIL_HASH|MODEL_DETAIL_HASH"
        r"|persisted\(\s*[\"']getTaskById[\"']"
        r"|persisted\(\s*[\"']getGenerationModelByVersionId[\"']")
    for module in sorted((REPO / "moonglade").rglob("*.py")):
        hits = saved_reads.findall(module.read_text(encoding="utf-8"))
        assert not hits, "{} still names a retired saved request: {}".format(module.name, hits)
    example = (REPO / "config.example.json").read_text(encoding="utf-8")
    assert "TASK_DETAIL_HASH" not in example and "MODEL_DETAIL_HASH" not in example
    for reader in (core.task_detail_gql, core._model_version_gql, core.model_name_gql,
                   core.resolve_model_base_id, core._resolve_model_preset,
                   core._task_detail_query):
        assert ".persisted(" not in inspect.getsource(reader), reader.__name__
