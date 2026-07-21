"""The start-up port pre-flight: never become the SECOND server on a port.

WHY THIS FILE EXISTS
--------------------
Werkzeug's dev server sets allow_reuse_address, and on Windows SO_REUSEADDR does
something Unix does not -- it lets a second socket bind a port that is ACTIVELY
SERVING, not just one stuck in TIME_WAIT. Two processes then hold :PORT and requests
land on whichever the OS picks, so you edit a file, reload, and read the OLD server's
answer with no error anywhere.

That has burned this project twice. Both times the "fix that didn't work" had in fact
worked perfectly, in a process nobody was talking to.

`Serve Gallery.pyw` already probed the X-Moonglade header before launching, but that
check lived only in the launcher -- and `python pixai_gallery.py --port N`, which is
how every script, harness and background process starts this thing, walked past it.
port_owner() is that probe moved somewhere it cannot be bypassed.
"""
import socket
import threading

import pytest

from pixai_gallery import create_app, port_owner


def _free_port():
    """A port number nothing is listening on: bind :0, read the port, release it."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_free_port_reports_no_owner():
    assert port_owner("127.0.0.1", _free_port()) == ""


def test_a_plain_listener_is_reported_as_other():
    """Something is there but it is not us -- refuse, do not adopt it.

    A bare accept-and-close socket speaks no HTTP at all, which is the harshest
    version of "not ours": the probe's urlopen raises rather than returning a
    response. That path must still answer "other", never "" -- returning "" would
    green-light binding a second server on top of a live process.
    """
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def _accept():
        try:
            conn, _ = srv.accept()
            conn.close()
        except OSError:
            pass

    t = threading.Thread(target=_accept, daemon=True)
    t.start()
    try:
        assert port_owner("127.0.0.1", port) == "other"
    finally:
        srv.close()


def test_a_live_gallery_is_recognised_as_ours_even_though_it_401s(tmp_path):
    """The whole reason the probe reads a HEADER and not a status code.

    /api/ping sits behind the login gate, so a healthy, fully-working server answers
    the probe with 401. Anything checking "did it return 200" would classify a live
    gated server as a dead port and cheerfully start a second one on top of it --
    which is the exact bug. X-Moonglade rides every response including the front
    door's 401 (pinned by tests/test_web_auth.py's
    test_every_response_carries_the_server_marker), so the header survives where the
    status code does not.
    """
    from werkzeug.serving import make_server

    app = create_app(tmp_path)
    srv = make_server("127.0.0.1", 0, app, threaded=True)
    port = srv.server_port
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        # Sanity-check the premise rather than assuming it: the probe endpoint really
        # does refuse anonymously. If this ever starts returning 200, this test is
        # still correct but no longer testing the interesting case.
        cli = app.test_client()
        assert cli.get("/api/ping").status_code == 401

        assert port_owner("127.0.0.1", port) == "moonglade"
        # 0.0.0.0 means "all interfaces", which we probe via loopback -- a server
        # bound this way must not read as free just because the bind address differs.
        assert port_owner("0.0.0.0", port) == "moonglade"
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize("host", ["0.0.0.0", "::", ""])
def test_wildcard_bind_addresses_probe_loopback(host):
    """0.0.0.0/::/"" are bind addresses, not connectable ones -- socket.create_connection
    to "0.0.0.0" is not a meaningful health check, so port_owner rewrites them to
    127.0.0.1. Without that rewrite the LAN-facing launch (--host 0.0.0.0, the one the
    tablet uses) would skip the pre-flight entirely."""
    assert port_owner(host, _free_port()) == ""
