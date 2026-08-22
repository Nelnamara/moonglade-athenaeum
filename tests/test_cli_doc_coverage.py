"""Drift guard: every CLI flag defined in moonglade_backup.py's argparse must be
documented somewhere in the wiki. Fails when a new flag is added without a wiki
mention, so the published CLI reference can't silently go stale again.

Flags are extracted with `ast` (not a regex) so every add_argument shape is caught:
short options (`-q`), underscores (`--foo_bar`), digits (`--2fa`), uppercase, and
option strings split across lines. Each add_argument call is one "group" (its short
+ long forms); a group counts as documented if ANY of its option strings appears in
the wiki as a whole token. This is coverage, not prose-quality: it guarantees a new
flag is *mentioned* somewhere, not that the mention is a good explanation. It is
also coverage-only — it never flags wiki-only tokens (the wiki legitimately names
the gallery server's own flags and explicitly names removed flags).
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKUP = ROOT / "moonglade_backup.py"
WIKI = ROOT / "wiki"

# Flags deliberately kept out of the public wiki. Keep this EMPTY unless a flag is
# intentionally internal; every entry needs a one-line reason. (Owner call
# 2026-08-22: the account viewers --credit-log/--coupons/--card-history ARE public.)
ALLOWLIST: dict[str, str] = {}


def _flag_groups() -> list[list[str]]:
    """One entry per add_argument call: its leading option strings (short + long)."""
    tree = ast.parse(BACKUP.read_text(encoding="utf-8"))
    groups: list[list[str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            opts: list[str] = []
            for arg in node.args:  # option strings are the leading positional args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith("-"):
                    opts.append(arg.value)
                else:
                    break
            if opts:
                groups.append(opts)
    return groups


def _wiki_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in WIKI.glob("*.md"))


def _is_documented(opt: str, wiki: str) -> bool:
    if opt.startswith("--"):
        # whole-token match: "--foo" must not be the prefix of "--foobar"
        return re.search(r"(?<![\w-])" + re.escape(opt) + r"(?![\w-])", wiki) is not None
    # short option: require it backticked (`-q`) so a stray "-q" in prose can't count
    return f"`{opt}`" in wiki


def test_every_cli_flag_is_documented():
    groups = _flag_groups()
    assert groups, "no add_argument option strings extracted from source — ast walk drift?"
    wiki = _wiki_text()
    missing: list[str] = []
    for opts in groups:
        if any(o in ALLOWLIST for o in opts):
            continue
        # prefer the long form(s); a short-only flag falls back to its short token
        checks = [o for o in opts if o.startswith("--")] or opts
        if not any(_is_documented(o, wiki) for o in checks):
            missing.append("/".join(opts))
    assert not missing, (
        "CLI flags defined in moonglade_backup.py but undocumented in wiki/*.md:\n  "
        + "\n  ".join(sorted(missing))
        + "\n\nDocument each in the appropriate wiki page (a short-only flag must be "
        "written backticked, e.g. `-q`), or add it to ALLOWLIST with a reason if it's "
        "intentionally internal."
    )


def test_allowlist_entries_still_exist():
    """An allowlisted flag that no longer exists in source is stale — drop it."""
    defined = {o for g in _flag_groups() for o in g}
    stale = sorted(f for f in ALLOWLIST if f not in defined)
    assert not stale, f"ALLOWLIST names flags no longer defined in source: {stale}"
