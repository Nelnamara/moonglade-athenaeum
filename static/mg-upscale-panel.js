/* mg-upscale-panel.js -- <mg-upscale-panel>: PixAI's Upscale, where PixAI puts it.

   Upscale is invoked on a picture that ALREADY EXISTS, not on one you are about to make.
   That distinction is the whole reason this file exists: the Generate drawer used to carry a
   three-way Off/Upscale/Hires segment, and it was wrong twice over -- it is not where PixAI
   offers it, and a drawer has no source image, so the ratio cap and the predicted output size
   were computed from the size the generation was ABOUT to be rather than from a real picture.
   The drawer now keeps only PixAI's `Enhance Details (HiRes)` BOOSTER; both real upscale
   methods live here.

   ---- THE TWO METHODS ------------------------------------------------------------------
   They are PixAI's own two radio buttons, and their `value` attributes ARE the parameter
   names -- `enlarge` is the one their UI labels "Upscale", `upscale` is the one it labels
   "Hires". They expose different controls and cost very differently:

     method            param family                                  upscaler  denoising  cost*
     ----------------  --------------------------------------------  --------  ---------  -----
     Upscale (ESRGAN)  enlarge + enlargeModel                        5 options  --         1200
     Hires             upscale + upscaleDenoisingStrength/Steps      --         yes        3700

   *measured on one source at ratio 1.4. Hires re-diffuses the image at the larger size, so it
   adds detail; ESRGAN runs an upscaler network over the finished pixels, so it adds
   resolution. That is why one is roughly 3x the other, and why the panel never presents them
   as a single "quality" slider.

   ---- THE RATIO CAP IS DYNAMIC ---------------------------------------------------------
   Not a constant. It is derived from the SOURCE's real dimensions against a per-mode
   output-pixel ceiling, so the same dialog offers 1.9 on one picture and 1.4 on another.
   Those ceilings arrive from the server in window.MG_UPSCALE.ceiling (they come from core's
   UPSCALE_PIXEL_CEILING) rather than being hand-ported here a second time -- the server
   re-derives and clamps on every price check AND submit, and a drifted copy would offer a
   ratio the server then silently pulls back with nothing on screen to say so.

   ---- WHAT IT SUBMITS ------------------------------------------------------------------
   Nothing new. An image-view upscale is an ordinary i2i generation -- `mediaId` + `strength`
   on a normal submit -- so this posts the SAME /api/price and /api/generate the drawer uses,
   with the source's own size, prompt and model. There is no /api/upscale, and deliberately
   so: a second submit path is a second place for the read-only guard, the free-card check and
   the job-tracker registration to be forgotten.

   The model is the one field that can be absent. It comes only from a per-task detail fetch,
   so a catalog that has never been swept may not have it, and a LOCALLY IMPORTED file can
   never have it -- there is no PixAI task behind it. The panel prefills from the image when
   the catalog knows it, because Hires re-diffuses and the original model keeps the style.
   When it does NOT know, it falls back to the version PixAI's own upscale submits (core's
   UPSCALE_FALLBACK_VERSION_ID, served in window.MG_UPSCALE) rather than refusing. That is
   not a guess: their dialog has no model control at all and always submits that value.
   Demanding one here was this app's own invention, and it made every locally imported file
   impossible to upscale -- Go dead behind "pick a model first", with the picker the only
   way out and no way at all if the picker failed to render. The picker is still offered as
   an override.

   Public API:
     .open(mediaIdOrRow)  -- open for a media_id (fetches its row) or a row already in hand.
     .close()
     attribute `inline`   -- render in flow (the detail page) instead of as a fixed flyout.
     event `mg-upscale`   -- {media_id, task_id} once a submit is accepted.
*/
(function () {
  'use strict';

  var STYLE_ID = 'mg-upscale-panel-style';
  var CSS = [
    'mg-upscale-panel{display:none;}',
    'mg-upscale-panel[open]{display:block;}',
    // Anchored by CSS, not by measured coordinates. The flyout is opened from the lightbox
    // bar, which is itself pinned to the top of a full-screen overlay, so "under the bar, at
    // the right edge" is a fixed, predictable spot -- and unlike a getBoundingClientRect()
    // placement it cannot be computed against a stale or slid-away rect. z-index must clear
    // the lightbox's own 300, or the panel opens BEHIND the picture it is about to upscale.
    'mg-upscale-panel:not([inline]){position:fixed;z-index:320;top:56px;right:12px;',
    ' width:min(420px,calc(100vw - 24px));max-height:calc(100vh - 72px);overflow:auto;}',
    '@media (max-width:520px){mg-upscale-panel:not([inline]){left:12px;right:12px;width:auto;}}',
    'mg-upscale-panel[inline]{margin-top:14px;}',
    // The glass face (design spec). ONE surface for both mounts -- only the anchoring
    // above differs. The rgba numbers are the spec's literal glass values, not palette.
    'mg-upscale-panel{border-radius:16px;border:1px solid rgba(182,146,230,.32);',
    ' background:linear-gradient(120deg,rgba(24,18,54,.92),rgba(14,11,32,.95));',
    ' -webkit-backdrop-filter:blur(18px) saturate(1.12);backdrop-filter:blur(18px) saturate(1.12);',
    ' box-shadow:0 24px 60px rgba(0,0,0,.55),0 0 34px rgba(182,146,230,.14);}',
    // Overlay law: both directions animate. Close is a [closing] attribute plus a 340ms
    // deferred drop of [open] in close() -- without the deferral the display:none flip
    // lands first and the exit keyframes are never seen. The flyout slides for the edge
    // it lives on; the inline mount is part of the page, so it fade-rises like one.
    '@keyframes mguIn{from{opacity:0;transform:translateX(34px) scale(.985);}to{opacity:1;transform:none;}}',
    '@keyframes mguOut{from{opacity:1;transform:none;}to{opacity:0;transform:translateX(34px) scale(.985);}}',
    'mg-upscale-panel:not([inline])[open]{animation:mguIn .4s cubic-bezier(.18,1.02,.26,1);}',
    // pointer-events:none while closing: the fade window is 340ms of a still-mounted,
    // still-[open] panel, and .mgu-go re-enables before close() on the submit path --
    // without this, a second click during the exit fade lands on a live Go and pays for
    // a SECOND generation. The instant close used to be this guard; the animation isn't
    // allowed to un-guard a spend path.
    'mg-upscale-panel:not([inline])[closing]{animation:mguOut .34s cubic-bezier(.4,0,.2,1) forwards;pointer-events:none;}',
    '@keyframes mguRise{from{opacity:0;transform:translateY(6px);}to{opacity:1;transform:none;}}',
    '@keyframes mguSink{from{opacity:1;transform:none;}to{opacity:0;transform:translateY(6px);}}',
    'mg-upscale-panel[inline][open]{animation:mguRise .22s cubic-bezier(.2,.9,.24,1);}',
    'mg-upscale-panel[inline][closing]{animation:mguSink .34s cubic-bezier(.4,0,.2,1) forwards;pointer-events:none;}',
    '.mgu-body{padding:12px 14px 14px;}',
    '.mgu-head{display:flex;align-items:center;gap:8px;padding:11px 14px 0;font-weight:600;}',
    '.mgu-head .x{margin-left:auto;background:none;border:none;color:var(--subtext);',
    ' font-size:18px;cursor:pointer;line-height:1;}',
    '.mgu-lbl{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--subtext);',
    ' margin:11px 0 4px;}',
    '.mgu-seg{display:flex;gap:6px;}',
    '.mgu-seg button{flex:1;padding:6px 8px;font-size:12px;border-radius:7px;cursor:pointer;',
    ' background:var(--surface0);color:var(--subtext);border:1px solid var(--surface1);',
    ' position:relative;z-index:1;transition:background .18s,border-color .18s,color .18s;}',
    '.mgu-seg button.on{background:var(--surface1);color:var(--text);border-color:var(--overlay0);}',
    // Tooltip law on the method hints. The segment sits at the top of the panel with the
    // whole body below it, so the tip pops DOWN into that open space, centered on its
    // button. These hints are sentences, so they take the spec's multi-line face (212px,
    // wrapping) rather than the one-line nowrap face. While a tip shows, its trigger
    // rises to the top of the component band (z 7) and the tip rides at z 5 as its
    // child -- no new band between components and overlays. No native `title`: on
    // touch, tapping a method already prints the same hint into the line below.
    '.mgu-seg button:hover,.mgu-seg button:focus-visible{z-index:7;}',
    '.mgu-tip{position:absolute;z-index:5;top:calc(100% + 8px);left:50%;width:212px;',
    ' transform:translate(-50%,-4px);opacity:0;pointer-events:none;text-align:left;',
    ' background:rgba(9,7,22,.96);border:1px solid rgba(182,146,230,.4);border-radius:8px;',
    ' padding:8px 11px;font-size:10.5px;font-weight:500;line-height:1.5;color:var(--text);',
    ' white-space:normal;box-shadow:0 10px 26px rgba(0,0,0,.6);',
    ' transition:opacity .18s cubic-bezier(.2,.9,.24,1),transform .18s cubic-bezier(.2,.9,.24,1);}',
    '.mgu-seg button:hover .mgu-tip,.mgu-seg button:focus-visible .mgu-tip{opacity:1;transform:translate(-50%,0);}',
    '.mgu-sel{width:100%;padding:6px 8px;border-radius:7px;background:var(--surface0);',
    ' color:var(--text);border:1px solid var(--surface1);font-size:12px;}',
    '.mgu-note{font-size:11px;color:var(--subtext);margin-top:4px;}',
    '.mgu-note.bad{color:var(--red);}',
    '.mgu-val{color:var(--lavender);}',
    '.mgu-dim{color:var(--overlay0);text-transform:none;}',
    // The primary action wears the skin-aware metallic accent (spec accentMetal), at the
    // spec's full-width in-panel geometry. Disabled/submitting is the spec's muted state:
    // the sheen keeps drifting, just desaturated, so "waiting" reads differently from a
    // flat dead control. mgMetal is the shared 7s drift; redefining it here is harmless
    // if another component's injected style already carries the identical keyframes.
    '@keyframes mgMetal{0%{background-position:0% 50%;}50%{background-position:100% 50%;}',
    ' 100%{background-position:0% 50%;}}',
    '.mgu-go{width:100%;margin-top:11px;padding:12px;border-radius:10px;cursor:pointer;',
    ' font-weight:800;font-size:14px;letter-spacing:.03em;white-space:nowrap;',
    ' color:color-mix(in oklab,var(--accent) 26%,#08040f);text-shadow:0 1px 0 rgba(255,255,255,.45);',
    ' border:1px solid rgba(255,255,255,.34);',
    ' background:linear-gradient(100deg,color-mix(in oklab,var(--accent) 50%,#06030d) 0%,',
    '  var(--accent) 18%,color-mix(in oklab,var(--accent) 22%,#ffffff) 34%,var(--accent) 50%,',
    '  color-mix(in oklab,var(--accent) 74%,#06030d) 68%,var(--mauve) 84%,',
    '  color-mix(in oklab,var(--accent) 50%,#06030d) 100%);',
    ' background-size:220% 100%;animation:mgMetal 7s ease-in-out infinite;',
    ' box-shadow:inset 0 1px 0 rgba(255,255,255,.72),inset 0 -3px 5px rgba(40,20,70,.5),',
    '  0 10px 26px rgba(0,0,0,.5);}',
    '.mgu-go[disabled]{filter:saturate(.6) brightness(.82);cursor:not-allowed;}',
    'mg-upscale-panel input[type=range]{width:100%;}'
  ].join('');

  function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = CSS;
    (document.head || document.documentElement).appendChild(s);
  }

  // The server hands these over so this file carries no second copy of core's numbers.
  // Absent (a page that forgot the __UPSCALE_CONST__ marker) is treated as "cannot compute a
  // cap", which disables the ratio control and says why -- never as a guessed default, which
  // would offer ratios the server then clamps with nothing on screen to explain the change.
  function consts() { return window.MG_UPSCALE || null; }

  // What to upscale WITH when the catalog cannot name the model that made the picture.
  // A model VERSION id (PixAI's own upscale submits one directly), so it goes out as
  // `version_id` -- sent as `model_id` it would enter the model->versions lookup, find
  // nothing, and come back "pick a model first". Served from core rather than retyped;
  // '' when this page never received the constants, which _canSubmit treats as "cannot
  // upscale", the same way a missing ceiling already disables the ratio.
  function fallbackVersion() { var c = consts(); return (c && c.fallbackVersionId) || ''; }

  var MODES = [
    { key: 'enlarge', label: 'Upscale',
      hint: 'Runs an upscaler network over the finished picture. Keeps it exactly as it is, ' +
            'just larger. Cheaper, and allows a bigger ratio.' },
    { key: 'upscale', label: 'Hires',
      hint: 'Re-renders the picture at the larger size, so it gains detail rather than only ' +
            'resolution. Allows a smaller ratio and costs roughly 3x.' }
  ];

  // Both mirror core.upscale_output_dims / max_upscale_ratio, which is also what the server
  // clamps to. Floor-to-a-multiple-of-8 reproduces the Python (and PixAI's own dialog)
  // exactly -- 1952, not 1960, at 1400 x 1.4.
  function outDims(w, h, r) {
    return [Math.max(64, Math.floor(w * r / 8) * 8), Math.max(64, Math.floor(h * r / 8) * 8)];
  }
  function maxRatio(w, h, mode) {
    var c = consts();
    if (!c || !c.ceiling || !c.ceiling[mode] || !w || !h) return 0;   // 0 == unknown, not 1
    for (var i = 30; i > 0; i--) {
      var r = Math.round((1 + i * 0.1) * 10) / 10;
      var o = outDims(w, h, r);
      if (o[0] * o[1] <= c.ceiling[mode]) return r;
    }
    return 1;
  }

  function h(tag, cls, txt) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }

  class MgUpscalePanelEl extends HTMLElement {
    connectedCallback() {
      if (this._built) return;
      this._built = true;
      injectStyle();
      this.mode = 'enlarge';
      this.src = null;
      this._build();
    }

    _build() {
      var self = this;
      injectStyle();

      var head = h('div', 'mgu-head');
      head.appendChild(h('span', null, '⇱ Upscale'));
      var x = h('button', 'x', '×');
      x.type = 'button';
      x.setAttribute('aria-label', 'Close');
      x.onclick = function () { self.close(); };
      if (!this.hasAttribute('inline')) head.appendChild(x);
      this.appendChild(head);

      var body = h('div', 'mgu-body');
      this.appendChild(body);

      this._source = h('div', 'mgu-note');
      body.appendChild(this._source);

      body.appendChild(h('div', 'mgu-lbl', 'Method'));
      var seg = h('div', 'mgu-seg');
      this._segBtns = {};
      MODES.forEach(function (m) {
        var b = h('button', null, m.label);
        b.type = 'button';
        // The hint rides as a styled tooltip child (tooltip law), not a native title.
        // The same text still lands in _modeHint for the selected mode -- which is
        // also what a touch user gets, since tapping IS selecting.
        b.appendChild(h('span', 'mgu-tip', m.hint));
        b.onclick = function () { self.setMode(m.key); };
        seg.appendChild(b);
        self._segBtns[m.key] = b;
      });
      body.appendChild(seg);
      this._modeHint = h('div', 'mgu-note');
      body.appendChild(this._modeHint);

      var rl = h('div', 'mgu-lbl', 'Ratio ');
      this._ratioVal = h('span', 'mgu-val', '1.2×');
      this._ratioMax = h('span', 'mgu-dim', '');
      rl.appendChild(this._ratioVal);
      rl.appendChild(document.createTextNode(' '));
      rl.appendChild(this._ratioMax);
      body.appendChild(rl);
      this._ratio = document.createElement('input');
      this._ratio.type = 'range';
      this._ratio.min = '1.1';
      this._ratio.step = '0.1';
      this._ratio.value = '1.2';
      this._ratio.oninput = function () { self._syncRatio(); self._price(); };
      body.appendChild(this._ratio);
      this._dims = h('div', 'mgu-note');
      body.appendChild(this._dims);

      // enlarge only -- PixAI's Hires has no upscaler dropdown, and that asymmetry is theirs.
      this._upWrap = h('div');
      this._upWrap.setAttribute('data-mgu', 'upscaler');
      this._upWrap.appendChild(h('div', 'mgu-lbl', 'Upscaler'));
      this._upModel = h('select', 'mgu-sel');
      this._upModel.onchange = function () { self._price(); };
      this._upWrap.appendChild(this._upModel);
      body.appendChild(this._upWrap);

      // Hires only.
      this._dnWrap = h('div');
      this._dnWrap.setAttribute('data-mgu', 'denoise');
      var dl = h('div', 'mgu-lbl', 'Denoising strength ');
      this._dnVal = h('span', 'mgu-val', '0.60');
      dl.appendChild(this._dnVal);
      dl.appendChild(h('span', 'mgu-dim', ' · PixAI: works better 0.4–0.6'));
      this._dnWrap.appendChild(dl);
      this._dn = document.createElement('input');
      this._dn.type = 'range';
      this._dn.min = '0.01';
      this._dn.max = '0.99';
      this._dn.step = '0.01';
      this._dn.value = '0.6';
      this._dn.oninput = function () {
        self._dnVal.textContent = (+self._dn.value).toFixed(2);
        self._price();
      };
      this._dnWrap.appendChild(this._dn);
      this._dnWrap.appendChild(h('div', 'mgu-lbl', 'Denoising steps'));
      this._dnSteps = h('input', 'mgu-sel');
      this._dnSteps.type = 'number';
      this._dnSteps.min = '1';
      this._dnSteps.max = '50';
      this._dnSteps.step = '1';
      this._dnSteps.value = '26';
      this._dnSteps.onchange = function () { self._price(); };
      this._dnWrap.appendChild(this._dnSteps);
      body.appendChild(this._dnWrap);

      body.appendChild(h('div', 'mgu-lbl', 'Model'));
      this._model = h('div', 'mgu-note');
      body.appendChild(this._model);
      // The fallback, and it is the SAME picker the Generate drawer opens -- not a second
      // model-choosing UI built for this panel. Mounted lazily on first use, like the
      // drawer's own ensurePickers(), so a panel opened on an image whose model is already
      // known never pays for it.
      this._pickBtn = h('button', 'mgu-sel', 'Choose a model…');
      this._pickBtn.type = 'button';
      this._pickBtn.style.cssText = 'display:none;cursor:pointer;text-align:left;';
      this._pickBtn.onclick = function () { self._openPicker(); };
      body.appendChild(this._pickBtn);
      this._pickHost = h('div', 'mgu-pick');
      this._pickHost.setAttribute('data-mgu', 'picker');
      this._pickHost.style.display = 'none';
      body.appendChild(this._pickHost);

      this._cost = document.createElement('mg-cost-badge');
      this._cost.setAttribute('hint', 'The cost appears once this image has a model.');
      this._cost.setAttribute('card-label', 'a card');
      body.appendChild(this._cost);

      this._go = h('button', 'mgu-go', 'Upscale');
      this._go.type = 'button';
      this._go.onclick = function () { self._submit(); };
      body.appendChild(this._go);

      this._msg = h('div', 'mgu-note');
      body.appendChild(this._msg);

      var c = consts();
      if (c && c.enlargeModels) {
        c.enlargeModels.forEach(function (name) {
          var o = document.createElement('option');
          o.value = name;
          o.textContent = name;
          if (name === c.defaultEnlargeModel) o.selected = true;
          self._upModel.appendChild(o);
        });
      }
    }

    // ---- state -------------------------------------------------------------------------
    setMode(mode) {
      this.mode = mode;
      var self = this;
      MODES.forEach(function (m) {
        self._segBtns[m.key].classList.toggle('on', m.key === mode);
        if (m.key === mode) self._modeHint.textContent = m.hint;
      });
      this._upWrap.style.display = (mode === 'enlarge') ? '' : 'none';
      this._dnWrap.style.display = (mode === 'upscale') ? '' : 'none';
      this._syncRatio();
      this._price();
    }

    _syncRatio() {
      var s = this.src || {};
      var w = parseInt(s.width, 10) || 0, hh = parseInt(s.height, 10) || 0;
      var mx = maxRatio(w, hh, this.mode);
      if (!mx) {
        this._ratio.disabled = true;
        this._ratioMax.textContent = '';
        this._dims.textContent = w && hh
          ? 'This page did not receive the upscale limits, so the ratio cannot be checked here.'
          : 'This image has no recorded size, so the ratio cannot be checked.';
        this._syncGo();
        return;
      }
      this._ratio.max = String(mx);
      this._ratio.disabled = (mx <= 1);
      if (+this._ratio.value > mx) this._ratio.value = String(mx);
      var r = +this._ratio.value, o = outDims(w, hh, r);
      this._ratioVal.textContent = r.toFixed(1) + '×';
      this._ratioMax.textContent = (mx <= 1) ? '' : ('· max ' + mx.toFixed(1) + '× for this picture');
      this._dims.textContent = (mx <= 1)
        ? ('This picture is already at PixAI’s ceiling for ' +
           (this.mode === 'enlarge' ? 'Upscale' : 'Hires') + '.')
        : (w + '×' + hh + ' → ' + o[0] + '×' + o[1]);
      this._syncGo();
    }

    _setMsg(t, bad) {
      this._msg.textContent = t || '';
      this._msg.classList.toggle('bad', !!bad);
    }

    // Go and the cost badge must refuse on exactly the same conditions, and they did not:
    // _price() also bails on a DISABLED ratio (a picture already at PixAI's ceiling, or a page
    // that never received the limits), so the badge stayed silent while Go still fired a real,
    // PAID /api/generate that upscaled nothing. One predicate now answers for both.
    _canSubmit() {
      var s = this.src || {};
      // A model the catalog never recorded is fine -- fallbackModel() covers it. Only a
      // page that never received the constants leaves nothing to submit with.
      return !!((s.model_id || fallbackVersion()) && !s.is_video && !this._ratio.disabled);
    }

    _syncGo() {
      this._go.disabled = !this._canSubmit();
    }

    // The model row. Prefilled when the catalog knows it; otherwise this says which case it
    // is, because the two have different answers: a never-swept catalog is fixable with one
    // command, while a locally imported file has no PixAI task and never will have a model.
    _paintModel() {
      var s = this.src || {};
      if (s.model_id) {
        this._pickBtn.style.display = 'none';
        this._pickHost.style.display = 'none';
        this._model.classList.remove('bad');
        this._model.textContent = (s.model_name || s.model_id) +
          (s.model_picked ? ' · chosen' : ' · from this image');
        this._syncGo();
        return;
      }
      // No recorded model is NOT a blocker. PixAI's own upscale dialog has no model control
      // at all -- their submit sets a fixed modelId and takes the prompt off the source's
      // original task -- so demanding one here was this app's own invention, and it made
      // every locally imported file (and anything predating a full meta sweep) impossible
      // to upscale: Go stayed dead with "pick a model first" and, if the picker failed to
      // render, no way at all to satisfy it.
      // The picker is still offered, because naming the original model IS the better answer
      // when it is known -- Hires re-diffuses, so the original keeps the style -- but it is
      // now an override, not a toll gate.
      this._pickBtn.style.display = '';
      this._model.classList.remove('bad');
      // Both cases upscale anyway, but they are not the same situation and are not collapsed
      // into one line: a never-swept catalog is fixable with one command and worth naming,
      // while a locally imported file has no PixAI task behind it and never will have a
      // model, so there is nothing to go and fill.
      this._model.textContent = s.local_import
        ? 'You imported this file, so PixAI has no record of which model made it. Upscaling ' +
          'with PixAI’s own upscale model — pick a different one if you’d rather.'
        : 'Your catalog does not know which model made this image, so it will upscale with ' +
          'PixAI’s own upscale model. Pick a different one, or fill the catalog in with:  ' +
          '--backfill-full-meta';
      this._syncGo();
    }

    _openPicker() {
      var self = this;
      if (!window.customElements.get('mg-model-picker')) {
        this._setMsg('The model picker is not loaded on this page.', true);
        return;
      }
      this._pickHost.style.display = '';
      this._pickBtn.style.display = 'none';
      if (this._picker) return;
      this._picker = document.createElement('mg-model-picker');
      this._picker.setAttribute('kind', 'base');
      this._picker.addEventListener('mg-pick', function (e) {
        var m = e.detail || {};
        if (!m.model_id) return;
        // Recorded on the source so every later price/submit carries it, and flagged as
        // CHOSEN rather than read off the image -- the panel says which it is, because
        // upscaling under a model the picture was not made with will change how it looks.
        self.src = Object.assign({}, self.src, {
          model_id: String(m.model_id),
          model_name: m.title || String(m.model_id),
          model_picked: true
        });
        self._pickHost.style.display = 'none';
        self._paintModel();
        self._price();
      });
      this._pickHost.appendChild(this._picker);
      // The panel scrolls (overflow:auto, and it is tall once the picker is in it), and the
      // Model row sits near the bottom -- so revealing the picker without moving to it puts
      // it BELOW the fold and the click reads as "nothing happened". Reported from the
      // lightbox flyout, where the panel is only 420px wide and correspondingly taller.
      // Deferred a frame so the element has been laid out before we scroll to it.
      var host = this._pickHost;
      requestAnimationFrame(function () {
        // 'start', not 'nearest'. `nearest` scrolls the MINIMUM distance, which on a short
        // window leaves the picker's top edge just inside the box and 33px of a 254px
        // control on screen -- measured. Sending it to the top of the scroll container is
        // what actually shows the thing that was just opened.
        // Scroll the panel itself rather than asking scrollIntoView to work it out. In the
        // flyout the panel IS the scroll container (position:fixed + overflow:auto), and
        // scrollIntoView moved it 24px and stopped -- 33px of a 254px control on screen,
        // measured. Setting scrollTop puts the picker's top at the panel's top outright.
        // The inline mount is not a scroll container, so it falls through to the page.
        if (self.scrollHeight > self.clientHeight + 1) {
          self.scrollTop = Math.max(0, host.offsetTop - self.offsetTop - 8);
        } else {
          try { host.scrollIntoView({ block: 'nearest' }); } catch (e) { /* older engines */ }
        }
        // Same courtesy the Generate drawer's own picker does on open: land in the search
        // box, so the next keystroke goes where it obviously should.
        var q = host.querySelector('.mg-q');
        if (q && q.focus) q.focus();
      });
    }

    // ---- open / close ------------------------------------------------------------------
    open(what) {
      var self = this;
      this.connectedCallback();
      // Re-opening mid-close must win over close()'s deferred unmount below, or the
      // panel blinks out 340ms into its own open.
      clearTimeout(this._closeT);
      this.removeAttribute('closing');
      this.setAttribute('open', '');
      this._setMsg('');
      // The same sequence token _price() carries, for a costlier reason: open on A, then
      // quickly on B, and a slow first response landing last would leave the panel -- and the
      // PAID submit it is one click from making -- bound to a picture no longer on screen.
      var mine = (this._openSeq = (this._openSeq || 0) + 1);
      var done = function (row) {
        if (mine !== self._openSeq) return;        // a later open already superseded this one
        self.src = row || null;
        if (!row) { self._setMsg('Could not load this image.', true); return; }
        if (row.is_video) {
          self._source.textContent = '';
          self._setMsg('Upscale works on images, not videos.', true);
          self._go.disabled = true;
          return;
        }
        self._source.textContent = (row.width && row.height)
          ? (row.width + '×' + row.height + ' source')
          : 'This image has no recorded size.';
        self._paintModel();
        self.setMode(self.mode || 'enlarge');
      };
      if (what && typeof what === 'object') { done(what); return this; }
      fetch('/api/image-meta/' + encodeURIComponent(String(what)))
        .then(function (r) { return r.json(); })
        .then(function (d) { done(d && !d.error ? d : null); },
              function () { done(null); });
      return this;
    }

    close() {
      var self = this;
      // The exit plays before the display:none flip: [closing] runs the reverse
      // slide+fade and the [open] drop is deferred 340ms -- the animation's own
      // length -- so the exit is ever seen at all (overlay law). Closing an already
      // closed panel stays a no-op.
      if (!this.hasAttribute('open')) return this;
      this.setAttribute('closing', '');
      clearTimeout(this._closeT);
      this._closeT = setTimeout(function () {
        self.removeAttribute('closing');
        self.removeAttribute('open');
      }, 340);
      return this;
    }

    // ---- price + submit ----------------------------------------------------------------
    // The SAME body /api/price and /api/generate already take from the drawer. An image-view
    // upscale is an ordinary i2i generation: the source's own size, prompt and model, plus
    // mediaId + strength. `strength` is not exposed as a control because PixAI's own dialog
    // has none -- it is sent at the value their captured jobs carried.
    _payload() {
      var s = this.src || {};
      var r = this._ratio.disabled ? null : +this._ratio.value;
      var body = {
        // The two sources of a model here are NOT the same kind of id, and sending them
        // in the same field is what produced "pick a model first" on a picture that
        // plainly had a model:
        //   * from the image -- the catalog's model_id is the task's submitted `modelId`,
        //     which is a model VERSION id. As `model_id` it entered the server's
        //     model->versions lookup, matched nothing, and the submit was refused.
        //   * from the picker -- a real MODEL id, which the server resolves to that
        //     model's current version, exactly as the Generate drawer does.
        // Nothing at all -> the version PixAI's own upscale submits.
        model_id: s.model_picked ? (s.model_id || '') : '',
        version_id: s.model_picked ? '' : (s.model_id || fallbackVersion()),
        prompt: s.prompt || '',
        negative: s.negative || '',
        width: parseInt(s.width, 10) || 0,
        height: parseInt(s.height, 10) || 0,
        steps: parseInt(s.steps, 10) || 25,
        cfg: parseFloat(s.cfg) || 7,
        count: 1,
        ref_media_id: s.media_id || '',
        ref_strength: 0.55,
        prompt_helper: false
      };
      if (this.mode === 'enlarge') {
        body.enlarge = r;
        body.enlarge_model = this._upModel.value || '';
      } else {
        body.upscale = r;
        body.upscale_denoise = +this._dn.value;
        body.upscale_denoise_steps = parseInt(this._dnSteps.value, 10) || 26;
      }
      return body;
    }

    _price() {
      var self = this;
      if (!this.src || !this.src.model_id || this._ratio.disabled) return;
      var mine = (this._costSeq = (this._costSeq || 0) + 1);
      // setChecking/setPrice are <mg-cost-badge>'s documented API. Passing null on a failed
      // FETCH is deliberate and is not the same as clear(): it is the badge's
      // could-not-verify state, and leaving the previous price on screen after a failed
      // check would show a number for settings that were never actually priced.
      this._cost.setChecking();
      fetch('/api/price', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this._payload())
      }).then(function (r) { return r.json(); }).then(function (d) {
        if (mine !== self._costSeq) return;          // a later edit already superseded this
        self._cost.setPrice(d);
      }, function () {
        if (mine !== self._costSeq) return;
        self._cost.setPrice(null);
      });
    }

    _submit() {
      var self = this;
      if (!this._canSubmit()) return;
      var idle = this._go.textContent;
      this._go.disabled = true;
      this._go.textContent = 'Submitting…';
      // Captured before the await for the same reason the filters panel does it: the panel
      // stays interactive while the request is in flight.
      var mid = this.src.media_id;
      fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this._payload())
      }).then(function (r) { return r.json(); }).then(function (d) {
        self._go.disabled = false;
        self._go.textContent = idle;
        if (!d || d.error || !d.task_id) {
          self._setMsg((d && d.error) || 'Could not start the upscale.', true);
          return;
        }
        self._setMsg('');
        self.close();
        self.dispatchEvent(new CustomEvent('mg-upscale', {
          bubbles: true, detail: { media_id: mid, task_id: d.task_id }
        }));
        if (window.Toast) {
          Toast.show({ kind: 'ok', title: 'Upscale started',
                       msg: 'Watch it in Activity · the result lands in your gallery' });
        }
      }, function (e) {
        self._go.disabled = false;
        self._go.textContent = idle;
        self._setMsg('Could not start the upscale: ' + ((e && e.message) || e), true);
      });
    }
  }

  if (!window.customElements.get('mg-upscale-panel')) {
    window.customElements.define('mg-upscale-panel', MgUpscalePanelEl);
  }
})();
