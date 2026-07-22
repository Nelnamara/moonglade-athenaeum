/* mg-cost-badge.js -- a framework-neutral <mg-cost-badge> custom element: the one place the
   suite says "this generation costs N credits" or "a free card covers it", so the four
   hand-written copies of that sentence (the gallery's Generate cost line, its Edit cost
   line, <mg-generate-drawer>'s .mgd-cost, the Loom's confirmSpend/cost-to-finish pill) can
   collapse onto one honest renderer instead of drifting apart.

   Fourth (and last) shared web component of the Option-A cohesion migration, same
   conventions as mg-model-picker.js / mg-gallery-picker.js / mg-generate-drawer.js: plain
   global via <script src>, NO build step, runs untranspiled, reads the shared
   DESIGN_TOKENS_CSS custom properties so it re-skins with the app, self-injects one <style>,
   light DOM (no shadow root) so host CSS and the token cascade both reach it.

   IT NEVER FETCHES. The host owns the network call to /api/price (and its debounce, its
   sequence guard, its abort-on-stale logic) and pushes the result in -- exactly like
   <mg-model-picker> takes its selection or <mg-generate-drawer> takes prefill(). That keeps
   this element mountable next to a price check that is already in flight for other reasons
   (the Loom prices a whole shot list at once and caches by priceFingerprint), and keeps a
   badge from quietly firing its own duplicate request per mount.

   The one non-negotiable rule it enforces, inherited verbatim from loom-core.js's
   formatCostEstimate: **a displayed "free" or "0 credits" must only ever mean a genuinely
   settled, zero-cost result -- never "not priced yet" and never "the price check failed."**
   Everything below exists to keep those four cases visually distinct:

     idle      not priced yet -- nothing to price, or the server said so (`note`). Muted.
     checking  a price request is in flight. Muted. (Transient; hosts may skip it.)
     free      a free card (kaisuuken) covers it -> 0 credits spent. Emerald.
     paid      settled credit cost, card or no card. Neutral, or amber via `warn`.
     error     could NOT verify -- fetch failed, server errored, or the response carried
               neither a cost nor a note. RED, and worded so a host reading it aloud still
               warns the user that generating may spend credits. Never silently neutral:
               this is the state a fail-closed spend gate exists for.

   Usage:
     <mg-cost-badge hint="Pick a source image to see the cost."></mg-cost-badge>
   Attributes (all optional, all live-observed):
     hint      -- the idle label. Hosts with a mode-dependent hint just re-set it (the
                  drawer's "Pick a source image" vs "Pick at least one reference").
     warn      -- a caution clause shown ONLY on the `paid` state, which also turns the
                  badge amber: warn="V4.0 full — ~2.5× Lite" renders
                  "⚠ V4.0 full — ~2.5× Lite · ≈ 210,000 credits". Empty/absent = no warning.
     compact   -- boolean; render as an inline pill (toolbar/near-a-button) instead of the
                  full-width bar (a drawer's cost line). Purely presentational.
     card-label-- fallback name for the covering card when the server didn't send one
                  ("a video card" / "an Edit card"); defaults to "a free card".
   Public API (a host sets data; the element never goes and gets it):
     setPrice(resp) -- feed the PARSED /api/price response: {cost, free, cards, card_name,
                  card_expires} on success, {cost:null, free:false, note} when the server
                  couldn't build priceable params, {error} on a server-side failure.
                  **Pass null/undefined when the fetch itself failed** -- that is the
                  could-not-verify state, deliberately NOT the same as clear().
     clear(hint)  -- back to not-yet-priced. Optional one-shot label overriding `hint`.
     setChecking()-- "Checking cost…" while the host's request is in flight.
     price        -- get: the last raw response (null if none/failed). set: === setPrice().
     state        -- 'idle'|'checking'|'free'|'paid'|'error'
     settled      -- true ONLY for 'free' and 'paid': the two states where the cost is
                  actually known. A spend gate should refuse-or-confirm on !settled rather
                  than read cost, which is exactly the fail-closed shape confirmSpend uses.
     cost         -- the raw credit number when known (what it WOULD cost, even in 'free',
                  which is what "saves ~N" reports), else null.
     free         -- true only in the 'free' state.
     text         -- the rendered label, for hosts/tests that want the same wording.
   Events:
     mg-cost -- bubbles + composes (so a React host's DOM listener sees it), fired on every
                public state push. detail: {state, settled, cost, free, cards, card_name,
                card_expires, text, raw}. A host gating a Go button listens to this instead
                of re-deriving the classification it just handed in. */
