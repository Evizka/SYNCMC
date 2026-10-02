"""Real HTTP party membership, persistence, privacy and reconnect regression tests."""
import copy
import hashlib
import json
import threading
import time

import pytest
import requests

import mcsync as m


def payload(identity="a" * 32, *, name="Саша", lease="b" * 64, **values):
    return {"id": identity, "lease": lease, "name": name, "state": "launcher", "rev": "", **values}


def wait_until(condition, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError("Party state did not arrive")


def subscribe(host, root, name):
    store = m.Store(root)
    store.settings["party_name"] = name
    store.save_settings()
    manifest = host.manifest()
    inst = store.create(name, minecraft=manifest["minecraft"], loader=manifest["loader"],
                        loader_version=manifest["loader_version"], sync_url=host.url("127.0.0.1"))
    return store, inst


def test_two_friends_share_one_roster_without_accounts_or_addresses(host, tmp_path):
    one, a = subscribe(host, tmp_path / "one", "Саша")
    two, b = subscribe(host, tmp_path / "two", "Ира")
    first = m.poll_party(one, a)
    second = m.poll_party(two, b, "playing")
    assert first["online"] and second["supported"]
    assert {p["name"] for p in second["room"]["members"]} == {"Хост", "Саша", "Ира"}
    assert next(p for p in second["room"]["members"] if p["name"] == "Ира")["state"] == "playing"
    assert len(m.poll_party(one, a)["room"]["members"]) == 3
    serialized = json.dumps(second["room"])
    for secret in (host.token, "lease", "lease_hash", "127.0.0.1", "accounts.json", str(tmp_path)):
        assert secret not in serialized


def test_identity_and_lease_survive_restart_but_are_different_for_other_rooms(host, tmp_path):
    store, inst = subscribe(host, tmp_path, "Имя")
    first = m.party_identity(store, inst.sync_url)
    assert m.party_identity(m.Store(store.root), inst.sync_url) == first
    other = inst.sync_url.rsplit("/", 1)[0] + "/" + "z" * 24
    assert m.party_identity(store, other)[:2] != first[:2]
    assert first[0] != first[1][:32]


def test_rejoining_after_client_restart_does_not_duplicate_a_friend(host, tmp_path):
    store, inst = subscribe(host, tmp_path, "Миша")
    m.poll_party(store, inst)
    restarted = m.Store(store.root)
    m.poll_party(restarted, restarted.load(inst.id))
    assert len(host.party.members()) == 1


def test_presence_checks_never_apply_mods_or_versions(host, tmp_path, snapshot):
    store, inst = subscribe(host, tmp_path, "Friend")
    before = snapshot(inst.directory)
    host.store.update(host.instance_id, minecraft="1.21.1")
    result = m.poll_party(store, inst)
    assert result["changed"]
    assert store.load(inst.id).minecraft == "1.20.1"
    assert snapshot(inst.directory) == before


def test_departure_and_expiry_remove_members_without_persisting_presence(host, tmp_path):
    store, inst = subscribe(host, tmp_path, "Friend")
    m.poll_party(store, inst)
    m.leave_party(store, inst)
    assert host.party.members() == []
    now = [0.0]
    directory = m.PartyDirectory(clock=lambda: now[0])
    directory.touch(payload())
    now[0] = m.PARTY_TTL - 0.01
    assert len(directory.members()) == 1
    now[0] = m.PARTY_TTL
    assert directory.members() == []


def test_another_friend_cannot_impersonate_or_remove_a_known_member(host):
    base = host.url("127.0.0.1")
    assert requests.post(base + "/party/heartbeat", json=payload(), timeout=5).status_code == 200
    for endpoint in ("heartbeat", "leave"):
        result = requests.post(base + "/party/" + endpoint, json=payload(lease="c" * 64), timeout=5)
        assert result.status_code == 409
    assert host.party.members()[0]["name"] == "Саша"


@pytest.mark.parametrize("bad", [
    {"id": "host"}, {"id": []}, {"lease": "short"}, {"state": "administrator"},
    {"state": []}, {"rev": "not a hash"}, {"name": "<img src=x>"},
    {"name": "x\ny"}, {"name": "a" * 33}, {"name": ""},
])
def test_invalid_presence_is_rejected_without_registering_a_peer(host, bad):
    result = requests.post(host.url("127.0.0.1") + "/party/heartbeat", json=payload(**bad), timeout=5)
    assert result.status_code == 400 and host.party.members() == []


def test_authentication_origin_body_limit_and_file_read_only(host):
    base = host.url("127.0.0.1")
    wrong = base.rsplit("/", 1)[0] + "/" + "z" * 24
    assert requests.post(wrong + "/party/heartbeat", json=payload(), timeout=5).status_code == 403
    assert requests.get(wrong + "/party.json", timeout=5).status_code == 403
    assert requests.post(base + "/party/heartbeat", json=payload(), headers={"Origin": "https://evil.example"}, timeout=5).status_code == 403
    assert requests.post(base + "/party/heartbeat", data=b"x" * (m.PARTY_MAX_BODY + 1), headers={"Content-Type": "application/json"}, timeout=5).status_code == 413
    assert requests.post(base + "/files/mods/a.jar", json=payload(), timeout=5).status_code == 405
    assert host.party.members() == []
    assert requests.get(base + "/files/mods/a.jar", timeout=5).content == b"host mod"


def test_roster_is_bounded_and_reusable_after_expiry():
    clock = [0.0]
    directory = m.PartyDirectory(clock=lambda: clock[0])
    for i in range(m.PARTY_MAX_MEMBERS):
        directory.touch(payload(f"{i:032x}"))
    with pytest.raises(m.UserError, match="заполнена"):
        directory.touch(payload("f" * 32))
    clock[0] = m.PARTY_TTL
    directory.touch(payload("f" * 32))
    assert len(directory.members()) == 1


@pytest.mark.parametrize("corrupt", [
    {"protocol": True}, {"protocol": 99}, {"members": []}, {"rev": "bad"},
    {"pack": {"name": "x", "minecraft": "../../outside"}},
])
def test_untrusted_roster_validation(host, corrupt):
    room = host.party_snapshot()
    with pytest.raises(m.UserError):
        m.validate_party_snapshot(room | corrupt)


def test_roster_cannot_duplicate_or_omit_the_host(host):
    room = host.party_snapshot()
    room["members"].append(copy.deepcopy(room["members"][0]))
    with pytest.raises(m.UserError):
        m.validate_party_snapshot(room)
    room["members"] = [dict(room["members"][0], id="a" * 32, role="friend")]
    with pytest.raises(m.UserError):
        m.validate_party_snapshot(room)


def test_old_host_fallback_is_online_without_inventing_friends(host, tmp_path, monkeypatch):
    store, inst = subscribe(host, tmp_path, "Friend")
    original = m.BoundedSession.post

    def old_post(session, url, **kwargs):
        response = requests.Response()
        response.status_code = 501
        response._content = b"Unsupported"
        response._content_consumed = True
        return response

    monkeypatch.setattr(m.BoundedSession, "post", old_post)
    result = m.poll_party(store, inst)
    assert result["online"] and not result["supported"] and "room" not in result
    monkeypatch.setattr(m.BoundedSession, "post", original)


def test_monitor_connects_and_keeps_playing_presence_without_manual_checks(host, tmp_path):
    store, inst = subscribe(host, tmp_path, "Friend")
    monitor = m.PartyMonitor(store, interval=0.1)
    try:
        monitor.start()
        wait_until(lambda: monitor.snapshot().get(inst.id, {}).get("online"))
        monitor.set_activity(inst.id, "playing")
        monitor.refresh()
        wait_until(lambda: any(p["state"] == "playing" for p in host.party.members()))
        assert monitor.snapshot()[inst.id]["source"] == hashlib.sha256(inst.sync_url.encode()).hexdigest()
    finally:
        monitor.stop()


def test_monitor_reconnects_to_restarted_host_with_the_same_invitation(host, tmp_path):
    store, inst = subscribe(host, tmp_path, "Friend")
    monitor = m.PartyMonitor(store, interval=0.1)
    try:
        monitor.start()
        wait_until(lambda: monitor.snapshot().get(inst.id, {}).get("online"))
        host.stop()
        monitor.refresh()
        wait_until(lambda: monitor.snapshot().get(inst.id, {}).get("online") is False)
        host.start(bind="127.0.0.1")
        monitor.refresh()
        wait_until(lambda: monitor.snapshot().get(inst.id, {}).get("online"))
        assert len(host.party.members()) == 1
    finally:
        monitor.stop()


def test_stale_success_never_stays_green_forever(store):
    monitor = m.PartyMonitor(store)
    monitor.states["id"] = {"online": True, "changed": False, "received_at": time.monotonic() - m.PARTY_TTL}
    assert monitor.snapshot()["id"]["online"] is False


def test_offline_errors_back_off_and_are_redacted(store, inst, monkeypatch):
    inst = store.update(inst.id, sync_url="http://127.0.0.1:25589/" + "a" * 24)
    monitor = m.PartyMonitor(store)
    monitor.sources[inst.id] = inst.sync_url

    def failed(*args, **kwargs):
        raise requests.ConnectionError("url: /" + "a" * 24 + "/party/heartbeat")

    monkeypatch.setattr(m, "poll_party", failed)
    for expected in (5, 10, 20, 30, 30):
        monitor._poll(inst, inst.sync_url)
        state = monitor.snapshot()[inst.id]
        assert state["online"] is False and state["retry_seconds"] == expected
        assert "a" * 24 not in state["error"]


def test_late_response_cannot_reconnect_a_removed_invitation(host, tmp_path, monkeypatch):
    store, inst = subscribe(host, tmp_path, "Friend")
    monitor = m.PartyMonitor(store)
    monitor.sources[inst.id] = inst.sync_url
    monkeypatch.setattr(m, "poll_party", lambda *args: {"online": True})
    monkeypatch.setattr(monitor, "_leave", lambda profile: None)
    monitor.forget(inst)
    monitor._poll(inst, inst.sync_url)
    assert inst.id not in monitor.snapshot()


def test_host_restores_saved_room_and_secret_but_not_legacy_unapproved_servers(host, store, inst, loopback_restart):
    settings = {"auto_start": True, "port": host.port, "token": host.token, "address": "127.0.0.1",
                "folders": list(m.SYNC_FOLDERS), "strict": True, "excludes": ["*.part", "*.tmp"]}
    old_url = host.url("127.0.0.1")
    m.atomic_json(inst.directory / "host_settings.json", settings)
    host.stop()
    restored, errors = m.resume_saved_hosts(store)
    try:
        assert not errors and restored[inst.id].url("127.0.0.1") == old_url
        assert requests.get(old_url + "/party.json", timeout=5).status_code == 200
    finally:
        for server in restored.values():
            server.stop()
    settings.pop("auto_start")
    m.atomic_json(inst.directory / "host_settings.json", settings)
    assert m.resume_saved_hosts(store) == ({}, {})


def test_resume_port_conflict_is_non_destructive(host, store, inst):
    settings = {"auto_start": True, "port": host.port, "token": host.token, "address": "127.0.0.1",
                "folders": list(m.SYNC_FOLDERS), "strict": True, "excludes": []}
    m.atomic_json(inst.directory / "host_settings.json", settings)
    restored, errors = m.resume_saved_hosts(store)
    assert not restored and inst.id in errors
    assert m.read_json(inst.directory / "host_settings.json") == settings
    assert requests.get(host.url("127.0.0.1") + "/manifest.json", timeout=5).status_code == 200


def test_cancelled_resume_never_opens_a_socket(store, inst):
    m.atomic_json(inst.directory / "host_settings.json", {"auto_start": True})
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(m.Cancelled):
        m.resume_saved_hosts(store, cancel=cancel)


def test_unchanged_mods_are_not_rehashed_for_each_heartbeat(host, monkeypatch, put, inst):
    original = m.sha1_file
    calls = []
    monkeypatch.setattr(m, "sha1_file", lambda path: (calls.append(path), original(path))[1])
    host._cached_at = 0
    host.manifest()
    assert not calls
    put(inst.game_dir, "mods/a.jar", b"changed host mod")
    host._cached_at = 0
    assert host.party_snapshot(refresh=True)["rev"] != inst.last_sync_rev
    assert len(calls) == 1


def test_launch_manifest_rehashes_even_if_file_metadata_was_preserved(host, inst):
    path = inst.game_dir / "mods/a.jar"
    old_digest = m.sha1_file(path)
    path.write_bytes(b"changed!")
    info = path.stat()
    stamp = (info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino, info.st_dev)
    # Simulate an in-place, same-sized Windows edit with restored timestamps.
    host._file_hashes["mods/a.jar"] = (stamp, old_digest)
    response = requests.get(host.url("127.0.0.1") + "/manifest.json", timeout=5)
    assert response.status_code == 200
    entry = next(item for item in response.json()["files"] if item["path"] == "mods/a.jar")
    assert entry["sha1"] == m.sha1_file(path) and entry["sha1"] != old_digest
