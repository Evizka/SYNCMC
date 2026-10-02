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
import json
import logging
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
APP_VERSION = "0.1.0"
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
    return re.sub(r"(https?://[^/\s]+/)[A-Za-z0-9_\-]{16,}(?=/|[\s'\"),]|$)",
                  r"\1[токен скрыт]", str(text))


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
        if not isinstance(self.playtime, (int, float)) or self.playtime < 0:
            raise UserError("Некорректное время в игре.")
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
        self.settings = {"client_id": "", "default_ram": 4096}
        saved = read_json(self.root / "settings.json", {})
        if not isinstance(saved, dict):
            raise UserError("Некорректный settings.json.")
        self.settings.update(saved)

    def instance_lock(self, instance_id: str) -> threading.RLock:
        with self.lock:
            return self._locks.setdefault(instance_id, threading.RLock())

    def save_settings(self) -> None:
        with self.lock:
            atomic_json(self.root / "settings.json", self.settings)

    def load(self, instance_id: str) -> Instance:
        if not re.fullmatch(r"[a-f0-9]{32}", instance_id):
            raise UserError("Некорректный ID сборки.")
        directory = safe_join(self.instances_dir, instance_id)
        value = read_json(directory / "instance.json")
        if not isinstance(value, dict) or value.get("id") != instance_id:
            raise UserError(f"Не удалось прочитать сборку {instance_id}.")
        fields = {f.name for f in dataclasses.fields(Instance)} - {"directory"}
        inst = Instance(**{k: v for k, v in value.items() if k in fields}, directory=directory)
        inst.validate()
        return inst

    def list_instances(self) -> list[Instance]:
        result = []
        for directory in sorted(self.instances_dir.iterdir()):
            if directory.is_dir() and re.fullmatch(r"[a-f0-9]{32}", directory.name):
                result.append(self.load(directory.name))
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
                                   last_sync_rev="", playtime=0, created_at=time.time())
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


def backup_worlds(inst: Instance, world: str | None = None) -> Path | None:
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
            for relative, path in files:
                archive.write(path, f"{world}/{relative}" if world else relative)
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


def launcher_lib() -> Any:
    with LIB_LOCK:
        lib = importlib.import_module("minecraft_launcher_lib")
        facade = LibraryRequests()
        for name, module in list(sys.modules.items()):
            if name.startswith("minecraft_launcher_lib") and getattr(module, "requests", None) is requests:
                module.requests = facade
        return lib


def resolve_loader_version(inst: Instance) -> str:
    if inst.loader == "vanilla":
        return ""
    if inst.loader_version:
        return version_id(inst.loader_version)
    loader = launcher_lib().mod_loader.get_mod_loader(inst.loader)
    # Forge's library adapter may return oldest-first; sort its numeric builds.
    versions = loader.get_loader_versions(inst.minecraft, True)
    if not versions:
        versions = loader.get_loader_versions(inst.minecraft, False)
    if not versions:
        raise UserError(f"{LOADERS[inst.loader]} не поддерживает Minecraft {inst.minecraft}.")
    if inst.loader == "forge":
        versions.sort(key=lambda v: tuple(int(x) for x in re.findall(r"\d+", v)), reverse=True)
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
            backup_worlds(inst)
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
        updated.validate()
        state = {entry["path"]: entry["sha1"] for entry in m["files"]}
        transaction.commit(replacements, plan.deletions,
                           {"sync_state.json": state, "instance.json": updated.to_dict()},
                           plan.expected, cancel)
    progress("Сборка синхронизирована", len(plan.downloads), len(plan.downloads))
    return updated


