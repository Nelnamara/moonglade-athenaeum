import React, { useEffect, useState } from "react";
import useSheet from "../hooks/useSheet.js";
import MobileSheet from "./MobileSheet.jsx";
import "../styles/publish.css";
import "../styles/publish-mobile.css";

/* Publish -- mobile, replaces the "no backend route" placeholder (2026-08-07,
   Moonglade Mobile.dc.html screenIsPublish + the pubconfirm sheet). Single column;
   real data throughout, the exact real pipeline desktop's PublishOverlay.jsx already
   proved: /api/next/detail (prefill), /api/myart/items (csrf), /api/next/library
   (recent-image strip), /api/suggest-prompt (✦ suggest a title), /api/tag-suggest
   (live tag search), /api/contests (real contest list), /api/myart/publish
   (preview-then-confirm).

   Real-data adaptations from the design's own placeholder content, same standard every
   prior mobile surface this session discloses rather than deciding silently:
   - "Choose a different image" strip: real recent library images, same as desktop.
   - Tags: the design's Tags row uses a fixed demo pool (SUGGEST_TAGS); wired to the
     same live PixAI tag search desktop uses.
   - The design's separate "Feature" row (a SECOND tag-chip list, FEATURE_LIST) doesn't
     map to any field PixAI's real publish mutation accepts (confirmed against the
     harvested submit form: title/description/tags(as tackIds)/visibility/hidePrompts/
     challenge only -- no "feature" concept). Read as the design's own duplicate/second
     tag-suggestion affordance rather than a distinct field, and folded into the one
     real Tags control instead of building a second, meaningless one.
   - Browse from disk: omitted, same as desktop's PublishOverlay.jsx. NOT a settled
     "captcha blocks it" -- corrected 2026-08-07, see that file's header comment and
     docs/DECISIONS.md's 2026-08-07 scoping entry. Whether PixAI's REST createFromMedia
     endpoint actually enforces its documented Turnstile requirement is unresolved;
     omitted here pending that answer, not pending a design decision.
   Preview -> confirm gate matches the design: "Preview & publish ->" opens a confirm
   sheet: preview + title + visibility/contest/tag summary; Back / Confirm & publish. */

