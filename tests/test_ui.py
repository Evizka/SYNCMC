import time

import pytest

import mcsync as m

pytestmark = pytest.mark.skipif(not m.QT_AVAILABLE, reason="Qt runtime libraries not available")


def wait_until(app, condition, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("GUI task did not complete")


def test_empty_window_then_instance(app, store):
    window = m.MainWindow(store, network_enabled=False)
    window.show()
    app.processEvents()
    assert window.instances.count() == 0 and not window.play_btn.isEnabled()
    inst = store.create("Наш сервер", loader="neoforge", loader_version="21.1.234")
    window.refresh_instances(inst.id)
    assert window.title_label.text() == "Наш сервер"
    assert window.play_btn.isEnabled()
    assert window.tabs.count() == 7
    assert window.loader_field.currentData() == "neoforge"
    assert window.loader_version_field.currentText() == "21.1.234"
    window.close()


def test_linked_version_fields_are_locked_but_java_ram_editable(app, store):
    inst = store.create("Друг", sync_url="http://127.0.0.1:25589/" + "x" * 24)
    window = m.MainWindow(store, network_enabled=False)
    assert window.current_id() == inst.id
    for field in (window.mc_field, window.loader_field, window.loader_version_field, window.server_field):
        assert not field.isEnabled()
    assert window.java_field.isEnabled() and window.ram_max.isEnabled()
    assert window.sync_btn.isEnabled() and not window.host_btn.isEnabled()
    assert not window.file_panels["mods"].add_btn.isEnabled()
    window.close()


def test_ram_controls_have_custom_slider_and_keep_precise_values(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    assert isinstance(window.ram_min, m.MemorySlider)
    assert isinstance(window.ram_max.slider, m.QSlider)
    assert window.ram_max.slider.objectName() == "memorySlider"
    ram_limit = m.physical_memory_mb()
    window.ram_max.slider.setValue(window.ram_max.slider.maximum())
    assert window.ram_max.value() == window.ram_max.maximum() == ram_limit
    expected = min(6144, ram_limit)
    window.ram_max.spinbox.setValue(expected)
    assert window.ram_max.value() == expected
    assert window.editor_values(inst)["ram_max"] == expected
    window.ram_max.setValue(min(inst.ram_max, ram_limit))

    dialog = m.SettingsDialog(window)
    assert dialog.ram.value() == min(4096, ram_limit)
    default_ram = min(8192, ram_limit)
    dialog.ram.spinbox.setValue(default_ram)
    dialog.save()
    assert m.Store(store.root).settings["default_ram"] == default_ram
    window.draft_timer.stop()
    window.close()


def test_build_icons_are_hidden_in_the_editor_and_cards_but_still_serialized(app, store):
    inst = store.create("Наша сборка", icon="sword")
    window = m.MainWindow(store, network_enabled=False)
    window.show()
    app.processEvents()

    assert not hasattr(window, "icon_field")
    assert all("Иконка" not in window.identity_form.itemAt(i, m.QFormLayout.ItemRole.LabelRole).widget().text()
               for i in range(window.identity_form.rowCount())
               if window.identity_form.itemAt(i, m.QFormLayout.ItemRole.LabelRole) is not None)
    assert window.instances.item(0).icon().isNull()
    assert window.library_grid.item(0).icon().isNull()

    # The stored value survives editing and saving, so 0.5.5 profiles keep loading unmodified.
    assert window.editor_values(inst)["icon"] == "sword"
    window.name_field.setText("Наша сборка 2")
    assert window.save_current()
    assert store.load(inst.id).icon == "sword"
    assert store.load(inst.id).icon == inst.icon
    window.close()


def test_periodic_badge_check_does_not_discard_unsaved_settings(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    window.notes_field.setPlainText("Unsaved notes")
    window.name_field.setText("Unsaved name")
    window.on_update_check({inst.id: True})
    assert window.notes_field.toPlainText() == "Unsaved notes"
    assert window.name_field.text() == "Unsaved name"
    assert "⬆" in window.instances.currentItem().text()
    window.close()


def test_background_task_returns_on_gui_thread_and_preserves_input(app, store, inst):
    from PySide6.QtCore import QThread
    window = m.MainWindow(store, network_enabled=False)
    window.notes_field.setPlainText("Work in progress")
    completed = []
    def done(result):
        completed.append((result, QThread.currentThread() == app.thread()))
    window.run_task("Test", lambda p, c: 123, done)
    assert window.busy
    wait_until(app, lambda: not window.busy)
    assert completed == [(123, True)]
    assert window.notes_field.toPlainText() == "Work in progress"
    window.close()


def test_sync_dialog_is_created_in_gui_thread_worker_waits(app, store, inst, manifest, monkeypatch):
    from PySide6.QtCore import QThread
    window = m.MainWindow(store, network_enabled=False)
    plan = m.build_plan(inst, manifest({"mods/a.jar": b"mod"}, minecraft="1.21.1"))
    created = []
    real_dialog = m.SyncConfirmDialog
    class AutoAccept(real_dialog):
        def __init__(self, *args):
            created.append(QThread.currentThread() == app.thread())
            super().__init__(*args)
        def exec(self):
            return m.QDialog.DialogCode.Accepted
    monkeypatch.setattr(m, "SyncConfirmDialog", AutoAccept)
    results = []
    window.run_task("Confirm", lambda p, c: window.wait_confirmation(inst, plan, c), results.append, inst.id)
    wait_until(app, lambda: not window.busy)
    assert results == [(True, True)] and created == [True]
    assert not (inst.game_dir / "mods/a.jar").exists()
    window.close()


def test_downgrade_dialog_and_backup_checkbox(app, inst, manifest):
    inst.minecraft = "1.21.1"
    plan = m.build_plan(inst, manifest({"mods/a.jar": b"mod"}))
    dialog = m.SyncConfirmDialog(inst, plan)
    assert plan.downgrade and dialog.backup.isChecked()
    text = "\n".join(widget.text() for widget in dialog.findChildren(m.QLabel))
    assert "понижение" in text and "1.21.1 → 1.20.1" in text
    dialog.reject()


def test_skin_preview_modern_legacy_and_validation(app):
    from PySide6.QtCore import QBuffer, QIODevice
    for height in (64, 32):
        image = m.QImage(64, height, m.QImage.Format.Format_ARGB32)
        image.fill(m.QColor("#65dfb7"))
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        assert image.save(buffer, "PNG")
        skin = m.SkinPreview()
        skin.load_png(bytes(buffer.data()))
        assert skin.pixmap().size() == m.QSize(160, 272)
        skin.slim = True
        skin.render_skin()
    with pytest.raises(m.UserError):
        skin.load_png(b"not a PNG")


def test_groups_copy_and_playtime_ui(app, store):
    a = store.create("A", group="Friends", playtime=7200)
    store.create("B", group="Solo")
    window = m.MainWindow(store, network_enabled=False)
    window.groups.setCurrentIndex(window.groups.findData("Friends"))
    assert window.instances.count() == 1 and window.current_id() == a.id
    assert "2.0 ч" in window.meta_label.text()
    window.on_game_finished(a.id, 0, 120, "")
    assert store.load(a.id).playtime == 7320
    window.close()
