"""The local CA may only vouch for this PC's own names: a letters-only PC name could be a public
top-level domain ("dev", "app"), so it never joins the CA's permitted names (2026-11-19
automated security finding on moonglade/tls.py)."""
import datetime

import pytest

pytest.importorskip("cryptography")

from moonglade import tls  # noqa: E402


@pytest.mark.parametrize("name, safe", [
    ("DESKTOP-ABC1234", True),
    ("gwilkins-pc", True),
    ("pc2", True),
    ("dev", False),
    ("app", False),
    ("local", False),
    ("xn--p1ai", False),
    ("host.example", False),
    ("", False),
])
def test_bare_name_is_safe(name, safe):
    assert tls.bare_name_is_safe(name) is safe


def test_ca_never_permits_a_letters_only_name(tmp_path, monkeypatch):
    from cryptography import x509
    monkeypatch.setattr(tls, "ca_cert_path", lambda: tmp_path / "ca.crt")
    monkeypatch.setattr(tls, "ca_key_path", lambda: tmp_path / "ca.key")
    now = datetime.datetime.now(datetime.timezone.utc)
    ca, _key = tls._ensure_ca(["dev", "DESKTOP-ABC1234"], now)
    nc = ca.extensions.get_extension_for_class(x509.NameConstraints).value
    permitted = {g.value.lower() for g in nc.permitted_subtrees if isinstance(g, x509.DNSName)}
    assert "dev" not in permitted
    assert "desktop-abc1234" in permitted
    assert {"localhost", "local"} <= permitted
