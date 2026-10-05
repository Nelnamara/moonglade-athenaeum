/* THE RECIPES' SHARED STATE -- one tiny external store for the whole page (the
   accountPrefsStore / momentStore pattern: subscribe + getSnapshot, no React import here).

   Three things live in it:
     open     which recipe surface is up (the picker at compact or market size, a recipe's
              page, the creator) and where in it -- so the SAME overlay keeps tab, search,
              filters and selection across ⤢ / ⤡ (K decision 1)
     dock     what the dock's recipe row last told us: its chips, its onChange, the model
              type, the LoRA count, whether the row is held. RecipeRow publishes this on
              every render; every opener (the row's + Browse, the command palette's "Browse
              recipes", the phone's Create) adds to the dock through it.
     request  the dock's current request and its last price answer, when lane w2-gen's
              dock publishes them (publishDockRequest / publishDockPrice). With them the
              picker adds the prompt budget and PixAI's own verdict (a price check with the
              candidate recipe) to its misfit check (H decision 10, T2b); without them it
              checks the model and the card's own usability only.
   Nothing here talks to the server. */

let _open = null;          // null | {view, size, tab, selectedId, pageId, creator}
let _dock = { recipes: [], onChange: null, modelType: "", loraCount: 0, held: false };
let _request = { payload: null, price: null };
const _cards = new Map();  // recipe id -> the last card seen (chips re-hydrate from it)
const _subs = new Set();
let _snap = { open: _open, dock: _dock, request: _request, v: 0 };

function _emit() {
  _snap = { open: _open, dock: _dock, request: _request, v: _snap.v + 1 };
  for (const f of _subs) { try { f(); } catch { /* one bad subscriber must not stop the rest */ } }
}

export function subscribe(f) { _subs.add(f); return () => _subs.delete(f); }
export function getSnapshot() { return _snap; }

/** Open the picker (or the creator / a page). Keeps the tab, search and filters the
    overlay last had when `keep` is set (the ⤢ / ⤡ toggle). */
export function openRecipes(opts) {
  const o = opts || {};
  _open = {
    view: o.view || "picker",
    // "" = the account's remembered size (K decision 1: "The size you last used is
    // remembered"); the palette's "Browse recipes" passes "market".
    size: o.size || (_open && _open.size) || "",
    tab: o.tab || "market",
    selectedId: o.selectedId || "",
    pageId: o.pageId || "",
    creator: o.creator || null,
    phone: !!o.phone,
    phoneScreen: o.phoneScreen || "sheet",
  };
  _emit();
}
export function updateOpen(patch) {
  if (!_open) return;
  _open = { ..._open, ...(patch || {}) };
  _emit();
}
export function closeRecipes() { _open = null; _emit(); }
export function isRecipesOpen() { return !!_open; }

/** The creator, over the same host: `creator` = {draftId?, prefill?, edit?, step?}. */
export function openCreator(creator, extra) {
  openRecipes({ ...(_open || {}), ...(extra || {}), view: "creator", creator: creator || {} });
}

export function bindDock(b) {
  const next = { ..._dock, ...(b || {}) };
  // A new onChange identity alone (a dock re-rendering on every keystroke) is stored
  // silently: nothing drawn depends on it, and an emit per keystroke would re-render an
  // open picker for nothing.
  const same = next.recipes === _dock.recipes && next.modelType === _dock.modelType &&
    next.loraCount === _dock.loraCount && next.held === _dock.held && next.modelTitle === _dock.modelTitle;
  _dock = next;
  if (!same) _emit();
}

/** For lane w2-gen's dock: the request it prices (buildPayload's output) -- the picker
    reads its prompt length and prices a candidate recipe against it. */
export function publishDockRequest(payload, meta) {
  const title = (meta && meta.modelTitle) || "";
  if (_request.payload === payload && _dock.modelTitle === title) return;
  _request = { ..._request, payload: payload || null };
  _dock = { ..._dock, modelTitle: title };   // "made for Tsubaki.2, not <this>"
  _emit();
}
/** For the dock: its last price answer -- a `recipe_error` there marks the chip. */
export function publishDockPrice(answer) {
  if (_request.price === answer) return;
  _request = { ..._request, price: answer || null };
  _emit();
}

export function cacheCards(list) {
  for (const c of list || []) if (c && c.id) _cards.set(String(c.id), c);
}
export function cachedCard(id) { return _cards.get(String(id)) || null; }

/** Add a card to the dock through its bound onChange. Returns the refusal text or "". */
export function addToDock(card, addFn) {
  const d = _dock;
  if (typeof d.onChange !== "function") return "The Generate dock isn't open";
  const { list, refused } = addFn(d.recipes, card);
  if (refused) return refused;
  if (list !== d.recipes) d.onChange(list);
  return "";
}
export function removeFromDock(id, removeFn) {
  const d = _dock;
  if (typeof d.onChange !== "function") return;
  d.onChange(removeFn(d.recipes, id));
}
