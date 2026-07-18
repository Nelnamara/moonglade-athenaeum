"""The Loom's full-bundle project export/import (tier 2 of the two-tier design; tier 1,
the lightweight JSON, is pure client-side and untested here). /api/loom/export-bundle
zips project.json plus every media file a project actually references; /api/loom/
import-bundle reconciles that media into the receiving catalog, skipping anything
already resolvable there. Both localhost-gated, same trust level as /export-zip."""
import io
import json
import zipfile

from PIL import Image

from pixai_gallery import CATALOG_FIELDS, create_app, save_catalog


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _png_bytes(color=(120, 40, 200), size=(16, 16)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _client(tmp_path, rows=()):
    if rows:
        save_catalog(tmp_path / "catalog.db", list(rows))
    return create_app(tmp_path).test_client()


def _project(**overrides):
    p = {
        "name": "Test Project",
        "acts": [{"id": "a1", "name": "Act 1", "cards": [
            {"id": "c1", "resultMid": "", "openFrame": {}, "closeFrame": {}, "refs": []},
        ]}],
        "assets": [],
    }
    p.update(overrides)
    return p


def _post_json(cli, url, payload):
    return cli.post(url, data=json.dumps(payload), content_type="application/json")


def _post_zip(cli, url, zip_bytes, filename="bundle.zip"):
    return cli.post(url, data={"file": (io.BytesIO(zip_bytes), filename)},
                     content_type="multipart/form-data")


def _make_bundle(project, thumbs=None, media=()):
    """media: [(media_id, ext, bytes)] -- mirrors what export-bundle itself produces."""
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_STORED) as z:
        z.writestr("project.json", json.dumps({"project": project, "thumbs": thumbs or {}}))
        for mid, ext, data in media:
            z.writestr("media/{}{}".format(mid, ext), data)
    return mem.getvalue()


# --- export-bundle ---------------------------------------------------------------

def test_export_bundle_includes_referenced_image(tmp_path):
    (tmp_path / "a_100.png").write_bytes(_png_bytes())
    cli = _client(tmp_path, [_row(media_id="100", filename="a_100.png")])
    project = _project(assets=[{"id": "as1", "mediaId": "100", "thumbId": ""}])
    r = _post_json(cli, "/api/loom/export-bundle", {"project": project, "thumbs": {}})
    assert r.status_code == 200
    assert r.headers.get("X-Bundle-Missing-Count") == "0"
    z = zipfile.ZipFile(io.BytesIO(r.data))
    assert "project.json" in z.namelist()
    assert "media/100.png" in z.namelist()
    assert json.loads(z.read("project.json"))["project"]["name"] == "Test Project"


def test_export_bundle_resolves_video_via_catalog_row_not_find_files(tmp_path):
    """find_files_for_media_id is image-only by design (INVARIANT 6/7 territory) -- a
    project referencing a video by media_id would silently vanish from every bundle
    without the /api/loom/export fallback: catalog row -> is_video + filename."""
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / "v_200.mp4").write_bytes(b"not a real mp4 but a real file")
    cli = _client(tmp_path, [_row(media_id="200", filename="videos/v_200.mp4", is_video="1")])
    project = _project(assets=[{"id": "as1", "mediaId": "200", "thumbId": ""}])
    r = _post_json(cli, "/api/loom/export-bundle", {"project": project, "thumbs": {}})
    assert r.headers.get("X-Bundle-Missing-Count") == "0"
    z = zipfile.ZipFile(io.BytesIO(r.data))
    assert "media/200.mp4" in z.namelist()
    assert z.read("media/200.mp4") == b"not a real mp4 but a real file"


def test_export_bundle_reports_missing_media_but_still_succeeds(tmp_path):
    """A referenced media_id with no file on disk doesn't fail the whole export -- a
    partial bundle is still useful, and the client surfaces what didn't travel."""
    cli = _client(tmp_path, [])
    project = _project(assets=[{"id": "as1", "mediaId": "does-not-exist", "thumbId": ""}])
    r = _post_json(cli, "/api/loom/export-bundle", {"project": project, "thumbs": {}})
    assert r.status_code == 200
    assert r.headers.get("X-Bundle-Missing-Count") == "1"
    z = zipfile.ZipFile(io.BytesIO(r.data))
    assert z.namelist() == ["project.json"]  # no media/ entries at all


def test_export_bundle_collects_every_reference_shape(tmp_path):
    """resultMid, both frame slots, and cast/assets all contribute -- refs[]/thumbId
    are deliberately excluded (client-only, already travel inside project.json)."""
    for mid in ("1", "2", "3", "4"):
        (tmp_path / "a_{}.png".format(mid)).write_bytes(_png_bytes())
    cli = _client(tmp_path, [_row(media_id=m, filename="a_{}.png".format(m)) for m in ("1", "2", "3", "4")])
    project = _project(
        acts=[{"id": "a1", "name": "Act 1", "cards": [{
            "id": "c1", "resultMid": "1",
            "openFrame": {"mediaId": "2"}, "closeFrame": {"mediaId": "3"},
            "refs": [{"id": "r1", "thumbId": "local-only", "mediaId": ""}],
        }]}],
        assets=[{"id": "as1", "mediaId": "4", "thumbId": ""}],
    )
    r = _post_json(cli, "/api/loom/export-bundle", {"project": project, "thumbs": {}})
    z = zipfile.ZipFile(io.BytesIO(r.data))
    names = set(z.namelist())
    assert names == {"project.json", "media/1.png", "media/2.png", "media/3.png", "media/4.png"}


