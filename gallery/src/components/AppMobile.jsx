import React, { useEffect, useMemo, useRef, useState } from "react";
import useLibrary from "../hooks/useLibrary.js";
import useSheet from "../hooks/useSheet.js";
import useFlavour from "../hooks/useFlavour.js";
import useGenerate from "../gen/useGenerate.js";
import useEditGenerate from "../gen/useEditGenerate.js";
import { apiPost, fetchAccount, fetchCollections, rateImage } from "../api.js";
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
import ContestChooserMobile from "./ContestChooserMobile.jsx";
import ContestEntryMobile from "./ContestEntryMobile.jsx";
import PublishMobile from "./PublishMobile.jsx";
import TrainMobile from "./TrainMobile.jsx";
import FolioMobile from "./FolioMobile.jsx";
import ContactSheetMobile from "./ContactSheetMobile.jsx";
import ClaimModal from "./ClaimModal.jsx";
import useClaimModal from "../hooks/useClaimModal.js";
import ActivityRow from "../notify/ActivityRow.jsx";
import { subscribe as subscribeJobs, dismiss as dismissJob, clearFinished as clearFinishedJobs } from "../notify/jobsStore.js";
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
       created here too (an imperative handle to the <CostBadge> CreateMobile
       mounts, the same pattern GenerateDrawer.jsx uses);
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
       dedicated <CostBadge> handle) -- never shared with Image mode's
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
     - Edit's own Fixer sub-tab renders a soon-state note -- see
       CreateMobile.jsx's own header comment for the full disclosure of what's
       deferred there and why. (Create's own Video mode is NOT a placeholder --
       it shipped for real the same day, see the VideoMode paragraph above.)

   FOLIO MOBILE (2026-08-03) -- the hero's gold "🌙 Folio of Honors" icon now
   opens the real FolioMobile.jsx full-page destination instead of the
   disclosing "coming later" toast it showed before this pass. `folioOpen`
   is lifted HERE for the identical reason detailsFor/lbIndex/cmode/VideoMode
   are: it must survive being opened from the hero (reachable from every tab)
   and cover the WHOLE shell, so it renders as a fixed overlay sibling below,
   same level as ImageDetailsMobile/LightboxMobile -- see FolioMobile.jsx's
   own header comment for why that's a dedicated full-screen presentation
   rather than MobileScreen.jsx's generic push chrome, and for the full list
   of real-data deviations from Folio Mobile.dc.html disclosed there. Data/
   narrator/glitch-reveal/replay logic all live in useFolio.js (lifted out of
   FolioOverlay.jsx the SAME day, desktop refactored to consume it too) --
   FolioMobile gets the identical engine, not a second fetch or a second,
   drifting celebration implementation.

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
       useLibrary() instance (see filterFromHealth below); word-cloud/
       folder-breakdown scoped out this pass (deliberate trim, not a "skip
       real data" call). Duplicates/Reclaimable (2026-08-03, closing the
       prior gap) now open the real Duplicate Review Mobile screen
       (DuplicateReviewMobile.jsx, nested inside HealthMobile.jsx's own
       pushed screen -- see that file's own header comment) -- real GET
       /api/duplicates + real POST /api/duplicates/resolve|undo, the exact
       same hook (useDuplicateReview.js) and backend routes desktop's
       DuplicateReviewOverlay.jsx uses, never a second write path.
       `afterDuplicatesResolved` below is this surface's own afterMutation()
       equivalent -- reloads the lifted useLibrary() grid once a duplicate
       copy actually leaves the visible library.
     - Import: one real file-picker button (native <input type="file">) --
       the design specifies no picker at all; "Browse a folder…" dropped
       (webkitdirectory has no reliable mobile support); collection picker
       is a real <select> of live `collections` data + new-collection input.
     - Contests: REBUILT 2026-09-04 to `Contest Mobile Handoff.dc.html`
       (Session D) -- an official 16:9 hero over community list cards, a
       "MY ENTRIES · n" door into the same board filtered to what this
       library has entered, an accordion detail, and a full-screen entry
       picker. The line that used to sit here ("pixai.art click-through
       ported forward") describes what this screen did BEFORE that pass:
       every card opened the website because there was no in-app
       destination. There is one now, and the link-out survives only as
       the detail view's footnote. See ContestsMobile.jsx's own header for
       the real-data deviations and the badge-hue divergence from desktop.
     - Publish (2026-08-07): single column, real /api/myart/publish preview-
       then-confirm pipeline (the exact one desktop's PublishOverlay.jsx
       proved), real recent-image strip, live suggest-a-title + tag search,
       real contest list. Reachable from the Menu AND from Image Details
       Mobile's own new ☁ Publish chip via publishFor/openPublish below.
     - Train a LoRA (2026-08-07): the dataset picker taps a whole recent
       generation TASK (new GET /api/train/recent-tasks), adding all of that
       task's REAL images (1-4, not the design's fixed demo "4") -- real
       free-quota-aware cost line, real curated base models + pricing (same
       /api/train/quota + /api/train/models desktop's TrainOverlay.jsx uses).

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
   purposes -- no second pagination copy.

   CONTACT SHEET MOBILE (2026-08-03) -- the Gallery tab's Actions sheet
   (ActionsMenu.jsx, mounted "as-is" inside GalleryMobile.jsx) has a real
   "▤ Print sheet" item that, on mobile, previously fell through to
   ActionsMenu's own desktop-shaped fallback (a bare window.open of the
   classic print page). `contactSheetTarget`/openContactSheet/
   closeContactSheet are lifted HERE for the identical reason detailsFor/
   lbIndex/folioOpen are (must survive being opened from the Gallery tab and
   cover the WHOLE shell), mirroring desktop App.jsx's own contactSheetTarget/
   openContactSheet pairing exactly (same {ids, collectionName} target shape,
   same "explicit ids win, collectionName is the fallback" contract). Renders
   as a fixed, full-viewport overlay sibling of ImageDetailsMobile/
   LightboxMobile/FolioMobile below. GalleryMobile.jsx's own onPrintSheet prop
   closes its local Actions sheet and calls openContactSheet(selIds) in the
   same click -- see that file's own header comment and ContactSheetMobile.jsx's
   for the full real-data-vs-design-mock disclosure (placeholder thumbnails,
   Share via the Web Share API instead of window.print()). */

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
// My Art/Import/Contests/Health/Publish/Train (2026-08-07) all render their own real
// component below -- every Menu destination is now live, matching desktop.
const SCREEN_TITLES = {
  myart: "My Art",
  publish: "Publish",
  train: "Train a LoRA",
  import: "Import",
  contests: "Contests",
  health: "Collection Health",
};

export default function AppMobile({ boot }) {
  const [tab, setTab] = useState("gallery");
  const [account, setAccount] = useState(null);
  const claimModal = useClaimModal(account, () => fetchAccount().then(setAccount));
  const [collections, setCollections] = useState(boot.collections || []);
  // 'loom' | 'menu' | null -- shared timer-safe state machine (hooks/useSheet.js,
  // 2026-08-07 review fix: the hand-rolled pair let a reopen inside the 280ms exit
  // window inherit a stale unmount timer and vanish).
  const { sheet, closing, open: openSheet, close: closeSheet } = useSheet(280);
  // The Menu sheet's pushed-screen destination -- generalizes MobileScreen.jsx
  // the same way `sheet` above already generalizes MobileSheet.jsx (one
  // string key, one shared mount). null | 'myart' | 'publish' | 'train' |
  // 'import' | 'contests' | 'health'. See header comment. 220ms = MobileScreen's
  // own CSS duration (vs the sheets' 280ms).
  const { sheet: screen, closing: screenClosing, open: openScreenKey, close: closeScreenRaw } = useSheet(220);
  // Header-docked Activity control, mobile idiom (Claude Design handoff 2026-08-09, drift
  // item 39): reuses the SAME jobsStore every host reads (real /api/jobs truth, no new
  // endpoint) and the app's existing MobileSheet/useSheet machinery -- not useActivity's own
  // open/close (that hook's open state drives jobsStore's PERSISTED mg_jobs_open flag, meant
  // for the desktop dropdown; the sheet's own open/closed state is `sheet === "activity"`
  // instead, ephemeral like every other mobile sheet, never persisted across reloads).
  const [jobsState, setJobsState] = useState({ jobs: [], open: false });
  useEffect(() => subscribeJobs(setJobsState), []);
  const jobsRunning = jobsState.jobs.filter((j) => (j.status || "running") === "running").length;
  const [jobExpandedId, setJobExpandedId] = useState(null);
  const toggleJobRow = (jid) => setJobExpandedId((cur) => (cur === jid ? null : jid));
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
  // (unlike desktop's bookmarkable /?image=<mid>) -- see
  // ImageDetailsMobile.jsx's own header comment for why that's a deliberate,
  // separate scope call, not an oversight.
  const [detailsFor, setDetailsFor] = useState(null);
  const openDetails = (mid) => setDetailsFor(mid);
  const closeDetails = () => setDetailsFor(null);

  // Publish (2026-08-07) -- which image a cross-page "☁ Publish" tap (Image Details
  // Mobile) handed to the Publish screen. Empty when Publish is opened from the Menu --
  // the screen then starts with its own recent-image strip instead of a pre-chosen one.
  // Mirrors desktop App.jsx's publishFor/openPublish exactly.
  const [publishFor, setPublishFor] = useState("");
  const openPublish = (mid) => { setPublishFor(mid || ""); openScreenKey("publish"); };

  /* CONTEST ENTRY (2026-09-04, Contest Mobile Handoff.dc.html frame D3) -- lifted HERE
     for the identical reason detailsFor/lbIndex/folioOpen are: the handoff keeps THREE
     entry points and two of them (the lightbox's action row, Image Details' chip) live on
     surfaces that already cover the whole shell, so the entry screen has to sit above
     them rather than inside the Contests screen that owns the third.
       contestEntry  -- {contest, mediaId} while the full-screen picker is up
       contestFor    -- the media_id waiting on a contest choice (the chooser sheet)
       entriesEpoch  -- bumped when an entry lands, so the Contests screen's "MY ENTRIES"
                        count and My-entries view re-read without being reopened. */
  const [contestEntry, setContestEntry] = useState(null);
  const [contestFor, setContestFor] = useState("");
  const [entriesEpoch, setEntriesEpoch] = useState(0);
  // From an image: choose the contest first (the sheet), then the picker with that image
  // pre-selected. From the board: the contest is already known, so it goes straight in.
  const openContestFor = (mid) => { setContestFor(mid || ""); openSheet("contest"); };
  const openContestEntry = (contest, mid) => {
    closeSheet();
    setContestEntry({ contest, mediaId: mid || "" });
  };
  const closeContestEntry = () => setContestEntry(null);

  // Lightbox Mobile (2026-08-03) -- mutually exclusive with detailsFor, see
  // header comment. Since #35 (2026-08-29) openLightbox has TWO callers with
  // different miss semantics: the PRIMARY grid tap (GalleryMobile's tapView --
  // every plain tap rides the findIndex gate now, so a mid-tap page replace is
  // a reachable state, not a rare race) falls back to opening Details by id,
  // which never depends on array membership -- a tap always opens SOMETHING;
  // Details' own ⛶ button passes no fallback and keeps the honest toast
  // (Details is already open there -- falling "back" to it would be a no-op
  // dressed as success). An earlier revision of this comment claimed Details
  // was the only caller; the adversarial review caught it going stale.
  const [lbIndex, setLbIndex] = useState(null);

  // Folio Mobile (2026-08-03) -- lifted HERE for the identical reason
  // detailsFor/lbIndex are: reachable from the hero on every tab, must cover
  // the whole shell. See header comment.
  const [folioOpen, setFolioOpen] = useState(false);
  const openFolio = () => setFolioOpen(true);
  const closeFolio = () => setFolioOpen(false);

  // Contact Sheet Mobile (2026-08-03) -- lifted HERE for the identical reason
  // detailsFor/lbIndex/folioOpen are: reachable from the Gallery tab's
  // Actions sheet, must cover the WHOLE shell. Mirrors desktop App.jsx's own
  // contactSheetTarget/openContactSheet exactly -- see header comment.
  const [contactSheetTarget, setContactSheetTarget] = useState(null); // null | {ids, collectionName}
  const openContactSheet = (ids, collectionName) => {
    setContactSheetTarget({ ids: ids || [], collectionName: collectionName || "" });
  };
  const closeContactSheet = () => setContactSheetTarget(null);
  const openLightbox = (mid, onMiss) => {
    const idx = lib.items.findIndex((it) => it.media_id === mid);
    if (idx < 0) {
      if (typeof onMiss === "function") { onMiss(mid); return; }
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
  // the grid-tap flavor (#35): a tap must always open SOMETHING -- on an index
  // miss (page replaced mid-tap) it opens Details by id instead of toasting.
  const openLightboxFromGrid = (mid) => openLightbox(mid, openDetails);
  const closeLightbox = () => setLbIndex(null);
  const openDetailsFromLightbox = (mid) => {
    setLbIndex(null);
    openDetails(mid);
  };

  // Same advParams shape App.jsx's own DetailsView mount builds (mirrors
  // /api/next/library's own filter params) -- so Prev/Next and "Find similar
  // (model)"/"View batch" walk the SAME filtered/sorted set the lifted
  // useLibrary() instance is currently showing, exactly like desktop.
  //
  // BUG FIX 2026-08-04 (same root cause found and fixed in App.jsx): this
  // was a plain object literal recomputed every render, so it got a new
  // reference every render regardless of whether any value inside it
  // actually changed. useImageDetails.js's fetch effect depends on
  // advParams by reference ([mediaId, advParams]), so a fresh reference
  // every render re-fires it every render: setState -> re-render -> new
  // object -> effect fires again -> ... an infinite loop that never lets
  // `loading` settle. useMemo keyed on the real underlying values fixes it.
  const detailsAdvParams = useMemo(() => ({
    q: lib.applied, media: lib.media, collection: lib.shelf,
    sort: lib.adv.sort !== "newest" ? lib.adv.sort : "", rating_min: lib.adv.ratingMin || "",
    model: lib.adv.model, lora: lib.adv.lora, from: lib.adv.dateFrom, to: lib.adv.dateTo,
    source: lib.adv.source, tag: lib.adv.tag, published: lib.adv.publishedOnly ? "1" : "",
  }), [lib.applied, lib.media, lib.shelf, lib.adv.sort, lib.adv.ratingMin, lib.adv.model,
      lib.adv.lora, lib.adv.dateFrom, lib.adv.dateTo, lib.adv.source, lib.adv.tag,
      lib.adv.publishedOnly]);

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

  // Menu row -> pushed screen. Both state changes fire in the SAME click,
  // matching design_handoff's own menuItems onClick (`{ sheet: null, screen:
  // 'X' }` in one setState) -- the sheet is yanked off instantly under the
  // incoming screen via openSheet(null) (clears any pending exit timer too),
  // not animated through closeSheet()'s 280ms path (that path stays reserved
  // for the scrim tap and "Not now", per the design research).
  const openScreen = (key) => {
    openSheet(null);
    openScreenKey(key);
  };
  // publishFor resets immediately, not after the exit animation: PublishMobile
  // seeds its own internal mid from the prop at MOUNT only, so the mounted,
  // exiting screen never re-reads it.
  const closeScreen = () => {
    closeScreenRaw();
    setPublishFor("");
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

  // Duplicate Review Mobile's onResolved (HealthMobile.jsx -> nested
  // DuplicateReviewMobile.jsx, see that hook's own header comment) -- the
  // SAME App.jsx afterMutation() shape DuplicateReviewOverlay.jsx's onResolved
  // already calls on desktop: reload the grid so a quarantined duplicate
  // copy actually leaves the visible library, once real, not just locally
  // marked resolved in the Duplicate Review screen's own session state.
  const afterDuplicatesResolved = async () => {
    lib.load(1, true);
    await refreshCollections();
  };

  // Publish/Train's own onPublished/onSubmitted -- same afterMutation() shape: a
  // freshly-published artwork or queued training doesn't change what the grid shows,
  // but Details' artwork_id (the "already published" state) does, so a reload keeps
  // that badge honest if the owner backs out to Details right after.
  const afterPublishOrTrain = async () => { lib.load(1, true); };

  // NavSpine.jsx's own logout(), ported verbatim (same /api/logout JSON POST +
  // cache-purge-then-navigate shape -- see that file's header comment for why).
  const logOut = () => {
    apiPost("/api/logout", { csrf: boot.csrf || "" }).then(() => {
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
            onClick={openFolio}>🌙</button>
          <button type="button" className="glm-iconbtn glm-iconbtn-teal" title="The Loom — video storyboard"
            onClick={() => openSheet("loom")}>▮</button>
          <button type="button" className="glm-iconbtn glm-iconbtn-lav" title="Activity"
            style={{ position: "relative" }} onClick={() => openSheet("activity")}>
            ◉
            {jobsRunning ? <span className="glm-iconbtn-badge" aria-hidden="true" /> : null}
          </button>
          <button type="button" className="glm-iconbtn glm-iconbtn-lav" title="More"
            onClick={() => openSheet("menu")}>☰</button>
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
        {account && Number(account.claim_credits) > 0 ? (
          <button type="button" className="glm-hero-claim" onClick={claimModal.claim}
            disabled={claimModal.claiming}>
            <i className="glm-claimribbon" aria-hidden="true" /> {claimModal.claiming ? "claiming…" : "+" + Number(account.claim_credits).toLocaleString() + " claim"}
          </button>
        ) : null}
      </header>

      <div className="glm-body">
        {tab === "gallery" && (
          <GalleryMobile boot={boot} collections={collections} refreshCollections={refreshCollections} {...lib}
            onOpenDetails={openDetails} onOpenLightbox={openLightboxFromGrid} onOpenContactSheet={openContactSheet} />
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
          {screen === "myart" && (
            <MyArtMobile onOpenPost={openDetails} onOpenTrain={() => openScreenKey("train")} />
          )}
          {screen === "health" && (
            <HealthMobile
              onModelFilter={(m) => filterFromHealth({ model: m })}
              onTagFilter={(t) => filterFromHealth({ tag: t })}
              onLoraFilter={(l) => filterFromHealth({ lora: l })}
              onOpenImport={() => openScreenKey("import")}
              boot={boot}
              onDuplicatesResolved={afterDuplicatesResolved}
            />
          )}
          {screen === "import" && <ImportMobile collections={collections} onImported={afterImported} />}
          {screen === "contests" && (
            <ContestsMobile onEnter={(c) => openContestEntry(c, "")}
              entriesEpoch={entriesEpoch} />
          )}
          {screen === "publish" && (
            <PublishMobile mediaId={publishFor} onClose={closeScreen} onPublished={afterPublishOrTrain} />
          )}
          {screen === "train" && (
            <TrainMobile onClose={closeScreen} />
          )}
        </MobileScreen>
      </div>

      <TabBarMobile tab={tab} setTab={setTab} />
      <PickerHost />
      {claimModal.open && (
        <ClaimModal credits={claimModal.credits} exiting={claimModal.exiting}
          claiming={claimModal.claiming} error={claimModal.error}
          onClaim={claimModal.claim} onDismiss={claimModal.dismiss} />
      )}

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
          onPublish={(mid) => { closeDetails(); openPublish(mid); }}
          onEnterContest={openContestFor}
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
          onEnterContest={openContestFor}
        />
      )}

      {/* Folio Mobile -- a fixed, full-viewport overlay above the hero/tab
          bar, same level as ImageDetailsMobile/LightboxMobile (see header
          comment for why it's not nested in MobileScreen). */}
      {folioOpen && <FolioMobile onClose={closeFolio} />}

      {/* Contact Sheet Mobile -- a fixed, full-viewport overlay above the
          hero/tab bar, same level as ImageDetailsMobile/LightboxMobile/
          FolioMobile (see header comment for why it's not nested in
          MobileScreen or GalleryMobile's own Actions sheet). */}
      {contactSheetTarget && (
        <ContactSheetMobile
          ids={contactSheetTarget.ids}
          collectionName={contactSheetTarget.collectionName}
          onClose={closeContactSheet}
        />
      )}

      {/* Contest entry (Contest Mobile Handoff.dc.html D3) -- a fixed, full-viewport
          surface at z 70, above LightboxMobile's own sheet (66), because the lightbox is
          one of the three places it opens from. See its own header comment for the
          always-a-confirm contract and the disclosed "/N max". */}
      {contestEntry && (
        <ContestEntryMobile
          contest={contestEntry.contest} preselectMediaId={contestEntry.mediaId}
          onClose={closeContestEntry}
          onEntered={() => setEntriesEpoch((n) => n + 1)}
        />
      )}

      {/* "Enter into a contest…" -- the choose-a-contest step for the two image-side
          entry points. The board's own Enter bar skips it: the contest is already known.
          `cmb-choosersheet` is the ONLY sheet on this screen that carries a class, and it
          is carrying a z-index: this one mounts while a viewer is up, so MobileSheet's
          shared 30/31 put its scrim and slab BEHIND the opaque .lbm-root/.idm-root that
          opened it and the chip read as dead. contest-mobile.css's rung (67/68) states the
          whole phone ladder; the other three sheets here open over the app shell only and
          stay on the shared rung. */}
      <MobileSheet open={sheet === "contest"} closing={closing} onClose={closeSheet}
        className="cmb-choosersheet" title="ENTER INTO A CONTEST">
        <ContestChooserMobile onPick={(c) => openContestEntry(c, contestFor)} />
      </MobileSheet>

      <MobileSheet open={sheet === "activity"} closing={closing} onClose={closeSheet}
        title={
          <span style={{ display: "flex", alignItems: "baseline" }}>
            <span>ACTIVITY {jobsState.jobs.length || ""}</span>
            <span style={{ flex: 1 }} />
            {jobsState.jobs.length ? (
              <span className="glm-sheet-title-action" role="button" tabIndex={0}
                onClick={() => clearFinishedJobs()}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); clearFinishedJobs(); } }}>
                clear finished
              </span>
            ) : null}
          </span>
        }>
        {!jobsState.jobs.length ? (
          <div className="at-empty">
            <img className="at-empty-nel" src="/branding/mascots/trk_empty.png" alt="" onError={(e) => e.currentTarget.remove()} />
            <div>The archive is quiet.<br />Generations and syncs will appear here.</div>
          </div>
        ) : (
          <div className="glm-activity-list">
            {jobsState.jobs.map((j) => (
              <ActivityRow key={j.job_id} job={j} compact
                expanded={jobExpandedId === j.job_id}
                onToggle={toggleJobRow} onDismiss={dismissJob}
              />
            ))}
          </div>
        )}
      </MobileSheet>

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
