import React, { useEffect, useState } from "react";
import "../styles/ai-tools.css";

/* The Bridge §4 "AI Tools — a browsable catalog of 28" (The Bridge.dc.html 247-293). Its own modal,
   launched from the nav when the mirror is armed (DECISIONS: "the AI-Tools tier splits by function —
   browse in a nav modal, generate in the gen drawer"). Browsing lives here (grid · search · tier
   tabs); picking a scene hands off to the gen drawer's generator (onPick). Each card carries the
   scene's real captured thumbnail and its control-row SHAPE so you know before opening whether it's
   one tap or a form. Thumbnails resolve loose-then-container via /branding/bridge/scene_*.webp
   (onError falls back to the initial, matching the branding contract). */

const SHAPE = {
  click:  { label: "1-Click",  color: "#8a93a2" },
  select: { label: "Select",   color: "var(--lavender)" },
  text:   { label: "Text",     color: "var(--peach)" },
  lang:   { label: "Language", color: "var(--sapphire)" },
  dual:   { label: "Dual",     color: "var(--mauve)" },
};

// [name, slug (thumbnail file), shape, tier, detail] -- from the comp's scene table (475-504),
// slugs matched to the captured scene_*.webp set.
const SCENES = [
  ["Acrylic Standee", "acrylic-standee", "click", false, ""],
  ["Anime Badge", "anime-badge", "click", false, ""],
  ["Anime Figure", "anime-figure", "select", false, "Figure / With-char"],
  ["Blush & Glasses", "blush-and-glasses", "click", true, ""],
  ["Character Ad", "character-ad", "select", true, "Billboard / Pop-up"],
  ["Character Card", "character-card", "lang", true, "+ Other"],
  ["Character Style", "character-style-generator", "lang", true, "EN / JP / KR / TC"],
  ["Chatfic", "chatfic", "lang", true, "EN / JP / KR / TC"],
  ["Christmas", "christmas", "select", false, "Hat / Scarf / Outfit"],
  ["Dakimakura", "dakimakura", "click", false, ""],
  ["Desktop Pet", "desktop-pet", "select", true, "Landscape / Portrait"],
  ["Duo Character", "dual-character-generator", "dual", true, "2 refs · ~26 poses"],
  ["Fantasy Character", "fantasy-character", "select", true, "5 classes"],
  ["Gacha Screen", "gacha-screen", "text", true, "name + lang"],
  ["Galgame", "galgame", "text", true, "name + lang"],
  ["Giant Statue", "giant-statue", "click", false, ""],
  ["JRPG Guide", "jrpg-guidebook", "select", true, "4 classes"],
  ["Lego", "lego", "click", false, ""],
  ["Magazine Cover", "magazine-cover", "click", false, ""],
  ["Paper Cutout", "paper-cutout", "select", true, "Silhouette / Layered"],
  ["Plushie", "plushie", "click", false, ""],
  ["Polaroid", "polaroid", "text", true, "name + lang"],
  ["RPG Gameplay", "rpg-gameplay", "text", true, "name + lang"],
  ["Stadium Big Screen", "stadium-big-screen", "click", true, ""],
  ["Summer Magazine", "summer-magazine", "click", true, ""],
  ["Tarot Card", "tarot-card", "select", false, "4 modes"],
  ["Trading Card", "trading-card", "click", true, ""],
  ["VTuber", "vtuber", "text", true, "name + lang"],
];

const TIERS = [["all", "All " + SCENES.length], ["free", "Free"], ["tier1", "Tier 1"]];

export default function AiToolsModal({ open, onClose, onPick }) {
  const [q, setQ] = useState("");
  const [tier, setTier] = useState("all");

  // Esc closes the top layer, like the drawer's overlays.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === "Escape") onClose && onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const shown = SCENES.filter(([name, , , t]) =>
    (tier === "all" || (tier === "tier1" && t) || (tier === "free" && !t)) &&
    (!q.trim() || name.toLowerCase().includes(q.trim().toLowerCase())));

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

        <div className="mgai-grid">
          {shown.map(([name, slug, shape, t, detail]) => {
            const m = SHAPE[shape];
            return (
              <button key={slug} type="button" className="mgai-card"
                onClick={() => onPick && onPick({ name, slug, shape, tier: t, detail })}
                title={name}>
                <div className="mgai-thumb">
                  <span className="mgai-initial">{name[0]}</span>
                  <img src={"/branding/bridge/scene_" + slug + ".webp"} alt="" loading="lazy"
                    onError={(e) => { e.currentTarget.style.display = "none"; }} />
                  {t ? <span className="mgai-tierbadge">Tier 1</span> : null}
                  <span className="mgai-shapedot" style={{ background: m.color }} />
                </div>
                <div className="mgai-meta">
                  <div className="mgai-name">{name}</div>
                  <span className="mgai-chip" style={{ color: m.color, borderColor: m.color }}>{m.label}</span>
                  {detail ? <div className="mgai-detail">{detail}</div> : null}
                </div>
              </button>
            );
          })}
          {shown.length === 0 ? <div className="mgai-empty">No tools match “{q}”.</div> : null}
        </div>

        <div className="mgai-foot">
          <span><b>{shown.length}</b> shown</span>
          <span className="mgai-tally">11 one-click · 8 select · 5 text · 3 language · 1 dual</span>
        </div>
      </div>
    </div>
  );
}
