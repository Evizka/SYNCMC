import json
import subprocess
import threading
import zipfile
from types import SimpleNamespace

import pytest

import mcsync as m


@pytest.mark.parametrize("value", ["broken JSON", "[]", '{"default_ram": "huge"}', '{"default_ram": true}', '{"client_id": 123}'])
def test_damaged_settings_are_recoverable_and_backed_up_before_save(tmp_path, value):
    root = tmp_path / "data"
    root.mkdir()
    original = root / "settings.json"
    original.write_text(value)
    store = m.Store(root)
    assert store.settings_error
    assert original.read_text() == value  # constructing a Store does not overwrite it
    assert store.create("Still usable").ram_max == 4096
    store.save_settings()
    backups = list((root / "recovery").glob("settings-*.json"))
    assert len(backups) == 1 and backups[0].read_text() == value
    assert not store.settings_error


def test_one_damaged_instance_does_not_block_the_library(store, inst):
    other = store.create("Damaged")
    original = b'{"id": "not-a-real-id"}'
    (other.directory / "instance.json").write_bytes(original)
    assert [i.id for i in store.list_instances()] == [inst.id]
    assert other.id in store.instance_errors
    assert (other.directory / "instance.json").read_bytes() == original


@pytest.mark.parametrize("field,value", [("playtime", float("nan")), ("playtime", float("inf")),
                                        ("last_played", -1), ("last_sync_at", 1e100),
                                        ("created_at", True), ("favorite", "yes")])
def test_invalid_clock_or_favorite_metadata_is_rejected(inst, field, value):
    setattr(inst, field, value)
    with pytest.raises(m.UserError):
        inst.validate()


def test_account_recovery_skips_bad_entries_without_losing_the_original(store):
    valid = {"id": "a" * 32, "name": "Player", "type": "offline"}
    data = {"accounts": [valid, 42, {}, {**valid, "id": "b" * 32, "expires_at": "wrong"}], "selected": "missing"}
    m.atomic_json(store.root / "accounts.json", data)
    accounts = m.Accounts(store)
    assert accounts.load_error and accounts.selected() == valid
    assert m.read_json(store.root / "accounts.json") == data
    accounts.add_offline("Another")
    backup = next((store.root / "recovery").glob("accounts-*.json"))
    assert m.read_json(backup) == data


def test_fully_corrupt_accounts_can_be_replaced_after_private_backup(store):
    (store.root / "accounts.json").write_text("broken")
    accounts = m.Accounts(store)
    assert accounts.selected() is None and accounts.load_error
    accounts.add_offline("Player")
    assert next((store.root / "recovery").glob("accounts-*.json")).read_text() == "broken"


@pytest.mark.parametrize("server", ["host:0", "host:", "host#", "host?", "host/path", "bad host"])
def test_server_typo_does_not_silently_change_the_address(server):
    with pytest.raises(m.UserError):
        m.parse_server(server)


@pytest.mark.parametrize("contents", ["broken", "[]", "null"])
def test_corrupt_installation_marker_is_reinstalled_not_an_attribute_error(store, inst, put, monkeypatch, contents):
    (inst.directory / "installed.json").write_text(contents)
    java = put(store.root, "java-test", b"test")
    calls = []
    def install(version, root, **kwargs):
        calls.append(version)
        put(root, f"versions/{version}/{version}.json", b"{}")
    library = SimpleNamespace(install=SimpleNamespace(install_minecraft_version=install),
        runtime=SimpleNamespace(get_version_runtime_information=lambda *args: {"name": "java-runtime-delta", "javaMajorVersion": 21},
                                get_executable_path=lambda *args: str(java), install_jvm_runtime=lambda *args, **kwargs: None))
    monkeypatch.setattr(m, "launcher_lib", lambda: library)
    current, version, _ = m.ensure_install(store, inst)
    assert calls == [inst.minecraft]
    assert m.read_json(inst.directory / "installed.json")["identity"] == list(current.identity)
    assert version == inst.minecraft


def test_javaw_is_normalized_to_console_java_for_hidden_windows_processes(tmp_path, monkeypatch):
    javaw, java = tmp_path / "javaw.exe", tmp_path / "java.exe"
    javaw.write_bytes(b"javaw")
    java.write_bytes(b"java")
    assert m.java_launcher_path(str(javaw)) == str(java)
    called = []
    def run(args, **kwargs):
        called.append(args)
        return subprocess.CompletedProcess(args, 0, "", 'openjdk version "21.0.8"')
    monkeypatch.setattr(m.subprocess, "run", run)
    assert m.java_major_version(str(javaw)) == 21 and called[0][0] == str(java)


