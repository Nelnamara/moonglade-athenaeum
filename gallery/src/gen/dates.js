// Local calendar day from a UTC ISO timestamp ("2026-07-30T06:42:23.683Z").
//
// PixAI stamps every generation in UTC, and the server used to hand the client
// created_at[:10] -- a UTC day. Anything made in the evening (US time) lands on the
// NEXT UTC day, so ~half the library showed the wrong date, and the Timeline's
// "Today / Yesterday" bands (computed from the browser's LOCAL clock) never matched
// it -- an image made at 8pm filed under tomorrow. Derive the day HERE, in the
// viewer's own timezone, from the full timestamp. (#30 placard review, 2026-08-22)
export function localDay(iso) {
  if (!iso) return "";
  // A bare day ("2026-07-30") carries no time and no zone: it is ALREADY a day, so pass
  // it through. (new Date() would read it as UTC midnight and shift it back a day in
  // any western zone -- the exact bug this helper exists to fix, in reverse.)
  if (/^\d{4}-\d{2}-\d{2}$/.test(String(iso))) return String(iso);
  const d = new Date(iso);
  if (isNaN(d)) return String(iso).slice(0, 10);   // not a timestamp -> whatever we were given
  const pad = (n) => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
}

// Local "YYYY-MM-DD · HH:MM" for a placard/stamp; "" when there is no timestamp.
export function localDayTime(iso) {
  if (!iso) return "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(String(iso))) return String(iso);   // a bare day has no time
  const d = new Date(iso);
  if (isNaN(d)) return String(iso).slice(0, 10);
  const pad = (n) => String(n).padStart(2, "0");
  return localDay(iso) + " · " + pad(d.getHours()) + ":" + pad(d.getMinutes());
}
