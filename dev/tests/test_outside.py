"""moonglade/outside.py: things outside the app that still name this install's old files,
found and fixed (DECISIONS 2026-10-07, pick 5).

Everything here runs against FAKES in temp folders: task XML handed back by a stand-in for
schtasks, Claude configs written by the test, and .lnk files built byte by byte. No test
touches the real Task Scheduler, the real Claude configs or the real Desktop: conftest makes
moonglade.outside.machine() refuse, and each test hands in its own Machine. (The one test
that drives Windows' own shortcut writer writes only into its temp folder, and only on
Windows.)

What is held:
  * the command rewrite: each old file to its new form, from any shape a task or shortcut
    gives it, and nothing that is another install's;
  * Task Scheduler: found from `schtasks /query /xml ONE`, rewritten through
    `schtasks /create /xml ... /f` with everything else in the task kept, its XML copied into
    the snapshot first; a task with a saved password, or one Windows refuses, is reported
    with why, never half-done;
  * Claude: Claude Desktop's config and both of Claude Code's scopes rewritten to
    `-m moonglade.mcp_server` (-P only for a Python of 3.11 or later, asked of the
    registration's own Python, which must have fastmcp) with PYTHONPATH added and the other
    env kept, written whole after a re-read (a change Claude made meanwhile is never lost); a
    copy kept beside the file, never in the install, and removed once the rewrite reads back;
    "Fixed" only then, with "restart Claude". A registration run through another program, or
    naming the old file by a relative path it does not anchor here, is reported with the
    command line to use, never rewritten; checked off Windows too;
  * shortcuts: only what changes is written (an icon-only fault gets its icon and nothing
    else), a copy kept, the file swapped in whole, and nothing left behind when Windows
    refuses; the launcher's pass only takes the ones that start this install's old launcher,
    now gone, never one this user cannot change, and sweeps a temp a killed save left;
  * off Windows only the Claude configs are looked at.
"""
import json
import ntpath
import os
import shutil
import struct
import subprocess
import sys

import pytest

from moonglade import outside

PY = r"C:\Python311\python.exe"
_CLSID = bytes.fromhex("0114020000000000c000000000000046")


# ---- a .lnk, built byte by byte (MS-SHLLINK: header, LinkInfo, unicode StringData) -----------

def build_lnk(target, args="", workdir="", icon="", icon_index=0, name="", idlist=b""):
    flags = 0x2 | 0x80                                   # HasLinkInfo | IsUnicode
    if idlist:
        flags |= 0x1
    for bit, value in ((0x4, name), (0x10, workdir), (0x20, args), (0x40, icon)):
        if value:
            flags |= bit
    header = struct.pack("<I16sIIQQQIiIHHII", 0x4C, _CLSID, flags, 0x20, 0, 0, 0, 0,
                         icon_index, 1, 0, 0, 0, 0)
    assert len(header) == 76
    body = b""
    if idlist:
        body += struct.pack("<H", len(idlist)) + idlist
    volume = struct.pack("<IIII", 17, 3, 0, 0x10) + b"\x00"
    ansi = target.encode("latin-1", "replace") + b"\x00"
    suffix = b"\x00"
    wide = target.encode("utf-16-le") + b"\x00\x00"
    wsuffix = b"\x00\x00"
    head = 0x24
    vol_at = head
    base_at = vol_at + len(volume)
    suffix_at = base_at + len(ansi)
    wbase_at = suffix_at + len(suffix)
    wsuffix_at = wbase_at + len(wide)
    size = wsuffix_at + len(wsuffix)
    info = struct.pack("<IIIIIIIII", size, head, 0x1, vol_at, base_at, 0, suffix_at,
                       wbase_at, wsuffix_at) + volume + ansi + suffix + wide + wsuffix
    assert len(info) == size
    body += info
    for bit, value in ((0x4, name), (0x10, workdir), (0x20, args), (0x40, icon)):
        if value:
            body += struct.pack("<H", len(value)) + value.encode("utf-16-le")
    return header + body + struct.pack("<I", 0)


def write_lnk(path, **kw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_lnk(**kw))
    return path


# ---- a fake machine ---------------------------------------------------------------------------

class FakeSchtasks:
    """A stand-in for schtasks.exe: /query /xml ONE lists the tasks, /query /tn X /xml gives
    one, /create /xml F /f records what would have been registered."""

    def __init__(self, tasks, create_rc=0, create_err="", encoding="utf-8"):
        self.tasks = dict(tasks)             # name -> task XML
        self.created = {}
        self.calls = []
        self.create_rc, self.create_err = create_rc, create_err
        self.encoding = encoding

    def _out(self, text):
        return text.encode(self.encoding)

    def __call__(self, argv):
        self.calls.append(list(argv))
        assert argv[0] == "schtasks", argv
        if argv[1:] == ["/query", "/xml", "ONE"]:
            parts = ['<?xml version="1.0" encoding="UTF-16"?>', "<Tasks>"]
            for name, xml in self.tasks.items():
                parts += ["  <!-- %s -->" % name, xml]
            parts.append("</Tasks>")
            return 0, self._out("\r\n".join(parts)), ""
        if argv[1:2] == ["/query"] and "/tn" in argv:
            name = argv[argv.index("/tn") + 1]
            if name not in self.tasks:
                return 1, b"", "ERROR: The system cannot find the file specified."
            return 0, self._out('<?xml version="1.0" encoding="UTF-16"?>\r\n'
                                + self.tasks[name]), ""
        if argv[1:2] == ["/create"]:
            name = argv[argv.index("/tn") + 1]
            raw = open(argv[argv.index("/xml") + 1], "rb").read()
            assert raw.startswith(b"\xff\xfe"), "schtasks reads task XML as UTF-16"
            self.created[name] = raw.decode("utf-16")
            if self.create_rc == 0:
                self.tasks[name] = self.created[name].split("?>", 1)[1].strip()
            return self.create_rc, b"", self.create_err
        raise AssertionError("unexpected schtasks call %r" % argv)


def task_xml(command, arguments="", workdir="", logon="InteractiveToken", user=None,
             group=None):
    wd = "<WorkingDirectory>%s</WorkingDirectory>" % workdir if workdir else ""
    args = "<Arguments>%s</Arguments>" % arguments if arguments else ""
    # The account the task runs as comes before its logon type, as Windows writes a principal.
    who = ("<UserId>%s</UserId>" % user if user else "") + \
        ("<GroupId>%s</GroupId>" % group if group else "")
    return (
        '<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
        "<RegistrationInfo><Author>DESKTOP\\owner</Author>"
        "<URI>\\Moonglade sync</URI></RegistrationInfo>"
        "<Triggers><CalendarTrigger><StartBoundary>2026-01-01T03:00:00</StartBoundary>"
        "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger>"
        "</Triggers>"
        '<Principals><Principal id="Author">%s<LogonType>%s</LogonType></Principal>'
        "</Principals>"
        "<Settings><Enabled>true</Enabled></Settings>"
        '<Actions Context="Author"><Exec><Command>%s</Command>%s%s</Exec></Actions>'
        "</Task>" % (who, logon, command, args, wd))


class SavedLnk:
    """A stand-in for Windows' shortcut writer: records what it was told and writes it, so
    the file on disk really changes. A field given as None is left as the shortcut has it."""

    def __init__(self, refuse=None):
        self.saved = []
        self.refuse = refuse

    def __call__(self, path, target, args, workdir, icon):
        if self.refuse:
            raise self.refuse
        self.saved.append(dict(path=str(path), target=target, args=args, workdir=workdir,
                               icon=icon))
        old = outside.read_lnk(path)
        icon_path, _, index = (icon or "").rpartition(",")
        path.write_bytes(build_lnk(old.target if target is None else target,
                                   args=old.args if args is None else args,
                                   workdir=old.workdir if workdir is None else workdir,
                                   icon=icon_path if icon else old.icon,
                                   icon_index=int(index) if icon else old.icon_index))


