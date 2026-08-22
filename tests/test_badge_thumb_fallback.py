"""_badge_thumb must not 404 (-> emoji) when the badge master lives only in the
container AND the thumbnail cache can't be written (read-only mount, full disk,
permissions). Adversarial-review finding 2026-08-22: it used to fall through to
None -> the route 404s -> every tier's badge silently becomes the emoji. It now
hands the image back in memory for the route to serve.
"""
import io
from pathlib import Path

from PIL import Image

import moonglade_gallery as G


def test_badge_thumb_returns_bytes_when_cache_unwritable(monkeypatch, tmp_path):
    buf = io.BytesIO()
    Image.new("RGBA", (300, 300), (10, 20, 30, 255)).save(buf, format="PNG")
    png = buf.getvalue()

    # A container-only master (no loose file) with a cache we can't write to.
    monkeypatch.setattr(G, "_branding_exists", lambda rel: True)
    monkeypatch.setattr(G, "_branding_bytes", lambda rel: png)
    monkeypatch.setattr(G, "_branding_mtime", lambda rel: 1.0)
    monkeypatch.setattr(G, "_role_dir", lambda role: tmp_path / "no-loose-master")

    def boom_mkdir(self, *a, **k):
        raise OSError("read-only file system")

    monkeypatch.setattr(Path, "mkdir", boom_mkdir)

    out = G._badge_thumb(str(tmp_path), "first-light")

    assert isinstance(out, (bytes, bytearray)), f"expected in-memory bytes, got {type(out)!r}"
    im = Image.open(io.BytesIO(bytes(out)))
    assert max(im.size) <= 256, f"should serve a resized thumb, got {im.size}"


def test_badge_thumb_returns_none_when_master_absent(monkeypatch, tmp_path):
    # No master at all -> still None (route 404 is correct here; there is nothing to serve).
    monkeypatch.setattr(G, "_branding_exists", lambda rel: False)
    assert G._badge_thumb(str(tmp_path), "does-not-exist") is None
