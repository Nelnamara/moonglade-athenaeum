import React, { useEffect, useRef, useState } from "react";
import useLibrary from "../hooks/useLibrary.js";
import useFlavour from "../hooks/useFlavour.js";
import useGenerate from "../gen/useGenerate.js";
import useEditGenerate from "../gen/useEditGenerate.js";
import { fetchAccount, fetchCollections } from "../api.js";
import GalleryMobile from "./GalleryMobile.jsx";
import CreateMobile, { MODES } from "./CreateMobile.jsx";
import VideoMode from "./VideoMode.jsx";
import ControlMobile from "./ControlMobile.jsx";
import TabBarMobile from "./TabBarMobile.jsx";
import MobileSheet from "./MobileSheet.jsx";
import PickerHost from "./PickerHost.jsx";
import "../styles/gallery-mobile.css";
import "../styles/create-mobile.css";

/* The mobile Gallery/Create/Control shell (design spec: Moonglade Mobile.dc.html)
   -- rendered by main.jsx in place of App.jsx whenever useIsMobile() is true,
   the THIRD mobile surface in gallery/src, following the exact pattern Login
   Mobile and Setup Wizard Mobile established: real logic lives in a shared hook
   (useLibrary.js, already extracted out of App.jsx for this), a new mobile
   presentation component consumes it, desktop is untouched.

   FIRST increment (2026-08-02) was Gallery-tab only. THIS increment adds the
   Create tab, Image mode (CreateMobile.jsx) on top of that, same shared-hook
   architecture throughout. What's real:
     - the hero (brand mark, stats, credits chip -- real boot.stats/account data,
       same /api/account App.jsx already calls) and the tab bar (TabBarMobile.jsx)
       switching Gallery/Create/Control;
     - the Gallery tab itself (GalleryMobile.jsx) -- fully wired to useLibrary(),
       lifted HERE (not called inside GalleryMobile) so filters/selection survive
       a Gallery <-> Create/Control tab switch instead of resetting on remount,
       matching App.jsx's own "the ONE place this state lives" call for the
       equivalent desktop refactor;
     - the Create tab's Image mode (CreateMobile.jsx) -- fully wired to
       useGenerate({ costRef }), lifted HERE for the identical reason useLibrary()
       was: a prompt/model/LoRA/frame/reference draft survives a Create <->
       Gallery/Control tab switch instead of resetting on remount. costRef is
       created here too (an imperative DOM handle to the real <mg-cost-badge>
       CreateMobile mounts, the same pattern GenerateDrawer.jsx uses);
     - cmode (Create's own Image/Edit/Video segmented-control state) and
       VideoMode itself (the shared <mg-generate-drawer> mount) -- lifted HERE
       2026-08-03 for a credit-safety reason, not just consistency: VideoMode
       mounts an element whose disconnectedCallback sweeps every outstanding
       poll timer for an already-charged, in-flight video render (see
       VideoMode.jsx's header comment). It was previously mounted INSIDE
       CreateMobile.jsx, which is itself only rendered while tab === "create"
       ({tab === "create" && <CreateMobile .../>} below) -- so switching the
       bottom nav to Gallery or Control unmounted it mid-submit and silently
       stopped tracking a job the server kept billing. Rendering VideoMode
       here, as a sibling OUTSIDE that conditional, means neither the inner
       segmented-control switch nor the outer tab switch ever removes it from
       the DOM -- only `visible` toggles display:none, same as before, one
       level higher. cmode/setCmode move up alongside it because CreateMobile's
       segmented control needs to keep selecting the SAME state VideoMode's
       visibility is computed from; CreateMobile still owns the segmented
       control's rendering, just reading/writing lifted state now instead of
       its own local state. See the .cm-videowrap render below for how this
       stays visually in the exact spot CreateMobile used to render it inline;
     - PickerHost -- mounted here for the first time on mobile (previously
       desktop-only, App.jsx's own mount). CreateMobile's Reference field calls
       the same askPicker() singleton EditTab/FixTab/FiltersPanel/GenerateDrawer
       already use; without a mounted host it silently resolves to null, so this
       is real wiring, not decoration;
     - The Loom sheet (hero's teal icon) -- a real link to /loom, which already
       works in landscape (docs/DECISIONS.md 2026-07-27: "the owner confirmed it
       already works well... only wants a link"), not a rebuild;
     - Log Out (Menu sheet) -- NavSpine.jsx's own POST /api/logout + cache-purge,
       ported verbatim (the one Menu item cheap enough, and important enough for
       a signed-in mobile session, to make real in this pass);
     - Create tab, Edit mode's own Edit sub-tab (2026-08-03) -- fully wired to
       useEditGenerate({ costRef: editCostRef }), lifted HERE for the IDENTICAL
       reason useGenerate() is: a picked source/refs/instruction/model draft
       survives a Create <-> Gallery/Control tab switch instead of resetting on
       CreateMobile's remount. editCostRef is its own separate ref (a second,
       dedicated <mg-cost-badge> handle) -- never shared with Image mode's
       costRef, matching editCore's own no-shared-debounce rule (see
       useEditGenerate.js's header comment). Fixer stays an honest sub-placeholder
       this increment (no touch-canvas box-drawing reference implementation
       exists anywhere yet); Enhance is not built at all on mobile (stays dead --
       see CreateMobile.jsx's header comment);
     - The Control tab (ControlMobile.jsx, 2026-08-03) -- a real full-page
       destination, NOT lifted above this conditional the way VideoMode was:
       its data layer (useControlPanel.js, extracted from ControlPanelOverlay.jsx
       the same day) already re-derives running-job state from the server on
       every mount, so unmounting it on a tab switch away from Control loses no
       tracking the way an unmounted <mg-generate-drawer> would -- see that
       hook's own header comment and ControlMobile.jsx's for the full "outer-
       tab-switch safety, checked explicitly" account. NOT passed `costRef`/
       `gen` state -- unrelated to Create's draft-generation surface entirely.

   What's an HONEST placeholder, not a shortcut on anything above:
     - Create's own Video mode (its segmented control's third leg), Edit's own
       Fixer sub-tab, and Create's Advanced screen render a soon-state
       note/toast -- see CreateMobile.jsx's own header comment for the full
       disclosure of what's deferred there and why.
     - The hero's gold Folio icon and the Menu sheet's other six destinations
       (My Art / Publish / Train / Import / Contests / Health) are each either
       their OWN separate mobile design file (Folio Mobile.dc.html) or a
       Control-tab-owned surface this increment doesn't build -- tapping one
       surfaces a disclosing toast via window.Toast (mg-notify.js, already
       loaded on this page) instead of a dead tap or a half-built screen. */