class Probe:
    """A stand-in for asking a registration's Python its version and whether it has fastmcp:
    records what was asked."""

    def __init__(self, version=(3, 11), fastmcp=True, starts=True):
        self.asked = []
        self.answer = {"version": version, "fastmcp": fastmcp} if starts else None

    def __call__(self, argv):
        self.asked.append(list(argv))
        return self.answer


@pytest.fixture
def install(tmp_path):
    root = tmp_path / "Moonglade Athenaeum"           # a space, as real folders have
    (root / "moonglade").mkdir(parents=True)
    (root / "Moonglade Launcher.pyw").write_text("# the launcher\n", encoding="utf-8")
    return root


@pytest.fixture
def box(tmp_path):
    """The machine's folders, all temp: where shortcuts live, the Claude configs, the
    snapshot and the icons."""
    class Box:
        desktop = tmp_path / "Desktop"
        public = tmp_path / "Public Desktop"
        programs = tmp_path / "Start Menu" / "Programs"
        common = tmp_path / "ProgramData Start Menu" / "Programs"
        taskbar = tmp_path / "User Pinned" / "TaskBar"
        claude_desktop = tmp_path / "AppData" / "Claude" / "claude_desktop_config.json"
        claude_code = tmp_path / "home" / ".claude.json"
        snapshot = tmp_path / "local" / ".snapshot" / "outside"
        icons = tmp_path / "local" / "icons"
    for d in (Box.desktop, Box.public, Box.programs, Box.common, Box.taskbar):
        d.mkdir(parents=True)
    return Box


ME = ("S-1-5-21-111-222-333-1001", "DESKTOP\\owner")      # the account running the app


def machine(box, platform="win32", tasks=None, save=None, probe=None, user=ME):
    return outside.Machine(
        platform=platform,
        shortcut_folders=[(box.desktop, "on your Desktop", False),
                          (box.public, "on the Desktop for all users", False),
                          (box.programs, "in your Start menu", True),
                          (box.common, "in the Start menu for all users", True),
                          (box.taskbar, "pinned to your taskbar", False)],
        claude_configs=[(box.claude_desktop, "Claude Desktop"), (box.claude_code, "Claude Code")],
        run=tasks if tasks is not None else FakeSchtasks({}),
        save_lnk=save or SavedLnk(),
        python=PY,
        probe=probe or Probe(),
        user=user)


def _fix(items, install, m, box, **kw):
    return outside.fix(items, install=install, m=m, snapshot=box.snapshot, icons=box.icons, **kw)


def _snapshots(box):
    return sorted(p.name for p in box.snapshot.iterdir()) if box.snapshot.is_dir() else []


# ---- the command rewrite ----------------------------------------------------------------------

def _rw(install, command, arguments="", workdir=""):
    return outside.rewrite_command(command, arguments, workdir, install, PY)


def test_the_app_made_shortcut_points_at_the_new_launcher(install):
    rw = _rw(install, r"C:\Python311\pythonw.exe", '"%s\\Serve Gallery.pyw"' % install,
             str(install))
    assert rw.changed and rw.refs == ["Serve Gallery.pyw"]
    assert rw.command == r"C:\Python311\pythonw.exe"
    assert rw.arguments == '"%s\\Moonglade Launcher.pyw"' % install
    assert rw.workdir == str(install)


def test_a_send_to_shortcut_on_the_launcher_itself(install):
    rw = _rw(install, str(install / "Serve Gallery.pyw"))
    # A Windows path, built the way Windows builds one (a POSIX tmp path on CI is joined with
    # a backslash, as a shortcut's target would be).
    assert rw.changed and rw.command == ntpath.join(str(install), "Moonglade Launcher.pyw")


def test_the_command_line_tool_becomes_the_code_folder(install):
    rw = _rw(install, PY, '"%s\\moonglade_backup.py" --sync --workers 8' % install)
    assert rw.arguments == '"%s\\moonglade" --sync --workers 8' % install
    assert rw.command == PY


def test_a_py_file_run_by_its_type_gets_python_named(install):
    rw = _rw(install, str(install / "moonglade_backup.py"), "--update")
    assert rw.command == PY
    assert rw.arguments == '"%s" --update' % ntpath.join(str(install), "moonglade")


def test_inside_cmd_the_old_file_is_rewritten_in_place(tmp_path):
    inst = tmp_path / "app"                                  # no space: an unquoted path
    rw = outside.rewrite_command(r"C:\Windows\System32\cmd.exe",
                                 '/c "python %s\\moonglade_backup.py --sync >> log.txt"' % inst,
                                 "", inst, PY)
    assert rw.arguments == '/c "python %s\\moonglade --sync >> log.txt"' % inst


def test_inside_cmd_a_file_started_by_its_type_gets_python_named(install):
    rw = _rw(install, r"C:\Windows\System32\cmd.exe",
             '/c "%s\\moonglade_backup.py" --update' % install)
    assert rw.arguments == '/c %s "%s\\moonglade" --update' % (PY, install)
    spaced = outside.rewrite_command(r"C:\Windows\System32\cmd.exe",
                                     '/c "%s\\moonglade_backup.py"' % install, "", install,
                                     r"C:\Program Files\Python311\python.exe")
    assert spaced.arguments == '/c "C:\\Program Files\\Python311\\python.exe" "%s\\moonglade"' % (
        install)


def test_py_launcher_options_still_count_as_python(install):
    rw = _rw(install, r"C:\Windows\py.exe", '-3 "%s\\moonglade_backup.py" --sync' % install)
    assert rw.arguments == '-3 "%s\\moonglade" --sync' % install


def test_the_old_server_becomes_the_module_started_in_the_app_folder(install):
    rw = _rw(install, PY, '"%s\\moonglade_gallery.py" --port 5757' % install)
    assert rw.changed
    assert rw.arguments == "-m moonglade.gallery --port 5757"
    assert rw.workdir == str(install)
    same = _rw(install, PY, '"%s\\moonglade_gallery.py"' % install, str(install))
    assert same.changed and same.workdir == str(install)


def test_the_old_server_from_another_start_in_folder_is_not_guessed(install, tmp_path):
    rw = _rw(install, PY, '"%s\\moonglade_gallery.py"' % install, str(tmp_path / "elsewhere"))
    assert rw.refs and not rw.changed
    assert "another folder" in rw.problem


def test_a_bare_name_counts_only_in_the_app_folder(install, tmp_path):
    rw = _rw(install, PY, "moonglade_backup.py --sync", str(install))
    assert rw.arguments == "moonglade --sync"
    rw = _rw(install, PY, r".\moonglade_backup.py --sync", str(install))
    assert rw.arguments == r".\moonglade --sync"
    other = _rw(install, PY, "moonglade_backup.py --sync", str(tmp_path / "other"))
    assert not other.refs and other.arguments == "moonglade_backup.py --sync"


def test_another_install_is_left_alone(install, tmp_path):
    for line in ('"D:\\Moonglade Athenaeum\\moonglade_backup.py" --sync',
                 '"%s2\\moonglade_backup.py" --sync' % install,
                 '"%s\\sub\\moonglade_backup.py" --sync' % install,
                 '"%s\\Serve Gallery.pyw.bak"' % install):
        rw = _rw(install, PY, line)
        assert not rw.refs and rw.arguments == line, line


