"""Layout layering guards.

Every page must fit the smallest window the launcher offers. Two defects used to show up as
"overlapping" UI: a container asked to be shorter than its own layout minimum (its children are
then drawn on top of each other), and decoration frames being counted as content. These tests walk
the real widget tree on every page at every supported window size and fail on both.
"""
import pytest

import mcsync as m

pytestmark = pytest.mark.skipif(not m.QT_AVAILABLE, reason="Qt runtime libraries not available")

if m.QT_AVAILABLE:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractScrollArea, QTabBar, QToolButton, QWidget

WINDOW_SIZES = ((1000, 690), (1280, 860), (1600, 1000))
LAYOUTS = ("comfortable", "compact", "gallery")


@pytest.fixture
def window(app, store):
    store.create("Первая", minecraft="1.21.1", loader="neoforge")
    store.create("Вторая", minecraft="1.20.1", group="Пати")
    win = m.MainWindow(store, network_enabled=False, theme="forest", layout="comfortable")
    win.show()
    app.processEvents()
    yield win, app
    win.close()


def arrange(win, app, size, layout):
    win.set_layout_mode(layout)
    win.resize(*size)
    app.processEvents()


def pages(win):
    return {
        "lobby": win.show_lobby,
        "library": win.show_library,
        "overview": lambda: (win.show_details(), win.show_overview_page(0)),
        "parameters": lambda: (win.show_details(), win.show_overview_page(1)),
        "mods": lambda: (win.show_details(), win.tabs.setCurrentIndex(1)),
        "resources": lambda: (win.show_details(), win.tabs.setCurrentIndex(2)),
        "shaders": lambda: (win.show_details(), win.tabs.setCurrentIndex(3)),
        "saves": lambda: (win.show_details(), win.tabs.setCurrentIndex(4)),
        "logs": lambda: (win.show_details(), win.tabs.setCurrentIndex(6)),
        "catalog": lambda: win.show_inline_page(win.catalog_page, title="Каталог модов",
                                                nav_key="library"),
        "party": win.show_party,
        "accounts": win.show_accounts,
        "settings": win.show_settings,
        "diagnostics": win.show_diagnostics,
        "connection-help": win.show_connection_help,
        "lan-properties": win.show_advanced_lan,
        "create-instance": win.create_instance,
        "connect-instance": win.connect_instance,
    }


@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize("size", WINDOW_SIZES)
def test_no_page_squeezes_page_content_below_its_layout_minimum(window, size, layout):
    """A layout smaller than its own minimum stacks its children on top of each other."""
    win, app = window
    arrange(win, app, size, layout)
    failures = []
    for name, open_page in pages(win).items():
        open_page()
        app.processEvents()
        win.repaint()
        app.processEvents()
        page = win.main_pages.currentWidget()
        for widget in page_containers(page):
            layout = widget.layout()
            if layout is None:
                continue
            needed = layout.minimumSize()
            current = widget.size()
            if needed.height() > current.height() + 1 or needed.width() > current.width() + 1:
                failures.append(f"{size[0]}x{size[1]} {layout} {name}: {describe(widget)} is "
                                f"{current.width()}x{current.height()} but its layout needs "
                                f"{needed.width()}x{needed.height()}")
    assert not failures, "squeezed containers:\n" + "\n".join(failures)


@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize("size", WINDOW_SIZES)
def test_no_visible_siblings_overlap_on_any_page(window, size, layout):
    """Siblings sharing a parent must not cover each other; decoration is mouse-transparent."""
    win, app = window
    arrange(win, app, size, layout)
    failures = []
    for name, open_page in pages(win).items():
        open_page()
        app.processEvents()
        win.repaint()
        app.processEvents()
        for parent in [win] + list(win.findChildren(QWidget)):
            if not parent.isVisible() or isinstance(parent, QTabBar):
                # Tab bar scroll arrows are native chrome; the dedicated test below pins
                # their size and behaviour on every platform.
                continue
            children = [child for child in parent.children()
                        if isinstance(child, QWidget) and child.isVisible()
                        and not child.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)]
            for index, first in enumerate(children):
                for second in children[index + 1:]:
                    overlap = first.geometry().intersected(second.geometry())
                    if overlap.width() > 3 and overlap.height() > 3:
                        failures.append(f"{size[0]}x{size[1]} {layout} {name}: {describe(first)} and "
                                        f"{describe(second)} overlap by "
                                        f"{overlap.width()}x{overlap.height()}")
    assert not failures, "overlapping siblings:\n" + "\n".join(sorted(set(failures)))


def page_containers(page):
    """Page content only: the page root and anything inside a scroll area may be clipped."""
    for widget in page.findChildren(QWidget):
        if any(isinstance(parent, QAbstractScrollArea) for parent in ancestors(widget)):
            continue
        if not widget.isVisible():
            continue
        yield widget


def ancestors(widget):
    parent = widget.parentWidget()
    while parent is not None:
        yield parent
        parent = parent.parentWidget()


def describe(widget):
    text = ""
    if hasattr(widget, "text"):
        try:
            text = str(widget.text())[:24]
        except (TypeError, ValueError):
            text = ""
    name = widget.objectName() or "-"
    return f"{type(widget).__name__}#{name}{('=' + text) if text else ''}"


def test_tab_bar_scroll_arrows_stay_small_separate_and_working(app, store):
    """Styled QToolButtons used to grow past the tab bar scroller and cover each other."""
    store.create("Первая", minecraft="1.21.1")
    win = m.MainWindow(store, network_enabled=False, theme="forest")
    win.resize(1000, 690)
    win.show()
    win.show_details()
    app.processEvents()
    bar = win.tabs.tabBar()
    arrows = {button.objectName(): button for button in bar.findChildren(QToolButton)}
    assert set(arrows) == {"ScrollLeftButton", "ScrollRightButton"}
    left, right = arrows["ScrollLeftButton"], arrows["ScrollRightButton"]
    assert right.width() <= 20 and left.width() <= 20
    overlap = left.geometry().intersected(right.geometry())
    assert overlap.width() <= 1 and overlap.height() <= 1
    first_tab_x = bar.tabRect(bar.count() - 1).x()
    right.click()
    app.processEvents()
    assert bar.tabRect(bar.count() - 1).x() < first_tab_x
    left.click()
    app.processEvents()
    # Windows tab bar may need an extra left click to fully restore position.
    if bar.tabRect(bar.count() - 1).x() != first_tab_x:
        left.click()
        app.processEvents()
    assert bar.tabRect(bar.count() - 1).x() == first_tab_x
    win.close()


def test_window_minimum_follows_its_content(app, store):
    """The window must refuse sizes at which its pages would squeeze or overlap."""
    store.create("Первая", minecraft="1.21.1")
    win = m.MainWindow(store, network_enabled=False, theme="forest")
    win.show()
    app.processEvents()
    content = win.centralWidget().layout().minimumSize()
    # Either the content fits the nominal minimum, or the window grew to fit the content;
    # a screen smaller than the content is the only case where the window stays smaller.
    screen = win.screen()
    fits = (win.minimumWidth() >= content.width() or
            win.minimumWidth() >= screen.availableGeometry().width() - 40)
    assert fits
    assert win.minimumHeight() >= win.minimum_window_size.height()
    win.resize(10, 10)
    app.processEvents()
    assert win.width() >= win.minimumWidth() and win.height() >= win.minimumHeight()
    win.close()
