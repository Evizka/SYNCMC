"""Connection feedback is explanatory, countdowns are real, and secrets stay hidden."""
import json

import pytest
import requests

import mcsync as m


def http_error(code):
    response = requests.Response()
    response.status_code = code
    return requests.HTTPError("private response body must not be displayed", response=response)


@pytest.mark.parametrize("exc,kind", [
    (http_error(401), "invitation"), (http_error(403), "invitation"),
    (http_error(409), "session"), (http_error(429), "busy"), (http_error(503), "busy"),
    (requests.Timeout("timeout"), "timeout"), (requests.ConnectionError("offline"), "network"),
    (m.UserError("invalid"), "protocol"), (OSError("unreadable"), "local"),
    (RuntimeError("unknown"), "unexpected"),
])
def test_failure_has_actionable_safe_classification(exc, kind):
    result = m.party_failure(exc)
    assert result["error_kind"] == kind and result["error_message"]
    assert "private response body" not in result["error_message"]


def test_error_url_is_redacted():
    token = "a" * 24
    result = m.party_failure(requests.ConnectionError(f"url: /{token}/party/heartbeat"))
    assert token not in json.dumps(result)


@pytest.mark.parametrize("address", ["192.168.1.118", "10.0.0.7", "172.16.0.9", "127.0.0.1"])
def test_private_party_timeout_explains_lan_vpn_and_firewall(address):
    token = "b" * 24
    url = f"http://{address}:25589/{token}"
    result = m.party_failure(requests.ConnectTimeout("timed out"), url)
    assert result["error_kind"] == "private_address"
    assert address in result["error_message"]
    assert "LAN/VPN" in result["error_message"]
    assert "брандмауэре" in result["error_message"]
    assert token not in json.dumps(result)


def test_private_party_address_hint_does_not_show_invitation_token():
    token = "c" * 24
    hint = m.party_address_hint(f"http://192.168.1.118:25589/{token}")
    assert "192.168.1.118:25589" in hint and "VPN" in hint
    assert token not in hint
    assert m.party_address_hint("8.8.8.8", default_port=25589) == ""
    assert m.party_address_hint("example.org") == ""


def test_radmin_ip_parser_reads_only_the_radmin_adapter():
    output = """Windows IP Configuration

Ethernet adapter Wi-Fi:
   IPv4 Address. . . . . . . . . . . : 192.168.1.118

Ethernet adapter Radmin VPN:
   IPv4 Address. . . . . . . . . . . : 26.14.22.33 (Preferred)
"""
    assert m.radmin_vpn_ipv4_from_output(output) == "26.14.22.33"


def test_radmin_ip_parser_ignores_lan_address_when_vpn_has_no_ipv4():
    output = """Ethernet adapter Radmin VPN:
   Media State . . . . . . . . . . . : Media disconnected

Ethernet adapter Wi-Fi:
   IPv4 Address. . . . . . . . . . . : 192.168.1.118
"""
    assert m.radmin_vpn_ipv4_from_output(output) == ""


def test_non_public_http_failure_keeps_generic_classification():
    result = m.party_failure(requests.ConnectTimeout("timed out"), "http://example.org:25589/" + "a" * 24)
    assert result["error_kind"] == "timeout"
    assert "слишком долго" in result["error_message"]


def test_monitor_passes_invitation_address_to_network_error_classifier(store, inst, monkeypatch):
    inst = store.update(inst.id, sync_url="http://192.168.1.118:25589/" + "d" * 24)
    monitor = m.PartyMonitor(store)
    monitor.sources[inst.id] = inst.sync_url
    monkeypatch.setattr(m, "poll_party", lambda *args: (_ for _ in ()).throw(requests.ConnectTimeout("timed out")))
    monitor._poll(inst, inst.sync_url)
    state = monitor.snapshot()[inst.id]
    assert state["error_kind"] == "private_address"
    assert "LAN/VPN" in state["error_message"]


def test_countdown_uses_actual_due_time_without_false_online():
    state = {"online": False, "retry_at": 110.0}
    assert "через 10 с" in m.party_connection_text(state, now=100.0)
    assert "через 2 с" in m.party_connection_text(state, now=108.1)
    assert "Пробуем подключиться" in m.party_connection_text(state, now=110.0)
    assert "автоматически" in m.party_connection_text({})
    assert "мс" not in m.party_connection_text({"online": True})


