import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { FIX_COLORS, FIX_MAX_BOXES, FIX_MIN_PX, scaleBoxes } from "../gen/editCore.js";
import { submitTask, useResultLines } from "../gen/submitTask.js";
import usePriceProbe from "../gen/usePriceProbe.js";
import { ResultLines } from "./EditTab.jsx";
import CostBadge from "./CostBadge.jsx";

/* The Fix tab: drag boxes over hands and faces, PixAI repairs what is inside
   them. Two things make this surface unlike every other:
   - a Fix ALWAYS spends, at a flat rate invariant to box count, and NO free card
     can ever cover it (the fixer endpoint has no kaisuukenId field), so the
     price is quoted in the confirm before anything is submitted;
   - boxes are drawn in DISPLAY pixels but submitted in ORIGINAL-image pixels;
     the server does not rescale, so the scale factor decides which part of the
     picture is actually repaired.

   `dock` (Generate dock, 2026-08-16 fidelity pass -- the DC's ONE footer on
   every tab, genLabel '✦ Fix <kind>'): when given ({ topEl, promptEl, goEl,
   resultsEl, balance, expanded }), the CostBadge + Fix button render into the
   dock footer's right column, the tab's status line into the composer's prompt
   slot (a Fix has no prompt) and the result lines under the settings grid via
   portals -- SAME costRef, SAME run() with its spend confirm.

   THE SOURCE IS SHARED (dock fidelity stage 3): `source` comes from the drawer's
   Edit state, picked in slab 1 -- the DC's SOURCE list serves Edit, Fixer and
   Enhance alike (Frontend Gallery.dc.html 1445-1468, 1501 'the source'), so a
   picture picked on the Edit sub-tab is the one the Fixer boxes. Boxes are in
   that picture's DISPLAY pixels, so they reset whenever the source changes.

   WHAT THIS RENDERS: slab 2 (REGION, DC 1470-1471 + 1499-1508) of the Edit grid,
   verbatim: the 'REGION' heading (1471 + 2931 editSlabLabel), then the DC's flex
   column (1500, gap 8) -- the always-visible instruction 'Drag a box over the hand
   or face on the source.' (1501), the Face / Hand segmented track (1502-1505,
   segStyle 2834-2835 -- the sub-tab strip's own container + segments) and the peach
   money-honesty note (1506). Beneath those, REAL-DATA EXTRAS the DC never drew
   (checklist region 3, DOCUMENTED -- not defects): the box-drawing canvas over the
   source (boxes are what /api/fix repairs; the DC only says 'Drag a box…' as copy)
   and a 'Clear N' button. The DC's own per-tab Pick/Change is NOT here any more:
   the source is slab 1's (SourceSlab), exactly as the DC has it. */
