#!/usr/bin/env python3
"""Capture real Qt UI variants with temporary demo data and NO network calls.

QT_QPA_PLATFORM=offscreen python scripts/preview_designs.py --output designs
Demo JAR placeholders are never shipped in a launcher or source archive.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import mcsync as m


def compare(images: list[tuple[str, str, object]], output: Path, columns: int = 3) -> None:
    rows = (len(images) + columns - 1) // columns
    canvas = m.QImage(columns * 660, rows * 620, m.QImage.Format.Format_RGB32)
    canvas.fill(m.QColor("#e9edf2"))
    painter = m.QPainter(canvas)
    font = m.QFont("DejaVu Sans")
    for index, (title, caption, image) in enumerate(images):
        x, y = (index % columns) * 660 + 10, (index // columns) * 620
        font.setPixelSize(23)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(m.QColor("#1a2535"))
        painter.drawText(m.QRect(x + 10, y + 8, 630, 48), m.Qt.AlignmentFlag.AlignVCenter, title)
        painter.drawImage(m.QRect(x, y + 62, 640, 430), image)
        font.setPixelSize(17)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(m.QColor("#58657a"))
        painter.drawText(m.QRect(x + 10, y + 508, 620, 100), m.Qt.TextFlag.TextWordWrap, caption)
    painter.end()
    if not canvas.save(str(output)):
        raise RuntimeError("Could not save comparison")


def capture(output: Path) -> None:
    if not m.QT_AVAILABLE:
        raise SystemExit("Qt system libraries are required: " + m.QT_IMPORT_ERROR)
    output.mkdir(parents=True, exist_ok=True)
    app = m.QApplication.instance() or m.QApplication([])
    app.setStyle("Fusion")
    images, layouts = [], []
    with tempfile.TemporaryDirectory(prefix="mcsync-design-preview-") as data:
        store = m.Store(data)
        store.settings["reduced_motion"] = True  # Capture settled states; production defaults to motion enabled.
        pack = store.create("Вечерний сервер", minecraft="1.21.1", loader="fabric", loader_version="0.16.14",
                            group="С друзьями", favorite=True, playtime=23.7 * 3600,
                            last_sync_at=time.time(), last_sync_rev="a" * 40,
                            sync_url="http://127.0.0.1:25589/demo-only-preview-token-01",
                            notes="Исследуем мир, строим общую базу и собираемся по вечерам. Перед большим обновлением — бэкап миров.")
        store.create("NeoFactory", minecraft="1.21.1", loader="neoforge", loader_version="21.1.234",
                     favorite=True, group="С друзьями", playtime=8 * 3600)
        store.create("Тихая долина", minecraft="1.20.1", loader="fabric", loader_version="0.16.10", group="Соло")
        store.create("Vanilla", minecraft="1.21.1", group="Соло")
        store.create("Sky Islands", minecraft="1.20.1", loader="quilt", loader_version="0.26.4", group="С друзьями")
        store.create("Уютный мир", minecraft="1.21.1", loader="fabric", loader_version="0.16.14", group="Соло")
        m.Accounts(store).add_offline("Alex")
        store.settings["party_name"] = "Миша"
        demo_room = {"protocol": 1, "rev": "a" * 40,
                     "pack": {"name": pack.name, "minecraft": pack.minecraft, "loader": pack.loader, "loader_version": pack.loader_version},
                     "members": [{"id": "host", "name": "Саша", "role": "host", "state": "launcher", "rev": "a" * 40},
                                 {"id": "b" * 32, "name": "Миша", "role": "friend", "state": "launcher", "rev": "a" * 40},
                                 {"id": "c" * 32, "name": "Ира", "role": "friend", "state": "playing", "rev": "a" * 40}]}

        mods = pack.game_dir / "mods"
        mods.mkdir()
        for filename, size in (("fabric-api-0.102.1+1.21.1.jar", 2600000),
                               ("sodium-fabric-0.6.0+mc1.21.1.jar", 1200000),
                               ("iris-fabric-1.8.0+mc1.21.1.jar", 2400000),
                               ("modmenu-11.0.1.jar", 912000),
                               ("appleskin-fabric-mc1.21-3.0.6.jar", 111000),
                               ("lithium-fabric-mc1.21.1-0.13.1.jar", 612000)):
            (mods / filename).write_bytes(b"MCSync UI preview placeholder\n" + b"\0" * size)
        world = pack.game_dir / "saves" / "Наш общий мир"
        world.mkdir(parents=True)
        (world / "level.dat").write_bytes(b"UI preview placeholder")

        def screenshot(key: str, mode: str, page: str, filename: str, connection: str = "online"):
            window = m.MainWindow(store, network_enabled=False, theme=key, layout=mode)
            # Explicitly synthetic demo presence, just like the demo files/counters above.
            # Production MainWindow never creates or injects online friends.
            state = {"online": True, "supported": True, "room": demo_room, "self_id": "b" * 32,
                     "changed": False, "latency_ms": 12, "checked_at": time.time()}
            if connection == "retry":
                state = {"online": False, "phase": "retry", "changed": None, "retry_seconds": 10}
            window.party_states[pack.id] = state
            window.sync_checks[pack.id] = state
            if connection == "host":
                store.update(pack.id, sync_url="")
                host = m.SyncHost(store, pack.id, port=0)
                host.start(bind="127.0.0.1")
                for peer in demo_room["members"][1:]:
                    host.party.touch(dict(peer, name="Саша" if peer["name"] == "Миша" else peer["name"],
                                          rev=host.manifest()["rev"], lease="d" * 64))
                window.hosts[pack.id] = host
            window.resize(1280, 860)
            window.refresh_instances(pack.id)
            if page == "gallery":
                window.show_library()
            elif page == "mods":
                window.tabs.setCurrentIndex(1)
            elif page == "parameters":
                window.show_overview_page(1)
            else:
                window.show_overview_page(0)
            window.statusBar().showMessage("Предпросмотр оформления · демонстрационные данные · сеть отключена")
            window.show()
            for _ in range(3):
                app.processEvents()
            image = window.grab().toImage()
            if not image.save(str(output / filename)):
                raise RuntimeError("Could not save preview")
            window.close()
            if connection == "host":
                store.update(pack.id, sync_url=pack.sync_url)
            app.processEvents()
            return image

        variants = {"forest": ("gallery", "gallery"), "nord": ("compact", "mods"),
                    "ember": ("comfortable", "summary"), "graphite": ("comfortable", "mods"),
                    "aurora": ("comfortable", "summary"), "paper": ("compact", "parameters")}
        for index, (key, (mode, page)) in enumerate(variants.items()):
            image = screenshot(key, mode, page, f"{key}.png")
            name = m.THEMES[key]["name"].split(" · ")[0]
            images.append((f"{index + 1}. {name}", m.THEMES[key]["description"] + "\n" + m.LAYOUTS[mode], image))
        for mode, page, title, caption in (("gallery", "gallery", "Библиотека карточек", "Полноценная стартовая библиотека: избранное, группы, поиск."),
                                          ("comfortable", "summary", "Комфортный обзор", "Моды, миры, время, синхронизация и готовность к запуску."),
                                          ("compact", "mods", "Компактный режим", "Небольшая шапка и более плотные списки. Для маленьких экранов.")):
            image = screenshot(m.DEFAULT_THEME, mode, page, f"layout-{mode}.png")
            layouts.append((title, caption, image))
        screenshot(m.DEFAULT_THEME, "comfortable", "parameters", "parameters.png")
        screenshot(m.DEFAULT_THEME, "comfortable", "summary", "party-reconnecting.png", "retry")
        screenshot(m.DEFAULT_THEME, "comfortable", "summary", "party-host.png", "host")
    compare(images, output / "options.png")
    compare(layouts, output / "layouts.png")
    print("Captured six real themes and three layouts:", output.resolve())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "designs")
    capture(parser.parse_args().output)
