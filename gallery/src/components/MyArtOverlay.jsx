import React, { useEffect, useMemo, useState } from "react";
import useMyArt, { fmt } from "../hooks/useMyArt.js";
import "../styles/overlays.css";
import "../styles/myart-contests.css";
import useScrollLock from "../hooks/useScrollLock.js";

/* "My Art" overlay — rebuilt 2026-08-06 to the returned handoff's tabbed-gallery
   design (Frontend Gallery.dc.html ovMyArt, markup 599-809, logic 2277-2436):
   sticky header (serif "Your artwork" + stat row + sub-tabs with count pills),
   toolbar (Visibility/Sort dropdowns), and a 3:4 card grid with real thumbnails,
   visibility badges, tag chips, and the footer avatar/title/date/likes row —
   replacing the old text-only ranked list.

   PHASE A (display-only), disclosed:
   - Artworks/Animations tabs run on REAL local data: GET /api/myart/items (every
     catalog row with an artwork_id, public and private, card-ready — thumbs are
     the local /thumbs/<mid>.jpg). The stat row keeps /api/your-art's LIVE view
     counts, exactly as before.
   - The design's hover actions (publish-toggle/edit-tags/delete) and bulk Manage
     are PixAI account MUTATIONS that have no backend yet (the Publish-flow
     stage). They render per the design but disabled, labeled honestly; wiring
     arrives with that stage. Card click opens Details, the app's real target.
   - Models & LoRAs / Assets: no local data source exists for ownership/uploads
     (verified against the catalog + routes 2026-08-06), so these tabs show the
     design's own "Nothing here yet." empty state plus a one-line why.
   - The heart-color rule, badge colors, tab pills, and grid geometry are the
     DC's literal values (heartCol: >10 mauve, >0 subtext, else overlay0). */

const VIS_OPTS = [["all", "All"], ["public", "Public"], ["private", "Private"]];
const SORT_OPTS = [["latest", "Latest"], ["oldest", "Oldest"], ["liked", "Most liked"]];
const TABS = [
  { key: "artworks", label: "Artworks" },
  { key: "animations", label: "Animations" },
  { key: "loras", label: "Models & LoRAs" },
  { key: "assets", label: "Assets" },
];

function Dropdown({ kick, value, opts, onPick }) {
  const [open, setOpen] = useState(false);
  const cur = (opts.find((o) => o[0] === value) || opts[0])[1];
  return (
    <div className="mgma2-dd">
      <button type="button" className="mgma2-ddbtn" onClick={() => setOpen(!open)}>
        <span className="k">{kick}</span><span className="v">{cur}</span><span className="c">▾</span>
      </button>
      {open && (
        <div className="mgma2-ddmenu">
          {opts.map(([k, label]) => (
            <div key={k} className={"mgma2-dditem" + (k === value ? " on" : "")}
              onClick={() => { onPick(k); setOpen(false); }}>{label}</div>
          ))}
        </div>
      )}
    </div>
  );
}

// DC:2324 verbatim -- the heart color scales with the like count.
const heartCol = (n) => (n > 10 ? "var(--mauve)" : n > 0 ? "var(--subtext)" : "var(--overlay0)");

const dateLabel = (iso) => {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  if (isNaN(d)) return iso;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
};

