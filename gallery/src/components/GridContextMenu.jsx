import React, { useEffect, useRef, useState } from "react";
import "../styles/context-menu.css";

/* Right-click context menu for a grid thumbnail -- the five classic Ctx actions
   (Edit / Send to Video / Find similar / Copy id / Open details) brought onto the
   React grid (owner picked "all five", 2026-08-07), plus Remix (issue #4,
   2026-08-13: load the picture's full recipe into the Generate drawer). Every
   action is also reachable via left-click -> details/lightbox; this is the fast
   power-user path.

   Pure presentation: App owns the {mid, thumb, x, y} target and the action callbacks;
   this places itself (clamped to the viewport) and closes on any outside click, Escape,
   scroll, or resize. */
export default function GridContextMenu({ target, onClose, actions }) {
  const ref = useRef(null);
  const [pos, setPos] = useState({ left: target.x, top: target.y, ready: false });

  // Clamp into the viewport AFTER measuring (a menu opened near the right/bottom edge
  // would otherwise spill off-screen).
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const w = el.offsetWidth, h = el.offsetHeight;
    const vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;
    setPos({
      left: Math.max(6, Math.min(target.x, vw - w - 6)),
      top: Math.max(6, Math.min(target.y, vh - h - 6)),
      ready: true,
    });
  }, [target.x, target.y]);

  useEffect(() => {
    // Outside-click close. The capture-phase mousedown listener MUST skip clicks INSIDE the
    // menu (#28): otherwise it closes -- unmounts -- the menu on a menu item's OWN mousedown,
    // before that item's onClick can fire its action, so EVERY action was a silent no-op
    // ("right-click Remix dead" -- in fact the whole menu was dead). The wrapper's
    // bubble-phase onMouseDown stopPropagation can't help: a window capture listener fires
    // first. (scroll/resize/Escape still close unconditionally -- there's no "inside" for them.)
    const onDownOutside = (e) => { if (!(ref.current && ref.current.contains(e.target))) onClose(); };
    const close = () => onClose();
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("mousedown", onDownOutside, true);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDownOutside, true);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const run = (fn) => (e) => { e.stopPropagation(); onClose(); fn(); };

  const items = [
    ["✎", "Edit", () => actions.onEdit(target.mid)],
    ["▶", "Send to Video", () => actions.onVideo(target.mid, target.thumb)],
    // Remix works for videos now too (SCOPE_2026-08-17 §2): the drawer routes a video's
    // recipe to the Video tab and an image's to the Image tab (GenerateDrawer.prefillRun),
    // so the item is offered on every row -- the same reason the Details footer no longer
    // hides its Remix button on videos.
    ["↺", "Remix", () => actions.onRemix(target.mid)],
    // #28 scope-add: videos only -- re-extract this clip's poster on demand (same
    // POST /api/rebuild-poster route as Image Details' button). Gated on target.isVideo.
    ...(target.isVideo ? [["🖼", "Rebuild poster", () => actions.onRebuildPoster(target.mid)]] : []),
    // ◈, not the ✧ this row wore before: B2 of the 2026-09-04 Gallery Chrome
    // handoff makes ◈ the one mark for visual similarity everywhere in the app,
    // so this menu row, the tile's own hover door, the lightbox row and the
    // Details strip all wear it — and all push the same ◈ token into the bar.
    ["◈", "Find similar", () => actions.onSimilar(target.mid)],
    ["⧉", "Copy id", () => actions.onCopyId(target.mid)],
    ["⤢", "Open details", () => actions.onDetails(target.mid)],
  ];

  return (
    // The wrapper swallows its own mousedown so clicking a row doesn't trip the
    // capture-phase outside-close before the row's own onClick fires.
    <div ref={ref} className="mgctx" role="menu"
      style={{ left: pos.left, top: pos.top, visibility: pos.ready ? "visible" : "hidden" }}
      onMouseDown={(e) => e.stopPropagation()}>
      {items.map(([icon, label, fn], i) => (
        <button type="button" key={i} className="mgctx-item" role="menuitem" onClick={run(fn)}>
          <span className="mgctx-ico" aria-hidden="true">{icon}</span>{label}
        </button>
      ))}
    </div>
  );
}