class SyncHost:
    """Read-only bearer-token HTTP server; only manifest-listed files are reachable."""
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

    def manifest(self, force: bool = False) -> dict[str, Any]:
        with self._manifest_lock, self.store.instance_lock(self.instance_id):
            if not force and self._cached and time.monotonic() - self._cached_at < 1:
                return copy.deepcopy(self._cached)
            inst = self.store.load(self.instance_id)
            if inst.loader != "vanilla" and not inst.loader_version:
                raise UserError("Сначала закрепите конкретную версию загрузчика (кнопка «Версии»).")
            files = []
            for folder in self.folders:
                for relative, path in iter_files(inst.game_dir / folder):
                    name = f"{folder}/{relative}"
                    if any(fnmatch.fnmatchcase(name, mask) or fnmatch.fnmatchcase(relative, mask)
                           for mask in self.excludes):
                        continue
                    files.append({"path": name, "sha1": sha1_file(path), "size": path.stat().st_size})
            manifest = validate_manifest({"name": inst.name, "minecraft": inst.minecraft,
                                          "loader": inst.loader, "loader_version": inst.loader_version,
                                          "server": inst.server, "strict": self.strict,
                                          "folders": list(self.folders), "files": files})
            self._cached, self._cached_at = manifest, time.monotonic()
            return copy.deepcopy(manifest)

    def start(self, bind: str = "0.0.0.0") -> None:
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
                    if endpoint == "manifest.json":
                        self.send_payload(json_bytes(host.manifest()), "application/json; charset=utf-8", head)
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
        if cached.get("source") == source_hash:
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
        return self.get("/search", query=query, facets=json.dumps(facets), limit=30, offset=offset)["hits"]

    def versions(self, project_id: str, inst: Instance) -> list[dict[str, Any]]:
        params = {"game_versions": json.dumps([inst.minecraft])}
        project = self.get(f"/project/{quote(project_id, safe='')}")
        if inst.loader != "vanilla" and project.get("project_type") in ("mod", "modpack"):
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
        self.data = read_json(self.path, {"selected": "", "accounts": []})
        if not isinstance(self.data, dict) or not isinstance(self.data.get("accounts"), list):
            raise UserError("Некорректный accounts.json.")

    def save(self) -> None:
        with self.lock:
            atomic_json(self.path, self.data)
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
        if (not isinstance(account.get("id"), str) or not re.fullmatch(r"[a-fA-F0-9]{32}", account["id"])
                or not isinstance(account.get("name"), str) or not account["name"]
                or account.get("type") not in ("offline", "microsoft")):
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
        if not re.fullmatch(r"[a-fA-F0-9\-]{36}", client_id.strip()):
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


def java_major_version(executable: str) -> int:
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
        port = str(parsed.port or 25565)
    except ValueError as exc:
        raise UserError("Некорректный адрес/порт Minecraft-сервера.") from exc
    if not parsed.hostname or parsed.path or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise UserError("Нужен адрес сервера вида play.example.org:25565.")
    return parsed.hostname, port


