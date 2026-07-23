"""Tests for network-layer functions with mocked requests.Session."""
import json
import pytest

import pixai_gallery_backup as core


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


# ---------------------------------------------------------------------------
# _quick_count() — verify it returns 0 on PixAIError without raising
# ---------------------------------------------------------------------------

class TestTaskDetailGql:
    def test_returns_task_on_success(self, mock_session, mocker):
        task = {"id": "t1", "parameters": {"prompts": "full prompt"}, "outputs": {}}
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"data": {"task": task}}
        mock_session.get.return_value = resp
        # Inject hash so the function doesn't raise
        import pixai_gallery_backup as c
        orig = c.TASK_DETAIL_HASH
        c.TASK_DETAIL_HASH = "fakehash"
        try:
            result = c.task_detail_gql(mock_session, "t1")
        finally:
            c.TASK_DETAIL_HASH = orig
        assert result["id"] == "t1"

    def test_returns_none_on_non_200(self, mock_session, mocker):
        import pixai_gallery_backup as c
        resp = mocker.MagicMock()
        resp.status_code = 500
        mock_session.get.return_value = resp
        orig = c.TASK_DETAIL_HASH
        c.TASK_DETAIL_HASH = "fakehash"
        try:
            result = c.task_detail_gql(mock_session, "t1")
        finally:
            c.TASK_DETAIL_HASH = orig
        assert result is None

    def test_raises_when_hash_missing(self, mock_session):
        import pixai_gallery_backup as c
        orig = c.TASK_DETAIL_HASH
        c.TASK_DETAIL_HASH = ""
        try:
            with pytest.raises(c.PixAIError, match="TASK_DETAIL_HASH"):
                c.task_detail_gql(mock_session, "t1")
        finally:
            c.TASK_DETAIL_HASH = orig


class TestModelNameGql:
    def test_returns_model_title_and_version(self, mock_session, mocker):
        import pixai_gallery_backup as c
        mv = {"name": "v1", "model": {"title": "Tsubaki.2"}}
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"data": {"generationModelVersion": mv}}
        mock_session.get.return_value = resp
        orig_hash = c.MODEL_DETAIL_HASH
        c.MODEL_DETAIL_HASH = "fakehash"
        # Clear module-level cache before test
        c.model_name_gql.__defaults__  # ensure it's the right function
        # Use a fresh call with a unique ID not in cache
        try:
            result = c.model_name_gql(mock_session, "unique_model_id_test_123")
        finally:
            c.MODEL_DETAIL_HASH = orig_hash
        assert result == "Tsubaki.2 v1"

    def test_returns_empty_for_empty_id(self, mock_session):
        import pixai_gallery_backup as c
        assert c.model_name_gql(mock_session, "") == ""
        assert c.model_name_gql(mock_session, None) == ""


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
        name_length=40, name_sep="_", organize_live=False, organize_adv_live=False,
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


def test_run_download_returns_its_fail_count(tmp_path, mocker, capsys):
    """D-4: run_download's own tally (dl['fail'] etc.) never reached any caller -- no
    return statement meant a partial-failure run was indistinguishable from a clean one
    to everything downstream (the CLI job log, the Panel). Also locks in the louder
    console notice that replaces the old easy-to-miss one-liner."""
    mocker.patch.object(core, "_make_session", return_value=mocker.MagicMock())
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
    from pixai_gallery import load_catalog
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
    from pixai_gallery import save_catalog, CATALOG_FIELDS
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
            "visibility": "PUBLIC", "isNsfw": True, "likedCount": 5,
            "commentCount": 2, "aesScore": 7.5,
            "tacks": [{"codeName": "contest_x", "displayName": "ContestX"},
                      {"displayName": "tag2"}],
            "extra": {"imageBlurHash": "U8A]jP%L",
                      "nsfwPredict": {"porn": 0.0510777, "hentai": 0.913348, "neutral": 0.01}}}
    m = core.extract_artwork_meta(node)
    assert m["media_id"] == "m1" and m["artwork_id"] == "aw1"
    assert m["title"] == "Lollipop Elf"
    assert m["is_published"] == "1" and m["is_nsfw"] == "1"
    assert m["liked_count"] == "5" and m["comment_count"] == "2"
    assert m["art_tags"] == "ContestX, tag2"
    # from the free `extra` block: blurhash placeholder + rounded per-category NSFW scores
    assert m["blurhash"] == "U8A]jP%L"
    assert m["nsfw_scores"] == '{"porn":0.051,"hentai":0.913,"neutral":0.01}'