const MENU_SOON = [
  { icon: "📈", label: "My Art" },
  { icon: "✎", label: "Publish" },
  { icon: "⚗", label: "Train a LoRA" },
  { icon: "⬆", label: "Import" },
  { icon: "🏅", label: "Contests" },
  { icon: "♡", label: "Health" },
];

export default function AppMobile({ boot }) {
  const [tab, setTab] = useState("gallery");
  const [account, setAccount] = useState(null);
  const [collections, setCollections] = useState(boot.collections || []);
  const [sheet, setSheet] = useState(null); // 'loom' | 'menu' | null
  const [closing, setClosing] = useState(false);
  const fl = useFlavour(undefined, boot.build_stamp);
  const lib = useLibrary();
  const costRef = useRef(null);
  const gen = useGenerate({ costRef });
  const editCostRef = useRef(null); // Edit mode's OWN cost-badge handle -- never shared with Image's costRef
  const edit = useEditGenerate({ costRef: editCostRef });
  const [cmode, setCmode] = useState("image"); // Create's Image/Edit/Video mode -- lifted, see header comment

  useEffect(() => { fetchAccount().then(setAccount); }, []);

  const refreshCollections = async () => {
    const c = await fetchCollections();
    if (c) setCollections(c);
  };

  const closeSheet = () => {
    setClosing(true);
    setTimeout(() => { setSheet(null); setClosing(false); }, 280);
  };

  const soonToast = (label) => {
    if (window.Toast) window.Toast.show({ title: label, msg: "Its own mobile pass — coming later." });
  };

  // NavSpine.jsx's own logout(), ported verbatim (same /api/logout JSON POST +
  // cache-purge-then-navigate shape -- see that file's header comment for why).
  const logOut = () => {
    fetch("/api/logout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ csrf: boot.csrf || "" }),
    }).catch(() => {}).then(() => {
      const go = () => { window.location.href = "/login"; };
      if ("caches" in window) {
        caches.keys().then((ks) => Promise.all(ks.map((k) => caches.delete(k)))).catch(() => {}).then(go);
      } else {
        go();
      }
    });
  };

  const stats = boot.stats || {};
  const credits = account && account.credits != null ? Number(account.credits).toLocaleString() : "—";

  return (
    <div className="glm-stage">
      <header className="glm-hero">
        <div className="glm-hero-bg" aria-hidden="true" />
        <div className="glm-hero-scrim" aria-hidden="true" />
        <div className="glm-hero-icons">
          <button type="button" className="glm-iconbtn glm-iconbtn-gold" title="Folio of Honors"
            onClick={() => soonToast("Folio of Honors")}>🌙</button>
          <button type="button" className="glm-iconbtn glm-iconbtn-teal" title="The Loom — video storyboard"
            onClick={() => setSheet("loom")}>▮</button>
          <button type="button" className="glm-iconbtn glm-iconbtn-lav" title="More"
            onClick={() => setSheet("menu")}>☰</button>
        </div>
        <div className="glm-hero-stats">
          <span><b>{Number(stats.images || 0).toLocaleString()}</b> img</span>
          <span><b>{Number(stats.videos || 0).toLocaleString()}</b> vid</span>
          <span><b>{Number(stats.collections || 0).toLocaleString()}</b> coll</span>
        </div>
        <div className="glm-hero-brand">
          <div className="glm-hero-mark">
            {boot.mark_url ? <img src={boot.mark_url} alt="" /> : "✦"}
          </div>
          <div className="glm-hero-brandtext">
            <div className="glm-hero-name">Moonglade Athenaeum</div>
            <div className={"glm-hero-flavour" + (fl.fading ? " fading" : "")}
              onClick={fl.reveal} title="Click for version info">
              {fl.text}
            </div>
          </div>
        </div>
        <a className="glm-hero-credits" href="https://pixai.art/en/membership/credit-packs"
          target="_blank" rel="noopener noreferrer">
          ✦ {credits}
        </a>
      </header>

      <div className="glm-body">
        {tab === "gallery" && (
          <GalleryMobile boot={boot} collections={collections} refreshCollections={refreshCollections} {...lib} />
        )}
        {tab === "create" && (
          <CreateMobile account={account} costRef={costRef} editCostRef={editCostRef}
            cmode={cmode} setCmode={setCmode} edit={edit} {...gen} />
        )}
        {tab === "control" && (
          <ControlMobile account={account} />
        )}

        {/* VideoMode, lifted here (see header comment) so it survives a
            Gallery/Control tab switch, not just Create's own segmented
            control. Absolutely positioned over .glm-body -- already
            position:relative and already sized to exactly the hero/tab-bar
            gap (gallery-mobile.css) -- with an invisible ghost copy of the
            segmented control reserving the same vertical gap the REAL one
            (rendered by CreateMobile above, still visible/clickable through
            this overlay's pointer-events:none) occupies. See create-mobile.css's
            .cm-videowrap block for the full rationale. */}
        <div className="cm-videowrap" style={{ display: (tab === "create" && cmode === "video") ? "" : "none" }}>
          <div className="cm-pad">
            <div className="cm-seg3 cm-videospacer" aria-hidden="true">
              {MODES.map(([k, label, title]) => (
                <button key={k} type="button" tabIndex={-1} title={title}
                  className={"cm-segbtn" + (k === "video" ? " on" : "")}>{label}</button>
              ))}
            </div>
            <VideoMode visible={tab === "create" && cmode === "video"} />
          </div>
        </div>
      </div>

      <TabBarMobile tab={tab} setTab={setTab} />
      <PickerHost />

      <MobileSheet open={sheet === "loom"} closing={closing} onClose={closeSheet} title="THE LOOM">
        <div className="glm-loom-note">
          Weave shots into a video sequence. <b>Rotate to landscape</b> — the Loom is built for
          the wide surface, and portrait stays cramped.
        </div>
        <div className="glm-sheet-actions">
          <a className="glm-primary glm-primary-loom" href="/loom">Open The Loom</a>
          <button type="button" className="glm-metal glm-widebtn" onClick={closeSheet}>Not now</button>
        </div>
      </MobileSheet>

      <MobileSheet open={sheet === "menu"} closing={closing} onClose={closeSheet} title="MENU">
        <div className="glm-menu-list">
          {MENU_SOON.map((mi) => (
            <button key={mi.label} type="button" className="glm-menu-item soon"
              title={mi.label + " — its own mobile pass, coming later"}
              onClick={() => soonToast(mi.label)}>
              <span className="glm-menu-icon" aria-hidden="true">{mi.icon}</span>{mi.label}
            </button>
          ))}
          <button type="button" className="glm-menu-item" onClick={logOut}>
            <span className="glm-menu-icon" aria-hidden="true">⏻</span>Log Out
          </button>
        </div>
      </MobileSheet>
    </div>
  );
}
