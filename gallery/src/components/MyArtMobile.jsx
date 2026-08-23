import React, { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost } from "../api.js";
import { fmt } from "../hooks/useMyArt.js";
import useSheet from "../hooks/useSheet.js";
import MobileSheet from "./MobileSheet.jsx";
import "../styles/control-mobile.css";
import "../styles/create-mobile.css";
import "../styles/myart-contests.css";
import "../styles/overlays.css";
import "../styles/gallery-mobile.css";
import "../styles/myart-mobile.css";

/* My Art -- mobile, rebuilt 2026-08-07 to Moonglade Mobile.dc.html's updated screenIsMyArt
   block (the design's own answer to FOR_CLAUDE_DESIGN_mobile-2026-08-06.md): the old flat
   ranked-text list is gone, replaced with the same tabbed card gallery desktop's
   MyArtOverlay.jsx already ships, adapted for touch. Real data throughout -- GET
   /api/myart/items (the exact route desktop uses), mutations via /api/myart/publish
   (same CSRF source). Anything IRREVERSIBLE (delete, per-card or bulk) always goes
   through a confirm sheet before confirm:true is sent; reversible per-card edits
   (visibility, tags) apply directly, matching the sheet-tap-is-the-intent touch
   pattern. (2026-08-07 review fix: per-card delete originally fired confirm:true on
   one tap -- an irreversible PixAI delete with no confirm step.)

   Touch adaptations from the design's own demo-data shortcuts, disclosed here (the
   mechanism the design specifies is real; only its filler numbers are placeholder):
   - Sub-tabs: real counts (artworks/animations split by is_video; LoRAs from the real
     model-search route desktop's LoRAs tab already proved out).
   - Card ⋯ overflow -> a bottom sheet (publish-toggle / edit tags / delete), matching the
     design's own touch pattern instead of desktop's hover reveal.
   - Edit tags is its own sheet with the SAME live PixAI tag search desktop's inline editor
     uses (not a plain text box).
   - Bulk Manage: checkbox circles + a fixed bottom bar, wired to the SAME real pipeline as
     desktop's bulk Manage -- one confirm sheet per action, calls run one at a time.
   - LoRAs/Assets tabs reuse the exact real data + the exact disclosed gap desktop's
     MyArtOverlay.jsx already has (LoRAs real via src=mine; Assets has no local data
     source, honest empty state). */

const heartCol = (n) => (n > 10 ? "var(--mauve)" : n > 0 ? "var(--subtext)" : "var(--overlay0)");
const dateLabel = (iso) => {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  if (isNaN(d)) return iso;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
};
const BASE_TINT = {
  SDXL_MODEL: ["var(--emerald)", "rgba(79,201,154,.18)", "XL"],
  MMDIT26A_MODEL: ["var(--mauve)", "rgba(182,146,230,.18)", "DiT.2"],
  SD_V1_MODEL: ["var(--gold)", "rgba(212,175,55,.18)", "SD"],
};
const baseTint = (t) => BASE_TINT[t] || ["var(--subtext)", "var(--surface0)", t ? t.replace("_MODEL", "") : "?"];

const TABS = [
  { key: "artworks", label: "Artworks" },
  { key: "animations", label: "Animations" },
  { key: "loras", label: "Models & LoRAs" },
  { key: "assets", label: "Assets" },
];
const VIS_OPTS = [["all", "All"], ["public", "Public"], ["private", "Private"]];
const SORT_OPTS = [["latest", "Latest first"], ["oldest", "Oldest first"], ["liked", "Most liked"]];

