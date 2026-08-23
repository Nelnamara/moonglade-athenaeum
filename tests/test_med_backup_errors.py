"""Five error paths in moonglade_backup.py that used to fail SILENTLY (batch F).

Every test here fails against the pre-fix code, and each one is written from the shape of
the user-visible symptom rather than the internals, because the whole class of bug is
"the program knew something and did not say it":

  M01  resolve_media() swallowed a media-CDN TLS failure into the same soft (None, {}) as a
       genuinely missing image, so the corporate-proxy case printed only "no url for media".
  M03  _bookmarks_persisted() never checked the HTTP status, so an auth/gateway refusal
       carrying valid non-GraphQL JSON became an empty Bookmarks tab.
  M04  video_faststart() logged nothing for a non-zero ffmpeg exit (its most common failure),
       and run_faststart_videos() counted such a file as neither fixed nor skipped.
       Round 2: the first repair turned that silent undercount into a FALSE ALARM. The sweep
       asked "is it faststart?" itself and then called video_faststart, which asks again --
       so a live-mirror remux (or a Trash purge) landing between the two answers was reported
       as "FAILED -- still not iOS-playable" about a file that was, by then, fine.
  M05  list_claims() failing was indistinguishable from an account with nothing to claim.
  M16  `--generate --task-id` on a video/mixed task: the new video block could raise out of
       run_generate after the images were already saved AND cataloged (download() answers an
       SSLError with a PixAIError), losing the summary and the return dict; and a video-ONLY
       recovery was not counted as a recovery at all, because the telemetry bump sat inside
       `if rows:` and a video task produces no image rows.
  M18  a transient lookup failure let --fix-models --relabel-removed permanently write
       "Unknown or removed model" over a still-valid model, unrepairable by re-running.
       Round 2 widened the M18 cases past "the request raised": PixAI refuses a GraphQL
       request at HTTP 200 with an `errors` array, which raise_for_status() waves through --
       and unlike a network blip, that shape refuses every id in the run at once.
"""
import subprocess
from types import SimpleNamespace

import pytest
import requests

import moonglade_backup as core


@pytest.fixture()
def verbose():
    """Turn -v on for the duration of a test (and back off afterwards, always), so a vlog()
    line lands in capsys. M04's whole claim is 'must at least show under -v'."""
    core.set_verbose(True)
    try:
        yield
    finally:
        core.set_verbose(False)


def _mp4(*types):
    """Minimal mp4 of top-level boxes; moov AFTER mdat = not faststart (needs a remux)."""
    import struct
    out = b""
    for t in types:
        pay = b"\x00" * 8
        out += struct.pack(">I", 8 + len(pay)) + t + pay
    return out


# ---------------------------------------------------------------------------
# M01 -- resolve_media() and the media-CDN TLS failure
# ---------------------------------------------------------------------------

