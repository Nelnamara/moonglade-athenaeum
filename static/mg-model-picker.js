/* mg-model-picker.js -- a framework-neutral <mg-model-picker> custom element: the rich
   model/LoRA picker (search box + cover cards + hover preview card) that BOTH the vanilla
   gallery and the React Loom can mount, so the widget lives in ONE place instead of two.

   The first shared web component of the Option-A cohesion migration (see
   docs/archive/SUITE_ARCHITECTURE_AUDIT_2026-07-13.md, archived). Loaded as a plain global
   via <script src>, exactly
   like picker-core.js and the vendored React -- NO build step, runs untranspiled (a native
   ES class is fine in every modern browser). It reads the shared DESIGN_TOKENS_CSS custom
   properties, so it re-skins with the app, and it owns its OWN floating preview element,
   which dissolves the gallery's singleton-#model-preview coupling.

   Usage:
     <mg-model-picker kind="base"></mg-model-picker>     // kind = "base" | "lora"
   On selection it emits a bubbling CustomEvent('mg-pick', { detail: <model row> }); the
   detail is the raw /api/model-search row (model_id, title, type, base_model, preview_url,
   liked_count, ref_count, official, description, ...). React hosts bind via a ref +
   addEventListener('mg-pick', ...) since React doesn't wire custom events through JSX props.

   D-11: opt-in MULTI-SELECT mode (`<mg-model-picker kind="lora" multi>`), added for the
   Loom's LoRA picker. Single-value mode (the default, `multi` absent) is UNCHANGED --
   byte-for-byte the same behavior as before, zero regression risk to the Gallery's mount,
   which doesn't use this component at all yet. In multi mode:
     - clicking a card TOGGLES membership (add/remove) instead of replacing a single value.
     - each picked LoRA is resolved via /api/model-version?all=1 (same endpoint the Gallery's
       own toggleLora() and the base-model picker's ?all=1 fetch both use) to fill
       version_id/lora_base_type/trigger_words from the first (latest) release, PLUS a full
       `versions` array on the entry so a host can offer a per-chip version selector (added
       2026-07-24 -- previously a plain fetch with no `all` param, silently discarding every
       release but the latest). The failure/pending cases are handled the same way as before
       (an unresolved LoRA is marked `failed`, never silently dropped -- see the Gallery's
       fail-open fix, audit 2026-07-21).
     - mg-pick's detail becomes { model, selected } (selected=true on add/resolve-update,
       false on remove) instead of the raw row -- a deliberate shape difference gated on
       the new opt-in attribute, not a change to the existing single-value contract.
     - `.selected` (getter) returns the current multi-select array.

   O12/O13 (Phase 2): opt-in `market` boolean attribute (`<mg-model-picker kind="lora" multi
   market>`), added for the gallery's LoRA browsing parity. OFF by default -- the Loom's
   existing kind="lora" multi mount does not set it, so it is byte-for-byte unaffected.
   When present, renders a Popular/Newest sort toggle + the same 6 category chips
   (character/style/pose/clothing/background/detail) the gallery's own #model-flyout has
   for LoRAs, and threads sort=/category= into /api/model-search (the server already
   honors both -- see moonglade_gallery.py's api_model_search -- only the client-side UI was
   missing). Independent of `kind`: the HOST decides when market makes sense (the gallery
   only ever sets it on its LoRA mount, matching its own long-standing "sort/category are a
   LoRA taxonomy, base models don't get them" design), the same way `show-type` on
   mg-gallery-picker.js is host-gated rather than baked into a mode.

   picker-parity-round2 (2026-07-24): two follow-ups found on the owner's live test of the
   above.

   1) LAYOUT: .mg-grid used to be a fixed `max-height:320px`, so a host that gives this
   element real vertical room (the gallery's #model-flyout, sized to fill most of the
   viewport) left a large dead area below the grid instead of using it. The element's own
   default is now `display:flex;flex-direction:column` (was `display:block`) with
   `.mg-grid{flex:1 1 auto}` and no max-height -- inside an UNconstrained parent (the
   standalone verification page below, or any future plain mount) this behaves EXACTLY like
   `display:block` did (a flex column with no assigned height sizes to its content, same as
   a block), so nothing regresses there; a HOST that actually constrains the element's
   height (via its own CSS -- see moonglade_gallery.py's `#model-flyout mg-model-picker` and the
   Loom's `.lv-mpick-body mg-model-picker`) now gets a grid that fills exactly that height
   and scrolls internally, instead of a second independent 320px cap fighting the host's own
   scroll container.

   2) ARCHITECTURE-AWARE LoRA sort/badge: opt-in `base-type` attribute
   (`<mg-model-picker kind="lora" ... base-type="SDXL_MODEL">`), set/updated by the HOST to
   the currently-selected base model's resolved `model_type` (both hosts already resolve
   this today for their own post-selection is_lora_compatible() gate -- this just reuses
   it). Threaded into /api/model-search as `base_type=`, which soft-sorts + tags results
   server-side (moonglade_backup.py's annotate_lora_compat -- see that function for the
   full compatible/unknown/incompatible reasoning); this component's only job is to render
   the `compat` tag it comes back with as a small badge on the card. No `base-type` set (or
   kind="base") -> byte-for-byte unaffected, same as `market`'s own opt-in contract.

   Continuous scroll (2026-07-24): a scroll listener on .mg-grid fires _loadMore() once the
   viewport nears the bottom, which fetches the SAME search (via _searchUrl, shared with
   _search() so a continuation can never silently drift onto different filters) with the
   last response's `cursor` and APPENDS results instead of replacing them. _hasMore/_cursor
   reset to false/'' on every fresh _search() (a new query is a new list). Server-side detail
   in moonglade_gallery.py's api_model_search comment -- has_more had been computed correctly
   the whole time; nothing here had ever read it or asked for a next page. */