@pytest.mark.parametrize("command, line", [
    (r"C:\Windows\System32\cmd.exe", '/c del "{i}\\moonglade_backup.py"'),
    (r"C:\Windows\System32\cmd.exe", '/c copy /y "{i}\\moonglade_backup.py" D:\\bak'),
    (r"C:\Windows\notepad.exe", '"{i}\\moonglade_backup.py"'),
    (r"C:\Windows\System32\cmd.exe", '/c type "{i}\\moonglade_gallery.py"'),
])
def test_an_old_file_named_for_another_program_is_reported_not_rewritten(install, command,
                                                                         line):
    """Python goes in front of an old file only where it is started by its type. Named for
    another program (del, copy, an editor), Python in front would make a different command --
    `del <python.exe> ...` deletes the interpreter -- so the line is left and reported."""
    line = line.format(i=install)
    rw = _rw(install, command, line)
    assert rw.refs and not rw.changed and "won't rewrite on a guess" in rw.problem
    assert rw.arguments == line


@pytest.mark.parametrize("command, line, want", [
    (r"C:\Windows\System32\cmd.exe", '/k "{i}\\moonglade_backup.py" --sync',
     '/k {py} "{i}\\moonglade" --sync'),
    (r"C:\Windows\System32\cmd.exe", '/q /c "{i}\\moonglade_backup.py"',
     '/q /c {py} "{i}\\moonglade"'),
    (r"C:\Windows\System32\cmd.exe", '/c start "" /min "{i}\\moonglade_backup.py" --sync',
     '/c start "" /min {py} "{i}\\moonglade" --sync'),
    (r"C:\Windows\System32\conhost.exe", 'cmd.exe /c "{i}\\moonglade_backup.py"',
     'cmd.exe /c {py} "{i}\\moonglade"'),
])
def test_an_old_file_started_by_its_type_still_gets_python_named(install, command, line,
                                                                  want):
    rw = _rw(install, command, line.format(i=install))
    assert rw.changed, rw.problem
    assert rw.arguments == want.format(i=install, py=PY)


def test_case_and_separators_are_windows_rules(install):
    line = '"%s/MOONGLADE_BACKUP.PY" --sync' % str(install).upper().replace("\\", "/")
    rw = _rw(install, PY, line)
    assert rw.refs == ["moonglade_backup.py"]
    assert rw.arguments.endswith('moonglade" --sync')


# ---- Task Scheduler ---------------------------------------------------------------------------

def _tasks(install):
    return {
        "\\Moonglade sync": task_xml(PY, '"%s\\moonglade_backup.py" --sync' % install),
        "\\Other install": task_xml(PY, '"D:\\Moonglade\\moonglade_backup.py" --sync'),
        "\\Microsoft\\Windows\\Defrag\\ScheduledDefrag": task_xml(
            r"%windir%\system32\defrag.exe", "-c -h -o"),
    }


def test_a_task_naming_this_install_is_found_and_nothing_else(install, box):
    m = machine(box, tasks=FakeSchtasks(_tasks(install)))
    found = outside.find(install, m, kinds=("task",))
    assert [(i.kind, i.key, i.label) for i in found] == [
        ("task", "\\Moonglade sync", "the scheduled task “Moonglade sync”")]


def test_a_task_is_rewritten_whole_with_its_xml_kept_first(install, box):
    st = FakeSchtasks(_tasks(install))
    m = machine(box, tasks=st)
    results = _fix(outside.find(install, m, kinds=("task",)), install, m, box)
    assert [r.as_dict() for r in results] == [
        {"label": "the scheduled task “Moonglade sync”", "fixed": True, "reason": "",
         "note": ""}]
    created = st.created["\\Moonglade sync"]
    assert "<Arguments>&quot;%s\\moonglade&quot; --sync</Arguments>" % install in created \
        or '<Arguments>"%s\\moonglade" --sync</Arguments>' % install in created
    assert "moonglade_backup.py" not in created
    assert "<DaysInterval>1</DaysInterval>" in created          # the rest is kept
    assert "<LogonType>InteractiveToken</LogonType>" in created
    assert 'xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"' in created
    assert set(st.created) == {"\\Moonglade sync"}             # nothing else registered
    snap = _snapshots(box)
    assert len(snap) == 1 and snap[0].endswith("task-Moonglade_sync.xml")
    assert "moonglade_backup.py" in (box.snapshot / snap[0]).read_text(encoding="utf-8")
    assert outside.find(install, m, kinds=("task",)) == []     # nothing left to find


def test_a_task_with_a_saved_password_is_reported_not_touched(install, box):
    st = FakeSchtasks({"\\Moonglade sync": task_xml(
        PY, '"%s\\moonglade_backup.py" --sync' % install, logon="Password")})
    m = machine(box, tasks=st)
    [r] = _fix(outside.find(install, m, kinds=("task",)), install, m, box)
    assert not r.fixed and "saved Windows password" in r.reason
    assert st.created == {} and _snapshots(box) == []


@pytest.mark.parametrize("who, words", [
    ({"user": "S-1-5-18", "logon": "ServiceAccount"}, "service account (S-1-5-18)"),
    ({"user": "S-1-5-21-111-222-333-1002"}, "another Windows account (S-1-5-21-111-222-333-1002)"),
    ({"user": "DESKTOP\\someone"}, "another Windows account (DESKTOP\\someone)"),
    ({"group": "S-1-5-32-545"}, "a group of Windows accounts"),
])
def test_a_task_that_runs_as_another_account_is_reported_not_touched(install, box, who,
                                                                    words):
    """The app re-registers a task only as the account running it. One that runs as SYSTEM,
    a service, a group or another user would get this user's python.exe -- one that account
    may not be able to read, or this user may be able to change under it -- so it is
    reported like a saved-password task, and left as it is."""
    st = FakeSchtasks({"\\Moonglade sync": task_xml(
        PY, '"%s\\moonglade_backup.py" --sync' % install, **who)})
    m = machine(box, tasks=st)
    [r] = _fix(outside.find(install, m, kinds=("task",)), install, m, box)
    assert not r.fixed and words in r.reason and "Task Scheduler" in r.reason
    assert st.created == {} and _snapshots(box) == []


@pytest.mark.parametrize("account", ["S-1-5-21-111-222-333-1001", "DESKTOP\\owner", "owner",
                                     "desktop\\OWNER"])
def test_a_task_that_runs_as_the_app_s_own_account_is_fixed(install, box, account):
    st = FakeSchtasks({"\\Moonglade sync": task_xml(
        PY, '"%s\\moonglade_backup.py" --sync' % install, user=account)})
    m = machine(box, tasks=st)
    [r] = _fix(outside.find(install, m, kinds=("task",)), install, m, box)
    assert r.fixed, r.reason
    assert "<UserId>%s</UserId>" % account in st.created["\\Moonglade sync"]


def test_a_task_whose_account_can_t_be_told_is_left_as_it_is(install, box):
    st = FakeSchtasks({"\\Moonglade sync": task_xml(
        PY, '"%s\\moonglade_backup.py" --sync' % install, user="DESKTOP\\owner")})
    m = machine(box, tasks=st, user=None)
    [r] = _fix(outside.find(install, m, kinds=("task",)), install, m, box)
    assert not r.fixed and st.created == {}


def test_a_task_windows_refuses_is_reported_with_why(install, box):
    st = FakeSchtasks(_tasks(install), create_rc=1, create_err="ERROR: Access is denied.")
    m = machine(box, tasks=st)
    [r] = _fix(outside.find(install, m, kinds=("task",)), install, m, box)
    assert not r.fixed and "administrator" in r.reason


def test_schtasks_output_in_utf16_is_read(install, box):
    m = machine(box, tasks=FakeSchtasks(_tasks(install), encoding="utf-16"))
    assert [i.key for i in outside.find(install, m, kinds=("task",))] == ["\\Moonglade sync"]


def test_a_task_carrying_a_doctype_is_never_parsed(install, box):
    evil = ('<!DOCTYPE Task [<!ENTITY x "moonglade_backup.py">]>'
            + task_xml(PY, '"%s\\&x;"' % install))
    m = machine(box, tasks=FakeSchtasks({"\\Odd": evil}))
    assert outside.find(install, m, kinds=("task",)) == []


