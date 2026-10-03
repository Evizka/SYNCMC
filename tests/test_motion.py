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
    assert window.main_pages.effect.opacity() == 1
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
    assert all(button.icon().isNull() is False for button in window.rail_buttons)
    assert all(not button.text() for button in window.rail_buttons)
    window.close()


def test_tab_switch_fades_in_without_discarding_editor_draft(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    window.show_details()
    window.show()
    app.processEvents()
    window.notes_field.setPlainText("Keep the unsaved draft")
    window.tabs.setCurrentWidget(window.file_panels["mods"])
    assert window.tabs.currentWidget() is window.file_panels["mods"]
    assert window.tabs.transition.duration() >= 250
    assert window.tabs.transition.state() == m.QPropertyAnimation.State.Running
    wait(app, lambda: window.tabs.transition.state() == m.QPropertyAnimation.State.Stopped)
    assert window.tabs.effect.opacity() == 1
    assert window.notes_field.toPlainText() == "Keep the unsaved draft"
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
    assert window.main_pages.effect.opacity() == 1
    assert window.tabs.transition.state() == m.QPropertyAnimation.State.Stopped
    assert window.tabs.effect.opacity() == 1
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


def test_party_companion_remains_visible_on_content_tabs(app, store, inst):
    window = m.MainWindow(store, network_enabled=False)
    window.show_details()  # Management keeps the companion; the new home is a single scene.
    window.show()
    app.processEvents()
    for i in range(window.tabs.count()):
        window.tabs.setCurrentIndex(i)
        app.processEvents()
        assert window.party_panel.isVisible()
        assert window.party_panel.roster.horizontalScrollBar().maximum() == 0
    window.close()
