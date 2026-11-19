/* notify/doneNotice.js -- the wording of the corner notice when an owner-started job finishes.
   Pure (no store, no DOM) so the loom node tests can import it.

   "Added to your gallery." is true only of a job that puts art in the library. The job `type`
   values the server writes to jobs.jsonl (moonglade/gallery.py _log_job calls) are:
     generate  -- every generation the web app starts (image, video, edit, fix, upscale, Loom);
                  the client registers it as type "generate" (notify/jobs.js) and the server
                  writes the finish (moonglade/gallery.py, the type="generate" _log_job rows)
     import    -- "Import task <id>" (gallery.py `type="import"`), collects a task's art
     panel     -- a Control Panel action; the row also carries `action`, the PANEL_ACTIONS key
     delete / claim / update / integrity / cli -- never add art (delete and claim, update and
                  integrity have their own wording or no toast; cli is a terminal command)
   Of the panel actions only the ones that PULL art in add to the gallery. The rest (Duplicate
   audit, Catalog stats, Organize preview, the Similar index, hashes ...) just finish. */

// PANEL_ACTIONS keys in moonglade/gallery.py whose job collects new art.
export const PANEL_ADDS_ART = new Set(["sync", "resync-full", "test-pull", "sync-videos"]);
const ADDING_TYPES = new Set(["generate", "import"]);

export function addsToGallery(j) {
  j = j || {};
  if (ADDING_TYPES.has(j.type)) return true;
  return j.type === "panel" && PANEL_ADDS_ART.has(j.action);
}

// -> { title, msg } for a job that finished cleanly.
export function doneNotice(j) {
  j = j || {};
  if (j.type === "delete") return { title: j.label || "Generation", msg: "Gone from PixAI." };
  const title = (j.label || "Generation") + " — done";
  return { title, msg: addsToGallery(j) ? "Added to your gallery." : "" };
}