(function () {
  'use strict';
  if (window.customElements && customElements.get('mg-model-picker')) return;

  // ---- small formatters (mirrors the gallery flyout's, kept identical on purpose) ----
  function esc(s) {
    return (s == null ? '' : String(s)).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function fmt(n) { return (Number(n) || 0).toLocaleString(); }
  function fmtCompact(n) {
    n = Number(n) || 0;
    if (n >= 1e9) return (n / 1e9).toFixed(1).replace(/\.0$/, '') + 'B';
    if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, '') + 'K';
    return String(n);
  }
  function tyShort(t) {
    t = (t || '').toUpperCase();
    if (t.indexOf('LORA') >= 0) return 'LoRA';
    if (t.indexOf('MMDIT') >= 0) return 'MMDiT';
    if (t.indexOf('DIT') >= 0) return 'DiT';
    if (t.indexOf('SDXL') >= 0) return 'SDXL';
    if (t.indexOf('SD_V1') >= 0) return 'SD1.5';
    if (t.indexOf('SD3') >= 0) return 'SD3';
    if (t.indexOf('Z_IMAGE') >= 0) return 'Z-Image';
    if (t.indexOf('CHAT') >= 0) return 'Chat';
    return (t.split('_')[0] || 'model').toLowerCase();
  }
  // picker-parity-round2: render the server's `compat` tag (annotate_lora_compat,
  // moonglade_backup.py) as a small badge. Hardcoded strings per branch, never the raw
  // tag value as visible text -- there's nothing untrusted in a same-origin JSON enum, but
  // matching this file's existing esc()-everything-dynamic discipline costs nothing.
  // 'unknown' (or no tag at all, i.e. no base selected) renders NOTHING -- see
  // annotate_lora_compat's own docstring: badging an unresolved architecture as compatible
  // would overclaim data the server doesn't have.
  function compatBadge(compat) {
    if (compat === 'yes') return '<span class="mg-cbadge yes">&#10003; compatible</span>';
    if (compat === 'no') return '<span class="mg-cbadge no" title="Different base architecture than the selected model &mdash; would fail on submit">&#9888; different arch</span>';
    return '';
  }
  function baseLabel(cat) {
    cat = (cat || '').replace(/^uploaded-/, '').replace(/[-_]+/g, ' ').trim();
    if (!cat) return '';
    if (/sdxl/i.test(cat)) return 'SDXL';
    if (/sd3/i.test(cat)) return 'SD3';
    if (/^sd ?v?1/i.test(cat)) return 'SD1.5';
    if (/flux/i.test(cat)) return 'Flux';
    if (/pony/i.test(cat)) return 'Pony';
    if (/illustrious/i.test(cat)) return 'Illustrious';
    return cat.replace(/\b\w/g, function (c) { return c.toUpperCase(); });
  }

  // ---- one injected <style>, scoped to the element, reading the shared app tokens ----
  var STYLE_ID = 'mg-model-picker-style';
  var MG_CSS = [
    /* picker-parity-round2: flex column, not block -- lets a host that actually
       constrains this element's height (e.g. #model-flyout mg-model-picker /
       .lv-mpick-body mg-model-picker) hand real vertical room down to .mg-grid via
       flex:1 below. In an unconstrained parent this sizes to content exactly like
       `display:block` used to (see the file header comment), so nothing regresses for a
       plain/standalone mount. min-height:0 lets it actually SHRINK inside a flex
       ancestor instead of the classic flex content-minimum trap. */
    'mg-model-picker{display:flex;flex-direction:column;min-height:0;font:13px/1.4 system-ui,sans-serif;color:var(--text,#d6d2e2);}',
    'mg-model-picker .mg-q{width:100%;box-sizing:border-box;background:var(--base,#0c0a1c);',
    ' border:1px solid var(--surface1,#3a3460);border-radius:8px;padding:7px 9px;color:var(--text,#d6d2e2);font:13px/1.2 system-ui;flex:none;}',
    'mg-model-picker .mg-q:focus{outline:0;border-color:var(--accent,#b692e6);}',
    /* O13 market UI (sort + category), opt-in via the `market` attribute -- same shape as
       the gallery's own #mkt-sort/#mkt-cats. flex:none -- natural size, never stretched. */
    'mg-model-picker .mg-mktsort{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;flex:none;}',
    'mg-model-picker .mg-mktsort button{min-width:72px;}',
    'mg-model-picker .mg-mktsort button{flex:1;padding:5px 0;font-size:11px;border-radius:6px;background:var(--surface0,#211f3a);',
    ' color:var(--subtext,#9a93ab);border:1px solid var(--surface1,#3a3460);cursor:pointer;}',
    'mg-model-picker .mg-mktsort button.on{background:var(--surface1,#3a3460);color:var(--text,#d6d2e2);',
    ' border-color:var(--accent,#b692e6);font-weight:600;}',
    'mg-model-picker .mg-mktcats{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px;flex:none;}',
    'mg-model-picker .mg-mktcats button{padding:3px 10px;font-size:10.5px;border-radius:11px;background:var(--surface0,#211f3a);',
    ' color:var(--subtext,#9a93ab);border:1px solid var(--surface1,#3a3460);cursor:pointer;}',
    'mg-model-picker .mg-mktcats button.on{background:var(--accent,#b692e6);color:var(--base,#0c0a1c);',
    ' border-color:var(--accent,#b692e6);font-weight:600;}',
    /* picker-parity round 3: the SOURCE row (Market / Bookmarked / Mine). Same button-row
       mechanism as .mg-mktsort so no new UI language is introduced, but deliberately louder --
       taller, heavier, and it takes the ACCENT fill when active where sort settles for the muted
       surface fill. Owner asked for these to be "more apparent"; that is the whole difference. */
    'mg-model-picker .mg-mktsrc{display:flex;gap:6px;margin-top:8px;flex:none;}',
    'mg-model-picker .mg-mktsrc button{flex:1;padding:7px 0;font-size:12px;font-weight:600;',
    ' letter-spacing:.02em;border-radius:7px;background:var(--surface0,#211f3a);',
    ' color:var(--subtext,#9a93ab);border:1px solid var(--surface1,#3a3460);cursor:pointer;}',
    'mg-model-picker .mg-mktsrc button.on{background:var(--accent,#b692e6);color:var(--base,#0c0a1c);',
    ' border-color:var(--accent,#b692e6);}',
    /* Posted-at + License. Dropdowns rather than more chips: neither is a browsing mode you
       flip between constantly, and three more chip rows would bury the grid. */
    'mg-model-picker .mg-mktsel{display:flex;gap:6px;margin-top:6px;flex:none;}',
    'mg-model-picker .mg-mktsel select{flex:1;min-width:0;background:var(--surface0,#211f3a);',
    ' border:1px solid var(--surface1,#3a3460);border-radius:6px;color:var(--subtext,#9a93ab);',
    ' font:10.5px/1.3 system-ui;padding:4px 6px;cursor:pointer;}',
    'mg-model-picker .mg-mktsel select.on{color:var(--text,#d6d2e2);border-color:var(--accent,#b692e6);}',
    /* picker-parity-round2: was a fixed max-height:320px (the O12/O13-round bug -- a tall
       host left dead space below this fixed cap instead of the grid using it). Now a flex
       item that fills whatever room the (flex-column) host element above has, with its own
       internal scroll for overflow -- see the file header comment for the unconstrained-
       parent fallback behavior. min-height keeps it from ever looking collapsed to nothing
       while a search is in flight in a very short host.
       grid-auto-rows:min-content -- found live 2026-07-24 (owner report: thumbnails
       "squished", grid "no longer scrollable"): giving .mg-grid a REAL, definite height
       (the flex:1 1 auto above) exposed a second bug riding along with the first fix.
       .mg-card has overflow:hidden, which per spec makes its OWN automatic minimum size
       (what grid track sizing falls back to) resolve to 0 instead of its content's real
       min-content height -- so with a definite container height and no card contributing
       a height floor, every implicit `auto` row track was stretching/compressing to
       divide the container's fixed height evenly across however many rows existed (empty-
       looking 320px cap hid this before: fewer visible rows, less pressure). 24 cards
       measured live: rows collapsed to ~41px each (image forced to a sliver, cropped by
       the card's own overflow:hidden -- "squished"), and since the compressed rows always
       exactly filled the container, scrollHeight never exceeded clientHeight either --
       "no longer scrollable" was the SAME bug, not a second one. min-content forces each
       auto row to size off its content's own minimum instead, restoring both real card
       height and real overflow. Verified live: rows back to ~200px, images a real 1:1
       square, scrollHeight now correctly exceeds clientHeight with 24+ cards. */
    'mg-model-picker .mg-grid{display:grid;grid-template-columns:1fr 1fr;grid-auto-rows:min-content;gap:7px;margin-top:8px;',
    ' flex:1 1 auto;min-height:140px;overflow:auto;transition:opacity .12s;}',
    'mg-model-picker .mg-card{position:relative;background:var(--surface0,#211f3a);border:1px solid var(--surface1,#3a3460);',
    ' border-radius:8px;overflow:hidden;cursor:pointer;}',
    'mg-model-picker .mg-card:hover{border-color:var(--accent,#b692e6);}',
    'mg-model-picker .mg-card.sel{border-color:var(--accent,#b692e6);box-shadow:0 0 0 1px var(--accent,#b692e6) inset;}',
    'mg-model-picker .mg-cov{width:100%;aspect-ratio:1/1;object-fit:cover;display:block;background:var(--base,#0c0a1c);}',
    'mg-model-picker .mg-cov.blur{filter:blur(14px);}',
    'mg-model-picker .mg-meta{padding:5px 6px;}',
    'mg-model-picker .mg-nm{font-size:11px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    'mg-model-picker .mg-sub{display:flex;gap:7px;margin-top:2px;font-size:9.5px;color:var(--subtext,#9a93ab);flex-wrap:wrap;}',
    /* picker-parity-round2: architecture-compat badge (base-type attribute -> server
       `compat` tag, see the file header comment). 'yes' = confirmed same architecture as
       the selected base, 'no' = confirmed different (would fail on submit) -- 'unknown'
       rows get no badge at all (see annotate_lora_compat's docstring: badging an unknown
       as compatible would overclaim data the app doesn't have). */
    'mg-model-picker .mg-cbadge{display:inline-block;margin-top:3px;font-size:9px;padding:1px 6px;border-radius:5px;font-weight:600;}',
    'mg-model-picker .mg-cbadge.yes{background:rgba(148,226,178,.16);color:var(--green,#94e2b2);}',
    'mg-model-picker .mg-cbadge.no{background:rgba(243,139,168,.16);color:var(--red,#f38ba8);}',
    'mg-model-picker .mg-empty{color:var(--subtext,#9a93ab);font-size:12px;padding:12px 4px;display:none;font-style:italic;flex:none;}',
    /* the floating preview -- fixed so the Loom canvas transform:scale() can't distort it */
    'mg-model-picker .mg-preview{position:fixed;z-index:600;width:300px;background:var(--mantle,#131024);',
    ' border:1px solid var(--surface1,#3a3460);border-radius:12px;box-shadow:0 22px 60px rgba(0,0,0,.6);',
    ' overflow:hidden;display:none;pointer-events:none;}',
    'mg-model-picker .mg-preview.open{display:block;}',
    'mg-model-picker .mg-preview img{width:100%;max-height:300px;object-fit:cover;display:block;}',
    'mg-model-picker .mg-preview img.blur{filter:blur(20px);}',
    'mg-model-picker .mp-meta{padding:10px 12px;}',
    'mg-model-picker .mp-nm{font-weight:700;font-size:13px;}',
    'mg-model-picker .mp-sub{display:flex;gap:9px;margin-top:4px;font-size:11px;color:var(--subtext,#9a93ab);flex-wrap:wrap;}',
    'mg-model-picker .mp-badges{display:flex;gap:5px;margin-top:6px;flex-wrap:wrap;}',
    'mg-model-picker .mp-badges .bdg{font-size:9.5px;padding:2px 6px;border-radius:5px;background:var(--surface0,#211f3a);color:var(--subtext,#9a93ab);}',
    'mg-model-picker .mp-badges .bdg.official{color:var(--accent,#b692e6);}',
    'mg-model-picker .mp-desc{margin-top:7px;font-size:11px;color:var(--subtext,#9a93ab);line-height:1.45;max-height:88px;overflow:hidden;}',
    // Owner report 2026-07-24: the grid "scrolls about 4 extra rows and then stops -- no
    // continuous scroll". Root cause was server-side (see api_model_search's own comment) --
    // has_more was already computed correctly the whole time, nothing client-side ever read
    // it or asked for a next page. flex:none -- a static line below the (already scrolling)
    // grid, not part of its own scroll content, so it never needs repositioning as cards append.
    'mg-model-picker .mg-loadmore{display:none;text-align:center;padding:6px 0 2px;font-size:10.5px;color:var(--subtext,#9a93ab);flex:none;}',
    'mg-model-picker .mg-loadmore.on{display:block;}'
  ].join('');

  function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = MG_CSS;
    (document.head || document.documentElement).appendChild(s);
  }

  class MgModelPickerEl extends HTMLElement {
    connectedCallback() {
      injectStyle();
      if (this._built) return;
      this._built = true;
      this._kind = this.getAttribute('kind') || 'base';
      this._q = '';
      this._seq = 0;
      this._value = null;
      this._multi = this.hasAttribute('multi');
      this._selected = [];
      this._market = this.hasAttribute('market');
      this._sort = 'trending';
      this._category = '';
      // picker-parity round 3. `_src` is WHICH LIST is being browsed; `_source` is a market
      // FILTER. PixAI's own UI overloads the word "source" for both, which is why these are
      // kept distinct here and in the query string.
      this._src = 'market';
      this._source = '';
      this._posted = '';
      this._license = '';
      // Base-model architecture filter. An ARRAY because their Model Type control is
      // multi-select -- successive clicks accumulate, measured off live requests. Empty means
      // "All", which the server turns into ANY_MODEL.
      this._modelTypes = [];
      // picker-parity-round2: the currently-selected base model's resolved model_type, set
      // (and kept updated) by the host -- see the file header comment. Only meaningful for
      // kind="lora"; a base-kind mount reads it but never sends it (nothing to compat-sort
      // a base model against).
      this._baseType = this.getAttribute('base-type') || '';
      // Pagination state (owner report 2026-07-24: no continuous scroll). _cursor/_hasMore
      // describe the CURRENT search only -- both reset on every fresh _search() (a new
      // query/filter is a new list, not a continuation of the old one). _loadingMore guards
      // against the scroll handler firing a second fetch while one is already in flight.
      this._cursor = '';
      this._hasMore = false;
      this._loadingMore = false;
      this.innerHTML =
        '<input class="mg-q" type="text" placeholder="search models…" aria-label="Search models">' +
        (this._market ? this._marketSkeleton() : '') +
        '<div class="mg-empty"></div>' +
        '<div class="mg-grid" role="listbox"></div>' +
        '<div class="mg-loadmore" aria-hidden="true">loading more…</div>' +
        '<div class="mg-preview" aria-hidden="true"></div>';
      this._input = this.querySelector('.mg-q');
      this._grid = this.querySelector('.mg-grid');
      this._empty = this.querySelector('.mg-empty');
      this._loadmore = this.querySelector('.mg-loadmore');
      this._preview = this.querySelector('.mg-preview');
      var self = this;
      this._input.addEventListener('input', function () { self._q = self._input.value; self._debounce(); });
      // Scroll-triggered "load more": _loadMore() is itself idempotent-guarded
      // (_loadingMore / !_hasMore), so this needs no separate debounce -- a fast scroll
      // firing the handler many times in a row just re-checks the same cheap arithmetic
      // until the guard lets exactly one fetch through.
      // Owner report 2026-07-24: "still slow and a bit choppy". A native scroll event can
      // fire many times per animation frame (especially with the DOM growing on every
      // load-more -- more content, more expensive layout). scrollHeight/scrollTop/
      // clientHeight are all LAYOUT reads -- doing that arithmetic unthrottled, on every
      // single event, forces a synchronous layout recalculation each time, which is
      // exactly what scroll jank is made of. requestAnimationFrame collapses any number
      // of events within one frame down to a single check, right before the browser
      // paints that frame anyway -- standard scroll-listener discipline, not a guess.
      var scrollRaf = null;
      this._grid.addEventListener('scroll', function () {
        if (scrollRaf) return;
        scrollRaf = requestAnimationFrame(function () {
          scrollRaf = null;
          var g = self._grid;
          if (g.scrollHeight - g.scrollTop - g.clientHeight < 150) self._loadMore();
        });
      });
      if (this._market) {
        this._syncFilterVisibility();
        this.querySelectorAll('.mg-mktsrc button').forEach(function (b) {
          b.addEventListener('click', function () {
            var v = b.getAttribute('data-src');
            if (v === self._src) return;
            self._src = v;
            self.querySelectorAll('.mg-mktsrc button').forEach(function (x) {
              x.classList.toggle('on', x === b);
            });
            self._syncFilterVisibility();
            self._search();
          });
        });
        // Model Type chips (base only). Multi-select: All clears, anything else toggles.
        this.querySelectorAll('.mg-mkttypes button').forEach(function (b) {
          b.addEventListener('click', function () {
            var v = b.getAttribute('data-mt');
            if (!v) {
              if (!self._modelTypes.length) return;
              self._modelTypes = [];
            } else {
              var at = self._modelTypes.indexOf(v);
              if (at >= 0) self._modelTypes.splice(at, 1);
              else self._modelTypes.push(v);
            }
            self.querySelectorAll('.mg-mkttypes button').forEach(function (x) {
              var xv = x.getAttribute('data-mt');
              x.classList.toggle('on', xv ? self._modelTypes.indexOf(xv) >= 0
                                          : !self._modelTypes.length);
            });
            self._search();
          });
        });
        this.querySelectorAll('.mg-mktsel select').forEach(function (sel) {
          sel.addEventListener('change', function () {
            if (sel.classList.contains('mg-posted')) self._posted = sel.value;
            else if (sel.classList.contains('mg-source')) self._source = sel.value;
            else if (sel.classList.contains('mg-license')) self._license = sel.value;
            // A set filter is worth showing at a glance without opening the dropdown.
            sel.classList.toggle('on', !!sel.value);
            self._search();
          });
        });
        this.querySelectorAll('.mg-mktsort button').forEach(function (b) {
          b.addEventListener('click', function () {
            var s = b.getAttribute('data-sort');
            if (s === self._sort) return;
            self._sort = s;
            self.querySelectorAll('.mg-mktsort button').forEach(function (x) { x.classList.toggle('on', x === b); });
            self._search();
          });
        });
        this.querySelectorAll('.mg-mktcats button').forEach(function (b) {
          b.addEventListener('click', function () {
            var c = b.getAttribute('data-cat') || '';
            if (c === self._category) return;
            self._category = c;
            self.querySelectorAll('.mg-mktcats button').forEach(function (x) { x.classList.toggle('on', x === b); });
            self._search();
          });
        });
      }
      // Owner report 2026-07-24: "still slow". Both the Gallery's ensurePickers() and the
      // Loom's pickerMounted create+mount a kind="base" AND a kind="lora" instance
      // TOGETHER on first flyout open (so switching tabs never re-fetches -- "each keeps
      // its OWN last-searched results independently"), but the OTHER one starts hidden
      // (style.display:none) -- the owner is looking at neither yet, usually the base
      // model first. Searching it anyway on mount means every single flyout open fired
      // TWO full searches competing for the same connection, for a tab nobody had asked
      // to see. Defer: skip the automatic browse-on-open here if the element starts
      // hidden, and let the host call ensureSearched() (below) the moment it actually
      // reveals this instance -- see setKind()/the pickerKind effect on each host.
      //
      // _stale (the 2026-07-21 audit follow-up) is the same idea one step further: this
      // instance HAS searched, but a filter changed while it was hidden, so its grid no
      // longer matches its own filters. Only base-type can do that today (see
      // attributeChangedCallback) -- every other filter lives on a control inside this
      // element, which nobody can touch without looking at it.
      this._searched = false;
      this._stale = false;
      if (this.style.display !== 'none') { this._searched = true; this._search(); } // browse-on-open: empty query -> the API's popular list
    }

    // Called by the host right after it makes a previously-hidden instance visible (see
    // the file header comment above). Normally a no-op after the first real call -- once
    // searched, switching tabs back and forth must never re-fetch, matching the existing
    // "each keeps its OWN last-searched results independently" contract. The one exception
    // is _stale: a base-type change that arrived while this instance was hidden deferred
    // its re-search to right here, so the newly-revealed grid isn't showing compat
    // sort/badges for a base model that is no longer selected.
    ensureSearched() {
      if (this._searched && !this._stale) return;
      this._search();
    }

    // O13: Popular/Newest sort + the gallery's 6 LoRA category chips, same list as
    // moonglade_gallery.py's #mkt-cats (All is the '' category, not a real server value).
    _marketSkeleton() {
      // "Mine" is LoRA-only: you author LoRAs, not base models, and PixAI's own base-model
      // picker offers no equivalent tab either.
      var mine = this._kind === 'lora'
        ? '<button type="button" data-src="mine">Mine</button>' : '';
      return (
        '<div class="mg-mktsrc"><button type="button" class="on" data-src="market">Market</button>' +
        '<button type="button" data-src="bookmark">Bookmarked</button>' + mine + '</div>' +
        '<div class="mg-mktfilters">' +
        // PixAI's own four, not our old Popular/Newest pair. Trending is their default.
        '<div class="mg-mktsort"><button type="button" class="on" data-sort="trending">Trending</button>' +
        '<button type="button" data-sort="liked">Most Liked</button>' +
        '<button type="button" data-sort="used">Most Used</button>' +
        '<button type="button" data-sort="newest">Latest</button></div>' +
        // LoRAs filter by CATEGORY; base models filter by ARCHITECTURE. Two different controls,
        // matching PixAI, rather than one shared row that half-applies.
        (this._kind === 'lora'
          // Nine categories, matching PixAI exactly. Animal and Realistic were missing; their
          // own training page leaked the canonical list by rendering raw i18n keys.
          ? '<div class="mg-mktcats"><button type="button" class="on" data-cat="">All</button>' +
            '<button type="button" data-cat="character">Character</button>' +
            '<button type="button" data-cat="animal">Animal</button>' +
            '<button type="button" data-cat="style">Style</button>' +
            '<button type="button" data-cat="realistic">Realistic</button>' +
            '<button type="button" data-cat="pose">Pose</button>' +
            '<button type="button" data-cat="clothing">Clothing</button>' +
            '<button type="button" data-cat="background">Background</button>' +
            '<button type="button" data-cat="detail">Detail</button>' +
            '<button type="button" data-cat="other">Other</button></div>'
          // Model Type. Every token measured off a live request -- a wrong enum here returns
          // the wrong rows rather than erroring, so none of these is a guess. MULTI-SELECT:
          // "All" clears the set, any other chip toggles.
          : '<div class="mg-mktcats mg-mkttypes">' +
            '<button type="button" class="on" data-mt="">All</button>' +
            '<button type="button" data-mt="MMDIT26B_MODEL">DiT.3</button>' +
            '<button type="button" data-mt="MMDIT26A_MODEL">DiT.2</button>' +
            '<button type="button" data-mt="DIT7_MODEL">DiT.1</button>' +
            '<button type="button" data-mt="USER_DIT26A_MODEL">Community DiT</button>' +
            '<button type="button" data-mt="SDXL_MODEL">SDXL</button>' +
            '<button type="button" data-mt="SD_V1_MODEL">SD 1.5</button></div>') +
        '<div class="mg-mktsel">' +
          '<select class="mg-posted" aria-label="Posted at">' +
            '<option value="">Any time</option>' +
            '<option value="yesterday">Yesterday</option>' +
            '<option value="7d">Past 7 days</option>' +
            '<option value="30d">Past 30 days</option></select>' +
          (this._kind === 'lora'
            ? '<select class="mg-source" aria-label="Source">' +
              '<option value="">Any source</option>' +
              '<option value="pixai">PixAI-trained</option>' +
              '<option value="external">External</option></select>' : '') +
          '<select class="mg-license" aria-label="License">' +
            '<option value="">Any licence</option>' +
            '<option value="COMMERCIAL">Commercial use OK</option></select>' +
        '</div></div>'
      );
    }

    // Only show filters the CURRENT source can actually honour. The bookmark list accepts a
    // keyword and the architecture filter and nothing else, so leaving sort/category/dropdowns
    // on screen there would be controls that silently do nothing -- which is exactly how the
    // Enhance cards wasted everyone's time. PixAI hides its own Filters button on that tab.
    _syncFilterVisibility() {
      var box = this.querySelector('.mg-mktfilters');
      if (box) box.style.display = this._src === 'bookmark' ? 'none' : '';
    }

    static get observedAttributes() { return ['kind', 'base-type']; }
    attributeChangedCallback(name, _old, val) {
      if (name === 'kind' && this._built && val && val !== this._kind) {
        this._kind = val; this._search();
      }
      // picker-parity-round2: base-type changes (a new base model picked, or cleared)
      // after the LoRA picker's own results are already on screen -- re-search so the
      // compat sort/badges reflect the NEW base immediately, not just on the next
      // keystroke/category click. '' is a legitimate value (base cleared), so this fires
      // even when val is falsy -- unlike 'kind' above, which never goes empty in practice.
      //
      // the 2026-07-21 audit follow-up: "already on screen" is the whole point, and this used
      // to search unconditionally. Picking a base model sets base-type on a LoRA picker
      // that is normally still HIDDEN (both hosts mount base+LoRA together and reveal one),
      // so the common flow fired a full request and built ~24 cards into a display:none
      // element nobody had asked to see -- and then the reveal fired the IDENTICAL request
      // a second time. Defer instead, in both hidden cases:
      //   never searched -> nothing to refresh; the reveal's ensureSearched() will run the
      //                     first search with the new _baseType already in place.
      //   searched but hidden -> mark _stale so the next reveal re-searches once, rather
      //                     than re-rendering a grid nobody is looking at right now.
      if (name === 'base-type' && this._built && (val || '') !== this._baseType) {
        this._baseType = val || '';
        if (this.style.display === 'none') { if (this._searched) this._stale = true; return; }
        this._search();
      }
    }

    _debounce() {
      clearTimeout(this._t);
      var self = this;
      this._t = setTimeout(function () { self._search(); }, 250);
    }

    // Shared by _search() (fresh list) and _loadMore() (continuation) so the two can never
    // drift on which filters apply -- a next-page fetch must carry the EXACT same
    // kind/q/market/base_type as the search it's continuing, only `cursor` differs.
    _searchUrl(cursor) {
      var u = '/api/model-search?kind=' + encodeURIComponent(this._kind) +
              '&size=24&q=' + encodeURIComponent(this._q || '');
      if (this._market) {
        u += '&src=' + encodeURIComponent(this._src);
        // Only send what this source honours, so a stale dropdown value cannot quietly
        // change a bookmark listing.
        if (this._src !== 'bookmark') {
          u += '&sort=' + encodeURIComponent(this._sort) +
               '&category=' + encodeURIComponent(this._category) +
               '&posted=' + encodeURIComponent(this._posted) +
               '&source=' + encodeURIComponent(this._source) +
               '&license=' + encodeURIComponent(this._license);
          // Repeated param, because the filter is multi-select server-side too.
          this._modelTypes.forEach(function (t) {
            u += '&model_type=' + encodeURIComponent(t);
          });
        }
      }
      // picker-parity-round2: architecture-aware compat sort/badge -- LoRA only (nothing
      // to compat-sort a base-model search against), and only once a base is actually
      // selected (empty base-type -> server leaves results untouched, see api_model_search).
      if (this._kind === 'lora' && this._baseType) {
        u += '&base_type=' + encodeURIComponent(this._baseType);
      }
      if (cursor) u += '&cursor=' + encodeURIComponent(cursor);
      return u;
    }

    _search() {
      // A search is a search, whoever asked for it -- browse-on-open, a keystroke, a
      // category chip, a base-type change, or ensureSearched(). Marking the flag HERE
      // rather than at each call site is what stops the flag from drifting out of step
      // with reality: it previously lived only on the two call sites that knew about it,
      // so a base-type-triggered search left _searched false and the very next
      // ensureSearched() re-ran the identical request. _stale clears for the same reason
      // -- whatever filters this search is carrying, the grid now matches them.
      this._searched = true;
      this._stale = false;
      var mine = ++this._seq, self = this;
      if (this._grid) this._grid.style.opacity = '.45';
      this._cursor = ''; this._hasMore = false;   // a fresh search is a new list, not a continuation
      fetch(this._searchUrl()).then(function (r) { return r.json(); }).then(function (d) {
        if (mine !== self._seq) return;
        self._hasMore = !!(d && d.has_more);
        self._cursor = (d && d.next_cursor) || '';
        self._render((d && d.results) || [], d && d.error, false);
        if (self._grid) self._grid.style.opacity = '1';
      }).catch(function () {
        if (mine !== self._seq) return;
        self._render([], 'network error', false);
        if (self._grid) self._grid.style.opacity = '1';
      });
    }

    // Owner report 2026-07-24: the grid stopped after ~4 extra rows with no continuous
    // scroll -- has_more/next_cursor were already correct server-side (see
    // api_model_search's comment), nothing here ever asked for a next page. Guarded by
    // _hasMore (server said there's more) and _loadingMore (no second fetch while one's
    // already in flight, e.g. a fast scroll re-triggering the listener). Uses the SAME
    // `mine`/`_seq` staleness guard as _search() -- a fresh search started while a
    // load-more was in flight must not let the old page's results land after it.
    _loadMore() {
      if (!this._hasMore || this._loadingMore) return;
      var mine = this._seq, self = this;
      this._loadingMore = true;
      if (this._loadmore) this._loadmore.classList.add('on');
      fetch(this._searchUrl(this._cursor)).then(function (r) { return r.json(); }).then(function (d) {
        self._loadingMore = false;
        if (self._loadmore) self._loadmore.classList.remove('on');
        if (mine !== self._seq) return;   // a fresh search superseded this continuation
        // A server-side {error:...} response (api_model_search's own except-clause shape)
        // carries no has_more/next_cursor at all -- leave _hasMore/_cursor exactly as they
        // were on a transient failure, same as the network-catch below, so the next scroll
        // near the bottom simply retries instead of a one-shot error permanently wedging
        // pagination closed with nothing visibly wrong.
        if (d && d.error) return;
        self._hasMore = !!(d && d.has_more);
        self._cursor = (d && d.next_cursor) || '';
        self._render((d && d.results) || [], null, true);
      }).catch(function () {
        self._loadingMore = false;
        if (self._loadmore) self._loadmore.classList.remove('on');
        // A failed load-more leaves _hasMore as it was (server never actually said "no
        // more") -- the next scroll near the bottom simply retries, no dead-end state.
      });
    }

    _render(rows, err, append) {
      var g = this._grid, e = this._empty, self = this;
      if (!append) g.innerHTML = '';
      if (err) { e.textContent = '⚠ ' + err; e.style.display = 'block'; return; }
      if (!append && !rows.length) { e.textContent = 'No results — try another search.'; e.style.display = 'block'; return; }
      e.style.display = 'none';
      rows.forEach(function (m) {
        var c = document.createElement('div');
        c.className = 'mg-card' + (self._isSelected(m) ? ' sel' : '');
        c.dataset.mid = m.model_id;      // lets deselect() find this card again
        var cov = m.preview_url
          ? '<img class="mg-cov' + (m.should_blur ? ' blur' : '') + '" loading="lazy" src="' + esc(m.preview_url) + '" alt="">'
          : '<div class="mg-cov"></div>';
        var uses = m.ref_count ? '<span>◈ ' + fmtCompact(m.ref_count) + '</span>' : '';
        c.innerHTML = cov +
          '<div class="mg-meta"><div class="mg-nm" title="' + esc(m.title) + '">' + esc(m.title) + '</div>' +
          '<div class="mg-sub"><span>' + tyShort(m.type) + '</span><span>♥ ' + fmt(m.liked_count) + '</span>' + uses + '</div>' +
          compatBadge(m.compat) + '</div>';
        c.addEventListener('click', function () { self._pick(m, c); });
        // Debounced (D-11): a raw mouseenter re-triggered an instant, un-animated,
        // freshly-repositioned popup on every card the mouse passed over while
        // scanning the grid -- what "browsing" actually is. Same fix as the Gallery's
        // own #model-flyout (moonglade_gallery.py's scheduleShowPreview/cancelPreview) --
        // two independently-drifted copies, both needed it.
        c.addEventListener('mouseenter', function () { self._schedulePreview(m, c); });
        c.addEventListener('mouseleave', function () { self._cancelPreview(); });
        g.appendChild(c);
      });
    }

    _isSelected(m) {
      if (this._multi) return this._selected.some(function (e) { return e.model_id === m.model_id; });
      return this._value && this._value.model_id === m.model_id;
    }

    _pick(m, card) {
      if (this._multi) { this._toggleMulti(m, card); return; }
      this._value = m;
      var g = this._grid;
      if (g) { var sel = g.querySelector('.mg-card.sel'); if (sel) sel.classList.remove('sel'); }
      if (card) card.classList.add('sel');
      this._hidePreview();
      this.dispatchEvent(new CustomEvent('mg-pick', { bubbles: true, composed: true, detail: m }));
    }

    _toggleMulti(m, card) {
      var self = this, i = -1;
      this._selected.forEach(function (e, j) { if (e.model_id === m.model_id) i = j; });
      this._hidePreview();
      if (i >= 0) {
        var removed = this._selected.splice(i, 1)[0];
        if (card) card.classList.remove('sel');
        this.dispatchEvent(new CustomEvent('mg-pick', {
          bubbles: true, composed: true, detail: { model: removed, selected: false }
        }));
        return;
      }
      // Same shape as the Gallery's toggleLora(): push an incomplete entry immediately
      // (host can render a pending/hourglass chip), resolve in the background, then
      // dispatch again with the filled-in entry. An empty/failed resolve is marked
      // `failed`, never silently dropped -- mirrors the fail-open fix (audit 2026-07-21):
      // a LoRA that never resolves must not be able to vanish from a submit unnoticed.
      var entry = { model_id: m.model_id, title: m.title, preview_url: m.preview_url,
                    version_id: '', weight: 0.7, lora_base_type: '', trigger_words: '', failed: false };
      this._selected.push(entry);
      if (card) card.classList.add('sel');
      this.dispatchEvent(new CustomEvent('mg-pick', {
        bubbles: true, composed: true, detail: { model: entry, selected: true }
      }));
      // &all=1 (per-LoRA version selection): every published release, not just the
      // silently-assumed latest -- entry.versions rides along so a host can offer a
      // per-chip selector, the same split as the base model's #gen-version/.lv-versel
      // (this component renders the CARDS, the host renders the picked-item chip UI).
      fetch('/api/model-version?model_id=' + encodeURIComponent(m.model_id) + '&all=1')
        .then(function (r) { return r.json(); })
        .then(function (d) {
          // Un-picking a LoRA while its resolve is still in flight used to RESURRECT it:
          // this landed afterwards and re-dispatched `selected: true`, putting a chip the
          // user had just removed back in the host's list. Same superseded-response guard
          // as <mg-upscale-panel>'s _price() seq token -- the entry's own identity is the
          // token here, since a different LoRA picked meanwhile is still legitimately ours
          // (and a re-pick pushes a NEW entry with its own resolve).
          if (self._selected.indexOf(entry) === -1) return;
          var versions = (d && d.versions) || [], v = versions[0] || {};
          entry.version_id = v.version_id || '';
          entry.lora_base_type = v.lora_base_model_type || '';
          entry.trigger_words = v.trigger_words || '';
          entry.versions = versions;
          entry.failed = !entry.version_id;
          self.dispatchEvent(new CustomEvent('mg-pick', {
            bubbles: true, composed: true, detail: { model: entry, selected: true }
          }));
        })
        .catch(function () {
          if (self._selected.indexOf(entry) === -1) return;
          entry.failed = true;
          self.dispatchEvent(new CustomEvent('mg-pick', {
            bubbles: true, composed: true, detail: { model: entry, selected: true }
          }));
        });
    }

    _showPreview(m, anchor) {
      var p = this._preview; if (!p || !m) return;
      var src = m.cover_url || m.preview_url;
      var base = baseLabel(m.base_model);
      var badges = '';
      if (base) badges += '<span class="bdg base">' + esc(base) + '</span>';
      if (m.official) badges += '<span class="bdg official" title="In-house / official model">✓ Official</span>';
      var stats = '<span>' + tyShort(m.type) + '</span>';
      if (m.ref_count) stats += '<span>◈ ' + fmtCompact(m.ref_count) + ' uses</span>';
      stats += '<span>♥ ' + fmt(m.liked_count) + '</span>';
      if (m.comment_count) stats += '<span>💬 ' + fmt(m.comment_count) + '</span>';
      p.innerHTML = (src ? '<img src="' + esc(src) + '"' + (m.should_blur ? ' class="blur"' : '') + ' alt="">' : '') +
        '<div class="mp-meta"><div class="mp-nm">' + esc(m.title) + '</div>' +
        '<div class="mp-sub">' + stats + '</div>' +
        (badges ? '<div class="mp-badges">' + badges + '</div>' : '') +
        (m.description ? '<div class="mp-desc">' + esc(m.description) + '</div>' : '') + '</div>';
      p.classList.add('open'); p.setAttribute('aria-hidden', 'false');
      this._place(p, anchor);
    }

    _hidePreview() {
      var p = this._preview;
      if (p) { p.classList.remove('open'); p.setAttribute('aria-hidden', 'true'); }
    }

    _schedulePreview(m, anchor) {
      var self = this;
      clearTimeout(this._pt);
      this._pt = setTimeout(function () { self._showPreview(m, anchor); }, 130);
    }

    _cancelPreview() {
      clearTimeout(this._pt);
      this._hidePreview();
    }

    _place(p, anchor) {
      var r = anchor.getBoundingClientRect(), w = 300, gap = 12, x;
      // open toward whichever side has room, biased right
      x = r.right + gap;
      if (x + w > window.innerWidth - 8) x = Math.max(8, r.left - w - gap);
      var y = Math.max(8, Math.min(r.top - 10, window.innerHeight - 380));
      p.style.left = x + 'px';
      p.style.top = y + 'px';
    }

    get value() { return this._value || null; }
    set value(v) { this._value = v || null; }
    get selected() { return this._selected.slice(); }

    // Drop a selection the HOST removed on its own. The host keeps its own copy of the
    // picked list and can drop an entry without a card ever being clicked -- the chip's
    // own remove button is the ordinary way a LoRA goes away. With no way to say so,
    // this component still believed the entry was picked, and three things went wrong
    // at once: the card stayed lit, the next click on it read as a REMOVE instead of a
    // re-add, and an in-flight /api/model-version resolve still considered the entry
    // live and re-dispatched `selected: true` -- putting back the LoRA just removed.
    // Deliberately does NOT fire mg-pick: the host asked for this, telling it what it
    // just did would only risk a loop.
    deselect(modelId) {
      var id = String(modelId == null ? '' : modelId), i = -1;
      this._selected.forEach(function (e, j) { if (String(e.model_id) === id) i = j; });
      if (i < 0) return false;
      this._selected.splice(i, 1);
      // Walked rather than queried: a model_id is not guaranteed to be a safe CSS
      // selector, and an id with a quote or a colon in it would throw.
      var cards = this._grid ? this._grid.querySelectorAll('.mg-card') : [];
      for (var k = 0; k < cards.length; k++) {
        if (cards[k].dataset.mid === id) { cards[k].classList.remove('sel'); break; }
      }
      return true;
    }
  }

  window.customElements.define('mg-model-picker', MgModelPickerEl);
})();
