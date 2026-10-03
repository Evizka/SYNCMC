#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""SYNCMC / MCSync — a small Minecraft launcher with friend-to-friend pack sync.

One application file; the core is importable without Qt. No PolyMC source is used.
Run: python mcsync.py. See README.md for networking, authentication and packaging.
"""
from __future__ import annotations

import argparse
import configparser
import contextlib
import copy
import dataclasses
import fnmatch
import hashlib
import hmac
import importlib
import importlib.metadata
import json
import logging
import math
import signal
import os
import re
import secrets
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import requests

APP_NAME = "MCSync"
APP_VERSION = "0.3.1"
LAUNCHER_LIB_VERSION = "8.0"
DEFAULT_THEME = "aurora"
THEMES = {
    "forest": {"name": "Forest · лесной / шалфей", "description": "Тёплый лесной интерфейс, мягкие акценты и спокойная игровая атмосфера.",
               "bg": "#101b17", "sidebar": "#15231d", "surface": "#192b22", "raised": "#24392d",
               "border": "#354d3e", "text": "#edf3e9", "muted": "#a8bdae", "accent": "#aad795",
               "hover": "#c1e9ad", "soft": "#304c34", "on_accent": "#182a1b", "warning": "#e8c080",
               "danger": "#f3a69d", "hero": "#294633", "art": "#89ab72", "art_dark": "#456f51"},
    "nord": {"name": "Nord · северный / ледяной", "description": "Холодный сине-серый интерфейс: хорошо подходит для компактного рабочего режима.",
             "bg": "#17212c", "sidebar": "#1d2b38", "surface": "#233442", "raised": "#2d4050",
             "border": "#3d5466", "text": "#edf3f8", "muted": "#acbfce", "accent": "#93cedf",
             "hover": "#b0e2ed", "soft": "#294b5c", "on_accent": "#152e3a", "warning": "#edc789",
             "danger": "#f2a5af", "hero": "#2b4556", "art": "#86afc4", "art_dark": "#486f8a"},
    "ember": {"name": "Ember · угольный / медный", "description": "Угольный фон, медные акценты и пиксельный закат — более тёплый характер.",
              "bg": "#1c1816", "sidebar": "#251f1b", "surface": "#2c2420", "raised": "#382d26",
              "border": "#4e3d32", "text": "#f6ede4", "muted": "#c6b29e", "accent": "#edb980",
              "hover": "#f5cea1", "soft": "#4a3626", "on_accent": "#312218", "warning": "#efce92",
              "danger": "#f2a49b", "hero": "#4a3528", "art": "#bd8d5d", "art_dark": "#785638"},
    "graphite": {"name": "Graphite · тёмный / зелёный", "description": "Спокойный графит, зелёные акценты и компактная библиотека.",
                 "bg": "#111416", "sidebar": "#191d20", "surface": "#1c2125", "raised": "#242a2f",
                 "border": "#30373d", "text": "#f0f3f4", "muted": "#a1adb4", "accent": "#a4e88e",
                 "hover": "#bdf6ab", "soft": "#293b2a", "on_accent": "#172519", "warning": "#efbd79",
                 "danger": "#f39898", "hero": "#24362b", "art": "#73a96a", "art_dark": "#345b45"},
    "aurora": {"name": "Aurora · тёмный / фиолетовый", "description": "Ночной фиолетовый, лавандовые акценты и более яркий игровой характер.",
               "bg": "#0f111a", "sidebar": "#141722", "surface": "#191d2b", "raised": "#232839",
               "border": "#2b3246", "text": "#f2f4ff", "muted": "#9aa5bd", "accent": "#b9a0ff",
               "hover": "#d4c1ff", "soft": "#3b2d54", "on_accent": "#26183a", "warning": "#edc083",
               "danger": "#f3a0b8", "hero": "#242138", "art": "#7c74b9", "art_dark": "#343e68"},
    "paper": {"name": "Paper · светлый / синий", "description": "Светлый рабочий стол, синие акценты и минимум визуального шума.",
              "bg": "#f1f4f8", "sidebar": "#ffffff", "surface": "#ffffff", "raised": "#f7f9fc",
              "border": "#dce3ec", "text": "#1a2535", "muted": "#61718a", "accent": "#3469df",
              "hover": "#4c7eec", "soft": "#e8effe", "on_accent": "#ffffff", "warning": "#895714",
              "danger": "#b73648", "hero": "#e6edf9", "art": "#9bb6e5", "art_dark": "#708fc0"},
}


LAYOUTS = {"comfortable": "Комфортный · обзор и параметры", "compact": "Компактный · больше информации",
           "gallery": "Карточки · библиотека при запуске"}


def layout_key(value: Any) -> str:
    return value if isinstance(value, str) and value in LAYOUTS else "comfortable"


def theme_key(value: Any) -> str:
    return value if isinstance(value, str) and value in THEMES else DEFAULT_THEME


USER_AGENT = f"SYNCMC/{APP_VERSION} (https://github.com/Evizka/SYNCMC)"
LOADERS = {"vanilla": "Vanilla", "fabric": "Fabric", "quilt": "Quilt",
           "forge": "Forge", "neoforge": "NeoForge"}
SYNC_FOLDERS = ("mods", "config", "resourcepacks", "shaderpacks")
PACK_FOLDERS = (*SYNC_FOLDERS, "saves", "screenshots", "kubejs", "scripts", "defaultconfigs")
PACK_FILES = ("options.txt", "servers.dat", "servers.dat_old")
MAX_FILES = 50_000
MAX_FILE_SIZE = 2 * 1024**3
MAX_PACK_SIZE = 20 * 1024**3
MAX_JSON_SIZE = 16 * 1024**2
TIMEOUT = (8, 45)
Progress = Callable[[str, int, int], None]
LOG = logging.getLogger("mcsync")
INSTALL_LOCK = threading.Lock()
LIB_LOCK = threading.Lock()


class UserError(Exception):
    """An error safe to show to the user (URLs are still redacted by the UI)."""


class Cancelled(UserError):
    pass


def no_progress(message: str, value: int = 0, maximum: int = 0) -> None:
    pass


def check_cancel(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise Cancelled("Операция отменена.")


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".part", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(name)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, json_bytes(value))


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return copy.deepcopy(default)
    if path.stat().st_size > MAX_JSON_SIZE:
        raise UserError(f"Слишком большой JSON: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise UserError(f"Повреждён {path.name}. Сохраните копию файла перед исправлением.") from exc


def sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative_path(value: str) -> str:
    """Portable POSIX path, including Windows ADS/reserved-name protections."""
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise UserError("Некорректный путь файла.")
    if value.startswith("/") or "\\" in value:
        raise UserError(f"Недопустимый путь: {value!r}")
    parts = value.split("/")
    for part in parts:
        if (not part or part in (".", "..") or part.endswith((".", " "))
                or re.search(r'[\x00-\x1f\x7f<>:"|?*]', part)
                or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])", part.split(".")[0])):
            raise UserError(f"Недопустимый путь: {value!r}")
    return value


def safe_join(base: Path | str, relative: str) -> Path:
    """Never creates files. Refuses symlinks, traversal and non-portable paths."""
    relative_path(relative)
    root = Path(base).resolve()
    candidate = root.joinpath(*relative.split("/"))
    part = root
    for component in relative.split("/"):
        part = part / component
        if part.is_symlink():
            raise UserError(f"Символические ссылки не поддерживаются: {relative}")
    if not candidate.resolve().is_relative_to(root):
        raise UserError(f"Путь выходит за каталог сборки: {relative}")
    return candidate


def sync_path(value: str) -> str:
    relative_path(value)
    if value.split("/", 1)[0] not in SYNC_FOLDERS or "/" not in value:
        raise UserError(f"Хост пытается изменить недопустимый файл: {value}")
    return value


def pack_path(value: str) -> str:
    relative_path(value)
    if value.split("/", 1)[0] not in PACK_FOLDERS and value not in PACK_FILES:
        raise UserError(f"Этот файл нельзя импортировать в сборку: {value}")
    return value


def version_id(value: str, allow_auto: bool = False) -> str:
    if allow_auto and value in ("", "auto", "latest", "последняя"):
        return ""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_+.\-]{1,100}", value):
        raise UserError("Некорректный идентификатор версии.")
    relative_path(value)
    return value


def normalize_sync_url(value: str) -> str:
    value = value.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise UserError("Некорректная ссылка синхронизации.") from exc
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or port == 0 or not re.fullmatch(r"/[A-Za-z0-9_\-]{16,128}", parsed.path)):
        raise UserError("Нужна ссылка вида http://адрес:порт/токен (токен не короче 16 символов).")
    return value


def redact(text: str) -> str:
    # A share URL is a bearer credential. Never put its token in logs/errors.
    text = re.sub(r"(https?://[^/\s]+/)[A-Za-z0-9_\-]{16,}(?=/|[\s'\"),]|$)",
                  r"\1[токен скрыт]", str(text))
    # urllib3 also formats connection errors as "url: /TOKEN/manifest.json".
    return re.sub(r"/[A-Za-z0-9_\-]{16,}(?=/(?:manifest\.json|files/|party(?:\.json|/)))",
                  "/[токен скрыт]", text)


def human_size(size: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            return f"{size:.1f} {unit}" if unit != "Б" else f"{int(size)} Б"
        size /= 1024
    return ""


def default_home() -> Path:
    if os.environ.get("MCSYNC_HOME"):
        return Path(os.environ["MCSYNC_HOME"]).expanduser()
    executable_dir = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    if (executable_dir / "portable.txt").exists():
        return executable_dir / "data"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "mcsync"


@dataclass
class Instance:
    id: str
    name: str
    minecraft: str = "1.21.1"
    loader: str = "vanilla"
    loader_version: str = ""
    group: str = ""
    notes: str = ""
    java: str = ""
    ram_min: int = 512
    ram_max: int = 4096
    jvm_args: str = ""
    pre_command: str = ""
    post_command: str = ""
    width: int = 1280
    height: int = 720
    server: str = ""
    playtime: float = 0.0
    favorite: bool = False
    last_played: float = 0.0
    last_sync_at: float = 0.0
    sync_url: str = ""
    sync_mode: str = "version"
    last_sync_rev: str = ""
    created_at: float = field(default_factory=time.time)
    directory: Path = field(default_factory=Path, repr=False, compare=False)

    @property
    def game_dir(self) -> Path:
        return self.directory / "game"

    @property
    def identity(self) -> tuple[str, str, str]:
        return self.minecraft, self.loader, self.loader_version if self.loader != "vanilla" else ""

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in dataclasses.fields(self) if f.name != "directory"}

    def validate(self) -> None:
        strings = ("id", "name", "minecraft", "loader", "loader_version", "group", "notes", "java",
                   "jvm_args", "pre_command", "post_command", "server", "sync_url", "sync_mode", "last_sync_rev")
        if any(not isinstance(getattr(self, key), str) for key in strings):
            raise UserError("Текстовые поля сборки должны быть строками.")
        if any(type(getattr(self, key)) is not int for key in ("ram_min", "ram_max", "width", "height")):
            raise UserError("Память и размер окна должны быть целыми числами.")
        if type(self.favorite) is not bool:
            raise UserError("Некорректное поле избранного.")
        for key in ("playtime", "last_played", "last_sync_at", "created_at"):
            value = getattr(self, key)
            limit = 10**10 if key == "playtime" else 4102444800
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= limit:
                raise UserError("Некорректное время в метаданных сборки.")
        if len(self.group) > 200 or len(self.notes) > 100_000:
            raise UserError("Слишком длинная группа или заметка.")
        if not re.fullmatch(r"[a-f0-9]{32}", self.id):
            raise UserError("Некорректный ID сборки.")
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 200:
            raise UserError("Название сборки должно содержать от 1 до 200 символов.")
        self.minecraft = version_id(self.minecraft)
        if self.loader not in LOADERS:
            raise UserError("Неизвестный загрузчик.")
        self.loader_version = "" if self.loader == "vanilla" else version_id(self.loader_version, True)
        if self.sync_url:
            self.sync_url = normalize_sync_url(self.sync_url)
        if self.sync_mode not in ("ask", "version", "auto"):
            raise UserError("Неизвестный режим синхронизации.")
        if not (256 <= self.ram_min <= self.ram_max <= 131072):
            raise UserError("RAM: минимум 256 МБ; минимальная память не больше максимальной.")
        if not (320 <= self.width <= 16384 and 240 <= self.height <= 16384):
            raise UserError("Некорректный размер окна.")
        if not isinstance(self.server, str) or len(self.server) > 255 or any(c.isspace() for c in self.server):
            raise UserError("Адрес сервера не должен содержать пробелы.")


def backup_private_file(source: Path) -> Path | None:
    """Never overwrite a damaged user file before making a private recovery copy."""
    if not source.exists():
        return None
    if source.is_symlink() or not source.is_file():
        raise UserError(f"Нельзя перезаписать необычный файл {source.name}.")
    recovery = source.parent / "recovery"
    if recovery.is_symlink():
        raise UserError("Папка восстановления не должна быть символической ссылкой.")
    recovery.mkdir(exist_ok=True)
    target = recovery / f"{source.stem}-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}{source.suffix}"
    shutil.copy2(source, target)
    if os.name != "nt":
        target.chmod(0o600)
    return target


class Store:
    """All private data is outside the source/executable by default."""
    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self.instances_dir = self.root / "instances"
        self.minecraft_dir = self.root / "minecraft"
        self.temp_dir = self.root / "temp"
        self.lock = threading.RLock()
        self._locks: dict[str, threading.RLock] = {}
        for directory in (self.root, self.instances_dir, self.minecraft_dir, self.temp_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.instance_errors: dict[str, str] = {}
        self.settings_error = ""
        self.settings = {"client_id": "", "default_ram": 4096, "theme": DEFAULT_THEME,
                         "layout": "comfortable", "sort": "favorite", "last_instance": ""}
        try:
            saved = read_json(self.root / "settings.json", {})
            if not isinstance(saved, dict):
                raise UserError("Некорректный settings.json.")
            self.settings.update(saved)
        except UserError as exc:
            self.settings_error = str(exc)
        ram = self.settings.get("default_ram")
        if type(ram) is not int or not 256 <= ram <= 131072:
            self.settings["default_ram"] = 4096
            self.settings_error = self.settings_error or "Некорректная RAM в settings.json; временно используется 4096 МБ."
        if not isinstance(self.settings.get("client_id"), str):
            self.settings["client_id"] = ""
            self.settings_error = self.settings_error or "Некорректный Client ID в settings.json."
        try:
            self.settings["party_name"] = party_name(self.settings.get("party_name", ""))
        except UserError:
            self.settings["party_name"] = ""
            self.settings_error = self.settings_error or "Некорректное имя в пати; задайте его в настройках."
        if type(self.settings.get("reduced_motion", False)) is not bool:
            self.settings["reduced_motion"] = False
            self.settings_error = self.settings_error or "Некорректное значение анимаций; используется обычный режим."
        self.settings["theme"] = theme_key(self.settings.get("theme"))
        self.settings["layout"] = layout_key(self.settings.get("layout"))
        if self.settings.get("sort") not in ("name", "recent", "favorite"):
            self.settings["sort"] = "favorite"

    def instance_lock(self, instance_id: str) -> threading.RLock:
        with self.lock:
            return self._locks.setdefault(instance_id, threading.RLock())

    def save_settings(self) -> None:
        with self.lock:
            if self.settings_error:
                backup_private_file(self.root / "settings.json")
            atomic_json(self.root / "settings.json", self.settings)
            self.settings_error = ""

    def load(self, instance_id: str) -> Instance:
        if not re.fullmatch(r"[a-f0-9]{32}", instance_id):
            raise UserError("Некорректный ID сборки.")
        directory = safe_join(self.instances_dir, instance_id)
        value = read_json(directory / "instance.json")
        if not isinstance(value, dict) or value.get("id") != instance_id or not isinstance(value.get("name"), str):
            raise UserError(f"Не удалось прочитать сборку {instance_id}.")
        fields = {f.name for f in dataclasses.fields(Instance)} - {"directory"}
        inst = Instance(**{k: v for k, v in value.items() if k in fields}, directory=directory)
        inst.validate()
        return inst

    def list_instances(self) -> list[Instance]:
        result = []
        errors = {}
        for directory in sorted(self.instances_dir.iterdir()):
            if directory.is_dir() and re.fullmatch(r"[a-f0-9]{32}", directory.name):
                try:
                    result.append(self.load(directory.name))
                except (UserError, OSError, TypeError, ValueError) as exc:
                    errors[directory.name] = redact(str(exc))
        self.instance_errors = errors
        return sorted(result, key=lambda inst: (inst.group.casefold(), inst.name.casefold()))

    def save(self, inst: Instance) -> None:
        inst.validate()
        expected = safe_join(self.instances_dir, inst.id)
        if inst.directory.resolve() != expected:
            raise UserError("Каталог сборки не принадлежит хранилищу.")
        with self.lock:
            atomic_json(expected / "instance.json", inst.to_dict())

    def update(self, instance_id: str, **values: Any) -> Instance:
        with self.lock:
            inst = self.load(instance_id)
            for key, value in values.items():
                if key in ("id", "directory") or not hasattr(inst, key):
                    raise UserError("Недопустимое поле сборки.")
                setattr(inst, key, value)
            self.save(inst)
            return inst

    def create(self, name: str, **values: Any) -> Instance:
        instance_id = uuid.uuid4().hex
        values.setdefault("ram_max", int(self.settings.get("default_ram", 4096)))
        inst = Instance(id=instance_id, name=name.strip(), directory=self.instances_dir / instance_id, **values)
        inst.validate()
        inst.game_dir.mkdir(parents=True)
        self.save(inst)
        return inst

    def copy_instance(self, source: Instance, name: str) -> Instance:
        inst = dataclasses.replace(source, id=uuid.uuid4().hex, name=name.strip(), sync_url="",
                                   last_sync_rev="", last_sync_at=0, last_played=0, favorite=False, playtime=0, created_at=time.time())
        inst.directory = self.instances_dir / inst.id
        inst.validate()
        stage = Path(tempfile.mkdtemp(prefix="copy-", dir=self.temp_dir))
        try:
            copy_tree_safe(source.game_dir, stage / "game")
            tracker = source.directory / "modrinth.json"
            if tracker.exists():
                shutil.copyfile(tracker, stage / tracker.name)
            atomic_json(stage / "instance.json", inst.to_dict())
            os.replace(stage, inst.directory)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        return inst

    def delete(self, inst: Instance) -> None:
        expected = safe_join(self.instances_dir, inst.id)
        if inst.directory.resolve() != expected:
            raise UserError("Недопустимый каталог сборки.")
        shutil.rmtree(expected)


def iter_files(root: Path) -> list[tuple[str, Path]]:
    if root.is_symlink():
        raise UserError(f"Символические ссылки не поддерживаются: {root.name}")
    if not root.exists():
        return []
    result = []
    for parent, directories, names in os.walk(root, followlinks=False):
        for name in [*directories, *names]:
            if (Path(parent) / name).is_symlink():
                raise UserError(f"Символические ссылки не поддерживаются: {name}")
        for name in names:
            path = Path(parent) / name
            relative = path.relative_to(root).as_posix()
            safe_join(root, relative)
            if not path.is_file():
                raise UserError(f"Необычный тип файла: {relative}")
            result.append((relative, path))
    return sorted(result)


def copy_tree_safe(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for relative, path in iter_files(source):
        target = safe_join(destination, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def backup_worlds(inst: Instance, world: str | None = None, *,
                  progress: Progress = no_progress, cancel: threading.Event | None = None) -> Path | None:
    check_cancel(cancel)
    saves = inst.game_dir / "saves"
    if world is not None:
        relative_path(world)
        if "/" in world:
            raise UserError("Нужна папка одного мира.")
        saves = safe_join(saves, world)
    files = iter_files(saves)
    if not files:
        return None
    backups = inst.directory / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    target = backups / f"saves-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}.zip"
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            total = sum(path.stat().st_size for _, path in files)
            done = 0
            for relative, path in files:
                check_cancel(cancel)
                info = zipfile.ZipInfo.from_file(path, f"{world}/{relative}" if world else relative)
                info.compress_type = zipfile.ZIP_DEFLATED
                with path.open("rb") as source, archive.open(info, "w", force_zip64=True) as destination:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        check_cancel(cancel)
                        destination.write(chunk)
                        done += len(chunk)
                        progress(f"Бэкап миров: {relative}", done, total)
            check_cancel(cancel)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


class BoundedSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.headers["User-Agent"] = USER_AGENT

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", TIMEOUT)
        return super().request(method, url, **kwargs)


class LibraryRequests:
    """Bound third-party HTTP waits without monkeypatching requests globally."""
    Session = BoundedSession
    session = BoundedSession

    def __getattr__(self, name: str) -> Any:
        if name in ("get", "post", "put", "delete", "head", "request"):
            def call(*args: Any, **kwargs: Any) -> requests.Response:
                kwargs.setdefault("timeout", TIMEOUT)
                return getattr(requests, name)(*args, **kwargs)
            return call
        return getattr(requests, name)


@dataclass(frozen=True)
class LauncherLibrary:
    """Explicit submodules, not the optional re-exports of the package root."""
    command: Any
    install: Any
    runtime: Any
    java_utils: Any
    mod_loader: Any


def library_error(detail: str) -> UserError:
    try:
        installed = importlib.metadata.version("minecraft-launcher-lib")
    except importlib.metadata.PackageNotFoundError:
        installed = "не установлена / не включена в архив"
    text = (f"Не удалось загрузить API minecraft-launcher-lib. Версия: {installed}.\n"
            f"{detail}\n\n")
    if getattr(sys, "frozen", False):
        text += ("Эта сборка приложения неполная или устарела. Скачайте новый архив MCSync "
                 "и распакуйте его целиком, включая _internal. Установка через pip не изменяет .exe.")
    else:
        text += (f"Установите зависимости в тот же Python, которым запускается лаунчер:\n"
                 f'python -m pip install --upgrade "minecraft-launcher-lib=={LAUNCHER_LIB_VERSION}"\n'
                 "Либо: python -m pip install -r requirements.txt")
    return UserError(text)


def launcher_lib() -> LauncherLibrary:
    with LIB_LOCK:
        modules = {}
        for name in ("command", "install", "runtime", "java_utils", "mod_loader"):
            qualified = "minecraft_launcher_lib." + name
            try:
                modules[name] = importlib.import_module(qualified)
            except ImportError as exc:
                raise library_error(f"Недоступен модуль {qualified}: {exc}") from exc
        facade = LibraryRequests()
        for name, module in list(sys.modules.items()):
            if name.startswith("minecraft_launcher_lib") and getattr(module, "requests", None) is requests:
                module.requests = facade
        return LauncherLibrary(**modules)


def loader_backend(loader_id: str, lib: Any = None) -> Any:
    if loader_id not in LOADERS or loader_id == "vanilla":
        raise UserError(f"Неизвестный мод-загрузчик: {loader_id}")
    lib = lib if lib is not None else launcher_lib()
    factory = getattr(getattr(lib, "mod_loader", None), "get_mod_loader", None)
    if not callable(factory):
        raise library_error("API mod_loader.get_mod_loader доступен начиная с версии 8.0.")
    try:
        backend = factory(loader_id)
    except (ValueError, KeyError) as exc:
        raise library_error(f"В библиотеке отсутствует загрузчик {LOADERS[loader_id]}.") from exc
    required = ("get_loader_versions", "get_installed_version", "install")
    if not all(callable(getattr(backend, name, None)) for name in required):
        raise library_error(f"Неполный API загрузчика {LOADERS[loader_id]}.")
    return backend


def check_launcher_library() -> None:
    """Offline startup/frozen-build check. Never downloads Minecraft or Java."""
    lib = launcher_lib()
    required = {"command": ("get_minecraft_command",), "install": ("install_minecraft_version",),
                "runtime": ("get_version_runtime_information", "get_executable_path", "install_jvm_runtime"),
                "java_utils": ("find_system_java_versions_information",)}
    for module, methods in required.items():
        if not all(callable(getattr(getattr(lib, module, None), name, None)) for name in methods):
            raise library_error(f"Неполный API модуля {module}.")
    for loader_id in LOADERS:
        if loader_id != "vanilla":
            loader_backend(loader_id, lib)


def resolve_loader_version(inst: Instance, *, backend: Any = None) -> str:
    if inst.loader == "vanilla":
        return ""
    if inst.loader_version:
        return version_id(inst.loader_version)
    loader = backend if backend is not None else loader_backend(inst.loader)
    # Forge's library adapter may return oldest-first; sort its numeric builds.
    versions = loader.get_loader_versions(inst.minecraft, True)
    if not versions:
        versions = loader.get_loader_versions(inst.minecraft, False)
    if not versions:
        raise UserError(f"{LOADERS[inst.loader]} не поддерживает Minecraft {inst.minecraft}.")
    if inst.loader == "forge":
        versions = sorted(versions, key=lambda v: tuple(int(x) for x in re.findall(r"\d+", v)), reverse=True)
    return version_id(versions[0])


def fetch_json(session: requests.Session, url: str, **kwargs: Any) -> Any:
    with session.get(url, stream=True, **kwargs) as response:
        response.raise_for_status()
        data = bytearray()
        for chunk in response.iter_content(64 * 1024):
            data.extend(chunk)
            if len(data) > MAX_JSON_SIZE:
                raise UserError("Сервер прислал слишком большой JSON.")
    try:
        return json.loads(data)
    except (ValueError, UnicodeError) as exc:
        raise UserError("Сервер прислал некорректный JSON.") from exc


def download_file(url: str, target: Path, *, sha1: str = "", size: int | None = None,
                  sha512: str = "", headers: dict[str, str] | None = None,
                  session: requests.Session | None = None, progress: Progress = no_progress,
                  cancel: threading.Event | None = None) -> None:
    """Write .part, verify both length and hash, only then replace the destination."""
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise UserError("Недопустимый URL скачивания.")
    if size is not None and (type(size) is not int or not 0 <= size <= MAX_FILE_SIZE):
        raise UserError("Недопустимый размер скачивания.")
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    own_session = session is None
    session = session or BoundedSession()
    digest, strong_digest = hashlib.sha1(), hashlib.sha512()
    total = 0
    try:
        check_cancel(cancel)
        with session.get(url, stream=True, headers=headers or {}) as response:
            response.raise_for_status()
            if parsed.scheme == "https" and urlsplit(response.url).scheme != "https":
                raise UserError("Сервер перенаправил HTTPS-скачивание на незащищённый адрес.")
            with part.open("wb") as stream:
                for chunk in response.iter_content(256 * 1024):
                    check_cancel(cancel)
                    total += len(chunk)
                    if total > (size if size is not None else MAX_FILE_SIZE):
                        raise UserError(f"Размер {target.name} больше заявленного.")
                    stream.write(chunk)
                    digest.update(chunk)
                    strong_digest.update(chunk)
                    progress(target.name, total, size or 0)
                stream.flush()
                os.fsync(stream.fileno())
        if size is not None and total != size:
            raise UserError(f"{target.name}: скачан не весь файл.")
        if sha1 and not hmac.compare_digest(digest.hexdigest(), sha1.lower()):
            raise UserError(f"{target.name}: SHA-1 не совпадает. Хост мог изменить сборку; повторите синхронизацию.")
        if sha512 and not hmac.compare_digest(strong_digest.hexdigest(), sha512.lower()):
            raise UserError(f"{target.name}: SHA-512 не совпадает.")
        check_cancel(cancel)
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)
        if own_session:
            session.close()


def fingerprint(root: Path, relative: str) -> str | None:
    path = safe_join(root, relative)
    if not path.exists():
        return None
    if not path.is_file():
        raise UserError(f"Вместо файла обнаружен каталог: {relative}")
    return sha1_file(path)


class FileTransaction:
    """Stage downloads first; roll back files AND metadata on commit failure.

    A persistent journal also allows recovery after the launcher/OS is killed.
    A world backup is separate and survives both a rollback and a successful sync.
    """
    META_NAMES = {"instance.json", "sync_state.json", "modrinth.json"}

    def __init__(self, inst: Instance):
        self.inst = inst
        self.stage = inst.directory / f".transaction-{uuid.uuid4().hex}"
        self.stage.mkdir(parents=True)
        self.keep = False

    def __enter__(self) -> FileTransaction:
        return self

    def staged_path(self, relative: str) -> Path:
        return safe_join(self.stage / "downloads", relative)

    def commit(self, replacements: dict[str, Path], deletions: list[str],
               metadata: dict[str, Any], expected: dict[str, str | None],
               cancel: threading.Event | None = None) -> None:
        paths = sorted(set(replacements) | set(deletions))
        if not set(metadata).issubset(self.META_NAMES):
            raise UserError("Недопустимые метаданные транзакции.")
        for path in paths:
            pack_path(path)
            if path not in expected or fingerprint(self.inst.game_dir, path) != expected[path]:
                raise UserError(f"{path} изменился во время операции. Повторите её, чтобы не потерять изменения.")
        actions = []
        for relative in paths:
            source = replacements.get(relative)
            if source is not None and (not source.is_file() or not source.resolve().is_relative_to(self.stage)):
                raise UserError("Файл скачивания не принадлежит транзакции.")
            actions.append({"path": relative, "old": expected[relative],
                            "new": sha1_file(source) if source else None})
        old_metadata = {}
        for name in metadata:
            original = self.inst.directory / name
            old_metadata[name] = original.exists()
            if original.exists():
                backup = self.stage / "metadata" / name
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original, backup)
        journal = {"phase": "applying", "actions": actions, "metadata": old_metadata}
        check_cancel(cancel)
        atomic_json(self.stage / "journal.json", journal)
        try:
            for relative in paths:
                check_cancel(cancel)
                target = safe_join(self.inst.game_dir, relative)
                if target.exists():
                    original = safe_join(self.stage / "originals", relative)
                    original.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(target, original)
                if relative in replacements:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(replacements[relative], target)
            check_cancel(cancel)
            for name, value in metadata.items():
                atomic_json(self.inst.directory / name, value)
            journal["phase"] = "committed"
            atomic_json(self.stage / "journal.json", journal)
        except BaseException:
            try:
                self.recover(self.inst, self.stage)
            except BaseException as exc:
                self.keep = True
                raise UserError(f"Не удалось завершить откат. Не запускайте игру. "
                                f"Каталог восстановления: {self.stage}") from exc
            raise

    @classmethod
    def recover(cls, inst: Instance, stage: Path) -> None:
        journal = read_json(stage / "journal.json", None)
        if journal is None or journal.get("phase") == "committed":
            return
        for action in reversed(journal["actions"]):
            relative = pack_path(action["path"])
            target = safe_join(inst.game_dir, relative)
            original = safe_join(stage / "originals", relative)
            if original.exists():
                if target.exists() and fingerprint(inst.game_dir, relative) not in (action["new"], action["old"]):
                    raise UserError(f"Файл {relative} изменён после сбоя; нужен ручной откат.")
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(original, target)
            elif action["old"] is None:
                if target.exists():
                    if fingerprint(inst.game_dir, relative) != action["new"]:
                        raise UserError(f"Файл {relative} изменён после сбоя; нужен ручной откат.")
                    target.unlink()
            elif fingerprint(inst.game_dir, relative) != action["old"]:
                raise UserError(f"Не найден оригинал {relative}; нужен ручной откат.")
        for name, existed in journal["metadata"].items():
            if name not in cls.META_NAMES:
                raise UserError("Некорректный журнал восстановления.")
            if existed:
                atomic_bytes(inst.directory / name, (stage / "metadata" / name).read_bytes())
            else:
                (inst.directory / name).unlink(missing_ok=True)
        journal["phase"] = "rolled_back"
        atomic_json(stage / "journal.json", journal)

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if not self.keep:
            shutil.rmtree(self.stage, ignore_errors=True)


def recover_transactions(store: Store) -> int:
    recovered = 0
    for inst in store.list_instances():
        for stage in inst.directory.iterdir():
            if stage.is_dir() and re.fullmatch(r"\.transaction-[a-f0-9]{32}", stage.name):
                if stage.is_symlink():
                    raise UserError("Каталог восстановления не может быть символической ссылкой.")
                FileTransaction.recover(inst, stage)
                shutil.rmtree(stage)
                recovered += 1
    return recovered


def manifest_revision(manifest: dict[str, Any]) -> str:
    identity = {key: manifest[key] for key in
                ("minecraft", "loader", "loader_version", "server", "strict", "files")}
    return hashlib.sha1(json.dumps(identity, sort_keys=True, ensure_ascii=False,
                                  separators=(",", ":")).encode("utf-8")).hexdigest()


def validate_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise UserError("Манифест сборки должен быть JSON-объектом.")
    name = value.get("name", "Сборка друга")
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        raise UserError("Некорректное название в манифесте.")
    loader = value.get("loader", "vanilla")
    if not isinstance(loader, str):
        raise UserError("Загрузчик в манифесте должен быть строкой.")
    loader = loader.lower()
    if loader not in LOADERS:
        raise UserError("Хост указал неподдерживаемый загрузчик.")
    minecraft = version_id(value.get("minecraft", ""))
    loader_version = "" if loader == "vanilla" else version_id(value.get("loader_version", ""))
    if loader_version in ("auto", "latest", "последняя"):
        raise UserError("Хост должен указать конкретную версию загрузчика.")
    server = value.get("server", "")
    if not isinstance(server, str) or len(server) > 255 or any(c.isspace() for c in server):
        raise UserError("Некорректный адрес сервера в манифесте.")
    strict = value.get("strict", False)
    if type(strict) is not bool:
        raise UserError("strict в манифесте должен быть true или false.")
    folders = value.get("folders", list(SYNC_FOLDERS))
    if (not isinstance(folders, list) or not folders or not all(isinstance(p, str) and p in SYNC_FOLDERS for p in folders)
            or len(set(folders)) != len(folders) or (strict and "mods" not in folders)):
        raise UserError("Некорректный список синхронизируемых папок.")
    entries = value.get("files")
    if not isinstance(entries, list) or len(entries) > MAX_FILES:
        raise UserError("Некорректный или слишком большой список файлов.")
    files, seen, total = [], set(), 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise UserError("Некорректная запись файла в манифесте.")
        path = sync_path(entry.get("path", ""))
        if path.split("/", 1)[0] not in folders or path.casefold() in seen:
            raise UserError(f"Конфликт или недопустимая папка: {path}")
        digest, size = entry.get("sha1", ""), entry.get("size")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{40}", digest):
            raise UserError(f"Некорректный SHA-1: {path}")
        if type(size) is not int or not 0 <= size <= MAX_FILE_SIZE:
            raise UserError(f"Недопустимый размер: {path}")
        total += size
        if total > MAX_PACK_SIZE:
            raise UserError("Сборка превышает лимит 20 ГБ.")
        seen.add(path.casefold())
        files.append({"path": path, "sha1": digest.lower(), "size": size})
    for path_name in seen:
        parts = path_name.split("/")
        if any("/".join(parts[:i]) in seen for i in range(1, len(parts))):
            raise UserError("В манифесте один путь одновременно используется как файл и каталог.")
    manifest = {"protocol": 1, "name": name, "minecraft": minecraft, "loader": loader,
                "loader_version": loader_version, "server": server, "strict": strict,
                "folders": folders, "files": sorted(files, key=lambda f: f["path"])}
    # Recompute locally, so stale/forged rev strings cannot suppress an update.
    manifest["rev"] = manifest_revision(manifest)
    return manifest


@dataclass
class SyncDownload:
    path: str
    sha1: str
    size: int
    action: str


@dataclass
class SyncPlan:
    manifest: dict[str, Any]
    downloads: list[SyncDownload]
    deletions: list[str]
    expected: dict[str, str | None]
    previous_state: dict[str, str]
    before: tuple[str, str, str]
    before_server: str
    sync_url: str
    version_changed: bool
    downgrade: bool

    @property
    def settings_changed(self) -> bool:
        return self.version_changed or self.before_server != self.manifest["server"]

    @property
    def has_changes(self) -> bool:
        return bool(self.downloads or self.deletions or self.settings_changed)

    @property
    def size(self) -> int:
        return sum(item.size for item in self.downloads)


def read_sync_state(inst: Instance) -> dict[str, str]:
    state = read_json(inst.directory / "sync_state.json", {})
    if not isinstance(state, dict):
        raise UserError("Некорректный sync_state.json.")
    if len({p.casefold() for p in state}) != len(state):
        raise UserError("Конфликт регистра путей в sync_state.json.")
    for path, digest in state.items():
        sync_path(path)
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{40}", digest):
            raise UserError("Некорректная запись sync_state.json.")
    return state


def release_tuple(version: str) -> tuple[int, ...] | None:
    if re.fullmatch(r"\d+\.\d+(?:\.\d+)?", version):
        parts = tuple(map(int, version.split(".")))
        return parts + (0,) * (3 - len(parts))
    return None


def build_plan(inst: Instance, m: dict[str, Any]) -> SyncPlan:
    """Read-only: never creates directories, changes files or saves metadata."""
    manifest = validate_manifest(m)
    state = read_sync_state(inst)
    downloads, deletions, expected = [], set(), {}
    desired = {f["path"]: f for f in manifest["files"]}
    desired_folded = {p.casefold(): p for p in desired}
    state_folded = {p.casefold(): digest for p, digest in state.items()}

    def aliases_desired(path: str) -> bool:
        candidate = desired_folded.get(path.casefold())
        if not candidate:
            return False
        source, target = safe_join(inst.game_dir, path), safe_join(inst.game_dir, candidate)
        return source.exists() and target.exists() and source.samefile(target)

    for path, entry in desired.items():
        current = fingerprint(inst.game_dir, path)
        is_config = path.startswith("config/")
        host_changed = state_folded.get(path.casefold()) != entry["sha1"]
        if current is None or (current != entry["sha1"] and (not is_config or host_changed)):
            downloads.append(SyncDownload(path, entry["sha1"], entry["size"],
                                          "заменить" if current is not None else "скачать"))
            expected[path] = current
        # An enabled host mod must not leave a disabled local twin (and vice versa).
        if path.startswith("mods/") and path.endswith((".jar", ".jar.disabled")):
            twin = path.removesuffix(".disabled") if path.endswith(".disabled") else path + ".disabled"
            if twin not in desired and fingerprint(inst.game_dir, twin) is not None:
                deletions.add(twin)
    for path in state:
        if path not in desired and not aliases_desired(path) and fingerprint(inst.game_dir, path) is not None:
            deletions.add(path)
    if manifest["strict"]:
        for relative, _ in iter_files(inst.game_dir / "mods"):
            path = "mods/" + relative
            if path.lower().endswith((".jar", ".jar.disabled")) and path not in desired and not aliases_desired(path):
                deletions.add(path)
    for path in deletions:
        expected[path] = fingerprint(inst.game_dir, path)
    after = (manifest["minecraft"], manifest["loader"], manifest["loader_version"])
    old_release, new_release = release_tuple(inst.minecraft), release_tuple(manifest["minecraft"])
    return SyncPlan(manifest, downloads, sorted(deletions), expected, state, inst.identity,
                    inst.server, inst.sync_url, inst.identity != after,
                    bool(old_release and new_release and new_release < old_release))


def apply_plan(inst: Instance, plan: SyncPlan, *, backup: bool = True,
               progress: Progress = no_progress, cancel: threading.Event | None = None,
               fetcher: Callable[[SyncDownload, Path], None] | None = None) -> Instance:
    """Download and verify everything before deletions/version changes; all-or-nothing."""
    if inst.identity != plan.before or inst.server != plan.before_server or inst.sync_url != plan.sync_url:
        raise UserError("Настройки сборки изменились. Повторите синхронизацию.")
    if read_sync_state(inst) != plan.previous_state:
        raise UserError("Сборка уже синхронизирована другой операцией. Повторите проверку.")
    m = validate_manifest(plan.manifest)
    if shutil.disk_usage(inst.directory).free < plan.size + 32 * 1024**2:
        raise UserError("Недостаточно свободного места для синхронизации.")
    with FileTransaction(inst) as transaction, BoundedSession() as session:
        replacements = {}
        for index, item in enumerate(plan.downloads):
            check_cancel(cancel)
            progress(f"{item.action.capitalize()}: {item.path}", index, len(plan.downloads))
            target = transaction.staged_path(item.path)
            if fetcher is not None:
                target.parent.mkdir(parents=True, exist_ok=True)
                fetcher(item, target)
            else:
                base = normalize_sync_url(inst.sync_url)
                download_file(f"{base}/files/{quote(item.path, safe='/')}", target,
                              sha1=item.sha1, size=item.size, headers={"If-Match": f'"{item.sha1}"'},
                              session=session, cancel=cancel)
            if not target.is_file() or target.stat().st_size != item.size or sha1_file(target) != item.sha1:
                raise UserError(f"Повреждённый файл: {item.path}. Сборка не изменена.")
            replacements[item.path] = target
        check_cancel(cancel)
        if backup and plan.version_changed:
            progress("Резервная копия миров…", 0, 0)
            backup_worlds(inst, progress=progress, cancel=cancel)
        # Re-read metadata after the confirmation/download window, before mutating anything.
        current = read_json(inst.directory / "instance.json", inst.to_dict())
        for key in ("minecraft", "loader", "loader_version", "server", "sync_url", "last_sync_rev"):
            if current.get(key, "") != inst.to_dict().get(key, ""):
                raise UserError("Сборка изменилась во время скачивания. Повторите синхронизацию.")
        if read_sync_state(inst) != plan.previous_state:
            raise UserError("Состояние синхронизации изменилось во время скачивания.")
        # Keep unrelated settings/notes/playtime that may have changed in another task.
        fields = set(inst.to_dict())
        updated = Instance(**{k: v for k, v in current.items() if k in fields}, directory=inst.directory)
        updated.minecraft, updated.loader, updated.loader_version = m["minecraft"], m["loader"], m["loader_version"]
        updated.server, updated.last_sync_rev = m["server"], m["rev"]
        updated.last_sync_at = time.time()
        updated.validate()
        state = {entry["path"]: entry["sha1"] for entry in m["files"]}
        transaction.commit(replacements, plan.deletions,
                           {"sync_state.json": state, "instance.json": updated.to_dict()},
                           plan.expected, cancel)
    progress("Сборка синхронизирована", len(plan.downloads), len(plan.downloads))
    return updated


# Party presence is separate from pack writes. No account names, IPs or local paths are shared.
PARTY_INTERVAL = 10.0
PARTY_TTL = 45.0
PARTY_MAX_MEMBERS = 32
PARTY_MAX_BODY = 4096
PARTY_STATES = {"launcher", "updating", "playing"}


def party_name(value: Any) -> str:
    if not isinstance(value, str) or len(value.strip()) > 32 or re.search(r"[\x00-\x1f\x7f<>]", value):
        raise UserError("Имя в пати: до 32 символов, без управляющих символов и HTML.")
    return value.strip()


def party_identity(store: Store, url: str) -> tuple[str, str, str]:
    """Stable, per-room identity; a private lease prevents peers impersonating each other."""
    with store.lock:
        key = store.settings.get("party_device_key", "")
        if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{64}", key):
            key = secrets.token_hex(32)
            store.settings["party_device_key"] = key
            store.save_settings()
        source = normalize_sync_url(url).encode()
        identity = hmac.new(bytes.fromhex(key), b"peer:" + source, hashlib.sha256).hexdigest()[:32]
        lease = hmac.new(bytes.fromhex(key), b"lease:" + source, hashlib.sha256).hexdigest()
        name = party_name(store.settings.get("party_name", "")) or "Игрок " + identity[:4].upper()
        return identity, lease, name


class PartyDirectory:
    """Bounded, in-memory room roster. Abandoned sessions expire, and leases are never public."""
    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.peers: dict[str, dict[str, Any]] = {}

    def prune(self) -> None:
        for key in [key for key, peer in self.peers.items() if self.clock() - peer["seen"] >= PARTY_TTL]:
            del self.peers[key]

    def touch(self, value: Any, *, leave: bool = False) -> None:
        if not isinstance(value, dict):
            raise UserError("Некорректные данные пати.")
        identity, lease = value.get("id"), value.get("lease")
        if (not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{32}", identity)
                or not isinstance(lease, str) or not re.fullmatch(r"[a-f0-9]{64}", lease)):
            raise UserError("Некорректная сессия пати.")
        name = party_name(value.get("name", ""))
        state, revision = value.get("state", "launcher"), value.get("rev", "")
        if (not isinstance(state, str) or state not in PARTY_STATES or not isinstance(revision, str)
                or (revision and not re.fullmatch(r"[a-f0-9]{40}", revision)) or (not leave and not name)):
            raise UserError("Некорректное состояние пати.")
        lease_hash = hashlib.sha256(lease.encode()).hexdigest()
        with self.lock:
            self.prune()
            old = self.peers.get(identity)
            if old and not hmac.compare_digest(old["lease_hash"], lease_hash):
                raise PermissionError("Сессия принадлежит другому участнику.")
            if leave:
                self.peers.pop(identity, None)
                return
            if not old and len(self.peers) >= PARTY_MAX_MEMBERS:
                raise UserError("Пати заполнена: максимум 32 друга.")
            self.peers[identity] = {"id": identity, "name": name, "state": state, "rev": revision,
                                    "role": "friend", "seen": self.clock(), "lease_hash": lease_hash}

    def members(self) -> list[dict[str, str]]:
        with self.lock:
            self.prune()
            return [{key: peer[key] for key in ("id", "name", "state", "rev", "role")}
                    for peer in sorted(self.peers.values(), key=lambda peer: (peer["name"].casefold(), peer["id"]))]


def validate_party_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or type(value.get("protocol")) is not int or value["protocol"] != 1:
        raise UserError("Неподдерживаемый ответ пати. Обновите лаунчер у хоста.")
    pack = value.get("pack")
    if not isinstance(pack, dict) or not isinstance(pack.get("name"), str) or not 1 <= len(pack["name"]) <= 200:
        raise UserError("Некорректная сборка в ответе пати.")
    minecraft = version_id(pack.get("minecraft"))
    loader = pack.get("loader")
    if not isinstance(loader, str) or loader not in LOADERS:
        raise UserError("Некорректный загрузчик пати.")
    loader_version = version_id(pack.get("loader_version", ""), allow_auto=loader == "vanilla")
    revision = value.get("rev")
    if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise UserError("Некорректная ревизия пати.")
    peers = value.get("members")
    if not isinstance(peers, list) or not 1 <= len(peers) <= PARTY_MAX_MEMBERS + 1:
        raise UserError("Некорректный список участников пати.")
    result, seen = [], set()
    for peer in peers:
        if not isinstance(peer, dict):
            raise UserError("Некорректный участник пати.")
        identity, state, role, rev = (peer.get(key) for key in ("id", "state", "role", "rev"))
        if (not isinstance(identity, str) or (identity != "host" and not re.fullmatch(r"[a-f0-9]{32}", identity))
                or identity in seen or not isinstance(state, str) or state not in PARTY_STATES
                or role != ("host" if identity == "host" else "friend")
                or not isinstance(rev, str) or (rev and not re.fullmatch(r"[a-f0-9]{40}", rev))):
            raise UserError("Некорректный участник пати.")
        seen.add(identity)
        name = party_name(peer.get("name"))
        if not name:
            raise UserError("Имя участника не задано.")
        result.append({"id": identity, "name": name, "state": state, "role": role, "rev": rev})
    if "host" not in seen:
        raise UserError("В ответе пати отсутствует хост.")
    return {"protocol": 1, "rev": revision, "pack": {"name": pack["name"], "minecraft": minecraft,
            "loader": loader, "loader_version": loader_version}, "members": result}


def read_party_response(response: requests.Response) -> dict[str, Any]:
    response.raise_for_status()
    if response.status_code != 200:
        raise UserError("Хост перенаправил запрос пати. Проверьте приглашение.")
    data = bytearray()
    for chunk in response.iter_content(8192):
        data.extend(chunk)
        if len(data) > 128 * 1024:
            raise UserError("Слишком большой ответ пати.")
    try:
        return validate_party_snapshot(json.loads(data))
    except (ValueError, UnicodeError):
        raise UserError("Хост прислал повреждённый ответ пати.") from None


def party_failure(exc: Exception) -> dict[str, Any]:
    """Classify errors without exposing a bearer URL or an untrusted response body."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    kind = "invitation" if status in (401, 403) else "session" if status == 409 else "busy" if status in (429, 502, 503, 504) else "timeout" if isinstance(exc, requests.Timeout) else "network" if isinstance(exc, requests.ConnectionError) else "protocol" if isinstance(exc, UserError) else "local" if isinstance(exc, OSError) else "unexpected"
    messages = {
        "invitation": "Хост отклонил приглашение. Попросите у друга действующую ссылку.",
        "session": "Хост не принял сессию. Дождитесь автоматического переподключения.",
        "busy": "Хост временно занят. MCSync повторит запрос автоматически.",
        "timeout": "Хост отвечает слишком долго. Проверка повторится автоматически.",
        "network": "Связь с хостом потеряна. Приглашение сохранено, переподключаемся.",
        "protocol": "Ответ хоста несовместим или повреждён. Обновите MCSync у обоих участников.",
        "local": "Не удалось прочитать локальные настройки пати. Откройте диагностику.",
        "unexpected": "Проверка пати не завершилась. Повторим её автоматически.",
    }
    return {"error_kind": kind, "error_message": messages[kind], "error": redact(str(exc))[:180]}


