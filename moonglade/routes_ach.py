"""moonglade/routes_ach.py -- the achievement routes: the Folio's read (/api/achievements, with its
once-a-day telemetry marks), the skin switch, the beacon's nonce top-up and its event, and the
narrator's poke, with the lock the read and the skin switch hold.

Split out of gallery.create_app (split phase 4, 2026-11-20), verbatim: create_app calls
register(app, ctx) once, where the block was, after the training routes. Names the block reads
from create_app's setup and the front door (the CSRF check, the beacon's session id) come in
through ctx (the bound-from-ctx lines below), so every closure on both sides holds the one same
object. The `_ach_lock` bound in register is create_app's own lock, moved with its only two users
(the achievements read and the skin switch): it shadows moonglade.ach_beacon's module-level
`_ach_lock` (gallery's, until the beacon's tables left gallery's top level), and it stays a
separate lock, as it was. The nonce tables and their functions (_ach_mint, _ach_consume,
_ach_debounced, _ach_rate_ok) live in moonglade.ach_beacon and are imported inside the routes
that call them, at call time, so the front door's page render, the Loom shell and these routes
mint and spend in one table, and a test's patch of moonglade.ach_beacon still reaches the route.
"""
import threading

from flask import jsonify, request, session

from moonglade import account_prefs as _account_prefs
from moonglade import achievements as _achievements
from moonglade import branding as _branding
from moonglade import telemetry as _telemetry


