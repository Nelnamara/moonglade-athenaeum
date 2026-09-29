import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { AT_REF_RE } from "../gen/tsubakiCore.js";

/* AtPrompt -- the Image tab's prompt on the Context side (Session H decision 2, the handoff's
   frame B): a contenteditable with @image chips, the same grammar as the Video tab's
   Multi-Reference prompt (gen/refChips.js), plus what B adds:
     - typing @ opens a menu of the context images (thumb + @imageN, then "add an image…");
       ↑ ↓ move, ↵ / Tab or a click inserts a chip, Esc closes;
     - a chip is ONE token -- contenteditable=false, so backspace removes it whole -- and is
       sent as the literal @imageN text PixAI reads (the chip's data-ref; promptText below);
     - a chip whose number points at no slot (the slot was removed -- @image0 after
       tsubakiCore.renumberAfterRemove -- or a number past the last slot) turns peach and reads
       "no image"; the host's gate refuses Generate while one is there;
     - phone: the suggestions are a chip row under the prompt while it has focus (the phone's
       "above the keyboard").

   `value` (the prompt STRING) is the one truth, owned by useGenerate: the DOM is rebuilt from
   it whenever it differs from what the DOM already says (a renumber, a snippet, "Edit with
   Tsubaki"'s seed), and every edit reports the DOM's text back through onChange. The text a
   paid submit carries is therefore the string the rest of the drawer reads, never a DOM
   read at submit time. */

function chipNode(tag, ctx) {
  const n = Number(String(tag).slice(6));
  const img = n >= 1 && n <= ctx.length ? ctx[n - 1] : null;
  const c = document.createElement("span");
  c.className = "mgat-chip" + (img ? "" : " dead");
  c.contentEditable = "false";
  c.setAttribute("data-ref", tag);
  c.title = img ? tag + " — context image " + n : tag + " points at no image — fix or delete it";
  if (img && img.thumb) {
    const im = document.createElement("img");
    im.src = img.thumb;
    im.alt = "";
    c.appendChild(im);
  } else {
    const ph = document.createElement("i");
    ph.className = "mgat-chipph";
    c.appendChild(ph);
  }
  const label = document.createElement("span");
  label.className = "mgat-chiptag";
  label.textContent = img ? tag : "no image";
  c.appendChild(label);
  return c;
}

/* The prompt as text: a chip contributes its data-ref, <br> a newline, nbsp a space. */
export function atText(ce) {
  if (!ce) return "";
  let out = "";
  (function walk(n) {
    n.childNodes.forEach((c) => {
      if (c.nodeType === 3) out += c.nodeValue;
      else if (c.getAttribute && c.getAttribute("data-ref")) out += c.getAttribute("data-ref");
      else if (c.nodeName === "BR") out += "\n";
      else { if (c.nodeName === "DIV" && out && !out.endsWith("\n")) out += "\n"; walk(c); }
    });
  })(ce);
  return out.replace(/ /g, " ");
}

/* Rebuild the whole field from the string (an external change). */
function renderInto(ce, text, ctx) {
  ce.textContent = "";
  const re = new RegExp(AT_REF_RE.source, "g");
  const str = String(text || "");
  let pos = 0;
  let m;
  const addText = (t) => {
    const parts = t.split("\n");
    parts.forEach((p, i) => {
      if (i) ce.appendChild(document.createElement("br"));
      if (p) ce.appendChild(document.createTextNode(p));
    });
  };
  while ((m = re.exec(str)) !== null) {
    if (m.index > pos) addText(str.slice(pos, m.index));
    ce.appendChild(chipNode(m[0], ctx));
    pos = m.index + m[0].length;
  }
  if (pos < str.length) addText(str.slice(pos));
}

/* Chip typed tokens in place (the Video prompt's rule: a token still being typed at the end of
   its text node waits for the pause or the blur). */
