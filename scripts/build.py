#!/usr/bin/env python3
"""Build a native, unsigned onedir application and a complete distributable ZIP.

Run on the target OS. Windows builds cannot be produced by Linux PyInstaller.
The Qt libraries remain dynamic/replaceable; ship the whole archive, not only .exe.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import os
import platform
import shutil
import stat
import subprocess
import sys
import sysconfig
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
NAME = "MCSync"
DEPENDENCIES = ("PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6",
                "requests", "minecraft-launcher-lib", "certifi", "charset-normalizer",
                "idna", "urllib3", "pyinstaller")


def zip_tree(source: Path, target: Path, prefix: str = "") -> None:
    """Preserve executable permissions and macOS framework symbolic links."""
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for parent, directories, files in os.walk(source, followlinks=False):
            links = [n for n in directories if (Path(parent) / n).is_symlink()]
            for name in sorted(files + links):
                path = Path(parent) / name
                relative = prefix + path.relative_to(source).as_posix()
                if path.is_symlink():
                    info = zipfile.ZipInfo(relative)
                    info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(info, os.readlink(path))
                else:
                    archive.write(path, relative)


def copy_notices(destination: Path) -> None:
    target = destination / "licenses"
    target.mkdir(parents=True, exist_ok=True)
    for name in DEPENDENCIES:
        package = importlib.metadata.distribution(name)
        for entry in package.files or []:
            parts = entry.parts
            basename = entry.name.lower()
            if ((".dist-info" in str(entry) and ("licenses" in parts or basename.startswith(("license", "copying", "notice"))))
                    or (name.startswith("PySide6") and basename.startswith(("license", "copying")))):
                source = Path(package.locate_file(entry))
                if source.is_file():
                    # Keep the original relative hierarchy to avoid license filename collisions.
                    dest = target / name / Path(*entry.parts)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, dest)
    for parent in (Path(sys.base_prefix), Path(sysconfig.get_path("stdlib"))):
        for filename in ("LICENSE.txt", "LICENSE"):
            source = parent / filename
            if source.is_file():
                shutil.copyfile(source, target / "Python-LICENSE.txt")
                break


def pyinstaller_command() -> list[str]:
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
               "--onedir", "--noupx", "--name", NAME,
               "--collect-submodules", "minecraft_launcher_lib", "--collect-data", "minecraft_launcher_lib",
               "--copy-metadata", "minecraft-launcher-lib", "--collect-data", "certifi", "--distpath", str(DIST),
               "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build")]
    if sys.platform == "darwin":
        command += ["--osx-bundle-identifier", "org.syncmc.launcher"]
    command.append(str(ROOT / "mcsync.py"))
    return command


def build(*, smoke: bool = True) -> Path:
    if sys.platform not in ("win32", "linux", "darwin"):
        raise SystemExit("Only Windows, Linux and macOS builds are configured.")
    subprocess.run(pyinstaller_command(), cwd=ROOT, check=True)
    if sys.platform == "darwin":
        application = DIST / f"{NAME}.app"
        executable = application / "Contents" / "MacOS" / NAME
        notices = application / "Contents" / "Resources"
    else:
        application = DIST / NAME
        executable = application / (NAME + (".exe" if sys.platform == "win32" else ""))
        notices = application
    for filename in ("README.md", "QUICKSTART_RU.md", "LICENSE", "THIRD_PARTY.md"):
        shutil.copyfile(ROOT / filename, notices / filename)
    (notices / "source").mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "mcsync.py", notices / "source" / "mcsync.py")
    shutil.copyfile(ROOT / "requirements.txt", notices / "source" / "requirements.txt")
    copy_notices(notices)
    if smoke:
        with tempfile.TemporaryDirectory(prefix="mcsync-build-smoke-") as data:
            env = os.environ.copy()
            env["QT_QPA_PLATFORM"] = "offscreen"
            subprocess.run([str(executable), "--smoke-test", "--data-dir", data],
                           env=env, check=True, timeout=45)
    os_name = {"win32": "windows", "linux": "linux", "darwin": "macos"}[sys.platform]
    machine = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(platform.machine().lower(), platform.machine().lower())
    target = DIST / f"{NAME}-{os_name}-{machine}.zip"
    # Archive one app only; PyInstaller also leaves a redundant onedir on macOS.
    zip_tree(application, target, prefix=application.name + "/")
    checksum = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(target.suffix + ".sha256").write_text(f"{checksum}  {target.name}\n", encoding="utf-8")
    print("Built:", target)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-smoke", action="store_true", help="Skip the frozen GUI startup test")
    build(smoke=not parser.parse_args().no_smoke)
