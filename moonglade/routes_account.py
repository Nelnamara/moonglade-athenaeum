"""moonglade/routes_account.py -- the account's routes: the header chip (/api/account), the
account detail (card history, coupons, the credit log), stats, the first-run API-key save
(LOCALHOST), the asset container's status and fetch, the daily claim, prompt snippets, the
Toolbox presets, saved views, the per-account preferences and the in-app guide (index, page,
online, About), with their helpers and the snippet, preset and saved-view locks.

Split out of gallery.create_app (split phase 4, 2026-11-20), verbatim: create_app calls
register(app, ctx) once, where the first block was, after the library routes. Names the block
reads from create_app's setup, the front door (the CSRF check, the PixAI session, the host-path
redactor) and the background block (the job log, the asset job) come in through ctx (the
bound-from-ctx lines below), so every closure on both sides holds the one same object; it hands
out _load_presets, which the spend routes read through their ctx as the same object. gallery's
own names are imported inside the function that reads them, at call time, so a test's patch of
moonglade.gallery still reaches the route.
"""
import json
import os
import secrets
import threading

from flask import jsonify, request, session

from moonglade import about as _about
from moonglade import account_prefs as _account_prefs
from moonglade import achievements as _achievements
from moonglade import assets as moonglade_assets
from moonglade import branding as _branding
from moonglade import cards as _cards
from moonglade import paths as _paths
from moonglade import task_reads as _task_reads
from moonglade import telemetry as _telemetry
from moonglade import updater as _updater


