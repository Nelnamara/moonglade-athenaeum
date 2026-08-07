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

   Built AS SPECIFIED. Where the DC carries demo data, the same control is wired to
   the real equivalent (the standing rule: the design wins every visible question):
   - "CHOOSE A DIFFERENT IMAGE" is the DC's inline horizontal strip, exactly as drawn
     -- its PUB_PICKS blank aspect swatches replaced by REAL recent library images at
     the same 52px-tall, aspect-derived-width geometry and the same selected outline.
     (An earlier pass wrongly substituted a modal picker for this strip; corrected
     2026-08-06.) The shared <mg-gallery-picker> is offered ALONGSIDE it for reaching
     past the recent window, not instead of it.
   - The ✦ suggest-a-title popover is REAL: GET /api/suggest-prompt (PixAI's own
     image-to-prompt, free and read-only -- an earlier pass skipped this on a wrong
     "spend-adjacent" assumption; suggest_prompt is documented FREE).
   - Tags use the DC's chips + dropdown, with the options coming from PixAI's live tag
     search (GET /api/tag-suggest, free) instead of the DC's fixed demo PUBLISH_TAGS
     list; free text still commits on Enter so nothing is unreachable.
   - Contest is populated from the live GET /api/contests feed, not a demo list.

   ONE control is NOT built and is a REAL blocker, not a preference: the DC's
   "⬆ Browse from disk…". Publishing an arbitrary uploaded file goes through PixAI's
   createFromMedia path, which their own form gates behind a Cloudflare TURNSTILE
   captcha (X-Turnstile-Token, action "artworkUpload" -- see the harvested SubmitForm
   chunk). Solving or bypassing a captcha is off-limits, so this control cannot be
   made to work honestly from here; it is surfaced to the owner rather than silently
   dropped. Publishing from the library (createArtworkFromTaskV2) has no such gate,
   which is why everything else here works.

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
  // The DC's inline "choose a different image" strip, on real recent library images.
  const [strip, setStrip] = useState([]);
  // ✦ suggest-a-title: PixAI's own image-to-prompt (free, read-only).
  const [sugOpen, setSugOpen] = useState(false);
  const [sugs, setSugs] = useState(null);
  // Tag dropdown backed by PixAI's live tag search (free).
  const [tagOpts, setTagOpts] = useState([]);
  const [tagOpen, setTagOpen] = useState(false);

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

  // CSRF rides on /api/myart/items (MG_BOOT doesn't carry it); contests are the live
  // feed; the strip is the real recent library (images only -- the DC's swatch pool,
  // with actual art in it).
  useEffect(() => {
    fetch("/api/myart/items").then((r) => r.json()).then((d) => setCsrf(d.csrf || "")).catch(() => {});
    fetch("/api/contests").then((r) => r.json())
      .then((d) => setContests((d.contests || []).filter((c) => c && c.title)))
      .catch(() => {});
    fetch("/api/next/library?page=1&page_size=24&media=image&sort=newest")
      .then((r) => r.json()).then((d) => setStrip((d.items || []).slice(0, 24)))
      .catch(() => {});
  }, []);

  // ✦ Suggest a title -- PixAI's image-to-prompt for THIS image. Free and read-only
  // (core.suggest_prompt's own docstring says so); fetched only when the popover opens.
  const openSuggest = () => {
    setSugOpen(!sugOpen);
    if (sugOpen || sugs || !mid) return;
    setSugs("loading");
    fetch("/api/suggest-prompt?media_id=" + encodeURIComponent(mid))
      .then((r) => r.json())
      .then((d) => setSugs((d.suggestions || []).filter(Boolean)))
      .catch(() => setSugs([]));
  };

  // Live tag options as you type (free tag search), the DC's dropdown with real data.
  useEffect(() => {
    const q = tagDraft.trim();
    if (q.length < 2) { setTagOpts([]); return; }
    let dead = false;
    const t = setTimeout(() => {
      fetch("/api/tag-suggest?q=" + encodeURIComponent(q))
        .then((r) => r.json())
        .then((d) => { if (!dead) setTagOpts((d.tags || []).slice(0, 8)); })
        .catch(() => {});
    }, 220);
    return () => { dead = true; clearTimeout(t); };
  }, [tagDraft]);

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
              {/* DC L314-321 -- the inline strip, at the DC's own geometry (52px tall,
                  width from the image's aspect, accent outline on the selected one),
                  carrying real recent art instead of blank swatches. */}
              <div className="mgpub-pickhead">CHOOSE A DIFFERENT IMAGE</div>
              <div className="mgpub-strip">
                {strip.map((s) => {
                  const w = Math.round(52 * ((s.w || 1) / (s.h || 1)));
                  return (
                    <button type="button" key={s.media_id} title={(s.w || "?") + "×" + (s.h || "?")}
                      className={"mgpub-swatch" + (s.media_id === mid ? " on" : "")}
                      style={{ width: Math.max(28, Math.min(w, 120)) + "px" }}
                      onClick={() => setMid(s.media_id)}>
                      <img src={s.thumb} alt="" loading="lazy" />
                    </button>
                  );
                })}
              </div>
              <button type="button" className="mgpub-browse" onClick={() => setPicking(true)}>
                🖼 Browse the whole library…
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
              {/* DC L326-340 -- title input + the ✦ suggest popover, on PixAI's own
                  free image-to-prompt for this exact image. */}
              <div className="mgpub-titlerow">
                <input className="mgpub-in" value={title} placeholder="Describe your artwork."
                  onChange={(e) => setTitle(e.target.value)} />
                <button type="button" title="Suggest a title from the image"
                  className={"mgpub-suggest" + (sugOpen ? " on" : "")}
                  disabled={!mid} onClick={openSuggest}>✦</button>
                {sugOpen && (
                  <div className="mgpub-sugpop">
                    <div className="h">Suggested Titles</div>
                    {sugs === "loading" && <div className="m">reading the image…</div>}
                    {Array.isArray(sugs) && sugs.length === 0 && <div className="m">nothing came back for this one.</div>}
                    {Array.isArray(sugs) && sugs.map((s, i) => (
                      <button type="button" className="mgpub-sugitem" key={i}
                        onClick={() => { setTitle(String(s).slice(0, 140)); setSugOpen(false); }}>
                        {String(s).slice(0, 140)}
                      </button>
                    ))}
                  </div>
                )}
              </div>

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
                  onChange={(e) => { setTagDraft(e.target.value); setTagOpen(true); }}
                  onFocus={() => setTagOpen(true)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addTag(tagDraft); setTagOpen(false); }
                    else if (e.key === "Backspace" && !tagDraft && tags.length) setTags(tags.slice(0, -1));
                    else if (e.key === "Escape") setTagOpen(false);
                  }} />
              </div>
              {/* DC L343-358's dropdown, with PixAI's live tag search behind it instead
                  of the mock's fixed list -- so what you pick is a tag that really exists. */}
              {tagOpen && tagOpts.length > 0 && (
                <div className="mgpub-tagmenu">
                  {tagOpts.filter((t) => !tags.includes(t)).map((t) => (
                    <button type="button" className="mgpub-tagopt" key={t}
                      onClick={() => { addTag(t); setTagOpen(false); }}>{t}</button>
                  ))}
                </div>
              )}
              <div className="mgpub-hint">
                Picking from the list guarantees the tag exists on PixAI. Typed tags are
                matched when you publish — anything that can't be matched is reported
                before the upload, not dropped quietly.
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
