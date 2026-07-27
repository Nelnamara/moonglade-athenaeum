"""Web import: POST /api/import-local brings local files into the catalog as source='local'
(the web equivalent of the CLI --import-local). Localhost-only, since it writes files onto the
server's machine and shells thumbnails. Nothing is uploaded to PixAI."""
import io
import re
import zipfile

import pytest

import moonglade_backup as core
from moonglade_gallery import load_catalog

from tests.conftest import login_client

LAN = "203.0.113.5"          # a non-loopback "LAN device" address


def _png():
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (8, 8), (90, 70, 160)).save(b, "PNG")
    b.seek(0)
    return b


def test_import_local_catalogs_uploads_as_local(tmp_path):
    """An uploaded file lands in imported/ under the content-addressed name
    (<stem>_local_<hash>.<ext>), cataloged source='local', and (when named) tagged to a
    collection. The id is LAST in the name, matching build_stem_name's convention for
    backed-up files, and it comes from the bytes -- so two different pictures that share
    a basename cannot collide the way they used to."""
    pytest.importorskip("PIL")
    cli = login_client(tmp_path)      # test client defaults to loopback 127.0.0.1
    r = cli.post("/api/import-local",
                 data={"files": (_png(), "my_ref.png"), "collection": "Imports"},
                 content_type="multipart/form-data")
    assert r.status_code == 200, r.get_data(as_text=True)
    d = r.get_json()
    assert d["ok"] and d["imported"] == 1 and d["skipped"] == 0
    local = [x for x in load_catalog(tmp_path / "catalog.db") if x.get("source") == "local"]
    assert len(local) == 1
    name = local[0]["filename"]
    assert re.fullmatch(r"imported/my_ref_local_[0-9a-f]{12}\.png", name), name
    assert local[0]["media_id"] in name                       # id rides in the filename
    assert (tmp_path / name).exists()                         # copied into the backup
    assert "Imports" in (local[0].get("collections") or "")   # collection tagged


def test_import_local_is_localhost_only(tmp_path):
    """A logged-in LAN session must NOT be able to write files onto the server's machine."""
    pytest.importorskip("PIL")
    cli = login_client(tmp_path)
    r = cli.post("/api/import-local",
                 data={"files": (_png(), "x.png")},
                 content_type="multipart/form-data",
                 environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code == 403
    assert not (tmp_path / "imported").exists()               # nothing written


def test_import_local_expands_a_zip(tmp_path):
    """A dropped .zip is expanded, and each image inside is imported."""
    pytest.importorskip("PIL")
    from PIL import Image
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, "w") as z:
        # Two DIFFERENT pictures on purpose: imports are keyed on content, so a zip of
        # the same bytes twice is one picture, not two, and would test nothing here.
        for name, colour in (("a.png", (30, 40, 60)), ("b.png", (200, 90, 20))):
            ib = io.BytesIO()
            Image.new("RGB", (8, 8), colour).save(ib, "PNG")
            z.writestr(name, ib.getvalue())
    zb.seek(0)
    cli = login_client(tmp_path)
    r = cli.post("/api/import-local",
                 data={"files": (zb, "bundle.zip")},
                 content_type="multipart/form-data")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["imported"] == 2                      # both extracted + cataloged
    stored = sorted(p.name for p in (tmp_path / "imported").glob("*.png"))
    assert len(stored) == 2, stored
    assert all(re.fullmatch(r"[ab]_local_[0-9a-f]{12}\.png", n) for n in stored), stored


def test_import_local_zip_slip_is_blocked(tmp_path):
    """A crafted zip member with a ../ path must not escape the temp dir."""
    pytest.importorskip("PIL")
    from PIL import Image
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, "w") as z:
        ib = io.BytesIO()
        Image.new("RGB", (8, 8), (1, 2, 3)).save(ib, "PNG")
        z.writestr("../../escape.png", ib.getvalue())         # zip-slip attempt
        ib2 = io.BytesIO()
        Image.new("RGB", (8, 8), (4, 5, 6)).save(ib2, "PNG")
        z.writestr("safe.png", ib2.getvalue())
    zb.seek(0)
    cli = login_client(tmp_path)
    r = cli.post("/api/import-local",
                 data={"files": (zb, "evil.zip")},
                 content_type="multipart/form-data")
    assert r.status_code == 200
    assert r.get_json()["imported"] == 1                      # only the safe member
    # the escaping member did not write outside the backup
    assert not (tmp_path.parent / "escape.png").exists()
    assert not (tmp_path / "escape.png").exists()
