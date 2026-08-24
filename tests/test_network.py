"""Tests for network-layer functions with mocked requests.Session."""
import json
import pytest
import requests

import moonglade_backup as core
from tests.fake_pixai import FakePixAI


def _make_response(mocker, status_code=200, json_body=None, text="", raises=None):
    """Build a fake requests.Response-like mock."""
    resp = mocker.MagicMock()
    resp.status_code = status_code
    resp.text = text
    if json_body is not None:
        resp.json.return_value = json_body
    else:
        resp.json.side_effect = ValueError("no json")
    if raises:
        resp.raise_for_status.side_effect = raises
    else:
        resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# gql()
# ---------------------------------------------------------------------------

class TestGql:
    def test_returns_data_on_success(self, mock_session):
        payload = {"data": {"user": {"taskSummaries": {"edges": [], "pageInfo": {}}}}}
        mock_session.get.return_value = _make_response(
            pytest.importorskip("unittest.mock"), json_body=payload
        )
        # Re-mock properly
        mock_session.get.return_value.status_code = 200
        mock_session.get.return_value.json.return_value = payload
        result = core.gql(mock_session, {"last": 10, "userId": "u1"})
        assert result == payload["data"]

    def test_raises_on_401(self, mock_session, mocker):
        resp = _make_response(mocker, status_code=401, json_body={})
        mock_session.get.return_value = resp
        with pytest.raises(core.PixAIError, match="401"):
            core.gql(mock_session, {"last": 10, "userId": "u1"})

    def test_raises_on_non_json(self, mock_session, mocker):
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.text = "not json at all"
        resp.json.side_effect = ValueError("no json")
        resp.raise_for_status.return_value = None
        mock_session.get.return_value = resp
        with pytest.raises(core.PixAIError, match="non-JSON"):
            core.gql(mock_session, {"last": 10, "userId": "u1"})

    def test_raises_on_graphql_errors(self, mock_session, mocker):
        payload = {"errors": [{"message": "something broke"}]}
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        mock_session.get.return_value = resp
        with pytest.raises(core.PixAIError, match="GraphQL error"):
            core.gql(mock_session, {"last": 10, "userId": "u1"})

    def test_raises_persisted_query_not_found(self, mock_session, mocker):
        payload = {"errors": [{"message": "PersistedQueryNotFound"}]}
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        mock_session.get.return_value = resp
        with pytest.raises(core.PixAIError, match="hash not recognized"):
            core.gql(mock_session, {"last": 10, "userId": "u1"})


class TestPageVariablesTakesTheIdFromTheClient:
    """USER_ID retirement (transport Stage 3): `page_variables` no longer reads the
    module-level `USER_ID` global. It had no session parameter -- the one history-feed
    helper that could not see the client -- which is exactly what made that global hard to
    retire. Now the account id is passed in, sourced at each call site from the client the
    run authenticated as (`_client_of(session).user_id`). These pin that the id travels as
    an argument: two clients with different ids yield different history-feed variables, and
    the module global no longer appears in the helper's executable body."""

    def test_uses_the_passed_id_not_the_module_global(self, monkeypatch):
        # Whatever the module global happens to be, the PASSED id is what lands on the wire.
        monkeypatch.setattr(core, "USER_ID", "GLOBAL-MUST-NOT-APPEAR")
        assert core.page_variables(30, "AAA") == {"last": 30, "userId": "AAA"}
        assert core.page_variables(30, "BBB") == {"last": 30, "userId": "BBB"}

    def test_two_clients_thread_their_own_ids(self):
        # The call-site idiom is page_variables(size, _client_of(session).user_id, ...):
        # build two clients with different ids and confirm each threads its own.
        a = core.PixAIClient(object(), user_id="acct-A")
        b = core.PixAIClient(object(), user_id="acct-B")
        assert core.page_variables(30, core._client_of(a).user_id)["userId"] == "acct-A"
        assert core.page_variables(30, core._client_of(b).user_id)["userId"] == "acct-B"

    def test_before_cursor_still_threads(self):
        assert core.page_variables(50, "acct-A", before="cur-1") == {
            "last": 50, "userId": "acct-A", "before": "cur-1"}

    def test_source_no_longer_reads_the_module_global(self):
        """Structural guard: no `USER_ID` name is read in page_variables' executable body.
        The docstring names it in prose (to explain the change) and is stripped first."""
        import ast
        import inspect
        import textwrap
        fn = ast.parse(textwrap.dedent(inspect.getsource(core.page_variables))).body[0]
        body = fn.body[1:] if ast.get_docstring(fn) is not None else fn.body
        names = {n.id for stmt in body for n in ast.walk(stmt) if isinstance(n, ast.Name)}
        assert "USER_ID" not in names, (
            "page_variables reads the USER_ID module global in code again -- the account id "
            "must come from the passed-in client/param, not a module global")


# ---------------------------------------------------------------------------
# resolve_media()
# ---------------------------------------------------------------------------

class TestResolveMedia:
    def test_picks_public_variant(self, mock_session, mocker):
        obj = {
            "urls": [
                {"variant": "THUMBNAIL", "url": "https://thumb.example.com/t"},
                {"variant": "PUBLIC", "url": "https://cdn.example.com/full"},
            ],
            "width": 512,
            "height": 768,
            "type": "IMAGE",
        }
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.json.return_value = obj
        resp.raise_for_status.return_value = None
        mock_session.get.return_value = resp

        url, info = core.resolve_media(mock_session, "mid123")
        assert url == "https://cdn.example.com/full"
        assert info["width"] == 512

    def test_returns_none_on_request_error(self, mock_session, mocker):
        import requests
        mock_session.get.side_effect = requests.RequestException("timeout")
        url, info = core.resolve_media(mock_session, "mid123")
        assert url is None
        assert info == {}

    def test_falls_back_when_no_public(self, mock_session, mocker):
        obj = {
            "urls": [{"variant": "THUMBNAIL", "url": "https://thumb.example.com/t"}],
            "width": 100,
            "height": 100,
            "type": "IMAGE",
        }
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.json.return_value = obj
        resp.raise_for_status.return_value = None
        mock_session.get.return_value = resp
        url, info = core.resolve_media(mock_session, "mid456")
        assert url is not None

    def test_returns_none_on_empty_urls(self, mock_session, mocker):
        obj = {"urls": [], "width": None, "height": None, "type": ""}
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.json.return_value = obj
        resp.raise_for_status.return_value = None
        mock_session.get.return_value = resp
        url, info = core.resolve_media(mock_session, "mid789")
        assert url is None


def test_variant_detection_cluster_is_gone():
    """The --variant CLI flag was deleted in D-5, but its whole self-referential support
    cluster survived as dead code: detect_variant() looped test_variant() over
    VARIANT_CANDIDATES, test_variant() called media_url() (MEDIA_TMPL-based), and nothing
    outside that chain ever called any of the three -- run_probe (the one plausible caller)
    actually calls resolve_media() above, a separate urls-list/URL_VARIANT_PREFERENCE
    mechanism (audit 2026-07-21, O7; a prior pass's claim that run_probe still needed this
    cluster via detect_variant() was wrong, re-verified here). Zero callers anywhere,
    confirmed by a repo-wide grep -- not even a test exercised it."""
    import re
    from pathlib import Path
    dead_names = ("detect_variant", "test_variant", "media_url", "MEDIA_TMPL", "VARIANT_CANDIDATES")
    for name in dead_names:
        assert not hasattr(core, name), name
    src = (Path(__file__).resolve().parents[1] / "moonglade_backup.py").read_text(encoding="utf-8")
    for name in dead_names:
        # word-boundary, not substring -- "_media_url" (a live dict key elsewhere) must not
        # false-fail this on "media_url".
        assert not re.search(r'\b' + re.escape(name) + r'\b', src), name
    # The LIVE mechanism (resolve_media's own resolution path) must be untouched.
    assert hasattr(core, "MEDIA_BASE")
    assert hasattr(core, "resolve_media")
    assert hasattr(core, "URL_VARIANT_PREFERENCE")


# ---------------------------------------------------------------------------
# _quick_count() — verify it returns 0 on PixAIError without raising
# ---------------------------------------------------------------------------

