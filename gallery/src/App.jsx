import React, { useCallback, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import ArtBand from "./components/ArtBand.jsx";
import Strip from "./components/Strip.jsx";
import Grid from "./components/Grid.jsx";
import Lightbox from "./components/Lightbox.jsx";
import DetailsView from "./components/DetailsView.jsx";
import GenerateDrawer from "./components/GenerateDrawer.jsx";
import PickerHost from "./components/PickerHost.jsx";
import {
  fetchLibrary, fetchAccount, fetchCollections,
  postForm, downloadZipForm, resolveVideoIds,
} from "./api.js";

const ADV_DEFAULTS = {
  sort: "newest", ratingMin: 0, model: "", lora: "",
  dateFrom: "", dateTo: "", source: "", tag: "", publishedOnly: false,
  // Not a flyout field -- set only via the Details view's "View batch" link.
  batch: "",
};

export default function App({ boot }) {
  // filters
  const [media, setMedia] = useState("");
  const [shelf, setShelf] = useState("");
  const [perPage, setPerPage] = useState(100);
  const [query, setQuery] = useState("");
  const [applied, setApplied] = useState("");
  const [adv, setAdv] = useState(ADV_DEFAULTS);
  const [flyOpen, setFlyOpen] = useState(false);
  // data
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(null);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [loading, setLoading] = useState(false);
  const [account, setAccount] = useState(null);
  const [collections, setCollections] = useState(boot.collections || []);
  // ui -- blur shares the classic gallery's localStorage key on purpose: one
  // setting, both surfaces, exactly the classic semantics (all thumbs 16px,
  // flagged 28px, hover reveals).
  const [blur, setBlurState] = useState(
    () => localStorage.getItem("gallery_privacy_blur") === "1"
  );
  const setBlur = (v) => {
    localStorage.setItem("gallery_privacy_blur", v ? "1" : "");
    setBlurState(v);
  };
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState(() => new Set());
  const [lbIndex, setLbIndex] = useState(null);
  const [genOpen, setGenOpen] = useState(false);
  const reqSeq = useRef(0);

  /* The Details view -- "the layer deeper" (owner, 2026-07-30), a real
     bookmarkable URL via the History API rather than a modal-only state
     swap, matching classic's genuinely separate /image/<mid> page. Reads
     ?image= on first load so a shared/bookmarked link opens straight there;
     back/forward (popstate) stays in sync since pushState never fires it. */
  const [detailsFor, setDetailsFor] = useState(
    () => new URLSearchParams(window.location.search).get("image") || null
  );
  /* The locked Direction C morph (docs/DECISIONS.md, artifact 477b4655): the
     image the owner was already looking at slides/resizes into the Details
     hero frame in place, via the native View Transitions API rather than a
     hand-rolled animation -- both ends carry the same view-transition-name
     ("vt-reveal": Lightbox.jsx's stage image, DetailsView.jsx's placard-frame).
     flushSync is required here -- without it React's own batching would defer
     the state update past the transition callback, and the browser would
     capture identical "before"/"after" snapshots. Feature-detected: browsers
     without support (pre-111 Firefox/Safari) just get the plain instant swap
     they already had. */
  const openDetails = (mid) => {
    const commit = () => {
      setLbIndex(null);
      window.history.pushState({}, "", "/next?image=" + encodeURIComponent(mid));
      setDetailsFor(mid);
    };
    if (document.startViewTransition) document.startViewTransition(() => flushSync(commit));
    else commit();
  };
  const closeDetails = () => {
    window.history.pushState({}, "", "/next");
    setDetailsFor(null);
  };
  useEffect(() => {
    const onPop = () => setDetailsFor(new URLSearchParams(window.location.search).get("image") || null);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const filterByModel = (name) => {
    closeDetails();
    setAdv((old) => ({ ...old, model: name }));
  };
  const filterByBatch = (batch) => {
    closeDetails();
    setAdv((old) => ({ ...old, batch }));
  };

  /* Generation completions refresh the library + credits chip.
     THREE channels, because there are three producers:
     - mg-gen-done: our own image submit path (useGenerate);
     - mg-submit:   the SHARED video drawer accepting a task -- it owns its own
                    poll, so it gets Jobs.register (never Jobs.track, which
                    would double-poll: the Loom's pinned contract);
     - mg-result:   that drawer finishing, which is when credits actually moved. */
  useEffect(() => {
    const refresh = () => { load(1, true); fetchAccount().then(setAccount); };
    const onSubmit = (e) => {
      const id = e.detail && (e.detail.task_id || e.detail.taskId);
      if (id && window.Jobs) window.Jobs.register(id, "Rendered");
    };
    const onResult = () => { refresh(); if (window.JobsCard) window.JobsCard.refresh(); };
    window.addEventListener("mg-gen-done", refresh);
    document.addEventListener("mg-submit", onSubmit);
    document.addEventListener("mg-result", onResult);
    return () => {
      window.removeEventListener("mg-gen-done", refresh);
      document.removeEventListener("mg-submit", onSubmit);
      document.removeEventListener("mg-result", onResult);
    };
  }); // eslint-disable-line react-hooks/exhaustive-deps

  const load = useCallback(
    async (p, replace) => {
      const seq = ++reqSeq.current;
      setLoading(true);
      try {
        const data = await fetchLibrary({
          q: applied, media, collection: shelf,
          page: p, page_size: perPage,
          sort: adv.sort !== "newest" ? adv.sort : "",
          rating_min: adv.ratingMin || "",
          model: adv.model, lora: adv.lora,
          from: adv.dateFrom, to: adv.dateTo,
          source: adv.source, tag: adv.tag,
          published: adv.publishedOnly ? "1" : "",
          batch: adv.batch,
        });
        if (seq !== reqSeq.current) return; // a newer request superseded this one
        setItems((old) => (replace ? data.items : old.concat(data.items)));
        setTotal(data.total);
        setPage(data.page);
        setPages(data.pages);
        return data; // the lightbox's page-boundary step needs the fresh page synchronously
      } finally {
        if (seq === reqSeq.current) setLoading(false);
      }
    },
    [applied, media, shelf, perPage, adv]
  );

  // The flyout commits a patch: advanced fields always; q/media/shelf/perPage
  // only when a saved view carries them.
  const applyAdvanced = (patch) => {
    const next = {};
    for (const k of Object.keys(ADV_DEFAULTS)) if (k in patch) next[k] = patch[k];
    setAdv((old) => ({ ...old, ...next }));
    if ("q" in patch) { setQuery(patch.q); setApplied(patch.q); }
    if ("media" in patch) setMedia(patch.media);
    if ("shelf" in patch) setShelf(patch.shelf);
    if (patch.perPage) setPerPage(patch.perPage);
    setFlyOpen(false);
  };
  const advCount = Object.keys(ADV_DEFAULTS).filter(
    (k) => JSON.stringify(adv[k]) !== JSON.stringify(ADV_DEFAULTS[k])
  ).length;

  // any filter change restarts from page 1
  useEffect(() => { load(1, true); }, [load]);
  useEffect(() => { fetchAccount().then(setAccount); }, []);

  const submitQuery = (forced) => {
    setApplied(forced !== undefined ? forced : query);
  };

  // Reset must clear the ADVANCED filters too, or a min-rating/sort/date range
  // set from the flyout silently survives a Reset click (owner QA 2026-07-30).
  const resetAll = () => {
    setQuery(""); setMedia(""); setShelf(""); setAdv(ADV_DEFAULTS);
    setApplied("");
  };

  /* The Konami Code easter egg, ported from the classic BASE_HTML (its CSS/JS
     never shipped to /next -- owner QA: "the Konami code is broken"; it wasn't,
     it was simply absent). Same sequence, same beacon, same visuals; styles
     live in styles.css. Mounted once, globally. */
  useEffect(() => {
    const seq = [38, 38, 40, 40, 37, 39, 37, 39, 66, 65];
    let pos = 0, busy = false;
    const onKey = (e) => {
      pos = e.keyCode === seq[pos] ? pos + 1 : (e.keyCode === seq[0] ? 1 : 0);
      if (pos !== seq.length) return;
      pos = 0;
      if (busy) return;
      busy = true;
      fetch("/api/ach-event", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event: "konami" }),
      }).catch(() => {});
      const glyphs = ["✦", "✧", "★", "✪", "✺"];
      const stars = [];
      for (let i = 0; i < 46; i++) {
        const s = document.createElement("div");
        s.className = "ee-star";
        s.textContent = glyphs[i % glyphs.length];
        s.style.left = Math.random() * 100 + "vw";
        s.style.fontSize = 13 + Math.random() * 24 + "px";
        s.style.animationDuration = 2.2 + Math.random() * 2.6 + "s";
        s.style.animationDelay = Math.random() * 1.8 + "s";
        document.body.appendChild(s);
        stars.push(s);
      }
      const scrim = document.createElement("div");
      scrim.className = "ee-scrim";
      document.body.appendChild(scrim);
      const nel = document.createElement("img");
      nel.className = "ee-nel";
      nel.src = "/branding/ee_nelstarfall.png";
      nel.onerror = () => nel.remove();
      document.body.appendChild(nel);
      // Built with DOM methods, not innerHTML -- both lines are fixed literals
      // (no interpolated data), but this way there is nothing to ever audit.
      const toast = document.createElement("div");
      toast.className = "ee-toast";
      toast.appendChild(document.createTextNode("✺ Elune-adore, Nelnamara ✺"));
      const sub = document.createElement("div");
      sub.style.cssText = "font-size:12.5px;color:var(--subtext);margin-top:7px;";
      sub.textContent = "The Athenaeum casts Starfall. Moonfire spam remains a lifestyle.";
      toast.appendChild(sub);
      document.body.appendChild(toast);
      let cast, loop;
      try { cast = new Audio("/branding/ee_starfall_cast.ogg"); cast.volume = 0.7; cast.play().catch(() => {}); } catch {}
      try { loop = new Audio("/branding/ee_starfall_loop.ogg"); loop.loop = true; loop.volume = 0.35; loop.play().catch(() => {}); } catch {}
      setTimeout(() => {
        document.querySelectorAll(".ee-star,.ee-toast,.ee-nel,.ee-scrim").forEach((n) => n.remove());
        try { loop && loop.pause(); } catch {}
        try { cast && cast.pause(); } catch {}
        busy = false;
      }, 7000);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const toggleSelected = (mid) =>
    setSelected((old) => {
      const s = new Set(old);
      s.has(mid) ? s.delete(mid) : s.add(mid);
      return s;
    });

  /* ---- bulk Actions: the classic flows, confirm texts verbatim ---- */
  const selIds = [...selected];
  const afterMutation = async () => {
    setSelected(new Set());
    load(1, true);
    const c = await fetchCollections();
    if (c) setCollections(c);
  };
  const actions = {
    addCollection: async () => {
      const name = window.prompt(
        "Add " + selIds.length + " image(s) to which collection? (a name; files are NOT moved)");
      if (name === null || !name.trim()) return;
      await postForm("/collection-add", { back: "/next", name: name.trim() }, selIds);
      afterMutation();
    },
    removeCollection: async (name) => {
      if (!name) return;
      if (!window.confirm(
        "Remove " + selIds.length + " item(s) from the collection “" + name + "”?\n\n" +
        "Only the collection label is removed — no files are deleted and nothing leaves your PixAI account.")) return;
      await postForm("/collection-remove", { back: "/next", name }, selIds);
      afterMutation();
    },
    sendCast: async () => {
      // cast is images -- videos are filtered out, unknown ids resolved like the classic
      const known = new Map(items.map((it) => [it.media_id, it.is_video]));
      const vids = await resolveVideoIds(selIds, known);
      const keep = selIds.filter((mid) => !vids.has(mid));
      if (!keep.length) return;
      setSelected(new Set()); // selection is consumed into the Loom cast
      window.location.href = "/loom?cast=" + encodeURIComponent(keep.join(","));
    },
    printSheet: () =>
      window.open("/contact-sheet?ids=" + encodeURIComponent(selIds.join(",")), "_blank"),
    downloadZip: () => downloadZipForm(selIds),
    replacePrompt: async () => {
      const find = window.prompt(
        "Find this text in the prompts of " + selIds.length + " selected image(s):");
      if (find === null || find === "") return;
      const repl = window.prompt('Replace "' + find + '" with: (leave blank to delete it)');
      if (repl === null) return;
      if (!window.confirm('Replace "' + find + '" with "' + repl + '" across ' +
        selIds.length + " prompt(s)? This edits catalog.db.")) return;
      await postForm("/bulk-replace-prompt", { back: "/next", find, replace: repl }, selIds);
      afterMutation();
    },
    deleteLocal: async () => {
      if (!window.confirm(
        "Remove " + selIds.length + " image" + (selIds.length !== 1 ? "s" : "") +
        " from the local catalog? Files move to the _deleted/ folder (recoverable); the cloud task is untouched.")) return;
      await postForm("/delete-bulk", { back: "/next" }, selIds);
      afterMutation();
    },
    deleteCloud: async (ids) => {
      // The typed gate, unchanged: the preview makes the consequence visible,
      // it does not replace the guard.
      const typed = window.prompt("This permanently deletes from PixAI. Type DELETE to confirm:");
      if (typed !== "DELETE") { window.alert("Cancelled."); return; }
      await postForm("/delete-tasks-bulk", { back: "/next" }, ids);
      afterMutation();
    },
  };

  const rate = async (mid, value) => {
    // optimistic; the server clamps 0-5 and answers the stored value
    setItems((old) => old.map((it) => (it.media_id === mid ? { ...it, rating: value } : it)));
    try {
      const { rateImage } = await import("./api.js");
      await rateImage(mid, value);
    } catch {
      /* a failed rate leaves the optimistic value; the next load corrects it */
    }
  };

  /* Lightbox "Edit"/"To Video" -> GenerateDrawer, matching classic's
     lbEdit()/lbVideo() (close the lightbox, then open the drawer already on
     the right tab with the source loaded). genRequest is a one-shot
     instruction: a fresh object (nonce included) every time, so asking for
     the SAME image twice in a row still re-fires the drawer's effect. */
  const [genRequest, setGenRequest] = useState(null);
  const requestEdit = (mid) => {
    setLbIndex(null);
    setGenOpen(true);
    setGenRequest({ tab: "edit", mid, nonce: Math.random() });
  };
  const requestVideo = (mid, thumb) => {
    setLbIndex(null);
    setGenOpen(true);
    setGenRequest({ tab: "video", mid, thumb, nonce: Math.random() });
  };

  return (
    <div className="app">
      {/* mg-head carries the collapsing-sticky mechanism: tall header, negative
          sticky top, so the art scrolls away and .strip pins. */}
      <header className="mg-head">
        <ArtBand boot={boot} />
        <Strip
          boot={boot} account={account}
          media={media} setMedia={setMedia}
          perPage={perPage} setPerPage={setPerPage}
          shelf={shelf} setShelf={setShelf}
          query={query} setQuery={setQuery} submitQuery={submitQuery} resetAll={resetAll}
          blur={blur} setBlur={setBlur}
          selectMode={selectMode} setSelectMode={setSelectMode}
          selectedCount={selected.size}
          selectedIds={selIds}
          clearSelection={() => setSelected(new Set())}
          collections={collections}
          actions={actions}
          adv={adv} advCount={advCount}
          flyOpen={flyOpen} setFlyOpen={setFlyOpen}
          applyAdvanced={applyAdvanced}
          onGenerate={() => setGenOpen(true)}
        />
      </header>
      {detailsFor ? (
        <DetailsView
          mediaId={detailsFor} onClose={closeDetails} onNavigate={openDetails}
          onRate={rate} onEdit={requestEdit}
          onDeleted={() => { closeDetails(); load(1, true); }}
          onFilterByModel={filterByModel} onFilterByBatch={filterByBatch}
          advParams={{
            q: applied, media, collection: shelf,
            sort: adv.sort !== "newest" ? adv.sort : "", rating_min: adv.ratingMin || "",
            model: adv.model, lora: adv.lora, from: adv.dateFrom, to: adv.dateTo,
            source: adv.source, tag: adv.tag, published: adv.publishedOnly ? "1" : "",
          }}
        />
      ) : (
        <Grid
          items={items} total={total} loading={loading}
          page={page} pages={pages}
          goToPage={(p) => load(p, true)}
          blur={blur}
          selectMode={selectMode} selected={selected} toggleSelected={toggleSelected}
          openLightbox={setLbIndex}
          onRate={rate}
        />
      )}
      {lbIndex != null && (
        <Lightbox
          items={items} index={lbIndex} setIndex={setLbIndex}
          onClose={() => setLbIndex(null)}
          onRate={rate}
          page={page} pages={pages} loadPage={load}
          onEdit={requestEdit} onToVideo={requestVideo}
          onOpenDetails={openDetails}
        />
      )}
      <GenerateDrawer open={genOpen} onClose={() => setGenOpen(false)} account={account}
        request={genRequest} />
      <PickerHost />
    </div>
  );
}
