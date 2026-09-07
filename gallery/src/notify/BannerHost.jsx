import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { subscribe, collapse, expand, requestUpdateOpen, subscribeUpdateHost, updateAffordance }
  from "./bannerStore.js";

/* BannerHost -- the React face of notify/bannerStore.js (owner ruling 2026-09-07, "update
   should be noticed anywhere"). One strip, portaled to document.body exactly like
   ToastHost.jsx so it is a body-level sibling of #root on every shell the notify root
   mounts on: the desktop gallery, the phone, the Loom and the setup wizard.

   IT PUSHES, IT NEVER COVERS. A fixed strip at the top of the viewport would sit straight
   over the desktop shell's sticky header (.mgx-hdr) and over the phone hero's four icon
   buttons, which are the first thing under the notch. So the strip measures its own height
   -- including the safe-area padding it takes on a notched phone -- publishes it as
   --mg-updbanner-h on <html>, and notify.css moves each shell's own top chrome down by
   exactly that (see the .mg-updbanner block there). The measurement is real rather than a
   guessed constant because the line wraps on a narrow phone.

   The × is deliberately absent: "Not now" folds the strip to a pill for this tab and the
   pill re-expands on tap. Nothing here can apply an update -- Update asks the shell to open
   the surface that owns the confirm (bannerStore.requestUpdateOpen).

   NO BUTTON THAT DOES NOTHING (2026-09-07, later the same day, correcting the first cut).
   The setup wizard mounts this root but registers no update host, and it is already served
   at "/" -- so its Update button pressed nothing at all. The strip now asks the store what
   this shell can actually do (bannerStore.updateAffordance) and draws the button only when
   the press can reach a confirm surface, with a short reason in its place when it cannot
   ("finish setup first" on the wizard). The Loom keeps its button: its press crosses to the
   gallery and the intent crosses with it. */

export default function BannerHost() {
  const [state, setState] = useState({ banner: null, collapsed: false });
  const [, setHasHost] = useState(false);
  const ref = useRef(null);
  useEffect(() => subscribe((banner, isCollapsed) => setState({ banner, collapsed: isCollapsed })), []);
  /* The shells register their host in their own mount effect, which can land after this one;
     the strip re-reads the affordance whenever that changes rather than deciding once. */
  useEffect(() => subscribeUpdateHost(setHasHost), []);
  const { banner, collapsed } = state;

  useLayoutEffect(() => {
    const root = typeof document !== "undefined" ? document.documentElement : null;
    const el = ref.current;
    if (!root) return undefined;
    if (!el) {
      root.classList.remove("mg-updbanner-on");
      root.style.removeProperty("--mg-updbanner-h");
      return undefined;
    }
    root.classList.add("mg-updbanner-on");
    const measure = () => root.style.setProperty("--mg-updbanner-h", el.offsetHeight + "px");
    measure();
    const ro = typeof ResizeObserver === "function" ? new ResizeObserver(measure) : null;
    if (ro) ro.observe(el);
    return () => {
      if (ro) ro.disconnect();
      root.classList.remove("mg-updbanner-on");
      root.style.removeProperty("--mg-updbanner-h");
    };
  }, [banner, collapsed]);

  if (!banner) return null;
  const { canOpen, why } = updateAffordance();
  return createPortal(
    <div ref={ref} className={"mg-updbanner" + (collapsed ? " small" : "")}
      role="status" aria-live="polite">
      {collapsed ? (
        <button type="button" className="mgub-pill" onClick={expand}
          title={"Moonglade " + banner.version + " is ready"}>
          {banner.version} ready
        </button>
      ) : (
        <>
          <span className="mgub-line">Moonglade {banner.version} is ready</span>
          {why ? <span className="mgub-why">{why}</span> : null}
          {canOpen ? (
            <button type="button" className="mgub-go" onClick={requestUpdateOpen}>Update</button>
          ) : null}
          <button type="button" className="mgub-later" onClick={collapse}>Not now</button>
        </>
      )}
    </div>,
    document.body,
  );
}
