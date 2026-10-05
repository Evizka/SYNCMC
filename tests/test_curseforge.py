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
        hits = client.search("  example  ", "mod", inst, sort="updated")

    assert hits[0]["provider"] == "curseforge" and hits[0]["project_id"] == 15
    _, url, kwargs = calls[0]
    assert url == "https://api.curseforge.com/v1/mods/search"
    assert kwargs["headers"]["x-api-key"] == "personal-key"
    assert kwargs["params"]["gameId"] == m.CURSEFORGE_GAME_ID
    assert kwargs["params"]["gameVersion"] == inst.minecraft
    assert kwargs["params"]["modLoaderType"] == m.CURSEFORGE_LOADER_IDS["fabric"]
    assert kwargs["params"]["searchFilter"] == "example"
    assert kwargs["params"]["sortField"] == 3


def test_curseforge_newest_sort_uses_released_date_field(monkeypatch):
    calls = []
    with m.CurseForgeClient("personal-key") as client:
        def fetch_json(session, url, **kwargs):
            calls.append(kwargs)
            return {"data": []}

        monkeypatch.setattr(m, "fetch_json", fetch_json)
        assert client.search("", "mod", None, sort="newest") == []
    assert calls[0]["params"]["sortField"] == 11  # ReleasedDate in the official CurseForge enum.


def test_curseforge_api_key_is_saved_in_local_settings_and_reloaded(tmp_path):
    store = m.Store(tmp_path / "profile")
    store.settings["curseforge_api_key"] = "host-private-key"
    store.save_settings()

    reopened = m.Store(tmp_path / "profile")
    assert reopened.settings["curseforge_api_key"] == "host-private-key"
    assert (reopened.root / "settings.json").is_file()


def test_catalog_icon_urls_are_limited_to_https_catalog_cdns():
    assert m.catalog_icon_url("https://cdn.modrinth.com/data/id/icon.png")
    assert m.catalog_icon_url("https://media.forgecdn.net/avatars/icon.png")
    assert not m.catalog_icon_url("http://cdn.modrinth.com/icon.png")
    assert not m.catalog_icon_url("https://evil.example/icon.png")
    assert not m.catalog_icon_url("https://cdn.modrinth.com.evil.example/icon.png")
    assert not m.catalog_icon_url("https://user:pass@cdn.modrinth.com/icon.png")


def test_catalog_icon_download_is_bounded_and_never_uses_curseforge_api_key(monkeypatch):
    url = "https://cdn.modrinth.com/data/id/icon.png"
    content = b"a small icon"
    calls = []

    class Response:
        status_code = 200

        def __init__(self):
            self.url = url
            self.headers = {"Content-Type": "image/png"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            assert chunk_size == 32 * 1024
            yield content

    class Session:
        def get(self, requested_url, **kwargs):
            calls.append((requested_url, kwargs))
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(m, "BoundedSession", Session)
    assert m.fetch_catalog_icon(url) == content
    requested_url, kwargs = calls[0]
    assert requested_url == url
    assert kwargs["allow_redirects"] is False
    assert "x-api-key" not in kwargs.get("headers", {})


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


def test_curseforge_install_downloads_and_verifies_file_before_tracking(host, store, inst):
    inst = store.update(inst.id, loader="fabric", loader_version="0.16.14")
    payload = b"host mod"

    class Client:
        def latest_file(self, project_id, instance, project_type):
            return cf_file(9001, "installed.jar", payload)

        def download_url(self, project_id, file_id):
            return host.url("127.0.0.1") + "/files/mods/a.jar"

    m.install_curseforge(inst, 900, "mod", "host-private-key", client=Client())

    installed = inst.game_dir / "mods/installed.jar"
    assert installed.read_bytes() == payload
    assert not (installed.with_suffix(".jar.part")).exists()
    tracker = m.read_json(inst.directory / "curseforge.json")
    assert tracker["900"]["sha1"] == hashlib.sha1(payload).hexdigest()


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
