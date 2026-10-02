import hashlib
import json
import zipfile

import pytest

import mcsync as m


def archive_at(path, entries):
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, m.json_bytes(content) if isinstance(content, dict) else content)
    return path


def test_export_import_roundtrip_keeps_content_not_machine_secrets(store, inst, put, tmp_path):
    inst = store.update(inst.id, loader="neoforge", loader_version="20.1.123", notes="Заметки", group="Друзья",
                        sync_url="http://127.0.0.1:25589/" + "private-token-0123456789",
                        pre_command="dangerous command", post_command="another command", java="C:/Java/java.exe",
                        jvm_args="-javaagent:private.jar")
    put(inst.game_dir, "mods/a.jar", b"mod")
    put(inst.game_dir, "config/a.toml", b"cfg")
    put(inst.game_dir, "saves/Мир/level.dat", b"world")
    put(inst.game_dir, "logs/private.log", b"private")
    put(inst.directory, "accounts.json", b"secret")
    exported = m.export_pack(inst, tmp_path / "pack.zip", include_worlds=True)
    with zipfile.ZipFile(exported) as archive:
        metadata = json.loads(archive.read("mcsync-instance.json"))
        assert not {"sync_url", "pre_command", "post_command", "java", "jvm_args"} & metadata.keys()
        assert "game/logs/private.log" not in archive.namelist()
        assert not any("accounts.json" in path for path in archive.namelist())
    imported = m.import_pack(store, exported)
    assert imported.id != inst.id
    assert imported.identity == inst.identity
    assert imported.notes == "Заметки" and imported.group == "Друзья"
    assert not imported.sync_url and not imported.pre_command and not imported.jvm_args
    assert (imported.game_dir / "mods/a.jar").read_bytes() == b"mod"
    assert (imported.game_dir / "saves/Мир/level.dat").read_bytes() == b"world"


def test_mrpack_export_roundtrip_with_neoforge(store, inst, put, tmp_path):
    inst = store.update(inst.id, loader="neoforge", loader_version="20.1.99")
    put(inst.game_dir, "mods/a.jar", b"mod")
    put(inst.game_dir, "saves/world/level.dat", b"world")
    path = m.export_pack(inst, tmp_path / "pack.mrpack", mrpack=True)
    with zipfile.ZipFile(path) as archive:
        index = json.loads(archive.read("modrinth.index.json"))
        assert index["dependencies"]["neoforge"] == "20.1.99"
        assert index["files"] == []
        assert "overrides/mods/a.jar" in archive.namelist()
        assert not any("saves/" in n for n in archive.namelist())
    imported = m.import_pack(store, path)
    assert imported.identity == inst.identity
    assert (imported.game_dir / "mods/a.jar").read_bytes() == b"mod"


@pytest.mark.parametrize("uid,loader,version", [
    ("net.fabricmc.fabric-loader", "fabric", "0.16.14"),
    ("org.quiltmc.quilt-loader", "quilt", "0.29.0"),
    ("net.minecraftforge", "forge", "47.4.0"),
    ("net.neoforged", "neoforge", "21.1.234"),
])
def test_prism_polymc_import(store, tmp_path, uid, loader, version):
    source = archive_at(tmp_path / "prism.zip", {
        "MyPack/mmc-pack.json": {"formatVersion": 1, "components": [
            {"uid": "net.minecraft", "version": "1.21.1"}, {"uid": uid, "version": version}]},
        "MyPack/instance.cfg": "[General]\nname=Пак друзей\nPreLaunchCommand=never execute\n",
        "MyPack/.minecraft/mods/a.jar": b"mod", "MyPack/.minecraft/logs/a.log": b"ignore",
    })
    inst = m.import_pack(store, source)
    assert inst.name == "Пак друзей"
    assert inst.loader == loader and inst.loader_version == version
    assert not inst.pre_command
    assert (inst.game_dir / "mods/a.jar").read_bytes() == b"mod"
    assert not (inst.game_dir / "logs/a.log").exists()


