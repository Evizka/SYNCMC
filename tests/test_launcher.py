import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

import mcsync as m


def test_version_flag_reports_current_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        m.main(["--version"])
    assert exit_info.value.code == 0
    assert "MCSync 0.5.5" in capsys.readouterr().out


@pytest.mark.parametrize("library", ["libGL.so.1", "libEGL.so.1"])
def test_missing_linux_opengl_runtime_has_an_actionable_package_hint(library):
    message = m.qt_runtime_message(f"{library}: cannot open shared object file", platform="linux")
    assert "Не удалось загрузить PySide6" in message
    assert "apt install libgl1 libegl1" in message
    assert "dnf install mesa-libGL mesa-libEGL" in message


def test_other_qt_import_failures_point_to_the_linux_dependency_instructions():
    message = m.qt_runtime_message("libxcb-cursor.so.0 is missing", platform="linux")
    assert "README.md" in message and "sudo apt install libgl1 libegl1" not in message


def test_startup_reports_platform_appropriate_fix_for_qt_failure(monkeypatch, capsys):
    monkeypatch.setattr(m, "QT_AVAILABLE", False)
    monkeypatch.setattr(m, "QT_IMPORT_ERROR", "libGL.so.1: cannot open shared object file")
    assert m.main(["--smoke-test"]) == 1
    output = capsys.readouterr().err
    assert "libGL.so.1" in output and "PySide6" in output
    if m.sys.platform == "linux":
        assert "sudo apt install libgl1 libegl1" in output
        assert "sudo dnf install mesa-libGL mesa-libEGL" in output
    else:
        assert "requirements.txt" in output


def test_offline_uuid_and_accounts_roundtrip(store):
    accounts = m.Accounts(store)
    account = accounts.add_offline("Player")
    assert account["id"] == "a01e3843e5213998958af459800e4d11"  # Java's OfflinePlayer:Player UUID
    assert m.Accounts(store).selected()["name"] == "Player"
    with pytest.raises(m.UserError):
        accounts.add_offline("Bad nickname!")
    accounts.remove(account["id"])
    assert accounts.selected() is None


@pytest.mark.parametrize("value", ["", "https://host/short", "ftp://host/" + "x" * 24,
                                     "http://user:pass@host/" + "x" * 24,
                                     "http://host/" + "x" * 24 + "?query=1",
                                     "http://host:invalid/" + "x" * 24,
                                     "http://host/" + "x" * 24 + "/extra"])
def test_share_url_validation(value):
    with pytest.raises(m.UserError):
        m.normalize_sync_url(value)


@pytest.mark.parametrize("server,expected", [
    ("play.example.org", ("play.example.org", "25565")),
    ("192.168.1.3:25566", ("192.168.1.3", "25566")),
    ("[::1]:25567", ("::1", "25567")), ("", ("", "")),
])
def test_server_parsing(server, expected):
    assert m.parse_server(server) == expected


@pytest.mark.parametrize("server", ["host:bad", "host/path", "user@host", "host?query", "host:99999"])
def test_invalid_server(server):
    with pytest.raises(m.UserError):
        m.parse_server(server)


@pytest.mark.parametrize("text,expected", [("-Dname=\"two words\" -XX:+UseG1GC", ["-Dname=two words", "-XX:+UseG1GC"]),
                                           ("", [])])
def test_jvm_argument_parsing(text, expected):
    assert m.split_args(text) == expected
    with pytest.raises(m.UserError):
        m.split_args('-Dname="not closed')


@pytest.mark.parametrize("version,major", [("1.8.0_431", 8), ("17.0.16", 17), ("21.0.8", 21)])
def test_java_executable_check(monkeypatch, version, major):
    def run(command, **kwargs):
        assert command == ["chosen-java", "-version"]
        assert kwargs["timeout"] == 15
        return subprocess.CompletedProcess(command, 0, "", f'openjdk version "{version}"\n')
    monkeypatch.setattr(m.subprocess, "run", run)
    assert m.java_major_version("chosen-java") == major


def test_library_http_facade_has_timeouts(monkeypatch):
    called = {}
    monkeypatch.setattr(m.requests, "get", lambda url, **kwargs: called.update(kwargs))
    m.LibraryRequests().get("https://example.org")
    assert called["timeout"] == m.TIMEOUT


def fake_library(store, put, calls, loader_id):
    java = put(store.root, "fake-java", b"java")
    def install_mc(version, directory, callback=None):
        calls.append(("minecraft", version))
        put(directory, f"versions/{version}/{version}.json", b"{}")
    def install_loader(mc, directory, **kwargs):
        calls.append((loader_id, mc, kwargs["loader_version"], kwargs["java"]))
        version = f"{loader_id}-{kwargs['loader_version']}"
        put(directory, f"versions/{version}/{version}.json", b"{}")
        return version
    loader = SimpleNamespace(get_loader_versions=lambda mc, stable: ["21.1.234"],
                             get_installed_version=lambda mc, v: f"{loader_id}-{v}", install=install_loader)
    return SimpleNamespace(
        mod_loader=SimpleNamespace(get_mod_loader=lambda lid: loader),
        install=SimpleNamespace(install_minecraft_version=install_mc),
        runtime=SimpleNamespace(get_version_runtime_information=lambda v, d: {"name": "java-runtime-delta", "javaMajorVersion": 21},
                                get_executable_path=lambda c, d: str(java),
                                install_jvm_runtime=lambda *a, **kw: calls.append(("java",))))


