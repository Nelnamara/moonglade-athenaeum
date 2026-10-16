"""Three small backend fixes (2026-10-15), one test group each.

1. The dead credit-log reason filter is gone: no --credit-log-reason flag, no `reason`
   argument on list_credit_log, and /api/account/credit-log ignores ?reason= instead of
   passing it down. (PixAI's `me.quotaLogs` read takes no such filter; nothing ever sent it.)
2. Issue #83: the zip export's "embed prompt" wrote row.get("model"), a key a catalog row
   never has, so every embedded file carried an empty model. It now writes model_name,
   falling back to model_id.
3. Issue #85: the Similar (embedding) index jobs are heavy and must not run beside GPU- or
   RAM-heavy programs (DECISIONS: "Never run the similarity/embedding index job alongside
   anything heavy"). The warning is on every surface that launches them.

Pure/mocked: no network, no spend, no real session."""
import inspect
import io
import re
import sys
import zipfile
from pathlib import Path

import pytest

from moonglade import backup as core
from moonglade.gallery import CATALOG_FIELDS, save_catalog

ROOT = Path(__file__).resolve().parents[2]


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _cli_help(monkeypatch, capsys):
    """The CLI's --help text, unwrapped so a phrase cannot be split across lines."""
    monkeypatch.setenv("COLUMNS", "4000")
    monkeypatch.setattr(sys, "argv", ["moonglade", "--help"])
    with pytest.raises(SystemExit) as ex:
        core.main()
    assert ex.value.code == 0
    return capsys.readouterr().out


def _flag_help(text, flag):
    """The help block of one option: from its own line to the next option's line."""
    blocks = re.split(r"\n  (?=-)", text)
    mine = [b for b in blocks if b.startswith(flag)]
    assert len(mine) == 1, "{} not found exactly once in --help".format(flag)
    return " ".join(mine[0].split())


# ---- 1. the dead credit-log reason filter ------------------------------------------

def test_credit_log_reason_flag_is_gone(monkeypatch, capsys):
    """Without the removal, argparse accepts --credit-log-reason; with it, exit code 2."""
    monkeypatch.setattr(sys, "argv", ["moonglade", "--credit-log", "--credit-log-reason", "task_cost"])
    with pytest.raises(SystemExit) as ex:
        core.main()
    assert ex.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_credit_log_reason_not_in_help_or_wiki(monkeypatch, capsys):
    assert "--credit-log-reason" not in _cli_help(monkeypatch, capsys)
    for page in (ROOT / "wiki").glob("*.md"):
        assert "--credit-log-reason" not in page.read_text(encoding="utf-8"), page.name


def test_list_credit_log_has_no_reason_argument():
    params = inspect.signature(core.list_credit_log).parameters
    assert "reason" not in params
    assert list(params) == ["session", "last", "before"]


def test_credit_log_route_does_not_pass_reason_down(tmp_path, monkeypatch):
    """The route used to forward ?reason=; list_credit_log now has no such parameter, so a
    forwarded one would be a TypeError. The strict fake below proves it is not forwarded."""
    from tests.conftest import login_client
    seen = {}

    def strict_list(session, last=50, before=None):
        seen.update(last=last, before=before)
        return {"entries": [], "has_more": False, "next_cursor": None}

    monkeypatch.setattr(core, "_make_session", lambda token=None: object())
    monkeypatch.setattr(core, "list_credit_log", strict_list)
    client = login_client(tmp_path)
    r = client.get("/api/account/credit-log?count=12&before=cur-1&reason=task_cost")
    assert r.status_code == 200
    assert r.get_json() == {"entries": [], "has_more": False, "next_cursor": None}
    assert seen == {"last": 12, "before": "cur-1"}


# ---- 2. issue #83: embed prompt writes the model ------------------------------------

def _export_one(tmp_path, monkeypatch, **row_kw):
    """POST one image to /export-zip with embed on, with embed_metadata recorded."""
    from tests.conftest import login_client
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="333", filename="c_333.png", prompt_preview="a lantern",
                       task_id="t-9", seed="42", created_at="2026-10-01T00:00:00", **row_kw)])
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "c_333.png").write_bytes(b"\x89PNG\r\n\x1a\nfakeimage")
    handed = []

    def fake_embed(path, fields):
        handed.append(dict(fields))
        return "ok"

    monkeypatch.setattr(core, "embed_metadata", fake_embed)
    client = login_client(tmp_path)
    z = client.post("/export-zip", data={"media_ids": "333", "embed": "1"})
    assert z.status_code == 200
    assert len(handed) == 1
    return handed[0]


