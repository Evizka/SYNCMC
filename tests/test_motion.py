import time

import pytest

import mcsync as m

pytestmark = pytest.mark.skipif(not m.QT_AVAILABLE, reason="Qt runtime libraries unavailable")


def wait(app, condition):
    until = time.monotonic() + 3
    while time.monotonic() < until:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("Animation did not settle")


def test_page_transition_does_not_change_draft_or_current_page_semantics(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    window.show()
    app.processEvents()
    window.name_field.setText("Unsaved")
    window.show_library()
    assert window.main_pages.currentWidget() is window.library_page
    wait(app, lambda: window.main_pages.transition.state() == m.QPropertyAnimation.State.Stopped)
    assert not window.main_pages.transition_indicator.isVisible()
    assert window.library_page.graphicsEffect() is None
    window.show_details()
    assert window.main_pages.currentWidget() is window.detail_stack
    assert window.name_field.text() == "Unsaved"
    wait(app, lambda: window.main_pages.transition.state() == m.QPropertyAnimation.State.Stopped)
    window.close()


def test_content_tabs_have_clear_vector_icons_and_accessible_descriptions(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    assert window.tabs.count() == len(window.tab_icon_names) == 8
    assert window.tab_icon_names == ["overview", "mods", "resources", "shaders", "worlds", "catalog", "console", "logs"]
    for index in range(window.tabs.count()):
        assert not window.tabs.tabIcon(index).isNull()
        assert window.tabs.tabToolTip(index)
        assert window.tabs.tabWhatsThis(index) == window.tabs.tabToolTip(index)
    assert set(window.nav_buttons) == {"home", "library", "build", "party", "accounts", "settings"}
    assert all(not button.icon().isNull() for button in window.nav_buttons.values())
    assert all(button.text() and button.accessibleName() for button in window.nav_buttons.values())
    assert window.nav_buttons["library"].text() == "Библиотека"
    window.close()


def test_tab_switch_keeps_draft_and_animates_only_the_indicator(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    window.show_details()
    window.show()
    app.processEvents()
    window.notes_field.setPlainText("Keep the unsaved draft")
    window.tabs.setCurrentWidget(window.file_panels["mods"])
    assert window.tabs.currentWidget() is window.file_panels["mods"]
    assert window.tabs.transition.duration() >= 300
    assert window.tabs.transition.targetObject() is window.tabs.tab_motion_indicator
    assert window.tabs.transition.state() == m.QPropertyAnimation.State.Running
    assert window.file_panels["mods"].graphicsEffect() is None
    wait(app, lambda: window.tabs.transition.state() == m.QPropertyAnimation.State.Stopped)
    assert window.notes_field.toPlainText() == "Keep the unsaved draft"
    assert window.tabs.indicator_geometry(window.tabs.currentIndex()) == window.tabs.tab_motion_indicator.geometry()
    window.close()


def test_tab_buttons_are_painted_before_hover_and_pages_have_no_opacity_effect(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    window.show_details()
    window.show()
    app.processEvents()
    panel = window.file_panels["mods"]
    window.tabs.setCurrentWidget(panel)
    wait(app, lambda: window.tabs.transition.state() == m.QPropertyAnimation.State.Stopped)
    app.processEvents()
    assert panel.isVisible() and panel.add_btn.isVisible()
    assert panel.add_btn.hover_amount == 0
    assert panel.graphicsEffect() is None
    assert window.detail_stack.graphicsEffect() is None
    assert window.main_pages.currentWidget().graphicsEffect() is None
    image = panel.add_btn.grab().toImage()
    assert not image.isNull()
    assert image.pixelColor(image.width() // 2, image.height() // 2).alpha() == 255
    window.close()


def test_reduced_motion_persists_and_finishes_active_transitions(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    window.show()
    app.processEvents()
    window.show_library()
    window.show_details()
    window.tabs.setCurrentWidget(window.file_panels["mods"])
    assert window.tabs.transition.state() == m.QPropertyAnimation.State.Running
    dialog = m.SettingsDialog(window)
    dialog.reduced_motion.setChecked(True)
    dialog.save()
    assert m.Store(store.root).settings["reduced_motion"] is True
    assert not m.motion_enabled()
    assert window.main_pages.transition.state() == m.QPropertyAnimation.State.Stopped
    assert not window.main_pages.transition_indicator.isVisible()
    assert window.tabs.transition.state() == m.QPropertyAnimation.State.Stopped
    assert window.tabs.tab_motion_indicator.geometry() == window.tabs.indicator_geometry(window.tabs.currentIndex())
    window.show_details()
    assert window.main_pages.transition.state() == m.QPropertyAnimation.State.Stopped
    window.close()


def test_tool_buttons_share_hover_feedback_without_moving_their_targets(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    window.show_details()
    window.show()
    app.processEvents()
    button = window.more_btn
    original = button.geometry()
    before = button.grab().toImage()
    button.animate_hover(1)
    wait(app, lambda: 0.2 < button.hover_amount < 0.9)
    assert button.grab().toImage() != before
    assert button.geometry() == original
    wait(app, lambda: button.hover_animation.state() == m.QVariantAnimation.State.Stopped)
    window.close()


def test_button_focus_keeps_the_existing_border_without_a_second_frame():
    for theme, colors in m.THEMES.items():
        stylesheet = m.theme_style(theme)
        assert f"QPushButton:focus, QToolButton:focus {{ border-color: {colors['border']}; }}" in stylesheet
        assert "QPushButton#play:focus, QPushButton#primary:focus, QPushButton#lobbyPlay:focus { border: 1px solid transparent; }" in stylesheet
        assert "border: 2px solid" not in stylesheet


def test_hover_mask_uses_the_corner_radius_of_each_button(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    assert window.nav_buttons["home"].property("motionRadius") == 0
    assert window.file_panels["mods"].refresh_btn.property("motionRadius") == 15
    assert window.play_btn.property("motionRadius") == 25
    assert window.lobby_page.configure.property("motionRadius") == 28
    assert window.nav_buttons["home"].motion_corner_radius(m.QRect(0, 0, 120, 40)) == 0
    assert "QPushButton#nav {" in m.theme_style(window.theme)
    assert "border-radius: 0px; background: transparent; color:" in m.theme_style(window.theme)
    window.close()


def test_hover_keeps_button_geometry_and_click_target(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    window.show()
    app.processEvents()
    btn = window.play_btn
    original = btn.geometry()
    btn.animate_hover(1)
    wait(app, lambda: btn.hover_animation.state() == m.QVariantAnimation.State.Stopped)
    assert btn.geometry() == original and btn.hover_amount == 1
    btn.animate_hover(0)
    wait(app, lambda: btn.hover_animation.state() == m.QVariantAnimation.State.Stopped)
    assert btn.geometry() == original and btn.hover_amount == 0
    window.close()


def test_repeated_background_refresh_does_not_restart_page_fade(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    window.show()
    app.processEvents()
    window.show_library()
    wait(app, lambda: window.main_pages.transition.state() == m.QPropertyAnimation.State.Stopped)
    for _ in range(4):
        window.refresh_party_state()
        window.show_library()
    assert window.main_pages.transition.state() == m.QPropertyAnimation.State.Stopped
    window.close()


def test_sidebar_filters_are_optional_but_retain_original_filtering(app, store, inst):
    store.create("Other", group="Friends")
    window = m.MainWindow(store, network_enabled=False)
    window.show()
    app.processEvents()
    assert not window.groups.isVisible()
    window.toggle_filters()
    assert window.groups.isVisible() and window.sort_combo.isVisible()
    window.groups.setCurrentIndex(window.groups.findData("Friends"))
    assert window.instances.count() == 1
    window.toggle_filters()
    assert not window.groups.isVisible()
    window.close()


def test_party_roster_uses_its_own_page_without_horizontal_overflow(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    window.show_party()
    window.show()
    app.processEvents()
    assert window.party_panel.isVisible()
    assert window.party_panel.roster.horizontalScrollBar().maximum() == 0
    window.show_details()
    for i in range(window.tabs.count()):
        window.tabs.setCurrentIndex(i)
        app.processEvents()
        assert not window.party_panel.isVisible()
        assert window.party_panel.roster.horizontalScrollBar().maximum() == 0
    window.close()
