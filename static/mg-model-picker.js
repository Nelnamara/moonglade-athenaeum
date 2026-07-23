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
     - each picked LoRA is resolved via /api/model-version (same as the Gallery's own
       toggleLora()) to fill version_id/lora_base_type/trigger_words; the failure/pending
       cases are handled the same way too (an unresolved LoRA is marked `failed`, never
       silently dropped -- see the Gallery's fail-open fix, audit 2026-07-21).
     - mg-pick's detail becomes { model, selected } (selected=true on add/resolve-update,
       false on remove) instead of the raw row -- a deliberate shape difference gated on
       the new opt-in attribute, not a change to the existing single-value contract.
     - `.selected` (getter) returns the current multi-select array. */
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
    'mg-model-picker{display:block;font:13px/1.4 system-ui,sans-serif;color:var(--text,#d6d2e2);}',
    'mg-model-picker .mg-q{width:100%;box-sizing:border-box;background:var(--base,#0c0a1c);',
    ' border:1px solid var(--surface1,#3a3460);border-radius:8px;padding:7px 9px;color:var(--text,#d6d2e2);font:13px/1.2 system-ui;}',
    'mg-model-picker .mg-q:focus{outline:0;border-color:var(--accent,#b692e6);}',
    'mg-model-picker .mg-grid{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:8px;',
    ' max-height:320px;overflow:auto;transition:opacity .12s;}',
    'mg-model-picker .mg-card{position:relative;background:var(--surface0,#211f3a);border:1px solid var(--surface1,#3a3460);',
    ' border-radius:8px;overflow:hidden;cursor:pointer;}',
    'mg-model-picker .mg-card:hover{border-color:var(--accent,#b692e6);}',
    'mg-model-picker .mg-card.sel{border-color:var(--accent,#b692e6);box-shadow:0 0 0 1px var(--accent,#b692e6) inset;}',
    'mg-model-picker .mg-cov{width:100%;aspect-ratio:1/1;object-fit:cover;display:block;background:var(--base,#0c0a1c);}',
    'mg-model-picker .mg-cov.blur{filter:blur(14px);}',
    'mg-model-picker .mg-meta{padding:5px 6px;}',
    'mg-model-picker .mg-nm{font-size:11px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    'mg-model-picker .mg-sub{display:flex;gap:7px;margin-top:2px;font-size:9.5px;color:var(--subtext,#9a93ab);flex-wrap:wrap;}',
    'mg-model-picker .mg-empty{color:var(--subtext,#9a93ab);font-size:12px;padding:12px 4px;display:none;font-style:italic;}',
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
    'mg-model-picker .mp-desc{margin-top:7px;font-size:11px;color:var(--subtext,#9a93ab);line-height:1.45;max-height:88px;overflow:hidden;}'
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
      this.innerHTML =
        '<input class="mg-q" type="text" placeholder="search models…" aria-label="Search models">' +
        '<div class="mg-empty"></div>' +
        '<div class="mg-grid" role="listbox"></div>' +
        '<div class="mg-preview" aria-hidden="true"></div>';
      this._input = this.querySelector('.mg-q');
      this._grid = this.querySelector('.mg-grid');
      this._empty = this.querySelector('.mg-empty');
      this._preview = this.querySelector('.mg-preview');
      var self = this;
      this._input.addEventListener('input', function () { self._q = self._input.value; self._debounce(); });
      this._search(); // browse-on-open: empty query -> the API's popular list
    }

    static get observedAttributes() { return ['kind']; }
    attributeChangedCallback(name, _old, val) {
      if (name === 'kind' && this._built && val && val !== this._kind) {
        this._kind = val; this._search();
      }
    }

    _debounce() {
      clearTimeout(this._t);
      var self = this;
      this._t = setTimeout(function () { self._search(); }, 250);
    }

    _search() {
      var mine = ++this._seq, self = this;
      if (this._grid) this._grid.style.opacity = '.45';
      var u = '/api/model-search?kind=' + encodeURIComponent(this._kind) +
              '&size=12&q=' + encodeURIComponent(this._q || '');
      fetch(u).then(function (r) { return r.json(); }).then(function (d) {
        if (mine !== self._seq) return;
        self._render((d && d.results) || [], d && d.error);
        if (self._grid) self._grid.style.opacity = '1';
      }).catch(function () {
        if (mine !== self._seq) return;
        self._render([], 'network error');
        if (self._grid) self._grid.style.opacity = '1';
      });
    }

    _render(rows, err) {
      var g = this._grid, e = this._empty, self = this;
      g.innerHTML = '';
      if (err) { e.textContent = '⚠ ' + err; e.style.display = 'block'; return; }
      if (!rows.length) { e.textContent = 'No results — try another search.'; e.style.display = 'block'; return; }
      e.style.display = 'none';
      rows.forEach(function (m) {
        var c = document.createElement('div');
        c.className = 'mg-card' + (self._isSelected(m) ? ' sel' : '');
        var cov = m.preview_url
          ? '<img class="mg-cov' + (m.should_blur ? ' blur' : '') + '" loading="lazy" src="' + esc(m.preview_url) + '" alt="">'
          : '<div class="mg-cov"></div>';
        var uses = m.ref_count ? '<span>◈ ' + fmtCompact(m.ref_count) + '</span>' : '';
        c.innerHTML = cov +
          '<div class="mg-meta"><div class="mg-nm" title="' + esc(m.title) + '">' + esc(m.title) + '</div>' +
          '<div class="mg-sub"><span>' + tyShort(m.type) + '</span><span>♥ ' + fmt(m.liked_count) + '</span>' + uses + '</div></div>';
        c.addEventListener('click', function () { self._pick(m, c); });
        // Debounced (D-11): a raw mouseenter re-triggered an instant, un-animated,
        // freshly-repositioned popup on every card the mouse passed over while
        // scanning the grid -- what "browsing" actually is. Same fix as the Gallery's
        // own #model-flyout (pixai_gallery.py's scheduleShowPreview/cancelPreview) --
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
      fetch('/api/model-version?model_id=' + encodeURIComponent(m.model_id))
        .then(function (r) { return r.json(); })
        .then(function (d) {
          entry.version_id = d.version_id || '';
          entry.lora_base_type = d.lora_base_model_type || '';
          entry.trigger_words = d.trigger_words || '';
          entry.failed = !entry.version_id;
          self.dispatchEvent(new CustomEvent('mg-pick', {
            bubbles: true, composed: true, detail: { model: entry, selected: true }
          }));
        })
        .catch(function () {
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
  }

  window.customElements.define('mg-model-picker', MgModelPickerEl);
})();
