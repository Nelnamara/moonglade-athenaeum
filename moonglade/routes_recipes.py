"""moonglade/routes_recipes.py -- PixAI's recipe market over moonglade.recipes (meta, market,
capability, batch, recent, Mine, style code, from-image, Sets, a recipe's page, its artworks and
tasks, and the creator's writes: publish, update, transition, set create and toggle) and the model
pickers' Saved tab (the sets, a model's state, the removed models, save, tick, remove, new set).

Split out of gallery.create_app (split phase 4, 2026-11-20), verbatim: create_app calls
register(app, ctx) once, before the library routes, which read _recipes, _recipe_user_id and
_read_only_flag (the model search's Saved source). Names the block reads from create_app's setup
and the front door (the CSRF check, the PixAI session, the host-path redactor) come in through ctx
(the bound-from-ctx lines below), so every closure on both sides holds the one same object.
gallery's own names are imported inside the function that reads them, at call time, so a test's
patch of moonglade.gallery still reaches the route.
"""
import secrets

from flask import jsonify, request, session

from moonglade import mirror as _mirror
from moonglade import models as _models
from moonglade import pixai_client as _pixai_client
from moonglade import task_reads as _task_reads


def register(app, ctx):
    from moonglade.web_tiers import LOGIN, tier
    # -- bound from ctx (split_move) --
    _check_csrf = ctx._check_csrf
    _gen_session = ctx._gen_session
    _redact_host_paths = ctx._redact_host_paths
    db_path = ctx.db_path
    # -- end --

    # --- Recipes (Session K + H3/H8/H10; lane w2-recipes) --------------------------------
    # PixAI's recipe market, a recipe's page, Mine, Sets and the creator's writes, over
    # moonglade.recipes (its module docstring has the whole contract). Reads are LOGIN, like
    # every other catalog-of-PixAI read here. Every write is a deliberate click: LOGIN,
    # explicit-token CSRF (_check_csrf), READ_ONLY refused inside moonglade.recipes before
    # its first network call, one attempt. Nothing here writes when a surface opens, and
    # GET /v2/recipes/draft (which CREATES a draft) is never called -- the creator's drafts
    # are the account's own prefs until the user publishes.

    def _recipes():
        from moonglade import recipes as moonglade_recipes
        return moonglade_recipes

    def _recipe_fail(e, **extra):
        """A read or write that failed, as the house's {error} answer (HTTP 200: the body
        is the answer, api.js's one rule)."""
        out = {"error": _redact_host_paths(str(e))[:240]}
        out.update(extra)
        return jsonify(out), 200

    def _recipe_user_id(core, gsession):
        uid = str(_pixai_client._client_of(gsession).user_id or "")
        if not uid:
            uid = core.resolve_user_id(gsession)
        return uid

    @app.route("/api/recipes/meta")
    @tier(LOGIN)
    def api_recipes_meta():
        """What every recipe surface needs once: the live category and model-type lists,
        the CSRF token for its writes, and the account's PixAI id (Mine and Sets)."""
        session.setdefault("csrf", secrets.token_hex(16))
        rec = _recipes()
        try:
            core, gsession = _gen_session()
        except Exception as e:                                   # noqa: BLE001
            return jsonify({"categories": list(rec.CATEGORIES),
                            "model_types": list(rec.MODEL_TYPES),
                            "csrf": session["csrf"], "user_id": "",
                            "max_recipes": rec.MAX_RECIPES,
                            "error": _redact_host_paths(str(e))[:200]})
        try:
            uid = _recipe_user_id(core, gsession)
        except Exception:                                        # noqa: BLE001
            uid = ""
        return jsonify({"categories": rec.categories(gsession),
                        "model_types": rec.model_types(gsession),
                        "csrf": session["csrf"], "user_id": uid,
                        "max_recipes": rec.MAX_RECIPES})

    @app.route("/api/recipes/market")
    @tier(LOGIN)
    def api_recipes_market():
        """One page of the market: ?sort=trending|most-liked|most-used|latest, page,
        page_size, category, model_type, model_id, q (search; newest first)."""
        a = request.args
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().market(
                gsession, sort=a.get("sort", "trending"), page=a.get("page", 1),
                page_size=a.get("page_size", 24), category=a.get("category", ""),
                model_type=a.get("model_type", ""), model_id=a.get("model_id", ""),
                query=a.get("q", "")))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, items=[])

    @app.route("/api/recipes/capability")
    @tier(LOGIN)
    def api_recipes_capability():
        """Which ingredient kinds a model takes, and how many of each (?model_type= or
        ?model_id=). Read live; the creator never guesses."""
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().capability(
                gsession, request.args.get("model_type", ""),
                request.args.get("model_id", "")))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, slots=[])

    @app.route("/api/recipes/batch")
    @tier(LOGIN)
    def api_recipes_batch():
        """Recipe cards by id (?ids=a,b,c, up to 20) -- the dock's chips after a reload."""
        ids = [i for i in (request.args.get("ids") or "").split(",") if i.strip()]
        try:
            core, gsession = _gen_session()
            return jsonify({"items": _recipes().batch(gsession, ids)})
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, items=[])

    @app.route("/api/recipes/recent")
    @tier(LOGIN)
    def api_recipes_recent():
        """The picker's History tab: recipes this account used most recently."""
        try:
            core, gsession = _gen_session()
            return jsonify({"items": _recipes().recently_used(
                gsession, request.args.get("limit", 30), request.args.get("model_type", ""))})
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, items=[])

    @app.route("/api/recipes/mine")
    @tier(LOGIN)
    def api_recipes_mine():
        """Mine: this account's recipes, archived and in-review ones included (PixAI never
        lists drafts; the app's own drafts live in the account prefs)."""
        a = request.args
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().user_recipes(
                gsession, _recipe_user_id(core, gsession), sort=a.get("sort", "latest"),
                cursor=a.get("cursor", ""), limit=a.get("limit", 30),
                model_type=a.get("model_type", "")))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, items=[])

    @app.route("/api/recipes/style-code")
    @tier(LOGIN)
    def api_recipes_style_code():
        """A legacy style code -> the recipe that replaced it (?code=&version_id=), or
        {recipe: null} for "No recipe replaces this code"."""
        try:
            core, gsession = _gen_session()
            return jsonify({"recipe": _recipes().by_style_code(
                gsession, request.args.get("code", ""), request.args.get("version_id", ""))})
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, recipe=None)

    @app.route("/api/recipes/from-image")
    @tier(LOGIN)
    def api_recipes_from_image():
        """⁂ Make a recipe (K decision 4). ?media_id=X&check=1 answers only whether the
        picture's model takes recipes (one cached /features read per model version); without
        `check`, the creator's step-2 prefill: the model, the task's LoRAs (version, weight,
        trigger words), the prompt, and the picture itself. The category is never guessed.
        A picture this library has no row for is refused (the route runs on the owner's
        credentials; the /api/task-params rule)."""
        from moonglade.gallery import get_row
        mid = str(request.args.get("media_id") or "").strip()
        row = get_row(db_path, mid) if mid else None
        if not row:
            return jsonify({"error": "no such picture in this library", "capable": False}), 404
        if str(row.get("is_video") or "") == "1":
            return jsonify({"capable": False, "why": "a video"})
        vid = str(row.get("model_id") or "").strip()
        if not vid:
            return jsonify({"capable": False, "why": "this picture's model isn't recorded"})
        rec = _recipes()
        try:
            core, gsession = _gen_session()
            feats = _models._model_features(gsession, vid)
            mtype = (feats or {}).get("model_type") or ""
            capable = bool(mtype) and mtype in rec.model_types(gsession)
            out = {"capable": capable, "model_type": mtype, "version_id": vid,
                   "model_title": str(row.get("model_name") or "")}
            if request.args.get("check") or not capable:
                return jsonify(out)
            base = _models.resolve_model_base_id(gsession, vid)
            prompt = str(row.get("prompt_full") or row.get("prompt_preview") or "")
            loras, unresolved = [], 0
            tid = str(row.get("task_id") or "").strip()
            task = _task_reads.task_detail_gql(gsession, tid, retries=1) if tid else None
            params = (task or {}).get("parameters") or {}
            if isinstance(params.get("prompts"), str) and params.get("prompts").strip():
                prompt = params["prompts"]
            lmap = params.get("lora") if isinstance(params.get("lora"), dict) else {}
            for lvid, weight in lmap.items():
                try:
                    w = float(weight)
                except (TypeError, ValueError):
                    unresolved += 1
                    continue
                lbase = _models.resolve_model_base_id(gsession, str(lvid))
                rows = _models.list_model_versions(gsession, lbase) if lbase else []
                vrow = next((r for r in rows if r.get("version_id") == str(lvid)), None) or {}
                loras.append({"version_id": str(lvid), "model_id": lbase, "weight": w,
                              "title": str(_models.model_name_gql(gsession, str(lvid)) or "")
                              or str(lvid),
                              "trigger_words": str(vrow.get("trigger_words") or "")})
            out.update({"model_id": base, "prompt": prompt, "loras": loras,
                        "unresolved": unresolved + (0 if task or not tid else 1),
                        "media_id": mid, "thumb": "/thumbs/{}.jpg".format(mid)})
            return jsonify(out)
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, capable=False)

    @app.route("/api/recipes/sets")
    @tier(LOGIN)
    def api_recipes_sets():
        """The Sets tab: this account's recipe sets (PixAI's collections of recipes)."""
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().sets_list(gsession, _recipe_user_id(core, gsession),
                                                cursor=request.args.get("cursor", "")))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, sets=[])

    @app.route("/api/recipes/sets/for/<recipe_id>")
    @tier(LOGIN)
    def api_recipes_sets_for(recipe_id):
        """"Save to a recipe set": every set, each with whether it holds this recipe."""
        try:
            core, gsession = _gen_session()
            return jsonify({"sets": _recipes().sets_for(gsession, recipe_id)})
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, sets=[])

    @app.route("/api/recipes/sets/<set_id>/items")
    @tier(LOGIN)
    def api_recipes_set_items(set_id):
        """One set's recipes."""
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().set_items(gsession, set_id,
                                                request.args.get("cursor", "")))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, items=[])

    @app.route("/api/recipes/<recipe_id>")
    @tier(LOGIN)
    def api_recipes_detail(recipe_id):
        """One recipe (the owner's view carries its slots; everyone else's, kinds only)."""
        try:
            core, gsession = _gen_session()
            return jsonify({"recipe": _recipes().detail(gsession, recipe_id)})
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, recipe=None)

    @app.route("/api/recipes/<recipe_id>/artworks")
    @tier(LOGIN)
    def api_recipes_artworks(recipe_id):
        """"Made with it" on a recipe's page (?sort=latest|most-liked, page)."""
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().artworks(
                gsession, recipe_id, request.args.get("sort", "latest"),
                request.args.get("page", 1), request.args.get("page_size", 12)))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, items=[])

    @app.route("/api/recipes/<recipe_id>/tasks")
    @tier(LOGIN)
    def api_recipes_tasks(recipe_id):
        """This account's generations with a recipe (?usage=test|normal)."""
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().tasks(
                gsession, recipe_id, request.args.get("usage", ""),
                request.args.get("page", 1), request.args.get("page_size", 12)))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, items=[])

    def _recipe_write_body():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return None, (jsonify({"error": "Expected a JSON object."}), 400)
        if not _check_csrf(body):
            return None, (jsonify({"error": "Your session expired. Reload the page and "
                                            "try again."}), 400)
        return body, None

    @app.route("/api/recipes/publish", methods=["POST"])
    @tier(LOGIN)
    def api_recipes_publish():
        """Publish the creator's draft (K decision 5): {csrf, draft, recipe_id?}. Creates
        the recipe on PixAI when there is no id yet (PixAI keeps ONE unfinished recipe per
        account and discards any other -- step 3 says so before this click), saves the full
        body, and moves it draft -> test -> published. Answers {recipe} or {error,
        recipe_id} -- the id of a recipe the create made before a later step failed, which
        the client keeps so the next attempt updates it rather than making another."""
        body, bad = _recipe_write_body()
        if bad:
            return bad
        rec = _recipes()
        try:
            core, gsession = _gen_session()
            return jsonify({"recipe": rec.publish(gsession, body.get("draft"),
                                                  body.get("recipe_id") or "")})
        except rec.RecipeWriteError as e:
            return _recipe_fail(e, code=e.code, recipe_id=e.recipe_id)
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e)

    @app.route("/api/recipes/update", methods=["POST"])
    @tier(LOGIN)
    def api_recipes_update():
        """Save an edit to an existing recipe (full replace): {csrf, recipe_id, draft,
        version}. `version` is the recipe's version when the creator opened it; a recipe
        changed on PixAI since is refused, not overwritten. Answers the recipe as PixAI
        reads it afterwards -- status `test` is "in review"."""
        body, bad = _recipe_write_body()
        if bad:
            return bad
        rec = _recipes()
        try:
            core, gsession = _gen_session()
            return jsonify({"recipe": rec.update(gsession, body.get("recipe_id"),
                                                 body.get("draft"), body.get("version"))})
        except rec.RecipeWriteError as e:
            return _recipe_fail(e, code=e.code)
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e)

    @app.route("/api/recipes/transition", methods=["POST"])
    @tier(LOGIN)
    def api_recipes_transition():
        """Archive or unarchive (Mine): {csrf, recipe_id, to: archived|published}."""
        body, bad = _recipe_write_body()
        if bad:
            return bad
        rec = _recipes()
        try:
            core, gsession = _gen_session()
            return jsonify({"recipe": rec.transition(gsession, body.get("recipe_id"),
                                                     str(body.get("to") or ""))})
        except rec.RecipeWriteError as e:
            return _recipe_fail(e, code=e.code)
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e)

    @app.route("/api/recipes/sets/create", methods=["POST"])
    @tier(LOGIN)
    def api_recipes_set_create():
        """+ New set: {csrf, title}. A private collection of recipes on PixAI."""
        body, bad = _recipe_write_body()
        if bad:
            return bad
        try:
            core, gsession = _gen_session()
            return jsonify({"set": _recipes().set_create(gsession, body.get("title"))})
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e)

    @app.route("/api/recipes/sets/toggle", methods=["POST"])
    @tier(LOGIN)
    def api_recipes_set_toggle():
        """A tick in "Save to a recipe set": {csrf, set_id, recipe_id, on, item_id?}.
        Applies at once (K decision 7: no Save button)."""
        body, bad = _recipe_write_body()
        if bad:
            return bad
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().set_toggle(gsession, body.get("set_id"),
                                                 body.get("recipe_id"), bool(body.get("on")),
                                                 body.get("item_id") or ""))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e)

    # ---- The model pickers' Saved tab (Session S): PixAI's model collections ----------------
    # Reads: the rail, a model's state (the "Keep this model" menu opens on it), the removed
    # models. Writes: ⊕ Save, a menu tick, taking a removed model's entry out, + New set --
    # each CSRF-checked here and READ_ONLY-checked first in moonglade.recipes, one attempt and
    # a read-back that decides the answer. A page of a set rides /api/model-search?src=saved.

    def _saved_kind():
        return "lora" if (request.args.get("kind") or "").lower() == "lora" else "base"

    def _read_only_flag(core):
        return bool(core.READ_ONLY or core._read_only_now())

    @app.route("/api/model-saved/sets")
    @tier(LOGIN)
    def api_model_saved_sets():
        """The rail: Saved first, then named sets A-Z, counting this picker's kind (?kind=base|
        lora), plus how many saved models PixAI no longer has, and whether READ_ONLY is on."""
        try:
            core, gsession = _gen_session()
            out = _recipes().model_sets(gsession, _recipe_user_id(core, gsession), _saved_kind())
            out["read_only"] = _read_only_flag(core)
            return jsonify(out)
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, sets=[])

    @app.route("/api/model-saved/state")
    @tier(LOGIN)
    def api_model_saved_state():
        """One model's place in the account's sets (?model_id=): the selector, a read only."""
        try:
            core, gsession = _gen_session()
            out = _recipes().model_state(gsession, request.args.get("model_id", ""))
            out["read_only"] = _read_only_flag(core)
            return jsonify(out)
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, sets=[])

    @app.route("/api/model-saved/old")
    @tier(LOGIN)
    def api_model_saved_old():
        """S2c: the old bookmarks Saved does not hold (?kind=base|lora), tagged "old". The old
        list is read as the Bookmarked tab read it (the website's identity)."""
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().model_old_bookmarks(
                gsession, _mirror.present_as_web(gsession), _recipe_user_id(core, gsession),
                _saved_kind()))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, rows=[])

    @app.route("/api/model-saved/unavailable")
    @tier(LOGIN)
    def api_model_saved_unavailable():
        """"K not available ▸": the removed models in Saved (?expect=K stops the walk early)."""
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().model_unavailable(
                gsession, _recipe_user_id(core, gsession), request.args.get("expect", 0)))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e, items=[])

    @app.route("/api/model-saved/save", methods=["POST"])
    @tier(LOGIN)
    def api_model_saved_save():
        """⊕ Save: {csrf, model_id} -> Saved on PixAI, then the read-back's answer."""
        body, bad = _recipe_write_body()
        if bad:
            return bad
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().model_save(gsession, _recipe_user_id(core, gsession),
                                                 body.get("model_id")))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e)

    @app.route("/api/model-saved/tick", methods=["POST"])
    @tier(LOGIN)
    def api_model_saved_tick():
        """A PixAI tick in "Keep this model": {csrf, set_id, model_id, on, item_id?}."""
        body, bad = _recipe_write_body()
        if bad:
            return bad
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().model_tick(gsession, body.get("set_id"),
                                                 body.get("model_id"), bool(body.get("on")),
                                                 body.get("item_id") or ""))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e)

    @app.route("/api/model-saved/remove", methods=["POST"])
    @tier(LOGIN)
    def api_model_saved_remove():
        """Take a removed model's entry out of Saved: {csrf, item_id}."""
        body, bad = _recipe_write_body()
        if bad:
            return bad
        try:
            core, gsession = _gen_session()
            return jsonify(_recipes().model_remove_gone(gsession, _recipe_user_id(core, gsession),
                                                        body.get("item_id")))
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e)

    @app.route("/api/model-saved/sets/create", methods=["POST"])
    @tier(LOGIN)
    def api_model_saved_set_create():
        """+ New set in "Keep this model": {csrf, title}. A private model set on PixAI."""
        body, bad = _recipe_write_body()
        if bad:
            return bad
        try:
            core, gsession = _gen_session()
            made = _recipes().set_create(gsession, body.get("title"), content_type="model")
            return jsonify({"set": made})
        except Exception as e:                                   # noqa: BLE001
            return _recipe_fail(e)

    # -- provided to ctx (split_move) --
    ctx._read_only_flag = _read_only_flag
    ctx._recipe_user_id = _recipe_user_id
    ctx._recipes = _recipes
    # -- end --