def test_parse_tasks_reads_the_one_document_form():
    text = ('<?xml version="1.0"?>\n<Tasks>\n  <!-- \\A -->\n<Task><x/></Task>\n'
            '  <!-- \\Folder\\B c -->\n<Task version="1.2"><y/></Task>\n</Tasks>')
    assert [n for n, _ in outside.parse_tasks(text)] == ["\\A", "\\Folder\\B c"]


# ---- Claude -----------------------------------------------------------------------------------

def _mcp(install, **extra):
    spec = {"command": "python", "args": [str(install / "moonglade_mcp.py")],
            "env": {"MOONGLADE_OUT": "D:\\library"}}
    spec.update(extra)
    return spec


def _write_json(path, doc, indent=2):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=indent) + "\n", encoding="utf-8")


def test_claude_desktops_registration_is_rewritten_with_its_env_kept(install, box):
    other = {"command": "npx", "args": ["-y", "@some/server"], "env": {"KEY": "secret"}}
    _write_json(box.claude_desktop, {"mcpServers": {"moonglade": _mcp(install), "other": other},
                                     "globalShortcut": "Ctrl+Space"})
    original = box.claude_desktop.read_bytes()
    m = machine(box)
    found = outside.find(install, m, kinds=("claude",))
    assert [i.label for i in found] == ["Claude Desktop's Moonglade tools"]
    [r] = _fix(found, install, m, box)
    assert r.fixed and r.note == "Restart Claude to use it."
    assert r.line() == "Fixed Claude Desktop's Moonglade tools. Restart Claude to use it."
    doc = json.loads(box.claude_desktop.read_text(encoding="utf-8"))
    new = doc["mcpServers"]["moonglade"]
    assert new["command"] == "python"
    assert new["args"] == ["-P", "-m", "moonglade.mcp_server"], "its Python said 3.11"
    assert new["env"] == {"MOONGLADE_OUT": "D:\\library", "PYTHONPATH": str(install)}
    assert doc["mcpServers"]["other"] == other
    assert doc["globalShortcut"] == "Ctrl+Space"
    assert box.claude_desktop.read_text(encoding="utf-8").startswith('{\n  "mcpServers"')
    # S6: a config can hold keys and tokens -- never copied into the install's snapshot; the
    # copy kept beside it goes once the rewrite reads back.
    assert _snapshots(box) == []
    assert [p.name for p in box.claude_desktop.parent.iterdir()] == [box.claude_desktop.name]
    assert original != box.claude_desktop.read_bytes()


def test_claude_codes_user_and_project_scopes_are_both_rewritten(install, box):
    _write_json(box.claude_code, {
        "numStartups": 12,
        "mcpServers": {"moonglade": _mcp(install)},
        "projects": {"C:\\work": {"mcpServers": {"mg": _mcp(install, env={})},
                                  "history": ["a"]},
                     "C:\\other": {"mcpServers": {"x": {"command": "node", "args": ["s.js"]}}}},
    })
    m = machine(box, probe=Probe(version=(3, 10)))
    found = outside.find(install, m, kinds=("claude",))
    assert [i.label for i in found] == ["Claude Code's Moonglade tools"]
    [r] = _fix(found, install, m, box)
    assert r.fixed
    doc = json.loads(box.claude_code.read_text(encoding="utf-8"))
    assert doc["numStartups"] == 12
    assert doc["mcpServers"]["moonglade"]["args"] == ["-m", "moonglade.mcp_server"], \
        "S5: a 3.10 Python refuses -P, so it is not written"
    assert doc["mcpServers"]["moonglade"]["args"][-1] == "moonglade.mcp_server"
    proj = doc["projects"]["C:\\work"]
    assert proj["mcpServers"]["mg"]["env"] == {"PYTHONPATH": str(install)}
    assert proj["history"] == ["a"]
    assert doc["projects"]["C:\\other"]["mcpServers"]["x"] == {"command": "node", "args": ["s.js"]}


def test_a_pythonpath_already_set_keeps_its_entries(install, box):
    _write_json(box.claude_desktop, {"mcpServers": {"moonglade": _mcp(
        install, env={"PYTHONPATH": "C:\\libs"})}})
    m = machine(box)
    _fix(outside.find(install, m, kinds=("claude",)), install, m, box)
    env = json.loads(box.claude_desktop.read_text(encoding="utf-8"))["mcpServers"]["moonglade"]["env"]
    assert env["PYTHONPATH"] == str(install) + ";C:\\libs"


def test_another_installs_registration_is_left_alone(install, box):
    _write_json(box.claude_desktop, {"mcpServers": {"moonglade": {
        "command": "python", "args": ["D:\\Moonglade\\moonglade_mcp.py"]}}})
    before = box.claude_desktop.read_bytes()
    m = machine(box)
    assert outside.find(install, m, kinds=("claude",)) == []
    assert outside.fix(None, install=install, m=m, snapshot=box.snapshot, icons=box.icons) == []
    assert box.claude_desktop.read_bytes() == before


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_off_windows_another_install_s_full_path_is_left_alone(install, box, platform):
    """#21: since Python 3.13 ntpath no longer calls "/home/..." absolute, so another install's
    registration was taken for this install's "unsure" one -- an item whose Fix could never
    work, offered at every start. Off Windows a "/"-rooted name is a full path."""
    _write_json(box.claude_desktop, {"mcpServers": {"moonglade": {
        "command": "python3", "args": ["/home/someone/other-install/moonglade_mcp.py"]}}})
    m = machine(box, platform=platform)
    assert outside.find(install, m, kinds=("claude",)) == []
    plan = outside.rewrite_mcp_server(
        {"command": "python3", "args": ["/home/someone/other-install/moonglade_mcp.py"]},
        install, PY, platform)
    assert plan is None


def test_a_registration_s_python_options_are_never_run_on_a_guess(install, box):
    """E: the fixer asks the registration's own Python its version before it writes. Only
    plain interpreter switches go with that question, so a registration carrying code of its
    own (`-c ...`) is reported, never run, and never written."""
    _write_json(box.claude_desktop, {"mcpServers": {"moonglade": {
        "command": "python", "args": ["-c", "import os; os.remove('x')",
                                      str(install / "moonglade_mcp.py")]}}})
    before = box.claude_desktop.read_bytes()
    probe = Probe(version=(3, 12))
    m = machine(box, probe=probe)
    [item] = outside.find(install, m, kinds=("claude",))
    [r] = _fix([item], install, m, box)
    assert not r.fixed and "options the app won't run on a guess" in r.reason
    assert probe.asked == [], "its Python was never started"
    assert box.claude_desktop.read_bytes() == before


def test_a_task_name_that_could_split_is_never_passed_to_schtasks(install, box):
    """E: every schtasks call is a list (no shell); a name with a quote or a line break is not
    passed at all."""
    st = FakeSchtasks({})
    m = machine(box, tasks=st)
    item = outside.Item("task", 'evil" /ru SYSTEM "', "the scheduled task", {
        "name": 'evil" /ru SYSTEM "'})
    [r] = _fix([item], install, m, box)
    assert not r.fixed and "won't pass to Task Scheduler" in r.reason
    assert st.calls == []


def test_the_shortcut_writer_s_script_never_carries_a_value(monkeypatch, tmp_path):
    """E: the shortcut's path and fields reach PowerShell as environment variables; the script
    is the same text every time, so a crafted name or argument -- a quote, a typographic
    quote (PowerShell ends a '...' string at those too), a `; command` -- is never code."""
    seen = []
    monkeypatch.setattr(outside, "_run", lambda argv, timeout=60, env=None:
                        seen.append((list(argv), dict(env or {}))) or (0, b"", ""))
    crafted = "x\u2019; Remove-Item -Recurse C:\\ ; '\" & calc"
    outside._save_lnk_with_powershell(tmp_path / ("short\u2019cut'; calc.lnk"), crafted,
                                      crafted, None, crafted + ",0")
    [(argv, env)] = seen
    assert argv[:4] == ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
    assert argv[4] == outside._LNK_SCRIPT, "the script is fixed text"
    assert "calc" not in " ".join(argv) and "\u2019" not in " ".join(argv)
    assert env["MOONGLADE_LNK_PATH"] == str(tmp_path / ("short\u2019cut'; calc.lnk"))
    assert env["MOONGLADE_LNK_TargetPath"] == crafted
    assert env["MOONGLADE_LNK_Arguments"] == crafted
    assert "MOONGLADE_LNK_SET_WorkingDirectory" not in env, "None leaves a field as it is"


