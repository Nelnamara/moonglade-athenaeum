/* gen/refChips.js -- the @image/@video/@audio reference chips inside the video drawer's
   contenteditable prompt, lifted out of VideoDrawer.jsx (2026-08-25) so the DOM algorithm is a
   real module: unit-testable, and fixable in exactly one place. The logic is the component's
   verbatim, plus the two fixes from the owner's 2026-08-25 QA recording:

   FIX 1 -- chips no longer NEST. makeChip() puts the literal tag text ("@image1") inside the
   chip, and chipify()'s TreeWalker used to walk EVERY text node -- including the label inside an
   existing chip -- so each blur (chipify(final=true)) re-matched the tag inside the chip and
   wrapped it in another chip: one extra layer per focus/blur cycle (the pile-up in the owner's
   video). The walker now skips text that already lives inside a .mgd-chip, and a self-heal pass
   flattens any chip that was already nested by the old code, so a corrupted field repairs itself
   on the next chipify instead of needing a reload.

   NOTE the spend-relevant invariant: promptText() reads a chip's data-ref and never descends
   into it, so even a piled-up field always emitted the CORRECT prompt text -- the corruption was
   visual only, never in a submit payload. Keep it that way: data-ref is the truth, the chip's
   inner DOM is presentation.

   The floating thumbnail preview is NOT here -- it belongs to the component (it owns the
   portaled preview element); chips reach it through the enter/leave hooks. */

export const REF_RE = /@(?:image|video|audio)\d+/g;

export const escHtml = (s) =>
  (s == null ? "" : String(s)).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const chipLead = (info) =>
  info && info.thumb ? '<img src="' + escHtml(info.thumb) + '" alt="">' : (info && info.kind === "audio" ? "♪ " : "");

/* One chip element. hooks = {enter(mid, el), leave()} -- wired to the component's floating
   preview; absent hooks (or an audio ref) mean no hover preview. */
export function makeChip(tag, info, hooks) {
  const c = document.createElement("span");
  c.className = "mgd-chip";
  c.contentEditable = "false";
  c.setAttribute("data-ref", tag);
  c.innerHTML = chipLead(info) + tag;
  if (info && info.mid && info.kind !== "audio" && hooks) {
    c.onmouseenter = () => hooks.enter(info.mid, c);
    c.onmouseleave = () => hooks.leave();
  }
  return c;
}

/* Wrap every known @ref in `ce`'s text into a chip. `final=false` (the input debounce) leaves a
   tag still being typed at the end of its text node alone; `final=true` (blur / programmatic set)
   chips everything. Restores the caret when the replaced text node held it. */
export function chipify(ce, map, final, hooks) {
  if (!ce) return;
  // Self-heal chips the pre-fix code nested (chip-inside-chip): rebuild the OUTERMOST chip's
  // presentation from its data-ref. Handlers live on the chip element itself, so they survive.
  ce.querySelectorAll(".mgd-chip .mgd-chip").forEach((inner) => {
    let outer = inner;
    while (outer.parentElement && outer.parentElement.closest(".mgd-chip")) outer = outer.parentElement.closest(".mgd-chip");
    if (outer && outer.querySelector(".mgd-chip")) {
      const tag = outer.getAttribute("data-ref") || "";
      if (!/^@(?:image|video|audio)\d+$/.test(tag)) { outer.remove(); return; }  // junk ref: drop, never innerHTML it
      outer.innerHTML = chipLead(map[tag]) + tag;
    }
  });
  const sel = window.getSelection();
  const walker = document.createTreeWalker(ce, NodeFilter.SHOW_TEXT), nodes = [];
  let tn;
  while ((tn = walker.nextNode())) {
    // FIX 1: a chip's own label text is presentation, not prompt -- never re-chipify it.
    if (tn.parentElement && tn.parentElement.closest(".mgd-chip")) continue;
    nodes.push(tn);
  }
  nodes.forEach((node) => {
    const t = node.nodeValue, found = [];
    let m;
    REF_RE.lastIndex = 0;
    while ((m = REF_RE.exec(t)) !== null) {
      if (!map[m[0]]) continue;
      if (!final && m.index + m[0].length === t.length) continue;   // still typing at the end
      found.push({ i: m.index, tag: m[0] });
    }
    if (!found.length) return;
    const caretHere = sel.rangeCount && sel.getRangeAt(0).startContainer === node;
    const frag = document.createDocumentFragment();
    let pos = 0;
    found.forEach((f) => {
      if (f.i > pos) frag.appendChild(document.createTextNode(t.slice(pos, f.i)));
      frag.appendChild(makeChip(f.tag, map[f.tag], hooks));
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

/* The prompt as plain text: chips contribute their data-ref (never their inner DOM), <br> is a
   newline, nbsp normalizes to space. This is the text a PAID submit carries -- byte-identical to
   the component's original (the   was a literal nbsp there). */
export function promptText(ce) {
  if (!ce) return "";
  let out = "";
  (function walk(n) {
    n.childNodes.forEach((c) => {
      if (c.nodeType === 3) out += c.nodeValue;
      else if (c.classList && c.classList.contains("mgd-chip")) out += c.getAttribute("data-ref");
      else if (c.nodeName === "BR") out += "\n";
      else walk(c);
    });
  })(ce);
  return out.replace(/ /g, " ").trim();
}
