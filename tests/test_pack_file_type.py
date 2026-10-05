"""The art pack's Explorer file type (pack v7; the owner approved the per-user registry entry,
2026-10-02): register_pack_file_type() names `.mgpack` "Moonglade art pack" with the app's own
icon, for the current user only.

Every test here hands the function a FAKE registry, so no test ever writes the real one, and
replaces the Explorer refresh call with a recorder. What is held: the exact keys and values,
read-first-write-only-what-differs, nothing outside HKEY_CURRENT_USER, no open command, a no-op
off Windows and without a pack, and an error that logs once and lets the start carry on."""
import inspect
import json
import logging

import pytest

from moonglade import container as mc
from moonglade import gallery as g
from moonglade import paths as moonglade_paths

ICO = b"\x00\x00\x01\x00fake-ico"          # bytes only; nothing here decodes an icon
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082")


class _Key:
    def __init__(self, root, path):
        self.root, self.path = root, path

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeWinreg:
    """The slice of `winreg` the function uses. Key paths and value names are matched without
    case, as the real registry does. Records every key opened or created and every write."""
    HKEY_CURRENT_USER = "HKCU"
    HKEY_LOCAL_MACHINE = "HKLM"
    HKEY_CLASSES_ROOT = "HKCR"
    HKEY_USERS = "HKU"
    KEY_READ = 0x20019
    KEY_WRITE = 0x20006
    REG_SZ = 1

    def __init__(self, fail_writes=False):
        self.values = {}          # (root, path.lower(), name.lower()) -> value
        self.keys = set()         # (root, path.lower())
        self.opened, self.created, self.writes = [], [], []
        self.fail_writes = fail_writes

    def OpenKey(self, root, path, reserved=0, access=KEY_READ):
        self.opened.append((root, path))
        if (root, path.lower()) not in self.keys:
            raise FileNotFoundError(2, "The system cannot find the file specified")
        return _Key(root, path)

    def QueryValueEx(self, key, name):
        try:
            return self.values[(key.root, key.path.lower(), name.lower())], self.REG_SZ
        except KeyError:
            raise FileNotFoundError(2, "The system cannot find the file specified") from None

    def CreateKeyEx(self, root, path, reserved=0, access=KEY_WRITE):
        self.created.append((root, path))
        if self.fail_writes:
            raise PermissionError(5, "Access is denied")
        self.keys.add((root, path.lower()))
        return _Key(root, path)

    def SetValueEx(self, key, name, reserved, typ, value):
        self.writes.append((key.root, key.path, name, typ, value))
        self.values[(key.root, key.path.lower(), name.lower())] = value

    def table(self):
        return {(root, path, name): v for (root, path, name), v in self.values.items()}


@pytest.fixture(autouse=True)
def lad(tmp_path, monkeypatch):
    """A temporary %LOCALAPPDATA%: the icon copy lands here, never in the real one."""
    folder = tmp_path / "localappdata"
    monkeypatch.setenv("LOCALAPPDATA", str(folder))
    return folder


def _icon_file(lad):
    return lad / "Moonglade Athenaeum" / "mgpack.ico"


@pytest.fixture
def told(monkeypatch):
    """Stands in for the Explorer refresh; counts the calls."""
    calls = []
    monkeypatch.setattr(g, "_tell_explorer_file_types_changed", lambda: calls.append(1))
    return calls


def _install_pack(tmp_path, ico=ICO):
    """A pack carrying the default mark and its launcher .ico, as the shipped pack does."""
    marks = {"marks": [{"id": "mark_4", "label": "Mark", "kind": "tile"}]}
    mc.write_container(g._container_path(), {
        g._role_rel("marks", "marks.json"): json.dumps(marks).encode("utf-8"),
        g._role_rel("marks", "mark_4.png"): PNG,
        g._role_rel("marks", "mark_4.ico"): ico,
    }, {})
    g._container_cache.update(path=None, mtime=None, box=None)


