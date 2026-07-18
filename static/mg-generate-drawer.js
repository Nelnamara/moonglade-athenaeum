/* mg-generate-drawer.js -- a framework-neutral <mg-generate-drawer> custom element: the
   shared Generate form that BOTH the vanilla gallery and the React Loom can mount, so the
   generation UI lives in ONE place instead of two hand-duplicated ones (the two Video tabs
   shipping the same audio feature with different gaps is exactly the drift this ends).

   Third shared web component of the Option-A cohesion migration, same conventions as
   mg-model-picker.js / mg-gallery-picker.js: plain global via <script src>, no build step,
   reads the shared DESIGN_TOKENS_CSS custom properties. THE GALLERY PANEL IS THE STANDARD:
   this is a faithful extraction of the gallery drawer's Video tab (markup + Gen video JS in
   pixai_gallery.py), not a redesign. Phase 1 ships the Video tab only; Image/Edit/Reference
   join it tab by tab.

   Usage:
     <mg-generate-drawer tab="video"></mg-generate-drawer>
   The element owns the full lifecycle -- form state, live cost (/api/price), submit
   (/api/loom/generate), poll (/api/task-status), result strip -- and stays picker-agnostic:
   it never opens a picker itself. Events (all bubble + compose for React DOM listeners):
     mg-pick-request -- detail: {slot, mode, respond(media_id, thumb)}. The host opens ITS
                        picker (gallery Picker.open, Loom openPick, harness
                        <mg-gallery-picker>) and calls respond() with the choice.
     mg-submit       -- detail: {task_id, payload}. Fired the moment the server accepts;
                        hosts may ALSO track the task in their own infra (gallery Jobs
                        card, Loom pendingTaskId persistence).
     mg-result       -- detail: {media_ids, is_video, duration, paid_credit}.
     mg-error        -- detail: {error}.
   Public API: setRefs([{media_id,thumb},...]) (the lightbox/bulk "Send to Video" entry;
   >1 ref switches to multi-ref), prefill({prompt,mode,duration,audio,audio_language,
   video_model,quality}) (the Loom's shot-context entry), payload() (inspection). */