export default function MyArtOverlay({ onClose, onOpenPost }) {
  useScrollLock();   // page never scrolls behind a full-screen panel (2026-08-06)
  const { d, err, stats } = useMyArt();          // stat row: live views, as before
  const [rows, setRows] = useState(null);
  const [rowsErr, setRowsErr] = useState(null);
  const [csrf, setCsrf] = useState("");
  const [tab, setTab] = useState("artworks");
  const [vis, setVis] = useState("all");
  const [sort, setSort] = useState("latest");
  // The confirm step: every account action previews first (what it will do, resolved
  // tags, whether it's irreversible) and only fires when the owner says go.
  const [ask, setAsk] = useState(null);       // {action, item, preview} | null
  const [busy, setBusy] = useState(false);
  const [actErr, setActErr] = useState("");
  const [editing, setEditing] = useState(null);   // media_id whose tags are being edited
  const [tagDraft, setTagDraft] = useState("");

  const load = () => fetch("/api/myart/items")
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
    .then((j) => { setRows(j.items || []); setCsrf(j.csrf || ""); });

  useEffect(() => {
    let dead = false;
    fetch("/api/myart/items")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then((j) => { if (!dead) { setRows(j.items || []); setCsrf(j.csrf || ""); } })
      .catch((e) => { if (!dead) setRowsErr(String(e.message || e)); });
    return () => { dead = true; };
  }, []);

  // Step 1: ask the server what this action WOULD do (no mutation, no spend).
  const preview = async (action, item, extra) => {
    setActErr(""); setBusy(true);
    try {
      const r = await fetch("/api/myart/publish", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, media_id: item.media_id, csrf, ...extra }),
      });
      const p = await r.json();
      if (p.error) { setActErr(p.error); return; }
      setAsk({ action, item, extra: extra || {}, preview: p });
    } catch (e) { setActErr(String(e.message || e)); } finally { setBusy(false); }
  };

  // Step 2: the owner confirmed -- fire the real PixAI mutation.
  const confirm = async () => {
    if (!ask) return;
    setBusy(true); setActErr("");
    try {
      const r = await fetch("/api/myart/publish", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: ask.action, media_id: ask.item.media_id,
                               csrf, confirm: true, ...ask.extra }),
      });
      const res = await r.json();
      if (res.error) { setActErr(res.error); return; }
      setAsk(null); setEditing(null);
      await load();
    } catch (e) { setActErr(String(e.message || e)); } finally { setBusy(false); }
  };

  const media = useMemo(() => {
    const all = rows || [];
    let list = all.filter((r) => (tab === "animations" ? r.is_video : !r.is_video));
    if (vis !== "all") list = list.filter((r) => (vis === "public" ? r.public : !r.public));
    if (sort === "oldest") list = [...list].reverse();          // base order is latest-first
    else if (sort === "liked") list = [...list].sort((a, b) => b.likes - a.likes);
    return list;
  }, [rows, tab, vis, sort]);

  const counts = useMemo(() => {
    const all = rows || [];
    return {
      artworks: all.filter((r) => !r.is_video).length,
      animations: all.filter((r) => r.is_video).length,
      loras: 0, assets: 0,
    };
  }, [rows]);

  const mediaTab = tab === "artworks" || tab === "animations";

  return (
    <>
      <div className="mgv-scrim" onClick={onClose} />
      <div className="mgv-host">
        <div className="mgv-slab mgma2-slab" role="dialog" aria-label="Your Art">

          {/* Sticky header: title row + stat row + sub-tabs (DC:604-623). */}
          <div className="mgma2-head">
            <div className="mgma2-titlerow">
              <div>
                <div className="mgma2-title">Your artwork</div>
                <div className="mgma2-sub">everything you've made, published or held back</div>
              </div>
              <button type="button" className="mgv-x" onClick={onClose} aria-label="Close">×</button>
            </div>
            {d && (
              <div className="mgma2-stats">
                {stats.map((st) => (
                  <div className="mgma2-stat" key={st.label}>
                    <div className={"mgma2-statval" + (st.accent ? " accent" : "")}>{st.value}</div>
                    <div className="mgma2-statlab">{st.label}</div>
                  </div>
                ))}
              </div>
            )}
            <div className="mgma2-tabs">
              {TABS.map((t) => (
                <button type="button" key={t.key}
                  className={"mgma2-tab" + (tab === t.key ? " on" : "")}
                  onClick={() => setTab(t.key)}>
                  {t.label}
                  <span className={"mgma2-pill" + (tab === t.key ? " on" : "")}>{counts[t.key]}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Toolbar (DC:627-664). Manage is a mutation surface -- Phase B. */}
          {mediaTab && (
            <div className="mgma2-toolbar">
              <Dropdown kick="Visibility" value={vis} opts={VIS_OPTS} onPick={setVis} />
              <Dropdown kick="Sort" value={sort} opts={SORT_OPTS} onPick={setSort} />
              <button type="button" className="mgma2-toolbtn" disabled
                title="Bulk actions come next — per-card publish, tags and delete are live now">
                ✎ Manage
              </button>
              {actErr && <span className="mgma2-acterr">⚠ {actErr}</span>}
            </div>
          )}

          {/* Confirm step. Nothing reaches the PixAI account until this is accepted --
              the server previewed exactly what it would do (including which tags it
              could resolve) without making a single mutating call. */}
          {ask && (
            <div className="mgma2-confirm">
              <div className="mgma2-confirmtitle">
                {ask.action === "delete" ? "Delete this artwork from PixAI?"
                  : ask.action === "tags" ? "Update tags on PixAI?"
                  : ask.preview.private ? "Make this private on PixAI?"
                  : "Make this public on PixAI?"}
              </div>
              <div className="mgma2-confirmbody">
                <b>{ask.item.title}</b>
                {ask.action === "tags" && (
                  <> — {ask.preview.tack_ids.length} tag{ask.preview.tack_ids.length === 1 ? "" : "s"} will be set
                    {ask.preview.unmatched_tags.length > 0 && (
                      <span className="warn"> · not found on PixAI: {ask.preview.unmatched_tags.join(", ")}</span>
                    )}
                  </>
                )}
                {ask.preview.irreversible && <span className="warn"> · this can't be undone on PixAI (your local copy stays)</span>}
                <div className="mgma2-confirmnote">No credits are spent by this action.</div>
              </div>
              <div className="mgma2-confirmacts">
                <button type="button" className="mgma2-toolbtn" onClick={() => setAsk(null)} disabled={busy}>Cancel</button>
                <button type="button"
                  className={"mgma2-godone" + (ask.preview.irreversible ? " danger" : "")}
                  onClick={confirm} disabled={busy}>
                  {busy ? "working…" : ask.action === "delete" ? "Delete it" : "Do it"}
                </button>
              </div>
            </div>
          )}

          <div className="mgma2-body">
            {!rows && !rowsErr && <div className="mgh-loading">loading your artwork…</div>}
            {rowsErr && <div className="mgh-loading">couldn't load — {rowsErr}</div>}
            {err && !d && <div className="mgh-loading">stats unavailable — {err}</div>}

            {mediaTab && rows && (
              media.length === 0 ? (
                <div className="mgma2-empty">Nothing here yet.</div>
              ) : (
                <div className="mgma2-grid">
                  {media.map((it) => (
                    <div className="mgma2-card" key={it.media_id} role="button" tabIndex={0}
                      onClick={() => onOpenPost && onOpenPost(it.media_id)}
                      onKeyDown={(e) => { if (e.key === "Enter") onOpenPost && onOpenPost(it.media_id); }}>
                      <div className="mgma2-art">
                        <img src={it.thumb} alt="" loading="lazy"
                          onError={(e) => { e.currentTarget.style.visibility = "hidden"; }} />
                        <span className={"mgma2-vis" + (it.public ? " pub" : " priv")}>
                          {it.public ? "◉ Public" : "🔒 Private"}
                        </span>
                        {/* DC:698-702 hover actions, now REAL -- each previews first. */}
                        <span className="mgma2-acts" onClick={(e) => e.stopPropagation()}>
                          <button type="button" disabled={busy}
                            title={it.public ? "Make private on PixAI" : "Make public on PixAI"}
                            onClick={() => preview("visibility", it, { private: it.public })}>
                            {it.public ? "🔒" : "◉"}
                          </button>
                          <button type="button" disabled={busy} title="Edit tags"
                            onClick={() => { setEditing(it.media_id); setTagDraft(it.tags.join(", ")); }}>✎</button>
                          <button type="button" disabled={busy} title="Delete from PixAI"
                            onClick={() => preview("delete", it)}>🗑</button>
                        </span>
                        {editing === it.media_id && (
                          <div className="mgma2-tagedit" onClick={(e) => e.stopPropagation()}>
                            <input value={tagDraft} autoFocus
                              placeholder="tags, comma separated"
                              onChange={(e) => setTagDraft(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") {
                                  preview("tags", it, { tags: tagDraft.split(",").map((s) => s.trim()).filter(Boolean) });
                                } else if (e.key === "Escape") setEditing(null);
                              }} />
                            <div className="mgma2-tagedit-row">
                              <button type="button" className="mgma2-toolbtn" onClick={() => setEditing(null)}>Cancel</button>
                              <button type="button" className="mgma2-godone" disabled={busy}
                                onClick={() => preview("tags", it, { tags: tagDraft.split(",").map((s) => s.trim()).filter(Boolean) })}>Done</button>
                            </div>
                          </div>
                        )}
                        {it.tags.length > 0 && (
                          <div className="mgma2-tagband">
                            {it.tags.map((t) => <span className="mgma2-tag" key={t}>#{t}</span>)}
                          </div>
                        )}
                        {it.is_video && <span className="mgma2-vid">▶</span>}
                      </div>
                      <div className="mgma2-foot">
                        <span className="mgma2-avatar">NL</span>
                        <span className="mgma2-ftitle" title={it.title}>{it.title}</span>
                        <span className="mgma2-fdate">{dateLabel(it.date)}</span>
                        <span className="mgma2-likes" style={{ color: heartCol(it.likes) }}>♥ {fmt(it.likes)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )
            )}

            {tab === "loras" && (
              <div className="mgma2-empty">
                Nothing here yet.
                <div className="mgma2-emptywhy">
                  Your published models &amp; LoRAs live on your PixAI account — listing them
                  here arrives with the publish pipeline.
                </div>
              </div>
            )}
            {tab === "assets" && (
              <div className="mgma2-empty">
                Nothing here yet.
                <div className="mgma2-emptywhy">
                  Reference sets, datasets and upscales you've uploaded aren't tracked
                  locally — this tab fills in with the publish pipeline.
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