class TestM01ResolveMediaTls:
    def test_ssl_failure_prints_the_actionable_ssl_help(self, mock_session, monkeypatch, capsys):
        """gql()/download() answer an SSLError with _ssl_help(); resolve_media said nothing at
        all, so a fixable LOCAL trust problem read as 'PixAI does not have this image'."""
        monkeypatch.setattr(core, "_media_tls_warned", False)
        mock_session.get.side_effect = requests.exceptions.SSLError(
            "certificate verify failed: unable to get local issuer certificate")

        url, info = core.resolve_media(mock_session, "mid-tls-1")

        assert (url, info) == (None, {})          # still fails SOFT -- callers depend on it
        out = capsys.readouterr().out
        assert "SSL verification failed" in out   # the same words gql()/download() raise
        assert "pip install truststore" in out
        assert "certificate verify failed" in out

    def test_ssl_help_is_said_once_per_process(self, mock_session, monkeypatch, capsys):
        """MEDIA_BASE is one host: if its handshake fails it fails for every image. A
        17,000-image backup must not repeat the paragraph 17,000 times and bury it.

        The latch is per PROCESS, which is the same as per run for the CLI and deliberately
        is NOT inside the long-lived gallery server -- see _warn_media_tls_once, and do not
        "fix" the wording back to 'run'."""
        monkeypatch.setattr(core, "_media_tls_warned", False)
        mock_session.get.side_effect = requests.exceptions.SSLError("bad cert")

        for mid in ("a", "b", "c"):
            assert core.resolve_media(mock_session, mid) == (None, {})

        out = capsys.readouterr().out
        assert out.count("pip install truststore") == 1
        assert "Said once per process" in out          # the message must not overclaim

    def test_ordinary_network_failure_stays_quiet(self, mock_session, monkeypatch, capsys):
        """A timeout or a 404 is NOT a trust problem -- printing the TLS paragraph for one
        would be the same bug pointing the other way."""
        monkeypatch.setattr(core, "_media_tls_warned", False)
        mock_session.get.side_effect = requests.RequestException("read timeout")

        assert core.resolve_media(mock_session, "mid-plain") == (None, {})
        assert "truststore" not in capsys.readouterr().out

    def test_the_paragraph_is_one_write_so_a_progress_frame_cannot_split_it(
            self, mock_session, monkeypatch):
        """resolve_media runs on the DOWNLOAD POOL's threads while the main thread redraws
        the \\r progress bar, so a paragraph emitted as several print() calls could have a bar
        frame land between its lines -- shredding, on a busy terminal, the one message the
        user most needs to read whole. One write is what makes that impossible."""
        import sys

        class Recorder:
            def __init__(self):
                self.writes = []

            def write(self, s):
                self.writes.append(s)

            def flush(self):
                pass

        rec = Recorder()
        monkeypatch.setattr(core, "_media_tls_warned", False)
        monkeypatch.setattr(sys, "stdout", rec)
        mock_session.get.side_effect = requests.exceptions.SSLError("bad cert")

        core.resolve_media(mock_session, "mid-tls-atomic")

        assert len(rec.writes) == 1, (
            "the TLS paragraph went out in {} writes -- a progress frame can land between "
            "any two of them".format(len(rec.writes)))
        blob = rec.writes[0]
        assert blob.startswith("\n")                  # breaks off a partial \r bar frame
        assert "MEDIA CDN TLS verification failed" in blob
        assert "pip install truststore" in blob
        assert "Said once per process" in blob

    def test_the_progress_bar_cannot_be_drawn_inside_a_console_block(self, monkeypatch):
        """The same race from the other side. The paragraph being atomic is only half of it:
        the bar writer has to respect the same lock, or the two atomic writes still interleave
        on the terminal. Held here from the main thread; the callback must wait."""
        import threading

        cb = core._make_progress()
        wrote = threading.Event()
        core._CONSOLE_LOCK.acquire()
        try:
            t = threading.Thread(target=lambda: (cb(1, 10), wrote.set()))
            t.start()
            assert not wrote.wait(0.25), (
                "the progress bar was drawn while a console block held the lock")
        finally:
            core._CONSOLE_LOCK.release()
        assert wrote.wait(2), "the progress bar never resumed after the lock was released"
        t.join()


# ---------------------------------------------------------------------------
# M03 -- _bookmarks_persisted() must not turn a refusal into an empty list
# ---------------------------------------------------------------------------

def _persisted_args():
    return dict(variables={}, want_lora=False, lbt="", kw="", after="", limit=24)


class TestM03BookmarksStatus:
    def test_raises_on_401_instead_of_returning_empty(self, mock_session, mocker):
        """A stale U3T / expired key answers with a plain REST-shaped body that has no
        'errors' array, so the old shape-only check fell through to `or {}` and the user saw
        an empty Bookmarks tab for a request that never ran."""
        resp = mocker.MagicMock()
        resp.status_code = 401
        resp.ok = False
        resp.text = '{"statusCode":401,"message":"Unauthorized"}'
        resp.json.return_value = {"statusCode": 401, "message": "Unauthorized"}
        mock_session.get.return_value = resp

        with pytest.raises(core.PixAIError, match="401"):
            core._bookmarks_persisted(mock_session, **_persisted_args())

    def test_raises_on_non_graphql_body_even_with_http_200(self, mock_session, mocker):
        """A gateway can answer 200 with its own JSON. A real GraphQL reply always carries a
        'data' key, so its absence -- not the status alone -- is the reliable tell."""
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.ok = True
        resp.text = '{"statusCode":502,"message":"Bad Gateway"}'
        resp.json.return_value = {"statusCode": 502, "message": "Bad Gateway"}
        mock_session.get.return_value = resp

        with pytest.raises(core.PixAIError, match="non-GraphQL"):
            core._bookmarks_persisted(mock_session, **_persisted_args())

    def test_still_returns_the_connection_on_success(self, mock_session, mocker):
        """The guards must not start rejecting good answers -- including a legitimately
        EMPTY bookmark list, which is a real state and not an error."""
        conn = {"totalCount": 0, "pageInfo": {"hasNextPage": False}, "edges": []}
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.ok = True
        resp.json.return_value = {"data": {"me": {"bookmarkedGenerationModels": conn}}}
        mock_session.get.return_value = resp

        assert core._bookmarks_persisted(mock_session, **_persisted_args()) == conn

    def test_persisted_query_rotation_still_gets_its_own_message(self, mock_session, mocker):
        """An APQ miss answers {"errors":[...]} with NO 'data' key at all, so the errors
        branch has to be tested before the shape guard or the self-healing hint is lost."""
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.ok = True
        resp.text = ""
        resp.json.return_value = {"errors": [{"message": "PersistedQueryNotFound"}]}
        mock_session.get.return_value = resp

        with pytest.raises(core.PixAIError, match="hash has rotated"):
            core._bookmarks_persisted(mock_session, **_persisted_args())