class TestTaskDetailGql:
    """task_detail_gql now rides the transport seam (PixAIClient.persisted). It is exercised
    against a FakePixAI, the second adapter behind that seam: a registered `getTaskById`
    answer is returned; a `fail` stands in for a read that raised at the seam."""
    def test_returns_task_on_success(self, monkeypatch):
        monkeypatch.setattr(core, "TASK_DETAIL_HASH", "fakehash")
        task = {"id": "t1", "parameters": {"prompts": "full prompt"}, "outputs": {}}
        fake = FakePixAI().on("getTaskById", {"task": task})
        assert core.task_detail_gql(fake, "t1")["id"] == "t1"

    def test_returns_none_on_server_failure(self, monkeypatch):
        """A read that fails at the seam (a 500 surfaces there as an HTTPError; a 401/GraphQL
        error as a PixAIError) must come back as None, never raise -- a blip here is read
        downstream as a LOST GENERATION, and this path exists so an outage is not reported as
        'your images are gone'."""
        monkeypatch.setattr(core, "TASK_DETAIL_HASH", "fakehash")
        fake = FakePixAI().fail("getTaskById", requests.HTTPError("HTTP 500"))
        assert core.task_detail_gql(fake, "t1") is None

    def test_raises_when_hash_missing(self, monkeypatch):
        monkeypatch.setattr(core, "TASK_DETAIL_HASH", "")
        with pytest.raises(core.PixAIError, match="TASK_DETAIL_HASH"):
            core.task_detail_gql(FakePixAI(), "t1")


class TestModelNameGql:
    def test_returns_model_title_and_version(self, monkeypatch):
        monkeypatch.setattr(core, "MODEL_DETAIL_HASH", "fakehash")
        mv = {"name": "v1", "model": {"title": "Tsubaki.2"}}
        fake = FakePixAI().on("getGenerationModelByVersionId", {"generationModelVersion": mv})
        # A unique id keeps the module-level lookup cache from answering with a prior test's.
        assert core.model_name_gql(fake, "unique_model_id_test_123") == "Tsubaki.2 v1"

    def test_returns_empty_for_empty_id(self):
        assert core.model_name_gql(FakePixAI(), "") == ""
        assert core.model_name_gql(FakePixAI(), None) == ""


class TestResolveModelBaseId:
    """The reuse-prefill's version->base-model reverse lookup (2026-08-02), fixing a real
    bug found live: the catalog's model_id is a VERSION id, and feeding that straight into
    applyModelRow's base-model version listing returns nothing every time. Now rides the
    transport seam; exercised against the FakePixAI adapter."""
    def test_returns_the_base_models_own_id(self, monkeypatch):
        monkeypatch.setattr(core, "MODEL_DETAIL_HASH", "fakehash")
        mv = {"name": "v1", "model": {"id": "1982880136609467518", "title": "Tsubaki.2"}}
        fake = FakePixAI().on("getGenerationModelByVersionId", {"generationModelVersion": mv})
        assert core.resolve_model_base_id(fake, "1983308862240288769") == "1982880136609467518"

    def test_empty_id_short_circuits(self):
        assert core.resolve_model_base_id(FakePixAI(), "") == ""
        assert core.resolve_model_base_id(FakePixAI(), None) == ""

    def test_no_hash_configured_fails_soft(self, monkeypatch):
        monkeypatch.setattr(core, "MODEL_DETAIL_HASH", "")
        assert core.resolve_model_base_id(FakePixAI(), "V1") == ""

    def test_graphql_error_fails_soft_not_raises(self, monkeypatch):
        """A GraphQL error is raised at the seam (persisted turns an `errors` array into a
        PixAIError); this soft-restore path swallows it and returns '' rather than surfacing a
        wrong-id toast for a case that is not the user's mistake."""
        monkeypatch.setattr(core, "MODEL_DETAIL_HASH", "fakehash")
        fake = FakePixAI().fail("getGenerationModelByVersionId",
                                core.PixAIError("GraphQL error: nope"))
        assert core.resolve_model_base_id(fake, "V1") == ""

    def test_removed_model_fails_soft(self, monkeypatch):
        """generationModelVersion: null (the model/version is gone) -- same '' answer as
        any other unresolvable case, never a crash."""
        monkeypatch.setattr(core, "MODEL_DETAIL_HASH", "fakehash")
        fake = FakePixAI().on("getGenerationModelByVersionId", {"generationModelVersion": None})
        assert core.resolve_model_base_id(fake, "V1") == ""

    def test_network_exception_fails_soft(self, monkeypatch):
        monkeypatch.setattr(core, "MODEL_DETAIL_HASH", "fakehash")
        fake = FakePixAI().fail("getGenerationModelByVersionId", RuntimeError("boom"))
        assert core.resolve_model_base_id(fake, "V1") == ""


class TestQuickCount:
    def test_returns_zero_on_api_error(self, mock_session, mocker):
        payload = {"errors": [{"message": "INTERNAL_SERVER_ERROR"}]}
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        mock_session.get.return_value = resp
        result = core._quick_count(mock_session, page_size=10)
        assert result == 0

    def test_counts_single_page(self, mock_session, mocker):
        conn_data = {
            "edges": [
                {"node": {"mediaId": "m1", "batchMediaIds": None}},
                {"node": {"mediaId": "m2", "batchMediaIds": ["m2", "m3"]}},
            ],
            "pageInfo": {"hasPreviousPage": False, "startCursor": None},
        }
        payload = {"data": {"user": {"taskSummaries": conn_data}}}
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        mock_session.get.return_value = resp
        # edge 1 → 1 id, edge 2 → 2 ids  (m2 deduped + m3)
        result = core._quick_count(mock_session, page_size=10)
        assert result == 3


# ---------------------------------------------------------------------------
# run_download: resume index + --update early-stop (perf-critical paths)
# ---------------------------------------------------------------------------

from types import SimpleNamespace


def _dl_args(out, **kw):
    base = dict(
        out=str(out), token="t", page_size=20, max=0, delay=0,
        name_length=40, name_sep="_", organize_live=False,
        convert=None, jpeg_quality=92, jpeg_bg="white", keep_webp=False,
        collect_only=False, full_meta=False, update=False, update_grace=2,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _page(mid, has_prev, cursor=""):
    node = {"id": "task_" + mid, "mediaId": mid, "batchMediaIds": [],
            "createdAt": "2024-01-01T00:00:00", "promptsPreview": "p", "status": "ok"}
    return {"user": {"taskSummaries": {
        "edges": [{"node": node}],
        "pageInfo": {"hasPreviousPage": has_prev, "startCursor": cursor}}}}


def _patch_download_layer(mocker):
    mocker.patch.object(core, "_make_session", return_value=mocker.MagicMock())
    mocker.patch.object(core, "_quick_count", return_value=3)
    mocker.patch.object(core, "resolve_media",
                        return_value=("http://x/img", {"width": "1", "height": "1"}))

    def fake_download(session, url, stem, **kw):
        dest = stem.with_suffix(".webp")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"img")
        return ("ok", dest)
    return mocker.patch.object(core, "download", side_effect=fake_download)


def test_resume_skips_on_disk_without_redownload(tmp_path, mocker):
    (tmp_path / "images").mkdir(parents=True)
    (tmp_path / "images" / "x_known.webp").write_bytes(b"img")
    dl = _patch_download_layer(mocker)
    mocker.patch.object(core, "gql", side_effect=[_page("new1", True, "c1"),
                                                  _page("known", False)])

    core.run_download(_dl_args(tmp_path))

    names = [str(c.args[2]) for c in dl.call_args_list]  # stem is 3rd positional
    assert any("new1" in n for n in names)
    assert not any("known" in n for n in names)


def test_resume_ignores_quarantined_deleted_file(tmp_path, mocker):
    """B11 (audit 2026-07-21): the startup disk-index walk's skip_dirs never learned
    about _deleted/ (only 'gallery'/'_duplicates') -- so a media_id purged locally
    (moved to _deleted/ by purge_media_local) is still indexed as 'already done' and
    resume/--update silently never re-downloads it, exactly as if it were a live file."""
    from moonglade_gallery import DELETED_DIRNAME
    qdir = tmp_path / DELETED_DIRNAME
    qdir.mkdir(parents=True)
    (qdir / "x_known.webp").write_bytes(b"img")
    dl = _patch_download_layer(mocker)
    mocker.patch.object(core, "gql", side_effect=[_page("known", False)])

    core.run_download(_dl_args(tmp_path))

    names = [str(c.args[2]) for c in dl.call_args_list]
    assert any("known" in n for n in names), (
        "a file quarantined under _deleted/ was indexed as 'already done' and "
        "never re-downloaded")


def test_resume_does_not_skip_a_zero_byte_file(tmp_path, mocker):
    """Invariant 3, audit 2026-07-21: the startup disk index used to count ANY file
    with a matching extension as 'already done', including a 0-byte one left behind by
    an interrupted download. That media_id then went into on_disk_by_mid and was
    filtered out of every future page -- permanently, since no --update/--sync ever
    re-attempts a media_id the index already claims to have. Mirrors the test above
    exactly, except the on-disk file for 'known' is empty: it must now be treated the
    SAME as if nothing were on disk at all, i.e. download() must be called for it."""
    (tmp_path / "images").mkdir(parents=True)
    (tmp_path / "images" / "x_known.webp").write_bytes(b"")   # 0 bytes -- interrupted
    dl = _patch_download_layer(mocker)
    mocker.patch.object(core, "gql", side_effect=[_page("new1", True, "c1"),
                                                  _page("known", False)])

    core.run_download(_dl_args(tmp_path))

    names = [str(c.args[2]) for c in dl.call_args_list]
    assert any("new1" in n for n in names)
    assert any("known" in n for n in names), (
        "the zero-byte file was indexed as 'already done' and never re-downloaded")