def test_the_registration_s_own_python_is_asked_with_its_own_options(install, box):
    """S5: `py -3.12 <old file>` runs the tools on 3.12, whatever Python runs the app: the
    py launcher is asked with its own option, and -P follows its answer."""
    _write_json(box.claude_desktop, {"mcpServers": {"moonglade": {
        "command": "py", "args": ["-3.12", str(install / "moonglade_mcp.py")]}}})
    probe = Probe(version=(3, 12))
    m = machine(box, probe=probe)
    [r] = _fix(outside.find(install, m, kinds=("claude",)), install, m, box)
    assert r.fixed and probe.asked == [["py", "-3.12"]]
    new = json.loads(box.claude_desktop.read_text(encoding="utf-8"))["mcpServers"]["moonglade"]
    assert new["command"] == "py" and new["args"] == ["-3.12", "-P", "-m", "moonglade.mcp_server"]


def test_a_registration_run_through_another_program_is_reported_with_the_line_to_use(
        install, box):
    """S5: `uv run --with fastmcp <old file>` is not rewritten on a guess (`-P -m ...` would
    land in uv's arguments): it is reported, with the command line to use."""
    _write_json(box.claude_code, {"mcpServers": {"moonglade": {
        "command": "uv", "args": ["run", "--with", "fastmcp",
                                  str(install / "moonglade_mcp.py")]}}})
    before = box.claude_code.read_bytes()
    m = machine(box)
    [item] = outside.find(install, m, kinds=("claude",))
    [r] = _fix([item], install, m, box)
    assert not r.fixed
    assert "starts through uv" in r.reason and "-m moonglade.mcp_server" in r.reason
    assert str(install) in r.reason
    assert box.claude_code.read_bytes() == before


@pytest.mark.parametrize("probe, words", [
    (Probe(starts=False), "couldn't be started"),
    (Probe(fastmcp=False), "doesn't have fastmcp"),
], ids=["no-python", "no-fastmcp"])
def test_a_python_that_cannot_run_the_tools_is_never_written(install, box, probe, words):
    """S5: "Fixed" only when the registration's own Python can run the new command."""
    _write_json(box.claude_desktop, {"mcpServers": {"moonglade": _mcp(install)}})
    before = box.claude_desktop.read_bytes()
    m = machine(box, probe=probe)
    [r] = _fix(outside.find(install, m, kinds=("claude",)), install, m, box)
    assert not r.fixed and words in r.reason
    assert box.claude_desktop.read_bytes() == before


def test_a_relative_old_file_is_this_install_s_only_where_it_starts_here(install, box,
                                                                        tmp_path):
    """Rehearsal 9: `.\\moonglade_mcp.py` names the file in whatever folder the server starts
    in. With no cwd saying that is this install, it would match every install's fixer: it is
    reported and left alone. With this install as its cwd, it is this install's."""
    _write_json(box.claude_desktop, {"mcpServers": {"moonglade": {
        "command": "python", "args": [".\\moonglade_mcp.py"]}}})
    before = box.claude_desktop.read_bytes()
    m = machine(box)
    [item] = outside.find(install, m, kinds=("claude",))
    [r] = _fix([item], install, m, box)
    assert not r.fixed and "which folder it starts in" in r.reason
    assert box.claude_desktop.read_bytes() == before
    _write_json(box.claude_desktop, {"mcpServers": {"moonglade": {
        "command": "python", "args": [".\\moonglade_mcp.py"], "cwd": str(install)}}})
    [r] = _fix(outside.find(install, m, kinds=("claude",)), install, m, box)
    assert r.fixed
    _write_json(box.claude_desktop, {"mcpServers": {"moonglade": {
        "command": "python", "args": [".\\moonglade_mcp.py"],
        "cwd": str(tmp_path / "another install")}}})
    assert outside.find(install, m, kinds=("claude",)) == []


def test_a_change_claude_makes_meanwhile_is_never_lost(install, box, monkeypatch):
    """S6: Claude rewrites its config often. Between the fixer's read and its replace, Claude
    wrote: the fixer reads it again and rewrites THAT, so both changes stand."""
    _write_json(box.claude_code, {"numStartups": 1,
                                  "mcpServers": {"moonglade": _mcp(install)}})
    m = machine(box)
    [item] = outside.find(install, m, kinds=("claude",))
    real = outside._backup_beside
    wrote = {"n": 0}

    def backup(path, data):
        out = real(path, data)
        if wrote["n"] == 0:                    # Claude writes, just then
            wrote["n"] += 1
            doc = json.loads(path.read_text(encoding="utf-8"))
            doc["numStartups"] = 2
            _write_json(path, doc)
        return out
    monkeypatch.setattr(outside, "_backup_beside", backup)
    [r] = _fix([item], install, m, box)
    assert r.fixed
    doc = json.loads(box.claude_code.read_text(encoding="utf-8"))
    assert doc["numStartups"] == 2, "Claude's change kept"
    assert doc["mcpServers"]["moonglade"]["args"][-1] == "moonglade.mcp_server", "and the fix"
    assert [p.name for p in box.claude_code.parent.iterdir()] == [".claude.json"]


def test_a_temp_a_killed_save_left_beside_a_config_is_swept(install, box):
    import time
    _write_json(box.claude_desktop, {"mcpServers": {"moonglade": _mcp(install)}})
    stale = box.claude_desktop.with_name(".claude_desktop_config.json.moonglade-0123abcd.tmp")
    stale.write_text("half", encoding="utf-8")
    old = time.time() - 3600
    os.utime(stale, (old, old))
    m = machine(box)
    _fix(outside.find(install, m, kinds=("claude",)), install, m, box)
    assert not stale.exists()


def test_a_registration_already_rewritten_finds_nothing(install, box):
    _write_json(box.claude_desktop, {"mcpServers": {"moonglade": {
        "command": "python", "args": ["-P", "-m", "moonglade.mcp_server"],
        "env": {"PYTHONPATH": str(install)}}}})
    assert outside.find(install, machine(box), kinds=("claude",)) == []


def test_a_broken_config_is_skipped_not_fatal(install, box):
    box.claude_desktop.parent.mkdir(parents=True)
    box.claude_desktop.write_text("{ not json", encoding="utf-8")
    assert outside.find(install, machine(box)) == []


def _beside(path):
    return sorted(p.name for p in path.parent.iterdir())


def test_a_lone_surrogate_in_the_config_is_kept_and_no_copy_is_left(install, box):
    """A string Claude cut in the middle of an emoji is saved with a lone surrogate escape.
    UTF-8 can't carry one raw, so the fix used to fail after its copy of the config (keys and
    tokens included) was made, leaving one more beside it at every press. It is written back
    as the escape it was read from, and the copy goes once the rewrite reads back."""
    box.claude_code.parent.mkdir(parents=True, exist_ok=True)
    box.claude_code.write_text(
        '{\n  "tipsHistory": {"x": "abc\\ud83d"},\n  "mcpServers": {"moonglade": %s}\n}\n'
        % json.dumps(_mcp(install)), encoding="utf-8")
    m = machine(box)
    [r] = _fix(outside.find(install, m, kinds=("claude",)), install, m, box)
    assert r.fixed, r.reason
    doc = json.loads(box.claude_code.read_text(encoding="utf-8"))
    assert doc["tipsHistory"]["x"] == "abc\ud83d", "the unrelated field is as it was"
    assert doc["mcpServers"]["moonglade"]["args"][-1] == "moonglade.mcp_server"
    assert _beside(box.claude_code) == [".claude.json"], "no copy left beside it"


