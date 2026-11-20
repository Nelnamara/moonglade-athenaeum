"""
moonglade/training.py
=====================
LoRA training: the tables and the live config readers (`training_config` and its parsers), the
free quota and the training card, the pause switch, the trigger-word and image rules, the Basic
submit (`submit_training`), and Advanced (the goals and types, the task and LoRA reads, the
caption quote and captions, the draft, media, captions, submit, retry and publish writers, the
error words). Moved verbatim out of moonglade/backup.py in the 3.22 split (phase 5). The config
road it reads (`CONFIG_API_BASE`, `_config_get`, `_cached_config`) and the model documents the
engine shares (`_GEN_MODEL_Q`, `_UPSERT_MODEL`) stay in the engine.

It reaches the card check as `_cards.match_kaisuuken` and the transport as `_pixai_client.X`.
The names it reads from the engine (the READ_ONLY gate `_check_read_only`, gql_adhoc,
gql_mutate, the `_rest_*` delegates, `_cached_config`, the error classes) are imported from
moonglade.backup inside each function that uses them, at call time, so a test's patch of
backup's binding still reaches them and importing this module never imports the engine.
"""
import datetime
import re
import sys

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run:  pip install requests")

from moonglade import cards as _cards
from moonglade import pixai_client as _pixai_client


_TRAIN_FREE_CURRENCY = "free::user_lora_training"
_CREATE_TRAINING = ("mutation createTrainingTask($input: CreateTrainingTaskInput!) {"
                    " createTrainingTask(input: $input) { id refId } }")
# PixAI's real LoRA-training categories, probed live off the train-lora page's own
# category select 2026-08-06 (the design mockup's character/style/concept was placeholder
# -- "concept" isn't a real PixAI value). Values are what the mutation takes.
TRAIN_CATEGORIES = ("character", "animal", "style", "realistic", "pose", "clothing",
                    "background", "detail", "other")
TRAIN_MIN_IMAGES = 10
TRAIN_MAX_IMAGES = 100


# The trainable base-model architectures, in the order PixAI's own train page shows them,
# each mapped to its friendly label. The label map is PixAI's own (harvested
# constants-*.js: mmdit26b->DiT.3, mmdit26a->DiT.2, dit7->DiT.1, sdxl->SDXL) plus SD 1.5.
# "Model Type" on the train page IS this architecture -- picking one filters which base
# models ("Model Theme") are offered; the value actually submitted is the chosen model's
# VERSION id, not its model id (the site names the field baseModelId but assigns it the
# versionId -- confirmed in the harvested submit builder).
_TRAIN_ARCHS = (
    ("MMDIT26B_MODEL", "DiT.3"),
    ("MMDIT26A_MODEL", "DiT.2"),
    ("DIT7_MODEL",     "DiT.1"),
    ("SDXL_MODEL",     "SDXL"),
    ("SD_V1_MODEL",    "SD 1.5"),
)

