/* THE FIRST-RUN GUIDE'S STEPS -- the ONE data file for every surface's welcome card, tour
   and notes (Session I decision 1; the layers are explained in help/guideCore.js).

   LATER WAVES EDIT THIS FILE, AND ONLY THIS FILE, when a surface's controls move. Each step
   anchors to a control by CSS selector (`at`: one selector, or a list tried in order until
   one is on screen), so a rebuilt control needs its selector here and nothing else. A
   selector that finds nothing on screen is not an error: the tour skips that mark and the
   notes pass over it, so a stale anchor degrades to a shorter guide, never a broken page.

   `moves` marks the anchors this build already knows will change -- the controls wave 2
   (the Tsubaki.3 Generate rebuild, recipes), wave 4 (the Folio) and wave 5 (power tools,
   curation, the Loom, the phone) are redrawing. Everything is anchored to what exists on
   feat/foundation today.

   The list's ORDER is the guide: the steps with `tour` text come first and are the tour
   (3-4 marks); every step has `note` text (or falls back to its tour text), and the notes
   walk the same list from where the tour stopped. guide-core.test.js pins that shape.

   COPY RULES: short, the app's own words for its screens and buttons (wiki/Glossary.md),
   and nothing about how any hidden part of the app is found or earned. */

const G = {};

/* ------------------------------------------------------------------ the gallery */
G.gallery = {
  desktop: {
    // Welcome copy verbatim from the handoff (section A, ① Welcome card).
    welcome: {
      title: "Welcome to the stacks",
      body: "Your PixAI work, backed up and browsable. Search, filter, open anything. ✦ Generate makes more.",
    },
    steps: [
      { id: "search", at: ".mgl-search",
        tour: "Search every prompt, model and tag you've saved. The ▾ beside it opens the full set of filters.",
        note: "Search reads prompts, models and tags." },
      // Handoff section A, ② Tour, step 2 of 4 -- verbatim.
      { id: "generate", at: [".mgx-actrow [data-dock-toggle]", ".mgx-launcher"],
        tour: "Everything you make starts here. The dock slides up, and your runs appear above the prompt." },
      { id: "rooms", at: ".mgx-navspine",
        tour: "Your other rooms: My Art, Contests, Health and the Control Panel. Each opens over the library; Esc brings you back.",
        note: "My Art, Contests, Health and the Control Panel open over the library." },
      { id: "activity", at: ".mgx-act-wrap",
        tour: "Activity lists what the app just did: generations, syncs and jobs. It keeps going while you browse." },
      // Handoff section A, ③ Nel's notes -- verbatim.
      { id: "filters", at: ".mgl-filters", note: "Filters live here. Try \"videos only\"." },
      { id: "layout", at: ".mgx-lay", note: "Four layouts: masonry, grid, hero and timeline." },
      { id: "size", at: ".mgx-size", note: "Drag SIZE to make the pictures bigger or smaller." },
      { id: "folio", at: ".mgx-metal-folio", note: "The Folio of Honors keeps what you've earned." },
      { id: "help", at: [".mgx-help", ".mgx-sephelp"],
        note: "The ? opens the guide on the page you're on. So does the ? key." },
    ],
  },
  phone: {
    // Phone copy from the options page's 1b phone card (Session I Help and First Run Options).
    welcome: { title: "Welcome to the stacks", body: "Tap anything to open it. Create makes more." },
    steps: [
      { id: "search", at: ".glm-search",
        tour: "Search your prompts, models and tags. Advanced holds the filters." },
      // Options page 1a phone card -- verbatim.
      { id: "create", at: ".glm-nav .glm-navitem:nth-child(2)", tour: "Create is where everything starts.",
        moves: "wave 5 (Q, the phone)" },
      { id: "icons", at: ".glm-hero-icons",
        tour: "The Folio, the Loom, Activity and the menu live up here.",
        moves: "wave 5 (Q, the phone)" },
      { id: "select", at: ".glm-bar .glm-metal", note: "Select picks several pictures at once." },
      { id: "kinds", at: ".glm-bar2", note: "Show everything, only images or only videos, and change the sort." },
      { id: "control", at: ".glm-nav .glm-navitem:nth-child(3)", note: "Control runs the syncs and the library's upkeep." },
      { id: "help", at: ".glm-help", note: "The ? opens the guide for the screen you're on." },
    ],
  },
};

