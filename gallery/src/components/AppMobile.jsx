import React, { useEffect, useRef, useState } from "react";
import useLibrary from "../hooks/useLibrary.js";
import useFlavour from "../hooks/useFlavour.js";
import useGenerate from "../gen/useGenerate.js";
import useEditGenerate from "../gen/useEditGenerate.js";
import { fetchAccount, fetchCollections, rateImage } from "../api.js";
import GalleryMobile from "./GalleryMobile.jsx";
import ImageDetailsMobile from "./ImageDetailsMobile.jsx";
import LightboxMobile from "./LightboxMobile.jsx";
import CreateMobile, { MODES } from "./CreateMobile.jsx";
import VideoMode from "./VideoMode.jsx";
import ControlMobile from "./ControlMobile.jsx";
import TabBarMobile from "./TabBarMobile.jsx";
import MobileSheet from "./MobileSheet.jsx";
import MobileScreen from "./MobileScreen.jsx";
import PickerHost from "./PickerHost.jsx";
import MyArtMobile from "./MyArtMobile.jsx";
import HealthMobile from "./HealthMobile.jsx";
import ImportMobile from "./ImportMobile.jsx";
import ContestsMobile from "./ContestsMobile.jsx";
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
     - Create's own Video mode (its segmented control's third leg) and Edit's
       own Fixer sub-tab render a soon-state note -- see CreateMobile.jsx's
       own header comment for the full disclosure of what's deferred there
       and why.
     - The hero's gold Folio icon is its OWN separate mobile design file
       (Folio Mobile.dc.html, not built this pass) -- tapping it surfaces a
       disclosing toast via window.Toast (mg-notify.js, already loaded on
       this page) instead of a dead tap.

   MENU NAVIGATION MECHANISM (2026-08-03) -- the Menu sheet's six destinations
   (My Art / Publish / Train / Import / Contests / Health) now push a REAL
   named screen instead of firing a soonToast() stub, using MobileScreen.jsx
   (already shipped, generic, reused as-is -- see CreateMobile.jsx's Advanced
   screen and ControlMobile.jsx's Branding drill-in for the two prior
   generic call sites this one now joins). What's real:
     - a single `screen` state (mirroring how `sheet` already generalizes
       MobileSheet.jsx to 'loom'/'menu'/null -- this does the same thing one
       level up for MobileScreen.jsx: one string key, one shared mount,
       content/title switch on the key, instead of six local open/closing
       boolean pairs repeated the way CreateMobile's advOpen/ControlMobile's
       brandOpen each are);
     - tapping a Menu row dismisses the sheet and pushes the screen in the
       SAME click (openScreen below) -- design_handoff's own menuItems onClick
       (`{ sheet: null, screen: 'X' }`, both in one setState) confirmed this is
       an instant sheet-dismiss for every row including Log Out, not the
       animated closeSheet() path scrim/other controls use; ported that way;
     - the push entry animation, back-chevron header chrome, and dismissal
       ownership contract are ALL MobileScreen.jsx's existing, unmodified
       contract (220ms open/closing pair, same as Advanced/Branding) -- no
       fork, no new push-screen component.
   REAL CONTENT (2026-08-03) -- four of the six pushed screens now render
   the real, live-data surface instead of the honest placeholder above: My
   Art, Collection Health, Import, and Contests. Each ported its desktop
   overlay's fetch/state logic into a shared hook (useMyArt.js/useHealth.js/
   useImport.js/useContests.js, gallery/src/hooks/) -- the SAME pattern
   useLibrary.js/useGenerate.js/useEditGenerate.js/useControlPanel.js already
   set 4 times this session -- so MyArtOverlay.jsx/HealthOverlay.jsx/
   ImportOverlay.jsx/ContestsOverlay.jsx (desktop) and MyArtMobile.jsx/
   HealthMobile.jsx/ImportMobile.jsx/ContestsMobile.jsx (mobile, rendered
   below) consume the exact same fetch, never a second copy of it. Each
   mobile component's own header comment discloses its real-data-vs-design-
   mock deviations in full (matching every desktop overlay's own precedent
   for the same kind of disclosure) -- summarized:
     - My Art: real stat labels kept (desktop's route can't back a plain
       "Views" total); row click-through to Details dropped -- no mobile
       Lightbox/Details surface exists anywhere yet.
     - Collection Health: all 12 real stat tiles shown (design mock only
       drew 8); a "Top models" section added (real, desktop has it, design
       omits it); tag/LoRA chips wired as LIVE filters through the lifted
       useLibrary() instance (see filterFromHealth below); Duplicates/
       Reclaimable render as plain, non-clickable tiles -- no mobile
       Duplicate Review surface exists yet (disclosed gap, not built this
       round, per instruction); word-cloud/folder-breakdown scoped out this
       pass (deliberate trim, not a "skip real data" call).
     - Import: one real file-picker button (native <input type="file">) --
       the design specifies no picker at all; "Browse a folder…" dropped
       (webkitdirectory has no reliable mobile support); collection picker
       is a real <select> of live `collections` data + new-collection input.
     - Contests: official/community split, live vote-type pills, real
       cover_url images, and pixai.art click-through all ported forward;
       community cards show a computed "days left" (design's own compact
       shape) instead of desktop's literal date range.
   Publish and Train stay honest placeholders -- see SOON_INFO below --
   because neither has ANY backend or desktop overlay anywhere in this app
   yet (unchanged from before this pass).

   IMAGE DETAILS MOBILE (2026-08-03) -- a plain tap on a Gallery tile outside
   select mode now opens the real Image Details screen (ImageDetailsMobile.jsx)
   instead of GalleryMobile.jsx's old "coming next" toast. detailsFor/
   openDetails/closeDetails, the rate() ported from App.jsx (no mobile
   equivalent existed -- the grid itself shows no stars), and the
   filterByModelFromDetails/filterByBatchFromDetails handlers all live HERE,
   lifted for the same reason cmode/VideoMode/lib are: Details must survive
   being opened from the Gallery tab and cover the WHOLE shell (hero + tab
   bar, not just .glm-body), so it mounts as a fixed overlay sibling below,
   not nested inside any one tab's own content. See ImageDetailsMobile.jsx's
   own header comment for the full scope disclosure (what's real vs. a
   disclosed placeholder) and useImageDetails.js for the shared data/action
   hook it and desktop's DetailsView.jsx both now consume.

   LIGHTBOX MOBILE (2026-08-03) -- Details' own "⛶ full-screen viewer" topbar
   button now opens the real LightboxMobile.jsx instead of its own "coming
   next" toast. `lbIndex` is lifted HERE for the identical reason `detailsFor`
   is (must survive/cover the whole shell), and is kept MUTUALLY EXCLUSIVE
   with `detailsFor` -- exactly mirroring desktop App.jsx's own lbIndex/
   detailsFor pairing (opening either one nulls the other). openLightbox
   resolves a media_id to its index in the SAME lib.items array Details/
   Gallery already share (Lightbox itself, like desktop's, reads chrome
   straight off that array -- see LightboxMobile.jsx's own header comment);
   openDetailsFromLightbox is the reverse trip, from the Lightbox's own
   "Details ›" pill. Real cross-page stepping reuses the SAME lib.page/
   lib.pages/lib.load this component already threads through for other
   purposes -- no second pagination copy. */

const MENU_ITEMS = [
  { icon: "📈", label: "My Art", screen: "myart" },
  { icon: "✎", label: "Publish", screen: "publish" },
  { icon: "⚗", label: "Train a LoRA", screen: "train" },
  { icon: "⬆", label: "Import", screen: "import" },
  { icon: "🏅", label: "Contests", screen: "contests" },
  { icon: "♡", label: "Health", screen: "health" },
];

// Per-screen header title -- text matches the design spec exactly (Health's
// screen is titled "Collection Health", not "Health" -- the row label and
// the pushed screen's title legitimately differ, same as the design mock).
// My Art/Import/Contests/Health render their own real component below
// (MyArtMobile/ImportMobile/ContestsMobile/HealthMobile.jsx); Publish/Train
// still render the honest placeholder in SOON_INFO -- neither has a backend
// or a desktop overlay ANYWHERE in this app yet (NavSpine.jsx's own desktop
// nav still marks both `soon: true`).
const SCREEN_TITLES = {
  myart: "My Art",
  publish: "Publish",
  train: "Train a LoRA",
  import: "Import",
  contests: "Contests",
  health: "Collection Health",
};

const SOON_INFO = {
  publish: [
    "Publish isn't built anywhere yet — desktop's own nav still marks it soon too, no backend route exists.",
    "Parked for a future pass.",
  ],
  train: [
    "Training isn't built anywhere yet — desktop's own nav still marks it soon too, no backend route exists.",
    "Parked for a future pass.",
  ],
};

export default function AppMobile({ boot }) {
  const [tab, setTab] = useState("gallery");
  const [account, setAccount] = useState(null);
  const [collections, setCollections] = useState(boot.collections || []);
  const [sheet, setSheet] = useState(null); // 'loom' | 'menu' | null
  const [closing, setClosing] = useState(false);
  // The Menu sheet's pushed-screen destination -- generalizes MobileScreen.jsx
  // the same way `sheet` above already generalizes MobileSheet.jsx (one
  // string key, one shared mount). null | 'myart' | 'publish' | 'train' |
  // 'import' | 'contests' | 'health'. See header comment.
  const [screen, setScreen] = useState(null);
  const [screenClosing, setScreenClosing] = useState(false);
  const fl = useFlavour(undefined, boot.build_stamp);
  const lib = useLibrary();
  const costRef = useRef(null);
  const gen = useGenerate({ costRef });
  const editCostRef = useRef(null); // Edit mode's OWN cost-badge handle -- never shared with Image's costRef
  const edit = useEditGenerate({ costRef: editCostRef });
  const [cmode, setCmode] = useState("image"); // Create's Image/Edit/Video mode -- lifted, see header comment

  // Image Details Mobile (2026-08-03) -- lifted HERE (not GalleryMobile.jsx)
  // for the identical reason `screen`/VideoMode/cmode are: it must survive
  // being opened from a tile tap and cover the WHOLE app shell (hero + tab
  // bar included, not just .glm-body), so it renders as a sibling of every
  // tab body below, same level as MobileScreen's own mount. No URL sync
  // (unlike desktop's bookmarkable /next?image=<mid>) -- see
  // ImageDetailsMobile.jsx's own header comment for why that's a deliberate,
  // separate scope call, not an oversight.
  const [detailsFor, setDetailsFor] = useState(null);
  const openDetails = (mid) => setDetailsFor(mid);
  const closeDetails = () => setDetailsFor(null);

  // Lightbox Mobile (2026-08-03) -- mutually exclusive with detailsFor, see
  // header comment. openLightbox is only ever called from Details (its own
  // ⛶ button), so `mid` is always present in the currently-loaded lib.items;
  // if it somehow isn't (a filter reloaded out from under an open Details
  // screen), this stays an honest toast rather than opening on a wrong index.
  const [lbIndex, setLbIndex] = useState(null);
  const openLightbox = (mid) => {
    const idx = lib.items.findIndex((it) => it.media_id === mid);
    if (idx < 0) {
      if (window.Toast) {
        window.Toast.show({
          title: "Full-screen viewer",
          msg: "This image isn't in the currently loaded page anymore, so it can't open full-screen.",
        });
      }
      return;
    }
    setDetailsFor(null);
    setLbIndex(idx);
  };
  const closeLightbox = () => setLbIndex(null);
  const openDetailsFromLightbox = (mid) => {
    setLbIndex(null);
    openDetails(mid);
  };

  // Same advParams shape App.jsx's own DetailsView mount builds (mirrors
  // /api/next/library's own filter params) -- so Prev/Next and "Find similar
  // (model)"/"View batch" walk the SAME filtered/sorted set the lifted
  // useLibrary() instance is currently showing, exactly like desktop.
  const detailsAdvParams = {
    q: lib.applied, media: lib.media, collection: lib.shelf,
    sort: lib.adv.sort !== "newest" ? lib.adv.sort : "", rating_min: lib.adv.ratingMin || "",
    model: lib.adv.model, lora: lib.adv.lora, from: lib.adv.dateFrom, to: lib.adv.dateTo,
    source: lib.adv.source, tag: lib.adv.tag, published: lib.adv.publishedOnly ? "1" : "",
  };

  // App.jsx's own rate(), ported: optimistic update of the lifted useLibrary()
  // items array + the real POST. No equivalent existed on mobile before this
  // (the Gallery grid itself shows no stars), so Details' own Stars control
  // is the first mobile consumer.
  const rate = async (mid, value) => {
    lib.setItems((old) => old.map((it) => (it.media_id === mid ? { ...it, rating: value } : it)));
    try {
      await rateImage(mid, value);
    } catch {
      /* a failed rate leaves the optimistic value; the next load corrects it */
    }
  };

  // Details' "Find similar (model)"/"View batch" chips -- App.jsx's own
  // filterByModel/filterByBatch, ported: close Details, land on the Gallery
  // tab (so the filtered result is actually visible), apply through the SAME
  // lifted useLibrary() instance every other mobile filter control uses.
  const filterByModelFromDetails = (name) => {
    closeDetails();
    setTab("gallery");
    lib.applyAdvanced({ model: name });
  };
  const filterByBatchFromDetails = (batch) => {
    closeDetails();
    setTab("gallery");
    lib.applyAdvanced({ batch });
  };

  useEffect(() => { fetchAccount().then(setAccount); }, []);

  const refreshCollections = async () => {
    const c = await fetchCollections();
    if (c) setCollections(c);
  };

  const closeSheet = () => {
    setClosing(true);
    setTimeout(() => { setSheet(null); setClosing(false); }, 280);
  };

  // Menu row -> pushed screen. Both state changes fire in the SAME click,
  // matching design_handoff's own menuItems onClick (`{ sheet: null, screen:
  // 'X' }` in one setState) -- the sheet is yanked off instantly under the
  // incoming screen, not animated through closeSheet()'s 280ms path (that
  // path stays reserved for the scrim tap and "Not now", per the design
  // research). Mirrors CreateMobile.jsx's closeAdv() timing exactly for the
  // screen side -- 220ms, matching MobileScreen.jsx's own CSS duration.
  const openScreen = (key) => {
    setSheet(null);
    setScreen(key);
  };
  const closeScreen = () => {
    setScreenClosing(true);
    setTimeout(() => { setScreen(null); setScreenClosing(false); }, 220);
  };

  // Health's tag/model/LoRA filter taps -- HealthMobile.jsx's own header
  // comment, point 3: "reuse existing UI mechanisms over building parallel
  // UI". Applies through the SAME lifted useLibrary() instance
  // GalleryMobile.jsx already reads/writes (lib.applyAdvanced, identical
  // one-patch commit path App.jsx's desktop applyAdvanced uses for
  // HealthOverlay's own onModelFilter/onTagFilter/onLoraFilter), then
  // switches to the Gallery tab and closes the pushed screen so the
  // filtered result is actually visible, not applied invisibly behind
  // Health's own screen.
  const filterFromHealth = (patch) => {
    lib.applyAdvanced(patch);
    setTab("gallery");
    closeScreen();
  };

  // Import's onImported -- App.jsx's own afterMutation(), ported: reload the
  // library page 1 (new/imported files should show up) and refresh the
  // collections list (a brand-new collection may have just been created).
  const afterImported = async () => {
    lib.load(1, true);
    await refreshCollections();
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
          <GalleryMobile boot={boot} collections={collections} refreshCollections={refreshCollections} {...lib}
            onOpenDetails={openDetails} />
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

        {/* Menu-sheet pushed screen -- a sibling of the tab bodies above
            within this unpositioned-ancestor-free .glm-body (position:
            relative), so .glm-screen's position:absolute;inset:0 resolves
            against .glm-body exactly the way CreateMobile's Advanced screen
            and .cm-videowrap already do. Mounted HERE (not inside any one
            tab) because the hamburger is reachable from all three tabs --
            switching Gallery/Create/Control while a screen is pushed must
            not unmount it. */}
        <MobileScreen open={!!screen} closing={screenClosing} onClose={closeScreen}
          title={screen ? SCREEN_TITLES[screen] : ""}>
          {screen === "myart" && <MyArtMobile />}
          {screen === "health" && (
            <HealthMobile
              onModelFilter={(m) => filterFromHealth({ model: m })}
              onTagFilter={(t) => filterFromHealth({ tag: t })}
              onLoraFilter={(l) => filterFromHealth({ lora: l })}
              onOpenImport={() => setScreen("import")}
            />
          )}
          {screen === "import" && <ImportMobile collections={collections} onImported={afterImported} />}
          {screen === "contests" && <ContestsMobile />}
          {(screen === "publish" || screen === "train") && (
            <div className="glm-placeholder cm-soon">
              <div className="glm-placeholder-icon" aria-hidden="true">
                {MENU_ITEMS.find((mi) => mi.screen === screen).icon}
              </div>
              <div className="glm-placeholder-title">{SCREEN_TITLES[screen]}</div>
              {SOON_INFO[screen].map((line, i) => (
                <div className="glm-placeholder-note" key={i}>{line}</div>
              ))}
            </div>
          )}
        </MobileScreen>
      </div>

      <TabBarMobile tab={tab} setTab={setTab} />
      <PickerHost />

      {/* Image Details Mobile -- a fixed, full-viewport overlay (its own CSS,
          z above the hero/tab bar/sheets) rather than a child of .glm-body,
          per this component's own header comment on why it's lifted here. */}
      {detailsFor && (
        <ImageDetailsMobile
          mediaId={detailsFor} onClose={closeDetails} onNavigate={openDetails}
          onRate={rate}
          onDeleted={() => { closeDetails(); lib.load(1, true); }}
          onFilterByModel={filterByModelFromDetails} onFilterByBatch={filterByBatchFromDetails}
          advParams={detailsAdvParams} items={lib.items}
          onOpenLightbox={openLightbox}
        />
      )}

      {/* Lightbox Mobile -- a fixed, full-viewport overlay above the hero/tab
          bar, mutually exclusive with ImageDetailsMobile (see header comment). */}
      {lbIndex != null && (
        <LightboxMobile
          items={lib.items} index={lbIndex} setIndex={setLbIndex}
          onClose={closeLightbox} onRate={rate}
          page={lib.page} pages={lib.pages} loadPage={lib.load}
          onOpenDetails={openDetailsFromLightbox}
        />
      )}

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
          {MENU_ITEMS.map((mi) => (
            <button key={mi.label} type="button" className="glm-menu-item"
              onClick={() => openScreen(mi.screen)}>
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
