/* mg-art-filters.js -- PixAI's 7 "art filters", applied locally, for free, offline.

   These are NOT generations. Each filter is two or three gradient overlays with a blend
   mode and an opacity, optionally plus a brightness/contrast/saturation tweak -- the whole
   definition is fetched by PixAI's own web client from a PUBLIC, unauthenticated endpoint
   and composited in the browser: their preview updates with no network request, their panel
   has no Generate button, and no credit price is ever shown for it.

     GET https://api.pixai.art/config/imageArtFilters   (200, no API key needed)

   The 7 recipes below are that response, baked in verbatim as captured on 2026-07-24 and
   re-fetched and compared field-by-field on 2026-07-25 (identical -- 7 filters, same 8 blend
   modes, same stops), so this feature works with no connection at all -- which the rest of
   this app requires of itself. Refreshing them is a copy-paste of the endpoint's `filters`
   array; to check them against the live endpoint, diff `MgArtFilters.FILTERS` against that
   response's `filters` with the keys sorted (PixAI's JSON key ORDER is not stable, its
   content is). The key names here are deliberately PixAI's own (`filters`, `blendMode`,
   `blendOpacity`, `stops`, `image_parameters`) so a re-fetch drops straight in and
   normalizeLayers() keeps absorbing the shape differences.

   Submitting these to PixAI as a `pixai-image-filter` generation (which this repo used to
   do from the CLI) charges credits and waits on a worker for something that is a handful of
   gradient fills. Everything here happens on the client, spends nothing, and needs no key.

   ---- BLEND-MODE MAPPING -------------------------------------------------------------
   The payload's mode names are a mix of CSS tokens and Photoshop names. Six of the eight
   map exactly; two do not, and are marked `exact:false` in BLEND_MODE_MAP with the reason:

     PixAI blendMode  CSS mix-blend-mode  canvas globalCompositeOperation  fidelity
     ---------------  ------------------  -------------------------------  --------
     darker-color     darken              darken                           APPROXIMATE
     lighter-color    lighten             lighten                          APPROXIMATE
     soft-light       soft-light          soft-light                       exact
     color-burn       color-burn          color-burn                       exact
     screen           screen              screen                           exact
     overlay          overlay             overlay                          exact
     saturation       saturation          saturation                       exact
     plus-lighter     plus-lighter        lighter                          exact (renamed)

   The two approximations are real and visible. Photoshop's "Darker Color" / "Lighter Color"
   compare the two colours as WHOLE colours and keep whichever one is darker/lighter,
   channels and all; CSS `darken`/`lighten` take the per-channel min/max, which can emit a
   third colour that is in neither input (min of #ff0000 and #00ff00 is #000000, black,
   where "Darker Color" would have picked one of the two). There is no CSS or canvas mode
   with the whole-colour behaviour, so `darken`/`lighten` is the closest available and the
   result differs from PixAI's own render wherever a layer's gradient crosses the image's
   hue. `plus-lighter` is only a rename, not an approximation: canvas spells the same
   additive (Porter-Duff "plus") operator `lighter`.

   Anything NOT in that table -- a ninth mode PixAI adds later -- returns null from
   blendModeFor() and gets its layer DROPPED with a warning. It is never coerced to
   `normal`, which would paint a flat gradient over the image and look nothing like the
   filter while appearing to have worked.

   ---- TWO THINGS THE PAYLOAD DOES NOT SAY --------------------------------------------
   1. Gradient DIRECTION. The stops carry positions 0..1 and no angle, so the direction is
      a choice. Both renderers here are pinned to the same one (top-to-bottom, CSS 180deg,
      DEFAULT_ANGLE_DEG) so the exported PNG always matches the on-screen preview; pass
      `angle` to change both together.
   2. Whether `image_parameters` adjust the base image or the finished composite. They are
      applied to the BASE here (CSS `filter` on the <img>, ctx.filter while drawing it),
      which is what the CSS overlay model does naturally and is therefore the reading that
      keeps preview and export identical. The three numbers are signed OFFSETS from 1, not
      multipliers: filter-v1-m6 ships brightness 0 and contrast 0, and a multiplier reading
      would render it as brightness(0) -- solid black.

   ---- TWO SETS: PIXAI'S AND OURS -----------------------------------------------------
   FILTERS is PixAI's seven, verbatim. MOONGLADE_FILTERS is our own five, authored here and
   derived from this app's five skin palettes. They are separate arrays and stay that way:
   FILTERS' whole contract is that refreshing it is a paste of the endpoint's `filters`
   array, which stops working the moment anything hand-written lives in it.

   Ours use ONLY the six blend modes that map exactly, so for that set the on-screen preview
   and the exported PNG are the same pixels rather than merely similar -- the two approximate
   whole-colour modes are deliberately unused. They also carry no `image_parameters`: the
   recipes are exactly the gradients that were reviewed as swatches and approved, and a
   brightness/contrast trim added after the fact would ship something other than what was
   signed off.

   `get()`, `list()` and every renderer treat both sets identically -- an id is an id. Use
   `groups()` when the UI needs to say which set a filter came from.

   Public API (all pure unless noted):
     FILTERS            -- PixAI's 7 recipes, verbatim.
     MOONGLADE_FILTERS  -- our 5, derived from the skins.
     groups()           -- [{source, label, ids}] in rail order, ours first.
     SOURCE_URL         -- the public endpoint PixAI's recipes came from.
     CAPTURED           -- the date the baked copy was last verified against SOURCE_URL.
     DEFAULT_ANGLE_DEG  -- 180 (top-to-bottom), shared by both renderers.
     BLEND_MODE_MAP     -- {mode: {css, canvas, exact, note}} -- the table above, as data.
     list()             -- every id in rail order (ours, then PixAI's).
     get(id)            -- a recipe from either set, or null.
     blendModeFor(mode, 'css'|'canvas')
                        -- the mapped value, or NULL for an unmapped mode. Throws on an
                           unknown target rather than guessing one.
     normalizeLayers(idOrRecipe, {strength})
                        -- {layers, warnings}. Drops disabled layers, drops layers whose
                           mode or colours can't be trusted (each one reported in
                           `warnings`), sorts stops ascending (stably), scales opacity by
                           `strength` and clamps it.
     gradientCss(layer, angle)        -- 'linear-gradient(180deg, #fff 0%, ...)'
     gradientEndpoints(w, h, angle)   -- {x0,y0,x1,y1} for ctx.createLinearGradient, using
                                         CSS's own gradient-line geometry.
     imageAdjustCss(idOrRecipe)       -- 'brightness(1.02) contrast(0.74) saturate(1.02)', or ''.
     swatchLayers(idOrRecipe)         -- layers for a picker tile (the gradients alone).
   DOM / canvas (these touch the document):
     renderSwatch(el, idOrRecipe)     -- fill `el` with that filter's gradient tile.
     applyPreview(host, id, opts)     -- live CSS preview: stacks overlay divs inside `host`
                                         over its <img>/<canvas>/<video>. No network, no copy
                                         of the pixels. Returns the normalizeLayers result.
     clearPreview(host, opts)         -- undo applyPreview.
     composite(source, id, opts)      -- bake the filter into a NEW <canvas> and return it.
     toDataURL(source, id, opts)      -- composite -> data: URL string.
     toBlob(source, id, opts)         -- composite -> Promise<Blob>, for saving.

   Export caveat worth knowing before you wire a Save button: composite() draws the source
   into a canvas, so if that source was loaded cross-origin without CORS the canvas is
   tainted and toDataURL/toBlob throw a SecurityError. Images served by this app's own
   gallery routes are same-origin and fine; a PixAI CDN URL dropped straight into an <img>
   is not, and needs crossOrigin="anonymous". */