def test_run_download_returns_its_fail_count(tmp_path, mocker, capsys, pixai):
    """D-4: run_download's own tally (dl['fail'] etc.) never reached any caller -- no
    return statement meant a partial-failure run was indistinguishable from a clean one
    to everything downstream (the CLI job log, the Panel). Also locks in the louder
    console notice that replaces the old easy-to-miss one-liner."""
    mocker.patch.object(core, "_quick_count", return_value=2)
    mocker.patch.object(core, "resolve_media",
                        return_value=("http://x/img", {"width": "1", "height": "1"}))

    def fake_download(session, url, stem, **kw):
        if "bad" in str(stem):
            return ("fail", None)
        dest = stem.with_suffix(".webp")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"img")
        return ("ok", dest)
    mocker.patch.object(core, "download", side_effect=fake_download)
    mocker.patch.object(core, "gql", side_effect=[_page("bad", True, "c1"), _page("good", False)])

    result = core.run_download(_dl_args(tmp_path))

    assert result is not None, "run_download must return its counts, not None"
    assert result["fail"] == 1
    assert result["ok"] == 1
    out = capsys.readouterr().out
    assert "FINISHED WITH ERRORS" in out
    assert "Exit code is still 0 by design" in out


class TestDownloadNeverWritesAZeroByteFile:
    """The other half of invariant 3: even if the resume index is fixed, download()
    itself must not CREATE a zero-byte file in the first place -- a 200 response with
    an empty/truncated body must not be promoted from the .part file to the real
    filename, or the very next run's resume index (now correctly fixed) would just
    find it and retry forever without the underlying cause (a bad response) ever
    being reported as a failure."""
    def test_empty_response_body_is_treated_as_a_failure(self, mock_session, mocker, tmp_path):
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.headers = {"Content-Type": "image/webp"}
        resp.raise_for_status.return_value = None
        resp.iter_content.return_value = iter([])   # zero chunks -> nbytes stays 0
        # requests.Response's context manager returns itself; a bare MagicMock's
        # auto-generated __enter__ would instead hand the code a SECOND, unconfigured
        # mock as `r`, silently detaching every attribute set above from what download()
        # actually reads.
        resp.__enter__ = mocker.Mock(return_value=resp)
        resp.__exit__ = mocker.Mock(return_value=False)
        mock_session.get.return_value = resp

        status, path = core.download(mock_session, "http://x/img", tmp_path / "stem",
                                     retries=0)

        assert status == "fail"
        assert path is None
        assert not (tmp_path / "stem.webp").exists(), (
            "an empty response body was promoted to a real file on disk")
        assert not list(tmp_path.glob("*.part")), "a stray .part file was left behind"


class TestDownloadVerifiesContentLength:
    """The mid-stream cousin of the zero-byte guard above (owner field-test 2026-07-23,
    'Videos corrupt on collect'): a connection cut MID-body can end the chunk stream
    cleanly, so download() wrote fewer bytes than the server's Content-Length promised
    and still promoted the .part -- a permanent truncated file, invisible to resume
    forever after. A short body must now fail the attempt through the same
    retry/backoff path as any other network error. Only enforced when the body is not
    content-encoded: requests decompresses gzip/br inside iter_content, so the header
    counts different bytes than we write."""
    @staticmethod
    def _resp(mocker, headers, chunks):
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.headers = headers
        resp.raise_for_status.return_value = None
        resp.iter_content.return_value = iter(chunks)
        resp.__enter__ = mocker.Mock(return_value=resp)
        resp.__exit__ = mocker.Mock(return_value=False)
        return resp

    def test_short_body_is_never_promoted_and_rides_the_retry_path(
            self, mock_session, mocker, tmp_path):
        mocker.patch("time.sleep")                  # retry backoff -- don't really wait
        vid = {"Content-Type": "video/mp4", "Content-Length": "1000"}
        short = self._resp(mocker, vid, [b"x" * 400])   # cut mid-body, stream ends cleanly
        good = self._resp(mocker, vid, [b"y" * 1000])
        mock_session.get.side_effect = [short, good]

        status, path = core.download(mock_session, "http://x/vid", tmp_path / "stem",
                                     retries=1)

        assert status == "ok"
        assert path is not None and path.read_bytes() == b"y" * 1000, (
            "a short body was promoted instead of retried")
        assert not list(tmp_path.glob("*.part"))
        assert mock_session.get.call_count == 2     # attempt 1 failed short, attempt 2 won

    def test_short_body_with_retries_exhausted_is_a_fail_not_a_file(
            self, mock_session, mocker, tmp_path):
        short = self._resp(mocker, {"Content-Type": "video/mp4", "Content-Length": "1000"},
                           [b"x" * 400])
        mock_session.get.return_value = short

        status, path = core.download(mock_session, "http://x/vid", tmp_path / "stem",
                                     retries=0)

        assert status == "fail" and path is None
        assert not list(tmp_path.glob("stem*")), (
            "a truncated body left a permanent file on disk")

    def test_content_encoded_body_is_exempt_from_the_check(
            self, mock_session, mocker, tmp_path):
        # gzip: iter_content yields DECOMPRESSED bytes, so 400 written vs 1000 promised
        # is normal, not truncation -- must not false-fail the download.
        resp = self._resp(mocker, {"Content-Type": "image/webp", "Content-Length": "1000",
                                   "Content-Encoding": "gzip"}, [b"z" * 400])
        mock_session.get.return_value = resp

        status, path = core.download(mock_session, "http://x/img", tmp_path / "stem",
                                     retries=0)

        assert status == "ok" and path is not None and path.stat().st_size == 400


def test_update_mode_stops_early(tmp_path, mocker):
    (tmp_path / "images").mkdir(parents=True)
    (tmp_path / "images" / "x_old.webp").write_bytes(b"img")
    _patch_download_layer(mocker)
    gql = mocker.patch.object(core, "gql", side_effect=[
        _page("fresh", True, "c1"), _page("old", True, "c2"),
        _page("should_not_fetch", False)])

    core.run_download(_dl_args(tmp_path, update=True, update_grace=1))

    assert gql.call_count == 2  # page3 never requested


def test_is_video_task_node():
    assert core._is_video_task_node({"i2vProModel": "v4.0.1"}) is True
    assert core._is_video_task_node({"i2vProModel": ""}) is False   # empty = not a video task
    assert core._is_video_task_node({"mediaId": "x"}) is False
    assert core._is_video_task_node({}) is False


def test_download_skips_video_task_posters(tmp_path, mocker):
    """A video task's node (i2vProModel set) must NOT be catalogued as an image -- its
    mediaId is the video's poster still (handled by run_sync_videos). Regression for the
    138 phantom poster-image duplicate rows."""
    from moonglade_gallery import load_catalog
    dl = _patch_download_layer(mocker)
    img_node = {"id": "task_img", "mediaId": "IMG1", "batchMediaIds": [],
                "createdAt": "2024-01-01T00:00:00", "promptsPreview": "p", "status": "ok"}
    vid_node = {"id": "task_vid", "mediaId": "POSTER1", "batchMediaIds": [],
                "createdAt": "2024-01-01T00:00:00", "promptsPreview": "p", "status": "ok",
                "i2vProModel": "v4.0.1"}                       # <-- marks it a video task
    page = {"user": {"taskSummaries": {
        "edges": [{"node": img_node}, {"node": vid_node}],
        "pageInfo": {"hasPreviousPage": False, "startCursor": ""}}}}
    mocker.patch.object(core, "gql", side_effect=[page])

    core.run_download(_dl_args(tmp_path))

    stems = [str(c.args[2]) for c in dl.call_args_list]        # stem is the 3rd positional
    assert any("IMG1" in s for s in stems)                     # the image WAS fetched
    assert not any("POSTER1" in s for s in stems)              # the video poster was NOT
    mids = {r["media_id"] for r in load_catalog(tmp_path / "catalog.db")}
    assert "IMG1" in mids and "POSTER1" not in mids            # no phantom poster-image row


def test_populated_catalog_skips_network_count(tmp_path, mocker):
    # With a populated catalog, the progress total comes from the catalog size --
    # no full-history _quick_count network walk.
    from moonglade_gallery import save_catalog, CATALOG_FIELDS
    db = tmp_path / "catalog.db"
    save_catalog(db, [{f: "" for f in CATALOG_FIELDS} |
                      {"media_id": "old", "filename": "x_old.webp"}])
    (tmp_path / "images").mkdir(parents=True)
    (tmp_path / "images" / "x_old.webp").write_bytes(b"img")
    _patch_download_layer(mocker)
    qc = mocker.patch.object(core, "_quick_count", return_value=999)
    mocker.patch.object(core, "gql", side_effect=[_page("old", False)])

    core.run_download(_dl_args(tmp_path, update=True, update_grace=1))

    assert qc.call_count == 0  # catalog estimate used, no network pre-count


