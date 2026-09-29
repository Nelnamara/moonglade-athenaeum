import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import useAccountPrefs from "../hooks/useAccountPrefs.js";
import useLayerHistory from "../hooks/useLayerHistory.js";
import {
  ABOUT_SLUG, classifyHref, githubSlug, glossaryMatchers, markPage, parseWiki,
  searchGuide, spansText,
} from "./helpCore.js";
import { GUIDE_SURFACES, NOTES_HIDDEN_KEY } from "./guideCore.js";
import { stepsFor } from "./guideSteps.js";
import { checkOnline, loadIndex, loadPage, visibleIndex } from "./helpData.js";
import { closeHelp, subscribe } from "./helpStore.js";
import { replayTour, resetGuides, setNotesHidden } from "./guideActions.js";
import { AboutCard } from "./AboutLayers.jsx";
import "../styles/help.css";

/* THE HELP OVERLAY (Session I decision 2; the handoff's section B, "2a").

   820 px, over whatever surface opened it; a 200 px page list with search on the left, the
   reader on the right, back/forward, a breadcrumb, the "vX.Y · this install" stamp. The
   pages are the wiki/ this install carries, parsed by helpCore.js into plain data and
   rendered here through React only. A wiki link opens the page in place (with history); an
   outside link gets ↗ and a new tab; a Glossary term gets a dotted underline and a card on
   hover (tap, on a phone). About is the list's last page. When a newer release is out and
   its copy of the page differs, one quiet line at the foot says so.

   Phone: a full-height sheet -- ‹ back (or close), the page's title, ☰ for the page list.
   The phone's Back gesture closes it like every other layer (useLayerHistory).

   Opening and closing are helpStore's (every door calls openHelp); Escape and the ? key
   are helpStore's too, on the capture phase, so they reach this layer before the surface
   underneath. */

function useHelpState() {
  const [s, setS] = useState(null);
  useEffect(() => subscribe((x) => setS({ ...x })), []);
  return s;
}

/* ---------------------------------------------------------------- inline rendering */
function Spans({ spans, ctx }) {
  return (spans || []).map((s, i) => {
    switch (s.t) {
      case "text": return <React.Fragment key={i}>{s.v}</React.Fragment>;
      case "b": return <b key={i}><Spans spans={s.c} ctx={ctx} /></b>;
      case "i": return <i key={i}><Spans spans={s.c} ctx={ctx} /></i>;
      case "code": return <code key={i}>{s.v}</code>;
      case "br": return <br key={i} />;
      case "term": return <Term key={i} s={s} ctx={ctx} />;
      case "a": return <Link key={i} s={s} ctx={ctx} />;
      default: return null;
    }
  });
}

function Link({ s, ctx }) {
  const where = classifyHref(s.href, ctx.slugs);
  const label = <Spans spans={s.c} ctx={ctx} />;
  if (where.kind === "external") {
    return (
      <a className="mghelp-a ext" href={where.href} target="_blank" rel="noopener noreferrer">
        {label}<span className="mghelp-ext" aria-hidden="true"> ↗</span>
      </a>
    );
  }
  if (where.kind === "page" || where.kind === "anchor") {
    const go = (e) => {
      e.preventDefault();
      if (where.kind === "anchor") ctx.go(ctx.slug, where.anchor);
      else ctx.go(where.slug, where.anchor);
    };
    return <a className="mghelp-a" href={"#" + (where.slug || "") + (where.anchor ? "#" + where.anchor : "")} onClick={go}>{label}</a>;
  }
  return <span>{label}</span>;
}

function Term({ s, ctx }) {
  const ref = useRef(null);
  const show = () => ctx.showTerm(s, ref.current);
  return (
    <span ref={ref} className="mghelp-term" tabIndex={0} role="button"
      aria-label={s.v + ": " + s.def}
      onMouseEnter={ctx.phone ? undefined : show}
      onMouseLeave={ctx.phone ? undefined : ctx.hideTermSoon}
      onFocus={show} onBlur={ctx.hideTermSoon}
      onClick={(e) => { e.stopPropagation(); ctx.toggleTerm(s, ref.current); }}>
      {s.v}
    </span>
  );
}

