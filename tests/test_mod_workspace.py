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


def png_bytes(tmp_path, name="pixel.png", color="#3366cc", size=8):
    image = m.QImage(size, size, m.QImage.Format.Format_RGB32)
    image.fill(m.QColor(color))
    target = tmp_path / name
    assert image.save(str(target), "PNG")
    return target.read_bytes()


@pytest.mark.skipif(not m.QT_AVAILABLE, reason="Qt runtime libraries not available")
def test_jar_mod_icon_reads_metadata_icons_and_common_fallbacks(tmp_path):
    art = png_bytes(tmp_path)
    fabric = make_jar(tmp_path / "mods" / "sodium.jar", {
        "fabric.mod.json": json.dumps({"id": "sodium", "name": "Sodium", "version": "0.6.13",
                                       "icon": "assets/sodium/icon.png"}),
        "assets/sodium/icon.png": art,
    })
    quilt = make_jar(tmp_path / "mods" / "qsl.jar", {
        "quilt.mod.json": json.dumps({"id": "qsl", "icon": "assets/qsl/art.png"}),
        "assets/qsl/art.png": art,
    })
    forge = make_jar(tmp_path / "mods" / "jei.jar", {
        "META-INF/mods.toml": 'modLoader="javafml"\n[[mods]]\nmodId="jei"\nlogoFile="META-INF/jei-logo.png"\n',
        "META-INF/jei-logo.png": art,
    })
    legacy = make_jar(tmp_path / "mods" / "old.jar", {
        "mcmod.info": json.dumps([{"name": "Old", "logoFile": "assets/old/logo.png"}]),
        "assets/old/logo.png": art,
    })
    plain = make_jar(tmp_path / "mods" / "plain.jar", {
        "fabric.mod.json": json.dumps({"id": "plain", "name": "Plain", "version": "1.0"}),
        "pack.png": art,
    })
    without_icon = make_jar(tmp_path / "mods" / "bare.jar", {
        "fabric.mod.json": json.dumps({"id": "bare", "name": "Bare", "version": "1.0"}),
    })
    oversized = make_jar(tmp_path / "mods" / "huge.jar", {"icon.png": b"\x89PNG" + b"0" * (1024 * 1024)})
    broken = tmp_path / "mods" / "broken.jar"
    broken.write_bytes(b"not a zip file")

    for jar in (fabric, quilt, forge, legacy, plain):
        icon = m.jar_mod_icon(jar)
        assert icon is not None and not icon.isNull(), jar.name
        assert icon.width() <= 64 and icon.height() <= 64
    assert m.jar_mod_icon(without_icon) is None
    assert m.jar_mod_icon(oversized) is None
    assert m.jar_mod_icon(broken) is None
    assert m.jar_mod_icon(tmp_path / "missing.jar") is None
    # Repeat lookups are answered from the file-stamp cache without new decodes.
    assert m.jar_mod_icon(fabric) is m.jar_mod_icon(fabric)


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


@pytest.mark.skipif(not m.QT_AVAILABLE, reason="Qt runtime libraries not available")
def test_mod_rows_carry_real_icons_and_the_delegate_paints_them(app, store, inst, tmp_path):
    art = png_bytes(tmp_path)
    make_jar(inst.game_dir / "mods" / "sodium.jar", {
        "fabric.mod.json": json.dumps({"id": "sodium", "name": "Sodium", "version": "0.6.13",
                                       "icon": "assets/sodium/icon.png"}),
        "assets/sodium/icon.png": art,
    })
    make_jar(inst.game_dir / "mods" / "plain.jar", {
        "fabric.mod.json": json.dumps({"id": "plain", "name": "Plain", "version": "1.0"}),
    })
    make_jar(inst.game_dir / "mods" / "quiet.jar.disabled", {
        "fabric.mod.json": json.dumps({"id": "quiet", "name": "Quiet", "version": "2.0",
                                       "icon": "icon.png"}),
        "icon.png": art,
    })
    window = m.MainWindow(store, network_enabled=False)
    window.show()
    window.open_manager("mods")
    panel = window.file_panels["mods"]
    wait_until(app, lambda: not panel._dirty and not panel._scan_pending)

    assert panel.list.count() == 3
    rows = {panel.list.item(i).data(int(m.Qt.ItemDataRole.UserRole) + 1)["display_name"]:
            panel.list.item(i).data(int(m.Qt.ItemDataRole.UserRole) + 1) for i in range(3)}
    assert rows["Sodium"]["icon"] is not None and not rows["Sodium"]["icon"].isNull()
    assert rows["Plain"]["icon"] is None
    assert rows["Quiet"]["icon"] is not None and rows["Quiet"]["enabled"] is False
    painted = panel.list.grab().toImage()
    assert not painted.isNull() and painted.width() > 0
    window.close()
