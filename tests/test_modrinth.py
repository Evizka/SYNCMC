import hashlib

import pytest

import mcsync as m


def version(pid, vid, content, dependencies=None, *, kind="mod", filename=None):
    name = filename or (pid + ".jar" if kind == "mod" else pid + ".zip")
    return {"id": vid, "project_id": pid, "game_versions": ["1.20.1"], "loaders": ["fabric"],
            "files": [{"filename": name, "primary": True, "url": f"https://cdn.modrinth.com/{vid}",
                       "hashes": {"sha1": hashlib.sha1(content).hexdigest()}, "size": len(content)}],
            "dependencies": dependencies or []}


class FakeClient:
    def __init__(self, versions, kinds=None):
        self.versions_by_id = {v["id"]: v for v in versions}
        self.latest_by_project = {v["project_id"]: v for v in versions}
        self.kinds = kinds or {}
        self.session = None
        self.calls = []

    def get(self, path):
        self.calls.append(path)
        if path.startswith("/version/"):
            return self.versions_by_id[path.removeprefix("/version/")]
        pid = path.removeprefix("/project/")
        return {"id": pid, "title": pid.upper(), "project_type": self.kinds.get(pid, "mod")}

    def latest(self, pid, inst):
        return self.latest_by_project[pid]


def fake_download(monkeypatch, content, fail=None):
    def download(url, target, **kwargs):
        vid = url.rsplit("/", 1)[-1]
        if fail == vid:
            raise OSError("interrupted Modrinth download")
        data = content[vid]
        assert kwargs["sha1"] == hashlib.sha1(data).hexdigest()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    monkeypatch.setattr(m, "download_file", download)


def test_required_pinned_dependencies_installed_optional_ignored(store, inst, monkeypatch):
    inst = store.update(inst.id, loader="fabric", loader_version="0.16.14")
    root = version("root", "root-1", b"root", [
        {"dependency_type": "required", "version_id": "api-pinned", "project_id": "api"},
        {"dependency_type": "optional", "project_id": "optional"}])
    pinned = version("api", "api-pinned", b"pinned")
    latest = version("api", "api-latest", b"latest")
    client = FakeClient([pinned, latest, root])
    fake_download(monkeypatch, {"root-1": b"root", "api-pinned": b"pinned"})
    titles = m.install_modrinth(inst, "root", client=client)
    assert set(titles) == {"ROOT", "API"}
    assert (inst.game_dir / "mods/api.jar").read_bytes() == b"pinned"
    assert m.read_json(inst.directory / "modrinth.json")["api"]["version_id"] == "api-pinned"
    assert not (inst.game_dir / "mods/optional.jar").exists()


def test_dependency_cycles_terminate(store, inst, monkeypatch):
    inst = store.update(inst.id, loader="fabric")
    root = version("root", "r1", b"root", [{"dependency_type": "required", "project_id": "api"}])
    api = version("api", "a1", b"api", [{"dependency_type": "required", "project_id": "root"}])
    client = FakeClient([root, api])
    fake_download(monkeypatch, {"r1": b"root", "a1": b"api"})
    assert len(m.install_modrinth(inst, "root", client=client)) == 2


def test_dependency_failure_leaves_existing_files_and_tracker(store, inst, put, snapshot, monkeypatch):
    inst = store.update(inst.id, loader="fabric")
    put(inst.game_dir, "mods/unrelated.jar", b"keep")
    root = version("root", "r1", b"root", [{"dependency_type": "required", "project_id": "api"}])
    api = version("api", "a1", b"api")
    before = snapshot(inst.directory)
    fake_download(monkeypatch, {"r1": b"root", "a1": b"api"}, fail="a1")
    with pytest.raises(OSError):
        m.install_modrinth(inst, "root", client=FakeClient([root, api]))
    assert snapshot(inst.directory) == before


def test_updating_removes_old_filename_and_preserves_disabled_state(store, inst, put, monkeypatch):
    inst = store.update(inst.id, loader="fabric")
    put(inst.game_dir, "mods/old.jar.disabled", b"old")
    m.atomic_json(inst.directory / "modrinth.json", {"root": {"path": "mods/old.jar", "version_id": "old",
                                                             "sha1": hashlib.sha1(b"old").hexdigest()}})
    new = version("root", "new", b"new", filename="new.jar")
    fake_download(monkeypatch, {"new": b"new"})
    m.install_modrinth(inst, "root", client=FakeClient([new]))
    assert not (inst.game_dir / "mods/old.jar.disabled").exists()
    assert (inst.game_dir / "mods/new.jar.disabled").read_bytes() == b"new"
    assert not (inst.game_dir / "mods/new.jar").exists()


def test_vanilla_rejects_mod_but_accepts_resourcepack(inst, monkeypatch):
    mod = version("mod", "m1", b"mod")
    with pytest.raises(m.UserError, match="загрузчик"):
        m.install_modrinth(inst, "mod", client=FakeClient([mod]))
    pack = version("pack", "p1", b"pack", kind="resourcepack")
    fake_download(monkeypatch, {"p1": b"pack"})
    m.install_modrinth(inst, "pack", client=FakeClient([pack], {"pack": "resourcepack"}))
    assert (inst.game_dir / "resourcepacks/pack.zip").read_bytes() == b"pack"


def test_resourcepack_versions_not_filtered_by_mod_loader(store, inst, monkeypatch):
    inst = store.update(inst.id, loader="neoforge")
    with m.ModrinthClient() as client:
        captured = []
        def get(path, **params):
            captured.append((path, params))
            if path.endswith("/version"):
                return []
            return {"project_type": "resourcepack"}
        monkeypatch.setattr(client, "get", get)
        client.versions("pack", inst)
        assert captured[-1][1] == {"game_versions": '["1.20.1"]'}


def test_subscriber_cannot_install_local_mods(store, inst):
    inst = store.update(inst.id, sync_url="http://localhost:25589/" + "x" * 24)
    with pytest.raises(m.UserError, match="хост"):
        m.install_modrinth(inst, "any-project")


def test_new_modpack_not_restricted_to_existing_instances_loader(store, inst, monkeypatch):
    inst = store.update(inst.id, loader="fabric")
    with m.ModrinthClient() as client:
        captured = []
        def get(path, **params):
            captured.append((path, params))
            if path.endswith("/version"):
                return []
            return {"project_type": "modpack"}
        monkeypatch.setattr(client, "get", get)
        client.versions("neoforge-pack", inst)
        assert captured[-1][1] == {"game_versions": '["1.20.1"]'}


def test_search_sends_page_offset_and_rejects_malformed_results(monkeypatch):
    with m.ModrinthClient() as client:
        calls = []
        def get(path, **kwargs):
            calls.append(kwargs)
            return {"hits": [{"title": "Result", "project_id": "test", "project_type": "mod"}]}
        monkeypatch.setattr(client, "get", get)
        assert len(client.search("q", "mod", None, offset=30)) == 1
        assert calls[0]["offset"] == 30 and calls[0]["limit"] == 30
        assert calls[0]["index"] == "downloads"
        monkeypatch.setattr(client, "get", lambda *a, **k: {"hits": [None]})
        with pytest.raises(m.UserError, match="результаты"):
            client.search("q", "mod", None)
