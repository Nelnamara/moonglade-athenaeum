"""
moonglade/about.py
==================
The in-app guide and the About card: the wiki pages shipped with this install (listing,
headings, glossary), this version's CHANGELOG entries, the version and release-kind labels, the
art pack line, and the "a newer version of this page is online" check. Moved verbatim out of
moonglade/gallery.py in the 3.21.0 split (phase 2).

Imports nothing from the gallery or the engine; version_tuple is the updater's
(`_updater.version_tuple`, as the gallery called it after the updater moved).
"""
import re
import threading
import time
from pathlib import Path

from moonglade import assets as moonglade_assets
from moonglade import paths as _paths
from moonglade import updater as _updater


# ---------------------------------------------------------------------------
# THE IN-APP GUIDE AND THE ABOUT CARD (Session I, 2026-09-28 -- the committed
# Design Handoff is ../moonglade-internal/design/handoff-2026-09-04/Help and First
# Run Handoff.dc.html; its numbered decisions are design/notes/help-first-run/NOTES.md).
#
# Help renders the wiki/ folder SHIPPED WITH THIS INSTALL. The app is a git checkout (see
# the updater's header below), so the pages on disk are the pages for the version that is
# running -- the online wiki follows the newest release instead, which is exactly why it
# is only ever offered as "a newer version of this page is online", never read in place.
#
# The server's part is small on purpose. It lists the pages in _Sidebar.md's order with
# their headings (the overlay's search covers titles and headings), hands ONE page's
# markdown over as text (the client parses it into plain data and React escapes every
# character -- there is no HTML sink anywhere on this road), reads the Glossary's terms,
# and cuts this version's CHANGELOG entry for About and what's new.
#
# A slug is served only if it is one of the files the listing itself found: it is looked
# up, never joined onto a path.
# ---------------------------------------------------------------------------
WIKI_WEB_URL = "https://github.com/Nelnamara/moonglade-athenaeum/wiki"
WIKI_RAW_URL = ("https://raw.githubusercontent.com/wiki/Nelnamara/moonglade-athenaeum/"
                "{slug}.md")
RELEASES_WEB_URL = "https://github.com/Nelnamara/moonglade-athenaeum/releases"
ISSUES_WEB_URL = "https://github.com/Nelnamara/moonglade-athenaeum/issues"
_WIKI_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
_WIKI_LINK_RE = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
_MD_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_GLOSSARY_ITEM_RE = re.compile(r"^- \*\*(.+?)\*\*\s*[—–-]+\s*(.*)$")
_CHANGELOG_HEAD_RE = re.compile(
    r"^## \[(\d+\.\d+\.\d+)\]\s*-\s*(\d{4}-\d{2}-\d{2})\s*(?:[—–-]+\s*(.*))?$")
_SURFACE_MARK_RE = re.compile(r"<!--\s*surface:\s*([a-z]+)\s*-->")
# The surfaces a what's-new highlight's "Show me" can open -- the first-run guide's own
# surfaces, less Branding, which no public text may point at.
HELP_SURFACES = ("gallery", "dock", "loom", "folio", "panel")
# Keyword inference for a highlight's surface when its CHANGELOG line carries no explicit
# <!-- surface: x --> mark: the bullet's bold lead is read first and its body only if the
# lead names nothing, and within one of them the EARLIEST keyword wins. No match means no
# "Show me" on that card rather than a guess.
_SURFACE_WORDS = (
    ("loom", ("the loom", "loom's", "storyboard")),
    ("folio", ("folio", "achievement")),
    ("panel", ("control panel", "job console", "runs itself")),
    ("dock", ("generate drawer", "generate dock", "the dock", "create screen",
              "cost badge", "the drawer", "generate", "generation")),
    ("gallery", ("the gallery", "gallery's", "the library", "lightbox", "the grid")),
)
WIKI_ONLINE_TTL = 1800           # a page compared against the online wiki: 30 min
WIKI_ONLINE_FAILURE_TTL = 90     # an unreachable GitHub is asked again soon, not hammered
_wiki_online_cache = {}
_wiki_online_lock = threading.Lock()


