import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { askPicker } from "./PickerHost.jsx";
import Flyout from "./Flyout.jsx";
import ActionsMenu from "./ActionsMenu.jsx";
import MgArtFilters from "../art/artFilters.js";
import "../styles/librarybar.css";

/* ============================================================================
   This file carries TWO surfaces during the parallel-workstream window:

   1. LibraryBar (the Library Bar workstream's deliverable, DC drift §10):
      search field · ⚲ Filters collapse pill (active-count badge, tray on its
      OWN ROW ABOVE the bar) · Clear · Select · Actions — the bar itself never
      wraps. Prop-compatible with Strip.jsx's contract ON PURPOSE: the
      integration pass swaps `<Strip …>` for `<FiltersPanel …>` (same props) in
      App.jsx's Banner libraryBar slot and the refit is live. Until then it is
      mounted nowhere and collides with nothing.

   2. ArtFiltersPanel (the art-filters compare panel this file used to be):
      GenerateDrawer.jsx — another workstream's file — still imports this
      module's DEFAULT export with {open, onClose, drawerRef, onSendToEdit}.
      Per the build map that panel becomes FilterCompare.jsx under the
      GenerateDock workstream; until that refit lands, breaking the live
      drawer to free a filename is a regression nobody asked for. So the
      default export DISPATCHES: the drawer's contract (a `drawerRef` prop)
      gets the preserved compare panel, verbatim; everything else gets the
      LibraryBar. When the dock workstream lifts the panel into
      FilterCompare.jsx, delete ArtFiltersPanel + the dispatcher here.
   ========================================================================== */

/* =============================== LIBRARY BAR ================================ */

/* Tray cycle-chips (DC filterChips). Values are the pilot's REAL filter values
   (Flyout.jsx's SOURCES/SORTS — mirrored here because Flyout doesn't export
   them and Flyout.jsx belongs to another workstream). The Sort chip cycles a
   short everyday subset; the full 12-option list stays in Advanced. Per the
   build map, perPage/shelf "either become tray chips or move into Advanced —
   flag for owner": they are tray chips here until the owner picks. */
const MEDIA_CYCLE = [["", "All"], ["image", "Images"], ["video", "Videos"]];
const SOURCE_CYCLE = [["", "All"], ["online", "PixAI history"], ["api", "Generated"],
  ["local", "Imported"], ["deleted", "Deleted on PixAI"]];
const SORT_CYCLE = ["newest", "oldest", "rating_desc", "aes_desc", "likes"];
const SORT_LABELS = {
  newest: "newest", oldest: "oldest", rating_desc: "highest rated",
  aes_desc: "aesthetic ↓", likes: "most liked",
};
const PER_CYCLE = [50, 100, 200];

function Chip({ label, active, onClick, title }) {
  return (
    <button type="button" className={"mgl-chip" + (active ? " on" : "")}
      onClick={onClick} title={title}>
      {label}
    </button>
  );
}

function cycleNext(list, cur) {
  const i = list.indexOf(cur);
  return list[(i + 1) % list.length]; // unknown value: (-1+1)=0 -> the baseline entry
}

/* The tray: its own full-width row ABOVE the search bar (DC filtersTrayStyle).
   Commits ride applyAdvanced — App.jsx's existing one-patch commit path — so
   every chip reuses the exact mechanism the Advanced flyout already commits
   through (media/shelf/perPage keys included). */
