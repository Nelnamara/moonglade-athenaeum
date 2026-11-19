// Pins the video-retirement clock (V3.2 leaves on 2026-11-23) to a day before it, so a test that
// uses V3.2 as an ordinary engine means the same thing on any date. Import this FIRST.
import { setVideoClock } from "../../../gallery/src/gen/videoDrawerCore.js";
setVideoClock(() => Date.parse("2026-11-18T12:00:00Z"));
