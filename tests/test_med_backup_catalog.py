"""Four correctness defects in moonglade_backup.py where the tool wrote (or reported) the
WRONG FACT rather than failing (batch G).

Each test fails against the pre-fix code, and each is written from the user-visible symptom
rather than the internals:

  M02  the same model blurred on Search (REST, honours the API's shouldBlur) but not on
       Market/Bookmarks (GraphQL, read the raw isNsfw) -- two paths, one documented row shape.
       Pinned against the QUERY DOCUMENTS, not against hand-built nodes: the first repair
       taught the shared rule to prefer `shouldBlur` while neither GraphQL document selected
       it, so it changed nothing a live row could see and the test that "proved" it fed in a
       payload no query in the file could produce.
  M06  --catalog-stats counted the _deleted/ soft-delete quarantine as part of the live
       library, overstating the very number the wiki tells you to read before cleaning up.
  M16  `--generate --task-id <a video task>` saved the mp4 into images/ with is_video blank,
       so the gallery served a video as an image: broken tile, no poster, no faststart.
  M17  an edit made with a model outside the hardcoded EDIT_MODELS pair was labelled with the
       literal "Edit" -- which --fix-models reads as "already resolved", so it stuck forever.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

import moonglade_backup as core
import moonglade_gallery as gallery
from moonglade_gallery import DELETED_DIRNAME, load_catalog


# ---------------------------------------------------------------------------
# M02 -- one blur rule for both model-row sources
# ---------------------------------------------------------------------------

def _fake_pixai(schema_has_blur, node_facts, calls):
    """A stand-in for PixAI's GraphQL endpoint that behaves like a SCHEMA, not like a mock.

    Two properties are the whole point, because the first repair of M02 was green against a
    mock that had neither:

      * it answers ONLY the leaves the document actually selected -- so a node carries
        `shouldBlur` if and only if the query asked for it, exactly as a real server behaves;
      * a document selecting a field the schema lacks is REFUSED outright (the entire page,
        not just that leaf), which is what makes adding an unprobed field a real risk.

    Serves both model-connection documents off the query text.
    """
    def _gql(session, query, variables=None, retries=None):
        calls.append(query)
        asked = core._MODEL_BLUR_FIELD in query
        if asked and not schema_has_blur:
            raise core.PixAIError(
                'GraphQL error: [{"message": "Cannot query field \\"shouldBlur\\" on type '
                '\\"GenerationModel\\"."}]')
        edges = []
        for i, facts in enumerate(node_facts):
            node = {"id": str(i + 1), "title": "Selene", "type": "SDXL_MODEL",
                    "likedCount": 0, "latestVersion": {"id": "v1"}, "media": {"urls": []},
                    "tags": [], "author": {}, "createdAt": "",
                    "isNsfw": facts.get("isNsfw", False)}
            if asked and "shouldBlur" in facts:
                node["shouldBlur"] = facts["shouldBlur"]
            edges.append({"node": node})
        conn = {"pageInfo": {}, "edges": edges}
        if "bookmarkedGenerationModels" in query:
            return {"me": {"id": "u1", "bookmarkedGenerationModels": conn}}
        return {"generationModels": conn}
    return _gql


class TestM02BlurParity:
    @pytest.fixture(autouse=True)
    def _fresh_latch(self, monkeypatch):
        """_model_blur_supported is a process-wide latch; no test may inherit another's.
        The refusal tally feeding it is process-wide too, so it resets here as well -- a test
        that started life one strike down would latch a call early and pass for the wrong
        reason."""
        monkeypatch.setattr(core, "_model_blur_supported", None)
        monkeypatch.setattr(core, "_model_blur_refusals", 0)

    def _rest_row(self, monkeypatch, payload):
        """One row out of the REST /generation-model/search path."""
        monkeypatch.setattr(core, "_rest_get",
                            lambda s, path, params=None, **k: {"data": [payload]})
        return core.model_search_rest(object())["results"][0]

    def _market_rows(self, monkeypatch, facts, schema_has_blur=True, calls=None):
        monkeypatch.setattr(core, "gql_adhoc",
                            _fake_pixai(schema_has_blur, facts, calls if calls is not None else []))
        return core.model_search_market_gql(object(), usage="MODEL")["results"]

    def _bookmark_rows(self, monkeypatch, facts, schema_has_blur=True, calls=None):
        monkeypatch.setattr(core, "gql_adhoc",
                            _fake_pixai(schema_has_blur, facts, calls if calls is not None else []))
        return core.model_bookmarks_gql(object(), usage="MODEL")["results"]

    # -- the queries must actually ASK for the flag ---------------------------------------

    def test_both_model_documents_select_the_viewer_scoped_flag(self, monkeypatch):
        """The heart of the second round. Preferring `shouldBlur` in the shared rule while
        neither document SELECTS it is a no-op: the field never arrives, every live row falls
        to isNsfw, and the picker behaves exactly as it did before the "fix"."""
        market, books = [], []
        self._market_rows(monkeypatch, [{"isNsfw": False}], calls=market)
        self._bookmark_rows(monkeypatch, [{"isNsfw": False}], calls=books)
        assert core._MODEL_BLUR_FIELD in market[0]
        assert core._MODEL_BLUR_FIELD in books[0]

    # -- one model, three sources, one answer ---------------------------------------------

    @pytest.mark.parametrize("facts,blurred", [
        ({"isNsfw": True}, True),                      # raw flag only: REST used to ignore it
        ({"isNsfw": True, "shouldBlur": True}, True),  # (the one case they already agreed on)
        ({"isNsfw": True, "shouldBlur": False}, False),  # opted in: Market ignored that
        ({"isNsfw": False, "shouldBlur": True}, True),   # ...and ignored this one too
    ])
    def test_every_source_answers_identically_for_identical_facts(self, monkeypatch, facts,
                                                                  blurred):
        """THE bug, end to end through the real query paths: one model, three tabs. REST read
        flag.shouldBlur while Market and Bookmarks read isNsfw, so three of these four models
        blurred on one tab and not the other -- in a picker that renders all of them in ONE
        grid and documents them as the same row shape.

        `blurred` is asserted as well as parity: three sources agreeing on the WRONG answer
        would satisfy an equality-only test."""
        rest = self._rest_row(monkeypatch,
                              {"id": "1", "title": "Selene", "flag": dict(facts)})
        market = self._market_rows(monkeypatch, [facts])[0]
        book = self._bookmark_rows(monkeypatch, [facts])[0]
        assert rest["should_blur"] == market["should_blur"] == book["should_blur"] == blurred

    def test_the_viewer_flag_beats_the_raw_content_flag_on_a_live_market_row(self, monkeypatch):
        """shouldBlur is the only signal computed against the VIEWER's content settings, so
        an account that opted in must not be blurred by isNsfw alone -- the exact complaint,
        and the case a hand-built node carrying a field no query requested cannot pin."""
        row = self._market_rows(monkeypatch, [{"isNsfw": True, "shouldBlur": False}])[0]
        assert row["should_blur"] is False
        row = self._market_rows(monkeypatch, [{"isNsfw": False, "shouldBlur": True}])[0]
        assert row["should_blur"] is True

    # -- err toward blurring where the data is genuinely ambiguous -------------------------

    def test_rest_row_without_the_viewer_flag_still_blurs_an_nsfw_model(self, monkeypatch):
        """Err toward blurring, on every path: a REST row that carries no shouldBlur used to
        read `bool(flag.get("shouldBlur"))` -> False and show an NSFW cover unblurred."""
        rest = self._rest_row(monkeypatch, {"id": "8", "title": "Nyx",
                                            "flag": {"isNsfw": True}})
        assert rest["should_blur"] is True

    def test_a_row_that_says_nothing_does_not_blur(self, monkeypatch):
        """Absence of both flags is not evidence of NSFW -- an ordinary model must not be
        blurred just because a projection omitted the fields."""
        assert self._market_rows(monkeypatch, [{}])[0]["should_blur"] is False

    # -- the field is UNPROBED, so a schema without it must not break the tab --------------

    def test_a_schema_without_the_field_degrades_instead_of_breaking_the_tab(self, monkeypatch):
        """`shouldBlur` on the GraphQL node is inferred from the REST row, not read off a live
        reply, and a field the schema lacks is a REJECTED QUERY -- the whole page. So the
        refusal is answered by re-running the SAME search without the field: rows still
        arrive, blur falls back to isNsfw, and the tab never goes blank."""
        calls = []
        rows = self._market_rows(monkeypatch, [{"isNsfw": True}], schema_has_blur=False,
                                 calls=calls)
        assert [r["should_blur"] for r in rows] == [True]
        assert len(calls) == 2 and core._MODEL_BLUR_FIELD not in calls[1]

    def test_a_repeated_refusal_is_remembered_so_it_stops_costing_a_retry(self, monkeypatch):
        """A retry on every search would double the picker's request count against a schema
        that will never carry the field -- so the refusal does eventually latch. It just takes
        TWO consecutive refusals to get there (see the next test for why)."""
        calls = []
        for _ in range(core._MODEL_BLUR_REFUSALS_BEFORE_GIVING_UP):
            self._market_rows(monkeypatch, [{"isNsfw": True}], schema_has_blur=False,
                              calls=calls)
        assert core._model_blur_supported is False
        assert len(calls) == 2 * core._MODEL_BLUR_REFUSALS_BEFORE_GIVING_UP

        self._market_rows(monkeypatch, [{"isNsfw": True}], schema_has_blur=False, calls=calls)
        assert len(calls) == 2 * core._MODEL_BLUR_REFUSALS_BEFORE_GIVING_UP + 1
        assert core._MODEL_BLUR_FIELD not in calls[-1]   # field-less from here on

    def test_one_transient_refusal_does_not_disable_the_field_for_the_whole_run(self,
                                                                               monkeypatch):
        """`gql_adhoc` raises PixAIError for a 200 carrying an `errors` array, which is the
        shape of PixAI's transient 'Internal server error' as much as of a rejected field. So
        a single refusal says nothing about the schema. Latching on one blip demoted the
        gallery -- a long-running process serving Search, Market and Bookmarks -- back to
        `isNsfw` until restart, silently reopening the disagreement M02 exists to close."""
        calls = []
        blip = {"n": 0}
        real = _fake_pixai(True, [{"isNsfw": True, "shouldBlur": False}], calls)

        def _one_blip(session, query, variables=None, retries=None):
            blip["n"] += 1
            if blip["n"] == 1:
                raise core.PixAIError("Internal server error")
            return real(session, query, variables, retries)
        monkeypatch.setattr(core, "gql_adhoc", _one_blip)

        core.model_search_market_gql(object(), usage="MODEL")          # eats the blip
        assert core._model_blur_supported is not False                 # NOT written off

        rows = core.model_search_market_gql(object(), usage="MODEL")["results"]
        assert core._MODEL_BLUR_FIELD in calls[-1]                     # still asking
        assert [r["should_blur"] for r in rows] == [False]             # viewer's own setting wins

    def test_a_real_failure_is_not_mistaken_for_a_missing_field(self, monkeypatch):
        """The degrade is keyed on evidence -- the same document minus the field SUCCEEDING --
        never on the wording of PixAI's error. An auth failure or an outage refuses both
        documents, so it must surface as the error it is and must not latch the flag off for
        the rest of the run."""
        def _always_refuse(session, query, variables=None, retries=None):
            raise core.PixAIError("401 Unauthorized -- API key missing/expired.")
        monkeypatch.setattr(core, "gql_adhoc", _always_refuse)

        with pytest.raises(core.PixAIError, match="401"):
            core.model_search_market_gql(object(), usage="MODEL")
        assert core._model_blur_supported is None

    def test_a_refused_flag_does_not_demote_bookmarks_to_the_persisted_hash(self, monkeypatch):
        """model_bookmarks_gql falls back to the persisted document on any PixAIError. If a
        blur refusal escaped, the bookmark tab would silently switch to PixAI's own fragment
        -- which we cannot narrow to the fields a row needs and which rots when they redeploy
        -- for a reason that has nothing to do with the hash."""
        def _boom(*a, **k):
            raise AssertionError("the persisted fallback must not be reached")
        monkeypatch.setattr(core, "_bookmarks_persisted", _boom)
        calls = []
        monkeypatch.setattr(core, "gql_adhoc",
                            _fake_pixai(False, [{"isNsfw": True}], calls))
        res = core.model_bookmarks_gql(object(), usage="MODEL")
        assert res["_path"] == "adhoc"
        assert [r["should_blur"] for r in res["results"]] == [True]


# ---------------------------------------------------------------------------
# M06 -- the trash is not part of the library
# ---------------------------------------------------------------------------

def _seed_backup_tree(root):
    """An `out` folder holding one live image, one gallery thumbnail, one quarantined
    duplicate and one soft-deleted image."""
    (root / "images").mkdir(parents=True)
    (root / "gallery" / "thumbs").mkdir(parents=True)
    (root / "_duplicates").mkdir()
    (root / DELETED_DIRNAME).mkdir()
    (root / "images" / "live_1.png").write_bytes(b"L" * 100)
    (root / "gallery" / "thumbs" / "1.jpg").write_bytes(b"t")
    (root / "_duplicates" / "dupe_2.png").write_bytes(b"D" * 50)
    (root / DELETED_DIRNAME / "trashed_3.png").write_bytes(b"T" * 400)


class TestM06TrashedImagesAreNotTheLibrary:
    def test_deleted_quarantine_is_excluded_from_the_disk_totals(self, tmp_path):
        """run_download's own scanner has skipped {gallery, _duplicates, _deleted} since B11;
        this one skipped only the first two, so every soft-deleted image still counted as part
        of the live library -- in both the file count and the byte total."""
        _seed_backup_tree(tmp_path)
        n, nbytes, thumbs = core._count_backup_images(tmp_path)
        assert n == 1 and nbytes == 100        # the live image only -- not the 400-byte trash
        assert thumbs == 1

    def test_the_trash_is_reported_rather_than_dropped(self, tmp_path):
        """Excluding it silently would just swap one wrong number for another: the totals
        would stop matching the folder with nothing on screen to explain the gap."""
        _seed_backup_tree(tmp_path)
        counts = core._count_backup_images(tmp_path)
        assert counts.trashed == 1 and counts.trashed_bytes == 400

    def test_the_three_tuple_unpacking_contract_is_unchanged(self, tmp_path):
        """Callers (and the older test pinning this) unpack exactly three values -- the
        quarantine totals ride alongside rather than as a fourth slot."""
        _seed_backup_tree(tmp_path)
        counts = core._count_backup_images(tmp_path)
        assert isinstance(counts, tuple) and len(counts) == 3
        assert tuple(counts) == (1, 100, 1)

    def test_catalog_stats_does_not_count_trash_as_library(self, tmp_path, capsys):
        """The end-to-end symptom: --catalog-stats is what the wiki points at for deciding
        what to clean up, and it reported the trashed image as part of the collection."""
        _seed_backup_tree(tmp_path)
        db = tmp_path / "catalog.db"
        gallery.init_db(db)
        row = {f: "" for f in gallery.CATALOG_FIELDS}
        row.update({"media_id": "1", "filename": "images/live_1.png"})
        gallery.save_catalog(db, [row])
        core.run_catalog_stats(SimpleNamespace(out=str(tmp_path)))
        out = capsys.readouterr().out
        assert "Image files on disk : 1" in out
        assert "1 soft-deleted in {}/".format(DELETED_DIRNAME) in out


# ---------------------------------------------------------------------------
# M16 -- a video recovered through --generate is still a video
# ---------------------------------------------------------------------------

_VIDEO_TASK = {
    "id": "TV1",
    "createdAt": "2026-07-27T00:00:00Z",
    "parameters": {"referenceVideo": {"prompt": "a moonlit lake", "duration": 5}},
    "outputs": {"videos": [{"mediaId": "VID9", "thumbnailMediaId": "POST9", "seed": "42"}]},
}


@pytest.fixture()
def video_task_network(monkeypatch):
    """Stub every network touch of a --task-id recovery whose task turns out to be a video."""
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "task_detail_gql", lambda s, t: _VIDEO_TASK)
    monkeypatch.setattr(core, "media_file_gql",
                        lambda s, mid: {"fileUrl": "https://cdn/{}.mp4".format(mid)})
    # A video's media object resolves to a perfectly good URL -- which is exactly why the old
    # path could download the mp4 through the IMAGE loop and never notice.
    monkeypatch.setattr(core, "resolve_media",
                        lambda s, mid: ("https://cdn/{}.png".format(mid), {"width": 8, "height": 8}))

    def fake_download(session, url, stem, **kw):
        path = Path(str(stem) + (".mp4" if url.endswith(".mp4") else ".png"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00binary")
        return "ok", path

    monkeypatch.setattr(core, "download", fake_download)
    monkeypatch.setattr(core, "video_faststart", lambda p: True)
    monkeypatch.setattr(core, "video_poster_thumb", lambda *a, **k: None)
    monkeypatch.setattr(gallery, "make_thumbnail", lambda *a, **k: None)


class TestM16VideoTaskRecoveredThroughGenerate:
    def _run(self, tmp_path):
        return core.run_generate(SimpleNamespace(
            out=str(tmp_path), params_json='{"prompts": "x", "modelId": "v"}',
            confirm=False, task_id="TV1", token=None))

    def test_video_output_is_cataloged_as_video_not_as_an_image(self, tmp_path,
                                                                video_task_network):
        """outputs.videos[].mediaId used to be folded into the image id list, so the clip was
        written with is_video blank -- and the gallery lists images with
        `COALESCE(is_video,'') != '1'`, so it served an mp4 through an <img> tag."""
        res = self._run(tmp_path)
        rows = load_catalog(tmp_path / "catalog.db")
        assert len(rows) == 1
        row = rows[0]
        assert row["media_id"] == "VID9"
        assert row["is_video"] == "1"                     # was "" -- served as an image
        assert row["filename"].startswith("videos/")      # was images/
        assert row["poster_media_id"] == "POST9"          # video-only metadata, was dropped
        assert res["videos"] == 1 and res["images"] == 0

    def test_the_mp4_lands_in_videos_and_never_in_images(self, tmp_path, video_task_network):
        """The file itself moved, not just the row: none of the video handling (poster
        thumbnail, faststart remux) ever runs on a file the image path pulled into images/."""
        self._run(tmp_path)
        assert [p.name for p in (tmp_path / "videos").rglob("*.mp4")]
        images = tmp_path / "images"
        assert not (images.exists() and list(images.rglob("*.*")))

    def test_the_user_is_told_which_command_was_the_direct_route(self, tmp_path, capsys,
                                                                 video_task_network):
        """Collecting silently would leave a user wondering why --generate produced a video;
        the pointer is the difference between a surprise and an answer."""
        self._run(tmp_path)
        out = capsys.readouterr().out
        assert "VIDEO output" in out
        assert "--generate-video --task-id TV1" in out


# ---------------------------------------------------------------------------
# M17 -- an unknown edit model must stay repairable
# ---------------------------------------------------------------------------

def _edit_task(model_id):
    params = {"prompts": "make it night"}
    if model_id is not None:
        params["chat"] = {"modelId": model_id, "prompts": "make it night"}
    else:
        params["chat"] = {"prompts": "make it night"}
    return {"id": "TE1", "createdAt": "2026-07-27T00:00:00Z",
            "parameters": params, "outputs": {"mediaId": "IMG1", "seed": "5"}}


@pytest.fixture()
def edit_task_network(monkeypatch):
    """Stub the network for `--edit-image --task-id` (recovering a chat task made elsewhere).
    Returns the list of model ids run_edit_image asked model_name_gql to resolve."""
    asked = []

    def _install(task, resolved_name):
        monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
        monkeypatch.setattr(core, "task_detail_gql", lambda s, t: task)
        monkeypatch.setattr(core, "resolve_media",
                            lambda s, mid: ("https://cdn/{}.png".format(mid),
                                            {"width": 8, "height": 8}))

        def fake_download(session, url, stem, **kw):
            path = Path(str(stem) + ".png")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\x00png")
            return "ok", path

        monkeypatch.setattr(core, "download", fake_download)
        monkeypatch.setattr(gallery, "make_thumbnail", lambda *a, **k: None)

        def fake_name(session, mid, **kw):
            asked.append(mid)
            return resolved_name(mid) if callable(resolved_name) else resolved_name

        monkeypatch.setattr(core, "model_name_gql", fake_name)
        return asked

    return _install


def _run_edit(tmp_path):
    core.run_edit_image(SimpleNamespace(out=str(tmp_path), task_id="TE1", token=None,
                                        prompt="", edit_src=[], params_json=""))
    return load_catalog(tmp_path / "catalog.db")[0]


class TestM17UnknownEditModel:
    def test_an_unknown_edit_model_is_resolved_by_name(self, tmp_path, edit_task_network):
        """extract_full_meta names a chat task only from the local 2-entry EDIT_MODELS table,
        so an edit made with any newer model got the literal string "Edit" and lost which
        model actually produced it."""
        asked = edit_task_network(_edit_task("3111000000000000001"), "Edit Ultra v2")
        row = _run_edit(tmp_path)
        assert asked == ["3111000000000000001"]
        assert row["model_name"] == "Edit Ultra v2"        # was the generic "Edit"
        assert row["model_id"] == "3111000000000000001"

    def test_an_unresolved_edit_model_is_left_repairable_by_fix_models(self, tmp_path,
                                                                      edit_task_network):
        """The permanent half of the bug: "Edit" is non-empty, non-digit and != the model id,
        so _needs_model_fix called the row RESOLVED and --fix-models never queued it again --
        the row was stuck showing "Edit" forever. Whatever the lookup returns now (its own
        soft-failure fallback is the id), the row stays in the repair queue."""
        edit_task_network(_edit_task("3111000000000000002"), lambda mid: mid)
        row = _run_edit(tmp_path)
        assert row["model_name"] != "Edit"
        assert core._needs_model_fix(row) == "3111000000000000002"

    def test_a_known_edit_model_keeps_its_local_label_without_a_lookup(self, tmp_path,
                                                                      edit_task_network):
        """The two models this app knows are still named locally -- no round trip, and the
        label a user already sees on those rows does not change."""
        known = core.EDIT_MODELS["reference-pro"]["model_id"]
        asked = edit_task_network(_edit_task(known), "should not be called")
        row = _run_edit(tmp_path)
        assert asked == []
        assert row["model_name"] == "Reference Pro"

    def test_a_chat_task_with_no_model_id_at_all_still_says_edit(self, tmp_path,
                                                                 edit_task_network):
        """The one case the generic label was ever right about: nothing to resolve, and
        _needs_model_fix returns '' for an id-less row either way, so "Edit" blocks no repair
        and beats an empty Model field."""
        edit_task_network(_edit_task(None), "unused")
        row = _run_edit(tmp_path)
        assert row["model_name"] == "Edit"
        assert core._needs_model_fix(row) == ""
