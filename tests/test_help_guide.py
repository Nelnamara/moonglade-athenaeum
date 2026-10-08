"""The in-app guide's server half (Session I, 2026-09-28): the wiki/ shipped with the
install as Help's pages, the Glossary's terms, this version's CHANGELOG entry for About and
what's new, and the "a newer version of this page is online" check.

What is pinned here is the CONTRACT the overlay reads -- page order from the sidebar, a
slug served only if the listing found it, headings out of code fences, glossary bullets
across wrapped lines, the running version's entry (never the newest in the file), the
release size that picks the sheet or About, and an online check that never asks GitHub
unless a newer release is out and never touches the network in a test. Tier enforcement
(LOGIN) is asserted by tests/test_route_tiers.py.
"""
import io

import pytest

from moonglade import backup as core
from moonglade import gallery as g
from tests.conftest import login_client


def _wiki(tmp_path, files):
    root = tmp_path / "wiki"
    root.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    return root


SIDEBAR = """**Moonglade**

[Home](Home)

**Guides**
- [The Gallery](Gallery)
- [The Loom](The-Loom)
- [Glossary](Glossary)
"""


# ---------------------------------------------------------------------------
# The page list
# ---------------------------------------------------------------------------

def test_the_index_follows_the_sidebar_and_appends_what_it_does_not_link(tmp_path):
    root = _wiki(tmp_path, {
        "_Sidebar.md": SIDEBAR,
        "Home.md": "# Home\n\n## Guides\n",
        "Gallery.md": "# The Gallery\n\n## Filters\n\n### Saved views\n",
        "The-Loom.md": "# The Loom\n\n```\n# not a heading\n```\n\n## Shots\n",
        "Glossary.md": "# Glossary\n",
        "FAQ.md": "# FAQ\n",
        "_Footer.md": "chrome, not a page",
    })
    idx = g.wiki_index(root)
    assert [p["slug"] for p in idx] == ["Home", "Gallery", "The-Loom", "Glossary", "FAQ"]
    gal = idx[1]
    assert gal["title"] == "The Gallery" and gal["heading"] == "The Gallery"
    assert gal["headings"] == [{"level": 2, "text": "Filters"}, {"level": 3, "text": "Saved views"}]
    # a # line inside a code fence is code, not a heading
    assert idx[2]["headings"] == [{"level": 2, "text": "Shots"}]
    # a page the sidebar never linked still appears, titled by its own heading
    assert idx[4]["title"] == "FAQ"


def test_headings_are_flattened_to_the_words_a_reader_sees():
    heads = g.md_headings("# The **Loom**\n## Free cards and `videos`\n## [Setup](Setup) steps\n")
    assert heads == [(1, "The Loom"), (2, "Free cards and videos"), (2, "Setup steps")]


def test_the_shipped_wiki_indexes_every_page_it_carries():
    idx = g.wiki_index()
    slugs = [p["slug"] for p in idx]
    assert slugs[0] == "Home"
    on_disk = sorted(p.stem for p in g.wiki_dir().glob("*.md") if not p.stem.startswith("_"))
    assert sorted(slugs) == on_disk
    # the four pages the guide opens from a surface header must be here
    for slug in ("Gallery", "Generating", "The-Loom", "Folio-of-Honors", "Control-Panel", "Glossary"):
        assert slug in slugs


# ---------------------------------------------------------------------------
# The Glossary
# ---------------------------------------------------------------------------

def test_glossary_terms_come_from_the_bullets_and_their_wrapped_lines(tmp_path):
    root = _wiki(tmp_path, {"Glossary.md": (
        "# Glossary\n\nIntro line.\n\n"
        "- **the dock** — the generate panel docked at the bottom of the screen, opened\n"
        "  with **✦ Generate**. See [Generating](Generating).\n"
        "- **toast** — a notice in the corner.\n"
        "\n## Reporting something\n\n- not a term line\n")})
    assert g.wiki_glossary(root) == [
        {"term": "the dock", "def": "the generate panel docked at the bottom of the screen, "
                                    "opened with ✦ Generate. See Generating."},
        {"term": "toast", "def": "a notice in the corner."},
    ]


def test_no_glossary_page_means_no_terms_rather_than_invented_ones(tmp_path):
    assert g.wiki_glossary(_wiki(tmp_path, {"Home.md": "# Home\n"})) == []


def test_the_shipped_glossary_has_terms():
    terms = g.wiki_glossary()
    assert terms, "wiki/Glossary.md carries the underlined terms; an empty read is a parse break"
    assert all(t["term"] and t["def"] for t in terms)


# ---------------------------------------------------------------------------
# The CHANGELOG entry
# ---------------------------------------------------------------------------

