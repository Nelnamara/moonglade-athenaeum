"""The command line's --search / --export-csv: the gallery's own query language over catalog.db,
read-only, no network; plus --help's titled sections leaving every flag as it was."""
import csv
import io
import json
import sys

import pytest

from moonglade import backup as core
from moonglade.gallery import CATALOG_FIELDS, save_catalog, catalog_csv_text


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


@pytest.fixture
def lib(tmp_path):
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="100000001", task_id="9001", filename="a.png", model_name="Ether Real",
             prompt_full="night elf druid, moonlit grove", rating="4", loras="Detail Tweaker:0.8",
             created_at="2026-08-04T12:00:00"),
        _row(media_id="100000002", task_id="9002", filename="b.png", model_name="Tsubaki",
             prompt_full="city street at dawn", loras="Detail Tweaker:0.3",
             created_at="2026-02-01T08:00:00"),
        _row(media_id="100000003", task_id="9003", filename="c.png", model_name="Ether Real",
             prompt_full="elf archer ✨", rating="2", created_at="2026-09-20T08:00:00"),
    ])
    return tmp_path


def run(monkeypatch, capsys, lib, *argv):
    monkeypatch.setattr(sys, "argv", ["prog", "--out", str(lib), *argv])
    core.main()
    return capsys.readouterr().out


def test_search_prints_rows(monkeypatch, capsys, lib):
    out = run(monkeypatch, capsys, lib, "--search", "elf rating:>=3")
    assert "100000001" in out and "2026-08-04" in out and "Ether Real" in out
    assert "4*" in out and "night elf druid" in out
    assert "100000003" not in out and "100000002" not in out
    assert "1 match(es)" in out


def test_search_uses_the_webs_numbers_and_ranges(monkeypatch, capsys, lib):
    out = run(monkeypatch, capsys, lib, "--search", "lora:detail>0.5 created:2026Q3")
    assert "100000001" in out and "100000002" not in out


def test_limit_and_json(monkeypatch, capsys, lib):
    out = run(monkeypatch, capsys, lib, "--search", "model:ether", "--limit", "1")
    assert out.count("1000000") == 1 and "1 of 2 match(es) shown" in out
    data = json.loads(run(monkeypatch, capsys, lib, "--search", "model:ether", "--json"))
    assert [d["media_id"] for d in data] == ["100000003", "100000001"]       # newest first
    assert set(data[0]) == {"media_id", "created_at", "model", "rating", "prompt"}


def test_export_csv_matches_the_web_export(monkeypatch, capsys, lib, tmp_path):
    dest = tmp_path / "out.csv"
    run(monkeypatch, capsys, lib, "--search", "model:ether", "--limit", "1",
        "--export-csv", str(dest))
    rows = list(csv.DictReader(io.StringIO(dest.read_text(encoding="utf-8"))))
    assert list(rows[0].keys()) == CATALOG_FIELDS
    assert sorted(r["media_id"] for r in rows) == ["100000001", "100000003"]   # --limit ignored
    with open(dest, encoding="utf-8", newline="") as fh:
        assert fh.read() == catalog_csv_text(rows)


def test_export_csv_alone_is_the_whole_catalog(monkeypatch, capsys, lib, tmp_path):
    dest = tmp_path / "all.csv"
    run(monkeypatch, capsys, lib, "--export-csv", str(dest))
    assert len(list(csv.DictReader(dest.open(encoding="utf-8", newline="")))) == 3


def test_search_never_touches_the_network(monkeypatch, capsys, lib):
    import socket

    def boom(*a, **k):
        raise AssertionError("network")
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(socket.socket, "connect", boom)
    assert "100000001" in run(monkeypatch, capsys, lib, "--search", "druid")


def test_help_sections_and_flags(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["prog", "--help"])
    with pytest.raises(SystemExit):
        core.main()
    h = capsys.readouterr().out
    for title in ("Backup:", "Library:", "Create:", "Account:", "Maintenance:", "Search:"):
        assert "\n" + title in h
    for flag in ("--sync", "--catalog-stats", "--generate", "--account", "--rebuild-thumbs",
                 "--search", "--export-csv", "--list-web-users", "--prompt", "--confirm"):
        assert flag in h
