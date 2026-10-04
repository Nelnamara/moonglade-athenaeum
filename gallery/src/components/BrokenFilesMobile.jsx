import React, { useState } from "react";
import MobileSheet from "./MobileSheet.jsx";
import MoonGauge from "./MoonGauge.jsx";
import CurateToast from "./CurateToast.jsx";
import { Pill } from "./BrokenFiles.jsx";
import useDataSaver from "../hooks/usePhonePrefs.js";
import { fractionOf, GAUGE_SIZES } from "../lib/moonGaugeCore.js";
import {
  ACTION_LABEL, ARCHIVE_TIP, ARCHIVE_WORD, bytesLine, byteFraction, chipOrAll, confirmLines, fixPlan,
  lostLine, pillFor, problemWords, rowAction, rowsFor, runHeader, shortId, visibleChips,
} from "../lib/brokenFilesCore.js";
import "../styles/broken-files.css";

/* The phone's Broken files screen (Session W, W6a; Archive Integrity Handoff §6). Pushed from
   Collection Health (HealthMobile.jsx) -- a problem tile opens it at that chip, the "Broken
   files ›" row at All -- as a second MobileScreen inside Health's own, the way Duplicates is.

   A chips row (36 px, scrolls sideways), 64 px rows (thumbnail, id, problem, pill), and a
   sticky "Fix all recoverable (N)" at the foot (drift 122's recipe: sticky to the scroller's
   foot with the home indicator's safe area under it). Tapping a row opens an action sheet:
   Re-download or Rebuild as they apply · Open details · Mark lost; a LOST row's sheet says
   why and offers Open details · Keep as is, never a re-download. Fix all confirms in a bottom
   sheet with the desktop's lines, plus Data saver's metered line. While a run goes, the top of
   the screen reads "n / N fixed" with the moon and Stop, and the Activity sheet mirrors it.

   Same hook as the desktop section (hooks/useBrokenFiles.js, `bf`, owned by HealthMobile so its
   tiles read the same counts), so the two can never disagree about a row. */

function useClosing(ms) {
  const [open, setOpen] = useState(null);
  const [closing, setClosing] = useState(false);
  const show = (v) => { setClosing(false); setOpen(v); };
  const hide = () => { setClosing(true); setTimeout(() => { setOpen(null); setClosing(false); }, ms); };
  return [open, closing, show, hide];
}