def test_parallel_workers_download_new_skip_known(tmp_path, mocker):
    # workers>1 path: new items fetched concurrently, on-disk items skipped.
    (tmp_path / "images").mkdir(parents=True)
    (tmp_path / "images" / "x_known.webp").write_bytes(b"img")
    dl = _patch_download_layer(mocker)

    def _multi_page(mids, has_prev, cursor=""):
        edges = [{"node": {"id": "t_" + m, "mediaId": m, "batchMediaIds": [],
                           "createdAt": "2024-01-01", "promptsPreview": "p", "status": "ok"}}
                 for m in mids]
        return {"user": {"taskSummaries": {
            "edges": edges, "pageInfo": {"hasPreviousPage": has_prev, "startCursor": cursor}}}}

    mocker.patch.object(core, "gql", side_effect=[_multi_page(["a", "b", "known"], False)])
    core.run_download(_dl_args(tmp_path, workers=4))

    names = [str(c.args[2]) for c in dl.call_args_list]
    assert sum("known" in n for n in names) == 0          # on-disk skipped
    assert any("_a" in n for n in names) and any("_b" in n for n in names)  # both new fetched


def test_update_and_workers_compose(tmp_path, mocker):
    # --update (early-stop) + --workers (parallel) together: new items fetched
    # concurrently at the top, then stop once a page is fully on disk.
    (tmp_path / "images").mkdir(parents=True)
    (tmp_path / "images" / "x_old.webp").write_bytes(b"img")
    dl = _patch_download_layer(mocker)

    def _mp(mids, has_prev, c=""):
        edges = [{"node": {"id": "t_" + m, "mediaId": m, "batchMediaIds": [],
                           "createdAt": "2024-01-01", "promptsPreview": "p", "status": "ok"}}
                 for m in mids]
        return {"user": {"taskSummaries": {
            "edges": edges, "pageInfo": {"hasPreviousPage": has_prev, "startCursor": c}}}}

    gql = mocker.patch.object(core, "gql", side_effect=[
        _mp(["new1", "new2"], True, "c1"), _mp(["old"], True, "c2"),
        _mp(["should_not_fetch"], False)])

    core.run_download(_dl_args(tmp_path, update=True, update_grace=1, workers=4))

    names = [str(c.args[2]) for c in dl.call_args_list]
    assert gql.call_count == 2                                   # stopped before page 3
    assert any("new1" in n for n in names) and any("new2" in n for n in names)
    assert not any("old" in n for n in names)                   # on-disk skipped


def test_extract_artwork_meta():
    node = {"id": "aw1", "mediaId": "m1", "title": "Lollipop Elf",
            "visibility": "PUBLIC", "isNsfw": True, "isSensitive": True, "likedCount": 5,
            "commentCount": 2, "aesScore": 7.5,
            "tacks": [{"codeName": "contest_x", "displayName": "ContestX"},
                      {"displayName": "tag2"}],
            "extra": {"imageBlurHash": "U8A]jP%L",
                      "nsfwPredict": {"porn": 0.0510777, "hentai": 0.913348, "neutral": 0.01}}}
    m = core.extract_artwork_meta(node)
    assert m["media_id"] == "m1" and m["artwork_id"] == "aw1"
    assert m["title"] == "Lollipop Elf"
    assert m["is_published"] == "1" and m["is_nsfw"] == "1" and m["is_sensitive"] == "1"
    assert m["liked_count"] == "5" and m["comment_count"] == "2"
    assert m["art_tags"] == "ContestX, tag2"
    # from the free `extra` block: blurhash placeholder + rounded per-category NSFW scores
    assert m["blurhash"] == "U8A]jP%L"
    assert m["nsfw_scores"] == '{"porn":0.051,"hentai":0.913,"neutral":0.01}'


def test_extract_artwork_meta_no_extra():
    # a node without an `extra` block leaves the new fields blank (never raises)
    m = core.extract_artwork_meta({"id": "a", "mediaId": "m", "visibility": "PRIVATE"})
    assert m["blurhash"] == "" and m["nsfw_scores"] == "" and m["is_published"] == "0" and m["is_sensitive"] == "0"


def test_sync_artworks_merges_by_media_id(tmp_path, mocker, pixai):
    from moonglade_gallery import save_catalog, CATALOG_FIELDS, load_catalog
    db = tmp_path / "catalog.db"
    save_catalog(db, [{f: "" for f in CATALOG_FIELDS} |
                      {"media_id": "m1", "filename": "x_m1.png"}])
    mocker.patch.object(core, "USER_ID", "u1")
    conn = {"edges": [{"node": {"id": "aw1", "mediaId": "m1", "title": "My Art",
                                "visibility": "PUBLIC", "isNsfw": False,
                                "likedCount": 3, "commentCount": 1,
                                "aesScore": 6.0, "tacks": []}}],
            "pageInfo": {"hasPreviousPage": False}}
    mocker.patch.object(core, "artwork_list_gql", return_value=conn)

    res = core.run_sync_artworks(SimpleNamespace(out=str(tmp_path), token=None, delay=0))

    assert res["artworks"] == 1 and res["matched"] == 1
    row = {r["media_id"]: r for r in load_catalog(db)}["m1"]
    assert row["title"] == "My Art" and row["liked_count"] == "3"
    assert row["is_published"] == "1" and row["artwork_id"] == "aw1"


def test_sync_artworks_tags_the_animation_video_row(tmp_path, mocker, pixai):
    """#20: an animation's catalog row is keyed by its MP4's media_id (is_video='1'), while the
    artwork node carries the still as `mediaId` and the mp4 as `videoMediaId`. The sync must tag
    the video row via videoMediaId, or the Animations tab (WHERE artwork_id!='') stays empty."""
    from types import SimpleNamespace
    from moonglade_gallery import save_catalog, CATALOG_FIELDS, load_catalog
    db = tmp_path / "catalog.db"
    # the ONLY local row is the video (the mp4); no separate poster row was downloaded
    save_catalog(db, [{f: "" for f in CATALOG_FIELDS} |
                      {"media_id": "vid1", "filename": "x_vid1.mp4", "is_video": "1"}])
    mocker.patch.object(core, "USER_ID", "u1")
    conn = {"edges": [{"node": {"id": "aw9", "mediaId": "poster1", "videoMediaId": "vid1",
                                "title": "My Animation", "visibility": "PUBLIC",
                                "isNsfw": False, "likedCount": 4, "commentCount": 0,
                                "aesScore": 6.0, "tacks": []}}],
            "pageInfo": {"hasPreviousPage": False}}
    mocker.patch.object(core, "artwork_list_gql", return_value=conn)

    res = core.run_sync_artworks(SimpleNamespace(out=str(tmp_path), token=None, delay=0))

    assert res["matched"] == 1                        # the video row matched via videoMediaId
    row = {r["media_id"]: r for r in load_catalog(db)}["vid1"]
    assert row["artwork_id"] == "aw9"                 # tagged -> now visible in Animations
    assert row["title"] == "My Animation" and row["is_video"] == "1"   # own media_id/flag kept


def test_sync_artworks_resolves_userid_via_session(tmp_path, mocker):
    """A config with NO USER_ID must NOT hard-fail: _make_session auto-resolves it from the API
    key, so run_sync_artworks builds the session FIRST, then proceeds. Regression for the web
    Control Panel error 'USER_ID missing from config.json'."""
    from types import SimpleNamespace
    from moonglade_gallery import save_catalog, CATALOG_FIELDS
    db = tmp_path / "catalog.db"
    save_catalog(db, [{f: "" for f in CATALOG_FIELDS} | {"media_id": "m1", "filename": "x_m1.png"}])
    mocker.patch.object(core, "USER_ID", "")                 # config has no user id
    def fake_session(tok=None):
        core.USER_ID = "resolved-99"                          # _make_session resolves it live
        return mocker.MagicMock()
    mocker.patch.object(core, "_make_session", side_effect=fake_session)
    mocker.patch.object(core, "artwork_list_gql",
                        return_value={"edges": [], "pageInfo": {"hasPreviousPage": False}})
    res = core.run_sync_artworks(SimpleNamespace(out=str(tmp_path), token=None, delay=0))
    assert res["artworks"] == 0 and core.USER_ID == "resolved-99"   # ran instead of raising


