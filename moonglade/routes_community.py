"""moonglade/routes_community.py -- the community routes: contests (the list, qualify, a
contest's artworks and winners, mine, enter, sync, check), artwork views, Your art and the My Art
items and publish, lineage, siblings, series and a batch's detail, and the inbox (pushed, the
list, the count, events, read, read all), comments (read, reply, delete) and the gift box (list,
claim), with their helpers.

Split out of gallery.create_app (split phase 4, 2026-11-20), verbatim: create_app calls
register(app, ctx) once, where the first block was, after the account routes. Names the block
reads from create_app's setup, the front door (the CSRF check, the PixAI session, the host-path
redactor) and the background block (the job log, the artworks kick) come in through ctx (the
bound-from-ctx lines below), so every closure on both sides holds the one same object. gallery's
own names are imported inside the function that reads them, at call time, so a test's patch of
moonglade.gallery still reaches the route.
"""
import secrets
import threading
import time

from flask import jsonify, request, session

from moonglade import contest_sync as _contest_sync
from moonglade import contest_wins
from moonglade import contests as _contests
from moonglade import jobs as _jobs
from moonglade import living as _living
from moonglade import pixai_client as _pixai_client
from moonglade import series as _series
from moonglade import telemetry as _telemetry


def register(app, ctx):
    from moonglade.web_tiers import LOGIN, tier
    # -- bound from ctx (split_move) --
    _artworks_kick = ctx._artworks_kick
    _check_csrf = ctx._check_csrf
    _gen_session = ctx._gen_session
    _log_job = ctx._log_job
    _redact_host_paths = ctx._redact_host_paths
    db_path = ctx.db_path
    out_dir = ctx.out_dir
    # -- end --

    @app.route("/api/contests")
    @tier(LOGIN)
    def api_contests():
        """The live PixAI contest board (community + official). Read-only PUBLIC data (not
        owner-private, no spend), so NOT localhost-gated -- the owner browsing over LAN still
        sees it. ?all=1 includes ended contests; default is only the currently-running ones.

        MEMOIZED for CONTESTS_TTL. Four surfaces mount this on open -- Contests, My Art,
        Publish and the mobile screen -- and each was pulling the live board over the
        network on every mount, which is the stall the owner reported on a modest machine
        (2026-09-03). A contest board changes over days; ninety seconds of staleness costs
        nothing and turns four page-open round trips into one. The two variants cache
        separately because they are different answers to different questions.

        Soft-fail semantics are unchanged, and a failure is NOT cached: an offline blip
        must not pin an empty board for the next minute and a half."""
        show_all = request.args.get("all") == "1"
        # The board's Refresh: one full walk that rewrites the settled-row cache.
        refresh = request.args.get("refresh") == "1"
        try:
            core, session = _gen_session()
            if refresh:
                rows, stale_at = _contest_sync.contest_board(core, session, force=True, full=True), None
            else:
                # A cold open answers from the saved list at once and refreshes behind it.
                rows, stale_at = _contest_sync.contest_board_swr(core, session)
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200], "contests": []}), 200
        # Both variants come off the ONE snapshot -- `active` is the server's own
        # runtimeStatus flag, the same thing list_contests(active_only=True) filters on.
        contests = rows if show_all else [c for c in rows if c.get("active")]
        # Whether the board was longer than the ceiling the reader walks to (the screens say
        # so under the list; until now only a log line did).
        bm = _contest_sync.contest_board_meta()
        board = {"truncated": bool(bm.get("truncated"))}
        if board["truncated"]:
            board["limit"] = int(bm.get("limit") or 0)
            board["total_count"] = int(bm.get("total_count") or 0)
        out = {"contests": contests,
               "official": sum(1 for c in contests if c["type"] == "official"),
               "community": sum(1 for c in contests if c["type"] != "official"),
               "board": board}
        if stale_at is not None:
            out["stale"] = True               # the saved list; a walk is refreshing it
            out["saved_at"] = stale_at
        return jsonify(out)

    @app.route("/api/contests/qualify")
    @tier(LOGIN)
    def api_contests_qualify():
        """For the contest cards' "you've used ..." line (2026-11-18): per running contest with
        rules, each rule's {kind, need, used, unknown} -- how many of the models/LoRAs it
        requires are ones this library's pictures were made with (moonglade/contest_qualify.py
        says exactly what "used" can and cannot mean). Read-only; the model-version reads it
        needs are capped, paced and kept a day. Soft-fails to {} like /api/contests."""
        from moonglade import contest_qualify as _cq
        try:
            core, session = _gen_session()
            rows = [c for c in _contest_sync.contest_board(core, session) if c.get("active")]
            return jsonify({"contests": _cq.board_qualify(core, session, rows, db_path)})
        except Exception as e:                           # noqa: BLE001
            return jsonify({"error": _redact_host_paths(str(e))[:200], "contests": {}}), 200

    @app.route("/api/contest/<slug>/artworks")
    @tier(LOGIN)
    def api_contest_artworks(slug):
        """One page of a contest's public entries -> the detail view's preview grid.

        `?page=N` (default 1). Thumbnails are built from each row's mediaId with the same
        `/v1/media/{id}/thumbnail` pattern list_contests already uses for cover art -- the
        entries are other people's artworks, so there is nothing local to serve. Only what
        the preview renders comes back (id, author name, thumb): the raw upstream rows
        carry more, and none of it is needed to draw eight squares.

        Soft-error-as-200 with an empty list, matching /api/contests: a contest board
        hiccup must not turn a detail view into an error page."""
        try:
            page = max(1, int(request.args.get("page") or 1))
        except (TypeError, ValueError):
            page = 1
        try:
            core, session = _gen_session()
            env = _contests.contest_artworks(session, slug, page=page)
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200],
                            "entries": [], "total_count": 0, "total_page": 0}), 200
        entries = []
        for r in env.get("data") or []:
            mid = str(r.get("mediaId") or "")
            entries.append({
                "id": str(r.get("id") or ""),
                "author_name": str(r.get("authorName") or ""),
                "thumb": ("https://api.pixai.art/v1/media/%s/thumbnail" % mid) if mid else "",
            })
        return jsonify({"entries": entries,
                        "total_count": int(env.get("totalCount") or 0),
                        "total_page": int(env.get("totalPage") or 0)})

    @app.route("/api/contest/<slug>/winners")
    @tier(LOGIN)
    def api_contest_winners(slug):
        """The winners of one contest -> the detail view's winners strip.

        Empty until the contest's result date: PixAI answers a running contest with an
        empty array rather than an error, which is exactly the "not decided yet" the strip
        needs to stay hidden on. The caller is expected to ask only once result_at has
        passed; asking early is simply empty, never wrong.

        `mine` marks the owner's own row (the design's YOU chip) by comparing authorId to
        the authenticated account -- the id never reaches the client. `rank` is the row's
        real PRIZE TIER (its `entry.rank`: 1, 2 or 3, shared by every winner in that tier)
        and `prize_amount` what that tier paid (PROBE 2026-09-29). It used to be the row's
        position in the list and 0, which on a 65-winner podium read as places 1 to 65 with
        no prize. A row that carries no placement gets rank 0 (unknown), never a guess.
        Soft-error-as-200, like every other read on this surface."""
        try:
            core, session = _gen_session()
            rows = _contests.contest_winners(session, slug)
            uid = str(_pixai_client._client_of(session).user_id or "")
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200], "winners": []}), 200
        winners = []
        for w in rows or []:
            ent = contest_wins.entry_of(w)
            rank = ent["rank"] if ent and ent["rank"] else 0
            prize = ent["prize"] if ent else 0
            mid = str(w.get("mediaId") or "")
            aid = str(w.get("authorId") or "")
            winners.append({
                "id": str(w.get("id") or ""),
                "rank": rank,
                "author_name": str(w.get("authorName") or ""),
                "thumb": ("https://api.pixai.art/v1/media/%s/thumbnail" % mid) if mid else "",
                "prize_amount": prize,
                "mine": bool(uid and aid == uid),
            })
        return jsonify({"winners": winners})

    @app.route("/api/contest/mine")
    @tier(LOGIN)
    def api_contest_mine():
        """This account's own contest entries, grouped by contest -> the My entries tab.

        TELEMETRY-DERIVED AND INSTANT. The entry record already lives locally (the same
        dedupe sets every entry path writes), so this route performs exactly ONE upstream
        call -- a single page of the contest board, purely to put titles and dates on the
        rows. It deliberately does not re-poll PixAI per contest: that is the detection
        sweep's job, on its own schedule, and a tab that fired N network calls on open
        would be unusable with twenty contests in flight.

        A failed board read is soft: the rows still come back, keyed by contest id with
        empty titles, because knowing you have entries somewhere beats an error page.

        Thumbs come from the local catalog by artwork_id (see artwork_media_ids); an
        artwork the library does not hold gets no thumb rather than a broken image.

        `won` is contest FACT and belongs on this surface -- the DC's results rows show
        it -- and since L3 it means VERIFIED: PixAI's own winners list carried the entry
        with an integer tier. `wins` lists them (tier, prize, how it was verified, the
        receipt link), `check` says where the daily check stands for the contest, and
        `unverified_legacy` marks a contest an older sweep once believed won that no check
        has confirmed yet. No metric name and no ladder language appears in this payload."""
        from moonglade.catalog_verbs import artwork_media_ids
        d = _telemetry.load_telemetry(out_dir)
        sets = d.get("sets") if isinstance(d.get("sets"), dict) else {}
        raw_keys = sets.get("contest_entry_keys")
        raw_legacy = sets.get("contest_win_keys")
        legacy_ids = {str(w) for w in raw_legacy} if isinstance(raw_legacy, list) else set()
        _e, _l, verified, checks = _contest_sync._cw_inputs(d)
        now_t = time.time()
        by_contest, order = {}, []
        for k in (raw_keys if isinstance(raw_keys, list) else []):
            cid, _, aid = str(k).partition(":")
            if not cid or not aid:
                continue
            if cid not in by_contest:
                by_contest[cid] = []
                order.append(cid)
            if aid not in by_contest[cid]:
                by_contest[cid].append(aid)
        board = {}
        try:
            core, session = _gen_session()
            # Titles only: the saved list is good enough, so this never waits on a walk.
            for c in _contest_sync.contest_board_swr(core, session)[0] or []:
                if isinstance(c, dict) and c.get("id"):
                    board[str(c["id"])] = c
        except Exception:                       # soft: key-only rows beat an error page
            board = {}
        thumbs = {}
        try:
            thumbs = artwork_media_ids(db_path, [a for cid in order for a in by_contest[cid]])
        except Exception:
            thumbs = {}
        rows = []
        shown_by_contest = {}
        for cid in order:
            c = board.get(cid) or {}
            aids = by_contest[cid]
            # No dedupe here, and the reason is worth keeping: media_id is the catalog's
            # PRIMARY KEY, so artwork_id -> media_id is injective and two keys can NEVER
            # resolve to one piece. The "defensive dedupe" that used to sit here could not
            # fire on any real store. The legacy double-key it was meant to cover is
            # healed where the truth actually is -- in the sweep, which sees both ids on
            # the upstream row and can discard the stale one.
            shown = list(aids)
            shown_by_contest[cid] = shown
            rows.append({
                "contest_id": cid,
                "slug": str(c.get("slug") or ""),
                "title": str(c.get("title") or ""),
                "type": str(c.get("type") or ""),
                "end_at": str(c.get("end_at") or ""),
                "result_at": str(c.get("result_at") or ""),
                "active": bool(c.get("active")),
                "url": str(c.get("url") or ""),
                "entry_artwork_ids": shown,
                "entries": [{"artwork_id": a, "media_id": thumbs.get(a, ""),
                             "thumb": ("/thumbs/%s.jpg" % thumbs[a]) if thumbs.get(a) else ""}
                            for a in shown],
                "won": bool(contest_wins.wins_for(verified, cid)),
                "wins": contest_wins.wins_for(verified, cid),
                "check": _contest_sync._cw_check_view(checks.get(cid), now_t),
                "unverified_legacy": bool(cid in legacy_ids
                                          and not contest_wins.wins_for(verified, cid)),
            })
        return jsonify({"contests": rows,
                        "total_entries": sum(len(shown_by_contest[cid]) for cid in order),
                        "sync_running": bool(_contest_sync._contest_sync_lock.locked()),
                        "last_sync_at": _contest_sync._contest_sync_last_ok.get("at", 0.0)})

    @app.route("/api/contest/enter", methods=["POST"])
    @tier(LOGIN)
    def api_contest_enter():
        """Enter one already-published artwork into a PixAI contest.

        ALWAYS-CONFIRM, and deliberately stronger than the house preview-first default:
        every submit gets an explicit confirm step, no exceptions (owner ruling F4,
        2026-08-31 contest-surface workshop). PixAI exposes no un-enter route, so there is
        no such thing as an entry worth firing without the owner saying so twice. Without
        `confirm: true` this route performs NO network call and returns what it WOULD do.

        `spends_credits` is None, NOT False. The contest contract declares an
        INSUFFICIENT_CREDITS error for this operation and no entry has ever been submitted
        to measure whether one is charged, so the honest answer is "unknown". False would
        be a promise the code cannot keep, on a screen a user reads before an irreversible
        action.

        THE CONTEST ID IS RESOLVED SERVER-SIDE, from the live board by slug -- a `contest_id`
        in the body is accepted and ignored. The id is what the ladder dedupes on, and the
        set it lands in is grow-only: a client that sent a wrong, stale or invented one would
        write a key nothing can ever correct. The board read is also what makes an unknown
        slug a 400 here rather than an upstream refusal later.

        LOGIN tier, not LOCALHOST: this is the owner managing their OWN account, the same
        class as publishing and claiming. CSRF: explicit-token class, matching
        /api/myart/publish -- a real account mutation triggered by one web click.
        READ_ONLY in config.json refuses the confirmed form regardless, inside core."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        slug = str(body.get("slug") or "").strip()
        artwork_id = str(body.get("artwork_id") or "").strip()
        if not (slug and artwork_id):
            return jsonify({"error": "slug and artwork_id are both required"}), 400
        if not body.get("confirm"):
            return jsonify({"preview": True, "slug": slug, "artwork_id": artwork_id,
                            "spends_credits": None, "irreversible": True})
        try:
            core, session = _gen_session()
        except Exception as e:
            return jsonify({"error": "PixAI session unavailable: %s"
                                     % _redact_host_paths(str(e))[:160]}), 502
        try:
            board = _contest_sync.contest_board(core, session)
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 502
        contest_id = next((str(c.get("id") or "") for c in board or []
                           if isinstance(c, dict) and str(c.get("slug") or "") == slug), "")
        if not contest_id:
            return jsonify({"error": "unknown contest"}), 400
        try:
            resp = _contests.contest_enter(session, slug, artwork_id)
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 502
        # A 2xx that says success:false is a refusal wearing a success code. Default True
        # for any other shape -- the response body is documented as {success} but only the
        # error paths were ever seen live, so absence must not read as failure.
        if isinstance(resp, dict) and not resp.get("success", True):
            return jsonify({"error": "the contest refused the entry"}), 502
        # OUTSIDE the try, silent-soft: the entry is already live and irreversible by the
        # time we get here, so a telemetry hiccup must never be reported as a failed entry.
        # Same key shape the detection sweep writes -- one dedupe set, so entering the same
        # artwork twice still counts once.
        try:
            _telemetry.telem_set_add("contest_entry_keys", "%s:%s" % (contest_id, artwork_id),
                          out_dir=out_dir)
        except Exception:
            pass
        return jsonify({"entered": True, "slug": slug, "artwork_id": artwork_id})

    @app.route("/api/contest/sync", methods=["POST"])
    @tier(LOGIN)
    def api_contest_sync():
        """Re-read this account's contest entries and wins from PixAI (see
        _contest_detection_sync). Catches entries made on pixai.art and wins decided while
        the app was closed -- neither of which produces any local event to hook.

        CSRF REQUIRED, like every sibling POST on this surface. It reaches PixAI with the
        owner's credentials on a cross-site-triggerable POST, which is what the token is
        for. (An earlier version of this docstring said the opposite; it described a route
        that no longer existed by the time anyone read it.)

        Single-flight via a module lock, and the answer is a STATE rather than a refusal --
        there is nothing for a caller to retry when a sweep is already running:
          {started: true}                     -- one is now running on its own thread
          {started: false, skipped: "recent"} -- one ran recently; nothing to do
          {started: false, busy: true}        -- one is already in flight
        Completion is NOT reported here: the sweep outlives this request. The client
        watches `sync_running` on /api/contest/mine instead.

        ONE count comes back, and only one. contest_wins is deliberately absent -- it is a
        hidden-only metric, and even a zero here would tell a reader that a win is something
        this app counts. What the sets contain never leaves the store either.

        CSRF, since 2026-09-03: every sibling POST on this surface carries the explicit
        token, and this one did not. It reaches PixAI with the owner's credentials on a
        cross-site-triggerable POST, which is exactly the shape the token exists for --
        cheap to add, and it makes the surface uniform instead of one-route-special.

        RETURNS IMMEDIATELY. The sweep runs on its own thread; the answer says whether one
        STARTED (or was skipped as recent, or was already busy), and the client watches
        /api/contest/mine's `sync_running` for completion."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        m = _telemetry.telemetry_metrics(out_dir)
        entries = int(m.get("contest_entries", 0) or 0)
        # RECENT: nothing to do, and nothing to wait for.
        if (time.time() - _contest_sync._contest_sync_last_ok.get("at", 0.0)) < _contest_sync.CONTEST_SYNC_RECENT_S:
            return jsonify({"started": False, "skipped": "recent",
                            "contest_entries": entries})
        if not _contest_sync._contest_sync_lock.acquire(False):
            return jsonify({"started": False, "busy": True, "contest_entries": entries})

        def _run():
            try:
                _contest_sync._contest_detection_sync(out_dir)
            finally:
                _contest_sync._contest_sync_lock.release()

        # OFF-THREAD, and this is the whole point: the sweep is paced (a third of a second
        # between contests, plus a read each) and can run 30-90 seconds against a real
        # board. It was doing that INSIDE the request, so opening the Contests overlay held
        # a worker and the browser's connection for the duration -- on a slow board the
        # overlay simply hung. The client watches /api/contest/mine's sync_running flag
        # instead, which costs a local telemetry read.
        try:
            threading.Thread(target=_run, daemon=True).start()
        except Exception as e:                   # noqa: BLE001
            # The lock is acquired HERE and released by the thread, so a thread that never
            # starts would leave contest sync permanently "busy" for the life of the
            # process -- every later open answering busy:true forever. Release it here and
            # say what happened. (Found by its own test, which stubs Thread.start.)
            _contest_sync._contest_sync_lock.release()
            return jsonify({"started": False,
                            "error": _redact_host_paths(str(e))[:200],
                            "contest_entries": entries}), 200
        return jsonify({"started": True, "contest_entries": entries})

    @app.route("/api/contest/check", methods=["POST"])
    @tier(LOGIN)
    def api_contest_check():
        """The Check button (E4, L3): "it won but isn't shown". The owner pastes the link to an
        entry (or to its contest) and presses Check; the app reads that contest's winners
        ONCE and records a win ONLY when the entry's artwork id is in the list with an integer
        tier rank and the author is this account. The link is kept as the receipt. Nothing else
        counts: no self-reported wins, no name-alike, no empty list read as "lost" (it reads as
        "not published yet").

        Body: {csrf, url, contest_id?, slug?}. `contest_id` is a contest from the account's
        own entries (the picker); `slug` a contest typed in; either may be left off when the
        link names the contest or the app already recorded the linked artwork's contest. The
        answer is always 200 with {verified, state, message, wins[]} -- a miss is an answer,
        not an error; `state` is one of verified, undecided, not_found, no_placement,
        not_yours, not_pixai, no_link, no_contest, failed, cooldown.

        LOGIN tier, CSRF required (it reaches PixAI with the owner's credentials on a
        cross-site-triggerable POST, like /api/contest/sync). It is a GET of PixAI's winners
        list and nothing else: there is no write to PixAI on this road, so READ_ONLY has
        nothing to refuse. Only pixai.art links are accepted, the slug is shape-checked
        before it becomes a path, and a contest is not re-read within a few seconds."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        status, payload = _contest_sync.contest_win_check(out_dir, body)
        return jsonify(payload), status

    @app.route("/api/artwork-views")
    @tier(LOGIN)
    def api_artwork_views():
        """Live view count for one published artwork -> the detail page's Views metric.
        Login required; uses the owner's key. ?id=<artwork_id>."""
        aid = (request.args.get("id") or "").strip()
        if not aid:
            return jsonify({"views": None}), 400
        try:
            core, session = _gen_session()
            return jsonify({"views": core.artwork_views(session, aid)})
        except Exception as e:
            return jsonify({"views": None, "error": _redact_host_paths(str(e))[:120]}), 200

    @app.route("/api/your-art")
    @tier(LOGIN)
    def api_your_art():
        """'Your Art' panel: the owner's top published works plus the library's real
        lifetime totals. Pure CATALOG read -- no network, no spend, works over LAN.

        THIS ROUTE USED TO MAKE TWELVE LIVE GRAPHQL CALLS ON EVERY OPEN, six at a time,
        to fetch view counts that no column existed for -- the lag saga, and the reason the
        panel could only ever report a "top 12" subtotal. PROBE_2026-09-06 established that
        the ad-hoc bulk `artworks(authorId, first:N)` query accepts `views`, so
        --sync-artworks now sweeps them into the catalog in a handful of paced calls and
        this route reads a column like every other number on the panel.

        That is not merely faster, it is more HONEST in two ways. The totals are now
        lifetime sums over the whole published library rather than a dozen rows. And the
        same probe measured that reading a view count COSTS a view -- so the old design
        inflated the owner's own twelve most-looked-at works by twelve views every single
        time he opened the panel to look at them. A sweep he runs deliberately still costs
        one view per work, but bounded to that sweep instead of to his curiosity.

        `views_synced` now means "the catalog has been swept", not "the live calls
        happened to succeed"; `?order=views` ranks by views instead of likes.

        No `_is_authorized_request()` conjunct here: this whole route is now covered by the
        global front-door hook (see _enforce_front_door()'s docstring), so reaching this line
        already guarantees it -- an explicit re-check here would be dead-always-true, the same
        class of redundant check removed from the 43 individually-gated routes."""
        order = "views" if (request.args.get("order") or "") == "views" else "likes"
        try:
            limit = max(1, min(int(request.args.get("limit") or 12), 200))
        except (TypeError, ValueError):
            limit = 12
        totals = _living.published_totals(db_path)
        top = _living.top_published_rows(db_path, limit, order=order)
        views_synced = totals.get("views_rows", 0) > 0
        for r in top:
            # '' and 0 are different answers (see myart_items): a never-swept row must not
            # render as a real zero, so it goes to the client as null.
            swept = (r.pop("views_raw", "") or "") != ""
            r["views"] = r["views"] if swept else None
            for k in ("views_prev", "views_at", "views_prev_at"):
                r.pop(k, None)
        return jsonify({"items": top, "totals": totals, "views_synced": views_synced,
                        "views_at": totals.get("views_at", ""),
                        # The blow-up note's payload. A LIST, capped, never a feed --
                        # see published_spikes() and views_spike().
                        "spikes": _living.published_spikes(db_path)})

    @app.route("/api/myart/items")
    @tier(LOGIN)
    def api_myart_items():
        """Card-ready rows for the My Art tabbed gallery (Frontend Gallery.dc.html's
        ovMyArt, rebuilt 2026-08-06): every catalog row that exists as a PixAI ARTWORK
        (artwork_id set by --sync-artworks), public AND private -- the design's
        Visibility filter distinguishes them ('everything you've made, published or
        held back'). Pure catalog read, no network: title/likes/comments/tags/nsfw
        arrive via --sync-artworks; thumbs are the local /thumbs/<mid>.jpg the grid
        already serves. The Artworks/Animations tab split is the is_video flag.

        `coverage` rides along (#42) so the overlay's empty state can say WHY it is
        empty: an unsynced library and a genuinely unpublished one produce the same
        zero rows here, and only the catalog-wide counts separate them. See
        myart_coverage()."""
        # First read on a library with no history yet: take today's reading now, so the window
        # has a baseline from the first open (a same-day rewrite is harmless).
        from moonglade.catalog_verbs import (myart_coverage, myart_items, myart_window,
                                             record_artwork_snapshots)
        win, window = myart_window(db_path)
        if not window["seen"]:
            record_artwork_snapshots(db_path)
            win, window = myart_window(db_path)
        items = []
        for r in myart_items(db_path):
            mid, title, preview = r["media_id"], r["title"], r["prompt_preview"]
            created, tags = r["created_at"], r["art_tags"]
            items.append({
                "media_id": mid, "artwork_id": r["artwork_id"],
                "title": (title or "").strip() or (preview or "").strip()[:60] or mid,
                "thumb": "/thumbs/%s.jpg" % mid,
                "is_video": r["is_video"] == "1", "is_nsfw": r["is_nsfw"] == "1",
                "date": (created or "")[:10],
                "created_at": created or "",
                "tags": [t.strip() for t in (tags or "").split(",") if t.strip()][:4],
                "public": r["is_published"] == "1",
                "sensitive": r["is_sensitive"] == "1",
                "likes": r["likes"], "comments": r["comments"],
                # null (never swept) vs 0 (swept, nobody looked) -- the card draws a
                # dash for the first and a real 0 for the second.
                "views": r["views"] if (r["views_raw"] or "") != "" else None,
                "views_30": win.get(r["artwork_id"], {}).get("views"),
                "likes_30": win.get(r["artwork_id"], {}).get("likes", 0),
            })
        # The card actions POST to /api/myart/publish, which is in the explicit-token
        # CSRF class; MG_BOOT doesn't carry the token, so it rides along here rather
        # than making the overlay fetch the whole Control Panel summary for one field.
        return jsonify({"items": items, "csrf": session.get("csrf", ""),
                        "coverage": myart_coverage(db_path),
                        # the All time / 30 days switch: `window` says whether the 30 is a full
                        # 30 days or only "since <date>" (history starts the day this shipped)
                        "window": window})

    @app.route("/api/myart/publish", methods=["POST"])
    @tier(LOGIN)
    def api_myart_publish():
        """Publish / unpublish / re-tag / delete one of the owner's artworks -- the My Art
        card actions and the Lightbox/Details Publish button.

        PREVIEW-FIRST, like every other account-mutating path in this app: without
        `confirm: true` the route performs NO network call and returns exactly what it
        WOULD do (action, target, resolved tag ids, and anything it could not resolve).
        The UI shows that preview and only then sends the confirmed call. READ_ONLY in
        config.json refuses the confirmed form regardless, inside the core functions.

        Actions:
          publish   -- createArtworkFromTaskV2 for a media_id that has no artwork yet
                       (needs its task_id + the image's index in that task)
          visibility-- upsertArtwork flipping public/private on an existing artwork
          tags      -- upsertArtwork replacing the tack list
          delete    -- deleteArtwork (irreversible on PixAI; local files untouched)

        CSRF: explicit-token class, matching /api/duplicates/resolve and the user-admin
        routes -- a real account mutation triggered by one web click."""
        from moonglade.catalog_verbs import artwork_row, publish_state
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        action = str(body.get("action") or "").strip()
        mid = str(body.get("media_id") or "").strip()
        if action not in ("publish", "visibility", "tags", "delete"):
            return jsonify({"error": "unknown action"}), 400
        row = artwork_row(db_path, mid)
        if not row:
            return jsonify({"error": "unknown media id"}), 400
        confirm = bool(body.get("confirm"))
        tags = body.get("tags") if isinstance(body.get("tags"), list) else None
        private = body.get("private")
        title = body.get("title")

        if action == "publish" and row["artwork_id"]:
            return jsonify({"error": "already published -- use visibility/tags instead"}), 400
        if action != "publish" and not row["artwork_id"]:
            return jsonify({"error": "not published yet -- publish it first"}), 400
        if action == "publish" and not row["task_id"]:
            return jsonify({"error": "no task id for that image -- it can't be published from a task"}), 400

        try:
            core, session = _gen_session()
        except Exception as e:
            return jsonify({"error": "PixAI session unavailable: %s" % e}), 502

        tack_ids, unmatched = [], []
        if tags is not None:
            tack_ids, unmatched = core.resolve_tack_ids(session, tags)   # read-only

        # Which image of its task this media_id is. Resolved SERVER-side from the task's
        # own ordered outputs, never taken from the client: publishing index 2 when the
        # user picked index 0 puts the wrong picture on their public profile, and that is
        # not a recoverable mistake. Read-only lookup, so it runs during preview too --
        # which is what lets the preview refuse an unresolvable image before confirming.
        media_index = None
        if action == "publish":
            media_index = core.task_media_index(session, row["task_id"], mid)
            if media_index is None:
                return jsonify({"error": "couldn't work out which image of task %s this is "
                                         "-- refusing to publish rather than risk the wrong "
                                         "one" % row["task_id"]}), 400

        if not confirm:
            return jsonify({"preview": True, "action": action, "media_id": mid,
                            "artwork_id": row["artwork_id"], "task_id": row["task_id"],
                            "title": title if title is not None else row["title"],
                            "private": private, "tack_ids": tack_ids,
                            "unmatched_tags": unmatched,
                            "media_index": media_index,
                            "spends_credits": False,
                            "irreversible": action == "delete"})
        try:
            if action == "publish":
                # Same null-preserving expression the preview above uses (line ~15873) --
                # an intentionally CLEARED title (title == "") must publish empty, not
                # silently fall back to the catalog's old title. `or` treats "" as falsy,
                # which is exactly the bug: the confirm sheet showed "(untitled)" but the
                # mutation went out with the stale title. Only an absent field (title is
                # None, the client never sent it) falls back. Found by ultrareview 2026-08-06.
                art = core.publish_artwork_from_task(
                    session, row["task_id"],
                    media_index=media_index,
                    title=(title if title is not None else row["title"]) or "",
                    description=body.get("description") or "",
                    tack_ids=tack_ids, private=bool(private),
                    hide_prompts=bool(body.get("hide_prompts")),
                    challenge=body.get("challenge") or None)
                result = {"artwork_id": art.get("id"), "published": True}
            elif action == "delete":
                core.delete_artwork(session, row["artwork_id"])
                result = {"deleted": True}
            else:
                art = core.update_artwork(
                    session, row["artwork_id"],
                    title=title,
                    tack_ids=(tack_ids if tags is not None else None),
                    private=(None if private is None else bool(private)))
                result = {"artwork_id": art.get("id") or row["artwork_id"], "updated": True}
        except Exception as e:
            return jsonify({"error": str(e)}), 502

        # Mirror the change into the catalog so the grid reflects it without a full sync.
        if action == "delete":
            publish_state(db_path, mid, artwork_id="", published=False)
        else:
            changed = {}
            if action == "publish":
                changed["artwork_id"] = result.get("artwork_id") or ""
                changed["published"] = not private
                # PUBLISH-AND-ENTER. Attaching `challenge` to the publish mutation does
                # NOT enter a contest -- found live 2026-09-01 (owner: "publish AND enter
                # from the publish NAV did not work; I published and then did the entry
                # successfully"). extra.challenge is artwork METADATA, the back-link
                # listArtworks returns on node.extra; the entry itself is a separate REST
                # call (POST /v2/contest/{slug}/artwork), which is exactly what the
                # working direct-entry path does. This publish path never made it, so the
                # contest row's "entering at publish is free" was a promise about
                # something that never happened.
                #
                # So make it happen: the artwork exists now and has an id, which is the
                # one thing the entry call needs. The client sends the contest ID (the
                # select's own value) and contest_enter needs the SLUG, so the board is
                # read to translate -- and that read doubles as validation, since an id
                # that is not on the board cannot be entered anyway.
                #
                # HONEST PARTIAL SUCCESS: the publish already happened and is
                # irreversible, so an entry failure can never turn this into a 502. It
                # comes back as {published: true, entry_error: ...} and the client says
                # both halves. Single attempt -- contest_enter is single-shot by
                # construction and READ_ONLY-guarded; a retry here would risk a second
                # entry for one click.
                challenge = str(body.get("challenge") or "")
                new_art_id = str(result.get("artwork_id") or "")
                if challenge and new_art_id:
                    try:
                        slug = next((str(c.get("slug") or "")
                                     for c in (_contest_sync.contest_board(core, session) or [])
                                     if isinstance(c, dict)
                                     and str(c.get("id") or "") == challenge), "")
                        if not slug:
                            result["entry_error"] = ("couldn't find that contest on the "
                                                     "board — the artwork was published, "
                                                     "but not entered")
                        else:
                            resp = _contests.contest_enter(session, slug, new_art_id)
                            if isinstance(resp, dict) and not resp.get("success", True):
                                result["entry_error"] = "the contest refused the entry"
                            else:
                                result["entered"] = True
                                # RECORD IT HERE. This path answered entered:true and wrote
                                # nothing, leaning on the sweep below -- which silently
                                # no-ops when the single-flight lock is held (a sweep from
                                # the overlay, or the previous publish's own kick). The
                                # entry then existed on PixAI and nowhere locally until
                                # some later sweep happened to catch it. The sweep is
                                # reconciliation; the path that KNOWS an entry just
                                # succeeded is the one that should say so. Same key shape
                                # every other writer uses -- artwork id, so the set dedupes
                                # against the sweep's own row rather than double-counting.
                                try:
                                    _telemetry.telem_set_add("contest_entry_keys",
                                                  "%s:%s" % (challenge, new_art_id),
                                                  out_dir=out_dir)
                                except Exception:
                                    pass
                    except Exception as e:                    # noqa: BLE001
                        result["entry_error"] = _redact_host_paths(str(e))[:200]
                elif challenge:
                    result["entry_error"] = ("the publish returned no artwork id, so the "
                                             "contest entry could not be made")
                # Then the detection sweep, which reads the truth back from PixAI: the
                # ladder counts what PixAI says happened, not what this route believes.
                # Off-thread and outside the try above, so nothing it does can delay this
                # response or turn an irreversible publish into a failure.
                if challenge:
                    try:
                        threading.Thread(target=_contest_sync._contest_sync_kick,
                                         args=(out_dir,), kwargs={"force": True},
                                         daemon=True).start()
                    except Exception:
                        pass
            if private is not None:
                changed["published"] = not private
            if tags is not None:
                changed["art_tags"] = ", ".join(
                    str(t).lstrip("#").strip() for t in tags)
                # Lamplighter (curation_streak) + The Long Vigil: tagging is curation.
                # Keyed day-lists, idempotent, silent-soft.
                try:
                    _telemetry.telem_mark_day(out_dir=out_dir, keys=("curation_days", "active_days"))
                except Exception:
                    pass
            if title is not None:
                changed["title"] = title
            publish_state(db_path, mid, **changed)
        # THE PUBLISH KICK (the living library, owner call 2). publish_state above wrote
        # what THIS route believes into THIS machine's catalog, and nothing else on earth
        # heard about it: publishing is a local UPDATE, and the only way any install learns
        # a publish is by re-reading PixAI's own list. So re-read it, now -- the machine the
        # owner published from is authoritative at once instead of within one sweep, and
        # what lands in the catalog is what PixAI says, not what this route assumed.
        #
        # Forced (past the fifteen-minute guard), off-thread and outside the try above, for
        # the same reasons the contest sweep's own publish kick is: nothing it does may
        # delay this response or turn an irreversible publish into a failure. Fires for
        # unpublish, re-tag and delete too -- each is a change to what listArtworks returns.
        #
        # Scheduled, even though a click reached this route: what the owner pressed was
        # Publish, and he has the publish's own answer in front of him. The sweep is the
        # library keeping itself honest afterwards, so it belongs in the Activity window
        # rather than in a second corner notice about a job he never started (owner's
        # walk, 2026-09-07).
        try:
            _artworks_kick(force=True, scheduled=True)
        except Exception:                                    # noqa: BLE001
            pass
        result["unmatched_tags"] = unmatched
        return jsonify(result)

    def _lineage_card(row):
        """One image reduced to a lineage chip: id, thumb, video flag, and a title hint."""
        mid = row["media_id"]
        return {"media_id": mid, "thumb": "/thumbs/%s.jpg" % mid,
                "is_video": (row["is_video"] == "1"),
                "title": (row["title"] or "").strip() or (row["prompt_preview"] or "").strip()[:48]}

    @app.route("/api/lineage/<media_id>")
    @tier(LOGIN)
    def api_lineage(media_id):
        """The family tree of one image, for Image Details' LINEAGE panel:
          * siblings -- the other outputs of the SAME generation task (share task_id; up to
            4 per batch). Free -- task_id is already indexed.
          * parent   -- the SOURCE image this one was derived from (source_media_id), plus
            the kind of derivation (edit/upscale/video).
          * children -- every image derived FROM this one (rows whose source_media_id == this).
        Pure catalog read, no network. Any dimension can be empty (an original txt2img with
        a batch size of 1 and no derivatives has an empty tree)."""
        from moonglade.catalog_verbs import lineage
        mid = str(media_id or "").strip()
        tree = lineage(db_path, mid)
        if tree is None:
            return jsonify({"error": "unknown media id"}), 404
        parent = tree["parent"]
        return jsonify({
            "media_id": mid,
            "siblings": [_lineage_card(r) for r in tree["siblings"]],
            "parent": (dict(_lineage_card(parent), kind=parent["kind"])
                       if parent else None),
            "children": [dict(_lineage_card(r), kind=r["kind"])
                         for r in tree["children"]],
        })

    @app.route("/api/siblings", methods=["POST"])
    @tier(LOGIN)
    def api_siblings():
        """Page-batched Sibling Strip data for the card placard (issue #30): every
        output of each requested task, in ONE query. The per-card /api/lineage fetch
        cost ~4.3s per 100-card page; this costs ~85ms (probe 2026-08-22).
        Body {"task_ids": [...]} (cap 200; blanks and non-strings dropped). Returns
        {"by_task": {task_id: [{media_id, is_video, thumb, batch_index}, ...]}},
        INCLUDING self (the client lights self by media_id); a task with
        fewer than 2 members is omitted -- a single output has no strip.
        ORDER (issue #33): when EVERY member of a task carries a batch_index --
        PixAI's own permanent output number, captured from getTaskById
        outputs.batch -- members come back in that order (media_id order can swap
        outputs); otherwise media_id order, as before. batch_index is an int, or
        null on a row that has none. Indexes are never renumbered or inferred: a
        deleted sibling leaves a true gap.
        An empty task_id is NEVER queried: every import shares '' and would
        otherwise become one giant pseudo-batch. Pure catalog read, no network."""
        from moonglade.catalog_verbs import sibling_media
        body = request.get_json(silent=True)
        if body is None:
            body = {}
        if not isinstance(body, dict):
            return jsonify({"error": "body must be a JSON object"}), 400
        raw_ids = body.get("task_ids") or []
        if not isinstance(raw_ids, list):
            return jsonify({"error": "task_ids must be a list"}), 400
        ids = []
        seen = set()
        for t in raw_ids:
            if not isinstance(t, str):
                continue
            t = t.strip()
            if not t or t in seen:
                continue
            seen.add(t)
            ids.append(t)
            if len(ids) >= 200:
                break
        by_task = {}
        if ids:
            for r in sibling_media(db_path, ids):
                mid = str(r["media_id"] or "")
                if not mid:
                    continue
                # PixAI's own output number (issue #33): int in the payload, null when
                # the row has none. A non-integer value counts as absent -- the index is
                # only ever the site's own captured fact, never guessed.
                try:
                    bi = int(str(r["batch_index"] or "").strip())
                except ValueError:
                    bi = None
                by_task.setdefault(str(r["task_id"]), []).append({
                    "media_id": mid,
                    "is_video": str(r["is_video"] or "") == "1",
                    "thumb": "/thumbs/{}.jpg?s=32".format(mid),
                    "batch_index": bi,
                })
            by_task = {t: m for t, m in by_task.items() if len(m) >= 2}
            # Order by PixAI's own batch_index only when EVERY member of the task has
            # one (issue #33: media_id order can swap outputs). Any member without an
            # index means the batch order is not fully known -- keep media_id order
            # rather than half-sorting; indexes are never renumbered or inferred.
            for members in by_task.values():
                if all(m["batch_index"] is not None for m in members):
                    members.sort(key=lambda m: m["batch_index"])
        return jsonify({"by_task": by_task})

    @tier(LOGIN)
    @app.route("/api/series", methods=["POST"])
    def api_series():
        """Page-batched dial-in series membership for the card placard and the
        grouped grid (issue #34): which of the requested tasks belong to a
        multi-task series, and where in it. Body {"task_ids": [...]} -- the same
        hygiene as /api/siblings (cap 200; blanks/non-strings dropped; non-list
        400). Returns {"by_task": {tid: {sid, v, of, reroll, label, title}}}.
        ONLY tasks that are in a multi-task series appear: singletons (85% of
        the library) cost nothing here and the client renders nothing for an
        absent tid -- the same "a single output has no strip" shape as
        /api/siblings. Pure catalog read (through the series cache), no
        network."""
        body = request.get_json(silent=True)
        if body is None:
            body = {}
        if not isinstance(body, dict):
            return jsonify({"error": "body must be a JSON object"}), 400
        raw_ids = body.get("task_ids") or []
        if not isinstance(raw_ids, list):
            return jsonify({"error": "task_ids must be a list"}), 400
        ids = []
        seen = set()
        for t in raw_ids:
            if not isinstance(t, str):
                continue
            t = t.strip()
            if not t or t in seen:
                continue
            seen.add(t)
            ids.append(t)
            if len(ids) >= 200:
                break
        out = {}
        if ids:
            by_task_idx, by_sid = _series.series_index(db_path)
            for tid in ids:
                hit = by_task_idx.get(tid)
                if not hit:
                    continue
                sid, v = hit
                s = by_sid.get(sid)
                if not s:
                    continue
                step = s["steps"][v - 1]
                out[tid] = {"sid": sid, "v": v, "of": s["count_tasks"],
                            "reroll": step["reroll"], "label": step["label"],
                            "title": s["title"]}
        return jsonify({"by_task": out})

    @tier(LOGIN)
    @app.route("/api/series/<sid>")
    def api_series_detail(sid):
        """One series' full struct for C's SESSION strip and B's expansion
        (issue #34): title, model, counts, [first_ts, last_ts] span, and the
        ordered steps {task_id, v, reroll, label, first_media_id, n}.
        first_media_id is the member task's first output in batch order when
        the order is known (#33), else lowest media_id. The sid is the FIRST
        member task's id -- deterministic across recomputes, so a bookmarked
        `?series=<sid>` URL keeps resolving (review item 1). 404 for a sid that
        is not a current multi-task series (including a sid whose series
        dissolved after deletions -- honest, like the v-numbers). Pure catalog
        read (through the series cache), no network."""
        _, by_sid = _series.series_index(db_path)
        s = by_sid.get(str(sid or "").strip())
        if not s:
            return jsonify({"error": "unknown series id"}), 404
        return jsonify(s)

    @tier(LOGIN)
    @app.route("/api/batch/<task_id>")
    def api_batch_detail(task_id):
        """One BATCH's struct in the SAME shape /api/series/<sid> returns.

        Owner ruling, 2026-09-07: a batch card opens in the SERIES modal now,
        "separately tagged so you know what you're looking at, batch or series" --
        it no longer takes the library over the way the ?batch= drill-down did. One
        modal wants one payload shape, so this answers the series struct: a batch is
        simply a series of ONE run, so `steps` holds exactly one entry, count_tasks
        is 1, and its label is "one generation" rather than a dial-in delta.

        The rows are the task's SURVIVING catalog rows -- read through query_catalog's
        own `batch` predicate, which is `(batch = ? OR task_id = ?)`, so this and the
        pictures listing the modal fetches next (/api/library?batch=<id>) see
        exactly the same set and their counts cannot disagree. Order is #33's batch
        order (batch_member_order).

        404 for an unknown id AND for a LONE image: one surviving row is not a batch.
        The grouped grid marks a batch stack only at >= 2 survivors (see the folded-BATCH
        arm of /api/library), so nothing can open one -- answering 200 here would
        invent a stack the library never draws. Pure catalog read, no network."""
        from moonglade.curation import batch_member_order, query_catalog
        tid = str(task_id or "").strip()
        rows = []
        if tid:
            rows, _ = query_catalog(db_path, batch=tid, page_size=None)
        if len(rows) < 2:
            return jsonify({"error": "unknown batch id"}), 404
        rows = batch_member_order(rows)
        first = rows[0]
        # The title is derived the way a series' is (_series_title over the same
        # capped prompt text), so the two stack kinds name themselves by one rule;
        # the row's own `title` column is the fallback when the prompt says nothing.
        title = _series._series_title(_series._series_text(first)) or str(first.get("title") or "").strip()
        stamps = sorted(str(r.get("created_at") or "") for r in rows
                        if str(r.get("created_at") or ""))
        return jsonify({
            "sid": tid,                 # the modal keys on this the same way it does a sid
            "task_id": tid,
            "title": title,
            "model": (str(first.get("model_name") or "")
                      or str(first.get("model_id") or "")),
            "count_tasks": 1,
            "count_images": len(rows),
            "span": [stamps[0], stamps[-1]] if stamps else ["", ""],
            "steps": [{
                "task_id": tid,
                "v": 1,
                "reroll": False,
                "label": "one generation",
                "first_media_id": str(first.get("media_id") or ""),
                "n": len(rows),
            }],
        })
    # --- The inbox, comments, gifts and the current event (Sessions R + Y, lane R) -------
    # Over moonglade.inbox (its docstring has the contract and the four write rules). Reads
    # are LOGIN, like every other read of PixAI here. A write is a deliberate press: LOGIN,
    # explicit-token CSRF (_check_csrf), then moonglade.inbox's own function -- READ_ONLY
    # first, one attempt, a read-back that decides the answer. Nothing here writes when the
    # panel opens, a list scrolls or a push arrives. Strangers' words pass through to the
    # browser and are never written to the catalog, a file or a log line.

    def _inbox():
        from moonglade import inbox as moonglade_inbox
        return moonglade_inbox

    def _inbox_fail(e, **extra):
        """A read that failed, as the house's {error} answer (HTTP 200: the body is the
        answer, api.js's one rule). PixAI's own message only -- never the words of a comment."""
        out = {"error": _redact_host_paths(str(e))[:240]}
        out.update(extra)
        return jsonify(out), 200

    def _inbox_read_only():
        from moonglade import backup as core
        return bool(core.READ_ONLY or core._read_only_now())

    def _inbox_local_media(items):
        """Fill each work's local media id (Details opens on it), from the catalog."""
        from moonglade.catalog_verbs import artwork_media_ids
        ids = [i["artwork"]["id"] for i in items if i.get("artwork")]
        found = artwork_media_ids(db_path, ids) if ids else {}
        for i in items:
            if i.get("artwork"):
                i["artwork"]["media_id"] = found.get(i["artwork"]["id"], "")
        return items

    def _inbox_tasks_to_activity(tasks):
        """R2c: TASK is never an inbox row -- Activity tells a job. A recent finished generation
        PixAI names that Activity never saw joins it as an ordinary done row, source "pixai"
        (the website mark) and via "inbox"; a row Activity holds as failed or stalled that PixAI
        says finished gets the "PixAI says: done" note through /api/jobs. A local log line only:
        nothing is sent to PixAI. Fails soft -- the inbox read must never break over it."""
        if not tasks:
            return
        try:
            from moonglade import backup as core
            jobs_by_id, _order, _n = _jobs._reconstruct_jobs(out_dir)
            for add in _inbox().task_activity(tasks, jobs_by_id):
                _log_job(add["job_id"], status="done", type="generate", label=add["label"],
                         source="pixai", via="inbox")
        except Exception:                                        # noqa: BLE001
            pass

    @app.route("/api/inbox/pushed")
    @tier(LOGIN)
    def api_inbox_pushed():
        """What the socket pushed since ?after=<seq>, as full inbox rows (the comment toast
        names who and which work). One read of the newest rows, none when nothing is new;
        nothing is marked read."""
        try:
            ib = _inbox()
            out = ib.pushed_since(ib.pixai_session(), request.args.get("after") or 0)
        except Exception as e:                                   # noqa: BLE001
            return _inbox_fail(e, items=[])
        out["items"] = _inbox_local_media(out["items"])
        return jsonify(out)

    @app.route("/api/inbox")
    @tier(LOGIN)
    def api_inbox():
        """One page of PixAI's inbox, newest first (?before=<cursor> pages older). Opening the
        panel is this one read and nothing else: no mark-read, no count write. Also answers
        read_only (the rows say why nothing gets marked) and the CSRF token its writes carry."""
        session.setdefault("csrf", secrets.token_hex(16))
        ib = _inbox()
        try:
            gsession = ib.pixai_session()
            page = ib.list_notifications(gsession, before=request.args.get("before") or None)
        except Exception as e:                                   # noqa: BLE001
            return _inbox_fail(e, items=[], csrf=session["csrf"],
                               read_only=_inbox_read_only())
        _inbox_tasks_to_activity(page["tasks"])
        return jsonify({"items": _inbox_local_media(page["items"]), "cursor": page["cursor"],
                        "has_more": page["has_more"], "csrf": session["csrf"],
                        "read_only": _inbox_read_only()})

    @app.route("/api/inbox/count")
    @tier(LOGIN)
    def api_inbox_count():
        """The doors' badges: PixAI's unread count (TASK excluded) for the inbox, the pending
        gifts for the gift box, and their total for the phone's Menu. Read on app open, on focus (the client debounces 30 s) and on a socket reconnect.
        Carries the CSRF token too, so a write that comes before the panel ever opened (a
        comment toast's Open thread) never goes out with an empty one."""
        session.setdefault("csrf", secrets.token_hex(16))
        try:
            out = dict(_inbox().unread_total(_inbox().pixai_session()))
        except Exception as e:                                   # noqa: BLE001
            return _inbox_fail(e, total=None, csrf=session["csrf"])
        out["csrf"] = session["csrf"]
        return jsonify(out)

    @app.route("/api/inbox/events")
    @tier(LOGIN)
    def api_inbox_events():
        """ON PIXAI NOW: the banners PixAI runs whose link is under /event/. Public and sent
        with no credential; cached an hour. The app never follows a link -- a press opens it."""
        return jsonify({"events": _inbox().current_events()})

    def _inbox_write_body():
        """The JSON body of an inbox write, or a refusal: CSRF before anything else."""
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return body, (jsonify({"error": "Your session expired. Reload the page and try "
                                            "again."}), 400)
        return body, None

    def _inbox_write(fn, *args):
        """Run one of moonglade.inbox's writes and hand back its answer. A crash past its own
        handling is an unclear answer, never a success."""
        ib = _inbox()
        try:
            return jsonify(fn(ib.pixai_session(), *args))
        except Exception as e:                                   # noqa: BLE001
            return jsonify({"state": "unclear", "error": _redact_host_paths(str(e))[:200],
                            "message": "No clear answer. Nothing was sent twice; check on "
                                       "PixAI."})

    @app.route("/api/inbox/read", methods=["POST"])
    @tier(LOGIN)
    def api_inbox_read():
        """Opening a row or a work card: {csrf, ids}. One mark-read write and its read-back."""
        body, bad = _inbox_write_body()
        if bad:
            return bad
        ids = body.get("ids") if isinstance(body.get("ids"), list) else []
        return _inbox_write(_inbox().mark_read, ids)

    @app.route("/api/inbox/read-all", methods=["POST"])
    @tier(LOGIN)
    def api_inbox_read_all():
        """⋯ Mark all read: {csrf, tab}. One watermark write for the tab's unread types."""
        body, bad = _inbox_write_body()
        if bad:
            return bad
        return _inbox_write(_inbox().mark_all_read, str(body.get("tab") or ""))

    def _own_work(artwork_id):
        """True when `artwork_id` is one of the owner's own published works -- a row in this
        library. Replies are for those alone (v1), and the thread is read only for them."""
        from moonglade.catalog_verbs import artwork_media_ids
        aid = str(artwork_id or "").strip()
        return bool(aid.isdigit() and artwork_media_ids(db_path, [aid]))

    @app.route("/api/comments/<artwork_id>")
    @tier(LOGIN)
    def api_comments(artwork_id):
        """A published work's comment thread (?page=N, 50 a page, newest first): read live when
        Details' comments section scrolls into view, kept five minutes in memory, never
        archived. Also: who "you" are (the account's id and display name, for the reply's
        question), read_only (the reply box shows disabled with the reason) and the CSRF token."""
        session.setdefault("csrf", secrets.token_hex(16))
        extra = {"csrf": session["csrf"], "read_only": _inbox_read_only()}
        if not _own_work(artwork_id):
            return _inbox_fail("Comments show for your own published works only.",
                               items=[], **extra)
        ib = _inbox()
        try:
            gsession = ib.pixai_session()
            out = dict(ib.read_thread(gsession, artwork_id, request.args.get("page") or 1))
        except Exception as e:                                   # noqa: BLE001
            return _inbox_fail(e, items=[], **extra)
        out.update(extra, my_name=ib.display_name(gsession))
        return jsonify(out)

    @app.route("/api/comments/<artwork_id>/reply", methods=["POST"])
    @tier(LOGIN)
    def api_comments_reply(artwork_id):
        """[Post publicly] in the reply's question: {csrf, reply_to, content}. One POST and its
        read-back (moonglade.inbox.post_reply). Your own works only."""
        body, bad = _inbox_write_body()
        if bad:
            return bad
        if not _own_work(artwork_id):
            return jsonify({"state": "refused", "message": "Replies are for your own published "
                                                           "works only. Nothing was posted."})
        return _inbox_write(_inbox().post_reply, artwork_id, body.get("reply_to"),
                            body.get("content"))

    @app.route("/api/comments/<artwork_id>/delete", methods=["POST"])
    @tier(LOGIN)
    def api_comments_delete(artwork_id):
        """[Delete] in "Delete my reply"'s question: {csrf, message_id}. One DELETE and its
        read-back (moonglade.inbox.delete_reply). Your own reply on your own work only."""
        body, bad = _inbox_write_body()
        if bad:
            return bad
        if not _own_work(artwork_id):
            return jsonify({"state": "refused", "message": "Only your own replies on your own "
                                                           "works. Nothing was deleted."})
        return _inbox_write(_inbox().delete_reply, artwork_id, body.get("message_id"))

    @app.route("/api/inbox/gifts")
    @tier(LOGIN)
    def api_inbox_gifts():
        """The Gifts tab and the phone's Gift box: PixAI's REWARD messages (the side-effect-free
        thread read -- never the DM mark-read) and the credit-pack bonuses on hand, which open
        PixAI. No thread at all is the real empty state."""
        session.setdefault("csrf", secrets.token_hex(16))
        extra = {"csrf": session["csrf"], "read_only": _inbox_read_only()}
        ib = _inbox()
        try:
            gsession = ib.pixai_session()
            out = dict(ib.list_gifts(gsession))
        except Exception as e:                                   # noqa: BLE001
            return _inbox_fail(e, gifts=[], bonuses=[], **extra)
        out.update(extra, bonuses=ib.credit_bonuses(gsession),
                   my_name=ib.display_name(gsession))      # the claim preview names the account
        return jsonify(out)

    @app.route("/api/inbox/gifts/claim", methods=["POST"])
    @tier(LOGIN)
    def api_inbox_gifts_claim():
        """[Claim] in a gift's preview: {csrf, id}. One claim write and its status read-back."""
        body, bad = _inbox_write_body()
        if bad:
            return bad
        return _inbox_write(_inbox().claim_gift, body.get("id"))

    # -- provided to ctx (split_move) --
    # -- end --
