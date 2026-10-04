
import threading
import time

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


def wait_until(app, condition):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("Background file scan did not finish")


def test_file_panels_and_logs_are_loaded_only_when_their_tab_is_active(app, store, inst, put):
    put(inst.game_dir, "mods/a.jar", b"mod")
    put(inst.directory, "launcher.log", b"launcher log")
    window = m.MainWindow(store, network_enabled=False)
    mods = window.file_panels["mods"]
    assert mods._dirty and not mods._scan_pending and mods.list.count() == 0
    assert window.logs_combo.count() == 0

    window.open_manager("mods")
    wait_until(app, lambda: not mods._dirty and not mods._scan_pending)
    assert mods.list.count() == 1
    assert window.logs_combo.count() == 0

    window.tabs.setCurrentWidget(window.logs_panel)
    wait_until(app, lambda: not window.logs_pending)
    assert window.logs_combo.count() == 1
    assert window.logs_combo.itemText(0) == "launcher.log"
    generation = window.logs_generation
    window.tabs.setCurrentWidget(window.file_panels["mods"])
    window.tabs.setCurrentWidget(window.logs_panel)
    assert window.logs_generation == generation and not window.logs_pending
    window.close()


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


def test_deleting_last_build_removes_it_and_shows_empty_state(app, store, monkeypatch):
    inst = store.create("Disposable")
    window = m.MainWindow(store, network_enabled=False)
    monkeypatch.setattr(m, "message", lambda *args, **kwargs: True)

    window.delete_instance()
    wait_until(app, lambda: not window.busy)

    assert not inst.directory.exists()
    assert window.current_id() == ""
    assert window.detail_stack.currentWidget() is window.empty_page
    window.close()


def test_deleting_active_host_stops_it_and_disables_autostart(app, store, inst, monkeypatch):
    class HostStub:
        def __init__(self):
            self.stopped = False

        def stop(self):
            self.stopped = True
            self.autostart = m.read_json(inst.directory / "host_settings.json")["auto_start"]

    host = HostStub()
    window = m.MainWindow(store, network_enabled=False)
    window.hosts[inst.id] = host
    m.atomic_json(inst.directory / "host_settings.json", {"auto_start": True})
    monkeypatch.setattr(m, "message", lambda *args, **kwargs: True)

    window.delete_instance()
    wait_until(app, lambda: not window.busy)

    assert host.stopped and host.autostart is False
    assert inst.id not in window.hosts and not inst.directory.exists()
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
    assert panel._dirty and not panel._scan_pending
    window.open_manager("mods")
    wait_until(app, lambda: not panel._dirty and not panel._scan_pending)
    assert all(other._dirty for name, other in window.file_panels.items() if name != "mods")
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
    wait_until(app, lambda: window.stat_mods.value.text() == "1" and window.stat_worlds.value.text() == "1")
    assert "2" in window.stat_mods.caption.text()
    assert "первом запуске" in window.summary_runtime.text()
    window.close()


def test_summary_directory_counts_never_block_the_ui_thread(app, store, inst, monkeypatch):
    main_thread = threading.get_ident()
    release = threading.Event()
    mods_started, worlds_started = threading.Event(), threading.Event()
    worker_threads = []

    def count_mods(root):
        worker_threads.append(threading.get_ident())
        mods_started.set()
        release.wait(2)
        return 2, 3

    def count_worlds(root):
        worker_threads.append(threading.get_ident())
        worlds_started.set()
        release.wait(2)
        return 1

    monkeypatch.setattr(m, "quick_file_counts", count_mods)
    monkeypatch.setattr(m, "quick_world_count", count_worlds)
    started = time.monotonic()
    window = m.MainWindow(store, network_enabled=False)
    try:
        assert time.monotonic() - started < 1.0
        assert mods_started.wait(1) and worlds_started.wait(1)
        assert worker_threads and all(thread_id != main_thread for thread_id in worker_threads)
    finally:
        # Never leave test workers blocked if an assertion fails on a slow runner.
        release.set()
    wait_until(app, lambda: window.stat_mods.value.text() == "2" and window.stat_worlds.value.text() == "1")
    window.close()


