"""The party UI keeps drafts, user consent and real connection state intact."""
import hashlib
import time
from types import SimpleNamespace

import pytest

import mcsync as m

pytestmark = pytest.mark.skipif(not m.QT_AVAILABLE, reason="Qt runtime libraries not available")


def wait_until(app, condition):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError("GUI party state did not arrive")


def linked(store):
    return store.create("Friend", sync_url="http://127.0.0.1:25589/" + "x" * 24)


def state(host, inst):
    return {"online": True, "supported": True, "room": host.party_snapshot(),
            "source": hashlib.sha256(inst.sync_url.encode()).hexdigest(), "checked_at": time.time(),
            "received_at": time.monotonic(), "latency_ms": 12}


def test_saved_invitation_does_not_invent_an_online_roster(app, store):
    linked(store)
    window = m.MainWindow(store, network_enabled=False)
    assert window.party_panel.roster.count() == 0
    assert "Подключаемся" in window.party_panel.badge.text()
    assert window.sync_label.property("connected") is False
    assert window.party_monitor.thread is None
    assert window.play_btn.text() == "▶  Играть"
    window.close()


def test_real_automatic_connection_renders_a_room_without_losing_edits(app, host, tmp_path):
    store = m.Store(tmp_path / "friend")
    store.settings["party_name"] = "Саша"
    inst = store.create("Friend", minecraft="1.20.1", sync_url=host.url("127.0.0.1"))
    window = m.MainWindow(store, network_enabled=True)
    try:
        window.name_field.setText("Unsaved title")
        window.notes_field.setPlainText("Unsaved notes")
        wait_until(app, lambda: window.party_panel.roster.count() == 2)
        assert window.sync_label.property("connected") is True
        assert "2 в сети" in window.party_panel.badge.text()
        assert window.name_field.text() == "Unsaved title"
        assert window.notes_field.toPlainText() == "Unsaved notes"
        assert store.load(inst.id).name == "Friend"
        window.busy = True
        window.refresh_party_state()
        assert window.party_panel.roster.count() == 2
        window.busy = False
    finally:
        window.busy = False
        window.close()


def test_failed_check_hides_online_peers_and_explains_auto_reconnect(app, store, host):
    inst = linked(store)
    window = m.MainWindow(store, network_enabled=False)
    window.party_monitor.states[inst.id] = state(host, inst)
    window.refresh_party_state()
    assert window.party_panel.roster.count() == 1
    window.party_monitor.states[inst.id] = dict(state(host, inst), online=False, changed=None)
    window.refresh_party_state()
    assert window.party_panel.roster.count() == 0
    assert "автоматически" in window.party_panel.connection.text()
    assert window.sync_label.property("connected") is False
    window.close()


def test_late_reply_for_a_different_invitation_is_ignored(app, store, host):
    inst = linked(store)
    window = m.MainWindow(store, network_enabled=False)
    window.party_monitor.states[inst.id] = dict(state(host, inst), source="wrong room")
    window.refresh_party_state()
    assert not window.party_panel.roster.count()
    assert inst.id not in window.sync_checks
    window.close()


def test_name_in_party_is_explicit_private_preference_not_the_account(app, store, inst):
    m.Accounts(store).add_offline("PrivatePlayer")
    window = m.MainWindow(store, network_enabled=False)
    window.name_field.setText("Keep draft")
    dialog = m.SettingsDialog(window)
    assert dialog.party_name_field.text() == ""
    dialog.party_name_field.setText("Лена")
    dialog.save()
    assert m.Store(store.root).settings["party_name"] == "Лена"
    assert window.name_field.text() == "Keep draft"
    assert store.load(inst.id).name == inst.name
    window.close()


def test_unsafe_nickname_is_rejected_before_joining(app, store, inst, monkeypatch):
    window = m.MainWindow(store, network_enabled=False)
    dialog = m.ConnectDialog(window)
    errors = []
    monkeypatch.setattr(m, "message", lambda *args, **kwargs: errors.append(args[2]))
    dialog.url.setText("http://host:25589/" + "x" * 24)
    dialog.alias.setText("<img src=x>")
    dialog.trust.setChecked(True)
    dialog.validate_and_accept()
    assert dialog.result() != m.QDialog.DialogCode.Accepted and errors
    dialog.reject()
    window.close()


