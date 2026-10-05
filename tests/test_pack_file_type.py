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

import moonglade_container as mc
import moonglade_gallery as g

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


@pytest.fixture
def told(monkeypatch):
    """Stands in for the Explorer refresh; counts the calls."""
    calls = []
    monkeypatch.setattr(g, "_tell_explorer_file_types_changed", lambda: calls.append(1))
    return calls


def _install_pack(tmp_path):
    """A pack carrying the default mark and its launcher .ico, as the shipped pack does."""
    marks = {"marks": [{"id": "mark_4", "label": "Mark", "kind": "tile"}]}
    mc.write_container(g._container_path(), {
        g._role_rel("marks", "marks.json"): json.dumps(marks).encode("utf-8"),
        g._role_rel("marks", "mark_4.png"): PNG,
        g._role_rel("marks", "mark_4.ico"): ICO,
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


def test_a_start_writes_the_per_user_file_type(tmp_path, told):
    _install_pack(tmp_path)
    reg = FakeWinreg()
    assert g.register_pack_file_type(tmp_path, winreg=reg, platform="win32") is True
    icon = g.branding_root().parent / "_container_cache" / "marks" / "mark_4.ico"
    assert reg.table() == _want(icon)
    assert icon.read_bytes() == ICO                   # a real file: Windows reads icons off disk
    assert {w[3] for w in reg.writes} == {FakeWinreg.REG_SZ}
    assert told == [1]


def test_the_icon_is_the_one_the_desktop_shortcut_uses(tmp_path, told):
    """Both ask _mark_ico_path for the current mark, so the pack's icon and the Desktop
    launcher's are the same file."""
    _install_pack(tmp_path)
    reg = FakeWinreg()
    g.register_pack_file_type(tmp_path, winreg=reg, platform="win32")
    shortcut_icon = g._mark_ico_path(g.load_branding(tmp_path)["mark"])
    icon_key = ("HKCU", "software\\classes\\moongladeathenaeum.artpack\\defaulticon", "")
    assert reg.table()[icon_key] == str(shortcut_icon) + ",0"
    assert "_mark_ico_path" in inspect.getsource(g.make_launcher_shortcut)


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
    """Its only production call site is main(): after the one-time rename (so the pack it
    looks for is the one under the new name) and after the coded tree is folded in (so a
    custom mark's .ico is where the icon lookup reads), before the app is built."""
    names = _main_calls()
    assert "register_pack_file_type" in names, "main() no longer registers the pack's type"
    i = names.index("register_pack_file_type")
    assert names.index("migrate_legacy_name") < i
    assert names.index("ensure_branding_discovery_tree") < i < names.index("create_app")
