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
