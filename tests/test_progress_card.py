"""Launch and download progress stays in a compact in-window card, never in a popup."""
import threading
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


def test_progress_card_is_embedded_in_the_main_window(app, store):
    store.create("Наша сборка")
    window = m.MainWindow(store, network_enabled=False)
    window.show()
    app.processEvents()
    card = window.task_card

    assert window.isAncestorOf(card) and card.isVisible()
    assert card.objectName() == "taskProgressCard"
    assert card.stage_label is window.task_label and card.bar is window.progress_bar
    assert card.percent_label is window.task_percent and card.cancel_btn is window.cancel_btn
    assert card.state == "idle" and not card.indicator.isVisible()
    assert not card.indicator.is_animating()
    window.close()


def test_download_task_animates_stage_percent_and_cancel_without_a_popup(app, store, monkeypatch):
    store.create("Наша сборка")
    window = m.MainWindow(store, network_enabled=False)
    window.show()
    app.processEvents()
    card = window.task_card
    top_level = set(app.topLevelWidgets())
    release = threading.Event()

    def work(progress, cancel):
        progress("Загрузка mods/example.jar", 250, 1000)
        cancel.wait(5)
        release.set()
        m.check_cancel(cancel)
        return "done"

    window.run_task("Установка Modrinth", work)
    wait_until(app, lambda: card.percent_label.text() == "25%")
    assert card.property("progressVariant") == "download"
    assert card.is_running() and card.cancel_btn.isVisible() and card.bar.isVisible()
    assert card.indicator.isVisible() and card.indicator.is_animating()
    assert "example.jar" in card.stage_label.text()
    phase = card.indicator.phase
    wait_until(app, lambda: card.indicator.phase != phase)
    assert set(app.topLevelWidgets()) == top_level

    card.cancel_btn.click()
    assert window.task["cancel"].is_set()
    release.set()
    wait_until(app, lambda: not window.busy)
    assert card.state == "cancelled" and not card.is_running()
    assert not card.indicator.is_animating() and not card.cancel_btn.isVisible()
    window.close()


def test_launch_preparation_uses_its_own_variant_with_percentage(app, store):
    store.create("Наша сборка")
    window = m.MainWindow(store, network_enabled=False)
    window.show()
    app.processEvents()
    card = window.task_card
    release = threading.Event()

    def work(progress, cancel):
        progress("Проверка установки…", 500, 1000)
        release.wait(5)
        return "ok"

    window.run_task("Подготовка запуска", work, variant="launch")
    wait_until(app, lambda: card.percent_label.text() == "50%")
    assert card.property("progressVariant") == "launch"
    assert card.variant == "launch"
    assert card.is_running()

    def done(_result):
        assert card.state == "done"
        assert card.property("progressVariant") == "launch"
        assert card.percent_label.text() == "100%"
        assert not card.indicator.isVisible() and not card.cancel_btn.isVisible()

    window.task["done"] = done
    release.set()
    wait_until(app, lambda: not window.busy)
    assert card.state == "done"
    window.close()


def test_progress_card_variants_are_styled_differently():
    css = m.theme_style()
    assert 'QFrame#taskProgressCard[progressVariant="launch"]' in css
    assert 'QFrame#taskProgressCard[progressVariant="download"]' in css
    assert 'QFrame#taskProgressCard[progressState="error"]' in css
    assert "QLabel#taskStage" in css and "QLabel#taskPercent" in css
    assert m.TaskProgressCard.VARIANTS == ("launch", "download")


def test_indicator_keeps_moving_with_reduced_motion(app, store):
    store.create("Наша сборка")
    window = m.MainWindow(store, network_enabled=False)
    window.show()
    app.processEvents()
    app.setProperty("reducedMotion", True)
    try:
        card = window.task_card
        card.begin("download", "Загрузка…")
        assert card.indicator.is_animating()
        phase = card.indicator.phase
        deadline = time.monotonic() + 2
        while card.indicator.phase == phase and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.02)
        assert card.indicator.phase != phase
        card.finish("done")
    finally:
        app.setProperty("reducedMotion", False)
        window.close()
