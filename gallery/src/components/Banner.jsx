import React, { useEffect, useState } from "react";
import "../styles/shell.css";
import useFlavour from "../hooks/useFlavour.js";
import { apiGet } from "../api.js";
import MarkAnimated from "./MarkAnimated.jsx";

/* The banner (DC "Frontend Gallery" §1): one region owning hero/slim state.
   Hero: art + right-aligned brand block on top, a bottom band with the library
   bar on the left and stat pills + the metallic Generate/Loom/Folio action row
   on the right. Slim: a single 62px row (brand only for now — see slimSlot).
   The slim TOGGLE lives in the separator bar; this component just receives
   `slim`. Retires ArtBand.jsx; Strip's brand block folds in here (its copy is
   hidden by shell.css while Strip still mounts as the interim library bar).

   MOUNT POINTS for other workstreams:
   - libraryBar  — the library bar (Strip today, LibraryBar.jsx after its
                   refit) renders in the hero bottom band's left column.
   - slimSlot    — the slim row's flexible left area; the LibraryBar refit
                   mounts its compact search cluster here (DC slim keeps
                   search available at 62px). Empty today.
   Stats are LIVE: boot.stats paints first, then GET /api/stats (adds
   coverage_pct) refreshes on mount and after every generation lands. */

function StatPill({ value, label, emerald }) {
  return (
    <div className={"mgx-statpill" + (emerald ? " emerald" : "")}>
      <span className="mgx-statval">{value}</span>
      <span className="mgx-statlab">{label}</span>
    </div>
  );
}

export default function Banner({
  boot, slim, running, dockOpen, onToggleDock, onFolio,
  libraryBar, slimSlot, flavours,
}) {
  const band = boot.band || { crop: 30 };
  const fl = useFlavour(flavours, boot.build_stamp);

  /* live stats: boot.stats first (no flash of em-dashes), /api/stats after —
     same numbers the classic banner bakes in, plus the coverage percent. */
  const [stats, setStats] = useState(boot.stats || null);
  useEffect(() => {
    let dead = false;
    const pull = () =>
      apiGet("/api/stats")
        .then((d) => { if (!dead && d && !d.error) setStats((s) => ({ ...(s || {}), ...d })); });
    pull();
    const again = () => pull();
    document.addEventListener("mg-result", again);
    window.addEventListener("mg-gen-done", again);
    return () => {
      dead = true;
      document.removeEventListener("mg-result", again);
      window.removeEventListener("mg-gen-done", again);
    };
  }, []);

  /* THE EXPAND IS ONE MOTION (ROADMAP S4, 2026-09-06). shell.css's `.mgx-bnr.expanding`
     block carries the full diagnosis and the measured numbers; the short of it is that the
     banner's height is `auto` when it is a hero, `auto` cannot be interpolated, and so the
     snap back to it lands in the FIRST frame of the expand -- the jump the owner reported --
     while the min-height that can actually animate is left sliding the remainder. This flag
     pins the height at the slim 62px for the length of that animation, so the box follows
     min-height the whole way up exactly as it follows it the whole way down.

     Only the slim -> hero direction: the collapse never needed it and gets no class.

     DERIVED DURING RENDER, not in an effect, and that is the difference between a fix and a
     worse bug. An effect commits a frame LATE: the first version of this ran the flip in a
     useEffect and the harness read 172.3px at t=0, then 62px at t=20ms, then the climb --
     the banner now jumped UP to content height, dropped back to the slim row, and only then
     opened. React's own "adjusting state when a prop changes" idiom re-renders before the
     browser sees anything, so `slim` leaving and `expanding` arriving are ONE commit and one
     paint. `prevSlim` starting AT `slim` is also what skips the mount: an install that opens
     slim, or opens hero, paints its settled banner rather than half a second of a transition
     it never made.

     The 500 matches the .5s in shell.css's own transition; the two are the same number by
     construction and are commented as a pair at that end. Not transitionend: the
     reduced-motion block turns that transition off entirely, and an event that never fires
     would strand the pin -- which is also why that block un-pins this class directly. */
  const [prevSlim, setPrevSlim] = useState(slim);
  const [expanding, setExpanding] = useState(false);
  if (prevSlim !== slim) {
    setPrevSlim(slim);
    setExpanding(!slim);   // false on the way down, so a collapse also cancels a live pin
  }
  useEffect(() => {
    if (!expanding) return undefined;
    const t = setTimeout(() => setExpanding(false), 500);
    return () => clearTimeout(t);
  }, [expanding]);

  const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString());
  const s = stats || {};
  const live = (running && running.count) || 0;

  return (
    <div className={"mgx-bnr" + (slim ? " slim" : "") + (expanding ? " expanding" : "")}>
      {/* art layer, clipped on its own so band popovers can escape the banner */}
      <div className="mgx-art" style={{ "--crop": (band.crop != null ? band.crop : 30) + "%" }}>
        <img src="/branding/banner.png" alt="" onError={(e) => e.currentTarget.remove()} />
      </div>

      {/* brand column (hero) / brand row (slim) */}
      <div className="mgx-navcol">
        <div className="mgx-slimslot">{slimSlot || null}</div>
        <div className="mgx-brand">
          <div className="mgx-brandtxt">
            <div className="mgx-title">Moonglade Athenaeum</div>
            <button type="button" title="Click for version info"
              className={"mgx-flavour" + (fl.fading ? " fading" : "") + (fl.alt ? " fA" : " fB")}
              onClick={fl.reveal}>
              {fl.text}
            </button>
          </div>
          {/* #24: the header now WEARS the picked animation. The markup is the same
              tilt/sheen/halo it always had -- MarkAnimated is that structure plus the
              mark-anim-<id> class and the four settings, so the treatment the Control
              Panel writes is finally the treatment the header shows. */}
          <MarkAnimated boot={boot} size={slim ? 56 : 96} />
        </div>
      </div>

      {/* hero-only bottom band: library bar left · stats over actions right */}
      <div className="mgx-bottom">
        <div className="mgx-libslot">{libraryBar || null}</div>
        <div className="mgx-bnrright">
          <div className="mgx-statsrow">
            {live > 0 ? (
              <div className="mgx-nelwrap"
                title={live + " generation" + (live === 1 ? "" : "s") + " running — the dock shows them resolve"}>
                <div className="mgx-nelhalo" aria-hidden="true" />
                <img className="mgx-nelimg" src="/branding/nel_spinner.png" alt=""
                  onError={(e) => e.currentTarget.remove()} />
              </div>
            ) : null}
            <StatPill value={fmt(s.images)} label="IMAGES" />
            {s.videos ? <StatPill value={fmt(s.videos)} label="VIDEOS" /> : null}
            {s.coverage_pct != null ? (
              <StatPill value={s.coverage_pct + "%"} label="BACKED UP" emerald />
            ) : null}
          </div>
          <div className="mgx-actrow">
            <button type="button" data-dock-toggle="1"
              className={"mgx-metal mgx-gen" + (dockOpen ? " mgx-dockdim" : "")}
              onClick={onToggleDock}
              title="Open or close the Generate dock">
              ✦ Generate
            </button>
            <a className="mgx-metal mgx-metal-loom mgx-metal-md" href="/loom"
              style={{ textDecoration: "none" }}
              title="The Loom — storyboard for multi-clip video">
              ▰ The Loom
            </a>
            <button type="button" className="mgx-metal mgx-metal-folio mgx-metal-md"
              onClick={onFolio}
              title="The Folio of Honors">
              🏆 Folio
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