# PixAI's curated training-base list is NOT the public generationModels catalog (the owner
# caught this -- the first build pulled the general model-picker feed). Both of PixAI's train
# pages read it, bundled with the pricing matrix and the dataset's image rule, from the public
# dynamic-config key `trainLoraModels`: GET <api>/config/trainLoraModels, no credential needed.
# The 2026-08-06 note here called that config "NOT reachable through any documented endpoint";
# it was wrong -- the key sat in the bundle all along, and the 2026-09-26 probe read it with a
# plain GET (SCOPE_2026-09-26 E7, probe findings SURF-13 / T07). training_config() now reads it
# live through _config_get, cached, and falls back to the snapshot below on any failure, so a
# failed read still offers and prices every base the site offered on 2026-09-26 -- Tsubaki.3
# (DiT.3, 100,000 credits) included. To refresh the snapshot, capture that GET and replace the
# three constants below.
_TRAIN_BASE_MODELS = [
    # (version_id, model_id, title, modelType, usage, cover)
    ("2024383379556065549", "2024383378759147749", "Tsubaki.3", "MMDIT26B_MODEL", "animation", "https://images-ng.pixai.art/images/stillThumb/87954a09-c834-48eb-ae0b-698cd9c7f471"),
    ("1983308862240288769", "1982880136609467518", "Tsubaki.2", "MMDIT26A_MODEL", "animation", "https://images-ng.pixai.art/images/stillThumb/b03c47d1-fcfa-4502-af96-7ef049ebaade"),
    ("1894092844569363483", "1884107375027888751", "Tsubaki", "DIT7_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/98cd261b-9a65-42cd-916b-df27b5e61607"),
    ("1844843519625072849", "1844843518698131638", "Illustrious-v1.0", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/2e0591cc-50fa-4e37-89c6-e641cf65c483"),
    ("1830737069924162722", "1800107133055979065", "NoobAI XL", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/bd4ff6a2-b3de-4645-94e8-3ad19ed82f3f"),
    ("1869108561160475178", "1869108554114044295", "Hinata v2", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/43cf3a51-b7e3-4e8c-8847-38b44471f03b"),
    ("1795876005752987687", "1795876005744599078", "Illustrious-v0.1", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/dc62608f-53f3-426f-a462-ea49578115cd"),
    ("1861558740588989558", "1861558737426484240", "Haruka-v2", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/1c51e854-da5d-4e38-9a60-5532d1e64d23"),
    ("1856956435031440023", "1856956427276171616", "Otome-v2", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/908f0958-f377-4cca-93ee-11438fd0752f"),
    ("1805666669332128958", "1805666668619097261", "Haruka", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/8f07e40a-dca1-41fe-a950-cf5c06a59d3f"),
    ("1772043571096449082", "1772043569905266745", "Hikari", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/11ca16f5-a018-4c4f-92e5-4f7d67d8ac84"),
    ("1856964022763541122", "1856964021647856206", "Illustrious-v2.0", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/2f6816a5-82f3-47e4-afa9-58a8415d0f22"),
    ("1788325270093701704", "1788325267627450916", "Waterfront-v0.9", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/52b7f937-5abc-4406-b753-b826115f92a3"),
    ("1728110559428576906", "1728110558497441412", "Animagine XL", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/49c70b8b-82f0-435b-97f9-0887139aa375"),
    ("1722800994358889032", "1722800993478085189", "PhotoPedia XL", "SDXL_MODEL", "realistic", "https://images-ng.pixai.art/images/thumb/1b5538ef-4ffd-4e00-ab27-393104db7b51"),
    ("1954632828118619567", "1954632827019711809", "Hoshino v2", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/fbc85e5d-6f5e-4b02-a54a-fc679001770f"),
    ("1811528826405408057", "1811528825797233974", "Hoshino", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/d3b638af-7bac-4878-8f3a-1ec4b62998ab"),
    ("1854247165841065427", "1854247164461139322", "Hinata v1", "SDXL_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/060b9c8c-ed2e-4e45-98c1-ac5df005b248"),
    ("1648918127446573124", "1648918125777240131", "Moonbeam", "SD_V1_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/96596124-b2cd-4619-819a-55b425c79307"),
    ("1718827626761711784", "1718827626749128871", "majicMIX realistic", "SD_V1_MODEL", "realistic", "https://images-ng.pixai.art/images/thumb/9bb8d254-ef76-44ef-8a1a-9a64a95df76b"),
    ("1648918115270508582", "1648918113336934437", "Anything V5", "SD_V1_MODEL", "animation", "https://images-ng.pixai.art/images/thumb/e0e7b6a7-baa5-4178-adbe-36610797019f"),
]

# Training prices per architecture (the same config's pricing.pricesByModelType, 2026-09-26
# capture). PixAI's basic trainer prices a run from this matrix, keyed by modelType: `price` for
# a fresh dataset -- the only tier this app quotes, since it never reuses a dataset or retrains
# -- `reuse` when re-using an existing dataset, `retrain` for a re-run. `originalPrice` (when
# present) is the pre-discount tag and is never what a run costs. A usable free-training quota
# overrides all of it to 0, and so does a matching training free card.
_TRAIN_PRICING = {
    "SD_V1_MODEL":    {"price": 25000, "retrain": 25000, "reuse": 12500},
    "SDXL_MODEL":     {"price": 25000, "retrain": 25000, "reuse": 12500, "originalPrice": 75000},
    "DIT7_MODEL":     {"price": 50000, "retrain": 50000, "reuse": 25000, "originalPrice": 150000},
    "MMDIT26A_MODEL": {"price": 100000, "retrain": 50000, "reuse": 50000, "originalPrice": 200000},
    "MMDIT26B_MODEL": {"price": 100000, "retrain": 70000, "reuse": 70000},
}

# The dataset's image rule (the same config's imageConstraints, 2026-09-26 capture): every
# image at least minWidth wide AND minHeight high, its long side over its short side at most
# maxAspectRatio. This is the SERVER's rule shape -- the contract's TRAINING_IMAGE_REJECTED
# error carries exactly these fields -- and it is stricter than the basic wizard's own client
# check (a 262,144-pixel count and a 1:3..3:1 ratio: an 800x400 image passes that and fails
# this), so this per-side rule is the safe superset (probe T04, verifier correction).
_TRAIN_IMAGE_CONSTRAINTS = {"minWidth": 512, "minHeight": 512, "maxAspectRatio": 3}

# The architectures whose trigger words must be at least 30 characters (PixAI's own
# TrainLoraFlowHeader rule, unchanged since August: DiT.2 and DiT.3).
_TRAIN_LONG_TRIGGER_TYPES = ("MMDIT26A_MODEL", "MMDIT26B_MODEL")
TRAIN_TRIGGER_MAX = 256
TRAIN_TRIGGER_MIN_DIT = 30


def _train_models_from(raw):
    """The live config's models[] as the app's row dicts, or None when it has none usable."""
    rows = (raw or {}).get("models") if isinstance(raw, dict) else None
    out = []
    for m in rows if isinstance(rows, list) else []:
        if not isinstance(m, dict):
            continue
        vid, mtype = str(m.get("versionId") or "").strip(), str(m.get("modelType") or "").strip()
        if not vid or not mtype:
            continue
        out.append({"version_id": vid, "model_id": str(m.get("modelId") or ""),
                    "title": str(m.get("modelName") or vid), "model_type": mtype,
                    "usage": str(m.get("usage") or ""), "cover": str(m.get("coverUrl") or "")})
    return out or None


def _train_pricing_from(raw):
    """The live config's pricing.pricesByModelType, integers only, or None when absent."""
    table = (((raw or {}).get("pricing") or {}).get("pricesByModelType")
             if isinstance(raw, dict) else None)
    if not isinstance(table, dict):
        return None
    out = {}
    for mtype, row in table.items():
        if not isinstance(row, dict):
            continue
        clean = {}
        for k in ("price", "retrain", "reuse", "originalPrice"):
            try:
                if row.get(k) is not None:
                    clean[k] = int(row[k])
            except (TypeError, ValueError):
                pass
        if "price" in clean:
            out[str(mtype)] = clean
    return out or None


def _train_constraints_from(raw):
    """imageConstraints off the live config, each field falling back on its own to the
    snapshot's when absent or not a positive number."""
    live = (raw or {}).get("imageConstraints") if isinstance(raw, dict) else None
    out = dict(_TRAIN_IMAGE_CONSTRAINTS)
    for k in out:
        try:
            v = float((live or {}).get(k))
        except (TypeError, ValueError):
            continue
        if v > 0:
            out[k] = v
    return out


def training_config():
    """PixAI's basic-training config: {models, pricing, image_constraints, live}.

    Read live from /config/trainLoraModels (cached, see _cached_config) and falling back,
    piece by piece, to the 2026-09-26 snapshot above: a failed read, or a body missing a
    piece, never leaves the panel with nothing to offer or price. `live` says whether the
    model list itself came off the wire. Read-only; never raises."""
    from moonglade.backup import _cached_config
    raw = _cached_config("trainLoraModels")
    live_models = _train_models_from(raw)
    models = live_models or [
        {"version_id": v, "model_id": mid, "title": title, "model_type": mtype,
         "usage": usage, "cover": cover}
        for (v, mid, title, mtype, usage, cover) in _TRAIN_BASE_MODELS]
    pricing = _train_pricing_from(raw) or {k: dict(v) for k, v in _TRAIN_PRICING.items()}
    return {"models": models, "pricing": pricing,
            "image_constraints": _train_constraints_from(raw), "live": bool(live_models)}


def training_model_type(version_id, config=None):
    """The architecture (modelType) of a training base, by VERSION id; None if unknown."""
    cfg = config or training_config()
    return next((m["model_type"] for m in cfg["models"]
                 if m["version_id"] == str(version_id)), None)


def training_price_for_version(version_id, config=None):
    """The training price (fresh dataset: `price`, never originalPrice) for the base behind
    version_id, from the live config (snapshot fallback) -- or None if the version isn't a
    known base or its type isn't priced. None means 'unknown', which the caller must treat as
    the unsafe case. The quote and the confirm both read it through the same cache, so they
    cannot disagree within the cache's hour."""
    cfg = config or training_config()
    row = cfg["pricing"].get(training_model_type(version_id, cfg) or "")
    return row.get("price") if row else None


# The architecture PixAI marks "Recommended" on both train pages since 2026-09-27 (DiT.3), and
# the one the Session J handoff pre-selects (decision 6a, DECISIONS 2026-09-28).
TRAIN_RECOMMENDED_TYPE = "MMDIT26B_MODEL"


def default_training_base(config=None):
    """The base the panel pre-selects: the Recommended architecture's first row (Tsubaki.3 --
    the handoff's 6a and PixAI's own basic page since 2026-09-27, whose DiT.3 tab opens
    selected), else the first SDXL row (PixAI's older default, `e.find(SdxlModel) ?? e[0]`),
    else the first row. This replaces the SCOPE_2026-09-26 E7 rule that avoided Tsubaki.3 for
    its price: the price now sits on the review footer before Start, and a paid start still
    needs the amount ticked."""
    cfg = config or training_config()
    offered = [m for m in cfg["models"] if m["model_type"] in dict(_TRAIN_ARCHS)]
    pick = (next((m for m in offered if m["model_type"] == TRAIN_RECOMMENDED_TYPE), None)
            or next((m for m in offered if m["model_type"] == "SDXL_MODEL"), None)
            or (offered[0] if offered else None))
    return pick["version_id"] if pick else ""


def list_trainable_base_models(session=None, per_type=None, config=None):
    """The base models a LoRA can be trained on, grouped by architecture -- the train
    page's Model Type -> Model Theme picker, in _TRAIN_ARCHS order. Served from PixAI's own
    config (training_config: live, snapshot fallback); `session` is accepted but unused, as
    the config read is anonymous. Each model dict: {version_id, model_id, title, cover, usage}.
    version_id is what `submit_training(base_model_id=...)` takes. An architecture this app has
    no label for is left out, as the site's own chip list does."""
    cfg = config or training_config()
    groups = []
    for arch, label in _TRAIN_ARCHS:
        models = [{"version_id": m["version_id"], "model_id": m["model_id"], "title": m["title"],
                   "cover": m["cover"], "usage": m["usage"]}
                  for m in cfg["models"] if m["model_type"] == arch]
        if models:
            row = cfg["pricing"].get(arch) or {}
            groups.append({"arch": arch, "label": label, "models": models,
                           "price": row.get("price"), "reuse": row.get("reuse"),
                           "list_price": row.get("originalPrice"),
                           "recommended": arch == TRAIN_RECOMMENDED_TYPE})
    return groups


def training_free_quota(session):
    """How many FREE LoRA trainings this account can use right now -- the membership quota
    under the currency `free::user_lora_training`, counted ONLY for a member. Read-only.

    PixAI's own trainer counts the quota only when `me.membership.tier != null` (tier 0
    counts), and prices the run in full otherwise (probe T09): so this returns quotaAmount when
    the membership tier -- read in the SAME query as the quota -- is present, and 0 when it is
    absent, null, or the read failed. 0 is the safe direction: it means 'treat this as paid',
    never 'assume it's free', so the paid confirm's accept_credit_cost applies.

    The quota is ONE of the two ways a training runs free. The other is a training free card
    (kaisuuken type `training-task`): PixAI's site checks for one too and attaches it --
    match_training_kaisuuken. (Owner ruling 4, 2026-09-26: the 2026-07-26 note "the free
    trainings ARE cards" and the old docstring here, "the quota, NOT a card", were each half
    right.)"""
    from moonglade.backup import gql_adhoc, PixAIError
    try:
        d = gql_adhoc(session,
                      "query($currency:String!){ me { id membership { tier }"
                      " quotaAmount(currency:$currency) } }",
                      {"currency": _TRAIN_FREE_CURRENCY}) or {}
        me = d.get("me") or {}
        membership = me.get("membership")
        tier = membership.get("tier") if isinstance(membership, dict) else None
        if tier is None:
            return 0
        return max(0, int(me.get("quotaAmount") or 0))
    except (PixAIError, requests.RequestException, TypeError, ValueError, AttributeError):
        return 0


def match_training_kaisuuken(session, base_version_id, raise_on_error=False):
    """The read-only training free-card check: /v2/kaisuuken/check with PixAI's own training
    shape {type: "training-task", baseModelId: <base VERSION id>, version: 2} (the site's
    useKaisuukenMatch). Same result and coverage rules as match_kaisuuken; nothing is
    consumed until createTrainingTask carries the returned id."""
    return _cards.match_kaisuuken(session, None, enrich=True, raise_on_error=raise_on_error,
                           training_base_model_id=base_version_id)


# The training pause switch's cache clock: PixAI's own pages poll it once a minute.
_TRAIN_STATUS_TTL = 60.0


def training_pause():
    """None when LoRA training is open -- or when the pause switch could not be read, which
    proceeds exactly as before this check existed -- else {"resumes_at": iso-or-""}.

    PixAI's public /config/trainLoraStatus: paused when `state == "PAUSED"` or
    `disabled == true` (its trainLoraStatus module); `resumesAt` is named only when it parses
    to a time still in the future. While paused the site redirects both train pages to a
    notice; this app refuses the submit instead. Read-only, cached for a minute."""
    from moonglade.backup import _cached_config
    raw = _cached_config("trainLoraStatus", ttl=_TRAIN_STATUS_TTL)
    if not isinstance(raw, dict):
        return None
    if not (raw.get("state") == "PAUSED" or raw.get("disabled") is True):
        return None
    resumes = ""
    ra = raw.get("resumesAt")
    if isinstance(ra, str) and ra.strip():
        try:
            when = datetime.datetime.fromisoformat(ra.strip().replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=datetime.timezone.utc)
            if when > datetime.datetime.now(datetime.timezone.utc):
                resumes = when.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        except ValueError:
            pass
    return {"resumes_at": resumes}


def normalize_trigger_words(text):
    """PixAI's own trigger-word normalizer, in its order (the train page's he()): runs of
    CR/LF become ", "; any whitespace run becomes one space; a run of commas with spaces
    between them becomes one ", "; lowercase; then leading and trailing commas and whitespace
    are stripped. The string validate_training checks -- and the one submitted -- is this."""
    s = str(text or "")
    s = re.sub(r"[\r\n]+", ", ", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r",\s*(?:,\s*)+", ", ", s)
    s = s.lower()
    return re.sub(r"^[,\s]+|[,\s]+$", "", s)


def trigger_word_length(text):
    """A trigger-word string's length as PixAI's page measures it: JavaScript's
    `String.length`, i.e. UTF-16 code units -- a character outside the Basic Multilingual
    Plane, such as an emoji, counts 2. Python's len() would count it once, and so let through a
    256-emoji string PixAI refuses as too long while refusing a 15-emoji DiT.3 trigger it
    accepts. The train panel's counter shows the same number (normalizeTrigger in
    gallery/src/gen/trainCore.js)."""
    return len(str(text or "").encode("utf-16-le")) // 2


def validate_training(base_model_id, media_ids, title, trigger_words, category,
                      training_task_id="", config=None):
    """Mirror the site's OWN pre-submit validation (its Er() builder) so a bad request is
    refused here instead of burning a round trip -- or worse, a free-training quota unit.
    Returns the normalized trigger words. Raises PixAIError with a plain-language reason.

    Trigger words follow PixAI's rule on the NORMALIZED string: empty refused, over 256
    characters refused, and under 30 refused on a DiT.2 / DiT.3 base (MMDIT26A / MMDIT26B).
    The image rule needs each image's size, which this has no way to know -- the caller runs
    check_training_images over its own catalog."""
    from moonglade.backup import PixAIError
    # base_model_id is the model VERSION id (list_trainable_base_models' version_id) --
    # PixAI's baseModelId input takes the version, not the model, id.
    if not base_model_id:
        raise PixAIError("pick a base model to train on")
    ids = [str(m) for m in (media_ids or []) if str(m).strip()]
    if len(ids) < TRAIN_MIN_IMAGES and not training_task_id:
        raise PixAIError("training needs at least %d images -- you have %d"
                         % (TRAIN_MIN_IMAGES, len(ids)))
    if len(ids) > TRAIN_MAX_IMAGES:
        raise PixAIError("training takes at most %d images -- you have %d"
                         % (TRAIN_MAX_IMAGES, len(ids)))
    if not str(title or "").strip():
        raise PixAIError("give the LoRA a name")
    tw = normalize_trigger_words(trigger_words)
    if not tw:
        raise PixAIError("trigger words are required -- they're how you summon the LoRA")
    # Counted the way the site counts them (trigger_word_length: JavaScript's `length`, UTF-16
    # code units), so an emoji is 2 here as it is there.
    units = trigger_word_length(tw)
    if units > TRAIN_TRIGGER_MAX:
        raise PixAIError("trigger words are too long -- %d characters at most, yours are %d"
                         % (TRAIN_TRIGGER_MAX, units))
    if training_model_type(base_model_id, config) in _TRAIN_LONG_TRIGGER_TYPES \
            and units < TRAIN_TRIGGER_MIN_DIT:
        raise PixAIError("trigger words must be at least %d characters on a DiT.2 or DiT.3 "
                         "base -- yours are %d" % (TRAIN_TRIGGER_MIN_DIT, units))
    if str(category or "") not in TRAIN_CATEGORIES:
        raise PixAIError("pick a category (%s)" % "/".join(TRAIN_CATEGORIES))
    return tw


def check_training_images(media_ids, dims, constraints=None):
    """Hold each dataset image to PixAI's training image rule (training_config's
    image_constraints: each side at least minWidth / minHeight, long side over short side at
    most maxAspectRatio). `dims` is {media_id: (width, height)} from the caller's catalog.

    Returns (rejected, unchecked): `rejected` is [{media_id, width, height, why}] for images
    the rule refuses; `unchecked` lists the ids whose size is unknown (not in `dims`, or not
    positive numbers) -- those are NOT passed as checked, the caller says they were not.

    This app REFUSES a run holding a rejected image, naming each one. PixAI's own basic
    wizard silently drops them and trains on the rest; refusing is deliberate here, so a paid
    run never trains on a different dataset than the one picked."""
    c = dict(_TRAIN_IMAGE_CONSTRAINTS)
    c.update(constraints or training_config()["image_constraints"])
    min_w, min_h, max_ar = float(c["minWidth"]), float(c["minHeight"]), float(c["maxAspectRatio"])
    rejected, unchecked = [], []
    for mid in [str(m) for m in (media_ids or []) if str(m).strip()]:
        wh = (dims or {}).get(mid)
        try:
            w, h = float(wh[0]), float(wh[1])
        except (TypeError, ValueError, IndexError, KeyError):
            w = h = 0.0
        if not (w > 0 and h > 0):
            unchecked.append(mid)
            continue
        if w < min_w or h < min_h:
            why = "smaller than %dx%d" % (min_w, min_h)
        elif max(w, h) / min(w, h) > max_ar:
            why = "longer than %g:1" % max_ar
        else:
            continue
        rejected.append({"media_id": mid, "width": int(w), "height": int(h), "why": why})
    return rejected, unchecked


def describe_rejected_training_images(rejected):
    """The refusal's own words for check_training_images' `rejected` list."""
    shown = ", ".join("%s (%dx%d, %s)" % (r["media_id"], r["width"], r["height"], r["why"])
                      for r in rejected[:8])
    more = " and %d more" % (len(rejected) - 8) if len(rejected) > 8 else ""
    return ("PixAI won't train on %d of these images — remove %s and try again: %s%s."
            % (len(rejected), "it" if len(rejected) == 1 else "them", shown, more))


def submit_training(session, base_model_id, media_ids, title, trigger_words, category,
                    training_task_id="", primary_lora_model_id="", kaisuuken_id="",
                    config=None):
    """Submit a real LoRA training task to PixAI (`createTrainingTask`).

    SPENDS unless the account has usable free-training quota left (training_free_quota) or
    the caller attaches a matching training free card (`kaisuuken_id`, from
    match_training_kaisuuken) -- so it goes through gql_mutate: SINGLE ATTEMPT, no retry, for
    exactly the reason
    every other spend path does. A lost response after the server accepted the task
    would, on retry, start a SECOND training and consume a second quota unit (or a real
    credit charge, which for training is large). _check_read_only gates it like every
    other account mutation.

    This function does NOT decide whether the user wants to pay: callers preview first
    (quota + validation) and only call this once the user has confirmed. Input shape
    mirrors the site's own form exactly. Returns the created task dict.

    `config` is the caller's training_config() -- the one it previewed and priced against --
    so this validates against the SAME config instead of a fresh re-read that could differ.
    A refusal before the network call (READ_ONLY, validation) is raised as LocalRefusal:
    nothing was sent, and the caller's spend guard must not say a run may have started."""
    from moonglade.backup import _check_read_only, gql_mutate, LocalRefusal, PixAIError
    try:
        _check_read_only("submit a LoRA training task")
        tw = validate_training(base_model_id, media_ids, title, trigger_words, category,
                               training_task_id, config=config)
    except LocalRefusal:
        raise
    except PixAIError as e:
        raise LocalRefusal(str(e)) from e
    inp = {
        "baseModelId": str(base_model_id),
        "mediaIds": [str(m) for m in (media_ids or []) if str(m).strip()],
        "title": str(title).strip(),
        "type": "USER_MULTI_LORA",
        "triggerWords": tw,
        "category": str(category),
    }
    if training_task_id:
        inp["trainingTaskId"] = str(training_task_id)
    if primary_lora_model_id:
        inp["primaryLoraModelId"] = str(primary_lora_model_id)
    if kaisuuken_id:
        inp["kaisuukenId"] = str(kaisuuken_id)
    d = gql_mutate(session, _CREATE_TRAINING, {"input": inp}) or {}
    return d.get("createTrainingTask") or {}


# --- LoRA training: the advanced flow, runs, publish (Session J, 2026-09-28) ------------------
# PixAI's advanced trainer is a draft (GraphQL createTrainingTask, trainingMode "advanced", no
# images, free) worked on through REST under /v2/training-task/{id}: the dataset (PUT media,
# free), a PAID describe round (POST caption, priced per task by GET caption-price), the owner's
# own edits of those descriptions (PUT captions/{mediaId}, free, only once a machine description
# exists), a PAID start (POST submit, priced by GET price), a PAID retry of a failed run (a NEW
# run), and an irreversible publish. Every writer below calls _check_read_only first and rides a
# single-attempt transport (gql_mutate, rest_post, rest_put, rest_patch). Callers preview and
# acknowledge; nothing here decides that the user wants to pay. The wire facts and the guard
# order are in ../moonglade-internal/design/notes/training/BUILD-w3-train.md.

# Basic's four goals (and Advanced's categories), PixAI's own values: its "Something else"
# sub-kind is never sent.
TRAIN_GOALS = (("character", "Character"), ("style", "Art style"), ("clothing", "Outfit"),
               ("other", "Something else"))
# The architectures Advanced offers (Tsubaki.3 Recommended, then Tsubaki.2).
TRAIN_ADVANCED_TYPES = ("MMDIT26B_MODEL", "MMDIT26A_MODEL")
# What PixAI's own advanced page submits: its parameter controls are inert ("coming soon") and
# it sends these defaults. Sent verbatim -- the quote route takes no length, and PixAI's own
# fallback price scales with it, so an unquoted length is never sent (spend review, finding 3).
TRAIN_DEFAULT_OPTIONS = {"trainingSteps": 325, "learningRate": 0.0006, "rank": 64,
                         "gradAccum": 2}
# A description, as PixAI's editor caps it (its contract would take 20,000; the editor is the
# rule users meet).
TRAIN_CAPTION_MAX = 1000

_TRAINING_TASK_FIELDS = ("id userId status trainingMode type refId retryCount createdAt "
                         "updatedAt startedAt endAt parameters { title mediaIds category "
                         "baseModelId triggerWords } extra { progress estimatedTotalTime } "
                         "outputs { message }")
_TRAINING_TASK_Q = "query($id: ID!) { trainingTask(id: $id) { " + _TRAINING_TASK_FIELDS + " } }"
_MY_LORAS_Q = ("query($au: ID, $ty: GenerationModelType, $n: Int, $b: String) { "
               "generationModels(authorId: $au, type: $ty, last: $n, before: $b) { "
               "pageInfo { hasPreviousPage startCursor } edges { node { id title isPrivate "
               "visibilityType createdAt mediaId latestAvailableVersion { id } trainingTask { "
               + _TRAINING_TASK_FIELDS + " } } } } }")


def training_eta(steps=325):
    """PixAI's own estimate (its advanced page's Br()): t = max(1, round(steps * 27 / 325))
    minutes, shown as "about t to round(t * 1.3) minutes" -- 27-35 at the default, the same
    number its basic page prints."""
    t = max(1, int(round(float(steps) * 27.0 / 325.0)))
    return {"min": t, "max": int(round(t * 1.3))}


def advanced_training_bases(config=None):
    """The two bases Advanced offers: one row per advanced architecture (an "animation" row
    preferred, as the site picks), Recommended first. [{version_id, title, cover, model_type,
    recommended}]."""
    cfg = config or training_config()
    out = []
    for mtype in TRAIN_ADVANCED_TYPES:
        rows = [m for m in cfg["models"] if m["model_type"] == mtype]
        pick = next((m for m in rows if m.get("usage") == "animation"), None) or \
            (rows[0] if rows else None)
        if pick:
            out.append({"version_id": pick["version_id"], "title": pick["title"],
                        "cover": pick["cover"], "model_type": mtype,
                        "recommended": mtype == TRAIN_RECOMMENDED_TYPE})
    return out


def training_price_tier(version_id, tier="price", config=None):
    """A base's price at one tier of PixAI's matrix (`price` fresh, `reuse` a reused dataset),
    or None when unknown. Never `originalPrice`."""
    cfg = config or training_config()
    row = cfg["pricing"].get(training_model_type(version_id, cfg) or "") or {}
    v = row.get(tier)
    return v if isinstance(v, int) else None


_TRAIN_ERROR_WORDS = {
    "TRAINING_IMAGE_REJECTED": "PixAI won't train on some of these images (smaller than its "
                               "minimum size, or too long and thin)",
    "TRAINING_DATASET_TOO_SMALL": "PixAI needs more images in this set before it can go on",
    "INSUFFICIENT_BALANCE": "there aren't enough credits on the account; nothing was charged",
    "MODEL_PUBLISH_CONFLICT": "another public LoRA already uses these weights",
    "LORA_REBATE_REQUIRES_PUBLIC": "only a public LoRA can join rebates",
}


def training_error_words(exc):
    """A PixAI training refusal in plain words: its defined code where it sent one, its own
    message otherwise."""
    from moonglade.backup import PixAIRestError
    if isinstance(exc, PixAIRestError):
        if exc.code in _TRAIN_ERROR_WORDS:
            return _TRAIN_ERROR_WORDS[exc.code]
        msg = str(exc.fields.get("message") or "").strip()
        if msg:
            return msg
    return str(exc)


def _task_path(task_id, suffix=""):
    from moonglade.backup import PixAIError
    tid = str(task_id or "").strip()
    if not tid.isdigit():
        raise PixAIError("not a training task id: %r" % (task_id,))
    return "/training-task/" + tid + suffix


def training_task(session, task_id):
    """One training task by id (GraphQL trainingTask) -- basic or advanced -- or raises.
    Read-only. `extra.progress` is PixAI's percentage (0-100) and `estimatedTotalTime` its
    whole-run estimate in milliseconds, both only while it runs."""
    from moonglade.backup import gql_adhoc, PixAIError
    d = gql_adhoc(session, _TRAINING_TASK_Q, {"id": str(task_id)}) or {}
    t = d.get("trainingTask")
    if not isinstance(t, dict):
        raise PixAIError("training task %s not found" % task_id)
    return t


def list_training_in_progress(session, limit=100):
    """Every advanced task still in the owner's hands (drafts through failed), newest activity
    first: [{id, status, title, baseModelId, mediaCount, updatedAt}]. Read-only."""
    from moonglade.backup import _rest_get
    d = _rest_get(session, "/training-task/in-progress",
                  params={"limit": max(1, min(int(limit), 100))}) or {}
    return [t for t in (d.get("tasks") or []) if isinstance(t, dict)]


def list_training_completed(session, limit=100):
    """Every finished advanced task, newest first, published or not (`modelId` null until
    published): [{id, title, baseModelId, mediaCount, modelId, completedAt}]. Read-only."""
    from moonglade.backup import _rest_get
    d = _rest_get(session, "/training-task/completed",
                  params={"limit": max(1, min(int(limit), 100))}) or {}
    return [t for t in (d.get("tasks") or []) if isinstance(t, dict)]


def list_my_trained_loras(session, pages=3, per_page=20):
    """The account's own trained LoRAs with the run behind each (GraphQL generationModels
    authorId + ANY_USER_LORA, the list PixAI's "Import from previous datasets" reads), newest
    first, up to `pages` pages. Each row: {model_id, title, is_private, visibility, created_at,
    cover_media_id, version_id, task} where task is the TrainingTask dict or None. Read-only."""
    from moonglade.backup import gql_adhoc
    uid = str(_pixai_client._client_of(session).user_id or "")
    out, before = [], None
    for _ in range(max(1, int(pages))):
        v = {"au": uid, "ty": "ANY_USER_LORA", "n": int(per_page)}
        if before:
            v["b"] = before
        d = (gql_adhoc(session, _MY_LORAS_Q, v) or {}).get("generationModels") or {}
        rows = []
        for e in d.get("edges") or []:
            n = (e or {}).get("node") or {}
            if not n.get("id"):
                continue
            ver = n.get("latestAvailableVersion") or {}
            rows.append({"model_id": str(n["id"]), "title": str(n.get("title") or ""),
                         "is_private": bool(n.get("isPrivate")),
                         "visibility": str(n.get("visibilityType") or ""),
                         "created_at": str(n.get("createdAt") or ""),
                         "cover_media_id": str(n.get("mediaId") or ""),
                         "version_id": str(ver.get("id") or ""),
                         "task": n.get("trainingTask") if isinstance(n.get("trainingTask"), dict)
                         else None})
        out.extend(reversed(rows))                 # `last` pages come oldest-first
        info = d.get("pageInfo") or {}
        if not info.get("hasPreviousPage") or not info.get("startCursor"):
            break
        before = info["startCursor"]
    return out


def training_caption_quote(session, task_id):
    """What the next describe round would charge: {image_count, total_price} -- PixAI's own
    per-task quote (the images with no machine description yet, times the unit price). The
    config's captionPricing is stale (100 there; 150 on the owner's capture draft), so this,
    never the config, is the number shown and acknowledged. Read-only."""
    from moonglade.backup import PixAIError, _rest_get
    d = _rest_get(session, _task_path(task_id, "/caption-price")) or {}
    if not isinstance(d.get("totalPrice"), (int, float)):
        raise PixAIError("PixAI returned no describe price for training task %s" % task_id)
    return {"image_count": int(d.get("imageCount") or 0),
            "total_price": int(d.get("totalPrice") or 0)}


def training_quote(session, task_id):
    """What starting (or retrying) this advanced task would charge today, by its base model --
    PixAI's own free quote (GET price). Read-only. Returns an int."""
    from moonglade.backup import PixAIError, _rest_get
    d = _rest_get(session, _task_path(task_id, "/price")) or {}
    if not isinstance(d.get("price"), (int, float)):
        raise PixAIError("PixAI returned no price for training task %s" % task_id)
    return int(d["price"])


def training_captions(session, task_id):
    """The task's descriptions: [{media_id, source (machine|user), caption_url, machine_url,
    user_url}]. The links are short-lived; fetch_caption_text reads each. Read-only."""
    from moonglade.backup import _rest_get
    d = _rest_get(session, _task_path(task_id, "/captions")) or {}
    out = []
    for it in d.get("items") or []:
        if isinstance(it, dict) and it.get("mediaId"):
            out.append({"media_id": str(it["mediaId"]), "source": str(it.get("source") or ""),
                        "caption_url": str(it.get("captionUrl") or ""),
                        "machine_url": str(it.get("machineCaptionUrl") or ""),
                        "user_url": str(it.get("userCaptionUrl") or "")})
    return out


def fetch_caption_text(url, limit=64 * 1024):
    """One description's text from its time-limited link (PixAI's own page fetches it the same
    way, without credentials). HTTPS only; NO PixAI credential rides this request -- a plain
    requests.get, never the account session; capped at `limit` bytes. Returns None on any
    failure (the caller shows the description as unreadable, never as empty-and-editable)."""
    u = str(url or "")
    if not u.startswith("https://"):
        return None
    try:
        r = requests.get(u, timeout=15, stream=True)
        if not r.ok:
            return None
        raw = r.raw.read(limit + 1, decode_content=True) or b""
        return raw[:limit].decode("utf-8", "replace").strip()
    except (requests.RequestException, OSError, ValueError):
        return None


def create_advanced_training_draft(session, base_model_id, title, trigger_words, category,
                                   config=None):
    """Create an ADVANCED training draft -- PixAI's own step-1 call (createTrainingTask with
    {type: LORA, trainingMode: advanced, title, category, baseModelId, triggerWords}, no
    images). FREE, but it writes to the account, so it runs only on the user's deliberate
    "Next · creates a draft" (DECISIONS 2026-09-28, nothing writes on open). Name, category,
    base and trigger words are fixed from here. Single attempt. Returns {id}."""
    from moonglade.backup import _check_read_only, gql_mutate, PixAIError
    _check_read_only("create a LoRA training draft")
    cfg = config or training_config()
    bases = {b["version_id"] for b in advanced_training_bases(cfg)}
    if str(base_model_id) not in bases:
        raise PixAIError("Advanced training runs on Tsubaki.3 or Tsubaki.2 only")
    if str(category or "") not in dict(TRAIN_GOALS):
        raise PixAIError("pick what you are training (%s)" % ", ".join(
            lab for _, lab in TRAIN_GOALS))
    # the dataset floor is checked when describing and starting, not here: a draft has none
    tw = validate_training(base_model_id, [], title, trigger_words, category,
                           training_task_id="draft", config=cfg)
    inp = {"type": "LORA", "trainingMode": "advanced", "title": str(title).strip(),
           "category": str(category), "baseModelId": str(base_model_id), "triggerWords": tw}
    d = gql_mutate(session, _CREATE_TRAINING, {"input": inp}) or {}
    task = d.get("createTrainingTask") or {}
    if not task.get("id"):
        raise PixAIError("PixAI created no draft")
    return {"id": str(task["id"])}


def replace_training_media(session, task_id, media_ids):
    """Replace an advanced task's whole image list (PUT media, <=100, free). Single attempt."""
    from moonglade.backup import _check_read_only, PixAIError, _rest_put
    _check_read_only("change a LoRA training set")
    ids = []
    for m in media_ids or []:
        m = str(m).strip()
        if m and m not in ids:
            ids.append(m)
    if len(ids) > TRAIN_MAX_IMAGES:
        raise PixAIError("training takes at most %d images -- you have %d"
                         % (TRAIN_MAX_IMAGES, len(ids)))
    d = _rest_put(session, _task_path(task_id, "/media"), {"mediaIds": ids}) or {}
    return [str(m) for m in (d.get("mediaIds") or ids)]


def start_training_captions(session, task_id):
    """PAID: send the set's undescribed images to PixAI's describe round (POST caption). The
    caller has quoted it (training_caption_quote) and had the amount acknowledged. Single
    attempt. Returns PixAI's new status."""
    from moonglade.backup import _check_read_only, _rest_post
    _check_read_only("describe LoRA training images (spends credits)")
    d = _rest_post(session, _task_path(task_id, "/caption"), {}) or {}
    return str(d.get("status") or "")


def save_training_caption(session, task_id, media_id, text):
    """Save the owner's own description for one image (PUT captions/{mediaId}; free; PixAI
    keeps it as a new version, the machine's stays on file). Only for an image PixAI has
    described already. 1 to TRAIN_CAPTION_MAX characters. Single attempt."""
    from moonglade.backup import _check_read_only, PixAIError, _rest_put
    _check_read_only("edit a LoRA training description")
    t = str(text or "").strip()
    if not t:
        raise PixAIError("a description can't be empty")
    if len(t) > TRAIN_CAPTION_MAX:
        raise PixAIError("a description is %d characters at most -- this one is %d"
                         % (TRAIN_CAPTION_MAX, len(t)))
    mid = str(media_id or "").strip()
    if not mid.isdigit():
        raise PixAIError("which image?")
    _rest_put(session, _task_path(task_id, "/captions/" + mid), {"text": t})
    return t


def submit_advanced_training(session, task_id):
    """PAID: start an advanced run (POST submit) with PixAI's own default options, exactly as
    its page sends them (TRAIN_DEFAULT_OPTIONS). No free card rides it -- PixAI's page attaches
    none. The caller has quoted it (training_quote) and had the amount acknowledged. Single
    attempt. Returns PixAI's new status."""
    from moonglade.backup import _check_read_only, _rest_post
    _check_read_only("start a LoRA training run (spends credits)")
    d = _rest_post(session, _task_path(task_id, "/submit"),
                   {"trainingOptions": dict(TRAIN_DEFAULT_OPTIONS)}) or {}
    return str(d.get("status") or "")


def retry_training(session, task_id):
    """PAID: a NEW run from a failed advanced one (POST retry: same set, same descriptions,
    charged again at today's price). The failed task stays as it is, so a second call would
    start and charge a second run -- the caller guards against that. Single attempt. Returns
    {id (the new run), origin_id, status}."""
    from moonglade.backup import _check_read_only, _rest_post
    _check_read_only("retry a LoRA training run (spends credits)")
    d = _rest_post(session, _task_path(task_id, "/retry"), {}) or {}
    return {"id": str(d.get("trainingTaskId") or ""),
            "origin_id": str(d.get("originTaskId") or task_id),
            "status": str(d.get("status") or "")}


def publish_training(session, task_id, visibility, rebate):
    """IRREVERSIBLE: turn a finished advanced run into a LoRA (POST publish, once per run).
    visibility private|public; rebate join|decline, and join only when public (refused here
    before PixAI would). Single attempt. Returns {model_id, version_id}."""
    from moonglade.backup import _check_read_only, PixAIError, _rest_post
    _check_read_only("publish a trained LoRA")
    if visibility not in ("private", "public"):
        raise PixAIError("publish it private or public")
    if rebate not in ("join", "decline"):
        raise PixAIError("join or decline rebates")
    if rebate == "join" and visibility != "public":
        raise PixAIError(_TRAIN_ERROR_WORDS["LORA_REBATE_REQUIRES_PUBLIC"])
    d = _rest_post(session, _task_path(task_id, "/publish"),
                   {"visibility": visibility, "loraRebate": rebate}) or {}
    return {"model_id": str(d.get("modelId") or ""), "version_id": str(d.get("versionId") or "")}
