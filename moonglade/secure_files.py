"""
moonglade/secure_files.py
=========================
Secrets at rest: the files that hold a credential are readable by the person running Moonglade
and nobody else on the machine.

The files: config.json (the PixAI API key, the session signing key and the account hashes),
local/mirror_session.json (the Mirror's PixAI sign-in), local/remembered_devices.json (remembered
browsers and paired TVs, with each TV token's hash), local/tls_key.pem (the home-network
server certificate's key) and local/tls_ca_key.pem (the key of the small certificate authority
that signs it). local/settings.json holds no secret (the library folder, the
bind address and port, the Bonjour name, the Mirror switch, launch switches, branding) and is
left as it is.

restrict_to_owner(path) runs after every write of one of them (an atomic write replaces the
file, and a new file takes its folder's permissions) and once at server start for the copies
already there (restrict_existing_secrets). On Windows the file's access list is replaced with
one that is NOT inherited from the folder and names two entries: the current Windows user and
SYSTEM (backup and indexing services run as SYSTEM, and an administrator can take ownership of
any file whatever its list says). On macOS and Linux the mode becomes 0600.

It fails soft: a file system that keeps no permissions, or an OS that refuses, writes one log
line and the write that called it still counts. Nothing here ever reads or logs a file's
contents.
"""
import logging
import os

_log = logging.getLogger(__name__)

# The two entries a Windows secret file keeps: the current user's SID goes in the first.
# D:P = a protected access list (nothing inherited from the folder); FA = full access;
# SY = the LocalSystem account.
_SDDL_OWNER_ONLY = "D:P(A;;FA;;;{sid})(A;;FA;;;SY)"


def _current_user_sid():
    """The current process user's SID as a string (S-1-5-21-...). Windows only; raises OSError."""
    import ctypes
    from ctypes import wintypes
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                          ctypes.POINTER(wintypes.HANDLE)]
    advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                             wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p,
                                                ctypes.POINTER(wintypes.LPWSTR)]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    TOKEN_QUERY, TOKEN_USER = 0x0008, 1
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_QUERY,
                                     ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        need = wintypes.DWORD(0)
        advapi32.GetTokenInformation(token, TOKEN_USER, None, 0, ctypes.byref(need))
        buf = ctypes.create_string_buffer(need.value or 256)
        if not advapi32.GetTokenInformation(token, TOKEN_USER, buf, len(buf),
                                            ctypes.byref(need)):
            raise ctypes.WinError(ctypes.get_last_error())
        psid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]   # TOKEN_USER.User.Sid
        text = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(psid, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return text.value
        finally:
            kernel32.LocalFree(text)
    finally:
        kernel32.CloseHandle(token)


def _restrict_windows(path):
    """Replace `path`'s access list with the owner-only one. Raises OSError when Windows refuses."""
    import ctypes
    from ctypes import wintypes
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetSecurityDescriptorDacl.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.BOOL)]
    advapi32.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p]
    advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    SDDL_REVISION_1, SE_FILE_OBJECT = 1, 1
    DACL_SECURITY_INFORMATION = 0x00000004
    PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
    sddl = _SDDL_OWNER_ONLY.format(sid=_current_user_sid())
    psd = ctypes.c_void_p()
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, SDDL_REVISION_1, ctypes.byref(psd), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        present, defaulted = wintypes.BOOL(), wintypes.BOOL()
        pdacl = ctypes.c_void_p()
        if not advapi32.GetSecurityDescriptorDacl(psd, ctypes.byref(present),
                                                  ctypes.byref(pdacl), ctypes.byref(defaulted)):
            raise ctypes.WinError(ctypes.get_last_error())
        rc = advapi32.SetNamedSecurityInfoW(
            str(path), SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, pdacl, None)
        if rc != 0:
            raise ctypes.WinError(rc)
    finally:
        kernel32.LocalFree(psd)


def restrict_to_owner(path):
    """Make `path` readable and writable by the current user only (and SYSTEM on Windows).

    Returns True when the permissions were set, False when the file is absent or the OS
    refused -- in which case one warning line names the file (never its contents) and the
    caller carries on. Never raises."""
    try:
        p = os.fspath(path)
    except TypeError:
        return False
    if not os.path.isfile(p):
        return False
    try:
        if os.name == "nt":
            _restrict_windows(p)
        else:
            os.chmod(p, 0o600)
        return True
    except Exception as e:                       # noqa: BLE001 -- a refusal must never stop a write
        _log.warning("couldn't limit %s to this user's account (%s); it keeps its folder's "
                     "permissions", os.path.basename(p), e)
        return False


def write_private(path, data):
    """Write `data` (str or bytes) to a NEW file at `path` that is owner-only BEFORE a byte of
    it is written: the file is created empty (0600 on POSIX), restricted, and only then
    filled and flushed to disk. For the temp file of an atomic secret write -- the caller
    os.replace()s it into place, and NTFS and POSIX both keep the moved file's permissions.
    Raises OSError like open() would; a restriction the OS refuses is the soft log line of
    restrict_to_owner, never an exception."""
    p = os.fspath(path)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.close(fd)
    restrict_to_owner(p)
    raw = data.encode("utf-8") if isinstance(data, str) else data
    with open(p, "r+b") as f:
        f.write(raw)
        f.truncate()
        f.flush()
        os.fsync(f.fileno())


def secret_files():
    """Every file this install keeps a secret in, whether or not it exists yet."""
    from moonglade import paths as _paths
    return [_paths.config_path(),
            _paths.local_path(_paths.MIRROR_SESSION_NAME),
            _paths.local_path(_paths.REMEMBERED_DEVICES_NAME),
            _paths.local_path(_paths.TLS_KEY_NAME),
            _paths.local_path(_paths.TLS_CA_KEY_NAME)]


def restrict_existing_secrets():
    """Once at server start: restrict the secret files already on disk. Returns how many were
    restricted. Never raises."""
    n = 0
    try:
        for p in secret_files():
            if restrict_to_owner(p):
                n += 1
    except Exception:                            # noqa: BLE001 -- a startup nicety
        _log.warning("couldn't check the secret files' permissions", exc_info=True)
    return n