def test_mrpack_overrides_and_client_environment(store, tmp_path, monkeypatch):
    index = {"formatVersion": 1, "game": "minecraft", "name": "MR pack",
             "dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.16.14"}, "files": [
                 {"path": "mods/server.jar", "env": {"client": "unsupported"}, "downloads": []},
                 {"path": "mods/client.jar", "downloads": ["https://cdn.modrinth.com/client.jar"],
                  "hashes": {"sha1": hashlib.sha1(b"client mod").hexdigest()}, "fileSize": 10}]}
    source = archive_at(tmp_path / "pack.mrpack", {
        "modrinth.index.json": index, "overrides/config/a.toml": b"common",
        "client-overrides/config/a.toml": b"client overrides", "server-overrides/config/a.toml": b"server only"})
    called = []

    def download(url, target, **kwargs):
        called.append(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"client mod")

    monkeypatch.setattr(m, "download_file", download)
    inst = m.import_pack(store, source)
    assert called == ["https://cdn.modrinth.com/client.jar"]
    assert not (inst.game_dir / "mods/server.jar").exists()
    assert (inst.game_dir / "config/a.toml").read_bytes() == b"client overrides"


@pytest.mark.parametrize("evil", ["../escape.txt", "overrides/../escape.txt", "/etc/a", "C:/a",
                                    "overrides/mods/a:stream", "overrides/config/CON.txt"])
def test_archive_traversal_is_rejected(store, tmp_path, evil):
    source = archive_at(tmp_path / "bad.zip", {
        "mcsync-instance.json": {"name": "bad", "minecraft": "1.20.1"}, evil: b"bad"})
    with pytest.raises(m.UserError):
        m.import_pack(store, source)
    assert store.list_instances() == []
    assert list(store.temp_dir.iterdir()) == []


def test_archive_symlink_rejected(store, tmp_path):
    source = tmp_path / "symlink.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("mcsync-instance.json", m.json_bytes({"name": "bad", "minecraft": "1.20.1"}))
        info = zipfile.ZipInfo("game/mods/link.jar")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        archive.writestr(info, "../../outside")
    with pytest.raises(m.UserError, match="Символические"):
        m.import_pack(store, source)
    assert store.list_instances() == []


def test_mrpack_download_failure_does_not_create_half_instance(store, tmp_path, monkeypatch):
    source = archive_at(tmp_path / "bad.mrpack", {"modrinth.index.json": {
        "formatVersion": 1, "game": "minecraft", "name": "Bad", "dependencies": {"minecraft": "1.20.1"},
        "files": [{"path": "mods/a.jar", "downloads": ["https://cdn.modrinth.com/a.jar"],
                   "hashes": {"sha1": "a" * 40}, "fileSize": 10}]}})
    monkeypatch.setattr(m, "download_file", lambda *a, **kw: (_ for _ in ()).throw(OSError("failure")))
    with pytest.raises(OSError):
        m.import_pack(store, source)
    assert store.list_instances() == []
    assert list(store.temp_dir.iterdir()) == []


def test_import_never_applies_embedded_shell_hooks(store, tmp_path):
    source = archive_at(tmp_path / "pack.zip", {"mcsync-instance.json": {
        "minecraft": "1.20.1", "name": "Untrusted", "pre_command": "execute me", "post_command": "execute me",
        "java": "/tmp/untrusted", "jvm_args": "-javaagent:untrusted", "sync_url": "http://untrusted/link"}})
    inst = m.import_pack(store, source)
    assert not any((inst.pre_command, inst.post_command, inst.java, inst.jvm_args, inst.sync_url))


def test_copy_is_disconnected_and_preserves_game_files(store, inst, put):
    inst = store.update(inst.id, sync_url="http://127.0.0.1:25589/" + "x" * 24, playtime=100)
    put(inst.game_dir, "mods/a.jar", b"mod")
    new = store.copy_instance(inst, "Независимая копия")
    assert not new.sync_url and new.playtime == 0
    assert (new.game_dir / "mods/a.jar").read_bytes() == b"mod"


def test_world_zip_root_or_single_folder(inst, tmp_path):
    source = archive_at(tmp_path / "one.zip", {"level.dat": b"world", "region/r.0.0.mca": b"region"})
    target = m.import_world(inst, source)
    assert (target / "level.dat").read_bytes() == b"world"
    source = archive_at(tmp_path / "two.zip", {"Folder/level.dat": b"world", "Folder/region/r.mca": b"region"})
    target = m.import_world(inst, source)
    assert (target / "level.dat").read_bytes() == b"world"
    with pytest.raises(m.UserError, match="существует"):
        m.import_world(inst, source)


def test_store_create_ram_override_and_bad_metadata(store):
    inst = store.create("Custom", ram_max=2048)
    assert inst.ram_max == 2048
    with pytest.raises(m.UserError):
        store.update(inst.id, notes={"not": "a string"})
    with pytest.raises(m.UserError):
        store.update(inst.id, ram_min=8000, ram_max=1000)
