import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import "../styles/command-palette.css";

/* THE COMMAND PALETTE + its two companion surfaces, built pixel-for-pixel off
   design/command-palette/Command Palette.dc.html (moonglade-internal) -- frames A-G for the
   states, frame H for every measurement, token, motion pair and z rung. Nothing here decides
   WHAT a command does: App.jsx hands down the list, hooks/useCommandPalette.js owns the
   keyboard layer and the state, palette/paletteCore.js owns the matching. This file is the
   render, and the row grammar it renders is the locked visual.

   Three exports, three frames:
     CommandPalette  A (open/empty) · B (filtering) · C (no results) · D (contextual) · E (scrolled)
     ShortcutSheet   G -- the ? cheat-sheet, four columns, its own scrim one rung higher
     GPendingChip    F -- the two-stroke G… waiting state, no scrim, no motion */

/* One list row. `sel` is the keyboard highlight -- --accent 13% fill + a 45% inset ring,
   icon flipped to --accent (frame A's `sel` note). Hover is a separate, quieter state, so a
   mouse resting on the list never fights the keyboard for what "current" means. */
function Row({ row, sel, onRun, onHover }) {
  const { cmd, parts } = row;
  return (
    <button
      type="button"
      data-row={row.index}
      className={"mgpal-row" + (sel ? " sel" : "")}
      onMouseMove={onHover}
      onClick={onRun}
    >
      <span className="mgpal-ico" aria-hidden="true">{cmd.icon}</span>
      <span className="mgpal-label">
        {parts.map((p, i) => (
          <span key={i} className={p.hit ? "hit" : undefined}>{p.t}</span>
        ))}
      </span>
      {cmd.sub ? <span className="mgpal-sub">{cmd.sub}</span> : null}
      <span className="mgpal-spacer" />
      {cmd.right ? (
        <span className={"mgpal-right" + (cmd.rightKind === "pill" ? " pill" : "")}>{cmd.right}</span>
      ) : null}
      {(cmd.keys || []).length ? (
        <span className="mgpal-keys">
          {cmd.keys.map((k) => <span key={k} className="mgpal-key">{k}</span>)}
        </span>
      ) : null}
    </button>
  );
}