def test_a_write_that_fails_leaves_no_copy_beside_the_config(install, box, monkeypatch):
    _write_json(box.claude_code, {"mcpServers": {"moonglade": _mcp(install)}})
    m = machine(box)
    [item] = outside.find(install, m, kinds=("claude",))

    def refuse(path, data, expect=None):
        raise ValueError("can't be written")
    monkeypatch.setattr(outside, "_write_atomically", refuse)
    [r] = _fix([item], install, m, box)
    assert not r.fixed and "couldn't be written" in r.reason
    assert _beside(box.claude_code) == [".claude.json"]


@pytest.mark.parametrize("option", ["-E", "-I"])
def test_a_registration_that_ignores_pythonpath_is_reported_never_written(install, box,
                                                                          option):
    """-E and -I make Python ignore PYTHONPATH, which the rewritten registration needs to find
    the app: it would be written, read back as Fixed, and never start. It is reported with
    the command line to use, and the file is left as it is."""
    _write_json(box.claude_desktop, {"mcpServers": {"moonglade": {
        "command": "python", "args": [option, str(install / "moonglade_mcp.py")]}}})
    before = box.claude_desktop.read_bytes()
    probe = Probe(version=(3, 12))
    m = machine(box, probe=probe)
    [item] = outside.find(install, m, kinds=("claude",))
    [r] = _fix([item], install, m, box)
    assert not r.fixed and option in r.reason and "PYTHONPATH" in r.reason
    assert probe.asked == []
    assert box.claude_desktop.read_bytes() == before


def test_a_change_claude_makes_while_the_new_file_is_flushed_is_kept(install, box,
                                                                     monkeypatch):
    """Claude writes after the fixer's own file is written and flushed, just before the
    replace: the file is compared again then, so the rewrite starts again from Claude's
    version, and both changes stand."""
    _write_json(box.claude_code, {"numStartups": 1,
                                  "mcpServers": {"moonglade": _mcp(install)}})
    m = machine(box)
    [item] = outside.find(install, m, kinds=("claude",))
    real, wrote = os.fsync, {"n": 0}

    def fsync(fd):
        real(fd)
        temps = [p for p in box.claude_code.parent.iterdir() if p.name.endswith(".tmp")]
        if temps and not wrote["n"]:                     # the fixer's own file, flushed
            wrote["n"] = 1
            doc = json.loads(box.claude_code.read_text(encoding="utf-8"))
            doc["numStartups"] = 2
            _write_json(box.claude_code, doc)
    monkeypatch.setattr(os, "fsync", fsync)
    [r] = _fix([item], install, m, box)
    assert wrote["n"] == 1 and r.fixed
    doc = json.loads(box.claude_code.read_text(encoding="utf-8"))
    assert doc["numStartups"] == 2, "Claude's change kept"
    assert doc["mcpServers"]["moonglade"]["args"][-1] == "moonglade.mcp_server", "and the fix"
    assert _beside(box.claude_code) == [".claude.json"]


def test_a_drive_less_name_is_another_folder_s_or_said_never_guessed(install, box):
    """On Windows a name rooted without a drive is on whatever drive Claude starts on. In
    another folder it is another install's, left alone; in this install's own folder it is
    reported, never rewritten on a guess about the drive."""
    here = ntpath.splitdrive(str(install))[1]
    _write_json(box.claude_desktop, {"mcpServers": {"moonglade": {
        "command": "python", "args": [here + "2\\moonglade_mcp.py"]}}})
    m = machine(box)
    assert outside.find(install, m, kinds=("claude",)) == []
    if ntpath.splitdrive(str(install))[0]:               # an install on a drive (Windows)
        _write_json(box.claude_desktop, {"mcpServers": {"moonglade": {
            "command": "python", "args": [here + "\\moonglade_mcp.py"]}}})
        before = box.claude_desktop.read_bytes()
        [r] = _fix(outside.find(install, m, kinds=("claude",)), install, m, box)
        assert not r.fixed and "which drive" in r.reason
        assert box.claude_desktop.read_bytes() == before


def test_off_windows_a_folder_differing_only_in_case_is_another_install(box):
    """On Linux /opt/moonglade and /opt/Moonglade are two folders: the fixer for one never
    rewrites the other's registration."""
    other = {"command": "python3", "args": ["/opt/moonglade/moonglade_mcp.py"]}
    assert outside.rewrite_mcp_server(other, "/opt/Moonglade", PY, "linux") is None
    mine = outside.rewrite_mcp_server(
        {"command": "python3", "args": ["/opt/Moonglade/moonglade_mcp.py"]},
        "/opt/Moonglade", PY, "linux")
    assert mine.new["env"]["PYTHONPATH"] == "/opt/Moonglade"
    assert outside.rewrite_mcp_server(other, "/opt/Moonglade", PY, "win32") is not None, \
        "on Windows the two are one folder"


def test_off_windows_only_the_claude_configs_are_looked_at(install, box):
    st = FakeSchtasks(_tasks(install))
    write_lnk(box.desktop / "Moonglade Athenaeum.lnk", target=str(install / "Serve Gallery.pyw"))
    _write_json(box.claude_code, {"mcpServers": {"moonglade": _mcp(install)}})
    m = machine(box, platform="linux", tasks=st)
    found = outside.find(install, m)
    assert [i.kind for i in found] == ["claude"]
    assert st.calls == []
    _fix(found, install, m, box)
    env = json.loads(box.claude_code.read_text(encoding="utf-8"))["mcpServers"]["moonglade"]["env"]
    assert env["PYTHONPATH"] == str(install)
    assert outside.repoint_shortcuts(install, m, box.snapshot, box.icons) == []


# ---- shortcuts --------------------------------------------------------------------------------

def _app_shortcut(box, install, icon_folder="_container_cache\\marks", folder=None):
    ico = install / icon_folder.replace("\\", os.sep) / "mark_4.ico"
    ico.parent.mkdir(parents=True, exist_ok=True)
    ico.write_bytes(b"\x00\x00\x01\x00ICON")
    return write_lnk((folder or box.desktop) / "Moonglade Athenaeum.lnk",
                     target=r"C:\Python311\pythonw.exe",
                     args='"%s\\Serve Gallery.pyw"' % install, workdir=str(install),
                     icon=str(ico), name="Moonglade Athenaeum")


def test_the_lnk_reader_reads_what_was_written(install):
    data = build_lnk(r"C:\Python311\pythonw.exe", args='"x y.pyw"', workdir=r"C:\app",
                     icon=r"C:\app\i.ico", icon_index=2, name="n", idlist=b"\x02\x00")
    lnk = outside.parse_lnk(data)
    assert (lnk.target, lnk.args, lnk.workdir, lnk.icon, lnk.icon_index) == (
        r"C:\Python311\pythonw.exe", '"x y.pyw"', r"C:\app", r"C:\app\i.ico", 2)
    assert outside.parse_lnk(b"not a shortcut") is None
    assert outside.parse_lnk(data[:90]) is None


