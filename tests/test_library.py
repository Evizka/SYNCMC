"""Regressions for the missing minecraft_launcher_lib.mod_loader screenshot."""
import importlib
import sys
from types import SimpleNamespace

import pytest

import mcsync as m


def test_explicit_submodule_import_does_not_need_package_reexport(monkeypatch):
    package = importlib.import_module("minecraft_launcher_lib")
    module = importlib.import_module("minecraft_launcher_lib.mod_loader")
    monkeypatch.delattr(package, "mod_loader", raising=False)
    assert not hasattr(package, "mod_loader")
    library = m.launcher_lib()
    assert library.mod_loader is module
    assert m.loader_backend("fabric", library).get_id() == "fabric"


@pytest.mark.parametrize("loader", ["fabric", "quilt", "forge", "neoforge"])
def test_all_real_loader_backends_are_available_offline(loader, monkeypatch):
    monkeypatch.setattr(m.requests, "get", lambda *a, **kw: pytest.fail("No HTTP during backend loading"))
    backend = m.loader_backend(loader)
    assert backend.get_id() == loader
    assert isinstance(backend.get_installed_version("1.21.1", "0.16.14"), str)


def test_startup_runtime_check_does_not_use_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Runtime checking must not download anything")
    monkeypatch.setattr(m.requests, "get", forbidden)
    monkeypatch.setattr(m.requests, "post", forbidden)
    m.check_launcher_library()


def test_missing_submodule_becomes_actionable_source_error(monkeypatch):
    original = m.importlib.import_module
    def importing(name, *args, **kwargs):
        if name == "minecraft_launcher_lib.mod_loader":
            raise ModuleNotFoundError("No module named 'minecraft_launcher_lib.mod_loader'")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(m.importlib, "import_module", importing)
    with pytest.raises(m.UserError, match="pip install") as error:
        m.launcher_lib()
    assert "minecraft-launcher-lib==8.0" in str(error.value)
    assert "minecraft_launcher_lib.mod_loader" in str(error.value)


def test_frozen_error_explains_that_pip_does_not_fix_exe(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(m, "launcher_lib", lambda: SimpleNamespace())
    with pytest.raises(m.UserError) as error:
        m.loader_backend("neoforge")
    assert "_internal" in str(error.value)
    assert "pip не изменяет .exe" in str(error.value)
    assert "pip install" not in str(error.value)


@pytest.mark.parametrize("api", [None, SimpleNamespace(), SimpleNamespace(get_mod_loader=42),
                                 SimpleNamespace(get_mod_loader=lambda key: SimpleNamespace())])
def test_old_or_incomplete_api_is_not_an_attribute_error(api, monkeypatch):
    monkeypatch.setattr(m, "launcher_lib", lambda: SimpleNamespace(mod_loader=api))
    with pytest.raises(m.UserError, match="API"):
        m.loader_backend("fabric")


def test_install_rejects_missing_api_before_changing_instance(store, inst, monkeypatch, snapshot):
    inst = store.update(inst.id, loader="fabric")
    before = snapshot(store.root)
    monkeypatch.setattr(m, "launcher_lib", lambda: SimpleNamespace())
    with pytest.raises(m.UserError, match="8.0"):
        m.ensure_install(store, inst)
    assert snapshot(store.root) == before


def test_unavailable_neoforge_has_clear_dependency_diagnostic(monkeypatch):
    def factory(loader):
        raise ValueError("unknown loader")
    monkeypatch.setattr(m, "launcher_lib", lambda: SimpleNamespace(mod_loader=SimpleNamespace(get_mod_loader=factory)))
    with pytest.raises(m.UserError, match="NeoForge"):
        m.loader_backend("neoforge")


def test_unknown_loader_is_rejected():
    with pytest.raises(m.UserError, match="Неизвестный"):
        m.loader_backend("unknown")