def _want(icon):
    c = "software\\classes\\"
    return {
        ("HKCU", c + ".mgpack", ""): "MoongladeAthenaeum.ArtPack",
        ("HKCU", c + "moongladeathenaeum.artpack", ""): "Moonglade art pack",
        ("HKCU", c + "moongladeathenaeum.artpack", "friendlytypename"): "Moonglade art pack",
        ("HKCU", c + "moongladeathenaeum.artpack\\defaulticon", ""): str(icon) + ",0",
    }


def test_a_start_writes_the_per_user_file_type(tmp_path, lad, told):
    _install_pack(tmp_path)
    reg = FakeWinreg()
    assert g.register_pack_file_type(tmp_path, winreg=reg, platform="win32") is True
    assert reg.table() == _want(_icon_file(lad))
    assert _icon_file(lad).read_bytes() == ICO        # a real file: Windows reads icons off disk
    assert {w[3] for w in reg.writes} == {FakeWinreg.REG_SZ}
    assert told == [1]


def test_the_icon_is_the_desktop_shortcuts_copied_to_one_place_outside_any_install(
        tmp_path, lad, told, monkeypatch):
    """The picture is the current mark's .ico, the one the Desktop shortcut uses. Explorer is
    pointed at a copy in one fixed per-user place rather than into an install's own cache, so
    every install on the account (the D: one and the C: one) names the same path, and moving
    or deleting an install never leaves Explorer pointing at a file that is gone."""
    _install_pack(tmp_path)
    reg = FakeWinreg()
    g.register_pack_file_type(tmp_path, winreg=reg, platform="win32")
    shortcut_icon = g._mark_ico_path(g.load_branding(tmp_path)["mark"])
    assert _icon_file(lad).read_bytes() == shortcut_icon.read_bytes()
    icon_key = ("HKCU", "software\\classes\\moongladeathenaeum.artpack\\defaulticon", "")
    assert reg.table()[icon_key] == str(_icon_file(lad)) + ",0"
    assert "_container_cache" not in reg.table()[icon_key]
    assert "_mark_ico_path" in inspect.getsource(g.make_launcher_shortcut)
    # a second install on the same account names the very same path
    other = tmp_path / "second-install"
    other.mkdir()
    monkeypatch.setattr(g, "branding_root", lambda: other / "branding")
    monkeypatch.setattr(moonglade_paths, "local_path", lambda name: other / name)
    _install_pack(other)
    g.register_pack_file_type(other, winreg=reg, platform="win32")
    assert reg.table()[icon_key] == str(_icon_file(lad)) + ",0"


def test_the_icon_copy_is_rewritten_only_when_its_bytes_differ(tmp_path, lad, told):
    _install_pack(tmp_path)
    reg = FakeWinreg()
    g.register_pack_file_type(tmp_path, winreg=reg, platform="win32")
    stamp = _icon_file(lad).stat().st_mtime_ns
    import time
    time.sleep(0.05)
    assert g.register_pack_file_type(tmp_path, winreg=reg, platform="win32") is False
    assert _icon_file(lad).stat().st_mtime_ns == stamp          # same bytes: untouched
    _install_pack(tmp_path, ico=ICO + b"-recut")                  # the mark's icon changed
    assert g.register_pack_file_type(tmp_path, winreg=reg, platform="win32") is True
    assert _icon_file(lad).read_bytes() == ICO + b"-recut"
    assert told == [1, 1]                                         # Explorer told about the new icon


def test_a_failed_icon_copy_keeps_the_registrys_icon_and_logs_once(
        tmp_path, monkeypatch, told, caplog):
    _install_pack(tmp_path)
    blocker = tmp_path / "not-a-folder"
    blocker.write_bytes(b"x")                                     # a folder can't be made under a file
    monkeypatch.setenv("LOCALAPPDATA", str(blocker))
    reg = FakeWinreg()
    icon_key = ("HKCU", "software\\classes\\moongladeathenaeum.artpack\\defaulticon", "")
    reg.keys.add(icon_key[:2])
    reg.values[icon_key] = "C:\\before\\mgpack.ico,0"
    with caplog.at_level(logging.INFO):
        assert g.register_pack_file_type(tmp_path, winreg=reg, platform="win32") is True
    assert reg.table()[icon_key] == "C:\\before\\mgpack.ico,0"     # today's icon kept
    assert reg.table()[("HKCU", "software\\classes\\.mgpack", "")] == "MoongladeAthenaeum.ArtPack"
    assert len([r for r in caplog.records if r.levelno >= logging.WARNING]) == 1


