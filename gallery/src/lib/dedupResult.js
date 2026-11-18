// The Dedup stages end with one plain sentence (moonglade/organize.py, RESULT_PREFIX). The
// Control Panel's result box leads with it and folds the job's file lines under a toggle
// (owner pick 2026-11-18, option 2). Keep RESULT_PREFIX in step with organize.py.
export const DEDUP_RESULT_PREFIX = "Result: ";

// Verify prints its counts indented too; they are not files.
const STAT_LINE = /^ {2}(safe - |DIFFERS - |ORPHAN {2}- )/;

// lines -> { sentence, files } or null when the job printed no Result line.
export function parseDedupResult(lines) {
  const all = Array.isArray(lines) ? lines.map(String) : [];
  let at = -1;
  for (let i = all.length - 1; i >= 0; i--) {
    if (all[i].startsWith(DEDUP_RESULT_PREFIX)) { at = i; break; }
  }
  if (at < 0) return null;
  const sentence = all[at].slice(DEDUP_RESULT_PREFIX.length).trim();
  // The file list is the LAST indented block before the sentence. Earlier indented blocks
  // are counts, not files (Audit's "Files per bucket:" lines), so they never join it.
  const indented = (ln) => /^ {2}\S/.test(ln);
  let end = at - 1;
  while (end >= 0 && !indented(all[end])) end--;
  let start = end;
  while (start - 1 >= 0 && indented(all[start - 1])) start--;
  const files = end < 0 ? [] : all.slice(start, end + 1)
    .filter((ln) => !STAT_LINE.test(ln)).map((ln) => ln.trim());
  const m = sentence.match(/\d[\d,]*/);
  return { sentence, files, count: m ? m[0] : String(files.length) };
}
