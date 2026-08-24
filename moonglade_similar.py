"""Moonglade Athenaeum — "more like this" visual similarity.

A SIDECAR index over the catalog's images: CLIP embeddings held in a Pixeltable table,
embedded via Pixeltable's BUILT-IN `huggingface.clip` by default since 2026-07-26 --
see _embedding_fn() for why that is a bug fix rather than a preference. The custom
`clip_gpu` UDF below remains as a fallback (MG_SIMILAR_EMBED=custom); its original
reason to exist was that the stock function ran on CPU ~13 img/s;
ours runs on the GPU ~decode-bound). `catalog.db` stays the source of truth — this module
only maps a media_id -> its nearest media_ids and never owns curation.

Heavy deps (pixeltable, torch, transformers) and Pixeltable's embedded Postgres load LAZILY
on first use, so importing this module (or the gallery) stays cheap. The gallery imports it
inside the /api/similar handler, not at startup.

Public API:
    sync(items, progress=None)            -> int    # index media_ids not yet embedded
    similar(query_path, k, exclude=...)   -> [(media_id, score)]
    count()                               -> int
    indexed_ids()                         -> set[str]
    is_available()                        -> bool    # torch/pixeltable importable?
"""
import threading
from pathlib import Path

import numpy as np
import PIL.Image
from PIL import ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True   # salvage partially-truncated downloads
import pixeltable as pxt
from pixeltable.func import Batch

MODEL = "openai/clip-vit-base-patch32"
_DIR = "moonglade"
_TBL = f"{_DIR}.images"
_IDX = "img_clip"          # explicit index name -> if_exists='ignore' can recognize it

_model_lock = threading.Lock()
_model: dict = {}          # lazy: {'mdl','proc','dev'}
_table_lock = threading.Lock()
_table: dict = {}          # cached handle


def _ensure_model() -> dict:
    """Load CLIP once, on the GPU if available. Called from inside the UDF."""
    if not _model:
        with _model_lock:
            if not _model:
                import torch
                from transformers import CLIPModel, AutoProcessor
                dev = "cuda" if torch.cuda.is_available() else "cpu"
                _model["mdl"] = CLIPModel.from_pretrained(MODEL).to(dev).eval()
                _model["proc"] = AutoProcessor.from_pretrained(MODEL)
                _model["dev"] = dev
    return _model


@pxt.udf(batch_size=64)
def clip_gpu(imgs: Batch[PIL.Image.Image]) -> Batch[pxt.Array[(512,), pxt.Float]]:
    """GPU CLIP image embedding. Uses the vision tower directly (transformers 5.x changed
    get_image_features to return a wrapper, not a tensor)."""
    import torch
    m = _ensure_model()
    pil = [im.convert("RGB") for im in imgs]
    with torch.no_grad():
        inp = m["proc"](images=pil, return_tensors="pt").to(m["dev"])
        vout = m["mdl"].vision_model(pixel_values=inp["pixel_values"])
        f = m["mdl"].visual_projection(vout.pooler_output)
        f = f / f.norm(dim=-1, keepdim=True)
    arr = f.cpu().numpy().astype(np.float32)
    return [arr[i] for i in range(arr.shape[0])]