export function CommandPalette({ palette }) {
  const { open, closing, query, setQuery, sel, setSel, move, groups, count, close, runSelected, run } = palette;
  const inputRef = useRef(null);
  const listRef = useRef(null);
  // Which scroll fades to paint. Frame A shows only the bottom one (at the top of a
  // capped list); frames D and E add the top one once scrolled -- an affordance, so it
  // has to follow the real scroll position rather than being drawn unconditionally.
  const [fade, setFade] = useState({ up: false, down: false });

  // Auto-focus on the OPEN transition only: re-focusing on every render would fight a
  // command that just moved focus somewhere else during the deferred exit.
  useEffect(() => { if (open) inputRef.current && inputRef.current.focus(); }, [open]);

  const readFade = () => {
    const el = listRef.current;
    if (!el) return;
    setFade({
      up: el.scrollTop > 1,
      down: el.scrollTop + el.clientHeight < el.scrollHeight - 1,
    });
  };
  // Keep the selection visible while ↑↓ walks past the 388px cap (frame E's "↑↓ auto-scrolls
  // the selection into view"), and re-read the fades in the same pass. Layout effect, so the
  // scroll lands before paint instead of one frame late.
  useLayoutEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const row = el.querySelector('[data-row="' + sel + '"]');
    if (row) row.scrollIntoView({ block: "nearest" });
    readFade();
  }, [sel, count, open]);

  if (!open && !closing) return null;

  const onKeyDown = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
    else if (e.key === "Home") { e.preventDefault(); setSel(0); }
    else if (e.key === "End") { e.preventDefault(); setSel(Math.max(0, count - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); runSelected(); }
    // Escape is the hook's, in capture, so it can stop the app's other Escape handlers.
  };

  const cls = closing ? " closing" : "";
  return (
    <>
      <div className={"mgpal-scrim" + cls} onMouseDown={close} />
      <div className={"mgpal-host" + cls}>
        <div className={"mgpal" + cls} role="dialog" aria-label="Command palette">
          <div className="mgpal-inputrow">
            <span className="mgpal-sglyph" aria-hidden="true">⌕</span>
            <input
              ref={inputRef}
              className="mgpal-input"
              value={query}
              placeholder="Search commands, collections…"
              aria-label="Search commands"
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onKeyDown}
            />
          </div>

          {count === 0 ? (
            /* Frame C, copy locked (§8.6). No mascot, no illustration -- the palette is a
               power tool -- and the footer collapses to esc, because there is nothing to
               move to and nothing to run. */
            <div className="mgpal-none">
              <div className="mgpal-none-1">
                No commands match <span className="mgpal-none-q">&quot;{query}&quot;</span>
              </div>
              <div className="mgpal-none-2">Try a shorter fragment — matches land anywhere in a label.</div>
            </div>
          ) : (
            <div className="mgpal-listwrap">
              <div className="mgpal-list" ref={listRef} onScroll={readFade}>
                {groups.map((g) => (
                  <React.Fragment key={g.name}>
                    <div className="mgpal-hdr">
                      {g.name}
                      {g.extra ? <span className="mgpal-hdr-extra">{g.extra}</span> : null}
                    </div>
                    {g.rows.map((r) => (
                      <Row
                        key={r.cmd.id}
                        row={r}
                        sel={r.index === sel}
                        onRun={() => run(r.cmd)}
                        onHover={() => setSel(r.index)}
                      />
                    ))}
                  </React.Fragment>
                ))}
              </div>
              {fade.up ? <div className="mgpal-fade top" aria-hidden="true" /> : null}
              {fade.down ? <div className="mgpal-fade bot" aria-hidden="true" /> : null}
            </div>
          )}

          <div className="mgpal-foot">
            {count === 0 ? (
              <><span className="mgpal-fkey">esc</span><span>close</span></>
            ) : (
              <>
                <span className="mgpal-fkey">↑↓</span><span>move</span>
                <span className="mgpal-fkey gap">↵</span><span>run</span>
                <span className="mgpal-fkey gap">esc</span><span>close</span>
              </>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

/* Frame G. Four columns per BRIEF §4.6 (Navigate / Create / Image / General); a two-stroke
   combo reads `G` *then* `L`, the italic "then" being the notation everywhere. The palette's
   own keys live in the footer strip, not in the columns -- they are not global keys. */
const SHEET_COLS = [
  {
    title: "Navigate",
    items: [
      ["G", "then", "L", "Library"],
      ["G", "then", "S", "Storyboard (the Loom)"],
      ["G", "then", "C", "Control Panel"],
      ["/", "", "", "Jump to Search"],
    ],
  },
  { title: "Create", items: [["N", "", "", "New generation"]] },
  { title: "Image", items: [["R", "", "", "↻ Again — re-roll the focused image"]] },
  {
    title: "General",
    items: [
      ["Ctrl/⌘", "", "K", "Open the palette"],
      ["?", "", "", "This cheat-sheet"],
      ["Esc", "", "", "Close the top layer"],
    ],
  },
];

export function ShortcutSheet({ open, closing, onClose }) {
  if (!open && !closing) return null;
  const cls = closing ? " closing" : "";
  return (
    <>
      <div className={"mgks-scrim" + cls} onMouseDown={onClose} />
      <div className={"mgks-host" + cls}>
        <div className={"mgks" + cls} role="dialog" aria-label="Keyboard shortcuts">
          <div className="mgks-titlerow">
            <div className="mgks-title">Keyboard shortcuts</div>
            <div className="mgks-sub">desktop gallery · global keys fire only outside text fields</div>
            <button type="button" className="mgks-x" onClick={onClose} aria-label="Close">×</button>
          </div>
          <div className="mgks-cols">
            {SHEET_COLS.map((c) => (
              <div key={c.title} className="mgks-col">
                <div className="mgks-coltitle">{c.title}</div>
                {c.items.map(([k1, sep, k2, label]) => (
                  <div key={label} className="mgks-item">
                    <span className="mgks-key">{k1}</span>
                    {sep ? <span className="mgks-sep">{sep}</span> : null}
                    {k2 ? <span className="mgks-key">{k2}</span> : null}
                    <span className="mgks-label">{label}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
          <div className="mgks-foot">
            <span className="mgks-footcaps">Inside the palette</span>
            <span className="mgks-foottxt">type to filter</span>
            <span className="mgks-fkey">↑↓</span><span>move</span>
            <span className="mgks-fkey gap">↵</span><span>run</span>
            <span className="mgks-fkey gap">esc</span><span>close</span>
          </div>
        </div>
      </div>
    </>
  );
}

/* Frame F. Appears the instant G lands -- no scrim, no motion, bottom-centre -- and clears
   on the second key, any other key, Esc, or the 1.8s timeout (all of that is the hook's).
   The DC's one placement rule: it must sit ABOVE the Generate dock's slot when the dock is
   open. The dock's height is not a constant (collapsed vs expanded settings), so it is
   MEASURED at show time rather than guessed -- the same cross-tree DOM read GenerateDrawer
   already makes for .mgx-hdr / .mgx-sep. */
export function GPendingChip({ open }) {
  const [bottom, setBottom] = useState(16);
  useLayoutEffect(() => {
    if (!open) return;
    const dock = document.querySelector(".mgx-dock-host.open .mgdock");
    const h = dock ? dock.getBoundingClientRect().height : 0;
    setBottom(h ? Math.round(h) + 24 : 16);   // dock bottom is 14px; 10px of air above it
  }, [open]);
  if (!open) return null;
  return (
    <div className="mgpal-gchip" style={{ bottom }} role="status">
      <span className="mgpal-gkey">G</span>
      <span className="mgpal-gdots">…</span>
      <span className="mgpal-ghints">
        <b>L</b> Library · <b>S</b> Storyboard · <b>C</b> Control Panel
      </span>
    </div>
  );
}

export default CommandPalette;