def test_catalog_browser_has_a_provider_rail_and_project_details(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    assert set(window.catalog_source_buttons) == {"modrinth", "curseforge"}
    assert window.catalog_splitter.count() == 2
    assert window.mr_results is window.catalog_splitter.widget(0)
    hit = {"provider": "modrinth", "project_id": "iris", "project_type": "shader",
           "slug": "iris", "title": "Iris Shaders", "author": "coderbot",
           "description": "A modern shaders mod.", "downloads": 125}
    window.mr_context = ("modrinth", "iris", "shader", inst)
    window.update_catalog_details(hit)
    assert window.catalog_project_title.text() == "Iris Shaders"
    assert window.catalog_project_author.text() == "coderbot"
    assert "Minecraft" in window.catalog_project_target.text()
    assert window.catalog_project_link.isEnabled()
    assert window.catalog_project_link.property("catalogUrl") == "https://modrinth.com/shader/iris"
    window.close()


def test_catalog_downloaded_icon_updates_results_and_project_details(app, store, inst):
    from PySide6.QtCore import QBuffer, QIODevice

    image = m.QImage(8, 8, m.QImage.Format.Format_ARGB32)
    image.fill(m.QColor(190, 40, 250))
    buffer = QBuffer()
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    payload = bytes(buffer.data())
    buffer.close()

    window = m.MainWindow(store, network_enabled=False)
    url = "https://cdn.modrinth.com/data/sample/icon.png"
    hit = {"provider": "modrinth", "project_id": "sample", "project_type": "mod",
           "title": "Sample", "icon_url": url}
    item = m.QListWidgetItem("Sample")
    item.setData(m.Qt.ItemDataRole.UserRole, hit)
    window.mr_results.addItem(item)
    window.mr_results.setCurrentItem(item)
    window.catalog_icon_loaded(url, payload)

    assert not item.icon().isNull()
    assert item.icon().pixmap(38, 38).toImage().pixelColor(19, 19) == m.QColor(190, 40, 250)
    assert window.catalog_project_icon.pixmap().toImage().pixelColor(18, 18) == m.QColor(190, 40, 250)
    window.close()


def test_catalog_autoloads_popular_mods_when_first_opened(app, store, inst, monkeypatch):
    calls = []

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def search(self, query, kind, profile, offset=0, sort="downloads"):
            calls.append((query, kind, profile.id if profile else None, offset, sort))
            return [{"project_id": "sodium", "title": "Sodium", "project_type": "mod",
                     "description": "Rendering optimization mod"}]

    monkeypatch.setattr(m, "ModrinthClient", Client)
    window = m.MainWindow(store, network_enabled=False)

    def run_task(title, work, done=None, instance_id=""):
        result = work(m.no_progress, None)
        if done:
            done(result)

    monkeypatch.setattr(window, "run_task", run_task)
    window.show_details()
    window.tabs.setCurrentWidget(window.modrinth_tab)

    assert window.mr_type.currentData() == "mod"
    assert window.mr_query.text() == ""
    assert window.mr_filter.isChecked()
    assert window.mr_sort.currentData() == "downloads"
    assert calls == [("", "mod", inst.id, 0, "downloads")]
    assert window.mr_results.count() == 1
    assert window.mr_results.item(0).text().startswith("Sodium")
    assert f"Подбор версии: Minecraft {inst.minecraft}" in window.catalog_project_target.text()
    assert window.mr_install_btn.isEnabled()
    window.close()


def test_curseforge_key_save_is_reused_for_the_local_host_search_and_download(
        app, store, inst, monkeypatch):
    inst = store.update(inst.id, loader="fabric", loader_version="0.16.14")
    window = m.MainWindow(store, network_enabled=False)
    select(window, inst.id)
    dialog = m.SettingsDialog(window)
    dialog.curseforge_key_field.setText("  host-private-key  ")
    dialog.save()
    key = m.Store(store.root).settings["curseforge_api_key"]
    assert key == "host-private-key"

    search_keys = []
    install_keys = []

    class Client:
        def __init__(self, api_key):
            search_keys.append(api_key)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def search(self, query, kind, profile, offset=0, sort="downloads"):
            return [{"provider": "curseforge", "project_id": 42, "project_type": "mod",
                     "title": "Host mod", "description": "", "icon_url": ""}]

    def install(host_instance, project_id, project_type, api_key, **kwargs):
        install_keys.append((host_instance.sync_url, project_id, api_key))
        return ["Host mod"]

    monkeypatch.setattr(m, "CurseForgeClient", Client)
    monkeypatch.setattr(m, "install_curseforge", install)
    monkeypatch.setattr(m, "message", lambda *args, **kwargs: True)
    monkeypatch.setattr(window, "save_current", lambda **kwargs: True)

    def run_task(title, work, done=None, instance_id=""):
        result = work(m.no_progress, None)
        if done:
            done(result)

    monkeypatch.setattr(window, "run_task", run_task)
    window.set_catalog_source("curseforge")
    window.show_details()
    window.tabs.setCurrentWidget(window.modrinth_tab)

    assert window.mr_results.count() == 1
    assert search_keys == [key]
    assert window.current_instance().sync_url == ""
    window.install_selected_modrinth()
    assert install_keys == [("", 42, key)]
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
        def search(self, query, kind, profile, offset=0, sort="downloads"):
            calls.append((offset, sort))
            count = 30 if offset == 0 else 1
            return [{"project_id": str(offset + i), "title": "Mod", "project_type": "mod"} for i in range(count)]
    monkeypatch.setattr(m, "ModrinthClient", Client)
    window = m.MainWindow(store, network_enabled=False)
    def run_task(title, work, done, *args, **kwargs):
        done(work(m.no_progress, None))
    monkeypatch.setattr(window, "run_task", run_task)
    window.mr_sort.setCurrentIndex(window.mr_sort.findData("newest"))
    window.search_modrinth()
    assert window.mr_next.isEnabled() and not window.mr_previous.isEnabled()
    window.change_modrinth_page(1)
    assert calls == [(0, "newest"), (30, "newest")] and window.mr_results.count() == 1
    assert window.mr_context[-1] == "newest"
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