def test_diagnostic_report_never_exports_tokens_sync_links_or_hooks(store):
    m.Accounts(store).put({"id": "a" * 32, "name": "Player", "type": "microsoft",
                           "access_token": "never-export-this-access", "refresh_token": "never-export-this-refresh"})
    store.create("Friend", sync_url="http://host:25589/never-export-this-sync-token",
                 pre_command="never-export-this-command")
    text = json.dumps(m.diagnostic_report(store))
    for secret in ("never-export-this-access", "never-export-this-refresh", "never-export-this-sync-token", "never-export-this-command"):
        assert secret not in text
    assert '"subscription": true' in text


def test_world_backup_cancellation_removes_partial_zip(inst, put):
    put(inst.game_dir, "saves/World/level.dat", b"a" * (3 * 1024**2))
    cancel = threading.Event()
    def progress(*args):
        cancel.set()
    with pytest.raises(m.Cancelled):
        m.backup_worlds(inst, progress=progress, cancel=cancel)
    assert not list((inst.directory / "backups").glob("*.zip"))
    assert (inst.game_dir / "saves/World/level.dat").is_file()


def test_backup_stream_reports_progress_and_is_a_valid_zip(inst, put):
    put(inst.game_dir, "saves/World/level.dat", b"data")
    updates = []
    archive = m.backup_worlds(inst, progress=lambda *args: updates.append(args))
    with zipfile.ZipFile(archive) as z:
        assert z.read("World/level.dat") == b"data"
    assert updates and updates[-1][1:] == (4, 4)


def test_rotating_game_log_has_bounded_generations(tmp_path):
    path = tmp_path / "launcher.log"
    with m.RotatingTextLog(path, max_bytes=20) as log:
        for i in range(20):
            log.write(f"line {i:02d}\n")
            log.flush()
    assert len(list(tmp_path.iterdir())) == 3
    assert all(p.stat().st_size <= 20 for p in tmp_path.iterdir())
    assert "line 19" in path.read_text()


def test_large_console_lines_are_bounded_and_still_redact_the_token(inst):
    session = m.GameSession(inst, [], {"access_token": "secret-access-token"}, lambda *a: None, lambda *a: None)
    text = session.clean("secret-access-token " + "a" * 100000)
    assert len(text) < 17000 and "secret-access-token" not in text and "сокращена" in text


def test_multiple_file_toggles_are_atomic_on_conflict(inst, put, snapshot):
    put(inst.game_dir, "mods/a.jar", b"a")
    put(inst.game_dir, "mods/b.jar", b"b")
    put(inst.game_dir, "mods/b.jar.disabled", b"conflict")
    before = snapshot(inst.directory)
    with pytest.raises(m.UserError, match="существует"):
        m.toggle_files(inst, "mods", ["a.jar", "b.jar"])
    assert snapshot(inst.directory) == before


def test_multiple_files_toggle_and_toggle_back(inst, put):
    put(inst.game_dir, "mods/a.jar", b"a")
    put(inst.game_dir, "mods/b.jar", b"b")
    m.toggle_files(inst, "mods", ["a.jar", "b.jar"])
    assert not (inst.game_dir / "mods/a.jar").exists()
    assert (inst.game_dir / "mods/a.jar.disabled").read_bytes() == b"a"
    m.toggle_files(inst, "mods", ["a.jar.disabled", "b.jar.disabled"])
    assert (inst.game_dir / "mods/b.jar").read_bytes() == b"b"


def test_linked_instance_rejects_backend_file_toggle(store, inst, put):
    put(inst.game_dir, "mods/a.jar", b"a")
    inst = store.update(inst.id, sync_url="http://host:25589/" + "x" * 24)
    with pytest.raises(m.UserError, match="хост"):
        m.toggle_files(inst, "mods", ["a.jar"])


@pytest.mark.parametrize("selected", [[], {}, 123])
def test_corrupt_selected_account_does_not_raise_typeerror(store, selected):
    valid = {"id": "a" * 32, "name": "Player", "type": "offline"}
    m.atomic_json(store.root / "accounts.json", {"accounts": [valid], "selected": selected})
    accounts = m.Accounts(store)
    assert accounts.selected() == valid and accounts.load_error


def test_legacy_short_microsoft_profile_names_are_not_lost(store):
    profile = {"id": "a" * 32, "name": "X", "type": "microsoft", "access_token": "test"}
    m.Accounts(store).put(profile)
    assert m.Accounts(store).selected() == profile


def test_client_id_must_be_a_uuid_not_thirty_six_hyphens():
    with pytest.raises(m.UserError, match="Client"):
        m.MicrosoftAuth("-" * 36)