function chipTyped(ce, ctx, final) {
  const walker = document.createTreeWalker(ce, NodeFilter.SHOW_TEXT);
  const nodes = [];
  let tn;
  while ((tn = walker.nextNode())) {
    if (tn.parentElement && tn.parentElement.closest("[data-ref]")) continue;
    nodes.push(tn);
  }
  const sel = window.getSelection();
  nodes.forEach((node) => {
    const t = node.nodeValue;
    const re = new RegExp(AT_REF_RE.source, "g");
    const found = [];
    let m;
    while ((m = re.exec(t)) !== null) {
      if (!final && m.index + m[0].length === t.length) continue;
      found.push({ i: m.index, tag: m[0] });
    }
    if (!found.length) return;
    const caretHere = sel && sel.rangeCount && sel.getRangeAt(0).startContainer === node;
    const frag = document.createDocumentFragment();
    let pos = 0;
    found.forEach((f) => {
      if (f.i > pos) frag.appendChild(document.createTextNode(t.slice(pos, f.i)));
      frag.appendChild(chipNode(f.tag, ctx));
      pos = f.i + f.tag.length;
    });
    const tail = document.createTextNode(t.slice(pos));
    frag.appendChild(tail);
    node.parentNode.replaceChild(frag, node);
    if (caretHere) {
      const r = document.createRange();
      r.setStart(tail, tail.length); r.collapse(true);
      sel.removeAllRanges(); sel.addRange(r);
    }
  });
}

/* The "@…" being typed right before the caret, or null. */
function atQuery(ce) {
  const sel = window.getSelection();
  if (!sel || !sel.rangeCount || !ce.contains(sel.anchorNode)) return null;
  const r = sel.getRangeAt(0);
  if (!r.collapsed || r.startContainer.nodeType !== 3) return null;
  const before = r.startContainer.nodeValue.slice(0, r.startOffset);
  const m = /(^|\s)@([a-z]*\d*)$/i.exec(before);
  if (!m) return null;
  return { node: r.startContainer, start: r.startOffset - m[2].length - 1, end: r.startOffset, q: m[2] };
}

