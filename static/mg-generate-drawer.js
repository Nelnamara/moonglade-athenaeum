/* mg-generate-drawer.js -- a framework-neutral <mg-generate-drawer> custom element: the
   shared Generate form that BOTH the vanilla gallery and the React Loom can mount, so the
   generation UI lives in ONE place instead of two hand-duplicated ones (the two Video tabs
   shipping the same audio feature with different gaps is exactly the drift this ends).

   Third shared web component of the Option-A cohesion migration, same conventions as
   mg-model-picker.js / mg-gallery-picker.js: plain global via <script src>, no build step,
   reads the shared DESIGN_TOKENS_CSS custom properties. Targets full PixAI Multi-ref
   parity (6 image + 3 video + 1 audio ref slots), negative prompt, Channel (Normal/Enhanced,
   PixAI's own wording), and the full 7-model roster with capability gating.

   Usage:
     <mg-generate-drawer></mg-generate-drawer>
   No attributes configure it at mount -- connectedCallback() never reads one off the host
   element (form state instead comes from prefill(), the Loom's shot-context entry, or the
   drawer's own internal defaults). The one attribute this file DOES read is data-loom-ctx,
   consumed by CSS alone (see the mgd-cam-wrap/mgd-quality-wrap rule below) to hide the
   drawer's own Camera/quality controls when a host -- currently only the Loom -- already
   owns equivalents.
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
     mg-error        -- detail: {error}. Only fires on a REAL server-reported failure -- an
                        elapsed-time-alone timeout never dispatches this (see mg-slow/
                        mg-paused instead); the render is still genuinely in flight, just slow.
     mg-slow         -- detail: {tier: 'slow'|'stale', elapsed, task_id}. Fired when the poll's
                        cadence downshifts (20min, then 90min) with no result yet -- a host
                        whose own board-grid card reads from its own state (not this drawer's
                        inline result div) needs this to keep that card's badge in sync.
     mg-paused       -- detail: {task_id}. Fired when the poll hits its 6h ceiling and stops
                        scheduling further calls for this task -- NOT a failure (status/
                        pendingTaskId are the host's to leave untouched); a reload or a fresh
                        _poll() call for the same task_id always gets a completely new budget.
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
     mg-duration-commit -- detail: {duration}. Fired ONLY from a direct user change on this
                        drawer's own Duration <select> -- never from prefill() (a plain
                        .value= assignment doesn't fire 'change'). No override-vs-base
                        distinction the way prompt has, so a host durably persisting this
                        writes it straight onto the shot's duration field.
     mg-audio-commit -- detail: {audioGen, audioLanguage}. Fired from a direct user change on
                        either the Generate-audio checkbox or the Audio-language select
                        (never from prefill()'s programmatic .checked/.value writes) --
                        reads both controls' live values at dispatch time so either control
                        changing alone still reports a complete, current pair.
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
    /* The cost line is <mg-cost-badge> now (static/mg-cost-badge.js). It brings its own box --
       padding/radius/border/font were lifted from the old .mgd-cost verbatim on purpose, so
       this swap is pixel-identical -- and its own emerald `free` / red `error` states, so
       those two rules are gone rather than duplicated. ONE thing has to be re-stated: this
       drawer has always painted the V4.0-full caution RED (via the old warn rule on the
       cost box), while the shared
       badge's default `warn` colour is amber/--peach. Overriding it keeps the migration a
       PURE refactor -- the loudest cost warning in the app (a 15s V4.0-full clip is ~210,000
       credits) must not get quieter as a side effect of a consolidation. Host tag + element +
       two attributes beats the badge's own rule on specificity, so this wins regardless of
       <style> injection order. If red-vs-amber is ever settled the other way, DELETE this
       rule -- do not re-fork the badge. */
    'mg-generate-drawer mg-cost-badge[data-state="paid"][data-warn]{border-color:var(--red,#f38ba8);color:var(--red,#f38ba8);}',
    'mg-generate-drawer .mgd-go{width:100%;padding:9px 0;border:none;border-radius:6px;background:var(--lavender,#b692e6);color:var(--base,#0c0a1c);font-size:13.5px;font-weight:600;cursor:pointer;}',
    'mg-generate-drawer .mgd-go:hover{opacity:.9;}',
    'mg-generate-drawer .mgd-go:disabled{opacity:.4;cursor:not-allowed;}',
    'mg-generate-drawer .mgd-result{margin-top:12px;display:none;}',
    'mg-generate-drawer .mgd-result img{width:100%;border-radius:10px;display:block;margin-bottom:6px;}',
    'mg-generate-drawer .mgd-result a{color:var(--accent-soft,#4fc99a);font-size:12px;text-decoration:none;}',
    // Concurrent generations (2026-07-23): each submission gets its own line inside
    // .mgd-result instead of one shared innerHTML a later submission would overwrite.
    // A hairline separator between entries is the only visual change when just one
    // submission is ever in flight (the common case).
    'mg-generate-drawer .mgd-result-line{margin-bottom:10px;padding-bottom:10px;border-bottom:1px solid var(--surface1,#3a3460);}',
    'mg-generate-drawer .mgd-result-line:last-child{margin-bottom:0;padding-bottom:0;border-bottom:none;}',
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
    'mg-generate-drawer .mgd-preview img{width:100%;max-height:300px;object-fit:cover;display:block;}',
    /* Privacy blur (audit 2026-07-21 S5): the reference-slot thumbnails (mgd-slot, set via
       slotBox()) never carried the host page's body.privacy-blur rule -- once picked, an
       NSFW reference image sat here in full, regardless of the toggle. Same shape as
       .card/.pick-cell in pixai_gallery.py; body is real light DOM, so it reaches straight
       through this element's own plain (non-shadow) markup. */
    'body.privacy-blur mg-generate-drawer .mgd-slot img{filter:blur(16px);transition:filter .12s;}',
    'body.privacy-blur mg-generate-drawer .mgd-slot[data-nsfw="1"] img{filter:blur(28px);}',
    'body.privacy-blur mg-generate-drawer .mgd-slot:hover img{filter:none;}'
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
  // (private/VIDEO_MODELS.md `/config/tools` dump, owner screenshots 2026-07-18; our
  // V4.0 pair was previously reversed).
  //
  // All seven are selectable as of 2026-07-21. V2.7 and V3.0 Flash shipped disabled on the
  // theory that a submit needs a numeric top-level modelId from VIDEO_MODELS, which we had
  // for only five. Two free --dump-params captures off real recovered tasks disproved it:
  // both carried modelId 1648918127446573124 -- "Moonbeam v1.0", an IMAGE checkpoint, i.e.
  // whatever the site's image picker happened to hold -- and PixAI rendered them anyway.
  // Three read-only price probes then settled it: v2.7 and v3.0.1 priced DIFFERENTLY
  // (~56,000 vs ~44,800 for 10s) off an IDENTICAL modelId, and dropping modelId entirely
  // priced the same. `i2vPro.model` is what resolves the engine; the numeric modelId does
  // not. Neither is card-eligible (the free cards are V4.0-specific), so the cost badge
  // correctly reads "no card" -- that is honest, not a failure.
  //
  // 'v3.0f' was never a real value: whoever added V3.0 Flash took its tags from
  // private/VIDEO_MODELS.md's `v3.0.1` row but typed the value as a guess. PixAI's own task
  // detail for 2036215858630781665 reads "Model Used: V3.0 Flash" and its submit says
  // `model: "v3.0.1"`.
  var MODELS = [
    { value: 'v4.0', label: 'V4.0 Preview', caps: ['multi-ref', 'audio', '15s', 'top quality', '~2.5× cost'] },
    { value: 'v4.0.1', label: 'V4.0 Lite Preview', caps: ['multi-ref', 'audio', '15s', 'end-frame'] },
    { value: 'v3.2', label: 'V3.2', caps: ['audio', 'prompt-following'] },
    { value: 'v3.0.2', label: 'V3.0 Lite', caps: ['complex motion', 'cheap'] },
    { value: 'v3.0', label: 'V3.0 (High Consistency)', caps: ['high-consistency', 'action presets', 'start/end'] },
    { value: 'v3.0.1', label: 'V3.0 Flash', caps: ['multi-shot', 'hires', 'fastest', 'no card'] },
    { value: 'v2.7', label: 'V2.7 (High Dynamics)', caps: ['camera moves', 'dynamic', 'no card'] }
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
    'v3.0.1': ['i2v'],
    'v2.7': ['i2v']
  };

  // Per-model MAX duration. 15s is exclusive to the v4.0 pair (private/VIDEO_MODELS.md:
  // "Duration: 5 / 10 for all; 15s exclusive to v4.0 series"). Before V2.7 / V3.0 Flash
  // were selectable this map wasn't needed -- every enabled model happened to allow 15s.
  // Enabling them without it would newly expose a 15s option that PixAI does not support
  // on those engines, at ~84,000 credits for a V2.7 clip with no card to cover it.
  var MODEL_MAXDUR = { 'v4.0': 15, 'v4.0.1': 15 };   // absent => 10s cap

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
    '<mg-cost-badge class="mgd-cost" style="margin-top:10px;" hint="Pick a source image to see the cost." card-label="a video card"></mg-cost-badge>' +
    '<button type="button" class="mgd-go">Generate video</button>' +
    '<div class="mgd-result"></div>' +
    '<div class="mgd-preview" aria-hidden="true"></div>';

  function slotBox(cssText) {
    var box = document.createElement('div');
    box.className = 'mgd-slot';
    box.style.cssText = 'position:relative;width:72px;height:72px;border-radius:8px;border:1px solid var(--surface1,#3a3460);background:var(--surface0,#211f3a);cursor:pointer;overflow:hidden;display:grid;place-items:center;color:var(--subtext,#9a93ab);font-size:10.5px;text-align:center;' + (cssText || '');
    return box;
  }

  // LOCAL PORT of loom/src/loom-mutations.js's friendlyGenErr(raw) -- same regex patterns,
  // same replacement text, verbatim -- so a generation rejected by PixAI's content filter
  // (or stopped short on insufficient balance) reads IDENTICALLY whether it surfaced via
  // the Loom's own poll path (classifyTaskStatus -> friendlyGenErr, an ES module built by
  // esbuild) or via THIS drawer's independent submit/poll cycle below. This file must stay
  // a plain global <script> with no build step (see the top-of-file doc comment) and so
  // must NOT import loom-mutations.js -- the mapping logic is intentionally duplicated
  // here instead of shared.
  // DUPLICATION RISK, same acknowledgment as the poll-tier constants (SLOW_AT/STALE_AT/
  // CEILING) mirroring the Loom's own POLL_SLOW_AT_MS/POLL_STALE_AT_MS/POLL_CEILING_MS below:
  // if loom-mutations.js's friendlyGenErr ever gets new/changed
  // regexes or replacement wording, THIS copy must be updated to match by hand, or the
  // Loom's own generation path and this drawer's silently drift out of sync with each
  // other on the exact same class of error. There is no shared-module fix available here
  // (that's the whole reason this is a local copy) -- a code-search for "friendlyGenErr"
  // is the only guard against drift on a future edit.
  function friendlyGenErr(raw) {
    var s = String(raw || '');
    if (/insufficient|INSUFFICIENT_BALANCE|40300010/i.test(s))
      return 'Out of balance for this model — no free card matched and credits are 0. Claim your daily rewards, or pick a card-covered model.';
    if (/moderat|content.?policy|flagged|prohibit|sensitive|not.?allowed|violat/i.test(s))
      return "PixAI's content filter blocked this generation — that's decided on PixAI's side, not in the Loom.";
    return s || 'generation failed';
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
      // HARD DEPENDENCY, new as of the cost-badge consolidation: MARKUP contains a
      // <mg-cost-badge>, and an undefined custom element is an inert <div>-alike whose
      // setChecking()/setPrice() would throw inside _costNow -- leaving the cost line frozen on
      // its idle hint next to a Go button that still spends. This element previously had NO
      // component dependencies at all (the gallery's own script-tag comment says so), so a
      // future host mounting it somewhere new deserves to be told at load time rather than at
      // spend time. The enforcing guard is the pytest that pairs the two <script> tags on every
      // page (test_cost_badge_ships_with_every_price_surface); this is the console breadcrumb.
      if (!(window.customElements && customElements.get('mg-cost-badge'))) {
        console.error('<mg-generate-drawer>: /static/mg-cost-badge.js is not loaded — the cost line will not render. Load it before this file.');
      }
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
      this._dur.addEventListener('change', function () {
        self._debCost();
        // Fired only from a real user change on this <select> -- prefill() sets
        // this._dur.value directly (a property assignment, not user input), which never
        // fires a native 'change' event, so there is no host<->drawer sync-loop risk here
        // (same guarantee mg-mode-commit relies on for _setMode() vs _userSetMode()).
        self.dispatchEvent(new CustomEvent('mg-duration-commit', { bubbles: true, composed: true,
          detail: { duration: +self._dur.value } }));
      });
      this._channel.addEventListener('change', function () { self._renderChanCap(); self._debCost(); });
      this._audio.addEventListener('change', function () { self._userToggleAudioGen(); });
      this._lang.addEventListener('change', function () { self._emitAudioCommit(); self._debCost(); });
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
      // Concurrent generations: each in-flight submission owns its own poll timeout (see
      // _poll below), tracked in this Set instead of the old single this._pollTimer --
      // sweep every one of them, not just the most recent submission's.
      (this._pollTimers || []).forEach(function (t) { clearTimeout(t); });
      this._pollTimers = null;
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

      // Duration options past this model's cap are disabled AND hidden -- hiding alone is
      // not enough, a hidden <option> stays keyboard-selectable and still submits. Setting
      // .value programmatically fires no 'change', so this never emits a spurious
      // mg-duration-commit (that event is contractually user-initiated only).
      var maxDur = MODEL_MAXDUR[this._model.value] || 10;
      this._dur.querySelectorAll('option').forEach(function (o) {
        var over = (+o.value) > maxDur;
        o.disabled = over;
        o.hidden = over;
      });
      if ((+this._dur.value) > maxDur) this._dur.value = String(maxDur);
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
          if (s.is_nsfw) box.setAttribute('data-nsfw', '1');
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
        if (s.is_nsfw) box.setAttribute('data-nsfw', '1');
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
          if (s.is_nsfw) box.setAttribute('data-nsfw', '1');
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
          respond: function (media_id, thumb, is_nsfw) {
            if (!media_id) return;
            var item = { media_id: String(media_id), thumb: thumb || ('/thumbs/' + media_id + '.jpg'), is_nsfw: !!is_nsfw };
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

    // Called ONLY from a direct user change on the Generate-audio checkbox -- never from
    // prefill()'s own `this._audio.checked = ...; this._audioToggle();` (a programmatic sync
    // that must not re-dispatch, mirroring _setMode()/_userSetMode()'s split).
    _userToggleAudioGen() {
      this._audioToggle();
      this._emitAudioCommit();
    }

    // Shared by both audio controls -- one event carries both fields (mirrors
    // mg-prompt-commit's own "one event, several firing triggers" shape: the debounce
    // timeout OR blur there; checkbox-change OR language-select-change here), since a host
    // durably persisting audio settings wants both written together. Reads live DOM state at
    // dispatch time, not cached values, so a language-only change (checkbox untouched) still
    // reports the checkbox's current state correctly.
    _emitAudioCommit() {
      this.dispatchEvent(new CustomEvent('mg-audio-commit', { bubbles: true, composed: true,
        detail: { audioGen: this._audio.checked, audioLanguage: this._lang.value } }));
    }

    _debCost() {
      clearTimeout(this._costTimer);
      var self = this;
      this._costTimer = setTimeout(function () { self._costNow(); }, 250);
    }

    // The cost line is <mg-cost-badge> (static/mg-cost-badge.js) and this method is now purely
    // the HOST half of that component's contract: it owns the network call, the 250ms debounce
    // (_debCost) and the _costSeq stale-response guard, and the badge owns every state's
    // wording and colour. Nothing about the request, the debounce or the abort-on-stale
    // behaviour changed -- only who renders the answer.
    _costNow() {
      var cost = this._cost, self = this;
      var p = this.payload();
      // Mode-dependent idle label, same two strings as before, handed over as the badge's
      // `hint` attribute instead of written straight into textContent.
      cost.setAttribute('hint', (this._mode === 'r2v') ? 'Pick at least one reference to see the cost.' : 'Pick a source image to see the cost.');
      if (!this._hasAnyRef(p)) { cost.removeAttribute('warn'); cost.clear(); return; }
      // v4.0 full is ~2.5x Lite (14k/s -> 210k for a 15s clip). Set BEFORE the response lands
      // so the badge's `paid` branch renders the caution inline; the badge deliberately ignores
      // `warn` in every other state, so a free/idle/error render is unaffected by it. The red
      // (not amber) colour is re-asserted by this file's own CSS override -- see that rule.
      if (p.video_model === 'v4.0') cost.setAttribute('warn', 'V4.0 full — ~2.5× Lite');
      else cost.removeAttribute('warn');
      cost.setChecking();
      var mine = ++this._costSeq;
      fetch('/api/price', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(p) })
        .then(function (r) { return r.json(); })
        // One line replaces the whole note/error/free/paid ladder. Two states get louder on
        // purpose: a {cost:null, free:false} response (which price_task returns whenever
        // PixAI's /v2/task-price errors -- it fails soft and returns None) used to render as
        // the price-shaped '≈ ? credits', and now reads as could-not-verify.
        .then(function (d) { if (mine === self._costSeq) cost.setPrice(d); })
        // setPrice(null) is NOT clear(): a failed fetch is the could-not-verify state, which
        // the badge renders red and words as "generating may spend credits". The old text here
        // was a neutral lowercase 'cost unavailable' -- indistinguishable from "cheap", on the
        // one surface where being unclear costs real credits.
        .catch(function () { if (mine === self._costSeq) cost.setPrice(null); });
    }

    // ---- submit -> poll -> result (the gallery runTask flow, self-contained) ----
    // Concurrent generations (owner-approved 2026-07-23): PixAI itself runs tasks in
    // parallel, so this drawer no longer locks Generate for the whole render. Each call
    // gets its OWN line appended into .mgd-result (never overwriting a sibling
    // submission's still-live status/result) and its OWN poll loop, tracked in
    // this._pollTimers (a Set of every outstanding timeout, not the old single
    // this._pollTimer a second submission used to clobber via clearTimeout). The Go
    // button frees up the moment the SERVER ANSWERS the submit -- accepted or rejected --
    // not when the task finishes rendering; setBusy() (below) is the host's own,
    // independent per-shot lock and is unaffected by this.
    _newResultLine() {
      this._result.style.display = 'block';
      var line = document.createElement('div');
      line.className = 'mgd-result-line';
      this._result.appendChild(line);
      return line;
    }

    _generate() {
      var self = this, p = this.payload();
      if (!this._hasAnyRef(p)) {
        var warn = this._newResultLine();
        warn.innerHTML = '<span style="color:var(--red,#f38ba8);font-size:12px;">' +
          (this._mode === 'r2v' ? 'Pick at least one reference first.' : 'Pick a source image first.') + '</span>';
        return;
      }
      var line = this._newResultLine();
      line.innerHTML = '<span class="mgd-moon"></span><span style="color:var(--subtext,#9a93ab);font-size:12px;">Submitting…</span>';
      this._rendering = true;
      this._go.disabled = true; this._go.textContent = 'Rendering…';
      function unlock() { self._rendering = false; self._go.disabled = false; self._go.textContent = 'Generate video'; }
      fetch('/api/loom/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(p) })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          unlock();   // the server answered -- free the button for the NEXT submission
          if (d.error || !d.task_id) { self._renderErrorInto(line, friendlyGenErr(d.error || 'submit failed')); return; }
          self.dispatchEvent(new CustomEvent('mg-submit', { bubbles: true, composed: true, detail: { task_id: d.task_id, payload: p } }));
          line.innerHTML = '<span class="mgd-moon"></span><span style="color:var(--subtext,#9a93ab);font-size:12px;">Queued — running…</span>';
          self._poll(d.task_id, line);
        })
        .catch(function () { unlock(); self._renderErrorInto(line, 'network error'); });
    }

    // These three thresholds mirror the Loom's own pollShot tiers exactly
    // (master-storyboard.jsx: POLL_SLOW_AT_MS/POLL_STALE_AT_MS/POLL_CEILING_MS) -- a literal
    // duplicate on purpose, same as GIVE_UP_MS was before it (no module system here to share
    // a constant from). KEEP THESE THREE NUMBERS IN SYNC if either file's tiers change.
    //
    // Softened 2026-07-18(pm): elapsed time alone no longer ends a render in failure -- the
    // old GIVE_UP_MS called done()+_renderError() at 20min, indistinguishable from a real
    // server failure (the owner's own motivating case was a late-surfacing content-moderation
    // rejection, not a timeout). Now elapsed time only slows the poll cadence and escalates
    // the message; only a real d.phase==='failed' response still calls _renderErrorInto(). At
    // the 6h ceiling this tab stops scheduling calls for this task (protects against polling a
    // permanently-wedged or deleted task forever) but that is NOT the old giveUp() either --
    // see pause below. `line` is this submission's own result-strip element (see
    // _newResultLine) -- every render/dispatch below is scoped to it, never to the whole
    // .mgd-result strip, so a sibling submission's line is untouched.
    _poll(taskId, line) {
      var self = this, startedAt = Date.now();
      var SLOW_AT = 20 * 60 * 1000, SLOW_MS = 20 * 1000;
      var STALE_AT = 90 * 60 * 1000, STALE_MS = 3 * 60 * 1000;
      var CEILING = 6 * 60 * 60 * 1000;
      if (!this._pollTimers) this._pollTimers = [];
      var pollTimers = this._pollTimers, timer = null;
      // schedule() replaces the old single-instance-field assignment this used to be --
      // each call is pushed onto the shared array (swept wholesale by disconnectedCallback)
      // instead of overwriting one field, so this task's poll loop can never silently kill
      // a DIFFERENT task's still-pending timeout (or vice versa).
      function schedule(fn, ms) {
        var idx = pollTimers.indexOf(timer);
        if (idx >= 0) pollTimers.splice(idx, 1);   // the timer that just fired is spent -- stop tracking it
        timer = setTimeout(fn, ms);
        pollTimers.push(timer);
      }
      function label(ms) { return ms < 3600000 ? (Math.round(ms / 60000) + 'm') : ((Math.round(ms / 360000) / 10) + 'h'); }
      // Ceiling reached: stop polling THIS session. NOT a giveUp() -- there is NO
      // _renderErrorInto() and NO 'failed' framing. pendingTaskId on the card (written by
      // the host's onVideoSubmit at submit time) is untouched by this -- a reload's resume
      // effect, or clicking the card's own "paused" status badge, gives it a fresh poll
      // budget rather than abandoning it.
      var pause = function () {
        line.innerHTML = '<span style="color:var(--subtext,#9a93ab);font-size:12px;">Paused auto-checking after ' + label(CEILING) +
          ' with no result — check pixai.art, or reopen this shot to check again (task ' + esc(String(taskId).slice(-6)) + ')</span>';
        self.dispatchEvent(new CustomEvent('mg-paused', { bubbles: true, composed: true, detail: { task_id: taskId } }));
      };
      schedule(function tick() {
        fetch('/api/task-status?task_id=' + encodeURIComponent(taskId))
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (!self.isConnected) return;
            var elapsed = Date.now() - startedAt;
            if (d.phase === 'done') {
              self._renderResultInto(line, d);
              self.dispatchEvent(new CustomEvent('mg-result', {
                bubbles: true, composed: true,
                detail: { media_ids: d.media_ids || [], is_video: !!d.is_video, duration: d.duration, paid_credit: d.paid_credit }
              }));
            } else if (d.phase === 'failed') {
              self._renderErrorInto(line, friendlyGenErr(d.error || ('task ' + (d.status || 'failed'))));
            } else if (elapsed > CEILING) {
              pause();
            } else if (elapsed > STALE_AT) {
              line.innerHTML = '<span class="mgd-moon"></span><span style="color:var(--amber,#f9d38c);font-size:12px;">Still going after ' + label(elapsed) +
                ' — unusual. Check pixai.art, or keep waiting (task ' + esc(String(taskId).slice(-6)) + ')</span>';
              self.dispatchEvent(new CustomEvent('mg-slow', { bubbles: true, composed: true, detail: { tier: 'stale', elapsed: elapsed, task_id: taskId } }));
              schedule(tick, STALE_MS);
            } else if (elapsed > SLOW_AT) {
              line.innerHTML = '<span class="mgd-moon"></span><span style="color:var(--amber,#f9d38c);font-size:12px;">Taking longer than expected (' + label(elapsed) +
                ', task ' + esc(String(taskId).slice(-6)) + ')</span>';
              self.dispatchEvent(new CustomEvent('mg-slow', { bubbles: true, composed: true, detail: { tier: 'slow', elapsed: elapsed, task_id: taskId } }));
              schedule(tick, SLOW_MS);
            } else {
              line.innerHTML = '<span class="mgd-moon"></span><span style="color:var(--subtext,#9a93ab);font-size:12px;">Rendering under the eclipse… (task ' + esc(String(taskId).slice(-6)) + ')</span>';
              schedule(tick, 2000);
            }
          })
          .catch(function () {
            if (!self.isConnected) return;
            var elapsed = Date.now() - startedAt;
            if (elapsed > CEILING) { pause(); return; }
            schedule(tick, elapsed > STALE_AT ? STALE_MS : elapsed > SLOW_AT ? SLOW_MS : 2000);
          });
      }, 2000);
    }

    _renderErrorInto(line, msg) {
      line.innerHTML = '<span style="color:var(--red,#f38ba8);font-size:12px;">' + esc(msg) + '</span>';
      this.dispatchEvent(new CustomEvent('mg-error', { bubbles: true, composed: true, detail: { error: msg } }));
    }

    _renderResultInto(line, d) {
      var ids = d.media_ids || [];
      var cost = d.paid_credit === 0 ? 'free (card used)' : ((d.paid_credit || 0).toLocaleString() + ' credits');
      var html = '<div style="color:var(--emerald,#4fc99a);font-size:12px;margin-bottom:6px;">✓ Rendered — ' + cost + '. Added to your gallery.</div>';
      ids.forEach(function (mid) {
        html += '<a href="/image/' + esc(mid) + '"><img src="/thumbs/' + esc(mid) + '.jpg" alt="result" loading="lazy"></a>';
      });
      line.innerHTML = html;
    }

    // Convenience wrapper for one-off errors that are NOT part of a tracked submission's
    // own line (e.g. _uploadAudio below, which runs before any /api/loom/generate call
    // exists) -- opens a fresh line and renders into it, same as every other error render.
    _renderError(msg) {
      this._renderErrorInto(this._newResultLine(), msg);
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