export default function PublishMobile({ mediaId, onClose, onPublished }) {
  const [mid, setMid] = useState(mediaId || "");
  const [row, setRow] = useState(null);
  const [err, setErr] = useState("");
  const [csrf, setCsrf] = useState("");
  const [contests, setContests] = useState([]);
  const [strip, setStrip] = useState([]);

  const [title, setTitle] = useState("");
  const [desc, setDesc] = useState("");
  const [tags, setTags] = useState([]);
  const [tagDraft, setTagDraft] = useState("");
  const [tagOpts, setTagOpts] = useState([]);
  const [contest, setContest] = useState("");
  const [priv, setPriv] = useState(false);
  const [hidePrompts, setHidePrompts] = useState(false);

  // 'confirm' | null -- shared timer-safe machine (hooks/useSheet.js)
  const { sheet, closing, open: openSheet, close: closeSheet } = useSheet(280);
  const [ask, setAsk] = useState(null);
  const [done, setDone] = useState(null);
  const [busy, setBusy] = useState(false);
  const [sugs, setSugs] = useState(null);


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
      })
      .catch((e) => { if (!dead) setErr(String(e.message || e)); });
    setSugs(null);
    return () => { dead = true; };
  }, [mid]);

  useEffect(() => {
    fetch("/api/myart/items").then((r) => r.json()).then((d) => setCsrf(d.csrf || "")).catch(() => {});
    fetch("/api/contests").then((r) => r.json())
      .then((d) => setContests((d.contests || []).filter((c) => c && c.title)))
      .catch(() => {});
    fetch("/api/next/library?page=1&page_size=18&media=image&sort=newest")
      .then((r) => r.json()).then((d) => setStrip((d.items || []).slice(0, 18))).catch(() => {});
  }, []);

  useEffect(() => {
    const q = tagDraft.trim();
    if (q.length < 2) { setTagOpts([]); return; }
    let dead = false;
    const t = setTimeout(() => {
      fetch("/api/tag-suggest?q=" + encodeURIComponent(q))
        .then((r) => r.json())
        .then((d) => { if (!dead) setTagOpts((d.tags || []).slice(0, 6)); })
        .catch(() => {});
    }, 220);
    return () => { dead = true; clearTimeout(t); };
  }, [tagDraft]);

  const addTag = (raw) => {
    const t = String(raw || "").replace(/^#/, "").trim();
    if (t && !tags.includes(t)) setTags(tags.concat([t]));
    setTagDraft("");
  };

  const runSuggest = () => {
    if (!mid || sugs) return;
    setSugs("loading");
    fetch("/api/suggest-prompt?media_id=" + encodeURIComponent(mid))
      .then((r) => r.json())
      .then((d) => { const s = (d.suggestions || []).filter(Boolean); setSugs(s); if (s[0]) setTitle(String(s[0]).slice(0, 140)); })
      .catch(() => setSugs([]));
  };

  const post = (extra) => fetch("/api/myart/publish", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      action: "publish", media_id: mid, csrf,
      title, description: desc, tags, private: priv, hide_prompts: hidePrompts,
      ...(contest ? { challenge: contest } : {}), ...extra,
    }),
  }).then((r) => r.json());

  const openConfirm = async () => {
    setBusy(true); setErr("");
    try {
      const p = await post({});
      if (p.error) { setErr(p.error); setBusy(false); return; }
      setAsk(p); openSheet("confirm");
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  };
  const confirm = async () => {
    setBusy(true); setErr("");
    try {
      const res = await post({ confirm: true });
      // Close the sheet on failure -- the error note renders in the main form,
      // UNDER the sheet's scrim; leaving the sheet up showed the user nothing
      // (desktop PublishOverlay collapses its ask the same way).
      if (res.error) { setErr(res.error); closeSheet(); return; }
      setDone(res); closeSheet();
      if (onPublished) onPublished(mid);
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  };

  const dims = row && row.width && row.height ? row.width + "×" + row.height : "";
  const srcLabel = [dims, row && (row.model_name || row.model_id)].filter(Boolean).join(" · ");
  const aspect = row && row.width && row.height ? row.width + " / " + row.height : "1 / 1";
  const already = row && (row.artwork_id || "").trim();

  return (
    <div className="pubm-wrap">
      {done ? (
        <div className="pubm-donebox">
          ✓ Published{done.unmatched_tags && done.unmatched_tags.length > 0
            ? " — these tags didn't exist on PixAI and weren't attached: " + done.unmatched_tags.join(", ") : "."}
        </div>
      ) : (
        <>
          <div className="pubm-frame" style={{ aspectRatio: aspect }}>
            {mid ? <img src={"/full/" + encodeURIComponent(mid)} alt="" /> : null}
          </div>
          <div className="pubm-srcrow"><span className="k">SOURCE</span><span className="v">{srcLabel || "loading…"}</span></div>

          <div className="pubm-lab">Choose a different image</div>
          <div className="pubm-stripwrap">
            {strip.map((s) => (
              <button type="button" key={s.media_id}
                className={"pubm-swatch" + (s.media_id === mid ? " on" : "")}
                onClick={() => setMid(s.media_id)}>
                <img src={s.thumb} alt="" />
              </button>
            ))}
          </div>

          {already ? (
            <div className="pubm-note warn">Already published on PixAI — use My Art to change it.</div>
          ) : (
            <>
              <div className="pubm-lab">Title</div>
              <div className="pubm-titlerow">
                <input className="pubm-in" value={title} placeholder="Describe your artwork."
                  onChange={(e) => setTitle(e.target.value)} />
                <button type="button" className="pubm-suggest" onClick={runSuggest}>✦</button>
              </div>
              {sugs === "loading" && <div className="pubm-hint">reading the image…</div>}
              {Array.isArray(sugs) && sugs.length > 0 && (
                <div className="pubm-sugrow">
                  {sugs.slice(0, 3).map((s, i) => (
                    <button type="button" key={i} className="pubm-sugchip"
                      onClick={() => setTitle(String(s).slice(0, 140))}>{String(s).slice(0, 28)}…</button>
                  ))}
                </div>
              )}

              <div className="pubm-lab">Description</div>
              <textarea className="pubm-in" rows={3} value={desc} onChange={(e) => setDesc(e.target.value)} />

              <div className="pubm-lab">Tags</div>
              <div className="pubm-tagbox">
                {tags.map((t) => (
                  <span className="pubm-chip" key={t} onClick={() => setTags(tags.filter((x) => x !== t))}>{t} ×</span>
                ))}
                <input className="pubm-taginput" value={tagDraft}
                  placeholder={tags.length ? "" : "add a tag…"}
                  onChange={(e) => setTagDraft(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addTag(tagDraft); } }} />
              </div>
              {tagOpts.length > 0 && (
                <div className="pubm-tagopts">
                  {tagOpts.filter((t) => !tags.includes(t)).map((t) => (
                    <span className="pubm-tagopt" key={t} onClick={() => addTag(t)}>+ {t}</span>
                  ))}
                </div>
              )}

              {contests.length > 0 && (
                <>
                  <div className="pubm-lab">Contest</div>
                  <select className="pubm-in" value={contest} onChange={(e) => setContest(e.target.value)}>
                    <option value="">Not entering a contest</option>
                    {contests.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
                  </select>
                </>
              )}

              <label className="pubm-toggle">
                <input type="checkbox" checked={hidePrompts} onChange={(e) => setHidePrompts(e.target.checked)} />
                <span>Hide Prompts</span>
              </label>
              <label className="pubm-toggle">
                <input type="checkbox" checked={priv} onChange={(e) => setPriv(e.target.checked)} />
                <span>Private</span>
              </label>

              {err && <div className="pubm-note err">⚠ {err}</div>}

              <button type="button" className="pubm-go" disabled={busy || !mid} onClick={openConfirm}>
                {busy ? "checking…" : "Preview & publish →"}
              </button>
            </>
          )}
        </>
      )}

      <MobileSheet open={sheet === "confirm"} closing={closing} onClose={closeSheet} title="READY TO PUBLISH">
        {ask && (
          <>
            <div className="pubm-frame small" style={{ aspectRatio: aspect }}>
              {mid ? <img src={"/full/" + encodeURIComponent(mid)} alt="" /> : null}
            </div>
            <div className="pubm-confirmtitle">{title || "(untitled)"}</div>
            <div className="pubm-confirmmeta">
              {priv ? "Private · only you" : "Public gallery"}
              {contest ? " · entered in a contest" : ""}
              {ask.tack_ids && ask.tack_ids.length ? " · " + ask.tack_ids.length + " tags" : ""}
              {ask.unmatched_tags && ask.unmatched_tags.length > 0
                ? " · not on PixAI: " + ask.unmatched_tags.join(", ") : ""}
            </div>
            <div className="glm-sheet-actions">
              <button type="button" className="glm-metal glm-widebtn" onClick={closeSheet} disabled={busy}>Back</button>
              <button type="button" className="glm-primary glm-widebtn" onClick={confirm} disabled={busy}>
                {busy ? "publishing…" : "Confirm & publish"}
              </button>
            </div>
          </>
        )}
      </MobileSheet>
    </div>
  );
}