def test_it_reads_first_and_writes_only_what_differs(tmp_path, told):
    _install_pack(tmp_path)
    reg = FakeWinreg()
    g.register_pack_file_type(tmp_path, winreg=reg, platform="win32")
    first = len(reg.writes)
    assert g.register_pack_file_type(tmp_path, winreg=reg, platform="win32") is False
    assert len(reg.writes) == first                   # all in place: nothing written
    assert told == [1]                                # and Explorer not bothered again
    reg.values[("HKCU", "software\\classes\\moongladeathenaeum.artpack",
                "friendlytypename")] = "something else"
    assert g.register_pack_file_type(tmp_path, winreg=reg, platform="win32") is True
    assert [w[2] for w in reg.writes[first:]] == ["FriendlyTypeName"]


def test_it_never_leaves_the_current_user_and_adds_no_open_command(tmp_path, told):
    _install_pack(tmp_path)
    reg = FakeWinreg()
    g.register_pack_file_type(tmp_path, winreg=reg, platform="win32")
    assert reg.opened and reg.created
    assert {root for root, _ in reg.opened + reg.created} == {"HKCU"}
    assert all(p.lower().startswith("software\\classes\\") for _, p in reg.created)
    assert not [p for _, p in reg.created if "shell" in p.lower()], "a pack must not open"
    src = inspect.getsource(g.register_pack_file_type)
    for other in ("HKEY_LOCAL_MACHINE", "HKEY_CLASSES_ROOT", "HKEY_USERS"):
        assert other not in src


def test_off_windows_it_does_nothing(tmp_path, told):
    _install_pack(tmp_path)
    reg = FakeWinreg()
    assert g.register_pack_file_type(tmp_path, winreg=reg, platform="linux") is False
    assert reg.opened == reg.created == reg.writes == []
    assert told == []


def test_without_a_pack_it_does_nothing(tmp_path, told):
    g._container_path().unlink(missing_ok=True)
    reg = FakeWinreg()
    assert g.register_pack_file_type(tmp_path, winreg=reg, platform="win32") is False
    assert reg.opened == reg.created == reg.writes == []


def test_a_registry_that_refuses_logs_once_and_the_start_carries_on(tmp_path, told, caplog):
    _install_pack(tmp_path)
    reg = FakeWinreg(fail_writes=True)
    with caplog.at_level(logging.INFO):
        assert g.register_pack_file_type(tmp_path, winreg=reg, platform="win32") is False
    warned = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warned) == 1
    assert told == []


def _main_calls():
    import ast
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(g.main)))
    calls = sorted((n.lineno, n.col_offset, getattr(n.func, "id", getattr(n.func, "attr", None)))
                   for n in ast.walk(tree) if isinstance(n, ast.Call))
    return [c[2] for c in calls]


def test_a_real_start_registers_the_file_type_after_the_pack_is_settled():
    """Its only production call site is main(): after the tidy that renames an old pack and
    brings it into local/ (so the pack it looks for is the one in its new place) and after the
    coded tree is folded in (so a custom mark's .ico is where the icon lookup reads), before
    the app is built."""
    names = _main_calls()
    assert "register_pack_file_type" in names, "main() no longer registers the pack's type"
    i = names.index("register_pack_file_type")
    assert names.index("tidy_app_folder") < i
    assert names.index("ensure_branding_discovery_tree") < i < names.index("create_app")


def test_no_test_can_reach_the_real_registry(tmp_path, lad, told):
    """conftest swaps the module a plain `import winreg` hands back for a stub that refuses
    every use, so a test that forgets to pass a fake can never touch the real registry: the
    function reaches the registry first, fails there, and writes nothing -- not even the
    icon copy."""
    import winreg
    with pytest.raises(OSError):
        winreg.HKEY_CURRENT_USER
    _install_pack(tmp_path)
    assert g.register_pack_file_type(tmp_path, platform="win32") is False
    assert not _icon_file(lad).exists()
    assert told == []
