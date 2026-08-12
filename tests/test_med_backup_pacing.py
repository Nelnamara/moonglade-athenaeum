"""M07 -- the parallel download stage ignored --delay entirely (batch: pacing).

`--delay` is documented as a politeness throttle that applies to most commands, not just to
downloads, and "be polite to their servers (paced requests)" is a standing rule of this
project. The serial download loop honours it (one sleep per downloaded image) and
_parallel_map honours it (one global slot per item, so the pool as a whole starts at most one
request per delay). run_download's OWN inline pool -- the branch taken by the default
`--workers 4`, i.e. by plain `python moonglade_backup.py`, the single highest-traffic code
path in the tool -- paced only the page listing and the per-task full-meta fetch, and then
fired up to 250 resolve_media + download pairs per page with nothing at all between them.

So the tests here are written from the wire, not from the internals: how far apart do the
per-image requests actually start, and does honouring the flag quietly cost the pool its
concurrency (the obvious wrong fix -- a per-thread sleep -- would still burst at
workers x rate; the other wrong fix -- serialising -- would make `--workers` a lie).

ROUND 2 (2026-07-27) added the other half of the contract, which the first repair got wrong
in the expensive direction: it paced the pool off the ARGPARSE DEFAULT, so every existing
install -- none of which ever asked for a download throttle -- was silently capped at
1/0.4 = 2.5 images/sec no matter how many workers, and CLAUDE.md's own `--workers 8
--page-size 500  # fast full backfill` stopped being fast. The gate now installs only when
the user TYPED --delay. Both states are pinned below, and so is the distinction itself,
end to end through the real CLI parser -- because `--delay 0.4` typed by hand and `--delay`
never mentioned produce the same NUMBER, and a repair that compares numbers overrides a
deliberate choice.
"""
import sys
import threading
import time
from types import SimpleNamespace

import pytest

import moonglade_backup as core


def _dl_args(out, **kw):
    """A default-shaped download run: parallel branch, nothing exotic turned on."""
    base = dict(
        out=str(out), token="t", page_size=20, max=0, delay=0.05, workers=4,
        name_length=40, name_sep="_",
        convert=None, jpeg_quality=92, jpeg_bg="white", keep_webp=False,
        collect_only=False, full_meta=False, update=False, update_grace=2,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _one_page(mids):
    """One listing page holding a single task whose batch carries every media_id.

    A batch keeps the page-listing fetch (which was ALREADY paced, and would otherwise
    contaminate the timings we are measuring) down to exactly one request, so every interval
    the tests observe belongs to the per-image work under test.
    """
    node = {"id": "task_batch", "mediaId": mids[0], "batchMediaIds": list(mids),
            "createdAt": "2024-01-01T00:00:00", "promptsPreview": "p", "status": "ok"}
    return {"user": {"taskSummaries": {
        "edges": [{"node": node}],
        "pageInfo": {"hasPreviousPage": False, "startCursor": ""}}}}


def _patch_download_layer(mocker, on_resolve=None, on_download=None):
    mocker.patch.object(core, "_make_session", return_value=mocker.MagicMock())
    mocker.patch.object(core, "_quick_count", return_value=0)

    def fake_resolve(session, mid):
        if on_resolve:
            on_resolve(mid)
        return ("http://x/" + mid, {"width": "1", "height": "1"})

    def fake_download(session, url, stem, **kw):
        if on_download:
            on_download(url)
        dest = stem.with_suffix(".webp")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"img")
        return ("ok", dest)

    mocker.patch.object(core, "resolve_media", side_effect=fake_resolve)
    mocker.patch.object(core, "download", side_effect=fake_download)