def _embedding_fn():
    """The embedding function to register on the index -- Pixeltable's BUILT-IN CLIP by
    preference, our `clip_gpu` UDF as a fallback.

    This is a bug fix, not a preference. Pixeltable stores the embedding function's
    FULLY-QUALIFIED PATH inside the index, so registering a UDF defined in this module ties the
    index to this module's NAME. The 2026-07-25 rename (pixai_similar -> moonglade_similar)
    therefore orphaned a working index: the stored reference still read "pixai_similar.clip_gpu"
    and no longer resolved. The built-in's path lives inside the pixeltable package, where our
    renames cannot reach it, so this cannot happen again.

    It also silently made the failure invisible -- see _get_table(), which CREATES a fresh table
    when it cannot open the existing one, so the orphaned index was replaced by an empty one with
    no exception raised anywhere.

    THERE IS DELIBERATELY NO FALLBACK TO clip_gpu, and restoring one would reintroduce a live
    failure. Measured 2026-07-26 on the production install:

        RequestError: The function `clip_gpu` is not a valid image embedding:
                      it must take a single image parameter

    A Pixeltable upgrade tightened embedding-function validation, and `clip_gpu` is a BATCHED udf
    (Batch[Image] -> Batch[Array]) which the new index code refuses. That is what actually broke
    "More like this" -- not the module rename, which was the first and wrong diagnosis. The stored
    index metadata became undeserialisable, so `get_table` AND `create_table` both failed, the
    latter because resolving a path collision loads the same unreadable metadata.

    So preferring the built-in is load-bearing rather than tidy: it takes a single image and
    passes validation. `clip_gpu` is kept below only because the batched-GPU technique is worth
    not losing, and because it documents why the custom path existed -- it is no longer reachable
    from here on purpose."""
    from pixeltable.functions.huggingface import clip as _builtin_clip
    try:
        return _builtin_clip.using(model_id=MODEL)
    except TypeError:
        # `using` signature differs across versions; a bare reference still validates.
        return _builtin_clip


def _get_table():
    """Get-or-create the sidecar table. On an EXISTING table return it as-is and NEVER
    re-touch the index: re-adding an embedding index on every open — and, worse, an
    UNNAMED one — is exactly what stacked duplicate indices and broke queries with
    'Column img has multiple embedding indices'. The index is added exactly ONCE, by
    explicit name (_IDX), at creation; new rows auto-embed through it."""
    if "t" not in _table:
        with _table_lock:
            if "t" not in _table:
                try:
                    t = pxt.get_table(_TBL)          # exists -> use as-is, no index churn
                except Exception:
                    pxt.create_dir(_DIR, if_exists="ignore")
                    t = pxt.create_table(
                        _TBL,
                        {"media_id": pxt.Required[pxt.String], "img": pxt.Image},
                        primary_key=["media_id"],
                        if_exists="ignore",
                    )
                    t.add_embedding_index("img", idx_name=_IDX,
                                          embedding=_embedding_fn(),
                                          if_exists="ignore")
                _table["t"] = t
    return _table["t"]


def is_available() -> bool:
    """True if the ML stack is importable (torch present). Cheap-ish; imports torch."""
    try:
        import torch  # noqa: F401
        return True
    except Exception:
        return False


def indexed_ids() -> set:
    t = _get_table()
    return {r["media_id"] for r in t.select(t.media_id).collect()}


def count() -> int:
    return _get_table().count()


def sync(items, progress=None, batch: int = 400) -> int:
    """items: iterable of (media_id, image_path). Insert those not already indexed;
    new rows auto-embed on the GPU. Robust against a messy library:
      - deduplicates media_ids within the scan and against what's already indexed
        (the backup legitimately holds the same media_id in more than one file), and
      - if a batch insert aborts (corrupt image, etc.), retries it row-by-row and
        skips only the offending rows — so one bad file never kills the build.
    Returns rows inserted; records the skipped-row count on sync.last_errors."""
    t = _get_table()
    have = indexed_ids()
    seen = set()
    new = []
    for m, p in items:
        m = str(m)
        if m in have or m in seen or not Path(p).exists():
            continue
        seen.add(m)
        new.append({"media_id": m, "img": str(p)})
    total = len(new)
    inserted = 0
    errs = 0
    for i in range(0, total, batch):
        chunk = new[i:i + batch]
        try:
            t.insert(chunk, on_error="ignore")
            inserted += len(chunk)
        except Exception:
            for row in chunk:              # a bad row aborted the batch — skip just it
                try:
                    t.insert([row], on_error="ignore")
                    inserted += 1
                except Exception:
                    errs += 1
        if progress:
            progress(min(i + batch, total), total)
    sync.last_errors = errs
    return inserted


sync.last_errors = 0


