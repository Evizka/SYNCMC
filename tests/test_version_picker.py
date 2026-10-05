"""Minecraft version dropdown: stretchable layout and a non-destructive catalog refresh."""
import time

import pytest

import mcsync as m

pytestmark = pytest.mark.skipif(not m.QT_AVAILABLE, reason="Qt runtime libraries not available")


def wait_until(app, condition, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("GUI task did not complete")


def test_catalog_versions_never_lose_the_saved_choice_without_qt():
    assert m.merge_version_choices([], ["1.7.10"]) == ["1.7.10"]
    assert m.merge_version_choices(["1.21.4"], ["1.7.10"]) == ["1.7.10", "1.21.4"]
    assert m.merge_version_choices(["1.21.4", "1.7.10"], ["1.7.10"]) == ["1.21.4", "1.7.10"]
    assert m.merge_version_choices(["1.21.4"], [None, "", "   "]) == ["1.21.4"]
    assert m.merge_version_choices(None, None) == []


def test_minecraft_dropdown_stretches_with_the_button_pinned_to_the_right(app, store):
    inst = store.create("Наша сборка")
    window = m.MainWindow(store, network_enabled=False)
    window.show()
    window.refresh_instances(inst.id)
    window.show_overview_page(1)
    app.processEvents()
    field, button = window.mc_field, window.mc_versions_btn
    assert field.isVisible() and button.isVisible()

    assert field.sizePolicy().horizontalPolicy() == m.QSizePolicy.Policy.Expanding
    assert button.sizePolicy().horizontalPolicy() == m.QSizePolicy.Policy.Fixed
    assert field.geometry().right() <= button.geometry().left()
    assert field.objectName() == "minecraftVersion"

    start = field.width()
    window.resize(window.width() + 260, window.height())
    app.processEvents()
    assert field.width() > start
    window.close()


def test_refresh_keeps_the_saved_version_visible_and_selectable(app, store, monkeypatch):
    inst = store.create("Старая сборка", minecraft="1.7.10")
    window = m.MainWindow(store, network_enabled=False)
    window.show()
    app.processEvents()
    assert window.mc_field.currentText() == "1.7.10"

    monkeypatch.setattr(m, "fetch_json", lambda session, url, **kwargs: {"versions": [
        {"id": "1.21.4", "type": "release"},
        {"id": "1.21.3", "type": "release"},
        {"id": "24w45a", "type": "snapshot"},
    ]})
    window.fetch_mc_versions()
    wait_until(app, lambda: not window.busy)

    assert m.read_json(store.root / "mc_versions.json") == ["1.21.4", "1.21.3", "24w45a"]
    assert window.mc_field.currentText() == "1.7.10"
    assert window.mc_field.itemText(0) == "1.7.10"
    assert window.mc_field.findText("1.21.4") >= 0
    assert store.load(inst.id).minecraft == "1.7.10"
    assert window.save_current()
    assert store.load(inst.id).minecraft == "1.7.10"
    window.close()


def test_refresh_switching_instances_keeps_each_version_in_the_dropdown(app, store, monkeypatch):
    old = store.create("Old", minecraft="1.7.10")
    new = store.create("New", minecraft="1.21.4")
    monkeypatch.setattr(m, "fetch_json", lambda session, url, **kwargs: {"versions": [
        {"id": "1.21.4", "type": "release"}, {"id": "1.20.1", "type": "release"}]})
    window = m.MainWindow(store, network_enabled=False)
    window.show()
    app.processEvents()

    window.fetch_mc_versions()
    wait_until(app, lambda: not window.busy)
    assert window.mc_field.currentText() in {"1.7.10", "1.21.4"}
    window.refresh_instances(old.id)
    assert window.mc_field.currentText() == "1.7.10" and window.mc_field.findText("1.7.10") >= 0
    window.refresh_instances(new.id)
    assert window.mc_field.currentText() == "1.21.4"
    window.close()