export default function FixTab({ visible, dock, source }) {
  const [tag, setTag] = useState("face");
  const [boxes, setBoxes] = useState([]);
  const [busy, setBusy] = useState(false);
  const [lines, openLine] = useResultLines();
  const imgRef = useRef(null);
  const canvasRef = useRef(null);
  const wrapRef = useRef(null);
  const costRef = useRef(null);
  const drag = useRef(null);
  const busyRef = useRef(false);

  // Boxes are display-pixel rectangles over ONE picture: a new source (picked in slab 1
  // on any sub-tab, or handed in from the lightbox) invalidates every one of them.
  useEffect(() => { setBoxes([]); }, [source]);

  /* The ▲-collapsed dock hides the settings grid with display:none (DC 1209), and a
     hidden <img> reports clientWidth 0 -- scaleBoxes would then fall back to scale 1
     and SUBMIT DISPLAY PIXELS AS ORIGINAL PIXELS, repairing the wrong region. So the
     last real measurement (natural / client width, taken whenever the picture is laid
     out) is remembered and stands in for the element while it is hidden. The dock's
     width does not change between collapsed and expanded, so the remembered scale is
     the live one. */
  const measured = useRef(null);
  const scaleEl = () => {
    const img = imgRef.current;
    // live only once the picture is both laid out AND decoded (naturalWidth 0 = not
    // loaded yet -- a scale of 0 would zero every box)
    if (img && img.clientWidth && img.naturalWidth) {
      measured.current = { naturalWidth: img.naturalWidth, clientWidth: img.clientWidth };
      return img;
    }
    return measured.current;
  };

  /* ---- price: the shared probe (gen/usePriceProbe.js), like every other cost surface ----
     A Fix's ONLY safety net is the confirm dialog's wording, and classic and pilot both let
     the settled figure sit null until the round trip landed, so clicking Fix right after the
     last box (a completely normal thing to do) could open a confirm reading "price could not
     be verified" even though the real number was one moment away (owner QA 2026-07-30:
     "works but never sends" -- it always sent, but a plausible read of an uncertain confirm
     is to cancel). run() used to flush the debounce and await the in-flight promise to close
     that window; it no longer has to. The probe's identity gate keeps ✦ Fix unpressable until
     a verdict for THESE boxes has settled, so by the time the dialog can open, probe.response
     already holds that payload's answer -- the guarantee replaces the flush. */
  const build = useCallback(() => ({
    payload: { mode: "fix", source, boxes: scaleBoxes(boxes, scaleEl()) },
    idle: (source && boxes.length) ? null : true,
  }), [source, boxes]);
  // `enabled: visible` is the #27 cleanup and the DC's re-price-on-sub-tab-entry (2927) in one
  // seam: hidden, no timer is armed and no request is out (the badge is portaled into the
  // footer and unmounts with the tab); becoming visible again forces a re-price, because the
  // badge comes back idle whatever the settled verdict says.
  const probe = usePriceProbe({ build, costRef, enabled: visible });

  useEffect(() => { probe.refresh(); }, [source, boxes, probe.refresh]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ---- the canvas: draw, paint, resize ---- */
  const paint = useCallback(() => {
    const c = canvasRef.current, img = imgRef.current;
    if (!c || !img) return;
    const w = img.clientWidth, h = img.clientHeight;
    if (!w || !h) return;
    if (img.naturalWidth) measured.current = { naturalWidth: img.naturalWidth, clientWidth: w };
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    const ctx = c.getContext("2d");
    ctx.clearRect(0, 0, w, h);
    const draw = (b) => {
      ctx.strokeStyle = FIX_COLORS[b.tag] || FIX_COLORS.face;
      ctx.lineWidth = 2;
      ctx.strokeRect(b.x, b.y, b.w, b.h);
      ctx.fillStyle = ctx.strokeStyle;
      ctx.font = "11px system-ui";
      ctx.fillText(b.tag, b.x + 3, b.y + 13);
    };
    boxes.forEach(draw);
    if (drag.current) draw({ ...drag.current, tag });
  }, [boxes, tag]);

  // (re)paint on box/tag changes and whenever the ▲ settings re-open: while the grid was
  // display:none the picture had no size, so a source picked or handed in meanwhile
  // never got its canvas sized -- the first visible layout does it.
  const expandedNow = dock ? dock.expanded : undefined;
  useEffect(() => { paint(); }, [paint, expandedNow]);
  useEffect(() => {
    const onResize = () => paint();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [paint]);

  const rel = (e) => {
    const r = canvasRef.current.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };
  const onDown = (e) => {
    if (e.button !== 0 || !source) return;
    const p = rel(e);
    drag.current = { x: p.x, y: p.y, w: 0, h: 0, ox: p.x, oy: p.y };
    e.preventDefault();
  };
  const onMove = (e) => {
    if (!drag.current) return;
    const p = rel(e);
    const d = drag.current;
    drag.current = {
      ...d,
      x: Math.min(d.ox, p.x), y: Math.min(d.oy, p.y),
      w: Math.abs(p.x - d.ox), h: Math.abs(p.y - d.oy),
    };
    paint();
  };
  const onUp = () => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    // the classic's minimum: a stray click is not a box
    if (d.w > FIX_MIN_PX && d.h > FIX_MIN_PX) {
      if (boxes.length >= FIX_MAX_BOXES) {
        if (window.Toast) {
          window.Toast.show({
            kind: "err", title: "That's the limit",
            msg: "A Fix carries at most " + FIX_MAX_BOXES + " boxes — the rest would be dropped server-side.",
          });
        }
      } else {
        setBoxes((old) => old.concat([{ x: d.x, y: d.y, w: d.w, h: d.h, tag }]));
      }
    }
    paint();
  };

  const run = async () => {
    if (busyRef.current || !source || !boxes.length) return;
    // PAYLOAD IDENTITY gate -- the button is already disabled on it; this is the click
    // that slips through a stale render (a keyboard Enter needs no repaint to fire). It
    // is ALSO what guarantees the number quoted below is this payload's.
    if (!probe.canSubmit) { probe.refresh(); return; }
    const d = probe.response;
    const priced = d && typeof d.cost === "number" ? d.cost : null;
    const quote = priced == null
      ? "The price could not be verified, and a Fix ALWAYS spends credits (no free card can cover it)."
      : "This will spend " + Number(priced).toLocaleString() +
        " credits — a Fix is never covered by a free card.";
    if (!window.confirm(
      "Repair " + boxes.length + " area" + (boxes.length === 1 ? "" : "s") + "?\n\n" + quote
    )) return;
    busyRef.current = true; setBusy(true);
    const emit = openLine("Submitting…");
    await submitTask("/api/fix",
      { source, boxes: scaleBoxes(boxes, scaleEl()) },
      { label: "Fixed", emit });
    busyRef.current = false; setBusy(false);
    // The submit DEBITED credits (a Fix always spends); the payload is byte-identical,
    // so only a FORCED re-price gets past the short-circuit.
    probe.refresh({ force: true });
  };

  if (!visible) return null;

  // The footer pieces (dock mode) -- one definition each, mounted inline or portaled.
  const inDock = !!dock;
  // genTitle -- REAL COPY (owner ruling 2026-08-16, checklist region 3 'Fixer submit
  // title / ready gating'): the DC's genTitle (3685) is one string pair for every tab --
  // 'Pick a model and write a prompt first' / 'Submit — this spends credits or a card' --
  // image-gen copy that is not tab-aware and, for a Fix, false twice over (no model, no
  // prompt; and no card can EVER cover a Fix). Same shape, true words: the not-ready
  // titles name the real gate (a source, then at least one box -- boxes are what /api/fix
  // repairs), the ready title says what the DC's says minus the card.
  const goTitle = !source ? "Pick a source image first"
    : !boxes.length ? "Drag at least one box first"
    : "Submit — this spends credits (a Fix is never card-covered)";
  // The price probe's verdict gates the button IN ADDITION to source/boxes/busy: the number
  // the confirm quotes must have been priced off the payload this click submits.
  const goOff = !source || !boxes.length || busy || !probe.canSubmit;
  const costLine = (
    /* no cardLabel: a Fix can never be card-covered */
    <CostBadge ref={costRef} hint="Drag a box over a hand or face to see the cost."
      stack={inDock || undefined} balance={inDock ? dock.balance : undefined} />
  );
  const goButton = inDock ? (
    <button type="button" className={"mgdock-gen" + (goOff ? " off" : "")} disabled={goOff}
      title={goTitle} onClick={run}><span>&#10022; Fix {tag}</span></button>
  ) : (
    <button className="gen" disabled={goOff} title={goTitle} onClick={run}>&#10022; Fix</button>
  );
  // The composer's line (a Fix has no prompt) -- the slab itself carries the DC's own
  // instruction copy (1501), so this only says where things stand.
  const statusNote = !source ? "Pick a source image in SOURCE, then drag a box over each hand or face to repair."
    : !boxes.length ? "Drag a box over a hand or face on the source — Face / Hand sets which."
    : "";
  // Composer top row (DC 1557-1562: pip · summary) + the prompt slot: a Fix has no prompt,
  // so the composer carries the tab's own status line instead of an empty box.
  const topRow = inDock ? (
    <>
      <span className="mgdock-modelchip static" title="Fixer — PixAI repairs what is inside your boxes">
        {source ? <img src={"/thumbs/" + encodeURIComponent(source) + ".jpg"} alt="" /> : <span className="mgdock-chipph" />}
        <span>Fixer</span>
      </span>
      <span className="mgdock-frames">{tag} · {boxes.length} {boxes.length === 1 ? "box" : "boxes"} · always spends</span>
    </>
  ) : null;
  const composerMsg = inDock ? (
    <div className="mgdock-composer-msg">
      {statusNote || ("Repairing " + boxes.length + (boxes.length === 1 ? " area" : " areas") + " — no prompt needed; the confirm quotes the price.")}
    </div>
  ) : null;

  // The result lines live OUTSIDE the ▲-gated grid in dock mode (a submit from the
  // collapsed footer must still be able to answer, incl. the "task MAY exist" warning).
  const results = lines.length ? <ResultLines lines={lines} /> : null;

  return (
    <div className="mgdock-slab" style={{ animationDelay: "60ms" }}>
      {inDock && dock.topEl ? createPortal(topRow, dock.topEl) : null}
      {inDock && dock.promptEl ? createPortal(composerMsg, dock.promptEl) : null}
      {inDock && dock.goEl ? createPortal(<>{costLine}{goButton}</>, dock.goEl) : null}
      {inDock && dock.resultsEl ? createPortal(results, dock.resultsEl) : null}
      {/* DC 1471 + 2931: editSlabLabel = 'REGION' under the Fixer sub-tab */}
      <div className="mgdock-lbl">REGION</div>
      {/* DC 1500-1507, verbatim: flex column gap 8 -> instruction copy (1501, 10.5px/1.5
          subtext, always visible) · Face / Hand segmented track (1502-1505: the same
          container + segStyle as the sub-tab strip; the pick is `tag`, DC fixKind, default
          'face') · the peach note (1506). The segments carry no per-tag colour -- the DC's
          segStyle has none; the tag colours (FIX_COLORS) live on the canvas strokes below,
          where they tell the boxes apart. */}
      <div className="mgdock-fixcol">
        <div className="mgdock-fixcopy">Drag a box over the hand or face on the source.</div>
        <div className="mgdock-segs" role="tablist" aria-label="Region kind">
          {[["face", "Face"], ["hand", "Hand"]].map(([t, l]) => (
            <button key={t} type="button" role="tab" aria-selected={tag === t}
              className={"mgdock-seg" + (tag === t ? " on" : "")}
              onClick={() => setTag(t)}>{l}</button>
          ))}
        </div>
        <div className="mgdock-peachnote">A fix can't be card-covered — it always spends, and always asks first.</div>

        {/* REAL-DATA EXTRAS (documented, not in the DC): the box canvas over the shared
            source -- boxes are the request (/api/fix {source, boxes}); drawn in display
            pixels, submitted in original pixels via scaleBoxes -- and the Clear button.
            The frame borrows the DC's preview-box chrome (fcPreviewBoxStyle 2948: radius
            10, 1px surface1, var(--base)) minus the square aspect: the picture must keep its
            own aspect because the boxes are laid out on it. */}
        {source ? (
          <div className="mgdock-fixwrap" ref={wrapRef}>
            <img ref={imgRef} src={"/full/" + encodeURIComponent(source)} alt=""
              onLoad={paint} draggable={false} />
            <canvas ref={canvasRef}
              onPointerDown={onDown} onPointerMove={onMove}
              onPointerUp={onUp} onPointerLeave={onUp} />
          </div>
        ) : null}
        {source ? (
          <div className="mgdock-fixrow">
            <span className="mgdock-note-sm">
              {boxes.length ? boxes.length + (boxes.length === 1 ? " box" : " boxes") + " · at most " + FIX_MAX_BOXES : "no boxes yet"}
            </span>
            <span className="sp" />
            <button type="button" className="gd-mini" onClick={() => setBoxes([])} disabled={!boxes.length}
              title="Remove every box">
              Clear{boxes.length ? " " + boxes.length : ""}
            </button>
          </div>
        ) : null}
      </div>
      {/* the status line lives in the dock composer in dock mode (composerMsg above) */}
      {!inDock && statusNote && <div className="gd-note">{statusNote}</div>}

      {!inDock && (
        <>
          <div className="gd-go">
            <span className="gd-cost">{costLine}</span>
            <span className="sp" />
            {goButton}
          </div>
          <ResultLines lines={lines} />
        </>
      )}
    </div>
  );
}
