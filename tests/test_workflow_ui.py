
import pytest

import mcsync as m

pytestmark = pytest.mark.skipif(not m.QT_AVAILABLE, reason="Qt runtime libraries not available")


def select(window, instance_id):
    for i in range(window.instances.count()):
        item = window.instances.item(i)
        if item.data(m.Qt.ItemDataRole.UserRole) == instance_id:
            window.instances.setCurrentItem(item)
            return
    raise AssertionError("Instance not found")


def test_switching_instances_preserves_a_draft_without_applying_versions(app, store):
    a = store.create("A", minecraft="1.20.1")
    b = store.create("B")
    window = m.MainWindow(store, network_enabled=False)
    select(window, a.id)
    window.name_field.setText("Pending name")
    window.notes_field.setPlainText("Pending notes")
    window.mc_field.setCurrentText("1.21.1")
    select(window, b.id)
    assert store.load(a.id).minecraft == "1.20.1" and store.load(a.id).name == "A"
    assert m.read_json(a.directory / "draft.json")["values"]["notes"] == "Pending notes"
    select(window, a.id)
    assert window.name_field.text() == "Pending name"
    assert window.mc_field.currentText() == "1.21.1"
    assert window.notes_field.toPlainText() == "Pending notes"
    assert window.save_current()
    assert store.load(a.id).minecraft == "1.21.1"
    assert not (a.directory / "draft.json").exists()
    window.close()


