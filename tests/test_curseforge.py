import hashlib

import pytest

import mcsync as m


def cf_file(file_id, name, content, dependencies=None):
    return {
        "id": file_id,
        "fileName": name,
        "fileLength": len(content),
        "displayName": name,
        "hashes": [{"algo": 1, "value": hashlib.sha1(content).hexdigest()}],
        "dependencies": dependencies or [],
    }


class FakeCurseForgeClient:
    def __init__(self, files):
        self.files = files
        self.latest_calls = []
        self.download_calls = []

    def latest_file(self, project_id, inst, project_type):
        self.latest_calls.append((project_id, project_type))
        return self.files[project_id]

    def download_url(self, project_id, file_id):
        self.download_calls.append((project_id, file_id))
        return f"https://cdn.example/{file_id}"


def test_search_uses_local_key_and_filters_game_and_loader(monkeypatch, store, inst):
    inst = store.update(inst.id, loader="fabric")
    with m.CurseForgeClient(" personal-key ") as client:
        calls = []

        def fetch_json(session, url, **kwargs):
            calls.append((session, url, kwargs))
            return {"data": [{"id": 15, "name": "Example", "summary": "A mod", "downloadCount": 9}]}

        monkeypatch.setattr(m, "fetch_json", fetch_json)
        hits = client.search("  example  ", "mod", inst)

    assert hits[0]["provider"] == "curseforge" and hits[0]["project_id"] == 15
    _, url, kwargs = calls[0]
    assert url == "https://api.curseforge.com/v1/mods/search"
    assert kwargs["headers"]["x-api-key"] == "personal-key"
    assert kwargs["params"]["gameId"] == m.CURSEFORGE_GAME_ID
    assert kwargs["params"]["gameVersion"] == inst.minecraft
    assert kwargs["params"]["modLoaderType"] == m.CURSEFORGE_LOADER_IDS["fabric"]
    assert kwargs["params"]["searchFilter"] == "example"


def test_install_adds_required_dependencies_and_never_sends_api_session_to_cdn(
        store, inst, monkeypatch):
    inst = store.update(inst.id, loader="fabric", loader_version="0.16.14")
    files = {
        101: cf_file(1001, "root.jar", b"root", [
            {"modId": 102, "relationType": 3},
            {"modId": 103, "relationType": 2},
        ]),
        102: cf_file(1002, "dependency.jar", b"dependency"),
        103: cf_file(1003, "optional.jar", b"optional"),
    }
    client = FakeCurseForgeClient(files)
    contents = {1001: b"root", 1002: b"dependency"}
    downloads = []

    def download(url, target, **kwargs):
        file_id = int(url.rsplit("/", 1)[-1])
        downloads.append(kwargs)
        assert url.startswith("https://")
        assert kwargs.get("session") is None
        assert kwargs["sha1"] == hashlib.sha1(contents[file_id]).hexdigest()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents[file_id])

    monkeypatch.setattr(m, "download_file", download)
    titles = m.install_curseforge(inst, 101, "mod", "secret", title="Root", client=client)

    assert len(titles) == 2
    assert (inst.game_dir / "mods/root.jar").read_bytes() == b"root"
    assert (inst.game_dir / "mods/dependency.jar").read_bytes() == b"dependency"
    assert not (inst.game_dir / "mods/optional.jar").exists()
    tracker = m.read_json(inst.directory / "curseforge.json")
    assert set(tracker) == {"101", "102"}
    assert client.latest_calls == [(101, "mod"), (102, "mod")]
    assert len(downloads) == 2


def test_install_preserves_disabled_state_when_file_name_changes(store, inst, monkeypatch):
    inst = store.update(inst.id, loader="fabric")
    old = b"old"
    put = inst.game_dir / "mods/old.jar.disabled"
    put.parent.mkdir(parents=True)
    put.write_bytes(old)
    m.atomic_json(inst.directory / "curseforge.json", {
        "101": {"project_id": 101, "file_id": 1, "title": "Old", "project_type": "mod",
                "path": "mods/old.jar", "sha1": hashlib.sha1(old).hexdigest()}
    })
    new = cf_file(2, "new.jar", b"new")
    client = FakeCurseForgeClient({101: new})

    def download(url, target, **kwargs):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"new")

    monkeypatch.setattr(m, "download_file", download)
    m.install_curseforge(inst, 101, "mod", "secret", client=client)
    assert not (inst.game_dir / "mods/old.jar.disabled").exists()
    assert (inst.game_dir / "mods/new.jar.disabled").read_bytes() == b"new"
    assert not (inst.game_dir / "mods/new.jar").exists()


def test_owned_client_closes_when_tracker_json_is_corrupt(monkeypatch, inst):
    class ClosableClient:
        closed = False

        def __exit__(self, *args):
            self.closed = True

    client = ClosableClient()
    monkeypatch.setattr(m, "CurseForgeClient", lambda _key: client)
    (inst.directory / "curseforge.json").write_text("{", encoding="utf-8")

    with pytest.raises(m.UserError, match="Повреждён"):
        m.install_curseforge(inst, 101, "resourcepack", "secret")
    assert client.closed
