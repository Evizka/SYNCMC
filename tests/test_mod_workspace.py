"""Focused coverage for compact local-mod management and its catalog route."""
import json
import time
import zipfile

import pytest

import mcsync as m


def make_jar(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return path


def test_jar_mod_identity_reads_fabric_metadata_without_extracting(tmp_path):
    jar = make_jar(tmp_path / "mods" / "sodium.jar", {
        "fabric.mod.json": json.dumps({"id": "sodium", "name": "Sodium", "version": "0.6.13"})
    })

    assert m.jar_mod_identity(jar) == ("Sodium", "0.6.13")
    assert not (tmp_path / "mods" / "fabric.mod.json").exists()


def test_jar_mod_identity_reads_forge_metadata_and_handles_invalid_archives(tmp_path):
    forge = make_jar(tmp_path / "mods" / "jei.jar", {
        "META-INF/mods.toml": 'modLoader="javafml"\n[[mods]]\nmodId="jei"\n'
                               'version="19.5.0.33"\ndisplayName="Just Enough Items"\n'
    })
    invalid = tmp_path / "mods" / "broken.jar"
    invalid.write_bytes(b"not a zip file")

    assert m.jar_mod_identity(forge) == ("Just Enough Items", "19.5.0.33")
    assert m.jar_mod_identity(invalid) == ("", "")


def test_jar_mod_identity_ignores_oversized_metadata(tmp_path):
    jar = make_jar(tmp_path / "mods" / "large.jar", {
        "fabric.mod.json": json.dumps({"name": "Too big", "version": "1"}) + " " * (256 * 1024)
    })

    assert m.jar_mod_identity(jar) == ("", "")


def wait_until(app, condition):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("GUI task did not finish")


@pytest.mark.skipif(not m.QT_AVAILABLE, reason="Qt runtime libraries not available")
def test_mod_workspace_uses_compact_rows_and_opens_catalog_in_main_window(app, store, inst, monkeypatch):
    make_jar(inst.game_dir / "mods" / "sodium.jar", {
        "fabric.mod.json": json.dumps({"id": "sodium", "name": "Sodium", "version": "0.6.13"})
    })
    window = m.MainWindow(store, network_enabled=False)
    window.show()
    window.open_manager("mods")
    panel = window.file_panels["mods"]
    wait_until(app, lambda: not panel._dirty and not panel._scan_pending)

    assert panel.list.count() == 1
    assert panel.list.objectName() == "modList"
    assert panel.refresh_btn.isHidden()
    assert panel.add_btn.text() == "Добавить файл"
    assert panel.download_btn.text() == "Скачать моды"
    item = panel.list.item(0)
    data = item.data(int(m.Qt.ItemDataRole.UserRole) + 1)
    assert (data["display_name"], data["version"]) == ("Sodium", "0.6.13")
    assert data["updated"]
    assert "Sodium" in item.text() and "0.6.13" in item.text()

    calls = []
    monkeypatch.setattr(window, "search_catalog", lambda **kwargs: calls.append(kwargs))
    panel.download_btn.click()
    assert window.main_pages.currentWidget() is window.catalog_page
    assert window.inline_returns[window.catalog_page] is window.detail_stack
    assert window.mr_type.currentData() == "mod"
    assert len(calls) == 1
    window.catalog_back_btn.click()
    assert window.main_pages.currentWidget() is window.detail_stack
    assert window.tabs.currentWidget() is panel
    window.close()
