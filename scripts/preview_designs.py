#!/usr/bin/env python3
"""Capture the real Qt UI in three themes, using temporary demo data and no network.

QT_QPA_PLATFORM=offscreen python scripts/preview_designs.py --output designs
Demo JAR placeholders are deleted with the temporary directory and never shipped.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import mcsync as m


def capture(output: Path) -> None:
    if not m.QT_AVAILABLE:
        raise SystemExit("Qt system libraries are required: " + m.QT_IMPORT_ERROR)
    output.mkdir(parents=True, exist_ok=True)
    app = m.QApplication.instance() or m.QApplication([])
    app.setStyle("Fusion")
    images = []
    with tempfile.TemporaryDirectory(prefix="mcsync-design-preview-") as data:
        store = m.Store(data)
        pack = store.create("Вечерний сервер", minecraft="1.21.1", loader="fabric", loader_version="0.16.14",
                            group="С друзьями", playtime=23.7 * 3600,
                            sync_url="http://127.0.0.1:25589/" + "demo-only-preview-token-01",
                            notes="Наш общий сервер: исследуем мир, строим базу и собираемся по вечерам.")
        store.create("NeoFactory", minecraft="1.21.1", loader="neoforge", loader_version="21.1.234", group="С друзьями")
        store.create("Тихая долина", minecraft="1.20.1", loader="fabric", loader_version="0.16.10", group="Соло")
        store.create("Vanilla", minecraft="1.21.1", group="Соло")
        m.Accounts(store).add_offline("Alex")
        mods = pack.game_dir / "mods"
        mods.mkdir()
        for filename, size in (("fabric-api-0.102.1+1.21.1.jar", 2600000),
                               ("sodium-fabric-0.6.0+mc1.21.1.jar", 1200000),
                               ("iris-fabric-1.8.0+mc1.21.1.jar", 2400000),
                               ("modmenu-11.0.1.jar", 912000),
                               ("appleskin-fabric-mc1.21-3.0.6.jar", 111000),
                               ("lithium-fabric-mc1.21.1-0.13.1.jar", 612000)):
            # Not real Minecraft mods. Purely local preview placeholders.
            (mods / filename).write_bytes(b"MCSync UI preview placeholder\n" + b"\0" * size)
        for key in m.THEMES:
            window = m.MainWindow(store, network_enabled=False, theme=key)
            window.resize(1280, 860)
            window.refresh_instances(pack.id)
            window.tabs.setCurrentIndex(1)  # actual Mods panel
            window.statusBar().showMessage("Предпросмотр оформления · демонстрационные данные · сеть отключена")
            window.show()
            for _ in range(3):
                app.processEvents()
            image = window.grab().toImage()
            if not image.save(str(output / f"{key}.png")):
                raise RuntimeError("Could not save preview")
            images.append((key, image))
            window.close()
            app.processEvents()

    # A comparison image accompanies the full-resolution individual captures.
    canvas = m.QImage(1980, 660, m.QImage.Format.Format_RGB32)
    canvas.fill(m.QColor("#e9edf2"))
    painter = m.QPainter(canvas)
    font = m.QFont("DejaVu Sans")
    font.setPixelSize(23)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(m.QColor("#1a2535"))
    for index, (key, image) in enumerate(images):
        x = index * 660 + 10
        painter.drawText(m.QRect(x + 10, 10, 630, 50), m.Qt.AlignmentFlag.AlignVCenter,
                         f"{index + 1}. {m.THEMES[key]['name']}")
        painter.drawImage(m.QRect(x, 70, 640, 430), image)
        painter.setPen(m.QColor("#58657a"))
        desc_font = m.QFont(font)
        desc_font.setPixelSize(18)
        desc_font.setBold(False)
        painter.setFont(desc_font)
        painter.drawText(m.QRect(x + 10, 520, 620, 100), m.Qt.TextFlag.TextWordWrap,
                         m.THEMES[key]["description"])
        painter.setFont(font)
        painter.setPen(m.QColor("#1a2535"))
    painter.end()
    canvas.save(str(output / "options.png"))
    print("Captured real UI previews:", output.resolve())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "designs")
    capture(parser.parse_args().output)