def test_extract_artwork_meta_no_extra():
    # a node without an `extra` block leaves the new fields blank (never raises)
    m = core.extract_artwork_meta({"id": "a", "mediaId": "m", "visibility": "PRIVATE"})
    assert m["blurhash"] == "" and m["nsfw_scores"] == "" and m["is_published"] == "0"


def test_sync_artworks_merges_by_media_id(tmp_path, mocker):
    from pixai_gallery import save_catalog, CATALOG_FIELDS, load_catalog
    db = tmp_path / "catalog.db"
    save_catalog(db, [{f: "" for f in CATALOG_FIELDS} |
                      {"media_id": "m1", "filename": "x_m1.png"}])
    mocker.patch.object(core, "USER_ID", "u1")
    mocker.patch.object(core, "_make_session", return_value=mocker.MagicMock())
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


def test_sync_artworks_resolves_userid_via_session(tmp_path, mocker):
    """A config with NO USER_ID must NOT hard-fail: _make_session auto-resolves it from the API
    key, so run_sync_artworks builds the session FIRST, then proceeds. Regression for the web
    Control Panel error 'USER_ID missing from config.json'."""
    from types import SimpleNamespace
    from pixai_gallery import save_catalog, CATALOG_FIELDS
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


def test_sync_artworks_flags_incomplete_pagination_as_a_failure(tmp_path, mocker):
    """B15: unlike gql() (retries 4x, then RAISES), artwork_list_gql swallows a
    RequestException/non-200/bad-JSON with NO retry and just returns None (see its
    own docstring: 'Returns the Relay connection dict ... or None on failure'). On
    page 1 that correctly raises; on page 2+ the pagination loop treats it EXACTLY
    like a legitimate 'no more pages' and breaks silently -- the run then reports a
    complete-looking total for what is actually a partial sync. FAILS before the
    fix: run_sync_artworks's return dict has no 'fail' key at all, so res['fail']
    raises KeyError."""
    from pixai_gallery import save_catalog, CATALOG_FIELDS
    db = tmp_path / "catalog.db"
    save_catalog(db, [{f: "" for f in CATALOG_FIELDS} | {"media_id": "m1", "filename": "x_m1.png"}])
    mocker.patch.object(core, "USER_ID", "u1")
    mocker.patch.object(core, "_make_session", return_value=mocker.MagicMock())
    page1 = {"edges": [{"node": {"id": "aw1", "mediaId": "m1", "title": "Page1 Art",
                                 "visibility": "PUBLIC", "isNsfw": False,
                                 "likedCount": 1, "commentCount": 0}}],
             "pageInfo": {"hasPreviousPage": True, "startCursor": "cursor2"}}
    # Page 1 succeeds; page 2's fetch "fails" (artwork_list_gql's own failure mode: None).
    mocker.patch.object(core, "artwork_list_gql", side_effect=[page1, None])

    res = core.run_sync_artworks(SimpleNamespace(out=str(tmp_path), token=None, delay=0))

    assert res["artworks"] == 1                 # page 1's artwork still landed -- not discarded
    assert res["fail"] == 1                      # but the early stop is now visible, not silent


def test_sync_artworks_counts_failed_video_downloads_as_a_failure(tmp_path, mocker):
    """B15: a video that fails to download after retries (download() returns
    ('fail', None), the same status run_download's own dl['fail'] counts) must be
    just as visible here -- currently it's silently absorbed into a lower
    'Videos saved/present: N of M' console tally with no return-value or job-status
    signal at all. FAILS before the fix for the same reason as the pagination
    test: no 'fail' key in the return dict."""
    from pixai_gallery import save_catalog, CATALOG_FIELDS
    db = tmp_path / "catalog.db"
    save_catalog(db, [{f: "" for f in CATALOG_FIELDS} | {"media_id": "m1", "filename": "x_m1.png"}])
    mocker.patch.object(core, "USER_ID", "u1")
    mocker.patch.object(core, "_make_session", return_value=mocker.MagicMock())
    conn = {"edges": [{"node": {"id": "aw1", "mediaId": "m1", "title": "Animated",
                                "visibility": "PUBLIC", "isNsfw": False,
                                "likedCount": 0, "commentCount": 0,
                                "videoMediaId": "vid1"}}],
            "pageInfo": {"hasPreviousPage": False}}
    mocker.patch.object(core, "artwork_list_gql", return_value=conn)
    mocker.patch.object(core, "already_downloaded", return_value=None)
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