def test_export_bundle_localhost_only(tmp_path):
    cli = _client(tmp_path, [])
    r = _post_json(cli, "/api/loom/export-bundle", {"project": _project()})
    r_lan = cli.post("/api/loom/export-bundle", data=json.dumps({"project": _project()}),
                      content_type="application/json", environ_overrides={"REMOTE_ADDR": "192.168.1.50"})
    assert r.status_code == 200
    assert r_lan.status_code == 403


# --- import-bundle -----------------------------------------------------------------

def test_import_bundle_catalogs_new_media_and_returns_project(tmp_path):
    cli = _client(tmp_path, [])
    project = _project(assets=[{"id": "as1", "mediaId": "new-1", "thumbId": ""}])
    zip_bytes = _make_bundle(project, media=[("new-1", ".png", _png_bytes((10, 200, 90)))])
    r = _post_zip(cli, "/api/loom/import-bundle", zip_bytes)
    d = r.get_json()
    assert r.status_code == 200
    assert d["media_added"] == 1
    assert d["project"]["name"] == "Test Project"
    dest = tmp_path / "imported" / "new-1.png"
    assert dest.exists()
    assert Image.open(dest).getpixel((0, 0)) == (10, 200, 90)
    thumb = tmp_path / "gallery" / "thumbs" / "new-1.jpg"
    assert thumb.exists()  # make_thumbnail ran for the new image


def test_import_bundle_catalog_row_shape(tmp_path):
    cli = _client(tmp_path, [])
    project = _project(assets=[{"id": "as1", "mediaId": "new-2", "thumbId": ""}])
    zip_bytes = _make_bundle(project, media=[("new-2", ".png", _png_bytes())])
    _post_zip(cli, "/api/loom/import-bundle", zip_bytes)
    import sqlite3
    con = sqlite3.connect(tmp_path / "catalog.db")
    row = con.execute("SELECT source, status, filename, is_video FROM catalog WHERE media_id=?",
                       ("new-2",)).fetchone()
    assert row == ("api", "imported", "imported/new-2.png", "")


def test_import_bundle_skips_media_already_present(tmp_path):
    """Idempotent both ways: media the receiving machine already has (by id) is left
    alone -- no duplicate file, no catalog write, no re-import work."""
    (tmp_path / "a_100.png").write_bytes(_png_bytes())
    cli = _client(tmp_path, [_row(media_id="100", filename="a_100.png")])
    project = _project(assets=[{"id": "as1", "mediaId": "100", "thumbId": ""}])
    zip_bytes = _make_bundle(project, media=[("100", ".png", _png_bytes((1, 1, 1)))])
    r = _post_zip(cli, "/api/loom/import-bundle", zip_bytes)
    assert r.get_json()["media_added"] == 0
    assert not (tmp_path / "imported" / "100.png").exists()  # never wrote a duplicate


def test_reimporting_the_same_bundle_twice_is_a_noop_the_second_time(tmp_path):
    cli = _client(tmp_path, [])
    project = _project(assets=[{"id": "as1", "mediaId": "new-3", "thumbId": ""}])
    zip_bytes = _make_bundle(project, media=[("new-3", ".png", _png_bytes())])
    d1 = _post_zip(cli, "/api/loom/import-bundle", zip_bytes).get_json()
    d2 = _post_zip(cli, "/api/loom/import-bundle", zip_bytes).get_json()
    assert d1["media_added"] == 1
    assert d2["media_added"] == 0


def test_import_bundle_rejects_a_zip_with_no_project_json(tmp_path):
    cli = _client(tmp_path, [])
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w") as z:
        z.writestr("not_project.json", "{}")
    r = _post_zip(cli, "/api/loom/import-bundle", mem.getvalue())
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_import_bundle_rejects_a_non_zip_file(tmp_path):
    cli = _client(tmp_path, [])
    r = _post_zip(cli, "/api/loom/import-bundle", b"this is not a zip file at all", filename="bundle.zip")
    assert r.status_code == 400


def test_import_bundle_requires_a_file(tmp_path):
    cli = _client(tmp_path, [])
    r = cli.post("/api/loom/import-bundle", data={}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_import_bundle_localhost_only(tmp_path):
    cli = _client(tmp_path, [])
    zip_bytes = _make_bundle(_project())
    r = cli.post("/api/loom/import-bundle", data={"file": (io.BytesIO(zip_bytes), "b.zip")},
                 content_type="multipart/form-data", environ_overrides={"REMOTE_ADDR": "192.168.1.50"})
    assert r.status_code == 403
