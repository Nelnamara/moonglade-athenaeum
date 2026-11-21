"""moonglade/routes_train.py -- LoRA training's routes: recent tasks, the free quota, the
base models, the cover proxy, the Basic submit (preview, then a confirm priced off the fresh quote,
the free card and the quota, under the single-flight start lock and the on-disk train guard), the
datasets and their thumbnails, the runs list, the advanced flow (open, draft, the set, a
description, describe, start), retry, publish, rebates and make public, with their helpers, the
per-run locks, the train guard and the runs cache.

Split out of gallery.create_app (split phase 4, 2026-11-20), verbatim: create_app calls
register(app, ctx) once, where the block was, after the community routes. Names the block reads
from create_app's setup and the front door (the CSRF check, the PixAI session, the host-path
redactor) come in through ctx (the bound-from-ctx lines below), so every closure on both sides
holds the one same object; the start lock, the per-run locks and the train guard are bound once,
in register, and nothing outside it holds them. The module-level names it reads (gallery's, and
TrainGuard, moonglade.train_guard's since it left gallery's top level) are imported inside the
function that reads them, at call time, so a test's patch of their module still reaches the
route.
"""
import threading
import time

from flask import jsonify, redirect, request

from moonglade import cards as _cards
from moonglade import gen_road as _gen_road
from moonglade import models as _models
from moonglade import paths as _paths
from moonglade import telemetry as _telemetry
from moonglade import training as _training


