"""Moonglade Athenaeum — "more like this" visual similarity.

A SIDECAR index over the catalog's images: CLIP embeddings held in a Pixeltable table,
GPU-embedded via a custom UDF (Pixeltable's stock `huggingface.clip` runs on CPU ~13 img/s;
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
_DIM = 512

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
                    t.add_embedding_index("img", idx_name=_IDX, embedding=clip_gpu,
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
    for name in (_TBL, "mg_probe.imgs", "mg_probe2.imgs", "mg_probe4.imgs"):
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
    """Helper: yield (media_id, path) for every image under root (media_id = INVARIANT 1,
    the last '_'-delimited stem chunk). For bootstrap builds off the organized backup tree.

    Skips gallery/ (thumbnails) plus the two quarantine dirs, _duplicates/ (--dedup) and
    _deleted/ (gallery delete) -- the same exclusion set pixai_gallery.py's
    find_image_file/find_files_for_media_id use (INVARIANT 6), so a purged or quarantined
    image never gets (re-)embedded into the similarity index."""
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    excluded_dirs = {"gallery", "_duplicates", "_deleted"}
    n = 0
    for p in Path(root).rglob("*"):
        if p.suffix.lower() in exts and not excluded_dirs & {q.lower() for q in p.parts}:
            yield (p.stem.split("_")[-1], p)
            n += 1
            if cap and n >= cap:
                return


# This module must be IMPORTED, never run as `python pixai_similar.py` — Pixeltable rejects
# UDFs defined in the __main__ namespace. Drive builds via a runner that does
# `import pixai_similar; pixai_similar.sync(pixai_similar.scan_dir(root))` or the gallery/panel.
