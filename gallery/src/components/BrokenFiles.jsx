import React, { useEffect, useRef, useState } from "react";
import CurateToast from "./CurateToast.jsx";
import MoonGauge from "./MoonGauge.jsx";
import useDataSaver from "../hooks/usePhonePrefs.js";
import { fractionOf } from "../lib/moonGaugeCore.js";
import { setBrokenFilesModalUp } from "../lib/brokenFilesNav.js";
import {
  ACTION_LABEL, ARCHIVE_TIP, ARCHIVE_WORD, bytesLine, byteFraction, chipOrAll, confirmLines, fixPlan,
  headerSummary, lostLine, middleEllipsis, pillFor, problemWords, rowAction, rowsFor, runHeader,
  shortId, sizeText, visibleChips,
} from "../lib/brokenFilesCore.js";
import "../styles/broken-files.css";

/* Health's Broken files section, desktop (Session W; Archive Integrity Handoff §1, §2, §5).

   It sits under Health's tiles and above the storage bars, and only when the last integrity
   check found broken rows. Chips: All · Zero-byte · Thumbnail · Suspect · Lost, each with its
   count, zero-count chips hidden. A row is 46 px: the thumbnail (or a dashed "?"), the short id
   in mono over "problem · path" (cut in the middle; the whole path in the title), the size, the
   pill, then only the action that applies and ⋯ (Open details · Mark lost · Copy path).

   A LOST row PixAI no longer has carries ARCHIVE beside LOST, says why in one line, and offers
   Open details · Keep as is. It never offers a re-download -- and the server's runner refuses
   one by itself, whatever this screen sends.

   Data and actions: hooks/useBrokenFiles.js (`bf`, owned by HealthOverlay so its tiles can read
   the same counts). Nothing here deletes anything. */

function copyText(text) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).catch(() => {});
  } catch { /* nothing to do */ }
}

export function Pill({ label, tone, title }) {
  return <span className={"mgbf-pill" + (tone ? " " + tone : "")} title={title || undefined}>{label}</span>;
}

/* One row: the 46 px line, then -- for a LOST row PixAI no longer has -- its reason and buttons,
   and for the row being fixed, the byte bar. (The phone draws its own 64 px row from the same
   core helpers; it reuses only Pill from this file.) */
function BrokenRow({ row, bf, menuOpen, setMenu, onOpenDetails, maxPath }) {
  const ref = useRef(null);
  const mid = row.media_id;
  const active = !!(bf.current && bf.current.media_id === mid);
  const result = bf.results[mid];
  const fixed = !!bf.fixedNow[mid];
  const failed = result && !result.ok && !active ? result : null;
  const act = bf.running ? null : rowAction(row, bf.readOnly);
  const line = lostLine(row);
  const pill = active ? { label: "…", tone: "" } : pillFor(row, fixed);
  const second = active
    ? (row.action === "redownload" ? bytesLine(bf.current) : "rebuilding the thumbnail…")
    : fixed
      ? (row.action === "redownload" ? "re-downloaded" : "thumbnail rebuilt")
      : failed
        ? failed.error
        : problemWords(row) + " · " + middleEllipsis(row.path, maxPath || 48);
  const frac = active ? byteFraction(bf.current) : null;

  useEffect(() => {
    if (!menuOpen) return undefined;
    const off = (e) => { if (ref.current && !ref.current.contains(e.target)) setMenu(null); };
    document.addEventListener("mousedown", off);
    return () => document.removeEventListener("mousedown", off);
  }, [menuOpen, setMenu]);

  const showMenu = !active && !fixed && !line;
  return (
    <div className="mgbf-item" ref={ref}>
      <div className={"mgbf-row" + (failed ? " failed" : "") + (fixed ? " fixed" : "")} data-mid={mid}>
        {row.thumb ? (
          <span className="mgbf-thumb" aria-hidden="true"
            style={{ backgroundImage: "url('/thumbs/" + encodeURIComponent(mid) + ".jpg')" }} />
        ) : (
          <span className="mgbf-thumb none" aria-hidden="true">?</span>
        )}
        <div className="mgbf-main" title={row.path}>
          <div className="mgbf-id">{shortId(mid)}</div>
          <div className="mgbf-prob">{second}</div>
        </div>
        {!active && sizeText(row) ? <span className="mgbf-size">{sizeText(row)}</span> : null}
        <Pill label={pill.label} tone={pill.tone} />
        {row.archive_only && !active && !fixed ? <Pill label={ARCHIVE_WORD} title={ARCHIVE_TIP} /> : null}
        {act && !fixed && !active ? (
          <button type="button" className="mgbf-ghost" onClick={() => bf.fix([{ media_id: mid, action: act }])}>{ACTION_LABEL[act]}</button>
        ) : null}
        {showMenu ? (
          <button type="button" className="mgbf-ghost mgbf-more" aria-label="More" aria-expanded={menuOpen}
            onClick={() => setMenu(menuOpen ? null : mid)}>⋯</button>
        ) : null}
        {menuOpen ? (
          <div className="mgbf-pop" role="menu">
            <button type="button" role="menuitem" onClick={() => { setMenu(null); onOpenDetails && onOpenDetails(mid); }}>Open details</button>
            {row.state !== "lost" ? (
              <button type="button" role="menuitem" onClick={() => { setMenu(null); bf.mark(mid, "lost", "Marked lost. Nothing was deleted."); }}>Mark lost</button>
            ) : null}
            <button type="button" role="menuitem" onClick={() => { setMenu(null); copyText(row.path); bf.say("Path copied."); }}>Copy path</button>
          </div>
        ) : null}
      </div>
      {frac != null ? (
        <div className="mgbf-bar" aria-hidden="true"><i style={{ width: (frac * 100) + "%" }} /></div>
      ) : null}
      {line ? (
        <>
          <div className="mgbf-lostline">{line}</div>
          <div className="mgbf-lostacts">
            <button type="button" className="mgbf-ghost" onClick={() => onOpenDetails && onOpenDetails(mid)}>Open details</button>
            <button type="button" className="mgbf-ghost" onClick={() => bf.mark(mid, "kept", "Kept as it is.")}>Keep as is</button>
          </div>
        </>
      ) : null}
    </div>
  );
}