(function () {
  'use strict';
  if (window.customElements && customElements.get('mg-generate-drawer')) return;

  function esc(s) {
    return (s == null ? '' : String(s)).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  // ---- styles: the gallery's .gen-* rules for this tab, verbatim values, scoped under
  // mgd-* names so mounting inside the gallery later can't collide with its live rules ----
  var STYLE_ID = 'mg-generate-drawer-style';
  var CSS = [
    'mg-generate-drawer{display:block;font:13px/1.4 system-ui,sans-serif;color:var(--text,#d6d2e2);}',
    'mg-generate-drawer .mgd-seg{display:flex;gap:6px;margin-bottom:10px;}',
    'mg-generate-drawer .mgd-seg button{flex:1;padding:6px 0;font-size:12px;border-radius:6px;background:var(--surface0,#211f3a);color:var(--subtext,#9a93ab);border:1px solid var(--surface1,#3a3460);cursor:pointer;}',
    'mg-generate-drawer .mgd-seg button.on{background:var(--lavender,#b692e6);color:var(--base,#0c0a1c);border-color:var(--lavender,#b692e6);font-weight:600;}',
    'mg-generate-drawer .mgd-lbl{color:var(--overlay0,#6a6088);font-size:10px;text-transform:uppercase;letter-spacing:.05em;margin:10px 0 4px;}',
    'mg-generate-drawer .mgd-slots{display:flex;gap:8px;flex-wrap:wrap;}',
    'mg-generate-drawer .mgd-ce{width:100%;box-sizing:border-box;background:var(--surface0,#211f3a);border:1px solid var(--surface1,#3a3460);border-radius:6px;color:var(--text,#d6d2e2);padding:7px 9px;font-size:13px;font-family:inherit;',
    ' min-height:66px;white-space:pre-wrap;overflow-y:auto;max-height:180px;margin-top:8px;}',
    'mg-generate-drawer .mgd-ce:empty::before{content:attr(data-placeholder);color:var(--overlay0,#6a6088);pointer-events:none;}',
    'mg-generate-drawer .mgd-ce:focus{outline:none;border-color:var(--accent-soft,#4fc99a);box-shadow:0 0 0 2px rgba(79,201,154,.25);}',
    'mg-generate-drawer .mgd-chip{display:inline-flex;align-items:center;gap:4px;background:var(--surface1,#3a3460);border:1px solid var(--overlay0,#6a6088);border-radius:5px;padding:1px 6px 1px 2px;font-size:11.5px;color:var(--lavender,#b692e6);margin:0 2px;vertical-align:-3px;cursor:default;user-select:none;}',
    'mg-generate-drawer .mgd-chip img{width:16px;height:16px;border-radius:3px;object-fit:cover;}',
    'mg-generate-drawer .mgd-row{display:flex;gap:8px;margin-top:8px;}',
    'mg-generate-drawer .mgd-sel{width:100%;box-sizing:border-box;background:var(--surface0,#211f3a);border:1px solid var(--surface1,#3a3460);border-radius:6px;color:var(--text,#d6d2e2);padding:6px 8px;font-size:12.5px;}',
    'mg-generate-drawer .mgd-sel:focus{outline:none;border-color:var(--accent-soft,#4fc99a);box-shadow:0 0 0 2px rgba(79,201,154,.25);}',
    'mg-generate-drawer .mgd-check{display:flex;align-items:center;gap:7px;color:var(--subtext,#9a93ab);font-size:12px;margin-top:8px;cursor:pointer;}',
    'mg-generate-drawer .mgd-cost{margin:12px 0 8px;padding:8px 10px;border-radius:6px;background:var(--surface0,#211f3a);border:1px solid var(--surface1,#3a3460);font-size:12.5px;color:var(--text,#d6d2e2);}',
    'mg-generate-drawer .mgd-cost.free{border-color:var(--emerald,#4fc99a);color:var(--emerald,#4fc99a);}',
    'mg-generate-drawer .mgd-cost.warn{border-color:var(--red,#f38ba8);color:var(--red,#f38ba8);}',
    'mg-generate-drawer .mgd-go{width:100%;padding:9px 0;border:none;border-radius:6px;background:var(--lavender,#b692e6);color:var(--base,#0c0a1c);font-size:13.5px;font-weight:600;cursor:pointer;}',
    'mg-generate-drawer .mgd-go:hover{opacity:.9;}',
    'mg-generate-drawer .mgd-go:disabled{opacity:.4;cursor:not-allowed;}',
    'mg-generate-drawer .mgd-result{margin-top:12px;display:none;}',
    'mg-generate-drawer .mgd-result img{width:100%;border-radius:10px;display:block;margin-bottom:6px;}',
    'mg-generate-drawer .mgd-result a{color:var(--accent-soft,#4fc99a);font-size:12px;text-decoration:none;}',
    'mg-generate-drawer .mgd-moon{display:inline-block;width:15px;height:15px;border-radius:50%;background:var(--lavender,#b692e6);position:relative;overflow:hidden;vertical-align:-3px;margin-right:7px;box-shadow:0 0 9px rgba(182,146,230,.75);}',
    'mg-generate-drawer .mgd-moon::after{content:"";position:absolute;inset:0;border-radius:50%;background:var(--mantle,#131024);animation:mgd-eclipse 2.6s ease-in-out infinite;}',
    '@keyframes mgd-eclipse{0%{transform:translateX(-102%);}50%{transform:translateX(0);}100%{transform:translateX(102%);}}',
    /* the floating ref preview -- fixed so a host transform:scale() can't distort it */
    'mg-generate-drawer .mgd-preview{position:fixed;z-index:600;width:300px;background:var(--mantle,#131024);border:1px solid var(--surface1,#3a3460);border-radius:12px;box-shadow:0 22px 60px rgba(0,0,0,.6);overflow:hidden;display:none;pointer-events:none;}',
    'mg-generate-drawer .mgd-preview.open{display:block;}',
    'mg-generate-drawer .mgd-preview img{width:100%;max-height:300px;object-fit:cover;display:block;}'
  ].join('');

  function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = CSS;
    (document.head || document.documentElement).appendChild(s);
  }

  // Per-mode chrome, copied from the gallery's setVideoMode.
  var MODE_LBL = {
    i2v: 'Source image (first frame)',
    flf: 'Start & end frame',
    r2v: 'Reference images'
  };
  var MODE_PH = {
    i2v: 'Describe the motion — ‘slow cinematic pan right, gentle waves…’',
    flf: 'Describe the transition from start frame to end frame…',
    r2v: 'Type @image1 to cite a ref — it becomes a chip — ‘the girl from @image1 walks the pier…’'
  };

  var MARKUP =
    '<div class="mgd-seg" role="tablist">' +
      '<button type="button" class="on" data-vmode="i2v">First frame</button>' +
      '<button type="button" data-vmode="flf">First + last</button>' +
      '<button type="button" data-vmode="r2v">Multi-ref</button>' +
    '</div>' +
    '<div class="mgd-lbl mgd-slots-lbl">Source image (first frame)</div>' +
    '<div class="mgd-slots"></div>' +
    '<div class="mgd-ce" contenteditable="true" data-placeholder=""></div>' +
    '<div class="mgd-row">' +
      '<div style="flex:1.4;"><div class="mgd-lbl">Model</div>' +
        '<select class="mgd-sel mgd-model">' +
          '<option value="v4.0.1" selected>V4.0 Lite Preview &middot; multi-ref &middot; 15s &middot; audio</option>' +
          '<option value="v4.0">V4.0 Preview (full) &middot; top quality &middot; pricier</option>' +
          '<option value="v3.2">V3.2 &middot; audio &middot; prompt-following</option>' +
          '<option value="v3.0.2">V3.0 Lite &middot; complex motion</option>' +
          '<option value="v3.0">V3.0 &middot; high consistency</option>' +
        '</select></div>' +
      '<div style="flex:1;"><div class="mgd-lbl">Duration (s)</div>' +
        '<select class="mgd-sel mgd-dur"><option>5</option><option>6</option><option>10</option><option>15</option></select></div>' +
    '</div>' +
    '<div class="mgd-row">' +
      '<div class="mgd-cam-wrap" style="flex:1;"><div class="mgd-lbl">Camera</div>' +
        '<select class="mgd-sel mgd-cam">' +
          '<option value="unset">Auto</option><option value="zoom">Zoom</option>' +
          '<option value="pan">Pan</option><option value="tilt">Tilt</option>' +
          '<option value="roll">Roll</option><option value="horizontal">Horizontal</option>' +
          '<option value="vertical-pan">Vertical pan</option>' +
        '</select></div>' +
      '<div style="flex:1;"><div class="mgd-lbl">Priority</div>' +
        '<select class="mgd-sel mgd-quality"><option value="professional">Professional</option><option value="basic">Basic (cheaper)</option></select></div>' +
    '</div>' +
    '<label class="mgd-check"><input type="checkbox" class="mgd-audio"> Generate audio <span style="color:var(--overlay0,#6a6088);">(V4.0 / V3.2 &middot; spoken lines in the prompt become voiceover)</span></label>' +
    '<div class="mgd-lang-wrap" style="display:none;margin-top:4px;"><div class="mgd-lbl">Audio language</div>' +
      '<select class="mgd-sel mgd-lang"><option value="english">English</option><option value="japanese">Japanese</option><option value="chinese">Chinese</option><option value="korean">Korean</option><option value="none">SE only (no dialogue)</option></select></div>' +
    '<div class="mgd-cost" style="margin-top:10px;">Pick a source image to see the cost.</div>' +
    '<button type="button" class="mgd-go">Generate video</button>' +
    '<div class="mgd-result"></div>' +
    '<div class="mgd-preview" aria-hidden="true"></div>';

  class MgGenerateDrawerEl extends HTMLElement {
    connectedCallback() {
      injectStyle();
      if (this._built) return;
      this._built = true;
      this._mode = 'i2v';
      this._slots = [null];
      this._costSeq = 0;
      this._costTimer = null;
      this._chipTimer = null;
      this._pollTimer = null;
      this.innerHTML = MARKUP;
      this._slotsLbl = this.querySelector('.mgd-slots-lbl');
      this._slotsWrap = this.querySelector('.mgd-slots');
      this._ce = this.querySelector('.mgd-ce');
      this._model = this.querySelector('.mgd-model');
      this._dur = this.querySelector('.mgd-dur');
      this._camWrap = this.querySelector('.mgd-cam-wrap');
      this._cam = this.querySelector('.mgd-cam');
      this._quality = this.querySelector('.mgd-quality');
      this._audio = this.querySelector('.mgd-audio');
      this._langWrap = this.querySelector('.mgd-lang-wrap');
      this._lang = this.querySelector('.mgd-lang');
      this._cost = this.querySelector('.mgd-cost');
      this._go = this.querySelector('.mgd-go');
      this._result = this.querySelector('.mgd-result');
      this._preview = this.querySelector('.mgd-preview');
      var self = this;
      this.querySelectorAll('.mgd-seg button').forEach(function (b) {
        b.addEventListener('click', function () { self._setMode(b.getAttribute('data-vmode')); });
      });
      this._ce.addEventListener('input', function () {
        clearTimeout(self._chipTimer);
        self._chipTimer = setTimeout(function () { self._chipify(false); self._debCost(); }, 300);
      });
      this._ce.addEventListener('blur', function () { self._chipify(true); });
      this._model.addEventListener('change', function () { self._debCost(); });
      this._dur.addEventListener('change', function () { self._debCost(); });
      this._audio.addEventListener('change', function () { self._audioToggle(); });
      this._go.addEventListener('click', function () { self._generate(); });
      this._setMode('i2v');
    }

    disconnectedCallback() {
      clearTimeout(this._costTimer);
      clearTimeout(this._chipTimer);
      clearTimeout(this._pollTimer);
    }

    // ---- mode + slots (gallery setVideoMode / renderVideoSlots, verbatim behavior) ----
    _setMode(m) {
      this._mode = m;
      var self = this;
      this.querySelectorAll('.mgd-seg button').forEach(function (b) {
        b.classList.toggle('on', b.getAttribute('data-vmode') === m);
      });
      if (m === 'i2v') this._slots = [this._slots[0] || null];
      else if (m === 'flf') this._slots = [this._slots[0] || null, this._slots[1] || null];
      else if (!this._slots.length) this._slots = [null];
      this._slotsLbl.textContent = MODE_LBL[m];
      this._ce.setAttribute('data-placeholder', MODE_PH[m]);
      this._camWrap.style.visibility = (m === 'r2v') ? 'hidden' : 'visible';
      this._renderSlots();
    }

    _renderSlots() {
      var wrap = this._slotsWrap, self = this;
      wrap.innerHTML = '';
      var refN = 0;
      this._slots.forEach(function (s, i) {
        var box = document.createElement('div');
        box.style.cssText = 'position:relative;width:78px;height:78px;border-radius:8px;border:1px solid var(--surface1,#3a3460);background:var(--surface0,#211f3a);cursor:pointer;overflow:hidden;display:grid;place-items:center;color:var(--subtext,#9a93ab);font-size:11px;text-align:center;';
        if (s) {
          refN++;
          var tag = (self._mode === 'flf' ? (i === 0 ? 'start' : 'end') : '@image' + refN);
          box.innerHTML = '<img src="' + esc(s.thumb) + '" style="width:100%;height:100%;object-fit:cover;">' +
            '<span style="position:absolute;left:3px;bottom:3px;background:rgba(21,19,28,.85);color:var(--lavender,#b692e6);font-size:9.5px;padding:1px 5px;border-radius:4px;">' + tag + '</span>' +
            '<button type="button" class="mgd-vs-x" style="position:absolute;top:2px;right:2px;width:17px;height:17px;border-radius:50%;border:none;background:rgba(21,19,28,.85);color:var(--subtext,#9a93ab);font-size:11px;line-height:1;cursor:pointer;padding:0;">&times;</button>';
          box.querySelector('.mgd-vs-x').onclick = function (ev) {
            ev.stopPropagation(); self._hidePreview();
            if (self._mode === 'r2v') { self._slots.splice(i, 1); if (!self._slots.length) self._slots = [null]; }
            else self._slots[i] = null;
            self._renderSlots();
          };
          box.onmouseenter = function () { self._showPreview(s.media_id, box); };
          box.onmouseleave = function () { self._hidePreview(); };
        } else {
          box.textContent = (self._mode === 'flf' ? (i === 0 ? '+ start' : '+ end') : '+ pick');
        }
        box.onclick = function () { self._requestPick(i); };
        wrap.appendChild(box);
      });
      if (this._mode === 'r2v' && this._slots.length < 9) {
        var add = document.createElement('button');
        add.type = 'button'; add.textContent = '+ add';
        add.style.cssText = 'width:78px;height:78px;border-radius:8px;border:1px dashed var(--surface1,#3a3460);background:transparent;color:var(--subtext,#9a93ab);cursor:pointer;font-size:11px;';
        add.onclick = function () { self._slots.push(null); self._renderSlots(); };
        wrap.appendChild(add);
      }
      this._debCost();
    }

    // Picker-agnostic: ask the host to pick. The host calls respond() with its choice.
    _requestPick(i) {
      var self = this;
      this.dispatchEvent(new CustomEvent('mg-pick-request', {
        bubbles: true, composed: true,
        detail: {
          slot: i, mode: this._mode,
          respond: function (media_id, thumb) {
            if (!media_id) return;
            self._slots[i] = { media_id: String(media_id), thumb: thumb || ('/thumbs/' + media_id + '.jpg') };
            self._renderSlots();
          }
        }
      }));
    }

    // ---- @image chips in the contenteditable prompt (gallery vpChipify family) ----
    _refMap() {
      var map = {}, n = 0;
      this._slots.forEach(function (s) {
        if (s && s.media_id) { n++; map['@image' + n] = { thumb: s.thumb, mid: s.media_id }; }
      });
      return map;
    }

    _makeChip(tag, info) {
      var self = this;
      var c = document.createElement('span');
      c.className = 'mgd-chip'; c.contentEditable = 'false';
      c.setAttribute('data-ref', tag);
      c.innerHTML = (info && info.thumb ? '<img src="' + esc(info.thumb) + '" alt="">' : '') + tag;
      if (info && info.mid) {
        c.onmouseenter = function () { self._showPreview(info.mid, c); };
        c.onmouseleave = function () { self._hidePreview(); };
      }
      return c;
    }

    _chipify(final) {
      var ce = this._ce, self = this;
      var map = this._refMap(), sel = window.getSelection();
      var walker = document.createTreeWalker(ce, NodeFilter.SHOW_TEXT), nodes = [], tn;
      while ((tn = walker.nextNode())) nodes.push(tn);
      var re = /@image\d+/g;
      nodes.forEach(function (node) {
        var t = node.nodeValue, m, found = [];
        re.lastIndex = 0;
        while ((m = re.exec(t)) !== null) {
          if (!map[m[0]]) continue;
          if (!final && m.index + m[0].length === t.length) continue;  // still typing at the end
          found.push({ i: m.index, tag: m[0] });
        }
        if (!found.length) return;
        var caretHere = sel.rangeCount && sel.getRangeAt(0).startContainer === node;
        var frag = document.createDocumentFragment(), pos = 0;
        found.forEach(function (f) {
          if (f.i > pos) frag.appendChild(document.createTextNode(t.slice(pos, f.i)));
          frag.appendChild(self._makeChip(f.tag, map[f.tag]));
          pos = f.i + f.tag.length;
        });
        var tail = document.createTextNode(t.slice(pos));
        frag.appendChild(tail);
        node.parentNode.replaceChild(frag, node);
        if (caretHere) {
          var r = document.createRange();
          r.setStart(tail, tail.length); r.collapse(true);
          sel.removeAllRanges(); sel.addRange(r);
        }
      });
    }

    _promptText() {
      var out = '';
      (function walk(n) {
        n.childNodes.forEach(function (c) {
          if (c.nodeType === 3) out += c.nodeValue;
          else if (c.classList && c.classList.contains('mgd-chip')) out += c.getAttribute('data-ref');
          else if (c.nodeName === 'BR') out += '\n';
          else walk(c);
        });
      })(this._ce);
      return out.replace(/\u00a0/g, ' ').trim();
    }

    _promptSet(v) {
      this._ce.textContent = v || '';
      this._chipify(true);
      this._debCost();
    }

    // ---- payload + live cost (gallery videoPayload / videoCostNow, same keys/strings) ----
    payload() {
      return {
        mode: this._mode.toUpperCase(),
        prompt: this._promptText(),
        images: this._slots.filter(function (s) { return s && s.media_id; }).map(function (s) { return s.media_id; }),
        duration: +this._dur.value,
        audio: this._audio.checked,
        video_model: this._model.value,
        camera_movement: (this._mode !== 'r2v' ? this._cam.value : ''),
        quality: this._quality.value,
        audio_language: this._lang.value
      };
    }

    _audioToggle() {
      this._langWrap.style.display = this._audio.checked ? '' : 'none';
      this._debCost();
    }

    _debCost() {
      clearTimeout(this._costTimer);
      var self = this;
      this._costTimer = setTimeout(function () { self._costNow(); }, 250);
    }

    _costNow() {
      var cost = this._cost, self = this;
      var p = this.payload();
      if (!p.images.length) { cost.className = 'mgd-cost'; cost.textContent = 'Pick a source image to see the cost.'; return; }
      cost.className = 'mgd-cost'; cost.textContent = 'Checking cost…';
      var mine = ++this._costSeq;
      fetch('/api/price', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(p) })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (mine !== self._costSeq) return;
          if (d.note) { cost.textContent = d.note; return; }
          if (d.error) { cost.textContent = '⚠ ' + d.error; return; }
          var n = d.cost != null ? d.cost.toLocaleString() : '?';
          if (d.free) {
            cost.className = 'mgd-cost free';
            cost.textContent = '🎫 FREE — ' + (d.card_name || 'a video card') + ' covers this' + (d.cards ? ' (' + d.cards + ' left)' : '') + ' · saves ~' + n + ' credits';
          } else {
            var big = (p.video_model === 'v4.0');   // v4.0 full is ~2.5x Lite (14k/s -> 210k for 15s)
            cost.className = 'mgd-cost' + (big ? ' warn' : '');
            cost.textContent = (big ? '⚠ V4.0 full — ~2.5× Lite · ' : '') + '≈ ' + n + ' credits';
          }
        }).catch(function () { if (mine !== self._costSeq) return; cost.textContent = 'cost unavailable'; });
    }

    // ---- submit -> poll -> result (the gallery runTask flow, self-contained) ----
    _generate() {
      var self = this, res = this._result, p = this.payload();
      if (!p.images.length) {
        res.style.display = 'block';
        res.innerHTML = '<span style="color:var(--red,#f38ba8);font-size:12px;">Pick a source image first.</span>';
        return;
      }
      res.style.display = 'block';
      res.innerHTML = '<span class="mgd-moon"></span><span style="color:var(--subtext,#9a93ab);font-size:12px;">Submitting…</span>';
      this._go.disabled = true; this._go.textContent = 'Rendering…';
      function done() { self._go.disabled = false; self._go.textContent = 'Generate video'; }
      fetch('/api/loom/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(p) })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.error || !d.task_id) { done(); self._renderError(d.error || 'submit failed'); return; }
          self.dispatchEvent(new CustomEvent('mg-submit', { bubbles: true, composed: true, detail: { task_id: d.task_id, payload: p } }));
          res.innerHTML = '<span class="mgd-moon"></span><span style="color:var(--subtext,#9a93ab);font-size:12px;">Queued — running…</span>';
          self._poll(d.task_id, done);
        })
        .catch(function () { done(); self._renderError('network error'); });
    }

    _poll(taskId, done) {
      var self = this, res = this._result;
      clearTimeout(this._pollTimer);
      this._pollTimer = setTimeout(function tick() {
        fetch('/api/task-status?task_id=' + encodeURIComponent(taskId))
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (!self.isConnected) return;
            if (d.phase === 'done') {
              done();
              self._renderResult(d);
              self.dispatchEvent(new CustomEvent('mg-result', {
                bubbles: true, composed: true,
                detail: { media_ids: d.media_ids || [], is_video: !!d.is_video, duration: d.duration, paid_credit: d.paid_credit }
              }));
            } else if (d.phase === 'failed') {
              done();
              self._renderError(d.error || ('task ' + (d.status || 'failed')));
            } else {
              res.innerHTML = '<span class="mgd-moon"></span><span style="color:var(--subtext,#9a93ab);font-size:12px;">Rendering under the eclipse… (task ' + esc(String(taskId).slice(-6)) + ')</span>';
              self._pollTimer = setTimeout(tick, 2000);
            }
          })
          .catch(function () {
            // transient poll blip: the task is still running server-side -- keep polling
            if (self.isConnected) self._pollTimer = setTimeout(tick, 2000);
          });
      }, 2000);
    }

    _renderError(msg) {
      var res = this._result;
      res.style.display = 'block';
      res.innerHTML = '<span style="color:var(--red,#f38ba8);font-size:12px;">' + esc(msg) + '</span>';
      this.dispatchEvent(new CustomEvent('mg-error', { bubbles: true, composed: true, detail: { error: msg } }));
    }

    _renderResult(d) {
      var res = this._result;
      res.style.display = 'block';
      var ids = d.media_ids || [];
      var cost = d.paid_credit === 0 ? 'free (card used)' : ((d.paid_credit || 0).toLocaleString() + ' credits');
      var html = '<div style="color:var(--emerald,#4fc99a);font-size:12px;margin-bottom:6px;">✓ Rendered — ' + cost + '. Added to your gallery.</div>';
      ids.forEach(function (mid) {
        html += '<a href="/image/' + esc(mid) + '"><img src="/thumbs/' + esc(mid) + '.jpg" alt="result" loading="lazy"></a>';
      });
      res.innerHTML = html;
    }

    // ---- floating ref preview (own element; no host singleton coupling) ----
    _showPreview(mid, anchor) {
      var p = this._preview; if (!p || !mid) return;
      p.innerHTML = '<img src="/thumbs/' + esc(mid) + '.jpg" alt="">';
      p.classList.add('open'); p.setAttribute('aria-hidden', 'false');
      var r = anchor.getBoundingClientRect(), w = 300, gap = 12, x;
      x = r.right + gap;
      if (x + w > window.innerWidth - 8) x = Math.max(8, r.left - w - gap);
      var y = Math.max(8, Math.min(r.top - 10, window.innerHeight - 380));
      p.style.left = x + 'px';
      p.style.top = y + 'px';
    }

    _hidePreview() {
      var p = this._preview;
      if (p) { p.classList.remove('open'); p.setAttribute('aria-hidden', 'true'); }
    }

    // ---- public host API ----
    // The lightbox / bulk-bar "Send to Video" entry (gallery addVideoRefs, sans host chrome).
    setRefs(refs) {
      refs = (refs || []).slice(0, 9);
      if (!refs.length) return;
      if (refs.length > 1) this._setMode('r2v');
      var slots = refs.map(function (r) { return { media_id: String(r.media_id || r.mid), thumb: r.thumb }; });
      if (refs.length > 1) { this._slots = slots; }
      else if (this._mode === 'r2v') { this._slots = [slots[0]]; }
      else { this._slots[0] = slots[0]; }
      this._renderSlots();
    }

    // Shot-context prefill for the Loom (and any host): only the keys present are applied.
    prefill(o) {
      o = o || {};
      if (o.mode && MODE_LBL[String(o.mode).toLowerCase()]) this._setMode(String(o.mode).toLowerCase());
      if (o.video_model != null) this._model.value = o.video_model;
      if (o.duration != null) this._dur.value = String(o.duration);
      if (o.quality != null) this._quality.value = o.quality;
      if (o.audio != null) { this._audio.checked = !!o.audio; this._audioToggle(); }
      if (o.audio_language != null) this._lang.value = o.audio_language;
      if (o.refs) this.setRefs(o.refs);
      if (o.prompt != null) this._promptSet(o.prompt);
      this._debCost();
    }

    get mode() { return this._mode; }
  }

  window.customElements.define('mg-generate-drawer', MgGenerateDrawerEl);
})();
