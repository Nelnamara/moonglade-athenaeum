import React, { useEffect, useState } from "react";
import { apiGet } from "../api.js";
import { sceneRows, shapeTally } from "../gen/sceneCatalog.js";
import "../styles/ai-tools.css";

/* The Bridge §4 "AI Tools — a browsable catalog" (The Bridge.dc.html 247-293). Its own modal,
   launched from the nav when the mirror is armed (DECISIONS: "the AI-Tools tier splits by function —
   browse in a nav modal, generate in the gen drawer"). Browsing lives here (grid · search · tier
   tabs); picking a scene hands off to the gen drawer's generator (onPick). Each card carries the
   scene's real captured thumbnail and its control-row SHAPE so you know before opening whether it's
   one tap or a form. Thumbnails resolve loose-then-container via /branding/bridge/scene_*.webp
   (matching the branding contract), then fall back to the catalog's own art for a scene we ship no
   local webp for, then to the initial.

   THE GRID IS LIVE (issue #36, 2026-09-04). It used to be a hardcoded 28-entry array, so the
   scenes PixAI has added since — daily-fortune, daily-setlog, mini-mart-ad — had no tile and were
   unreachable. It now comes from GET /api/scenes (listChatEditingScenes, normalized server-side);
   gen/sceneCatalog.js holds the curated copy overlaid on those rows and the 28-tile OFFLINE
   FALLBACK, so the modal is never empty. Same tiles, same layout — only the source changed. */

/* The control chip's five colours follow the HUE LAW (handoff comp A4, pick 1g, committed
   2026-09-04): 1-Click emerald · Select lavender · Text gold · Language cyan · Dual mauve.
   Three of them moved with that pass -- 1-Click was gunmetal (the dead-tier grey, which
   read as "unavailable" on the tiles that need the least work), Text was peach and
   Language sapphire, neither of which is a hue this app assigns meaning to. No new hues:
   every value below is an existing token. */
const SHAPE = {
  click:  { label: "1-Click",  color: "var(--emerald)" },
  select: { label: "Select",   color: "var(--lavender)" },
  text:   { label: "Text",     color: "var(--gold)" },
  lang:   { label: "Language", color: "var(--loomc, #47cbc3)" },
  dual:   { label: "Dual",     color: "var(--mauve)" },
};

export default function AiToolsModal({ open, onClose, onPick }) {
  const [q, setQ] = useState("");
  const [tier, setTier] = useState("all");
  const [live, setLive] = useState(null);   // null until /api/scenes answers; [] on failure

  // Esc closes the top layer, like the drawer's overlays.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === "Escape") onClose && onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // The live catalog, read once per open. apiGet never throws and never retries (api.js's one
  // rule), so a refusal, an outage or an unarmed mirror all land the same way: [] -> the
  // curated 28 render instead of an empty grid.
  useEffect(() => {
    if (!open) return undefined;
    let alive = true;
    apiGet("/api/scenes").then((d) => {
      if (alive) setLive((d && !d.error && d.scenes) || []);
    });
    return () => { alive = false; };
  }, [open]);

  if (!open) return null;

  const scenes = sceneRows(live);
  const TIERS = [["all", "All " + scenes.length], ["free", "Free"], ["tier1", "Tier 1"]];

  const shown = scenes.filter((s) =>
    (tier === "all" || (tier === "tier1" && s.tier) || (tier === "free" && !s.tier)) &&
    (!q.trim() || s.name.toLowerCase().includes(q.trim().toLowerCase())));

  return (
    <div className="mgai-scrim" onClick={onClose}>
      <div className="mgai-modal" role="dialog" aria-label="AI Tools" onClick={(e) => e.stopPropagation()}>
        <div className="mgai-head">
          <div className="mgai-title">✦ AI Tools</div>
          <div className="mgai-armed">● mirror armed</div>
          <div className="mgai-search">
            <span aria-hidden="true">⌕</span>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search tools…" aria-label="Search tools" />
          </div>
          <div className="mgai-tiers">
            {TIERS.map(([id, lbl]) => (
              <button key={id} type="button" className={"mgai-tier" + (tier === id ? " on" : "")}
                onClick={() => setTier(id)}>{lbl}</button>
            ))}
          </div>
          <button type="button" className="mgai-x" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {/* the SCROLLER wraps the grid rather than being it -- see ai-tools.css's note on
            .mgai-scroll: a grid that is also the scroll container sized its rows before the
            track width was known, and every card came out 48px tall */}
        <div className="mgai-scroll">
        <div className="mgai-grid">
          {shown.map((s) => {
            const m = SHAPE[s.shape] || SHAPE.click;
            return (
              <button key={s.slug} type="button" className="mgai-card"
                onClick={() => onPick && onPick({ name: s.name, slug: s.slug, shape: s.shape,
                                                  tier: s.tier, detail: s.detail })}
                title={s.name}>
                {/* 16:10 art on top (handoff comp A4): the thumbnail is the card now, not a
                    strip above the label. The fallback chain is unchanged and is the comp's
                    own: curated local webp -> the catalog's PixAI demo image -> the gradient
                    + serif-initial placeholder underneath. Never an empty strip.
                    The art is shown WHOLE, never cropped (ai-tools.css carries the why); the
                    two lines below are what that costs -- on load, the art box learns that it
                    has a picture (so the initial steps aside) and which URL actually won (so
                    the blurred backdrop behind the picture is that same image). */}
                <div className="mgai-art">
                  <span className="mgai-initial">{s.name[0]}</span>
                  <img src={"/branding/bridge/scene_" + s.slug + ".webp"} alt="" loading="lazy"
                    onLoad={(e) => {
                      const el = e.currentTarget;
                      const box = el.parentNode;
                      if (!box) return;
                      box.style.setProperty("--mgai-art", 'url("' + (el.currentSrc || el.src) + '")');
                      box.classList.add("has-art");
                    }}
                    onError={(e) => {
                      // No local art for this scene -> try the catalog's own thumbnail once,
                      // then give up and let the initial show through.
                      const el = e.currentTarget;
                      if (s.thumb && el.dataset.fell !== "1") { el.dataset.fell = "1"; el.src = s.thumb; return; }
                      el.style.display = "none";
                    }} />
                  {s.tier ? <span className="mgai-tierbadge">Tier 1</span> : null}
                  {/* the control chip is pinned top-right OVER the art, hue-law coloured --
                      it says how much work the tool needs before you open it */}
                  <span className="mgai-chip" style={{ color: m.color, borderColor: m.color }}>{m.label}</span>
                </div>
                <div className="mgai-meta">
                  <div className="mgai-name">{s.name}</div>
                  {s.detail ? <div className="mgai-detail">{s.detail}</div> : null}
                </div>
              </button>
            );
          })}
          {shown.length === 0 ? <div className="mgai-empty">No tools match “{q}”.</div> : null}
        </div>
        </div>

        <div className="mgai-foot">
          <span><b>{shown.length}</b> shown</span>
          <span className="mgai-tally">{shapeTally(scenes)}</span>
        </div>
      </div>
    </div>
  );
}