def wiki_dir():
    """The wiki/ folder shipped with this install (moonglade.paths.wiki_dir())."""
    return _paths.wiki_dir()


def changelog_path():
    """This install's own CHANGELOG.md (moonglade.paths.changelog_path())."""
    return _paths.changelog_path()


def md_plain(text):
    """Inline markdown -> the words a reader sees: a link keeps its label, the emphasis and
    code marks go, whitespace collapses. Titles, headings, glossary cards and changelog
    lines are all shown as plain text, so this is the one place they are flattened."""
    s = _WIKI_LINK_RE.sub(lambda m: m.group(1), str(text or ""))
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def display_version(version):
    """What the guide prints for a version: always the full x.y.z, the same string the
    build stamp and the Panel's About rows print (one version format everywhere,
    2026-11-18; before that a .0 release printed as x.y). It is also what `seen.whatsnew`
    stores; an account that stored the old x.y form is read as x.y.0 (helpCore.js
    whatsNewPlan), so the change never re-announces a release."""
    v = _updater.version_tuple(version)
    if not v:
        return str(version or "")
    return "%d.%d.%d" % v


def release_kind(version):
    """major | minor | patch. A patch release gets the toast only (it opens About); a
    minor or major one gets the what's-new sheet too (decision 3)."""
    v = _updater.version_tuple(version)
    if not v:
        return "patch"
    if v[2]:
        return "patch"
    return "major" if v[1] == 0 else "minor"


def wiki_web_url(slug):
    """The online copy of one page; the wiki's own address for Home."""
    return WIKI_WEB_URL if slug == "Home" else WIKI_WEB_URL + "/" + slug


def _wiki_pages_on_disk(root):
    """{slug: path} for every page file in `root` whose name is a valid slug. Files named
    _Something (the sidebar, a footer) are chrome, not pages."""
    out = {}
    try:
        for p in sorted(Path(root).glob("*.md")):
            if not p.stem.startswith("_") and _WIKI_SLUG_RE.match(p.stem):
                out[p.stem] = p
    except OSError:
        pass
    return out


def md_headings(md):
    """[(level, plain text)] for every ATX heading outside a fenced code block."""
    out, fence = [], False
    for line in str(md or "").splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        m = _MD_HEADING_RE.match(line)
        if m:
            text = md_plain(m.group(2))
            if text:
                out.append((len(m.group(1)), text))
    return out


def wiki_index(root=None):
    """The guide's page list: [{slug, title, heading, headings:[{level, text}]}].

    ORDER is _Sidebar.md's -- the same order the online wiki's own sidebar shows -- with
    any page the sidebar does not link appended by name, so a page can never be missing
    from the guide just because nobody added it to the sidebar. `title` is the sidebar's
    label (what the reader knows the page as); `heading` is the page's own # line."""
    root = Path(root) if root else wiki_dir()
    pages = _wiki_pages_on_disk(root)
    order, labels = [], {}
    try:
        side = (root / "_Sidebar.md").read_text(encoding="utf-8")
    except OSError:
        side = ""
    for label, target in _WIKI_LINK_RE.findall(side):
        slug = target.split("#", 1)[0]
        if slug in pages and slug not in labels:
            order.append(slug)
            labels[slug] = md_plain(label)
    order += [s for s in sorted(pages) if s not in labels]
    out = []
    for slug in order:
        try:
            heads = md_headings(pages[slug].read_text(encoding="utf-8"))
        except OSError:
            continue
        h1 = next((t for lvl, t in heads if lvl == 1), "")
        out.append({
            "slug": slug,
            "title": labels.get(slug) or h1 or slug.replace("-", " "),
            "heading": h1,
            "headings": [{"level": lvl, "text": t} for lvl, t in heads if lvl > 1],
        })
    return out


