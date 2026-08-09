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
    sticky: !!o.sticky,
    out: false,
  }]);
  emit();
  const remove = () => dismiss(id);
  if (!o.sticky) setTimeout(remove, o.ttl || 5200);
  return remove;
}
