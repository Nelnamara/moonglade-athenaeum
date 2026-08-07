import React, { useEffect, useRef, useState } from "react";
import "../styles/overlays.css";
import "../styles/publish.css";
import useScrollLock from "../hooks/useScrollLock.js";

/* Publish panel — Frontend Gallery.dc.html's ovPublish (markup 294-390, values
   2890-2937), built on the real publish pipeline (POST /api/myart/publish).

   Shell per the design: min(1040px) slab, "Publish artwork" header, two-column body
   (minmax(300px,440px) 1fr) with each column its own scroll. Left = the real image
   with its real dimensions/model as SOURCE; right = title/description/tags/contest
   and the toggles, ending in the metallic Publish button.

   Real-data adaptations from the DC, disclosed:
   - The DC's "choose a different image" strip is a pool of blank aspect swatches
     (PUB_PICKS). Real art has to come from the real library, so that row opens the
     SHARED <mg-gallery-picker> the Loom and the Branding banner editor already use,
     rather than a second, parallel image-chooser. "Browse from disk" is dropped for
     the same reason: you publish something already in your library, and the picker
     is how this app has always answered "pick one of my images".
   - Tags are free text here, not the DC's fixed PUBLISH_TAGS list: PixAI resolves
     tags to real "tack" ids server-side, and the confirm step reports any that don't
     resolve instead of pretending a made-up list is authoritative.
   - Contest is populated from the live GET /api/contests feed (the same one the
     Contests overlay shows), not a demo list.
   - The ✦ suggest-a-title popover is NOT built this pass; the prompt already prefills
     the title, and a real suggestion would be a spend-adjacent call. Left out rather
     than faked.

   Nothing reaches the PixAI account until the confirm step: the panel asks the server
   for a preview (what it would do, which tags resolved, which image of the batch it
   worked out) and only then sends confirm: true. */

