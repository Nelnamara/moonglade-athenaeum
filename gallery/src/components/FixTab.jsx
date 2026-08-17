import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { FIX_COLORS, FIX_MAX_BOXES, FIX_MIN_PX, scaleBoxes } from "../gen/editCore.js";
import { submitTask, useResultLines } from "../gen/submitTask.js";
import { askPicker } from "./PickerHost.jsx";
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
   balance }), the CostBadge + Fix button render into the dock footer's right
   column and the tab's status line into the composer's prompt slot (a Fix has
   no prompt) via portals -- SAME costRef, SAME run() with its spend confirm. */
export default function FixTab({ visible, dock }) {
  const [source, setSource] = useState("");
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
  const seq = useRef(0);
  const timer = useRef(0);
  const costVal = useRef(null);   // the settled figure, for the confirm dialog

  /* ---- price: own debounce + seq, like every other cost surface ----
     `pending` holds the in-flight quote's promise. A Fix's ONLY safety net is
     the confirm dialog's wording -- classic and pilot both let costVal sit null
     until the round trip settles, so clicking Fix right after the last box (a
     completely normal thing to do) could open a confirm reading "price could
     not be verified" even though the real number was one moment away (owner QA
     2026-07-30: "works but never sends" -- it always sent, but a plausible read
     of an uncertain confirm is to cancel). run() now flushes and awaits this
     before it ever shows the dialog. */
  const pending = useRef(null);
  const fireCost = useCallback(() => {
    const mine = ++seq.current;
    const badge = costRef.current;
    if (!source || !boxes.length) {
      costVal.current = null;
      pending.current = null;
      if (badge && badge.clear) badge.clear();
      return null;
    }
    if (badge && badge.setChecking) badge.setChecking();
    const p = fetch("/api/price", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "fix", source, boxes: scaleBoxes(boxes, imgRef.current) }),
    })
      .then((r) => r.json())
      .then((d) => {
        if (mine !== seq.current) return;
        costVal.current = d && typeof d.cost === "number" ? d.cost : null;
        if (costRef.current) costRef.current.setPrice(d);
      })
      .catch(() => {
        if (mine !== seq.current) return;
        costVal.current = null;
        if (costRef.current) costRef.current.setPrice(null);
      })
      .finally(() => { if (pending.current === p) pending.current = null; });
    pending.current = p;
    return p;
  }, [source, boxes]);

  useEffect(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(fireCost, 250);
  }, [fireCost]);

  /* ---- the canvas: draw, paint, resize ---- */
  const paint = useCallback(() => {
    const c = canvasRef.current, img = imgRef.current;
    if (!c || !img) return;
    const w = img.clientWidth, h = img.clientHeight;
    if (!w || !h) return;
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

  useEffect(() => { paint(); }, [paint]);
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

  const pickSource = async () => {
    const m = await askPicker({ type: "image" });
    if (m) { setSource(m.media_id); setBoxes([]); }
  };

  const run = async () => {
    if (busyRef.current || !source || !boxes.length) return;
    // Flush a pending debounce so a click right after the last box doesn't
    // read a stale null, then await whatever quote is already in flight.
    if (timer.current) { clearTimeout(timer.current); timer.current = 0; fireCost(); }
    if (pending.current) await pending.current;
    const priced = costVal.current;
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
      { source, boxes: scaleBoxes(boxes, imgRef.current) },
      { label: "Fixed", emit });
    busyRef.current = false; setBusy(false);
  };

  if (!visible) return null;

  // The footer pieces (dock mode) -- one definition each, mounted inline or portaled.
  const inDock = !!dock;
  const goTitle = !source ? "Pick an image first"
    : !boxes.length ? "Drag at least one box"
    : "Submit the repair — always spends";
  const goOff = !source || !boxes.length || busy;
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
  const statusNote = !source ? "Pick an image, then drag a box over each hand or face to repair."
    : !boxes.length ? "Drag a box over a hand or face — the tag button above sets which."
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

  return (
    <div className="gd-body">
      {inDock && dock.topEl ? createPortal(topRow, dock.topEl) : null}
      {inDock && dock.promptEl ? createPortal(composerMsg, dock.promptEl) : null}
      {inDock && dock.goEl ? createPortal(<>{costLine}{goButton}</>, dock.goEl) : null}
      <div className="gd-row">
        <button className="card" onClick={pickSource}>
          {source ? "▨ Change" : "▨ Pick"}
        </button>
        {["face", "hand"].map((t) => (
          <button key={t} className={"gd-chip" + (tag === t ? " on" : "")}
            style={tag === t ? { borderColor: FIX_COLORS[t], color: FIX_COLORS[t] } : null}
            onClick={() => setTag(t)}>{t}</button>
        ))}
        <button className="gd-mini" onClick={() => setBoxes([])} disabled={!boxes.length}>
          Clear{boxes.length ? " " + boxes.length : ""}
        </button>
      </div>

      {source ? (
        <div className="gd-fixwrap" ref={wrapRef}>
          <img ref={imgRef} src={"/full/" + encodeURIComponent(source)} alt=""
            onLoad={paint} draggable={false} />
          <canvas ref={canvasRef}
            onPointerDown={onDown} onPointerMove={onMove}
            onPointerUp={onUp} onPointerLeave={onUp} />
        </div>
      ) : null}
      {/* the status line lives in the dock composer in dock mode (composerMsg above) */}
      {!inDock && statusNote && <div className="gd-note">{statusNote}</div>}

      {!inDock && (
        <div className="gd-go">
          <span className="gd-cost">{costLine}</span>
          <span className="sp" />
          {goButton}
        </div>
      )}

      <ResultLines lines={lines} />
    </div>
  );
}