def test_the_apps_old_desktop_shortcut_is_re_pointed_target_and_icon(install, box):
    lnk = _app_shortcut(box, install)
    original = lnk.read_bytes()
    save = SavedLnk()
    m = machine(box, save=save)
    found = outside.find(install, m, kinds=("shortcut",))
    assert [(i.label, i.auto) for i in found] == [
        ("the shortcut “Moonglade Athenaeum” on your Desktop", True)]
    [r] = _fix(found, install, m, box)
    assert r.fixed, r.reason
    [s] = save.saved
    assert s["args"] == '"%s\\Moonglade Launcher.pyw"' % install
    assert s["target"] is None and s["workdir"] is None, "only what changes is written"
    assert s["icon"] == "%s,0" % (box.icons / "mark_4.ico")
    assert (box.icons / "mark_4.ico").read_bytes() == b"\x00\x00\x01\x00ICON"
    now = outside.read_lnk(lnk)
    assert now.args == '"%s\\Moonglade Launcher.pyw"' % install
    assert now.icon == str(box.icons / "mark_4.ico")
    [snap] = _snapshots(box)
    assert (box.snapshot / snap).read_bytes() == original
    assert sorted(p.name for p in box.desktop.iterdir()) == ["Moonglade Athenaeum.lnk"]
    assert outside.find(install, m, kinds=("shortcut",)) == []


def test_a_send_to_shortcut_in_a_start_menu_folder_is_found(install, box):
    write_lnk(box.programs / "Moonglade" / "Moonglade.lnk",
              target=str(install / "Serve Gallery.pyw"))
    save = SavedLnk()
    m = machine(box, save=save)
    [item] = outside.find(install, m, kinds=("shortcut",))
    assert item.label == "the shortcut “Moonglade” in your Start menu"
    [r] = _fix([item], install, m, box)
    assert r.fixed and save.saved[0]["target"] == str(install / "Moonglade Launcher.pyw")


def test_shortcuts_to_other_things_are_left_alone(install, box):
    write_lnk(box.desktop / "Other.lnk", target=r"C:\Program Files\Other\other.exe")
    write_lnk(box.desktop / "Other install.lnk", target=r"C:\Python311\pythonw.exe",
              args='"D:\\Moonglade\\Serve Gallery.pyw"', icon=r"D:\Moonglade\_container_cache\x.ico")
    write_lnk(box.desktop / "New.lnk", target=r"C:\Python311\pythonw.exe",
              args='"%s\\Moonglade Launcher.pyw"' % install,
              icon=str(box.icons / "mark_4.ico"))
    (box.desktop / "notes.txt").write_text("not a shortcut")
    (box.desktop / "Broken.lnk").write_bytes(b"garbage")
    assert outside.find(install, machine(box), kinds=("shortcut",)) == []


def test_an_icon_only_in_an_old_cache_is_moved_to_the_icons_folder(install, box):
    ico = install / "local" / "cache" / "marks" / "mark_2.ico"
    ico.parent.mkdir(parents=True)
    ico.write_bytes(b"ICO2")
    write_lnk(box.taskbar / "Moonglade Athenaeum.lnk", target=r"C:\Python311\pythonw.exe",
              args='"%s\\Moonglade Launcher.pyw"' % install, icon=str(ico))
    save = SavedLnk()
    m = machine(box, save=save)
    [item] = outside.find(install, m, kinds=("shortcut",))
    assert not item.auto and item.label.endswith("pinned to your taskbar"), \
        "S7: an icon-only fault is offered in the notice, not fixed at every start"
    assert outside.repoint_shortcuts(install, m, box.snapshot, box.icons) == []
    [r] = _fix([item], install, m, box)
    assert r.fixed and save.saved[0]["icon"] == "%s,0" % (box.icons / "mark_2.ico")
    assert save.saved[0]["target"] is None and save.saved[0]["args"] is None \
        and save.saved[0]["workdir"] is None, "S7: only the icon is written"
    assert outside.read_lnk(box.taskbar / "Moonglade Athenaeum.lnk").args == \
        '"%s\\Moonglade Launcher.pyw"' % install


def test_an_icon_only_shortcut_whose_icon_is_gone_is_not_offered(install, box):
    """Its target is right and its icon is already blank: nothing is there to move, so it is
    not put to the owner as something to fix (it could only ever fail again)."""
    write_lnk(box.desktop / "M.lnk", target=r"C:\Python311\pythonw.exe",
              args='"%s\\Moonglade Launcher.pyw"' % install,
              icon=str(install / "_container_cache" / "marks" / "gone.ico"))
    assert outside.find(install, machine(box), kinds=("shortcut",)) == []


def test_an_icon_the_move_already_brought_into_local_icons_is_re_pointed(install, box):
    """The move copies the old cache's .ico files into local\\icons\\ and then deletes the
    cache (moonglade.migrate's install half), so a shortcut whose only fault is its icon names
    a file that is gone -- but its copy is in local\\icons\\, and Fix points it there (the
    notice offers it; the launcher's pass leaves an icon-only fault alone, S7)."""
    (box.icons / "mark_3.ico").parent.mkdir(parents=True, exist_ok=True)
    (box.icons / "mark_3.ico").write_bytes(b"ICO3")
    write_lnk(box.desktop / "M.lnk", target=r"C:\Python311\pythonw.exe",
              args='"%s\\Moonglade Launcher.pyw"' % install,
              icon=str(install / "_container_cache" / "marks" / "mark_3.ico"))
    save = SavedLnk()
    m = machine(box, save=save)
    assert outside.repoint_shortcuts(install, m, box.snapshot, box.icons) == []
    results = _fix(outside.find(install, m, kinds=("shortcut",), icons=box.icons),
                   install, m, box)
    assert [r.fixed for r in results] == [True]
    assert save.saved[0]["icon"] == "%s,0" % (box.icons / "mark_3.ico")
    assert save.saved[0]["args"] is None


def test_an_icon_already_gone_is_offered_from_the_app_when_it_can(install, box):
    write_lnk(box.desktop / "M.lnk", target=r"C:\Python311\pythonw.exe",
              args='"%s\\Serve Gallery.pyw"' % install,
              icon=str(install / "_container_cache" / "marks" / "mark_7.ico"))
    save = SavedLnk()
    m = machine(box, save=save)
    [item] = outside.find(install, m, kinds=("shortcut",))
    asked = []
    [r] = _fix([item], install, m, box,
               provide_icon=lambda stem: (asked.append(stem), b"FROMPACK")[1])
    assert r.fixed and asked == ["mark_7"]
    assert save.saved[0]["args"] == '"%s\\Moonglade Launcher.pyw"' % install
    assert (box.icons / "mark_7.ico").read_bytes() == b"FROMPACK"


def test_an_icon_that_cannot_be_had_is_left_as_it_was_and_the_target_still_fixed(install, box):
    old_icon = str(install / "_container_cache" / "marks" / "mark_9.ico")
    write_lnk(box.desktop / "M.lnk", target=r"C:\Python311\pythonw.exe",
              args='"%s\\Serve Gallery.pyw"' % install, icon=old_icon)
    save = SavedLnk()
    m = machine(box, save=save)
    [r] = _fix(outside.find(install, m, kinds=("shortcut",)), install, m, box)
    assert r.fixed and save.saved[0]["icon"] is None
    assert outside.read_lnk(box.desktop / "M.lnk").icon == old_icon


def test_a_folder_windows_refuses_is_reported_and_the_shortcut_kept(install, box):
    lnk = _app_shortcut(box, install, folder=box.common)
    before = lnk.read_bytes()
    m = machine(box, save=SavedLnk(refuse=PermissionError(13, "Access is denied")))
    [item] = outside.find(install, m, kinds=("shortcut",))
    assert item.label.endswith("in the Start menu for all users")
    [r] = _fix([item], install, m, box)
    assert not r.fixed and "administrator" in r.reason
    assert lnk.read_bytes() == before
    assert sorted(p.name for p in box.common.iterdir()) == ["Moonglade Athenaeum.lnk"]
    assert _snapshots(box) == [], "S7: a refusal leaves no copy behind either"