# ---------------------------------------------------------------------------
# M04 -- a non-zero ffmpeg exit is a normal failure, and must be visible + counted
# ---------------------------------------------------------------------------

def _ffmpeg_refuses(monkeypatch, stderr=b"[mp4 @ 0x55] could not find sample table\n"):
    """ffmpeg exits non-zero and writes no usable temp -- a genuine refusal."""
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        seen.setdefault("calls", []).append(cmd)
        # A faithful CompletedProcess shape: media_tools' runner reads BOTH streams
        # (stderr is where ffmpeg says why it refused; stdout is piped too, and with
        # -v error it is empty on every road).
        return SimpleNamespace(returncode=1, stdout=b"", stderr=stderr)
    monkeypatch.setattr(subprocess, "run", fake_run)
    return seen


def _ffmpeg_succeeds(monkeypatch):
    """ffmpeg writes its temp and exits 0 -- the remux worked."""
    def fake_run(cmd, **kw):
        from pathlib import Path
        Path(cmd[-1]).write_bytes(_mp4(b"ftyp", b"moov", b"mdat"))
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
    monkeypatch.setattr(subprocess, "run", fake_run)


class TestM04Faststart:
    def test_nonzero_ffmpeg_exit_is_logged_with_its_stderr(self, tmp_path, monkeypatch,
                                                           verbose, capsys):
        """ffmpeg refusing `-c copy` raises nothing -- it just exits non-zero. That branch
        produced no message even under -v, contradicting the function's own comment, and
        stderr (the only place ffmpeg says WHY) was thrown at DEVNULL."""
        clip = tmp_path / "nf.mp4"
        clip.write_bytes(_mp4(b"ftyp", b"mdat", b"moov"))
        before = clip.read_bytes()
        monkeypatch.setattr(core, "ffmpeg_path", lambda: "ffmpeg")
        seen = _ffmpeg_refuses(
            monkeypatch, b"[mp4 @ 0x55] track 1: could not find sample table\n")

        assert core.video_faststart(clip) is False
        out = capsys.readouterr().out
        assert "ffmpeg exit 1" in out
        assert "could not find sample table" in out          # ffmpeg's own reason survives
        assert seen.get("stderr") is subprocess.PIPE         # captured, not DEVNULL
        assert clip.read_bytes() == before                   # original untouched
        assert not list(tmp_path.glob("*__fstmp__*"))        # temp cleaned up

    def test_a_refusal_and_a_no_op_are_no_longer_the_same_answer(self, tmp_path, monkeypatch):
        """The distinction the sweep below is built on. `video_faststart` returns False for
        both "ffmpeg refused" and "there was nothing to do", which is fine for the collect-time
        callers that only want the file made streamable -- but a sweep that has to name the
        clips still broken cannot tell them apart, and so named the wrong ones."""
        monkeypatch.setattr(core, "ffmpeg_path", lambda: "ffmpeg")
        already = tmp_path / "already.mp4"
        already.write_bytes(_mp4(b"ftyp", b"moov", b"mdat"))
        gone = tmp_path / "gone.mp4"
        broken = tmp_path / "broken.mp4"
        broken.write_bytes(_mp4(b"ftyp", b"mdat", b"moov"))
        _ffmpeg_refuses(monkeypatch)

        assert core._video_faststart_attempt(already) == core.FASTSTART_NOT_NEEDED
        assert core._video_faststart_attempt(gone) == core.FASTSTART_NOT_NEEDED
        assert core._video_faststart_attempt(broken) == core.FASTSTART_REFUSED
        assert core.video_faststart(broken) is False      # the bool face is unchanged

    def test_run_faststart_accounts_for_every_video(self, tmp_path, monkeypatch, capsys):
        """fixed + skipped used to be less than total when a clip was refused, with nothing
        naming the file that is STILL not iOS-playable -- the one thing the command exists
        to tell you."""
        vdir = tmp_path / "videos"
        vdir.mkdir()
        (vdir / "ok.mp4").write_bytes(_mp4(b"ftyp", b"moov", b"mdat"))    # already faststart
        (vdir / "broken.mp4").write_bytes(_mp4(b"ftyp", b"mdat", b"moov"))
        monkeypatch.setattr(core, "ffmpeg_path", lambda: "ffmpeg")
        _ffmpeg_refuses(monkeypatch)                                      # ffmpeg refuses it

        res = core.run_faststart_videos(SimpleNamespace(out=str(tmp_path)))

        assert res["failed"] == 1
        assert res["fixed"] + res["skipped"] + res["failed"] == res["total"] == 2
        assert "broken.mp4" in capsys.readouterr().out

    def test_a_clip_another_collector_remuxed_mid_sweep_is_not_called_a_failure(
            self, tmp_path, monkeypatch, capsys):
        """The false alarm the first repair introduced, under concurrency wiki/Backing-Up.md
        explicitly blesses ("safe to run while the gallery or a live watch is collecting").

        The sweep asked `_mp4_is_faststart` itself, then called `video_faststart`, which asks
        the SAME question again -- and the live mirror remuxing that clip in between made the
        two answers disagree. A disagreement was reported as "FAILED <name> -- still not
        iOS-playable" and counted in `failed`, for a file that had just been fixed.

        Modelled exactly: False to whoever asks first, True to anyone who asks after. Against
        the pre-fix code the counter reaches 2 and the run reports one failure; the fix is
        that there is only ever ONE asker, so there is no disagreement to misread.
        """
        vdir = tmp_path / "videos"
        vdir.mkdir()
        (vdir / "raced.mp4").write_bytes(_mp4(b"ftyp", b"mdat", b"moov"))
        monkeypatch.setattr(core, "ffmpeg_path", lambda: "ffmpeg")
        _ffmpeg_succeeds(monkeypatch)
        asked = {"n": 0}

        def racing(p):
            asked["n"] += 1
            return asked["n"] > 1          # the mirror won the race after the first check
        monkeypatch.setattr(core, "_mp4_is_faststart", racing)

        res = core.run_faststart_videos(SimpleNamespace(out=str(tmp_path)))

        assert asked["n"] == 1, (
            "the sweep asked 'is it faststart?' {} times -- two askers can disagree, and the "
            "disagreement is what got reported as a failure".format(asked["n"]))
        assert res["failed"] == 0
        out = capsys.readouterr().out
        assert "still not iOS-playable" not in out
        assert "still not faststart" not in out

    def test_a_clip_purged_from_trash_mid_sweep_is_not_called_a_failure(
            self, tmp_path, monkeypatch, capsys):
        """Same shape, other cause: the gallery's Trash purge removes the clip while the
        sweep is on it. ffmpeg then fails because its INPUT is gone, which is not a refusal --
        there is no file left to be 'still not iOS-playable'. Pre-fix, the sweep's own check
        ran while the file existed and video_faststart's `p.exists()` ran after it did not, so
        the run named a path the user cannot even go and look at."""
        vdir = tmp_path / "videos"
        vdir.mkdir()
        clip = vdir / "purged.mp4"
        clip.write_bytes(_mp4(b"ftyp", b"mdat", b"moov"))
        monkeypatch.setattr(core, "ffmpeg_path", lambda: "ffmpeg")
        _ffmpeg_refuses(monkeypatch, b"purged.mp4: No such file or directory\n")

        def purge_then_answer(p):
            core.Path(p).unlink(missing_ok=True)     # Trash purge lands right here
            return False
        monkeypatch.setattr(core, "_mp4_is_faststart", purge_then_answer)

        res = core.run_faststart_videos(SimpleNamespace(out=str(tmp_path)))

        assert res["failed"] == 0 and res["skipped"] == 1
        assert "still not iOS-playable" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# M05 -- "the fetch failed" is not "you have nothing to claim"