def test_artwork_detail_hash_config_key_is_gone():
    """ARTWORK_DETAIL_HASH was read from config.json with a baked-in default, same shape as
    its sibling ARTWORK_LIST_HASH just above -- but unlike that sibling (used by
    artwork_list_gql/run_sync_artworks right here in this file), nothing anywhere ever reads
    ARTWORK_DETAIL_HASH (audit 2026-07-21, schema-config-drift appendix row: "read from config
    and given a baked default, then never used anywhere"). config.example.json documented it
    as a settable override, so that mention goes too -- its live sibling stays."""
    import json
    from pathlib import Path
    assert not hasattr(core, "ARTWORK_DETAIL_HASH")
    assert hasattr(core, "ARTWORK_LIST_HASH")   # the live sibling must be untouched
    repo_root = Path(__file__).resolve().parents[1]
    src = (repo_root / "moonglade_backup.py").read_text(encoding="utf-8")
    assert "ARTWORK_DETAIL_HASH" not in src
    example_cfg = json.loads((repo_root / "config.example.json").read_text(encoding="utf-8"))
    assert "ARTWORK_DETAIL_HASH" not in example_cfg
    assert "ARTWORK_LIST_HASH" in example_cfg   # sibling override documentation stays


def test_sync_artworks_with_videos_skips_already_downloaded(tmp_path, mocker, pixai):
    """B16 (audit 2026-07-21): already_downloaded() gates --sync-artworks --with-videos'
    resume check on find_files_for_media_id's default _IMAGE_EXTS-only matcher -- no
    .mp4 ever matches, so it's a guaranteed-False no-op for videos. Every video fired a
    full resolve_media round trip on every single run, even one already on disk."""
    from moonglade_gallery import save_catalog, CATALOG_FIELDS
    save_catalog(tmp_path / "catalog.db", [{f: "" for f in CATALOG_FIELDS} |
                                           {"media_id": "unrelated", "filename": "x_unrelated.png"}])
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / "clip_V1.mp4").write_bytes(b"already here")
    mocker.patch.object(core, "USER_ID", "u1")
    conn = {"edges": [{"node": {"id": "aw1", "mediaId": "", "title": "Anim",
                                "visibility": "PUBLIC", "isNsfw": False,
                                "likedCount": 0, "commentCount": 0, "aesScore": 0,
                                "tacks": [], "videoMediaId": "V1"}}],
            "pageInfo": {"hasPreviousPage": False}}
    mocker.patch.object(core, "artwork_list_gql", return_value=conn)
    # Mocked with a well-formed return (not a bare MagicMock): if the bug fires and
    # this DOES get called, _fetch_video must still complete cleanly so the failure
    # shows up as the assertion below, not an incidental unpack/network crash.
    resolve = mocker.patch.object(core, "resolve_media",
                                  return_value=("http://example.com/v.mp4", {"width": "1"}))
    mocker.patch.object(core, "download",
                        return_value=("ok", tmp_path / "videos" / "clip_V1.mp4"))

    res = core.run_sync_artworks(SimpleNamespace(out=str(tmp_path), token=None, delay=0,
                                                 with_videos=True, workers=1))

    resolve.assert_not_called()
    assert res["videos"] == 1


def test_sync_artworks_flags_incomplete_pagination_as_a_failure(tmp_path, mocker, pixai):
    """B15: unlike gql() (retries 4x, then RAISES), artwork_list_gql swallows a
    RequestException/non-200/bad-JSON with NO retry and just returns None (see its
    own docstring: 'Returns the Relay connection dict ... or None on failure'). On
    page 1 that correctly raises; on page 2+ the pagination loop treats it EXACTLY
    like a legitimate 'no more pages' and breaks silently -- the run then reports a
    complete-looking total for what is actually a partial sync. FAILS before the
    fix: run_sync_artworks's return dict has no 'fail' key at all, so res['fail']
    raises KeyError."""
    from moonglade_gallery import save_catalog, CATALOG_FIELDS
    db = tmp_path / "catalog.db"
    save_catalog(db, [{f: "" for f in CATALOG_FIELDS} | {"media_id": "m1", "filename": "x_m1.png"}])
    mocker.patch.object(core, "USER_ID", "u1")
    page1 = {"edges": [{"node": {"id": "aw1", "mediaId": "m1", "title": "Page1 Art",
                                 "visibility": "PUBLIC", "isNsfw": False,
                                 "likedCount": 1, "commentCount": 0}}],
             "pageInfo": {"hasPreviousPage": True, "startCursor": "cursor2"}}
    # Page 1 succeeds; page 2's fetch "fails" (artwork_list_gql's own failure mode: None).
    mocker.patch.object(core, "artwork_list_gql", side_effect=[page1, None])

    res = core.run_sync_artworks(SimpleNamespace(out=str(tmp_path), token=None, delay=0))

    assert res["artworks"] == 1                 # page 1's artwork still landed -- not discarded
    assert res["fail"] == 1                      # but the early stop is now visible, not silent


def test_sync_artworks_counts_failed_video_downloads_as_a_failure(tmp_path, mocker, pixai):
    """B15: a video that fails to download after retries (download() returns
    ('fail', None), the same status run_download's own dl['fail'] counts) must be
    just as visible here -- currently it's silently absorbed into a lower
    'Videos saved/present: N of M' console tally with no return-value or job-status
    signal at all. FAILS before the fix for the same reason as the pagination
    test: no 'fail' key in the return dict."""
    from moonglade_gallery import save_catalog, CATALOG_FIELDS
    db = tmp_path / "catalog.db"
    save_catalog(db, [{f: "" for f in CATALOG_FIELDS} | {"media_id": "m1", "filename": "x_m1.png"}])
    mocker.patch.object(core, "USER_ID", "u1")
    conn = {"edges": [{"node": {"id": "aw1", "mediaId": "m1", "title": "Animated",
                                "visibility": "PUBLIC", "isNsfw": False,
                                "likedCount": 0, "commentCount": 0,
                                "videoMediaId": "vid1"}}],
            "pageInfo": {"hasPreviousPage": False}}
    mocker.patch.object(core, "artwork_list_gql", return_value=conn)
    # already_downloaded_video, not already_downloaded -- B16 (merged separately, same
    # sweep) redirected this call site to the video-aware matcher.
    mocker.patch.object(core, "already_downloaded_video", return_value=None)
    mocker.patch.object(core, "resolve_media", return_value=("https://x/vid1.mp4", {}))
    mocker.patch.object(core, "download", return_value=("fail", None))

    res = core.run_sync_artworks(SimpleNamespace(
        out=str(tmp_path), token=None, delay=0, with_videos=True, workers=1))

    assert res["videos"] == 0                    # the failed video was not counted as saved
    assert res["fail"] == 1                       # and the failure is now visible


def test_resolve_loras(mocker):
    mocker.patch.object(core, "model_name_gql",
                        side_effect=lambda s, vid: {"111": "DetailLora", "222": "222"}.get(str(vid), str(vid)))
    task = {"parameters": {"lora": {"111": 0.7, "222": 0.5}}}
    out = core.resolve_loras(mocker.MagicMock(), task)
    assert "DetailLora:0.7" in out
    assert "lora 222:0.5" in out          # unresolved id gets a "lora <id>" label
    assert core.resolve_loras(mocker.MagicMock(), {"parameters": {}}) == ""


def test_needs_model_fix():
    # numeric model_name with matching id -> needs fixing
    assert core._needs_model_fix({"model_id": "123", "model_name": "123"}) == "123"
    # blank name but has id -> needs fixing
    assert core._needs_model_fix({"model_id": "456", "model_name": ""}) == "456"
    # model_name itself is the numeric id, no model_id column -> use it
    assert core._needs_model_fix({"model_id": "", "model_name": "789"}) == "789"
    # already readable -> no fix
    assert core._needs_model_fix({"model_id": "123", "model_name": "Tsubaki v1"}) == ""
    # nothing to go on -> no fix
    assert core._needs_model_fix({"model_id": "", "model_name": ""}) == ""


def test_fix_models_resolves_numeric_names(tmp_path, mocker, pixai):
    from moonglade_gallery import save_catalog, CATALOG_FIELDS, load_catalog
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "m1", "filename": "a.png",
                                           "model_id": "999", "model_name": "999"},
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "m2", "filename": "b.png",
                                           "model_id": "999", "model_name": "999"},
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "m3", "filename": "c.png",
                                           "model_id": "111", "model_name": "Already Named"},
    ])
    mocker.patch.object(core, "model_name_gql", return_value="Tsubaki.2 v1")

    res = core.run_fix_models(SimpleNamespace(out=str(tmp_path), token=None, delay=0))

    assert res["fixed"] == 2          # both m1/m2 (model 999) fixed
    rows = {r["media_id"]: r for r in load_catalog(db)}
    assert rows["m1"]["model_name"] == "Tsubaki.2 v1"
    assert rows["m3"]["model_name"] == "Already Named"   # untouched


