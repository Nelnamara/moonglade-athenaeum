/* mg-generate-drawer.js -- a framework-neutral <mg-generate-drawer> custom element: the
   shared Generate form that BOTH the vanilla gallery and the React Loom can mount, so the
   generation UI lives in ONE place instead of two hand-duplicated ones (the two Video tabs
   shipping the same audio feature with different gaps is exactly the drift this ends).

   Third shared web component of the Option-A cohesion migration, same conventions as
   mg-model-picker.js / mg-gallery-picker.js: plain global via <script src>, no build step,
   reads the shared DESIGN_TOKENS_CSS custom properties. Built against the owner-locked
   "Video Tab -- Full Parity Mockup v1" (docs/STATE.md artifact ledger): full PixAI Multi-ref
   parity (6 image + 3 video + 1 audio ref slots), negative prompt, Channel (Normal/Enhanced,
   PixAI's own wording), and the full 7-model roster with capability gating.

   Usage:
     <mg-generate-drawer tab="video"></mg-generate-drawer>
   The element owns the full lifecycle -- form state, live cost (/api/price), submit
   (/api/loom/generate), poll (/api/task-status), result strip -- and stays picker-agnostic
   for gallery picks: it never opens a gallery picker itself. Audio refs are the one
   exception -- there's no gallery/catalog concept for raw audio files, so the audio slot
   uploads directly to /api/upload (same free 3-step S3 handshake every other upload path
   uses), no host mediation needed.
   Events (all bubble + compose for React DOM listeners):
     mg-pick-request -- detail: {slot, bank, mode, kind, respond(media_id, thumb)}. The host
                        opens ITS picker (gallery Picker.open, Loom openPick, harness
                        <mg-gallery-picker>) filtered to `kind` ('image'|'video') and calls
                        respond() with the choice. `bank` distinguishes which slot array the
                        pick is for ('primary'|'vid') when a host cares.
     mg-submit       -- detail: {task_id, payload}. Fired the moment the server accepts;
                        hosts may ALSO track the task in their own infra (gallery Jobs
                        card, Loom pendingTaskId persistence).
     mg-result       -- detail: {media_ids, is_video, duration, paid_credit}.
     mg-error        -- detail: {error}.
     mg-dirty        -- fired the moment the user TYPES in the prompt box (not on a
                        programmatic prefill()). Hosts that auto-recompose the prompt from
                        other state (the Loom's shot fields) use this to know a hand-edit
                        is in progress and should win over the next auto re-sync.
     mg-prompt-commit -- detail: {text}. Fired once per edit "session" -- 300ms after the
                        last keystroke, or immediately on blur, whichever comes first.
                        Distinct from mg-dirty (which fires every keystroke for cheap live
                        tracking): a host that wants to DURABLY PERSIST a hand-edit (not
                        just know one is in progress) listens for this instead.
     mg-mode-commit  -- detail: {vmode}. Fired ONLY from a direct user click on one of this
                        drawer's own mode-segment buttons -- never from prefill() or
                        _applyModelGating() re-asserting/auto-switching the mode internally,
                        which would create a host<->drawer sync loop. vmode is this drawer's
                        own 3-value vocabulary ('i2v'|'flf'|'r2v'); a host that maps this to a
                        richer mode concept (e.g. the Loom's 4-value I2V/R2V/V2V/FLF card
                        field) owns that mapping entirely -- this drawer has no concept of the
                        host's mode values at all (stays host-agnostic, per this file's own
                        contract).
   Public API:
     setRefs([{media_id,thumb},...]) -- the lightbox/bulk "Send to Video" entry, image refs
       only (unchanged from Phase 1); >1 ref switches to multi-ref.
     prefill({prompt,mode,duration,audio,audio_language,video_model,quality,negative,
       is_private,images,video_refs,audio_ref}) -- the Loom's shot-context entry. images/
       video_refs are arrays of {media_id,thumb}; audio_ref is {media_id,filename}|null.
     payload() -- inspection; the exact object POSTed to /api/price and /api/loom/generate.
     flushPromptEdit() -- synchronously commits a pending (not-yet-debounced) hand-edit and
       returns its text, or null if nothing was pending. For a host about to overwrite this
       drawer with different content, or about to read committed state faster than the
       300ms debounce would otherwise allow.
     setBusy(bool) -- disables/enables the Go button for a generation this drawer did NOT
       itself start (e.g. a batch run elsewhere submitted the active shot). No-ops while
       this drawer's OWN submit/poll is in flight -- that lifecycle owns the button then. */
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
    'mg-generate-drawer .mgd-lbl:first-child{margin-top:0;}',
    'mg-generate-drawer .mgd-note{text-transform:none;letter-spacing:0;color:var(--overlay0,#6a6088);}',
    'mg-generate-drawer .mgd-slots{display:flex;gap:8px;flex-wrap:wrap;}',
    'mg-generate-drawer .mgd-ce{width:100%;box-sizing:border-box;background:var(--surface0,#211f3a);border:1px solid var(--surface1,#3a3460);border-radius:6px;color:var(--text,#d6d2e2);padding:7px 9px;font-size:13px;font-family:inherit;',
    ' min-height:66px;white-space:pre-wrap;overflow-y:auto;max-height:180px;margin-top:8px;}',
    'mg-generate-drawer .mgd-ce:empty::before{content:attr(data-placeholder);color:var(--overlay0,#6a6088);pointer-events:none;}',
    'mg-generate-drawer .mgd-ce:focus{outline:none;border-color:var(--accent-soft,#4fc99a);box-shadow:0 0 0 2px rgba(79,201,154,.25);}',
    'mg-generate-drawer .mgd-neg{width:100%;box-sizing:border-box;background:var(--surface0,#211f3a);border:1px solid var(--surface1,#3a3460);border-radius:6px;color:var(--subtext,#9a93ab);padding:6px 9px;font-size:12.5px;font-family:inherit;min-height:32px;resize:vertical;margin-top:6px;}',
    'mg-generate-drawer .mgd-neg:focus{outline:none;border-color:var(--accent-soft,#4fc99a);color:var(--text,#d6d2e2);}',
    'mg-generate-drawer .mgd-chip{display:inline-flex;align-items:center;gap:4px;background:var(--surface1,#3a3460);border:1px solid var(--overlay0,#6a6088);border-radius:5px;padding:1px 6px 1px 2px;font-size:11.5px;color:var(--lavender,#b692e6);margin:0 2px;vertical-align:-3px;cursor:default;user-select:none;}',
    'mg-generate-drawer .mgd-chip img{width:16px;height:16px;border-radius:3px;object-fit:cover;}',
    'mg-generate-drawer .mgd-row{display:flex;gap:8px;margin-top:8px;}',
    'mg-generate-drawer .mgd-row>div{flex:1;}',
    'mg-generate-drawer .mgd-row>div.grow{flex:1.4;}',
    'mg-generate-drawer .mgd-sel{width:100%;box-sizing:border-box;background:var(--surface0,#211f3a);border:1px solid var(--surface1,#3a3460);border-radius:6px;color:var(--text,#d6d2e2);padding:6px 8px;font-size:12.5px;}',
    'mg-generate-drawer .mgd-sel:focus{outline:none;border-color:var(--accent-soft,#4fc99a);box-shadow:0 0 0 2px rgba(79,201,154,.25);}',
    'mg-generate-drawer .mgd-sel:disabled{color:var(--overlay0,#6a6088);}',
    /* Loom mount only: Camera + Basic/Professional are each already owned by an existing
       Loom control (the shot Camera field; the top-strip Draft toggle) -- host sets
       data-loom-ctx on the element itself to hide the shared drawer's own copies rather
       than show two controls for the same setting. Gallery/harness mounts are unaffected. */
    'mg-generate-drawer[data-loom-ctx] .mgd-cam-wrap,mg-generate-drawer[data-loom-ctx] .mgd-quality-wrap{display:none;}',
    'mg-generate-drawer .mgd-caps{display:flex;gap:5px;flex-wrap:wrap;margin-top:5px;}',
    'mg-generate-drawer .mgd-cap{font-size:9.5px;background:var(--surface0,#211f3a);border:1px solid var(--surface1,#3a3460);color:var(--subtext,#9a93ab);padding:1px 7px;border-radius:5px;}',
    'mg-generate-drawer .mgd-cap.hot{color:var(--emerald,#4fc99a);border-color:var(--emerald,#4fc99a);}',
    'mg-generate-drawer .mgd-cap.crown{color:#e08fd6;border-color:#e08fd6;}',
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
    'mg-generate-drawer .mgd-vidbadge{position:absolute;top:2px;left:2px;background:rgba(21,19,28,.88);color:var(--text,#d6d2e2);font-size:9px;padding:0 4px;border-radius:4px;line-height:1.5;}',
    'mg-generate-drawer .mgd-audiorow{margin-top:6px;}',
    'mg-generate-drawer .mgd-audiochip{display:inline-flex;align-items:center;gap:7px;background:var(--surface0,#211f3a);border:1px solid var(--surface1,#3a3460);border-radius:6px;padding:5px 10px;font-size:11.5px;color:var(--text,#d6d2e2);}',
    'mg-generate-drawer .mgd-audiochip button{background:none;border:none;color:var(--subtext,#9a93ab);cursor:pointer;font-size:13px;padding:0;line-height:1;}',
    'mg-generate-drawer .mgd-audioadd{background:var(--surface0,#211f3a);border:1px dashed var(--surface1,#3a3460);color:var(--subtext,#9a93ab);border-radius:6px;padding:6px 14px;font-size:11.5px;cursor:pointer;}',
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

  // Per-mode chrome, copied from the gallery's setVideoMode. i2v/flf's primary slot is
  // always the Start Frame -- flf's End Frame (Optional) renders as its own labeled block
  // (see .mgd-endlbl/.mgd-endslots) since PixAI shows them as two separately-labeled boxes,
  // not one combined "start & end" section. Exact PixAI wording, title case, confirmed on
  // V3.0 Lite's and V3.2's real panels (private/GENERATOR_SURFACE.md, 2026-07-18).
  var MODE_LBL = {
    i2v: 'Start Frame',
    flf: 'Start Frame',
    r2v: 'Image references'
  };
  var MODE_PH = {
    i2v: 'Describe the motion — ‘slow cinematic pan right, gentle waves…’',
    flf: 'Describe the transition from start frame to end frame…',
    r2v: 'Type @image1 / @video1 / @audio1 to cite a ref — it becomes a chip — ‘the girl from @image1 dances to @audio1…’'
  };

  // Full site roster, in PixAI's real model-picker order -- newest first, V2.7 last
  // (private/GENERATOR_SURFACE.md per-model matrix, owner screenshots 2026-07-18; our
  // V4.0 pair was previously reversed). Only the five with a real numeric modelId in
  // VIDEO_MODELS (pixai_gallery_backup.py) are selectable -- PixAI resolves "Unknown or
  // removed model" without one, and no free card can match. The other two ship
  // visible-but-disabled so the roster is honest about what exists without offering a
  // guaranteed-fail submit; enable once each gets one --dump-params capture (free,
  // read-only) off a real recovered task.
  var MODELS = [
    { value: 'v4.0', label: 'V4.0 Preview', caps: ['multi-ref', 'audio', '15s', 'top quality', '~2.5× cost'] },
    { value: 'v4.0.1', label: 'V4.0 Lite Preview', caps: ['multi-ref', 'audio', '15s', 'end-frame'] },
    { value: 'v3.2', label: 'V3.2', caps: ['audio', 'prompt-following'] },
    { value: 'v3.0.2', label: 'V3.0 Lite', caps: ['complex motion', 'cheap'] },
    { value: 'v3.0', label: 'V3.0 (High Consistency)', caps: ['high-consistency', 'action presets', 'start/end'] },
    { value: 'v3.0f', label: 'V3.0 Flash', caps: ['multi-shot'], disabled: true },
    { value: 'v2.7', label: 'V2.7 (High Dynamics)', caps: ['camera moves', 'dynamic'], disabled: true }
  ];

  // Per-model reference/frame-mode gating -- which of our i2v/flf/r2v vmode buttons a given
  // model actually supports. Confirmed matrix, all 7 models (private/GENERATOR_SURFACE.md,
  // owner screenshots 2026-07-18): Multi-Reference (r2v) is exclusive to the V4.0 pair; the
  // First+Last tier (flf) is available on the three V3.0-generation models; V2.7 and V3.0
  // Flash offer First Frame only. Leaving End Frame empty in flf mode already submits as
  // first-frame-only (see _hasAnyRef), matching PixAI's own "End Frame (Optional)" behavior.
  var MODEL_VMODES = {
    'v4.0': ['i2v', 'flf', 'r2v'],
    'v4.0.1': ['i2v', 'flf', 'r2v'],
    'v3.2': ['i2v', 'flf'],
    'v3.0.2': ['i2v', 'flf'],
    'v3.0': ['i2v', 'flf'],
    'v3.0f': ['i2v'],
    'v2.7': ['i2v']
  };

  // Matches the server's VIDEO_DURATIONS / _snap_video_duration exactly -- prefill() snaps
  // to the nearest of these so an out-of-range shot duration (e.g. a hand-typed "8") can
  // never leave the <select> on a value with no matching <option>, which resolves to an
  // empty string and silently submits duration:0. Found live 2026-07-18 wiring the Loom
  // mount: the seed project's example shot has duration:8, composed correctly into the
  // prompt text ("~8s") but breaking the (fixed 5/6/10/15) duration selector.
  var DURATIONS = [5, 6, 10, 15];
  function snapDuration(d) {
    d = Number(d);
    if (!isFinite(d)) return 5;
    return DURATIONS.reduce(function (best, v) { return Math.abs(v - d) < Math.abs(best - d) ? v : best; });
  }

  var CHANNEL_CAP = {
    normal: 'Please keep creations SFW',
    enhanced: '👑 Enhanced — for professional creators'
  };

  var MODEL_OPTIONS_HTML = MODELS.map(function (m) {
    return '<option value="' + m.value + '"' + (m.value === 'v4.0.1' ? ' selected' : '') +
      (m.disabled ? ' disabled title="Needs one --dump-params capture before it can submit"' : '') +
      '>' + esc(m.label) + (m.disabled ? ' (not yet available)' : '') + '</option>';
  }).join('');

  var MARKUP =
    '<div class="mgd-seg" role="tablist">' +
      '<button type="button" class="on" data-vmode="i2v">First Frame</button>' +
      '<button type="button" data-vmode="flf">First &amp; Last Frames</button>' +
      '<button type="button" data-vmode="r2v">Multi-Reference</button>' +
    '</div>' +
    '<div class="mgd-lbl mgd-slots-lbl">Start Frame</div>' +
    '<div class="mgd-slots mgd-imgslots"></div>' +
    '<div class="mgd-lbl mgd-endlbl" style="display:none;">End Frame <span class="mgd-note">(Optional)</span></div>' +
    '<div class="mgd-slots mgd-endslots" style="display:none;"></div>' +
    '<div class="mgd-lbl mgd-vidlbl" style="display:none;">Video references <span class="mgd-note">&middot; up to 3 &middot; 2&ndash;15s each, 15s total</span></div>' +
    '<div class="mgd-slots mgd-vidslots" style="display:none;"></div>' +
    '<div class="mgd-lbl mgd-audlbl" style="display:none;">Audio reference <span class="mgd-note">&middot; WAV &le;15MB</span></div>' +
    '<div class="mgd-audiorow" style="display:none;"></div>' +
    '<input type="file" class="mgd-audiofile" accept="audio/*" style="display:none;">' +
    '<div class="mgd-ce" contenteditable="true" data-placeholder=""></div>' +
    '<div class="mgd-lbl">Negative prompt</div>' +
    '<textarea class="mgd-neg" placeholder="blurry, extra fingers, watermark"></textarea>' +
    '<div class="mgd-row">' +
      '<div class="grow"><div class="mgd-lbl">Model</div>' +
        '<select class="mgd-sel mgd-model">' + MODEL_OPTIONS_HTML + '</select>' +
        '<div class="mgd-caps mgd-modelcaps"></div></div>' +
      '<div><div class="mgd-lbl">Duration (s)</div>' +
        '<select class="mgd-sel mgd-dur"><option>5</option><option>6</option><option>10</option><option>15</option></select></div>' +
    '</div>' +
    '<div class="mgd-row">' +
      '<div class="mgd-cam-wrap"><div class="mgd-lbl">Camera</div>' +
        '<select class="mgd-sel mgd-cam">' +
          '<option value="unset">Unset</option>' +
          '<option value="horizontal">Side-to-side move</option>' +
          '<option value="vertical-pan">Vertical Pan</option>' +
          '<option value="zoom">Zoom in or out</option>' +
          '<option value="pan">Camera sweep</option>' +
          '<option value="tilt">Tilt up or down</option>' +
          '<option value="roll">Camera spin</option>' +
        '</select></div>' +
      '<div class="mgd-quality-wrap"><div class="mgd-lbl">Basic / Professional</div>' +
        '<select class="mgd-sel mgd-quality"><option value="basic">Basic</option><option value="professional" selected>Professional</option></select></div>' +
      '<div><div class="mgd-lbl">Channel</div>' +
        '<select class="mgd-sel mgd-channel"><option value="normal" selected>Normal</option><option value="enhanced">Enhanced</option></select>' +
        '<div class="mgd-caps mgd-chancap"></div></div>' +
    '</div>' +
    '<label class="mgd-check"><input type="checkbox" class="mgd-audio"> Generate audio <span class="mgd-note">(spoken lines in the prompt become voiceover)</span></label>' +
    '<div class="mgd-lang-wrap" style="display:none;margin-top:4px;"><div class="mgd-lbl">Audio language</div>' +
      '<select class="mgd-sel mgd-lang"><option value="english">English</option><option value="japanese">Japanese</option><option value="chinese">Chinese</option><option value="korean">Korean</option><option value="none">SE only (no dialogue)</option></select></div>' +
    '<div class="mgd-cost" style="margin-top:10px;">Pick a source image to see the cost.</div>' +
    '<button type="button" class="mgd-go">Generate video</button>' +
    '<div class="mgd-result"></div>' +
    '<div class="mgd-preview" aria-hidden="true"></div>';

  function slotBox(cssText) {
    var box = document.createElement('div');
    box.style.cssText = 'position:relative;width:72px;height:72px;border-radius:8px;border:1px solid var(--surface1,#3a3460);background:var(--surface0,#211f3a);cursor:pointer;overflow:hidden;display:grid;place-items:center;color:var(--subtext,#9a93ab);font-size:10.5px;text-align:center;' + (cssText || '');
    return box;
  }

  class MgGenerateDrawerEl extends HTMLElement {
    connectedCallback() {
      injectStyle();
      if (this._built) return;
      this._built = true;
      this._mode = 'i2v';
      this._slots = [null];        // i2v/flf primary bank
      this._imgSlots = [null];     // r2v image bank (max 6)
      this._vidSlots = [];         // r2v video bank (max 3)
      this._audSlot = null;        // r2v audio ref: {media_id, filename} | null
      this._costSeq = 0;
      this._costTimer = null;
      this._chipTimer = null;
      this._pollTimer = null;
      this._dirty = false;       // true from the first keystroke since the last commit/sync
      this._rendering = false;   // true while THIS drawer's own submit/poll is in flight
      this.innerHTML = MARKUP;
      this._slotsLbl = this.querySelector('.mgd-slots-lbl');
      this._slotsWrap = this.querySelector('.mgd-imgslots');
      this._endLbl = this.querySelector('.mgd-endlbl');
      this._endWrap = this.querySelector('.mgd-endslots');
      this._vidLbl = this.querySelector('.mgd-vidlbl');
      this._vidWrap = this.querySelector('.mgd-vidslots');
      this._audLbl = this.querySelector('.mgd-audlbl');
      this._audRow = this.querySelector('.mgd-audiorow');
      this._audFile = this.querySelector('.mgd-audiofile');
      this._ce = this.querySelector('.mgd-ce');
      this._neg = this.querySelector('.mgd-neg');
      this._model = this.querySelector('.mgd-model');
      this._modelCaps = this.querySelector('.mgd-modelcaps');
      this._dur = this.querySelector('.mgd-dur');
      this._camWrap = this.querySelector('.mgd-cam-wrap');
      this._cam = this.querySelector('.mgd-cam');
      this._quality = this.querySelector('.mgd-quality');
      this._channel = this.querySelector('.mgd-channel');
      this._chanCap = this.querySelector('.mgd-chancap');
      this._audio = this.querySelector('.mgd-audio');
      this._langWrap = this.querySelector('.mgd-lang-wrap');
      this._lang = this.querySelector('.mgd-lang');
      this._cost = this.querySelector('.mgd-cost');
      this._go = this.querySelector('.mgd-go');
      this._result = this.querySelector('.mgd-result');
      this._preview = this.querySelector('.mgd-preview');
      var self = this;
      this.querySelectorAll('.mgd-seg button').forEach(function (b) {
        b.addEventListener('click', function () { self._userSetMode(b.getAttribute('data-vmode')); });
      });
      this._ce.addEventListener('input', function () {
        self._dirty = true;
        self.dispatchEvent(new CustomEvent('mg-dirty', { bubbles: true, composed: true }));
        clearTimeout(self._chipTimer);
        self._chipTimer = setTimeout(function () { self._chipify(false); self._debCost(); self._emitCommitIfDirty(); }, 300);
      });
      this._ce.addEventListener('blur', function () { self._chipify(true); self._emitCommitIfDirty(); });
      this._neg.addEventListener('input', function () { self._debCost(); });
      this._model.addEventListener('change', function () { self._renderModelCaps(); self._applyModelGating(); self._debCost(); });
      this._dur.addEventListener('change', function () { self._debCost(); });
      this._channel.addEventListener('change', function () { self._renderChanCap(); self._debCost(); });
      this._audio.addEventListener('change', function () { self._audioToggle(); });
      this._audFile.addEventListener('change', function () {
        var f = self._audFile.files[0]; self._audFile.value = '';
        if (f) self._uploadAudio(f);
      });
      this._go.addEventListener('click', function () { self._generate(); });
      this._renderModelCaps();
      this._renderChanCap();
      this._setMode('i2v');
      this._applyModelGating();
    }

    disconnectedCallback() {
      clearTimeout(this._costTimer);
      clearTimeout(this._chipTimer);
      clearTimeout(this._pollTimer);
    }

    // ---- mode + the primary (image) slot bank -------------------------------------
    _primary() { return this._mode === 'r2v' ? this._imgSlots : this._slots; }
    _setPrimary(arr) { if (this._mode === 'r2v') this._imgSlots = arr; else this._slots = arr; }

    _setMode(m) {
      this._mode = m;
      var self = this;
      this.querySelectorAll('.mgd-seg button').forEach(function (b) {
        b.classList.toggle('on', b.getAttribute('data-vmode') === m);
      });
      if (m === 'i2v') this._slots = [this._slots[0] || null];
      else if (m === 'flf') this._slots = [this._slots[0] || null, this._slots[1] || null];
      else if (!this._imgSlots.length) this._imgSlots = [null];
      this._slotsLbl.textContent = MODE_LBL[m];
      this._ce.setAttribute('data-placeholder', MODE_PH[m]);
      this._camWrap.style.visibility = (m === 'r2v') ? 'hidden' : 'visible';
      var showR2v = (m === 'r2v');
      this._vidLbl.style.display = showR2v ? '' : 'none';
      this._vidWrap.style.display = showR2v ? '' : 'none';
      this._audLbl.style.display = showR2v ? '' : 'none';
      this._audRow.style.display = showR2v ? '' : 'none';
      this._renderSlots();
      if (showR2v) { this._renderVidSlots(); this._renderAudioRow(); }
    }

    // Called ONLY from a direct user click on a mode-segment button (First Frame/First &
    // Last Frames/Multi-Reference). Applies the mode locally via _setMode AND tells the host
    // a real, user-initiated mode choice happened -- distinct from _setMode() itself, which
    // is ALSO called internally by prefill() (re-syncing FROM the host), _applyModelGating()
    // (an auto-switch forced by a model/mode incompatibility), and setRefs() (a host-driven
    // bulk "Send to Video" load) -- none of those represent the user asking for a mode, and
    // none of them may dispatch, or a click -> event -> host update -> prefill() -> _setMode()
    // -> re-dispatch loop results. Mirrors the mg-prompt-commit / _emitCommitIfDirty split.
    _userSetMode(m) {
      this._setMode(m);
      this.dispatchEvent(new CustomEvent('mg-mode-commit', { bubbles: true, composed: true, detail: { vmode: m } }));
    }

    // Shows/hides the mode buttons a selected model doesn't actually support (MODEL_VMODES)
    // and switches off an now-invalid current mode. Called on model change and prefill.
    _applyModelGating() {
      var allowed = MODEL_VMODES[this._model.value] || ['i2v', 'flf', 'r2v'];
      this.querySelectorAll('.mgd-seg button').forEach(function (b) {
        b.style.display = allowed.indexOf(b.getAttribute('data-vmode')) === -1 ? 'none' : '';
      });
      if (allowed.indexOf(this._mode) === -1) this._setMode(allowed[0]);
    }

    // ---- primary (image) bank rendering: i2v/flf's _slots, r2v's _imgSlots --------
    // flf only ever renders _slots[0] (Start Frame) here -- _slots[1] (End Frame) gets its
    // own labeled block via _renderEndSlot, matching PixAI's two-separately-labeled-boxes
    // layout rather than one combined "start & end" row.
    _renderSlots() {
      var wrap = this._slotsWrap, self = this, arr = this._primary();
      wrap.innerHTML = '';
      var mainArr = (this._mode === 'flf') ? [arr[0]] : arr;
      var refN = 0;
      mainArr.forEach(function (s, i) {
        var box = slotBox();
        if (s) {
          refN++;
          var tag = (self._mode === 'flf' ? 'start' : '@image' + refN);
          box.innerHTML = '<img src="' + esc(s.thumb) + '" style="width:100%;height:100%;object-fit:cover;">' +
            '<span style="position:absolute;left:3px;bottom:3px;background:rgba(21,19,28,.88);color:var(--lavender,#b692e6);font-size:9px;padding:1px 5px;border-radius:4px;">' + tag + '</span>' +
            '<button type="button" class="mgd-vs-x" style="position:absolute;top:2px;right:2px;width:16px;height:16px;border-radius:50%;border:none;background:rgba(21,19,28,.88);color:var(--subtext,#9a93ab);font-size:10px;line-height:1;cursor:pointer;padding:0;">&times;</button>';
          box.querySelector('.mgd-vs-x').onclick = function (ev) {
            ev.stopPropagation(); self._hidePreview();
            if (self._mode === 'r2v') { arr.splice(i, 1); if (!arr.length) arr = [null]; self._setPrimary(arr); }
            else self._slots[i] = null;
            self._renderSlots();
          };
          box.onmouseenter = function () { self._showPreview(s.media_id, box); };
          box.onmouseleave = function () { self._hidePreview(); };
        } else {
          box.textContent = (self._mode === 'flf' || self._mode === 'i2v') ? '+ start' : '+ pick';
        }
        box.onclick = function () { self._requestPick('primary', i); };
        wrap.appendChild(box);
      });
      if (this._mode === 'r2v' && arr.length < 6) {
        var add = document.createElement('button');
        add.type = 'button'; add.textContent = '+ add';
        add.style.cssText = 'width:72px;height:72px;border-radius:8px;border:1px dashed var(--surface1,#3a3460);background:transparent;color:var(--subtext,#9a93ab);cursor:pointer;font-size:11px;';
        add.onclick = function () { arr.push(null); self._setPrimary(arr); self._renderSlots(); };
        wrap.appendChild(add);
      }
      this._renderEndSlot();
      this._debCost();
    }

    // End Frame (Optional) -- flf mode only, always _slots[1]. Leaving it empty is valid
    // (see _hasAnyRef): PixAI's own "(Optional)" label means Start Frame alone submits fine.
    _renderEndSlot() {
      var self = this;
      if (this._mode !== 'flf') {
        this._endLbl.style.display = 'none';
        this._endWrap.style.display = 'none';
        return;
      }
      this._endLbl.style.display = '';
      this._endWrap.style.display = '';
      this._endWrap.innerHTML = '';
      var box = slotBox(), s = this._slots[1];
      if (s) {
        box.innerHTML = '<img src="' + esc(s.thumb) + '" style="width:100%;height:100%;object-fit:cover;">' +
          '<span style="position:absolute;left:3px;bottom:3px;background:rgba(21,19,28,.88);color:var(--lavender,#b692e6);font-size:9px;padding:1px 5px;border-radius:4px;">end</span>' +
          '<button type="button" class="mgd-vs-x" style="position:absolute;top:2px;right:2px;width:16px;height:16px;border-radius:50%;border:none;background:rgba(21,19,28,.88);color:var(--subtext,#9a93ab);font-size:10px;line-height:1;cursor:pointer;padding:0;">&times;</button>';
        box.querySelector('.mgd-vs-x').onclick = function (ev) {
          ev.stopPropagation(); self._hidePreview(); self._slots[1] = null; self._renderEndSlot(); self._debCost();
        };
        box.onmouseenter = function () { self._showPreview(s.media_id, box); };
        box.onmouseleave = function () { self._hidePreview(); };
      } else {
        box.textContent = '+ end';
      }
      box.onclick = function () { self._requestPick('primary', 1); };
      this._endWrap.appendChild(box);
    }

    // ---- video reference bank (r2v only, max 3) -- real poster thumbs, play badge -
    _renderVidSlots() {
      var wrap = this._vidWrap, self = this;
      wrap.innerHTML = '';
      if (!this._vidSlots.length) this._vidSlots = [null];
      var refN = 0;
      this._vidSlots.forEach(function (s, i) {
        var box = slotBox('border-style:dashed;');
        if (s) {
          refN++;
          box.style.borderStyle = 'solid';
          box.innerHTML = '<img src="' + esc(s.thumb) + '" style="width:100%;height:100%;object-fit:cover;">' +
            '<span class="mgd-vidbadge">▶</span>' +
            '<span style="position:absolute;left:3px;bottom:3px;background:rgba(21,19,28,.88);color:var(--lavender,#b692e6);font-size:9px;padding:1px 5px;border-radius:4px;">@video' + refN + '</span>' +
            '<button type="button" class="mgd-vs-x" style="position:absolute;top:2px;right:2px;width:16px;height:16px;border-radius:50%;border:none;background:rgba(21,19,28,.88);color:var(--subtext,#9a93ab);font-size:10px;line-height:1;cursor:pointer;padding:0;">&times;</button>';
          box.querySelector('.mgd-vs-x').onclick = function (ev) {
            ev.stopPropagation(); self._hidePreview();
            self._vidSlots.splice(i, 1); if (!self._vidSlots.length) self._vidSlots = [null];
            self._renderVidSlots();
          };
          box.onmouseenter = function () { self._showPreview(s.media_id, box); };
          box.onmouseleave = function () { self._hidePreview(); };
        } else {
          box.textContent = '+ video';
        }
        box.onclick = function () { self._requestPick('vid', i); };
        wrap.appendChild(box);
      });
      if (this._vidSlots.length < 3) {
        var add = document.createElement('button');
        add.type = 'button'; add.textContent = '+ add';
        add.style.cssText = 'width:72px;height:72px;border-radius:8px;border:1px dashed var(--surface1,#3a3460);background:transparent;color:var(--subtext,#9a93ab);cursor:pointer;font-size:11px;';
        add.onclick = function () { self._vidSlots.push(null); self._renderVidSlots(); };
        wrap.appendChild(add);
      }
      this._debCost();
    }

    // ---- audio reference (r2v only, single slot, direct upload -- no gallery picker
    // has a concept of audio media, so this bypasses mg-pick-request entirely) -------
    _renderAudioRow() {
      var wrap = this._audRow, self = this;
      wrap.innerHTML = '';
      if (this._audSlot) {
        var chip = document.createElement('span');
        chip.className = 'mgd-audiochip';
        chip.innerHTML = '♪ @audio1 &middot; ' + esc(this._audSlot.filename) +
          ' <button type="button">&times;</button>';
        chip.querySelector('button').onclick = function () {
          self._audSlot = null; self._renderAudioRow(); self._debCost();
        };
        wrap.appendChild(chip);
      } else {
        var add = document.createElement('button');
        add.type = 'button'; add.className = 'mgd-audioadd'; add.textContent = '+ Audio';
        add.onclick = function () { self._audFile.click(); };
        wrap.appendChild(add);
      }
    }

    _uploadAudio(file) {
      var self = this;
      if (file.size > 15 * 1024 * 1024) { this._renderError('Audio file too large — PixAI allows up to 15MB.'); return; }
      var wrap = this._audRow;
      wrap.innerHTML = '<span class="mgd-note">Uploading ' + esc(file.name) + '…</span>';
      var fd = new FormData(); fd.append('file', file);
      fetch('/api/upload', { method: 'POST', body: fd })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.error || !d.media_id) { self._renderError(d.error || 'audio upload failed'); self._renderAudioRow(); return; }
          self._audSlot = { media_id: String(d.media_id), filename: file.name };
          self._renderAudioRow();
          self._debCost();
        })
        .catch(function () { self._renderError('audio upload failed (network)'); self._renderAudioRow(); });
    }

    // Picker-agnostic: ask the host to pick. The host calls respond() with its choice.
    // bank: 'primary' (image) | 'vid' (video) -- drives the `kind` hint hosts filter on.
    _requestPick(bank, i) {
      var self = this;
      this.dispatchEvent(new CustomEvent('mg-pick-request', {
        bubbles: true, composed: true,
        detail: {
          slot: i, bank: bank, mode: this._mode, kind: (bank === 'vid' ? 'video' : 'image'),
          respond: function (media_id, thumb) {
            if (!media_id) return;
            var item = { media_id: String(media_id), thumb: thumb || ('/thumbs/' + media_id + '.jpg') };
            if (bank === 'vid') { self._vidSlots[i] = item; self._renderVidSlots(); }
            else { var arr = self._primary(); arr[i] = item; self._setPrimary(arr); self._renderSlots(); }
          }
        }
      }));
    }

    // ---- @image/@video/@audio chips in the contenteditable prompt -----------------
    _refMap() {
      var map = {}, n = 0;
      this._primary().forEach(function (s) {
        if (s && s.media_id) { n++; map['@image' + n] = { thumb: s.thumb, mid: s.media_id, kind: 'image' }; }
      });
      if (this._mode === 'r2v') {
        var vn = 0;
        this._vidSlots.forEach(function (s) {
          if (s && s.media_id) { vn++; map['@video' + vn] = { thumb: s.thumb, mid: s.media_id, kind: 'video' }; }
        });
        if (this._audSlot && this._audSlot.media_id) {
          map['@audio1'] = { mid: this._audSlot.media_id, kind: 'audio' };
        }
      }
      return map;
    }

    _makeChip(tag, info) {
      var self = this;
      var c = document.createElement('span');
      c.className = 'mgd-chip'; c.contentEditable = 'false';
      c.setAttribute('data-ref', tag);
      var lead = info && info.thumb ? '<img src="' + esc(info.thumb) + '" alt="">' : (info && info.kind === 'audio' ? '♪ ' : '');
      c.innerHTML = lead + tag;
      if (info && info.mid && info.kind !== 'audio') {
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
      var re = /@(?:image|video|audio)\d+/g;
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
      return out.replace(/ /g, ' ').trim();
    }

    _promptSet(v) {
      this._ce.textContent = v || '';
      this._chipify(true);
      this._debCost();
      this._dirty = false;   // programmatic sync, not a pending hand-edit
    }

    // Fires mg-prompt-commit once per genuine edit "session" (debounced 300ms after the
    // last keystroke, or immediately on blur, whichever comes first) -- distinct from
    // mg-dirty, which fires on every keystroke for cheap "something changed" tracking.
    // A host that wants to durably persist a hand-edit (vs. just knowing one is in
    // progress) listens for this instead.
    _emitCommitIfDirty() {
      if (!this._dirty) return;
      this._dirty = false;
      this.dispatchEvent(new CustomEvent('mg-prompt-commit', { bubbles: true, composed: true, detail: { text: this._promptText() } }));
    }

    // ---- model / channel capability captions ---------------------------------------
    _renderModelCaps() {
      var chosen = null;
      for (var i = 0; i < MODELS.length; i++) if (MODELS[i].value === this._model.value) { chosen = MODELS[i]; break; }
      this._modelCaps.innerHTML = chosen ? chosen.caps.map(function (t) {
        return '<span class="mgd-cap hot">' + esc(t) + '</span>';
      }).join('') : '';
    }

    _renderChanCap() {
      var v = this._channel.value;
      this._chanCap.innerHTML = '<span class="mgd-cap' + (v === 'enhanced' ? ' crown' : '') + '">' + CHANNEL_CAP[v] + '</span>';
    }

    // ---- payload + live cost --------------------------------------------------------
    payload() {
      var images = this._primary().filter(function (s) { return s && s.media_id; }).map(function (s) { return s.media_id; });
      var video_refs = this._mode === 'r2v'
        ? this._vidSlots.filter(function (s) { return s && s.media_id; }).map(function (s) { return s.media_id; })
        : [];
      var audio_refs = (this._mode === 'r2v' && this._audSlot && this._audSlot.media_id) ? [this._audSlot.media_id] : [];
      return {
        mode: this._mode.toUpperCase(),
        prompt: this._promptText(),
        negative: this._neg.value.trim(),
        images: images,
        video_refs: video_refs,
        audio_refs: audio_refs,
        duration: +this._dur.value,
        audio: this._audio.checked,
        video_model: this._model.value,
        camera_movement: (this._mode !== 'r2v' ? this._cam.value : ''),
        quality: this._quality.value,
        audio_language: this._lang.value,
        is_private: (this._channel.value === 'enhanced')
      };
    }

    _hasAnyRef(p) { return !!(p.images.length || p.video_refs.length || p.audio_refs.length); }

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
      if (!this._hasAnyRef(p)) {
        cost.className = 'mgd-cost';
        cost.textContent = (this._mode === 'r2v') ? 'Pick at least one reference to see the cost.' : 'Pick a source image to see the cost.';
        return;
      }
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
      if (!this._hasAnyRef(p)) {
        res.style.display = 'block';
        res.innerHTML = '<span style="color:var(--red,#f38ba8);font-size:12px;">' +
          (this._mode === 'r2v' ? 'Pick at least one reference first.' : 'Pick a source image first.') + '</span>';
        return;
      }
      res.style.display = 'block';
      res.innerHTML = '<span class="mgd-moon"></span><span style="color:var(--subtext,#9a93ab);font-size:12px;">Submitting…</span>';
      this._rendering = true;
      this._go.disabled = true; this._go.textContent = 'Rendering…';
      function done() { self._rendering = false; self._go.disabled = false; self._go.textContent = 'Generate video'; }
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

    // POLL_GIVE_UP_MS mirrors the Loom's own pollShot give-up threshold (generous against
    // the longest real clips -- 15s @ V4.0 full genuinely takes several minutes -- while
    // still eventually freeing the Go button and marking a truly dead task, rather than
    // polling forever with no way to retry). Found 2026-07-18 live-testing: this loop had
    // no give-up path at all before.
    _poll(taskId, done) {
      var self = this, res = this._result, startedAt = Date.now(), GIVE_UP_MS = 20 * 60 * 1000;
      clearTimeout(this._pollTimer);
      var giveUp = function () {
        done();
        self._renderError('timed out waiting for this render — check the task on pixai.art, or try again');
      };
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
            } else if (Date.now() - startedAt > GIVE_UP_MS) {
              giveUp();
            } else {
              res.innerHTML = '<span class="mgd-moon"></span><span style="color:var(--subtext,#9a93ab);font-size:12px;">Rendering under the eclipse… (task ' + esc(String(taskId).slice(-6)) + ')</span>';
              self._pollTimer = setTimeout(tick, 2000);
            }
          })
          .catch(function () {
            // transient poll blip: the task is still running server-side -- keep polling,
            // unless we're past the give-up threshold too.
            if (!self.isConnected) return;
            if (Date.now() - startedAt > GIVE_UP_MS) { giveUp(); return; }
            self._pollTimer = setTimeout(tick, 2000);
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
      var p = this._preview;
      // A prefilled slot can carry a local data-URL (a cast asset never uploaded to PixAI
      // yet) instead of a real media_id -- /thumbs/<id>.jpg would 404 for that, so skip
      // rather than show a broken image.
      if (!p || !mid || !/^\d+$/.test(mid)) return;
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
    // Synchronously flushes a pending (not-yet-debounced) hand-edit and returns its text,
    // or null if there was nothing pending. For a host about to overwrite this drawer with
    // a DIFFERENT shot's content (prefill()) or about to read committed state for a
    // generate call that can't wait out the 300ms debounce (the toolbar's "Generate all"
    // button) -- both cases where a real edit sitting in the debounce window would
    // otherwise be silently dropped, since the pending mg-prompt-commit that debounce was
    // going to fire never gets the chance to.
    flushPromptEdit() {
      clearTimeout(this._chipTimer);
      this._chipify(true);
      if (!this._dirty) return null;
      this._dirty = false;
      return this._promptText();
    }

    // Lets a host (the Loom) disable this drawer's own Go button when ITS OWN card state
    // says a generation is already in flight for the active shot -- covers the case where
    // some OTHER path (a toolbar batch run) submitted this exact shot, not this drawer.
    // No-ops while _rendering is true: this drawer's OWN _generate()/done() lifecycle
    // already owns _go.disabled/text for a submit IT started, and must not be fought by a
    // host-driven call that doesn't know that submit is in flight.
    setBusy(isBusy) {
      if (this._rendering) return;
      this._go.disabled = !!isBusy;
    }

    // The lightbox / bulk-bar "Send to Video" entry (gallery addVideoRefs, sans host
    // chrome). Image refs only, as today's gallery bulk-send is -- unchanged from Phase 1.
    // undefined/null (no array at all) is a no-op -- the caller has no opinion, leave
    // whatever's already in the slots. An explicit EMPTY ARRAY clears the primary bank --
    // load-bearing for prefill() below: switching the Loom to a shot/draft with zero refs
    // used to leave the PREVIOUS shot's images sitting in the drawer, unnoticed, ready to
    // submit against the wrong shot's generation. Found 2026-07-18 live-testing.
    setRefs(refs) {
      if (!Array.isArray(refs)) return;
      refs = refs.slice(0, 6);
      if (refs.length > 1) this._setMode('r2v');
      var slots = refs.map(function (r) {
        var mid = String(r.media_id || r.mid);
        return { media_id: mid, thumb: r.thumb || ('/thumbs/' + mid + '.jpg') };
      });
      if (refs.length > 1) { this._setPrimary(slots); }
      else if (this._mode === 'r2v') { this._setPrimary([slots[0] || null]); }
      else { this._slots[0] = slots[0] || null; }
      this._renderSlots();
    }

    // Shot-context prefill for the Loom (and any host): only the keys present are applied.
    // images/video_refs: [{media_id,thumb}]. audio_ref: {media_id,filename}|null.
    prefill(o) {
      o = o || {};
      if (o.mode && MODE_LBL[String(o.mode).toLowerCase()]) this._setMode(String(o.mode).toLowerCase());
      if (o.video_model != null) { this._model.value = o.video_model; this._renderModelCaps(); }
      if (o.duration != null) this._dur.value = String(snapDuration(o.duration));
      if (o.quality != null) this._quality.value = o.quality;
      if (o.is_private != null) { this._channel.value = o.is_private ? 'enhanced' : 'normal'; this._renderChanCap(); }
      if (o.audio != null) { this._audio.checked = !!o.audio; this._audioToggle(); }
      if (o.audio_language != null) this._lang.value = o.audio_language;
      if (o.negative != null) this._neg.value = o.negative;
      if (o.refs) this.setRefs(o.refs);                    // back-compat alias for images
      if (o.images) this.setRefs(o.images);
      // Array.isArray (not truthy-length) so an EXPLICIT empty array clears stale video
      // refs from a previous shot, same reasoning as setRefs() above -- a shot with no
      // video refs used to leave the last shot's video slots sitting there unnoticed.
      if (Array.isArray(o.video_refs)) {
        this._vidSlots = o.video_refs.slice(0, 3).map(function (r) {
          var mid = String(r.media_id || r.mid);
          return { media_id: mid, thumb: r.thumb || ('/thumbs/' + mid + '.jpg') };
        });
        if (this._mode === 'r2v') this._renderVidSlots();
      }
      // undefined = caller has no opinion (leave it); explicit null = clear it. Distinct
      // from images/video_refs above only because callers that never mention audio_ref at
      // all (the gallery bulk-send path) still need "don't touch it" to work.
      if (o.audio_ref !== undefined) {
        this._audSlot = o.audio_ref ? { media_id: String(o.audio_ref.media_id), filename: o.audio_ref.filename || 'audio ref' } : null;
        if (this._mode === 'r2v') this._renderAudioRow();
      }
      if (o.prompt != null) this._promptSet(o.prompt);
      // Gate LAST, after refs/mode are all settled -- setRefs() above can itself force
      // mode to r2v (>1 ref), so an earlier gate call could be second-guessed by it. One
      // final authoritative pass here means the drawer never ends up showing a mode/slot
      // bank the selected model doesn't actually support.
      this._applyModelGating();
      this._debCost();
    }

    get mode() { return this._mode; }
  }

  window.customElements.define('mg-generate-drawer', MgGenerateDrawerEl);
})();