class TestM07ParallelDownloadHonoursDelay:
    def test_an_explicitly_chosen_delay_paces_the_whole_pool(self, tmp_path, mocker):
        """THE bug: with `--workers 4` the per-image requests went out back-to-back at
        whatever rate the network returned them -- --delay bought the user nothing on the one
        command they run most. Against the pre-fix code all six resolves start inside the same
        millisecond, so both assertions below fail.

        `delay=0.05` here is a plain float, which is what argparse produces from a TYPED
        --delay (and what a caller that builds its own args namespace means). That is the
        state the throttle applies in; the default state is the next test.

        The pace is GLOBAL, not per thread: four threads each sleeping `delay` would still
        put four requests on the wire per slot, which is the burst the flag exists to stop.
        """
        starts = []
        _patch_download_layer(mocker, on_resolve=lambda mid: starts.append(time.monotonic()))
        mids = ["m%d" % i for i in range(6)]
        mocker.patch.object(core, "gql", side_effect=[_one_page(mids)])

        core.run_download(_dl_args(tmp_path, delay=0.05, workers=4))

        assert len(starts) == len(mids), "every image must still be fetched exactly once"
        starts.sort()
        # Measured across the resolves themselves, not the whole run: setup (db create,
        # catalog upsert) costs enough wall clock that a total-runtime bound would pass even
        # for a pool that fired all six requests in the same millisecond.
        span = starts[-1] - starts[0]
        # 6 starts one slot apart is 5 gaps of real time.sleep, which is a FLOOR: machine
        # load can only push this span higher, never below the bound, so it never flakes
        # red. An unpaced pool spans ~0s and cannot reach it. The finer contract -- each
        # slot exactly `delay` apart, global not per-thread -- is pinned deterministically
        # by TestPaceGate below; asserting it here on RECORDED wall-clock times only measured
        # scheduling jitter (the recording runs after pace() returns) and was the flake.
        assert span >= 0.05 * 5 * 0.8, (
            "6 images all started within {:.3f}s -- the pool ignored --delay".format(span))

    def test_pacing_did_not_quietly_turn_the_pool_serial(self, tmp_path, mocker):
        """The other way to get this wrong. Honouring --delay must gate when each request
        STARTS, not hold a lock across the request itself: with a delay well under the time a
        download takes, several downloads have to be in flight at once, or `--workers` has
        stopped meaning anything and a large backup slows to the serial path's wall clock.

        The proof is OVERLAP, not wall clock: if two downloads are ever in flight at once the
        pool did not serialise. That is a property of concurrency, not of speed, so it holds
        on any machine (the GIL releases inside the download's sleep, so the pool's threads
        run concurrently however loaded the box is). A bound on total runtime instead would
        flake under load for a property load has nothing to do with -- which is exactly the
        de-flake this pass makes.
        """
        lock = threading.Lock()
        live = {"now": 0, "peak": 0}

        def slow_download(url):
            with lock:
                live["now"] += 1
                live["peak"] = max(live["peak"], live["now"])
            time.sleep(0.15)
            with lock:
                live["now"] -= 1

        _patch_download_layer(mocker, on_download=slow_download)
        mids = ["m%d" % i for i in range(8)]
        mocker.patch.object(core, "gql", side_effect=[_one_page(mids)])

        core.run_download(_dl_args(tmp_path, delay=0.02, workers=4))

        assert live["peak"] >= 2, (
            "no two downloads ever overlapped -- the pace gate serialised the pool")

    def test_a_defaulted_delay_leaves_the_download_stage_at_full_speed(self, tmp_path, mocker):
        """The regression the first repair shipped, and the reason this test exists.

        `core.DEFAULT_DELAY` is precisely what `args.delay` holds when the user never typed
        the flag -- the value argparse hands over untouched. Pacing off it capped the DEFAULT
        backup at one image per 0.4s across the whole pool: 17,000 images could not finish
        their download stage in under 1h53m however many workers were asked for, and the
        Control Panel's Download-workers selector (which spawns the CLI with --workers N and
        no --delay at all) stopped meaning anything.

        Six images at 0.4s a slot is >= 2s of pure gate. The bound below is a twentieth of
        that, so the paced build cannot reach it however fast the machine is.
        """
        starts = []
        _patch_download_layer(mocker, on_resolve=lambda mid: starts.append(time.monotonic()))
        mids = ["m%d" % i for i in range(6)]
        mocker.patch.object(core, "gql", side_effect=[_one_page(mids)])

        core.run_download(_dl_args(tmp_path, delay=core.DEFAULT_DELAY, workers=4))

        assert len(starts) == len(mids), "every image must still be fetched exactly once"
        span = max(starts) - min(starts)
        assert span < 0.1, (
            "6 images spread over {:.3f}s on a DEFAULTED --delay -- the download stage is "
            "being throttled without the user asking".format(span))

    def test_the_banner_only_claims_pacing_when_pacing_happens(self, tmp_path, mocker, capsys):
        """A banner that says "paced to one image per 0.4s across the pool" while the pool is
        running flat out is worse than no banner: it is the line an owner would quote back
        when asking why their backup is slow, and it would send them chasing a throttle that
        is not there."""
        _patch_download_layer(mocker)
        mocker.patch.object(core, "gql", side_effect=[_one_page(["m1"])])
        core.run_download(_dl_args(tmp_path, delay=core.DEFAULT_DELAY, workers=4))
        out = capsys.readouterr().out
        assert "Parallel downloads: 4 workers." in out
        assert "paced" not in out

        _patch_download_layer(mocker)
        mocker.patch.object(core, "gql", side_effect=[_one_page(["m1"])])
        core.run_download(_dl_args(tmp_path / "b", delay=0.01, workers=4))
        assert "paced to one image per 0.01s across the pool" in capsys.readouterr().out


