import React from "react";

/* The art band: pure decoration plus ONE anchored column -- the destination rail,
   Manuscript-style small-caps links with the gold underline. Fixed height (the
   locked 340 default; the Branding panel makes it a setting later), so there is
   nothing here that can reflow. The reflow bug has no ingredients. */
export default function ArtBand({ boot }) {
  const band = boot.band || { height: 340, crop: 30 };
  const csrf = boot.csrf || "";
  // Height now belongs to the sticky header (--bnr-hero), not the band: the band
  // fills it. Only the crop slice is the band's own business; the Branding
  // panel's future size setting will drive --bnr-hero.
  return (
    <div className="artband" style={{ "--crop": band.crop + "%" }}>
      <img className="artimg" src="/branding/banner.png" alt="" />
      <nav className="rail" aria-label="Destinations">
        <a href="/panel">Panel</a>
        <a href="/health">Health</a>
        <a className="soon" title="Ports with its panel — use the classic gallery meanwhile">Contests</a>
        <a className="soon" title="Ports with its panel — use the classic gallery meanwhile">My Art</a>
        <a className="soon" title="Publish — arrives with Epic C">Publish</a>
        <a className="soon" title="Folio of Honors — ports with its panel">Folio</a>
        {boot.user ? (
          <form method="post" action="/logout" className="railout">
            <input type="hidden" name="csrf" value={csrf} />
            <button type="submit" title={"Signed in as " + boot.user}>Sign out</button>
          </form>
        ) : null}
      </nav>
      {/* Transient tier, same as the rail: rides the art away on scroll. Restored
          2026-07-30 -- this block was dropped entirely in an earlier restructure
          (owner QA caught it: "stats not visible"). */}
      <Stats stats={boot.stats} />
    </div>
  );
}

function Stats({ stats }) {
  const s = stats || {};
  const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString());
  return (
    <span className="gt-stats">
      <span><b>{fmt(s.images)}</b><i>images</i></span>
      {s.videos ? <span><b>{fmt(s.videos)}</b><i>videos</i></span> : null}
      {s.collections ? <span><b>{fmt(s.collections)}</b><i>collections</i></span> : null}
    </span>
  );
}
