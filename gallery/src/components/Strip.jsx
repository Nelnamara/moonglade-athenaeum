import React, { useEffect, useRef, useState } from "react";
import Flyout from "./Flyout.jsx";
import ActionsMenu from "./ActionsMenu.jsx";

// The classic's own rotating lines (moonglade_gallery.py, the tagline IIFE) --
// this component never got shipped to /next, so the tagline sat frozen. Owner
// QA 2026-07-30. Respects prefers-reduced-motion, same as the classic.
const TAGLINES = [
  "a library against the Void", "the archive remembers", "what the moon keeps",
  "every dream, kept", "a light in the Nightmare",
];
function useTagline() {
  const [i, setI] = useState(0);
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const id = setInterval(() => {
      setVisible(false);
      setTimeout(() => { setI((n) => (n + 1) % TAGLINES.length); setVisible(true); }, 500);
    }, 9000);
    return () => clearInterval(id);
  }, []);
  return { text: TAGLINES[i], visible };
}

/* The Mix's glass strip, live. Two rows:
   row 1 — brand · media pills · page/shelf groups · stats · backup pill
   row 2 — [Clear · Select · Actions] hugging the search slab, filter trio on its
           right, then the eye and the CTA run. Wrap groups are unbreakable (.nb)
           so nothing ever strands alone on a row. */
export default function Strip({
  boot, account,
  media, setMedia,
  perPage, setPerPage,
  shelf, setShelf,
  query, setQuery, submitQuery,
  blur, setBlur,
  selectMode, setSelectMode,
  selectedCount, selectedIds, clearSelection,
  collections, actions,
  adv, advCount, flyOpen, setFlyOpen, applyAdvanced,
  onGenerate, resetAll,
}) {
  const coverage = account && account.coverage_pct != null ? account.coverage_pct : null;
  const credits = account && account.credits != null ? Number(account.credits).toLocaleString() : null;
  const tagline = useTagline();
  const searchRef = useRef(null);

  /* The Advanced flyout must close on outside click and Escape -- it only closed
     via its own trigger before (owner QA 2026-07-30). Scoped to .srch so a click
     on the trigger button itself is never treated as "outside". */
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

  return (
    <div className="strip">
      {/* The brand is the strip's own LEFT COLUMN, a sibling of the rows -- not a
          member of row 1. As a row member it forced a spacer, and that spacer was
          the dead air beside the title the owner called out. The mark carries the
          chosen branding: --mark-url feeds the glint mask (a built stylesheet
          cannot Jinja-interpolate it) and anim-<name> drives the effect. */}
      <div className="brand">
        <span className={"mk anim-" + (boot.mark_anim || "classic")
                         + (boot.mark_kind === "tile" ? " mk-tile" : "")}
              style={{ "--mark-url": "url('" + (boot.mark_url || "/branding/logo.png") + "')" }}>
          <span className="mark-m">M</span>
          <img src={boot.mark_url || "/branding/logo.png"} alt=""
               onError={(e) => e.currentTarget.remove()} />
        </span>
        <div className="brand-txt">
          <div className="bn">Moonglade Athenaeum</div>
          <div className="tg">
            <span id="tagline" style={{ opacity: tagline.visible ? 1 : 0, transition: "opacity .5s" }}>
              {tagline.text}
            </span>
            <span className="ver" title="The React pilot — the classic gallery is untouched at /">
              next · {boot.build_stamp}
            </span>
          </div>
        </div>
      </div>
      <div className="strip-rows">
      <div className="row">
        <span className="gt-g gl">
        <div className="grp" role="radiogroup" aria-label="Media type">
          {["", "image", "video"].map((m) => (
            <button
              key={m || "all"}
              className={"g" + (media === m ? " on" : "")}
              onClick={() => setMedia(m)}
            >
              {m === "" ? "All" : m === "image" ? "Images" : "Videos"}
            </button>
          ))}
        </div>
        <div className="grp">
          <select
            className="g gsel"
            value={perPage}
            onChange={(e) => setPerPage(Number(e.target.value))}
            aria-label="Per page"
          >
            {[50, 100, 200].map((n) => (
              <option key={n} value={n}>{n} / page</option>
            ))}
          </select>
          <select
            className="g gsel"
            value={shelf}
            onChange={(e) => setShelf(e.target.value)}
            aria-label="Collection"
          >
            <option value="">All collections</option>
            {collections.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>
        </span>
        <span className="sp" />
        <span className="gt-g gr">
          {coverage != null && (
            <span className="bkd" title="How much of your PixAI history is archived locally">
              {coverage}% backed up
            </span>
          )}
        </span>
      </div>

      <div className="row">
        <div className="hug">
          <span className="nb">
            <button className="card" onClick={clearSelection} title="Empty the selection">
              Clear{selectedCount > 0 ? " " + selectedCount : ""}
            </button>
            <button
              className={"card" + (selectMode ? " on" : "")}
              onClick={() => setSelectMode(!selectMode)}
              title="Select mode: click images to toggle them"
            >
              Select{selectMode ? ": ON" : ""}
            </button>
            <ActionsMenu
              ids={selectedIds}
              shelf={shelf}
              isTrueLocal={boot.is_true_local}
              onAddCollection={actions.addCollection}
              onRemoveCollection={actions.removeCollection}
              onSendCast={actions.sendCast}
              onPrintSheet={actions.printSheet}
              onDownloadZip={actions.downloadZip}
              onReplacePrompt={actions.replacePrompt}
              onDeleteLocal={actions.deleteLocal}
              onDeleteCloud={actions.deleteCloud}
            />
          </span>
          <div className="srch" ref={searchRef}>
            <i>⚲</i>
            <input
              value={query}
              placeholder="search the library — night*, an id, model:tsubaki…"
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submitQuery()}
            />
            <button
              className={"adv" + (advCount > 0 ? " has" : "")}
              onClick={() => setFlyOpen(!flyOpen)}
              aria-expanded={flyOpen}
            >
              Advanced{advCount > 0 ? " " + advCount : ""} ▾
            </button>
            {flyOpen && (
              <Flyout
                boot={boot}
                current={adv}
                onApply={applyAdvanced}
                onClose={() => setFlyOpen(false)}
              />
            )}
          </div>
          <span className="nb">
            <button className="card" onClick={submitQuery}>Filter</button>
            <button className="card" onClick={resetAll}>Reset</button>
            {boot.is_true_local ? (
              <button className="card soon" disabled title="Import ports next — use the classic gallery meanwhile">
                &#8593; Import
              </button>
            ) : null}
          </span>
        </div>
        <span className="nb">
          <button
            className={"card eye" + (blur ? " on" : "")}
            onClick={() => setBlur(!blur)}
            title="Privacy blur: blur all thumbnails until you hover"
          >
            &#128065; {blur ? "Unblur" : "Privacy blur"}
          </button>
          {boot.is_local ? (
            <button className="gen" onClick={onGenerate} title="Open the Generate drawer">
              &#10022; Generate
            </button>
          ) : null}
          <a className="card loom" href="/loom" title="The Loom — video storyboard">&#9648; The Loom</a>
          <a className="card cred" href="/panel" title="Your PixAI balance — open the Control Panel">
            {credits ? <>&#9670; {credits}{account.cards != null ? <> &middot; &#127915; {account.cards}</> : null}</> : <>&#9670; &mdash;</>}
          </a>
        </span>
      </div>
      </div>
    </div>
  );
}
