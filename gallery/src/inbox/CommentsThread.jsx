import React, { useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "../api.js";
import { show as toastShow } from "../notify/toastStore.js";
import {
  threadOf, hiddenLine, commentMeta, replyCheck, replyQuestion, deleteQuestion,
} from "./inboxCore.js";
import { takeFocus } from "./inboxStore.js";
import MobileSheet from "../components/MobileSheet.jsx";
import "../styles/comments.css";

/* THE THREAD IN DETAILS (Session R, R5b + R6c; Inbox and Event Handoff §5-6, §10; drift 127-128).
   Image Details and Image Details Mobile, for a published work of yours, in place of the
   "💬 n" count.

   READ: when the section scrolls into view (not when Details opens), newest first, 50 a page,
   "Load older" at the end; the server keeps it five minutes in memory and never archives it.
   Top-level comments show with "N replies ▸", one indent deep; a chain holding your comment
   opens by itself, and so does the one an inbox quote pointed at. Your comments wear "you".
   Flagged comments are hidden behind one count line. Reactions and stickers are read-only:
   there is no like, react or report control anywhere here.

   REPLY: an inline box under the comment with a mono counter (4,095). Send raises ONE question
   -- a toast on the desktop, a bottom sheet with 44 px buttons on the phone -- that names who
   you post as, whose comment and which work, and quotes the text in full: [Back] [Post
   publicly]. One POST in flight with the box locked; never a retry; the server reads the thread
   back and says "Posted · found in the thread" (emerald) or the peach "not found, check on
   PixAI", after which Send stays off until the text changes. Refusals are peach, in plain
   words. "Delete my reply" (ruby: it can't be undone) asks the same way and keeps the same
   rules. Under READ_ONLY the box shows, disabled, with the reason. */

function bg(url) {
  return url ? { backgroundImage: "url('" + String(url).replace(/'/g, "%27") + "')" } : undefined;
}

function Comment({ c, now, replies, open, onToggle, onReply, onDelete, deleteOff, indent }) {
  return (
    <div className={"cm-c" + (indent ? " indent" : "")} data-comment={c.id}>
      <div className="cm-head">
        <span className="cm-av" style={bg(c.author.avatar)} aria-hidden="true" />
        <span className="cm-name">{c.author.name}</span>
        {c.you ? <span className="cm-you">you</span> : null}
      </div>
      {c.sticker ? (
        <span className="cm-sticker" style={bg(c.sticker)} role="img" aria-label="sticker" />
      ) : null}
      {/* Another person's words are shown in quotes, as the handoff draws them; yours are not. */}
      {c.content ? <div className="cm-text">{c.you ? c.content : "\"" + c.content + "\""}</div> : null}
      <div className="cm-foot">
        <span className="cm-meta">
          {commentMeta(c, now, 0, false)}
          {replies ? (
            <>
              {" · "}
              <button type="button" className="cm-toggle" aria-expanded={open} onClick={onToggle}>
                {replies + " repl" + (replies === 1 ? "y" : "ies") + (open ? " ▾" : " ▸")}
              </button>
            </>
          ) : null}
        </span>
        {onReply ? <button type="button" className="cm-replylink" onClick={onReply}>Reply</button> : null}
        {onDelete ? (
          <button type="button" className="cm-delete" onClick={onDelete} disabled={!!deleteOff}
            title={deleteOff ? "The last delete had no clear answer. Check on PixAI; this unlocks when the comments are read again." : undefined}>
            Delete my reply
          </button>
        ) : null}
      </div>
    </div>
  );
}

export default function CommentsThread({ row, phone }) {
  const artworkId = String((row && row.artwork_id) || "").trim();
  const published = !!(row && row.is_published === "1" && artworkId);
  const [data, setData] = useState(null);       // {items, total, has_more, me, my_name, read_only, csrf}
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState({});
  const [focusId, setFocusId] = useState("");
  const [box, setBox] = useState(null);         // {to, text, sending, state, message, lastSent}
  const [ask, setAsk] = useState(null);         // phone: {kind: "reply"|"delete", ...}
  const [deleting, setDeleting] = useState(null);  // {id, state, message}
  // Replies posted while this thread is open: "Delete my reply" is offered under these (PixAI
  // has no edit), for as long as the thread stays open.
  const [posted, setPosted] = useState([]);
  // A reply whose delete had no clear answer may already be gone: its Delete stays off until
  // the thread is read again (review item 3).
  const [delLocked, setDelLocked] = useState([]);
  const ref = useRef(null);
  const textRef = useRef(null);
  const askToken = useRef(0);
  const inFlight = useRef(false);
  const [seen, setSeen] = useState(false);

  // reset per work. `current` lets a read that lands after the picture changed be dropped, so
  // one work's comments can never be drawn under another's.
  const current = useRef(artworkId);
  const arrived = useRef(false);
  useEffect(() => {
    current.current = artworkId;
    setData(null); setError(""); setPage(1); setOpen({}); setBox(null); setAsk(null);
    setDeleting(null); setSeen(false); setPosted([]); setDelLocked([]);
    const f = takeFocus(artworkId);
    setFocusId(f ? f.commentId : "");
    arrived.current = !!f;
    if (f) setSeen(true);
  }, [artworkId]);

  // read when the section scrolls into view
  useEffect(() => {
    if (!published || seen || !ref.current) return undefined;
    if (typeof IntersectionObserver === "undefined") { setSeen(true); return undefined; }
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) setSeen(true); });
    io.observe(ref.current);
    return () => io.disconnect();
  }, [published, seen, artworkId]);

  const read = (p) => apiGet("/api/comments/" + encodeURIComponent(artworkId), { page: p }).then((d) => {
    if (current.current !== artworkId) return;
    if (d.error && !(d.items || []).length) { setError(d.error); setData((cur) => cur || { ...d, items: [] }); return; }
    setError("");
    if (p === 1) setDelLocked([]);
    setData((cur) => (p > 1 && cur ? { ...d, items: cur.items.concat(d.items || []) } : d));
    setPage(p);
  });

  useEffect(() => {
    if (published && seen) read(1);
  }, [published, seen, artworkId]); // eslint-disable-line react-hooks/exhaustive-deps

  // arriving from the inbox: Details opens at its comments, and at the quoted comment when a
  // quote was the door
  useEffect(() => {
    if (!arrived.current || !data || !ref.current) return;
    arrived.current = false;
    const el = focusId ? ref.current.querySelector('[data-comment="' + focusId + '"]') : null;
    if (el) el.scrollIntoView({ block: "center" });
    else ref.current.scrollIntoView({ block: "start" });
  }, [focusId, data]);

  if (!published) return null;
  const now = Date.now();
  const items = (data && data.items) || [];
  const t = threadOf(items, focusId);
  const readOnly = !!(data && data.read_only);
  const work = (row.title || "").trim() || "this work";
  const total = data && data.total != null ? data.total : Number(row.comment_count || 0);

  const openBox = (c) => {
    setBox({ to: c, text: "", sending: false, state: "", message: "", lastSent: null });
    setTimeout(() => textRef.current && textRef.current.focus(), 0);
  };

  /* ONE QUESTION, ONE PRESS, ONE POST. Each question carries a token; pressing its [Post
     publicly] spends the token, and a press on a question that is no longer the live one (a
     second toast, or a toast left standing after the first post answered) does nothing. A post
     already in flight blocks every other press. Together they keep two presses from ever being
     two POSTs -- the server is single-attempt per request, so this is where a double send would
     have to be stopped. */
  const post = (tok, b) => {
    if (tok !== askToken.current || inFlight.current || !b) return;
    askToken.current += 1;
    inFlight.current = true;
    setBox({ ...b, sending: true, state: "", message: "" });
    apiPost("/api/comments/" + encodeURIComponent(artworkId) + "/reply",
      { csrf: data.csrf, reply_to: b.to.id, content: b.text }).then((d) => {
      const state = (d && d.state) || "unclear";
      const message = (d && (d.message || d.error)) || "No clear answer from PixAI. Check on PixAI before trying again.";
      if (state === "done" && d.comment) {
        setData((cur) => ({ ...cur, items: [d.comment].concat(cur.items),
          total: cur.total != null ? cur.total + 1 : cur.total }));
        setOpen((o) => ({ ...o, [rootIdOf(b.to)]: true }));
        setPosted((ids) => ids.concat([d.comment.id]));
        setBox({ ...b, text: "", sending: false, state, message, lastSent: null, posted: true });
      } else {
        setBox({ ...b, sending: false, state, message, lastSent: state === "unclear" ? b.text : null });
      }
      inFlight.current = false;
    });
  };

  const rootIdOf = (c) => {
    const ch = t.chains.find((x) => x.root.id === c.id || x.replies.some((r) => r.id === c.id));
    return ch ? ch.root.id : c.id;
  };

  const askPost = () => {
    const b = box;
    if (!b || inFlight.current) return;
    const tok = ++askToken.current;
    const q = replyQuestion(data.my_name, b.to.author.name, work);
    if (phone) { setAsk({ kind: "reply", q, text: b.text.trim(), tok, b }); return; }
    toastShow({
      kind: "", icon: "❝", title: q, quote: b.text.trim(), wide: true, sticky: true,
      actions: [
        { label: "Back", run: () => textRef.current && textRef.current.focus() },
        { label: "Post publicly", run: () => post(tok, b) },
      ],
    });
  };

  const del = (tok, c) => {
    if (tok !== askToken.current || inFlight.current) return;
    askToken.current += 1;
    inFlight.current = true;
    setDeleting({ id: c.id, state: "sending", message: "" });
    apiPost("/api/comments/" + encodeURIComponent(artworkId) + "/delete",
      { csrf: data.csrf, message_id: c.id }).then((d) => {
      const state = (d && d.state) || "unclear";
      inFlight.current = false;
      setDeleting({ id: c.id, state, message: (d && (d.message || d.error)) || "" });
      if (state === "unclear") setDelLocked((ids) => ids.concat([c.id]));
      if (state === "done") {
        setData((cur) => ({ ...cur, items: cur.items.filter((x) => x.id !== c.id),
          total: cur.total != null ? Math.max(0, cur.total - 1) : cur.total }));
      }
    });
  };

  const askDelete = (c) => {
    if (inFlight.current || delLocked.indexOf(c.id) >= 0) return;
    const tok = ++askToken.current;
    const q = deleteQuestion(work);
    if (phone) { setAsk({ kind: "delete", q, c, tok }); return; }
    toastShow({
      kind: "", icon: "⚠", title: q, sticky: true,
      actions: [
        { label: "Keep", run: () => {} },
        { label: "Delete", tone: "ruby", run: () => del(tok, c) },
      ],
    });
  };

  const canDelete = (c) => c.you && !readOnly && posted.indexOf(c.id) >= 0;
  const check = box ? replyCheck(box.text) : null;
  const sendOff = !box || box.sending || !check.ok || readOnly ||
    (box.lastSent != null && box.lastSent === box.text);

  const replyBox = (c) => {
    if (!box || box.to.id !== c.id) return null;
    if (readOnly) {
      return (
        <div className="cm-box">
          <div className="cm-field off" aria-disabled="true">Reply</div>
          <div className="cm-warn">Read-only mode is on (READ_ONLY in config.json), so replies are off.</div>
        </div>
      );
    }
    return (
      <div className="cm-box">
        <textarea ref={textRef} className="cm-field" rows={1} value={box.text} disabled={box.sending}
          aria-label={"Reply to " + c.author.name}
          onChange={(e) => {
            const v = e.target.value;
            e.target.style.height = "auto";
            e.target.style.height = e.target.scrollHeight + "px";
            setBox({ ...box, text: v, state: box.state === "done" ? "" : box.state });
          }}
          onKeyDown={(e) => { if (e.key === "Escape") { e.preventDefault(); setBox(null); } }} />
        <div className="cm-boxrow">
          <span className={"cm-count" + (check.over ? " over" : "")}>{check.label}</span>
          {check.tooLong ? <span className="cm-warn">{check.tooLong}</span> : null}
          <span className="cm-sp" />
          <button type="button" className="cm-ghost" onClick={() => setBox(null)}>Cancel</button>
          <button type="button" className="cm-btn" disabled={sendOff} onClick={askPost}>
            {box.sending ? "Posting…" : "Send"}
          </button>
        </div>
        {box.state === "done" ? <div className="cm-ok">{box.message}</div> : null}
        {box.state === "unclear" ? <div className="cm-peachbox">{box.message} <a href={"https://pixai.art/en/artwork/" + encodeURIComponent(artworkId)} target="_blank" rel="noopener noreferrer">↗</a></div> : null}
        {box.state === "refused" || box.state === "read_only" ? <div className="cm-warn">{box.message}</div> : null}
      </div>
    );
  };

  const delLine = (c) => (deleting && deleting.id === c.id && deleting.state !== "done" ? (
    deleting.state === "sending" ? <div className="cm-dim">Deleting…</div>
      : <div className="cm-peachbox">{deleting.message}</div>
  ) : null);

  return (
    <section className={"cm-thread" + (phone ? " phone" : "")} ref={ref} aria-label="Comments">
      <div className="cm-lab">COMMENTS · {Number(total || 0).toLocaleString()}</div>
      {error ? <div className="cm-warn">{"Couldn't read the comments from PixAI: " + error}</div> : null}
      {seen && !data && !error ? <div className="cm-dim">Reading the comments…</div> : null}
      {data && !t.chains.length && !t.hidden && !error ? <div className="cm-dim">No comments yet.</div> : null}
      {t.chains.map((ch) => {
        const isOpen = open[ch.root.id] != null ? open[ch.root.id] : ch.open;
        return (
          <div className="cm-chain" key={ch.root.id}>
            <Comment c={ch.root} now={now} replies={ch.replies.length} open={isOpen}
              onToggle={() => setOpen((o) => ({ ...o, [ch.root.id]: !isOpen }))}
              onReply={ch.root.you ? null : () => openBox(ch.root)}
              onDelete={canDelete(ch.root) ? () => askDelete(ch.root) : null}
              deleteOff={delLocked.indexOf(ch.root.id) >= 0} />
            {delLine(ch.root)}
            {replyBox(ch.root)}
            {isOpen ? ch.replies.map((r) => (
              <React.Fragment key={r.id}>
                <Comment c={r} now={now} indent onReply={r.you ? null : () => openBox(r)}
                  onDelete={canDelete(r) ? () => askDelete(r) : null}
                  deleteOff={delLocked.indexOf(r.id) >= 0} />
                {delLine(r)}
                {replyBox(r)}
              </React.Fragment>
            )) : null}
          </div>
        );
      })}
      {deleting && deleting.state === "done" ? <div className="cm-ok">{deleting.message}</div> : null}
      {t.hidden ? <div className="cm-dim">{hiddenLine(t.hidden)}</div> : null}
      {data && data.has_more ? (
        <div className="cm-older"><button type="button" className="cm-link" onClick={() => read(page + 1)}>Load older</button></div>
      ) : null}

      {phone ? (
        <MobileSheet open={!!ask} closing={false} onClose={() => setAsk(null)} title="" className="cm-asksheet">
          {ask ? (
            <div className="cm-ask">
              <div className="cm-askq">{ask.q}</div>
              {ask.kind === "reply" ? (
                <div className={"cm-askquote" + (ask.text.length > 240 || ask.text.split(/\n/).length > 6 ? " long" : "")}>
                  {ask.text}
                </div>
              ) : null}
              <div className="cm-askacts">
                <button type="button" className="cm-ghost big" onClick={() => {
                  setAsk(null);
                  if (ask.kind === "reply") setTimeout(() => textRef.current && textRef.current.focus(), 0);
                }}>{ask.kind === "reply" ? "Back" : "Keep"}</button>
                <button type="button" className={"cm-btn big" + (ask.kind === "delete" ? " ruby" : "")}
                  onClick={() => { const a = ask; setAsk(null); if (a.kind === "reply") post(a.tok, a.b); else del(a.tok, a.c); }}>
                  {ask.kind === "reply" ? "Post publicly" : "Delete"}
                </button>
              </div>
            </div>
          ) : null}
        </MobileSheet>
      ) : null}
    </section>
  );
}