export default function BrokenFilesMobile({ bf, chip, setChip, onOpenDetails }) {
  const [rowOpen, rowClosing, openRow, closeRow] = useClosing(280);
  const [asking, askClosing, ask, unask] = useClosing(280);
  const saver = useDataSaver();
  const metered = !!(saver.active && saver.info && saver.info.metered);
  const doc = bf.doc;
  const chips = visibleChips(doc && doc.counts, true);
  const shown = chipOrAll(chips, chip);
  const rows = rowsFor(doc, shown, bf.gone);
  const plan = fixPlan(doc, bf.readOnly, bf.done);
  const sheetRow = rowOpen ? ((doc && doc.rows) || []).find((r) => r.media_id === rowOpen) : null;
  const c = confirmLines(plan, metered);

  const act = (fn) => { closeRow(); fn(); };
  return (
    <div className="mgbf-m">
      {bf.running && bf.status ? (
        <div className="mgbf-m-run">
          <span className="mgbf-run">{runHeader(bf.status)}</span>
          <MoonGauge fraction={fractionOf(bf.status.done, bf.status.total)} size={GAUGE_SIZES.phone} bar={false}
            label="Fixing broken files" />
          <span style={{ flex: 1 }} />
          <button type="button" className="mgbf-ghost" onClick={() => bf.stop()}>Stop</button>
        </div>
      ) : null}
      {bf.readOnly ? (
        <div className="mgbf-warn">Read-only mode is on, so files won{"’"}t be re-downloaded. Thumbnails can still be rebuilt.</div>
      ) : null}
      <div className="mgbf-m-chips" role="tablist" aria-label="Problem">
        {chips.map((ch) => (
          <button type="button" key={ch.key} role="tab" aria-selected={shown === ch.key}
            className={"mgbf-chip" + (shown === ch.key ? " on" : "")} onClick={() => setChip(ch.key)}>
            {ch.label} {ch.n}
          </button>
        ))}
      </div>
      <div className="mgbf-m-rows">
        {rows.map((r) => {
          const active = !!(bf.current && bf.current.media_id === r.media_id);
          const fixed = !!bf.fixedNow[r.media_id];
          const res = bf.results[r.media_id];
          const failed = res && !res.ok && !active ? res : null;
          const pill = active ? { label: "…", tone: "" } : pillFor(r, fixed);
          const frac = active ? byteFraction(bf.current) : null;
          return (
            <div className="mgbf-m-item" key={r.media_id}>
              <button type="button" className={"mgbf-m-row" + (failed ? " failed" : "")}
                onClick={() => { if (!active && !fixed) openRow(r.media_id); }}>
                {r.thumb ? (
                  <span className="mgbf-thumb" aria-hidden="true"
                    style={{ backgroundImage: "url('/thumbs/" + encodeURIComponent(r.media_id) + ".jpg')" }} />
                ) : (
                  <span className="mgbf-thumb none" aria-hidden="true">?</span>
                )}
                <span className="mgbf-main">
                  <span className="mgbf-id">{shortId(r.media_id)}</span>
                  <span className="mgbf-prob">
                    {active ? (r.action === "redownload" ? bytesLine(bf.current) : "rebuilding the thumbnail…")
                      : fixed ? (r.action === "redownload" ? "re-downloaded" : "thumbnail rebuilt")
                        : failed ? failed.error : problemWords(r)}
                  </span>
                </span>
                <span className="mgbf-m-pills">
                  <Pill label={pill.label} tone={pill.tone} />
                  {r.archive_only && !active && !fixed ? <Pill label={ARCHIVE_WORD} title={ARCHIVE_TIP} /> : null}
                </span>
              </button>
              {frac != null ? <div className="mgbf-bar" aria-hidden="true"><i style={{ width: (frac * 100) + "%" }} /></div> : null}
            </div>
          );
        })}
        {!rows.length ? <div className="mgbf-empty">Nothing under this chip now.</div> : null}
      </div>
      {!bf.running && plan.total > 0 ? (
        <div className="mgbf-m-foot">
          <button type="button" className="mgbf-btn" onClick={() => ask(true)}>
            {"Fix all recoverable (" + plan.total + ")"}
          </button>
        </div>
      ) : null}

      {/* the row's action sheet */}
      <MobileSheet open={!!sheetRow} closing={rowClosing} onClose={closeRow}
        title={sheetRow ? shortId(sheetRow.media_id) + " · " + problemWords(sheetRow) : ""}>
        {sheetRow ? (() => {
          const a = bf.running ? null : rowAction(sheetRow, bf.readOnly);
          const line = lostLine(sheetRow);
          return (
            <div className="mgbf-m-sheet">
              {line ? <div className="mgbf-lostline">{line}</div> : null}
              {a ? <button type="button" onClick={() => act(() => bf.fix([{ media_id: sheetRow.media_id, action: a }]))}>{ACTION_LABEL[a]}</button> : null}
              <button type="button" onClick={() => act(() => onOpenDetails && onOpenDetails(sheetRow.media_id))}>Open details</button>
              {line ? (
                <button type="button" onClick={() => act(() => bf.mark(sheetRow.media_id, "kept", "Kept as it is."))}>Keep as is</button>
              ) : sheetRow.state !== "lost" ? (
                <button type="button" onClick={() => act(() => bf.mark(sheetRow.media_id, "lost", "Marked lost. Nothing was deleted."))}>Mark lost</button>
              ) : null}
            </div>
          );
        })() : null}
      </MobileSheet>

      {/* Fix all's confirm: a bottom sheet with the desktop's lines */}
      <MobileSheet open={!!asking} closing={askClosing} onClose={unask} title={c.title}>
        <div className="mgbf-m-confirm">
          {c.lines.map((l) => <div className="mgbf-cline" key={l}>{l}</div>)}
        </div>
        <div className="glm-sheet-actions mgbf-m-cacts">
          <button type="button" className="mgbf-ghost" onClick={unask}>Cancel</button>
          <button type="button" className="mgbf-btn" onClick={() => { unask(); if (plan.total) bf.fix(plan.items); }}>{c.go}</button>
        </div>
      </MobileSheet>

      <CurateToast toast={bf.toast} onUndo={bf.undo} onDismiss={bf.dismiss} />
    </div>
  );
}