def test_export_embed_carries_the_model_name(tmp_path, monkeypatch):
    fields = _export_one(tmp_path, monkeypatch, model_name="Moon Lantern v2", model_id="m-77")
    assert fields["model"] == "Moon Lantern v2"
    assert fields["media_id"] == "333" and fields["seed"] == "42"


def test_export_embed_falls_back_to_model_id(tmp_path, monkeypatch):
    fields = _export_one(tmp_path, monkeypatch, model_name="", model_id="m-77")
    assert fields["model"] == "m-77"


def test_export_embed_model_is_readable_from_the_downloaded_png(tmp_path):
    """End to end with the real embed_metadata: the model comes back out of the PNG chunk."""
    pytest.importorskip("PIL")
    from PIL import Image
    from tests.conftest import login_client
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="444", filename="d_444.png", prompt_preview="a stag",
                       model_name="Silver Stag", model_id="m-5")])
    (tmp_path / "images").mkdir()
    Image.new("RGB", (8, 8), (30, 40, 60)).save(tmp_path / "images" / "d_444.png", "PNG")
    client = login_client(tmp_path)
    z = client.post("/export-zip", data={"media_ids": "444", "fmt": "png", "embed": "1"})
    assert z.status_code == 200
    data = zipfile.ZipFile(io.BytesIO(z.data)).read("d_444.png")
    assert Image.open(io.BytesIO(data)).text.get("model") == "Silver Stag"


# ---- 3. issue #85: the Similar jobs say they are heavy -------------------------------

HEAVY = "GPU- or RAM-heavy"


@pytest.mark.parametrize("flag", ["--rebuild-similar", "--sync-similar"])
def test_similar_cli_help_warns_it_is_heavy(flag, monkeypatch, capsys):
    block = _flag_help(_cli_help(monkeypatch, capsys), flag)
    assert "Heavy:" in block and HEAVY in block


@pytest.mark.parametrize("action", ["sync-similar", "rebuild-similar"])
def test_similar_panel_chips_warn_it_is_heavy(action, tmp_path):
    from tests.conftest import login_client
    d = login_client(tmp_path).get("/api/panel/summary").get_json()
    by_action = {a["action"]: a for a in d["actions"]}
    assert HEAVY in by_action[action]["label"]


@pytest.mark.parametrize("src", ["gallery/src/components/ControlPanelOverlay.jsx",
                                 "gallery/src/components/ControlMobile.jsx"])
def test_similar_chip_tooltips_warn_it_is_heavy(src):
    """The chips draw their own short text, so the warning rides on the tooltip."""
    text = (ROOT / src).read_text(encoding="utf-8")
    for action in ("sync-similar", "rebuild-similar"):
        line = next(ln for ln in text.splitlines() if 'actionSpec("{}")'.format(action) in ln)
        assert HEAVY in line, "{} chip in {} has no heavy warning".format(action, src)


@pytest.mark.parametrize("page", ["Control-Panel.md", "Backing-Up.md"])
def test_similar_wiki_pages_warn_it_is_heavy(page):
    text = " ".join((ROOT / "wiki" / page).read_text(encoding="utf-8").split())
    assert HEAVY in text


@pytest.mark.parametrize("action", ["sync-similar", "rebuild-similar"])
def test_similar_scheduler_rows_warn_it_is_heavy(action):
    """The scheduler starts both jobs unattended (nightly top-up, 60-day rebuild backstop),
    so its note -- the tooltip on the 'Runs itself' row -- carries the warning too."""
    from moonglade.gallery import LIVING_BY_ACTION
    assert HEAVY in LIVING_BY_ACTION[action]["note"]


def test_similar_wiki_scheduler_and_launch_lines_warn_it_is_heavy():
    """The wiki's scheduler table rows and the Gallery page's how-to-build line."""
    cp = (ROOT / "wiki" / "Control-Panel.md").read_text(encoding="utf-8").splitlines()
    for key in ("| **Top up Similar** |", "| **Full re-walk** "):
        row = next(ln for ln in cp if ln.startswith(key))
        assert HEAVY in row, key
    gal = " ".join((ROOT / "wiki" / "Gallery.md").read_text(encoding="utf-8").split())
    assert "--rebuild-similar" in gal and HEAVY in gal