/* ------------------------------------------------------------------ the Generate dock */
G.dock = {
  desktop: {
    welcome: {
      title: "The Generate dock",
      body: "Write a prompt, pick a model, press Generate. Runs land above the prompt as they finish.",
    },
    steps: [
      { id: "tabs", at: ".mgdock-tabs", tour: "Image, Edit or Video. Each tab keeps its own settings." },
      { id: "model", at: [".mgdock-modelchip", ".mgdock-modelrow"],
        tour: "Pick a model first. Browse opens the full picker, with the LoRAs beside it.",
        note: "Pick a model; browse opens the picker.",
        moves: "wave 2 (H, the Tsubaki.3 drawer: the LoRAs | Context images switch and the recipe row)" },
      { id: "prompt", at: ".mgdock-prompt", tour: "Describe the picture here." },
      { id: "go", at: [".mgdock-gen", ".mgdock-gocol"],
        tour: "Generate. The price shows above it before you spend, and a free card is used when one fits.",
        moves: "wave 5 (M, the multi-send confirm)" },
      { id: "settings", at: ".mgdock-expand", note: "▲ opens the settings: frame, size, count and tuning.",
        moves: "wave 2 (H, eleven ratios and size tiers) and wave 5 (M)" },
      { id: "history", at: ".mgdock-hist", note: "History shows the last seven days of runs." },
      { id: "snippets", at: ".mgdock-snipbtn", note: "Snippets keeps the prompt pieces you reuse.",
        moves: "wave 5 (M, presets and lists)" },
      { id: "close", at: ".mgdock-x", note: "× closes the dock. Runs keep going." },
    ],
  },
  phone: {
    welcome: { title: "Create", body: "Write a prompt, pick a model and tap Generate." },
    steps: [
      { id: "modes", at: ".cm-seg3", tour: "Image, Edit or Video." },
      { id: "prompt", at: ".cm-ta", tour: "Describe the picture here." },
      { id: "model", at: ".cm-modelrow", tour: "Pick a model; browse opens the picker.",
        moves: "wave 2 (H) and wave 5 (Q)" },
      { id: "go", at: ".cm-generate", tour: "Generate shows its price above it before you spend." },
      { id: "lora", at: ".cm-addlora", note: "Add a LoRA to steer the style.", moves: "wave 2 (H)" },
      { id: "ratio", at: ".cm-chiprow", note: "Pick the frame's shape.", moves: "wave 2 (H, eleven ratios)" },
      { id: "advanced", at: ".cm-advrow", note: "Advanced holds size, count and tuning.", moves: "wave 2 (H)" },
    ],
  },
};

/* ------------------------------------------------------------------ the Loom */
G.loom = {
  desktop: {
    welcome: { title: "The Loom", body: "Plan a video as acts and shots, then render it shot by shot." },
    steps: [
      { id: "board", at: ".lv-board",
        tour: "The board: your acts, with a card for each shot. Click a shot to work on it.",
        moves: "wave 5 (P, the Loom)" },
      { id: "reel", at: ".lv-reel", tour: "The reel bar: every shot, sized by how long it runs.",
        moves: "wave 5 (P)" },
      { id: "cast", at: ".lv-panel",
        tour: "Cast & assets: the people and things your shots cite as @image1, @video1.",
        note: "Cast & assets holds what your shots cite.", moves: "wave 5 (P)" },
      { id: "genall", at: ".lv-genall",
        tour: "Generate all renders every shot that isn't done yet, one after another." },
      { id: "draft", at: ".lv-draft", note: "Draft renders at the cheaper quality. Turn it off for the keepers." },
      { id: "cost", at: ".lv-cost-pill", note: "The estimate for Generate all. Click it to refresh." },
      { id: "back", at: ".lv-close", note: "← Gallery takes you back to where you were." },
      { id: "help", at: "#eb-help-btn", note: "The ? opens The Loom's page of the guide." },
    ],
  },
  phone: {
    welcome: { title: "The Loom", body: "Plan a video as acts and shots, then render it shot by shot." },
    steps: [
      { id: "card", at: ".lm-card", tour: "Each card is a shot. Tap one to work on it.", moves: "wave 5 (P)" },
      { id: "reel", at: ".lm-reelbar", tour: "The reel: every shot, sized by its length.", moves: "wave 5 (P)" },
      { id: "addshot", at: ".lm-addshot", tour: "+ Shot adds one to this act." },
      { id: "draft", at: ".lm-chip", note: "Draft renders at the cheaper quality." },
      { id: "addact", at: ".lm-addact", note: "+ New act starts the next part of the piece." },
      { id: "back", at: ".lm-back", note: "← Gallery takes you back." },
    ],
  },
};