def test_sync_runs_all_three_steps_in_order(tmp_path, mocker, monkeypatch):
    """Control Panel consolidation: --sync folds fix-models and the metadata backfill in after
    the pull (previously just 2 steps), so a synced catalog is always fully labeled without a
    separate click/action. Backfill precedes fix-models on purpose (audit 2026-08-15): backfill
    fills model_id for rows that never saw detail, so fix-models then relabels them same-run."""
    calls = []
    seen = {}
    mocker.patch.object(core, "run_download",
                        side_effect=lambda a, progress=None: calls.append("download") or seen.__setitem__("dl_progress", progress))
    mocker.patch.object(core, "run_fix_models", side_effect=lambda a: calls.append("fix_models"))
    mocker.patch.object(core, "run_backfill_full_meta", side_effect=lambda a: calls.append("backfill"))
    monkeypatch.setattr("sys.argv", ["prog", "--sync", "--out", str(tmp_path)])

    core.main()

    assert calls == ["download", "backfill", "fix_models"]
    # the download step must receive args.progress (main() sets it via _make_progress),
    # else the panel's progress bar is blank during the download -- the thing the owner hit.
    assert callable(seen["dl_progress"])


def test_progress_counter_does_not_double_count(tmp_path, mocker):
    # Regression: the progress counter must NOT be seeded with the on-disk count
    # (that double-counted already-downloaded items and overshot 100%).
    from moonglade_gallery import save_catalog, CATALOG_FIELDS
    db = tmp_path / "catalog.db"
    save_catalog(db, [{f: "" for f in CATALOG_FIELDS} |
                      {"media_id": m, "filename": "x_%s.webp" % m} for m in ("a", "b")])
    (tmp_path / "images").mkdir(parents=True)
    for m in ("a", "b"):
        (tmp_path / "images" / ("x_%s.webp" % m)).write_bytes(b"img")
    _patch_download_layer(mocker)
    edges = [{"node": {"id": "t_" + m, "mediaId": m, "batchMediaIds": [],
                       "createdAt": "2024-01-01", "promptsPreview": "p", "status": "ok"}}
             for m in ("a", "b")]
    mocker.patch.object(core, "gql", side_effect=[
        {"user": {"taskSummaries": {"edges": edges,
                                    "pageInfo": {"hasPreviousPage": False}}}}])

    seen = []
    core.run_download(_dl_args(tmp_path), progress=lambda d, t, n: seen.append((d, t)))

    max_done = max(d for d, t in seen)
    total = seen[-1][1]
    assert max_done <= total          # never overshoots the denominator
    assert max_done == 2              # two items walked, counted once each


# ---------------------------------------------------------------------------
# gql_adhoc + account_info (ad-hoc GraphQL path -- no persisted hash)
# ---------------------------------------------------------------------------

def test_gql_adhoc_returns_data(mocker):
    sess = mocker.MagicMock()
    sess.post.return_value = _make_response(mocker, 200, {"data": {"me": {"id": "1"}}})
    assert core.gql_adhoc(sess, "query{ me { id } }") == {"me": {"id": "1"}}


def test_gql_adhoc_raises_on_graphql_error(mocker):
    sess = mocker.MagicMock()
    sess.post.return_value = _make_response(mocker, 200, {"errors": [{"message": "nope"}]})
    with pytest.raises(core.PixAIError):
        core.gql_adhoc(sess, "query{ bad }")


def test_account_info_parses_me(pixai):
    pixai.on("me", {"me": {
        "id": "42", "quotaAmount": 21290, "tasks": {"totalCount": 19623},
        "followerCount": 30, "followingCount": 4,
        "membership": {"membershipId": "membership-plus", "tier": 2,
                       "privilege": {"dailyClaimAdded": 10000, "professionalMode": True}},
        "subscription": {"planId": "membership-plus", "status": "active",
                         "cancelAtPeriodEnd": True, "endAt": "2026-07-08T00:00:00Z"}}})
    me = core.account_info(pixai)
    assert me["quotaAmount"] == 21290
    assert me["membership"]["membershipId"] == "membership-plus"
    assert me["tasks"]["totalCount"] == 19623      # server's lifetime task count (backup coverage)
    assert me["followerCount"] == 30


def test_account_query_does_not_ask_for_roles(pixai):
    """This test used to assert the OPPOSITE, and that is why the account query shipped broken.

    It checked `"roles" in _ACCOUNT_QUERY` and then mocked a response containing roles -- so it
    passed while the real query was rejected outright by PixAI. `me.roles` is a
    `RoleConnection`; selected bare it fails GraphQL VALIDATION, which fails the whole
    document, so account_info() returned nothing and the credits chip read 0/0 while the
    membership-derived LoRA cap, the --account dashboard and the first-run setup wizard's key
    validation all silently lost their data too.

    A mocked response can never catch that class of bug: the failure is server-side schema
    validation, and the mock replaces exactly the thing that would have failed. If roles are
    ever genuinely wanted, query them SEPARATELY with a subfield selection so a mistake there
    cannot take the account read down with it.
    """
    assert "roles" not in core._ACCOUNT_QUERY, (
        "roles is back in the account query -- bare, it fails validation and takes credits, "
        "membership, the LoRA cap and the setup wizard with it")
    pixai.on("me", {"me": {"id": "42", "quotaAmount": 1850640}})
    assert core.account_info(pixai)["quotaAmount"] == 1850640

def test_account_info_empty_on_error(pixai):
    pixai.fail("me", core.PixAIError("boom"))
    assert core.account_info(pixai) == {}                       # soft-fail (web relies on this)
    with __import__("pytest").raises(core.PixAIError):          # ...but can surface the reason
        core.account_info(pixai, raise_on_error=True)


def test_run_account_info_reports_real_reason(pixai, capsys):
    """The dashboard distinguishes an auth failure from a transient blip, instead of the old
    catch-all that blamed the API key for any hiccup."""
    from types import SimpleNamespace
    pixai.fail("me", core.PixAIError("401 Unauthorized -- API key"))
    core.run_account_info(SimpleNamespace(token=None))
    assert "API key" in capsys.readouterr().out
    pixai.fail("me", core.PixAIError("connection reset"))
    core.run_account_info(SimpleNamespace(token=None))
    assert "temporary" in capsys.readouterr().out.lower()


# ---- credit_balance: me { quotaAmount, quotaAmount(currency:"free"/"paid") } split ----

def test_credit_balance_returns_the_free_paid_split(pixai):
    # The real split: aliased quotaAmount fields on `me` with currency "free"/"paid"
    # (recovered from the site's own operation AST, verified live 2026-08-07).
    pixai.on("me", {"me": {"id": "42", "total": 3752991, "free": 219951, "paid": 3533040}})
    result = core.credit_balance(pixai)
    assert result == {"total": 3752991, "free": 219951, "paid": 3533040}


def test_credit_balance_fails_soft(pixai):
    pixai.fail("me", core.PixAIError("boom"))
    assert core.credit_balance(pixai) == {
        "total": None, "free": None, "paid": None}


def test_run_account_info_shows_free_paid_breakdown(pixai, capsys):
    """The dashboard's "Credits (balance)" line breaks the balance into free vs paid, the
    same split the site's own Membership & Credits page shows and quotaAmount alone can't.

    Both reads are anonymous `query { me { ... } }` documents, so they share one key on the
    fake and the answer dispatches on the document -- account_info's query has
    tasks.totalCount, credit_balance's has the aliased split."""
    from types import SimpleNamespace

    def answer(call):
        if "total: quotaAmount" in call.document:
            return {"me": {"id": "42", "total": 3752991, "free": 219951, "paid": 3533040}}
        return {"me": {"id": "42", "quotaAmount": 3752991}}

    pixai.on("me", answer)
    res = core.run_account_info(SimpleNamespace(token=None))
    out = capsys.readouterr().out
    assert "of which free" in out and "219,951" in out
    assert "of which paid" in out and "3,533,040" in out
    assert res["free_credits"] == 219951 and res["paid_credits"] == 3533040

