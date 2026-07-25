import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// The reel's "Play sequence" was HARD-muted: <video autoPlay muted> with nothing able to
// turn sound on, while the exported mp4 carries real audio. So a storyboard could be
// reviewed end to end without ever hearing what the render will actually sound like -- and
// nothing in the UI hinted that silence was a player choice rather than silent footage.
//
// master-storyboard.jsx is JSX compiled by esbuild (and historically Babel in-browser), not
// an importable module here, so this file follows the same convention as its neighbours
// (loom-df-veil-stacking, loom-picker-flyout-overlay): the non-obvious wiring is pinned by
// source assertions. Two subtleties are pinned deliberately, because both are the kind of
// thing that silently reverts:
//
//  1. muting is applied IMPERATIVELY through the ref, not left to React's `muted` JSX prop.
//     React does not reliably reflect `muted` onto a <video> element -- it is a documented
//     rough edge -- so a JSX-only fix can appear correct in source and do nothing live.
//  2. the effect re-applies on SHOT CHANGE. The element carries key={clip.mid}, so advancing
//     a shot destroys and recreates it, and a fresh element comes back with the initial
//     `muted` attribute set. Without the shot index in the dependency list, unmuting would
//     silently undo itself at every shot boundary -- the exact bug this fixes, just moved.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8");

function seqPlayerSource() {
  const start = src.indexOf("function SequencePlayer(");
  assert.ok(start !== -1, "SequencePlayer no longer exists in master-storyboard.jsx");
  // to the next top-level function declaration
  const rest = src.slice(start + 10);
  const nextFn = rest.indexOf("\nfunction ");
  return nextFn === -1 ? src.slice(start) : src.slice(start, start + 10 + nextFn);
}

describe("reel playback audio", () => {
  const body = seqPlayerSource();

  test("the reel player owns a mute state rather than hardcoding silence", () => {
    assert.match(body, /useState\(/, "SequencePlayer has no state at all");
    assert.match(body, /\[\s*muted\s*,\s*setMuted\s*\]/,
      "no muted/setMuted state -- the reel is still hard-muted with no way to hear audio");
  });

  test("mute is applied imperatively through the video ref", () => {
    assert.match(body, /\.muted\s*=/,
      "muted is never assigned on the element; React's `muted` JSX prop alone does not " +
      "reliably reflect onto a <video>, so a source-only fix can do nothing live");
  });

  test("the mute effect re-applies when the shot changes", () => {
    // the element is keyed by clip.mid, so each shot boundary remounts it
    assert.match(body, /key=\{clip\.mid\}/,
      "the reel video is no longer keyed per shot -- re-check whether the remount " +
      "reasoning below still holds");
    const effects = body.match(/useEffect\([\s\S]*?\}\s*,\s*\[[^\]]*\]\s*\)/g) || [];
    const muteEffect = effects.find((e) => /\.muted\s*=/.test(e));
    assert.ok(muteEffect, "no useEffect applies the mute state to the element");
    const deps = muteEffect.slice(muteEffect.lastIndexOf("["));
    assert.match(deps, /\bmuted\b/, "mute effect does not react to the mute state: " + deps);
    assert.match(deps, /\bi\b/,
      "mute effect does not re-run on shot change, so advancing a shot remounts the " +
      "element and silently re-mutes it: " + deps);
  });

  test("there is a user-facing control in the player bar", () => {
    assert.match(body, /setMuted\(/, "nothing ever toggles the mute state");
    assert.match(body, /sb-seq-bar/, "the player bar is gone -- where did the control go?");
  });

  test("autoplay still starts muted, so playback is not blocked", () => {
    // Browsers block autoplay WITH sound absent a user gesture. Opening the reel is a
    // click, but the initial state must still be muted-safe: a reel that silently fails to
    // start is worse than one that starts quiet.
    assert.match(body, /useState\(true\)/,
      "the mute state must initialise to true so autoplay is never blocked");
  });
});

// ---------------------------------------------------------------------------
// ShotPreview -- the per-shot scrub player on each card. Owner 2026-07-25: "preview pane only
// has the play/pause no sound - By design? Seems we want audio in the scrub too - especially
// when we add the audio track at some point."
//
// It needs a DIFFERENT rule from the reel, because this player scrubs on hover
// (onMouseMove={scrub}) and a board holds many cards. Sound tied to the element alone would
// mean dragging the mouse across the board machine-guns audio from every card it crosses, and
// even on one card a hover-scrub is the playhead being thrown around, which sounds like
// garbage rather than like the shot.
//
// So the gate is sound AND actually-playing: audio during a real play, silence while
// scrubbing. The `playing` state already exists for the play/pause button, so the effect
// depends on both.
// ---------------------------------------------------------------------------
describe("per-shot preview audio", () => {
  function shotPreviewSource() {
    const start = src.indexOf("function ShotPreview(");
    assert.ok(start !== -1, "ShotPreview no longer exists in master-storyboard.jsx");
    const rest = src.slice(start + 10);
    const nextFn = rest.indexOf("\nfunction ");
    return nextFn === -1 ? src.slice(start) : src.slice(start, start + 10 + nextFn);
  }
  const body = shotPreviewSource();

  test("the preview owns a sound state", () => {
    assert.match(body, /\[\s*soundOn\s*,\s*setSoundOn\s*\]/,
      "no soundOn/setSoundOn state -- the per-shot preview is still hard-muted");
  });

  test("it defaults to silent", () => {
    assert.match(body, /useState\(false\)[^\n]*\/\/[^\n]*sound|soundOn[\s\S]{0,80}useState\(false\)/,
      "sound must default OFF: a board of cards that scrub on hover would otherwise play " +
      "audio at every card the pointer crosses");
  });

  test("audio is gated on ACTUALLY PLAYING, not merely on the toggle", () => {
    const effects = body.match(/useEffect\([\s\S]*?\}\s*,\s*\[[^\]]*\]\s*\)/g) || [];
    const muteEffect = effects.find((e) => /\.muted\s*=/.test(e));
    assert.ok(muteEffect, "no useEffect applies the sound state to the element");
    assert.match(muteEffect, /playing/,
      "the mute effect ignores `playing`, so a hover-scrub would make noise: " + muteEffect);
    const deps = muteEffect.slice(muteEffect.lastIndexOf("["));
    assert.match(deps, /soundOn/, "effect does not react to the toggle: " + deps);
    assert.match(deps, /playing/, "effect does not re-run when playback starts/stops: " + deps);
  });

  test("there is a toggle in the preview's control row", () => {
    assert.match(body, /setSoundOn\(/, "nothing toggles the sound state");
    assert.match(body, /sb-shotprev-ctrls/, "the control row is gone -- where did the toggle go?");
  });
});