export default function AtPrompt({
  value, onChange, ctx, onAddImage, placeholder, phone, className, style, onFocusChange,
}) {
  const ceRef = useRef(null);
  const wrapRef = useRef(null);
  const [menu, setMenu] = useState(null);   // {x, y, up, at, idx} while the @ menu is open
  const [focused, setFocused] = useState(false);
  const typing = useRef(0);
  const lastRange = useRef(null);
  const ctxKey = (ctx || []).map((c) => c.media_id + "|" + (c.thumb || "")).join(",");

  // External changes rebuild the DOM (a renumber, a snippet, a seed); our own edits do not,
  // because by then the DOM already says exactly `value`.
  useLayoutEffect(() => {
    const ce = ceRef.current;
    if (!ce) return;
    if (atText(ce) !== String(value || "")) renderInto(ce, value, ctx || []);
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  // The slots changed (added, removed, renumbered): every chip re-reads its image.
  useLayoutEffect(() => {
    const ce = ceRef.current;
    if (ce) renderInto(ce, value, ctx || []);
  }, [ctxKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const report = useCallback(() => {
    const ce = ceRef.current;
    if (!ce) return;
    const t = atText(ce);
    if (!t.trim() && ce.innerHTML) ce.innerHTML = "";         // keep :empty for the placeholder
    onChange(t);
  }, [onChange]);

  const items = (ctx || []).map((c, i) => ({ tag: "@image" + (i + 1), thumb: c.thumb }));

  const openMenuAt = () => {
    const ce = ceRef.current, wrap = wrapRef.current;
    const at = atQuery(ce);
    if (!at || phone) { setMenu(null); return; }
    const r = document.createRange();
    r.setStart(at.node, at.start); r.setEnd(at.node, at.start + 1);
    const rc = r.getBoundingClientRect();
    const wr = wrap.getBoundingClientRect();
    const roomBelow = window.innerHeight - rc.bottom;
    setMenu((old) => ({
      x: Math.max(0, Math.min(rc.left - wr.left, wr.width - 200)),
      y: roomBelow > 170 ? rc.bottom - wr.top + 6 : rc.top - wr.top - 6,
      up: roomBelow <= 170, at, idx: old ? Math.min(old.idx, items.length) : 0,
    }));
  };

  /* Insert a chip for `tag` at the caret, replacing the "@…" being typed when there is one. */
  const insertChip = (tag, at) => {
    const ce = ceRef.current;
    if (!ce) return;
    ce.focus();
    const sel = window.getSelection();
    let range;
    if (at && at.node && ce.contains(at.node)) {
      range = document.createRange();
      range.setStart(at.node, at.start); range.setEnd(at.node, at.end);
    } else if (lastRange.current && ce.contains(lastRange.current.startContainer)) {
      range = lastRange.current;
    } else {
      range = document.createRange();
      range.selectNodeContents(ce); range.collapse(false);
    }
    range.deleteContents();
    const chip = chipNode(tag, ctx || []);
    const space = document.createTextNode(" ");
    range.insertNode(space);
    range.insertNode(chip);
    const after = document.createRange();
    after.setStart(space, 1); after.collapse(true);
    sel.removeAllRanges(); sel.addRange(after);
    lastRange.current = after.cloneRange();
    setMenu(null);
    report();
  };

  const pickAdd = async (at) => {
    setMenu(null);
    if (!onAddImage) return;
    const n = await onAddImage();       // resolves to the new slot's number, or 0
    if (n > 0) insertChip("@image" + n, at);
  };

  const onKeyDown = (e) => {
    if (menu) {
      const count = items.length + (onAddImage ? 1 : 0);
      if (e.key === "ArrowDown") { e.preventDefault(); setMenu({ ...menu, idx: (menu.idx + 1) % Math.max(1, count) }); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); setMenu({ ...menu, idx: (menu.idx - 1 + count) % Math.max(1, count) }); return; }
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); setMenu(null); return; }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        if (menu.idx < items.length) insertChip(items[menu.idx].tag, menu.at);
        else pickAdd(menu.at);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      // a line break, never a <div>: the text reads one \n per break
      e.preventDefault();
      document.execCommand("insertLineBreak");
      report();
    }
  };

  const onInput = () => {
    report();
    openMenuAt();
    clearTimeout(typing.current);
    typing.current = setTimeout(() => {
      const ce = ceRef.current;
      if (ce) { chipTyped(ce, ctx || [], false); report(); }
    }, 300);
  };

  const onPaste = (e) => {
    e.preventDefault();
    const t = (e.clipboardData && e.clipboardData.getData("text/plain")) || "";
    document.execCommand("insertText", false, t);
    const ce = ceRef.current;
    if (ce) { chipTyped(ce, ctx || [], true); report(); }
  };

  const remember = () => {
    const sel = window.getSelection();
    if (sel && sel.rangeCount && ceRef.current && ceRef.current.contains(sel.anchorNode)) {
      lastRange.current = sel.getRangeAt(0).cloneRange();
    }
  };

  useEffect(() => () => clearTimeout(typing.current), []);

  return (
    <div ref={wrapRef} className={"mgat" + (phone ? " phone" : "")}>
      <div ref={ceRef} className={"mgat-ce" + (className ? " " + className : "")} style={style}
        contentEditable suppressContentEditableWarning role="textbox" aria-multiline="true"
        aria-label="Prompt" data-placeholder={placeholder}
        onInput={onInput} onKeyDown={onKeyDown} onPaste={onPaste}
        onKeyUp={remember} onMouseUp={remember}
        onFocus={() => { setFocused(true); if (onFocusChange) onFocusChange(true); }}
        onBlur={() => {
          remember();
          const ce = ceRef.current;
          if (ce) { chipTyped(ce, ctx || [], true); report(); }
          // The phone's chip row folds a beat AFTER the blur: folding it at once moves every
          // control under the prompt up while the tap that caused the blur is still landing,
          // and the tap then lands on whatever slid under the finger.
          setTimeout(() => {
            if (ceRef.current && document.activeElement === ceRef.current) return;
            setFocused(false);
          }, 220);
          if (onFocusChange) onFocusChange(false);
          setTimeout(() => setMenu(null), 120);
        }} />
      {menu && (
        <div className={"mgat-menu" + (menu.up ? " up" : "")} role="listbox"
          style={{ left: menu.x, top: menu.y }}
          onMouseDown={(e) => e.preventDefault()}>
          {items.map((it, i) => (
            <button type="button" key={it.tag} role="option" aria-selected={menu.idx === i}
              className={"mgat-opt" + (menu.idx === i ? " on" : "")}
              onClick={() => insertChip(it.tag, menu.at)}>
              {it.thumb ? <img src={it.thumb} alt="" /> : <i className="mgat-optph" />}
              <span className="mgat-opttag">{it.tag}</span>
              <span className="sp" />
              {menu.idx === i ? <span className="mgat-optkey">↵</span> : null}
            </button>
          ))}
          {onAddImage && (
            <button type="button" className={"mgat-opt add" + (menu.idx === items.length ? " on" : "")}
              onClick={() => pickAdd(menu.at)}>
              <i className="mgat-optph" /><span>add an image…</span>
            </button>
          )}
        </div>
      )}
      {phone && focused && items.length > 0 && (
        <div className="mgat-row" onMouseDown={(e) => e.preventDefault()}>
          {items.map((it) => (
            <button type="button" key={it.tag} className="mgat-rowchip"
              onPointerDown={(e) => e.preventDefault()}
              onClick={() => insertChip(it.tag, atQuery(ceRef.current))}>
              {it.thumb ? <img src={it.thumb} alt="" /> : <i className="mgat-optph" />}{it.tag}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