def test_draft_survives_restart_and_can_be_discarded(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    window.notes_field.setPlainText("Keep after restart")
    window.close()
    restarted = m.MainWindow(m.Store(store.root), network_enabled=False)
    assert restarted.notes_field.toPlainText() == "Keep after restart"
    assert store.load(inst.id).notes == ""
    restarted.discard_draft()
    assert restarted.notes_field.toPlainText() == ""
    assert not (inst.directory / "draft.json").exists()
    restarted.close()


def test_search_hiding_a_profile_does_not_discard_its_input(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    window.notes_field.setPlainText("Don't lose to filtering")
    window.search.setText("nothing matches")
    assert not window.current_id()
    window.search.clear()
    assert window.notes_field.toPlainText() == "Don't lose to filtering"
    window.close()


def test_subscription_draft_cannot_override_host_version_fields(app, store):
    inst = store.create("Linked", minecraft="1.21.1", sync_url="http://host:25589/" + "x" * 24)
    m.atomic_json(inst.directory / "draft.json", {"schema": 1, "values": {"minecraft": "1.12.2", "loader": "forge", "notes": "Allowed"}})
    window = m.MainWindow(store, network_enabled=False)
    assert window.mc_field.currentText() == "1.21.1"
    assert window.loader_field.currentData() == "vanilla"
    assert window.notes_field.toPlainText() == "Allowed"
    window.close()


def test_bad_draft_values_do_not_crash_the_editor(app, store, inst):
    m.atomic_json(inst.directory / "draft.json", {"values": {"loader": [], "notes": 123, "ram_max": "invalid", "name": ["bad"]}})
    window = m.MainWindow(store, network_enabled=False)
    assert window.name_field.text() == inst.name and window.ram_max.value() == inst.ram_max
    window.close()


def test_ram_slider_restores_a_precise_draft_and_saves_it(app, store, inst):
    m.atomic_json(inst.directory / "draft.json", {"schema": 1, "values": {"ram_max": 6144}})
    window = m.MainWindow(store, network_enabled=False)
    assert window.ram_max.value() == 6144
    assert window.ram_max.spinbox.value() == 6144
    assert window.save_current()
    assert store.load(inst.id).ram_max == 6144
    window.close()


@pytest.mark.parametrize("layout", list(m.LAYOUTS))
def test_layouts_render_and_keep_the_same_controls(app, store, inst, layout):
    window = m.MainWindow(store, network_enabled=False, layout=layout)
    window.show()
    app.processEvents()
    assert window.layout_mode == layout
    if layout == "gallery":
        assert window.main_pages.currentWidget() is window.library_page
        assert window.library_grid.count() == 1
        window.open_library_instance(window.library_grid.item(0))
        assert window.main_pages.currentWidget() is window.lobby_page
    else:
        assert window.main_pages.currentWidget() is window.lobby_page
    assert window.current_id() == inst.id and window.play_btn.isEnabled()
    assert not window.grab().isNull()
    window.close()


def test_theme_and_layout_overrides_remain_session_only_after_close(app, store, inst):
    window = m.MainWindow(store, network_enabled=False, theme="ember", layout="gallery")
    window.close()
    fresh = m.Store(store.root)
    assert fresh.settings["theme"] == m.DEFAULT_THEME and fresh.settings["layout"] == "comfortable"


def test_favorite_and_recent_sort_are_real_persistent_metadata(app, store):
    a = store.create("A", last_played=10)
    b = store.create("B", last_played=20)
    window = m.MainWindow(store, network_enabled=False)
    select(window, b.id)
    window.toggle_favorite()
    assert store.load(b.id).favorite
    assert window.instances.item(0).data(m.Qt.ItemDataRole.UserRole) == b.id
    window.sort_combo.setCurrentIndex(window.sort_combo.findData("recent"))
    assert window.instances.item(0).data(m.Qt.ItemDataRole.UserRole) == b.id
    window.sort_combo.setCurrentIndex(window.sort_combo.findData("name"))
    assert window.instances.item(0).data(m.Qt.ItemDataRole.UserRole) == a.id
    window.close()


def test_file_filter_and_selection_survive_background_refresh(app, store, inst, put):
    put(inst.game_dir, "mods/a.jar", b"a")
    put(inst.game_dir, "mods/b.jar", b"b")
    window = m.MainWindow(store, network_enabled=False)
    panel = window.file_panels["mods"]
    panel.list.setCurrentRow(0)
    assert panel.toggle_btn.isEnabled()
    window.on_update_check({inst.id: True})
    assert panel.selected() == ["a.jar"]
    panel.filter_field.setText("b.jar")
    assert panel.list.item(0).isHidden() and not panel.selected()
    assert not panel.toggle_btn.isEnabled() and "1 / 2" in panel.summary.text()
    window.close()


def test_summary_counts_actual_files_and_worlds(app, store, inst, put):
    put(inst.game_dir, "mods/a.jar", b"a")
    put(inst.game_dir, "mods/b.jar.disabled", b"b")
    put(inst.game_dir, "saves/World/level.dat", b"world")
    window = m.MainWindow(store, network_enabled=False)
    assert window.stat_mods.value.text() == "1"
    assert "2" in window.stat_mods.caption.text()
    assert window.stat_worlds.value.text() == "1"
    assert "первом запуске" in window.summary_runtime.text()
    window.close()


def test_long_names_and_notes_do_not_force_an_oversized_window(app, store):
    store.create("Очень длинное имя " * 10, group="G" * 200, notes="\n" * 1000)
    window = m.MainWindow(store, network_enabled=False)
    window.resize(1000, 690)
    window.show()
    app.processEvents()
    assert window.width() <= 1000 and window.height() <= 690
    window.close()


def test_corrupted_profile_has_a_nonblocking_diagnostics_banner(app, store, inst):
    broken = store.create("Broken")
    (broken.directory / "instance.json").write_text("broken")
    window = m.MainWindow(store, network_enabled=False)
    assert window.current_id() == inst.id
    assert "Повреждённые сборки" in window.recovery_label.text()
    dialog = m.DiagnosticsDialog(window)
    assert broken.id in dialog.view.toPlainText()
    dialog.reject()
    window.close()


def test_backup_dialog_worker_finishes_without_modifying_the_instance(app, store, inst, put):
    put(inst.game_dir, "saves/World/level.dat", b"world")
    window = m.MainWindow(store, network_enabled=False)
    dialog = m.BackupProgressDialog(inst, window)
    assert dialog.exec() == m.QDialog.DialogCode.Accepted
    assert list((inst.directory / "backups").glob("*.zip"))
    assert store.load(inst.id).minecraft == inst.minecraft
    window.close()


def test_modrinth_install_button_requires_an_eligible_selection(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    assert not window.mr_install_btn.isEnabled()
    item = m.QListWidgetItem("A mod")
    item.setData(m.Qt.ItemDataRole.UserRole, {"project_id": "a", "project_type": "mod"})
    window.mr_results.addItem(item)
    window.mr_results.setCurrentItem(item)
    assert window.mr_install_btn.isEnabled()
    store.update(inst.id, sync_url="http://host:25589/" + "x" * 24)
    window.load_detail()
    assert not window.mr_install_btn.isEnabled()
    window.close()


def test_modrinth_can_page_results_and_resets_pages_when_query_changes(app, store, inst, monkeypatch):
    calls = []
    class Client:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def search(self, query, kind, profile, offset=0):
            calls.append(offset)
            count = 30 if offset == 0 else 1
            return [{"project_id": str(offset + i), "title": "Mod", "project_type": "mod"} for i in range(count)]
    monkeypatch.setattr(m, "ModrinthClient", Client)
    window = m.MainWindow(store, network_enabled=False)
    def run_task(title, work, done, *args, **kwargs):
        done(work(m.no_progress, None))
    monkeypatch.setattr(window, "run_task", run_task)
    window.search_modrinth()
    assert window.mr_next.isEnabled() and not window.mr_previous.isEnabled()
    window.change_modrinth_page(1)
    assert calls == [0, 30] and window.mr_results.count() == 1
    assert "31–31" in window.mr_page_label.text()
    assert window.mr_previous.isEnabled() and not window.mr_next.isEnabled()
    window.mr_query.setText("a new query")
    assert not window.mr_previous.isEnabled() and window.mr_context is None
    window.close()


def test_offline_host_status_is_from_a_check_not_from_having_a_link(app, store):
    inst = store.create("Linked", sync_url="http://host:25589/" + "x" * 24)
    window = m.MainWindow(store, network_enabled=False)
    assert "недоступен" not in window.sync_label.text()
    window.on_update_check({inst.id: {"online": False, "changed": None}})
    assert "недоступен" in window.sync_label.text()
    window.on_update_check({inst.id: {"online": True, "changed": False}})
    assert "недоступен" not in window.sync_label.text()
    window.close()
