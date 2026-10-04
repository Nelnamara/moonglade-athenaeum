import React, { useEffect, useRef, useState } from "react";
import {
  TABS, GLYPH, groupInbox, workDelta, timeAgo, giftMeta, giftPreview, bonusText, expiringLines, expiryText,
} from "./inboxCore.js";
import { openItem, loadMore, claimGift, clearClaim, markAllRead } from "./inboxStore.js";

/* The bodies behind the doors (Inbox and Event Handoff §1-3, §7, §9, §10): the inbox's, shared by
   the desktop's ✉ panel and the phone's Inbox sheet, and the gift box's, shared by the desktop's
   🎁 panel and the phone's Gift box sheet. The doors differ; the rows do not.

   The inbox, from the top (R1a, less the gifts and the event since the owner's walk 2026-10-04):
   the kind tabs, the work cards, then EVERYTHING ELSE. Opening a row or a card navigates and marks
   what it gathers read on PixAI (one write -- inboxStore.openItem); nothing here writes on open,
   scroll or tab. The gift box: ON PIXAI NOW, the free cards about to expire, then the gifts. */

const TIP_DELAY_MS = 600;

/* A thumb, an avatar, a banner: a computed background, never an <img> hole. */
function bg(url) {
  return url ? { backgroundImage: "url('" + String(url).replace(/'/g, "%27") + "')" } : undefined;
}

function thumbOf(art) {
  if (!art) return "";
  if (art.media_id) return "/thumbs/" + encodeURIComponent(art.media_id) + ".jpg";
  return art.thumb || "";
}

/* ⋯ in the title row: "Mark all read" (R3b) -- one watermark write for the tab's unread kinds,
   then a read-back of the count. */
export function MarkAllMenu({ tab }) {
  const [menu, setMenu] = useState(false);
  return (
    <span className="ib-menuwrap">
      <button type="button" className="ib-more" aria-label="More" aria-expanded={menu}
        onClick={() => setMenu((v) => !v)}>⋯</button>
      {menu ? (
        <span className="ib-menu" role="menu">
          <button type="button" role="menuitem" className="ib-menuitem"
            onClick={() => { setMenu(false); markAllRead(tab); }}>
            Mark all read
          </button>
        </span>
      ) : null}
    </span>
  );
}

export function KindTabs({ tab, onTab, phone }) {
  return (
    <div className={"ib-tabs" + (phone ? " phone" : "")} role="tablist" aria-label="Kinds">
      {TABS.map(([k, label]) => (
        <button key={k} type="button" role="tab" aria-selected={tab === k}
          className={"ib-chip" + (tab === k ? " on" : "")} onClick={() => onTab(k)}>{label}</button>
      ))}
    </div>
  );
}

/* ON PIXAI NOW (Y3a; resized on the owner's walk 2026-10-04: "cramped but also too small"): one
   banner per row at the full width of the gift box's panel or the phone's sheet, at the banner
   image's own aspect -- read off the probe that also catches a failure -- and a wide 3:1 box while
   it loads or if it fails. The label keeps its treatment (the title, then "event ↗", bold, on the
   scrim's dark) but has a strip of its own under the art at 13 px, so it never sits on the art's
   busy part. A press opens PixAI's own page in a new tab -- the app never requests the link itself.
   An image that fails leaves the box on a surface tint, never an <img> hole. */
export function EventCards({ events }) {
  const [failed, setFailed] = useState({});
  const [shape, setShape] = useState({});
  useEffect(() => {
    (events || []).forEach((e) => {
      if (!e.image || failed[e.link] || shape[e.link]) return;
      const probe = new Image();
      probe.onload = () => {
        if (probe.naturalWidth > 0 && probe.naturalHeight > 0) {
          setShape((m) => ({ ...m, [e.link]: probe.naturalWidth + " / " + probe.naturalHeight }));
        }
      };
      probe.onerror = () => setFailed((f) => ({ ...f, [e.link]: true }));
      probe.src = e.image;
    });
  }, [events]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!events || !events.length) return null;
  return (
    <>
      <div className="ib-lab">ON PIXAI NOW</div>
      <div className="ib-events">
        {events.map((e) => {
          const art = failed[e.link] || !e.image ? null : e.image;
          return (
            <button key={e.link} type="button" className={"ib-event" + (art ? "" : " noimg")}
              title={e.title + " on PixAI"} onClick={() => window.open(e.link, "_blank", "noopener")}>
              <span className="ib-event-art" aria-hidden="true"
                style={{ ...(art ? bg(art) : {}), ...(art && shape[e.link] ? { aspectRatio: shape[e.link] } : {}) }} />
              <span className="ib-event-t">{e.title}<br />event ↗</span>
            </button>
          );
        })}
      </div>
    </>
  );
}

function Tip({ readOnly }) {
  return (
    <span className="ib-tip" role="tooltip">
      {readOnly ? "Read-only mode is on, so this stays unread on PixAI." : "Opening this marks it read on PixAI."}
    </span>
  );
}

/* The 600 ms hover tip on an unread row (R3b), popping toward open space. */
function useTip() {
  const [tip, setTip] = useState(null);
  const timer = useRef(0);
  useEffect(() => () => clearTimeout(timer.current), []);
  const on = (key, el) => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      let above = false;
      try {
        const r = el.getBoundingClientRect();
        const box = el.closest(".ib-scroll");
        const b = box ? box.getBoundingClientRect() : { bottom: window.innerHeight };
        above = r.bottom + 44 > b.bottom;
      } catch { /* geometry is best-effort */ }
      setTip({ key, above });
    }, TIP_DELAY_MS);
  };
  const off = () => { clearTimeout(timer.current); setTip(null); };
  return { tip, on, off };
}