/* Ported from static/mg-art-filters.js into the React/Vite build (2026-08-08,
   the vanilla static/ -> React campaign). The IIFE body is kept VERBATIM -- this
   is an engine (gradient/canvas compositing behind the already-React FiltersPanel),
   so it becomes an ES MODULE, not a component; only the boundary changed:
   `window.MgArtFilters = {...}` is now a returned + default-exported const. */
const MgArtFilters = (function () {
  'use strict';

  var SOURCE_URL = 'https://api.pixai.art/config/imageArtFilters';
  var CAPTURED = '2026-07-25';    // last date the baked copy was verified against SOURCE_URL
  var DEFAULT_ANGLE_DEG = 180;   // CSS 180deg == top to bottom

  // ---- the recipes, verbatim from the endpoint (see CAPTURED) -------------------------
  // Left exactly as served, quirks and all, so a refresh is a paste and any weirdness
  // stays visible: filter-v1-m1/f1 declares its stops BACKWARDS (position 1 before 0), and
  // filter-v1-m6/f1 declares THREE stops on two positions (1, 0.6, 1). normalizeLayers()
  // is what makes those renderable; nothing is pre-massaged here.
  var FILTERS = [
    {
      id: 'filter-v1-m1', version: 1, name: 'Filter M1',
      filters: [
        { name: 'f1', enabled: true, blendMode: 'darker-color', blendOpacity: 0.9,
          stops: [{ color: 'rgba(215, 255, 223, 1)', position: 1 },
                  { color: '#ffffff', position: 0 }] },
        { name: 'f2', enabled: true, blendMode: 'soft-light', blendOpacity: 0.7,
          stops: [{ color: 'rgba(179, 250, 255, 1)', position: 0 },
                  { color: 'rgba(117, 48, 227, 1)', position: 1 }] }
      ]
    },
    {
      id: 'filter-v1-m2', version: 1, name: 'Filter M2',
      filters: [
        { name: 'f1', enabled: true, blendMode: 'darker-color', blendOpacity: 0.45,
          stops: [{ color: 'rgba(95, 78, 197, 1)', position: 0 },
                  { color: 'rgba(255, 249, 210, 1)', position: 1 }] },
        { name: 'f2', enabled: true, blendMode: 'color-burn', blendOpacity: 0.7,
          stops: [{ color: 'rgba(255, 181, 0, 1)', position: 0 },
                  { color: 'rgba(255, 128, 213, 1)', position: 1 }] },
        { name: 'f3', enabled: true, blendMode: 'lighter-color', blendOpacity: 0.4,
          stops: [{ color: 'rgba(163, 196, 223, 1)', position: 1 },
                  { color: 'rgba(111, 145, 186, 1)', position: 0 }] }
      ]
    },
    {
      id: 'filter-v1-m3', version: 1, name: 'Filter M3',
      filters: [
        { name: 'f1', enabled: true, blendMode: 'plus-lighter', blendOpacity: 0.39,
          stops: [{ color: 'rgba(0, 238, 236, 1)', position: 0 },
                  { color: 'rgba(255, 203, 221, 1)', position: 1 }] },
        { name: 'f2', enabled: true, blendMode: 'saturation', blendOpacity: 0.43,
          stops: [{ color: 'rgba(68, 47, 93, 1)', position: 0 },
                  { color: 'rgba(244, 157, 173, 1)', position: 1 }] }
      ]
    },
    {
      id: 'filter-v1-m4', version: 1, name: 'Filter M4',
      filters: [
        { name: 'f1', enabled: true, blendMode: 'soft-light', blendOpacity: 0.54,
          stops: [{ color: 'rgba(255, 194, 161, 1)', position: 0 },
                  { color: 'rgba(255, 177, 189, 1)', position: 1 }] },
        { name: 'f2', enabled: true, blendMode: 'color-burn', blendOpacity: 0.85,
          stops: [{ color: 'rgba(215, 214, 77, 1)', position: 0 },
                  { color: 'rgba(254, 169, 191, 1)', position: 0.5 },
                  { color: 'rgba(206, 255, 186, 1)', position: 1 }] }
      ],
      image_parameters: { brightness: 0.04, contrast: 0.05, saturation: 0.1 }
    },
    {
      id: 'filter-v1-m5', version: 1, name: 'Filter M5',
      filters: [
        { name: 'f1', enabled: true, blendMode: 'darker-color', blendOpacity: 0.22,
          stops: [{ color: 'rgba(255, 204, 206, 1)', position: 0 },
                  { color: 'rgba(255, 218, 123, 1)', position: 1 }] },
        { name: 'f2', enabled: true, blendMode: 'soft-light', blendOpacity: 0.9,
          stops: [{ color: 'rgba(255, 154, 173, 1)', position: 0 },
                  { color: 'rgba(255, 238, 255, 1)', position: 1 }] }
      ],
      image_parameters: { brightness: 0.02, contrast: -0.26, saturation: 0.02 }
    },
    {
      id: 'filter-v1-m6', version: 1, name: 'Filter M6',
      filters: [
        { name: 'f1', enabled: true, blendMode: 'lighter-color', blendOpacity: 0.4,
          stops: [{ color: '#f4e4c1', position: 1 },
                  { color: 'rgba(234, 118, 88, 1)', position: 0.6 },
                  { color: 'rgba(0, 17, 49, 1)', position: 1 }] },
        { name: 'f2', enabled: true, blendMode: 'screen', blendOpacity: 0.16,
          stops: [{ color: 'rgba(250, 243, 98, 1)', position: 0 },
                  { color: 'rgba(235, 41, 171, 1)', position: 0.6 },
                  { color: 'rgba(0, 17, 49, 1)', position: 1 }] }
      ],
      image_parameters: { brightness: 0, contrast: 0, saturation: 0.12 }
    },
    {
      id: 'filter-v1-m7', version: 1, name: 'Filter M7',
      filters: [
        { name: 'f1', enabled: true, blendMode: 'overlay', blendOpacity: 0.81,
          stops: [{ color: 'rgba(179, 250, 255, 1)', position: 0 },
                  { color: 'rgba(117, 48, 227, 1)', position: 1 }] },
        { name: 'f2', enabled: true, blendMode: 'soft-light', blendOpacity: 0.4,
          stops: [{ color: 'rgba(150, 197, 255, 1)', position: 0 },
                  { color: '#ffffff', position: 1 }] }
      ],
      image_parameters: { brightness: 0.02, contrast: -0.06, saturation: 0 }
    }
  ];

  // ---- the Moonglade set: ours, derived from this app's own skins ---------------------
  // Authored here, not fetched: each one takes its skin's accent and lead colours out of
  // SKINS in moonglade_gallery.py, so a filtered image reads as this app rather than as a
  // generic wash. Same key shape as PixAI's payload, so normalizeLayers() and both renderers
  // treat them identically and neither array needs a special case anywhere.
  //
  // Kept OUT of FILTERS deliberately -- see this file's header. Every blend mode below is one
  // of the six exact ones; no image_parameters, so what shipped is what was approved as
  // swatches. The skin each palette came from is named on the recipe so a skin retint can be
  // traced back to the filter that has to move with it.
  var MOONGLADE_FILTERS = [
    {
      id: 'mg-moonglade', version: 1, name: 'Moonglade', skin: 'moonglade',
      note: 'The default skin. Lavender leads, emerald in the shadows.',
      filters: [
        { name: 'f1', enabled: true, blendMode: 'soft-light', blendOpacity: 0.6,
          stops: [{ color: '#b692e6', position: 0 },
                  { color: '#4fc99a', position: 1 }] },
        { name: 'f2', enabled: true, blendMode: 'screen', blendOpacity: 0.2,
          stops: [{ color: '#0c0a1c', position: 0 },
                  { color: '#3a3460', position: 1 }] }
      ]
    },
    {
      id: 'mg-nightfallen', version: 1, name: 'Nightfallen', skin: 'nightfallen',
      note: 'Void-touched. Crushes the darks, keeps a violet bloom up top.',
      filters: [
        { name: 'f1', enabled: true, blendMode: 'color-burn', blendOpacity: 0.42,
          stops: [{ color: '#241a3f', position: 0 },
                  { color: '#a678f0', position: 1 }] },
        { name: 'f2', enabled: true, blendMode: 'soft-light', blendOpacity: 0.55,
          stops: [{ color: '#c9a6ff', position: 0 },
                  { color: '#080610', position: 1 }] }
      ]
    },
    {
      id: 'mg-moonlit', version: 1, name: 'Moonlit Silver', skin: 'moonlit',
      note: 'Cold silver and glacier blue. The gentlest of the five -- good on portraits.',
      filters: [
        { name: 'f1', enabled: true, blendMode: 'soft-light', blendOpacity: 0.6,
          stops: [{ color: '#bcd6f5', position: 0 },
                  { color: '#8fb8e8', position: 1 }] },
        { name: 'f2', enabled: true, blendMode: 'screen', blendOpacity: 0.18,
          stops: [{ color: '#0b1018', position: 0 },
                  { color: '#334358', position: 1 }] }
      ]
    },
    {
      id: 'mg-ember', version: 1, name: 'Embercourt', skin: 'ember',
      note: 'Warm venthyr gold. The only one of the five that pushes contrast up.',
      filters: [
        { name: 'f1', enabled: true, blendMode: 'overlay', blendOpacity: 0.48,
          stops: [{ color: '#e8935f', position: 0 },
                  { color: '#f0b48f', position: 1 }] },
        { name: 'f2', enabled: true, blendMode: 'color-burn', blendOpacity: 0.32,
          stops: [{ color: '#5a352c', position: 0 },
                  { color: '#160c0c', position: 1 }] }
      ]
    },
    {
      id: 'mg-verdant', version: 1, name: 'Verdant Grove', skin: 'verdant',
      note: 'Deep moss. The strongest colour shift of the set.',
      filters: [
        { name: 'f1', enabled: true, blendMode: 'soft-light', blendOpacity: 0.6,
          stops: [{ color: '#8fe8bf', position: 0 },
                  { color: '#5fd39a', position: 1 }] },
        { name: 'f2', enabled: true, blendMode: 'color-burn', blendOpacity: 0.38,
          stops: [{ color: '#173026', position: 0 },
                  { color: '#2a5140', position: 1 }] }
      ]
    }
  ];

  // Rail order: ours first -- they are the house set, and the panel groups them under their
  // own heading. ALL_FILTERS is what get()/list() walk, so nothing downstream has to know
  // there are two arrays.
  var GROUPS = [
    { source: 'moonglade', label: 'Moonglade', filters: MOONGLADE_FILTERS },
    { source: 'pixai', label: 'PixAI', filters: FILTERS }
  ];
  var ALL_FILTERS = GROUPS.reduce(function (acc, g) { return acc.concat(g.filters); }, []);

  // ---- blend-mode mapping (the table in this file's header, as data) -------------------
  var BLEND_MODE_MAP = {
    'darker-color': {
      css: 'darken', canvas: 'darken', exact: false,
      note: "Photoshop's Darker Color keeps whichever whole colour is darker; CSS/canvas " +
            "darken takes the per-channel minimum, which can emit a colour present in " +
            "neither input. Closest available -- differs where a gradient crosses the hue."
    },
    'lighter-color': {
      css: 'lighten', canvas: 'lighten', exact: false,
      note: "Photoshop's Lighter Color keeps whichever whole colour is lighter; CSS/canvas " +
            "lighten takes the per-channel maximum. Same approximation as darker-color."
    },
    'soft-light':   { css: 'soft-light', canvas: 'soft-light', exact: true },
    'color-burn':   { css: 'color-burn', canvas: 'color-burn', exact: true },
    'screen':       { css: 'screen', canvas: 'screen', exact: true },
    'overlay':      { css: 'overlay', canvas: 'overlay', exact: true },
    'saturation':   { css: 'saturation', canvas: 'saturation', exact: true },
    'plus-lighter': {
      css: 'plus-lighter', canvas: 'lighter', exact: true,
      note: "Same additive (Porter-Duff 'plus') operator in both, only the spelling " +
            "differs: canvas has no 'plus-lighter', it calls it 'lighter'."
    }
  };

  function blendModeFor(mode, target) {
    if (target !== 'css' && target !== 'canvas') {
      throw new Error("mg-art-filters: blendModeFor target must be 'css' or 'canvas', got " +
                      JSON.stringify(target));
    }
    var e = BLEND_MODE_MAP[mode];
    // Deliberately null, not a default: see this file's header. An unmapped mode has to be
    // dropped and reported, because rendering it as `normal` looks like a working filter.
    return e ? e[target] : null;
  }

  // ---- helpers ------------------------------------------------------------------------
  // Only the two colour forms the payload actually uses (hex and rgb/rgba). Every stop
  // colour ends up concatenated into a CSS `linear-gradient(...)` string, so a stop that
  // isn't a colour literal is a way into that string -- and while the baked recipes are
  // trusted, normalizeLayers() also accepts a freshly re-fetched payload.
  var SAFE_COLOR = /^(#[0-9a-fA-F]{3,8}|rgba?\(\s*[\d.,%\s]+\s*\))$/;

  function clamp01(n) { return n < 0 ? 0 : (n > 1 ? 1 : n); }
  // Trims float noise so a 0.22 opacity scaled by a 0.8 strength reaches the DOM as
  // '0.176' rather than '0.17600000000000002', and so canvas globalAlpha and CSS opacity
  // end up the same number rather than differing in the 17th digit.
  function round4(n) { return Math.round(n * 1e4) / 1e4; }
  function num(n) { return String(round4(n)); }

  function get(id) {
    for (var i = 0; i < ALL_FILTERS.length; i++)
      if (ALL_FILTERS[i].id === id) return ALL_FILTERS[i];
    return null;
  }
  function list() { return ALL_FILTERS.map(function (f) { return f.id; }); }
  // For a UI that wants headed sections rather than one undifferentiated strip. Returns ids,
  // not recipes, so a caller can't mutate the baked data through it.
  function groups() {
    return GROUPS.map(function (g) {
      return { source: g.source, label: g.label,
               ids: g.filters.map(function (f) { return f.id; }) };
    });
  }

  function resolve(idOrRecipe) {
    if (idOrRecipe && typeof idOrRecipe === 'object') return idOrRecipe;
    var r = get(idOrRecipe);
    if (!r) throw new Error('mg-art-filters: no such filter: ' + idOrRecipe);
    return r;
  }

  function normalizeLayers(idOrRecipe, opts) {
    var recipe = resolve(idOrRecipe);
    var o = opts || {};
    var strength = (o.strength == null) ? 1 : Number(o.strength);
    if (!isFinite(strength)) strength = 1;
    var warnings = [];
    var layers = [];
    (recipe.filters || []).forEach(function (L) {
      if (L.enabled === false) return;                 // dropped, not drawn at zero
      var css = blendModeFor(L.blendMode, 'css');
      var canvas = blendModeFor(L.blendMode, 'canvas');
      if (!css || !canvas) {
        warnings.push('dropped layer "' + (L.name || '?') + '" of ' + recipe.id +
                      ': unmapped blend mode "' + L.blendMode + '"');
        return;
      }
      var stops = (L.stops || []).filter(function (s) {
        if (s && typeof s.color === 'string' && SAFE_COLOR.test(s.color)) return true;
        warnings.push('dropped an unrecognised stop colour in "' + (L.name || '?') +
                      '" of ' + recipe.id + ': ' + JSON.stringify(s && s.color));
        return false;
      }).map(function (s, i) {
        return { color: s.color, position: clamp01(Number(s.position) || 0), _i: i };
      });
      // A gradient needs its stops ascending -- CSS clamps a descending stop up to the
      // previous one, which collapses the whole gradient into a flat band, and canvas's
      // addColorStop is order-independent but reads wrong next to the CSS path. The sort
      // must be STABLE: filter-v1-m6/f1 has two different colours on position 1, and their
      // declared order is what decides which one wins at the 100% end.
      stops.sort(function (a, b) { return (a.position - b.position) || (a._i - b._i); });
      stops.forEach(function (s) { delete s._i; });
      layers.push({
        name: L.name || '',
        blendMode: L.blendMode,
        css: css,
        canvas: canvas,
        opacity: round4(clamp01(Number(L.blendOpacity) * strength)),
        stops: stops
      });
    });
    return { id: recipe.id, layers: layers, warnings: warnings };
  }

  function gradientCss(layer, angle) {
    var a = (angle == null) ? DEFAULT_ANGLE_DEG : angle;
    var parts = layer.stops.map(function (s) {
      return s.color + ' ' + num(s.position * 100) + '%';
    });
    return 'linear-gradient(' + num(a) + 'deg, ' + parts.join(', ') + ')';
  }

  // CSS's gradient-line geometry, so a canvas export lines up with the CSS preview instead
  // of merely looking similar: 0deg points up and the angle runs clockwise, the line passes
  // through the box centre, and its length is |w*sin| + |h*cos| -- which for anything off
  // the four axes is LONGER than the box side, and shorter than the diagonal.
  function gradientEndpoints(w, h, angle) {
    var a = (angle == null) ? DEFAULT_ANGLE_DEG : angle;
    var t = axisTrig(a);
    var dx = t.s, dy = -t.c;                       // screen coords: y grows downward
    var len = Math.abs(w * t.s) + Math.abs(h * t.c);
    var cx = w / 2, cy = h / 2, half = len / 2;
    return { x0: cx - dx * half, y0: cy - dy * half, x1: cx + dx * half, y1: cy + dy * half };
  }

  // Math.sin(Math.PI) is 1.22e-16, not 0, and that error survives into the endpoints as a
  // fractional-pixel skew on what should be a dead-straight top-to-bottom gradient. The
  // four axis angles -- which include the default 180 -- are returned exactly.
  function axisTrig(deg) {
    var r = ((Number(deg) % 360) + 360) % 360;
    if (r === 0) return { s: 0, c: 1 };
    if (r === 90) return { s: 1, c: 0 };
    if (r === 180) return { s: 0, c: -1 };
    if (r === 270) return { s: -1, c: 0 };
    var rad = r * Math.PI / 180;
    return { s: Math.sin(rad), c: Math.cos(rad) };
  }

  // brightness/contrast/saturation are signed offsets from 1 (see this file's header).
  // A zero offset is a no-op and is omitted rather than emitted as brightness(1), so a
  // filter with no real adjustment yields '' and no filter property is set at all.
  function imageAdjustCss(idOrRecipe) {
    var p = resolve(idOrRecipe).image_parameters;
    if (!p) return '';
    var out = [];
    if (p.brightness) out.push('brightness(' + num(1 + p.brightness) + ')');
    if (p.contrast) out.push('contrast(' + num(1 + p.contrast) + ')');
    if (p.saturation) out.push('saturate(' + num(1 + p.saturation) + ')');
    return out.join(' ');
  }

  // A swatch has no image under it, so the bottom layer is forced opaque and `normal`:
  // filter-v1-m5's first layer is 0.22 opacity over nothing, which would render as a
  // near-blank tile. Everything above it keeps its own mode and opacity, so the seven tiles
  // stay visually distinct and are built only from each recipe's own gradients -- the
  // payload carries no separate swatch definition to copy.
  function swatchLayers(idOrRecipe) {
    var layers = normalizeLayers(idOrRecipe).layers.map(function (L) {
      return { name: L.name, blendMode: L.blendMode, css: L.css, canvas: L.canvas,
               opacity: L.opacity, stops: L.stops };
    });
    if (layers.length) { layers[0] = Object.assign({}, layers[0], { css: 'normal', canvas: 'source-over', opacity: 1 }); }
    return layers;
  }

  // ---- DOM: one injected <style>, same convention as the other static/mg-*.js ----------
  // `isolation:isolate` is the load-bearing line: without it mix-blend-mode blends the
  // overlays against everything painted behind the container as well, so the same filter
  // looks different depending on the page background it happens to be mounted over.
  var STYLE_ID = 'mg-art-filters-style';
  var CSS = [
    '.mgaf-stage,.mgaf-swatch{position:relative;isolation:isolate;}',
    '.mgaf-stage{display:inline-block;line-height:0;}',
    '.mgaf-stage>[data-mgaf-layer],.mgaf-swatch>[data-mgaf-layer]{position:absolute;',
    ' inset:0;pointer-events:none;}',
    '.mgaf-swatch{display:block;overflow:hidden;}'
  ].join('');

  function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = CSS;
    (document.head || document.documentElement).appendChild(s);
  }

  function clearLayers(host) {
    var old = host.querySelectorAll(':scope > [data-mgaf-layer]');
    for (var i = 0; i < old.length; i++) old[i].parentNode.removeChild(old[i]);
  }

  function buildLayerDivs(host, layers, angle) {
    layers.forEach(function (L) {
      var d = document.createElement('div');
      d.setAttribute('data-mgaf-layer', L.name || '');
      d.style.backgroundImage = gradientCss(L, angle);
      d.style.mixBlendMode = L.css;
      d.style.opacity = String(L.opacity);
      host.appendChild(d);
    });
  }

  function renderSwatch(el, idOrRecipe, opts) {
    injectStyle();
    var o = opts || {};
    el.classList.add('mgaf-swatch');
    clearLayers(el);
    buildLayerDivs(el, swatchLayers(idOrRecipe), o.angle);
    return el;
  }

  // Live preview with zero pixel work: the image stays the image, the overlays are divs.
  // `host` should wrap only the target media -- any other child of it ends up beneath the
  // overlays too.
  function applyPreview(host, idOrRecipe, opts) {
    injectStyle();
    var o = opts || {};
    var n = normalizeLayers(idOrRecipe, o);
    var target = o.target || host.querySelector('img,canvas,video');
    host.classList.add('mgaf-stage');
    clearLayers(host);
    if (target) target.style.filter = imageAdjustCss(idOrRecipe);
    buildLayerDivs(host, n.layers, o.angle);
    return n;
  }

  function clearPreview(host, opts) {
    var o = opts || {};
    var target = o.target || host.querySelector('img,canvas,video');
    if (target) target.style.filter = '';
    clearLayers(host);
    host.classList.remove('mgaf-stage');
    return host;
  }

  // ---- canvas: the same recipe, baked into pixels for export --------------------------
  function composite(source, idOrRecipe, opts) {
    var o = opts || {};
    var n = normalizeLayers(idOrRecipe, o);
    var w = o.width || source.naturalWidth || source.videoWidth || source.width;
    var h = o.height || source.naturalHeight || source.videoHeight || source.height;
    if (!w || !h) {
      throw new Error('mg-art-filters: source has no intrinsic size yet -- wait for the ' +
                      "image's load event, or pass {width, height}");
    }
    var canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    var ctx = canvas.getContext('2d');
    var adjust = imageAdjustCss(idOrRecipe);
    if (adjust) {
      // ctx.filter is the canvas twin of the CSS filter the preview puts on the <img>.
      // Where it is missing the composite is still correct in its gradients and only
      // loses the brightness/contrast/saturation trim, so it degrades rather than fails.
      if ('filter' in ctx) ctx.filter = adjust;
      else n.warnings.push("this canvas has no ctx.filter -- skipped " + adjust);
    }
    ctx.drawImage(source, 0, 0, w, h);
    if ('filter' in ctx) ctx.filter = 'none';
    var g = gradientEndpoints(w, h, o.angle);
    n.layers.forEach(function (L) {
      var grad = ctx.createLinearGradient(g.x0, g.y0, g.x1, g.y1);
      L.stops.forEach(function (s) { grad.addColorStop(s.position, s.color); });
      ctx.globalCompositeOperation = L.canvas;
      ctx.globalAlpha = L.opacity;
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, w, h);
    });
    // Put the context back: a blend op or a partial alpha left set is the classic way a
    // later unrelated draw on the same context comes out wrong.
    ctx.globalCompositeOperation = 'source-over';
    ctx.globalAlpha = 1;
    canvas.mgafWarnings = n.warnings;
    return canvas;
  }

  function toDataURL(source, idOrRecipe, opts) {
    var o = opts || {};
    return composite(source, idOrRecipe, o).toDataURL(o.mime || 'image/png', o.quality);
  }

  function toBlob(source, idOrRecipe, opts) {
    var o = opts || {};
    var canvas = composite(source, idOrRecipe, o);
    return new Promise(function (resolve_, reject) {
      canvas.toBlob(function (b) {
        if (b) resolve_(b);
        else reject(new Error('mg-art-filters: canvas.toBlob produced nothing'));
      }, o.mime || 'image/png', o.quality);
    });
  }

  return {
    SOURCE_URL: SOURCE_URL,
    CAPTURED: CAPTURED,
    DEFAULT_ANGLE_DEG: DEFAULT_ANGLE_DEG,
    FILTERS: FILTERS,
    MOONGLADE_FILTERS: MOONGLADE_FILTERS,
    BLEND_MODE_MAP: BLEND_MODE_MAP,
    list: list,
    get: get,
    groups: groups,
    blendModeFor: blendModeFor,
    normalizeLayers: normalizeLayers,
    gradientCss: gradientCss,
    gradientEndpoints: gradientEndpoints,
    imageAdjustCss: imageAdjustCss,
    swatchLayers: swatchLayers,
    renderSwatch: renderSwatch,
    applyPreview: applyPreview,
    clearPreview: clearPreview,
    composite: composite,
    toDataURL: toDataURL,
    toBlob: toBlob
  };
})();

export default MgArtFilters;
