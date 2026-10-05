"""Language preference migrations and English UI strings stay consistent."""
import pytest

import mcsync as m


def test_language_defaults_to_russian_and_survives_settings_reload(tmp_path):
    profile = tmp_path / "profile"
    store = m.Store(profile)
    assert store.settings["language"] == "ru"
    store.save_settings()
    assert m.Store(profile).settings["language"] == "ru"


def test_unknown_saved_language_falls_back_to_russian(tmp_path):
    profile = tmp_path / "profile"
    store = m.Store(profile)
    store.settings["language"] = "xx"
    store.save_settings()

    reopened = m.Store(profile)
    assert reopened.settings["language"] == "ru"


def test_supported_language_keys_are_explicit():
    assert m.language_key("ru") == "ru"
    assert m.language_key("en") == "en"
    for invalid in (None, "", "RU", "fr", 3):
        assert m.language_key(invalid) == "ru"


def test_english_catalog_has_unique_keys_and_no_cyrillic_translations():
    import json
    import re
    from pathlib import Path

    path = Path(m.__file__).resolve().parent / "assets" / "locale" / "en.json"
    pairs = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=list)
    keys = [key for key, _ in pairs]
    assert len(keys) == len(set(keys))
    assert all(isinstance(key, str) and isinstance(value, str) and value
               for key, value in pairs)
    assert all(not re.search(r"[А-Яа-яЁё]", value) for _, value in pairs)


def test_visible_ui_literals_and_templates_have_english_catalog_entries():
    import ast
    import json
    import re
    from pathlib import Path

    root = Path(m.__file__).resolve().parent
    source = (root / "mcsync.py").read_text(encoding="utf-8")
    translations = json.loads((root / "assets" / "locale" / "en.json").read_text(encoding="utf-8"))
    attributes = {"setText", "setWindowTitle", "setToolTip", "setPlaceholderText", "setAccessibleName",
                  "setAccessibleDescription", "setWhatsThis", "setStatusTip", "addTab", "addAction",
                  "addItem", "setItemText", "addRow", "setTabText", "setTabToolTip", "showMessage",
                  "setTitle", "setTextFormat"}
    constructors = {"label", "button", "message", "ElidedLabel", "QCheckBox", "QLabel", "QPushButton",
                    "QToolButton", "QMessageBox", "QComboBox", "QFormLayout"}
    visible, templates = set(), set()

    class Calls(ast.NodeVisitor):
        def visit_Call(self, node):
            function = node.func
            name = function.attr if isinstance(function, ast.Attribute) else function.id if isinstance(function, ast.Name) else ""
            if name in attributes | constructors:
                for child in ast.walk(node):
                    if isinstance(child, ast.Constant) and isinstance(child.value, str) and re.search(r"[А-Яа-яЁё]", child.value):
                        visible.add(child.value)
                    if isinstance(child, ast.JoinedStr):
                        template = "".join(value.value if isinstance(value, ast.Constant) and isinstance(value.value, str)
                                            else "{VAR}" for value in child.values
                                            if isinstance(value, (ast.Constant, ast.FormattedValue)))
                        if re.search(r"[А-Яа-яЁё]", template):
                            templates.add(template)
            self.generic_visit(node)

    Calls().visit(ast.parse(source))
    assert visible <= translations.keys()
    assert templates <= translations.keys()


def test_ui_translation_defaults_to_russian_and_maps_english():
    assert m.translate_ui_text("Библиотека", "ru") == "Библиотека"
    assert m.translate_ui_text("Библиотека", "en") == "Library"


def test_dynamic_ui_templates_keep_values_and_translate_labels():
    assert m.translate_ui_text("Выбрано модов: 3", "en") == "Selected mods: 3"
    assert m.translate_ui_text("Minecraft LAN подтверждён вручную · 25565. MCSync не проверяет и не открывает игровой порт.", "en") == (
        "Minecraft LAN was manually confirmed · 25565. MCSync does not check or open the game port.")
    assert m.translate_ui_text("Скачивание mods/example.jar", "en") == "Downloading mods/example.jar"
    assert m.translate_ui_text("В ИГРЕ  ·  12 мин", "en") == "IN GAME  ·  12 min"
    assert m.translate_ui_text("4 МБ", "en") == "4 MB"
    assert m.translate_ui_text("Создайте группу «Моды»", "en", partial=True) == "Create a group «Mods»"
    assert m.translate_ui_text("Example Mod\nВерсия: 1.2\nИзменён: 2026-10-05\nФайл: mods/example.jar\nРазмер: 4 МБ · включён", "en") == (
        "Example Mod\nVersion: 1.2\nModified: 2026-10-05\nFile: mods/example.jar\nSize: 4 MB · enabled")
    assert m.translate_ui_text("Ответ хоста несовместим или повреждён. Обновите MCSync у обоих участников.", "en") == (
        "The host response is incompatible or damaged. Update MCSync for both players.")


@pytest.mark.skipif(not m.QT_AVAILABLE, reason="Qt runtime libraries not available")
def test_settings_language_switch_translates_and_restores_navigation(app, store):
    window = m.MainWindow(store, network_enabled=False)
    assert window.nav_buttons["library"].text() == "Библиотека"
    source_status = "Автоустановка Java  ·  Vanilla / Fabric / Quilt / Forge / NeoForge"
    window.statusBar().showMessage(source_status)

    english = m.SettingsDialog(window)
    english.language_field.setCurrentIndex(english.language_field.findData("en"))
    english.save()
    assert store.settings["language"] == "en"
    assert window.language == "en"
    assert window.nav_buttons["library"].text() == "Library"
    assert window.settings_btn.text() == "Settings"
    assert english.language_field.currentText() == "English"
    section_labels = {widget.text() for widget in english.findChildren(m.QLabel)}
    assert "Appearance" in section_labels
    assert "Оформление" not in section_labels
    assert window.statusBar().currentMessage() == (
        "Automatic Java installation  ·  Vanilla / Fabric / Quilt / Forge / NeoForge")

    english = m.SettingsDialog(window)
    assert english.language_field.currentData() == "en"
    english.language_field.setCurrentIndex(english.language_field.findData("ru"))
    english.save()
    assert store.settings["language"] == "ru"
    assert window.nav_buttons["library"].text() == "Библиотека"
    assert window.statusBar().currentMessage() == source_status
    window.close()
