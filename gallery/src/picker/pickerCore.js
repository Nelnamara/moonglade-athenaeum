/* picker-core.js -- shared browse/filter/paginate/infinite-scroll logic for BOTH image
   pickers in this app: the gallery's vanilla-JS `Picker` IIFE (moonglade_gallery.py) and the
   Loom's React `GalleryPick` component (loom/master-storyboard.jsx). Both fetch the same
   /api/gallery-images + /api/collections and reimplemented the same querystring/paging/
   debounce/scroll logic twice; this is the ONE place that logic lives now.

   Framework-agnostic on purpose: no DOM nodes, no React elements, no JSX. A caller
   configures it with plain data + callbacks and drives it imperatively; each surface
   renders the results however its own markup/CSS wants to (gallery: .pick-cell divs;
   Loom: .sb-pick-cell JSX). No build step -- attaches to `window.PickerCore`, loaded via
   a plain <script src> tag (mirrors how the Loom already gets React/ReactDOM as globals). */
/* Ported from static/picker-core.js into the React/Vite build (2026-08-08, the
   vanilla static/ -> React campaign). Framework-agnostic browse/filter/paginate/
   infinite-scroll engine behind GalleryPicker; the IIFE body is kept VERBATIM,
   only the boundary changed: `global.PickerCore = {...}` is now a returned +
   default-exported const. */
const PickerCore = (function () {
  'use strict';

  function createPickerCore(opts) {
    opts = opts || {};
    var endpoint = opts.endpoint || '/api/gallery-images';
    var collectionsEndpoint = opts.collectionsEndpoint || '/api/collections';
    var pageSize = opts.pageSize || 60;
    var debounceMs = opts.debounceMs == null ? 280 : opts.debounceMs;
    var maxAutoFillPage = opts.maxAutoFillPage || 4;
    var onResults = opts.onResults || function () {};
    var onCollections = opts.onCollections || function () {};
    var onError = opts.onError || function () {};

    // Filters are seeded PER INSTANCE, not defaulted once here -- in particular `type`
    // must stay '' for the gallery Picker (server already treats '' the same as absent,
    // defaulting to "image" -- see /api/gallery-images's `gtype or "image"`) so its
    // behavior is byte-identical to before this refactor. The Loom seeds its own
    // defaultType per open() call. Getting this backwards would make the gallery
    // Picker start surfacing videos it never has.
    var filters = Object.assign({
      q: '', collection: '', source: '', type: '', rating_min: 0, sort: 'newest'
    }, opts.defaultFilters || {});

    var page = 1, loading = false, hasMore = false, debounceTimer = null, destroyed = false;
    var loadSeq = 0;

    function qs(p) {
      var enc = encodeURIComponent;
      return endpoint + '?limit=' + pageSize + '&page=' + p +
        '&q=' + enc(filters.q || '') +
        '&collection=' + enc(filters.collection || '') +
        '&source=' + enc(filters.source || '') +
        '&type=' + enc(filters.type || '') +
        '&rating_min=' + enc(filters.rating_min || 0) +
        '&sort=' + enc(filters.sort || 'newest');
    }

    function fetchCollections() {
      fetch(collectionsEndpoint).then(function (r) { return r.json(); })
        .then(function (d) { if (!destroyed) onCollections(d.collections || []); })
        .catch(function (e) { onError(e); });
    }

    function load(append) {
      // Only APPENDS are deduped by the in-flight guard. A filter/query change (append
      // false) must always win: the old `if (loading) return` dropped it outright, and
      // the scroll-triggered page-2 fetch it lost to then appended the OLD filter's
      // results into the grid anyway. `loadSeq` is the same superseded-response token
      // <UpscalePanel>'s doPrice() uses -- a fetch that a newer load has replaced
      // resolves into a no-op instead of clobbering the grid (and leaves `loading`
      // alone, because the load that replaced it owns that flag now).
      if (loading && append) return;
      loading = true;
      var atPage = page;
      var mine = ++loadSeq;
      fetch(qs(atPage)).then(function (r) { return r.json(); }).then(function (d) {
        if (mine !== loadSeq) return;
        loading = false;
        if (destroyed) return;
        var imgs = d.images || [];
        hasMore = ((d.page || atPage) * (d.limit || pageSize)) < (d.total || 0);
        onResults(imgs, { total: d.total || 0, append: !!append, hasMore: hasMore, page: atPage });
      }).catch(function (e) { if (mine !== loadSeq) return; loading = false; onError(e); });
    }

    function reload() { page = 1; load(false); }

    function setFilter(key, value) { filters[key] = value; page = 1; load(false); }

    function setFilters(patch) { Object.assign(filters, patch || {}); page = 1; load(false); }

    function setQuery(q, ms) {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function () {
        filters.q = q; page = 1; load(false);
      }, ms == null ? debounceMs : ms);
    }

    function loadMore() { if (hasMore && !loading) { page++; load(true); } }

    // Auto-pull extra pages if the grid doesn't yet overflow (no scrollbar => infinite
    // scroll can never trigger). Capped at maxAutoFillPage so a tall/glitched layout
    // can't runaway-load; a "Load more" control (where one exists) covers the rest.
    function maybeFillPage(gridEl) {
      if (hasMore && !loading && page < maxAutoFillPage &&
          gridEl && gridEl.scrollHeight <= gridEl.clientHeight + 4) {
        page++; load(true);
      }
    }

    function onScroll(gridEl, thresholdPx) {
      if (!gridEl) return;
      var t = thresholdPx == null ? 320 : thresholdPx;
      if (hasMore && !loading && gridEl.scrollTop + gridEl.clientHeight > gridEl.scrollHeight - t) {
        loadMore();
      }
    }

    function destroy() { destroyed = true; clearTimeout(debounceTimer); }

    return {
      setQuery: setQuery, setFilter: setFilter, setFilters: setFilters, reload: reload,
      loadMore: loadMore, maybeFillPage: maybeFillPage, onScroll: onScroll,
      fetchCollections: fetchCollections, destroy: destroy,
      getFilters: function () { return Object.assign({}, filters); },
      getPage: function () { return page; },
      hasMore: function () { return hasMore; }
    };
  }

  return { create: createPickerCore };
})();

export default PickerCore;
