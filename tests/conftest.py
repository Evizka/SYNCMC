import hashlib
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import mcsync as m


@pytest.fixture
def store(tmp_path):
    return m.Store(tmp_path / "data")


@pytest.fixture
def inst(store):
    return store.create("Наша сборка", minecraft="1.20.1")


@pytest.fixture
def manifest():
    def make(files=None, **values):
        data = {"name": "Хост", "minecraft": "1.20.1", "loader": "vanilla",
                "loader_version": "", "server": "", "strict": False, "files": []}
        data.update(values)
        data["files"] = [{"path": path, "sha1": hashlib.sha1(content).hexdigest(), "size": len(content)}
                         for path, content in (files or {}).items()]
        return m.validate_manifest(data)
    return make


@pytest.fixture
def put():
    def write(root, relative, content=b"content"):
        path = Path(root) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path
    return write


@pytest.fixture
def snapshot():
    def snap(root):
        return {p.relative_to(root).as_posix(): p.read_bytes()
                for p in root.rglob("*") if p.is_file()}
    return snap


@pytest.fixture
def app():
    if not m.QT_AVAILABLE:
        pytest.skip("Qt system libraries are unavailable: " + m.QT_IMPORT_ERROR)
    from PySide6.QtWidgets import QApplication
    existing = QApplication.instance()
    application = existing or QApplication([])
    application.setStyle("Fusion")
    application.setStyleSheet(m.STYLE)
    yield application


@pytest.fixture
def host(store, inst, put):
    put(inst.game_dir, "mods/a.jar", b"host mod")
    put(inst.game_dir, "config/settings.toml", b"host config")
    server = m.SyncHost(store, inst.id, port=0)
    server.start(bind="127.0.0.1")
    yield server
    server.stop()