(function () {
  'use strict';
  if (window.customElements && customElements.get('mg-cost-badge')) return;

  function esc(s) {
    return (s == null ? '' : String(s)).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function fmt(n) { return Number(n).toLocaleString(); }

  // ---- one injected <style>, scoped to the element, reading the shared app tokens ----
  // Box values (padding/radius/font-size/border) are mg-generate-drawer's .mgd-cost
  // verbatim, so a drawer that later swaps its hand-rolled cost div for this element gets a
  // pixel-identical bar. Colour grammar: emerald = covered (nothing spent), amber = spends
  // and the host flagged it as pricey, red = we could not verify and generating may spend.
  var STYLE_ID = 'mg-cost-badge-style';
  var CSS = [
    'mg-cost-badge{display:block;margin:12px 0 8px;padding:8px 10px;border-radius:6px;',
    ' background:var(--surface0,#211f3a);border:1px solid var(--surface1,#3a3460);',
    ' font:12.5px/1.4 system-ui,sans-serif;color:var(--text,#d6d2e2);}',
    'mg-cost-badge[data-state="idle"],mg-cost-badge[data-state="checking"]{color:var(--subtext,#9a93ab);}',
    'mg-cost-badge[data-state="free"]{border-color:var(--emerald,#4fc99a);color:var(--emerald,#4fc99a);}',
    'mg-cost-badge[data-state="paid"][data-warn]{border-color:var(--peach,#fab387);color:var(--peach,#fab387);}',
    'mg-cost-badge[data-state="error"]{border-color:var(--red,#f38ba8);color:var(--red,#f38ba8);}',
    /* compact: an inline pill for a toolbar or a spot next to a Go button */
    'mg-cost-badge[compact]{display:inline-flex;align-items:center;gap:6px;margin:0;',
    ' padding:3px 9px;border-radius:999px;font-size:11.5px;white-space:nowrap;}',
    'mg-cost-badge .mgc-sub{display:block;margin-top:2px;font-size:11px;color:var(--overlay0,#6a6088);}',
    /* On one line in compact, so it needs its own separator -- without the ::before the
       expiry butts straight against "…saves ~84,000 credits" with no space at all (caught
       in the harness 2026-07-21). The block form gets its gap from the line break instead.
       No margin: the host's own flex `gap` already spaces the two items apart. */
    'mg-cost-badge[compact] .mgc-sub{display:inline;margin:0;}',
    'mg-cost-badge[compact] .mgc-sub::before{content:"· ";}',
    /* the eclipse pip, matching the drawer's own in-flight moon at badge scale */
    'mg-cost-badge .mgc-pip{display:inline-block;width:9px;height:9px;border-radius:50%;',
    ' background:var(--lavender,#b692e6);position:relative;overflow:hidden;vertical-align:-1px;',
    ' margin-right:6px;box-shadow:0 0 7px rgba(182,146,230,.7);}',
    'mg-cost-badge .mgc-pip::after{content:"";position:absolute;inset:0;border-radius:50%;',
    ' background:var(--surface0,#211f3a);animation:mgc-eclipse 2.6s ease-in-out infinite;}',
    '@keyframes mgc-eclipse{0%{transform:translateX(-102%);}50%{transform:translateX(0);}100%{transform:translateX(102%);}}'
  ].join('');

  function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = CSS;
    (document.head || document.documentElement).appendChild(s);
  }

  var DEFAULT_HINT = 'No cost yet — nothing to price.';
  // Deliberately says "may spend credits" rather than going quiet: this is the state where
  // the app does NOT know, and the Loom's confirmSpend already words its fail-closed dialog
  // the same way ("Couldn't verify the cost or free-card coverage — it may spend credits").
  var ERR_TEXT = "Couldn't verify the cost — generating may spend credits.";
  var ERR_TITLE = "Couldn't verify the cost or free-card coverage. Generating may spend credits.";

  // A free card's expiresAt is ISO8601, or null for a card that never expires (see
  // match_kaisuuken in pixai_gallery_backup.py) -- null/unparseable just renders nothing
  // rather than an "Invalid Date". Epoch numbers are tolerated in case a caller pre-parses.
  function expiryNote(v) {
    if (v == null || v === '') return null;
    var t;
    if (typeof v === 'number') t = v < 1e12 ? v * 1000 : v;   // seconds vs milliseconds
    else t = Date.parse(String(v));
    if (!isFinite(t)) return null;
    var days = Math.ceil((t - Date.now()) / 86400000);
    var when = days < 0 ? 'expired' :
               days === 0 ? 'expires today' :
               days === 1 ? 'expires tomorrow' :
               'expires in ' + days + ' days';
    return { text: when, title: new Date(t).toLocaleString() };
  }

  class MgCostBadgeEl extends HTMLElement {
    connectedCallback() {
      injectStyle();
      if (this._built) return;
      this._built = true;
      this._state = 'idle';
      this._raw = null;
      this._note = '';      // one-shot idle label from clear(hint) or the server's `note`
      this._msg = '';       // server-side error string, when there was one
      this._text = '';
      // A cost that changes under the user deserves announcing, but never interrupts.
      if (!this.hasAttribute('role')) this.setAttribute('role', 'status');
      if (!this.hasAttribute('aria-live')) this.setAttribute('aria-live', 'polite');
      this._render();
    }

    static get observedAttributes() { return ['hint', 'warn', 'card-label']; }
    attributeChangedCallback() { if (this._built) this._render(); }

    // ---- public API: the host pushes, this element renders ------------------------
    // resp === null/undefined means THE PRICE CHECK ITSELF FAILED (fetch threw, JSON
    // unparseable). That is the could-not-verify state on purpose -- a host that wants
    // "not priced yet" calls clear() instead. Conflating the two is precisely the bug
    // this component exists to make impossible.
    setPrice(resp) {
      var d = (resp && typeof resp === 'object') ? resp : null;
      this._raw = d;
      this._note = '';
      this._msg = '';
      if (!d) {
        this._state = 'error';
      } else if (d.error) {
        this._state = 'error';
        this._msg = String(d.error);
      } else if (d.free) {
        this._state = 'free';
      } else if (d.cost != null && isFinite(Number(d.cost))) {
        // Checked BEFORE `note` so a response carrying both can never hide a real cost
        // behind a hint. (The server only ever sends one or the other today.)
        this._state = 'paid';
      } else if (d.note) {
        this._state = 'idle';
        this._note = String(d.note);
      } else {
        // free:false, cost:null, no note, no error -- nothing was actually priced. Honest
        // answer is "we don't know", NOT a neutral silence and certainly not "0 credits".
        this._state = 'error';
      }
      this._render();
      this._emit();
    }

    clear(hint) {
      this._state = 'idle';
      this._raw = null;
      this._msg = '';
      this._note = hint ? String(hint) : '';
      this._render();
      this._emit();
    }

    setChecking() {
      this._state = 'checking';
      this._msg = '';
      this._render();
      this._emit();
    }

    // ---- rendering -----------------------------------------------------------------
    _render() {
      var d = this._raw || {}, st = this._state;
      var warn = (this.getAttribute('warn') || '').trim();
      var main = '', sub = null, title = '';
      if (st === 'free') {
        var card = d.card_name || (this.getAttribute('card-label') || '').trim() || 'a free card';
        var left = (d.cards != null && isFinite(Number(d.cards))) ? ' (' + fmt(d.cards) + ' left)' : '';
        var saves = (d.cost != null && isFinite(Number(d.cost))) ? ' · saves ~' + fmt(d.cost) + ' credits' : '';
        main = '🎫 FREE — ' + card + ' covers this' + left + saves;
        sub = expiryNote(d.card_expires);
        title = 'A free card is applied automatically at submit — this generation spends 0 credits.';
      } else if (st === 'paid') {
        var n = Number(d.cost);
        // A settled ZERO is real (nothing to spend) but is NOT the free-card state, and must
        // not borrow its wording or its emerald -- same distinction loom-core.js draws
        // between its "🎫 free" and "0 cr" branches.
        main = (n === 0) ? '0 credits — this spends nothing'
                         : (warn ? '⚠ ' + warn + ' · ' : '') + '≈ ' + fmt(n) + ' credits';
        title = (n === 0) ? 'Priced at zero credits. No free card was involved.'
                          : 'No free card covers this — generating spends credits.';
      } else if (st === 'error') {
        main = '⚠ ' + (this._msg || ERR_TEXT);
        title = ERR_TITLE;
      } else if (st === 'checking') {
        main = '<span class="mgc-pip"></span>Checking cost…';
      } else {
        main = this._note || (this.getAttribute('hint') || '').trim() || DEFAULT_HINT;
      }
      // `main` is plain TEXT in every branch except 'checking' (whose only markup is this
      // file's own literal pip span), so it is escaped wholesale here -- server-supplied
      // strings (card_name, note, error) can never reach innerHTML unescaped.
      var html = (st === 'checking') ? main : esc(main);
      if (sub) html += '<span class="mgc-sub" title="' + esc(sub.title) + '">' + esc(sub.text) + '</span>';
      this.innerHTML = html;
      this._text = (st === 'checking' ? 'Checking cost…' : main) + (sub ? ' · ' + sub.text : '');
      this.setAttribute('data-state', st);
      if (st === 'paid' && warn) this.setAttribute('data-warn', '1');
      else this.removeAttribute('data-warn');
      if (title) this.setAttribute('title', title); else this.removeAttribute('title');
    }

    _emit() {
      var d = this._raw || {};
      this.dispatchEvent(new CustomEvent('mg-cost', {
        bubbles: true, composed: true,
        detail: {
          state: this._state,
          settled: this.settled,
          cost: this.cost,
          free: this._state === 'free',
          cards: (d.cards != null ? d.cards : null),
          card_name: (d.card_name != null ? d.card_name : null),
          card_expires: (d.card_expires != null ? d.card_expires : null),
          text: this._text,
          raw: this._raw
        }
      }));
    }

    // ---- read-only accessors -------------------------------------------------------
    get state() { return this._state || 'idle'; }
    get settled() { return this._state === 'free' || this._state === 'paid'; }
    get free() { return this._state === 'free'; }
    get cost() {
      var c = this._raw && this._raw.cost;
      return (c != null && isFinite(Number(c))) ? Number(c) : null;
    }
    get text() { return this._text || ''; }
    get price() { return this._raw; }
    set price(v) { this.setPrice(v); }
  }

  window.customElements.define('mg-cost-badge', MgCostBadgeEl);
})();