export default function PublishOverlay({ mediaId, onClose, onPublished }) {
  useScrollLock();
  const [row, setRow] = useState(null);
  const [err, setErr] = useState("");
  const [csrf, setCsrf] = useState("");
  const [contests, setContests] = useState([]);
  const [mid, setMid] = useState(mediaId || "");

  const [title, setTitle] = useState("");
  const [desc, setDesc] = useState("");
  const [tags, setTags] = useState([]);
  const [tagDraft, setTagDraft] = useState("");
  const [contest, setContest] = useState("");
  const [priv, setPriv] = useState(false);
  const [hidePrompts, setHidePrompts] = useState(false);

  const [ask, setAsk] = useState(null);      // the server's preview, awaiting confirm
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  const [picking, setPicking] = useState(false);
  const pickerRef = useRef(null);

  // Prefill from the real catalog row -- title, tags and prompt are already there.
  useEffect(() => {
    if (!mid) return;
    let dead = false;
    setRow(null); setErr("");
    fetch("/api/next/detail/" + encodeURIComponent(mid))
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then((d) => {
        if (dead) return;
        const r0 = d.row || {};
        setRow(r0);
        setTitle((r0.title || "").trim() || (r0.prompt_preview || "").trim().slice(0, 80));
        setTags((r0.art_tags || "").split(",").map((s) => s.trim()).filter(Boolean));
        setDesc("");
      })
      .catch((e) => { if (!dead) setErr(String(e.message || e)); });
    return () => { dead = true; };
  }, [mid]);

  // CSRF rides on /api/myart/items (MG_BOOT doesn't carry it); contests are the live feed.
  useEffect(() => {
    fetch("/api/myart/items").then((r) => r.json()).then((d) => setCsrf(d.csrf || "")).catch(() => {});
    fetch("/api/contests").then((r) => r.json())
      .then((d) => setContests((d.contests || []).filter((c) => c && c.title)))
      .catch(() => {});
  }, []);

  const bindPicker = (el) => {
    pickerRef.current = el;
    if (el && !el._mgBound) {
      el._mgBound = true;
      el.addEventListener("mg-pick", (e) => { setPicking(false); setMid(e.detail.media_id); });
      el.addEventListener("mg-close", () => setPicking(false));
    }
  };

  const addTag = (raw) => {
    const t = String(raw || "").replace(/^#/, "").trim();
    if (t && !tags.includes(t)) setTags(tags.concat([t]));
    setTagDraft("");
  };

  const post = (extra) => fetch("/api/myart/publish", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      action: "publish", media_id: mid, csrf,
      title, description: desc, tags, private: priv, hide_prompts: hidePrompts,
      ...(contest ? { challenge: contest } : {}),
      ...extra,
    }),
  }).then((r) => r.json());

  const preview = async () => {
    setBusy(true); setErr("");
    try {
      const p = await post({});
      if (p.error) { setErr(p.error); return; }
      setAsk(p);
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  };

  const confirm = async () => {
    setBusy(true); setErr("");
    try {
      const res = await post({ confirm: true });
      if (res.error) { setErr(res.error); setAsk(null); return; }
      setDone(res);
      if (onPublished) onPublished(mid);
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  };

  const already = row && (row.artwork_id || "").trim();
  const dims = row && row.width && row.height ? row.width + "×" + row.height : "";
  const srcLabel = [dims, row && (row.model_name || row.model_id)].filter(Boolean).join(" · ");
  const aspect = row && row.width && row.height ? row.width + " / " + row.height : "1 / 1";

  return (
    <>
      <div className="mgv-scrim" onClick={onClose} />
      <div className="mgv-host">
        <div className="mgpub-slab" role="dialog" aria-label="Publish artwork">
          <div className="mgpub-head">
            <div className="mgpub-title">Publish artwork</div>
            <button type="button" className="mgv-x" onClick={onClose} aria-label="Close">×</button>
          </div>

          <div className="mgpub-body">
            {/* LEFT: the real image + where it came from */}
            <div className="mgpub-left">
              <div className="mgpub-frame" style={{ aspectRatio: aspect }}>
                {mid ? <img src={"/full/" + encodeURIComponent(mid)} alt="" /> : null}
                <div className="mgpub-gloss" />
              </div>
              <div className="mgpub-srcrow">
                <span className="k">SOURCE</span>
                <span className="v">{srcLabel || (mid ? "loading…" : "nothing picked yet")}</span>
              </div>
              <button type="button" className="mgpub-browse" onClick={() => setPicking(true)}>
                🖼 Choose a different image…
              </button>
              {already ? (
                <div className="mgpub-note warn">
                  This one is already published on PixAI. Use My Art to change its
                  visibility, tags or to remove it.
                </div>
              ) : null}
            </div>

            {/* RIGHT: the form */}
            <div className="mgpub-right">
              <label className="mgpub-lab">Title</label>
              <input className="mgpub-in" value={title} placeholder="Describe your artwork."
                onChange={(e) => setTitle(e.target.value)} />

              <label className="mgpub-lab">Description</label>
              <textarea className="mgpub-in" rows={3} value={desc}
                onChange={(e) => setDesc(e.target.value)} />

              <label className="mgpub-lab">Tags</label>
              <div className="mgpub-tagbox">
                {tags.map((t) => (
                  <span className="mgpub-chip" key={t} title="Remove"
                    onClick={() => setTags(tags.filter((x) => x !== t))}>{t} ×</span>
                ))}
                <input className="mgpub-taginput" value={tagDraft}
                  placeholder={tags.length ? "" : "Select the tags related to your artwork."}
                  onChange={(e) => setTagDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addTag(tagDraft); }
                    else if (e.key === "Backspace" && !tagDraft && tags.length) setTags(tags.slice(0, -1));
                  }}
                  onBlur={() => addTag(tagDraft)} />
              </div>
              <div className="mgpub-hint">
                Tags are matched to PixAI's own tag list when you publish — anything it
                can't match is reported before the upload, not dropped quietly.
              </div>

              {contests.length > 0 && (
                <>
                  <label className="mgpub-lab">Contest</label>
                  <select className="mgpub-in" value={contest} onChange={(e) => setContest(e.target.value)}>
                    <option value="">Not entering a contest</option>
                    {contests.map((c) => (
                      <option key={c.id} value={c.id}>{c.title}</option>
                    ))}
                  </select>
                </>
              )}

              <label className="mgpub-toggle">
                <input type="checkbox" checked={priv} onChange={(e) => setPriv(e.target.checked)} />
                <span>Keep it private — visible only to you on PixAI</span>
              </label>
              <label className="mgpub-toggle">
                <input type="checkbox" checked={hidePrompts} onChange={(e) => setHidePrompts(e.target.checked)} />
                <span>Hide the prompt from other people</span>
              </label>

              {err && <div className="mgpub-note err">⚠ {err}</div>}

              {done ? (
                <div className="mgpub-note ok">
                  ✓ Published. It's on your PixAI profile now
                  {done.unmatched_tags && done.unmatched_tags.length > 0
                    ? " — these tags didn't exist on PixAI and weren't attached: " + done.unmatched_tags.join(", ")
                    : "."}
                </div>
              ) : ask ? (
                <div className="mgpub-confirm">
                  <div className="t">Publish this to your PixAI profile?</div>
                  <div className="b">
                    <b>{title || "(untitled)"}</b>
                    {ask.tack_ids && <> · {ask.tack_ids.length} tag{ask.tack_ids.length === 1 ? "" : "s"}</>}
                    {ask.unmatched_tags && ask.unmatched_tags.length > 0 && (
                      <span className="warn"> · not on PixAI, won't be attached: {ask.unmatched_tags.join(", ")}</span>
                    )}
                    {typeof ask.media_index === "number" && <> · image {ask.media_index + 1} of its batch</>}
                    {priv && <> · private</>}
                    <div className="n">No credits are spent by publishing.</div>
                  </div>
                  <div className="a">
                    <button type="button" className="mgpub-ghost" onClick={() => setAsk(null)} disabled={busy}>Back</button>
                    <button type="button" className="mgpub-go" onClick={confirm} disabled={busy}>
                      {busy ? "publishing…" : "Publish it"}
                    </button>
                  </div>
                </div>
              ) : (
                <button type="button" className="mgpub-go big" disabled={busy || !mid || !!already}
                  onClick={preview}>
                  {busy ? "checking…" : "✦ Publish"}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
      {picking && <mg-gallery-picker ref={bindPicker} default-type="image"></mg-gallery-picker>}
    </>
  );
}
