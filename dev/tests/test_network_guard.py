"""The network guard (#98): a test that opens a connection leaving this machine fails.

The mechanism is dev/tests/netguard.py and its hooks are in dev/tests/conftest.py. These tests
hold three things: loopback is never touched (the suite's own servers all live there), a remote
address or name is refused AND recorded with who asked, and a recorded attempt really fails the
test that made it -- including one made by a Python process the test started, and one swallowed
by the code under test, which is how the app treats every network error. The last two run a
small pytest session of their own, because the failure is the one thing a test cannot assert
about itself.
"""
import os
import socket
import subprocess
import sys
import textwrap

import pytest

from tests import conftest as suite
from tests import netguard

# A documentation-only address (RFC 5737 TEST-NET-1): not routable anywhere, and nothing here
# ever sends to it -- the guard refuses before the socket is asked to.
REMOTE_IP = "192.0.2.1"


def _drain():
    """Take this test's own deliberate attempts out of the suite's books, so the guard does not
    fail the test that proves it works."""
    with suite._NET_LOCK:
        taken = list(suite._NET_ATTEMPTS)
        suite._NET_ATTEMPTS[:] = []
    return taken


def test_loopback_is_never_refused():
    for host in ("127.0.0.1", "127.1.2.3", "::1", "localhost", "app.localhost", "0.0.0.0", ""):
        assert netguard.is_loopback_host(host), host
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    client = socket.socket()
    client.connect(server.getsockname())                       # a real loopback connect
    client.close()
    server.close()
    assert socket.getaddrinfo("localhost", 80)
    assert _drain() == []


def test_an_ipv4_mapped_loopback_is_loopback_on_every_python():
    # ::ffff:127.0.0.1 is 127.0.0.1 on a dual-stack socket; ipaddress calls it loopback only from 3.13
    assert netguard.is_loopback_host("::ffff:127.0.0.1")
    assert not netguard.is_loopback_host("::ffff:192.0.2.1")


def test_a_remote_address_or_name_is_not_loopback():
    for host in (REMOTE_IP, "8.8.8.8", "2001:db8::1", "api.pixai.art", "example.com"):
        assert not netguard.is_loopback_host(host), host


def test_a_remote_connect_is_refused_and_recorded_with_who_asked():
    s = socket.socket()
    try:
        with pytest.raises(ConnectionRefusedError, match="#98"):
            s.connect((REMOTE_IP, 443))
        assert s.connect_ex((REMOTE_IP, 443)) != 0
    finally:
        s.close()
    taken = _drain()
    assert [(k, t) for k, t, *_ in taken] == [("connect", (REMOTE_IP, 443)),
                                              ("connect_ex", (REMOTE_IP, 443))]
    assert "dev/tests/test_network_guard.py" in " ".join(taken[0][2]), taken[0][2]


def test_a_remote_lookup_is_refused_and_recorded():
    with pytest.raises(socket.gaierror, match="#98"):
        socket.getaddrinfo("api.pixai.art", 443)
    assert [(k, t) for k, t, *_ in _drain()] == [("lookup", "api.pixai.art")]


def test_the_failure_names_the_address_and_the_caller():
    message = suite._net_message([("connect", (REMOTE_IP, 443), ["moonglade/x.py:1 f"],
                                  "test_x.py::test_y (call)", "Thread-9")])
    assert REMOTE_IP in message and "moonglade/x.py:1 f" in message and "#98" in message
    # ...and who was running, and on which thread, so a background thread's attempt does not
    # blame the innocent test that happened to report next
    assert "test_x.py::test_y (call)" in message and "Thread-9" in message


_NESTED = textwrap.dedent('''
    import socket
    import subprocess
    import sys
    import pytest


    def test_a_swallowed_remote_connect_still_fails():
        try:
            socket.create_connection(("%(ip)s", 443), timeout=1)
        except OSError:
            pass                                   # the app treats a network error as "offline"


    def test_a_python_the_test_started_still_fails():
        subprocess.run([sys.executable, "-c",
                        "import socket; socket.getaddrinfo('api.pixai.art', 443)"],
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=120)


    def test_a_real_failure_keeps_its_text_beside_the_network_message():
        try:
            socket.getaddrinfo("api.pixai.art", 443)
        except OSError:
            pass
        assert 1 == 2, "REAL-ASSERTION-MESSAGE"


    @pytest.mark.network
    def test_a_marked_test_is_left_alone():
        socket.getaddrinfo("%(ip)s", 443)          # numeric: no lookup is sent anywhere


    def test_loopback_is_left_alone():
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        socket.create_connection(server.getsockname(), timeout=5).close()
        server.close()
''' % {"ip": REMOTE_IP})


def test_a_recorded_attempt_fails_the_test_that_made_it(tmp_path):
    """The whole path in a session of its own: this suite's conftest loaded as a plugin over four
    small tests. Three are refused and reported FAILED (one swallowed the error as the app does,
    one started a Python that looked a name up, one also had a real assertion failure, whose text
    must stay beside the network message); the marked one and the loopback one pass."""
    (tmp_path / "test_nested.py").write_text(_NESTED, encoding="utf-8")
    env = dict(os.environ)
    env.pop(netguard.LOG_ENV, None)
    env.pop(netguard.OFF_ENV, None)
    dev = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    repo = os.path.dirname(dev)
    env["PYTHONPATH"] = os.pathsep.join([dev, repo])
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "tests.conftest", "-p", "no:cacheprovider",
         "-o", "addopts=", "--rootdir", str(tmp_path), "-q", "-rA", str(tmp_path / "test_nested.py")],
        cwd=str(tmp_path), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, timeout=600)
    out = r.stdout.decode("utf-8", "replace")
    assert "FAILED test_nested.py::test_a_swallowed_remote_connect_still_fails" in out, out
    assert "FAILED test_nested.py::test_a_python_the_test_started_still_fails" in out, out
    assert "FAILED test_nested.py::test_a_real_failure_keeps_its_text_beside_the_network_message" in out, out
    assert "REAL-ASSERTION-MESSAGE" in out and "api.pixai.art" in out, out       # both, not one
    assert "made while" in out and "test_a_python_the_test_started_still_fails" in out, out
    assert "PASSED test_nested.py::test_a_marked_test_is_left_alone" in out, out
    assert "PASSED test_nested.py::test_loopback_is_left_alone" in out, out
    assert REMOTE_IP in out and "api.pixai.art" in out, out        # the message names them
    assert "3 failed, 2 passed" in out, out