/* ---------------------------------------------------------------- blocks */
function Block({ b, ctx }) {
  switch (b.type) {
    case "h": {
      const cls = "mghelp-h" + Math.min(4, b.level);
      const Tag = "h" + Math.min(6, b.level + 1);   // the overlay's own title is the h2 slot
      return <Tag id={"mgh-" + b.anchor} className={cls}><Spans spans={b.spans} ctx={ctx} /></Tag>;
    }
    case "p": return <p className="mghelp-p"><Spans spans={b.spans} ctx={ctx} /></p>;
    case "ul":
    case "ol": {
      const Tag = b.type;
      return (
        <Tag className="mghelp-list-b" start={b.type === "ol" ? b.start : undefined}>
          {b.items.map((it, i) => {
            // A Glossary bullet opens on its bold term: that is the anchor a card links to.
            const lead = ctx.slug === "Glossary" && it[0] && it[0].t === "b" ? spansText(it[0].c) : "";
            return <li key={i} id={lead ? "mgh-term-" + githubSlug(lead) : undefined}><Spans spans={it} ctx={ctx} /></li>;
          })}
        </Tag>
      );
    }
    case "code": return <pre className="mghelp-code">{b.text}</pre>;
    case "hr": return <hr className="mghelp-hr" />;
    case "quote":
      return <blockquote className="mghelp-quote">{b.blocks.map((x, i) => <Block key={i} b={x} ctx={ctx} />)}</blockquote>;
    case "table":
      return (
        <div className="mghelp-tablewrap">
          <table className="mghelp-table">
            <thead><tr>{b.head.map((c, i) => <th key={i} style={b.align[i] ? { textAlign: b.align[i] } : undefined}><Spans spans={c} ctx={ctx} /></th>)}</tr></thead>
            <tbody>
              {b.rows.map((r, ri) => (
                <tr key={ri}>{r.map((c, i) => <td key={i} style={b.align[i] ? { textAlign: b.align[i] } : undefined}><Spans spans={c} ctx={ctx} /></td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    default: return null;
  }
}

/* ---------------------------------------------------------------- the overlay */
export default function HelpOverlay({ phone }) {
  const st = useHelpState();
  const open = !!(st && st.open);
  const closing = !!(st && st.closing);
  const up = open || closing;
  const [index, setIndex] = useState(null);
  const [cur, setCur] = useState({ slug: "Home", anchor: "" });
  const [back, setBack] = useState([]);
  const [fwd, setFwd] = useState([]);
  const [page, setPage] = useState(null);          // {slug, blocks} | {slug, error}
  const [online, setOnline] = useState(null);      // {differs, url}
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const [listOpen, setListOpen] = useState(false); // phone: the ☰ page list
  const [term, setTerm] = useState(null);          // {s, left, top}
  const readerRef = useRef(null);
  const hideTimer = useRef(null);
  const prefs = useAccountPrefs();

  // Each OPEN starts on the page it was opened for, with a fresh history.
  useEffect(() => {
    if (!st || !st.open) return;
    setCur({ slug: st.slug, anchor: st.anchor || "" });
    setBack([]); setFwd([]); setQ(""); setListOpen(false); setTerm(null);
  }, [st && st.nonce]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!up || index) return;
    loadIndex().then((d) => { if (d && !d.error) setIndex(visibleIndex(d)); });
  }, [up, index]);

  useLayerHistory(!!(phone && open), closeHelp);

  const pages = (index && index.pages) || [];
  const slugs = useMemo(() => new Set(pages.map((p) => p.slug)), [pages]);
  const matchers = useMemo(() => glossaryMatchers((index && index.glossary) || []), [index]);
  const titleOf = useCallback((slug) => {
    if (slug === ABOUT_SLUG) return "About";
    const p = pages.find((x) => x.slug === slug);
    return p ? p.title : slug.replace(/-/g, " ");
  }, [pages]);

  // Load and parse the page on screen.
  useEffect(() => {
    if (!up) return undefined;
    let live = true;
    setOnline(null);
    setTerm(null);
    if (cur.slug === ABOUT_SLUG) { setPage({ slug: ABOUT_SLUG, blocks: [] }); return undefined; }
    setPage((p) => (p && p.slug === cur.slug ? p : null));
    loadPage(cur.slug).then((d) => {
      if (!live) return;
      if (!d || d.error) { setPage({ slug: cur.slug, error: (d && d.error) || "That page could not be read." }); return; }
      const blocks = parseWiki(d.markdown);
      setPage({ slug: cur.slug, blocks: cur.slug === "Glossary" ? blocks : markPage(blocks, matchers) });
      checkOnline(cur.slug).then((o) => { if (live && o && !o.error) setOnline(o); });
    });
    return () => { live = false; };
  }, [up, cur.slug, matchers]);

  // Land on the anchor (or the top) once the page is on screen. The READER scrolls, never
  // the page behind the overlay.
  useEffect(() => {
    const el = readerRef.current;
    if (!el || !page || page.slug !== cur.slug) return;
    if (cur.anchor) {
      const target = el.querySelector("#" + CSS.escape("mgh-" + cur.anchor))
        || el.querySelector("#" + CSS.escape("mgh-term-" + cur.anchor));
      if (target) {
        el.scrollTop = target.offsetTop - 8;
        return;
      }
    }
    el.scrollTop = 0;
  }, [page, cur]);

  const go = useCallback((slug, anchor) => {
    setBack((b) => b.concat([cur]));
    setFwd([]);
    setCur({ slug, anchor: anchor || "" });
    setQ("");
    setListOpen(false);
  }, [cur]);
  const goBack = () => {
    if (!back.length) { if (phone) closeHelp(); return; }
    setFwd((f) => [cur].concat(f));
    setCur(back[back.length - 1]);
    setBack((b) => b.slice(0, -1));
  };
  const goFwd = () => {
    if (!fwd.length) return;
    setBack((b) => b.concat([cur]));
    setCur(fwd[0]);
    setFwd((f) => f.slice(1));
  };

  /* The Glossary card: one card for the reader, placed under the term, inside the reader's
     own width. */
  const placeTerm = useCallback((s, el) => {
    const reader = readerRef.current;
    if (!reader || !el) return;
    clearTimeout(hideTimer.current);
    const rr = reader.getBoundingClientRect();
    const tr = el.getBoundingClientRect();
    const w = Math.min(240, rr.width - 24);
    const left = Math.max(12, Math.min(tr.left - rr.left, rr.width - w - 12));
    const top = tr.bottom - rr.top + reader.scrollTop + 8;
    setTerm({ s, left, top, w });
  }, []);
  const ctx = {
    slug: cur.slug, slugs, phone: !!phone, go,
    showTerm: placeTerm,
    toggleTerm: (s, el) => {
      if (term && term.s === s) { setTerm(null); return; }
      placeTerm(s, el);
    },
    hideTermSoon: () => {
      clearTimeout(hideTimer.current);
      hideTimer.current = setTimeout(() => setTerm(null), 220);
    },
  };

  const hits = useMemo(() => searchGuide(pages, q, 40), [pages, q]);
  useEffect(() => { setSel(0); }, [q]);
  const openHit = (h) => { if (h) go(h.slug, h.heading ? githubSlug(h.heading) : ""); };
  const onSearchKey = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setSel((x) => Math.min(x + 1, Math.max(0, hits.length - 1))); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSel((x) => Math.max(0, x - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); openHit(hits[sel]); }
  };

  if (!up) return null;

  const from = (st && st.from) || "";
  const canReplay = GUIDE_SURFACES.includes(from) && !!stepsFor(from, !!phone);
  const notesHidden = !!prefs.get(NOTES_HIDDEN_KEY, false);
  const version = index ? "v" + index.display_version + " · this install" : "";
  const crumb = cur.slug === "Home" ? ["Home"] : ["Home", titleOf(cur.slug)];

  const list = (
    <nav className="mghelp-list" aria-label="Guide pages">
      <input className="mghelp-search" type="search" placeholder="Search the guide" value={q}
        onChange={(e) => setQ(e.target.value)} onKeyDown={onSearchKey} aria-label="Search the guide"
        autoFocus={!phone} />
      <div className="mghelp-pages">
        {q.trim() ? (
          hits.length ? hits.map((h, i) => (
            <button type="button" key={h.slug + "|" + h.heading + "|" + i}
              className={"mghelp-hit" + (i === sel ? " on" : "")} onClick={() => openHit(h)}>
              <span className="t">{h.heading || h.title}</span>
              {h.heading ? <span className="s">{h.title}</span> : null}
            </button>
          )) : <div className="mghelp-none">Nothing in the guide matches.</div>
        ) : (
          pages.map((p) => ({ slug: p.slug, title: p.title })).concat([{ slug: ABOUT_SLUG, title: "About" }]).map((p) => (
            <button type="button" key={p.slug}
              className={"mghelp-page" + (cur.slug === p.slug ? " on" : "")}
              aria-current={cur.slug === p.slug ? "page" : undefined}
              onClick={() => go(p.slug, "")}>{p.title}</button>
          ))
        )}
      </div>
      <div className="mghelp-acts">
        {canReplay ? (
          <button type="button" onClick={() => { replayTour(from); closeHelp(); }}>Replay this tour</button>
        ) : null}
        <button type="button" onClick={() => setNotesHidden(!notesHidden)}>
          {notesHidden ? "Show Nel's notes" : "Hide Nel's notes"}
        </button>
        <button type="button" className="dim"
          onClick={() => { resetGuides().then(() => closeHelp()); }}>Reset guides</button>
        {phone && version ? <div className="mghelp-verline">{version}</div> : null}
      </div>
    </nav>
  );

  const reader = (
    <article className="mghelp-reader" ref={readerRef} onClick={() => term && setTerm(null)}>
      {cur.slug === ABOUT_SLUG ? (
        <AboutCard inline />
      ) : !page || page.slug !== cur.slug ? (
        <div className="mghelp-loading">Opening the page…</div>
      ) : page.error ? (
        <div className="mghelp-loading">{page.error}</div>
      ) : (
        <>
          {page.blocks.map((b, i) => <Block key={i} b={b} ctx={ctx} />)}
          {online && online.differs ? (
            <a className="mghelp-online" href={online.url} target="_blank" rel="noopener noreferrer">
              A newer version of this page is online ↗
            </a>
          ) : null}
        </>
      )}
      {term ? (
        <div className="mghelp-card" style={{ left: term.left, top: term.top, width: term.w }}
          onMouseEnter={() => clearTimeout(hideTimer.current)} onMouseLeave={ctx.hideTermSoon}
          onClick={(e) => e.stopPropagation()}>
          <b>{term.s.term.charAt(0).toUpperCase() + term.s.term.slice(1)}</b>
          {" · "}{term.s.def}{" "}
          <button type="button" className="mghelp-cardlink"
            onClick={() => { setTerm(null); go("Glossary", "term-" + githubSlug(term.s.term)); }}>
            Glossary ›
          </button>
        </div>
      ) : null}
    </article>
  );

  const cls = (closing ? " closing" : "");
  if (phone) {
    return createPortal(
      <div className={"mghelp-sheet" + cls} role="dialog" aria-modal="true" aria-label="Guide" data-keeps-dock="1">
        <div className="mghelp-sheethead">
          <button type="button" className="mghelp-44" onClick={goBack}
            aria-label={back.length ? "Back" : "Close the guide"}>‹</button>
          <div className="mghelp-sheettitle">{listOpen ? "Guide" : titleOf(cur.slug)}</div>
          <button type="button" className={"mghelp-44" + (listOpen ? " on" : "")}
            onClick={() => setListOpen((v) => !v)} aria-label="Pages" aria-expanded={listOpen}>☰</button>
        </div>
        {listOpen ? list : reader}
      </div>,
      document.body,
    );
  }
  return createPortal(
    <>
      <div className={"mghelp-scrim" + cls} onMouseDown={closeHelp} data-keeps-dock="1" />
      <div className={"mghelp-host" + cls} data-keeps-dock="1">
        <div className={"mghelp" + cls} role="dialog" aria-modal="true" aria-label="Guide">
          <div className="mghelp-head">
            <div className="mghelp-title">Guide</div>
            <div className="mghelp-nav">
              <button type="button" onClick={goBack} disabled={!back.length} aria-label="Back">‹</button>
              <button type="button" onClick={goFwd} disabled={!fwd.length} aria-label="Forward">›</button>
            </div>
            <div className="mghelp-crumb">
              {crumb.map((c, i) => (
                <React.Fragment key={i}>
                  {i ? " / " : ""}
                  {i === 0 && crumb.length > 1
                    ? <button type="button" onClick={() => go("Home", "")}>{c}</button>
                    : <span>{c}</span>}
                </React.Fragment>
              ))}
            </div>
            <div className="sp" />
            <div className="mghelp-ver">{version}</div>
            <button type="button" className="mghelp-x" onClick={closeHelp} aria-label="Close the guide">×</button>
          </div>
          <div className="mghelp-body">
            {list}
            {reader}
          </div>
        </div>
      </div>
    </>,
    document.body,
  );
}