class TestM07DelayWasChosen:
    """Told apart through the REAL CLI parser, not by comparing numbers.

    `--delay 0.4` typed by hand and `--delay` never mentioned yield the same float, so any
    `== 0.4` or `== parser.get_default("delay")` test silently overrides a user who happened
    to choose the shipped value. These go through main()'s own argparse, exiting early on
    --list-web-users (the first command main dispatches, before it touches the network or the
    library), so what is pinned is the parser as shipped rather than a stand-in for it.
    """

    def _parse(self, tmp_path, mocker, *argv):
        seen = {}
        mocker.patch.object(core, "run_list_web_users", side_effect=lambda a: seen.update(a=a))
        mocker.patch.object(sys, "argv", ["moonglade_backup.py", "--out", str(tmp_path),
                                          "--list-web-users"] + list(argv))
        import moonglade_logging
        try:
            core.main()
        finally:
            moonglade_logging._reset_for_tests()
        return seen["a"]

    def test_an_untouched_flag_reads_as_not_chosen(self, tmp_path, mocker):
        args = self._parse(tmp_path, mocker)
        assert args.delay == 0.4                      # the documented default still applies
        assert core._delay_was_chosen(args) is False

    def test_typing_the_default_value_still_counts_as_choosing_it(self, tmp_path, mocker):
        """The case a number comparison cannot see. A user who reads the help, decides 0.4 is
        the pace they want, and types it must get pacing -- not be told they meant nothing."""
        args = self._parse(tmp_path, mocker, "--delay", "0.4")
        assert args.delay == 0.4
        assert core._delay_was_chosen(args) is True

    def test_any_other_typed_value_counts_too(self, tmp_path, mocker):
        for typed, expected in (("1.5", 1.5), ("0", 0.0)):
            args = self._parse(tmp_path, mocker, "--delay", typed)
            assert args.delay == expected
            assert core._delay_was_chosen(args) is True


class TestPaceGate:
    """The primitive itself, now shared by _parallel_map and run_download's inline pool.

    Driven with a FROZEN clock and a RECORDING sleep (both injected) so the assertions land
    on the slots the gate BOOKS, not on real wall-clock gaps. The old versions spawned real
    threads and compared `time.monotonic()` deltas, which measured OS scheduling jitter and
    flaked under concurrent load; the contract they meant to check -- one global slot per
    `delay`, handed out under a lock so no two callers collide -- is exact and testable
    without any real time passing.
    """

    def test_slots_are_global_across_threads_not_per_thread(self):
        """Six real threads share one gate; the clock never advances and sleeps are recorded
        instead of waited. Each thread must be handed its OWN cumulative slot -- the lock is
        what stops two of them reading the same `next_start` and booking a duplicate. With a
        frozen clock the k-th slot's wait is k*delay, and the first (wait 0) does not sleep,
        so the five recorded waits must be exactly one each of {delay .. 5*delay}. A missing
        lock shows up as a duplicated wait, never the full distinct set. A per-thread gate
        (sleep `delay` in every worker) would record five identical `delay`s instead."""
        waits = []
        guard = threading.Lock()
        pace = core._pace_gate(
            0.05,
            clock=lambda: 0.0,                        # frozen: no real time eats a wait
            sleep=lambda w: (guard.acquire(), waits.append(w), guard.release()))

        threads = [threading.Thread(target=pace) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(waits) == pytest.approx([0.05 * i for i in range(1, 6)]), (
            "threads booked overlapping slots -- the gate's lock is not holding globally")

    def test_no_delay_costs_nothing(self):
        """--delay 0 must stay a true no-op: no lock, no clock read, no sleep, so a caller can
        install the gate unconditionally instead of branching around it. Asserted BY
        CONSTRUCTION -- the injected clock and sleep are never touched across 1000 calls --
        rather than by racing 1000 iterations against a wall-clock bound a loaded machine
        could blow."""
        touched = []
        pace = core._pace_gate(
            0, clock=lambda: touched.append("clock"),
            sleep=lambda w: touched.append("sleep"))
        for _ in range(1000):
            assert pace() is None
        assert touched == [], "a zero delay still read the clock or slept -- not a real no-op"