def wiki_glossary(root=None):
    """[{term, def}] from Glossary.md's `- **term** -- definition` bullets (a definition may
    wrap onto indented lines under its bullet). No Glossary.md answers [] -- the guide then
    underlines nothing; it never invents a term."""
    root = Path(root) if root else wiki_dir()
    try:
        lines = (root / "Glossary.md").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out, cur = [], None
    for line in lines:
        m = _GLOSSARY_ITEM_RE.match(line)
        if m:
            cur = {"term": md_plain(m.group(1)), "def": m.group(2).strip()}
            out.append(cur)
        elif cur is not None and line.startswith("  ") and line.strip():
            cur["def"] += " " + line.strip()
        else:
            cur = None
    for t in out:
        t["def"] = md_plain(t["def"])
    return [t for t in out if t["term"] and t["def"]]


def _changelog_surface(*texts):
    """The surface the first text that names one names, earliest keyword first."""
    for text in texts:
        low = str(text or "").lower()
        best, at = "", None
        for surface, words in _SURFACE_WORDS:
            for w in words:
                i = low.find(w)
                if i >= 0 and (at is None or i < at):
                    best, at = surface, i
        if best:
            return best
    return ""


def _changelog_item(raw, section):
    """One CHANGELOG bullet -> {lead, text, surface, section}. The lead is the bullet's
    bold opening sentence when it has one (the house style), else its first sentence; the
    trailing "(2026-09-26)" date tag is dropped. An explicit <!-- surface: x --> mark names
    the surface a what's-new "Show me" opens; without one it is inferred from the words."""
    raw = str(raw or "").strip()
    mark = _SURFACE_MARK_RE.search(raw)
    raw = _SURFACE_MARK_RE.sub("", raw).strip()
    raw = re.sub(r"\s*\(\d{4}-\d{2}-\d{2}[^)]*\)\s*$", "", raw)
    m = re.match(r"^\*\*(.+?)\*\*\s*(.*)$", raw, re.S)
    if m:
        lead, text = md_plain(m.group(1)), md_plain(m.group(2))
    else:
        plain = md_plain(raw)
        cut = re.search(r"[.!?](?:\s|$)", plain)
        lead = plain[:cut.end()].strip() if cut else plain
        text = plain[len(lead):].strip() if cut else ""
    lead = lead.rstrip(" .:")
    if mark and mark.group(1) in HELP_SURFACES:
        surface = mark.group(1)
    else:
        surface = _changelog_surface(lead, text)
    return {"lead": lead[:240], "text": text[:700], "surface": surface, "section": section}


def changelog_entries(text=None):
    """Every RELEASED version block in CHANGELOG.md, in file order (newest first):
    [{version, date, title, items:[...]}]. [Unreleased] is not a release and is skipped.
    Items are the top-level `- ` bullets; a `### Heading` inside a block names the
    section the bullets under it belong to ("" for the block's own list)."""
    if text is None:
        try:
            text = changelog_path().read_text(encoding="utf-8")
        except OSError:
            return []
    entries, cur, item, section = [], None, None, ""

    def _close_item():
        if cur is not None and item:
            cur["items"].append(_changelog_item(" ".join(item), section))

    for line in str(text).splitlines():
        if line.startswith("## "):
            _close_item()
            item = None
            m = _CHANGELOG_HEAD_RE.match(line.strip())
            cur = None
            section = ""
            if m:
                cur = {"version": m.group(1), "date": m.group(2),
                       "title": md_plain(m.group(3) or ""), "items": []}
                entries.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith("### "):
            _close_item()
            item = None
            section = md_plain(line[4:])
        elif line.startswith("- "):
            _close_item()
            item = [line[2:].strip()]
        elif line.strip() and item is not None:
            item.append(line.strip())
        elif not line.strip():
            _close_item()
            item = None
    _close_item()
    return entries