# ---------------------------------------------------------------------------

class TestM05Claims:
    def test_list_claims_carries_the_failure_reason(self):
        """conftest blocks live /v2, so _rest_get raises here exactly as a 5xx would. The
        fail-soft contract (an empty list) is preserved for the gallery's callers."""
        res = core.list_claims(object())

        assert res == []                              # unchanged for every existing caller
        assert getattr(res, "error", "")              # ...but it now says why

    def test_run_claims_does_not_call_a_failed_fetch_empty(self, monkeypatch, capsys):
        """The bug in one line: a ready daily-credit reward went unclaimed because a
        transient 5xx printed 'No claimable rewards found'."""
        monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())

        res = core.run_claims(SimpleNamespace(token=None, claims=True, claim="", confirm=False))

        out = capsys.readouterr().out
        assert "No claimable rewards found" not in out
        assert "Could NOT read your claimable rewards" in out
        assert res.get("error")

    def test_genuinely_empty_still_reads_as_empty(self, monkeypatch, capsys):
        """The other half of the distinction -- and proof a caller handing back a PLAIN list
        (no .error attribute) still works, which is how the existing tests stub this."""
        monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
        monkeypatch.setattr(core, "list_claims", lambda s: [])

        res = core.run_claims(SimpleNamespace(token=None, claims=True, claim="", confirm=False))

        assert res == {"rewards": 0}
        assert "No claimable rewards found" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# M18 -- a failed lookup must never be mistaken for a removed model
