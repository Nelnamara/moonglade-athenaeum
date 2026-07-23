/* mg-gallery-picker.js -- a framework-neutral <mg-gallery-picker> custom element wrapping
   the shared PickerCore (picker-core.js) with real rendering: a full "pick an image from
   your catalog" modal (search, collection/type/rating/sort filters, infinite scroll).

   Second shared web component of the Option-A cohesion migration (see
   docs/archive/SUITE_ARCHITECTURE_AUDIT_2026-07-13.md, archived), same conventions as
   mg-model-picker.js: plain global
   via <script src>, no build step, reads the shared DESIGN_TOKENS_CSS. PickerCore already
   unified the browse/filter/paginate LOGIC between the gallery's vanilla Picker and the
   Loom's React GalleryPick; this element unifies the missing piece -- the RENDERING -- so
   a future caller mounts one thing instead of two hand-authored grids.

   Usage (mount-to-open / unmount-to-close, matching the Loom's existing pickCb pattern):
     <mg-gallery-picker default-type="image"></mg-gallery-picker>
   Optional boolean attributes (all OFF by default, so the first adopter's behavior is a
   byte-for-byte match of what it already had -- no surface added silently):
     show-type          -- render the Image/Video/All type dropdown
     show-source         -- render the Source (AI-generated / imported local) dropdown
     show-upload         -- render an "Upload" button (POSTs to /api/upload, then picks it)
     show-copy-prompt    -- render a "copy prompt on pick" checkbox (persisted to localStorage)
   Events (both bubble + compose, so a React host's DOM listener sees them):
     mg-pick  -- detail: {media_id, thumb, prompt, is_video}
     mg-close -- fired on Escape / backdrop click / the X button; the host is expected to
                 unmount (or hide) the element in response -- this element does not
                 self-hide, matching the mount/unmount idiom it replaces in the Loom. */