/* ------------------------------------------------------------------ the Folio */
G.folio = {
  desktop: {
    welcome: {
      title: "The Folio of Honors",
      body: "What you've earned, and what's close. The ladders climb from common to legendary.",
    },
    steps: [
      { id: "tabs", at: ".mgfo-tabs", tour: "The summary, the full list, and your statistics.",
        moves: "wave 4 (G and O, the Folio)" },
      { id: "reach", at: ".mgfo-reach", tour: "Within reach: the honors you're closest to.",
        moves: "wave 4 (O)" },
      { id: "rail", at: ".mgfo-catlist", tour: "Categories: jump to a ladder or a milestone.",
        moves: "wave 4 (O)" },
      { id: "search", at: ".mgfo-search", note: "Search the record by name." },
      { id: "ledger", at: ".mgfo-ledger", note: "Your progress in each category.", moves: "wave 4 (O)" },
      { id: "relics", at: ".mgfo-relics", note: "Relics: skins and banners, applied from the Control Panel.",
        moves: "wave 4 (L2, relics by kind)" },
    ],
  },
  phone: {
    welcome: { title: "The Folio of Honors", body: "What you've earned, and what's close." },
    steps: [
      { id: "tabs", at: ".fm-tabsrow", tour: "The summary, the full list, and your statistics.",
        moves: "wave 4 (G and O)" },
      { id: "recent", at: ".fm-hscroll", tour: "Recently entered: the newest first." },
      { id: "ledger", at: ".fm-ledgerbox", tour: "Your progress in each category.", moves: "wave 4 (O)" },
      { id: "reach", at: ".fm-reachcard", note: "The honor you're closest to.", moves: "wave 4 (O)" },
      { id: "relics", at: ".fm-relicchip", note: "Relics: tap to see the full list.", moves: "wave 4 (L2)" },
      { id: "back", at: ".fm-back", note: "← Gallery takes you back." },
    ],
  },
};

/* ------------------------------------------------------------------ the Control Panel */
G.panel = {
  desktop: {
    welcome: {
      title: "The Control Panel",
      body: "The jobs that keep the library current, and the switches that run it.",
    },
    steps: [
      { id: "console", at: ".mgcp-consolehead",
        tour: "The job console: one job at a time, with its log as it runs." },
      { id: "living", at: ".mgcp-living",
        tour: "Runs itself: the jobs the app does on its own, how often, and Run now." },
      { id: "sync", at: ".mgcp-syncbtn", tour: "Sync now pulls new work and fills in what's missing." },
      { id: "version", at: ".mgcp-ver", tour: "The version stamp. Click it for About and what changed." },
      { id: "ledger", at: ".mgcp-seg", note: "Ledger lists every run the console has recorded." },
      { id: "server", at: ".mgcp-srvrow", note: "Restart or stop the server from here." },
      { id: "lan", at: ".mgcp-bonjour", note: "Let phones on your Wi-Fi find the gallery." },
    ],
  },
  phone: {
    welcome: { title: "Control", body: "Syncs, upkeep and the switches that run the library." },
    steps: [
      { id: "glance", at: ".ctm-statgrid", tour: "At a glance: what the library holds." },
      { id: "mirror", at: ".ctm-mirror", tour: "Live Mirror pulls in each finished generation as it lands." },
      { id: "sync", at: ".mgcp-syncbtn", tour: "Sync now pulls new work and fills in what's missing." },
      { id: "about", at: ".mghelp-aboutrow", note: "About shows the version and what changed in it." },
      { id: "ledger", at: ".glm-tab .cm-seg3", note: "Ledger lists every run the console has recorded." },
      { id: "skins", at: ".mgcp-skinsrow-wrap", note: "Skins recolour the whole app." },
    ],
  },
};

/* ------------------------------------------------------------------ Branding
   Mounted only where the tab itself is drawn, so its key cannot exist before the tab does
   (guideCore.js). The copy says what the tab is for, never how it is found. */
G.branding = {
  desktop: {
    welcome: {
      title: "Branding",
      body: "The mark, its motion, the type and the banners. Make the Athenaeum yours.",
    },
    steps: [
      { id: "sections", at: ".mgcp-brandnav", tour: "The tab's sections, one at a time." },
      { id: "mark", at: ".mgcp-markprevrow", tour: "Your mark, animated live as you change it." },
      { id: "motion", at: ".mgcp-animchips", tour: "How the mark moves. The sliders below tune its speed and size." },
      { id: "type", at: ".mgcp-fontrow", note: "Type pairings for the whole app." },
      { id: "sliders", at: ".mgcp-sliderbox", note: "Speed and size of the mark's motion." },
      { id: "launcher", at: ".mgcp-launcherbtn", note: "Use your mark as the installed app's icon." },
    ],
  },
  phone: {
    welcome: {
      title: "Branding",
      body: "The mark, its motion, the type and the banners.",
    },
    steps: [
      { id: "sections", at: ".mgcp-brandnav", tour: "The tab's sections, one at a time." },
      { id: "mark", at: ".mgcp-markprevrow", tour: "Your mark, animated live as you change it." },
      { id: "motion", at: ".mgcp-animchips", tour: "How the mark moves." },
      { id: "type", at: ".mgcp-fontrow", note: "Type pairings for the whole app." },
      { id: "launcher", at: ".mgcp-launcherbtn", note: "Use your mark as the installed app's icon." },
    ],
  },
};

export const GUIDE = G;

/* One surface's guide for the layout in use. */
export function stepsFor(surface, phone) {
  const g = G[surface];
  if (!g) return null;
  return phone ? g.phone : g.desktop;
}