def register(app, ctx):
    from moonglade.web_tiers import LOCALHOST, LOGIN, tier
    # -- bound from ctx (split_move) --
    _asset_job = ctx._asset_job
    _check_csrf = ctx._check_csrf
    _gen_session = ctx._gen_session
    _log_job = ctx._log_job
    _redact_host_paths = ctx._redact_host_paths
    db_path = ctx.db_path
    out_dir = ctx.out_dir
    # -- end --

    @app.route("/api/account")
    @tier(LOGIN)
    def api_account():
        """Credits + free-card balance for the header chip. Read-only; login required.
        Fails soft to nulls so the header never breaks."""
        from moonglade.gallery import backup_coverage
        try:
            core, session = _gen_session()
            me = core.account_info(session)
            try:
                credits = int(me.get("quotaAmount") or 0)
            except (TypeError, ValueError):
                credits = None
            cards = 0
            cards_by, expiries = [], []
            for k in _cards.list_kaisuukens(session):
                try:
                    n = int(k.get("count") or 0)
                except (TypeError, ValueError):
                    n = 0
                cards += n
                exp = (k.get("expires") or "")[:10]
                # category (Model Card / Video Card) was fetched by list_kaisuukens all
                # along but dropped before reaching cards_by, so the header tooltip and the
                # new Account-detail modal's Cards tab couldn't tell the types apart. Default
                # to "" (not None) so the JS `k.category ? ... : ""` check always compares a
                # string. (Carried by hand from the card-coupon-ledger branch, 2026-08-07.)
                cards_by.append({"name": k.get("name"), "count": n, "expires": exp,
                                 "category": k.get("category") or "",
                                 # Session Y (#69): each expiry date and its count, for the
                                 # chip's peach underline and "N <kind> expire <date>" lines.
                                 "expiry_counts": k.get("expiry_counts") or []})
                if exp and n:
                    expiries.append(exp)
            card_expiry = min(expiries) if expiries else None
            # claimable daily rewards (free credits/stamina) -- for the "+N claim" badge
            claim_credits, claim_ids = 0, []
            for c in core.list_claims(session):
                if not c.get("canClaim"):
                    continue
                claim_ids.append(c.get("id"))
                if "credit" in str(c.get("id") or "").lower():
                    try:
                        claim_credits += int(c.get("amount") or 0)
                    except (TypeError, ValueError):
                        pass
            sub = me.get("subscription") or {}
            # Real per-account LoRA-per-generation entitlement, straight from PixAI's own
            # membership data -- already fetched by account_info() for the CLI's --account
            # dashboard (run_account_info), never previously reached the web app, so the
            # picker had no real cap to enforce or show. `lora` wins when present (mirrors
            # the CLI's own field-check order -- an account's live paid entitlement);
            # `freeUserLora` is the fallback for an account with no `lora` value at all.
            # Exact coexistence semantics of the two fields are unconfirmed (no live account
            # to probe against from this checkout) -- treated as a soft pre-submit guard the
            # client can warn from, not a hard block, since PixAI's own server is the real
            # authority on any submit that slips past it.
            # Shared with the submit-side guard so the number the drawer PAINTS and the
            # number the server ENFORCES can never disagree. Crucially this now returns the
            # free-tier cap for a non-member instead of null: null hid the counter and
            # switched the client guard off entirely the moment a membership lapsed.
            lora_cap = core.account_lora_cap(me)
            # Backup coverage: server's lifetime TASK count vs distinct tasks we hold locally.
            # Both are task counts (not images), so the ratio is honest.
            try:
                server_tasks = int((me.get("tasks") or {}).get("totalCount"))
            except (TypeError, ValueError):
                server_tasks = None
            cov = backup_coverage(db_path, out_dir, server_tasks)
            local_tasks, coverage = cov["local"], cov["pct"]
            # Paid/free credit split for the rail sub-line (Account-detail design, drift
            # §37). A SUPPLEMENTARY read in its own guard: it must never break the core
            # account response (credits/cards/coverage) if the split call fails -- a failure
            # just leaves free/paid null, which the rail renders as an honest "split unknown".
            try:
                bal = core.credit_balance(session) or {}
            except Exception:
                bal = {}
            return jsonify({"credits": credits, "cards": cards,
                            "credits_free": bal.get("free"), "credits_paid": bal.get("paid"),
                            "cards_by": cards_by, "card_expiry": card_expiry,
                            "claim_credits": claim_credits, "claim_ids": claim_ids,
                            "sub": {"end": (sub.get("endAt") or "")[:10],
                                    "cancel": bool(sub.get("cancelAtPeriodEnd"))},
                            "server_tasks": server_tasks, "local_tasks": local_tasks,
                            "coverage_pct": coverage, "coverage_note": cov["note"],
                            "followers": me.get("followerCount"),
                            "following": me.get("followingCount"),
                            "lora_cap": lora_cap,
                            # True / False / null=unknown. The drawer gates members-only
                            # controls on an explicit False only, so an unreadable account
                            # never strips a paying member's options.
                            "is_member": core.account_is_member(me)})
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    # --- Account detail (cards · coupons · credit ledger) -------------------------------
    # The web UI for the card-coupon-ledger branch's backend, wired into the Control Panel's
    # "PixAI account" modal (Account-detail design, drift §37). All three are READ-ONLY
    # account queries -- no mutation, no spend, no redeem -- and fail soft to {"error"}, 200
    # exactly like /api/account, so the modal degrades gracefully when PixAI is unreachable.
    def _acct_count(default, lo=1, hi=100):
        try:
            return max(lo, min(int(request.args.get("count") or default), hi))
        except (TypeError, ValueError):
            return default

    @app.route("/api/account/card-history")
    @tier(LOGIN)
    def api_account_card_history():
        """Benefit-card (kaisuuken) usage. ?all=1 -> the lifetime type roster
        (kaisuuken_type_catalog); otherwise the recent usage events (list_kaisuuken_logs,
        forward-paginated via ?after=<cursor>). Read-only."""
        try:
            core, session = _gen_session()
            if request.args.get("all") in ("1", "true", "yes"):
                return jsonify(_cards.kaisuuken_type_catalog(session))
            after = request.args.get("after") or None
            return jsonify(_cards.list_kaisuuken_logs(session, first=_acct_count(20), after=after))
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/account/coupons")
    @tier(LOGIN)
    def api_account_coupons():
        """Coupons / Credit Boost. On-hand (available|locked) by default; ?history=1 swaps
        to redeemed|expired. Informational only -- no redeem/apply here by design. Read-only,
        forward-paginated via ?after=<cursor>."""
        try:
            core, session = _gen_session()
            history = request.args.get("history") in ("1", "true", "yes")
            statuses = _cards.COUPON_STATUSES_HISTORY if history else _cards.COUPON_STATUSES_ON_HAND
            after = request.args.get("after") or None
            return jsonify(_cards.list_extra_package_boosts(session, statuses=statuses,
                                                          first=_acct_count(20), after=after))
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/account/credit-log")
    @tier(LOGIN)
    def api_account_credit_log():
        """Full credit movement history (purchase/gift/spend/refund). Newest-first;
        BACKWARD-paginated via ?before=<cursor>. Read-only."""
        try:
            core, session = _gen_session()
            before = request.args.get("before") or None
            return jsonify(_cards.list_credit_log(session, last=_acct_count(30),
                                                before=before))
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/stats")
    @tier(LOGIN)
    def api_stats():
        """Catalog totals for fetch()-driven headers: the SAME numbers the classic
        template bakes into its banner (catalog_counts -- images, videos, distinct
        collections) plus the backed-up percent its cover-badge lazily pulls from
        /api/account, computed the identical way (server lifetime TASK count from
        account_info vs distinct_task_count locally; both are tasks, not images, so
        the ratio is honest -- see api_account above). LOGIN tier, matching index()
        and /api/account.

        The account read fails soft: coverage_pct/server_tasks come back null when
        PixAI is unreachable, which is exactly the case where the classic banner
        shows counts but hides its coverage badge. The catalog counts never depend
        on the network."""
        from moonglade.gallery import backup_coverage
        from moonglade.curation import catalog_counts
        counts = catalog_counts(db_path)
        try:
            core, gsession = _gen_session()
            me = core.account_info(gsession)
            server_tasks = int((me.get("tasks") or {}).get("totalCount"))
        except Exception:                                    # noqa: BLE001
            server_tasks = None
        cov = backup_coverage(db_path, out_dir, server_tasks)
        return jsonify({"images": counts["images"], "videos": counts["videos"],
                        "collections": counts["collections"],
                        "local_tasks": cov["local"], "server_tasks": server_tasks,
                        "coverage_pct": cov["pct"], "coverage_note": cov["note"]})

    @app.route("/api/setup/save-key", methods=["POST"])
    @tier(LOCALHOST)
    def api_setup_save_key():
        """First-run wizard: validate the submitted key with a real, read-only account_info
        call, and only write config.json AFTER that succeeds -- never write first and hope.

        Deliberately does NOT go through core._make_session()/load_token(): those prefer
        the module-cached core._cfg over a fresh config.json read (by design, so a running
        process doesn't need a restart to keep using its already-loaded key), which means
        validating "the same way normal calls authenticate" would silently validate against
        whatever key was cached at process start, not the one just pasted here. Confirmed
        live: a garbage key was reported as verified because the real cached key answered
        instead. Building the session by hand with the submitted key as the sole credential
        avoids that entirely.

        LOCALHOST-ONLY, enforced below -- this docstring has claimed it since the route
        was written, but the check itself was never actually present; a route-gating
        audit found and reproduced it 2026-07-19. It belongs in the same trust class as
        /api/branding/shortcut: it rewrites config.json, the file that also holds
        AUTH_SECRET_KEY and AUTH_USERS. Without the check, any logged-in LAN session
        could point the owner's generations at a foreign API key -- on a server started
        without a key (the exact first-run state this endpoint exists for) load_token's
        fresh-disk fallback picks it up on the very next spend."""
        body = request.get_json(silent=True) or {}
        key = (body.get("api_key") or "").strip()
        if not key:
            return jsonify({"error": "paste your API key first"}), 400
        from moonglade import backup as core
        import requests as _requests
        test_session = _requests.Session()
        test_session.headers.update({
            "Authorization": "Bearer {}".format(key),
            "Accept": "application/json",
            "User-Agent": "pixai-personal-backup/1.0",
            "apollo-require-preflight": "true",
            "x-apollo-operation-name": core.OPERATION_NAME,
        })
        try:
            me = core.account_info(test_session, raise_on_error=True)
        except Exception as e:
            msg = _redact_host_paths(str(e))
            if "401" in msg or "Unauthorized" in msg:
                return jsonify({"error": "That key was rejected by PixAI -- double-check it."}), 200
            return jsonify({"error": "Couldn't verify that key (temporary connection issue) -- try again."}), 200
        # THE config.json path (core._config_path(), i.e. moonglade.paths.config_path()) --
        # never rebuilt by hand: a hand-built copy is how a test once wrote the checkout's real
        # file (2026-08-02), and it would stop matching the moment the code left the app folder.
        cfg_path = core._config_path()
        # Serialize against the account writers on core._accounts_lock. This is the only
        # config.json read-modify-write in the app that doesn't go through core's account
        # helpers (deliberately -- see the note above about the module-cached _cfg), which
        # made it the one writer that could lost-update: /api/users/add commits a new
        # account between this read and this write, and the write puts back a snapshot
        # that never had it, silently erasing the account. Same lock, so same queue.
        with core._accounts_lock:
            try:
                cfg = json.loads(_paths.decode_text(cfg_path.read_bytes())) \
                    if cfg_path.exists() else {}
            except ValueError:
                # Present but unparseable -- REFUSE rather than overwrite. The old
                # bare `cfg = {}` fallback wrote back a one-key stub, destroying
                # AUTH_USERS (dropping the install into local-bootstrap mode),
                # AUTH_SECRET_KEY (logging everyone out), and now AUTH_EPOCH_SEQ
                # (rewinding revocation state itself).
                return jsonify({"error": "config.json exists but could not be parsed; "
                                         "not overwriting it. Fix or restore the file, "
                                         "then save the key again."}), 200
            except OSError as e:
                return jsonify({"error": "Could not read config.json: {}".format(
                    _redact_host_paths(str(e)))}), 200
            cfg["PIXAI_API_KEY"] = key
            try:
                # The atomic writer (a temp, flushed, then swapped in): a write cut short here
                # would leave a torn config.json, which stops every start in the move
                # (moonglade.migrate) where 3.19 still started.
                core._save_config(cfg)
            except OSError as e:
                return jsonify({"error": "Key verified, but couldn't write config.json: {}".format(
                    _redact_host_paths(str(e)))}), 200
            # Writing the file is only half of "saved": load_token() prefers core's
            # import-time _cfg snapshot over a fresh disk read, so a server that already
            # had a key kept authenticating every generation/account call with the OLD
            # one -- rotating a revoked key or switching accounts changed nothing until a
            # restart, while this route reported success. Refreshed ONLY for the field
            # just persisted, and only after the write actually landed; the rest of the
            # snapshot keeps the caching behaviour the rest of the app relies on.
            core._cfg["PIXAI_API_KEY"] = key
        try:
            credits = int(me.get("quotaAmount") or 0)
        except (TypeError, ValueError):
            credits = None
        return jsonify({"ok": True, "credits": credits})

    @app.route("/api/assets/status")
    @tier(LOGIN)
    def api_assets_status():
        """The asset container's current state: whether a (re)fetch is needed and,
        if a fetch is running/just finished/just failed, its live progress. LOGIN
        tier -- a read-only status poll, same trust class as /api/panel/status's
        non-sensitive half (this payload carries no host paths or account detail
        to redact, so unlike that route there is no local-vs-LAN split here).

        `needs` is computed fresh each call (moonglade.assets.needs_download(),
        a marker-file comparison, not a full re-hash) so a container that just
        finished downloading -- or was hand-copied in from another machine mid-
        session -- is reflected on the very next poll, not after a restart."""
        job = _asset_job.status()
        manifest = moonglade_assets.read_manifest()
        return jsonify({
            "needs": moonglade_assets.needs_download(_branding._container_path(), manifest),
            "manifest_present": manifest is not None,
            **job,
        })

    @app.route("/api/assets/fetch", methods=["POST"])
    @tier(LOGIN)
    def api_assets_fetch():
        """Start the asset container fetch. LOGIN tier (was LOCALHOST until
        2026-08-26): a signed-in LAN device may start it, because the Setup
        Wizard on a LAN device is exactly where a first run hits this -- it
        drives the checking -> downloading phases off /api/assets/status and
        this POST, and a localhost gate made that whole phase unreachable from
        the only machine that needed it.

        WHY IT DOESN'T BELONG WITH /api/setup/save-key. That neighbour writes a
        CALLER-SUPPLIED value into config.json (the file holding PIXAI_API_KEY /
        AUTH_SECRET_KEY / AUTH_USERS) -- the caller chooses what lands. This
        route chooses nothing: it pulls ONE fixed asset, pinned in
        moonglade/manifest.json to a single Release URL, verified against that
        manifest's sha256 cold before the swap, into one known path
        (_container_path()). No argument reaches it -- request body ignored --
        so a LAN caller cannot aim it at a different source, a different file,
        or a different destination. It is a fetch of a constant, not a write of
        an input.

        WHY REPEAT 685MB FETCHES AREN'T A LAN BANDWIDTH LEVER. AssetFetchJob's
        single-flight guard already blocks concurrency: start() takes self._lock
        and returns False while _state["status"] == "running", so a second call
        never launches a second thread -- it is the 409 below, matching
        /api/panel/run's own busy shape. One job at a time is the ceiling, and
        it was the ceiling before this tier change too; the gate was never what
        bounded the traffic."""
        started = _asset_job.start()
        if not started:
            st = _asset_job.status()
            if st["status"] == "running":
                return jsonify({"error": "a download is already running"}), 409
            return jsonify({"error": st.get("error") or "could not start"}), 200
        return jsonify({"ok": True})

    @app.route("/api/claim", methods=["POST"])
    @tier(LOGIN)
    def api_claim():
        """Claim ready daily rewards (free credits/stamina to the owner's OWN account -- no
        money moves). Login required; the header click IS the confirmation. One bad claim
        doesn't abort the rest. Returns {claimed, credits}.

        A successful claim also writes its own ACTIVITY TRACKER line (jobs.jsonl, which is
        what /api/jobs serves the tray). Written here rather than in the client because
        the tracker renders server truth -- a line added client-side would vanish on the
        next poll -- and because this route is the single seam both claim triggers funnel
        through: the header pill and the mascot popup share one `claim` in
        useClaimModal.js, which posts here. One hook, both paths, plus anything that
        claims later."""
        try:
            core, session = _gen_session()
            claimed, credits = 0, 0
            for c in core.list_claims(session):
                if not c.get("canClaim"):
                    continue
                try:
                    core.claim_reward(session, c.get("id"))
                    claimed += 1
                    if "credit" in str(c.get("id") or "").lower():
                        credits += int(c.get("amount") or 0)
                except Exception:                        # noqa: BLE001
                    pass
            if claimed:
                _telemetry.telem_bump("claims", claimed, out_dir=out_dir)   # Claimant
                # Terminal the moment it is written: a claim is instantaneous, so the row
                # is born "done" rather than passing through running. Its own id keeps it
                # out of the orphan sweep (which only chases numeric PixAI task ids) and
                # lets each claim keep its own line instead of overwriting the last one.
                _log_job("claim-" + secrets.token_hex(6), status="done", type="claim",
                         label=_achievements.claim_job_label(claimed, credits))
            return jsonify({"claimed": claimed, "credits": credits})
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    _snips_lock = threading.Lock()

    def _snips_path(user):
        # The login's own folder (moonglade.paths.account_dir, a case-safe key, so "Nel" and
        # "nel" don't collapse onto one file the way a bare quote(username) did on NTFS).
        d = _paths.account_dir(out_dir, user)
        d.mkdir(parents=True, exist_ok=True)
        return d / "snippets.json"

    def _read_snips_file(p):
        try:
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return [str(s) for s in data]
        except (OSError, ValueError):
            pass
        return []

    def _load_snippets(user):
        """This account's snippets. (The old install-wide file was copied into every login
        with none of its own by the move, moonglade.migrate, and is gone.)"""
        return _read_snips_file(_snips_path(user))

    @app.route("/api/snippets", methods=["GET", "POST"])
    @tier(LOGIN)
    def api_snippets():
        """Prompt snippets/favorites, stored PER-ACCOUNT (accounts/<key>/snippets.json in the
        library's _moonglade/) so one signed-in account can't see or wholesale-clobber
        another's -- same split saved views already got. Login required (any session, local
        or LAN)."""
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "not logged in"}), 401
        with _snips_lock:
            if request.method == "POST":
                body = request.get_json(silent=True) or {}
                # The explicit token, like every other per-account write
                # (dev/tests/test_csrf_coverage.py): checked before anything is read or written.
                if not _check_csrf(body):
                    return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
                snips = body.get("snippets")
                if not isinstance(snips, list):
                    return jsonify({"error": "snippets must be a list"}), 400
                clean = [str(s)[:800] for s in snips if str(s).strip()][:200]
                try:
                    # A temp beside it, then swapped in: a write cut short never leaves a
                    # torn snippets.json (the move reads a torn new home as damaged).
                    target = _snips_path(user)
                    tmp = target.with_name(target.name + ".tmp")
                    tmp.write_text(json.dumps(clean), encoding="utf-8")
                    os.replace(tmp, target)
                except OSError as e:
                    return jsonify({"error": _redact_host_paths(str(e))[:160]}), 200
                return jsonify({"snippets": clean})
            return jsonify({"snippets": _load_snippets(user)})
    _presets_lock = threading.Lock()

    # Toolbox presets are PER-ACCOUNT, one file in each login's folder (presets.json) --
    # same shape as _view_presets_path/_snips_path. They shipped install-wide; Moonglade is
    # explicitly not single-user (the repo is public and has real external users), so on any
    # install with more than one account, install-wide meant every account could see, and
    # overwrite, every other account's imported presets. The old shared file was copied into
    # every login with none of its own by the move (moonglade.migrate), and is gone.
    def _presets_path(user):
        d = _paths.account_dir(out_dir, user)
        d.mkdir(parents=True, exist_ok=True)
        return d / "presets.json"

    def _read_presets_data(p):
        try:
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except (OSError, ValueError):
            pass
        return {}

    def _load_presets(user):
        return _read_presets_data(_presets_path(user))

    @app.route("/api/presets", methods=["GET", "POST"])
    @tier(LOGIN)
    def api_presets():
        """Toolbox presets, stored per-account (presets.json in the login's folder) (preset
        prompts are PixAI-authored content, so they live as the owner's own captured
        task data, never in the repo). GET lists {name: {label, scene_id}} (no prompt
        bodies). POST {task_id, label?} imports one from a task the owner ran on the
        site: fetches the task, extracts chat.prompts + sceneId + modelId, saves it.
        Login required; uses the owner's key on import.

        The account comes from the SESSION, never the request body -- same contract as
        /api/view-presets and /api/snippets: a client that could name its own key could
        read and overwrite anyone's presets."""
        user = str(session.get("user") or "")
        if not user:
            return jsonify({"error": "authentication required"}), 401
        with _presets_lock:
            presets = _load_presets(user)
            if request.method == "GET":
                return jsonify({"presets": {
                    k: {"label": v.get("label") or k, "scene_id": v.get("scene_id", "")}
                    for k, v in presets.items()}})
            body = request.get_json(silent=True) or {}
            # The explicit token, before the import reads the task from PixAI with the
            # owner's key (dev/tests/test_csrf_coverage.py).
            if not _check_csrf(body):
                return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
            tid = str(body.get("task_id") or "").strip()
            if not tid:
                return jsonify({"error": "task_id required"}), 400
            try:
                core, gsession = _gen_session()
                task = _task_reads.task_detail_gql(gsession, tid) or {}
                params = task.get("parameters") or {}
                chat = params.get("chat") or {}
                prompt = chat.get("prompts") or params.get("prompts") or ""
                scene = str(params.get("sceneId") or "").strip()
                if not prompt:
                    return jsonify({"error": "task has no prompt to bank"}), 200
                name = scene or ("preset-" + tid[-6:])
                presets[name] = {
                    "label": (body.get("label") or "").strip()
                             or scene.replace("-", " ").title() or name,
                    "scene_id": scene,
                    "prompt": prompt,
                    "model_id": str(chat.get("modelId") or ""),
                    "from_task": tid,
                }
                dest = _presets_path(user)
                tmp = dest.with_suffix(".tmp")
                tmp.write_text(json.dumps(presets, indent=1), encoding="utf-8")
                os.replace(tmp, dest)   # atomic: a torn write can't eat the set
                return jsonify({"imported": name,
                                "label": presets[name]["label"]})
            except Exception as e:
                return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    _view_presets_lock = threading.Lock()

    # Saved views are PER-ACCOUNT, one file in each login's folder (views.json).
    #
    # They shipped install-wide (a single out_dir/view_presets.json) by analogy with
    # /api/skin, which is the right analogy for a THEME and the wrong one here: a skin is
    # a cosmetic preference, whereas a saved view is a stored search -- names and query
    # strings that say what someone looks for in their own library. Moonglade is
    # explicitly not single-user (the repo is public and has real external users), so on
    # any install with more than one account, install-wide means every account reads, and
    # can overwrite or delete, every other account's saved searches.
    #
    # For the case this feature was built for -- one owner, desktop and tablet, same
    # account against one server -- per-account behaves identically. Nothing is lost.
    def _view_presets_path(user):
        # The login's own folder, keyed by a case-safe key (B14 residual): the original
        # quote(username, safe="") here was case-PRESERVING, so "Nel" and "nel" quoted to two
        # different strings that named the SAME file on NTFS (case-insensitive-but-preserving),
        # even though account identity itself is case-sensitive. See _account_key's own
        # docstring for the full story.
        d = _paths.account_dir(out_dir, user)
        d.mkdir(parents=True, exist_ok=True)
        return d / "views.json"

    def _read_presets_file(p):
        try:
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {str(k): v for k, v in data.items() if isinstance(v, str)}
        except (OSError, ValueError):
            pass
        return {}

    def _load_view_presets(user):
        """This account's saved views. (The old install-wide file was copied into every login
        with none of its own by the move, moonglade.migrate, and is gone.)"""
        return _read_presets_file(_view_presets_path(user))

    def _ok_view_query(q):
        # Presets navigate via location.href = '/' + query on load. Requiring the
        # leading '?' (exactly what savePreset stores: location.search || '?') keeps
        # every stored value a same-page filter string -- a bare '//host' would resolve
        # protocol-relative and turn a saved view into an off-site redirect.
        return isinstance(q, str) and q.startswith("?") and len(q) <= 4096

    @app.route("/api/view-presets", methods=["GET", "POST"])
    @tier(LOGIN)
    def api_view_presets():
        """Saved-view presets (the gallery's "Saved views…" dropdown): {name: query
        string}, stored server-side in the login's folder so a view saved at the
        desktop exists on the tablet. Login tier (no spend, nothing destructive), and
        scoped to ONE ACCOUNT -- see _view_presets_dir() for why a saved search is not
        the same kind of thing as the install-wide skin choice. They lived in
        localStorage before this, one private set per browser; the client pushes a legacy
        set up through POST {merge} once, existing names winning ties. POST {name, query}
        saves one; POST {delete: name} removes one, wired to a "Delete" button next to the
        saved-view select (see deletePreset() in the page script).

        The account comes from the SESSION and is never accepted from the request body:
        a client that could name its own key could read and overwrite anyone's set, which
        would give back the exact cross-account exposure the per-account split removes."""
        user = str(session.get("user") or "")
        if not user:
            # Unreachable through the front door (/api/ is gated), so this is belt and
            # braces -- but the per-account contract must fail closed rather than fall
            # back to a shared or empty-named file if that ever stops being true.
            return jsonify({"error": "authentication required"}), 401
        with _view_presets_lock:
            presets = _load_view_presets(user)
            if request.method == "POST":
                body = request.get_json(silent=True) or {}
                # The explicit token, like every other per-account write
                # (dev/tests/test_csrf_coverage.py): checked before the set is changed.
                if not _check_csrf(body):
                    return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
                if isinstance(body.get("merge"), dict):
                    for k, v in body["merge"].items():
                        k = str(k).strip()
                        if k and k not in presets and _ok_view_query(v):
                            presets[k] = v
                elif body.get("delete") is not None:
                    presets.pop(str(body.get("delete")), None)
                else:
                    name = str(body.get("name") or "").strip()
                    if not name:
                        return jsonify({"error": "name required"}), 400
                    if not _ok_view_query(body.get("query")):
                        return jsonify({"error": "query must be a '?…' filter string"}), 400
                    presets[name] = body["query"]
                dest = _view_presets_path(user)
                tmp = dest.with_suffix(".tmp")
                tmp.write_text(json.dumps(presets, indent=1), encoding="utf-8")
                os.replace(tmp, dest)   # atomic: a torn write can't eat the set
            return jsonify({"presets": presets})

    # The one body shape POST /api/account/prefs accepts; anything else is refused.
    _ACCOUNT_PREFS_BODY_KEYS = frozenset(("set", "unset", "csrf"))

    @app.route("/api/account/prefs", methods=["GET", "POST"])
    @tier(LOGIN)
    def api_account_prefs():
        """The signed-in account's own preferences document -- the store is
        account_prefs_get/account_prefs_update above (see their section header for the
        file, the key rules, the caps and the corrupt-file contract).

        GET  -> {"prefs": {...}, "csrf": "..."}. The token rides along the way
                /api/myart/items hands its own out, so the client hook needs no boot
                plumbing to make its first write.
        POST {"csrf": "...", "set": {key: value}, "unset": [key]} -> {"prefs": {...}},
                the whole updated document. Either of set/unset may be omitted, not
                both; any other top-level field is refused. One bad key or value refuses
                the whole change (400, plain message) and writes nothing.

        LOGIN tier -- per-account state, the same tier as /api/view-presets,
        /api/snippets and the Loom's store. CSRF: the explicit-token class
        (_check_csrf(), the helper /api/duplicates/resolve and the user-admin routes
        use), because this is a state-changing POST a single forged request could
        otherwise drive.

        The account comes from the SESSION, never the body -- same contract as every
        per-account store here: a client that could name the account could read and
        overwrite anyone's."""
        user = str(session.get("user") or "")
        if not user:
            # Unreachable through the front door; fails closed if that ever changes,
            # and never falls back to ACCOUNT_LOCAL or a shared file.
            return jsonify({"error": "authentication required"}), 401
        if request.method == "GET":
            session.setdefault("csrf", secrets.token_hex(16))
            return jsonify({"prefs": _account_prefs.account_prefs_get(out_dir, user),
                            "csrf": session["csrf"]})
        if (request.content_length or 0) > 2 * _account_prefs.ACCOUNT_PREFS_DOC_MAX:
            return jsonify({"error": "That change is too large to save."}), 400
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "Expected a JSON object: "
                                     "{\"set\": {...}, \"unset\": [...]}."}), 400
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        extra = sorted(str(k) for k in body if k not in _ACCOUNT_PREFS_BODY_KEYS)
        if extra:
            return jsonify({"error": "Unknown field(s): {}. Send only 'set' and "
                                     "'unset'.".format(", ".join(extra)[:120])}), 400
        if "set" not in body and "unset" not in body:
            return jsonify({"error": "Nothing to change: send 'set' and/or 'unset'."}), 400
        if "set" in body and not isinstance(body["set"], dict):
            return jsonify({"error": "'set' must be an object of {key: value}."}), 400
        if "unset" in body and not isinstance(body["unset"], list):
            return jsonify({"error": "'unset' must be a list of keys."}), 400
        try:
            prefs = _account_prefs.account_prefs_update(out_dir, user, set_=body.get("set"),
                                         unset=body.get("unset"))
        except _account_prefs.AccountPrefsError as e:
            return jsonify({"error": str(e)}), 400
        except _account_prefs.AccountPrefsBusy as e:
            return jsonify({"error": str(e)}), 503
        except OSError as e:
            return jsonify({"error": "Could not save preferences: "
                                     + _redact_host_paths(str(e))[:160]}), 500
        return jsonify({"prefs": prefs})

    # ---- the in-app guide (Session I) -- see the module-level section "THE IN-APP GUIDE
    # AND THE ABOUT CARD" for what each piece reads. All four are read-only and LOGIN tier:
    # the guide is for anyone who can sign in, LAN sessions included, and none of them
    # writes, spends or reaches PixAI. ------------------------------------------------------
    @app.route("/api/help/index")
    @tier(LOGIN)
    def api_help_index():
        """The guide's page list (sidebar order, with each page's headings for the search),
        the Glossary's terms, and the version stamp the overlay prints."""
        from moonglade import backup as core
        return jsonify({
            "version": core.__version__,
            "display_version": _about.display_version(core.__version__),
            "pages": _about.wiki_index(),
            "glossary": _about.wiki_glossary(),
            "wiki_url": _about.WIKI_WEB_URL,
        })

    def _help_page_file(slug):
        """The page file for `slug`, looked up in the listing -- never a path built from
        the request. None for anything the listing did not find."""
        if not _about._WIKI_SLUG_RE.match(str(slug or "")):
            return None
        return _about._wiki_pages_on_disk(_about.wiki_dir()).get(slug)

    @app.route("/api/help/page/<slug>")
    @tier(LOGIN)
    def api_help_page(slug):
        """One page's markdown, as text. The client parses it into plain data and renders
        it through React, so nothing here is ever HTML."""
        p = _help_page_file(slug)
        if p is None:
            return jsonify({"error": "That page is not in this install's guide."}), 404
        try:
            md = p.read_text(encoding="utf-8")
        except OSError as e:
            return jsonify({"error": "Could not read that page: "
                                     + _redact_host_paths(str(e))[:160]}), 500
        return jsonify({"slug": slug, "markdown": md, "url": _about.wiki_web_url(slug)})

    @app.route("/api/help/online/<slug>")
    @tier(LOGIN)
    def api_help_online(slug):
        """Does the online wiki carry a newer copy of this page? Asked after the page has
        rendered, so a slow or absent network never holds the reader up. Only consults
        GitHub when the updater's own cached answer says a newer release is out -- see
        wiki_online_differs -- so an up-to-date install never asks at all."""
        p = _help_page_file(slug)
        if p is None:
            return jsonify({"error": "That page is not in this install's guide."}), 404
        try:
            md = p.read_text(encoding="utf-8")
        except OSError:
            return jsonify({"differs": False, "url": _about.wiki_web_url(slug)})
        behind = bool((_updater._update_cache.get("payload") or {}).get("behind"))
        return jsonify({"differs": _about.wiki_online_differs(slug, md, behind),
                        "url": _about.wiki_web_url(slug)})

    @app.route("/api/help/about")
    @tier(LOGIN)
    def api_help_about():
        """The About card: this version's CHANGELOG entry, the release's size (which decides
        between the what's-new sheet and About after an update), the art pack, the earlier
        entries. Whether a newer release is out is /api/update/check's to say, not this."""
        from moonglade import backup as core
        return jsonify(_about.about_payload(core.__version__, _branding._container_path()))

    # -- provided to ctx (split_move) --
    ctx._load_presets = _load_presets
    # -- end --