# ---------------------------------------------------------------------------

def _model_cache():
    """model_name_gql memoises into a module-level default arg; reach it to assert WHAT got
    cached, since caching a failure as if it were an answer is half of this bug."""
    cache = core.model_name_gql.__defaults__[0]
    assert isinstance(cache, dict)
    return cache


def _reply(mocker, payload, status=200, text=""):
    """A response object that answers with `payload`, the way PixAI actually answers.

    Note the default status: PixAI refuses a GraphQL request with HTTP **200** plus an
    `errors` array (that is why gql() reads `errors` before it looks at the status at all,
    and why CLAUDE.md has a recapture procedure for PersistedQueryNotFound). A stub that only
    ever fails by raising -- which is all the first repair's tests did -- cannot see this.
    """
    r = mocker.MagicMock()
    r.status_code = status
    r.ok = status < 400
    r.text = text or str(payload)
    r.json.return_value = payload
    r.raise_for_status.side_effect = (
        None if status < 400 else requests.HTTPError("HTTP {}".format(status)))
    return r


def _catalog_with_one_row(tmp_path, vid):
    from moonglade_gallery import save_catalog, CATALOG_FIELDS
    db = tmp_path / "catalog.db"
    save_catalog(db, [{f: "" for f in CATALOG_FIELDS} | {
        "media_id": "m1", "filename": "a.png", "model_id": vid, "model_name": vid}])
    return db