function Row({ row, now, tip, readOnly, notice, children, onOpen }) {
  const hover = row.unread ? {
    onMouseEnter: (e) => tip.on(row.key, e.currentTarget),
    onMouseLeave: tip.off,
  } : {};
  return (
    <>
      <button type="button" className={"ib-row" + (row.unread ? " unread" : "")} {...hover}
        onClick={() => { tip.off(); onOpen(row); }}>
        <span className="ib-dot" aria-hidden="true" />
        {children}
        <span className="ib-meta">{timeAgo(row.at, now)}</span>
        {tip.tip && tip.tip.key === row.key ? (
          <span className={"ib-tipwrap" + (tip.tip.above ? " above" : "")}><Tip readOnly={readOnly} /></span>
        ) : null}
      </button>
      {notice && notice.key === row.key ? <div className="ib-warn">{notice.text}</div> : null}
    </>
  );
}

function GiftIcon({ small }) {
  return <span className={"ib-giftic" + (small ? " small" : "")} aria-hidden="true" />;
}

/* Gifts (R9c): a PENDING REWARD message gets Claim ▸, which swaps the row's detail for a
   preview (what, which account, expiry, "One attempt.") with [Back] [Claim]: one write and a
   status read-back. 409 / 410 come back as peach words. A done gift dims with "claimed" /
   "expired". Credit-pack bonuses open PixAI and send nothing. Gifts are not billing: no gold.
   With none, the section is absent (the gift box's one quiet line covers an empty box). */
export function GiftRows({ data, error, claim, claimLocked, readOnly }) {
  const [preview, setPreview] = useState("");
  if (error) return <div className="ib-warn">{"Couldn't read your gifts from PixAI: " + error}</div>;
  if (!data) return <div className="ib-dim">Reading your gifts…</div>;
  const gifts = data.gifts || [];
  const bonuses = data.bonuses || [];
  if (!gifts.length && !bonuses.length) return null;
  return (
    <>
      {gifts.map((g) => {
        const pending = g.status === "PENDING";
        const mine = claim && claim.id === g.id ? claim : null;
        const locked = !!(claimLocked && claimLocked[g.id]);
        return (
          <React.Fragment key={g.id}>
            <div className={"ib-gift" + (pending ? "" : " done")}>
              <GiftIcon />
              <span className="ib-gift-t">Gift from PixAI · {g.what}</span>
              {pending ? (
                <>
                  <span className="ib-meta">{giftMeta(g)}</span>
                  {preview !== g.id ? (
                    <button type="button" className="ib-btn" disabled={readOnly || locked}
                      title={readOnly ? "Read-only mode is on, so nothing can be claimed."
                        : locked ? "The last claim had no clear answer. Check on PixAI; this unlocks when the gifts are read again."
                          : "Claim this gift"}
                      onClick={() => { clearClaim(); setPreview(g.id); }}>Claim ▸</button>
                  ) : null}
                </>
              ) : (
                <span className="ib-meta">{giftMeta(g)}</span>
              )}
            </div>
            {preview === g.id && pending ? (
              <>
                <div className="ib-quote">{giftPreview(g, data.my_name)}</div>
                <div className="ib-acts">
                  <button type="button" className="ib-ghost" onClick={() => setPreview("")}>Back</button>
                  <button type="button" className="ib-btn"
                    disabled={!!(mine && mine.state === "sending") || readOnly || locked}
                    onClick={() => claimGift(g.id).then((d) => { if (d && d.state === "done") setPreview(""); })}>
                    {mine && mine.state === "sending" ? "Claiming…" : "Claim"}
                  </button>
                </div>
              </>
            ) : null}
            {mine && mine.state === "done" ? <div className="ib-ok">{mine.message}</div> : null}
            {mine && mine.state !== "done" && mine.state !== "sending" ? (
              <div className="ib-peachbox">{mine.message}</div>
            ) : null}
          </React.Fragment>
        );
      })}
      {bonuses.map((b) => (
        <div className="ib-gift" key={"b" + b.code}>
          <GiftIcon />
          <span className="ib-gift-t">{bonusText(b)}</span>
          <a className="ib-link" href="https://pixai.art/en/membership/credit-packs" target="_blank"
            rel="noopener noreferrer">Open on PixAI ↗</a>
        </div>
      ))}
    </>
  );
}