def party_connection_text(state: dict[str, Any], *, now: float | None = None) -> str:
    if state.get("online"):
        latency = state.get("latency_ms")
        return "На связи · проверяется автоматически" + (f" · {latency} мс" if type(latency) is int else "")
    if state.get("online") is False:
        message = state.get("error_message") or "Хост недоступен. Приглашение сохранено — переподключаемся автоматически."
        if state.get("retry_at") is not None:
            remaining = max(0, math.ceil(state["retry_at"] - (time.monotonic() if now is None else now)))
            message += f" Следующая попытка через {remaining} с." if remaining else " Пробуем подключиться…"
        return message
    return "Приглашение сохранено. Подключаемся автоматически — повторно вводить ссылку не нужно."


def validate_host_preferences(value: Any) -> dict[str, Any]:
    """Reject corrupt/private host settings before constructing Qt fields or opening sockets."""
    if not isinstance(value, dict):
        raise UserError("Повреждены настройки пати: ожидался объект JSON.")
    for key in ("strict", "auto_start"):
        if key in value and type(value[key]) is not bool:
            raise UserError("Повреждены переключатели настроек пати.")
    if "port" in value and (type(value["port"]) is not int or not 1024 <= value["port"] <= 65535):
        raise UserError("Некорректный сохранённый порт пати.")
    if "address" in value and (not isinstance(value["address"], str) or not value["address"] or re.search(r"[/\s?#@]", value["address"])):
        raise UserError("Некорректный сохранённый адрес пати.")
    if "token" in value and (not isinstance(value["token"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", value["token"])):
        raise UserError("Повреждено сохранённое приглашение пати.")
    if "folders" in value and (not isinstance(value["folders"], list) or not value["folders"] or not all(isinstance(x, str) and x in SYNC_FOLDERS for x in value["folders"])):
        raise UserError("Некорректные папки раздачи пати.")
    if "excludes" in value and (not isinstance(value["excludes"], list) or len(value["excludes"]) > 256 or not all(isinstance(x, str) and len(x) <= 512 for x in value["excludes"])):
        raise UserError("Некорректные исключения раздачи пати.")
    return value


def poll_party(store: Store, inst: Instance, state: str = "launcher") -> dict[str, Any]:
    base = normalize_sync_url(inst.sync_url)
    identity, lease, name = party_identity(store, base)
    payload = {"id": identity, "lease": lease, "name": name, "state": state, "rev": inst.last_sync_rev}
    started = time.monotonic()
    with BoundedSession() as session:
        with session.post(base + "/party/heartbeat", json=payload, timeout=(2, 3),
                          stream=True, allow_redirects=False) as response:
            if response.status_code not in (404, 405, 501):
                room = read_party_response(response)
                return {"online": True, "phase": "online", "room": room, "self_id": identity,
                        "changed": room["rev"] != inst.last_sync_rev, "supported": True,
                        "checked_at": time.time(), "latency_ms": round((time.monotonic() - started) * 1000)}
        # Old hosts still get automatic connectivity/revision checks, without a fake roster.
        manifest = validate_manifest(fetch_json(session, base + "/manifest.json", timeout=(2, 3)))
        return {"online": True, "phase": "online", "supported": False, "changed": manifest["rev"] != inst.last_sync_rev,
                "checked_at": time.time(), "latency_ms": round((time.monotonic() - started) * 1000)}


def leave_party(store: Store, inst: Instance) -> None:
    identity, lease, _ = party_identity(store, inst.sync_url)
    with BoundedSession() as session:
        with session.post(normalize_sync_url(inst.sync_url) + "/party/leave", json={"id": identity, "lease": lease},
                          timeout=(1, 2), allow_redirects=False) as response:
            response.raise_for_status()


class PartyMonitor:
    """Daemon supervisor; up to four bounded requests, independent of UI/launch/install tasks."""
    def __init__(self, store: Store, *, interval: float = PARTY_INTERVAL):
        self.store, self.interval = store, interval
        self.lock = threading.RLock()
        self.states: dict[str, dict[str, Any]] = {}
        self.activities: dict[str, str] = {}
        self.sources: dict[str, str] = {}
        self.due: dict[str, float] = {}
        self.failures: dict[str, int] = {}
        self.running: set[str] = set()
        self.leave_slots = threading.BoundedSemaphore(2)
        self.selected = ""
        self.stop_event, self.wakeup = threading.Event(), threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, name="MCSync-party", daemon=True)
            self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.wakeup.set()
        if self.thread:
            self.thread.join(timeout=0.1)
        # Workers finish their bounded request and send leave; a killed process expires by TTL.

    def refresh(self) -> None:
        with self.lock:
            self.due.clear()
        self.wakeup.set()

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self.lock:
            states = copy.deepcopy(self.states)
            for state in states.values():
                if state.get("online") and time.monotonic() - state.get("received_at", time.monotonic()) >= PARTY_TTL:
                    state.update(online=False, phase="retry", changed=None, error="Ответ хоста устарел; переподключаемся.")
            return states

    def set_activity(self, instance_id: str, state: str) -> None:
        with self.lock:
            new = state if state in PARTY_STATES else "launcher"
            if self.activities.get(instance_id, "launcher") != new:
                self.due[instance_id] = 0
                self.wakeup.set()
            self.activities[instance_id] = new

    def forget(self, inst: Instance) -> None:
        with self.lock:
            for mapping in (self.states, self.sources, self.due, self.failures, self.activities):
                mapping.pop(inst.id, None)
        if inst.sync_url and self.thread is not None and not self.stop_event.is_set():
            self._schedule_leave(inst)

    def _schedule_leave(self, inst: Instance) -> None:
        # An unreachable departed room must not block heartbeat to other rooms.
        # Excess departures expire server-side by TTL rather than creating unbounded threads.
        if not self.leave_slots.acquire(blocking=False):
            return
        def work() -> None:
            try:
                self._leave(inst)
            finally:
                self.leave_slots.release()
        threading.Thread(target=work, name="MCSync-party-leave", daemon=True).start()

    def _leave(self, inst: Instance) -> None:
        with contextlib.suppress(requests.RequestException, UserError, OSError):
            leave_party(self.store, inst)

    def _poll(self, inst: Instance, source: str) -> None:
        try:
            with self.lock:
                state = self.activities.get(inst.id, "launcher")
            result = poll_party(self.store, self.store.load(inst.id), state)
            with self.lock:
                self.failures[inst.id] = 0
                delay = self.interval if result.get("supported") else max(self.interval, 30)
        except Exception as exc:
            with self.lock:
                failures = self.failures.get(inst.id, 0) + 1
                self.failures[inst.id] = failures
            delay = min(30, 5 * 2 ** min(failures - 1, 3))
            result = {"online": False, "phase": "retry", "changed": None, "checked_at": time.time(),
                      **party_failure(exc), "retry_seconds": delay}
        with self.lock:
            self.running.discard(inst.id)
            live = self.sources.get(inst.id) == source and not self.stop_event.is_set()
            if live:
                result["source"] = hashlib.sha256(source.encode()).hexdigest()
                result["received_at"] = time.monotonic()
                self.states[inst.id] = result
                self.due[inst.id] = time.monotonic() + delay
                result["retry_at"] = self.due[inst.id] if not result.get("online") else None
        if not live:
            self._schedule_leave(inst)
        self.wakeup.set()

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                instances = {inst.id: inst for inst in self.store.list_instances() if inst.sync_url}
                with self.lock:
                    removed = set(self.sources) - set(instances)
                    old = [(key, self.sources.pop(key)) for key in removed]
                    for key in removed:
                        self.states.pop(key, None)
                        self.due.pop(key, None)
                    for inst in instances.values():
                        if self.sources.get(inst.id) != inst.sync_url:
                            self.sources[inst.id] = inst.sync_url
                            self.due.pop(inst.id, None)
                            self.states.pop(inst.id, None)
                    ordered = sorted(instances.values(), key=lambda inst: (inst.id != self.selected, self.due.get(inst.id, 0)))
                    for inst in ordered:
                        if len(self.running) >= 4:
                            break
                        if inst.id not in self.running and self.due.get(inst.id, 0) <= time.monotonic():
                            self.running.add(inst.id)
                            threading.Thread(target=self._poll, args=(inst, inst.sync_url),
                                             name="MCSync-party-pulse", daemon=True).start()
                for key, source in old:
                    # Only the saved URL and opaque session are used, never deleted instance files.
                    departed = Instance(id=key, name="", directory=self.store.instances_dir / key, sync_url=source)
                    self._schedule_leave(departed)
            except (UserError, OSError):
                pass
            self.wakeup.wait(0.5)
            self.wakeup.clear()
        with contextlib.suppress(UserError, OSError):
            for inst in self.store.list_instances():
                if inst.sync_url:
                    self._schedule_leave(inst)


def resume_saved_hosts(store: Store, *, cancel: threading.Event | None = None,
                       skip: set[str] | None = None) -> tuple[dict[str, SyncHost], dict[str, str]]:
    hosts, errors = {}, {}
    for inst in store.list_instances():
        if inst.sync_url or inst.id in (skip or set()):
            continue
        try:
            settings = read_json(inst.directory / "host_settings.json", {})
            if not isinstance(settings, dict) or settings.get("auto_start") is not True:
                continue
            check_cancel(cancel)
            validate_host_preferences(settings)
            if type(settings.get("port")) is not int or not 1024 <= settings["port"] <= 65535:
                raise UserError("Некорректный сохранённый порт пати.")
            if not isinstance(settings.get("token"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", settings["token"]):
                raise UserError("Повреждено приглашение пати. Создайте новое в настройках раздачи.")
            if (not isinstance(settings.get("folders"), list) or not all(isinstance(x, str) for x in settings["folders"])
                    or not isinstance(settings.get("excludes"), list) or not all(isinstance(x, str) for x in settings["excludes"])
                    or type(settings.get("strict")) is not bool):
                raise UserError("Повреждены настройки пати.")
            host = SyncHost(store, inst.id, port=settings["port"], token=settings["token"],
                            folders=tuple(settings["folders"]), excludes=tuple(settings["excludes"]), strict=settings["strict"])
            host.url(settings.get("address", ""))
            host.start()
            hosts[inst.id] = host
        except Cancelled:
            for host in hosts.values():
                host.stop()
            raise
        except (UserError, OSError, TypeError, ValueError) as exc:
            errors[inst.id] = redact(str(exc))
    if cancel is not None and cancel.is_set():
        for host in hosts.values():
            host.stop()
        raise Cancelled("Восстановление пати отменено.")
    return hosts, errors


class SyncHost:
    """Read-only pack files plus bounded, token-authenticated ephemeral party presence."""
    def __init__(self, store: Store, instance_id: str, *, port: int = 25589,
                 token: str | None = None, folders: tuple[str, ...] = SYNC_FOLDERS,
                 excludes: tuple[str, ...] = ("*.part", "*.tmp"), strict: bool = True):
        if not folders or not set(folders).issubset(SYNC_FOLDERS) or (strict and "mods" not in folders):
            raise UserError("Выберите папки для раздачи; строгий режим требует папку mods.")
        self.store, self.instance_id = store, instance_id
        self.port, self.token = port, token or secrets.token_urlsafe(24)
        if not re.fullmatch(r"[A-Za-z0-9_\-]{16,128}", self.token):
            raise UserError("Некорректный токен раздачи.")
        self.folders, self.excludes, self.strict = folders, excludes, strict
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self._manifest_lock = threading.Lock()
        self._cached: dict[str, Any] | None = None
        self._cached_at = 0.0
        self._file_hashes: dict[str, tuple[tuple[int, ...], str]] = {}
        self.party = PartyDirectory()
        self.party_state = "launcher"

    def party_snapshot(self, *, refresh: bool = False) -> dict[str, Any]:
        if refresh:
            manifest = self.manifest()
        else:
            with self._manifest_lock:
                manifest = copy.deepcopy(self._cached)
            if manifest is None:
                manifest = self.manifest()
        with self.party.lock:
            name = party_name(self.store.settings.get("party_name", "")) or "Хост"
            owner = {"id": "host", "name": name, "role": "host", "state": self.party_state, "rev": manifest["rev"]}
            return {"protocol": 1, "rev": manifest["rev"], "pack": {key: manifest[key] for key in
                    ("name", "minecraft", "loader", "loader_version")}, "members": [owner, *self.party.members()]}

    def manifest(self, force: bool = False) -> dict[str, Any]:
        with self._manifest_lock, self.store.instance_lock(self.instance_id):
            if not force and self._cached and time.monotonic() - self._cached_at < 1:
                return copy.deepcopy(self._cached)
            inst = self.store.load(self.instance_id)
            if inst.loader != "vanilla" and not inst.loader_version:
                raise UserError("Сначала закрепите конкретную версию загрузчика (кнопка «Версии»).")
            files = []
            hashes = {}
            for folder in self.folders:
                for relative, path in iter_files(inst.game_dir / folder):
                    name = f"{folder}/{relative}"
                    if any(fnmatch.fnmatchcase(name, mask) or fnmatch.fnmatchcase(relative, mask)
                           for mask in self.excludes):
                        continue
                    info = path.stat()
                    stamp = (info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino, info.st_dev)
                    previous = self._file_hashes.get(name)
                    digest = previous[1] if not force and previous and previous[0] == stamp else sha1_file(path)
                    hashes[name] = (stamp, digest)
                    files.append({"path": name, "sha1": digest, "size": info.st_size})
            manifest = validate_manifest({"name": inst.name, "minecraft": inst.minecraft,
                                          "loader": inst.loader, "loader_version": inst.loader_version,
                                          "server": inst.server, "strict": self.strict,
                                          "folders": list(self.folders), "files": files})
            self._file_hashes = hashes
            self._cached, self._cached_at = manifest, time.monotonic()
            return copy.deepcopy(manifest)

    def start(self, bind: str = "0.0.0.0") -> None:
        # Windows SO_REUSEADDR permits two listeners on the same port. Refuse an
        # already reachable service instead of silently stealing the party port.
        if self.port:
            address = "127.0.0.1" if bind == "0.0.0.0" else bind
            try:
                connection = socket.create_connection((address, self.port), timeout=0.3)
            except OSError:
                pass
            else:
                connection.close()
                raise UserError(f"Порт {self.port} уже используется. Выберите другой порт пати.")
        self.manifest(force=True)
        host = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "MCSync/1"

            def setup(self) -> None:
                super().setup()
                self.connection.settimeout(20)

            def log_message(self, fmt: str, *args: Any) -> None:
                # BaseHTTPRequestHandler logs the secret token in the path; never use it.
                pass

            def do_HEAD(self) -> None:
                self.serve(head=True)

            def do_GET(self) -> None:
                self.serve(head=False)

            def do_POST(self) -> None:
                try:
                    segments = urlsplit(self.path).path.split("/", 2)
                    provided = segments[1] if len(segments) > 1 else ""
                    if not hmac.compare_digest(provided.encode("utf-8"), host.token.encode("ascii")):
                        self.send_error(403, "Forbidden")
                        return
                    endpoint = segments[2] if len(segments) > 2 else ""
                    if endpoint not in ("party/heartbeat", "party/leave"):
                        self.send_error(405, "Files and manifests are read-only")
                        return
                    if self.headers.get("Origin") or self.headers.get("Transfer-Encoding"):
                        self.send_error(403, "Browser-origin and chunked requests are not accepted")
                        return
                    length = int(self.headers.get("Content-Length", "0"))
                    if length > PARTY_MAX_BODY:
                        self.send_error(413)
                        return
                    if length <= 0 or not self.headers.get("Content-Type", "").lower().startswith("application/json"):
                        self.send_error(400)
                        return
                    body = self.rfile.read(length)
                    if len(body) != length:
                        self.send_error(400)
                        return
                    host.party.touch(json.loads(body), leave=endpoint == "party/leave")
                    self.send_payload(json_bytes(host.party_snapshot(refresh=True)), "application/json; charset=utf-8", False)
                except PermissionError:
                    self.send_error(409, "Session belongs to a different peer")
                except (UserError, UnicodeError, ValueError, TypeError):
                    self.send_error(400, "Invalid party request")
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    pass
                except OSError:
                    self.send_error(500, "Unable to read pack")

            def send_payload(self, data: bytes, content_type: str, head: bool) -> None:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                if not head:
                    self.wfile.write(data)

            def serve(self, head: bool) -> None:
                try:
                    path = urlsplit(self.path).path
                    segments = path.split("/", 2)
                    provided = segments[1] if len(segments) > 1 else ""
                    if not hmac.compare_digest(provided.encode("utf-8"), host.token.encode("ascii")):
                        self.send_error(403, "Forbidden")
                        return
                    endpoint = segments[2] if len(segments) > 2 else ""
                    if endpoint == "party.json":
                        self.send_payload(json_bytes(host.party_snapshot()), "application/json; charset=utf-8", head)
                        return
                    if endpoint == "manifest.json":
                        self.send_payload(json_bytes(host.manifest(force=True)), "application/json; charset=utf-8", head)
                        return
                    if not endpoint.startswith("files/"):
                        self.send_error(404)
                        return
                    relative = sync_path(unquote(endpoint[6:], errors="strict"))
                    entry = next((f for f in host.manifest()["files"] if f["path"] == relative), None)
                    if entry is None:
                        self.send_error(404)
                        return
                    inst = host.store.load(host.instance_id)
                    target = safe_join(inst.game_dir, relative)
                    with target.open("rb") as stream:
                        digest = hashlib.sha1()
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(chunk)
                        etag = f'"{digest.hexdigest()}"'
                        if (digest.hexdigest() != entry["sha1"]
                                or self.headers.get("If-Match", etag) != etag):
                            self.send_error(412, "Pack changed; request a new manifest")
                            return
                        stream.seek(0)
                        self.send_response(200)
                        self.send_header("Content-Type", "application/octet-stream")
                        self.send_header("Content-Length", str(os.fstat(stream.fileno()).st_size))
                        self.send_header("ETag", etag)
                        self.send_header("X-Content-Type-Options", "nosniff")
                        self.end_headers()
                        if not head:
                            shutil.copyfileobj(stream, self.wfile, 256 * 1024)
                except (UserError, UnicodeError, ValueError):
                    self.send_error(400, "Invalid path or manifest")
                except FileNotFoundError:
                    self.send_error(404)
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    pass
                except OSError:
                    self.send_error(500, "Unable to read pack")

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True
            slots = threading.BoundedSemaphore(32)

            def process_request(self, request: Any, client_address: Any) -> None:
                if not self.slots.acquire(blocking=False):
                    request.close()
                    return
                try:
                    super().process_request(request, client_address)
                except BaseException:
                    self.slots.release()
                    raise

            def process_request_thread(self, request: Any, client_address: Any) -> None:
                try:
                    super().process_request_thread(request, client_address)
                finally:
                    self.slots.release()

        self.httpd = Server((bind, self.port), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="SyncHost", daemon=True)
        self.thread.start()

    def url(self, address: str) -> str:
        address = address.strip()
        if not address or re.search(r"[/\s?#@]", address):
            raise UserError("Введите IP или DNS-имя без http:// и порта.")
        if ":" in address and not address.startswith("["):
            address = f"[{address}]"
        return normalize_sync_url(f"http://{address}:{self.port}/{self.token}")

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
        if self.thread:
            self.thread.join(timeout=3)
            self.thread = None


def fetch_manifest(inst: Instance, *, allow_cache: bool = True) -> tuple[dict[str, Any], bool]:
    base = normalize_sync_url(inst.sync_url)
    cache_path = inst.directory / "manifest_cache.json"
    source_hash = hashlib.sha256(base.encode("utf-8")).hexdigest()
    try:
        with BoundedSession() as session:
            manifest = validate_manifest(fetch_json(session, base + "/manifest.json"))
        atomic_json(cache_path, {"source": source_hash, "fetched_at": time.time(), "manifest": manifest})
        return manifest, False
    except (requests.ConnectionError, requests.Timeout):
        cached = read_json(cache_path, {}) if allow_cache else {}
        if isinstance(cached, dict) and cached.get("source") == source_hash and "manifest" in cached:
            return validate_manifest(cached["manifest"]), True
        raise UserError("Хост недоступен, а кеша этой сборки ещё нет. Проверьте адрес и подключение.") from None


@dataclass
class SyncResult:
    instance: Instance
    message: str
    offline: bool = False


def sync_instance(store: Store, instance_id: str, *,
                  confirm: Callable[[Instance, SyncPlan], tuple[bool, bool]] | None = None,
                  allow_offline: bool = False, progress: Progress = no_progress,
                  cancel: threading.Event | None = None) -> SyncResult:
    inst = store.load(instance_id)
    if not inst.sync_url:
        return SyncResult(inst, "Эта сборка не подключена к хосту.")
    progress("Проверка сборки у хоста…", 0, 0)
    manifest, cached = fetch_manifest(inst)
    check_cancel(cancel)
    plan = build_plan(inst, manifest)
    if cached:
        if not inst.last_sync_rev:
            raise UserError("Первую установку нельзя выполнить без доступного хоста.")
        if not allow_offline and plan.has_changes:
            raise UserError("Хост недоступен. В кеше только манифест, недостающие файлы скачать нельзя.")
        return SyncResult(inst, "Хост недоступен — используется последняя установленная сборка. "
                          "Кеш манифеста не применяется для удаления файлов или смены версий.", True)
    need_confirm = bool(inst.last_sync_rev and plan.has_changes and
                        (inst.sync_mode == "ask" or (inst.sync_mode == "version" and plan.version_changed)))
    backup = True
    if need_confirm:
        if confirm is None:
            raise UserError("Изменения требуют подтверждения в интерфейсе.")
        accepted, backup = confirm(inst, plan)
        if not accepted:
            raise Cancelled("Синхронизация отменена; версия и файлы не изменены.")
    with store.instance_lock(instance_id):
        check_cancel(cancel)
        inst = apply_plan(store.load(instance_id), plan, backup=backup, progress=progress, cancel=cancel)
    return SyncResult(inst, "Сборка актуальна." if not plan.has_changes else "Сборка обновлена.")


def checked_zip(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > MAX_FILES:
        raise UserError("В архиве слишком много файлов.")
    seen, total = set(), 0
    for info in infos:
        name = info.filename.rstrip("/")
        relative_path(name)
        if name.casefold() in seen:
            raise UserError(f"Повторяющийся путь в архиве: {name}")
        seen.add(name.casefold())
        if stat.S_ISLNK(info.external_attr >> 16):
            raise UserError("Символические ссылки в архивах не поддерживаются.")
        if info.flag_bits & 1:
            raise UserError("Зашифрованные архивы не поддерживаются.")
        if info.file_size > MAX_FILE_SIZE:
            raise UserError(f"Слишком большой файл в архиве: {name}")
        total += info.file_size
        if total > MAX_PACK_SIZE:
            raise UserError("Распакованный архив превышает лимит 20 ГБ.")
    return infos


def zip_json(archive: zipfile.ZipFile, name: str) -> Any:
    if archive.getinfo(name).file_size > MAX_JSON_SIZE:
        raise UserError("Слишком большой индекс сборки в архиве.")
    try:
        return json.loads(archive.read(name))
    except (ValueError, UnicodeError) as exc:
        raise UserError("Некорректный индекс сборки в архиве.") from exc


def extract_entry(archive: zipfile.ZipFile, info: zipfile.ZipInfo, root: Path, relative: str) -> None:
    target = safe_join(root, relative)
    if info.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(info) as source, target.open("wb") as stream:
        shutil.copyfileobj(source, stream, 256 * 1024)


def pack_dependencies(dependencies: dict[str, str]) -> tuple[str, str, str]:
    if not isinstance(dependencies, dict):
        raise UserError("Некорректные зависимости сборки.")
    mc = version_id(dependencies.get("minecraft", ""))
    loader_keys = {"fabric-loader": "fabric", "quilt-loader": "quilt", "forge": "forge", "neoforge": "neoforge"}
    selected = [(lid, dependencies[key]) for key, lid in loader_keys.items() if key in dependencies]
    if len(selected) > 1:
        raise UserError("У сборки не может быть нескольких загрузчиков одновременно.")
    if not selected:
        return mc, "vanilla", ""
    lid, version = selected[0]
    # Some pack formats include Minecraft's prefix in the Forge build.
    if lid == "forge":
        version = version.removeprefix(mc + "-")
    return mc, lid, version_id(version)


def import_pack(store: Store, source: Path | str, *, progress: Progress = no_progress,
                cancel: threading.Event | None = None) -> Instance:
    source = Path(source)
    stage = Path(tempfile.mkdtemp(prefix="import-", dir=store.temp_dir))
    inst = Instance(uuid.uuid4().hex, source.stem, directory=stage,
                    ram_max=int(store.settings.get("default_ram", 4096)))
    inst.game_dir.mkdir()
    try:
        with zipfile.ZipFile(source) as archive, BoundedSession() as session:
            infos = checked_zip(archive)
            names = [info.filename for info in infos if not info.is_dir()]
            roots = [n for n in names if PurePosixPath(n).name in
                     ("modrinth.index.json", "mcsync-instance.json", "mmc-pack.json")]
            if len(roots) != 1:
                raise UserError("Архив должен содержать один индекс .mrpack, MCSync или PolyMC/Prism.")
            index_name = roots[0]
            prefix = index_name[: -len(PurePosixPath(index_name).name)]
            value = zip_json(archive, index_name)
            if not isinstance(value, dict):
                raise UserError("Некорректный индекс сборки.")
            basename = PurePosixPath(index_name).name
            if basename == "modrinth.index.json":
                if value.get("formatVersion") != 1 or value.get("game") != "minecraft":
                    raise UserError("Поддерживается только Minecraft .mrpack, formatVersion 1.")
                inst.minecraft, inst.loader, inst.loader_version = pack_dependencies(value.get("dependencies", {}))
                inst.name = value.get("name", source.stem)
                entries = value.get("files", [])
                if not isinstance(entries, list) or len(entries) > MAX_FILES:
                    raise UserError("Некорректный список файлов .mrpack.")
                seen, total = set(), 0
                for index, entry in enumerate(entries):
                    check_cancel(cancel)
                    path = pack_path(entry.get("path", ""))
                    if path.casefold() in seen:
                        raise UserError("Повторяющийся путь в индексе .mrpack.")
                    seen.add(path.casefold())
                    if entry.get("env", {}).get("client") == "unsupported":
                        continue
                    urls, hashes = entry.get("downloads", []), entry.get("hashes", {})
                    if not urls or not isinstance(urls, list) or not all(isinstance(u, str) for u in urls):
                        raise UserError(f"Нет адреса скачивания: {path}")
                    if any(urlsplit(u).scheme != "https" for u in urls):
                        raise UserError(".mrpack может скачивать файлы только по HTTPS.")
                    digest = hashes.get("sha1", "")
                    if not re.fullmatch(r"[a-fA-F0-9]{40}", digest):
                        raise UserError(f"В индексе нет корректного SHA-1: {path}")
                    size = entry.get("fileSize")
                    if type(size) is not int or not 0 <= size <= MAX_FILE_SIZE:
                        raise UserError(f"Недопустимый размер файла: {path}")
                    total += size
                    if total > MAX_PACK_SIZE:
                        raise UserError(".mrpack превышает лимит 20 ГБ.")
                    progress(f"Загрузка {path}", index, len(entries))
                    last_error = None
                    for url in urls:
                        try:
                            download_file(url, safe_join(inst.game_dir, path), sha1=digest, size=size,
                                          sha512=hashes.get("sha512", ""), session=session, cancel=cancel)
                            last_error = None
                            break
                        except (requests.RequestException, UserError) as exc:
                            if isinstance(exc, Cancelled):
                                raise
                            last_error = exc
                    if last_error:
                        raise last_error
                # Common overrides first; client-specific overrides take precedence.
                for folder in ("overrides/", "client-overrides/"):
                    for info in infos:
                        base = prefix + folder
                        if info.filename.startswith(base) and not info.is_dir():
                            check_cancel(cancel)
                            path = pack_path(info.filename[len(base):])
                            extract_entry(archive, info, inst.game_dir, path)
            elif basename == "mcsync-instance.json":
                inst.minecraft = value.get("minecraft", inst.minecraft)
                inst.loader = value.get("loader", "vanilla")
                inst.loader_version = value.get("loader_version", "")
                for key in ("name", "notes", "group", "ram_min", "ram_max", "width", "height", "server"):
                    if key in value:
                        setattr(inst, key, value[key])
                for info in infos:
                    base = prefix + "game/"
                    if info.filename.startswith(base) and not info.is_dir():
                        check_cancel(cancel)
                        extract_entry(archive, info, inst.game_dir, pack_path(info.filename[len(base):]))
            else:
                components = value.get("components", [])
                dependencies = {}
                mapping = {"net.minecraft": "minecraft", "net.fabricmc.fabric-loader": "fabric-loader",
                           "org.quiltmc.quilt-loader": "quilt-loader", "net.minecraftforge": "forge",
                           "net.neoforged": "neoforge", "net.neoforged.neoforge": "neoforge"}
                for component in components:
                    if component.get("uid") in mapping:
                        dependencies[mapping[component["uid"]]] = component.get("version", "")
                inst.minecraft, inst.loader, inst.loader_version = pack_dependencies(dependencies)
                config_name = prefix + "instance.cfg"
                if config_name in names:
                    if archive.getinfo(config_name).file_size > MAX_JSON_SIZE:
                        raise UserError("Слишком большой instance.cfg.")
                    text = archive.read(config_name).decode("utf-8-sig")
                    cfg = configparser.ConfigParser(interpolation=None, strict=False)
                    cfg.read_string(text if text.lstrip().startswith("[") else "[General]\n" + text)
                    if cfg.has_section("General"):
                        inst.name = cfg.get("General", "name", fallback=inst.name)
                        inst.notes = cfg.get("General", "notes", fallback="")
                for info in infos:
                    for folder in (".minecraft/", "minecraft/", "game/"):
                        base = prefix + folder
                        if info.filename.startswith(base) and not info.is_dir():
                            check_cancel(cancel)
                            path = info.filename[len(base):]
                            # Prism exports may contain libraries/logs; import game content only.
                            if path.split("/", 1)[0] in PACK_FOLDERS or path in PACK_FILES:
                                extract_entry(archive, info, inst.game_dir, pack_path(path))
                            break
        # Never import local commands, Java paths, bearer links, tokens or account data.
        inst.validate()
        check_cancel(cancel)
        destination = store.instances_dir / inst.id
        atomic_json(stage / "instance.json", inst.to_dict())
        os.replace(stage, destination)
        inst.directory = destination
        return inst
    except (zipfile.BadZipFile, KeyError, TypeError, AttributeError, configparser.Error) as exc:
        raise UserError("Не удалось прочитать формат архива сборки.") from exc
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def export_pack(inst: Instance, destination: Path | str, *, mrpack: bool = False,
                include_worlds: bool = False, progress: Progress = no_progress,
                cancel: threading.Event | None = None) -> Path:
    destination = Path(destination).resolve()
    if destination.is_relative_to(inst.directory.resolve()):
        raise UserError("Экспортируйте архив за пределы каталога сборки.")
    metadata = inst.to_dict()
    for key in ("id", "java", "pre_command", "post_command", "jvm_args", "sync_url",
                "last_sync_rev", "playtime", "created_at"):
        metadata.pop(key, None)
    if mrpack:
        dependencies = {"minecraft": inst.minecraft}
        if inst.loader != "vanilla":
            key = {"fabric": "fabric-loader", "quilt": "quilt-loader", "forge": "forge", "neoforge": "neoforge"}[inst.loader]
            dependencies[key] = resolve_loader_version(inst)
        index = {"formatVersion": 1, "game": "minecraft", "name": inst.name,
                 "versionId": time.strftime("%Y%m%d%H%M%S"), "dependencies": dependencies, "files": []}
    files = [(relative, path) for relative, path in iter_files(inst.game_dir)
             if (relative.split("/", 1)[0] in PACK_FOLDERS or relative in PACK_FILES)
             and (include_worlds or not relative.startswith("saves/"))]
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + ".part")
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            archive.writestr("modrinth.index.json" if mrpack else "mcsync-instance.json",
                             json_bytes(index if mrpack else metadata))
            for i, (relative, path) in enumerate(files):
                check_cancel(cancel)
                progress(f"Экспорт {relative}", i, len(files))
                archive.write(path, ("overrides/" if mrpack else "game/") + relative)
        os.replace(part, destination)
    finally:
        part.unlink(missing_ok=True)
    return destination


def import_world(inst: Instance, source: Path | str) -> Path:
    source = Path(source)
    name = source.stem if source.is_file() else source.name
    relative_path(name)
    destination = safe_join(inst.game_dir / "saves", name)
    if destination.exists():
        raise UserError("Мир с таким названием уже существует. Переименуйте импортируемую папку/архив.")
    stage = Path(tempfile.mkdtemp(prefix="world-", dir=inst.directory))
    try:
        if source.is_dir():
            copy_tree_safe(source, stage)
        else:
            with zipfile.ZipFile(source) as archive:
                infos = checked_zip(archive)
                names = [i.filename for i in infos if not i.is_dir()]
                if "level.dat" in names:
                    prefix = ""
                else:
                    worlds = [n for n in names if n.endswith("/level.dat") and n.count("/") == 1]
                    if len(worlds) != 1:
                        raise UserError("В ZIP должна быть одна папка мира с level.dat.")
                    prefix = worlds[0].removesuffix("level.dat")
                for info in infos:
                    if not info.is_dir() and info.filename.startswith(prefix):
                        extract_entry(archive, info, stage, info.filename[len(prefix):])
        if not (stage / "level.dat").is_file():
            raise UserError("Это не папка мира Minecraft: отсутствует level.dat.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(stage, destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return destination


def toggle_files(inst: Instance, folder: str, paths: list[str], *,
                 progress: Progress = no_progress, cancel: threading.Event | None = None) -> None:
    """Enable/disable a selection atomically; conflicts never leave a half-toggled set."""
    if inst.sync_url:
        raise UserError("Состав файлов подписки меняет хост.")
    if folder not in ("mods", "resourcepacks", "shaderpacks"):
        raise UserError("Эту папку нельзя переключать.")
    if not paths:
        return
    operations, expected = [], {}
    for name in dict.fromkeys(paths):
        relative_path(name)
        source = folder + "/" + name
        target = source.removesuffix(".disabled") if source.endswith(".disabled") else source + ".disabled"
        if safe_join(inst.game_dir, target).exists():
            raise UserError(f"Уже существует {target}; сначала разрешите конфликт.")
        digest = fingerprint(inst.game_dir, source)
        if digest is None:
            raise UserError(f"Файл исчез: {source}")
        operations.append((source, target))
        expected[source], expected[target] = digest, None
    with FileTransaction(inst) as transaction:
        replacements = {}
        for index, (source, target) in enumerate(operations):
            check_cancel(cancel)
            progress("Переключение " + source, index, len(operations))
            staged = transaction.staged_path(target)
            staged.parent.mkdir(parents=True, exist_ok=True)
            with safe_join(inst.game_dir, source).open("rb") as incoming, staged.open("wb") as outgoing:
                for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
                    check_cancel(cancel)
                    outgoing.write(chunk)
            replacements[target] = staged
        transaction.commit(replacements, [source for source, _ in operations], {}, expected, cancel)


class ModrinthClient:
    API = "https://api.modrinth.com/v2"

    def __init__(self):
        self.session = BoundedSession()

    def __enter__(self) -> ModrinthClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.session.close()

    def get(self, path: str, **params: Any) -> Any:
        return fetch_json(self.session, self.API + path, params=params)

    def search(self, query: str, project_type: str, inst: Instance | None,
               offset: int = 0) -> list[dict[str, Any]]:
        facets = [[f"project_type:{project_type}"]]
        if inst is not None:
            facets.append([f"versions:{inst.minecraft}"])
            if project_type == "mod" and inst.loader != "vanilla":
                facets.append([f"categories:{inst.loader}"])
        result = self.get("/search", query=query, facets=json.dumps(facets), limit=30, offset=offset)
        if (not isinstance(result, dict) or not isinstance(result.get("hits"), list)
                or any(not isinstance(hit, dict) or not isinstance(hit.get("project_id"), str)
                       or not isinstance(hit.get("title"), str) or not isinstance(hit.get("description", ""), str)
                       for hit in result["hits"])):
            raise UserError("Modrinth вернул некорректные результаты поиска.")
        return result["hits"]

    def versions(self, project_id: str, inst: Instance) -> list[dict[str, Any]]:
        params = {"game_versions": json.dumps([inst.minecraft])}
        project = self.get(f"/project/{quote(project_id, safe='')}")
        # A modpack creates a NEW instance and chooses its own loader from its index.
        if inst.loader != "vanilla" and project.get("project_type") == "mod":
            params["loaders"] = json.dumps([inst.loader])
        versions = self.get(f"/project/{quote(project_id, safe='')}/version", **params)
        return sorted(versions, key=lambda v: (v.get("version_type") == "release", v.get("date_published", "")), reverse=True)

    def latest(self, project_id: str, inst: Instance) -> dict[str, Any]:
        versions = self.versions(project_id, inst)
        if not versions:
            raise UserError(f"Нет совместимой версии проекта {project_id} для {inst.minecraft} / {LOADERS[inst.loader]}.")
        return versions[0]


def install_modrinth(inst: Instance, project_id: str, *, client: ModrinthClient | None = None,
                     selected_version: dict[str, Any] | None = None, progress: Progress = no_progress,
                     cancel: threading.Event | None = None) -> list[str]:
    """Resolve required dependencies (including pinned versions) before touching files."""
    if inst.sync_url:
        raise UserError("Моды синхронизируемой сборки меняет хост. Установите проект у него.")
    own_client = client is None
    client = client or ModrinthClient()
    tracker = read_json(inst.directory / "modrinth.json", {})
    if not isinstance(tracker, dict):
        raise UserError("Некорректный modrinth.json.")
    resolved: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    titles = []

    def resolve(pid: str, version: dict[str, Any] | None = None) -> None:
        check_cancel(cancel)
        version = version or client.latest(pid, inst)
        pid = version.get("project_id", pid)
        if pid in resolved:
            if resolved[pid][1]["id"] != version["id"]:
                raise UserError("Зависимости требуют разные версии одного мода; установка отменена.")
            return
        project = client.get(f"/project/{quote(pid, safe='')}")
        kind = project.get("project_type", "mod")
        if kind not in ("mod", "resourcepack", "shader"):
            raise UserError("Для сборок Modrinth используйте установку .mrpack в новую сборку.")
        if inst.minecraft not in version.get("game_versions", []):
            raise UserError(f"{project['title']}: закреплённая зависимость несовместима с Minecraft.")
        if kind == "mod" and (inst.loader == "vanilla" or inst.loader not in version.get("loaders", [])):
            raise UserError(f"{project['title']}: нужен совместимый загрузчик модов, не Vanilla.")
        resolved[pid] = (project, version)  # mark before recursion; cycles cannot loop forever
        for dependency in version.get("dependencies", []):
            if dependency.get("dependency_type") != "required":
                continue
            if dependency.get("version_id"):
                pinned = client.get(f"/version/{quote(dependency['version_id'], safe='')}")
                resolve(pinned["project_id"], pinned)
            elif dependency.get("project_id"):
                resolve(dependency["project_id"])
            else:
                raise UserError(f"Не удалось разрешить обязательную зависимость {project['title']}.")

    try:
        resolve(project_id, selected_version)
        replacements, deletions, expected = {}, set(), {}
        updated = copy.deepcopy(tracker)
        with FileTransaction(inst) as transaction:
            for index, (pid, (project, version)) in enumerate(resolved.items()):
                check_cancel(cancel)
                files = version.get("files", [])
                if not files:
                    raise UserError("Modrinth не вернул файл версии.")
                item = next((f for f in files if f.get("primary")), files[0])
                filename = relative_path(item["filename"])
                if "/" in filename:
                    raise UserError("Modrinth вернул некорректное имя файла.")
                folder = {"mod": "mods", "resourcepack": "resourcepacks", "shader": "shaderpacks"}[project["project_type"]]
                old = tracker.get(pid, {})
                old_path = old.get("path", "")
                if old_path:
                    pack_path(old_path)
                if old_path and fingerprint(inst.game_dir, old_path + ".disabled") is not None:
                    old_path += ".disabled"
                    filename += ".disabled"
                relative = folder + "/" + filename
                current = fingerprint(inst.game_dir, relative)
                if current is not None and relative != old_path:
                    if current != item.get("hashes", {}).get("sha1"):
                        raise UserError(f"{relative} уже существует и не принадлежит этому проекту.")
                if old_path and old_path != relative and fingerprint(inst.game_dir, old_path) is not None:
                    old_hash = fingerprint(inst.game_dir, old_path)
                    if old_hash != old.get("sha1"):
                        raise UserError(f"{old_path} изменён вручную. Обновление отменено, чтобы не потерять файл.")
                    if any(v.get("path") in (old_path, old_path.removesuffix(".disabled")) for k, v in tracker.items() if k != pid):
                        raise UserError("Файл используется несколькими проектами; автоматическое удаление запрещено.")
                    deletions.add(old_path)
                    expected[old_path] = old_hash
                digest = item.get("hashes", {}).get("sha1", "")
                if not re.fullmatch(r"[a-fA-F0-9]{40}", digest):
                    raise UserError("Modrinth не вернул корректный SHA-1.")
                if relative in replacements:
                    raise UserError("Разные проекты пытаются установить файл с одним именем.")
                expected[relative] = current
                staged = transaction.staged_path(relative)
                progress(f"Установка {project['title']}", index, len(resolved))
                if urlsplit(item["url"]).scheme != "https":
                    raise UserError("Скачивание Modrinth должно использовать HTTPS.")
                download_file(item["url"], staged, sha1=digest, size=item["size"],
                              sha512=item.get("hashes", {}).get("sha512", ""),
                              session=client.session, cancel=cancel)
                replacements[relative] = staged
                updated[pid] = {"project_id": pid, "version_id": version["id"], "title": project["title"],
                                "path": relative.removesuffix(".disabled"), "sha1": digest.lower()}
                titles.append(project["title"])
            transaction.commit(replacements, sorted(deletions - set(replacements)),
                               {"modrinth.json": updated}, expected, cancel)
        return titles
    finally:
        if own_client:
            client.__exit__()


def update_modrinth(inst: Instance, *, progress: Progress = no_progress,
                    cancel: threading.Event | None = None) -> list[str]:
    tracker = read_json(inst.directory / "modrinth.json", {})
    updated = []
    with ModrinthClient() as client:
        for index, pid in enumerate(list(tracker)):
            check_cancel(cancel)
            progress(f"Проверка {tracker[pid].get('title', pid)}", index, len(tracker))
            latest = client.latest(pid, inst)
            if latest["id"] != tracker[pid].get("version_id"):
                updated.extend(install_modrinth(inst, pid, client=client, selected_version=latest,
                                               progress=progress, cancel=cancel))
                tracker = read_json(inst.directory / "modrinth.json", {})
    return list(dict.fromkeys(updated))


def install_modrinth_pack(store: Store, project_id: str, inst: Instance | None = None, *,
                          progress: Progress = no_progress, cancel: threading.Event | None = None) -> Instance:
    with ModrinthClient() as client:
        if inst is None:
            versions = client.get(f"/project/{quote(project_id, safe='')}/version")
            versions.sort(key=lambda v: v.get("date_published", ""), reverse=True)
            if not versions:
                raise UserError("У проекта нет доступных версий.")
            version = versions[0]
        else:
            version = client.latest(project_id, inst)
        files = version["files"]
        item = next((f for f in files if f.get("primary") and f["filename"].endswith(".mrpack")),
                    next((f for f in files if f["filename"].endswith(".mrpack")), None))
        if item is None:
            raise UserError("У этой сборки нет .mrpack-файла.")
        stage = Path(tempfile.mkdtemp(prefix="modrinth-", dir=store.temp_dir))
        try:
            target = stage / "pack.mrpack"
            if urlsplit(item["url"]).scheme != "https":
                raise UserError("Скачивание Modrinth должно использовать HTTPS.")
            download_file(item["url"], target, sha1=item["hashes"]["sha1"], size=item["size"],
                          session=client.session, cancel=cancel, progress=progress)
            return import_pack(store, target, progress=progress, cancel=cancel)
        finally:
            shutil.rmtree(stage)


class Accounts:
    """Plaintext tokens, restricted to the local user on POSIX; see security notes."""
    def __init__(self, store: Store):
        self.path = store.root / "accounts.json"
        self.lock = threading.RLock()
        self.load_error = ""
        self.data = {"selected": "", "accounts": []}
        try:
            data = read_json(self.path, self.data)
            if not isinstance(data, dict) or not isinstance(data.get("accounts"), list):
                raise UserError("Некорректный accounts.json.")
            valid, seen = [], set()
            for account in data["accounts"]:
                if not self.valid_profile(account) or account["id"] in seen:
                    self.load_error = "В accounts.json есть повреждённые или повторные профили. Они не используются; оригинал сохранён."
                    continue
                seen.add(account["id"])
                valid.append(account)
            selected = data.get("selected", "")
            if not isinstance(selected, str):
                self.load_error = "Некорректный выбранный аккаунт. Использован первый исправный профиль."
            self.data = {"accounts": valid, "selected": selected if isinstance(selected, str) and selected in seen else (valid[0]["id"] if valid else "")}
        except UserError as exc:
            self.load_error = str(exc)

    @staticmethod
    def valid_profile(account: Any) -> bool:
        if (not isinstance(account, dict) or not isinstance(account.get("id"), str)
                or not re.fullmatch(r"[a-fA-F0-9]{32}", account["id"])
                or not isinstance(account.get("name"), str) or not re.fullmatch(r"[A-Za-z0-9_]{1,16}", account["name"])
                or account.get("type") not in ("offline", "microsoft")):
            return False
        if any(key in account and not isinstance(account[key], str) for key in ("access_token", "refresh_token")):
            return False
        expires = account.get("expires_at", 0)
        return type(expires) in (int, float) and math.isfinite(expires) and expires >= 0

    def save(self) -> None:
        with self.lock:
            if self.load_error:
                backup_private_file(self.path)
            atomic_json(self.path, self.data)
            self.load_error = ""
            if os.name != "nt":
                self.path.chmod(0o600)

    def add_offline(self, name: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", name):
            raise UserError("Ник: 3–16 латинских букв, цифр или символов подчёркивания.")
        digest = hashlib.md5(("OfflinePlayer:" + name).encode("utf-8")).digest()
        account = {"id": uuid.UUID(bytes=digest, version=3).hex, "name": name, "type": "offline"}
        self.put(account)
        return account

    def put(self, account: dict[str, Any]) -> None:
        if not self.valid_profile(account):
            raise UserError("Некорректный профиль аккаунта.")
        with self.lock:
            self.data["accounts"] = [a for a in self.data["accounts"] if a["id"] != account["id"]] + [account]
            self.data["selected"] = account["id"]
            self.save()

    def selected(self) -> dict[str, Any] | None:
        with self.lock:
            return copy.deepcopy(next((a for a in self.data["accounts"]
                                       if a["id"] == self.data.get("selected")), None))

    def remove(self, account_id: str) -> None:
        with self.lock:
            self.data["accounts"] = [a for a in self.data["accounts"] if a["id"] != account_id]
            if self.data.get("selected") == account_id:
                self.data["selected"] = self.data["accounts"][0]["id"] if self.data["accounts"] else ""
            self.save()


class MicrosoftAuth:
    BASE = "https://login.microsoftonline.com/consumers/oauth2/v2.0"

    def __init__(self, client_id: str):
        if not isinstance(client_id, str) or not re.fullmatch(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}", client_id.strip()):
            raise UserError("Укажите свой Azure Application (Client) ID в настройках. "
                            "Нужны public client/device code flow и одобрение Mojang: aka.ms/AppRegInfo.")
        self.client_id = client_id.strip()
        self.session = BoundedSession()

    def __enter__(self) -> MicrosoftAuth:
        return self

    def __exit__(self, *args: Any) -> None:
        self.session.close()

    def start_device(self) -> dict[str, Any]:
        with self.session.post(self.BASE + "/devicecode", data={
                "client_id": self.client_id, "scope": "XboxLive.signin offline_access"}) as response:
            if not response.ok:
                raise UserError("Microsoft отклонил device code flow. Проверьте Client ID и настройки public client.")
            return response.json()

    def poll_device(self, device: dict[str, Any], cancel: threading.Event) -> dict[str, Any]:
        end = time.monotonic() + int(device.get("expires_in", 900))
        interval = max(1, int(device.get("interval", 5)))
        while time.monotonic() < end:
            if cancel.wait(interval):
                raise Cancelled("Вход отменён.")
            with self.session.post(self.BASE + "/token", data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": self.client_id, "device_code": device["device_code"]}) as response:
                data = response.json()
                if response.ok:
                    return self.exchange(data)
                error = data.get("error")
                if error == "authorization_pending":
                    continue
                if error == "slow_down":
                    interval += 5
                    continue
                raise UserError("Вход Microsoft отменён, код истёк или приложение не разрешено. Повторите вход.")
        raise UserError("Код Microsoft истёк. Начните вход заново.")

    def refresh(self, account: dict[str, Any]) -> dict[str, Any]:
        with self.session.post(self.BASE + "/token", data={
                "grant_type": "refresh_token", "client_id": self.client_id,
                "refresh_token": account.get("refresh_token", ""),
                "scope": "XboxLive.signin offline_access"}) as response:
            if not response.ok:
                raise UserError("Сессия Microsoft истекла. Войдите снова в окне аккаунтов.")
            tokens = response.json()
            tokens.setdefault("refresh_token", account.get("refresh_token", ""))
            return self.exchange(tokens)

    def post_json(self, url: str, data: dict[str, Any], error: str) -> dict[str, Any]:
        with self.session.post(url, json=data) as response:
            if not response.ok:
                raise UserError(error)
            return response.json()

    def exchange(self, tokens: dict[str, Any]) -> dict[str, Any]:
        xbl = self.post_json("https://user.auth.xboxlive.com/user/authenticate", {
            "Properties": {"AuthMethod": "RPS", "SiteName": "user.auth.xboxlive.com",
                           "RpsTicket": "d=" + tokens["access_token"]},
            "RelyingParty": "http://auth.xboxlive.com", "TokenType": "JWT"},
            "Xbox Live отклонил вход. Проверьте наличие профиля Xbox у аккаунта.")
        xsts = self.post_json("https://xsts.auth.xboxlive.com/xsts/authorize", {
            "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl["Token"]]},
            "RelyingParty": "rp://api.minecraftservices.com/", "TokenType": "JWT"},
            "XSTS отклонил вход. Проверьте профиль Xbox, возрастные и региональные ограничения.")
        uhs = xsts["DisplayClaims"]["xui"][0]["uhs"]
        mc = self.post_json("https://api.minecraftservices.com/authentication/login_with_xbox", {
            "identityToken": f"XBL3.0 x={uhs};{xsts['Token']}"},
            "Minecraft отклонил приложение. Client ID должен быть одобрен Mojang (aka.ms/AppRegInfo).")
        with self.session.get("https://api.minecraftservices.com/minecraft/profile", headers={
                "Authorization": "Bearer " + mc["access_token"]}) as response:
            if not response.ok:
                raise UserError("Нет доступного профиля Minecraft Java. Нужна лицензия и созданный игровой профиль.")
            profile = response.json()
        return {"id": profile["id"], "name": profile["name"], "type": "microsoft",
                "access_token": mc["access_token"], "refresh_token": tokens["refresh_token"],
                "expires_at": time.time() + int(mc.get("expires_in", 86400)),
                "skins": profile.get("skins", []), "client_id": self.client_id}


def launch_account(accounts: Accounts, store: Store) -> dict[str, Any]:
    account = accounts.selected()
    if account is None:
        raise UserError("Добавьте и выберите аккаунт перед запуском игры.")
    if account["type"] == "microsoft" and account.get("expires_at", 0) < time.time() + 120:
        with MicrosoftAuth(account.get("client_id") or store.settings.get("client_id", "")) as auth:
            account = auth.refresh(account)
        accounts.put(account)
    return account


def skin_url(account: dict[str, Any]) -> str:
    skins = account.get("skins", [])
    active = next((skin for skin in skins if skin.get("state") == "ACTIVE"), skins[0] if skins else {})
    url = active.get("url", "")
    parsed = urlsplit(url)
    if parsed.hostname == "textures.minecraft.net" and parsed.scheme in ("http", "https"):
        return urlunsplit(("https", parsed.netloc, parsed.path, "", ""))
    if url:
        raise UserError("Неподдерживаемый адрес скина.")
    return ""


def download_skin(account: dict[str, Any]) -> bytes:
    url = skin_url(account)
    if not url:
        raise UserError("У аккаунта нет опубликованного скина. Можно открыть локальный PNG для предпросмотра.")
    with BoundedSession() as session, session.get(url, stream=True) as response:
        response.raise_for_status()
        data = bytearray()
        for chunk in response.iter_content(65536):
            data.extend(chunk)
            if len(data) > 512 * 1024:
                raise UserError("Файл скина слишком большой.")
    return bytes(data)


def split_args(text: str) -> list[str]:
    try:
        lexer = shlex.shlex(text, posix=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        if os.name == "nt":
            lexer.escape = ""  # preserve C:\paths; remove grouping quotes, not backslashes
        return list(lexer)
    except ValueError as exc:
        raise UserError("В JVM-аргументах не закрыта кавычка.") from exc


def java_launcher_path(executable: str) -> str:
    """Use console Java with CREATE_NO_WINDOW so Windows output/errors are captured."""
    if Path(executable).name.lower() == "javaw.exe":
        located = shutil.which(executable) or executable
        sibling = Path(located).with_name("java.exe")
        if sibling.is_file():
            return str(sibling)
    return executable


def java_major_version(executable: str) -> int:
    executable = java_launcher_path(executable)
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        result = subprocess.run([executable, "-version"], capture_output=True, text=True,
                                errors="replace", timeout=15, creationflags=flags)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UserError("Не удалось выполнить выбранную Java (проверка -version).") from exc
    found = re.search(r'(?:version\s+"|openjdk\s+)(\d+)(?:\.(\d+))?', result.stderr + result.stdout)
    if result.returncode != 0 or not found:
        raise UserError("Не удалось определить версию выбранного Java executable.")
    major = int(found.group(1))
    return int(found.group(2)) if major == 1 and found.group(2) else major


def parse_server(value: str) -> tuple[str, str]:
    if not value:
        return "", ""
    try:
        parsed = urlsplit("//" + value)
        port = 25565 if parsed.port is None else parsed.port
    except ValueError as exc:
        raise UserError("Некорректный адрес/порт Minecraft-сервера.") from exc
    if (not parsed.hostname or parsed.path or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not 1 <= port <= 65535 or value.endswith(":") or any(c in value for c in "/?#@")
            or any(c.isspace() for c in value)):
        raise UserError("Нужен адрес сервера вида play.example.org:25565.")
    return parsed.hostname, str(port)


def ensure_install(store: Store, inst: Instance, *, repair: bool = False,
                   progress: Progress = no_progress, cancel: threading.Event | None = None) -> tuple[Instance, str, str]:
    lib = launcher_lib()
    with INSTALL_LOCK:
        check_cancel(cancel)
        backend = loader_backend(inst.loader, lib) if inst.loader != "vanilla" else None
        concrete = resolve_loader_version(inst, backend=backend)
        if inst.loader_version != concrete:
            inst = store.update(inst.id, loader_version=concrete)
        installed_version = inst.minecraft if backend is None else backend.get_installed_version(inst.minecraft, concrete)
        version_id(installed_version)
        marker_path = inst.directory / "installed.json"
        try:
            marker = read_json(marker_path, {})
        except UserError:
            marker = {}
            LOG.warning("Некорректный installed.json у %s; установка будет проверена заново.", inst.id)
        if not isinstance(marker, dict):
            marker = {}
        client_json = store.minecraft_dir / "versions" / inst.minecraft / (inst.minecraft + ".json")
        launch_json = store.minecraft_dir / "versions" / installed_version / (installed_version + ".json")
        ready = (marker.get("identity") == list(inst.identity) and marker.get("version") == installed_version
                 and client_json.is_file() and launch_json.is_file())
        state = {"max": 0}

        def callback_status(message: str) -> None:
            check_cancel(cancel)
            progress(message, 0, 0)

        callbacks = {"setStatus": callback_status,
                     "setMax": lambda n: state.update(max=max(1, n)),
                     "setProgress": lambda n: (check_cancel(cancel), progress("Установка Minecraft / Java", n, state["max"]))}
        if repair or not ready:
            progress(f"Установка Minecraft {inst.minecraft}…", 0, 0)
            lib.install.install_minecraft_version(inst.minecraft, store.minecraft_dir, callback=callbacks)
        info = lib.runtime.get_version_runtime_information(inst.minecraft, store.minecraft_dir)
        component = info["name"] if info else "jre-legacy"
        required_major = info["javaMajorVersion"] if info else 8
        java = java_launcher_path(inst.java.strip())
        if java:
            if not Path(java).is_file() and not shutil.which(java):
                raise UserError("Указанный Java executable не найден.")
            major = java_major_version(java)
            if major < required_major:
                raise UserError(f"Нужна Java {required_major} или новее; выбрана Java {major}. Выберите «Авто».")
        else:
            java = lib.runtime.get_executable_path(component, store.minecraft_dir) or ""
            if not java or not Path(java).is_file():
                progress(f"Установка Java {required_major} от Mojang…", 0, 0)
                lib.runtime.install_jvm_runtime(component, store.minecraft_dir, callback=callbacks)
                java = lib.runtime.get_executable_path(component, store.minecraft_dir) or ""
            if not java or not Path(java).is_file():
                raise UserError("Mojang Java недоступна для этой платформы. Установите Java вручную и укажите путь.")
        java = java_launcher_path(java)
        if (repair or not ready) and inst.loader != "vanilla":
            check_cancel(cancel)
            progress(f"Установка {LOADERS[inst.loader]} {concrete}…", 0, 0)
            installed_version = backend.install(
                inst.minecraft, store.minecraft_dir, loader_version=concrete, callback=callbacks, java=java)
        check_cancel(cancel)
        atomic_json(marker_path, {"identity": list(inst.identity), "version": installed_version, "java": java})
        return inst, installed_version, java


def minecraft_command(store: Store, inst: Instance, version: str, java: str,
                      account: dict[str, Any]) -> list[str]:
    inst.validate()
    arguments = split_args(inst.jvm_args)
    # Exactly one RAM pair; user-specified JVM RAM flags do not override the UI silently.
    arguments = [arg for arg in arguments if not arg.startswith(("-Xmx", "-Xms"))]
    options = {"username": account["name"], "uuid": account["id"],
               "token": account.get("access_token", "0"), "executablePath": java,
               "jvmArguments": [f"-Xms{inst.ram_min}M", f"-Xmx{inst.ram_max}M", *arguments],
               "launcherName": "SYNCMC", "launcherVersion": APP_VERSION,
               "gameDirectory": str(inst.game_dir), "customResolution": True,
               "resolutionWidth": str(inst.width), "resolutionHeight": str(inst.height),
               "enableLoggingConfig": True}
    if inst.server:
        host, port = parse_server(inst.server)
        release = release_tuple(inst.minecraft)
        if release and release >= (1, 20, 0):
            options["quickPlayPath"] = str(inst.directory / "quickplay.json")
            options["quickPlayMultiplayer"] = inst.server
        else:
            options["server"], options["port"] = host, port
    return launcher_lib().command.get_minecraft_command(version, store.minecraft_dir, options)


def installation_ready(store: Store, inst: Instance) -> bool:
    """Read local installation markers only. No API calls or downloads in the UI."""
    try:
        marker = read_json(inst.directory / "installed.json", {})
        if not isinstance(marker, dict) or marker.get("identity") != list(inst.identity):
            return False
        installed = version_id(marker.get("version", ""))
        return all((store.minecraft_dir / "versions" / v / (v + ".json")).is_file()
                   for v in (inst.minecraft, installed))
    except (UserError, OSError, TypeError):
        return False


def playtime_text(seconds: float) -> str:
    return f"{seconds / 3600:.1f} ч" if seconds >= 3600 else f"{seconds / 60:.0f} мин"


def diagnostic_report(store: Store) -> dict[str, Any]:
    """Shareable-ish report. Never exports account names, tokens, hooks or sync URLs."""
    checks = [{"check": "qt_runtime", "ok": QT_AVAILABLE,
               "message": "PySide6 доступен" if QT_AVAILABLE else redact(QT_IMPORT_ERROR)}]
    try:
        check_launcher_library()
        checks.append({"check": "loader_api", "ok": True, "message": "Fabric / Quilt / Forge / NeoForge доступны"})
    except (UserError, ImportError, OSError) as exc:
        checks.append({"check": "loader_api", "ok": False, "message": redact(str(exc))})
    try:
        free = shutil.disk_usage(store.root).free
        checks.append({"check": "disk", "ok": free > 256 * 1024**2, "message": f"Свободно {human_size(free)}"})
    except OSError as exc:
        checks.append({"check": "disk", "ok": False, "message": redact(str(exc))})
    instances = store.list_instances()
    accounts = Accounts(store)
    return {"application": APP_NAME, "version": APP_VERSION, "python": sys.version.split()[0],
            "platform": sys.platform, "frozen": bool(getattr(sys, "frozen", False)),
            "qt_available": QT_AVAILABLE, "data_directory": str(store.root), "checks": checks,
            "settings_warning": store.settings_error, "account_warning": accounts.load_error,
            "account_counts": {kind: sum(a["type"] == kind for a in accounts.data["accounts"])
                               for kind in ("offline", "microsoft")},
            "client_id_configured": bool(store.settings.get("client_id")),
            "instances": [{"name": i.name, "minecraft": i.minecraft, "loader": i.loader,
                           "loader_version": i.loader_version, "subscription": bool(i.sync_url),
                           "installed": installation_ready(store, i), "ram_mb": i.ram_max} for i in instances],
            "damaged_instances": dict(store.instance_errors),
            "note": "Токены, ссылки, аккаунты и команды не включены. Пути/названия сборок могут быть личными данными. "
                    "Отчёт не проверяет Microsoft-вход, интернет или совместимость модов."}


class RotatingTextLog:
    """Bound game log growth without changing the line-oriented console reader."""
    def __init__(self, path: Path, max_bytes: int = 8 * 1024**2):
        self.path, self.max_bytes = path, max_bytes
        self.stream: Any = None
        self.size = 0

    def __enter__(self) -> RotatingTextLog:
        if self.path.is_symlink():
            raise UserError("Журнал запуска не должен быть символической ссылкой.")
        self.size = self.path.stat().st_size if self.path.exists() else 0
        self.stream = self.path.open("a", encoding="utf-8")
        return self

    def __exit__(self, *args: Any) -> None:
        if self.stream:
            self.stream.close()

    def write(self, text: str) -> None:
        count = len(text.encode("utf-8"))
        if self.size and self.size + count > self.max_bytes:
            self.stream.close()
            old, older = self.path.with_name(self.path.name + ".1"), self.path.with_name(self.path.name + ".2")
            older.unlink(missing_ok=True)
            if old.exists():
                os.replace(old, older)
            os.replace(self.path, old)
            self.stream = self.path.open("w", encoding="utf-8")
            self.size = 0
        self.stream.write(text)
        self.size += count

    def flush(self) -> None:
        self.stream.flush()


class GameSession:
    def __init__(self, inst: Instance, command: list[str], account: dict[str, Any],
                 output: Callable[[str], None], finished: Callable[[int, float, str], None]):
        self.inst, self.command, self.account = inst, command, account
        self.output, self.finished = output, finished
        self.process: subprocess.Popen | None = None
        self.cancel = threading.Event()
        self.thread = threading.Thread(target=self.run, name=f"Minecraft-{inst.id[:6]}", daemon=True)

    def clean(self, text: str) -> str:
        token = self.account.get("access_token", "")
        text = redact(text.replace(token, "[токен скрыт]") if token else text)
        return text[:16384] + " … [строка сокращена]" if len(text) > 16384 else text

    def stop(self) -> None:
        self.cancel.set()
        process = self.process
        if process:
            threading.Thread(target=self._stop_tree, args=(process,), name="MCSync-stop-game", daemon=True).start()

    @staticmethod
    def _stop_tree(process: subprocess.Popen) -> None:
        if os.name == "nt":
            # Kill the whole tree, including children of a local shell hook. Do not
            # terminate the parent first: taskkill would then lose its descendants.
            try:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            except (OSError, subprocess.TimeoutExpired):
                with contextlib.suppress(OSError):
                    process.kill()
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            with contextlib.suppress(OSError):
                process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, signal.SIGKILL)
            with contextlib.suppress(OSError):
                process.kill()

    def run_process(self, command: list[str] | str, log: Any, *, shell: bool = False) -> int:
        check_cancel(self.cancel)
        env = os.environ.copy()
        env["MCSYNC_INSTANCE_DIR"] = str(self.inst.game_dir)
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(command, cwd=self.inst.game_dir, env=env, shell=shell,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace", creationflags=flags, start_new_session=os.name != "nt")
        if self.cancel.is_set():
            self.stop()
        for line in self.process.stdout:
            line = self.clean(line.rstrip("\n"))
            log.write(line + "\n")
            log.flush()
            self.output(line)
        return self.process.wait()

    def run(self) -> None:
        started, elapsed, code, error = 0.0, 0.0, -1, ""
        try:
            with RotatingTextLog(self.inst.directory / "launcher.log") as log:
                self.output("──────── Запуск Minecraft ────────")
                if self.inst.pre_command:
                    self.output("Выполняется локальная команда перед запуском…")
                    code = self.run_process(self.inst.pre_command, log, shell=True)
                    if code != 0:
                        raise UserError(f"Команда перед запуском завершилась с кодом {code}.")
                check_cancel(self.cancel)
                started = time.monotonic()
                code = self.run_process(self.command, log)
                elapsed = time.monotonic() - started
                started = 0
                if self.inst.post_command and not self.cancel.is_set():
                    self.output("Выполняется локальная команда после выхода…")
                    post_code = self.run_process(self.inst.post_command, log, shell=True)
                    if post_code != 0:
                        self.output(f"Команда после выхода: код {post_code}.")
        except Exception as exc:
            error = self.clean(str(exc))
        finally:
            if started:
                elapsed = time.monotonic() - started
            self.finished(code, elapsed, error)


# Importing the core/test suite does not require a graphical session or Qt libraries.
QT_IMPORT_ERROR = ""
try:
    from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, QTimer, QUrl, QLockFile, QPropertyAnimation, QVariantAnimation, QEasingCurve, Signal, Slot
    from PySide6.QtGui import (QColor, QDesktopServices, QFont, QFontMetrics, QIcon, QImage, QKeySequence, QShortcut,
                              QLinearGradient, QPainter, QPainterPath, QPalette, QPixmap, QPolygon)
    from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
                                  QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGraphicsOpacityEffect,
                                  QHBoxLayout, QInputDialog, QLabel,
                                  QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                                  QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                                  QScrollArea, QSpinBox, QSplitter, QStackedWidget, QStyle,
                                  QStyledItemDelegate, QTabWidget, QToolButton, QVBoxLayout,
                                  QWidget)
    QT_AVAILABLE = True
except ImportError as exc:
    QT_AVAILABLE, QT_IMPORT_ERROR = False, str(exc)


if QT_AVAILABLE:
    def theme_style(key: str = DEFAULT_THEME) -> str:
        colors = dict(THEMES[theme_key(key)])
        colors["success"] = "#23764c" if theme_key(key) == "paper" else "#7ee7b5"
        stylesheet = """
        QWidget { color: @text; font-size: 13px; }
        QMainWindow, QDialog, QWidget#central, QWidget#overviewContent { background: @bg; }
        QLabel { background: transparent; }
        QLabel#brand { font-size: 24px; font-weight: 700; color: @text; }
        QLabel#pageTitle { font-size: 19px; font-weight: 600; }
        QLabel#title { font-size: 26px; font-weight: 700; }
        QLabel#sectionTitle { font-size: 14px; font-weight: 600; }
        QLabel#statValue { font-size: 24px; font-weight: 700; }
        QPushButton#segment:checked, QPushButton#nav:checked { background: @soft; color: @accent; border-color: @border; }
        QPushButton#nav { text-align: left; }
        QLabel#notice { color: @warning; background: @raised; border-radius: 6px; padding: 7px; }
        QLabel#muted { color: @muted; }
        QLabel#kicker { color: @muted; font-size: 10px; font-weight: 600; }
        QLabel#warning { color: @warning; }
        QLabel#badge { background: @soft; color: @accent; border-radius: 6px; padding: 5px 9px; font-size: 11px; }
        QLabel#badge[status="local"] { color: @muted; background: @raised; }
        QLabel#badge[status="pending"] { color: @warning; background: @raised; }
        QLabel#badge[connected="true"] { color: @success; background: @raised; }
        QFrame#sidebar { background: @sidebar; border: none; border-radius: 16px; }
        QFrame#card { background: @surface; border: none; border-radius: 14px; }
        QFrame#statCard { background: transparent; border: none; border-radius: 10px; }
        QFrame#statCard[interactive="true"]:hover, QFrame#statCard:focus { background: @raised; }
        QFrame#statStrip { background: @surface; border: none; border-radius: 14px; }
        QLabel#statValue { font-size: 28px; font-weight: 700; }
        QFrame#partyCard { background: @surface; border: none; border-radius: 14px; }
        QListWidget#partyRoster { background: transparent; border: none; padding: 0; }
        QListWidget#partyRoster::item { margin: 0; padding: 0; }
        QLabel#flowHint { color: @muted; font-size: 12px; padding: 2px 4px; }
        QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {
            background: @raised; border: 1px solid @border; border-radius: 7px;
            padding: 7px 9px; min-height: 20px; selection-background-color: @soft;
            selection-color: @text;
        }
        QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: @accent; }
        QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: @muted; background: @surface; }
        QComboBox::drop-down { width: 25px; border: none; }
        QSpinBox::up-button, QSpinBox::down-button { width: 20px; border: none; }
        QComboBox QAbstractItemView { background: @surface; color: @text; selection-background-color: @soft; }
        QPushButton, QToolButton {
            background: @raised; border: 1px solid @border; border-radius: 7px;
            padding: 8px 12px; min-height: 20px; font-weight: 500;
        }
        QPushButton:hover, QToolButton:hover { background: @soft; border-color: @accent; }
        QPushButton:pressed, QToolButton:pressed { background: @surface; }
        QPushButton:disabled, QToolButton:disabled { color: @muted; background: @surface; border-color: @border; }
        QPushButton#play, QPushButton#primary { background: @accent; color: @on_accent; font-weight: 700; border: none; }
        QPushButton#play { padding: 12px 25px; font-size: 15px; border-radius: 11px; }
        QPushButton#nav { padding: 10px 14px; border: none; border-radius: 10px; }
        QPushButton#segment { padding: 6px 12px; min-height: 18px; border: none; }
        QPushButton#play:hover, QPushButton#primary:hover { background: @hover; }
        QPushButton#play:disabled, QPushButton#primary:disabled { background: @soft; color: @muted; }
        QPushButton#ghost, QToolButton#ghost { background: transparent; border-color: transparent; }
        QPushButton#ghost:hover, QToolButton#ghost:hover { background: @raised; border-color: @border; }
        QPushButton#danger { color: @danger; }
        QPushButton#danger:disabled { color: @muted; }
        QListWidget { background: @surface; border: 1px solid @border; border-radius: 9px; outline: none; padding: 5px; }
        QListWidget#instances, QListWidget#libraryGrid { background: transparent; border: none; padding: 0; }
        QListWidget::item { padding: 11px 9px; border-radius: 6px; margin: 2px; }
        QListWidget::item:selected { background: @soft; color: @text; }
        QListWidget::item:hover:!selected { background: @raised; }
        QTabWidget::pane { border: none; background: transparent; }
        QTabBar { background: transparent; }
        QTabBar::tab {
            background: transparent; color: @muted; padding: 10px 12px;
            border-bottom: 2px solid @border; margin-bottom: 8px;
        }
        QTabBar::tab:selected { color: @text; border-bottom-color: @accent; }
        QTabBar::tab:hover { color: @accent; }
        QTabBar::tab:disabled { color: @muted; }
        QScrollArea { border: none; background: transparent; }
        QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
        QScrollBar:horizontal { background: transparent; height: 8px; margin: 0; }
        QScrollBar::handle { background: @border; border-radius: 4px; min-height: 24px; min-width: 24px; }
        QScrollBar::handle:hover { background: @muted; }
        QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
        QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
        QProgressBar { border: none; border-radius: 4px; text-align: center; background: @raised; min-height: 10px; }
        QProgressBar::chunk { background: @accent; border-radius: 4px; }
        QCheckBox { padding: 4px 0; spacing: 8px; }
        QSplitter::handle { background: transparent; width: 12px; }
        QMenu { background: @surface; border: 1px solid @border; border-radius: 8px; padding: 6px; }
        QMenu::item { padding: 8px 24px 8px 12px; border-radius: 5px; }
        QMenu::item:selected { background: @soft; }
        QMenu::separator { height: 1px; background: @border; margin: 5px; }
        QStatusBar { background: @bg; color: @muted; font-size: 11px; }
        QStatusBar::item { border: none; }
        QToolTip { background: @surface; color: @text; border: 1px solid @border; padding: 6px; }
        """
        for token, color in colors.items():
            stylesheet = stylesheet.replace("@" + token, color)
        return stylesheet

    STYLE = theme_style()

    def apply_theme(app: QApplication, key: str) -> None:
        colors = THEMES[theme_key(key)]
        palette = QPalette()
        for role, token in ((QPalette.ColorRole.Window, "bg"), (QPalette.ColorRole.WindowText, "text"),
                            (QPalette.ColorRole.Base, "surface"), (QPalette.ColorRole.AlternateBase, "raised"),
                            (QPalette.ColorRole.Text, "text"), (QPalette.ColorRole.Button, "raised"),
                            (QPalette.ColorRole.ButtonText, "text"), (QPalette.ColorRole.Highlight, "soft"),
                            (QPalette.ColorRole.HighlightedText, "text"), (QPalette.ColorRole.PlaceholderText, "muted"),
                            (QPalette.ColorRole.ToolTipBase, "surface"), (QPalette.ColorRole.ToolTipText, "text")):
            palette.setColor(role, QColor(colors[token]))
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(colors["muted"]))
        app.setPalette(palette)
        app.setStyleSheet(theme_style(key))
        font = QFont("Segoe UI" if sys.platform == "win32" else "DejaVu Sans")
        font.setPointSize(10)
        app.setFont(font)

    def motion_enabled() -> bool:
        app = QApplication.instance()
        return app is not None and not bool(app.property("reducedMotion"))

    class MotionButton(QPushButton):
        """Short, non-moving hover affordance; hit target and keyboard focus stay stable."""
        def __init__(self, text: str):
            super().__init__(text)
            self.hover_amount = 0.0
            self.hover_animation = QVariantAnimation(self)
            self.hover_animation.setDuration(140)
            self.hover_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.hover_animation.valueChanged.connect(self._hover_value)

        def _hover_value(self, value: Any) -> None:
            self.hover_amount = float(value)
            self.update()

        def animate_hover(self, target: float) -> None:
            target = float(target)
            self.hover_animation.stop()
            if not motion_enabled():
                self._hover_value(target)
                return
            self.hover_animation.setStartValue(self.hover_amount)
            self.hover_animation.setEndValue(target)
            self.hover_animation.start()

        def enterEvent(self, event: Any) -> None:
            super().enterEvent(event)
            if self.isEnabled():
                self.animate_hover(1.0)

        def leaveEvent(self, event: Any) -> None:
            super().leaveEvent(event)
            self.animate_hover(0.0)

        def paintEvent(self, event: Any) -> None:
            super().paintEvent(event)
            if self.hover_amount > 0 and self.isEnabled():
                painter = QPainter(self)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                color = self.palette().color(QPalette.ColorRole.HighlightedText)
                color.setAlpha(round(55 * self.hover_amount))
                painter.setPen(color)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 9, 9)
                painter.end()

    class FadeStack(QStackedWidget):
        """Current page changes immediately; only its appearance eases in, never its data."""
        def __init__(self):
            super().__init__()
            self.transition = QPropertyAnimation(self)
            self.transition.setPropertyName(b"opacity")
            self.transition.setDuration(180)
            self.transition.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.effect: QGraphicsOpacityEffect | None = None
            self.transition.finished.connect(self.finish_transition)

        def finish_transition(self) -> None:
            if self.effect:
                self.effect.setOpacity(1.0)

        def setCurrentIndex(self, index: int) -> None:
            if index == self.currentIndex() or not 0 <= index < self.count():
                return
            self.transition.stop()
            self.finish_transition()
            super().setCurrentIndex(index)
            if not motion_enabled() or not self.isVisible():
                return
            widget = self.currentWidget()
            effect = widget.graphicsEffect()
            if not isinstance(effect, QGraphicsOpacityEffect):
                effect = QGraphicsOpacityEffect(widget)
                widget.setGraphicsEffect(effect)
            self.effect = effect
            self.transition.setTargetObject(effect)
            self.transition.setStartValue(0.35)
            self.transition.setEndValue(1.0)
            self.transition.start()

        def setCurrentWidget(self, widget: QWidget) -> None:
            self.setCurrentIndex(self.indexOf(widget))

        def disable_motion(self) -> None:
            self.transition.stop()
            self.finish_transition()

    class HeroFrame(QWidget):
        """Procedural voxel accent: no downloaded artwork, assets or fake game screenshots."""
        def __init__(self, key: str):
            super().__init__()
            self.key = theme_key(key)
            self.setMinimumHeight(182)

        def paintEvent(self, event: Any) -> None:
            colors = THEMES[self.key]
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(0, 0, self.width(), self.height(), 12, 12)
            painter.setClipPath(path)
            gradient = QLinearGradient(0, 0, self.width(), 0)
            gradient.setColorAt(0, QColor(colors["hero"]))
            gradient.setColorAt(1, QColor(colors["surface"]))
            painter.fillPath(path, gradient)
            art_rect = QRect(self.width() // 3, 0, self.width() * 2 // 3 + 1, self.height())
            paint_landscape(painter, art_rect, self.key, 4)
            fade = QLinearGradient(0, 0, self.width(), 0)
            fade.setColorAt(0, QColor(colors["hero"]))
            fade.setColorAt(0.4, QColor(colors["hero"]))
            veil = QColor(colors["hero"])
            veil.setAlpha(30)
            fade.setColorAt(1, veil)
            painter.fillRect(self.rect(), fade)
            painter.end()

    class InstanceDelegate(QStyledItemDelegate):
        def __init__(self, main: MainWindow):
            super().__init__(main)
            self.main = main

        def sizeHint(self, option: Any, index: Any) -> QSize:
            return QSize(250, 66 if self.main.layout_mode == "compact" else 82)

        def paint(self, painter: QPainter, option: Any, index: Any) -> None:
            value = index.data(int(Qt.ItemDataRole.UserRole) + 1) or {}
            if not value:
                return super().paint(painter, option, index)
            colors = THEMES[self.main.theme]
            selected = bool(option.state & QStyle.StateFlag.State_Selected)
            hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = option.rect.adjusted(0, 3, -1, -3)
            painter.setPen(Qt.PenStyle.NoPen)
            if selected or hovered:
                painter.setBrush(QColor(colors["soft"] if selected else colors["raised"]))
                painter.drawRoundedRect(rect, 9, 9)
            if selected:
                painter.setBrush(QColor(colors["accent"]))
                painter.drawRoundedRect(rect.left(), rect.top() + 16, 3, rect.height() - 32, 1, 1)
            icon_rect = QRect(rect.left() + 13, rect.top() + 14, 43, 43)
            painter.setBrush(QColor(colors["raised"]))
            painter.drawRoundedRect(icon_rect, 10, 10)
            icon = index.data(Qt.ItemDataRole.DecorationRole)
            if icon:
                icon.paint(painter, icon_rect.adjusted(7, 7, -7, -7))
            x = rect.left() + 68
            available = max(20, rect.width() - 78)
            title_font = QFont(option.font)
            title_font.setPixelSize(13)
            title_font.setBold(True)
            painter.setFont(title_font)
            painter.setPen(QColor(colors["text"]))
            title = value.get("name", "")
            if value.get("update"):
                title = "↑ " + title
            elif value.get("running"):
                title = "▶ " + title
            elif value.get("favorite"):
                title = "★ " + title
            painter.drawText(QRect(x, rect.top() + 12, available, 20), Qt.AlignmentFlag.AlignVCenter,
                             QFontMetrics(title_font).elidedText(title, Qt.TextElideMode.ElideRight, available))
            small = QFont(option.font)
            small.setPixelSize(11)
            painter.setFont(small)
            painter.setPen(QColor(colors["muted"]))
            detail = value.get("detail", "")
            painter.drawText(QRect(x, rect.top() + 33, available, 18), Qt.AlignmentFlag.AlignVCenter,
                             QFontMetrics(small).elidedText(detail, Qt.TextElideMode.ElideRight, available))
            painter.setPen(QColor(colors["accent"] if value.get("linked") else colors["muted"]))
            state = "АВТОСИНХРОНИЗАЦИЯ" if value.get("linked") else "ЛОКАЛЬНАЯ СБОРКА"
            small.setPixelSize(9)
            painter.setFont(small)
            if self.main.layout_mode != "compact":
                painter.drawText(QRect(x, rect.top() + 52, available, 15), Qt.AlignmentFlag.AlignVCenter, state)
            painter.restore()


    class FileDelegate(QStyledItemDelegate):
        def __init__(self, main: MainWindow):
            super().__init__(main)
            self.main = main

        def sizeHint(self, option: Any, index: Any) -> QSize:
            return QSize(350, 54 if self.main.layout_mode == "compact" else 63)

        def paint(self, painter: QPainter, option: Any, index: Any) -> None:
            value = index.data(int(Qt.ItemDataRole.UserRole) + 1) or {}
            if not value:
                return super().paint(painter, option, index)
            colors = THEMES[self.main.theme]
            selected = bool(option.state & QStyle.StateFlag.State_Selected)
            hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = option.rect.adjusted(1, 1, -1, -1)
            painter.setPen(Qt.PenStyle.NoPen)
            if selected or hovered:
                painter.setBrush(QColor(colors["soft"] if selected else colors["raised"]))
                painter.drawRoundedRect(rect, 7, 7)
            icon_rect = QRect(rect.left() + 10, rect.top() + 10, 40, 40)
            painter.setBrush(QColor(colors["raised"]))
            painter.drawRoundedRect(icon_rect, 8, 8)
            small = QFont(option.font)
            small.setPixelSize(9)
            small.setBold(True)
            painter.setFont(small)
            painter.setPen(QColor(colors["accent"] if value.get("enabled", True) else colors["muted"]))
            painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, value.get("kind", "JAR"))
            font = QFont(option.font)
            font.setPixelSize(13)
            painter.setFont(font)
            painter.setPen(QColor(colors["text"] if value.get("enabled", True) else colors["muted"]))
            x, width = rect.left() + 63, max(30, rect.width() - 78)
            painter.drawText(QRect(x, rect.top() + 9, width, 23), Qt.AlignmentFlag.AlignVCenter,
                             QFontMetrics(font).elidedText(value.get("name", ""), Qt.TextElideMode.ElideRight, width))
            font.setPixelSize(11)
            painter.setFont(font)
            painter.setPen(QColor(colors["muted"]))
            description = value.get("description", "")
            painter.drawText(QRect(x, rect.top() + 33, width, 18), Qt.AlignmentFlag.AlignVCenter,
                             QFontMetrics(font).elidedText(description, Qt.TextElideMode.ElideRight, width))
            painter.restore()


    class ElidedLabel(QLabel):
        """Keep full accessible text, but don't let long names expand the window."""
        def sizeHint(self) -> QSize:
            return QSize(min(350, self.fontMetrics().horizontalAdvance(self.text()) + 6), self.fontMetrics().height() + 5)

        def minimumSizeHint(self) -> QSize:
            return QSize(12, self.fontMetrics().height() + 5)

        def paintEvent(self, event: Any) -> None:
            painter = QPainter(self)
            painter.setFont(self.font())
            painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
            painter.drawText(self.contentsRect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, self.contentsRect().width()))
            painter.end()

        def setText(self, text: str) -> None:
            super().setText(text)
            self.setToolTip(text)

    class StatCard(QFrame):
        activated = Signal()

        def __init__(self, title: str):
            super().__init__()
            self.setObjectName("statCard")
            layout = QVBoxLayout(self)
            layout.setContentsMargins(18, 12, 18, 12)
            layout.setSpacing(5)
            layout.addWidget(label(title, "muted"))
            self.value = label("—", "statValue")
            self.caption = label("", "muted", True)
            layout.addWidget(self.value)
            layout.addWidget(self.caption)

        def make_action(self, text: str, callback: Callable) -> None:
            self.setProperty("interactive", True)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setAccessibleName(text)
            self.setToolTip(text + " · Enter / пробел")
            self.activated.connect(callback)

        def mouseReleaseEvent(self, event: Any) -> None:
            super().mouseReleaseEvent(event)
            if self.property("interactive") and event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
                self.activated.emit()

        def keyPressEvent(self, event: Any) -> None:
            if self.property("interactive") and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                self.activated.emit()
                event.accept()
            else:
                super().keyPressEvent(event)

        def set_value(self, value: str, caption: str) -> None:
            self.value.setText(value)
            self.caption.setText(caption)

    def paint_landscape(painter: QPainter, rect: QRect, key: str, variant: int = 0) -> None:
        """Original, deterministic pixel landscape. No external image downloads."""
        colors = THEMES[key]
        painter.save()
        painter.setClipRect(rect, Qt.ClipOperation.IntersectClip)
        painter.setPen(Qt.PenStyle.NoPen)
        gradient = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
        gradient.setColorAt(0, QColor(colors["hero"]).lighter(135))
        gradient.setColorAt(1, QColor(colors["surface"]))
        painter.fillRect(rect, gradient)
        unit = max(3, rect.height() // 18)
        if key == "aurora":
            moon = QColor("#d6c7ff")
            moon.setAlpha(140)
            painter.setBrush(moon)
            painter.drawRect(rect.right() - 9 * unit, rect.top() + 3 * unit, 3 * unit, 3 * unit)
            painter.setBrush(QColor("#b9a0ff"))
            for i in range(18):
                x = rect.left() + (i * 79 + variant * 23) % max(1, rect.width())
                y = rect.top() + (i * 17 + 11) % max(1, rect.height() // 2)
                painter.drawRect(x, y, 2, 2)
        if key in ("ember", "paper"):
            sun = QColor(colors["accent"])
            sun.setAlpha(110)
            painter.setBrush(sun)
            painter.drawRect(rect.right() - 15 * unit, rect.top() + 3 * unit, 5 * unit, 5 * unit)
        for layer in range(3):
            color = QColor(colors["art"] if layer != 1 else colors["art_dark"])
            color.setAlpha(75 + 35 * layer)
            painter.setBrush(color)
            base = rect.top() + rect.height() * (4 + layer * 3) // 10
            points = [QPoint(rect.left(), rect.bottom() + 1)]
            last_y = base
            for index, x in enumerate(range(rect.left(), rect.right() + unit * 4, unit * 4)):
                y = base + ((index * 7 + variant * 3 + layer * 5) % 9 - 4) * unit
                y = min(rect.bottom(), max(rect.top() + 2 * unit, y))
                points.extend((QPoint(x, last_y), QPoint(x, y)))
                last_y = y
            points.append(QPoint(rect.right() + unit * 4, rect.bottom() + 1))
            painter.drawPolygon(QPolygon(points))
        if key in ("forest", "nord", "graphite", "aurora"):
            color = QColor(colors["art_dark"])
            color.setAlpha(200)
            painter.setBrush(color)
            for index in range(4):
                x = rect.left() + rect.width() * (4 + index) // 9
                y = rect.top() + rect.height() // 2 + (index % 2) * unit * 2
                painter.drawRect(x, y + unit * 3, unit, unit * 7)
                for level in range(3):
                    painter.drawRect(x - unit * (level + 1), y + level * 2 * unit,
                                     (level * 2 + 3) * unit, unit * 3)
        painter.restore()

    class GridDelegate(QStyledItemDelegate):
        def __init__(self, main: MainWindow):
            super().__init__(main)
            self.main = main

        def sizeHint(self, option: Any, index: Any) -> QSize:
            return QSize(254, 166)

        def paint(self, painter: QPainter, option: Any, index: Any) -> None:
            data = index.data(int(Qt.ItemDataRole.UserRole) + 1) or {}
            colors = THEMES[self.main.theme]
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = option.rect.adjusted(3, 3, -3, -3)
            path = QPainterPath()
            path.addRoundedRect(rect, 11, 11)
            painter.setClipPath(path)
            painter.fillPath(path, QColor(colors["surface"]))
            art = QRect(rect.left(), rect.top(), rect.width(), 64)
            paint_landscape(painter, art, self.main.theme, sum(ord(c) for c in data.get("name", "")) % 9)
            icon = index.data(Qt.ItemDataRole.DecorationRole)
            if icon:
                icon.paint(painter, QRect(rect.left() + 13, rect.top() + 14, 36, 36))
            if data.get("favorite"):
                painter.setPen(QColor(colors["accent"]))
                font = QFont(option.font)
                font.setPixelSize(17)
                painter.setFont(font)
                painter.drawText(QRect(rect.right() - 34, rect.top() + 10, 25, 26), Qt.AlignmentFlag.AlignCenter, "★")
            font = QFont(option.font)
            font.setPixelSize(14)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(colors["text"]))
            x, width = rect.left() + 14, rect.width() - 28
            painter.drawText(QRect(x, rect.top() + 74, width, 23), Qt.AlignmentFlag.AlignVCenter,
                             QFontMetrics(font).elidedText(data.get("name", ""), Qt.TextElideMode.ElideRight, width))
            font.setPixelSize(11)
            font.setBold(False)
            painter.setFont(font)
            painter.setPen(QColor(colors["muted"]))
            painter.drawText(QRect(x, rect.top() + 100, width, 18), Qt.AlignmentFlag.AlignVCenter, data.get("detail", ""))
            status = "↑ Есть обновление" if data.get("update") else "▶ В игре" if data.get("running") else (
                     "Автосинхронизация" if data.get("linked") else "Локальная сборка")
            painter.setPen(QColor(colors["accent"] if data.get("linked") or data.get("running") else colors["muted"]))
            painter.drawText(QRect(x, rect.top() + 127, width, 18), Qt.AlignmentFlag.AlignVCenter, status)
            painter.setClipping(False)
            painter.setPen(QColor(colors["accent"] if option.state & QStyle.StateFlag.State_MouseOver else colors["border"]))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 11, 11)
            painter.restore()

    class DiagnosticsDialog(QDialog):
        def __init__(self, main: MainWindow):
            super().__init__(main)
            self.main = main
            self.setWindowTitle("Диагностика MCSync")
            self.resize(760, 610)
            layout = QVBoxLayout(self)
            layout.addWidget(label("Проверка лаунчера", "title"))
            layout.addWidget(label("Без скачиваний, входа в аккаунт и изменений сборок. "
                                   "В отчёте нет токенов, ссылок синхронизации или локальных команд.", "muted", True))
            self.view = QPlainTextEdit()
            self.view.setReadOnly(True)
            layout.addWidget(self.view, 1)
            layout.addWidget(label("Пути и названия сборок могут содержать личные данные. "
                                   "Проверьте отчёт перед отправкой. Повреждённые файлы не удаляются.", "warning", True))
            layout.addLayout(row(button("Обновить", self.refresh), button("Скопировать", self.copy),
                                 button("Сохранить JSON", self.save), button("Готово", self.accept)))
            self.refresh()

        def refresh(self) -> None:
            self.report = diagnostic_report(self.main.store)
            self.view.setPlainText(json_bytes(self.report).decode("utf-8"))

        def copy(self) -> None:
            QApplication.clipboard().setText(self.view.toPlainText())

        def save(self) -> None:
            path, _ = QFileDialog.getSaveFileName(self, "Сохранить диагностику", "MCSync-diagnostics.json", "JSON (*.json)")
            if path:
                try:
                    atomic_json(Path(path), self.report)
                except OSError as exc:
                    message(self, "Не удалось сохранить отчёт", str(exc))


    def label(text: str = "", kind: str = "", wrap: bool = False) -> QLabel:
        result = QLabel(text)
        result.setTextFormat(Qt.TextFormat.PlainText)
        result.setWordWrap(wrap)
        if kind:
            result.setObjectName(kind)
        return result

    def button(text: str, callback: Callable, kind: str = "") -> QPushButton:
        result = MotionButton(text)
        result.setAccessibleName(text)
        if kind:
            result.setObjectName(kind)
        result.clicked.connect(callback)
        return result

    def row(*widgets: QWidget) -> QHBoxLayout:
        layout = QHBoxLayout()
        for widget in widgets:
            layout.addWidget(widget)
        return layout

    def message(parent: QWidget, title: str, text: str, *, question: bool = False) -> bool:
        box = QMessageBox(parent)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setWindowTitle(title)
        box.setText(redact(text))
        box.setIcon(QMessageBox.Icon.Question if question else QMessageBox.Icon.Warning)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                               if question else QMessageBox.StandardButton.Ok)
        if question:
            box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def cube_icon(color: str = "#65dfb7") -> QIcon:
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        base = QColor(color)
        painter.setBrush(base.lighter(125))
        painter.drawPolygon(QPolygon([QPoint(32, 5), QPoint(58, 19), QPoint(32, 33), QPoint(6, 19)]))
        painter.setBrush(base)
        painter.drawPolygon(QPolygon([QPoint(6, 19), QPoint(32, 33), QPoint(32, 59), QPoint(6, 45)]))
        painter.setBrush(base.darker(145))
        painter.drawPolygon(QPolygon([QPoint(32, 33), QPoint(58, 19), QPoint(58, 45), QPoint(32, 59)]))
        painter.end()
        return QIcon(pixmap)

    def open_path(path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    @dataclass
    class Confirmation:
        event: threading.Event = field(default_factory=threading.Event)
        accepted: bool = False
        backup: bool = True

    class Bridge(QObject):
        task_done = Signal(int, object, str)
        progress = Signal(int, str, object, object)
        confirm_sync = Signal(object, object, object)
        update_check_done = Signal(object)
        game_output = Signal(str, str)
        game_finished = Signal(str, int, float, str)

    class BackupBridge(QObject):
        progress = Signal(str, object, object)
        finished = Signal(str)

    class BackupProgressDialog(QDialog):
        """Local version changes do not block the GUI while compressing large worlds."""
        def __init__(self, inst: Instance, parent: QWidget):
            super().__init__(parent)
            self.setWindowTitle("Резервная копия миров")
            self.resize(520, 210)
            self.cancel = threading.Event()
            self.bridge = BackupBridge(self)
            self.bridge.progress.connect(self.on_progress)
            self.bridge.finished.connect(self.on_finished)
            layout = QVBoxLayout(self)
            layout.addWidget(label("Сначала сохраним миры", "sectionTitle"))
            self.info = label("Создание ZIP-копии…", "muted", True)
            self.bar = QProgressBar()
            self.bar.setRange(0, 0)
            layout.addWidget(self.info)
            layout.addWidget(self.bar)
            layout.addWidget(button("Отменить", self.reject))

            def work() -> None:
                try:
                    backup_worlds(inst, progress=self.bridge.progress.emit, cancel=self.cancel)
                    check_cancel(self.cancel)
                    self.bridge.finished.emit("")
                except Cancelled:
                    self.bridge.finished.emit("cancel")
                except Exception as exc:
                    self.bridge.finished.emit(redact(str(exc)))
            self.worker = threading.Thread(target=work, name="MCSync-world-backup", daemon=True)
            self.worker.start()

        @Slot(str, object, object)
        def on_progress(self, text: str, value: int, maximum: int) -> None:
            self.info.setText(text)
            self.bar.setRange(0, 1000 if maximum else 0)
            if maximum:
                self.bar.setValue(min(1000, int(value / maximum * 1000)))

        @Slot(str)
        def on_finished(self, error: str) -> None:
            if self.cancel.is_set() or error == "cancel":
                return
            if error:
                self.reject()
                message(self.parentWidget(), "Бэкап не создан", error + "\nВерсия сборки не изменена.")
            else:
                self.accept()

        def reject(self) -> None:
            self.cancel.set()
            super().reject()


    class SyncConfirmDialog(QDialog):
        def __init__(self, inst: Instance, plan: SyncPlan, parent: QWidget | None = None):
            super().__init__(parent)
            self.setWindowTitle("Подтвердить обновление сборки")
            self.resize(720, 570)
            self.plan = plan
            layout = QVBoxLayout(self)
            layout.addWidget(label(inst.name, "title"))
            m = plan.manifest
            lines = []
            if inst.minecraft != m["minecraft"]:
                lines.append(f"Minecraft: {inst.minecraft} → {m['minecraft']}")
            if inst.loader != m["loader"] or inst.loader_version != m["loader_version"]:
                before = f"{LOADERS[inst.loader]} {inst.loader_version or 'авто'}"
                after = f"{LOADERS[m['loader']]} {m['loader_version']}"
                lines.append(f"Загрузчик: {before} → {after}")
            if inst.server != m["server"]:
                lines.append(f"Сервер: {inst.server or 'не задан'} → {m['server'] or 'не задан'}")
            layout.addWidget(label("\n".join(lines) or "Версия игры и загрузчика не меняются.", wrap=True))
            if plan.downgrade:
                layout.addWidget(label("ВНИМАНИЕ: понижение версии Minecraft. Миры новой версии могут быть повреждены. "
                                       "Рекомендуется не открывать их в старой версии.", "warning", True))
            elif plan.version_changed:
                layout.addWidget(label("Совместимость модов и миров после смены версии не гарантируется.", "warning", True))
            layout.addWidget(label(f"Скачать/заменить: {len(plan.downloads)} • Удалить: {len(plan.deletions)} • "
                                   f"Загрузка: {human_size(plan.size)}", "muted"))
            diff = QPlainTextEdit()
            diff.setReadOnly(True)
            diff.setPlainText("\n".join([f"+ {f.action}: {f.path} ({human_size(f.size)})" for f in plan.downloads]
                                        + [f"− удалить: {path}" for path in plan.deletions]) or "Изменяются только параметры версии/сервера.")
            layout.addWidget(diff, 1)
            self.backup = QCheckBox("Создать ZIP-копию миров (saves) перед сменой версии")
            self.backup.setChecked(True)
            self.backup.setEnabled(plan.version_changed)
            layout.addWidget(self.backup)
            layout.addWidget(label("Сначала скачиваются и проверяются все файлы. При отмене сборка не меняется.", "muted", True))
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Обновить")
            buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)

    class NewInstanceDialog(QDialog):
        def __init__(self, versions: list[str], parent: QWidget):
            super().__init__(parent)
            self.setWindowTitle("Новая сборка")
            self.resize(440, 300)
            layout = QVBoxLayout(self)
            layout.addWidget(label("Новая сборка", "title"))
            form = QFormLayout()
            self.name = QLineEdit()
            self.name.setPlaceholderText("Например, Наш сервер")
            self.mc = QComboBox()
            self.mc.setEditable(True)
            self.mc.addItems(versions or ["1.21.1", "1.20.1"])
            self.loader = QComboBox()
            for key, title in LOADERS.items():
                self.loader.addItem(title, key)
            self.loader_version = QLineEdit()
            self.loader_version.setPlaceholderText("Пусто = последняя совместимая при установке")
            form.addRow("Название", self.name)
            form.addRow("Minecraft", self.mc)
            form.addRow("Загрузчик", self.loader)
            form.addRow("Версия загрузчика", self.loader_version)
            layout.addLayout(form)
            layout.addWidget(label("Список версий можно обновить в настройках сборки. Java установится автоматически.", "muted", True))
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            buttons.accepted.connect(self.validate_and_accept)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)

        def validate_and_accept(self) -> None:
            try:
                Instance(uuid.uuid4().hex, self.name.text().strip(), self.mc.currentText().strip(),
                         self.loader.currentData(), self.loader_version.text().strip()).validate()
            except (UserError, ValueError) as exc:
                message(self, "Проверьте поля", str(exc))
                return
            self.accept()

    class ConnectDialog(QDialog):
        def __init__(self, parent: QWidget):
            super().__init__(parent)
            self.setWindowTitle("Подключиться к сборке друга")
            self.resize(540, 330)
            layout = QVBoxLayout(self)
            layout.addWidget(label("Вступить в пати", "title"))
            layout.addWidget(label("Вставьте приглашение друга один раз. MCSync запомнит пати, восстановит связь "
                                   "после перезапуска и проверит моды перед игрой за вас.", "muted", True))
            self.url = QLineEdit()
            self.url.setPlaceholderText("http://адрес:25589/токен")
            self.name = QLineEdit()
            self.name.setPlaceholderText("Название (необязательно)")
            layout.addWidget(self.url)
            layout.addWidget(self.name)
            self.alias = QLineEdit(getattr(parent, "store", None).settings.get("party_name", "") if hasattr(parent, "store") else "")
            self.alias.setMaxLength(32)
            self.alias.setPlaceholderText("Ваше имя для друзей (необязательно)")
            layout.addWidget(self.alias)
            self.trust = QCheckBox("Я доверяю хосту: моды содержат исполняемый код")
            layout.addWidget(self.trust)
            layout.addWidget(label("HTTP не шифруется. Передавайте ссылку приватно и используйте "
                                   "локальную сеть или VPN (например, Tailscale/Radmin).", "warning", True))
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Подключиться")
            buttons.accepted.connect(self.validate_and_accept)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)

        def validate_and_accept(self) -> None:
            try:
                normalize_sync_url(self.url.text())
                party_name(self.alias.text())
                if not self.trust.isChecked():
                    raise UserError("Подключайтесь только к сборкам людей, которым доверяете.")
            except UserError as exc:
                message(self, "Проверьте ссылку", str(exc))
                return
            self.accept()

    class DropList(QListWidget):
        dropped = Signal(object)

        def __init__(self):
            super().__init__()
            self.setAcceptDrops(True)
            self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        def dragEnterEvent(self, event: Any) -> None:
            if event.mimeData().hasUrls() and all(url.isLocalFile() for url in event.mimeData().urls()):
                event.acceptProposedAction()

        def dragMoveEvent(self, event: Any) -> None:
            if event.mimeData().hasUrls():
                event.acceptProposedAction()

        def dropEvent(self, event: Any) -> None:
            paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
            if paths:
                self.dropped.emit(paths)
                event.acceptProposedAction()

    class FilePanel(QWidget):
        def __init__(self, folder: str, main: MainWindow):
            super().__init__()
            self.folder, self.main = folder, main
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 5, 0, 0)
            layout.setSpacing(10)
            heading = QHBoxLayout()
            title = {"mods": "Моды сборки", "resourcepacks": "Ресурспаки", "shaderpacks": "Шейдеры", "saves": "Миры"}[folder]
            heading.addWidget(label(title, "sectionTitle"))
            heading.addStretch()
            self.summary = label("", "muted")
            heading.addWidget(self.summary)
            layout.addLayout(heading)
            self.hint = label("Перетащите сюда файлы или нажмите «Добавить».", "muted", True)
            layout.addWidget(self.hint)
            self.filter_field = QLineEdit()
            self.filter_field.setPlaceholderText("Найти файл…")
            self.filter_field.setClearButtonEnabled(True)
            self.filter_field.setAccessibleName("Поиск файлов сборки")
            layout.addWidget(self.filter_field)
            self.list = DropList()
            self.list.setMouseTracking(True)
            self.list.setItemDelegate(FileDelegate(main))
            self.list.setAccessibleName("Файлы сборки")
            self.filter_field.textChanged.connect(self.apply_filter)
            self.list.itemSelectionChanged.connect(self.update_selection_buttons)
            self._editable = False
            self.list.dropped.connect(self.add_paths)
            self.list.itemDoubleClicked.connect(lambda _: self.open_world() if folder == "saves" else self.toggle())
            layout.addWidget(self.list, 1)
            self.add_btn = button("Добавить", self.pick_files)
            self.toggle_btn = button("Включить / выключить", self.toggle)
            self.delete_btn = button("Удалить", self.delete, "danger")
            self.backup_btn = button("Бэкап мира", self.backup)
            self.folder_btn = button("Открыть папку", self.open_folder)
            actions = row(self.add_btn, self.backup_btn if folder == "saves" else self.toggle_btn,
                          self.delete_btn, self.folder_btn)
            layout.addLayout(actions)
            if folder == "saves":
                self.toggle_btn.hide()
            else:
                self.backup_btn.hide()

        def refresh(self, inst: Instance | None, locked: bool = False) -> None:
            selection = set(self.selected())
            scroll = self.list.verticalScrollBar().value()
            self.list.blockSignals(True)
            self.list.clear()
            if inst:
                root = inst.game_dir / self.folder
                if self.folder == "saves":
                    if root.exists():
                        for path in sorted(root.iterdir()):
                            if path.is_dir() and not path.is_symlink():
                                item = QListWidgetItem(path.name)
                                item.setData(Qt.ItemDataRole.UserRole, path.name)
                                item.setData(int(Qt.ItemDataRole.UserRole) + 1,
                                             {"name": path.name, "kind": "МИР", "description": "Папка мира · двойной клик — открыть"})
                                self.list.addItem(item)
                else:
                    for relative, path in iter_files(root):
                        enabled = not relative.endswith(".disabled")
                        item = QListWidgetItem(f"{'●' if enabled else '○'}  {relative}   ·   {human_size(path.stat().st_size)}")
                        item.setData(Qt.ItemDataRole.UserRole, relative)
                        item.setData(int(Qt.ItemDataRole.UserRole) + 1,
                                     {"name": relative.removesuffix(".disabled"), "enabled": enabled,
                                      "kind": "JAR" if self.folder == "mods" else "ZIP",
                                      "description": f"{'Включён' if enabled else 'Отключён'} · {human_size(path.stat().st_size)}"})
                        item.setToolTip(relative)
                        self.list.addItem(item)
            for i in range(self.list.count()):
                item = self.list.item(i)
                item.setSelected(item.data(Qt.ItemDataRole.UserRole) in selection)
            self.list.blockSignals(False)
            self.list.verticalScrollBar().setValue(scroll)
            self.summary.setText(f"Файлов: {self.list.count()}")
            managed = bool(inst and inst.sync_url and self.folder != "saves")
            self.hint.setText("Этими файлами управляет хост. Изменения модов вносите у него." if managed else
                              "Перетащите папку/ZIP мира сюда." if self.folder == "saves" else
                              "Перетащите сюда .jar / .zip. Выключенные файлы имеют суффикс .disabled.")
            for widget in (self.add_btn, self.toggle_btn, self.delete_btn):
                widget.setEnabled(bool(inst) and not locked and not managed)
            self.backup_btn.setEnabled(bool(inst) and not locked)
            self.folder_btn.setEnabled(bool(inst))
            self.list.setAcceptDrops(bool(inst) and not locked and not managed)
            self._editable = bool(inst) and not locked and not managed
            self.apply_filter()

        def apply_filter(self, *args: Any) -> None:
            query = self.filter_field.text().casefold()
            shown = 0
            for i in range(self.list.count()):
                item = self.list.item(i)
                visible = query in str(item.data(Qt.ItemDataRole.UserRole)).casefold()
                item.setHidden(not visible)
                if not visible:
                    item.setSelected(False)
                shown += int(visible)
            self.summary.setText(f"Файлов: {shown} / {self.list.count()}" if query else f"Файлов: {self.list.count()}")
            self.update_selection_buttons()

        def update_selection_buttons(self) -> None:
            selected = bool(self.list.selectedItems())
            self.toggle_btn.setEnabled(self._editable and selected)
            self.delete_btn.setEnabled(self._editable and selected)

        def selected(self) -> list[str]:
            return [item.data(Qt.ItemDataRole.UserRole) for item in self.list.selectedItems()]

        def pick_files(self) -> None:
            if self.folder == "saves":
                if message(self, "Импорт мира", "Выбрать папку мира?\n«Нет» — выбрать ZIP-архив.", question=True):
                    path = QFileDialog.getExistingDirectory(self, "Папка мира")
                    paths = [path] if path else []
                else:
                    paths, _ = QFileDialog.getOpenFileNames(self, "ZIP мира", filter="ZIP (*.zip)")
            else:
                paths, _ = QFileDialog.getOpenFileNames(self, "Добавить файлы", filter="Minecraft (*.jar *.zip *.disabled);;Все файлы (*)")
            if paths:
                self.add_paths([Path(path) for path in paths])

        def add_paths(self, paths: list[Path]) -> None:
            inst = self.main.current_instance()
            if not inst or self.main.is_locked(inst.id) or (inst.sync_url and self.folder != "saves"):
                return
            for source in paths:
                if self.folder != "saves":
                    try:
                        target = safe_join(inst.game_dir / self.folder, source.name)
                        if target.exists() and not message(self, "Заменить файл?", source.name, question=True):
                            return
                    except UserError as exc:
                        message(self, "Не удалось добавить файл", str(exc))
                        return

            def work(progress: Progress, cancel: threading.Event) -> None:
                for i, source in enumerate(paths):
                    check_cancel(cancel)
                    progress(f"Импорт {source.name}", i, len(paths))
                    if self.folder == "saves":
                        import_world(inst, source)
                    else:
                        if source.is_symlink() or not source.is_file():
                            raise UserError("Добавляйте только обычные файлы, без символических ссылок.")
                        if self.folder == "mods" and not source.name.endswith((".jar", ".jar.disabled")):
                            raise UserError("В mods можно добавлять только .jar или .jar.disabled.")
                        if self.folder != "mods" and not source.name.endswith((".zip", ".zip.disabled")):
                            raise UserError("Ресурспаки/шейдеры должны быть ZIP-архивами.")
                        target = safe_join(inst.game_dir / self.folder, source.name)
                        if source.resolve() == target.resolve():
                            continue
                        target.parent.mkdir(parents=True, exist_ok=True)
                        part = target.with_name(target.name + ".part")
                        try:
                            shutil.copy2(source, part)
                            os.replace(part, target)
                        finally:
                            part.unlink(missing_ok=True)
            self.main.run_task("Добавление файлов", work, lambda _: self.main.load_detail(), inst.id)

        def toggle(self) -> None:
            inst, selected = self.main.current_instance(), self.selected()
            if not inst or inst.sync_url or self.main.is_locked(inst.id) or not selected:
                return
            self.main.run_task("Переключение файлов",
                               lambda p, c: toggle_files(inst, self.folder, selected, progress=p, cancel=c),
                               lambda _: self.main.load_detail(reload_fields=False), inst.id)

        def delete(self) -> None:
            inst, selected = self.main.current_instance(), self.selected()
            if not inst or not selected or self.main.is_locked(inst.id) or (inst.sync_url and self.folder != "saves"):
                return
            if not message(self, "Удалить файлы?", "\n".join(selected) +
                           ("\nПеред удалением миров будет сделан бэкап." if self.folder == "saves" else ""), question=True):
                return

            def work(progress: Progress, cancel: threading.Event) -> None:
                for relative in selected:
                    check_cancel(cancel)
                    path = safe_join(inst.game_dir / self.folder, relative)
                    if self.folder == "saves":
                        backup_worlds(inst, relative, progress=progress, cancel=cancel)
                        shutil.rmtree(path)
                    else:
                        path.unlink()
            self.main.run_task("Удаление", work, lambda _: self.main.load_detail(), inst.id)

        def backup(self) -> None:
            inst, selected = self.main.current_instance(), self.selected()
            if not inst or self.main.is_locked(inst.id):
                return

            def work(progress: Progress, cancel: threading.Event) -> list[Path]:
                result = []
                for world in selected or [None]:
                    check_cancel(cancel)
                    progress("Резервная копия миров…", 0, 0)
                    path = backup_worlds(inst, world, progress=progress, cancel=cancel)
                    if path:
                        result.append(path)
                return result
            self.main.run_task("Резервная копия", work,
                               lambda paths: self.main.statusBar().showMessage("Создано архивов: " + str(len(paths)), 12000), inst.id)

        def open_folder(self) -> None:
            inst = self.main.current_instance()
            if inst:
                path = inst.game_dir / self.folder
                path.mkdir(parents=True, exist_ok=True)
                open_path(path)

        def open_world(self) -> None:
            inst, selected = self.main.current_instance(), self.selected()
            if inst and selected:
                open_path(safe_join(inst.game_dir / "saves", selected[0]))

    class PartyDelegate(QStyledItemDelegate):
        def __init__(self, main: MainWindow):
            super().__init__(main)
            self.main = main

        def sizeHint(self, option: Any, index: Any) -> QSize:
            return QSize(250, 48)

        def paint(self, painter: QPainter, option: Any, index: Any) -> None:
            data = index.data(int(Qt.ItemDataRole.UserRole) + 1) or {}
            colors = THEMES[self.main.theme]
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = option.rect.adjusted(2, 2, -2, -2)
            avatar = QRect(rect.left() + 3, rect.top() + 5, 32, 32)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors["soft"]))
            painter.drawRoundedRect(avatar, 10, 10)
            painter.setPen(QColor(colors["accent"]))
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
            name = data.get("name", "?")
            painter.drawText(avatar, Qt.AlignmentFlag.AlignCenter, name[:2].upper())
            content = QRect(avatar.right() + 12, rect.top() + 3, max(0, rect.width() - 58), 21)
            painter.setPen(QColor(colors["text"]))
            title = name + (" · Вы" if data.get("self") else "") + (" · хост" if data.get("role") == "host" else "")
            painter.drawText(content, Qt.AlignmentFlag.AlignVCenter,
                             painter.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, content.width()))
            font.setBold(False)
            font.setPixelSize(11)
            painter.setFont(font)
            healthy = "#23764c" if self.main.theme == "paper" else "#7ee7b5"
            painter.setPen(QColor(healthy if data.get("ready") else colors["warning"]))
            content.translate(0, 20)
            painter.drawText(content, Qt.AlignmentFlag.AlignVCenter,
                             painter.fontMetrics().elidedText(data.get("caption", ""), Qt.TextElideMode.ElideRight, content.width()))
            painter.restore()

    class PartyPanel(QFrame):
        """A real roster, not a decorative online counter. All untrusted text is plain."""
        def __init__(self, main: MainWindow):
            super().__init__()
            self.main = main
            self.setFixedWidth(246)
            self.setObjectName("partyCard")
            layout = QVBoxLayout(self)
            layout.setContentsMargins(18, 16, 18, 16)
            layout.setSpacing(8)
            heading = QHBoxLayout()
            self.title = ElidedLabel("Пати с друзьями")
            self.title.setObjectName("sectionTitle")
            heading.addWidget(self.title, 1)
            self.badge = label("Постоянная ссылка", "badge")
            layout.addLayout(heading)
            layout.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignLeft)
            self.rename = button("Моё имя", lambda: SettingsDialog(main).exec(), "ghost")
            self.action = button("Пригласить друзей", main.summary_sync_action)
            self.action.setAccessibleName("Приглашение или обновление пати")
            self.connection = label("", "muted", True)
            self.connection.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(self.connection)
            self.roster = QListWidget()
            self.roster.setObjectName("partyRoster")
            self.roster.setItemDelegate(PartyDelegate(main))
            self.roster.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            self.roster.setViewMode(QListWidget.ViewMode.ListMode)
            self.roster.setResizeMode(QListWidget.ResizeMode.Adjust)
            self.roster.setMovement(QListWidget.Movement.Static)
            self.roster.setWrapping(False)
            self.roster.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.roster.setSpacing(2)
            self.roster.setAccessibleName("Участники пати и их реальные статусы")
            self.roster.setMinimumHeight(0)
            self.roster.setMaximumHeight(260)
            layout.addWidget(self.roster)
            self.explanation = label("", "muted", True)
            self.explanation.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(self.explanation)
            layout.addStretch(1)
            layout.addWidget(self.action)
            layout.addWidget(self.rename, 0, Qt.AlignmentFlag.AlignLeft)
            self.repair = button("Помощь со связью", self.help_connection, "ghost")
            self.repair.hide()
            layout.addWidget(self.repair)
            self._roster_key: Any = None

        def help_connection(self) -> None:
            inst = self.main.current_instance()
            state = self.main.party_states.get(inst.id, {}) if inst else {}
            if state.get("error_kind") == "invitation":
                self.main.change_invitation()
            else:
                ConnectionHelpDialog(self.main).exec()

        def resizeEvent(self, event: Any) -> None:
            super().resizeEvent(event)
            if hasattr(self, "roster"):
                self.resize_roster()

        def resize_roster(self) -> None:
            height = min(260, 52 * self.roster.count() + 4)
            if self.roster.height() != height:
                self.roster.setFixedHeight(height)

        def refresh(self, inst: Instance | None) -> None:
            if inst is None:
                return
            state = self.main.party_states.get(inst.id, {})
            host = self.main.hosts.get(inst.id)
            room = host.party_snapshot() if host else state.get("room") if state.get("online") else None
            is_host = bool(host)
            online = is_host or state.get("online") is True
            connected = bool(inst.sync_url)
            self.title.setText("Вы — хост пати" if is_host else "Ваша пати" if connected else "Пати с друзьями")
            self.badge.setText(f"● {len(room['members'])} в сети" if room else "● Хост в сети" if online else
                               "Переподключение…" if state.get("online") is False else
                               "Подключаемся…" if connected else "Постоянная ссылка")
            self.badge.setProperty("status", "linked" if online else "pending" if connected else "local")
            self.badge.setProperty("connected", online)
            self.badge.style().unpolish(self.badge)
            self.badge.style().polish(self.badge)
            if is_host:
                self.connection.setText("Пати открыта. Приглашение сохранится после перезапуска лаунчера.")
            elif connected:
                self.connection.setText(party_connection_text(state))
            else:
                error = self.main.host_errors.get(inst.id)
                self.connection.setText("Не удалось восстановить пати: " + error if error else
                                        "Создайте пати один раз. Друзья будут видеть друг друга и получать вашу сборку.")
            self.roster.setVisible(bool(room))
            key = json.dumps(room, sort_keys=True) if room else ""
            own_id = "host" if is_host else state.get("self_id")
            if (key, own_id) != self._roster_key:
                self._roster_key = (key, own_id)
                self.roster.clear()
                if room:
                    for peer in room["members"]:
                        ready = peer["rev"] == room["rev"]
                        caption = "В игре" if peer["state"] == "playing" else "Обновляется" if peer["state"] == "updating" else "В лаунчере"
                        caption += " · актуально" if ready else " · нужно обновление"
                        data = dict(peer, self=peer["id"] == own_id, ready=ready, caption=caption)
                        item = QListWidgetItem(peer["name"] + " — " + caption)
                        item.setData(int(Qt.ItemDataRole.UserRole) + 1, data)
                        self.roster.addItem(item)
                self.resize_roster()
            if connected and online and state.get("supported") is False:
                explanation = "Хост использует старый MCSync. Связь проверяется автоматически; для списка друзей обновите его до 0.3.0+."
            elif connected and not online and state.get("online") is False:
                explanation = "Проверьте, что у хоста открыт MCSync и вы в одной LAN/VPN-сети. Проверки продолжатся и во время игры."
            elif connected:
                explanation = "Просто нажмите «Играть»: моды обновятся сами. Смена версии — " + (
                    "с подтверждением и бэкапом миров." if inst.sync_mode != "auto" else "автоматически, с бэкапом миров.")
            else:
                explanation = "Отправьте приглашение приватно. Для разных сетей нужен VPN или доступ к порту; это не облачный сервис."
            self.explanation.setText(explanation)
            self.action.setText("Обновить сейчас" if connected and inst.id in self.main.update_badges else
                                "Параметры пати" if connected else "Пригласить ещё" if is_host else "Создать пати")
            self.action.setEnabled(not self.main.busy and not self.main.is_locked(inst.id))
            self.repair.setVisible(bool(connected and state.get("online") is False))
            self.repair.setEnabled(not self.main.busy and not self.main.is_locked(inst.id))
            self.repair.setText("Новое приглашение" if state.get("error_kind") == "invitation" else "Помощь со связью")

    class ConnectionHelpDialog(QDialog):
        def __init__(self, main: MainWindow):
            super().__init__(main)
            self.setWindowTitle("Помощь с подключением к пати")
            self.resize(520, 390)
            layout = QVBoxLayout(self)
            layout.addWidget(label("Пати сохранена", "title"))
            layout.addWidget(label("MCSync уже переподключается сам. Повторно нажимать «Проверить» не нужно.", "muted", True))
            for title, text in (("1. Хост", "У друга должен быть открыт MCSync и включена пати."),
                                ("2. Общая сеть", "Вы должны видеть LAN/VPN-адрес хоста. Порт пати — не порт Minecraft-сервера."),
                                ("3. Приглашение", "Если адрес или секрет поменялся, замените приглашение — файлы и миры сохранятся.")):
                layout.addWidget(label(title, "sectionTitle"))
                layout.addWidget(label(text, "muted", True))
            layout.addWidget(button("Заменить приглашение…", lambda: (self.accept(), main.change_invitation())))
            layout.addWidget(button("Открыть диагностику", lambda: DiagnosticsDialog(main).exec(), "ghost"))
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)

    class HostDialog(QDialog):
        def __init__(self, main: MainWindow, inst: Instance):
            super().__init__(main)
            self.main, self.inst = main, inst
            self.setWindowTitle("Приглашение в пати")
            self.resize(570, 570)
            self.settings_error = ""
            try:
                settings = validate_host_preferences(read_json(inst.directory / "host_settings.json", {}))
            except (UserError, OSError) as exc:
                self.settings_error = redact(str(exc))
                settings = {}
            layout = QVBoxLayout(self)
            layout.addWidget(label("Создать пати для друзей", "title"))
            if self.settings_error:
                layout.addWidget(label("Настройки пати повреждены. При создании новой пати оригинал будет сохранён "
                                       "в recovery; друзьям понадобится новое приглашение.", "notice", True))
            layout.addWidget(label("Сервер работает, пока открыт лаунчер. Ссылка секретная: любой её получатель "
                                   "может скачать выбранные файлы. Миры и аккаунты не раздаются.", "muted", True))
            form = QFormLayout()
            self.address = QLineEdit(settings.get("address", self.local_ip()))
            self.port = QSpinBox()
            self.port.setRange(1024, 65535)
            self.port.setValue(settings.get("port", 25589))
            form.addRow("IP/DNS для друзей", self.address)
            form.addRow("HTTP-порт", self.port)
            layout.addLayout(form)
            self.advanced_toggle = button("Папки и правила раздачи  ▾", self.toggle_advanced, "ghost")
            layout.addWidget(self.advanced_toggle)
            self.advanced = QWidget()
            advanced_layout = QVBoxLayout(self.advanced)
            advanced_layout.setContentsMargins(0, 0, 0, 0)
            self.folders = {}
            folder_row = QHBoxLayout()
            for folder in SYNC_FOLDERS:
                box = QCheckBox(folder)
                box.setChecked(folder in settings.get("folders", SYNC_FOLDERS))
                self.folders[folder] = box
                folder_row.addWidget(box)
            advanced_layout.addLayout(folder_row)
            self.autostart = QCheckBox("Восстанавливать пати при следующем открытии MCSync")
            self.autostart.setChecked(settings.get("auto_start", True) is True)
            layout.addWidget(self.autostart)
            self.strict = QCheckBox("Строгий режим: удалять у друзей лишние .jar и .jar.disabled")
            self.strict.setChecked(settings.get("strict", True))
            advanced_layout.addWidget(self.strict)
            advanced_layout.addWidget(label("Исключения (маски fnmatch, одна на строку)"))
            self.excludes = QPlainTextEdit("\n".join(settings.get("excludes", ["*.part", "*.tmp"])))
            self.excludes.setMaximumHeight(95)
            advanced_layout.addWidget(self.excludes)
            layout.addWidget(self.advanced)
            self.advanced.hide()
            layout.addWidget(label("HTTP не шифрует данные. Проверьте config на пароли/токены. "
                                   "Для интернета нужен VPN или настройка доступа к этому порту; NAT автоматически не обходится.", "warning", True))
            self.url_field = QLineEdit()
            self.url_field.setReadOnly(True)
            self.url_field.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_invitation = QCheckBox("Показать секретное приглашение")
            self.show_invitation.toggled.connect(lambda shown: self.url_field.setEchoMode(
                QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password))
            self.url_field.setPlaceholderText("После запуска здесь появится ссылка")
            layout.addWidget(self.url_field)
            layout.addWidget(self.show_invitation)
            self.start_btn = button("Создать пати", self.start_host, "play")
            self.stop_btn = button("Остановить", self.stop_host, "danger")
            self.copy_btn = button("Скопировать приглашение", self.copy_url)
            layout.addLayout(row(self.start_btn, self.stop_btn, self.copy_btn))
            self.state_label = label("", "muted", True)
            layout.addWidget(self.state_label)
            self.refresh()

        def toggle_advanced(self) -> None:
            show = not self.advanced.isVisible()
            self.advanced.setVisible(show)
            self.advanced_toggle.setText("Папки и правила раздачи  ▴" if show else "Папки и правила раздачи  ▾")

        @staticmethod
        def local_ip() -> str:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.connect(("8.8.8.8", 80))
                    return sock.getsockname()[0]
            except OSError:
                return "127.0.0.1"

        def refresh(self) -> None:
            host = self.main.hosts.get(self.inst.id)
            active = host is not None
            self.start_btn.setEnabled(not active and not self.main.busy)
            self.stop_btn.setEnabled(active)
            self.copy_btn.setEnabled(active)
            for widget in (self.address, self.port, self.autostart, self.strict, self.excludes, *self.folders.values()):
                widget.setEnabled(not active)
            if host:
                self.url_field.setText(host.url(self.address.text()))
            else:
                self.url_field.clear()
            self.state_label.setText("Пати открыта. Отправьте приглашение один раз; друзья переподключатся сами." if active else
                                     "Нажмите «Создать пати», затем скопируйте приглашение. Для друзей нужен ваш LAN/VPN-адрес.")

        def start_host(self) -> None:
            settings = {"address": self.address.text().strip(), "port": self.port.value(),
                        "auto_start": self.autostart.isChecked(), "strict": self.strict.isChecked(),
                        "folders": [p for p, box in self.folders.items() if box.isChecked()],
                        "excludes": [s.strip() for s in self.excludes.toPlainText().splitlines() if s.strip()]}
            try:
                previous = validate_host_preferences(read_json(self.inst.directory / "host_settings.json", {}))
            except (UserError, OSError):
                try:
                    backup_private_file(self.inst.directory / "host_settings.json")
                except (UserError, OSError) as exc:
                    message(self, "Не удалось сохранить повреждённые настройки", redact(str(exc)))
                    return
                previous = {}
            settings["token"] = previous.get("token") or secrets.token_urlsafe(24)

            def work(progress: Progress, cancel: threading.Event) -> SyncHost:
                inst = self.main.store.load(self.inst.id)
                if inst.sync_url:
                    raise UserError("Для раздачи нужна собственная сборка, а не подписка на другого хоста.")
                if inst.loader != "vanilla" and not inst.loader_version:
                    progress("Определение версии загрузчика…", 0, 0)
                    concrete = resolve_loader_version(inst)
                    self.main.store.update(inst.id, loader_version=concrete)
                host = SyncHost(self.main.store, inst.id, port=settings["port"], token=settings["token"],
                                folders=tuple(settings["folders"]), excludes=tuple(settings["excludes"]),
                                strict=settings["strict"])
                host.url(settings["address"])  # validate before opening a listening socket
                check_cancel(cancel)
                host.start()
                try:
                    check_cancel(cancel)
                    atomic_json(inst.directory / "host_settings.json", settings)
                except BaseException:
                    host.stop()
                    raise
                return host

            def done(host: SyncHost) -> None:
                self.main.host_errors.pop(self.inst.id, None)
                self.main.hosts[self.inst.id] = host
                self.refresh()
                self.main.load_detail()
            self.main.run_task("Запуск раздачи", work, done, self.inst.id)

        def stop_host(self) -> None:
            try:
                settings = read_json(self.inst.directory / "host_settings.json", {})
                settings["auto_start"] = False
                atomic_json(self.inst.directory / "host_settings.json", settings)
            except (UserError, OSError, TypeError) as exc:
                message(self, "Не удалось сохранить остановку", redact(str(exc)))
                return
            host = self.main.hosts.pop(self.inst.id, None)
            if host:
                host.stop()
            self.refresh()
            self.main.load_detail()

        def copy_url(self) -> None:
            QApplication.clipboard().setText(self.url_field.text())
            self.state_label.setText("Ссылка скопирована. Отправьте её только друзьям, которым доверяете.")

    class LoginBridge(QObject):
        device_ready = Signal(object)
        finished = Signal(object, str)

    class MicrosoftLoginDialog(QDialog):
        def __init__(self, client_id: str, parent: QWidget):
            super().__init__(parent)
            self.client_id = client_id
            self.cancel = threading.Event()
            self.account = None
            self.url = ""
            self.setWindowTitle("Вход Microsoft")
            self.resize(530, 320)
            layout = QVBoxLayout(self)
            layout.addWidget(label("Вход без пароля в лаунчере", "title"))
            self.info = label("Запрос кода Microsoft…", "muted", True)
            self.code = QLineEdit()
            self.code.setReadOnly(True)
            self.code.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.code.setStyleSheet("font-size: 24px; font-weight: 600;")
            layout.addWidget(self.info)
            layout.addWidget(self.code)
            self.browser = button("Открыть Microsoft", self.open_browser)
            self.browser.setEnabled(False)
            layout.addLayout(row(self.browser, button("Скопировать код", lambda: QApplication.clipboard().setText(self.code.text()))))
            layout.addWidget(label("Вводите пароль только на официальном сайте Microsoft. "
                                   "Лаунчер не запрашивает пароль или Client Secret.", "muted", True))
            layout.addWidget(button("Отмена", self.reject))
            self.bridge = LoginBridge(self)
            self.bridge.device_ready.connect(self.on_device)
            self.bridge.finished.connect(self.on_finished)
            self.thread = threading.Thread(target=self.work, name="MicrosoftLogin", daemon=True)
            self.thread.start()

        def work(self) -> None:
            try:
                with MicrosoftAuth(self.client_id) as auth:
                    device = auth.start_device()
                    self.bridge.device_ready.emit(device)
                    account = auth.poll_device(device, self.cancel)
                self.bridge.finished.emit(account, "")
            except Exception as exc:
                self.bridge.finished.emit(None, str(exc))

        @Slot(object)
        def on_device(self, device: dict[str, Any]) -> None:
            if self.cancel.is_set():
                return
            self.url = device.get("verification_uri", "https://microsoft.com/devicelogin")
            self.code.setText(device["user_code"])
            self.info.setText(f"Откройте {self.url}, введите код и дождитесь завершения входа.")
            self.browser.setEnabled(True)

        def open_browser(self) -> None:
            parsed = urlsplit(self.url)
            if parsed.scheme == "https" and (parsed.hostname == "microsoft.com" or
                                               (parsed.hostname or "").endswith(".microsoft.com") or
                                               parsed.hostname == "login.microsoftonline.com"):
                QDesktopServices.openUrl(QUrl(self.url))

        @Slot(object, str)
        def on_finished(self, account: dict[str, Any] | None, error: str) -> None:
            if self.cancel.is_set():
                return
            if error:
                self.info.setText(redact(error))
                self.code.clear()
                return
            self.account = account
            self.accept()

        def reject(self) -> None:
            self.cancel.set()
            super().reject()

        def closeEvent(self, event: Any) -> None:
            self.cancel.set()
            super().closeEvent(event)

    class SkinPreview(QLabel):
        def __init__(self):
            super().__init__()
            self.image = QImage()
            self.slim = False
            self.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setMinimumSize(160, 290)
            self.setText("Скин\n64×64 / 64×32 PNG")
            self.setObjectName("muted")

        def load_png(self, data: bytes) -> None:
            if (len(data) > 512 * 1024 or data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24
                    or int.from_bytes(data[16:20], "big") != 64
                    or int.from_bytes(data[20:24], "big") not in (32, 64)):
                raise UserError("Скин должен быть PNG 64×64 или 64×32, не больше 512 КБ.")
            image = QImage.fromData(data, "PNG")
            if image.isNull():
                raise UserError("Не удалось прочитать PNG скина.")
            self.image = image
            self.render_skin()

        def render_skin(self) -> None:
            if self.image.isNull():
                return
            canvas = QImage(20, 34, QImage.Format.Format_ARGB32)
            canvas.fill(QApplication.palette().color(QPalette.ColorRole.Base))
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

            def piece(x: int, y: int, w: int, h: int, dx: int, dy: int, mirror: bool = False) -> None:
                image = self.image.copy(x, y, w, h)
                if mirror:
                    image = image.flipped(Qt.Orientation.Horizontal)
                painter.drawImage(QRect(dx + 2, dy + 1, w, h), image)

            modern, arm = self.image.height() == 64, 3 if self.slim else 4
            piece(8, 8, 8, 8, 4, 0)
            piece(20, 20, 8, 12, 4, 8)
            piece(44, 20, arm, 12, 4 - arm, 8)
            piece(36, 52, arm, 12, 12, 8) if modern else piece(44, 20, arm, 12, 12, 8, True)
            piece(4, 20, 4, 12, 4, 20)
            piece(20, 52, 4, 12, 8, 20) if modern else piece(4, 20, 4, 12, 8, 20, True)
            piece(40, 8, 8, 8, 4, 0)  # hat overlay also exists in legacy skins
            if modern:
                piece(20, 36, 8, 12, 4, 8)
                piece(44, 36, arm, 12, 4 - arm, 8)
                piece(52, 52, arm, 12, 12, 8)
                piece(4, 36, 4, 12, 4, 20)
                piece(4, 52, 4, 12, 8, 20)
            painter.end()
            self.setPixmap(QPixmap.fromImage(canvas.scaled(160, 272, Qt.AspectRatioMode.KeepAspectRatio,
                                                         Qt.TransformationMode.FastTransformation)))

    class AccountsDialog(QDialog):
        def __init__(self, main: MainWindow):
            super().__init__(main)
            self.main = main
            self.setWindowTitle("Аккаунты и скины")
            self.resize(760, 480)
            layout = QVBoxLayout(self)
            layout.addWidget(label("Аккаунты", "title"))
            columns = QHBoxLayout()
            left = QVBoxLayout()
            self.list = QListWidget()
            self.list.currentItemChanged.connect(self.selected_changed)
            left.addWidget(self.list)
            left.addLayout(row(button("Офлайн", self.add_offline), button("Microsoft", self.add_microsoft)))
            left.addLayout(row(button("Выбрать", self.select), button("Удалить", self.remove, "danger")))
            columns.addLayout(left, 1)
            right = QVBoxLayout()
            self.skin = SkinPreview()
            right.addWidget(self.skin)
            self.slim = QCheckBox("Модель Slim (Alex)")
            self.slim.toggled.connect(self.set_slim)
            right.addWidget(self.slim)
            right.addLayout(row(button("Открыть PNG", self.open_png), button("Скин Microsoft", self.fetch_skin)))
            columns.addLayout(right)
            layout.addLayout(columns, 1)
            layout.addWidget(label("Офлайн-аккаунт не проходит авторизацию на online-mode серверах. "
                                   "Локальный PNG — только предпросмотр, скин в игре не подменяется. "
                                   "Microsoft-токены хранятся локально в accounts.json без шифрования.", "warning", True))
            layout.addWidget(button("Готово", self.accept))
            self.refresh()

        def current(self) -> dict[str, Any] | None:
            item = self.list.currentItem()
            return item.data(Qt.ItemDataRole.UserRole) if item else None

        def refresh(self) -> None:
            self.list.clear()
            for account in self.main.accounts.data["accounts"]:
                selected = account["id"] == self.main.accounts.data["selected"]
                item = QListWidgetItem(f"{'● ' if selected else ''}{account['name']}\n"
                                       f"{'Microsoft • Java Edition' if account['type'] == 'microsoft' else 'Офлайн'}")
                item.setData(Qt.ItemDataRole.UserRole, account)
                self.list.addItem(item)
                if selected:
                    self.list.setCurrentItem(item)
            self.main.refresh_accounts()

        def selected_changed(self, *args: Any) -> None:
            account = self.current()
            if not account:
                return
            path = self.main.store.root / "skins" / (account["id"] + ".png")
            skins = account.get("skins", [])
            self.slim.setChecked(any(s.get("variant") == "SLIM" and s.get("state") == "ACTIVE" for s in skins))
            self.skin.clear()
            self.skin.image = QImage()
            self.skin.setText("Откройте PNG\nили загрузите скин Microsoft")
            if path.exists():
                try:
                    self.skin.load_png(path.read_bytes())
                except UserError:
                    pass

        def set_slim(self, value: bool) -> None:
            self.skin.slim = value
            self.skin.render_skin()

        def add_offline(self) -> None:
            name, ok = QInputDialog.getText(self, "Офлайн-аккаунт", "Ник (3–16 латинских букв, цифр или _)")
            if ok:
                try:
                    self.main.accounts.add_offline(name.strip())
                    self.refresh()
                except UserError as exc:
                    message(self, "Не удалось добавить аккаунт", str(exc))

        def add_microsoft(self) -> None:
            dialog = MicrosoftLoginDialog(self.main.store.settings.get("client_id", ""), self)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.account:
                self.main.accounts.put(dialog.account)
                self.refresh()

        def select(self) -> None:
            account = self.current()
            if account:
                self.main.accounts.data["selected"] = account["id"]
                self.main.accounts.save()
                self.refresh()

        def remove(self) -> None:
            account = self.current()
            if account and message(self, "Удалить аккаунт?", account["name"] +
                                   "\nЛокальные токены будут удалены; это не отзывает сессию в Microsoft.", question=True):
                self.main.accounts.remove(account["id"])
                self.refresh()

        def open_png(self) -> None:
            path, _ = QFileDialog.getOpenFileName(self, "Скин PNG", filter="PNG (*.png)")
            if path:
                try:
                    file = Path(path)
                    if file.stat().st_size > 512 * 1024:
                        raise UserError("Скин слишком большой.")
                    self.skin.load_png(file.read_bytes())
                except (OSError, UserError) as exc:
                    message(self, "Скин", str(exc))

        def fetch_skin(self) -> None:
            account = self.current()
            if not account:
                return

            def done(data: bytes) -> None:
                self.skin.load_png(data)
                atomic_bytes(self.main.store.root / "skins" / (account["id"] + ".png"), data)
            self.main.run_task("Загрузка скина", lambda p, c: download_skin(account), done)

    class SettingsDialog(QDialog):
        def __init__(self, main: MainWindow):
            super().__init__(main)
            self.main = main
            self.setWindowTitle("Настройки MCSync")
            self.resize(620, 530)
            layout = QVBoxLayout(self)
            layout.addWidget(label(f"MCSync {APP_VERSION}", "title"))
            form = QFormLayout()
            self.client_id = QLineEdit(main.store.settings.get("client_id", ""))
            self.client_id.setPlaceholderText("Свой Azure Application (Client) ID")
            self.ram = QSpinBox()
            self.ram.setRange(512, 131072)
            self.ram.setSingleStep(512)
            self.ram.setSuffix(" МБ")
            self.ram.setValue(int(main.store.settings.get("default_ram", 4096)))
            self.theme_field = QComboBox()
            for key, info in THEMES.items():
                self.theme_field.addItem(info["name"], key)
            self.theme_field.setCurrentIndex(self.theme_field.findData(main.theme))
            self.theme_hint = label(THEMES[main.theme]["description"], "muted", True)
            self.theme_field.currentIndexChanged.connect(lambda _: self.theme_hint.setText(
                THEMES[self.theme_field.currentData()]["description"]))
            self.layout_field = QComboBox()
            for key, text in LAYOUTS.items():
                self.layout_field.addItem(text, key)
            self.layout_field.setCurrentIndex(self.layout_field.findData(main.layout_mode))
            self.party_name_field = QLineEdit(main.store.settings.get("party_name", ""))
            self.party_name_field.setMaxLength(32)
            self.party_name_field.setPlaceholderText("Например, Саша · аккаунт Minecraft не передаётся")
            form.addRow("Ваше имя в пати", self.party_name_field)
            form.addRow("Оформление", self.theme_field)
            form.addRow("Интерфейс", self.layout_field)
            form.addRow("Microsoft Client ID", self.client_id)
            form.addRow("RAM новых сборок", self.ram)
            layout.addLayout(form)
            layout.addWidget(self.theme_hint)
            self.reduced_motion = QCheckBox("Уменьшить анимации и переходы")
            self.reduced_motion.setChecked(bool(main.store.settings.get("reduced_motion", False)))
            layout.addWidget(self.reduced_motion)
            layout.addWidget(label("Для Microsoft нужен ваш public-client Azure Client ID и одобрение Mojang. "
                                   "Client Secret не нужен. Сторонние ключи лаунчеров не используются.", "muted", True))
            layout.addWidget(button("Регистрация приложения: aka.ms/AppRegInfo", lambda:
                                    QDesktopServices.openUrl(QUrl("https://aka.ms/AppRegInfo"))))
            layout.addWidget(label("Данные: " + str(main.store.root), "muted", True))
            layout.addLayout(row(button("Открыть папку данных", lambda: open_path(main.store.root)),
                                 button("Диагностика", lambda: DiagnosticsDialog(main).exec())))
            layout.addWidget(label("Ctrl+S — сохранить · Ctrl+F — поиск · Ctrl+L — библиотека · F1 — диагностика", "muted", True))
            layout.addWidget(label("Независимый проект; не связан с Mojang/Microsoft или PolyMC/Prism.", "muted", True))
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
            buttons.accepted.connect(self.save)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)

        def save(self) -> None:
            chosen = self.theme_field.currentData()
            try:
                alias = party_name(self.party_name_field.text())
            except UserError as exc:
                message(self, "Проверьте имя в пати", str(exc))
                return
            self.main.store.settings.update(reduced_motion=self.reduced_motion.isChecked(), party_name=alias, client_id=self.client_id.text().strip(), default_ram=self.ram.value(),
                                            theme=chosen, layout=self.layout_field.currentData())
            self.main.store.save_settings()
            QApplication.instance().setProperty("reducedMotion", self.reduced_motion.isChecked())
            if self.reduced_motion.isChecked():
                self.main.main_pages.disable_motion()
                self.main.overview_stack.disable_motion()
            self.main.set_theme(chosen)
            self.main.set_layout_mode(self.layout_field.currentData())
            self.main.party_monitor.refresh()
            self.main.refresh_party_state()
            self.accept()

    class MainWindow(QMainWindow):
        def __init__(self, store: Store, *, network_enabled: bool = True, theme: str | None = None, layout: str | None = None):
            super().__init__()
            self.store, self.accounts = store, Accounts(store)
            QApplication.instance().setProperty("reducedMotion", bool(store.settings.get("reduced_motion", False)))
            self.theme = theme_key(theme if theme is not None else store.settings.get("theme"))
            self.layout_mode = layout_key(layout if layout is not None else store.settings.get("layout"))
            self.sync_checks: dict[str, dict[str, Any]] = {}
            self.party_states: dict[str, dict[str, Any]] = {}
            self.party_monitor = PartyMonitor(store)
            self.host_errors: dict[str, str] = {}
            self._loading_fields = False
            self._editor_baseline: dict[str, Any] = {}
            self._draft_memory: dict[str, dict[str, Any]] = {}
            self.draft_timer = QTimer(self)
            self.draft_timer.setSingleShot(True)
            self.draft_timer.timeout.connect(self.flush_draft)
            apply_theme(QApplication.instance(), self.theme)
            self.network_enabled = network_enabled
            self.bridge = Bridge(self)
            self.bridge.task_done.connect(self.task_done)
            self.bridge.progress.connect(self.task_progress)
            self.bridge.confirm_sync.connect(self.on_confirm_sync)
            self.bridge.update_check_done.connect(self.on_update_check)
            self.bridge.game_output.connect(self.on_game_output)
            self.bridge.game_finished.connect(self.on_game_finished)
            self.hosts: dict[str, SyncHost] = {}
            self.games: dict[str, GameSession] = {}
            self.buffers: dict[str, list[str]] = {}
            self.update_badges: set[str] = set()
            self.checking = False
            self.closing = False
            self.busy = False
            self.task: dict[str, Any] | None = None
            self.task_number = 0
            self.loaded_id = ""
            self.setWindowTitle(f"MCSync {APP_VERSION} — сборки для друзей")
            self.setWindowIcon(cube_icon(THEMES[self.theme]["accent"]))
            self.resize(1280, 860)
            self.setMinimumSize(1000, 690)
            central = QWidget()
            central.setObjectName("central")
            self.setCentralWidget(central)
            outer = QVBoxLayout(central)
            outer.setContentsMargins(18, 18, 18, 6)
            outer.setSpacing(0)
            splitter = QSplitter(Qt.Orientation.Horizontal)
            splitter.setChildrenCollapsible(False)
            self.sidebar = QFrame()
            self.sidebar.setObjectName("sidebar")
            self.sidebar.setMinimumWidth(225)
            self.sidebar.setMaximumWidth(275)
            left_layout = QVBoxLayout(self.sidebar)
            left_layout.setContentsMargins(16, 22, 16, 16)
            left_layout.setSpacing(10)
            brand_row = QHBoxLayout()
            self.brand_icon = label()
            self.brand_icon.setPixmap(cube_icon(THEMES[self.theme]["accent"]).pixmap(34, 34))
            brand_row.addWidget(self.brand_icon)
            brand_row.addWidget(label("MCSync", "brand"))
            brand_row.addStretch()
            left_layout.addLayout(brand_row)
            left_layout.addWidget(label("Твои друзья. Одна сборка.", "muted"))
            left_layout.addSpacing(13)
            self.library_btn = button("Все сборки", self.show_library, "nav")
            self.library_btn.setCheckable(True)
            left_layout.addWidget(self.library_btn)
            left_layout.addSpacing(5)
            left_layout.addWidget(label("БИБЛИОТЕКА", "kicker"))
            self.search = QLineEdit()
            self.search.setPlaceholderText("Поиск сборки…")
            self.search.setClearButtonEnabled(True)
            self.search.setAccessibleName("Поиск сборки")
            self.groups = QComboBox()
            self.groups.addItem("Все группы", None)
            self.groups.setAccessibleName("Группа сборок")
            self.groups.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            self.groups.setMinimumContentsLength(12)
            left_layout.addWidget(self.search)
            self.filter_toggle = button("Фильтры и порядок  ▾", self.toggle_filters, "ghost")
            left_layout.addWidget(self.filter_toggle)
            left_layout.addWidget(self.groups)
            self.groups.hide()
            self.sort_combo = QComboBox()
            for text, value in (("Избранное сначала", "favorite"), ("По названию", "name"), ("Недавно играли", "recent")):
                self.sort_combo.addItem(text, value)
            self.sort_combo.setCurrentIndex(max(0, self.sort_combo.findData(store.settings.get("sort"))))
            self.sort_combo.setAccessibleName("Порядок сборок")
            left_layout.addWidget(self.sort_combo)
            self.sort_combo.hide()
            self.instances = QListWidget()
            self.instances.setObjectName("instances")
            self.instances.setIconSize(QSize(42, 42))
            self.instances.setItemDelegate(InstanceDelegate(self))
            self.instances.setMouseTracking(True)
            self.instances.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.instances.setAccessibleName("Сборки Minecraft")
            self.instances.currentItemChanged.connect(self.on_instance_changed)
            self.instances.itemDoubleClicked.connect(lambda _: self.launch())
            left_layout.addWidget(self.instances, 1)
            self.count_label = label("", "muted")
            left_layout.addWidget(self.count_label)
            left_layout.addSpacing(8)
            self.new_btn = button("+  Создать сборку", self.create_instance)
            self.connect_btn = button("Вступить в пати", self.connect_instance, "primary")
            self.import_btn = button("Импорт .mrpack / ZIP", self.import_instance, "ghost")
            for widget in (self.new_btn, self.connect_btn, self.import_btn):
                left_layout.addWidget(widget)
            splitter.addWidget(self.sidebar)

            workspace = QWidget()
            workspace_layout = QVBoxLayout(workspace)
            workspace_layout.setContentsMargins(8, 0, 0, 0)
            workspace_layout.setSpacing(18)
            header = QHBoxLayout()
            header.addWidget(label("Мои сборки", "pageTitle"))
            header.addStretch()
            self.account_combo = QComboBox()
            self.account_combo.setMinimumWidth(170)
            self.account_combo.setMaximumWidth(240)
            self.account_combo.setAccessibleName("Аккаунт для запуска Minecraft")
            self.account_combo.currentIndexChanged.connect(self.account_changed)
            self.accounts_btn = button("Аккаунты", self.show_accounts, "ghost")
            self.settings_btn = button("Настройки", lambda: SettingsDialog(self).exec(), "ghost")
            header.addWidget(self.account_combo)
            header.addWidget(self.accounts_btn)
            header.addWidget(self.settings_btn)
            workspace_layout.addLayout(header)
            self.recovery_label = label("", "notice", True)
            self.recovery_label.hide()
            workspace_layout.addWidget(self.recovery_label)
            self.main_pages = FadeStack()
            self.library_page = self.build_library_page()
            self.main_pages.addWidget(self.library_page)
            self.detail_stack = QStackedWidget()
            self.empty_page = self.build_empty_page()
            self.detail_stack.addWidget(self.empty_page)
            self.details = QWidget()
            detail_layout = QVBoxLayout(self.details)
            detail_layout.setContentsMargins(0, 0, 0, 0)
            detail_layout.setSpacing(13)
            self.hero = HeroFrame(self.theme)
            hero_layout = QVBoxLayout(self.hero)
            hero_layout.setContentsMargins(22, 18, 22, 18)
            hero_layout.setSpacing(17)
            title_row = QHBoxLayout()
            self.hero_icon = label()
            self.hero_icon.setPixmap(cube_icon(THEMES[self.theme]["accent"]).pixmap(42, 42))
            title_row.addWidget(self.hero_icon, 0, Qt.AlignmentFlag.AlignTop)
            title_row.addSpacing(8)
            title_col = QVBoxLayout()
            title_col.setSpacing(4)
            self.hero_kicker = ElidedLabel("СБОРКА MINECRAFT")
            self.hero_kicker.setObjectName("kicker")
            self.title_label = ElidedLabel("Выберите сборку")
            self.title_label.setObjectName("title")
            self.meta_label = ElidedLabel("Создайте свою или подключитесь к другу по ссылке.")
            self.meta_label.setObjectName("muted")
            title_col.addWidget(self.hero_kicker)
            title_col.addWidget(self.title_label)
            title_col.addWidget(self.meta_label)
            title_row.addLayout(title_col, 1)
            title_row.addSpacing(25)
            hero_layout.addLayout(title_row)
            actions = QHBoxLayout()
            actions.setSpacing(8)
            self.play_btn = button("▶  Играть", self.launch, "play")
            self.play_btn.setMinimumWidth(160)
            self.play_btn.setToolTip("Minecraft и Java подготовятся автоматически. Ctrl+Enter — играть / остановить.")
            self.sync_btn = button("Обновить сейчас", self.sync_now)
            self.host_btn = button("Пригласить друзей", self.show_host)
            self.more_btn = QToolButton()
            self.more_btn.setText("Ещё")
            self.more_btn.setAccessibleName("Действия со сборкой")
            self.more_btn.setObjectName("ghost")
            self.more_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu = QMenu(self.more_btn)
            self.manual_sync_action = menu.addAction("Обновить сборку сейчас")
            self.manual_sync_action.triggered.connect(self.sync_now)
            self.favorite_action = menu.addAction("Добавить в избранное")
            self.favorite_action.triggered.connect(self.toggle_favorite)
            self.game_folder_btn = menu.addAction("Открыть папку сборки")
            self.game_folder_btn.triggered.connect(self.open_game_folder)
            self.copy_btn = menu.addAction("Создать независимую копию")
            self.copy_btn.triggered.connect(self.copy_instance)
            self.export_btn = menu.addAction("Экспорт .mrpack / ZIP")
            self.export_btn.triggered.connect(self.export_instance)
            menu.addSeparator()
            self.delete_btn = menu.addAction("Удалить сборку…")
            self.delete_btn.triggered.connect(self.delete_instance)
            self.more_btn.setMenu(menu)
            for widget in (self.play_btn, self.sync_btn, self.host_btn, self.more_btn):
                actions.addWidget(widget)
            actions.addStretch()
            self.sync_label = label("", "badge")
            actions.addWidget(self.sync_label, 0, Qt.AlignmentFlag.AlignVCenter)
            hero_layout.addLayout(actions)
            detail_layout.addWidget(self.hero)
            self.flow_hint = label("", "flowHint", True)
            self.flow_hint.setTextFormat(Qt.TextFormat.PlainText)
            detail_layout.addWidget(self.flow_hint)
            self.tabs = QTabWidget()
            self.tabs.setDocumentMode(True)
            self.tabs.tabBar().setUsesScrollButtons(True)
            self.tabs.tabBar().setExpanding(False)
            self.tabs.setMinimumWidth(0)
            self.tabs.tabBar().setDrawBase(False)
            self.overview = self.build_instance_overview()
            self.tabs.addTab(self.overview, "Обзор")
            self.file_panels = {}
            for folder, title in (("mods", "Моды"), ("resourcepacks", "Ресурсы"), ("shaderpacks", "Шейдеры"), ("saves", "Миры")):
                panel = FilePanel(folder, self)
                self.file_panels[folder] = panel
                self.tabs.addTab(panel, title)
            self.modrinth_tab = self.build_modrinth()
            self.tabs.addTab(self.modrinth_tab, "Modrinth")
            self.console_instance = ""
            self.console = QPlainTextEdit()
            self.console.setReadOnly(True)
            self.console.setMaximumBlockCount(5000)
            self.console.setStyleSheet("font-family: Consolas, 'DejaVu Sans Mono', monospace; font-size: 12px;")
            self.tabs.addTab(self.console, "Консоль")
            self.tabs.addTab(self.build_logs(), "Логи")
            self.content_row = QHBoxLayout()
            self.content_row.setSpacing(14)
            self.content_row.addWidget(self.tabs, 1)
            self.content_row.addWidget(self.party_panel)
            detail_layout.addLayout(self.content_row, 1)
            self.detail_stack.addWidget(self.details)
            self.main_pages.addWidget(self.detail_stack)
            workspace_layout.addWidget(self.main_pages, 1)
            task_row = QHBoxLayout()
            self.task_label = label("Готово к запуску", "muted")
            self.progress_bar = QProgressBar()
            self.progress_bar.setMaximumWidth(260)
            self.progress_bar.setRange(0, 1000)
            self.progress_bar.setValue(0)
            self.progress_bar.hide()
            self.cancel_btn = button("Отменить", self.cancel_task)
            self.cancel_btn.hide()
            task_row.addWidget(self.task_label, 1)
            task_row.addWidget(self.progress_bar)
            task_row.addWidget(self.cancel_btn)
            workspace_layout.addLayout(task_row)
            splitter.addWidget(workspace)
            splitter.setSizes([248, 1030])
            splitter.setStretchFactor(0, 0)
            splitter.setStretchFactor(1, 1)
            outer.addWidget(splitter, 1)
            self.statusBar().showMessage("Автоустановка Java  ·  Vanilla / Fabric / Quilt / Forge / NeoForge")
            self.search.textChanged.connect(lambda *_: self.refresh_instances(reload_fields=False))
            self.groups.currentIndexChanged.connect(lambda *_: self.refresh_instances(reload_fields=False))
            self.sort_combo.currentIndexChanged.connect(lambda *_: self.refresh_instances(reload_fields=False))
            self.connect_editor_signals()
            self.refresh_accounts()
            last = store.settings.get("last_instance", "")
            self.refresh_instances(last if isinstance(last, str) else "")
            self.set_layout_mode(self.layout_mode)
            if self.layout_mode != "gallery":
                self.show_details()
            shortcuts = {"Ctrl+F": self.search.setFocus, "Ctrl+S": self.save_current,
                         "Ctrl+N": self.create_instance, "Ctrl+Return": self.launch,
                         "Ctrl+L": self.show_library, "Ctrl+,": lambda: self.show_overview_page(1),
                         "F1": lambda: DiagnosticsDialog(self).exec()}
            self.shortcuts = []
            for keys, callback in shortcuts.items():
                if sys.platform == "darwin":
                    keys = keys.replace("Ctrl+", "Meta+")
                shortcut = QShortcut(QKeySequence(keys), self)
                shortcut.activated.connect(callback)
                self.shortcuts.append(shortcut)
            self.update_timer = QTimer(self)
            self.update_timer.setInterval(1000)
            self.update_timer.timeout.connect(self.refresh_party_state)
            if network_enabled:
                self.party_monitor.start()
                self.update_timer.start()
                QTimer.singleShot(400, self.resume_parties)

        def toggle_filters(self) -> None:
            visible = not self.groups.isVisible()
            self.groups.setVisible(visible)
            self.sort_combo.setVisible(visible)
            self.filter_toggle.setText("Фильтры и порядок  ▴" if visible else "Фильтры и порядок  ▾")

        def resizeEvent(self, event: Any) -> None:
            super().resizeEvent(event)
            if hasattr(self, "party_panel"):
                self.party_panel.setFixedWidth(246 if self.width() >= 1150 else 215)

        def build_empty_page(self) -> QWidget:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.addStretch(1)
            icon = label()
            icon.setPixmap(cube_icon(THEMES[self.theme]["accent"]).pixmap(78, 78))
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.empty_icon = icon
            layout.addWidget(icon)
            self.empty_title = label("Всё начинается со сборки", "title")
            self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.empty_title)
            self.empty_hint = label("Создайте свой мир или подключитесь к сборке друга.\n"
                                    "Моды, Minecraft и Java — всё в одном месте.", "muted", True)
            self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.empty_hint)
            actions = QHBoxLayout()
            actions.addStretch()
            actions.addWidget(button("+  Создать сборку", self.create_instance, "primary"))
            actions.addWidget(button("Подключиться к другу", self.connect_instance))
            actions.addStretch()
            layout.addSpacing(12)
            layout.addLayout(actions)
            layout.addStretch(2)
            return page

        def set_theme(self, key: str) -> None:
            """Change appearance without reloading/discarding in-progress instance fields."""
            self.theme = theme_key(key)
            apply_theme(QApplication.instance(), self.theme)
            color = THEMES[self.theme]["accent"]
            self.setWindowIcon(cube_icon(color))
            self.brand_icon.setPixmap(cube_icon(color).pixmap(34, 34))
            self.hero_icon.setPixmap(cube_icon(color).pixmap(52, 52))
            self.empty_icon.setPixmap(cube_icon(color).pixmap(78, 78))
            self.hero.key = self.theme
            self.hero.update()
            self.library_grid.viewport().update()
            for i in range(self.instances.count()):
                item = self.instances.item(i)
                data = item.data(int(Qt.ItemDataRole.UserRole) + 1) or {}
                item.setIcon(cube_icon(color if data.get("linked") else THEMES[self.theme]["muted"]))
            self.instances.viewport().update()


        def build_library_page(self) -> QWidget:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 2, 0, 0)
            layout.setSpacing(17)
            intro = QFrame()
            intro.setObjectName("card")
            intro_layout = QVBoxLayout(intro)
            intro_layout.setContentsMargins(22, 21, 22, 21)
            intro_layout.addWidget(label("Во что играем сегодня?", "title"))
            intro_layout.addWidget(label("Создайте свою сборку или войдите в пати друга. Java, Minecraft и обновления подготовит MCSync.", "muted", True))
            actions = QHBoxLayout()
            actions.addWidget(button("+  Создать сборку", self.create_instance, "primary"))
            actions.addWidget(button("Подключиться к другу", self.connect_instance))
            actions.addStretch()
            intro_layout.addLayout(actions)
            layout.addWidget(intro)
            heading = QHBoxLayout()
            heading.addWidget(label("Все сборки", "sectionTitle"))
            heading.addStretch()
            self.library_summary = label("", "muted")
            heading.addWidget(self.library_summary)
            layout.addLayout(heading)
            self.library_grid = QListWidget()
            self.library_grid.setObjectName("libraryGrid")
            self.library_grid.setViewMode(QListWidget.ViewMode.IconMode)
            self.library_grid.setResizeMode(QListWidget.ResizeMode.Adjust)
            self.library_grid.setMovement(QListWidget.Movement.Static)
            self.library_grid.setWrapping(True)
            self.library_grid.setGridSize(QSize(270, 180))
            self.library_grid.setSpacing(7)
            self.library_grid.setMouseTracking(True)
            self.library_grid.setItemDelegate(GridDelegate(self))
            self.library_grid.setAccessibleName("Карточки сборок")
            self.library_grid.itemClicked.connect(self.open_library_instance)
            self.library_grid.itemActivated.connect(self.open_library_instance)
            layout.addWidget(self.library_grid, 1)
            layout.addWidget(label("1 · Откройте сборку    2 · Выберите аккаунт    3 · Нажмите «Играть»", "muted", True))
            return page

        def show_library(self) -> None:
            self.flush_draft()
            self.main_pages.setCurrentWidget(self.library_page)
            self.library_btn.setChecked(True)
            self.library_grid.viewport().update()

        def show_details(self) -> None:
            self.main_pages.setCurrentWidget(self.detail_stack)
            self.library_btn.setChecked(False)

        def open_library_instance(self, item: QListWidgetItem) -> None:
            instance_id = item.data(Qt.ItemDataRole.UserRole)
            self.refresh_instances(instance_id)
            self.show_details()

        def on_instance_changed(self, *args: Any) -> None:
            self.show_details()
            self.load_detail()

        def set_layout_mode(self, value: str) -> None:
            self.layout_mode = layout_key(value)
            compact = self.layout_mode == "compact"
            self.hero.setMinimumHeight(148 if compact else 192)
            self.hero.layout().setContentsMargins(18 if compact else 22, 12 if compact else 18,
                                                  18 if compact else 22, 12 if compact else 18)
            self.hero.layout().setSpacing(9 if compact else 17)
            self.instances.doItemsLayout()
            for panel in self.file_panels.values():
                panel.list.doItemsLayout()
            if self.layout_mode == "gallery":
                self.show_library()
            self.instances.viewport().update()

        def toggle_favorite(self) -> None:
            inst = self.current_instance()
            if inst and not self.busy:
                self.flush_draft()
                self.store.update(inst.id, favorite=not inst.favorite)
                self.refresh_instances(inst.id, reload_fields=False)

        def build_instance_overview(self) -> QWidget:
            panel = QWidget()
            outer = QVBoxLayout(panel)
            outer.setContentsMargins(0, 2, 0, 0)
            outer.setSpacing(12)
            switch = QHBoxLayout()
            self.summary_btn = button("Сводка", lambda: self.show_overview_page(0), "segment")
            self.parameters_btn = button("Параметры", lambda: self.show_overview_page(1), "segment")
            for btn in (self.summary_btn, self.parameters_btn):
                btn.setCheckable(True)
                switch.addWidget(btn)
            switch.addStretch()
            switch.addWidget(button("Диагностика", lambda: DiagnosticsDialog(self).exec(), "ghost"))
            outer.addLayout(switch)
            self.overview_stack = FadeStack()
            summary = QWidget()
            summary_layout = QVBoxLayout(summary)
            summary_layout.setContentsMargins(0, 0, 0, 0)
            summary_layout.setSpacing(13)
            stats_strip = QFrame()
            stats_strip.setObjectName("statStrip")
            stats = QHBoxLayout(stats_strip)
            stats.setContentsMargins(0, 0, 0, 0)
            stats.setSpacing(0)
            self.stat_mods, self.stat_worlds, self.stat_time = StatCard("Моды ↗"), StatCard("Миры ↗"), StatCard("Время в игре")
            self.stat_mods.make_action("Открыть моды сборки", lambda: self.tabs.setCurrentWidget(self.file_panels["mods"]))
            self.stat_worlds.make_action("Открыть миры сборки", lambda: self.tabs.setCurrentWidget(self.file_panels["saves"]))
            for card in (self.stat_mods, self.stat_worlds, self.stat_time):
                stats.addWidget(card, 1)
            summary_layout.addWidget(stats_strip)
            columns = QHBoxLayout()
            columns.setSpacing(12)
            self.party_panel = PartyPanel(self)
            self.summary_sync = self.party_panel.explanation
            self.summary_sync_btn = self.party_panel.action
            self.party_panel.setParent(self.details)
            runtime = QFrame()
            runtime.setObjectName("card")
            runtime_layout = QVBoxLayout(runtime)
            runtime_layout.setContentsMargins(18, 17, 18, 17)
            runtime_layout.addWidget(label("Готовность к запуску", "sectionTitle"))
            self.summary_runtime = label("", "muted", True)
            runtime_layout.addWidget(self.summary_runtime, 1)
            runtime_layout.addWidget(button("Настроить запуск", lambda: self.show_overview_page(1), "ghost"),
                                     0, Qt.AlignmentFlag.AlignLeft)
            columns.addWidget(runtime, 1)
            notes = QFrame()
            notes.setObjectName("card")
            notes_layout = QVBoxLayout(notes)
            notes_layout.setContentsMargins(18, 17, 18, 17)
            title = QHBoxLayout()
            title.addWidget(label("Заметки", "sectionTitle"))
            title.addStretch()
            title.addWidget(button("Редактировать", self.edit_notes, "ghost"))
            notes_layout.addLayout(title)
            self.summary_notes = label("", "muted", True)
            notes_layout.addWidget(self.summary_notes)
            columns.addWidget(notes, 1)
            summary_layout.addLayout(columns)
            summary_layout.addStretch()
            summary_scroll = QScrollArea()
            summary_scroll.setWidgetResizable(True)
            summary_scroll.setWidget(summary)
            self.overview_stack.addWidget(summary_scroll)
            self.parameters_panel = self.build_overview()
            self.overview_stack.addWidget(self.parameters_panel)
            outer.addWidget(self.overview_stack, 1)
            self.show_overview_page(0)
            return panel

        def show_overview_page(self, index: int) -> None:
            if hasattr(self, "overview"):
                self.tabs.setCurrentWidget(self.overview)
            self.overview_stack.setCurrentIndex(index)
            self.summary_btn.setChecked(index == 0)
            self.parameters_btn.setChecked(index == 1)
            if index == 0 and hasattr(self, "file_panels"):
                self.update_summary(self.current_instance())

        def edit_notes(self) -> None:
            self.show_overview_page(1)
            self.parameter_scroll.ensureWidgetVisible(self.notes_field)
            self.notes_field.setFocus()

        def summary_sync_action(self) -> None:
            inst = self.current_instance()
            if inst and inst.sync_url:
                if inst.id in self.update_badges:
                    self.sync_now()
                else:
                    self.show_overview_page(1)
            else:
                self.show_host()

        def update_summary(self, inst: Instance | None) -> None:
            if inst is None:
                return
            items = self.file_panels["mods"].list
            enabled = sum(bool((items.item(i).data(int(Qt.ItemDataRole.UserRole) + 1) or {}).get("enabled", True))
                          for i in range(items.count()))
            self.stat_mods.set_value(str(enabled), f"Включено · всего файлов {items.count()}")
            count = self.file_panels["saves"].list.count()
            self.stat_worlds.set_value(str(count), "Локальные миры · ZIP-бэкапы")
            self.stat_time.set_value(playtime_text(inst.playtime), "Учёт времени этого лаунчера")
            self.party_panel.refresh(inst)
            state = "Игра установлена" if installation_ready(self.store, inst) else "Игра и Java установятся при первом запуске"
            java = Path(inst.java).name if inst.java else "Автоматически · Mojang Java"
            self.summary_runtime.setText(f"{state}\nRAM: {human_size(inst.ram_max * 1024**2)} · окно {inst.width}×{inst.height}\n"
                                         f"Java: {java}" + (f"\nСервер: {inst.server}" if inst.server else ""))
            note = " ".join(self.notes_field.toPlainText().split())
            self.summary_notes.setText(note[:400] + ("…" if len(note) > 400 else "") if note else "Планы на вечер, полезные команды или напоминания — добавь свою заметку.")

        def editor_values(self, inst: Instance) -> dict[str, Any]:
            values = {"name": self.name_field.text().strip(), "group": self.group_field.currentText().strip(),
                      "notes": self.notes_field.toPlainText(), "java": self.java_field.text().strip(),
                      "ram_min": self.ram_min.value(), "ram_max": self.ram_max.value(),
                      "jvm_args": self.jvm_field.text(), "pre_command": self.pre_field.text(),
                      "post_command": self.post_field.text(), "width": self.width_field.value(), "height": self.height_field.value()}
            if inst.sync_url:
                values["sync_mode"] = self.sync_mode_field.currentData()
            else:
                values.update(minecraft=self.mc_field.currentText().strip(), loader=self.loader_field.currentData(),
                              loader_version=self.loader_version_field.currentText().strip(), server=self.server_field.text().strip())
            return values

        def connect_editor_signals(self) -> None:
            for field in (self.name_field, self.java_field, self.jvm_field, self.pre_field, self.post_field, self.server_field):
                field.textChanged.connect(self.editor_changed)
            for field in (self.group_field, self.mc_field, self.loader_version_field):
                field.currentTextChanged.connect(self.editor_changed)
            for field in (self.loader_field, self.sync_mode_field):
                field.currentIndexChanged.connect(self.editor_changed)
            for field in (self.ram_min, self.ram_max, self.width_field, self.height_field):
                field.valueChanged.connect(self.editor_changed)
            self.notes_field.textChanged.connect(self.editor_changed)

        def editor_changed(self, *args: Any) -> None:
            if not self._loading_fields and self.loaded_id and not self.busy:
                self.draft_timer.start(600)
                self.draft_label.setText("Есть изменения · черновик сохраняется")
                self.discard_btn.setEnabled(True)

        def flush_draft(self) -> None:
            if self._loading_fields or not self.loaded_id or not self._editor_baseline:
                return
            self.draft_timer.stop()
            try:
                inst = self.store.load(self.loaded_id)
                values = self.editor_values(inst)
                changes = {key: value for key, value in values.items() if value != self._editor_baseline.get(key)}
                if changes:
                    self._draft_memory[inst.id] = changes
                    atomic_json(inst.directory / "draft.json", {"schema": 1, "values": changes})
                    if os.name != "nt":
                        (inst.directory / "draft.json").chmod(0o600)
                    self.draft_label.setText("Черновик сохранён · применится по кнопке «Сохранить»")
                    self.discard_btn.setEnabled(True)
                else:
                    self._draft_memory.pop(inst.id, None)
                    (inst.directory / "draft.json").unlink(missing_ok=True)
                    self.draft_label.setText("Все параметры сохранены")
                    self.discard_btn.setEnabled(False)
            except (UserError, OSError) as exc:
                LOG.warning("Не удалось сохранить черновик: %s", redact(str(exc)))
                self.draft_label.setText("Черновик не записан: проверьте доступ к папке данных")

        def restore_draft(self, inst: Instance) -> None:
            try:
                saved = read_json(inst.directory / "draft.json", {})
                values = self._draft_memory.get(inst.id, saved.get("values", {}) if isinstance(saved, dict) else {})
                if not isinstance(values, dict):
                    raise UserError("Некорректный черновик.")
                fields = {"name": self.name_field, "group": self.group_field, "minecraft": self.mc_field,
                          "loader_version": self.loader_version_field, "server": self.server_field,
                          "notes": self.notes_field, "java": self.java_field, "jvm_args": self.jvm_field,
                          "pre_command": self.pre_field, "post_command": self.post_field,
                          "ram_min": self.ram_min, "ram_max": self.ram_max, "width": self.width_field, "height": self.height_field}
                for key, value in values.items():
                    if key not in self._editor_baseline:
                        continue  # A host-managed version must never be restored from a local draft.
                    if key in ("loader", "sync_mode"):
                        choices = LOADERS if key == "loader" else ("ask", "version", "auto")
                        if isinstance(value, str) and value in choices:
                            field = self.loader_field if key == "loader" else self.sync_mode_field
                            field.setCurrentIndex(field.findData(value))
                    elif key in fields:
                        field = fields[key]
                        if isinstance(field, QSpinBox):
                            if type(value) is int and field.minimum() <= value <= field.maximum():
                                field.setValue(value)
                        elif isinstance(value, str) and len(value) <= 100_000:
                            if isinstance(field, QPlainTextEdit):
                                field.setPlainText(value)
                            elif isinstance(field, QComboBox):
                                field.setCurrentText(value)
                            else:
                                field.setText(value)
                self.draft_label.setText("Восстановлен черновик · изменения ещё не применены" if values else "Все параметры сохранены")
                self.discard_btn.setEnabled(bool(values))
            except (UserError, OSError) as exc:
                self.draft_label.setText("Не удалось прочитать черновик · оригинал не изменён")
                LOG.warning("Черновик %s: %s", inst.id, redact(str(exc)))

        def discard_draft(self) -> None:
            inst = self.current_instance()
            if inst and not self.busy:
                self._draft_memory.pop(inst.id, None)
                (inst.directory / "draft.json").unlink(missing_ok=True)
                self._editor_baseline = {}  # don't re-capture the discarded editor contents
                self.load_detail()


        def cached_versions(self) -> list[str]:
            value = read_json(self.store.root / "mc_versions.json", [])
            return value if isinstance(value, list) and all(isinstance(v, str) for v in value) else []

        def build_overview(self) -> QWidget:
            panel = QWidget()
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(0, 0, 0, 0)
            panel_layout.setSpacing(10)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            self.parameter_scroll = scroll
            content = QWidget()
            content.setObjectName("overviewContent")
            layout = QVBoxLayout(content)
            layout.setContentsMargins(0, 0, 8, 0)
            layout.setSpacing(12)

            def card(title: str, hint: str) -> tuple[QFrame, QVBoxLayout, QFormLayout]:
                widget = QFrame()
                widget.setObjectName("card")
                card_layout = QVBoxLayout(widget)
                card_layout.setContentsMargins(18, 16, 18, 16)
                card_layout.setSpacing(12)
                heading = QHBoxLayout()
                heading.addWidget(label(title, "sectionTitle"))
                heading.addStretch()
                card_layout.addLayout(heading)
                if hint:
                    card_layout.addWidget(label(hint, "muted", True))
                form = QFormLayout()
                form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
                form.setHorizontalSpacing(18)
                form.setVerticalSpacing(9)
                card_layout.addLayout(form)
                layout.addWidget(widget)
                return widget, card_layout, form

            _, _, form = card("Сборка", "Версии и сервер. У подписки эти параметры задаёт хост.")
            self.identity_form = form
            self.name_field = QLineEdit()
            self.group_field = QComboBox()
            self.group_field.setEditable(True)
            self.group_field.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            self.group_field.setMinimumContentsLength(12)
            self.group_field.lineEdit().setPlaceholderText("Без группы")
            self.mc_field = QComboBox()
            self.mc_field.setEditable(True)
            self.mc_field.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            self.mc_field.setMinimumContentsLength(10)
            self.mc_field.addItems(self.cached_versions() or ["1.21.1", "1.20.1"])
            self.loader_field = QComboBox()
            for key, title in LOADERS.items():
                self.loader_field.addItem(title, key)
            self.loader_version_field = QComboBox()
            self.loader_version_field.setEditable(True)
            self.loader_version_field.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            self.loader_version_field.setMinimumContentsLength(10)
            self.loader_version_field.lineEdit().setPlaceholderText("Пусто = авто")
            self.loader_field.currentIndexChanged.connect(self.loader_changed)
            self.mc_versions_btn = button("Обновить список", self.fetch_mc_versions, "ghost")
            self.loader_versions_btn = button("Совместимые версии", self.fetch_loader_versions, "ghost")
            form.addRow("Название", self.name_field)
            form.addRow("Группа", self.group_field)
            form.addRow("Minecraft", row(self.mc_field, self.mc_versions_btn))
            form.addRow("Загрузчик", self.loader_field)
            form.addRow("Версия загрузчика", row(self.loader_version_field, self.loader_versions_btn))
            self.server_field = QLineEdit()
            self.server_field.setPlaceholderText("play.example.org:25565 · необязательно")
            form.addRow("Автовход на сервер", self.server_field)
            self.sync_mode_field = QComboBox()
            for text, value in (("Спрашивать о любых изменениях", "ask"),
                                ("Спрашивать только при смене версий", "version"),
                                ("Автоматически (включая смену версий)", "auto")):
                self.sync_mode_field.addItem(text, value)
            form.addRow("Синхронизация", self.sync_mode_field)
            self.disconnect_btn = button("Отсоединить от хоста", self.disconnect_instance, "ghost")
            form.addRow("", self.disconnect_btn)
            _, launch_layout, form = card("Параметры запуска", "Локальные настройки — у каждого друга свои.")
            self.ram_min = QSpinBox()
            self.ram_max = QSpinBox()
            for spin in (self.ram_min, self.ram_max):
                spin.setRange(256, 131072)
                spin.setSingleStep(256)
                spin.setSuffix(" МБ")
            form.addRow("RAM мин. / макс.", row(self.ram_min, self.ram_max))
            self.java_field = QLineEdit()
            self.java_field.setPlaceholderText("Авто — Java от Mojang")
            self.java_pick_btn = button("Путь", self.pick_java, "ghost")
            self.java_find_btn = button("Найти Java", self.find_java, "ghost")
            form.addRow("Java", row(self.java_field, self.java_pick_btn, self.java_find_btn))
            self.jvm_field = QLineEdit()
            self.jvm_field.setPlaceholderText("Дополнительные JVM-аргументы")
            form.addRow("JVM", self.jvm_field)
            self.width_field, self.height_field = QSpinBox(), QSpinBox()
            self.width_field.setRange(320, 16384)
            self.height_field.setRange(240, 16384)
            form.addRow("Размер окна", row(self.width_field, self.height_field))
            self.advanced = QWidget()
            advanced_layout = QFormLayout(self.advanced)
            advanced_layout.setContentsMargins(0, 0, 0, 0)
            advanced_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            self.pre_field, self.post_field = QLineEdit(), QLineEdit()
            self.pre_field.setPlaceholderText("Локальная shell-команда; не синхронизируется")
            self.post_field.setPlaceholderText("Локальная shell-команда после выхода")
            advanced_layout.addRow("Перед запуском", self.pre_field)
            advanced_layout.addRow("После выхода", self.post_field)
            self.advanced.hide()
            self.advanced_btn = QToolButton()
            self.advanced_btn.setObjectName("ghost")
            self.advanced_btn.setText("Дополнительные команды")
            self.advanced_btn.setArrowType(Qt.ArrowType.RightArrow)
            self.advanced_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self.advanced_btn.setCheckable(True)
            self.advanced_btn.toggled.connect(self.advanced.setVisible)
            self.advanced_btn.toggled.connect(lambda open_: self.advanced_btn.setArrowType(
                Qt.ArrowType.DownArrow if open_ else Qt.ArrowType.RightArrow))
            launch_layout.addWidget(self.advanced_btn, 0, Qt.AlignmentFlag.AlignLeft)
            launch_layout.addWidget(self.advanced)
            notes = QFrame()
            notes.setObjectName("card")
            notes_layout = QVBoxLayout(notes)
            notes_layout.setContentsMargins(18, 16, 18, 16)
            notes_layout.addWidget(label("Заметки", "sectionTitle"))
            self.notes_field = QPlainTextEdit()
            self.notes_field.setPlaceholderText("Что важно помнить об этой сборке?")
            self.notes_field.setFixedHeight(95)
            notes_layout.addWidget(self.notes_field)
            layout.addWidget(notes)
            layout.addStretch()
            scroll.setWidget(content)
            panel_layout.addWidget(scroll, 1)
            self.save_btn = button("Сохранить настройки", self.save_current, "primary")
            self.repair_btn = button("Проверить / переустановить", self.repair_install, "ghost")
            self.discard_btn = button("Сбросить черновик", self.discard_draft, "ghost")
            self.discard_btn.setEnabled(False)
            self.draft_label = label("Все параметры сохранены", "muted", True)
            footer = row(self.save_btn, self.repair_btn, self.discard_btn)
            footer.addStretch()
            panel_layout.addLayout(footer)
            panel_layout.addWidget(self.draft_label)
            panel_layout.addWidget(label("При смене версии рекомендуется подтверждение и резервная копия миров.", "muted", True))
            return panel


        def build_modrinth(self) -> QWidget:
            panel = QWidget()
            layout = QVBoxLayout(panel)
            self.mr_query = QLineEdit()
            self.mr_query.setPlaceholderText("Sodium, Fabric API, сборка…")
            self.mr_type = QComboBox()
            for text, value in (("Моды", "mod"), ("Ресурспаки", "resourcepack"), ("Шейдеры", "shader"), ("Сборки", "modpack")):
                self.mr_type.addItem(text, value)
            self.mr_search_btn = button("Найти", self.search_modrinth)
            layout.addLayout(row(self.mr_query, self.mr_type, self.mr_search_btn))
            self.mr_filter = QCheckBox("Только для версии Minecraft этой сборки")
            self.mr_filter.setChecked(True)
            layout.addWidget(self.mr_filter)
            self.mr_results = QListWidget()
            self.mr_results.itemDoubleClicked.connect(lambda _: self.install_selected_modrinth())
            self.mr_results.currentItemChanged.connect(self.modrinth_selection_changed)
            layout.addWidget(self.mr_results, 1)
            self.mr_context: tuple[str, str, Instance | None] | None = None
            self.mr_offset, self.mr_more = 0, False
            self.mr_page_label = label("Введите запрос и нажмите «Найти»", "muted")
            self.mr_previous = button("← Назад", lambda: self.change_modrinth_page(-1), "ghost")
            self.mr_next = button("Далее →", lambda: self.change_modrinth_page(1), "ghost")
            self.mr_previous.setEnabled(False)
            self.mr_next.setEnabled(False)
            layout.addLayout(row(self.mr_previous, self.mr_page_label, self.mr_next))
            self.mr_query.textChanged.connect(self.invalidate_modrinth_pages)
            self.mr_type.currentIndexChanged.connect(self.invalidate_modrinth_pages)
            self.mr_filter.toggled.connect(self.invalidate_modrinth_pages)
            self.mr_install_btn = button("Установить + зависимости", self.install_selected_modrinth)
            self.mr_update_btn = button("Обновить установленные моды", self.update_mods)
            self.mr_update_btn.setToolTip("Обновляются только проекты, установленные через Modrinth в этом лаунчере.")
            layout.addLayout(row(self.mr_install_btn, self.mr_update_btn))
            layout.addWidget(label("Сборки .mrpack устанавливаются в новую сборку. Для модов выбирается последняя "
                                   "совместимая версия и обязательные зависимости; необязательные не ставятся.", "muted", True))
            self.mr_query.returnPressed.connect(self.search_modrinth)
            return panel

        def build_logs(self) -> QWidget:
            panel = QWidget()
            layout = QVBoxLayout(panel)
            self.logs_combo = QComboBox()
            self.logs_combo.currentIndexChanged.connect(self.show_log)
            layout.addLayout(row(self.logs_combo, button("Обновить", self.refresh_logs),
                                 button("Бэкапы", self.open_backups)))
            self.log_view = QPlainTextEdit()
            self.log_view.setReadOnly(True)
            self.log_view.setMaximumBlockCount(10000)
            layout.addWidget(self.log_view, 1)
            layout.addWidget(label("Показывается последний 1 МБ текста. Логи могут содержать личные данные — "
                                   "проверяйте их перед публикацией.", "muted", True))
            return panel

        def current_id(self) -> str:
            item = self.instances.currentItem()
            return item.data(Qt.ItemDataRole.UserRole) if item else ""

        def current_instance(self) -> Instance | None:
            instance_id = self.current_id()
            return self.store.load(instance_id) if instance_id else None

        def is_locked(self, instance_id: str) -> bool:
            return instance_id in self.games or bool(self.task and self.task.get("instance_id") == instance_id)

        def refresh_instances(self, selected_id: str = "", *, reload_fields: bool = True) -> None:
            self.flush_draft()
            explicit = bool(selected_id)
            selected_id = selected_id or self.current_id()
            all_instances = self.store.list_instances()
            order = self.sort_combo.currentData()
            if order == "recent":
                all_instances.sort(key=lambda inst: (-inst.last_played, inst.name.casefold()))
            elif order == "favorite":
                all_instances.sort(key=lambda inst: (not inst.favorite, inst.group.casefold(), inst.name.casefold()))
            else:
                all_instances.sort(key=lambda inst: inst.name.casefold())
            self.store.settings["sort"] = order
            group, query = self.groups.currentData(), self.search.text().casefold()
            self.groups.blockSignals(True)
            self.groups.clear()
            self.groups.addItem("Все группы", None)
            for name in sorted({inst.group for inst in all_instances if inst.group}):
                self.groups.addItem(name, name)
            index = self.groups.findData(group)
            self.groups.setCurrentIndex(max(0, index))
            self.groups.blockSignals(False)
            group = self.groups.currentData()
            self.instances.blockSignals(True)
            self.instances.clear()
            self.library_grid.clear()
            for inst in all_instances:
                if (group is not None and inst.group != group) or query not in (inst.name + " " + inst.group).casefold():
                    continue
                prefix = "⬆ " if inst.id in self.update_badges else "▶ " if inst.id in self.games else "★ " if inst.favorite else ""
                detail = f"{inst.minecraft}  ·  {LOADERS[inst.loader]}"
                if inst.sync_url:
                    detail += "  ·  SYNC"
                color = THEMES[self.theme]["accent" if inst.sync_url else "muted"]
                metadata = {"name": inst.name, "detail": f"{inst.minecraft} · {LOADERS[inst.loader]}",
                            "linked": bool(inst.sync_url), "update": inst.id in self.update_badges,
                            "running": inst.id in self.games, "favorite": inst.favorite}
                item = QListWidgetItem(cube_icon(color), f"{prefix}{inst.name}\n{detail}")
                item.setData(Qt.ItemDataRole.UserRole, inst.id)
                item.setData(int(Qt.ItemDataRole.UserRole) + 1, metadata)
                item.setToolTip(inst.name + ("\nЕсть обновления у хоста" if inst.id in self.update_badges else ""))
                self.instances.addItem(item)
                tile = QListWidgetItem(item.icon(), inst.name)
                tile.setData(Qt.ItemDataRole.UserRole, inst.id)
                tile.setData(int(Qt.ItemDataRole.UserRole) + 1, metadata)
                tile.setToolTip(inst.name)
                self.library_grid.addItem(tile)
                if inst.id == selected_id:
                    self.instances.setCurrentItem(item)
            if not self.instances.currentItem() and self.instances.count():
                self.instances.setCurrentRow(0)
            self.instances.blockSignals(False)
            self.count_label.setText(f"Сборки: {self.instances.count()} / {len(all_instances)}")
            linked = sum(bool(i.sync_url) for i in all_instances)
            self.library_summary.setText(f"Сборки: {self.instances.count()} · подписки: {linked}")
            warnings = []
            if self.store.instance_errors:
                warnings.append(f"Повреждённые сборки: {len(self.store.instance_errors)}")
            if self.store.settings_error:
                warnings.append("Проверьте настройки")
            if self.accounts.load_error:
                warnings.append("Проверьте аккаунты")
            self.recovery_label.setText(" · ".join(warnings) + " · Подробности: Диагностика (F1)" if warnings else "")
            self.recovery_label.setVisible(bool(warnings))
            self.load_detail(reload_fields=reload_fields)
            if explicit:
                self.show_details()
            self.store.settings["last_instance"] = self.current_id()


        def load_detail(self, *, reload_fields: bool = True) -> None:
            inst = self.current_instance()
            reload_fields = reload_fields or (inst.id if inst else "") != self.loaded_id
            if reload_fields:
                self.flush_draft()
            self.loaded_id = inst.id if inst else ""
            if inst is None:
                self._editor_baseline = {}
            self.detail_stack.setCurrentWidget(self.details if inst else self.empty_page)
            if not inst:
                filtered = bool(self.search.text() or self.groups.currentData())
                self.empty_title.setText("Сборка не найдена" if filtered else "Всё начинается со сборки")
                self.empty_hint.setText("Попробуйте другой запрос или выберите все группы." if filtered else
                                        "Создайте свой мир или подключитесь к сборке друга.\n"
                                        "Моды, Minecraft и Java — всё в одном месте.")
            self.hero_kicker.setText(inst.group.upper() if inst and inst.group else "СБОРКА MINECRAFT")
            locked = bool(inst and self.is_locked(inst.id))
            can_edit = bool(inst) and not self.busy and not locked
            self.overview.setEnabled(bool(inst))
            self.parameters_panel.setEnabled(can_edit)
            self.title_label.setText(inst.name if inst else "Выберите сборку")
            if inst:
                playtime = f"{inst.playtime / 3600:.1f} ч" if inst.playtime >= 3600 else f"{inst.playtime / 60:.0f} мин"
                self.meta_label.setText(f"Minecraft {inst.minecraft} • {LOADERS[inst.loader]} "
                                        f"{inst.loader_version or ('авто' if inst.loader != 'vanilla' else '')} • В игре: {playtime}")
                if reload_fields:
                    self._loading_fields = True
                    self.name_field.setText(inst.name)
                    self.group_field.clear()
                    self.group_field.addItems(sorted({i.group for i in self.store.list_instances() if i.group}))
                    self.group_field.setCurrentText(inst.group)
                    self.mc_field.setCurrentText(inst.minecraft)
                    self.loader_field.blockSignals(True)
                    self.loader_field.setCurrentIndex(self.loader_field.findData(inst.loader))
                    self.loader_field.blockSignals(False)
                    self.loader_version_field.setCurrentText(inst.loader_version)
                    self.server_field.setText(inst.server)
                    self.sync_mode_field.setCurrentIndex(self.sync_mode_field.findData(inst.sync_mode))
                    self.java_field.setText(inst.java)
                    self.jvm_field.setText(inst.jvm_args)
                    self.ram_min.setValue(inst.ram_min)
                    self.ram_max.setValue(inst.ram_max)
                    self.width_field.setValue(inst.width)
                    self.height_field.setValue(inst.height)
                    self.pre_field.setText(inst.pre_command)
                    self.post_field.setText(inst.post_command)
                    self.notes_field.setPlainText(inst.notes)
                    self._editor_baseline = self.editor_values(inst)
                    self.restore_draft(inst)
                    self._loading_fields = False
                self.favorite_action.setText("Убрать из избранного" if inst.favorite else "Добавить в избранное")
                self.favorite_action.setEnabled(not self.busy)
                self.update_connection_badge(inst)
            else:
                self.meta_label.setText("Создайте свою или подключитесь к другу по ссылке.")
                self.sync_label.clear()
            version_editable = can_edit and not (inst and inst.sync_url)
            for widget in (self.mc_field, self.mc_versions_btn, self.loader_field, self.server_field):
                widget.setEnabled(version_editable)
            for widget in (self.loader_version_field, self.loader_versions_btn):
                widget.setEnabled(version_editable and bool(inst and self.loader_field.currentData() != "vanilla"))
            self.sync_mode_field.setEnabled(can_edit and bool(inst and inst.sync_url))
            self.identity_form.setRowVisible(self.sync_mode_field, bool(inst and inst.sync_url))
            self.identity_form.setRowVisible(self.disconnect_btn, bool(inst and inst.sync_url))
            self.sync_btn.setVisible(bool(inst and inst.sync_url and inst.id in self.update_badges))
            self.host_btn.setVisible(bool(inst and not inst.sync_url))
            self.more_btn.setEnabled(bool(inst))
            self.play_btn.setText("■  Остановить" if inst and inst.id in self.games else "▶  Играть")
            self.manual_sync_action.setVisible(bool(inst and inst.sync_url))
            self.manual_sync_action.setEnabled(can_edit and bool(inst and inst.sync_url))
            self.play_btn.setEnabled(bool(inst) and (not self.busy or inst.id in self.games))
            self.sync_btn.setEnabled(can_edit and bool(inst and inst.sync_url))
            self.host_btn.setEnabled(can_edit and not (inst and inst.sync_url))
            self.export_btn.setEnabled(can_edit)
            self.game_folder_btn.setEnabled(bool(inst))
            self.copy_btn.setEnabled(can_edit)
            self.delete_btn.setEnabled(can_edit and not (inst and inst.id in self.hosts))
            for panel in self.file_panels.values():
                panel.refresh(inst, locked or self.busy)
            self.update_summary(inst)
            self.mr_update_btn.setEnabled(can_edit and not (inst and inst.sync_url))
            self.mr_search_btn.setEnabled(not self.busy)
            self.modrinth_selection_changed()
            self.mr_previous.setEnabled(not self.busy and bool(self.mr_context) and self.mr_offset > 0)
            self.mr_next.setEnabled(not self.busy and bool(self.mr_context) and self.mr_more)
            if self.console_instance != (inst.id if inst else ""):
                self.console_instance = inst.id if inst else ""
                self.console.setPlainText("\n".join(self.buffers.get(inst.id, [])) if inst else "")
            self.refresh_logs()
            for widget in (self.new_btn, self.connect_btn, self.import_btn, self.accounts_btn, self.settings_btn, self.account_combo,
                           self.search, self.groups, self.sort_combo, self.instances, self.library_grid):
                widget.setEnabled(not self.busy)

        def refresh_accounts(self) -> None:
            selected = self.accounts.data.get("selected")
            self.account_combo.blockSignals(True)
            self.account_combo.clear()
            for account in self.accounts.data["accounts"]:
                self.account_combo.addItem(account["name"] + (" (офлайн)" if account["type"] == "offline" else ""), account["id"])
            if not self.account_combo.count():
                self.account_combo.addItem("Нет аккаунта", "")
            index = self.account_combo.findData(selected)
            self.account_combo.setCurrentIndex(max(0, index))
            self.account_combo.blockSignals(False)

        def account_changed(self, index: int) -> None:
            if index >= 0 and self.account_combo.itemData(index):
                self.accounts.data["selected"] = self.account_combo.itemData(index)
                self.accounts.save()

        def show_accounts(self) -> None:
            AccountsDialog(self).exec()
            self.refresh_accounts()

        def loader_changed(self, *args: Any) -> None:
            self.loader_version_field.clear()
            enabled = self.loader_field.currentData() != "vanilla"
            self.loader_version_field.setEnabled(enabled)
            self.loader_versions_btn.setEnabled(enabled)

        def save_current(self, checked: bool = False, *, notify: bool = True) -> bool:
            inst = self.current_instance()
            if not inst or self.is_locked(inst.id) or self.busy:
                return False
            values = self.editor_values(inst)
            candidate = dataclasses.replace(inst, **values)
            try:
                candidate.validate()
                parse_server(candidate.server)
                split_args(candidate.jvm_args)
                if inst.id in self.hosts and candidate.loader != "vanilla" and not candidate.loader_version:
                    raise UserError("Для активной раздачи выберите конкретную совместимую версию загрузчика.")
                if candidate.identity != inst.identity and iter_files(inst.game_dir / "saves"):
                    if not message(self, "Смена версии", "Версия игры/загрузчика меняется. Создать бэкап миров и сохранить?", question=True):
                        return False
                    backup_dialog = BackupProgressDialog(inst, self)
                    if backup_dialog.exec() != QDialog.DialogCode.Accepted:
                        return False
                if inst.sync_url and inst.sync_mode != "auto" and candidate.sync_mode == "auto":
                    if not message(self, "Автоматическая смена версий", "В этом режиме версии меняются БЕЗ подтверждения. "
                                   "Бэкап миров всё равно создаётся. Включить?", question=True):
                        return False
                self.store.update(inst.id, **values)
                self._editor_baseline = values
                self._draft_memory.pop(inst.id, None)
                (inst.directory / "draft.json").unlink(missing_ok=True)
                self.draft_timer.stop()
                self.draft_label.setText("Все параметры сохранены")
                self.discard_btn.setEnabled(False)
            except (UserError, OSError, ValueError) as exc:
                message(self, "Не удалось сохранить", str(exc))
                return False
            if notify:
                self.refresh_instances(inst.id)
                self.statusBar().showMessage("Настройки сохранены", 5000)
            return True

        def create_instance(self) -> None:
            dialog = NewInstanceDialog(self.cached_versions(), self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                inst = self.store.create(dialog.name.text(), minecraft=dialog.mc.currentText().strip(),
                                         loader=dialog.loader.currentData(), loader_version=dialog.loader_version.text().strip())
                self.search.clear()
                self.groups.setCurrentIndex(0)
                self.refresh_instances(inst.id)

        def connect_instance(self) -> None:
            dialog = ConnectDialog(self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            url, requested_name = normalize_sync_url(dialog.url.text()), dialog.name.text().strip()
            if hasattr(dialog, "alias"):
                self.store.settings["party_name"] = party_name(dialog.alias.text())
                self.store.save_settings()
            for existing in self.store.list_instances():
                if existing.sync_url == url:
                    self.search.clear()
                    self.groups.setCurrentIndex(0)
                    self.refresh_instances(existing.id)
                    self.party_monitor.refresh()
                    self.statusBar().showMessage("Вы уже в этой пати. Приглашение сохранено; соединение восстановится автоматически.", 8000)
                    return

            def work(progress: Progress, cancel: threading.Event) -> Instance:
                progress("Подключение к хосту…", 0, 0)
                with BoundedSession() as session:
                    manifest = validate_manifest(fetch_json(session, url + "/manifest.json"))
                check_cancel(cancel)
                inst = self.store.create(requested_name or manifest["name"], minecraft=manifest["minecraft"],
                                         loader=manifest["loader"], loader_version=manifest["loader_version"], sync_url=url)
                # Keep the subscription if the first download fails, so it can be retried.
                return sync_instance(self.store, inst.id, progress=progress, cancel=cancel).instance

            def done(inst: Instance) -> None:
                self.search.clear()
                self.groups.setCurrentIndex(0)
                self.refresh_instances(inst.id)
            self.run_task("Подключение к сборке", work, done)

        def copy_instance(self) -> None:
            inst = self.current_instance()
            if not inst or self.is_locked(inst.id) or not self.save_current(notify=False):
                return
            inst = self.store.load(inst.id)
            name, ok = QInputDialog.getText(self, "Копия сборки", "Название (копия будет независимой от хоста)",
                                           text=inst.name + " — копия")
            if ok:
                self.run_task("Копирование сборки", lambda p, c: self.store.copy_instance(inst, name),
                              lambda new: self.refresh_instances(new.id), inst.id)

        def delete_instance(self) -> None:
            inst = self.current_instance()
            if not inst or self.is_locked(inst.id) or inst.id in self.hosts:
                return
            if message(self, "Удалить сборку целиком?", inst.name +
                       "\nБудут удалены её файлы, миры и локальные бэкапы. Экспортируйте важные данные заранее.", question=True):
                self.run_task("Удаление сборки", lambda p, c: self.store.delete(inst), lambda _: self.refresh_instances(), inst.id)

        def import_instance(self) -> None:
            source, _ = QFileDialog.getOpenFileName(self, "Импорт сборки", filter="Сборки (*.mrpack *.zip)")
            if source and message(self, "Доверие сборке", "Моды содержат исполняемый код. Вы доверяете источнику архива?", question=True):
                self.run_task("Импорт сборки", lambda p, c: import_pack(self.store, source, progress=p, cancel=c),
                              lambda inst: self.refresh_instances(inst.id))

        def export_instance(self) -> None:
            inst = self.current_instance()
            if not inst or not self.save_current(notify=False):
                return
            inst = self.store.load(inst.id)
            destination, selected_filter = QFileDialog.getSaveFileName(self, "Экспорт сборки", inst.name + ".zip",
                                                                       "MCSync ZIP (*.zip);;Modrinth pack (*.mrpack)")
            if not destination:
                return
            mrpack = "mrpack" in selected_filter or destination.lower().endswith(".mrpack")
            if not Path(destination).suffix:
                destination += ".mrpack" if mrpack else ".zip"
            worlds = message(self, "Миры в архиве", "Включить миры (saves) в экспорт?", question=True)
            self.run_task("Экспорт сборки", lambda p, c: export_pack(inst, destination, mrpack=mrpack,
                          include_worlds=worlds, progress=p, cancel=c),
                          lambda path: self.statusBar().showMessage("Архив: " + str(path), 15000), inst.id)

        def change_invitation(self) -> None:
            inst = self.current_instance()
            if not inst or not inst.sync_url or self.busy or self.is_locked(inst.id):
                return
            dialog = ConnectDialog(self)
            dialog.setWindowTitle("Заменить приглашение — сборка сохранится")
            dialog.url.setText(inst.sync_url)
            dialog.name.setText(inst.name)
            dialog.name.setEnabled(False)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            try:
                url = normalize_sync_url(dialog.url.text())
                alias = party_name(dialog.alias.text())
                self.store.settings["party_name"] = alias
                self.store.save_settings()
                self.store.update(inst.id, sync_url=url)
            except (UserError, OSError) as exc:
                message(self, "Приглашение не сохранено", redact(str(exc)))
                return
            if self.network_enabled:
                self.party_monitor.forget(inst)
            for mapping in (self.party_states, self.sync_checks):
                mapping.pop(inst.id, None)
            self.update_badges.discard(inst.id)
            self.party_monitor.refresh()
            self.load_detail(reload_fields=False)
            self.statusBar().showMessage("Приглашение заменено. Файлы и миры сохранены; версии проверятся с подтверждением перед игрой.", 10000)

        def disconnect_instance(self) -> None:
            inst = self.current_instance()
            if inst and not self.is_locked(inst.id) and message(self, "Отсоединить от хоста?", "Файлы сохранятся. "
                    "Версии и моды снова можно будет менять вручную.", question=True):
                self.party_monitor.forget(inst)
                self.party_states.pop(inst.id, None)
                self.sync_checks.pop(inst.id, None)
                self.store.update(inst.id, sync_url="", last_sync_rev="")
                (inst.directory / "sync_state.json").unlink(missing_ok=True)
                (inst.directory / "manifest_cache.json").unlink(missing_ok=True)
                self.update_badges.discard(inst.id)
                self.refresh_instances(inst.id)

        def show_host(self) -> None:
            inst = self.current_instance()
            if inst and self.save_current(notify=False):
                HostDialog(self, self.store.load(inst.id)).exec()
                self.load_detail()

        def open_game_folder(self) -> None:
            inst = self.current_instance()
            if inst:
                open_path(inst.game_dir)

        def open_backups(self) -> None:
            inst = self.current_instance()
            if inst:
                path = inst.directory / "backups"
                path.mkdir(exist_ok=True)
                open_path(path)

        def fetch_mc_versions(self) -> None:
            def work(progress: Progress, cancel: threading.Event) -> list[str]:
                with BoundedSession() as session:
                    manifest = fetch_json(session, "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")
                check_cancel(cancel)
                releases = [v["id"] for v in manifest["versions"] if v["type"] == "release"]
                snapshots = [v["id"] for v in manifest["versions"] if v["type"] == "snapshot"]
                versions = releases + snapshots
                atomic_json(self.store.root / "mc_versions.json", versions)
                return versions

            previous = self.mc_field.currentText()

            def done(versions: list[str]) -> None:
                self.mc_field.clear()
                self.mc_field.addItems(versions)
                self.mc_field.setCurrentText(previous)
                self.statusBar().showMessage("Список версий обновлён (релизы, затем снапшоты).", 8000)
            self.run_task("Список Minecraft", work, done)

        def fetch_loader_versions(self) -> None:
            inst = self.current_instance()
            if not inst:
                return
            candidate = dataclasses.replace(inst, minecraft=self.mc_field.currentText().strip(),
                                             loader=self.loader_field.currentData(), loader_version="")
            try:
                candidate.validate()
            except UserError as exc:
                message(self, "Версии загрузчика", str(exc))
                return
            if candidate.loader == "vanilla":
                return

            def work(progress: Progress, cancel: threading.Event) -> list[str]:
                loader = loader_backend(candidate.loader)
                versions = loader.get_loader_versions(candidate.minecraft, False)
                if candidate.loader == "forge":
                    versions.sort(key=lambda v: tuple(int(x) for x in re.findall(r"\d+", v)), reverse=True)
                check_cancel(cancel)
                if not versions:
                    raise UserError("Нет совместимых версий загрузчика.")
                return versions

            def done(versions: list[str]) -> None:
                self.mc_field.setCurrentText(candidate.minecraft)
                self.loader_field.blockSignals(True)
                self.loader_field.setCurrentIndex(self.loader_field.findData(candidate.loader))
                self.loader_field.blockSignals(False)
                self.loader_version_field.clear()
                self.loader_version_field.addItems(versions)
                self.loader_version_field.setCurrentIndex(0)
                self.loader_version_field.setEnabled(True)
                self.loader_versions_btn.setEnabled(True)
                self.statusBar().showMessage("Выберите версию и сохраните настройки.", 8000)
            self.run_task("Версии загрузчика", work, done)

        def pick_java(self) -> None:
            path, _ = QFileDialog.getOpenFileName(self, "Java executable", filter="Java (java java.exe javaw.exe);;Все файлы (*)")
            if path:
                self.java_field.setText(path)

        def find_java(self) -> None:
            def done(versions: list[dict[str, Any]]) -> None:
                if not versions:
                    message(self, "Java", "Системная Java не найдена. Оставьте поле пустым для автоустановки.")
                    return
                names = [f"Java {v['version']} — {v['java_path']}" for v in versions]
                selected, ok = QInputDialog.getItem(self, "Java", "Выберите Java", names, editable=False)
                if ok:
                    self.java_field.setText(versions[names.index(selected)]["java_path"])
            self.run_task("Поиск Java", lambda p, c: launcher_lib().java_utils.find_system_java_versions_information(), done)

        def repair_install(self) -> None:
            inst = self.current_instance()
            if inst and self.save_current(notify=False):
                self.run_task("Проверка установки", lambda p, c: ensure_install(self.store, self.store.load(inst.id),
                              repair=True, progress=p, cancel=c), lambda _: self.refresh_instances(inst.id), inst.id)

        def sync_now(self) -> None:
            inst = self.current_instance()
            if not inst or not inst.sync_url or not self.save_current(notify=False):
                return

            def work(progress: Progress, cancel: threading.Event) -> SyncResult:
                return sync_instance(self.store, inst.id, confirm=lambda i, p: self.wait_confirmation(i, p, cancel),
                                     progress=progress, cancel=cancel)

            def done(result: SyncResult) -> None:
                self.sync_checks[inst.id] = {"online": not result.offline, "changed": False, "checked_at": time.time()}
                self.update_badges.discard(inst.id)
                self.refresh_instances(inst.id)
                self.statusBar().showMessage(result.message, 15000)
            self.run_task("Синхронизация", work, done, inst.id)

        def launch(self) -> None:
            inst = self.current_instance()
            if not inst:
                return
            if inst.id in self.games:
                self.games[inst.id].stop()
                self.statusBar().showMessage("Остановка игры…", 5000)
                return
            if not self.save_current(notify=False):
                return
            if self.accounts.selected() is None:
                self.show_accounts()
                if self.accounts.selected() is None:
                    return

            def work(progress: Progress, cancel: threading.Event) -> tuple[Instance, list[str], dict[str, Any], str]:
                current = self.store.load(inst.id)
                sync_message = ""
                if current.sync_url:
                    result = sync_instance(self.store, current.id, allow_offline=True,
                                           confirm=lambda i, p: self.wait_confirmation(i, p, cancel),
                                           progress=progress, cancel=cancel)
                    current, sync_message = result.instance, result.message
                progress("Проверка аккаунта…", 0, 0)
                account = launch_account(self.accounts, self.store)
                check_cancel(cancel)
                current, version, java = ensure_install(self.store, current, progress=progress, cancel=cancel)
                command = minecraft_command(self.store, current, version, java, account)
                check_cancel(cancel)
                return current, command, account, sync_message

            def done(result: tuple[Instance, list[str], dict[str, Any], str]) -> None:
                current, command, account, sync_message = result
                session = GameSession(current, command, account,
                                      lambda text: self.bridge.game_output.emit(current.id, text),
                                      lambda code, elapsed, error: self.bridge.game_finished.emit(current.id, code, elapsed, error))
                self.store.update(current.id, last_played=time.time())
                self.games[current.id] = session
                self.buffers.setdefault(current.id, [])
                if sync_message:
                    self.on_game_output(current.id, sync_message)
                self.update_badges.discard(current.id)
                session.thread.start()
                self.refresh_instances(current.id)
                self.tabs.setCurrentWidget(self.console)
                self.statusBar().showMessage("Minecraft запущен. Лаунчер можно свернуть.", 8000)
            self.run_task("Подготовка запуска", work, done, inst.id)

        @Slot(str, str)
        def on_game_output(self, instance_id: str, text: str) -> None:
            buffer = self.buffers.setdefault(instance_id, [])
            buffer.append(text)
            if len(buffer) > 5000:
                del buffer[: len(buffer) - 5000]
            if self.current_id() == instance_id:
                self.console.appendPlainText(text)

        @Slot(str, int, float, str)
        def on_game_finished(self, instance_id: str, code: int, elapsed: float, error: str) -> None:
            session = self.games.pop(instance_id, None)
            try:
                current = self.store.load(instance_id)
                self.store.update(instance_id, playtime=current.playtime + elapsed)
            except (UserError, OSError) as exc:
                LOG.warning("Время игры не записано: %s", redact(str(exc)))
            self.on_game_output(instance_id, error if error else f"Игра завершена. Код: {code}; время: {elapsed / 60:.1f} мин.")
            self.refresh_instances(reload_fields=False)
            if (error or code != 0) and not self.closing and not (session and session.cancel.is_set()):
                message(self, "Игра завершилась с ошибкой", error or f"Код выхода {code}. Откройте вкладки «Консоль» и «Логи».")

        def invalidate_modrinth_pages(self, *args: Any) -> None:
            self.mr_context, self.mr_offset, self.mr_more = None, 0, False
            self.mr_previous.setEnabled(False)
            self.mr_next.setEnabled(False)

        def change_modrinth_page(self, direction: int) -> None:
            if not self.busy and self.mr_context:
                offset = self.mr_offset + direction * 30
                if offset >= 0:
                    self.search_modrinth(offset=offset, context=self.mr_context)

        def search_modrinth(self, *, offset: int = 0, context: tuple | None = None) -> None:
            query, kind, inst = context or (self.mr_query.text(), self.mr_type.currentData(),
                                            self.current_instance() if self.mr_filter.isChecked() else None)

            def work(progress: Progress, cancel: threading.Event) -> list[dict[str, Any]]:
                with ModrinthClient() as client:
                    hits = client.search(query, kind, inst, offset=offset)
                check_cancel(cancel)
                return hits

            def done(hits: list[dict[str, Any]]) -> None:
                self.mr_context, self.mr_offset, self.mr_more = (query, kind, inst), offset, len(hits) == 30
                self.mr_results.clear()
                for hit in hits:
                    item = QListWidgetItem(hit["title"] + "\n" + hit.get("description", "")[:170])
                    item.setData(Qt.ItemDataRole.UserRole, hit)
                    item.setToolTip(hit.get("description", ""))
                    self.mr_results.addItem(item)
                target = f" · {inst.minecraft} / {LOADERS[inst.loader]}" if inst else " · все версии"
                self.mr_page_label.setText((f"Результаты {offset + 1}–{offset + len(hits)}" if hits else "Ничего не найдено") + target)
                self.mr_previous.setEnabled(offset > 0)
                self.mr_next.setEnabled(self.mr_more)
                self.modrinth_selection_changed()
            self.run_task("Поиск Modrinth", work, done)

        def modrinth_selection_changed(self, *args: Any) -> None:
            item, inst = self.mr_results.currentItem(), self.current_instance()
            data = item.data(Qt.ItemDataRole.UserRole) if item else {}
            eligible = bool(data and (data.get("project_type") == "modpack" or
                            (inst and not inst.sync_url and not self.is_locked(inst.id))))
            self.mr_install_btn.setEnabled(not self.busy and eligible)

        def install_selected_modrinth(self) -> None:
            item = self.mr_results.currentItem()
            if not item:
                return
            hit, inst = item.data(Qt.ItemDataRole.UserRole), self.current_instance()
            if hit["project_type"] == "modpack":
                if not message(self, "Установить сборку?", hit["title"] +
                               "\nБудет создана новая сборка. Вы доверяете модам из этого проекта?", question=True):
                    return
                filtered = inst if self.mr_filter.isChecked() else None
                self.run_task("Установка Modrinth-сборки", lambda p, c: install_modrinth_pack(self.store,
                              hit["project_id"], filtered, progress=p, cancel=c),
                              lambda new: self.refresh_instances(new.id))
            elif inst and not self.is_locked(inst.id) and not inst.sync_url:
                if not self.save_current(notify=False):
                    return
                inst = self.store.load(inst.id)
                if message(self, "Установить проект?", hit["title"] + "\nБудут установлены обязательные зависимости.", question=True):
                    self.run_task("Установка Modrinth", lambda p, c: install_modrinth(inst, hit["project_id"], progress=p, cancel=c),
                                  lambda titles: self.statusBar().showMessage("Установлены: " + ", ".join(titles), 15000), inst.id)
            else:
                message(self, "Modrinth", "Выберите локальную сборку. Моды подписки устанавливает хост.")

        def update_mods(self) -> None:
            inst = self.current_instance()
            if inst and not inst.sync_url and not self.is_locked(inst.id):
                self.run_task("Обновление модов", lambda p, c: update_modrinth(inst, progress=p, cancel=c),
                              lambda titles: self.statusBar().showMessage("Обновлены: " + ", ".join(titles) if titles else
                              "Совместимых обновлений для известных Modrinth-проектов нет.", 15000), inst.id)

        def refresh_logs(self) -> None:
            inst = self.current_instance()
            self.logs_combo.blockSignals(True)
            previous = self.logs_combo.currentData()
            self.logs_combo.clear()
            if inst:
                launcher = inst.directory / "launcher.log"
                if launcher.exists():
                    self.logs_combo.addItem("launcher.log", str(launcher))
                for folder in ("logs", "crash-reports"):
                    for relative, path in reversed(iter_files(inst.game_dir / folder)):
                        if path.suffix in (".log", ".txt"):
                            self.logs_combo.addItem(folder + "/" + relative, str(path))
            index = self.logs_combo.findData(previous)
            self.logs_combo.setCurrentIndex(max(0, index))
            self.logs_combo.blockSignals(False)
            self.show_log()

        def show_log(self, *args: Any) -> None:
            value = self.logs_combo.currentData()
            self.log_view.clear()
            if not value:
                return
            path = Path(value)
            try:
                with path.open("rb") as stream:
                    size = path.stat().st_size
                    stream.seek(max(0, size - 1024**2))
                    text = stream.read(1024**2).decode("utf-8", errors="replace")
                for account in self.accounts.data["accounts"]:
                    for key in ("access_token", "refresh_token"):
                        token = account.get(key)
                        if token:
                            text = text.replace(token, "[токен скрыт]")
                self.log_view.setPlainText(redact(text))
            except OSError as exc:
                self.log_view.setPlainText(str(exc))

        def run_task(self, title: str, function: Callable, done: Callable | None = None, instance_id: str = "") -> None:
            if self.busy:
                self.statusBar().showMessage("Сначала завершите текущую операцию.", 5000)
                return
            self.task_number += 1
            task_id = self.task_number
            cancel = threading.Event()
            self.task = {"id": task_id, "cancel": cancel, "done": done, "instance_id": instance_id}
            self.busy = True
            self.task_label.setText(title + "…")
            self.progress_bar.setRange(0, 0)
            self.progress_bar.show()
            self.cancel_btn.show()
            self.load_detail(reload_fields=False)

            def work() -> None:
                try:
                    result = function(lambda text, value=0, maximum=0:
                                      self.bridge.progress.emit(task_id, text, value, maximum), cancel)
                    self.bridge.task_done.emit(task_id, result, "")
                except Cancelled as exc:
                    self.bridge.task_done.emit(task_id, None, "cancel:" + str(exc))
                except Exception as exc:
                    LOG.error("%s: %s", title, redact(str(exc)))
                    self.bridge.task_done.emit(task_id, None, redact(str(exc)) or type(exc).__name__)
            threading.Thread(target=work, name=f"MCSync-task-{task_id}", daemon=True).start()

        @Slot(int, str, object, object)
        def task_progress(self, task_id: int, text: str, value: int, maximum: int) -> None:
            if not self.task or self.task["id"] != task_id:
                return
            self.task_label.setText(redact(text))
            if maximum > 0:
                self.progress_bar.setRange(0, 1000)
                self.progress_bar.setValue(max(0, min(1000, int(value / maximum * 1000))))
            else:
                self.progress_bar.setRange(0, 0)

        @Slot(int, object, str)
        def task_done(self, task_id: int, result: Any, error: str) -> None:
            if not self.task or self.task["id"] != task_id:
                return
            callback = self.task["done"]
            self.task, self.busy = None, False
            self.progress_bar.hide()
            self.cancel_btn.hide()
            self.refresh_instances(reload_fields=False)
            self.party_monitor.refresh()
            if error.startswith("cancel:"):
                self.task_label.setText(error[7:])
            elif error:
                self.task_label.setText("Операция не завершена")
                message(self, "Ошибка", error)
            else:
                self.task_label.setText("Готово")
                if callback:
                    try:
                        callback(result)
                    except Exception as exc:
                        message(self, "Ошибка интерфейса", str(exc))

        def cancel_task(self) -> None:
            if self.task:
                self.task["cancel"].set()
                self.task_label.setText("Отмена… (ожидание завершения текущего запроса)")

        def wait_confirmation(self, inst: Instance, plan: SyncPlan, cancel: threading.Event) -> tuple[bool, bool]:
            request = Confirmation()
            self.bridge.confirm_sync.emit(inst, plan, request)
            while not request.event.wait(0.2):
                check_cancel(cancel)
                if self.closing:
                    raise Cancelled("Лаунчер закрывается.")
            check_cancel(cancel)
            return request.accepted, request.backup

        @Slot(object, object, object)
        def on_confirm_sync(self, inst: Instance, plan: SyncPlan, request: Confirmation) -> None:
            try:
                if self.closing or (self.task and self.task["cancel"].is_set()):
                    return
                dialog = SyncConfirmDialog(inst, plan, self)
                request.accepted = dialog.exec() == QDialog.DialogCode.Accepted
                request.backup = dialog.backup.isChecked()
            finally:
                request.event.set()

        def update_connection_badge(self, inst: Instance) -> None:
            state = self.sync_checks.get(inst.id, {})
            pending = inst.id in self.update_badges
            if inst.sync_url:
                offline = state.get("online") is False
                self.sync_label.setText("Хост недоступен" if offline else "↑ Есть обновление" if pending else
                                        ("● Хост в сети" if state.get("supported") is False else "● В пати") if state.get("online") else "Подключаемся…")
                status = "pending" if pending or offline else "linked"
                self.sync_label.setToolTip("Проверки каждые 10 с. Переподключение автоматическое; установленная сборка доступна офлайн." if offline else
                                          "Обновления установятся перед игрой. Подтверждение смены версии сохранено.")
            elif inst.id in self.hosts:
                self.sync_label.setText("● Пати открыта")
                self.sync_label.setToolTip("Приглашение постоянно, друзья подключаются автоматически. Для связи нужен открытый MCSync.")
                status = "linked"
            else:
                self.sync_label.setText("Своя сборка")
                self.sync_label.setToolTip("Создайте пати и пригласите друзей одной постоянной ссылкой.")
                status = "local"
            self.sync_label.setProperty("status", status)
            self.sync_label.setProperty("connected", bool(inst.id in self.hosts or state.get("online") is True))
            self.sync_label.style().unpolish(self.sync_label)
            self.sync_label.style().polish(self.sync_label)
            if not self.accounts.data.get("accounts"):
                text = "Первый шаг: добавьте аккаунт вверху. Затем нажмите «Играть» — Java и Minecraft установятся сами."
            elif inst.sync_url:
                text = "Вы в одной пати. Просто нажмите «Играть» — связь и обновления проверяются за вас."
            else:
                text = "Играть одному — «Играть». Вместе — «Пригласить друзей», отправьте ссылку один раз."
            self.flow_hint.setText(text)

        def refresh_party_state(self) -> None:
            if self.closing:
                return
            self.party_monitor.selected = self.current_id()
            states = self.party_monitor.snapshot()
            for inst in self.store.list_instances():
                activity = "playing" if inst.id in self.games else "updating" if self.task and self.task["instance_id"] == inst.id else "launcher"
                self.party_monitor.set_activity(inst.id, activity)
                if inst.id in self.hosts:
                    self.hosts[inst.id].party_state = activity
                state = states.get(inst.id)
                expected_source = hashlib.sha256(inst.sync_url.encode()).hexdigest() if inst.sync_url else ""
                for mapping in (self.party_states, self.sync_checks):
                    cached = mapping.get(inst.id, {})
                    if cached.get("source") and cached["source"] != expected_source:
                        mapping.pop(inst.id, None)
                        self.update_badges.discard(inst.id)
                if not state or not inst.sync_url:
                    continue
                if state.get("source") != expected_source:
                    continue  # Ignore late responses from a removed or changed invitation.
                if state.get("checked_at", time.time()) < inst.last_sync_at <= time.time():
                    continue
                self.party_states[inst.id] = state
                self.sync_checks[inst.id] = state
                revision = (state.get("room") or {}).get("rev")
                changed = revision != inst.last_sync_rev if revision else state.get("changed")
                if changed is True:
                    self.update_badges.add(inst.id)
                elif changed is False:
                    self.update_badges.discard(inst.id)
            inst = self.current_instance()
            if inst:
                self.update_connection_badge(inst)
                self.sync_btn.setVisible(bool(inst.sync_url and inst.id in self.update_badges))
                self.party_panel.refresh(inst)

        def resume_parties(self) -> None:
            if self.closing or not self.network_enabled:
                return
            if self.busy:
                QTimer.singleShot(2000, self.resume_parties)
                return
            pending = False
            for inst in self.store.list_instances():
                if inst.sync_url or inst.id in self.hosts:
                    continue
                try:
                    settings = read_json(inst.directory / "host_settings.json", {})
                    pending = pending or (isinstance(settings, dict) and settings.get("auto_start") is True)
                except (UserError, OSError) as exc:
                    self.host_errors[inst.id] = redact(str(exc))
            if not pending:
                self.refresh_party_state()
                return

            def work(progress: Progress, cancel: threading.Event):
                progress("Восстанавливаем вашу пати…", 0, 0)
                return resume_saved_hosts(self.store, cancel=cancel, skip=set(self.hosts))

            def done(result):
                hosts, errors = result
                self.hosts.update(hosts)
                self.host_errors.update(errors)
                self.load_detail(reload_fields=False)
            self.run_task("Восстановление пати", work, done)

        def check_updates(self) -> None:
            if self.network_enabled and not self.closing:
                self.party_monitor.refresh()

        @Slot(object)
        def on_update_check(self, result: dict[str, Any]) -> None:
            self.checking = False
            for instance_id, changed in result.items():
                if isinstance(changed, dict):
                    self.sync_checks[instance_id] = changed
                    changed = changed.get("changed")
                    if changed is None:
                        continue
                if changed:
                    self.update_badges.add(instance_id)
                else:
                    self.update_badges.discard(instance_id)
            if not self.busy:
                self.refresh_instances(reload_fields=False)

        def closeEvent(self, event: Any) -> None:
            if self.busy:
                message(self, "Операция ещё выполняется", "Отмените операцию и дождитесь завершения перед закрытием лаунчера.")
                event.ignore()
                return
            if self.games and not message(self, "Закрыть лаунчер?", "Запущенные игры будут остановлены. Закрыть?", question=True):
                event.ignore()
                return
            self.flush_draft()
            try:
                self.store.save_settings()
            except (UserError, OSError) as exc:
                LOG.warning("Настройки окна не сохранены: %s", redact(str(exc)))
            self.closing = True
            self.update_timer.stop()
            self.party_monitor.stop()
            for host in self.hosts.values():
                host.stop()
            for instance_id, game in list(self.games.items()):
                game.stop()
                game.thread.join(timeout=6)
                # Queued finished signals are drained while the window still exists.
            QApplication.processEvents()
            event.accept()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MCSync — Minecraft launcher with pack synchronization")
    parser.add_argument("--data-dir", type=Path, help="Override the private data directory")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    parser.add_argument("--theme", choices=list(THEMES), help="Override appearance for this session")
    parser.add_argument("--layout", choices=list(LAYOUTS), help="Override interface layout for this session")
    parser.add_argument("--diagnose", action="store_true", help="Print an offline diagnostic report, without starting Qt")
    parser.add_argument("--report-path", type=Path, help="Write --diagnose JSON to this file")
    parser.add_argument("--smoke-test", action="store_true", help="Create/show the GUI, then exit without network calls")
    args = parser.parse_args(argv)
    if args.report_path and not args.diagnose:
        parser.error("--report-path requires --diagnose")
    if args.diagnose:
        try:
            report = diagnostic_report(Store(args.data_dir or default_home()))
            if args.report_path:
                atomic_json(args.report_path, report)
            if sys.stdout is not None:
                print(json_bytes(report).decode("utf-8"))
            return 0 if all(c["ok"] for c in report["checks"]) else 1
        except (UserError, OSError) as exc:
            if sys.stderr is not None:
                print(redact(str(exc)), file=sys.stderr)
            return 1
    if not QT_AVAILABLE:
        error = "Не удалось загрузить PySide6: " + QT_IMPORT_ERROR + "\nУстановите requirements.txt; на Linux нужны системные библиотеки Qt (см. README)."
        if sys.platform == "win32" and not args.smoke_test:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, error, APP_NAME, 16)
        else:
            print(error, file=sys.stderr)
        return 1
    app = QApplication([sys.argv[0]])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setWindowIcon(cube_icon())
    try:
        check_launcher_library()
        store = Store(args.data_dir or default_home())
        session_lock = QLockFile(str(store.root / "launcher.lock"))
        session_lock.setStaleLockTime(30_000)
        if not session_lock.tryLock(0):
            raise UserError("MCSync уже открыт для этой папки данных. Перейдите к существующему окну. "
                            "Для независимого лаунчера используйте другой --data-dir.")
        from logging.handlers import RotatingFileHandler
        handler = RotatingFileHandler(store.root / "mcsync.log", maxBytes=2 * 1024**2, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        LOG.setLevel(logging.INFO)
        LOG.addHandler(handler)
        recovered = recover_transactions(store)
        window = MainWindow(store, network_enabled=not args.smoke_test, theme=args.theme, layout=args.layout)
        if recovered:
            window.statusBar().showMessage(f"Восстановлено незавершённых операций: {recovered}", 15000)
    except Exception as exc:
        if args.smoke_test:
            print(redact(str(exc)), file=sys.stderr)
        else:
            message(None, "Не удалось открыть MCSync", str(exc))
        return 1

    def handle_exception(exc_type: Any, value: BaseException, tb: Any) -> None:
        import traceback
        text = redact("".join(traceback.format_exception(exc_type, value, tb)))
        LOG.error("%s", text)
        if args.smoke_test:
            app.exit(1)
        else:
            message(window, "Ошибка MCSync", str(value) + "\nПодробности: mcsync.log в папке данных.")
    sys.excepthook = handle_exception
    window.show()
    if args.smoke_test:
        QTimer.singleShot(350, app.quit)
    try:
        return app.exec()
    finally:
        window.flush_draft()
        session_lock.unlock()
        handler.close()
        LOG.removeHandler(handler)


if __name__ == "__main__":
    raise SystemExit(main())