def register(app, ctx):
    from moonglade.train_guard import TrainGuard
    from moonglade.web_tiers import LOGIN, tier
    # -- bound from ctx (split_move) --
    _check_csrf = ctx._check_csrf
    _gen_session = ctx._gen_session
    _redact_host_paths = ctx._redact_host_paths
    db_path = ctx.db_path
    out_dir = ctx.out_dir
    thumb_dir = ctx.thumb_dir
    # -- end --

    @app.route("/api/train/recent-tasks")
    @tier(LOGIN)
    def api_train_recent_tasks():
        """Recent generations grouped by task, for the mobile Train dataset picker
        (Moonglade Mobile.dc.html's 'tap a task, it adds its images' tile grid). Desktop's
        picker selects individual images one at a time; the mobile design picks whole
        TASKS instead -- each tile is one generation, tapping it adds every real sibling
        image from that batch. The design's own mock assumes every task contributes
        exactly 4 images (a fixed demo constant); real batches are 1-4, so this returns
        each task's REAL image count and media_id list rather than a hardcoded number --
        the mobile picker's running total is a sum of real counts, not tiles*4.

        PAGES BY TASK (issue #56): `next_before` is the cursor for the page below this one
        (null when there is nothing older); the picker sends it back as `before_at` +
        `before_task` when its sentinel scrolls into view, the desktop pool's mechanism.
        Pure catalog read, no network."""
        from moonglade.gallery import recent_train_task_page
        try:
            limit = max(1, min(int(request.args.get("limit") or 18), 60))
        except ValueError:
            limit = 18
        at = (request.args.get("before_at") or "").strip()
        before = {"at": at, "task": (request.args.get("before_task") or "").strip()} \
            if at else None
        page, nxt = recent_train_task_page(db_path, limit, before,
                                           (request.args.get("q") or "").strip())
        tasks = [dict(t, thumb="/thumbs/%s.jpg" % t["media_ids"][0]) for t in page]
        return jsonify({"tasks": tasks, "next_before": nxt})

    @app.route("/api/train/quota")
    @tier(LOGIN)
    def api_train_quota():
        """How many FREE LoRA trainings this account can use (PixAI's membership quota
        `free::user_lora_training`, counted only for a member -- core.training_free_quota).
        A training free card is the other free road; the submit preview checks for one per
        base (core.match_training_kaisuuken). Read-only, free."""
        try:
            core, session = _gen_session()
            return jsonify({"free_trainings": _training.training_free_quota(session)})
        except Exception as e:
            return jsonify({"free_trainings": 0,
                            "error": _redact_host_paths(str(e))[:200]}), 200

    @app.route("/api/train/models")
    @tier(LOGIN)
    def api_train_models():
        """Trainable base models grouped by architecture (the train panel's Model Type ->
        Model Theme picker). Read-only, free. Each model carries the VERSION id the submit
        needs, its real title, and a cover -- fixing the earlier build, which used the
        generic market search and rendered raw model ids with no architecture grouping.

        Off PixAI's own training config (core.training_config: /config/trainLoraModels,
        cached, the 2026-09-26 snapshot as fallback), so Tsubaki.3 (DiT.3) is offered and
        priced. `default_version_id` is the base the panel pre-selects -- the first SDXL
        row, PixAI's own default (SCOPE_2026-09-26 E7) -- not the first group's first
        model, which with DiT.3 listed first would be the 100,000-credit base."""
        try:
            core, session = _gen_session()
            cfg = _training.training_config()
            pause = _training.training_pause()
            return jsonify({"groups": _training.list_trainable_base_models(config=cfg),
                            "pricing": cfg["pricing"],
                            "default_version_id": _training.default_training_base(cfg),
                            # Session J: the Recommended tab (6a), Advanced's two bases, the
                            # four goals, PixAI's own estimate at its default length, the set
                            # rule, and its pause switch -- all read here, nothing written
                            "recommended_arch": _training.TRAIN_RECOMMENDED_TYPE,
                            "advanced_bases": _training.advanced_training_bases(cfg),
                            "goals": [{"value": v, "label": lab} for v, lab in _training.TRAIN_GOALS],
                            "eta": _training.training_eta(
                                _training.TRAIN_DEFAULT_OPTIONS["trainingSteps"]),
                            "image_constraints": cfg["image_constraints"],
                            "min_images": _training.TRAIN_MIN_IMAGES,
                            "max_images": _training.TRAIN_MAX_IMAGES,
                            "paused": pause is not None,
                            "resumes_at": (pause or {}).get("resumes_at") or ""})
        except Exception as e:
            return jsonify({"groups": [], "error": _redact_host_paths(str(e))[:200]}), 200

    import requests as _rq

    @app.route("/api/train/cover")
    @app.route("/api/pixai-cdn/thumb")   # the general name -- covers My Art's LoRA cards too
    @tier(LOGIN)
    def api_train_cover():
        """Proxy a PixAI CDN thumbnail (images-ng.pixai.art), which the browser can't load
        cross-origin from localhost but the server fetches fine. Started as the Train
        panel's base-model covers; My Art's Models & LoRAs tab (2026-08-06) hit the exact
        same block for its own cover_url rows and reuses this route rather than growing a
        second proxy. SSRF-guarded: the URL host MUST be exactly the PixAI image CDN --
        nothing else is fetchable through here. Read-only, cached a day (these thumbnails
        are immutable)."""
        from moonglade.web_policy import harden_file_response
        from moonglade.scenes import pixai_cdn_url_ok
        import urllib.parse as _up
        raw = request.args.get("u") or ""
        try:
            parsed = _up.urlparse(raw)
        except ValueError:
            return ("bad url", 400)
        if not pixai_cdn_url_ok(raw):
            return ("forbidden host", 403)
        try:
            # PUBLIC CDN thumbnails -- no auth needed (verified). A PLAIN per-request
            # requests.get, NOT _gen_session() and NOT a shared Session: the panel loads
            # ~15 covers at once across Flask's request threads, and (a) minting an
            # authenticated PixAI session per image is too slow, while (b) sharing one
            # requests.Session across those threads is not thread-safe and hangs them.
            # A fresh get() per call is thread-safe and plenty fast for cached thumbnails.
            r = _rq.get(raw, timeout=20)
            if r.status_code != 200:
                return ("upstream %d" % r.status_code, 502)
            resp = app.response_class(r.content,
                                      mimetype=r.headers.get("content-type", "image/webp"))
            resp.headers["Cache-Control"] = "public, max-age=86400"
            # Someone else's file under this origin: a cover that is not a raster
            # picture goes out as a download, never as a page.
            return harden_file_response(resp, _up.urlparse(raw).path.rsplit("/", 1)[-1])
        except Exception:
            return ("fetch failed", 502)

    _basic_start_lock = threading.Lock()

    def _reuse_ok(core, session, dataset_task_id, media_ids):
        """Is this Basic start a REUSE of an earlier set (PixAI's `reuse` price, sent as
        `trainingTaskId` with no images)? Only for a FINISHED Basic run that made a LoRA --
        found in the account's own LoRA list, the list the import shows -- and only when the
        posted images are exactly that run's set, same length, same ids (the site's own
        check; spend review, finding 7). Anything else, a failed read included, is a fresh
        set priced and sent in full. Never raises."""
        try:
            loras = _training.list_my_trained_loras(session, pages=5)
        except Exception:                               # noqa: BLE001
            return False
        posted = [str(m) for m in (media_ids or [])]
        for m in loras:
            t = m.get("task") or {}
            if str(t.get("id") or "") != str(dataset_task_id):
                continue
            if t.get("trainingMode") == "advanced" or str(t.get("status") or "") != "completed":
                return False
            ds = [str(x) for x in ((t.get("parameters") or {}).get("mediaIds") or [])]
            return (len(ds) == len(posted) and len(set(posted)) == len(posted)
                    and set(ds) == set(posted))
        return False

    @app.route("/api/train/submit", methods=["POST"])
    @tier(LOGIN)
    def api_train_submit():
        """Submit a Basic LoRA training task -- PREVIEW-FIRST, like /api/myart/publish.

        Without `confirm: true` this makes NO mutating call: it validates the request
        with the site's own rules and reports the real cost position (how many free
        trainings remain, whether a training free card covers it, what it costs).

        VALIDATION (SCOPE_2026-09-26 E7), before anything else: PixAI's trigger-word rules
        on the normalized string (core.validate_training), and its image rule over this
        catalog's own image sizes (core.check_training_images). An image the rule refuses
        refuses the whole run, named; an image whose size the catalog does not know is
        listed as not checked, never passed as checked.

        A REUSED SET (Session J 2a, 2026-09-28). `dataset_task_id` names an earlier Basic run
        whose set the grid holds exactly (imported whole); when _reuse_ok confirms it, the run
        is priced at PixAI's `reuse` tier and sent as PixAI's own page sends it --
        `trainingTaskId` and no images. Anything that is not exactly such a set is a fresh run,
        priced and sent in full; the preview says which (`reuse`, `price_reason`).

        COST. PixAI's train pages price a run from the same config the base list comes
        from (core.training_config -- `price` for a fresh dataset, `reuse` for a reused one).
        A run is FREE when either
          * the account is a member (membership tier present, 0 included) with free-training
            quota left -- it consumes one quota unit; or
          * a training free card matches the base (core.match_training_kaisuuken, checked
            only when the quota does not cover the run -- a deliberate difference from the
            site, see the comment at the check) and its held count is known to cover it --
            its id rides the submit.
        Anything else charges credits, and the confirmed call is REFUSED unless the caller
        sends `accept_credit_cost` as the AMOUNT it showed, equal to this run's price (409
        when it is not). A bare `true` is accepted only for a run whose price could not be
        quoted; whenever there is a number to name, the number is required (spend review
        2026-09-28, finding 6). A card check that FAILS treats the run as paid (owner,
        2026-09-26).

        DOUBLE STARTS (spend review 2026-09-28, finding 1). A Basic run has no id until PixAI
        creates it, so one account-wide lock serialises confirms (a second concurrent one gets
        409), and the on-disk TrainGuard is checked and ARMED before the mutation: the same
        run confirmed again within a minute is refused as a double click, and an unclear
        failure (a timeout, a dropped connection, a 5xx -- PixAI may have created and charged
        it) keeps the guard for 15 minutes and says the run may have started. Only a definite
        refusal disarms it.

        ORDER on the confirm: CSRF -> READ_ONLY (before ANY read, the reuse read included) ->
        validation -> quota / card -> the lock -> the guard -> the pause switch -> the
        amount -> arm -> one createTrainingTask -> resolve. Single attempt."""
        from moonglade.gallery import media_dims
        from moonglade.train_guard import TrainGuard
        body = request.get_json(silent=True) or {}
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        from moonglade import backup as core
        media_ids = body.get("media_ids") if isinstance(body.get("media_ids"), list) else []
        media_ids = [str(m) for m in media_ids if str(m).strip()]
        base_model_id = str(body.get("base_model_id") or "").strip()
        title = str(body.get("title") or "")
        trigger = str(body.get("trigger_words") or "")
        category = str(body.get("category") or "")
        dataset_task_id = str(body.get("dataset_task_id") or "").strip()
        confirming = bool(body.get("confirm"))
        if confirming:
            # READ_ONLY refuses the spend BEFORE the confirm's own reads -- the reuse check, the
            # free-card check and the pause switch -- so a read-only install makes no call on
            # the account for a submit it is going to refuse. submit_training checks it too.
            try:
                core._check_read_only("submit a LoRA training task")
            except Exception as e:                    # noqa: BLE001
                return jsonify({"error": str(e)}), 502
        try:
            core, session = _gen_session()
        except Exception as e:
            return jsonify({"error": "PixAI session unavailable: %s" % e}), 502

        cfg = _training.training_config()
        reuse = bool(dataset_task_id) and dataset_task_id.isdigit() and \
            _reuse_ok(core, session, dataset_task_id, media_ids)
        try:
            tw = _training.validate_training(base_model_id, media_ids, title, trigger, category,
                                        training_task_id=dataset_task_id if reuse else "",
                                        config=cfg)
        except Exception as e:
            return jsonify({"error": str(e)}), 400
        unchecked, image_note = [], ""
        if not reuse:
            rejected, unchecked = _training.check_training_images(
                media_ids, media_dims(db_path, media_ids), cfg["image_constraints"])
            if rejected:
                return jsonify({"error": _training.describe_rejected_training_images(rejected),
                                "rejected_images": rejected}), 400
            image_note = ("" if not unchecked else
                          "%d image%s could not be checked against PixAI's size rule (this "
                          "library doesn't know %s size)." % (
                              len(unchecked), "" if len(unchecked) == 1 else "s",
                              "its" if len(unchecked) == 1 else "their"))

        free_left = _training.training_free_quota(session)
        free_by_quota = free_left > 0
        # credits, or None -- off `cfg`, the very config the validation above read, so one
        # request can never validate against the live config and price off the snapshot
        list_price = _training.training_price_for_version(base_model_id, cfg)
        price = _training.training_price_tier(base_model_id, "reuse", cfg) if reuse else list_price
        # The training free card (owner ruling 4): checked only when the quota does not
        # already make the run free -- "before a paid run", as SCOPE_2026-09-26 E7 words it.
        # A DELIBERATE DIFFERENCE FROM THE SITE: PixAI's basic trainer runs the card check
        # whatever the quota and attaches a matching card even when the quota covers the run
        # (so there the card is spent and the quota kept); here a member holding both spends a
        # quota unit and keeps the card. Recorded in DECISIONS with the other differences.
        # Read-only; the card is spent only by the submit that carries its id. A FAILED check
        # never refuses (owner, 2026-09-26): the run is treated as paid, so the paid confirm's
        # acknowledgement -- which names the amount -- is what lets it through.
        card, card_checked = None, True
        if not free_by_quota:
            try:
                best = _training.match_training_kaisuuken(session, base_model_id,
                                                     raise_on_error=True)
            except Exception:                         # noqa: BLE001
                best, card_checked = None, False
            # A card whose held count is UNKNOWN is not taken as covering, although
            # card_covers() assumes a 1-ticket job is covered: PixAI's own training check
            # keeps only matches with consumeAmount <= total, so it would not attach it
            # either -- and here it would skip the paid acknowledgement on a 25k-100k run.
            if best and best.get("id") and _cards.card_covers(best) \
                    and not best.get("balance_unknown"):
                card = best
        free_by_card = card is not None
        is_free = free_by_quota or free_by_card
        reason = "reusing a dataset" if reuse else ""
        if free_by_quota:
            cost_note = "Free — uses 1 of your %d free trainings." % free_left
        elif free_by_card:
            cost_note = ("Free — your training free card%s covers this base, and it is "
                         "used up by this run." % (" (%s)" % card["name"]
                                                   if card.get("name") else ""))
        elif price is not None:
            cost_note = ("No free trainings or training free card for this base — it costs "
                         "%s credits to train%s." % ("{:,}".format(price),
                                                     " (the rate for reusing a dataset)"
                                                     if reuse else ""))
        else:
            cost_note = ("No free trainings or training free card for this base, and PixAI's "
                         "price list has no price for it — the amount could not be quoted.")
        if is_free and price is not None:
            cost_note += " (Normally %s credits.)" % "{:,}".format(price)
        if not free_by_quota and not card_checked:
            cost_note += " (Your free cards couldn't be checked just now.)"
        if not confirming:
            return jsonify({
                "preview": True, "image_count": len(media_ids),
                "title": title.strip(), "trigger_words": tw, "category": category,
                "free_trainings_left": free_left, "is_free": is_free,
                "free_by": "quota" if free_by_quota else ("card" if free_by_card else None),
                "card": ({"name": card.get("name"), "expires": card.get("expiresAt")}
                         if card else None),
                "price": price, "list_price": list_price, "reuse": reuse,
                "price_reason": reason, "cost_note": cost_note,
                "eta": _training.training_eta(_training.TRAIN_DEFAULT_OPTIONS["trainingSteps"]),
                "unchecked_images": unchecked, "image_note": image_note,
            })
        if not _basic_start_lock.acquire(blocking=False):
            return jsonify({"error": "Another training start is already on its way. Nothing "
                                     "was sent again."}), 409
        try:
            key = TrainGuard.basic_key(base_model_id, media_ids,
                                       dataset_task_id if reuse else "", title)
            blocked = train_guard.basic_blocked(key)
            if blocked:
                return jsonify({"error": blocked}), 409
            pause = _training.training_pause()
            if pause is not None:
                return jsonify({"error": "PixAI has paused new LoRA training runs%s, so nothing "
                                         "was submitted. Runs already training carry on." %
                                         (" — it expects to be back around %s"
                                          % pause["resumes_at"]
                                          if pause.get("resumes_at") else "")}), 409
            accepted = body.get("accept_credit_cost")
            if not is_free:
                if price is None:
                    if not bool(accepted):
                        return jsonify({"error": "This training charges credits (amount "
                                                 "unknown). Re-send with accept_credit_cost "
                                                 "to proceed."}), 402
                elif accepted is None or accepted is False:
                    return jsonify({"error": "This training charges credits (%s). Re-send "
                                             "with accept_credit_cost to proceed."
                                             % "{:,}".format(price)}), 402
                elif not _exact_amount(accepted, price):
                    # The acknowledgement names an amount (the panels send the price they
                    # showed): it must still be THIS run's price. A base changed after the
                    # quote, a set no longer a reuse, or a price list that moved refuses here
                    # instead of charging a number nobody accepted; a bare `true` is refused
                    # because there IS a number to name.
                    return jsonify({"error": "The price changed since you accepted it — you "
                                             "accepted %s, and this training costs %s credits. "
                                             "Nothing was spent; check the cost and confirm "
                                             "again." % (
                                                 ("{:,} credits".format(accepted)
                                                  if isinstance(accepted, (int, float))
                                                  and not isinstance(accepted, bool)
                                                  else "an unnamed amount"),
                                                 "{:,}".format(price))}), 409
            train_guard.basic_arm(key)
            try:
                task = _training.submit_training(
                    session, base_model_id, [] if reuse else media_ids, title, trigger,
                    category, training_task_id=dataset_task_id if reuse else "",
                    kaisuuken_id=(card["id"] if free_by_card else ""), config=cfg)
            except Exception as e:
                if _gen_road.definite_refusal(e, "training"):
                    train_guard.basic_resolve(key, "refused")
                    return jsonify({"error": str(e)}), 502
                train_guard.basic_resolve(key, "ambiguous")
                _runs_dirty()
                return jsonify({"error": "PixAI didn't answer clearly, so this run may have "
                                         "started. Check Runs before starting it again.",
                                "maybe_started": True}), 502
            train_guard.basic_resolve(key, "started")
        finally:
            _basic_start_lock.release()
        _runs_dirty()
        # (The Academy counts runs PixAI reports finished -- api_train_runs -- not submits.)
        return jsonify({"submitted": True, "task": task, "was_free": is_free,
                        "used_card": free_by_card, "reuse": reuse,
                        "free_trainings_left": (max(0, free_left - 1) if free_by_quota
                                                else free_left)})

    # ---- Training, Session J (2026-09-28): the advanced flow, runs, publish -------------------
    # The design, its adversarial review and the guard order per route are in
    # ../moonglade-internal/design/notes/training/BUILD-w3-train.md. Every route here is LOGIN
    # tier like the rest of /api/train, every POST checks the CSRF token first, and every
    # confirm checks READ_ONLY before it reads anything else. OPENING a screen only reads
    # (DECISIONS 2026-09-28, "Nothing writes on open").
    #
    # LOCKS. One lock per training task (and per model, for make-public). The paid and
    # irreversible routes (describe, start, retry, publish, make public) take it WITHOUT
    # waiting and refuse with 409 when another request holds it: the second of two clicks, two
    # tabs or a phone and a desktop never sends a second paid POST. The free writes (the set,
    # a description) wait for it (up to 15 s), so quick edits queue instead of being dropped.
    _train_locks = {}
    _train_locks_mu = threading.Lock()

    def _train_lock(key):
        with _train_locks_mu:
            lk = _train_locks.get(key)
            if lk is None:
                lk = _train_locks[key] = threading.Lock()
            return lk

    _BUSY = ("Another request is already working on this run. Nothing was sent again -- give "
             "it a moment, then look again.")
    # An advanced describe/start confirm refused by TrainGuard.paid_blocked (finding F1).
    _PAID_MAYBE_REFUSAL = ("Your last confirm of %s may have gone through: PixAI didn't "
                           "answer clearly. Check Runs before trying again (this guard clears "
                           "by itself after 15 minutes). Nothing was sent.")
    train_guard = TrainGuard(lambda: _paths.records_path(out_dir, "train_guard.json"))
    _runs_cache = {"full": None, "light": None}

    def _runs_dirty():
        _runs_cache["full"] = _runs_cache["light"] = None

    def _train_csrf_body():
        body = request.get_json(silent=True) or {}
        return body, _check_csrf(body)

    def _train_refusal(e, status=502):
        from moonglade import backup as core
        if isinstance(e, core.PixAIRestError):
            payload = {"error": _training.training_error_words(e), "code": e.code}
            ids = e.data.get("mediaIds")
            if isinstance(ids, list):
                payload["rejected_ids"] = [str(x) for x in ids]
            return jsonify(payload), (e.status if e.status and 400 <= e.status < 500 else 502)
        return jsonify({"error": _redact_host_paths(str(e))[:300]}), status

    def _read_only_refusal(core, what):
        try:
            core._check_read_only(what)
        except Exception as e:                          # noqa: BLE001
            return jsonify({"error": str(e)}), 502
        return None

    def _pause_refusal(core):
        pause = _training.training_pause()
        if pause is None:
            return None
        return jsonify({"error": "PixAI has paused LoRA training%s, so nothing was sent. Runs "
                                 "already training carry on." %
                                 (" -- it expects to be back around %s" % pause["resumes_at"]
                                  if pause.get("resumes_at") else ""),
                        "paused": True}), 409

    def _exact_amount(accepted, price):
        """The acknowledgement a paid confirm must carry: the NUMBER the user was shown, equal to
        the fresh quote. A bool is never an amount (True == 1 in Python), and a bare `true` is
        refused whenever there is a price to name (spend review, finding 6). A fractional
        amount is never the quote: int() would truncate 1200.5 onto a quote of 1200, so the
        number must be integer-valued AND equal (waves 2+3 review, finding F6)."""
        if isinstance(accepted, bool) or not isinstance(accepted, (int, float)):
            return False
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            return False
        try:
            a, p = float(accepted), float(price)
        except (OverflowError, ValueError):
            return False
        return a.is_integer() and a == p

    def _amount_refusal(accepted, price, what):
        if accepted is None or accepted is False:
            return jsonify({"error": "%s costs %s credits. Nothing was sent: confirm the amount "
                                     "to go ahead." % (what, "{:,}".format(price))}), 402
        return jsonify({"error": "The price changed since you saw it -- %s now costs %s "
                                 "credits. Nothing was sent; check it and confirm again."
                                 % (what.lower(), "{:,}".format(price)),
                        "price": price}), 409

    def _base_names(cfg):
        return {m["version_id"]: m["title"] for m in cfg["models"]}

    def _thumb_for(mid):
        return "/api/train/thumb/%s" % mid if mid else ""

    @app.route("/api/train/datasets")
    @tier(LOGIN)
    def api_train_datasets():
        """Earlier training sets to import ("Import from previous datasets", Session J 2a): the
        account's own finished Basic runs that made a LoRA -- the list PixAI's own import
        dialog shows (advanced runs are left out, as there). Each: {task_id, model_id, title,
        trigger_words, category, base_version_id, media_ids, count, cover}. Read-only."""
        try:
            core, session = _gen_session()
            loras = _training.list_my_trained_loras(session, pages=3)
        except Exception as e:                          # noqa: BLE001
            return jsonify({"datasets": [], "error": _redact_host_paths(str(e))[:200]}), 200
        out = []
        for m in loras:
            t = m.get("task") or {}
            p = t.get("parameters") or {}
            ids = [str(x) for x in (p.get("mediaIds") or []) if str(x).strip()]
            if not t.get("id") or t.get("trainingMode") == "advanced" or not ids \
                    or str(t.get("status") or "") != "completed":
                continue
            out.append({"task_id": str(t["id"]), "model_id": m["model_id"],
                        "title": str(p.get("title") or m["title"]),
                        "trigger_words": str(p.get("triggerWords") or ""),
                        "category": str(p.get("category") or ""),
                        "base_version_id": str(p.get("baseModelId") or ""),
                        "media_ids": ids, "count": len(ids),
                        "cover": _thumb_for(ids[0])})
        return jsonify({"datasets": out})

    _thumb_url_cache = {}

    @app.route("/api/train/thumb/<media_id>")
    @tier(LOGIN)
    def api_train_thumb(media_id):
        """A training-set image's picture, for any PixAI media id: this library's own thumbnail
        when it has one, otherwise PixAI's (an upload, or an image from an earlier set), read
        through the host-guarded CDN proxy. Read-only."""
        import urllib.parse as _up
        mid = str(media_id or "").strip()
        if not mid.isdigit():
            return ("bad id", 400)
        if (thumb_dir / ("%s.jpg" % mid)).is_file():
            return redirect("/thumbs/%s.jpg" % mid)
        url = _thumb_url_cache.get(mid)
        if url is None:
            try:
                core, session = _gen_session()
                url = core.media_thumbnail_url(session, mid) or ""
            except Exception:                           # noqa: BLE001
                url = ""
            if len(_thumb_url_cache) > 2000:
                _thumb_url_cache.clear()
            _thumb_url_cache[mid] = url
        if not url or _up.urlparse(url).netloc != "images-ng.pixai.art":
            return ("no picture", 404)
        return redirect("/api/pixai-cdn/thumb?u=" + _up.quote(url, safe=""))

    def _run_row_advanced(t, names, done=False):
        base = str(t.get("baseModelId") or "")
        row = {"id": str(t.get("id") or ""), "mode": "advanced",
               "title": str(t.get("title") or "") or "Untitled LoRA",
               "base_version_id": base, "base_name": names.get(base, ""),
               "image_count": int(t.get("mediaCount") or 0),
               "cover": "", "progress": None, "eta_left_ms": None, "reason": "",
               "model_id": "", "version_id": "", "visibility": "", "rebate": None,
               "trigger_words": ""}
        if done:
            row.update(status="done", model_id=str(t.get("modelId") or ""),
                       at=str(t.get("completedAt") or ""))
            row["published"] = bool(row["model_id"])
        else:
            st = str(t.get("status") or "")
            row.update(status=st, at=str(t.get("updatedAt") or ""), published=False)
            if st == "draft":
                row["step"] = "images" if row["image_count"] < 10 else "descriptions"
            elif st == "captioning":
                row["step"] = "describing"
            elif st == "captionReady":
                row["step"] = "descriptions"
        return row

    def _apply_detail(row, task):
        """Progress, the time left and PixAI's reason off a GraphQL TrainingTask."""
        extra = task.get("extra") or {}
        p = extra.get("progress")
        if isinstance(p, (int, float)) and row["status"] == "running":
            row["progress"] = max(0.0, min(100.0, float(p)))
            est = extra.get("estimatedTotalTime")
            if isinstance(est, (int, float)) and est > 0:
                row["eta_left_ms"] = int(est * (100.0 - row["progress"]) / 100.0)
        msg = ((task.get("outputs") or {}).get("message") or "")
        if row["status"] == "failed" and msg:
            row["reason"] = str(msg)[:300]
        ids = (task.get("parameters") or {}).get("mediaIds") or []
        if ids and not row.get("cover"):
            row["cover"] = _thumb_for(str(ids[0]))
        if (task.get("parameters") or {}).get("triggerWords"):
            row["trigger_words"] = str(task["parameters"]["triggerWords"])

    @app.route("/api/train/runs")
    @tier(LOGIN)
    def api_train_runs():
        """Runs (Session J 5c): advanced drafts, describe rounds, queued, training, failed and
        finished runs (PixAI's REST in-progress / completed lists) and Basic runs (the
        account's own LoRA list, where PixAI keeps them), one list, newest first, each with a
        status, PixAI's percentage while it trains, and the one action it offers. `running`
        is what the pinned strip shows. `?running=1` is the strip's light read (no finished
        runs). Read-only; answered from a 10-second cache so several open surfaces polling at
        once cost PixAI one read."""
        light = (request.args.get("running") or "") == "1"
        key = "light" if light else "full"
        hit = _runs_cache.get(key)
        if hit is not None and time.time() - hit[0] < 10.0:
            return jsonify(hit[1])
        errors = []
        try:
            core, session = _gen_session()
        except Exception as e:                          # noqa: BLE001
            return jsonify({"runs": [], "running": [], "error": str(e)[:200]}), 200
        cfg = _training.training_config()
        names = _base_names(cfg)
        rows, details = [], []
        try:
            for t in _training.list_training_in_progress(session, 100):
                rows.append(_run_row_advanced(t, names))
        except Exception as e:                          # noqa: BLE001
            errors.append("advanced runs: " + _redact_host_paths(str(e))[:120])
        loras = []
        try:
            loras = _training.list_my_trained_loras(session, pages=1 if light else 2)
        except Exception as e:                          # noqa: BLE001
            errors.append("your LoRAs: " + _redact_host_paths(str(e))[:120])
        by_model = {m["model_id"]: m for m in loras}
        # The Academy (loras_trained) counts runs PIXAI reports finished, by id: basic runs off
        # the account's LoRA list (every read), advanced ones off the finished list (the full
        # read). A failed run never lands here, so neither it nor its retry counts twice.
        finished = [str((m.get("task") or {}).get("id")) for m in loras
                    if (m.get("task") or {}).get("id")
                    and (m.get("task") or {}).get("trainingMode") != "advanced"
                    and str((m.get("task") or {}).get("status") or "") == "completed"]
        if not light:
            try:
                for t in _training.list_training_completed(session, 100):
                    if t.get("id"):
                        finished.append(str(t["id"]))
                    r = _run_row_advanced(t, names, done=True)
                    m = by_model.get(r["model_id"])
                    if m:
                        r["visibility"] = "private" if m["is_private"] else "public"
                        r["version_id"] = m["version_id"]
                        if m.get("task"):
                            _apply_detail(r, m["task"])
                    rows.append(r)
            except Exception as e:                      # noqa: BLE001
                errors.append("finished runs: " + _redact_host_paths(str(e))[:120])
        smap = {"completed": "done", "waiting": "waiting", "running": "running",
                "failed": "failed", "cancelled": "failed", "canceled": "failed"}
        for m in loras:
            t = m.get("task") or {}
            if not t.get("id") or t.get("trainingMode") == "advanced":
                continue                                 # advanced runs come from REST above
            st = smap.get(str(t.get("status") or ""), "")
            if not st or (light and st not in ("waiting", "running")):
                continue
            p = t.get("parameters") or {}
            r = {"id": str(t["id"]), "mode": "basic",
                 "title": str(p.get("title") or m["title"] or "Untitled LoRA"),
                 "base_version_id": str(p.get("baseModelId") or ""),
                 "base_name": names.get(str(p.get("baseModelId") or ""), ""),
                 "image_count": len(p.get("mediaIds") or []), "status": st,
                 "at": str(t.get("endAt") or t.get("updatedAt") or m["created_at"] or ""),
                 "cover": "", "progress": None, "eta_left_ms": None, "reason": "",
                 "model_id": m["model_id"], "version_id": m["version_id"],
                 "published": True, "rebate": None, "trigger_words": "",
                 "visibility": "private" if m["is_private"] else "public"}
            _apply_detail(r, t)
            rows.append(r)
        # PixAI's percentage for advanced runs that are training (the REST list has none) and
        # its reason for failed ones: a few GraphQL reads, newest first.
        for r in rows:
            if r["mode"] == "advanced" and r["status"] in ("running", "failed") \
                    and len(details) < (3 if light else 6):
                details.append(r)
        for r in details:
            try:
                _apply_detail(r, _training.training_task(session, r["id"]))
            except Exception:                           # noqa: BLE001
                pass
        guarded = train_guard.retried()
        for r in rows:
            g = guarded.get(r["id"])
            if g:
                r["retry"] = g
        # newest first, then (stable) the live ones on top: training, queued, describing
        order = {"running": 0, "waiting": 1, "captioning": 2}
        rows.sort(key=lambda r: r.get("at") or "", reverse=True)
        rows.sort(key=lambda r: order.get(r["status"], 3))
        running = [r for r in rows if r["status"] in ("running", "waiting")]
        payload = {"runs": rows if not light else running, "running": running,
                   "errors": errors}
        try:
            _telemetry.telem_set_add_many("trained_runs", finished, out_dir=out_dir)
        except Exception:                               # noqa: BLE001
            pass
        _runs_cache[key] = (time.time(), payload)
        return jsonify(payload)

    @app.route("/api/train/advanced/<task_id>")
    @tier(LOGIN)
    def api_train_advanced_get(task_id):
        """One advanced draft as its wizard needs it: the fixed set-up (name, trigger, category,
        base), the image set, each image's description (PixAI's machine text, and the owner's
        where he rewrote it), PixAI's describe quote while describing is possible, and its
        start quote once every image is described. READ-ONLY -- opening or continuing a draft
        writes nothing."""
        tid = str(task_id or "").strip()
        if not tid.isdigit():
            return jsonify({"error": "not a training task"}), 400
        try:
            core, session = _gen_session()
            t = _training.training_task(session, tid)
        except Exception as e:                          # noqa: BLE001
            return _train_refusal(e)
        if t.get("trainingMode") != "advanced":
            return jsonify({"error": "that run isn't an advanced one"}), 400
        cfg = _training.training_config()
        p = t.get("parameters") or {}
        ids = [str(x) for x in (p.get("mediaIds") or [])]
        status = str(t.get("status") or "")
        out = {"task": {"id": tid, "status": status, "title": str(p.get("title") or ""),
                        "trigger_words": str(p.get("triggerWords") or ""),
                        "category": str(p.get("category") or ""),
                        "base_version_id": str(p.get("baseModelId") or ""),
                        "base_name": _base_names(cfg).get(str(p.get("baseModelId") or ""), ""),
                        "media_ids": ids},
               "captions": {}, "caption_quote": None, "quote": None,
               "eta": _training.training_eta(_training.TRAIN_DEFAULT_OPTIONS["trainingSteps"]),
               "caption_max": _training.TRAIN_CAPTION_MAX, "errors": []}
        if status != "draft":
            try:
                items = _training.training_captions(session, tid)
            except Exception as e:                      # noqa: BLE001
                items = []
                out["errors"].append("descriptions: " + _redact_host_paths(str(e))[:120])
            from concurrent.futures import ThreadPoolExecutor

            def _texts(it):
                text = _training.fetch_caption_text(it["caption_url"])
                machine = text if it["source"] != "user" else \
                    _training.fetch_caption_text(it["machine_url"]) if it["machine_url"] else None
                return it["media_id"], {"source": it["source"], "text": text,
                                        "machine_text": machine}
            with ThreadPoolExecutor(max_workers=8) as ex:
                for mid, c in ex.map(_texts, items):
                    out["captions"][mid] = c
        if status in ("draft", "captionReady") and ids:
            try:
                out["caption_quote"] = _training.training_caption_quote(session, tid)
            except Exception as e:                      # noqa: BLE001
                out["errors"].append("describe price: " + _redact_host_paths(str(e))[:120])
        if status == "captionReady":
            try:
                out["quote"] = _training.training_quote(session, tid)
            except Exception as e:                      # noqa: BLE001
                out["errors"].append("price: " + _redact_host_paths(str(e))[:120])
        return jsonify(out)

    @app.route("/api/train/advanced/draft", methods=["POST"])
    @tier(LOGIN)
    def api_train_advanced_draft():
        """Create an advanced draft -- the user's deliberate "Next · creates a draft" and
        nothing else (Session J 3c). Free, but a write: CSRF, then READ_ONLY before any read,
        then PixAI's pause switch, then one createTrainingTask."""
        body, ok = _train_csrf_body()
        if not ok:
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        from moonglade import backup as core
        refused = _read_only_refusal(core, "create a LoRA training draft")
        if refused:
            return refused
        refused = _pause_refusal(core)
        if refused:
            return refused
        try:
            core_, session = _gen_session()
            d = _training.create_advanced_training_draft(
                session, str(body.get("base_model_id") or ""), str(body.get("title") or ""),
                str(body.get("trigger_words") or ""), str(body.get("category") or ""))
        except core.PixAIError as e:
            return (_train_refusal(e) if isinstance(e, core.PixAIRestError)
                    else (jsonify({"error": str(e)}), 400))
        except Exception as e:                          # noqa: BLE001
            return _train_refusal(e)
        _runs_dirty()
        return jsonify({"id": d["id"]})

    @app.route("/api/train/advanced/<task_id>/media", methods=["POST"])
    @tier(LOGIN)
    def api_train_advanced_media(task_id):
        """Replace the draft's image set (PUT media; free). The per-side image rule runs over
        this library's sizes first and refuses a failing image by name, as Basic does."""
        from moonglade.gallery import media_dims
        body, ok = _train_csrf_body()
        if not ok:
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        from moonglade import backup as core
        tid = str(task_id or "").strip()
        ids = body.get("media_ids") if isinstance(body.get("media_ids"), list) else None
        if not tid.isdigit() or ids is None:
            return jsonify({"error": "which run, and which images?"}), 400
        ids = [str(m) for m in ids if str(m).strip()]
        cfg = _training.training_config()
        rejected, _unchecked = _training.check_training_images(
            ids, media_dims(db_path, ids), cfg["image_constraints"])
        if rejected:
            return jsonify({"error": _training.describe_rejected_training_images(rejected),
                            "rejected_ids": [r["media_id"] for r in rejected]}), 400
        refused = _read_only_refusal(core, "change a LoRA training set")
        if refused:
            return refused
        lk = _train_lock("task:" + tid)
        if not lk.acquire(timeout=15):
            return jsonify({"error": _BUSY}), 409
        try:
            core_, session = _gen_session()
            saved = _training.replace_training_media(session, tid, ids)
        except Exception as e:                          # noqa: BLE001
            return _train_refusal(e)
        finally:
            lk.release()
        _runs_dirty()
        return jsonify({"media_ids": saved})

    @app.route("/api/train/advanced/<task_id>/captions/<media_id>", methods=["POST"])
    @tier(LOGIN)
    def api_train_advanced_caption_save(task_id, media_id):
        """Save the owner's own description for one image (PUT; free; 1 to 1,000 characters;
        only once PixAI has described it)."""
        body, ok = _train_csrf_body()
        if not ok:
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        from moonglade import backup as core
        tid, mid = str(task_id or "").strip(), str(media_id or "").strip()
        text = str(body.get("text") or "").strip()
        if not tid.isdigit() or not mid.isdigit():
            return jsonify({"error": "which image?"}), 400
        if not text or len(text) > _training.TRAIN_CAPTION_MAX:
            return jsonify({"error": "A description is 1 to %s characters."
                                     % "{:,}".format(_training.TRAIN_CAPTION_MAX)}), 400
        refused = _read_only_refusal(core, "edit a LoRA training description")
        if refused:
            return refused
        lk = _train_lock("task:" + tid)
        if not lk.acquire(timeout=15):
            return jsonify({"error": _BUSY}), 409
        try:
            core_, session = _gen_session()
            saved = _training.save_training_caption(session, tid, mid, text)
        except Exception as e:                          # noqa: BLE001
            return _train_refusal(e)
        finally:
            lk.release()
        return jsonify({"text": saved})

    @app.route("/api/train/advanced/<task_id>/caption", methods=["POST"])
    @tier(LOGIN)
    def api_train_advanced_caption(task_id):
        """PAID: PixAI describes the set's undescribed images (Session J 3c, corrected by the
        2026-09-28 capture: this is the only way in -- PixAI has no write-your-own path before
        it). Preview-first: without `confirm` it only quotes (GET caption-price: the count
        and the total, PixAI's own number, never the config's stale unit price). The confirm:
        CSRF -> READ_ONLY -> this run's lock (refuses when held) -> pause switch -> the run
        re-read (a draft or in review, at least 10 images) -> a FRESH quote -> nothing left
        to describe refuses -> `accept_credit_cost` must be the fresh total, as a number ->
        one POST caption."""
        body, ok = _train_csrf_body()
        if not ok:
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        from moonglade import backup as core
        tid = str(task_id or "").strip()
        if not tid.isdigit():
            return jsonify({"error": "not a training task"}), 400
        confirming = bool(body.get("confirm"))
        if confirming:
            refused = _read_only_refusal(core, "describe LoRA training images")
            if refused:
                return refused
        lk = _train_lock("task:" + tid)
        if not lk.acquire(blocking=False):
            return jsonify({"error": _BUSY}), 409
        try:
            if confirming:
                refused = _pause_refusal(core)
                if refused:
                    return refused
            try:
                core_, session = _gen_session()
                t = _training.training_task(session, tid)
            except Exception as e:                      # noqa: BLE001
                return _train_refusal(e)
            st = str(t.get("status") or "")
            n = len((t.get("parameters") or {}).get("mediaIds") or [])
            if confirming and train_guard.paid_blocked("caption", tid, st):
                return jsonify({"error": _PAID_MAYBE_REFUSAL % "describing these images",
                                "maybe_started": True}), 409
            if t.get("trainingMode") != "advanced" or st not in ("draft", "captionReady"):
                return jsonify({"error": "PixAI is %s this run, so it can't be described "
                                         "now. Nothing was sent." %
                                         ("already describing" if st == "captioning"
                                          else "past that step on")}), 409
            if n < _training.TRAIN_MIN_IMAGES:
                return jsonify({"error": "Add at least %d more image%s first. Nothing was sent."
                                         % (_training.TRAIN_MIN_IMAGES - n,
                                            "" if _training.TRAIN_MIN_IMAGES - n == 1 else "s")}), 400
            try:
                q = _training.training_caption_quote(session, tid)
            except Exception as e:                      # noqa: BLE001
                return _train_refusal(e)
            per = (q["total_price"] // q["image_count"]) if q["image_count"] else None
            if not confirming:
                return jsonify({"preview": True, "image_count": q["image_count"],
                                "total_price": q["total_price"], "per_image": per})
            if q["image_count"] <= 0:
                return jsonify({"error": "Every image is described already. Nothing was "
                                         "sent."}), 409
            accepted = body.get("accept_credit_cost")
            if not _exact_amount(accepted, q["total_price"]):
                return _amount_refusal(accepted, q["total_price"], "Describing these images")
            train_guard.paid_arm("caption", tid, st)
            try:
                status = _training.start_training_captions(session, tid)
            except Exception as e:                      # noqa: BLE001
                if _gen_road.definite_refusal(e, "training"):
                    train_guard.paid_resolve("caption", tid, "refused")
                    return _train_refusal(e)
                train_guard.paid_resolve("caption", tid, "ambiguous")
                _runs_dirty()
                return jsonify({"error": "PixAI didn't answer clearly, so describing these "
                                         "images may have started. Check Runs before "
                                         "describing again.",
                                "maybe_started": True}), 502
            train_guard.paid_resolve("caption", tid, "done")
        finally:
            lk.release()
        _runs_dirty()
        return jsonify({"started": True, "status": status or "captioning",
                        "charged": q["total_price"], "image_count": q["image_count"]})

    @app.route("/api/train/advanced/<task_id>/submit", methods=["POST"])
    @tier(LOGIN)
    def api_train_advanced_submit(task_id):
        """PAID: start an advanced run (Session J 3c, Parameters -> Start). PixAI's own default
        options are sent verbatim (core.TRAIN_DEFAULT_OPTIONS) -- its page locks them, and its
        quote takes no length, so this route takes no parameters from the client (spend review,
        finding 3). No free card rides it, as on PixAI's page. Preview quotes GET price; the
        confirm: CSRF -> READ_ONLY -> the run's lock (refuses when held) -> pause switch ->
        the run re-read (in review, every image described) -> a FRESH quote ->
        `accept_credit_cost` equal to it (a quote of 0 needs none) -> one POST submit. The
        member quota is read before and after, so the answer can say if PixAI used one of the
        member's free trainings (whether it does for an advanced run is not known)."""
        body, ok = _train_csrf_body()
        if not ok:
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        from moonglade import backup as core
        tid = str(task_id or "").strip()
        if not tid.isdigit():
            return jsonify({"error": "not a training task"}), 400
        confirming = bool(body.get("confirm"))
        if confirming:
            refused = _read_only_refusal(core, "start a LoRA training run")
            if refused:
                return refused
        lk = _train_lock("task:" + tid)
        if not lk.acquire(blocking=False):
            return jsonify({"error": _BUSY}), 409
        try:
            if confirming:
                refused = _pause_refusal(core)
                if refused:
                    return refused
            try:
                core_, session = _gen_session()
                t = _training.training_task(session, tid)
                if confirming and train_guard.paid_blocked("submit", tid,
                                                           str(t.get("status") or "")):
                    return jsonify({"error": _PAID_MAYBE_REFUSAL % "this run",
                                    "maybe_started": True}), 409
                if t.get("trainingMode") != "advanced" or t.get("status") != "captionReady":
                    return jsonify({"error": "This run isn't waiting to start (PixAI says: %s). "
                                             "Nothing was sent." % (t.get("status") or "?")}), 409
                ids = [str(x) for x in ((t.get("parameters") or {}).get("mediaIds") or [])]
                described = {c["media_id"] for c in _training.training_captions(session, tid)}
                left = [m for m in ids if m not in described]
                if left:
                    return jsonify({"error": "Describe the %d remaining image%s first. Nothing "
                                             "was sent." % (len(left),
                                                            "" if len(left) == 1 else "s"),
                                    "undescribed": left}), 409
                price = _training.training_quote(session, tid)
            except Exception as e:                      # noqa: BLE001
                return _train_refusal(e)
            eta = _training.training_eta(_training.TRAIN_DEFAULT_OPTIONS["trainingSteps"])
            if not confirming:
                return jsonify({"preview": True, "price": price, "eta": eta,
                                "image_count": len(ids), "is_free": price == 0})
            accepted = body.get("accept_credit_cost")
            if price > 0 and not _exact_amount(accepted, price):
                return _amount_refusal(accepted, price, "This training")
            before = _training.training_free_quota(session)
            train_guard.paid_arm("submit", tid, t.get("status"))
            try:
                status = _training.submit_advanced_training(session, tid)
            except Exception as e:                      # noqa: BLE001
                if _gen_road.definite_refusal(e, "training"):
                    train_guard.paid_resolve("submit", tid, "refused")
                    return _train_refusal(e)
                train_guard.paid_resolve("submit", tid, "ambiguous")
                _runs_dirty()
                return jsonify({"error": "PixAI didn't answer clearly, so this run may have "
                                         "started. Check Runs before starting it again.",
                                "maybe_started": True}), 502
            train_guard.paid_resolve("submit", tid, "done")
            after = _training.training_free_quota(session)
        finally:
            lk.release()
        _runs_dirty()
        return jsonify({"submitted": True, "status": status or "waiting", "price": price,
                        "used_free_training": bool(before > after)})

    @app.route("/api/train/runs/<task_id>/retry", methods=["POST"])
    @tier(LOGIN)
    def api_train_retry(task_id):
        """PAID, A NEW RUN: retry a failed advanced run (same set, same descriptions; charged
        again at PixAI's current price, its GET price quote). PixAI leaves the failed run as
        it is and would take a second retry, so the retry guard (on disk) is checked first and
        armed right before the POST; only a definite refusal disarms it. No free card rides
        it, as on PixAI's page."""
        body, ok = _train_csrf_body()
        if not ok:
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        from moonglade import backup as core
        tid = str(task_id or "").strip()
        if not tid.isdigit():
            return jsonify({"error": "not a training task"}), 400
        confirming = bool(body.get("confirm"))
        if confirming:
            refused = _read_only_refusal(core, "retry a LoRA training run")
            if refused:
                return refused
        lk = _train_lock("task:" + tid)
        if not lk.acquire(blocking=False):
            return jsonify({"error": _BUSY}), 409
        try:
            g = train_guard.retry_state(tid)
            if g:
                return jsonify({"error": ("This run was retried already -- the new run is in "
                                          "Runs. Nothing was sent." if g["state"] == "done" else
                                          "A retry of this run may have started: PixAI didn't "
                                          "answer clearly. Check Runs. Nothing was sent."),
                                "retry": g}), 409
            if confirming:
                refused = _pause_refusal(core)
                if refused:
                    return refused
            try:
                core_, session = _gen_session()
                t = _training.training_task(session, tid)
                if t.get("trainingMode") != "advanced" or t.get("status") != "failed":
                    return jsonify({"error": "Only a failed advanced run can be retried. "
                                             "Nothing was sent."}), 409
                price = _training.training_quote(session, tid)
            except Exception as e:                      # noqa: BLE001
                return _train_refusal(e)
            if not confirming:
                return jsonify({"preview": True, "price": price, "is_free": price == 0,
                                "eta": _training.training_eta(
                                    _training.TRAIN_DEFAULT_OPTIONS["trainingSteps"])})
            accepted = body.get("accept_credit_cost")
            if price > 0 and not _exact_amount(accepted, price):
                return _amount_refusal(accepted, price, "Retrying this run")
            train_guard.retry_arm(tid)
            try:
                res = _training.retry_training(session, tid)
            except Exception as e:                      # noqa: BLE001
                if _gen_road.definite_refusal(e, "training"):
                    train_guard.retry_resolve(tid, "refused")
                    return _train_refusal(e)
                train_guard.retry_resolve(tid, "ambiguous")
                _runs_dirty()
                return jsonify({"error": "PixAI didn't answer clearly, so the retry may have "
                                         "started. Check Runs before trying again.",
                                "maybe_started": True}), 502
            train_guard.retry_resolve(tid, "done", res.get("id") or "")
        finally:
            lk.release()
        _runs_dirty()
        return jsonify({"retried": True, "id": res.get("id") or "", "price": price})

    _PUBLISH_TICKS = {"private": ["no_delete"], "public": ["no_delete", "no_private"]}

    @app.route("/api/train/runs/<task_id>/publish", methods=["POST"])
    @tier(LOGIN)
    def api_train_publish(task_id):
        """IRREVERSIBLE: publish a finished advanced run as a LoRA (Session J 4a). The request
        must carry every consequence the sheet ticked, exactly: private ["no_delete"], public
        ["no_delete", "no_private"]; rebates only when public. CSRF -> READ_ONLY -> the run's
        lock -> the finished list re-read (finished, not yet published) -> one POST publish."""
        body, ok = _train_csrf_body()
        if not ok:
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        from moonglade import backup as core
        tid = str(task_id or "").strip()
        vis = str(body.get("visibility") or "")
        rebate = "join" if body.get("rebate") in (True, "join") else "decline"
        acks = body.get("acknowledged") if isinstance(body.get("acknowledged"), list) else []
        if not tid.isdigit() or vis not in _PUBLISH_TICKS:
            return jsonify({"error": "publish it private or public"}), 400
        if rebate == "join" and vis != "public":
            return jsonify({"error": "Only a public LoRA can join rebates. Nothing was "
                                     "sent."}), 400
        if sorted(str(a) for a in acks) != sorted(_PUBLISH_TICKS[vis]):
            return jsonify({"error": "Tick every line under \"This can't be undone\" to "
                                     "publish. Nothing was sent."}), 400
        refused = _read_only_refusal(core, "publish a trained LoRA")
        if refused:
            return refused
        lk = _train_lock("task:" + tid)
        if not lk.acquire(blocking=False):
            return jsonify({"error": _BUSY}), 409
        try:
            try:
                core_, session = _gen_session()
                done = {str(t.get("id")): t for t in _training.list_training_completed(session, 100)}
            except Exception as e:                      # noqa: BLE001
                return _train_refusal(e)
            t = done.get(tid)
            if not t:
                return jsonify({"error": "That run hasn't finished training. Nothing was "
                                         "sent."}), 409
            if t.get("modelId"):
                return jsonify({"error": "That run is published already. Nothing was "
                                         "sent."}), 409
            try:
                res = _training.publish_training(session, tid, vis, rebate)
            except Exception as e:                      # noqa: BLE001
                return _train_refusal(e)
        finally:
            lk.release()
        _runs_dirty()
        return jsonify({"published": True, "visibility": vis, "rebate": rebate == "join",
                        **res})

    @app.route("/api/train/models/<model_id>/rebates")
    @tier(LOGIN)
    def api_train_model_rebates(model_id):
        """Whether one of your LoRAs can join rebates (PixAI's check). Read-only."""
        mid = str(model_id or "").strip()
        if not mid.isdigit():
            return jsonify({"offered": False, "joined": False, "can_join": False}), 400
        try:
            core, session = _gen_session()
            return jsonify(core.lora_rebate_eligibility(session, mid))
        except Exception:                               # noqa: BLE001
            return jsonify({"offered": False, "joined": False, "can_join": False})

    @app.route("/api/train/models/<model_id>/make-public", methods=["POST"])
    @tier(LOGIN)
    def api_train_make_public(model_id):
        """IRREVERSIBLE: a private LoRA of yours goes public (Session J 4a, "Private -> public
        later": the same sheet, Public fixed, one tick), optionally joining rebates. Exactly
        PixAI's own two calls. CSRF -> the one tick -> READ_ONLY -> the model's lock -> the
        model re-read (yours, private) -> upsertGenerationModel {isPrivate: false} -> only
        when asked and PixAI offers it, the rebate PATCH."""
        body, ok = _train_csrf_body()
        if not ok:
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
        from moonglade import backup as core
        mid = str(model_id or "").strip()
        acks = body.get("acknowledged") if isinstance(body.get("acknowledged"), list) else []
        join = body.get("rebate") in (True, "join")
        if not mid.isdigit():
            return jsonify({"error": "which LoRA?"}), 400
        if [str(a) for a in acks] != ["no_private"]:
            return jsonify({"error": "Tick \"It can't go back to private\" to go on. Nothing "
                                     "was sent."}), 400
        refused = _read_only_refusal(core, "make a LoRA public")
        if refused:
            return refused
        lk = _train_lock("model:" + mid)
        if not lk.acquire(blocking=False):
            return jsonify({"error": _BUSY}), 409
        try:
            try:
                core_, session = _gen_session()
                m = _models.generation_model_brief(session, mid)
            except Exception as e:                      # noqa: BLE001
                return _train_refusal(e)
            me = str(getattr(session, "user_id", "") or core.USER_ID or "")
            if me and m["author_id"] and m["author_id"] != me:
                return jsonify({"error": "That LoRA isn't yours. Nothing was sent."}), 403
            if not m["is_private"]:
                return jsonify({"error": "That LoRA is public already. Nothing was sent."}), 409
            try:
                core.make_model_public(session, mid)
            except Exception as e:                      # noqa: BLE001
                return _train_refusal(e)
            joined, note = False, ""
            if join:
                try:
                    el = core.lora_rebate_eligibility(session, mid)
                    if el["can_join"]:
                        core.join_lora_rebates(session, mid)
                        joined = True
                    else:
                        note = "PixAI isn't offering rebates for it right now."
                except Exception:                       # noqa: BLE001
                    note = ("It is public, but joining rebates didn't go through; you can "
                            "try again from its run.")
        finally:
            lk.release()
        _runs_dirty()
        return jsonify({"public": True, "rebate": joined, "note": note})

    # -- provided to ctx (split_move) --
    # -- end --