def rebuild(items, progress=None, batch: int = 400):
    """Nuke and re-embed from scratch — the clean cure for a corrupted / duplicate-index
    table. Drops the sidecar table (plus any stale dev-probe tables), forgets the cached
    handle, then a fresh sync() recreates ONE clean named index and re-embeds every image.
    Returns rows inserted (skipped-row count on sync.last_errors, via sync())."""
    # Drop failures used to be swallowed here, which is how a broken table survived a
    # "rebuild": the drop failed, sync() then hit the same unreadable metadata, and the job
    # reported a confusing downstream error instead of the real one. The MAIN table's failure is
    # now raised with instructions; the dev-probe tables stay best-effort, since their absence is
    # normal and their presence is incidental.
    try:
        pxt.drop_table(_TBL, force=True, if_not_exists="ignore")
    except Exception as e:
        raise RuntimeError(
            "Could not drop the existing similarity index, so it cannot be rebuilt in place: "
            "{}. This happens when the stored index metadata is no longer readable by the "
            "installed Pixeltable -- every API call that touches the table, including the drop, "
            "has to load that metadata first. Clear Pixeltable's store directory "
            "(~/.pixeltable) and run this again. That directory holds this index plus Pixeltable's "
            "own media and file caches -- roughly 300 MB here -- and every byte of it is "
            "regenerable from the image library, so clearing it loses no original data."
            .format(e)) from e
    for name in ("mg_probe.imgs", "mg_probe2.imgs", "mg_probe4.imgs"):
        try:
            pxt.drop_table(name, force=True, if_not_exists="ignore")
        except Exception:
            pass
    for d in ("mg_probe", "mg_probe2", "mg_probe4"):
        try:
            pxt.drop_dir(d, force=True)
        except Exception:
            pass
    _table.clear()                      # forget cached handle -> _get_table recreates fresh
    return sync(items, progress=progress, batch=batch)


def similar(query_path, k: int = 48, exclude_media_id=None):
    """Return [(media_id, score)] for the k images most visually similar to query_path,
    dropping the query's own row (a self-match scores 1.0)."""
    t = _get_table()
    sim = t.img.similarity(image=str(query_path), idx=_IDX)
    rows = t.order_by(sim, asc=False).limit(k + 1).select(t.media_id, score=sim).collect()
    out = []
    for r in rows:
        if exclude_media_id is not None and r["media_id"] == str(exclude_media_id):
            continue
        out.append((r["media_id"], float(r["score"])))
        if len(out) >= k:
            break
    return out


def scan_dir(root, cap=None):
    """Helper: yield (media_id, path) for every embeddable image under root
    (media_id = INVARIANT 1). For bootstrap builds off the organized backup tree.

    The similarity index's view of the ONE library scan (moonglade_gallery.py's
    "LIBRARY SCAN" section). It asks for two things the other nine walkers do not:

      * kinds=("embeddable",) -- {.png,.jpg,.jpeg,.webp}, deliberately NARROWER
        than the shared image set, which also carries .gif and .avif. Those are
        real library images; they are just not fed to CLIP. (Named disagreement 1
        in the scan's header -- a caller choice, not a bug to widen.)
      * QUARANTINE_EXCLUDE_ANYWHERE -- gallery/ (thumbnails) plus the two
        quarantine dirs, _duplicates/ (--dedup) and _deleted/ (gallery delete),
        matched by directory NAME at any depth UNDER root rather than as
        top-level subtrees, so a purged or quarantined image never gets
        (re-)embedded. Matching under root (not against the absolute path) is what
        stops an ANCESTOR folder that happens to share one of these names -- a
        library at D:\\Photos\\Gallery\\pixai_backup -- from skipping every image
        in the library and building an EMPTY index with no error.

    The gallery is imported here rather than at module top because the dependency
    only runs one way at import time: the gallery imports THIS module lazily,
    inside its /api/similar handler.
    """
    from moonglade_gallery import scan_library, QUARANTINE_EXCLUDE_ANYWHERE
    n = 0
    for e in scan_library(root, kinds=("embeddable",),
                          exclude=QUARANTINE_EXCLUDE_ANYWHERE):
        yield (e.media_id, e.path)
        n += 1
        if cap and n >= cap:
            return


# This module must be IMPORTED, never run as `python moonglade_similar.py` — Pixeltable rejects
# UDFs defined in the __main__ namespace. Drive builds via a runner that does
# `import moonglade_similar; moonglade_similar.sync(moonglade_similar.scan_dir(root))` or the gallery/panel.
