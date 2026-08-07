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

   Real local data throughout: GET /api/myart/items (every catalog row with an
   artwork_id, public and private, card-ready — thumbs are the local
   /thumbs/<mid>.jpg). The stat row keeps /api/your-art's LIVE view counts.
   The heart-color rule, badge colors, tab pills, and grid geometry are the
   DC's literal values (heartCol: >10 mauve, >0 subtext, else overlay0).

   Per-card actions (publish-toggle/edit-tags/delete) and bulk Manage all run
   through the SAME real /api/myart/publish pipeline, preview-then-confirm --
   bulk Manage (2026-08-06) is not a second code path, it is the identical
   preview()/confirm() calling in a loop over the selection with ONE confirm
   sheet in front of all of them, so a batch action can't fire N account
   mutations off one accidental tap. Models & LoRAs / Assets: LoRAs is real
   (see loras state below); Assets still has no local data source, so it stays
   the design's own "Nothing here yet." empty state plus a one-line why. */

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

// DC's BASE_TINT (L2393): named colors for the three architectures it called out by
// name; anything else falls to its own fallback (subtext on surface0) rather than a
// made-up color -- includes DiT.1/DiT.3, which the design never assigned a tint.
const BASE_TINT = {
  SDXL_MODEL: ["var(--emerald)", "rgba(79,201,154,.18)", "XL"],
  MMDIT26A_MODEL: ["var(--mauve)", "rgba(182,146,230,.18)", "DiT.2"],
  SD_V1_MODEL: ["var(--gold)", "rgba(212,175,55,.18)", "SD"],
};
const baseTint = (t) => BASE_TINT[t] || ["var(--subtext)", "var(--surface0)", t ? t.replace("_MODEL", "") : "?"];

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
  // Bulk Manage (DC:661-678): a selection mode over the SAME real pipeline the per-card
  // actions use. Visibility/delete need no server-side resolution before confirming
  // (unlike a single publish's media_index, or tags' tack_ids), so bulk skips the
  // preview round-trip and goes straight to one confirm sheet covering the whole batch.
  const [manageOn, setManageOn] = useState(false);
  const [selected, setSelected] = useState(() => new Set());
  const [bulkAsk, setBulkAsk] = useState(null);     // {action, extra, count} | null
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkErr, setBulkErr] = useState("");
  const [bulkResult, setBulkResult] = useState(null);   // {ok, fail} after a run, transient

  // Models & LoRAs tab: real data via the SAME market route the Generate drawer's own
  // picker already uses (src=mine -- "the ordinary market connection filtered by the
  // signed-in user's own id, exactly as PixAI's MY LORA tab does it", per that route's
  // own docstring). Fetched once, lazily, the first time the tab is opened.
  const [loras, setLoras] = useState(null);
  const [lorasErr, setLorasErr] = useState("");
  useEffect(() => {
    if (tab !== "loras" || loras !== null) return;
    let dead = false;
    fetch("/api/model-search?src=mine&kind=lora&size=48")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then((d) => { if (!dead) setLoras(d.results || []); })
      .catch((e) => { if (!dead) setLorasErr(String(e.message || e)); });
    return () => { dead = true; };
  }, [tab, loras]);

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

  const toggleManage = () => { setManageOn((v) => !v); setSelected(new Set()); setBulkResult(null); };
  const toggleSelect = (mid) => setSelected((cur) => {
    const next = new Set(cur);
    if (next.has(mid)) next.delete(mid); else next.add(mid);
    return next;
  });

  const askBulk = (action, extra) => {
    setBulkErr(""); setBulkResult(null);
    setBulkAsk({ action, extra: extra || {}, count: selected.size });
  };

  // One confirm covers the whole batch; the individual account mutations still run one
  // request at a time (never parallel) -- polite to PixAI's servers, same pacing ethos
  // as every other multi-call path in this app, and it means a partial failure midway
  // is countable rather than an unordered pile of racing responses.
  const confirmBulk = async () => {
    if (!bulkAsk) return;
    setBulkBusy(true); setBulkErr("");
    let ok = 0, fail = 0;
    for (const mid of selected) {
      try {
        const r = await fetch("/api/myart/publish", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: bulkAsk.action, media_id: mid, csrf,
                                 confirm: true, ...bulkAsk.extra }),
        });
        const res = await r.json();
        if (res.error) fail++; else ok++;
      } catch (e) { fail++; }
    }
    setBulkAsk(null); setBulkBusy(false); setBulkResult({ ok, fail });
    setSelected(new Set());
    await load();
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
      loras: loras ? loras.length : 0, assets: 0,
    };
  }, [rows, loras]);

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

          {/* Toolbar (DC:627-664). */}
          {mediaTab && (
            <div className="mgma2-toolbar">
              <Dropdown kick="Visibility" value={vis} opts={VIS_OPTS} onPick={setVis} />
              <Dropdown kick="Sort" value={sort} opts={SORT_OPTS} onPick={setSort} />
              <button type="button" className={"mgma2-toolbtn" + (manageOn ? " on" : "")}
                onClick={toggleManage}>
                {manageOn ? "Done" : "✎ Manage"}
              </button>
              {actErr && <span className="mgma2-acterr">⚠ {actErr}</span>}
            </div>
          )}

          {/* Bulk bar (DC:667-678) -- same real pipeline as the per-card actions, one
              confirm sheet covering the whole selection. */}
          {mediaTab && manageOn && (
            <div className="mgma2-bulkbar">
              <span className="n">{selected.size} selected</span>
              {selected.size > 0 && (
                <>
                  <button type="button" className="mgma2-toolbtn"
                    onClick={() => askBulk("visibility", { private: false })}>◉ Publish</button>
                  <button type="button" className="mgma2-toolbtn"
                    onClick={() => askBulk("visibility", { private: true })}>🔒 Unpublish</button>
                  <button type="button" className="mgma2-toolbtn danger"
                    onClick={() => askBulk("delete", {})}>🗑 Delete</button>
                </>
              )}
              <button type="button" className="mgma2-toolbtn" disabled={selected.size === 0}
                onClick={() => setSelected(new Set())}>Clear</button>
              {bulkResult && (
                <span className="mgma2-bulkresult">
                  {bulkResult.ok} done{bulkResult.fail ? ", " + bulkResult.fail + " failed" : ""}
                </span>
              )}
              {bulkErr && <span className="mgma2-acterr">⚠ {bulkErr}</span>}
            </div>
          )}

          {/* Bulk confirm -- same shape as the per-card one, scoped to the whole batch. */}
          {bulkAsk && (
            <div className="mgma2-confirm">
              <div className="mgma2-confirmtitle">
                {bulkAsk.action === "delete"
                  ? "Delete " + bulkAsk.count + " artwork" + (bulkAsk.count === 1 ? "" : "s") + " from PixAI?"
                  : (bulkAsk.extra.private ? "Make " : "Make ") + bulkAsk.count + " item"
                    + (bulkAsk.count === 1 ? "" : "s") + (bulkAsk.extra.private ? " private" : " public") + " on PixAI?"}
              </div>
              <div className="mgma2-confirmbody">
                {bulkAsk.action === "delete" && (
                  <span className="warn">this can't be undone on PixAI (your local copies stay)</span>
                )}
                <div className="mgma2-confirmnote">No credits are spent by this action.</div>
              </div>
              <div className="mgma2-confirmacts">
                <button type="button" className="mgma2-toolbtn" onClick={() => setBulkAsk(null)} disabled={bulkBusy}>Cancel</button>
                <button type="button"
                  className={"mgma2-godone" + (bulkAsk.action === "delete" ? " danger" : "")}
                  onClick={confirmBulk} disabled={bulkBusy}>
                  {bulkBusy ? "working…" : bulkAsk.action === "delete" ? "Delete them" : "Do it"}
                </button>
              </div>
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
                  {media.map((it) => {
                    const isSel = selected.has(it.media_id);
                    return (
                    <div className={"mgma2-card" + (manageOn && isSel ? " sel" : "")}
                      key={it.media_id} role="button" tabIndex={0}
                      onClick={() => (manageOn ? toggleSelect(it.media_id) : (onOpenPost && onOpenPost(it.media_id)))}
                      onKeyDown={(e) => { if (e.key === "Enter") (manageOn ? toggleSelect(it.media_id) : (onOpenPost && onOpenPost(it.media_id))); }}>
                      <div className="mgma2-art">
                        <img src={it.thumb} alt="" loading="lazy"
                          onError={(e) => { e.currentTarget.style.visibility = "hidden"; }} />
                        {/* DC:2340-2341 -- the bulk-select checkbox replaces the visibility
                            badge while managing (it hides itself in manage mode below). */}
                        {manageOn ? (
                          <span className={"mgma2-checkbox" + (isSel ? " on" : "")}>{isSel ? "✓" : ""}</span>
                        ) : (
                          <span className={"mgma2-vis" + (it.public ? " pub" : " priv")}>
                            {it.public ? "◉ Public" : "🔒 Private"}
                          </span>
                        )}
                        {/* DC:698-702 hover actions, REAL -- hidden during manage mode so a
                            single-item action can't fire mid-selection. */}
                        {!manageOn && (
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
                        )}
                        {!manageOn && editing === it.media_id && (
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
                    );
                  })}
                </div>
              )
            )}

            {tab === "loras" && (
              lorasErr ? (
                <div className="mgma2-empty">couldn't load — {lorasErr}</div>
              ) : loras === null ? (
                <div className="mgh-loading">loading your models &amp; LoRAs…</div>
              ) : loras.length === 0 ? (
                <div className="mgma2-empty">Nothing here yet.</div>
              ) : (
                /* DC:775-805 -- 4:5 LoRA cards, real data from PixAI's own market
                   connection (src=mine). Not built: the DC's UNPUBLISHED lock -- the
                   route this rides on carries no visibility field for a LoRA row
                   (verified 2026-08-06), so it's left off rather than always-published
                   guessed; and the pager -- the DC's own was a no-op, and up to 48
                   LoRAs load in one page, past what any real account here has. */
                <div className="mgma2-loragrid">
                  {loras.map((m) => {
                    const [tc, tbg, tlabel] = baseTint(m.lora_base_model_type);
                    return (
                      <a className="mgma2-loracard" key={m.model_id}
                        href={"https://pixai.art/model/" + encodeURIComponent(m.model_id)}
                        target="_blank" rel="noreferrer">
                        <div className="mgma2-loraart">
                          {/* Same PixAI CDN cross-origin issue the Train picker's covers
                              hit (images-ng.pixai.art won't hotlink from localhost) --
                              same host-guarded proxy, and eager for the same reason
                              (this grid can sit below the fold too). */}
                          {m.cover_url ? <img src={"/api/pixai-cdn/thumb?u=" + encodeURIComponent(m.cover_url)} alt="" /> : null}
                          <span className="mgma2-lorabadge">◈ USER LORA</span>
                          <span className="mgma2-lorabase" style={{ color: tc, background: tbg, borderColor: tc }}>{tlabel}</span>
                          <div className="mgma2-loraname">{m.title}</div>
                        </div>
                        <div className="mgma2-lorastats">
                          <span className="fire">🔥 {fmt(m.ref_count)}</span>
                          <span>💬 {fmt(m.comment_count)}</span>
                          <span className="mgma2-lorapill">♥ {fmt(m.liked_count)}</span>
                        </div>
                      </a>
                    );
                  })}
                </div>
              )
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
