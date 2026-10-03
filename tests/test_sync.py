import hashlib
import json
import os
import threading
import zipfile
from pathlib import Path

import pytest
import requests

import mcsync as m


def hash_of(content):
    return hashlib.sha1(content).hexdigest()


@pytest.mark.parametrize("path", ["../a", "/etc/passwd", "C:/a", "mods/../a", "mods\\a.jar",
                                   "mods//a.jar", "mods/a:stream", "mods/a\x00", "mods/CON.jar",
                                   "mods/nul.txt", "mods/COM1.jar", "mods/LPT9.jar", "mods/a.",
                                   "mods/a ", "mods/./a", "mods/*.jar", ""])
def test_safe_join_rejects_nonportable_paths(tmp_path, path):
    with pytest.raises(m.UserError):
        m.safe_join(tmp_path, path)


def test_safe_join_unicode_and_spaces(tmp_path):
    assert m.safe_join(tmp_path, "config/наши настройки.toml") == tmp_path / "config/наши настройки.toml"


def test_safe_join_rejects_symlink(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    link = tmp_path / "root" / "mods"
    link.parent.mkdir()
    try:
        link.symlink_to(other, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink permission unavailable")
    with pytest.raises(m.UserError):
        m.safe_join(link.parent, "mods/a.jar")
    with pytest.raises(m.UserError):
        m.iter_files(link)


@pytest.mark.parametrize("changes", [
    {"minecraft": "../../x"}, {"loader": "evil"}, {"loader": []}, {"strict": "yes"},
    {"loader": "fabric", "loader_version": "latest"},
    {"loader": "fabric", "loader_version": ""}, {"server": "host --argument"},
    {"files": [{"path": "saves/level.dat", "sha1": "a" * 40, "size": 5}]},
    {"files": [{"path": "mods/a.jar", "sha1": "wrong", "size": 5}]},
    {"files": [{"path": "mods/a.jar", "sha1": "a" * 40, "size": -1}]},
    {"files": [{"path": "mods/a.jar", "sha1": "a" * 40, "size": True}]},
    {"folders": ["saves"]}, {"folders": []},
    {"folders": ["config"], "strict": True},
])
def test_manifest_validation(manifest, changes):
    data = manifest()
    data.update(changes)
    with pytest.raises(m.UserError):
        m.validate_manifest(data)


def test_manifest_rejects_case_collisions(manifest):
    with pytest.raises(m.UserError):
        manifest({"mods/A.jar": b"a", "mods/a.jar": b"b"})


def test_manifest_rev_covers_all_sync_settings(manifest):
    base = manifest({"mods/a.jar": b"a"})
    for field, value in [("minecraft", "1.21.1"), ("loader", "fabric"),
                         ("loader_version", "0.16.14"), ("server", "example.org"), ("strict", True)]:
        changed = dict(base)
        changed[field] = value
        if changed["loader"] == "fabric":
            changed["loader_version"] = "0.16.14"
        assert m.manifest_revision(changed) != base["rev"]
    forged = dict(base, rev="f" * 40)
    assert m.validate_manifest(forged)["rev"] == base["rev"]


def test_plan_is_read_only(inst, manifest, put, snapshot):
    put(inst.game_dir, "mods/a.jar", b"old")
    before = snapshot(inst.directory)
    directories = set(inst.directory.rglob("*"))
    plan = m.build_plan(inst, manifest({"mods/a.jar": b"new", "config/a.toml": b"cfg"}, minecraft="1.21.1"))
    assert plan.version_changed and len(plan.downloads) == 2
    assert snapshot(inst.directory) == before
    assert set(inst.directory.rglob("*")) == directories
    assert inst.minecraft == "1.20.1"


def test_mods_repaired_but_user_config_preserved(inst, manifest, put):
    files = {"mods/a.jar": b"host", "config/a.toml": b"host cfg"}
    put(inst.game_dir, "mods/a.jar", b"locally changed")
    put(inst.game_dir, "config/a.toml", b"local preferences")
    m.atomic_json(inst.directory / "sync_state.json", {p: hash_of(v) for p, v in files.items()})
    plan = m.build_plan(inst, manifest(files))
    assert [item.path for item in plan.downloads] == ["mods/a.jar"]


def test_changed_host_config_replaces_and_missing_config_downloads(inst, manifest, put):
    put(inst.game_dir, "config/a.toml", b"local")
    m.atomic_json(inst.directory / "sync_state.json", {"config/a.toml": hash_of(b"previous host"),
                                                     "config/missing.toml": hash_of(b"same host")})
    plan = m.build_plan(inst, manifest({"config/a.toml": b"changed host", "config/missing.toml": b"same host"}))
    assert {item.path for item in plan.downloads} == {"config/a.toml", "config/missing.toml"}


def test_removed_files_and_strict_mods(inst, manifest, put):
    owned = {"config/removed.toml": b"cfg", "resourcepacks/removed.zip": b"pack", "mods/gone.jar": b"mod"}
    for path, data in {**owned, "mods/extra.jar": b"extra", "mods/extra.jar.disabled": b"disabled",
                       "mods/sub/extra.jar": b"nested", "mods/readme.txt": b"keep", "config/local.toml": b"keep"}.items():
        put(inst.game_dir, path, data)
    m.atomic_json(inst.directory / "sync_state.json", {p: hash_of(v) for p, v in owned.items()})
    plan = m.build_plan(inst, manifest(strict=True))
    assert set(plan.deletions) == set(owned) | {"mods/extra.jar", "mods/extra.jar.disabled", "mods/sub/extra.jar"}


@pytest.mark.parametrize("host_disabled", [False, True])
def test_host_controls_enabled_disabled_mods(inst, manifest, put, host_disabled):
    path = "mods/a.jar.disabled" if host_disabled else "mods/a.jar"
    twin = "mods/a.jar" if host_disabled else "mods/a.jar.disabled"
    put(inst.game_dir, twin, b"old")
    plan = m.build_plan(inst, manifest({path: b"new"}))
    assert [item.path for item in plan.downloads] == [path]
    assert plan.deletions == [twin]


def test_plan_detects_loader_change_and_downgrade(inst, manifest):
    inst.minecraft = "1.21.1"
    plan = m.build_plan(inst, manifest(loader="neoforge", loader_version="20.1.99"))
    assert plan.version_changed and plan.downgrade


def test_bad_state_cannot_delete_outside_game(inst, manifest, put):
    put(inst.directory, "sync_state.json", json.dumps({"../accounts.json": "a" * 40}).encode())
    with pytest.raises(m.UserError):
        m.build_plan(inst, manifest())


def test_apply_download_failure_changes_nothing(inst, manifest, put, snapshot):
    put(inst.game_dir, "mods/a.jar", b"old")
    plan = m.build_plan(inst, manifest({"mods/a.jar": b"new", "mods/b.jar": b"b"}, minecraft="1.21.1"))
    before = snapshot(inst.directory)

    def fetch(item, target):
        if item.path.endswith("b.jar"):
            raise OSError("interrupted download")
        target.write_bytes(b"new")

    with pytest.raises(OSError):
        m.apply_plan(inst, plan, fetcher=fetch)
    assert snapshot(inst.directory) == before
    assert not list(inst.directory.glob(".transaction-*"))


def test_apply_rejects_bad_hash_before_any_deletion(inst, manifest, put, snapshot):
    put(inst.game_dir, "mods/extra.jar", b"keep on failure")
    before = snapshot(inst.directory)
    plan = m.build_plan(inst, manifest({"mods/a.jar": b"abc"}, strict=True, minecraft="1.21.1"))
    with pytest.raises(m.UserError, match="Повреждённый"):
        m.apply_plan(inst, plan, fetcher=lambda f, p: p.write_bytes(b"xyz"))
    assert snapshot(inst.directory) == before


def test_apply_success_updates_metadata_after_files_and_backs_up_worlds(store, inst, manifest, put):
    put(inst.game_dir, "saves/Мир/level.dat", b"precious world")
    put(inst.game_dir, "mods/extra.jar", b"extra")
    desired = {"mods/a.jar": b"new", "config/a.toml": b"settings"}
    plan = m.build_plan(inst, manifest(desired, strict=True, minecraft="1.21.1",
                                       loader="neoforge", loader_version="21.1.234", server="play.example.org"))
    updated = m.apply_plan(inst, plan, fetcher=lambda f, p: p.write_bytes(desired[f.path]))
    assert updated.minecraft == "1.21.1" and updated.loader == "neoforge"
    assert store.load(inst.id).loader_version == "21.1.234"
    assert not (inst.game_dir / "mods/extra.jar").exists()
    assert m.read_sync_state(inst) == {p: hash_of(v) for p, v in desired.items()}
    archives = list((inst.directory / "backups").glob("*.zip"))
    assert len(archives) == 1
    with zipfile.ZipFile(archives[0]) as archive:
        assert archive.read("Мир/level.dat") == b"precious world"


def test_apply_detects_edit_after_confirmation(inst, manifest, put):
    target = put(inst.game_dir, "mods/a.jar", b"old")
    plan = m.build_plan(inst, manifest({"mods/a.jar": b"new"}))
    target.write_bytes(b"edit while downloading")
    with pytest.raises(m.UserError, match="изменился"):
        m.apply_plan(inst, plan, fetcher=lambda f, p: p.write_bytes(b"new"))
    assert target.read_bytes() == b"edit while downloading"
    assert not (inst.directory / "sync_state.json").exists()


def test_metadata_save_failure_rolls_back_files_and_state(inst, manifest, put, snapshot, monkeypatch):
    put(inst.game_dir, "mods/a.jar", b"old")
    put(inst.game_dir, "mods/extra.jar", b"extra")
    m.atomic_json(inst.directory / "sync_state.json", {"mods/a.jar": hash_of(b"old")})
    desired = {"mods/a.jar": b"new", "mods/b.jar": b"added"}
    plan = m.build_plan(inst, manifest(desired, strict=True, minecraft="1.21.1"))
    before = snapshot(inst.directory)
    real = m.atomic_json

    def fail(path, value):
        if Path(path) == inst.directory / "instance.json":
            raise OSError("disk failure")
        real(path, value)

    monkeypatch.setattr(m, "atomic_json", fail)
    with pytest.raises(OSError):
        m.apply_plan(inst, plan, fetcher=lambda f, p: p.write_bytes(desired[f.path]))
    assert snapshot(inst.directory) == before


def test_cancel_before_apply_leaves_files_unchanged(inst, manifest, snapshot):
    plan = m.build_plan(inst, manifest({"mods/a.jar": b"a"}))
    event = threading.Event()
    event.set()
    before = snapshot(inst.directory)
    with pytest.raises(m.Cancelled):
        m.apply_plan(inst, plan, cancel=event, fetcher=lambda f, p: p.write_bytes(b"a"))
    assert snapshot(inst.directory) == before


def test_crash_recovery_restores_originals_and_metadata(store, inst, put, snapshot):
    original = put(inst.game_dir, "mods/a.jar", b"old")
    before = snapshot(inst.directory)
    tx = m.FileTransaction(inst)
    put(tx.stage, "metadata/instance.json", (inst.directory / "instance.json").read_bytes())
    backup = tx.stage / "originals/mods/a.jar"
    backup.parent.mkdir(parents=True)
    os.replace(original, backup)
    put(inst.game_dir, "mods/a.jar", b"new")
    put(inst.game_dir, "mods/added.jar", b"added")
    m.atomic_json(inst.directory / "sync_state.json", {})
    m.atomic_json(tx.stage / "journal.json", {"phase": "applying", "actions": [
        {"path": "mods/a.jar", "old": hash_of(b"old"), "new": hash_of(b"new")},
        {"path": "mods/added.jar", "old": None, "new": hash_of(b"added")}],
        "metadata": {"instance.json": True, "sync_state.json": False}})
    assert m.recover_transactions(store) == 1
    assert snapshot(inst.directory) == before


def test_host_auth_allowlist_and_manifest(host, inst, put):
    put(inst.game_dir, "config/private.tmp", b"not shared")
    base = host.url("127.0.0.1")
    response = requests.get(base + "/manifest.json", timeout=5)
    assert response.status_code == 200
    assert {f["path"] for f in response.json()["files"]} == {"mods/a.jar", "config/settings.toml"}
    assert requests.get(base + "/files/mods/a.jar", timeout=5).content == b"host mod"
    assert requests.head(base + "/files/mods/a.jar", timeout=5).headers["Content-Length"] == "8"
    assert requests.get(base + "/files/config/private.tmp", timeout=5).status_code == 404
    assert requests.get(base + "/files/%2e%2e%2faccounts.json", timeout=5).status_code == 400
    assert requests.get(base + "/files/mods%2f%2e%2e%2f%2e%2e%2finstance.json", timeout=5).status_code == 400
    assert requests.get(base + "/instance.json", timeout=5).status_code == 404
    wrong = base.rsplit("/", 1)[0] + "/" + "x" * 24
    assert requests.get(wrong + "/manifest.json", timeout=5).status_code == 403


def test_host_rejects_changed_file_for_old_manifest(host, inst, put):
    manifest = host.manifest()
    digest = next(f["sha1"] for f in manifest["files"] if f["path"] == "mods/a.jar")
    put(inst.game_dir, "mods/a.jar", b"a newer mod")
    response = requests.get(host.url("127.0.0.1") + "/files/mods/a.jar",
                            headers={"If-Match": f'"{digest}"'}, timeout=5)
    assert response.status_code == 412
    assert host.manifest(force=True)["rev"] != manifest["rev"]


@pytest.mark.parametrize("mode,version_change,expected", [
    ("ask", False, 1), ("ask", True, 1), ("version", False, 0),
    ("version", True, 1), ("auto", False, 0), ("auto", True, 0)])
def test_confirmation_modes(store, inst, host, put, mode, version_change, expected):
    friend = store.create("Друг", sync_url=host.url("127.0.0.1"), sync_mode=mode)
    called = []
    confirm = lambda i, p: (called.append(p) or True, True)
    first = m.sync_instance(store, friend.id, confirm=confirm)
    assert called == []  # initial trusted installation is unattended
    assert first.instance.last_sync_rev
    put(inst.game_dir, "mods/a.jar", b"changed host mod")
    if version_change:
        store.update(inst.id, minecraft="1.21.1")
    host.manifest(force=True)
    m.sync_instance(store, friend.id, confirm=confirm)
    assert len(called) == expected
    assert (friend.game_dir / "mods/a.jar").read_bytes() == b"changed host mod"


def test_declining_version_change_does_not_mutate(store, inst, host, snapshot):
    friend = store.create("Друг", sync_url=host.url("127.0.0.1"))
    m.sync_instance(store, friend.id)
    store.update(inst.id, minecraft="1.21.1")
    host.manifest(force=True)
    before = snapshot(friend.game_dir)
    metadata = (friend.directory / "instance.json").read_bytes()
    with pytest.raises(m.Cancelled):
        m.sync_instance(store, friend.id, confirm=lambda i, p: (False, True))
    assert snapshot(friend.game_dir) == before
    assert (friend.directory / "instance.json").read_bytes() == metadata


def test_offline_uses_cache_without_deleting_or_changing_versions(store, inst, host, put, snapshot):
    friend = store.create("Друг", sync_url=host.url("127.0.0.1"))
    m.sync_instance(store, friend.id)
    store.update(inst.id, minecraft="1.21.1")
    host.manifest(force=True)
    m.fetch_manifest(store.load(friend.id))  # latest revision was fetched, not accepted
    put(friend.game_dir, "mods/local.jar", b"keep while offline")
    host.stop()
    before = snapshot(friend.game_dir)
    result = m.sync_instance(store, friend.id, allow_offline=True)
    assert result.offline and result.instance.minecraft == "1.20.1"
    assert snapshot(friend.game_dir) == before
    with pytest.raises(m.UserError, match="недоступен"):
        m.sync_instance(store, friend.id)


def test_cache_is_bound_to_exact_share_link(store, host):
    friend = store.create("Друг", sync_url=host.url("127.0.0.1"))
    m.sync_instance(store, friend.id)
    host.stop()
    store.update(friend.id, sync_url=f"http://127.0.0.1:{host.port}/" + "y" * 24)
    with pytest.raises(m.UserError, match="кеша"):
        m.fetch_manifest(store.load(friend.id))


def test_invalid_token_is_not_hidden_by_cache(store, host):
    friend = store.create("Друг", sync_url=host.url("127.0.0.1"))
    m.sync_instance(store, friend.id)
    host.token = "z" * 24
    with pytest.raises(requests.HTTPError):
        m.fetch_manifest(store.load(friend.id))


def test_download_part_verification_and_cleanup(host, tmp_path):
    target = tmp_path / "a.jar"
    target.write_bytes(b"existing")
    url = host.url("127.0.0.1") + "/files/mods/a.jar"
    with pytest.raises(m.UserError, match="SHA-1"):
        m.download_file(url, target, sha1="0" * 40, size=8)
    assert target.read_bytes() == b"existing"
    assert not (tmp_path / "a.jar.part").exists()
    m.download_file(url, target, sha1=hash_of(b"host mod"), size=8)
    assert target.read_bytes() == b"host mod"


def test_logs_redact_bearer_url():
    secret = "SuperPrivate_Token-0123456789"
    for text in [f"http://example.org:25589/{secret}/files/a", f"Connection error: 'https://example.org/{secret}'"]:
        assert secret not in m.redact(text)
    assert m.redact("http://example.org/mods/a.jar") == "http://example.org/mods/a.jar"


def test_manifest_name_not_shadowed_by_file_validation(manifest):
    result = manifest({"mods/a.jar": b"mod", "config/a.toml": b"cfg"}, name="Name of the pack")
    assert result["name"] == "Name of the pack"


def test_file_cannot_be_parent_directory_in_manifest(manifest):
    with pytest.raises(m.UserError, match="каталог"):
        manifest({"mods/a.jar": b"a", "mods/a.jar/config.toml": b"b"})


def test_case_only_host_rename_does_not_delete_the_desired_file(inst, manifest, put):
    content = b"mod"
    put(inst.game_dir, "mods/Old.jar", content)
    m.atomic_json(inst.directory / "sync_state.json", {"mods/Old.jar": hash_of(content)})
    plan = m.build_plan(inst, manifest({"mods/old.jar": content}, strict=True))
    updated = m.apply_plan(inst, plan, fetcher=lambda f, p: p.write_bytes(content))
    assert (updated.game_dir / "mods/old.jar").read_bytes() == content
    assert m.read_sync_state(updated) == {"mods/old.jar": hash_of(content)}
    # Case-insensitive filesystems may retain the original casing; that is harmless.
    assert len(list((updated.game_dir / "mods").iterdir())) == 1


def test_logs_redact_relative_urls_in_urllib3_errors():
    token = "private-share-token-0123456789"
    for endpoint in ("manifest.json", "files/mods/a.jar"):
        text = f"HTTPConnectionPool(host='host', port=25589): Max retries exceeded with url: /{token}/{endpoint}"
        assert token not in m.redact(text)
        assert "[токен скрыт]" in m.redact(text)
