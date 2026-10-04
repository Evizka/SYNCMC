"""Reference-inspired composition, capsule controls and genuinely visible motion."""
import time
from pathlib import Path

import pytest

import mcsync as m

pytestmark = pytest.mark.skipif(not m.QT_AVAILABLE, reason="Qt libraries unavailable")


def wait(app, condition):
    limit = time.monotonic() + 4
    while time.monotonic() < limit:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("Motion did not settle")


def test_cinematic_artwork_is_local_and_loads_in_native_qt(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    assert not window.hero.artwork.isNull()
    assert window.hero.artwork.width() >= 1200
    assert not m.app_icon().isNull()
    assert m.theme_artwork_path("aurora").name == "aurora-world.jpg"
    assert (Path(m.__file__).resolve().parent / "assets/app-icon.png").is_file()
    assert window.title_label.objectName() == "cinematicTitle"
    window.close()


def test_theme_changes_reload_matching_backgrounds_on_both_screens(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    hero_before = window.hero.artwork.toImage()
    lobby_before = window.lobby_page.artwork.toImage()
    window.set_theme("paper")
    assert window.hero.key == window.lobby_page.key == "paper"
    assert window.hero.artwork.toImage() != hero_before
    assert window.lobby_page.artwork.toImage() != lobby_before
    window.set_theme("forest")
    assert window.hero.key == window.lobby_page.key == "forest"
    assert window.hero.artwork.width() >= 1200 and window.lobby_page.artwork.width() >= 1200
    window.close()


def test_labeled_vertical_navigation_stays_expanded_without_losing_data(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    window.show()
    app.processEvents()
    assert window.sidebar.width() >= 225
    assert window.instances.isVisible() and window.instances.count() == 1
    assert {button.text() for button in window.nav_buttons.values()} >= {
        "Главная", "Библиотека", "Сборка", "Пати", "Аккаунты", "Настройки"}
    assert all(button.height() >= 40 for button in window.nav_buttons.values())
    window.name_field.setText("Keep draft")
    window.nav_buttons["library"].click()
    app.processEvents()
    assert window.main_pages.currentWidget() is window.library_page
    assert window.sidebar.width() >= 225 and window.name_field.text() == "Keep draft"
    assert window.current_id() == inst.id
    window.close()


def test_regular_sections_and_forms_are_embedded_in_the_main_window(app, store):
    window = m.MainWindow(store, network_enabled=False)
    window.show()
    window.show_settings()
    settings = window.main_pages.currentWidget()
    assert isinstance(settings, m.SettingsDialog)
    assert window.main_pages.indexOf(settings) >= 0 and not settings.isWindow()
    assert settings.window() is window
    settings.party_name_field.setText("Keep this draft")
    window.show_settings()
    assert window.main_pages.currentWidget() is settings
    assert settings.party_name_field.text() == "Keep this draft"
    settings.reject()
    app.processEvents()
    assert window.main_pages.currentWidget() is window.lobby_page

    window.show_accounts()
    accounts = window.main_pages.currentWidget()
    assert isinstance(accounts, m.AccountsDialog) and not accounts.isWindow()
    accounts.reject()
    app.processEvents()

    window.show_diagnostics()
    diagnostics = window.main_pages.currentWidget()
    assert isinstance(diagnostics, m.DiagnosticsDialog) and not diagnostics.isWindow()
    diagnostics.reject()
    app.processEvents()

    window.create_instance()
    form = window.main_pages.currentWidget()
    assert isinstance(form, m.NewInstanceDialog) and not form.isWindow()
    form.name.setText("Inline world")
    form.validate_and_accept()
    app.processEvents()
    assert any(item.name == "Inline world" for item in store.list_instances())
    assert window.main_pages.currentWidget() is window.lobby_page

    window.show_party()
    window.show_connection_help()
    help_page = window.main_pages.currentWidget()
    assert isinstance(help_page, m.ConnectionHelpDialog) and not help_page.isWindow()
    window.back_from_subpage()
    assert window.main_pages.currentWidget() is window.party_page
    window.show_host()
    host = window.main_pages.currentWidget()
    assert isinstance(host, m.HostDialog) and not host.isWindow()
    host.reject()
    app.processEvents()
    assert window.main_pages.currentWidget() is window.party_page
    window.close()


def test_gallery_search_remains_available_with_labeled_navigation(app, store, inst):
    store.create("Other")
    window = m.MainWindow(store, network_enabled=False)
    window.show()
    window.focus_library_search()
    app.processEvents()
    assert window.gallery_search is window.search
    assert window.gallery_search.isVisible()
    assert not window.library_page.findChildren(m.QLineEdit)
    assert not window.library_page.findChildren(m.QPushButton)
    window.gallery_search.setText("Other")
    assert window.instances.count() == 1
    assert window.search.text() == "Other"
    window.close()


def test_library_empty_state_replaces_blank_gallery_and_recovers(app, store):
    window = m.MainWindow(store, network_enabled=False, layout="gallery")
    window.show()
    app.processEvents()
    assert window.library_empty.isVisible()
    assert window.library_empty_title.text() == "Библиотека пока пуста"

    store.create("A new build")
    window.refresh_instances()
    assert window.library_grid.isVisible() and window.library_grid.count() == 1
    assert window.library_empty.isHidden()

    window.search.setText("no matching build")
    assert window.library_grid.isHidden()
    assert window.library_empty.isVisible()
    assert window.library_empty_title.text() == "Сборки не найдены"
    window.search.clear()
    assert window.library_grid.isVisible() and window.library_grid.count() == 1
    window.close()


def test_capsule_css_covers_all_native_button_types_and_specific_variants():
    css = m.theme_style()
    for selector in ("QPushButton, QToolButton", "QPushButton#ghost",
                     "QPushButton#primary", "QPushButton#danger", "QPushButton#segment"):
        assert selector in css
    assert "QPushButton#play { padding: 12px 30px; font-size: 16px; border-radius: 25px; min-height: 34px; }" in css
    assert "QPushButton#nav:checked" in css
    assert "padding: 9px 18px; min-height: 28px; font-size: 14px; font-weight: 600;" in css
    assert "QPushButton:hover, QToolButton:hover" in css
    assert "QPushButton#play:focus, QPushButton#primary:focus, QPushButton#lobbyPlay:focus" in css
    assert "QPushButton#play:disabled, QPushButton#primary:disabled, QPushButton#lobbyPlay:disabled" in css


def test_hover_sheen_has_a_visible_intermediate_frame_without_moving_the_target(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    window.show()
    app.processEvents()
    btn = window.play_btn
    before = btn.grab().toImage()
    original = btn.geometry()
    btn.animate_hover(1)
    wait(app, lambda: 0.2 < btn.hover_amount < 0.9)
    middle = btn.grab().toImage()
    assert middle != before and btn.geometry() == original
    assert btn.hover_animation.duration() >= 250
    wait(app, lambda: btn.hover_animation.state() == m.QVariantAnimation.State.Stopped)
    window.close()


def test_press_feedback_is_visible_and_reduced_motion_keeps_controls_usable(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    window.show()
    app.processEvents()
    btn = window.play_btn
    before = btn.grab().toImage()
    btn.animate_press(1)
    wait(app, lambda: btn.press_amount > 0.6)
    assert btn.grab().toImage() != before
    app.setProperty("reducedMotion", True)
    btn.animate_press(0)
    btn.animate_hover(1)
    assert btn.press_amount == 0 and btn.hover_amount == 1
    assert btn.hover_animation.state() == m.QVariantAnimation.State.Stopped
    window.close()


def test_page_motion_is_longer_and_never_hides_page_controls(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    window.show()
    app.processEvents()
    window.show_library()
    assert window.main_pages.transition.duration() >= 350
    assert window.library_page.graphicsEffect() is None
    wait(app, lambda: window.main_pages.transition.state() == m.QPropertyAnimation.State.Stopped)
    assert not window.main_pages.transition_indicator.isVisible()
    window.close()


def test_party_page_uses_the_full_workspace_without_overlapping_controls(app, store):
    store.create("Room", sync_url="http://host:25589/" + "a" * 24)
    window = m.MainWindow(store, network_enabled=False)
    window.resize(1000, 690)
    window.show_party()
    window.show()
    app.processEvents()
    assert window.height() <= 690 and window.width() <= 1000
    assert window.main_pages.currentWidget() is window.party_page
    assert window.party_page.isAncestorOf(window.party_panel)
    assert window.party_page.layout().count() == 2
    assert window.party_panel.layout().itemAt(0).geometry().bottom() < window.party_panel.action.geometry().top()
    window.close()
