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

  const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString());
  const s = stats || {};
  const live = (running && running.count) || 0;

  return (
    <div className={"mgx-bnr" + (slim ? " slim" : "")}>
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