def ensure_install(store: Store, inst: Instance, *, repair: bool = False,
                   progress: Progress = no_progress, cancel: threading.Event | None = None) -> tuple[Instance, str, str]:
    lib = launcher_lib()
    with INSTALL_LOCK:
        check_cancel(cancel)
        concrete = resolve_loader_version(inst)
        if inst.loader_version != concrete:
            inst = store.update(inst.id, loader_version=concrete)
        installed_version = inst.minecraft if inst.loader == "vanilla" else lib.mod_loader.get_mod_loader(
            inst.loader).get_installed_version(inst.minecraft, concrete)
        version_id(installed_version)
        marker_path = inst.directory / "installed.json"
        marker = read_json(marker_path, {})
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
        java = inst.java.strip()
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
        if (repair or not ready) and inst.loader != "vanilla":
            check_cancel(cancel)
            progress(f"Установка {LOADERS[inst.loader]} {concrete}…", 0, 0)
            installed_version = lib.mod_loader.get_mod_loader(inst.loader).install(
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
        return redact(text.replace(token, "[токен скрыт]") if token else text)

    def stop(self) -> None:
        self.cancel.set()
        process = self.process
        if process and process.poll() is None:
            with contextlib.suppress(OSError):
                process.terminate()
            threading.Thread(target=self._kill_later, args=(process,), daemon=True).start()

    @staticmethod
    def _kill_later(process: subprocess.Popen) -> None:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(OSError):
                process.kill()

    def run_process(self, command: list[str] | str, log: Any, *, shell: bool = False) -> int:
        check_cancel(self.cancel)
        env = os.environ.copy()
        env["MCSYNC_INSTANCE_DIR"] = str(self.inst.game_dir)
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(command, cwd=self.inst.game_dir, env=env, shell=shell,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace", creationflags=flags)
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
            with (self.inst.directory / "launcher.log").open("a", encoding="utf-8") as log:
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
    from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal, Slot
    from PySide6.QtGui import QColor, QDesktopServices, QIcon, QImage, QPainter, QPixmap, QPolygon
    from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
                                  QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                                  QHBoxLayout, QInputDialog, QLabel,
                                  QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                                  QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                                  QScrollArea, QSpinBox, QSplitter, QTabWidget, QVBoxLayout,
                                  QWidget)
    QT_AVAILABLE = True
except ImportError as exc:
    QT_AVAILABLE, QT_IMPORT_ERROR = False, str(exc)


if QT_AVAILABLE:
    STYLE = """
    QWidget { background: #101722; color: #e8edf6; font-size: 13px; }
    QMainWindow, QDialog { background: #101722; }
    QFrame#card { background: #172130; border: 1px solid #273449; border-radius: 10px; }
    QLabel { background: transparent; }
    QLabel#brand { font-size: 24px; font-weight: 700; color: #65dfb7; }
    QLabel#title { font-size: 23px; font-weight: 600; }
    QLabel#muted { color: #a0aec3; }
    QLabel#warning { color: #ffc775; }
    QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {
        background: #172130; border: 1px solid #33435b; border-radius: 6px; padding: 7px;
        selection-background-color: #245d50;
    }
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border-color: #65dfb7; }
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: #7e8ca1; border-color: #273449; }
    QPushButton { background: #25334a; border: 1px solid #33435b; border-radius: 6px; padding: 8px 12px; }
    QPushButton:hover { background: #31445f; border-color: #57718f; }
    QPushButton:pressed { background: #1c293d; }
    QPushButton:disabled { color: #65748a; background: #1b2636; border-color: #273449; }
    QPushButton#play { background: #65dfb7; color: #10271f; font-weight: 700; border: none; padding: 12px 23px; }
    QPushButton#play:hover { background: #89eacd; }
    QPushButton#play:disabled { background: #32554a; color: #92b3a8; }
    QPushButton#danger { color: #ff9b9b; }
    QListWidget { background: #131d2b; border: 1px solid #273449; border-radius: 8px; outline: none; }
    QListWidget::item { padding: 11px; border-bottom: 1px solid #202d40; }
    QListWidget::item:selected { background: #234039; color: #eafff7; border-left: 3px solid #65dfb7; }
    QListWidget::item:hover:!selected { background: #1c2a3d; }
    QTabWidget::pane { border: 1px solid #273449; border-radius: 6px; top: -1px; }
    QTabBar::tab { background: #172130; padding: 10px 12px; border-bottom: 2px solid transparent; }
    QTabBar::tab:selected { background: #1b293b; border-bottom-color: #65dfb7; }
    QTabBar::tab:disabled { color: #65748a; }
    QScrollArea { border: none; }
    QProgressBar { border: 1px solid #33435b; border-radius: 5px; text-align: center; background: #172130; }
    QProgressBar::chunk { background: #3cae8d; border-radius: 4px; }
    QCheckBox { padding: 4px; }
    QSplitter::handle { background: #202d40; }
    QToolTip { background: #25334a; color: #ffffff; border: 1px solid #57718f; padding: 4px; }
    """

    def label(text: str = "", kind: str = "", wrap: bool = False) -> QLabel:
        result = QLabel(text)
        result.setTextFormat(Qt.TextFormat.PlainText)
        result.setWordWrap(wrap)
        if kind:
            result.setObjectName(kind)
        return result

    def button(text: str, callback: Callable, kind: str = "") -> QPushButton:
        result = QPushButton(text)
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
        box.setWindowTitle(title)
        box.setTextFormat(Qt.TextFormat.PlainText)
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
            layout.addWidget(label("Одна ссылка — одна сборка", "title"))
            layout.addWidget(label("Друг запускает «Раздать сборку» и отправляет ссылку. "
                                   "При запуске лаунчер проверит моды и версии за вас.", "muted", True))
            self.url = QLineEdit()
            self.url.setPlaceholderText("http://адрес:25589/токен")
            self.name = QLineEdit()
            self.name.setPlaceholderText("Название (необязательно)")
            layout.addWidget(self.url)
            layout.addWidget(self.name)
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
            self.hint = label("Перетащите сюда файлы или нажмите «Добавить».", "muted", True)
            layout.addWidget(self.hint)
            self.list = DropList()
            self.list.setAccessibleName("Файлы сборки")
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
            self.list.clear()
            if inst:
                root = inst.game_dir / self.folder
                if self.folder == "saves":
                    if root.exists():
                        for path in sorted(root.iterdir()):
                            if path.is_dir() and not path.is_symlink():
                                item = QListWidgetItem(path.name)
                                item.setData(Qt.ItemDataRole.UserRole, path.name)
                                self.list.addItem(item)
                else:
                    for relative, path in iter_files(root):
                        enabled = not relative.endswith(".disabled")
                        item = QListWidgetItem(f"{'●' if enabled else '○'}  {relative}   ·   {human_size(path.stat().st_size)}")
                        item.setData(Qt.ItemDataRole.UserRole, relative)
                        if not enabled:
                            item.setForeground(QColor("#7e8ca1"))
                        self.list.addItem(item)
            managed = bool(inst and inst.sync_url and self.folder != "saves")
            self.hint.setText("Этими файлами управляет хост. Изменения модов вносите у него." if managed else
                              "Перетащите папку/ZIP мира сюда." if self.folder == "saves" else
                              "Перетащите сюда .jar / .zip. Выключенные файлы имеют суффикс .disabled.")
            for widget in (self.add_btn, self.toggle_btn, self.delete_btn):
                widget.setEnabled(bool(inst) and not locked and not managed)
            self.backup_btn.setEnabled(bool(inst) and not locked)
            self.folder_btn.setEnabled(bool(inst))
            self.list.setAcceptDrops(bool(inst) and not locked and not managed)

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
            inst = self.main.current_instance()
            if not inst or inst.sync_url or self.main.is_locked(inst.id):
                return
            try:
                for relative in self.selected():
                    source = safe_join(inst.game_dir / self.folder, relative)
                    name = relative.removesuffix(".disabled") if relative.endswith(".disabled") else relative + ".disabled"
                    target = safe_join(inst.game_dir / self.folder, name)
                    if target.exists():
                        raise UserError(f"Уже существует {name}; сначала разрешите конфликт.")
                    os.replace(source, target)
                self.refresh(inst)
            except (OSError, UserError) as exc:
                message(self, "Не удалось переключить файл", str(exc))

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
                        backup_worlds(inst, relative)
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
                    path = backup_worlds(inst, world)
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

    class HostDialog(QDialog):
        def __init__(self, main: MainWindow, inst: Instance):
            super().__init__(main)
            self.main, self.inst = main, inst
            self.setWindowTitle("Раздать сборку друзьям")
            self.resize(570, 570)
            settings = read_json(inst.directory / "host_settings.json", {})
            layout = QVBoxLayout(self)
            layout.addWidget(label("Хост сборки", "title"))
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
            self.folders = {}
            folder_row = QHBoxLayout()
            for folder in SYNC_FOLDERS:
                box = QCheckBox(folder)
                box.setChecked(folder in settings.get("folders", SYNC_FOLDERS))
                self.folders[folder] = box
                folder_row.addWidget(box)
            layout.addLayout(folder_row)
            self.strict = QCheckBox("Строгий режим: удалять у друзей лишние .jar и .jar.disabled")
            self.strict.setChecked(settings.get("strict", True))
            layout.addWidget(self.strict)
            layout.addWidget(label("Исключения (маски fnmatch, одна на строку)"))
            self.excludes = QPlainTextEdit("\n".join(settings.get("excludes", ["*.part", "*.tmp"])))
            self.excludes.setMaximumHeight(95)
            layout.addWidget(self.excludes)
            layout.addWidget(label("HTTP не шифрует данные. Проверьте config на пароли/токены. "
                                   "Для интернета нужен VPN или настройка доступа к этому порту; NAT автоматически не обходится.", "warning", True))
            self.url_field = QLineEdit()
            self.url_field.setReadOnly(True)
            self.url_field.setPlaceholderText("После запуска здесь появится ссылка")
            layout.addWidget(self.url_field)
            self.start_btn = button("Запустить раздачу", self.start_host, "play")
            self.stop_btn = button("Остановить", self.stop_host, "danger")
            self.copy_btn = button("Копировать ссылку", self.copy_url)
            layout.addLayout(row(self.start_btn, self.stop_btn, self.copy_btn))
            self.state_label = label("", "muted", True)
            layout.addWidget(self.state_label)
            self.refresh()

        @staticmethod
        def local_ip() -> str:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.connect(("8.8.8.8", 80))
                    return sock.getsockname()[0]
            except OSError:
                return "192.168.1.100"

        def refresh(self) -> None:
            host = self.main.hosts.get(self.inst.id)
            active = host is not None
            self.start_btn.setEnabled(not active and not self.main.busy)
            self.stop_btn.setEnabled(active)
            self.copy_btn.setEnabled(active)
            for widget in (self.address, self.port, self.strict, self.excludes, *self.folders.values()):
                widget.setEnabled(not active)
            if host:
                self.url_field.setText(host.url(self.address.text()))
            else:
                self.url_field.clear()
            self.state_label.setText("Раздача запущена • закройте это окно и продолжайте работу." if active else "Раздача остановлена.")

        def start_host(self) -> None:
            settings = {"address": self.address.text().strip(), "port": self.port.value(),
                        "strict": self.strict.isChecked(),
                        "folders": [p for p, box in self.folders.items() if box.isChecked()],
                        "excludes": [s.strip() for s in self.excludes.toPlainText().splitlines() if s.strip()]}
            previous = read_json(self.inst.directory / "host_settings.json", {})
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
                    atomic_json(inst.directory / "host_settings.json", settings)
                except BaseException:
                    host.stop()
                    raise
                return host

            def done(host: SyncHost) -> None:
                self.main.hosts[self.inst.id] = host
                self.refresh()
                self.main.load_detail()
            self.main.run_task("Запуск раздачи", work, done, self.inst.id)

        def stop_host(self) -> None:
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
            canvas.fill(QColor("#172130"))
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
            self.resize(570, 380)
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
            form.addRow("Microsoft Client ID", self.client_id)
            form.addRow("RAM новых сборок", self.ram)
            layout.addLayout(form)
            layout.addWidget(label("Для Microsoft нужен ваш public-client Azure Client ID и одобрение Mojang. "
                                   "Client Secret не нужен. Сторонние ключи лаунчеров не используются.", "muted", True))
            layout.addWidget(button("Регистрация приложения: aka.ms/AppRegInfo", lambda:
                                    QDesktopServices.openUrl(QUrl("https://aka.ms/AppRegInfo"))))
            layout.addWidget(label("Данные: " + str(main.store.root), "muted", True))
            layout.addWidget(button("Открыть папку данных", lambda: open_path(main.store.root)))
            layout.addWidget(label("Независимый проект; не связан с Mojang/Microsoft или PolyMC/Prism.", "muted", True))
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
            buttons.accepted.connect(self.save)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)

        def save(self) -> None:
            self.main.store.settings.update(client_id=self.client_id.text().strip(), default_ram=self.ram.value())
            self.main.store.save_settings()
            self.accept()

    class MainWindow(QMainWindow):
        def __init__(self, store: Store, *, network_enabled: bool = True):
            super().__init__()
            self.store, self.accounts = store, Accounts(store)
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
            self.setWindowIcon(cube_icon())
            self.resize(1250, 830)
            self.setMinimumSize(980, 650)
            central = QWidget()
            self.setCentralWidget(central)
            outer = QVBoxLayout(central)
            outer.setContentsMargins(18, 14, 18, 14)
            header = QHBoxLayout()
            header.addWidget(label("MCSync", "brand"))
            header.addWidget(label("СБОРКИ ДЛЯ ДРУЗЕЙ", "muted"))
            header.addStretch()
            self.account_combo = QComboBox()
            self.account_combo.setMinimumWidth(175)
            self.account_combo.currentIndexChanged.connect(self.account_changed)
            self.accounts_btn = button("Аккаунты / скины", self.show_accounts)
            self.settings_btn = button("Настройки", lambda: SettingsDialog(self).exec())
            header.addWidget(self.account_combo)
            header.addWidget(self.accounts_btn)
            header.addWidget(self.settings_btn)
            outer.addLayout(header)
            toolbar = QHBoxLayout()
            self.new_btn = button("+ Новая сборка", self.create_instance)
            self.connect_btn = button("Подключиться по ссылке", self.connect_instance)
            self.import_btn = button("Импорт .mrpack / ZIP", self.import_instance)
            self.copy_btn = button("Копия", self.copy_instance)
            self.delete_btn = button("Удалить сборку", self.delete_instance, "danger")
            for widget in (self.new_btn, self.connect_btn, self.import_btn, self.copy_btn, self.delete_btn):
                toolbar.addWidget(widget)
            toolbar.addStretch()
            outer.addLayout(toolbar)
            splitter = QSplitter(Qt.Orientation.Horizontal)
            left = QWidget()
            left_layout = QVBoxLayout(left)
            left_layout.setContentsMargins(0, 0, 8, 0)
            self.search = QLineEdit()
            self.search.setPlaceholderText("Найти сборку…")
            self.search.setClearButtonEnabled(True)
            self.groups = QComboBox()
            self.groups.addItem("Все группы", None)
            left_layout.addWidget(self.search)
            left_layout.addWidget(self.groups)
            self.instances = QListWidget()
            self.instances.setIconSize(QSize(42, 42))
            self.instances.setAccessibleName("Сборки Minecraft")
            self.instances.currentItemChanged.connect(lambda *_: self.load_detail())
            self.instances.itemDoubleClicked.connect(lambda _: self.launch())
            left_layout.addWidget(self.instances, 1)
            self.count_label = label("", "muted")
            left_layout.addWidget(self.count_label)
            splitter.addWidget(left)
            self.details = QWidget()
            detail_layout = QVBoxLayout(self.details)
            detail_layout.setContentsMargins(8, 0, 0, 0)
            title_row = QHBoxLayout()
            title_col = QVBoxLayout()
            self.title_label = label("Выберите сборку", "title")
            self.meta_label = label("Создайте свою или подключитесь к другу по ссылке.", "muted", True)
            title_col.addWidget(self.title_label)
            title_col.addWidget(self.meta_label)
            title_row.addLayout(title_col, 1)
            self.play_btn = button("▶ Запустить", self.launch, "play")
            title_row.addWidget(self.play_btn)
            detail_layout.addLayout(title_row)
            actions = QHBoxLayout()
            self.sync_btn = button("⟳ Синхронизировать", self.sync_now)
            self.host_btn = button("Раздать сборку", self.show_host)
            self.export_btn = button("Экспорт", self.export_instance)
            self.game_folder_btn = button("Папка сборки", self.open_game_folder)
            for widget in (self.sync_btn, self.host_btn, self.export_btn, self.game_folder_btn):
                actions.addWidget(widget)
            actions.addStretch()
            detail_layout.addLayout(actions)
            self.sync_label = label("", "muted", True)
            detail_layout.addWidget(self.sync_label)
            self.tabs = QTabWidget()
            self.tabs.setDocumentMode(True)
            self.overview = self.build_overview()
            self.tabs.addTab(self.overview, "Обзор")
            self.file_panels = {}
            for folder, title in (("mods", "Моды"), ("resourcepacks", "Ресурсы"), ("shaderpacks", "Шейдеры"), ("saves", "Миры")):
                panel = FilePanel(folder, self)
                self.file_panels[folder] = panel
                self.tabs.addTab(panel, title)
            self.modrinth_tab = self.build_modrinth()
            self.tabs.addTab(self.modrinth_tab, "Modrinth")
            self.console = QPlainTextEdit()
            self.console.setReadOnly(True)
            self.console.setMaximumBlockCount(5000)
            self.console.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
            self.tabs.addTab(self.console, "Консоль")
            self.tabs.addTab(self.build_logs(), "Логи")
            detail_layout.addWidget(self.tabs, 1)
            splitter.addWidget(self.details)
            splitter.setSizes([285, 900])
            splitter.setStretchFactor(0, 0)
            splitter.setStretchFactor(1, 1)
            outer.addWidget(splitter, 1)
            task_row = QHBoxLayout()
            self.task_label = label("Готово", "muted")
            self.progress_bar = QProgressBar()
            self.progress_bar.setMaximumWidth(280)
            self.progress_bar.setRange(0, 1000)
            self.progress_bar.setValue(0)
            self.progress_bar.hide()
            self.cancel_btn = button("Отменить", self.cancel_task)
            self.cancel_btn.hide()
            task_row.addWidget(self.task_label, 1)
            task_row.addWidget(self.progress_bar)
            task_row.addWidget(self.cancel_btn)
            outer.addLayout(task_row)
            self.statusBar().showMessage("Автоустановка Java • Vanilla / Fabric / Quilt / Forge / NeoForge")
            self.search.textChanged.connect(lambda *_: self.refresh_instances(reload_fields=False))
            self.groups.currentIndexChanged.connect(lambda *_: self.refresh_instances(reload_fields=False))
            self.refresh_accounts()
            self.refresh_instances()
            self.update_timer = QTimer(self)
            self.update_timer.setInterval(90_000)
            self.update_timer.timeout.connect(self.check_updates)
            if network_enabled:
                self.update_timer.start()
                QTimer.singleShot(3000, self.check_updates)

        def cached_versions(self) -> list[str]:
            value = read_json(self.store.root / "mc_versions.json", [])
            return value if isinstance(value, list) and all(isinstance(v, str) for v in value) else []

        def build_overview(self) -> QWidget:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            content = QWidget()
            layout = QVBoxLayout(content)
            form = QFormLayout()
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            self.name_field = QLineEdit()
            self.group_field = QComboBox()
            self.group_field.setEditable(True)
            self.mc_field = QComboBox()
            self.mc_field.setEditable(True)
            self.mc_field.addItems(self.cached_versions() or ["1.21.1", "1.20.1"])
            self.loader_field = QComboBox()
            for key, title in LOADERS.items():
                self.loader_field.addItem(title, key)
            self.loader_version_field = QComboBox()
            self.loader_version_field.setEditable(True)
            self.loader_version_field.lineEdit().setPlaceholderText("Пусто = авто")
            self.loader_field.currentIndexChanged.connect(self.loader_changed)
            self.mc_versions_btn = button("Обновить список", self.fetch_mc_versions)
            self.loader_versions_btn = button("Совместимые версии", self.fetch_loader_versions)
            form.addRow("Название", self.name_field)
            form.addRow("Группа", self.group_field)
            form.addRow("Minecraft", row(self.mc_field, self.mc_versions_btn))
            form.addRow("Загрузчик", self.loader_field)
            form.addRow("Версия загрузчика", row(self.loader_version_field, self.loader_versions_btn))
            self.server_field = QLineEdit()
            self.server_field.setPlaceholderText("play.example.org:25565 (необязательно)")
            form.addRow("Автовход на сервер", self.server_field)
            self.sync_mode_field = QComboBox()
            for text, value in (("Спрашивать о любых изменениях", "ask"),
                                ("Спрашивать только при смене версий", "version"),
                                ("Автоматически (включая смену версий)", "auto")):
                self.sync_mode_field.addItem(text, value)
            form.addRow("Синхронизация", self.sync_mode_field)
            self.disconnect_btn = button("Отсоединить от хоста", self.disconnect_instance)
            form.addRow("", self.disconnect_btn)
            self.ram_min = QSpinBox()
            self.ram_max = QSpinBox()
            for spin in (self.ram_min, self.ram_max):
                spin.setRange(256, 131072)
                spin.setSingleStep(256)
                spin.setSuffix(" МБ")
            form.addRow("RAM минимум / максимум", row(self.ram_min, self.ram_max))
            self.java_field = QLineEdit()
            self.java_field.setPlaceholderText("Авто — Java от Mojang")
            self.java_pick_btn = button("Путь", self.pick_java)
            self.java_find_btn = button("Найти Java", self.find_java)
            form.addRow("Java executable", row(self.java_field, self.java_pick_btn, self.java_find_btn))
            self.jvm_field = QLineEdit()
            self.jvm_field.setPlaceholderText("Дополнительные JVM-аргументы")
            form.addRow("JVM", self.jvm_field)
            self.width_field, self.height_field = QSpinBox(), QSpinBox()
            self.width_field.setRange(320, 16384)
            self.height_field.setRange(240, 16384)
            form.addRow("Окно (ширина / высота)", row(self.width_field, self.height_field))
            self.pre_field, self.post_field = QLineEdit(), QLineEdit()
            self.pre_field.setPlaceholderText("Локальная shell-команда (не импортируется и не синхронизируется)")
            self.post_field.setPlaceholderText("Локальная shell-команда после выхода")
            form.addRow("Перед запуском", self.pre_field)
            form.addRow("После выхода", self.post_field)
            layout.addLayout(form)
            layout.addWidget(label("Заметки"))
            self.notes_field = QPlainTextEdit()
            self.notes_field.setMaximumHeight(130)
            layout.addWidget(self.notes_field)
            self.save_btn = button("Сохранить настройки", self.save_current)
            self.repair_btn = button("Проверить / переустановить игру", self.repair_install)
            layout.addLayout(row(self.save_btn, self.repair_btn))
            layout.addWidget(label("В режиме «Автоматически» смена версии проходит без диалога, но с бэкапом миров. "
                                   "Для обычного использования рекомендуется подтверждение версий.", "muted", True))
            layout.addStretch()
            scroll.setWidget(content)
            return scroll

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
            layout.addWidget(self.mr_results, 1)
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
            selected_id = selected_id or self.current_id()
            all_instances = self.store.list_instances()
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
            for inst in all_instances:
                if (group is not None and inst.group != group) or query not in (inst.name + " " + inst.group).casefold():
                    continue
                prefix = "⬆ " if inst.id in self.update_badges else "▶ " if inst.id in self.games else ""
                detail = f"{inst.minecraft}  ·  {LOADERS[inst.loader]}"
                if inst.sync_url:
                    detail += "  ·  SYNC"
                item = QListWidgetItem(cube_icon("#65dfb7" if inst.sync_url else "#80aaf5"), f"{prefix}{inst.name}\n{detail}")
                item.setData(Qt.ItemDataRole.UserRole, inst.id)
                item.setToolTip(inst.name + ("\nЕсть обновления у хоста" if inst.id in self.update_badges else ""))
                self.instances.addItem(item)
                if inst.id == selected_id:
                    self.instances.setCurrentItem(item)
            if not self.instances.currentItem() and self.instances.count():
                self.instances.setCurrentRow(0)
            self.instances.blockSignals(False)
            self.count_label.setText(f"Сборки: {self.instances.count()} / {len(all_instances)}")
            self.load_detail(reload_fields=reload_fields)

        def load_detail(self, *, reload_fields: bool = True) -> None:
            inst = self.current_instance()
            reload_fields = reload_fields or (inst.id if inst else "") != self.loaded_id
            self.loaded_id = inst.id if inst else ""
            locked = bool(inst and self.is_locked(inst.id))
            can_edit = bool(inst) and not self.busy and not locked
            self.overview.setEnabled(can_edit)
            self.title_label.setText(inst.name if inst else "Выберите сборку")
            if inst:
                playtime = f"{inst.playtime / 3600:.1f} ч" if inst.playtime >= 3600 else f"{inst.playtime / 60:.0f} мин"
                self.meta_label.setText(f"Minecraft {inst.minecraft} • {LOADERS[inst.loader]} "
                                        f"{inst.loader_version or ('авто' if inst.loader != 'vanilla' else '')} • В игре: {playtime}")
                if reload_fields:
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
                if inst.sync_url:
                    self.sync_label.setText("⬆ У хоста есть обновления." if inst.id in self.update_badges else
                                            "Подключено к хосту • версии и состав модов управляются автоматически.")
                elif inst.id in self.hosts:
                    self.sync_label.setText("Раздача активна • изменения файлов и настроек попадут к друзьям при проверке.")
                else:
                    self.sync_label.setText("Локальная сборка • можно раздать друзьям одной ссылкой.")
            else:
                self.meta_label.setText("Создайте свою или подключитесь к другу по ссылке.")
                self.sync_label.clear()
            version_editable = can_edit and not (inst and inst.sync_url)
            for widget in (self.mc_field, self.mc_versions_btn, self.loader_field, self.server_field):
                widget.setEnabled(version_editable)
            for widget in (self.loader_version_field, self.loader_versions_btn):
                widget.setEnabled(version_editable and bool(inst and self.loader_field.currentData() != "vanilla"))
            self.sync_mode_field.setEnabled(can_edit and bool(inst and inst.sync_url))
            self.disconnect_btn.setVisible(bool(inst and inst.sync_url))
            self.play_btn.setText("■ Остановить" if inst and inst.id in self.games else "▶ Запустить")
            self.play_btn.setEnabled(bool(inst) and (not self.busy or inst.id in self.games))
            self.sync_btn.setEnabled(can_edit and bool(inst and inst.sync_url))
            self.host_btn.setEnabled(can_edit and not (inst and inst.sync_url))
            self.export_btn.setEnabled(can_edit)
            self.game_folder_btn.setEnabled(bool(inst))
            self.copy_btn.setEnabled(can_edit)
            self.delete_btn.setEnabled(can_edit and not (inst and inst.id in self.hosts))
            for panel in self.file_panels.values():
                panel.refresh(inst, locked or self.busy)
            self.mr_update_btn.setEnabled(can_edit and not (inst and inst.sync_url))
            self.mr_search_btn.setEnabled(not self.busy)
            self.mr_install_btn.setEnabled(not self.busy and not locked)
            self.console.setPlainText("\n".join(self.buffers.get(inst.id, [])) if inst else "")
            self.refresh_logs()
            for widget in (self.new_btn, self.connect_btn, self.import_btn, self.accounts_btn, self.settings_btn, self.account_combo):
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
                    backup_worlds(inst)
                if inst.sync_url and inst.sync_mode != "auto" and candidate.sync_mode == "auto":
                    if not message(self, "Автоматическая смена версий", "В этом режиме версии меняются БЕЗ подтверждения. "
                                   "Бэкап миров всё равно создаётся. Включить?", question=True):
                        return False
                self.store.update(inst.id, **values)
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
            if not inst or self.is_locked(inst.id):
                return
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

        def disconnect_instance(self) -> None:
            inst = self.current_instance()
            if inst and not self.is_locked(inst.id) and message(self, "Отсоединить от хоста?", "Файлы сохранятся. "
                    "Версии и моды снова можно будет менять вручную.", question=True):
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
                loader = launcher_lib().mod_loader.get_mod_loader(candidate.loader)
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
            current = self.store.load(instance_id)
            self.store.update(instance_id, playtime=current.playtime + elapsed)
            self.on_game_output(instance_id, error if error else f"Игра завершена. Код: {code}; время: {elapsed / 60:.1f} мин.")
            self.refresh_instances()
            if (error or code != 0) and not self.closing and not (session and session.cancel.is_set()):
                message(self, "Игра завершилась с ошибкой", error or f"Код выхода {code}. Откройте вкладки «Консоль» и «Логи».")

        def search_modrinth(self) -> None:
            query, kind = self.mr_query.text(), self.mr_type.currentData()
            inst = self.current_instance() if self.mr_filter.isChecked() else None

            def work(progress: Progress, cancel: threading.Event) -> list[dict[str, Any]]:
                with ModrinthClient() as client:
                    hits = client.search(query, kind, inst)
                check_cancel(cancel)
                return hits

            def done(hits: list[dict[str, Any]]) -> None:
                self.mr_results.clear()
                for hit in hits:
                    item = QListWidgetItem(hit["title"] + "\n" + hit.get("description", "")[:170])
                    item.setData(Qt.ItemDataRole.UserRole, hit)
                    self.mr_results.addItem(item)
                self.statusBar().showMessage(f"Найдено: {len(hits)} (первые 30 результатов)", 8000)
            self.run_task("Поиск Modrinth", work, done)

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

        def check_updates(self) -> None:
            if not self.network_enabled or self.checking or self.busy or self.closing:
                return
            instances = [inst for inst in self.store.list_instances() if inst.sync_url and inst.id not in self.games]
            if not instances:
                return
            self.checking = True

            def work() -> None:
                result = {}
                for inst in instances:
                    try:
                        manifest, cached = fetch_manifest(inst, allow_cache=False)
                        result[inst.id] = manifest["rev"] != inst.last_sync_rev
                    except (requests.RequestException, UserError, OSError):
                        # A periodic check must never block launch with an error dialog.
                        continue
                self.bridge.update_check_done.emit(result)
            threading.Thread(target=work, name="MCSync-update-check", daemon=True).start()

        @Slot(object)
        def on_update_check(self, result: dict[str, bool]) -> None:
            self.checking = False
            for instance_id, changed in result.items():
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
            self.closing = True
            self.update_timer.stop()
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
    parser.add_argument("--smoke-test", action="store_true", help="Create/show the GUI, then exit without network calls")
    args = parser.parse_args(argv)
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
        store = Store(args.data_dir or default_home())
        from logging.handlers import RotatingFileHandler
        handler = RotatingFileHandler(store.root / "mcsync.log", maxBytes=2 * 1024**2, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        LOG.setLevel(logging.INFO)
        LOG.addHandler(handler)
        recovered = recover_transactions(store)
        window = MainWindow(store, network_enabled=not args.smoke_test)
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
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