def test_backfill_full_meta_recovers_historical_paid_credit(tmp_path, mocker, pixai):
    """getTaskById returns the task's top-level paidCredit for HISTORICAL tasks (the
    same persisted response our full-meta path replays -- verified against a real
    captured task, 2026-07-04), so --backfill-full-meta can recover spend history:

    - a row fetched because its meta is missing also gains paid_credit, and
    - --with-credit (mirroring --with-loras) re-processes rows whose meta is already
      complete but whose paid_credit is blank, without touching their existing meta.
    """
    from moonglade_gallery import save_catalog, load_catalog, CATALOG_FIELDS

    db = tmp_path / "catalog.db"
    save_catalog(db, [
        # t1: meta missing -> fetched by a plain --backfill-full-meta run
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "m1", "task_id": "t1",
                                           "filename": "a.png"},
        # t2: meta genuinely complete, cost unknown -> fetched only with --with-credit.
        # "Complete" has to include a detail-only field (model_id/steps/sampler/cfg_scale):
        # a prompt and a seed alone are NOT proof the task detail was ever fetched, and
        # treating them as proof is what stranded such rows -- see the test below.
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "m2", "task_id": "t2",
                                           "filename": "b.png", "prompt_full": "kept",
                                           "seed": "77", "model_id": "9001",
                                           "steps": "25", "sampler": "Euler a"},
    ])
    tasks = {
        "t1": {"parameters": {"prompts": "night elf druid"}, "outputs": {"seed": 5},
               "paidCredit": 300},
        "t2": {"parameters": {"prompts": "ignored -- row already has meta"},
               "outputs": {}, "paidCredit": 0},
    }
    mocker.patch.object(core, "task_detail_gql", side_effect=lambda s, tid: tasks[str(tid)])

    # Pass 1: plain backfill -> t1 fetched (missing meta) and gains cost; t2 untouched.
    core.run_backfill_full_meta(SimpleNamespace(out=str(tmp_path), token=None, delay=0))
    rows = {r["media_id"]: r for r in load_catalog(db)}
    assert rows["m1"]["prompt_full"] == "night elf druid"
    assert rows["m1"]["paid_credit"] == "300"        # historical cost recovered
    assert rows["m2"]["paid_credit"] == ""           # complete row not re-fetched

    # Pass 2: --with-credit -> t2 re-fetched for its blank cost; existing meta kept;
    # its genuinely-free cost stored as '0', never '' .
    core.run_backfill_full_meta(SimpleNamespace(out=str(tmp_path), token=None, delay=0,
                                                with_credit=True))
    rows = {r["media_id"]: r for r in load_catalog(db)}
    assert rows["m2"]["paid_credit"] == "0"
    assert rows["m2"]["prompt_full"] == "kept" and rows["m2"]["seed"] == "77"


def test_live_capture_writes_every_field_the_backfill_would(monkeypatch, tmp_path):
    """The point of capturing a generation as it happens is not having to go back for it.

    extract_full_meta hands over twelve fields; the live row wrote eight of them and dropped
    sampler, natural_prompt, clip_skip and loras, so those arrived blank and only appeared
    once a --backfill-full-meta came past -- the exact manual step this path exists to
    remove. `loras` is the clearest case: extract_full_meta returns "" for it BY DESIGN and
    documents that the caller resolves it. The backfill did. This did not.

    Asserted against extract_full_meta's own output rather than a hardcoded list, so a field
    added there later shows up here as a failure instead of silently going unwritten.
    """
    import pathlib
    from moonglade_gallery import CATALOG_FIELDS

    task = {
        "id": "T1", "createdAt": "2026-07-26T00:00:00Z", "status": "completed",
        "parameters": {"prompts": "night elf druid", "modelId": "42",
                       "extra": {"naturalPrompts": "a druid, at night"},
                       "lora": {"L1": 0.8}},
        "outputs": {"seed": 5, "batch": [{"mediaId": "m1", "seed": 5}],
                    "detailParameters": {"steps": 25, "sampler": "Euler a",
                                         "cfg_scale": 7, "clipSkip": 2}},
    }
    fm = core.extract_full_meta(task)
    # Every field extract_full_meta resolves for an ordinary generation must reach the row.
    expected = {k for k, v in fm.items()
                if k in CATALOG_FIELDS and str(v or "").strip()}
    expected |= {"loras"}          # "" by design out of extract_full_meta; caller resolves it
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "moonglade_backup.py").read_text(encoding="utf-8")
    # _download_image_task is the SHARED downloader: collect_generation (the web
    # app + job tracker) goes through it, so it is the path that matters most.
    body = src[src.index("def _download_image_task("):]
    body = body[:body.index(chr(10) + "        rows.append(full)")]
    missing = sorted(f for f in expected if '"{}"'.format(f) not in body)
    assert not missing, (
        "the live capture never writes {} -- they stay blank until a backfill comes past"
        .format(missing))


def test_a_freshly_captured_generation_gets_its_model_NAME_not_just_its_id(monkeypatch, tmp_path):
    """extract_full_meta fills model_name only for a CHAT task (Edit/Fix, resolved locally
    from EDIT_MODELS). For an ordinary generation it is blank and the caller must fill it --
    which --backfill-full-meta did and the live capture did not, so every image captured as
    it was generated showed a raw 19-digit model id on its detail page until a backfill
    happened past. Reported from the owner's own gallery: "Model 1983308862240288769".
    """
    assert core._resolved_model_name(object(), {"model_name": "Reference Pro"}, "1") ==         "Reference Pro", "a chat task's locally-resolved label must win"
    monkeypatch.setattr(core, "model_name_gql", lambda s, mid: "Tsubaki .2")
    assert core._resolved_model_name(object(), {}, "1983308862240288769") == "Tsubaki .2"
    assert core._resolved_model_name(object(), {}, "") == "", "no id, nothing to resolve"

    def boom(s, mid):
        raise core.PixAIError("lookup down")

    monkeypatch.setattr(core, "model_name_gql", boom)
    assert core._resolved_model_name(object(), {}, "1") == "", (
        "a failed lookup must cost the label, never the row")


def test_the_backfill_separates_errors_from_tasks_that_carried_no_prompt(tmp_path, mocker,
                                                                         capsys, pixai):
    """One number covered two unrelated things: the fetch threw, or it returned fine and
    simply carried no prompt (a deleted task, or a kind that records none). Those have
    completely different answers, and a single "157 failed" had us guessing twice."""
    from moonglade_gallery import save_catalog, CATALOG_FIELDS

    base = {f: "" for f in CATALOG_FIELDS}
    save_catalog(tmp_path / "catalog.db",
                 [base | {"media_id": "m%d" % i, "task_id": "t%d" % i,
                          "filename": "%d.png" % i} for i in range(4)])
    mocker.patch.object(core, "model_name_gql", side_effect=lambda s, m: "M")
    mocker.patch.object(core, "resolve_loras", side_effect=lambda s, t: "")

    def detail(_s, tid):
        if tid == "t0":
            raise core.PixAIError("HTTP 429 rate limited")
        if tid == "t1":
            return {"parameters": {"prompts": "real"}, "outputs": {}}
        return {"parameters": {}, "outputs": {}}          # fetched fine, no prompt

    mocker.patch.object(core, "task_detail_gql", side_effect=detail)
    core.run_backfill_full_meta(SimpleNamespace(out=str(tmp_path), token=None, delay=0))
    out = capsys.readouterr().out
    assert "Why they failed:" in out and "429" in out, "the real error must be named"
    assert "carried no prompt" in out, (
        "the two tasks that returned fine must not be reported as errors")


def test_parallel_map_reports_failures_instead_of_swallowing_them():
    """A worker's exception used to be discarded outright (`except Exception: res = None`).

    A real 17,289-task backfill consequently printed "16,044 failed" with no reason attached
    to any of them -- a number nobody can act on, and one that makes a 93%-failure run look
    the same as a successful one apart from the digits. The same total covers a rotated hash,
    an expired key, a rate limit and a genuinely deleted task, and those have four different
    answers.
    """
    seen = []

    def boom(i):
        if i % 2:
            raise RuntimeError("rate limited (429)")
        return i

    out = list(core._parallel_map(range(6), boom, workers=4,
                                  on_error=lambda it, e: seen.append((it, str(e)))))
    assert len(out) == 6, "a failing worker must not drop its item from the stream"
    assert [r for _, r in out].count(None) == 3, "failures still yield None, as before"
    assert sorted(i for i, _ in seen) == [1, 3, 5]
    assert all("429" in msg for _, msg in seen), "the reason must reach the caller"


def test_parallel_map_paces_the_whole_pool_not_each_thread():
    """--delay was dropped entirely once workers > 1, on the reasoning that "concurrency
    itself paces". It does not: eight threads firing as fast as they complete is a burst, and
    being polite to PixAI's servers is a standing rule of this project that should not switch
    itself off because a flag was passed.

    The pace is GLOBAL -- one request start per `delay` across the whole pool -- so raising
    --workers buys latency hiding up to that ceiling rather than a bigger burst.
    """
    import time

    starts = []

    def stamp(i):
        starts.append(time.monotonic())
        return i

    t0 = time.monotonic()
    list(core._parallel_map(range(8), stamp, workers=8, delay=0.05))
    span = time.monotonic() - t0
    # 8 starts one slot apart is 7 gaps of real time.sleep -- a FLOOR, so load can only push
    # this span higher, never below the bound. A pool that ignored the pace finishes in ~0s
    # and cannot reach it. The finer per-slot contract (each start exactly `delay` after the
    # last, global not per-thread) is pinned deterministically in
    # tests/test_med_backup_pacing.py::TestPaceGate; asserting it here on recorded wall-clock
    # times only measured scheduling jitter and was the flake this pass removes.
    assert span >= 0.05 * 7 * 0.8, (
        "8 workers finished in {:.3f}s -- the pool ignored the pace".format(span))