class TestM18ModelLookupFailure:
    def test_strict_raises_while_soft_callers_still_get_the_id(self, mock_session, monkeypatch):
        monkeypatch.setattr(core, "MODEL_DETAIL_HASH", "fakehash")
        mock_session.get.side_effect = requests.RequestException("connection reset")
        mid = "m18-strict-0001"

        with pytest.raises(core.PixAIError, match="lookup failed"):
            core.model_name_gql(mock_session, mid, strict=True)
        # every other caller only wants a label, and keeps the old fallback unchanged
        assert core.model_name_gql(mock_session, mid) == mid

    def test_failure_is_not_memoised_as_a_name(self, mock_session, monkeypatch):
        """--sync runs the full-meta pass and --fix-models in ONE process, sharing this
        cache. Caching the id on failure laundered a blip into a 'resolved to its own id'
        verdict for the relabel step that came after it."""
        monkeypatch.setattr(core, "MODEL_DETAIL_HASH", "fakehash")
        mock_session.get.side_effect = requests.RequestException("timeout")
        mid = "m18-cache-0001"

        assert core.model_name_gql(mock_session, mid) == mid        # soft caller goes first
        assert _model_cache().get(mid) is core._MODEL_LOOKUP_FAILED
        with pytest.raises(core.PixAIError):                        # the verdict survives
            core.model_name_gql(mock_session, mid, strict=True)

    def test_absent_hash_is_a_real_cannot_resolve_not_a_failure(self, mock_session, monkeypatch):
        """An unconfigured install asks nothing and falls back to the id by design; that is
        an answer, not a failure, and strict mode must not start raising on it."""
        monkeypatch.setattr(core, "MODEL_DETAIL_HASH", "")
        mid = "m18-nohash-0001"

        assert core.model_name_gql(mock_session, mid, strict=True) == mid

    def test_relabel_removed_refuses_to_act_on_a_failed_lookup(self, tmp_path, monkeypatch,
                                                               mocker):
        """THE BUG. One timeout mid-run used to write 'Unknown or removed model' over every
        row of a still-valid model, and _needs_model_fix then read those rows as resolved --
        so re-running --fix-models never repaired it. Permanent, without editing the DB."""
        from moonglade_gallery import save_catalog, load_catalog, CATALOG_FIELDS
        vid = "918273645500000001"
        db = tmp_path / "catalog.db"
        save_catalog(db, [
            {f: "" for f in CATALOG_FIELDS} | {"media_id": "m1", "filename": "a.png",
                                               "model_id": vid, "model_name": vid},
            {f: "" for f in CATALOG_FIELDS} | {"media_id": "m2", "filename": "b.png",
                                               "model_id": vid, "model_name": vid},
        ])
        monkeypatch.setattr(core, "MODEL_DETAIL_HASH", "fakehash")
        session = mocker.MagicMock()
        session.get.side_effect = requests.RequestException("503 from the API")
        mocker.patch.object(core, "_make_session", return_value=session)

        res = core.run_fix_models(SimpleNamespace(
            out=str(tmp_path), token=None, delay=0, relabel_removed=True))

        rows = {r["media_id"]: r for r in load_catalog(db)}
        assert rows["m1"]["model_name"] == vid          # NOT "Unknown or removed model"
        assert rows["m2"]["model_name"] == vid
        assert res["relabeled"] == 0
        assert res["lookup_failed"] == 1
        # and the rows are still queued for the next run, i.e. the damage is repairable
        assert core._needs_model_fix(rows["m1"]) == vid

    @pytest.mark.parametrize("payload,status,what", [
        ({"errors": [{"message": "PersistedQueryNotFound"}]}, 200,
         "a rotated persisted hash -- refuses EVERY id in the run"),
        ({"errors": [{"message": "Not authenticated"}]}, 200,
         "an auth failure PixAI surfaces as a resolver error, not a 401"),
        ({"errors": [{"message": "Internal server error"}], "data": None}, 200,
         "the Prisma internal error this codebase already documents"),
        ({"statusCode": 401, "message": "Unauthorized"}, 200,
         "an edge that answers in valid, non-GraphQL JSON"),
        ({"data": {}}, 200,
         "a reply that never carried the field we asked about"),
    ])
    def test_a_refusal_answered_at_http_200_is_a_failure_not_a_verdict(
            self, tmp_path, monkeypatch, mocker, payload, status, what):
        """THE ROUND-2 BUG, and the one with the widest blast radius.

        `raise_for_status()` sees nothing wrong with any of these, so the first repair --
        which treated only an EXCEPTION as a failure -- read an empty payload as "PixAI
        answered and this model has no name", cached the id as if it were a name, and let
        --relabel-removed stamp "Unknown or removed model" over the row. A network blip hits
        one id; every shape here refuses ALL of them, so one run would have destroyed the
        model provenance of the whole catalog, unrepairable without editing the DB.
        """
        vid = "918273645500000003"
        db = _catalog_with_one_row(tmp_path, vid)
        monkeypatch.setattr(core, "MODEL_DETAIL_HASH", "fakehash")
        session = mocker.MagicMock()
        session.get.return_value = _reply(mocker, payload, status)
        mocker.patch.object(core, "_make_session", return_value=session)

        res = core.run_fix_models(SimpleNamespace(
            out=str(tmp_path), token=None, delay=0, relabel_removed=True))

        from moonglade_gallery import load_catalog
        row = load_catalog(db)[0]
        assert row["model_name"] == vid, what
        assert res["relabeled"] == 0 and res["lookup_failed"] == 1
        assert core._needs_model_fix(row) == vid        # still repairable by a re-run
        assert _model_cache().get(vid) is core._MODEL_LOOKUP_FAILED

    def test_a_200_with_errors_is_not_laundered_through_the_cache_into_sync(
            self, mock_session, monkeypatch, mocker):
        """--sync runs the full-meta pass and --fix-models in ONE process off this cache. A
        soft caller meeting the 200+errors body first must not park the id in the cache as a
        name, or the relabel step behind it gets a cache HIT and reads it as resolved."""
        monkeypatch.setattr(core, "MODEL_DETAIL_HASH", "fakehash")
        mid = "m18-gqlerr-0001"
        mock_session.get.return_value = _reply(
            mocker, {"errors": [{"message": "PersistedQueryNotFound"}]})

        assert core.model_name_gql(mock_session, mid) == mid     # soft caller: label only
        assert _model_cache().get(mid) is core._MODEL_LOOKUP_FAILED
        with pytest.raises(core.PixAIError, match="lookup failed"):
            core.model_name_gql(mock_session, mid, strict=True)

    def test_relabel_removed_still_relabels_a_genuinely_removed_model(self, tmp_path,
                                                                      monkeypatch, mocker):
        """The conservative guard must not neuter the flag: PixAI ANSWERING with a null
        version really does mean the model is gone, and that still gets relabelled."""
        from moonglade_gallery import save_catalog, load_catalog, CATALOG_FIELDS
        vid = "918273645500000002"
        db = tmp_path / "catalog.db"
        save_catalog(db, [
            {f: "" for f in CATALOG_FIELDS} | {"media_id": "m1", "filename": "a.png",
                                               "model_id": vid, "model_name": vid},
        ])
        monkeypatch.setattr(core, "MODEL_DETAIL_HASH", "fakehash")
        resp = mocker.MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"data": {"generationModelVersion": None}}
        session = mocker.MagicMock()
        session.get.return_value = resp
        mocker.patch.object(core, "_make_session", return_value=session)

        res = core.run_fix_models(SimpleNamespace(
            out=str(tmp_path), token=None, delay=0, relabel_removed=True))

        rows = {r["media_id"]: r for r in load_catalog(db)}
        assert rows["m1"]["model_name"] == "Unknown or removed model"
        assert res["relabeled"] == 1 and res["lookup_failed"] == 0


