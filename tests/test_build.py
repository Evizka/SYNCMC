import os
import stat
import zipfile

import pytest

from scripts.build import zip_tree


def test_archive_preserves_root_and_executable_mode(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    executable = app / "MCSync"
    executable.write_bytes(b"test executable")
    executable.chmod(0o755)
    target = tmp_path / "app.zip"
    zip_tree(app, target, prefix="MCSync/")
    with zipfile.ZipFile(target) as archive:
        assert archive.read("MCSync/MCSync") == b"test executable"
        if os.name != "nt":
            assert (archive.getinfo("MCSync/MCSync").external_attr >> 16) & 0o111


def test_archive_preserves_macos_style_symlinks(tmp_path):
    app = tmp_path / "app"
    (app / "Versions/A").mkdir(parents=True)
    (app / "Versions/A/binary").write_bytes(b"framework")
    try:
        (app / "Versions/Current").symlink_to("A", target_is_directory=True)
    except OSError:
        pytest.skip("Symlink permission unavailable")
    target = tmp_path / "app.zip"
    zip_tree(app, target)
    with zipfile.ZipFile(target) as archive:
        info = archive.getinfo("Versions/Current")
        assert stat.S_ISLNK(info.external_attr >> 16)
        assert archive.read(info) == b"A"
        assert archive.read("Versions/A/binary") == b"framework"


def test_frozen_build_includes_the_dynamically_imported_loader_api():
    from scripts.build import pyinstaller_command
    command = pyinstaller_command()
    assert command[command.index("--collect-submodules") + 1] == "minecraft_launcher_lib"
    assert command[command.index("--copy-metadata") + 1] == "minecraft-launcher-lib"
    assert "--onedir" in command and command[-1].endswith("mcsync.py")


def test_native_build_bundles_the_local_cinematic_asset():
    from scripts.build import pyinstaller_command
    command = pyinstaller_command()
    data = command[command.index("--add-data") + 1]
    assert data.endswith(os.pathsep + "assets")
    assert "assets" in data


def test_each_theme_has_a_distinct_local_voxel_background():
    import mcsync as m
    paths = {key: m.theme_artwork_path(key) for key in m.THEMES}
    assert len(paths) == 6
    assert len({path.name for path in paths.values()}) == 6
    assert all(path.is_file() and path.stat().st_size > 50_000 for path in paths.values())
    assert paths["paper"].name == "paper-world.jpg"
    assert paths["nord"].name == "nord-world.jpg"


def test_brand_icon_assets_are_available_for_the_ui_and_native_builders():
    from scripts.build import ROOT
    assets = ROOT / "assets"
    assert (assets / "app-icon.png").is_file()
    assert (assets / "app-icon.ico").is_file()
    iconset = assets / "app-icon.icns"
    content = iconset.read_bytes()
    assert content[:4] == b"icns"
    assert int.from_bytes(content[4:8], "big") == len(content)


@pytest.mark.parametrize(("platform", "extension"), (("win32", ".ico"), ("darwin", ".icns")))
def test_native_builder_embeds_platform_icon(monkeypatch, platform, extension):
    import scripts.build as build
    monkeypatch.setattr(build.sys, "platform", platform)
    command = build.pyinstaller_command()
    icon_index = command.index("--icon")
    icon_path = command[icon_index + 1].replace("\\", "/")
    assert icon_path.endswith("assets/app-icon" + extension)
    assert command[-1].endswith("mcsync.py")
