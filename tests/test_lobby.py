import hashlib
import time

import pytest

import mcsync as m

pytestmark=pytest.mark.skipif(not m.QT_AVAILABLE, reason='Qt unavailable')


def test_home_is_one_scene_not_the_management_dashboard(app, store, inst):
    window=m.MainWindow(store,network_enabled=False)
    window.show();app.processEvents()
    assert window.main_pages.currentWidget() is window.lobby_page
    assert not window.header_widget.isVisible()
    assert not window.tabs.isVisible() and not window.party_panel.isVisible()
    assert window.lobby_page.play.isVisible() and window.lobby_page.configure.isHidden()
    assert window.lobby_page.create.isHidden() and window.lobby_page.connect.isHidden()
    assert window.lobby_page.open_library.isHidden()
    assert window.lobby_page.title.text() == inst.name.upper()
    assert not window.lobby_page.artwork.isNull()
    window.close()


def test_side_navigation_opens_content_and_returns_home(app, store, inst):
    window=m.MainWindow(store,network_enabled=False)
    window.show()
    for page in ('mods', 'saves', 'parameters'):
        window.open_manager(page);app.processEvents()
        assert window.main_pages.currentWidget() is window.detail_stack
        assert not window.header_widget.isVisible()
        window.show_lobby();app.processEvents()
        assert window.main_pages.currentWidget() is window.lobby_page
    window.open_manager('party');app.processEvents()
    assert window.main_pages.currentWidget() is window.party_page
    assert window.header_widget.isVisible()
    window.show_lobby();app.processEvents()
    assert window.main_pages.currentWidget() is window.lobby_page
    window.close()


def test_lobby_refreshes_real_ram_account_and_party_state_without_navigating(app, store):
    url='http://host:25589/'+'a'*24
    inst=store.create('Lobby',sync_url=url,ram_max=6144)
    m.Accounts(store).add_offline('VisibleNick')
    window=m.MainWindow(store,network_enabled=False)
    window.show()
    assert '6.0' in window.lobby_page.ram_chip.text()
    assert window.lobby_page.profile.text() == "Аккаунты"
    assert window.lobby_page.profile.isHidden()
    assert not window.lobby_page.party_chip.property('connected')
    window.party_monitor.states[inst.id]={'online':True,'supported':False,'checked_at':time.time(),
        'source':hashlib.sha256(url.encode()).hexdigest()}
    window.refresh_party_state()
    assert window.lobby_page.party_chip.property('connected') is True
    assert window.main_pages.currentWidget() is window.lobby_page
    window.close()


def test_lobby_does_not_discard_unsaved_fields(app, store, inst):
    window=m.MainWindow(store,network_enabled=False)
    window.name_field.setText('Unsaved name')
    window.notes_field.setPlainText('Unsaved note')
    window.show_lobby();window.open_manager('parameters')
    assert window.name_field.text()=='Unsaved name' and window.notes_field.toPlainText()=='Unsaved note'
    assert store.load(inst.id).name==inst.name
    window.close()


def test_no_account_is_an_explicit_next_step_not_a_fake_login(app, store, inst):
    window=m.MainWindow(store,network_enabled=False)
    assert window.lobby_page.profile.text() == "Аккаунты"
    assert window.lobby_page.profile.isHidden()
    assert 'аккаунт' in window.lobby_page.description.text()
    window.close()


def test_lobby_actions_are_capsules_and_reveal_reduced_motion_is_respected(app, store, inst):
    window=m.MainWindow(store,network_enabled=False)
    window.show();app.processEvents()
    assert window.lobby_page.reveal.duration()>=450
    app.setProperty('reducedMotion',True)
    window.lobby_page.animate_reveal()
    assert window.lobby_page.title.reveal_amount==1.0
    css=m.theme_style()
    assert 'QPushButton#lobbyPlay' in css and 'QPushButton#lobbyConfigure' in css
    assert 'border-radius: 28px; min-height: 34px; padding: 12px 30px; font-size: 16px' in css
    assert window.lobby_page.play.minimumWidth() == 184
    assert window.lobby_page.configure.minimumWidth() == 184
    window.close()


def test_empty_search_never_leaves_a_stale_launchable_lobby(app, store, inst):
    window=m.MainWindow(store,network_enabled=False)
    window.show()
    app.processEvents()
    window.search.setText('not present')
    app.processEvents()
    assert window.current_instance() is None
    assert window.main_pages.currentWidget() is window.lobby_page
    assert not window.lobby_page.play.isEnabled()
    assert window.lobby_page.open_library.isVisible()
    assert window.lobby_page.create.isHidden() and window.lobby_page.connect.isHidden()
    window.close()


def test_lobby_background_does_not_restart_reveal_on_every_heartbeat(app, store, inst):
    window=m.MainWindow(store,network_enabled=False)
    window.show();app.processEvents()
    window.show_lobby()
    deadline=time.monotonic()+3
    while window.lobby_page.reveal.state()!=m.QVariantAnimation.State.Stopped and time.monotonic()<deadline:
        app.processEvents();time.sleep(.01)
    for _ in range(5):window.refresh_party_state()
    assert window.lobby_page.reveal.state()==m.QVariantAnimation.State.Stopped
    assert window.lobby_page.title.reveal_amount==1.0
    window.close()