export function FilterTray({ closing, media, shelf, perPage, adv, collections, models, commit }) {
  const srcLabel = (SOURCE_CYCLE.find((s) => s[0] === (adv.source || "")) || SOURCE_CYCLE[0])[1];
  const mediaLabel = (MEDIA_CYCLE.find((m) => m[0] === (media || "")) || MEDIA_CYCLE[0])[1];
  const shelfOpts = [""].concat(collections || []);
  const stars = adv.ratingMin || 0;
  /* Model chip (DC filterChips lead with it). The DC cycles a 3-entry
     placeholder list; the real library has dozens of models, so cycling is
     unusable -- the chip opens an anchored list of the library's real models
     instead (owner-disclosed adaptation, 2026-08-01). Commits ride the same
     applyAdvanced path as the Advanced flyout's model field. */
  const [modelMenu, setModelMenu] = useState(null); // {x, y} anchor or null
  const modelBtn = useRef(null);
  useEffect(() => {
    if (!modelMenu) return;
    const onDown = (e) => {
      if (modelBtn.current && modelBtn.current.contains(e.target)) return;
      if (!e.target.closest || !e.target.closest(".mgl-menu")) setModelMenu(null);
    };
    const onKey = (e) => { if (e.key === "Escape") setModelMenu(null); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [modelMenu]);
  const openModelMenu = () => {
    const r = modelBtn.current.getBoundingClientRect();
    setModelMenu({ x: Math.max(10, Math.min(r.left, window.innerWidth - 252)), y: r.bottom + 8 });
  };
  const modelLabel = adv.model ? (adv.model.length > 18 ? adv.model.slice(0, 17) + "…" : adv.model) : "any";
  return (
    <div className={"mgl-tray" + (closing ? " closing" : "")}>
      <span ref={modelBtn}>
        <Chip label={"Model · " + modelLabel} active={!!adv.model}
          title="Filter by the model that made it"
          onClick={() => (modelMenu ? setModelMenu(null) : openModelMenu())} />
      </span>
      {modelMenu && (
        <div className="mgl-menu" style={{ left: modelMenu.x, top: modelMenu.y, maxHeight: "50vh", overflowY: "auto" }}>
          <div className="mgl-item" onClick={() => { commit({ model: "" }); setModelMenu(null); }}>any</div>
          {(models || []).map((m) => (
            <div key={m} className="mgl-item" onClick={() => { commit({ model: m }); setModelMenu(null); }}>{m}</div>
          ))}
        </div>
      )}
      <Chip label={"Media · " + mediaLabel} active={media !== ""}
        title="Cycle: All → Images → Videos"
        onClick={() => commit({ media: cycleNext(MEDIA_CYCLE.map((m) => m[0]), media || "") })} />
      <Chip label={"Source · " + srcLabel} active={!!adv.source}
        title="Where each file came from"
        onClick={() => commit({ source: cycleNext(SOURCE_CYCLE.map((s) => s[0]), adv.source || "") })} />
      <Chip label={"Sort · " + (SORT_LABELS[adv.sort] || adv.sort)} active={adv.sort !== "newest"}
        title="Everyday sorts — the full list lives in Advanced (▾ on the search field)"
        onClick={() => commit({ sort: cycleNext(SORT_CYCLE, adv.sort) })} />
      <Chip label={"★ " + (stars >= 5 ? "5" : stars + "+")} active={stars > 0}
        title="Minimum rating"
        onClick={() => commit({ ratingMin: (stars + 1) % 6 })} />
      <Chip label={"Collection · " + (shelf || "any")} active={!!shelf}
        title="Cycle through your collections"
        onClick={() => commit({ shelf: cycleNext(shelfOpts, shelf || "") })} />
      <Chip label={"Page · " + perPage} active={perPage !== 100}
        title="Results per page"
        onClick={() => commit({ perPage: cycleNext(PER_CYCLE, perPage) })} />
    </div>
  );
}

/* The library bar (DC drift §10). Same prop names as Strip.jsx so the swap-in
   is a one-line App change; `account`, `blur/setBlur`, `onGenerate` are
   accepted for that compatibility but unused — the shell's separator bar and
   banner own blur, credits and Generate now. Strip's Import stub is dropped:
   the NavSpine carries Import (gated on boot.is_true_local). */
export function LibraryBar({
  boot, account, // eslint-disable-line no-unused-vars
  media, setMedia, // setMedia unused directly: media commits via applyAdvanced
  perPage, setPerPage, // eslint-disable-line no-unused-vars
  shelf, setShelf, // eslint-disable-line no-unused-vars
  query, setQuery, submitQuery, resetAll,
  blur, setBlur, // eslint-disable-line no-unused-vars
  selectMode, setSelectMode,
  selectedCount, selectedIds, clearSelection,
  collections, actions,
  adv, advCount, flyOpen, setFlyOpen, applyAdvanced,
  onGenerate, // eslint-disable-line no-unused-vars
  onSendVideo, onMutated,
}) {
  const [trayOpen, setTrayOpen] = useState(false);
  const [trayClosing, setTrayClosing] = useState(false);
  const trayTimer = useRef(null);
  const searchRef = useRef(null);

  /* the pill's active-count badge: tray-visible filters (media/shelf) plus
     everything advCount already tracks (source/sort/rating/model/…). perPage
     is pagination, not a filter — it never lights the badge. */
  const activeCount = advCount + (media ? 1 : 0) + (shelf ? 1 : 0);

  // DC toggleFilters: mgTrayOut .2s runs on a still-mounted row, THEN unmount
  const toggleTray = () => {
    if (trayOpen && !trayClosing) {
      setTrayClosing(true);
      clearTimeout(trayTimer.current);
      trayTimer.current = setTimeout(() => { setTrayOpen(false); setTrayClosing(false); }, 200);
    } else {
      clearTimeout(trayTimer.current);
      setTrayOpen(true);
      setTrayClosing(false);
    }
  };
  useEffect(() => () => clearTimeout(trayTimer.current), []);

  /* Advanced flyout closes on outside click and Escape (ported verbatim from
     Strip.jsx — owner QA 2026-07-30). Scoped to the search slab so a click on
     the caret itself is never treated as "outside". */
  useEffect(() => {
    if (!flyOpen) return;
    const onDown = (e) => {
      if (searchRef.current && !searchRef.current.contains(e.target)) setFlyOpen(false);
    };
    const onKey = (e) => { if (e.key === "Escape") setFlyOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [flyOpen, setFlyOpen]);

  /* DC's Clear, copy-true to its title ("Clear the current filter and
     selection"): filters + query + selection + select mode, one press. The
     pilot's separate Reset button folds into this — flagged for the owner. */
  const clearAll = () => {
    resetAll();
    clearSelection();
    setSelectMode(false);
  };

  const trayShown = trayOpen || trayClosing;

  return (
    <div className="mgl-wrap">
      {trayShown && (
        <FilterTray
          closing={trayClosing}
          media={media} shelf={shelf} perPage={perPage} adv={adv}
          collections={collections}
          models={boot.models || []}
          commit={applyAdvanced}
        />
      )}
      <div className="mgl-bar">
        <div className={"mgl-search" + (flyOpen ? " open" : "")} ref={searchRef}>
          <i className="mgl-sglyph" onClick={() => submitQuery()} title="Search">⌕</i>
          <input
            value={query}
            placeholder="search the library — night*, an id, model:tsubaki…"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submitQuery()}
          />
          <button
            type="button"
            className={"mgl-scaret" + (flyOpen ? " open" : "")}
            onClick={() => setFlyOpen(!flyOpen)}
            aria-expanded={flyOpen}
            title="Advanced search, operators and saved views"
          >
            ▾
          </button>
          {flyOpen && (
            <Flyout
              boot={boot}
              current={adv}
              onApply={applyAdvanced}
              onClose={() => setFlyOpen(false)}
              onPrintCollection={actions && actions.printCollection}
              onSaveView={actions && actions.saveView}
              onDeleteView={actions && actions.deleteView}
              buildViewQuery={actions && actions.buildViewQuery}
            />
          )}
        </div>

        <button
          type="button"
          className={"mgl-pill mgl-filters"
            + (trayOpen && !trayClosing ? " open" : "")
            + (activeCount ? " lit" : "")}
          onClick={toggleTray}
          aria-expanded={trayOpen && !trayClosing}
          title="Show or hide the library filters"
        >
          <span>⚲ Filters{activeCount ? " · " + activeCount : ""}</span>
          <span className="mgl-caret8">{trayOpen && !trayClosing ? "◂" : "▸"}</span>
        </button>

        <button type="button" className="mgl-pill mgl-clear" onClick={clearAll}
          title="Clear the current filter and selection">
          Clear
        </button>

        <button
          type="button"
          className={"mgl-pill" + (selectMode ? " on" : "")}
          onClick={() => setSelectMode(!selectMode)}
          title="Select mode: click images to toggle them"
        >
          Select: {selectMode ? "ON" : "OFF"}
        </button>

        <ActionsMenu
          ids={selectedIds}
          shelf={shelf}
          isTrueLocal={boot.is_true_local}
          onSendCast={actions && actions.sendCast}
          onPrintSheet={actions && actions.printSheet}
          onDownloadZip={actions && actions.downloadZip}
          clearSelection={clearSelection}
          onSendVideo={onSendVideo}
          onMutated={onMutated}
        />
      </div>
    </div>
  );
}

/* ============================ ART FILTERS PANEL =============================
   Preserved from this file's previous life (see the header comment) except for
   place()'s geometry, updated below for the GenerateDock reshell (2026-08-02).
   Lifting this into its own FilterCompare.jsx is still open; not required for
   the panel to sit correctly relative to the new dock. */

/* Placement, adapted for the GenerateDock reshell (found by adversarial
   review, 2026-08-02): this used to be adaptive side-by-side against a
   RIGHT-docked side drawer (try left of it; below AF_MIN_SIDE, centre over
   the viewport). The dock is bottom-center now, capped at min(1180,
   100vw-32), so there is no "beside" a horizontally-centered panel -- the
   old left-side branch was dead code (leftRoom could never reach 1050 on any
   real viewport) and its vertical anchor (`r.top + 8`, meant to hug a tall
   side panel's own top) instead hugged the BOTTOM of the screen, since a
   bottom-anchored dock's top edge sits low -- overlapping the dock's own
   reel/composer. Now: always centred horizontally (matching what already
   happened in practice), and anchored ABOVE the dock's top edge with `gap`
   clearance, clamped on-screen. Two pictures are worth judging from about
   380px each: 380*2 + 28 (gap) + 26 (padding) = 814; AF_W keeps headroom. */
const AF_W = 1180;

/* Art filters -- what REPLACED the Enhance surface (owner, 2026-07-29: "Art
   filters replaced enhance. no need to rebuild [enhance]").

   This is a FLOATING panel beside the drawer, matching classic's
   #filters-flyout -- NOT a tab body (owner QA 2026-07-30: "it opens a
   floating panel in classic, you added it to the drawer inline"). Original
   and Preview render side by side so a filter is judged by comparison, not
   by toggling No filter back and forth from memory. #af-orig-equivalent is a
   SECOND <img> of the same /full/ url rather than a clone of the preview's:
   the preview image is what MgArtFilters mutates (a CSS filter, overlay divs
   at inset:0), and anything sharing that element would be filtered too,
   leaving nothing to compare against. Same-origin and already cached, so the
   second one costs a cache hit, not a download.

   These are NOT generations: the art-filter engine composites gradient layers
   in the browser, so nothing is sent, nothing is spent, and it works
   offline. Only the two exits touch the server -- Save (POST
   /api/import-local, local library write) and Send to image gen (POST
   /api/upload, a free S3 handshake). Deliberately keeps its OWN source pick
   rather than sharing the Edit tab's (that state lives inside EditTab, not
   lifted to the drawer) -- comparing a filter doesn't require committing to
   an edit source first. */
export function ArtFiltersPanel({ open, onClose, drawerRef, onSendToEdit }) {
  const AF = MgArtFilters;   // was window.MgArtFilters (static/mg-art-filters.js), now bundled
  const [source, setSource] = useState("");
  const [active, setActive] = useState(null);
  const [strength, setStrength] = useState(1);
  const [angle, setAngle] = useState(180);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const panelRef = useRef(null);
  const stageRef = useRef(null);
  const imgRef = useRef(null);
  const railRef = useRef(null);

  const opts = useCallback(() => ({ strength: Number(strength), angle: Number(angle) }), [strength, angle]);

  // swatch tiles, grouped -- painted by the library itself, built once per open panel
  useEffect(() => {
    if (!open || !AF || !railRef.current) return;
    const rail = railRef.current;
    if (rail.firstChild) return;
    AF.groups().forEach((grp) => {
      const head = document.createElement("div");
      head.className = "af-grp";
      head.textContent = grp.label;
      rail.appendChild(head);
      const grid = document.createElement("div");
      grid.className = "af-tiles";
      rail.appendChild(grid);
      grp.ids.forEach((id) => {
        const rec = AF.get(id) || {};
        const tile = document.createElement("button");
        tile.type = "button";
        tile.className = "af-tile";
        tile.title = (rec.name || id) + " · free, applied in your browser" + (rec.note ? " — " + rec.note : "");
        tile.dataset.afid = id;
        const sw = document.createElement("div");
        sw.className = "sw";
        const cap = document.createElement("div");
        cap.className = "cap";
        cap.textContent = (rec.name || id).replace("Filter ", "");
        tile.appendChild(sw);
        tile.appendChild(cap);
        grid.appendChild(tile);
        AF.renderSwatch(sw, id); // the tile IS that filter's own gradients, no art needed
      });
    });
  }, [open, AF]);

  /* Clicks on the rail, delegated so imperatively-painted tiles work. `open`
     MUST be in the deps: this component returns null while closed, so on the
     first run railRef.current is null and the listener binds to nothing --
     without re-running on the closed->open flip, every tile click is
     swallowed (the exact gotcha that bit the earlier inline build). */
  useEffect(() => {
    const rail = railRef.current;
    if (!rail) return;
    const onClick = (e) => {
      const t = e.target.closest && e.target.closest(".af-tile");
      if (t) setActive((cur) => (t.dataset.afid === cur ? null : t.dataset.afid));
    };
    rail.addEventListener("click", onClick);
    return () => rail.removeEventListener("click", onClick);
  }, [open]);

  useEffect(() => {
    const rail = railRef.current;
    if (!rail) return;
    rail.querySelectorAll(".af-tile").forEach((t) => {
      t.classList.toggle("on", t.dataset.afid === active);
    });
  }, [active, open]);

  // (re)apply the live preview -- pure CSS overlays, no pixels copied
  useEffect(() => {
    if (!open || !AF || !stageRef.current) return;
    const host = stageRef.current;
    AF.clearPreview(host);
    if (!active) { setMsg(source ? "" : "Pick an image first — then this filter previews over it."); return; }
    if (!source) { setMsg("Pick an image first — then this filter previews over it."); return; }
    const n = AF.applyPreview(host, active, opts());
    const rec = AF.get(active) || {};
    // normalizeLayers reports any layer it had to drop (an unmapped blend mode, a stop
    // colour that isn't a plain literal) -- the preview still renders, just without that
    // layer, so saying so is the difference between "this looks off" and a silent wrong result.
    setMsg(n.warnings && n.warnings.length ? n.warnings[0] : (rec.name || active) + " · nothing sent, nothing spent");
  }, [AF, active, source, opts, open]);

  /* Placement follows the drawer's own rect -- called on open, on either
     image's load (the panel's height depends on the picture's rendered
     height), and on resize. Two-pass like the classic: write width first,
     THEN measure offsetHeight (needs .open and the width already applied),
     THEN write left/top. */
  const place = useCallback(() => {
    const f = panelRef.current, d = drawerRef.current;
    if (!f || !d) return;
    const r = d.getBoundingClientRect();
    const vw = window.innerWidth, vh = window.innerHeight, pad = 8, gap = 10;
    const w = Math.min(AF_W, vw - pad * 2);
    const x = (vw - w) / 2;
    f.style.width = Math.round(w) + "px";
    // Cap available height to the room actually free ABOVE the dock, not the
    // whole viewport -- the two-pass measure below must never size the panel
    // taller than what fits without covering the dock either way.
    f.style.maxHeight = Math.max(120, r.top - gap - pad) + "px";
    const h = f.offsetHeight;
    f.style.left = Math.round(Math.max(pad, x)) + "px";
    // Bottom edge sits `gap` above the dock's top; clamped so it can never
    // start above the viewport's own top padding.
    f.style.top = Math.round(Math.max(pad, r.top - gap - h)) + "px";
  }, [drawerRef]);

  useLayoutEffect(() => { if (open) place(); }, [open, place]);

  useEffect(() => {
    if (!open) return;
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [open, place]);

  const pickSource = async () => {
    const m = await askPicker({ type: "image" });
    if (m) { setSource(m.media_id); setActive(null); }
  };

  const bake = async () => {
    if (!AF || !imgRef.current || !active) return null;
    return AF.toBlob(imgRef.current, active, opts());
  };

  const save = async () => {
    if (!active) { setMsg("Pick a filter first."); return; }
    setBusy(true);
    try {
      const blob = await bake();
      if (!blob) return;
      const fd = new FormData();
      // Strength/angle are part of the OUTPUT, not just the filter id -- without them in
      // the name, re-saving the same filter at a different slider position collides with
      // the first file's name and run_import_local's path-based dedup silently treats a
      // genuinely different image as the same one (owner 2026-07-29: "wont save its new
      // image... writing the same filename" -- confirmed against run_import_local, which
      // keys purely on filename, not content).
      const tag = active + "_s" + Number(strength).toFixed(2).replace(".", "") + "_a" + angle;
      fd.append("files", blob, source + "_" + tag + ".png");
      const r = await fetch("/api/import-local", { method: "POST", body: fd });
      const d = await r.json();
      if (d.error) {
        const friendly = r.status === 403
          ? "This only works when you're at the machine running the server — not over LAN/tablet."
          : d.error;
        setMsg(friendly);
        if (window.Toast) window.Toast.show({ kind: "err", title: "Not saved", msg: friendly });
        return;
      }
      const text = d.imported ? "Saved to your library." : "Already in your library (a duplicate).";
      setMsg(text);
      if (window.Toast) window.Toast.show({ kind: d.imported ? "ok" : "", title: text });
      if (d.imported) window.dispatchEvent(new CustomEvent("mg-gen-done"));
    } catch (e) {
      const m = "Couldn't save: " + (e && e.message ? e.message : "unknown error");
      setMsg(m);
      if (window.Toast) window.Toast.show({ kind: "err", title: "Not saved", msg: m });
    } finally { setBusy(false); }
  };

  const sendToEdit = async () => {
    if (!active) { setMsg("Pick a filter first."); return; }
    setBusy(true);
    try {
      const blob = await bake();
      if (!blob) return;
      const fd = new FormData();
      fd.append("file", blob, "filtered_" + active + ".png");
      const d = await fetch("/api/upload", { method: "POST", body: fd }).then((r) => r.json());
      if (d.error || !d.media_id) { setMsg(d.error || "Upload failed."); return; }
      const name = (AF.get(active) || {}).name || active;
      onClose();
      onSendToEdit(d.media_id);
      if (window.Toast) {
        window.Toast.show({ kind: "ok", title: "Filtered image is your edit source", msg: name + " · uploaded free, nothing generated yet" });
      }
    } catch (e) {
      setMsg("Couldn't send: " + (e && e.message ? e.message : "unknown error"));
    } finally { setBusy(false); }
  };

  if (!open) return null;
  return (
    <div className="af-panel" ref={panelRef} role="dialog" aria-label="Art filters">
      <div className="gd-head">
        <span className="gd-lbl" style={{ fontSize: 13, letterSpacing: 0, textTransform: "none" }}>&#9673; Art filters</span>
        <span className="sp" />
        <button className="card" onClick={onClose} aria-label="Close">&times;</button>
      </div>
      {!AF ? (
        <div className="gd-note">The art-filter library did not load on this page.</div>
      ) : (
        <div className="af-wrap">
          <div className="af-col">
            <div className="af-frame">
              <img alt="the unfiltered original" src={source ? "/full/" + encodeURIComponent(source) : undefined} onLoad={place} />
            </div>
            <div className="af-cap">Original</div>
          </div>
          <div className="af-col">
            <div className="af-frame">
              <div className="af-stage" ref={stageRef}>
                <img ref={imgRef} alt="filtered preview" src={source ? "/full/" + encodeURIComponent(source) : undefined} onLoad={place} />
              </div>
            </div>
            <div className="af-cap">Preview &middot; <b>{active ? (AF.get(active) || {}).name || active : "no filter"}</b></div>
          </div>
          <div className="af-rail">
            <div className="gd-row">
              <button className="card" onClick={pickSource}>{source ? "▨ Change" : "▨ Pick"}</button>
              <span className="gd-note">free · local</span>
            </div>
            <div ref={railRef} />
            <div className="gd-lbl">Strength <span style={{ color: "var(--lavender, var(--accent))" }}>{Number(strength).toFixed(2)}</span></div>
            <input type="range" min="0" max="1" step="0.01" value={strength}
              onChange={(e) => setStrength(e.target.value)} />
            <div className="gd-lbl">Angle <span style={{ color: "var(--lavender, var(--accent))" }}>{angle}&deg;</span></div>
            <input type="range" min="0" max="345" step="15" value={angle}
              onChange={(e) => setAngle(e.target.value)} />
            <div className="af-acts">
              <button type="button" className="card" onClick={() => setActive(null)}>No filter</button>
              <button type="button" className="gen" disabled={!active || !source || busy} onClick={save}>Save to library</button>
              <button type="button" className="card" disabled={!active || !source || busy} onClick={sendToEdit}
                title="Upload the filtered image to PixAI (free) and load it as the Edit source">
                Send to image gen
              </button>
              <button type="button" className="card" disabled title="Publishing to PixAI is not built yet">Publish</button>
            </div>
            {msg && <div className="af-msg">{msg}</div>}
          </div>
        </div>
      )}
    </div>
  );
}

/* ============================== DEFAULT EXPORT ==============================
   The compatibility dispatcher (see the file header): GenerateDrawer.jsx's
   mount always passes `drawerRef`, the LibraryBar contract never does. Delete
   this together with ArtFiltersPanel once the dock workstream's
   FilterCompare.jsx owns the compare panel. */
export default function FiltersPanel(props) {
  if ("drawerRef" in props) return <ArtFiltersPanel {...props} />;
  return <LibraryBar {...props} />;
}