/* The inbox: work cards, then everything else. */
export function InboxBody({ st, tab, now }) {
  const tip = useTip();
  const scrollRef = useRef(null);
  const g = groupInbox(st.items, tab);
  const onScroll = (e) => {
    const el = e.currentTarget;
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 40) loadMore();
  };
  const empty = st.loaded && !g.works.length && !g.rest.length;
  return (
    <div className="ib-scroll" ref={scrollRef} onScroll={onScroll}>
      {st.error ? <div className="ib-warn">{"Couldn't read your PixAI inbox: " + st.error}</div> : null}
      {!st.loaded && !st.error ? <div className="ib-dim">Reading your PixAI inbox…</div> : null}
      {g.works.map((w) => (
        <React.Fragment key={w.key}>
          <Row row={w} now={now} tip={tip} readOnly={st.readOnly} notice={st.notice} onOpen={openItem}>
            <span className="ib-thumb" style={bg(thumbOf(w.artwork))} aria-hidden="true" />
            <span className="ib-text">{w.artwork.title || "Untitled"}<br />{workDelta(w)}</span>
          </Row>
          {w.quote ? (
            <button type="button" className="ib-quote ib-quotebtn"
              onClick={() => openItem({ ...w, focusId: w.quote.id })}>
              {w.quote.name}: {"“"}{w.quote.text}{"”"}
            </button>
          ) : null}
        </React.Fragment>
      ))}
      {g.rest.length ? <div className="ib-lab">EVERYTHING ELSE</div> : null}
      {g.rest.map((r) => (
        <Row key={r.key} row={r} now={now} tip={tip} readOnly={st.readOnly} notice={st.notice} onOpen={openItem}>
          <span className="ib-glyph" aria-hidden="true">{GLYPH[r.kind] || GLYPH.news}</span>
          <span className="ib-text">{r.text}</span>
        </Row>
      ))}
      {empty ? <div className="ib-dim">Nothing here from PixAI yet.</div> : null}
      {st.loading && st.loaded ? <div className="ib-dim">Reading older notifications…</div> : null}
    </div>
  );
}

/* THE GIFT BOX (owner's walk, 2026-10-04), the desktop's 🎁 panel and the phone's Gift box sheet:
   ON PIXAI NOW (absent with nothing live), one peach line per kind of free card that lapses within
   three days -- the credits chip's hover lines, word for word (absent with none) -- then the gifts
   with Claim ▸. With nothing in any of the three, one quiet line. Reads only: what it shows was
   read when the door opened. */
export function GiftBoxBody({ st, account, now }) {
  const cardsBy = (account && account.cards_by ? account.cards_by : []).filter((c) => c.count > 0);
  const expiry = expiringLines(cardsBy, now);
  const data = st.giftData;
  const noGifts = !!data && !st.giftError && !(data.gifts || []).length && !(data.bonuses || []).length;
  const empty = st.events != null && !st.events.length && !expiry.lines.length && noGifts;
  return (
    <div className="ib-scroll">
      <EventCards events={st.events} />
      {expiry.lines.map((l) => <div className="ib-expiry-line" key={l.kind + l.at}>{expiryText(l)}</div>)}
      <GiftRows data={data} error={st.giftError} claim={st.claim} claimLocked={st.claimLocked} readOnly={st.readOnly} />
      {empty ? <div className="ib-dim">Nothing waiting. Gifts from PixAI and cards about to expire show here.</div> : null}
    </div>
  );
}
