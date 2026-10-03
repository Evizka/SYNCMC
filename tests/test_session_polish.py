import hashlib
import threading
import time

import pytest

import mcsync as m


def test_slow_departures_are_bounded_and_do_not_block_supervisor(store, inst, monkeypatch):
    monitor = m.PartyMonitor(store)
    entered, release = [], threading.Event()
    def leave(profile):
        entered.append(profile.id)
        release.wait(2)
    monkeypatch.setattr(monitor, '_leave', leave)
    start = time.monotonic()
    try:
        for _ in range(20):
            monitor._schedule_leave(inst)
        assert time.monotonic() - start < 0.5
        until = time.monotonic() + 1
        while len(entered) < 2 and time.monotonic() < until:
            time.sleep(0.01)
        assert len(entered) == 2
    finally:
        release.set()


@pytest.mark.skipif(not m.QT_AVAILABLE, reason='Qt unavailable')
def test_stat_tiles_navigate_without_modifying_drafts(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    window.notes_field.setPlainText('Keep this unsaved')
    window.stat_mods.activated.emit()
    assert window.tabs.currentWidget() is window.file_panels['mods']
    window.stat_worlds.activated.emit()
    assert window.tabs.currentWidget() is window.file_panels['saves']
    assert window.notes_field.toPlainText() == 'Keep this unsaved'
    assert store.load(inst.id).notes == ''
    window.close()


@pytest.mark.skipif(not m.QT_AVAILABLE, reason='Qt unavailable')
def test_host_details_are_collapsible_and_defaults_remain_safe(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    dialog = m.HostDialog(window, inst)
    dialog.show()
    app.processEvents()
    assert not dialog.advanced.isVisible()
    assert dialog.strict.isChecked() and dialog.autostart.isChecked()
    assert all(box.isChecked() for box in dialog.folders.values())
    dialog.toggle_advanced()
    assert dialog.advanced.isVisible()
    dialog.show_invitation.setChecked(True)
    assert dialog.url_field.echoMode() == m.QLineEdit.EchoMode.Normal
    dialog.reject()
    window.close()


def test_invalid_accessibility_setting_is_not_treated_as_true(store):
    store.settings['reduced_motion'] = 'false'
    store.save_settings()
    restarted = m.Store(store.root)
    assert restarted.settings['reduced_motion'] is False and restarted.settings_error


@pytest.mark.skipif(not m.QT_AVAILABLE, reason='Qt unavailable')
def test_future_saved_sync_timestamp_does_not_suppress_live_presence(app, store, inst):
    url = 'http://host:25589/' + 'a' * 24
    inst = store.update(inst.id, sync_url=url, last_sync_at=time.time() + 3600)
    window = m.MainWindow(store, network_enabled=False)
    window.party_monitor.states[inst.id] = {'source':hashlib.sha256(url.encode()).hexdigest(),
        'online':True, 'supported':False, 'checked_at':time.time()}
    window.refresh_party_state()
    assert window.sync_label.property('connected') is True
    window.close()


@pytest.mark.skipif(not m.QT_AVAILABLE, reason='Qt unavailable')
def test_invitation_is_not_changed_if_preferences_cannot_be_saved(app, store, inst, monkeypatch):
    old = 'http://host:25589/' + 'a' * 24
    new = 'http://host:25589/' + 'b' * 24
    inst = store.update(inst.id, sync_url=old)
    window = m.MainWindow(store, network_enabled=False)
    monkeypatch.setattr(m,'message',lambda *a,**kw:None)
    monkeypatch.setattr(store,'save_settings',lambda:(_ for _ in ()).throw(OSError('disk full')))
    window.change_invitation()
    dialog = window.main_pages.currentWidget()
    assert isinstance(dialog, m.ConnectDialog) and not dialog.isWindow()
    dialog.url.setText(new)
    dialog.alias.setText('Alias')
    dialog.validate_and_accept()
    app.processEvents()
    assert store.load(inst.id).sync_url == old
    assert window.main_pages.currentWidget() is dialog
    monkeypatch.undo()
    window.close()