def test_the_launchers_pass_never_tries_a_shortcut_this_user_cannot_change(install, box,
                                                                          monkeypatch):
    """S7: an all-users shortcut without administrator rights is not tried again at every
    start (nor copied into the snapshot each time): the notice still offers it."""
    _app_shortcut(box, install, folder=box.common)
    save = SavedLnk()
    m = machine(box, save=save)
    monkeypatch.setattr(outside, "_may_change", lambda path: False)
    assert outside.repoint_shortcuts(install, m, box.snapshot, box.icons) == []
    assert save.saved == [] and _snapshots(box) == []
    assert [i.label for i in outside.find(install, m, kinds=("shortcut",))] == [
        "the shortcut “Moonglade Athenaeum” in the Start menu for all users"]


def test_the_launchers_pass_sweeps_a_temp_a_killed_save_left(install, box):
    import time
    stale = box.desktop / ".Moonglade Athenaeum.moonglade-0123abcd.lnk"
    stale.write_bytes(b"half a shortcut")
    old = time.time() - 3600
    os.utime(stale, (old, old))
    fresh = box.desktop / ".Moonglade Athenaeum.moonglade-89abcdef.lnk"
    fresh.write_bytes(b"a save in progress")
    mine = box.desktop / ".hidden.lnk"
    mine.write_bytes(b"not ours")
    os.utime(mine, (old, old))
    outside.repoint_shortcuts(install, machine(box), box.snapshot, box.icons)
    assert not stale.exists() and fresh.exists() and mine.exists()


def test_the_launchers_pass_takes_only_shortcuts_whose_old_target_is_gone(install, box):
    """S7: only a shortcut that starts this install's old launcher, now gone. One naming
    another old file (here still present, and one gone) waits for the notice's Fix."""
    _app_shortcut(box, install)
    write_lnk(box.programs / "Old CLI.lnk", target=PY,
              args='"%s\\moonglade_backup.py" --sync' % install)
    write_lnk(box.programs / "Old server.lnk", target=PY,
              args='"%s\\moonglade_gallery.py"' % install)
    (install / "moonglade_backup.py").write_text("# still here, somehow\n")
    save = SavedLnk()
    m = machine(box, save=save)
    results = outside.repoint_shortcuts(install, m, box.snapshot, box.icons)
    assert [r.label for r in results] == ["the shortcut “Moonglade Athenaeum” on your Desktop"]
    assert len(save.saved) == 1
    assert os.path.dirname(save.saved[0]["path"]) == str(box.desktop)
    assert outside.read_lnk(box.programs / "Old CLI.lnk").args.endswith("moonglade_backup.py\" --sync")


def test_the_launchers_pass_never_asks_about_tasks_or_claude(install, box):
    st = FakeSchtasks(_tasks(install))
    _write_json(box.claude_desktop, {"mcpServers": {"moonglade": _mcp(install)}})
    before = box.claude_desktop.read_bytes()
    m = machine(box, tasks=st)
    assert outside.repoint_shortcuts(install, m, box.snapshot, box.icons) == []
    assert st.calls == [] and box.claude_desktop.read_bytes() == before


@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("powershell"),
                    reason="Windows' own shortcut writer")
def test_windows_own_shortcut_writer_round_trips(install, box):
    """The real writer (PowerShell's WScript.Shell, as the app's shortcut button uses) on a
    shortcut Windows itself made, in this test's temp folder only."""
    lnk = box.desktop / "Moonglade Athenaeum.lnk"
    ico = install / "_container_cache" / "marks" / "mark_4.ico"
    ico.parent.mkdir(parents=True)
    ico.write_bytes(b"\x00\x00\x01\x00ICON")

    def q(s):
        return "'" + str(s).replace("'", "''") + "'"
    ps = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut(%s); $s.TargetPath = %s; "
          "$s.Arguments = %s; $s.WorkingDirectory = %s; $s.IconLocation = %s; $s.Save()" % (
              q(lnk), q(sys.executable), q('"%s\\Serve Gallery.pyw"' % install), q(install),
              q(str(ico) + ",0")))
    # stdin=DEVNULL: a run with no console (an agent's shell) can hand this process a
    # standard-input handle Windows will not duplicate, and a child that inherits it fails
    # to start with "the handle is invalid" (seen 2026-10-07: DuplicateHandle refused it
    # under pytest's capture before any other test had run). The child needs no input.
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                   check=True, capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
    made = outside.read_lnk(lnk)
    assert made.args == '"%s\\Serve Gallery.pyw"' % install
    assert ntpath.normcase(made.target) == ntpath.normcase(sys.executable)
    m = outside.Machine(platform="win32", shortcut_folders=[(box.desktop, "on your Desktop",
                                                             False)], python=PY)
    [r] = _fix(outside.find(install, m, kinds=("shortcut",)), install, m, box)
    assert r.fixed, r.reason
    now = outside.read_lnk(lnk)
    assert now.args == '"%s\\Moonglade Launcher.pyw"' % install
    assert ntpath.normcase(now.icon) == ntpath.normcase(str(box.icons / "mark_4.ico"))
    assert sorted(p.name for p in box.desktop.iterdir()) == ["Moonglade Athenaeum.lnk"]


@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("powershell"),
                    reason="Windows' own shortcut writer")
def test_a_crafted_shortcut_argument_is_saved_as_text_never_run(install, box, tmp_path):
    """E, for real: arguments carried over from a shortcut that try to break out of the
    writer's script (a quote, a typographic quote, `; New-Item ...`) are saved verbatim, and
    nothing they name happens. Only this test's temp folder is written."""
    marker = tmp_path / "ran.txt"
    assert " " not in str(marker)                       # a bare path: no quote to double
    crafted = '"%s\\Serve Gallery.pyw" x’; New-Item -ItemType File -Path %s; ‘' % (
        install, marker)
    lnk = box.desktop / "Crafted.lnk"
    lnk.write_bytes(build_lnk(sys.executable, args="placeholder"))
    outside._save_lnk_with_powershell(lnk, None, crafted, None, None)
    assert not marker.exists(), "nothing in the argument ran"
    assert outside.read_lnk(lnk).args == crafted


# ---- words and the guard ----------------------------------------------------------------------

def test_the_notice_and_the_result_are_plain_words():
    items = [outside.Item("task", "\\A", "the scheduled task “A”", {}),
             outside.Item("claude", "c", "Claude Desktop's Moonglade tools", {})]
    title, msg = outside.notice_words(items)
    assert title == "Some things outside Moonglade still use its old file names."
    assert msg == ("They are the scheduled task “A” and Claude Desktop's Moonglade tools. "
                   "Press Fix them to point them at the new names.")
    assert outside.fix_label(items) == "Fix them"
    title, msg = outside.notice_words(items[:1])
    assert title == "The scheduled task “A” still uses Moonglade's old file names."
    assert msg == "Press Fix it to point it at the new names."
    assert outside.fix_label(items[:1]) == "Fix it"
    ok = [outside.Result("the scheduled task “A”", True)]
    assert outside.result_words(ok) == (
        "ok", "Fixed.", "The scheduled task “A” now uses the new names.")
    mixed = ok + [outside.Result("Claude Desktop's Moonglade tools", False,
                                 "its config couldn't be written (in use or not allowed)")]
    kind, title, msg = outside.result_words(mixed)
    assert (kind, title) == ("err", "Some couldn't be fixed.")
    assert msg == ("Fixed the scheduled task “A”. Couldn't fix Claude Desktop's Moonglade "
                   "tools: its config couldn't be written (in use or not allowed).")
    assert outside.result_words([])[0] == "ok"
    claude = [outside.Result("Claude Desktop's Moonglade tools", True,
                             note="Restart Claude to use it.")]
    assert outside.result_words(claude) == (
        "ok", "Fixed.", "Claude Desktop's Moonglade tools now uses the new names. "
                        "Restart Claude to use it.")


def test_no_test_can_reach_the_real_machine():
    with pytest.raises(RuntimeError, match="real machine"):
        outside.machine()
    with pytest.raises(RuntimeError, match="real machine"):
        outside.find()