def test_fix_models_resolves_numeric_names(tmp_path, mocker):
    from pixai_gallery import save_catalog, CATALOG_FIELDS, load_catalog
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "m1", "filename": "a.png",
                                           "model_id": "999", "model_name": "999"},
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "m2", "filename": "b.png",
                                           "model_id": "999", "model_name": "999"},
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "m3", "filename": "c.png",
                                           "model_id": "111", "model_name": "Already Named"},
    ])
    mocker.patch.object(core, "_make_session", return_value=mocker.MagicMock())
    mocker.patch.object(core, "model_name_gql", return_value="Tsubaki.2 v1")

    res = core.run_fix_models(SimpleNamespace(out=str(tmp_path), token=None, delay=0))

    assert res["fixed"] == 2          # both m1/m2 (model 999) fixed
    rows = {r["media_id"]: r for r in load_catalog(db)}
    assert rows["m1"]["model_name"] == "Tsubaki.2 v1"
    assert rows["m3"]["model_name"] == "Already Named"   # untouched


def test_sync_runs_all_three_steps_in_order(tmp_path, mocker, monkeypatch):
    """Control Panel consolidation: --sync now folds fix-models in between the pull
    and the metadata backfill (previously just 2 steps), so a synced catalog is always
    fully labeled without a separate click/action."""
    calls = []
    seen = {}
    mocker.patch.object(core, "run_download",
                        side_effect=lambda a, progress=None: calls.append("download") or seen.__setitem__("dl_progress", progress))
    mocker.patch.object(core, "run_fix_models", side_effect=lambda a: calls.append("fix_models"))
    mocker.patch.object(core, "run_backfill_full_meta", side_effect=lambda a: calls.append("backfill"))
    monkeypatch.setattr("sys.argv", ["prog", "--sync", "--out", str(tmp_path)])

    core.main()

    assert calls == ["download", "fix_models", "backfill"]
    # the download step must receive args.progress (main() sets it via _make_progress),
    # else the panel's progress bar is blank during the download -- the thing the owner hit.
    assert callable(seen["dl_progress"])


def test_progress_counter_does_not_double_count(tmp_path, mocker):
    # Regression: the progress counter must NOT be seeded with the on-disk count
    # (that double-counted already-downloaded items and overshot 100%).
    from pixai_gallery import save_catalog, CATALOG_FIELDS
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


def test_account_info_parses_me(mocker):
    mocker.patch.object(core, "gql_adhoc", return_value={"me": {
        "id": "42", "quotaAmount": 21290, "tasks": {"totalCount": 19623},
        "followerCount": 30, "followingCount": 4,
        "membership": {"membershipId": "membership-plus", "tier": 2,
                       "privilege": {"dailyClaimAdded": 10000, "professionalMode": True}},
        "subscription": {"planId": "membership-plus", "status": "active",
                         "cancelAtPeriodEnd": True, "endAt": "2026-07-08T00:00:00Z"}}})
    me = core.account_info(mocker.MagicMock())
    assert me["quotaAmount"] == 21290
    assert me["membership"]["membershipId"] == "membership-plus"
    assert me["tasks"]["totalCount"] == 19623      # server's lifetime task count (backup coverage)
    assert me["followerCount"] == 30


def test_account_info_empty_on_error(mocker):
    mocker.patch.object(core, "gql_adhoc", side_effect=core.PixAIError("boom"))
    assert core.account_info(mocker.MagicMock()) == {}          # soft-fail (web relies on this)
    with __import__("pytest").raises(core.PixAIError):          # ...but can surface the reason
        core.account_info(mocker.MagicMock(), raise_on_error=True)


def test_run_account_info_reports_real_reason(mocker, capsys):
    """The dashboard distinguishes an auth failure from a transient blip, instead of the old
    catch-all that blamed the API key for any hiccup."""
    from types import SimpleNamespace
    mocker.patch.object(core, "_make_session", lambda *a, **k: object())
    mocker.patch.object(core, "gql_adhoc", side_effect=core.PixAIError("401 Unauthorized -- API key"))
    core.run_account_info(SimpleNamespace(token=None))
    assert "API key" in capsys.readouterr().out
    mocker.patch.object(core, "gql_adhoc", side_effect=core.PixAIError("connection reset"))
    core.run_account_info(SimpleNamespace(token=None))
    assert "temporary" in capsys.readouterr().out.lower()