def register(app, ctx):
    from moonglade.web_tiers import LOGIN, tier
    # -- bound from ctx (split_move) --
    _ach_sid = ctx._ach_sid
    _check_csrf = ctx._check_csrf
    db_path = ctx.db_path
    out_dir = ctx.out_dir
    # -- end --

    _ach_lock = threading.Lock()

    _telem_day = {"day": None}   # once-per-day throttle for the passive marks

    @app.route("/api/achievements")
    @tier(LOGIN)
    def api_achievements():
        """Milestone progress + skin unlocks, computed from local catalog stats +
        the persisted telemetry counters. Read-only catalog data (no spend, no
        network) so — like the picker — it's NOT localhost-gated; the owner browsing
        over LAN still sees their trophies. ?mark=1 records the currently newly-earned
        achievements as 'seen' so the unlock toast fires exactly once.

        Side effects (cheap, fail-soft): marks today in the Vigil day ledger and sweeps
        the state-derived feat flags. (It no longer looks at the time of day: a page load
        is not evidence of anything -- see stamp_session_hour.) A feat the
        roster marks hidden goes out MASKED until it is earned -- collapsed with
        every other still-masked one into a single ??? placeholder, so devtools
        can't spoil them or even count how many remain; the whole feat tab stays
        cloaked until the first feat lands."""
        import datetime as _dt
        try:
            today = _dt.date.today().isoformat()
            if _telem_day["day"] != today:
                _telem_day["day"] = today
                _telemetry.telem_mark_day(out_dir=out_dir)
                _telemetry.sweep_telemetry(out_dir)
        except Exception:
            pass
        # ONE telemetry read for the whole request. This route wanted the store three
        # times -- the metric flatten, the first-sync gate, and compute's `sets` -- and
        # was reading and parsing the file for each. Same values, a third of the I/O.
        #
        # Loaded BEFORE the branding sweep, and handed to it, because the sweep's own
        # flag short-circuit wants exactly this store and used to parse it a second
        # time on every fetch. The sweep writes through to the file and mirrors the
        # FLAG it may set back into this dict, so the copy the rest of the request
        # reads from carries that write -- without that, a store loaded before the
        # sweep is one write stale for the remainder of the request. (A baseline the
        # sweep records is read only by the next scan, so it is not mirrored.)
        telem = _telemetry.load_telemetry(out_dir)
        # Unlike sweep_telemetry above, this runs EVERY call rather than once a day:
        # a file dropped into the tree since the last fetch is picked up on the next
        # reload, not up to a day later. See sweep_branding_drops()'s own docstring.
        try:
            _branding.sweep_branding_drops(out_dir, telem=telem)
        except Exception:
            pass
        metrics = _achievements.achievement_metrics(db_path)
        metrics.update(_telemetry.telemetry_metrics(out_dir, telem=telem))
        # Gate the unlock toasts until the first full sync completes (see first_sync_complete):
        # first-light is images>=1, so without this it pops seconds into a fresh first sync.
        fsd = _telemetry.first_sync_complete(out_dir, db_path, telem=telem)
        persist_error = None
        with _ach_lock:
            state = _achievements.load_ach_state(out_dir)
            result = _achievements.compute_achievements(metrics, state.get("seen"),
                                          sets=telem.get("sets", {}),
                                          earned_at=state.get("earned_at"))
            newly = result["newly"]
            if not fsd:
                result["newly"] = []   # first sync still running -- withhold celebrations and
                newly = []             # leave `seen` untouched so the rungs fire on completion
            if fsd and request.args.get("mark") == "1":
                today = _dt.date.today().isoformat()
                ea = dict(state.get("earned_at") or {})
                # stamp every currently-earned achievement not yet dated: backfills the
                # pre-existing earns as "recognized today", records new ones going forward
                for a in result["achievements"]:
                    if a["earned"] and a["id"] not in ea:
                        ea[a["id"]] = today
                state["earned_at"] = ea
                if newly:
                    state["seen"] = sorted(set(state.get("seen") or []) | set(newly))
                # save_ach_state()'s bool return used to be discarded here, so a disk-write
                # failure still answered 200 with no hint that "seen"/earned_at never made it
                # to disk -- the newly-earned toast would then re-fire on the next load since
                # the server forgot it already showed it. The achievements DATA below is still
                # correct either way (computed fresh from the catalog every call, not from the
                # state file), so this stays a soft error alongside a normal response rather
                # than failing the whole request.
                if not _achievements.save_ach_state(out_dir, state):
                    persist_error = "could not save achievement progress (disk write failed)"
            earned_at = state.get("earned_at") or {}
        feats_revealed = any(
            a["earned"] for a in result["achievements"] if a["tier"] == "feat")
        unleashed = any(a["id"] == "triggered" and a["earned"]
                        for a in result["achievements"])
        # Hidden feats never appear in the array until they are earned. They used to
        # collapse to ONE "???" placeholder entry (2026-08-13); Session G replaced that with
        # `feats.masked` below -- a riddle and a silhouette for one feat, and no entry at
        # all, so neither the array's length nor any entry in it says anything about how
        # many secrets remain.
        masked_metrics, n_masked, visible = set(), 0, []
        sealed_by_id = {r["id"]: r for r in _achievements._roster() if isinstance(r, dict)}
        earned_ids = {a["id"] for a in result["achievements"] if a["earned"]}
        for a in result["achievements"]:
            if a["hidden"] and not a["earned"]:
                n_masked += 1
                masked_metrics.add(a["metric"])
                continue
            if not a["earned"]:               # roasts are the reward, not a preview
                a["roast"] = ""
                a["roast_nsfw"] = ""
            elif not unleashed:               # uncensored lines stay locked until Triggered
                a["roast_nsfw"] = ""
            if a["earned"]:                   # the roster flags go out only once earned
                a.update(_branding._earned_roster_flags(sealed_by_id.get(a["id"])))
            else:                             # "N to go": never a feat, never an unmeasured metric
                prog = _achievements.achievement_progress(a, metrics)
                if prog is not None:
                    a["progress"] = prog
            visible.append(a)
        result["feats"] = _branding._feats_payload(earned_ids, n_masked, feats_revealed, unleashed,
                                         app.secret_key)
        # The Folio's Marks row (relics by kind): earned, awarded marks only.
        try:
            result["relics"] = {"marks": _branding.earned_relic_marks(out_dir, earned_ids)}
        except Exception:
            result["relics"] = {"marks": []}
        result["achievements"] = visible
        # a masked feat's metric name/value must not leak through the metrics echo
        still_visible = {a["metric"] for a in result["achievements"] if a.get("metric")}
        for k in masked_metrics - still_visible:
            metrics.pop(k, None)
        # The Vigil chip (O5): the run of days with a generation, and the best run ever. From the
        # gen_days ledger; a fresh install with no days answers day 1, best 1.
        try:
            _gd = (telem.get("day_lists") or {}).get("gen_days")
            result["vigil"] = _telemetry.vigil_status(_gd if isinstance(_gd, list) else [])
        except Exception:
            result["vigil"] = {"day": 1, "best": 1}
        result["feats_revealed"] = feats_revealed
        result["unleash_available"] = unleashed
        result["skin"] = state.get("skin", "moonglade")
        result["earned_at"] = earned_at   # {id: iso-date}; only earned ids -> no hidden-feat leak
        result["metrics"] = metrics
        if persist_error:
            result["error"] = persist_error
        return jsonify(result)

    @app.route("/api/skin", methods=["POST"])
    @tier(LOGIN)
    def api_skin():
        """Set the active cosmetic skin. Only an *earned* skin may be applied (server checks
        against current unlocks), so a client can't force a locked palette. Persists to
        out_dir/_moonglade/records/achievements.json. Cosmetic + local-only, no spend."""
        body = request.get_json(silent=True) or {}
        skin = str(body.get("skin") or "").strip()
        if skin not in _achievements._skin_ids():
            return jsonify({"error": "unknown skin"}), 400
        # #38: this gate used to compute from achievement_metrics() ALONE -- no
        # telemetry merge, no earned_at -- so any telemetry-backed or pinned skin
        # unlock showed earned in the Folio yet 403'd here. It now runs the exact
        # recipe /api/achievements and _mark_earned() use (guarded by
        # dev/tests/test_achievements.py's gate-parity tests).
        _m = _achievements.achievement_metrics(db_path)
        _m.update(_telemetry.telemetry_metrics(out_dir))
        result = _achievements.compute_achievements(_m,
                                      sets=_telemetry.load_telemetry(out_dir).get("sets", {}),
                                      earned_at=_achievements.load_ach_state(out_dir).get("earned_at"))
        earned = {s["id"] for s in result["skins"] if s["earned"]}
        if skin not in earned:
            return jsonify({"error": "skin locked", "skin": _achievements.load_ach_state(out_dir)["skin"]}), 403
        with _ach_lock:
            state = _achievements.load_ach_state(out_dir)
            changed = state.get("skin") != skin
            state["skin"] = skin
            saved = _achievements.save_ach_state(out_dir, state)
        if not saved:
            # save_ach_state() is "best-effort; swallows write errors" by design (its own
            # docstring) -- but that return value used to be dropped on the floor here, so a
            # disk-write failure still answered 200 {"skin": skin} as if it had stuck. Report
            # what's ACTUALLY active (a fresh read, not the requested value) instead of lying.
            return jsonify({"error": "could not save skin (disk write failed)",
                            "skin": _achievements.load_ach_state(out_dir)["skin"]}), 200
        if changed:                       # Interior Decorator: an explicit re-dress
            _telemetry.telem_bump("skin_changed_runs", out_dir=out_dir)
        return jsonify({"skin": skin})

    @app.route("/api/ach-nonce")
    @tier(LOGIN)
    def api_ach_nonce():
        """A fresh beacon nonce for a page whose own has gone stale (idle past the 60s
        window, or spent). Same session budget as the events themselves -- see
        _ach_rate_ok(). The render seams (app_page, /loom) mint their first one inline;
        this is the top-up."""
        from moonglade.ach_beacon import _ach_mint, _ach_rate_ok
        sid = _ach_sid()
        if not _ach_rate_ok(sid):
            return jsonify({"error": "slow down"}), 429
        return jsonify({"nonce": _ach_mint(sid)})

    @app.route("/api/ach-event", methods=["POST"])
    @tier(LOGIN)
    def api_ach_event():
        """Feat-event beacon from the front-end: the Starfall key-sequence moment and the
        in-app manual. Whitelisted event names only; each is a cosmetic local counter
        (no spend). Narrator pokes used to ride this beacon; they have their own route
        (/api/narrator/poke) since the ladder, which keeps its count and clocks per
        account on the server, and an event named "narrator" is refused here so no
        second road can move that count.

        LOGIN again since 2026-09-07, on the owner's ruling ("I feel like
        triggered should be obtainable easily on a phone just like desktop. For
        sure build the nonce."). The per-render nonce this route now requires is
        what makes LOGIN honest, and it is the work the 2026-08-26 comment here
        listed as "NOT DONE HERE".

        THE HISTORY, kept because the reasoning still stands. LOCALHOST from
        2026-08-26 to 2026-09-07: the beacon is the ONLY thing standing between a
        feat and being earned -- there is no server-side re-check that the
        gesture actually happened, so any signed-in session could POST
        a feat event straight from a console and arm the feat without ever
        entering the code. Narrowing to loopback meant a feat could only be armed
        at the server's own keyboard, the one place the gesture can be witnessed.
        The cost was that a phone or any other LAN device lost all three feats,
        and the owner judged that cost too high once the nonce was buildable.

        WHAT THE NONCE WITNESSES INSTEAD. Not where the request came from, but
        that it came from a page THIS SERVER RENDERED FOR THIS SESSION: the
        nonce is minted into the render (window.MG_BOOT.ach_nonce, or the Loom
        shell's own inline mint), is good for exactly one event inside 60
        seconds, and is refused when presented by another session. A console POST
        has none. A replay has a spent one. A nonce lifted from someone else's
        page is not this session's to spend. That is a softer witness than
        loopback -- someone determined can still read their own page's nonce out
        of MG_BOOT and curl it -- but it is the same class of witness CSRF gives
        us everywhere else, and it costs a phone nothing.

        Also here, so a real gesture stays one event: a 150ms debounce per
        (session, event), and 30 beacon calls per session per rolling minute,
        beyond which the answer is 429 and no counter moves. The debounce is a
        wall-clock gap, so its width IS its meaning: 150ms is under a hand and
        over a double-fired DOM event, which is the only thing it should fold
        together. It shipped at 400ms earlier the same day and swallowed every
        second tap of an ordinary phone tap-rate -- see _ach_debounced(). A
        debounced reply is accepted, hands back a nonce and counts nothing.

        The other half of one double-fired click is one nonce sent twice: the
        twin that loses is refused 403 as consumed. The clients do NOT refresh
        and retry that one -- see achNonce.js -- or the retry would count the
        same gesture twice from the other side.

        The clients still treat a refusal as a no-op by design: api.js never
        throws (a 403 comes back as an {error} body) and the key-sequence handler
        is explicitly fail-soft (the stars and toast still play). What is new
        is that every caller now goes through notify/achNonce.js, which adopts
        the `next_nonce` an accepted event returns and re-asks /api/ach-nonce
        once on a stale-page 403 before giving up quietly.

        THE EVENT NAMES ARE PUBLIC -- they sit in served JS and in this whitelist -- so they
        name the moment, never the gesture: the key sequence posts "starfall" (renamed
        2026-10-02 from a word that gave the egg away). There is no alias for the old name:
        a stale cached page's 400 is a silent no-op and the next press after a reload counts.
        The telemetry flag it sets keeps its key, which is the sealed roster's metric."""
        from moonglade.ach_beacon import _ach_consume, _ach_debounced, _ach_mint, _ach_rate_ok
        sid = _ach_sid()
        if not _ach_rate_ok(sid):
            return jsonify({"error": "slow down"}), 429
        body = request.get_json(silent=True) or {}
        ev = str(body.get("event") or "").strip()
        if ev not in ("starfall", "docs"):
            return jsonify({"error": "unknown event"}), 400
        # One refusal wording for missing, unknown, expired and foreign alike: which
        # check failed is exactly the thing a replay probe would want to learn, and
        # every one of them has the same fix for a real page.
        if not _ach_consume(str(body.get("nonce") or ""), sid):
            return jsonify({"error": "stale page — reload"}), 403
        # A consumed nonce always buys the next one, debounced or not -- otherwise the
        # second half of a double-fire leaves the page with no nonce at all.
        nxt = _ach_mint(sid)
        if _ach_debounced(sid, ev):
            return jsonify({"ok": True, "debounced": True, "next_nonce": nxt})
        if ev == "starfall":
            _telemetry.telem_flag("konami_triggered", out_dir=out_dir)
            return jsonify({"ok": True, "next_nonce": nxt})
        _telemetry.telem_bump("docs_opened", out_dir=out_dir)
        return jsonify({"ok": True, "next_nonce": nxt})

    @app.route("/api/narrator/poke", methods=["POST"])
    @tier(LOGIN)
    def api_narrator_poke():
        """One poke at the narrator. Body: {"csrf": "..."} and nothing else. Answer:
        {"ok": true, "line": "..."} -- and, on the one poke that ends the ladder, a `final`
        object carrying the two lines that poke is answered with.

        THE SERVER DECIDES, THE CLIENT PAINTS. The count, the clocks and the choice of line
        are this route's and moonglade.narrator.poke()'s (a pure core that takes the time as
        a parameter); the page is told a line and nothing else, so it can learn neither how
        far along it is, nor which stage, nor whether a poke counted. A poke that does not
        count answers exactly like one that does.

        WHICH ACCOUNT: the session's, never the body's. The state is per account and is
        kept where the account cannot write it (account_state_*, not the prefs store).

        WHAT IT WRITES: that account's own ladder state, and -- only on a poke that counted
        -- the install's `narrator_pokes` metric raised to that account's count (a maximum,
        not a sum, so two accounts never pool their pokes). Triggered is then earned the way
        every feat is: the metric meets the sealed roster's threshold, and the next
        achievements read stamps it. Nothing here spends, reaches PixAI or retries.

        LINES come only from the sealed pack (`poke_lines`); a pack with none for what is
        being said answers a bare ellipsis, never copy invented here. LOGIN tier, CSRF by
        the explicit token (_check_csrf), like the other per-account writes."""
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "authentication required"}), 401
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "Expected a JSON object."}), 400
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        from moonglade import narrator as _nar
        pools = _nar.clean_pools(_achievements._poke_lines())
        now, today = _account_prefs._narrator_clock()
        try:
            with _account_prefs.account_state_locked(out_dir, user) as p:
                doc = _account_prefs.account_state_read(p)
                st, res = _nar.poke(doc.get("ladder"), now, today, pools)
                _account_prefs.account_state_write(p, dict(doc, ladder=st))
        except _account_prefs.AccountPrefsBusy as e:
            return jsonify({"error": str(e)}), 503
        except OSError:
            return jsonify({"error": "Could not save that."}), 500
        # The metric follows the count: only ever up, and re-asserted once the ladder is
        # done so a write that was lost once is repaired by the next poke.
        if res["counted"] or res["count"] >= _nar.FINAL:
            _telemetry.telem_max("narrator_pokes", res["count"], out_dir=out_dir)
        out = {"ok": True, "line": res["line"]}
        if res["final"]:
            final = {}
            out["line"] = _nar.NEUTRAL
            feat = next((a for a in _achievements._roster() if a.get("metric") == "narrator_pokes"), None)
            if feat and feat["id"] in _branding._earned_achievement_ids(out_dir, db_path, need=feat["id"]):
                final = {"id": feat["id"],
                         "clean": feat.get("roast") or feat.get("desc") or "",
                         "unleashed": feat.get("roast_nsfw") or ""}
                out["line"] = final["clean"] or _nar.NEUTRAL
                choice = _nar.clean_choice(_achievements._poke_lines().get("choice"))
                if choice:
                    final["choice"] = choice
            out["final"] = final
        return jsonify(out)

    # -- provided to ctx (split_move) --
    # -- end --
