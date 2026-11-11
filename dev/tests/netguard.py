"""The network guard's mechanism (#98): refuse, and record, every connection that leaves this
machine. Plain standard library, because two things import it: dev/tests/conftest.py (this
process, every thread of it, and each pytest-xdist worker) and the `sitecustomize` the
conftest hands to the Python processes a test starts (see `child_site`).

WHAT IS REFUSED. `socket.socket.connect` / `connect_ex` to an IPv4/IPv6 address that is not
loopback, and `socket.getaddrinfo` for a name that is not this machine. Allowed: 127.0.0.0/8,
::1, `localhost` and `*.localhost`, the bind wildcards (0.0.0.0 and ::, which name no remote
party), and unix-socket paths. Everything the suite does against its own servers is one of
those.

A refusal alone would not make a test fail: the app catches network errors by design (an
offline machine still shows a Panel), so a refused call just looks like an offline answer.
Every attempt is therefore also handed to the `record` callback, and the conftest turns a
recorded attempt into a failure of the test that was running.
"""
import ipaddress
import os
import socket
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Set to "1" in the environment while a test that is marked @pytest.mark.network runs, so the
# child processes it starts stand down with it.
OFF_ENV = "MOONGLADE_NETGUARD_OFF"
# Where a child process appends the attempts it made (one "kind<TAB>target" line each); the
# conftest reads the file back and charges them to the running test.
LOG_ENV = "MOONGLADE_NETGUARD_LOG"

_LOOPBACK_NAMES = frozenset({"", "localhost", "localhost.localdomain", "0.0.0.0", "::", "::1",
                             "<broadcast>"})
_real = {}


def is_loopback_host(host):
    """True for a host that is this machine (see the module docstring)."""
    if host is None:
        return True
    if isinstance(host, (bytes, bytearray)):
        host = bytes(host).decode("ascii", "ignore")
    host = str(host)
    if host in _LOOPBACK_NAMES or host.endswith(".localhost"):
        return True
    try:
        addr = ipaddress.ip_address(host.split("%")[0])
    except ValueError:
        return False
    # ::ffff:127.0.0.1 is 127.0.0.1 spelled for a dual-stack socket; Python before 3.13 does not
    # call it loopback itself.
    mapped = getattr(addr, "ipv4_mapped", None)
    return (mapped or addr).is_loopback


def callers(limit=6):
    """The app and test frames (not the libraries between them) that led to the call,
    outermost first, as `path:line function`, repo-relative."""
    root = REPO_ROOT.as_posix() + "/"
    frames = []
    for f in traceback.extract_stack()[:-3]:
        path = os.path.normpath(f.filename).replace("\\", "/")
        if "/site-packages/" in path or path.startswith("<") or not path.startswith(root):
            continue
        frames.append("%s:%d %s" % (path[len(root):], f.lineno, f.name))
    return frames[-limit:]


def install(record):
    """Replace the three socket entry points, once per process. `record(kind, target)` is
    called for every non-loopback attempt and returns True when the attempt is to be refused
    (False means "let it through": the test is marked @pytest.mark.network)."""
    if _real:
        return
    _real.update(connect=socket.socket.connect, connect_ex=socket.socket.connect_ex,
                 getaddrinfo=socket.getaddrinfo)
    inet = (socket.AF_INET, socket.AF_INET6)

    def _remote(sock, address):
        host = address[0] if isinstance(address, tuple) and address else None
        return sock.family in inet and not is_loopback_host(host)

    def connect(self, address):
        if _remote(self, address) and record("connect", address):
            raise ConnectionRefusedError(
                "network guard (#98): refused a non-loopback connect to %r" % (address,))
        return _real["connect"](self, address)

    def connect_ex(self, address):
        if _remote(self, address) and record("connect_ex", address):
            return 10061 if os.name == "nt" else 111               # connection refused
        return _real["connect_ex"](self, address)

    def getaddrinfo(host, *a, **k):
        if not is_loopback_host(host) and record("lookup", host):
            raise socket.gaierror(
                socket.EAI_NONAME, "network guard (#98): refused a non-loopback lookup of %r"
                % (host,))
        return _real["getaddrinfo"](host, *a, **k)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo


def child_record(kind, target):
    """The `record` a child process installs: write the attempt to the parent's log file and
    refuse it, unless the parent's test is marked @pytest.mark.network."""
    if os.environ.get(OFF_ENV) == "1":
        return False
    path = os.environ.get(LOG_ENV)
    if path:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("%s\t%s\n" % (kind, target))
        except OSError:
            pass
    return True


# The `sitecustomize` written for child processes. It loads THIS file by absolute path (no
# sys.path entry, so nothing else from dev/tests can shadow a module in the child).
CHILD_SITECUSTOMIZE = '''\
import os
if os.environ.get(%(log_env)r):
    try:
        import importlib.util as _u
        _spec = _u.spec_from_file_location("_moonglade_netguard", %(path)r)
        _mod = _u.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _mod.install(_mod.child_record)
    except Exception:
        pass
'''


def child_site(folder):
    """Write the child-process `sitecustomize.py` into `folder` and return the folder, to be put
    first on PYTHONPATH. (A Python started with -I or -S does not read it; none of the suite's
    children are.)"""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "sitecustomize.py").write_text(
        CHILD_SITECUSTOMIZE % {"log_env": LOG_ENV, "path": str(Path(__file__).resolve())},
        encoding="utf-8")
    return folder
