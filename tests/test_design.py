"""Appearance changes must not break launcher controls or in-progress edits."""
import time

import pytest

import mcsync as m

pytestmark = pytest.mark.skipif(not m.QT_AVAILABLE, reason="Qt runtime libraries not available")


def wait_until(app, condition):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("GUI task did not finish")


@pytest.mark.parametrize("theme", list(m.THEMES))
def test_each_theme_renders_all_tabs_and_keeps_the_instance(app, store, inst, put, theme):
    put(inst.game_dir, "mods/a.jar", b"preview")
    put(inst.game_dir, "resourcepacks/a.zip", b"preview")
    window = m.MainWindow(store, network_enabled=False, theme=theme)
    window.show()
    app.processEvents()
    assert window.theme == theme
    assert app.palette().color(m.QPalette.ColorRole.Window).name() == m.THEMES[theme]["bg"]
    assert window.current_id() == inst.id
    assert window.detail_stack.currentWidget() is window.details
    for index in range(window.tabs.count()):
        window.tabs.setCurrentIndex(index)
        app.processEvents()
        assert not window.grab().isNull()
    window.close()


def test_theme_setting_persists_without_discarding_unsaved_instance_edits(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    window.name_field.setText("Not saved yet")
    window.notes_field.setPlainText("Keep these edits")
    dialog = m.SettingsDialog(window)
    dialog.theme_field.setCurrentIndex(dialog.theme_field.findData("paper"))
    dialog.save()
    assert window.theme == "paper"
    assert window.name_field.text() == "Not saved yet"
    assert window.notes_field.toPlainText() == "Keep these edits"
    assert m.Store(store.root).settings["theme"] == "paper"
    # Appearance saves no instance metadata behind the user's back.
    assert store.load(inst.id).name == inst.name
    window.close()
    restarted = m.MainWindow(m.Store(store.root), network_enabled=False)
    assert restarted.theme == "paper"
    restarted.close()


def test_invalid_saved_theme_is_safe_and_can_be_changed(app, store, inst):
    store.settings["theme"] = "does-not-exist"
    store.save_settings()
    window = m.MainWindow(store, network_enabled=False)
    assert window.theme == m.DEFAULT_THEME
    window.set_theme("aurora")
    assert window.theme == "aurora"
    window.close()


def test_theme_override_is_not_silently_persisted(app, store, inst):
    window = m.MainWindow(store, network_enabled=False, theme="aurora")
    assert window.theme == "aurora"
    assert m.Store(store.root).settings["theme"] == m.DEFAULT_THEME
    window.close()


def test_empty_and_no_search_results_have_a_useful_page(app, store):
    window = m.MainWindow(store, network_enabled=False)
    assert window.detail_stack.currentWidget() is window.empty_page
    store.create("My world")
    window.refresh_instances()
    assert window.detail_stack.currentWidget() is window.details
    window.search.setText("Not found")
    assert window.detail_stack.currentWidget() is window.empty_page
    assert "не найдена" in window.empty_title.text()
    assert not window.play_btn.isEnabled()
    window.close()


def test_subscribed_pack_cannot_edit_files_from_the_redesigned_menu(app, store, put):
    inst = store.create("Friend", sync_url="http://127.0.0.1:25589/" + "x" * 24)
    target = put(inst.game_dir, "mods/a.jar", b"host mod")
    window = m.MainWindow(store, network_enabled=False)
    panel = window.file_panels["mods"]
    assert not panel.add_btn.isEnabled() and not panel.toggle_btn.isEnabled()
    assert panel.folder_btn.isEnabled()
    assert panel.list.count() == 1
    panel.list.setCurrentRow(0)
    panel.toggle()
    assert target.read_bytes() == b"host mod" and not target.with_name("a.jar.disabled").exists()
    assert window.more_btn.menu().actions()
    assert window.export_btn.isEnabled()
    window.close()


def test_update_badge_uses_real_revision_state_and_survives_theme_change(app, store, inst):
    inst = store.update(inst.id, sync_url="http://127.0.0.1:25589/" + "x" * 24)
    window = m.MainWindow(store, network_enabled=False)
    window.notes_field.setPlainText("Don't discard")
    assert window.sync_label.property("status") == "linked"
    window.on_update_check({inst.id: True})
    assert window.sync_label.property("status") == "pending"
    assert "обновление" in window.sync_label.text()
    window.set_theme("aurora")
    assert window.sync_label.property("status") == "pending"
    assert window.notes_field.toPlainText() == "Don't discard"
    window.close()


def test_legacy_api_in_background_version_query_shows_a_helpful_message(app, store, inst, monkeypatch):
    from types import SimpleNamespace
    inst = store.update(inst.id, loader="fabric")
    window = m.MainWindow(store, network_enabled=False)
    errors = []
    monkeypatch.setattr(m, "launcher_lib", lambda: SimpleNamespace())
    monkeypatch.setattr(m, "message", lambda parent, title, text, **kwargs: errors.append(text))
    window.notes_field.setPlainText("Work in progress")
    window.fetch_loader_versions()
    wait_until(app, lambda: not window.busy)
    assert len(errors) == 1 and "8.0" in errors[0] and "pip install" in errors[0]
    assert "has no attribute" not in errors[0]
    assert window.notes_field.toPlainText() == "Work in progress"
    window.close()


def test_selected_aurora_is_default_for_new_data_but_saved_theme_is_preserved(store):
    assert m.DEFAULT_THEME == "aurora"
    assert m.Store(store.root).settings["theme"] == "aurora"
    store.settings["theme"] = "paper"
    store.save_settings()
    assert m.Store(store.root).settings["theme"] == "paper"
