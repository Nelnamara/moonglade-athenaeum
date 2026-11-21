"""
moonglade/name_hunt.py
======================
The name hunt on the model pickers' Bookmarked and Mine tabs: `_hunt_by_name` pages PixAI's own
list and keeps only the rows whose name carries the search, up to `_HUNT_MAX_PAGES` pages. The
route that calls it is moonglade/routes_library.py's. Moved verbatim out of
moonglade/gallery.py in the 3.22 split (phase 4).

It needs nothing from the gallery or the engine.
"""


# --- The name hunt on the Bookmarked and Mine tabs (owner, 2026-09-07: "search is still
# shit"). Measured that day with the app's own client: the bookmarks operation takes a
# keyword and answers 24 rows that mostly do NOT carry it ("eyes" -> "Special Eyes XL" then
# a page of unrelated titles), and the author-filtered market connection ignores the keyword
# outright (the same four rows for "eyes" and for nothing). So neither tab searched. Both
# lists are the owner's OWN (a few hundred bookmarks, a handful of his LoRAs), so the honest
# search is to walk the list and keep the rows whose title or description carries the words --
# bounded, and the whole answer comes back in one page (no cursor), because a filtered walk
# cannot hand out a cursor that means anything to the next call.
_HUNT_MAX_PAGES = 20


def _hunt_by_name(fetch_page, q, size):
    """Walk `fetch_page(after)` (a callable returning the picker's payload shape: results /
    has_more / next_cursor) and keep the rows whose title or description contains every word
    of `q`, case-insensitively. Stops at the source's end, at _HUNT_MAX_PAGES, or once
    `size * 4` matches are in hand. Answers has_more False: the hunt is one page."""
    words = [w for w in (q or "").lower().split() if w]
    keep, after, pages = [], None, 0
    while pages < _HUNT_MAX_PAGES:
        page = fetch_page(after) or {}
        if page.get("error") and not page.get("results"):
            return page
        for row in page.get("results") or []:
            hay = ((row.get("title") or "") + " " + (row.get("description") or "")).lower()
            if all(w in hay for w in words):
                keep.append(row)
        pages += 1
        if not page.get("has_more") or not page.get("next_cursor") or len(keep) >= size * 4:
            break
        after = page["next_cursor"]
    return {"results": keep, "has_more": False, "next_cursor": "", "hunted_pages": pages}