def art_pack_info(container_path):
    """{installed, version} for the About card's "art pack vN". The version comes from the
    installed pack's own marker when the downloader wrote one, else from the manifest when
    the pack on disk is the one this build expects; a missing pack says so. (About never
    lists old copies for a person to delete: the app removes its own old files itself.)"""
    try:
        present = Path(container_path).exists()
    except OSError:
        present = False
    if not present:
        return {"installed": False, "version": ""}
    marker = moonglade_assets._read_marker(Path(container_path)) or {}
    if marker.get("version"):
        info = {"installed": True, "version": str(marker["version"])}
    else:
        man = moonglade_assets.read_manifest()
        try:
            current = bool(man) and not moonglade_assets.needs_download(Path(container_path), man)
        except Exception:                        # noqa: BLE001 -- a label, never a failure
            current = False
        info = {"installed": True, "version": str(man["version"]) if current else ""}
    return info


def about_payload(version, container_path, entries=None):
    """What the About card, the post-update toast and the what's-new sheet read: this
    version's CHANGELOG entry (the running version's, not the newest in the file), the
    release's size (major/minor/patch), the art pack, and the earlier entries for "Earlier
    versions"."""
    entries = changelog_entries() if entries is None else entries
    vt = _updater.version_tuple(version)
    cur = next((e for e in entries if e["version"] == str(version)), None)
    earlier = [e for e in entries
               if vt and _updater.version_tuple(e["version"]) and _updater.version_tuple(e["version"]) < vt][:24]
    return {
        "version": str(version),
        "display_version": display_version(version),
        "kind": release_kind(version),
        "date": (cur or {}).get("date", ""),
        "title": (cur or {}).get("title", ""),
        "items": (cur or {}).get("items", []),
        "earlier": earlier,
        "pack": art_pack_info(container_path),
        "releases_url": RELEASES_WEB_URL,
        "issues_url": ISSUES_WEB_URL,
        "wiki_url": WIKI_WEB_URL,
    }


def _md_same(a, b):
    def norm(s):
        return "\n".join(ln.rstrip() for ln in str(s or "").replace("\r\n", "\n").strip().split("\n"))
    return norm(a) == norm(b)


def wiki_online_differs(slug, local_md, behind, opener=None, now=None):
    """Is a NEWER copy of this page online? Only asked when a newer release is known to be
    out (`behind`, from the updater's own cached answer): the online wiki is re-published
    at every release tag, so with no newer release there is no newer page, and GitHub is
    not asked at all. When it is asked, the answer is cached per page (WIKI_ONLINE_TTL; an
    unreachable GitHub for WIKI_ONLINE_FAILURE_TTL), and a failure answers False -- a quiet
    link that is missing is fine, one that is wrong is not. `opener` is the seam the tests
    substitute; nothing in the suite touches the network."""
    if not behind:
        return False
    now = time.time() if now is None else now
    with _wiki_online_lock:
        c = _wiki_online_cache.get(slug)
        if c and (now - c["at"]) < c["ttl"]:
            return c["differs"]
    import urllib.request
    opener = opener or urllib.request.urlopen
    try:
        req = urllib.request.Request(WIKI_RAW_URL.format(slug=slug), headers={
            "User-Agent": "moonglade-athenaeum-guide"})
        with opener(req, timeout=6) as resp:
            online = resp.read(2 * 1024 * 1024).decode("utf-8", "replace")
        differs, ttl = (not _md_same(online, local_md)), WIKI_ONLINE_TTL
    except Exception:                            # noqa: BLE001 -- offline is not an error here
        differs, ttl = False, WIKI_ONLINE_FAILURE_TTL
    with _wiki_online_lock:
        _wiki_online_cache[slug] = {"at": now, "ttl": ttl, "differs": differs}
    return differs