def test_connection_dialog_explains_private_invite_without_blocking_lan_users(app, store):
    window = m.MainWindow(store, network_enabled=False)
    dialog = m.ConnectDialog(window)
    token = "x" * 24
    dialog.url.setText(f"http://192.168.1.118:25589/{token}")
    assert not dialog.network_hint.isHidden()
    assert "192.168.1.118:25589" in dialog.network_hint.text()
    assert token not in dialog.network_hint.text()
    dialog.url.setText("http://example.org:25589/" + token)
    assert dialog.network_hint.isHidden()
    dialog.reject()
    window.close()


def test_pasting_the_same_invitation_selects_existing_party_not_a_duplicate(app, store, monkeypatch):
    inst = linked(store)
    window = m.MainWindow(store, network_enabled=False)
    dialog = SimpleNamespace(url=SimpleNamespace(text=lambda: inst.sync_url),
                             name=SimpleNamespace(text=lambda: "Another title"),
                             exec=lambda: m.QDialog.DialogCode.Accepted)
    monkeypatch.setattr(m, "ConnectDialog", lambda parent: dialog)
    monkeypatch.setattr(window, "run_task", lambda *args, **kwargs: pytest.fail("must not download or create another pack"))
    window.connect_instance()
    assert len(store.list_instances()) == 1 and window.current_id() == inst.id
    window.close()


def test_host_stopping_explicitly_disables_autostart_without_rotating_invitation(app, host, store, inst):
    settings = {"auto_start": True, "port": host.port, "token": host.token, "address": "127.0.0.1",
                "folders": list(m.SYNC_FOLDERS), "strict": True, "excludes": []}
    m.atomic_json(inst.directory / "host_settings.json", settings)
    window = m.MainWindow(store, network_enabled=False)
    window.hosts[inst.id] = host
    dialog = m.HostDialog(window, inst)
    dialog.stop_host()
    saved = m.read_json(inst.directory / "host_settings.json")
    assert saved["auto_start"] is False and saved["token"] == settings["token"]
    assert inst.id not in window.hosts
    assert m.resume_saved_hosts(store) == ({}, {})
    dialog.reject()
    window.close()


def test_host_autostart_can_be_restored_in_the_gui_without_a_popup(app, host, store, inst, loopback_restart):
    settings = {"auto_start": True, "port": host.port, "token": host.token, "address": "127.0.0.1",
                "folders": list(m.SYNC_FOLDERS), "strict": True, "excludes": []}
    m.atomic_json(inst.directory / "host_settings.json", settings)
    host.stop()
    window = m.MainWindow(store, network_enabled=True)
    try:
        wait_until(app, lambda: inst.id in window.hosts and not window.busy)
        assert window.hosts[inst.id].token == settings["token"]
        assert "хост" in window.party_panel.title.text()
        assert window.party_panel.roster.count() == 1
    finally:
        window.close()
    assert m.read_json(inst.directory / "host_settings.json")["auto_start"] is True


def test_update_button_only_appears_when_there_are_changes(app, store):
    inst = linked(store)
    window = m.MainWindow(store, network_enabled=False)
    window.show_details()  # The update action lives in management, not the minimal launch lobby.
    window.show()
    app.processEvents()
    assert not window.sync_btn.isVisible()
    window.on_update_check({inst.id: {"online": True, "changed": True}})
    assert window.sync_btn.isVisible()
    assert window.sync_btn.text() == "Обновить сейчас"
    assert window.manual_sync_action.isEnabled()
    window.close()


def test_legacy_host_does_not_show_an_invented_member_count(app, store):
    inst = linked(store)
    window = m.MainWindow(store, network_enabled=False)
    legacy = {"online": True, "supported": False, "changed": False,
              "source": hashlib.sha256(inst.sync_url.encode()).hexdigest()}
    window.party_monitor.states[inst.id] = legacy
    window.refresh_party_state()
    assert window.party_panel.roster.count() == 0
    assert "старый MCSync" in window.party_panel.explanation.text()
    assert "Хост в сети" in window.party_panel.badge.text()
    window.close()


def test_party_layout_renders_on_a_small_window_in_all_themes(app, store, host):
    inst = linked(store)
    window = m.MainWindow(store, network_enabled=False)
    window.party_monitor.states[inst.id] = state(host, inst)
    window.refresh_party_state()
    window.resize(1000, 690)
    window.show()
    for key in m.THEMES:
        window.set_theme(key)
        app.processEvents()
        assert window.width() <= 1000 and window.height() <= 690
        assert not window.grab().isNull()
    window.close()
