/* notify/toastStore.js -- the corner-toast engine, ported from static/mg-notify.js's Toast IIFE
   (no-vanilla campaign, component 6). A MODULE SINGLETON, deliberately outside any React
   lifecycle: show() must work the moment the bundle evaluates (early submit errors) and keep
   working regardless of what mounts or unmounts. The React <ToastHost> merely renders this
   store's state; the timers live here.

   API (published as window.Toast by notify/index.jsx, same contract as the vanilla):
     show({kind, title, msg, icon, thumb, sticky, ttl}) -> remove()
       kind: '' info (lavender) | 'ok' (emerald) | 'err' (red) | 'unlock' (gold)
       icon: overrides the per-kind default glyph
       thumb: image URL, rendered as a background-image span (never a raw <img src> -- the
              design-spec toast-icon rule, so the preload scanner can't fetch it)
       sticky: stays until the × / remove(); else auto-dismisses after ttl (default 5200ms)
       avatar: image URL drawn as a round portrait in place of the glyph (the post-update
               toast's Nel, Session I 3b) -- a background-image span, same rule as thumb
       action: {label, run} -- one button on the toast; pressing it runs `run` and
               dismisses the toast (the post-update toast's "What's new")
       actions: [{label, run, tone}] -- up to two buttons in a row under the text, for a
               toast that asks a question (the narrator's choice). Pressing one runs it and
               dismisses the toast; `tone: "ruby"` draws it in the destructive/spicy red.
               Ignored when `action` is given.
       foot: a small line under the buttons (the choice's "you can change this later")
       quote: a block of quoted text under the title, clamped at six lines with a fade (the
              reply's question quotes the reply in full -- Sessions R + Y, R6c)
       wide: the toast widens to 420 px (a question carrying a quote)
       code: a short mono tail on the title ("Updated to" + "3.14")
   The two-phase exit (add .out, unmount 340ms later) matches the exit-animation duration. */

let seq = 0;
let toasts = [];            // [{id, kind, icon, title, msg, thumb, sticky, out}]
const subs = new Set();

function emit() { subs.forEach((fn) => fn(toasts)); }

export function subscribe(fn) {
  subs.add(fn);
  fn(toasts);
  return () => subs.delete(fn);
}

export function getToasts() { return toasts; }

export function dismiss(id) {
  const t = toasts.find((x) => x.id === id);
  if (!t || t.out) return;
  t.out = true;                                  // plays mg-toast-out
  toasts = toasts.slice();
  emit();
  setTimeout(() => {
    toasts = toasts.filter((x) => x.id !== id);  // unmount after the 340ms exit
    emit();
  }, 340);
}

export function show(o) {
  o = o || {};
  const kind = o.kind || "";
  const icon = o.icon || (kind === "ok" ? "✓" : kind === "err" ? "⚠" : kind === "unlock" ? "🏆" : "◉");
  const id = ++seq;
  toasts = toasts.concat([{
    id, kind, icon,
    title: o.title || "",
    msg: o.msg || "",
    thumb: o.thumb || "",
    avatar: o.avatar || "",
    code: o.code || "",
    action: o.action && typeof o.action.run === "function"
      ? { label: String(o.action.label || ""), run: o.action.run } : null,
    actions: !o.action && Array.isArray(o.actions)
      ? o.actions.filter((a) => a && typeof a.run === "function").slice(0, 2)
        .map((a) => ({ label: String(a.label || ""), run: a.run, tone: a.tone === "ruby" ? "ruby" : "" }))
      : [],
    foot: o.foot ? String(o.foot) : "",
    quote: o.quote ? String(o.quote) : "",
    wide: !!o.wide,
    sticky: !!o.sticky,
    out: false,
  }]);
  emit();
  const remove = () => dismiss(id);
  if (!o.sticky) setTimeout(remove, o.ttl || 5200);
  return remove;
}