@pytest.mark.parametrize("value", [[], None, {"port": "25589"}, {"port": True}, {"port": 70000},
    {"address": "http://bad"}, {"token": "short"}, {"folders": "mods"}, {"folders": ["saves"]},
    {"excludes": "*.tmp"}, {"strict": "yes"}, {"auto_start": 1}])
def test_corrupt_host_preferences_never_reach_qt_or_a_listening_socket(value):
    with pytest.raises(m.UserError):
        m.validate_host_preferences(value)


def test_legacy_partial_host_preferences_are_supported():
    assert m.validate_host_preferences({}) == {}
    value = {"port": 25589, "address": "127.0.0.1", "folders": ["mods"], "strict": True}
    assert m.validate_host_preferences(value) == value


def test_unexpected_monitor_failure_is_not_silently_swallowed(store, inst, monkeypatch):
    inst = store.update(inst.id, sync_url="http://host:25589/" + "x" * 24)
    monitor = m.PartyMonitor(store)
    monitor.sources[inst.id] = inst.sync_url
    monkeypatch.setattr(m, "poll_party", lambda *args: (_ for _ in ()).throw(RuntimeError("failure")))
    monitor._poll(inst, inst.sync_url)
    result = monitor.snapshot()[inst.id]
    assert result["online"] is False and result["error_kind"] == "unexpected"
    assert result["retry_at"] > result["received_at"]


@pytest.mark.skipif(not m.QT_AVAILABLE, reason="Qt libraries unavailable")
def test_new_invitation_preserves_worlds_versions_and_confirmation(app, store, inst, put):
    old = "http://host:25589/" + "a" * 24
    new = "http://host:25589/" + "b" * 24
    inst = store.update(inst.id, sync_url=old, last_sync_rev="c" * 40)
    world = put(inst.game_dir, "saves/World/level.dat", b"do not alter this")
    window = m.MainWindow(store, network_enabled=False)
    window.change_invitation()
    dialog = window.main_pages.currentWidget()
    assert isinstance(dialog, m.ConnectDialog) and not dialog.isWindow()
    dialog.url.setText(new)
    dialog.alias.setText("New name")
    dialog.validate_and_accept()
    app.processEvents()
    updated = store.load(inst.id)
    assert updated.sync_url == new and updated.identity == inst.identity
    assert updated.last_sync_rev == inst.last_sync_rev and updated.sync_mode == "version"
    assert world.read_bytes() == b"do not alter this"
    assert not window.sync_label.property("connected")
    window.close()


@pytest.mark.skipif(not m.QT_AVAILABLE, reason="Qt libraries unavailable")
@pytest.mark.parametrize("content", ["broken", "[]", '{"port":"bad"}'])
def test_host_dialog_handles_corrupt_settings_without_overwriting(app, store, inst, content):
    path = inst.directory / "host_settings.json"
    path.write_text(content)
    window = m.MainWindow(store, network_enabled=False)
    dialog = m.HostDialog(window, inst)
    assert dialog.settings_error
    assert dialog.url_field.echoMode() == m.QLineEdit.EchoMode.Password
    assert path.read_text() == content
    dialog.reject()
    window.close()


@pytest.mark.skipif(not m.QT_AVAILABLE, reason="Qt libraries unavailable")
def test_old_room_ui_is_cleared_when_source_changes(app, store, inst):
    old = "http://host:25589/" + "a" * 24
    inst = store.update(inst.id, sync_url=old)
    import hashlib
    window = m.MainWindow(store, network_enabled=False)
    cached = {"source": hashlib.sha256(old.encode()).hexdigest(), "online": True}
    window.party_states[inst.id] = cached
    window.sync_checks[inst.id] = cached
    store.update(inst.id, sync_url="http://host:25589/" + "b" * 24)
    window.refresh_party_state()
    assert inst.id not in window.party_states and inst.id not in window.sync_checks
    assert window.sync_label.property("connected") is False
    window.close()