CHANGELOG = """# Changelog

## [Unreleased]

- Not released yet. (2026-09-28)

## [3.15.0] - 2026-10-01 — Open Book

- **Help opens from every header.** The guide reads the wiki this install carries.
  It wraps onto a second line. (2026-10-01)
- **The Loom's quick guide retired.** Its ? opens The Loom's page instead. (2026-10-01)
- A plain line with no bold lead. And a second sentence.
- **Pinned somewhere.** Nothing in here names a surface. <!-- surface: folio -->

### Under the hood
- **Routes.** Four read-only routes. (2026-10-01)

## [3.14.1] - 2026-09-27 — Small Mend

- **A fix.** In the library.

## [3.14.0] - 2026-09-26 — Moving Pictures

- **Older.** Something.
"""


def test_changelog_entries_cut_each_release_and_skip_unreleased():
    es = g.changelog_entries(CHANGELOG)
    assert [e["version"] for e in es] == ["3.15.0", "3.14.1", "3.14.0"]
    e = es[0]
    assert (e["date"], e["title"]) == ("2026-10-01", "Open Book")
    leads = [(i["lead"], i["section"]) for i in e["items"]]
    assert leads == [("Help opens from every header", ""),
                     ("The Loom's quick guide retired", ""),
                     ("A plain line with no bold lead", ""),
                     ("Pinned somewhere", ""),
                     ("Routes", "Under the hood")]
    # the wrapped line joins its bullet, and the trailing date tag goes
    assert e["items"][0]["text"] == ("The guide reads the wiki this install carries. "
                                     "It wraps onto a second line.")
    assert e["items"][2]["text"] == "And a second sentence."


def test_a_highlight_names_its_surface_by_mark_or_by_its_words():
    items = g.changelog_entries(CHANGELOG)[0]["items"]
    assert items[1]["surface"] == "loom"          # "The Loom's" in the lead
    assert items[3]["surface"] == "folio"         # the explicit mark wins
    assert items[2]["surface"] == ""              # nothing named: no "Show me", no guess
    assert "<!--" not in items[3]["text"]


def test_about_reads_the_running_versions_entry_not_the_newest(tmp_path):
    es = g.changelog_entries(CHANGELOG)
    a = g.about_payload("3.14.1", tmp_path / "nopack" / "moonglade.mgpack", entries=es)
    assert (a["version"], a["display_version"], a["kind"]) == ("3.14.1", "3.14.1", "patch")
    assert (a["date"], a["title"]) == ("2026-09-27", "Small Mend")
    assert [i["lead"] for i in a["items"]] == ["A fix"]
    # earlier versions are strictly older than the running one
    assert [e["version"] for e in a["earlier"]] == ["3.14.0"]
    assert a["pack"] == {"installed": False, "version": ""}


def test_release_size_and_display_version():
    assert (g.display_version("3.15.0"), g.release_kind("3.15.0")) == ("3.15", "minor")
    assert (g.display_version("3.15.2"), g.release_kind("3.15.2")) == ("3.15.2", "patch")
    assert (g.display_version("4.0.0"), g.release_kind("4.0.0")) == ("4.0", "major")


def test_the_pack_version_reads_the_installed_marker(tmp_path):
    (tmp_path / "pack").mkdir()
    dat = tmp_path / "pack" / "moonglade.mgpack"
    dat.write_bytes(b"x")
    (tmp_path / "pack" / "moonglade.mgpack.version").write_text('{"version": "7", "sha256": "ab"}')
    assert g.art_pack_info(dat) == {"installed": True, "version": "7"}


def test_about_never_lists_old_copies_to_delete(tmp_path):
    """The app removes its own old copies (DECISIONS 2026-10-05: "The ownership of deleting
    dead files should NEVER be on the user"), so About's art-pack line never carries a list
    of files to delete -- not even with an old pack under its pre-v7 name beside the new one
    (the move removes that itself: tests/test_assets.py)."""
    from moonglade import assets as ma
    (tmp_path / "pack").mkdir()
    new = tmp_path / "pack" / "moonglade.mgpack"
    new.write_bytes(b"x")
    (tmp_path / "pack" / ma.LEGACY_NAME).write_bytes(b"an older pack")
    assert "note" not in g.art_pack_info(new)
    assert "note" not in g.about_payload("3.14.1", new, out_dir=tmp_path)["pack"]
    new.unlink()
    assert g.art_pack_info(new) == {"installed": False, "version": ""}


def test_about_shows_the_packs_note_in_its_own_stamp_style():
    """The note is one more line in the About card's existing stamp style, under the
    "app x.y.z · art pack vN" line -- no new element, and the card names no file itself."""
    import pathlib
    import re
    src = pathlib.Path("gallery/src/help/AboutLayers.jsx").read_text(encoding="utf-8")
    assert re.search(r'\{about\.pack && about\.pack\.note \? \(?\s*<div className="mgab-stamp">'
                     r'\{about\.pack\.note\}</div>', src), "About does not show the pack's note"