(function () {
  'use strict';
  if (window.customElements && customElements.get('mg-gallery-picker')) return;

  function esc(s) {
    return (s == null ? '' : String(s)).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  var STYLE_ID = 'mg-gallery-picker-style';
  var CSS = [
    /* 500, not 400: the one live mount (the Loom) renders this as a root-level sibling
       OVER its .lv-overlay shell, which is also 400 -- an equal z-index only wins by DOM
       order, which is luck, not layering (same fix as the Loom's own .sb-pick-ov). 500 is
       the shell's established full-screen-modal tier: above the overlay and Deep Focus's
       veil, below mg-notify's toasts (510) and the unlock moment (520). */
    'mg-gallery-picker{position:fixed;inset:0;z-index:500;display:flex;align-items:center;',
    ' justify-content:center;padding:20px;background:rgba(6,4,16,.76);font:13px/1.4 system-ui,sans-serif;}',
    'mg-gallery-picker .mg-pk-box{width:920px;max-width:94vw;height:82vh;background:var(--mantle,#131024);',
    ' border:1px solid var(--surface1,#3a3460);border-radius:12px;padding:14px;display:flex;flex-direction:column;gap:9px;}',
    'mg-gallery-picker .mg-pk-head{display:flex;align-items:center;gap:9px;}',
    'mg-gallery-picker .mg-pk-t{font-size:15px;font-weight:700;white-space:nowrap;color:var(--text,#d6d2e2);}',
    'mg-gallery-picker .mg-pk-q{flex:1;min-width:140px;background:var(--base,#0c0a1c);border:1px solid var(--surface1,#3a3460);',
    ' border-radius:8px;padding:7px 9px;color:var(--text,#d6d2e2);font:13px/1.2 system-ui;}',
    'mg-gallery-picker .mg-pk-q:focus{outline:0;border-color:var(--accent,#b692e6);}',
    'mg-gallery-picker .mg-pk-x{background:none;border:none;color:var(--subtext,#9a93ab);font-size:24px;',
    ' line-height:1;cursor:pointer;padding:0 4px;}',
    'mg-gallery-picker .mg-pk-x:hover{color:var(--text,#d6d2e2);}',
    'mg-gallery-picker .mg-pk-filters{display:flex;gap:6px;flex-wrap:wrap;align-items:center;}',
    'mg-gallery-picker .mg-pk-filters select{background:var(--surface0,#211f3a);border:1px solid var(--surface1,#3a3460);',
    ' border-radius:6px;color:var(--text,#d6d2e2);padding:5px 9px;font-size:12px;cursor:pointer;max-width:210px;}',
    'mg-gallery-picker .mg-pk-copy{display:flex;align-items:center;gap:6px;font-size:11.5px;color:var(--subtext,#9a93ab);}',
    'mg-gallery-picker .mg-pk-upload{background:var(--surface0,#211f3a);border:1px solid var(--surface1,#3a3460);',
    ' color:var(--text,#d6d2e2);border-radius:6px;padding:5px 10px;font-size:12px;cursor:pointer;}',
    'mg-gallery-picker .mg-pk-upload:hover{border-color:var(--accent,#b692e6);}',
    'mg-gallery-picker .mg-pk-count{margin-left:auto;font-size:11px;color:var(--subtext,#9a93ab);font-family:ui-monospace,monospace;}',
    'mg-gallery-picker .mg-pk-sizer{display:flex;align-items:center;gap:5px;font-size:11px;color:var(--subtext,#9a93ab);}',
    'mg-gallery-picker .mg-pk-sizer input{width:70px;}',
    'mg-gallery-picker .mg-pk-grid{flex:1;overflow-y:auto;display:grid;',
    ' grid-template-columns:repeat(auto-fill,minmax(var(--mg-pk-tile,122px),1fr));',
    ' grid-auto-rows:var(--mg-pk-tile,122px);gap:8px;align-content:start;transition:opacity .12s;}',
    'mg-gallery-picker .mg-pk-cell{position:relative;border-radius:8px;overflow:hidden;border:1px solid var(--surface1,#3a3460);',
    ' cursor:pointer;background:var(--surface0,#211f3a);}',
    'mg-gallery-picker .mg-pk-cell:hover{border-color:var(--accent,#b692e6);}',
    'mg-gallery-picker .mg-pk-cell img{width:100%;height:100%;object-fit:cover;display:block;}',
    'mg-gallery-picker .mg-pk-vid{position:absolute;top:5px;right:5px;background:rgba(6,4,16,.72);color:var(--text,#d6d2e2);',
    ' font-size:9px;border-radius:4px;padding:1px 6px;}',
    'mg-gallery-picker .mg-pk-empty{grid-column:1/-1;color:var(--subtext,#9a93ab);text-align:center;padding:34px;font-size:13px;}',
    /* Privacy blur (audit 2026-07-21 S5): this component never carried the host page's
       body.privacy-blur rule at all -- picking through <mg-gallery-picker> (the Loom's own
       gallery picker) painted the whole catalog unblurred regardless of the toggle. body is
       real light DOM (no shadow root here), so the host page's class reaches straight in,
       same shape as .card/.pick-cell in pixai_gallery.py. */
    'body.privacy-blur mg-gallery-picker .mg-pk-cell img{filter:blur(16px);transition:filter .12s;}',
    'body.privacy-blur mg-gallery-picker .mg-pk-cell[data-nsfw="1"] img{filter:blur(28px);}',
    'body.privacy-blur mg-gallery-picker .mg-pk-cell:hover img{filter:none;}'
  ].join('');

  function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = CSS;
    (document.head || document.documentElement).appendChild(s);
  }

  var COPY_KEY = 'pick-copyprompt';   // same localStorage key the gallery's own Picker uses
  var TILE_KEY = 'mg-pk-tile';        // persisted thumbnail-size preference, shared by every picker instance

  class MgGalleryPickerEl extends HTMLElement {
    connectedCallback() {
      injectStyle();
      if (this._built) return;
      this._built = true;

      var dt = this.getAttribute('default-type');
      this._type = dt === 'video' ? 'video' : dt === 'all' ? '' : 'image';
      this._q = ''; this._collection = ''; this._rating = 0; this._sort = 'newest';
      this._showType = this.hasAttribute('show-type');
      this._showSource = this.hasAttribute('show-source');
      this._showUpload = this.hasAttribute('show-upload');
      this._showCopy = this.hasAttribute('show-copy-prompt');
      this._source = '';

      this.innerHTML = this._skeleton();
      this._q_el = this.querySelector('.mg-pk-q');
      this._grid = this.querySelector('.mg-pk-grid');
      this._empty = this.querySelector('.mg-pk-empty');
      this._count = this.querySelector('.mg-pk-count');
      this._collEl = this.querySelector('[data-f="collection"]');
      this._typeEl = this.querySelector('[data-f="type"]');
      this._sourceEl = this.querySelector('[data-f="source"]');
      this._ratingEl = this.querySelector('[data-f="rating"]');
      this._sortEl = this.querySelector('[data-f="sort"]');
      this._sizeEl = this.querySelector('.mg-pk-sizer input');
      if (this._sizeEl) {
        var savedTile = 122;
        try { savedTile = +(localStorage.getItem(TILE_KEY)) || 122; } catch (e) { /* private mode */ }
        this._sizeEl.value = savedTile;
        this.style.setProperty('--mg-pk-tile', savedTile + 'px');
        this._sizeEl.addEventListener('input', function () {
          self.style.setProperty('--mg-pk-tile', self._sizeEl.value + 'px');
          try { localStorage.setItem(TILE_KEY, self._sizeEl.value); } catch (e) { /* private mode */ }
        });
      }
      this._copyEl = this.querySelector('.mg-pk-copyck');
      if (this._copyEl) {
        try { this._copyEl.checked = localStorage.getItem(COPY_KEY) === '1'; } catch (e) { /* private mode */ }
        this._copyEl.addEventListener('change', function () {
          try { localStorage.setItem(COPY_KEY, this.checked ? '1' : '0'); } catch (e) { /* private mode */ }
        });
      }

      var self = this;
      this._core = window.PickerCore.create({
        defaultFilters: { type: this._type, collection: this._collection, source: this._source,
                          rating_min: this._rating, sort: this._sort },
        onResults: function (imgs, meta) { self._onResults(imgs, meta); },
        onCollections: function (colls) { self._onCollections(colls); },
        onError: function () { if (self._grid) self._grid.style.opacity = '1'; },
      });
      this._core.fetchCollections();
      // PickerCore.create() does NOT auto-load (by design -- see picker-core.js) -- the
      // original callers each triggered their own first search (the vanilla Picker's
      // open() calls setFilters() directly; GalleryPick's mount-time useEffect scheduled
      // one via its debounce). Do it immediately (not through _schedule()'s debounce) so
      // browse-on-open paints right away instead of waiting 160ms for nothing to change.
      this._core.setFilters({ q: this._q, collection: this._collection, type: this._type,
                              source: this._source, rating_min: this._rating, sort: this._sort });

      this._q_el.addEventListener('input', function () { self._q = self._q_el.value; self._schedule(); });
      [this._collEl, this._typeEl, this._sourceEl, this._ratingEl, this._sortEl].forEach(function (el) {
        if (el) el.addEventListener('change', function () { self._readFilters(); self._schedule(); });
      });
      this.querySelector('.mg-pk-x').addEventListener('click', function () { self._close(); });
      this.addEventListener('click', function (e) { if (e.target === self) self._close(); });
      this._grid.addEventListener('scroll', function () { self._core.onScroll(self._grid, 280); });
      this._onKey = function (e) { if (e.key === 'Escape') self._close(); };
      window.addEventListener('keydown', this._onKey);
      if (this._showUpload) {
        this._fileEl = this.querySelector('.mg-pk-file');
        this.querySelector('.mg-pk-upload').addEventListener('click', function () { self._fileEl.click(); });
        this._fileEl.addEventListener('change', function () { self._upload(); });
      }
      setTimeout(function () { self._q_el.focus(); }, 60);
    }

    disconnectedCallback() {
      if (this._core) this._core.destroy();
      if (this._onKey) window.removeEventListener('keydown', this._onKey);
    }

    _skeleton() {
      var opt = function (v, label) { return '<option value="' + esc(v) + '">' + esc(label) + '</option>'; };
      var typeSel = this._showType
        ? '<select data-f="type"><option value="">Image + video</option>' +
          '<option value="image">Images</option><option value="video">Videos</option></select>' : '';
      var sourceSel = this._showSource
        ? '<select data-f="source">' + opt('', 'Any source') + opt('api', 'Generated (AI)') +
          opt('local', 'Imported local') + '</select>' : '';
      var uploadBtn = this._showUpload
        ? '<button type="button" class="mg-pk-upload">＋ Upload</button>' +
          '<input type="file" class="mg-pk-file" accept="image/*" style="display:none">' : '';
      var copyCk = this._showCopy
        ? '<label class="mg-pk-copy"><input type="checkbox" class="mg-pk-copyck"> Copy prompt on pick</label>' : '';
      return (
        '<div class="mg-pk-box" role="dialog" aria-label="Pick from your gallery">' +
        '<div class="mg-pk-head"><span class="mg-pk-t">Pick from your gallery</span>' +
        '<input class="mg-pk-q" type="text" placeholder="Search your images…">' +
        '<button type="button" class="mg-pk-x" title="Close (Esc)">&#215;</button></div>' +
        '<div class="mg-pk-filters">' +
        '<select data-f="collection"><option value="">All collections</option></select>' +
        typeSel + sourceSel +
        '<select data-f="rating"><option value="0">Any rating</option>' +
        opt(1, '★+') + opt(2, '★★+') + opt(3, '★★★+') + opt(4, '★★★★+') + opt(5, '★★★★★') + '</select>' +
        '<select data-f="sort"><option value="newest">Newest first</option><option value="oldest">Oldest first</option></select>' +
        uploadBtn +
        '<label class="mg-pk-sizer">Size <input type="range" min="90" max="240" step="8" title="Thumbnail size"></label>' +
        '<span class="mg-pk-count"></span></div>' +
        copyCk +
        '<div class="mg-pk-grid"></div>' +
        '<div class="mg-pk-empty" style="display:none;">No matches for these filters.</div>' +
        '</div>'
      );
    }

    _readFilters() {
      this._collection = this._collEl.value;
      this._type = this._typeEl ? this._typeEl.value : this._type;
      this._source = this._sourceEl ? this._sourceEl.value : this._source;
      this._rating = +this._ratingEl.value;
      this._sort = this._sortEl.value;
    }

    _schedule() {
      // ONE combined debounce over q + every select, matching GalleryPick's existing
      // "any filter changing restarts the same 160ms timer" behavior exactly.
      clearTimeout(this._t);
      var self = this;
      this._t = setTimeout(function () {
        self._core.setFilters({ q: self._q, collection: self._collection, type: self._type,
                                source: self._source, rating_min: self._rating, sort: self._sort });
      }, 160);
    }

    _onCollections(colls) {
      var sel = this._collEl; if (!sel) return;
      var cur = sel.value;
      sel.innerHTML = '<option value="">All collections</option>' +
        (colls || []).map(function (c) { return '<option value="' + esc(c) + '">' + esc(c) + '</option>'; }).join('');
      sel.value = cur;
    }

    _onResults(imgs, meta) {
      var g = this._grid, e = this._empty, self = this;
      g.style.opacity = '1';
      if (this._count) this._count.textContent = (meta.total || 0).toLocaleString();
      if (!meta.append) g.innerHTML = '';
      if (!imgs.length && !meta.append) { e.style.display = 'block'; return; }
      e.style.display = 'none';
      imgs.forEach(function (m) {
        var c = document.createElement('div');
        c.className = 'mg-pk-cell';
        c.title = m.prompt || m.media_id;
        if (m.is_nsfw === '1') c.setAttribute('data-nsfw', '1');
        c.innerHTML = '<img loading="lazy" decoding="async" src="' + esc(m.thumb) + '" alt="">' +
          (m.is_video === '1' ? '<span class="mg-pk-vid">▶</span>' : '');
        c.addEventListener('click', function () { self._pick(m); });
        g.appendChild(c);
      });
      // if the loaded tiles don't yet overflow, there's no scrollbar to drive infinite
      // scroll -- pull one more page (core caps this so it can't runaway-load)
      this._core.maybeFillPage(g);
    }

    _pick(m) {
      if (this._copyEl && this._copyEl.checked && m.prompt) {
        try { navigator.clipboard && navigator.clipboard.writeText(m.prompt); } catch (e) { /* clipboard denied */ }
      }
      this.dispatchEvent(new CustomEvent('mg-pick', { bubbles: true, composed: true,
        detail: { media_id: m.media_id, thumb: m.thumb, prompt: m.prompt || '',
                  is_video: m.is_video === '1', duration: m.duration || '', is_nsfw: m.is_nsfw === '1' } }));
    }

    _upload() {
      var f = this._fileEl.files[0]; if (!f) return;
      var self = this;
      this._empty.textContent = 'Uploading ' + f.name + '…';
      this._empty.style.display = 'block';
      var fd = new FormData(); fd.append('file', f);
      fetch('/api/upload', { method: 'POST', body: fd }).then(function (r) { return r.json(); })
        .then(function (d) {
          self._fileEl.value = '';
          if (d.error || !d.media_id) { self._empty.textContent = '⚠ Upload failed: ' + (d.error || 'no media id'); return; }
          self._empty.style.display = 'none';
          self._pick({ media_id: d.media_id, prompt: '', thumb: URL.createObjectURL(f) });
        }).catch(function () {
          self._fileEl.value = '';
          self._empty.textContent = '⚠ Upload failed (network).';
        });
    }

    _close() {
      this.dispatchEvent(new CustomEvent('mg-close', { bubbles: true, composed: true }));
    }
  }

  window.customElements.define('mg-gallery-picker', MgGalleryPickerEl);
})();
