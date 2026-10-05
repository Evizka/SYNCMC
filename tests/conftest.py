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
    # Closing hides widgets but need not destroy signal cycles. Release each test's
    # Qt windows so later palette changes don't repolish dozens of hidden windows.
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QDialog, QMainWindow
    for widget in application.topLevelWidgets():
        if isinstance(widget, (QMainWindow, QDialog)):
            widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()


@pytest.fixture
def host(store, inst, put):
    put(inst.game_dir, "mods/a.jar", b"host mod")
    put(inst.game_dir, "config/settings.toml", b"host config")
    server = m.SyncHost(store, inst.id, port=0)
    server.start(bind="127.0.0.1")
    yield server
    server.stop()


@pytest.fixture
def loopback_restart(monkeypatch):
    # Sandbox networking may hold an internal-address forwarder briefly after
    # a loopback listener closes. Rebind the SAME interface in these HTTP tests;
    # production SyncHost still defaults to 0.0.0.0 for real friends.
    original = m.SyncHost.start
    monkeypatch.setattr(m.SyncHost, "start", lambda host, bind="0.0.0.0": original(host, bind="127.0.0.1"))


def pytest_runtest_logstart(nodeid, location):
    # Preserve the last active test when a native Qt crash prevents JUnit output.
    if os.environ.get("GITHUB_ACTIONS") == "true":
        path = Path("test-output/pytest-progress.txt")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as progress:
            progress.write(f"START {nodeid}\n")


def pytest_runtest_logreport(report):
    if os.environ.get("GITHUB_ACTIONS") == "true":
        path = Path("test-output/pytest-progress.txt")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as progress:
            progress.write(f"{report.when} {report.outcome} {report.nodeid}\n")
    # Expose real-OS failures via Checks API, even when signed log downloads fail.
    if report.failed and os.environ.get("GITHUB_ACTIONS") == "true":
        text = m.redact(report.longreprtext)[-5500:]
        text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print("::error title=" + report.nodeid.replace(",", " ") + "::" + text, flush=True)