export default function MyArtMobile({ onOpenPost, onOpenTrain }) {
  const [rows, setRows] = useState(null);
  const [rowsErr, setRowsErr] = useState("");
  const [csrf, setCsrf] = useState("");
  const [stats, setStats] = useState(null);
  const [tab, setTab] = useState("artworks");
  const [vis, setVis] = useState("all");
  const [sort, setSort] = useState("latest");
  const [manageOn, setManageOn] = useState(false);
  const [selected, setSelected] = useState(() => new Set());
  const [loras, setLoras] = useState(null);
  const [lorasErr, setLorasErr] = useState("");

  // 'sort' | 'cardmenu' | 'cardtags' | null -- shared timer-safe machine (hooks/useSheet.js)
  const { sheet, closing, open: openSheet, close: closeSheet } = useSheet(280);
  const [menuId, setMenuId] = useState(null);
  const [tagsId, setTagsId] = useState(null);
  const [tagDraft, setTagDraft] = useState("");
  const [tagOpts, setTagOpts] = useState([]);
  const [bulkAsk, setBulkAsk] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");


  const load = () => apiGet("/api/myart/items")
    .then((j) => {
      if (j.error) throw new Error(j.error);
      setRows(j.items || []); setCsrf(j.csrf || "");
    });

  useEffect(() => {
    let dead = false;
    load().catch((e) => { if (!dead) setRowsErr(String(e.message || e)); });
    apiGet("/api/your-art").then((d) => {
      if (dead) return;
      setStats([
        { value: fmt((d.totals || {}).count), label: "PUBLISHED", accent: false },
        { value: (d.totals || {}).views_top != null ? fmt(d.totals.views_top) : "—", label: "VIEWS (TOP 12)", accent: true },
        { value: fmt((d.totals || {}).likes), label: "LIKES", accent: false },
        { value: fmt((d.totals || {}).comments), label: "COMMENTS", accent: false },
      ]);
    }).catch(() => {});
    return () => { dead = true; };
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (tab !== "loras" || loras !== null) return;
    let dead = false;
    apiGet("/api/model-search?src=mine&kind=lora&size=48")
      .then((d) => {
        if (dead) return;
        if (d.error) setLorasErr(d.error); else setLoras(d.results || []);
      });
    return () => { dead = true; };
  }, [tab, loras]);

  useEffect(() => {
    const q = tagDraft.trim();
    if (q.length < 2) { setTagOpts([]); return; }
    let dead = false;
    const t = setTimeout(() => {
      apiGet("/api/tag-suggest?q=" + encodeURIComponent(q))
        .then((d) => { if (!dead) setTagOpts((d.tags || []).slice(0, 6)); });
    }, 220);
    return () => { dead = true; clearTimeout(t); };
  }, [tagDraft]);

  const media = useMemo(() => {
    const all = rows || [];
    let list = all.filter((r) => (tab === "animations" ? r.is_video : !r.is_video));
    if (vis !== "all") list = list.filter((r) => (vis === "public" ? r.public : !r.public));
    if (sort === "oldest") list = [...list].reverse();
    else if (sort === "liked") list = [...list].sort((a, b) => b.likes - a.likes);
    return list;
  }, [rows, tab, vis, sort]);

  const counts = useMemo(() => {
    const all = rows || [];
    return {
      artworks: all.filter((r) => !r.is_video).length,
      animations: all.filter((r) => r.is_video).length,
      loras: loras ? loras.length : 0, assets: 0,
    };
  }, [rows, loras]);

  const menuItem = menuId ? media.find((m) => m.media_id === menuId) : null;
  const tagsItem = tagsId ? media.find((m) => m.media_id === tagsId) : null;

  const toggleManage = () => { setManageOn((v) => !v); setSelected(new Set()); };
  const toggleSelect = (mid) => setSelected((cur) => {
    const next = new Set(cur);
    if (next.has(mid)) next.delete(mid); else next.add(mid);
    return next;
  });

  // One real mutation call, used by both the card-menu sheet and bulk actions.
  // Never throws: a network error / non-JSON response resolves to {error} so every
  // caller's setBusy(false) is reached (a throw here used to latch busy=true forever).
  const mutate = async (action, mediaId, extra) => {
    return apiPost("/api/myart/publish",
      { action, media_id: mediaId, csrf, confirm: true, ...extra });
  };

  const cardTogglePublish = async () => {
    if (!menuItem) return;
    setBusy(true); setErr("");
    const res = await mutate("visibility", menuItem.media_id, { private: menuItem.public });
    setBusy(false);
    if (res.error) { setErr(res.error); return; }
    closeSheet(); await load();
  };
  // Delete is irreversible on PixAI, so the card-menu row NEVER fires it directly --
  // it routes into the same confirm sheet bulk uses, carrying an explicit mids list.
  // The 300ms delay lets the card-menu sheet finish its exit animation first (the
  // sheets share the `closing` flag, so opening one mid-close renders it backwards).
  const askCardDelete = () => {
    if (!menuItem) return;
    const mid = menuItem.media_id;
    closeSheet();
    setTimeout(() => setBulkAsk({ action: "delete", extra: {}, count: 1, mids: [mid] }), 300);
  };
  const saveTags = async (newTags) => {
    if (!tagsItem) return;
    setBusy(true); setErr("");
    const res = await mutate("tags", tagsItem.media_id, { tags: newTags });
    setBusy(false);
    if (res.error) { setErr(res.error); return; }
    await load();
  };

  const askBulk = (action, extra) => { setBulkAsk({ action, extra, count: selected.size }); };
  const confirmBulk = async () => {
    if (!bulkAsk) return;
    const mids = bulkAsk.mids || Array.from(selected);
    setBusy(true); let ok = 0, fail = 0;
    for (const mid of mids) {
      const res = await mutate(bulkAsk.action, mid, bulkAsk.extra);
      if (res.error) fail++; else ok++;
    }
    setBusy(false); setBulkAsk(null);
    if (!bulkAsk.mids) setSelected(new Set());
    await load();
  };

  const mediaTab = tab === "artworks" || tab === "animations";

  return (
    <>
      {stats && (
        <div className="myam-statrow">
          {stats.map((st) => (
            <div className="myam-statcell" key={st.label}>
              <div className="myam-statval" style={{ color: st.accent ? "var(--lavender)" : "var(--text)" }}>{st.value}</div>
              <div className="myam-statlabel">{st.label}</div>
            </div>
          ))}
        </div>
      )}

      <div className="myam-tabrow">
        {TABS.map((t) => (
          <button type="button" key={t.key}
            className={"myam-tab" + (tab === t.key ? " on" : "")}
            onClick={() => { setTab(t.key); setManageOn(false); setSelected(new Set()); }}>
            {t.label}
            <span className={"myam-pill" + (tab === t.key ? " on" : "")}>{counts[t.key]}</span>
          </button>
        ))}
      </div>

      <div className="myam-toolbar">
        {mediaTab && (
          <>
            <div className="myam-visseg">
              {VIS_OPTS.map(([k, l]) => (
                <button type="button" key={k} className={"myam-vischip" + (vis === k ? " on" : "")}
                  onClick={() => setVis(k)}>{l}</button>
              ))}
            </div>
            <button type="button" className="myam-sortbtn" onClick={() => openSheet("sort")}>
              ↕ {sort === "oldest" ? "Oldest" : sort === "liked" ? "Liked" : "Latest"}
            </button>
          </>
        )}
        {tab === "loras" && onOpenTrain && (
          <button type="button" className="myam-traincta" onClick={onOpenTrain}>◆ Train a LoRA</button>
        )}
        <div className="myam-spacer" />
        {mediaTab && (
          <button type="button" className={"myam-managebtn" + (manageOn ? " on" : "")} onClick={toggleManage}>
            {manageOn ? "Done" : "Manage"}
          </button>
        )}
      </div>

      {err && <div className="myam-err">⚠ {err}</div>}

      {!rows && !rowsErr && <div className="mgh-loading">loading your artwork…</div>}
      {rowsErr && <div className="mgh-loading">couldn't load — {rowsErr}</div>}

      {mediaTab && rows && (
        media.length === 0 ? (
          <div className="mgh-loading" style={{ padding: "24px 0" }}>Nothing here yet.</div>
        ) : (
          <div className="myam-grid">
            {media.map((it) => {
              const isSel = selected.has(it.media_id);
              return (
                <div key={it.media_id}
                  className={"myam-card" + (manageOn && isSel ? " sel" : "")}
                  onClick={() => {
                    if (manageOn) toggleSelect(it.media_id);
                    else if (onOpenPost) onOpenPost(it.media_id);
                  }}>
                  <div className="myam-thumb">
                    <img src={it.thumb} alt="" loading="lazy"
                      onError={(e) => { e.currentTarget.style.visibility = "hidden"; }} />
                    {it.is_video && <span className="myam-play">▶</span>}
                    {manageOn ? (
                      <span className={"myam-check" + (isSel ? " on" : "")}>{isSel ? "✓" : ""}</span>
                    ) : (
                      <>
                        <span className={"myam-visbadge" + (it.public ? " pub" : "")}>{it.public ? "Public" : "Private"}</span>
                        <button type="button" className="myam-menubtn"
                          onClick={(e) => { e.stopPropagation(); setMenuId(it.media_id); openSheet("cardmenu"); }}>⋯</button>
                      </>
                    )}
                    {it.tags.length > 0 && (
                      <div className="myam-tagrow">
                        {it.tags.slice(0, 2).map((t) => <span className="myam-tagchip" key={t}>#{t}</span>)}
                      </div>
                    )}
                  </div>
                  <div className="myam-foot">
                    <span className="myam-avatar">NL</span>
                    <div className="myam-metacol">
                      <div className="myam-title">{it.title}</div>
                      <div className="myam-date">{dateLabel(it.date)}</div>
                    </div>
                    <span className="myam-likes" style={{ color: heartCol(it.likes) }}>♥ {fmt(it.likes)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )
      )}

      {tab === "loras" && (
        lorasErr ? <div className="mgh-loading">couldn't load — {lorasErr}</div>
        : loras === null ? <div className="mgh-loading">loading your models &amp; LoRAs…</div>
        : loras.length === 0 ? <div className="mgh-loading" style={{ padding: "24px 0" }}>Nothing here yet.</div>
        : loras.map((m) => {
            const [tc] = baseTint(m.lora_base_model_type);
            return (
              <a className="myam-loracard" key={m.model_id}
                href={"https://pixai.art/model/" + encodeURIComponent(m.model_id)}
                target="_blank" rel="noreferrer">
                <div className="myam-loramark" style={{ color: tc }}>◆</div>
                <div className="myam-loracol">
                  <div className="myam-loraname">{m.title}</div>
                  <div className="myam-lorameta">🔥 {fmt(m.ref_count)} uses · ♥ {fmt(m.liked_count)}</div>
                </div>
              </a>
            );
          })
      )}

      {tab === "assets" && (
        <div className="mgh-loading" style={{ padding: "24px 0" }}>
          Nothing here yet.
          <div style={{ fontSize: 11, marginTop: 8 }}>
            Uploaded reference sets, datasets and upscales aren't tracked locally.
          </div>
        </div>
      )}

      {manageOn && mediaTab && (
        <div className="myam-bulkbar">
          <span className="myam-bulkcount">{selected.size} selected</span>
          <div className="myam-spacer" />
          {selected.size > 0 && (
            <>
              <button type="button" className="myam-bulkbtn" onClick={() => askBulk("visibility", { private: false })}>◉ Publish</button>
              <button type="button" className="myam-bulkbtn" onClick={() => askBulk("visibility", { private: true })}>🔒 Hide</button>
              <button type="button" className="myam-bulkdgr" onClick={() => askBulk("delete", {})}>🗑</button>
            </>
          )}
          <button type="button" className="myam-bulkbtn" disabled={selected.size === 0} onClick={() => setSelected(new Set())}>Clear</button>
        </div>
      )}

      {/* Sort sheet */}
      <MobileSheet open={sheet === "sort"} closing={closing} onClose={closeSheet} title="SORT">
        {SORT_OPTS.map(([k, l]) => (
          <button type="button" key={k} className={"myam-sheetopt" + (sort === k ? " on" : "")}
            onClick={() => { setSort(k); closeSheet(); }}>{l}</button>
        ))}
      </MobileSheet>

      {/* Card overflow menu */}
      <MobileSheet open={sheet === "cardmenu"} closing={closing} onClose={closeSheet}
        title={(menuItem && menuItem.title) || ""}>
        <button type="button" className="myam-sheetrow" disabled={busy} onClick={cardTogglePublish}>
          <span>{menuItem && menuItem.public ? "🔒" : "◉"}</span>
          {menuItem && menuItem.public ? "Make private" : "Publish (make public)"}
        </button>
        <button type="button" className="myam-sheetrow"
          onClick={() => { setTagsId(menuId); setTagDraft(""); openSheet("cardtags"); }}>
          <span>✎</span>Edit tags
        </button>
        <button type="button" className="myam-sheetrow dgr" disabled={busy} onClick={askCardDelete}>
          <span>🗑</span>Delete
        </button>
      </MobileSheet>

      {/* Edit tags sheet -- same live PixAI tag search as desktop's inline editor. */}
      <MobileSheet open={sheet === "cardtags"} closing={closing} onClose={closeSheet} title="EDIT TAGS">
        <div className="myam-sheetsub">On this artwork — tap to remove</div>
        <div className="myam-tagbox">
          {tagsItem && tagsItem.tags.map((t) => (
            <span className="myam-tagpill" key={t}
              onClick={() => saveTags(tagsItem.tags.filter((x) => x !== t))}>#{t} ×</span>
          ))}
        </div>
        <div className="myam-sheetsub">Add a tag</div>
        <input className="myam-taginput" value={tagDraft} placeholder="search tags…"
          onChange={(e) => setTagDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && tagDraft.trim()) {
              saveTags((tagsItem ? tagsItem.tags : []).concat(tagDraft.trim()));
              setTagDraft("");
            }
          }} />
        {tagOpts.length > 0 && (
          <div className="myam-tagopts">
            {tagOpts.filter((t) => !(tagsItem && tagsItem.tags.includes(t))).map((t) => (
              <span className="myam-tagadd" key={t}
                onClick={() => { saveTags((tagsItem ? tagsItem.tags : []).concat(t)); setTagDraft(""); }}>+ {t}</span>
            ))}
          </div>
        )}
        <button type="button" className="glm-primary glm-widebtn" style={{ marginTop: 14 }}
          disabled={busy} onClick={closeSheet}>Done</button>
      </MobileSheet>

      {/* Bulk confirm */}
      <MobileSheet open={!!bulkAsk} closing={closing} onClose={() => setBulkAsk(null)}
        title={bulkAsk && bulkAsk.action === "delete" ? "DELETE ARTWORK" : "CHANGE VISIBILITY"}>
        {bulkAsk && (
          <>
            <div className="myam-sheetsub">
              {bulkAsk.action === "delete"
                ? "Delete " + bulkAsk.count + " item" + (bulkAsk.count === 1 ? "" : "s") + " from PixAI? This can't be undone (your local copies stay)."
                : "Make " + bulkAsk.count + " item" + (bulkAsk.count === 1 ? "" : "s") + (bulkAsk.extra.private ? " private" : " public") + " on PixAI? No credits are spent."}
            </div>
            <div className="glm-sheet-actions">
              <button type="button" className="glm-metal glm-widebtn" onClick={() => setBulkAsk(null)} disabled={busy}>Back</button>
              <button type="button" className="glm-primary glm-widebtn" onClick={confirmBulk} disabled={busy}>
                {busy ? "working…" : bulkAsk.action === "delete" ? "Delete" : "Confirm"}
              </button>
            </div>
          </>
        )}
      </MobileSheet>
    </>
  );
}