# ---------------------------------------------------------------------------
# M16 -- collecting a video through --generate must not eat the run, or the ledger
# ---------------------------------------------------------------------------

_MIXED_TASK = {
    "id": "TM1",
    "createdAt": "2026-07-27T00:00:00Z",
    "parameters": {"referenceVideo": {"prompt": "a moonlit lake", "duration": 5}},
    "outputs": {"mediaId": "IMG1", "seed": "5",
                "videos": [{"mediaId": "VID9", "thumbnailMediaId": "POST9", "seed": "42"}]},
}

_VIDEO_ONLY_TASK = {
    "id": "TV2",
    "createdAt": "2026-07-27T00:00:00Z",
    "parameters": {"referenceVideo": {"prompt": "a moonlit lake", "duration": 5}},
    "outputs": {"videos": [{"mediaId": "VID9", "thumbnailMediaId": "POST9", "seed": "42"}]},
}


@pytest.fixture()
def recovery_network(monkeypatch):
    """Stub every network touch of a `--generate --task-id` recovery, and record telemetry.

    Returns (install, bumps): `install(task, video_download)` wires the task getTaskById
    returns and how download() behaves for the .mp4, and `bumps` collects the names passed to
    moonglade_gallery.telem_bump (imported inside run_generate, so patching the module
    attribute is what the call actually sees).
    """
    import moonglade_gallery as gallery
    bumps = []

    def install(task, video_download="ok"):
        monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
        monkeypatch.setattr(core, "task_detail_gql", lambda s, t: task)
        monkeypatch.setattr(core, "media_file_gql",
                            lambda s, mid: {"fileUrl": "https://cdn/{}.mp4".format(mid)})
        monkeypatch.setattr(core, "resolve_media",
                            lambda s, mid: ("https://cdn/{}.png".format(mid),
                                            {"width": 8, "height": 8}))
        monkeypatch.setattr(core, "video_faststart", lambda p: True)
        monkeypatch.setattr(core, "video_poster_thumb", lambda *a, **k: None)
        monkeypatch.setattr(gallery, "make_thumbnail", lambda *a, **k: None)
        monkeypatch.setattr(gallery, "telem_bump",
                            lambda name, out_dir=None: bumps.append(name))

        def fake_download(session, url, stem, **kw):
            from pathlib import Path
            if url.endswith(".mp4") and video_download != "ok":
                # download() answers an SSLError with `raise PixAIError(_ssl_help())` -- the
                # corporate-proxy/antivirus case the whole _ssl_help paragraph exists for.
                raise core.PixAIError("SSL verification failed (proxy intercepting HTTPS)")
            path = Path(str(stem) + (".mp4" if url.endswith(".mp4") else ".png"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\x00binary")
            return "ok", path

        monkeypatch.setattr(core, "download", fake_download)

    return install, bumps


class TestM16VideoCollectionFailsSoft:
    def _run(self, tmp_path, task_id):
        return core.run_generate(SimpleNamespace(
            out=str(tmp_path), params_json='{"prompts": "x", "modelId": "v"}',
            confirm=False, task_id=task_id, token=None))

    def test_a_failed_video_fetch_does_not_swallow_the_images_already_saved(
            self, tmp_path, capsys, recovery_network):
        """The image half of this command walks past an image it cannot fetch with a
        `continue`. The video block had no equivalent, so a media-CDN TLS failure inside
        download() escaped through main's handler AFTER save_catalog had already run: the
        images were on disk and in the catalog, and the user got an error exit instead of the
        summary listing them. run_generate's return dict never happened either, so any caller
        reading it saw nothing at all.

        Against the pre-fix code this test errors out of run_generate with PixAIError.
        """
        install, _bumps = recovery_network
        install(_MIXED_TASK, video_download="ssl-error")

        res = self._run(tmp_path, "TM1")

        assert res == {"submitted": True, "task_id": "TM1", "images": 1, "videos": 0}
        out = capsys.readouterr().out
        assert "video collection FAILED" in out
        assert "SSL verification failed" in out          # WHY, not just THAT
        # The clip is paid for and still on PixAI: name the command that gets it for free.
        assert "--generate-video --task-id TM1" in out
        assert "Generated + cataloged 1 image(s)" in out

    def test_the_image_rows_survive_a_failed_video_fetch(self, tmp_path, recovery_network):
        """Not just the summary text -- the catalog itself. The images were saved before the
        video block ran, so an escape there loses the report, never the data; this pins that
        the soft-fail did not change what is on disk."""
        from moonglade_gallery import load_catalog
        install, _bumps = recovery_network
        install(_MIXED_TASK, video_download="ssl-error")

        self._run(tmp_path, "TM1")

        rows = load_catalog(tmp_path / "catalog.db")
        assert [r["media_id"] for r in rows] == ["IMG1"]
        assert rows[0]["filename"].startswith("images/")


class TestM16RecoveryIsCounted:
    def _run(self, tmp_path, task_id):
        return core.run_generate(SimpleNamespace(
            out=str(tmp_path), params_json='{"prompts": "x", "modelId": "v"}',
            confirm=False, task_id=task_id, token=None))

    def test_a_video_only_recovery_counts_as_a_recovery(self, tmp_path, recovery_network):
        """'Against the Void' rewards pulling a stranded, ALREADY PAID FOR task back by id.
        The bump lived inside `if rows:` -- and a video-only task produces no image rows by
        construction, so the one recovery most worth counting (a paid video render) moved
        nothing. Against the pre-fix code `bumps` comes back empty."""
        install, bumps = recovery_network
        install(_VIDEO_ONLY_TASK)

        res = self._run(tmp_path, "TV2")

        assert res["videos"] == 1 and res["images"] == 0
        assert bumps == ["recover_events"]

    def test_a_recovery_that_saved_nothing_is_still_not_counted(self, tmp_path,
                                                                recovery_network):
        """The boundary in the other direction: 'recovered' has to mean something came back.
        A video-only task whose clip could not be fetched rescued nothing, so nothing is
        counted -- the ledger must not reward a run that ended empty-handed."""
        install, bumps = recovery_network
        install(_VIDEO_ONLY_TASK, video_download="ssl-error")

        res = self._run(tmp_path, "TV2")

        assert res["images"] == 0 and res["videos"] == 0
        assert bumps == []

    def test_a_mixed_recovery_is_counted_exactly_once(self, tmp_path, recovery_network):
        """One task pulled back is one recovery, however many kinds of output it held --
        moving the bump out of `if rows:` must not start double-counting it."""
        install, bumps = recovery_network
        install(_MIXED_TASK)

        res = self._run(tmp_path, "TM1")

        assert res["images"] == 1 and res["videos"] == 1
        assert bumps == ["recover_events"]