def test_a_real_start_never_asks_the_owner_to_delete_an_old_pack(tmp_path, monkeypatch,
                                                                   capsys):
    """A start that finds the pack under both names in the app folder handles it itself (the
    rename's "both" answer, then the move): nothing on the console or in the log tells the
    owner to delete something (S13)."""
    from moonglade import assets as ma
    from moonglade import migrate as mig
    from moonglade import paths
    from moonglade import setup as msetup
    app = tmp_path / "app"
    app.mkdir()
    (app / ma.LEGACY_NAME).write_bytes(b"an older pack")
    (app / "moonglade.mgpack").write_bytes(b"the pack")
    monkeypatch.setattr(paths, "local_dir", lambda: app / "local")
    monkeypatch.setattr(paths, "local_path", lambda name: app / "local" / name)
    monkeypatch.setattr(mig, "old_app_root", lambda: app)
    done = msetup.prepare("cli", explicit_out=str(tmp_path / "no-library"))
    said = capsys.readouterr().out + done.summary()
    assert "yourself" not in said and "safe to delete" not in said.lower()
    assert (app / "local" / "moonglade.mgpack").read_bytes() == b"the pack"


def test_the_running_version_has_a_changelog_entry():
    """About and what's new read the running version's block; a release cut without one
    would show an empty card on every install that runs it."""
    a = g.about_payload(core.__version__, g._container_path())
    assert a["title"] and a["items"], "CHANGELOG.md has no [%s] block" % core.__version__


# ---------------------------------------------------------------------------
# The online check
# ---------------------------------------------------------------------------

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def _fresh_online_cache(monkeypatch):
    monkeypatch.setattr(g, "_wiki_online_cache", {})


def test_the_online_check_never_asks_while_no_newer_release_is_out():
    def opener(*a, **k):
        raise AssertionError("GitHub must not be asked when no newer release is out")
    assert g.wiki_online_differs("Home", "# Home\n", behind=False, opener=opener) is False


def test_the_online_check_compares_and_caches_per_page():
    calls = []

    def opener(req, timeout=None):
        calls.append(req.full_url)
        return _Resp(b"# Home\n\nNew line online.\n")
    assert g.wiki_online_differs("Home", "# Home\n", True, opener=opener, now=1000) is True
    assert g.wiki_online_differs("Home", "# Home\n", True, opener=opener, now=1500) is True
    assert calls == ["https://raw.githubusercontent.com/wiki/Nelnamara/moonglade-athenaeum/Home.md"]
    # the same text with other line endings is the same page
    assert g.wiki_online_differs("Setup", "# Setup\r\nA\r\n", True,
                                 opener=lambda r, timeout=None: _Resp(b"# Setup\nA\n"),
                                 now=1000) is False


def test_an_unreachable_github_is_a_quiet_no_and_is_asked_again_soon():
    def down(req, timeout=None):
        raise OSError("offline")
    assert g.wiki_online_differs("FAQ", "x", True, opener=down, now=1000) is False
    hit = []
    assert g.wiki_online_differs("FAQ", "x", True, now=1000 + g.WIKI_ONLINE_FAILURE_TTL + 1,
                                 opener=lambda r, timeout=None: hit.append(1) or _Resp(b"y")) is True
    assert hit == [1]


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------

def test_index_route_carries_pages_glossary_and_the_version(tmp_path):
    d = login_client(tmp_path).get("/api/help/index").get_json()
    assert d["version"] == core.__version__
    assert d["display_version"] == g.display_version(core.__version__)
    assert d["pages"][0]["slug"] == "Home" and d["glossary"]


def test_page_route_serves_a_listed_page_and_refuses_anything_else(tmp_path):
    cli = login_client(tmp_path)
    r = cli.get("/api/help/page/The-Loom")
    assert r.status_code == 200
    d = r.get_json()
    assert d["markdown"].startswith("# The Loom")
    assert d["url"] == g.WIKI_WEB_URL + "/The-Loom"
    for bad in ("_Sidebar", "..%2FCHANGELOG", "Nope", "The-Loom.md"):
        assert cli.get("/api/help/page/" + bad).status_code == 404, bad


def test_online_route_answers_without_asking_while_up_to_date(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "_update_cache", {"at": 0, "payload": {"behind": False}, "ttl": 1})

    def boom(*a, **k):
        raise AssertionError("no network while up to date")
    monkeypatch.setattr(g, "wiki_online_differs",
                        lambda slug, md, behind, **k: boom() if behind else False)
    d = login_client(tmp_path).get("/api/help/online/Home").get_json()
    assert d == {"differs": False, "url": g.WIKI_WEB_URL}


def test_about_route_is_the_running_version(tmp_path):
    d = login_client(tmp_path).get("/api/help/about").get_json()
    assert d["version"] == core.__version__
    assert d["kind"] in ("major", "minor", "patch")
    assert d["releases_url"].endswith("/releases")