@pytest.mark.parametrize("loader", ["fabric", "quilt", "forge", "neoforge"])
def test_install_pins_loader_and_reuses_completed_installation(store, inst, put, monkeypatch, loader):
    inst = store.update(inst.id, loader=loader)
    calls = []
    library = fake_library(store, put, calls, loader)
    monkeypatch.setattr(m, "launcher_lib", lambda: library)
    updated, version, java = m.ensure_install(store, inst)
    assert updated.loader_version == "21.1.234"
    assert store.load(inst.id).loader_version == "21.1.234"
    assert (loader, inst.minecraft, "21.1.234", java) in calls
    before = list(calls)
    m.ensure_install(store, store.load(inst.id))
    assert calls == before  # completed installation can start without an installer network round-trip
    m.ensure_install(store, store.load(inst.id), repair=True)
    assert len(calls) > len(before)


def test_minecraft_command_ram_and_quickplay(store, inst, monkeypatch):
    inst = store.update(inst.id, minecraft="1.21.1", jvm_args='-Xmx999M -Dname="two words"', server="play.example.org:25566")
    captured = {}
    def command(version, directory, options):
        captured.update(options)
        return [options["executablePath"], "Minecraft"]
    monkeypatch.setattr(m, "launcher_lib", lambda: SimpleNamespace(command=SimpleNamespace(get_minecraft_command=command)))
    account = {"name": "Player", "id": "a" * 32, "type": "offline"}
    assert m.minecraft_command(store, inst, "1.21.1", "java", account) == ["java", "Minecraft"]
    assert captured["jvmArguments"] == [f"-Xms{inst.ram_min}M", f"-Xmx{inst.ram_max}M", "-Dname=two words"]
    assert captured["quickPlayMultiplayer"] == "play.example.org:25566"
    assert "server" not in captured
    assert captured["gameDirectory"] == str(inst.game_dir)


def test_game_session_console_token_redaction_and_local_hooks(inst):
    inst.pre_command, inst.post_command = "echo before", "echo after"
    output, completed = [], []
    event = threading.Event()
    def finish(*args):
        completed.append(args)
        event.set()
    token = "a-private-access-token"
    session = m.GameSession(inst, [sys.executable, "-c", f"print('Minecraft says {token}')"],
                            {"access_token": token}, output.append, finish)
    session.thread.start()
    assert event.wait(10)
    session.thread.join(timeout=1)
    assert completed[0][0] == 0 and completed[0][1] > 0
    text = (inst.directory / "launcher.log").read_text()
    assert "before" in text and "after" in text
    assert token not in text and token not in "\n".join(output)
    assert "[токен скрыт]" in text


def test_microsoft_requires_own_client_id():
    with pytest.raises(m.UserError, match="Client"):
        m.MicrosoftAuth("")


def test_device_flow_slow_down_and_pending(monkeypatch):
    auth = m.MicrosoftAuth("00000000-0000-0000-0000-000000000001")
    responses = [{"error": "authorization_pending"}, {"error": "slow_down"}, {"access_token": "private"}]
    class Response:
        def __init__(self, data):
            self.data, self.ok = data, "error" not in data
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def json(self): return self.data
    class Session:
        def post(self, url, data):
            assert data["client_id"] == auth.client_id
            return Response(responses.pop(0))
    class Event:
        def __init__(self):
            self.intervals = []
        def wait(self, interval):
            self.intervals.append(interval)
            return False
    auth.session.close()
    auth.session = Session()
    monkeypatch.setattr(auth, "exchange", lambda t: {"name": "Player"})
    event = Event()
    result = auth.poll_device({"device_code": "code", "interval": 1, "expires_in": 90}, event)
    assert event.intervals == [1, 1, 6]
    assert result == {"name": "Player"}


def test_device_flow_cancellation():
    with m.MicrosoftAuth("00000000-0000-0000-0000-000000000001") as auth:
        cancel = threading.Event()
        cancel.set()
        with pytest.raises(m.Cancelled):
            auth.poll_device({"device_code": "code"}, cancel)


def test_skin_uses_only_official_texture_host():
    account = {"skins": [{"state": "ACTIVE", "url": "http://textures.minecraft.net/texture/abc"}]}
    assert m.skin_url(account) == "https://textures.minecraft.net/texture/abc"
    with pytest.raises(m.UserError):
        m.skin_url({"skins": [{"url": "https://unknown.example/skin.png"}]})