/* "Fix all recoverable" confirms ONCE (W3c): the total, the re-downloads with their estimated
   size, the local rebuilds, the lost files left alone, "Nothing is deleted." -- and on a metered
   connection Data saver's line. No "don't ask again". Its own rung above Health's slab
   (broken-files.css, 428/429; dev/tests/test_z_ladder.py). Exported for the phone's bottom sheet,
   which shows the same lines. */
export function FixConfirm({ plan, metered, onCancel, onGo }) {
  const c = confirmLines(plan, metered);
  useEffect(() => {
    setBrokenFilesModalUp(true);
    const onKey = (e) => { if (e.key === "Escape") onCancel(); };
    window.addEventListener("keydown", onKey, true);
    return () => { setBrokenFilesModalUp(false); window.removeEventListener("keydown", onKey, true); };
  }, [onCancel]);
  return (
    <>
      <div className="mgbf-scrim" onClick={onCancel} aria-hidden="true" />
      <div className="mgbf-host">
        <div className="mgbf-confirm" role="alertdialog" aria-label={c.title}>
          <div className="mgbf-ctitle">{c.title}</div>
          {c.lines.map((l) => <div className="mgbf-cline" key={l}>{l}</div>)}
          <div className="mgbf-cacts">
            <button type="button" className="mgbf-ghost" onClick={onCancel}>Cancel</button>
            <button type="button" className="mgbf-btn" onClick={onGo} autoFocus>{c.go}</button>
          </div>
        </div>
      </div>
    </>
  );
}

export default function BrokenFiles({ bf, chip, setChip, onOpenDetails, sectionRef }) {
  const [menu, setMenu] = useState(null);
  const [asking, setAsking] = useState(false);
  const saver = useDataSaver();
  const metered = !!(saver.active && saver.info && saver.info.metered);
  const doc = bf.doc;
  const chips = visibleChips(doc && doc.counts);
  const shown = chipOrAll(chips, chip);
  const rows = rowsFor(doc, shown, bf.gone);
  const plan = fixPlan(doc, bf.readOnly, bf.done);
  const go = () => { setAsking(false); if (plan.total) bf.fix(plan.items); };
  return (
    <section className="mgbf" ref={sectionRef} aria-label="Broken files">
      <div className="mgbf-head">
        <div className="mgbf-title">Broken files</div>
        {bf.running && bf.status ? (
          <>
            <span className="mgbf-run">{runHeader(bf.status)}</span>
            <MoonGauge fraction={fractionOf(bf.status.done, bf.status.total)} size={16} bar={false}
              label="Fixing broken files" />
            <button type="button" className="mgbf-ghost" onClick={() => bf.stop()}>Stop</button>
          </>
        ) : (
          <>
            <span className="mgbf-sum">{headerSummary(doc)}</span>
            {plan.total > 0 ? (
              <button type="button" className="mgbf-btn" onClick={() => setAsking(true)}>
                {"Fix all recoverable (" + plan.total + ")"}
              </button>
            ) : null}
          </>
        )}
      </div>
      {asking ? (
        <FixConfirm plan={plan} metered={metered} onCancel={() => setAsking(false)} onGo={go} />
      ) : null}
      {bf.readOnly ? (
        <div className="mgbf-warn">Read-only mode is on, so files won{"’"}t be re-downloaded. Thumbnails can still be rebuilt.</div>
      ) : null}
      <div className="mgbf-chips" role="tablist" aria-label="Problem">
        {chips.map((c) => (
          <button type="button" key={c.key} role="tab" aria-selected={shown === c.key}
            className={"mgbf-chip" + (shown === c.key ? " on" : "")} onClick={() => setChip(c.key)}>
            {c.label} {c.n}
          </button>
        ))}
      </div>
      <div className="mgbf-rows">
        {rows.map((r) => (
          <BrokenRow key={r.media_id} row={r} bf={bf} menuOpen={menu === r.media_id} setMenu={setMenu}
            onOpenDetails={onOpenDetails} />
        ))}
        {!rows.length ? <div className="mgbf-empty">Nothing under this chip now.</div> : null}
      </div>
      <CurateToast toast={bf.toast} onUndo={bf.undo} onDismiss={bf.dismiss} />
    </section>
  );
}
