/* ONLY COPIES (#66). A picture PixAI no longer has -- its task left your PixAI history as of the last
   check, or PixAI dropped that one image -- is the only copy anywhere; the server marks such a row
   `archive_only` (moonglade_gallery.is_archive_only) and the grid badges it ARCHIVE.

   The owner's ruling on the 2026-10-03 walk: WARN, DON'T BLOCK. The bulk "Delete locally" and
   Duplicate Review take only copies with the rest, and their confirm names them first. The words say
   what really happens next, which tests/test_archive_only_guard.py proves on the server: the Trash's
   Restore puts the picture AND its catalog row back, and Duplicate Review's Undo does the same.
   loom/test/only-copy.test.js pins this file. */

/* The duplicate tiers whose members are DIFFERENT pictures. In the byte-identical tiers (same_media,
   identical_file) the copy you keep holds the same bytes, so removing an archive-only member loses
   nothing and there is nothing to warn about. */
export const ONLY_COPY_TIERS = { same_seed: true, near_duplicate: true };

/* The members of duplicate group `g` that are the only copy of their picture and are not the keeper. */
export function onlyCopyMembers(g, keeperPath) {
  if (!g || !ONLY_COPY_TIERS[g.matchType]) return [];
  return (g.members || []).filter((m) => m.archive_only && m.path !== keeperPath);
}

/* The confirm's sentence: `k` of the `n` pictures about to go are only copies. `road` is where they go:
   "trash" (Delete locally: the _deleted/ folder, which the Trash restores from) or "duplicates"
   (Duplicate Review: _duplicates/, which its Undo restores from). "" when k is 0. */
export function onlyCopyNote(k, n, road) {
  const many = Math.floor(Number(k)) || 0;
  if (many <= 0) return "";
  const all = Math.floor(Number(n)) || 0;
  const one = many === 1;
  const them = one ? "it" : "them";
  const head = one && all === 1
    ? "This is the only copy"
    : many + " of these " + (one ? "is" : "are") + " the only copy";
  const rest = many < all ? " with the rest" : "";
  const tail = road === "duplicates"
    ? " to _duplicates/" + rest + ", and Undo puts " + them + " back."
    : " to the Trash" + rest + ", and the Trash can restore " + them + ".";
  return head + " — PixAI no longer has " + them + ". " + (one ? "It goes" : "They go") + tail;
}

/* The same fact in a few words, for a button that has no confirm of its own. */
export function onlyCopyShort(k) {
  const many = Math.floor(Number(k)) || 0;
  if (many <= 0) return "";
  return many === 1 ? "1 is the only copy" : many + " are only copies";
}