def test_backfill_names_why_tasks_failed(tmp_path, mocker, capsys, pixai):
    """The summary is by REASON, not just a total, and a majority-failure run says plainly
    that re-running it unchanged repeats it -- while making clear nothing already fetched is
    lost, because the backfill is resumable."""
    from moonglade_gallery import save_catalog, CATALOG_FIELDS

    base = {f: "" for f in CATALOG_FIELDS}
    save_catalog(tmp_path / "catalog.db",
                 [base | {"media_id": "m%d" % i, "task_id": "t%d" % i,
                          "filename": "%d.png" % i} for i in range(40)])
    mocker.patch.object(core, "task_detail_gql",
                        side_effect=core.PixAIError("HTTP 429 rate limited"))
    core.run_backfill_full_meta(SimpleNamespace(out=str(tmp_path), token=None, delay=0,
                                                workers=4))
    out = capsys.readouterr().out
    assert "Why they failed:" in out
    assert "429" in out, "the actual reason must be printed, not just a count"
    assert "resumable" in out, "a mass failure must say nothing fetched was lost"
    assert "--workers 2 --delay 1" in out, "it must suggest a gentler pace"


def test_full_metadata_is_the_default_on_a_pull(monkeypatch, tmp_path):
    """Full metadata used to be the thing you only got by asking, so a plain run or --update
    created rows with no prompt, no seed and no model -- and nothing said so until something
    needed one. It is the default now, with --no-full-meta as the explicit opt-out.

    Driven through main()'s real parser and its real dispatch, so what is asserted is the
    value the command actually receives rather than what the help text claims. --catalog-stats
    is the vehicle because it is the one command that needs no API key; the command itself is
    stubbed, so nothing runs and no network is touched. --full-meta stays accepted so existing
    commands, the docs and the Panel's whitelisted argv (`resync-full` sends exactly that
    flag) keep working unchanged.
    """
    seen = {}
    monkeypatch.setattr(core, "run_catalog_stats", lambda a: seen.__setitem__("ns", a))

    def parsed(argv):
        seen.clear()
        monkeypatch.setattr("sys.argv", ["moonglade_backup.py", "--catalog-stats",
                                         "--out", str(tmp_path)] + argv)
        core.main()
        return seen["ns"]

    assert parsed([]).full_meta is True, "a plain pull must fetch metadata"
    assert parsed(["--update"]).full_meta is True
    assert parsed(["--full-meta"]).full_meta is True, "the old flag must still be accepted"
    assert parsed(["--no-full-meta"]).full_meta is False
    # Order must not matter -- the opt-out is the last word wherever it appears.
    assert parsed(["--no-full-meta", "--update"]).full_meta is False


def test_catalog_stats_reports_metadata_coverage(tmp_path, capsys):
    """The stats screen only ever described FILES: it could say "35,133 entries, all
    downloaded" about a catalog in which not one row knew which model made it. Coverage is
    what decides whether a sweep is due, and the unique-TASK count is what the sweep costs --
    metadata is fetched once per task, so a batch's images are one call, not four.

    `loras` is deliberately absent from the report: a generation with no LoRAs stores that
    column blank too, so a blank one cannot be told apart from one never fetched, and
    reporting it would send you re-fetching tasks that are already complete.
    """
    from moonglade_gallery import save_catalog, CATALOG_FIELDS

    base = {f: "" for f in CATALOG_FIELDS}
    save_catalog(tmp_path / "catalog.db", [
        base | {"media_id": "m1", "task_id": "t1", "filename": "a.png",
                "prompt_full": "p", "model_id": "1", "model_name": "WAI"},
        # two rows of ONE task, both missing everything -> 2 rows, 1 task to fetch
        base | {"media_id": "m2", "task_id": "t2", "filename": "b.png"},
        base | {"media_id": "m3", "task_id": "t2", "filename": "c.png"},
        # imported locally: no PixAI task behind it, so it can never carry a model
        base | {"media_id": "m4", "filename": "d.png", "source": "local"},
    ])
    core.run_catalog_stats(SimpleNamespace(out=str(tmp_path), progress=None))
    out = capsys.readouterr().out
    assert "Metadata coverage" in out
    assert "1 / 4" in out, "model coverage must be counted per row"
    assert "3 missing across 1 tasks" in out, (
        "the sweep's cost is unique TASKS, not rows -- a batch is one call")
    assert "imported locally" in out, (
        "locally imported rows can never have a model and must not read as a gap to chase")
    assert "--backfill-full-meta" in out, "the report must name the command that fixes it"
    assert "loras" not in out.lower(), "a blank loras column is ambiguous, not a gap"


def test_backfill_full_meta_refetches_rows_that_have_only_a_prompt(tmp_path, mocker, pixai):
    """A row can hold a prompt and a seed while holding no model, steps, sampler or CFG.

    prompt_full was the ONLY sentinel for "this row has its full metadata", so every such
    row was skipped by every backfill, forever, and the sweep printed "Nothing to backfill"
    over a catalog that could not say which model made any of it. Measured on a real catalog
    before this changed: 788 of 800 rows had a prompt, 5 had a model id, and a backfill was
    a no-op. The model id is not cosmetic -- an image-view upscale submits i2i and needs it.
    """
    from moonglade_gallery import save_catalog, load_catalog, CATALOG_FIELDS

    db = tmp_path / "catalog.db"
    save_catalog(db, [
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "m1", "task_id": "t1",
                                           "filename": "a.png",
                                           "prompt_full": "night elf druid", "seed": "5"},
    ])
    task = {"parameters": {"prompts": "night elf druid", "modelId": "4242"},
            "outputs": {"seed": 5, "detailParameters": {"samplingSteps": 25,
                                                        "samplingMethod": "Euler a"}}}
    mocker.patch.object(core, "task_detail_gql", side_effect=lambda s, tid: task)
    mocker.patch.object(core, "model_name_gql", side_effect=lambda s, mid: "WAI v17")
    mocker.patch.object(core, "resolve_loras", side_effect=lambda s, t: "")

    core.run_backfill_full_meta(SimpleNamespace(out=str(tmp_path), token=None, delay=0))
    row = {r["media_id"]: r for r in load_catalog(db)}["m1"]
    assert row["model_id"] == "4242", "the prompt-only row was skipped again"
    assert row["model_name"] == "WAI v17"

    # And it settles: a second pass has nothing left to do, so this does not become a row
    # that is re-fetched on every sweep forever.
    calls = []
    mocker.patch.object(core, "task_detail_gql",
                        side_effect=lambda s, tid: calls.append(tid) or task)
    core.run_backfill_full_meta(SimpleNamespace(out=str(tmp_path), token=None, delay=0))
    assert calls == [], "the filled row is being re-fetched on every run"


# ---------------------------------------------------------------------------
# The IPv6 loopback companion listener (2026-08-06)
# ---------------------------------------------------------------------------
# Chrome resolves `localhost` dual-stack and tries ::1 FIRST; a server bound only
# to 127.0.0.1 makes every fresh browser connection burn ~300ms failing that
# attempt (measured live: connect 312ms vs 39ms of real server work). The gallery
# now starts a second werkzeug listener on [::1] beside the IPv4 bind.

def test_gallery_starts_an_ipv6_loopback_companion():
    """Source-level guard: the companion block exists, is gated to loopback-ish
    hosts only (an explicit LAN --host must not sprout extra listeners), and
    fails soft when the machine has no IPv6 stack."""
    import pathlib
    src = pathlib.Path("moonglade_gallery.py").read_text(encoding="utf-8")
    assert 'if args.host in ("127.0.0.1", "0.0.0.0", "localhost"):' in src
    assert '_make_server6("::1", args.port, app' in src
    assert src.index('_make_server6("::1"') < src.index(
        "app.run(host=args.host, port=args.port"), \
        "the companion must be up BEFORE app.run() blocks"


def test_ipv6_loopback_actually_serves_a_wsgi_app():
    """Functional smoke on this machine: werkzeug really can bind [::1] and answer
    over IPv6 -- the exact mechanism the companion uses. Skips (never fails) where
    the OS has no usable IPv6 loopback."""
    import socket
    import threading
    import urllib.request

    from werkzeug.serving import make_server

    def app(environ, start_response):
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"ok6"]

    try:
        srv = make_server("::1", 0, app, threaded=True)
    except (OSError, socket.gaierror) as e:  # pragma: no cover - machine-dependent
        pytest.skip("no usable IPv6 loopback on this machine: %s" % e)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        port = srv.server_port
        body = urllib.request.urlopen(
            "http://[::1]:%d/" % port, timeout=5).read()
        assert body == b"ok6"
    finally:
        srv.shutdown()
        t.join(timeout=5)
