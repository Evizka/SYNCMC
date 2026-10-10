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
import ctypes
import copy
import dataclasses
import fnmatch
import functools
import hashlib
import hmac
import importlib
import importlib.metadata
import ipaddress
import json
import logging
import math
import signal
import os
import queue
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
import zlib
from collections import OrderedDict
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import requests

APP_NAME = "MCSync"
APP_VERSION = "0.7.6"
LAUNCHER_LIB_VERSION = "8.0"
DEFAULT_THEME = "aurora"
INSTANCE_ICONS = {
    "portal": "Портал",
    "sword": "Меч",
    "pickaxe": "Кирка",
    "torch": "Факел",
    "chest": "Сундук",
    "creeper": "Крипер",
    "book": "Книга",
}
THEMES = {
    "forest": {"name": "Forest", "description": "Тёплый лесной интерфейс, мягкие акценты и спокойная игровая атмосфера.",
               "bg": "#101b17", "sidebar": "#15231d", "surface": "#192b22", "raised": "#24392d",
               "border": "#354d3e", "text": "#edf3e9", "muted": "#a8bdae", "accent": "#aad795",
               "hover": "#c1e9ad", "soft": "#304c34", "on_accent": "#182a1b", "warning": "#e8c080",
               "danger": "#f3a69d", "hero": "#294633", "art": "#89ab72", "art_dark": "#456f51"},
    "nord": {"name": "Nord", "description": "Холодный сине-серый интерфейс: хорошо подходит для компактного рабочего режима.",
             "bg": "#17212c", "sidebar": "#1d2b38", "surface": "#233442", "raised": "#2d4050",
             "border": "#3d5466", "text": "#edf3f8", "muted": "#acbfce", "accent": "#93cedf",
             "hover": "#b0e2ed", "soft": "#294b5c", "on_accent": "#152e3a", "warning": "#edc789",
             "danger": "#f2a5af", "hero": "#2b4556", "art": "#86afc4", "art_dark": "#486f8a"},
    "ember": {"name": "Ember", "description": "Угольный фон, медные акценты и пиксельный закат — более тёплый характер.",
              "bg": "#1c1816", "sidebar": "#251f1b", "surface": "#2c2420", "raised": "#382d26",
              "border": "#4e3d32", "text": "#f6ede4", "muted": "#c6b29e", "accent": "#edb980",
              "hover": "#f5cea1", "soft": "#4a3626", "on_accent": "#312218", "warning": "#efce92",
              "danger": "#f2a49b", "hero": "#4a3528", "art": "#bd8d5d", "art_dark": "#785638"},
    "graphite": {"name": "Graphite", "description": "Спокойный графит, зелёные акценты и компактная библиотека.",
                 "bg": "#111416", "sidebar": "#191d20", "surface": "#1c2125", "raised": "#242a2f",
                 "border": "#30373d", "text": "#f0f3f4", "muted": "#a1adb4", "accent": "#a4e88e",
                 "hover": "#bdf6ab", "soft": "#293b2a", "on_accent": "#172519", "warning": "#efbd79",
                 "danger": "#f39898", "hero": "#24362b", "art": "#73a96a", "art_dark": "#345b45"},
    "aurora": {"name": "Aurora Soft", "description": "Мягкий ночной фиолетовый, приглушённые лавандовые акценты и спокойный игровой характер.",
               "bg": "#12131f", "sidebar": "#171927", "surface": "#1d2130", "raised": "#272c3e",
               "border": "#323a50", "text": "#eceefa", "muted": "#97a2ba", "accent": "#a99ae0",
               "hover": "#c4b8ee", "soft": "#38314f", "on_accent": "#241a36", "warning": "#e6bd88",
               "danger": "#e8a3b6", "hero": "#262439", "art": "#7a74ae", "art_dark": "#363c5c"},
    "ocean": {"name": "Ocean", "description": "Глубокий тёмно-синий, бирюзовые акценты и спокойная морская глубина.",
              "bg": "#0b1622", "sidebar": "#0f1d2b", "surface": "#132433", "raised": "#1a3040",
              "border": "#27414f", "text": "#e8f2f6", "muted": "#9ab4c0", "accent": "#5fc9db",
              "hover": "#8adfea", "soft": "#1c3d4a", "on_accent": "#0a2029", "warning": "#e8c789",
              "danger": "#f0a49e", "hero": "#142c3c", "art": "#5fa4b8", "art_dark": "#2b5a72"},
    "cloud": {"name": "Cloud", "description": "Светлый небесный фон, воздушные голубые акценты и мягкие облака.",
              "bg": "#eef3f8", "sidebar": "#f8fafc", "surface": "#ffffff", "raised": "#f2f6fa",
              "border": "#d3dfe9", "text": "#1d2b3a", "muted": "#65768a", "accent": "#5b93d9",
              "hover": "#79a9e6", "soft": "#e4edf9", "on_accent": "#ffffff", "warning": "#895714",
              "danger": "#b73648", "hero": "#dde9f6", "art": "#a8c5e6", "art_dark": "#7ba3d0"},
    "paper": {"name": "Paper", "description": "Светлый рабочий стол, синие акценты и минимум визуального шума.",
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


LIGHT_THEMES = ("paper", "cloud")


def success_color(key: Any) -> str:
    """Success/health green shared by the stylesheet and painted badges; dark green reads on light themes."""
    return "#23764c" if theme_key(key) in LIGHT_THEMES else "#7ee7b5"


def language_key(value: Any) -> str:
    """Normalize the saved UI language; Russian remains the safe legacy default."""
    return value if isinstance(value, str) and value in {"ru", "en"} else "ru"


_UI_LANGUAGE = "ru"
_UI_TRANSLATIONS: dict[str, str] | None = None
_UI_TEMPLATE_TRANSLATIONS: list[tuple[re.Pattern[str], str]] | None = None
_UI_PARTIAL_TRANSLATIONS: list[tuple[str, str]] | None = None


def set_ui_language(value: Any) -> str:
    """Set the language used by subsequent UI text updates and return its key."""
    global _UI_LANGUAGE
    _UI_LANGUAGE = language_key(value)
    return _UI_LANGUAGE


def translate_ui_text(value: Any, language: str | None = None, *, partial: bool = False) -> Any:
    """Translate exact UI copy; partial phrase matching is reserved for controlled status/error text."""
    if not isinstance(value, str):
        return value
    if language_key(language if language is not None else _UI_LANGUAGE) != "en":
        return value
    global _UI_TRANSLATIONS, _UI_TEMPLATE_TRANSLATIONS, _UI_PARTIAL_TRANSLATIONS
    if _UI_TRANSLATIONS is None:
        source = Path(__file__).resolve().parent / "assets" / "locale" / "en.json"
        try:
            loaded = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        pairs = ({key: text for key, text in loaded.items()
                  if isinstance(key, str) and isinstance(text, str)} if isinstance(loaded, dict) else {})
        _UI_TRANSLATIONS = {key: text for key, text in pairs.items() if "{VAR}" not in key}
        templates = []
        for key, text in pairs.items():
            if "{VAR}" not in key:
                continue
            source_parts = key.split("{VAR}")
            if text.count("{VAR}") != len(source_parts) - 1:
                continue
            regex = "^" + "([\\s\\S]*?)".join(re.escape(part) for part in source_parts) + "$"
            templates.append((re.compile(regex), text))
        _UI_TEMPLATE_TRANSLATIONS = sorted(templates, key=lambda item: len(item[0].pattern), reverse=True)
        _UI_PARTIAL_TRANSLATIONS = sorted(
            ((key, text) for key, text in _UI_TRANSLATIONS.items()
             if len(key.strip()) >= 4 and re.search(r"[А-Яа-яЁё]", key)),
            key=lambda item: len(item[0]), reverse=True)
    translated = _UI_TRANSLATIONS.get(value)
    if translated is not None:
        return translated
    for pattern, template in _UI_TEMPLATE_TRANSLATIONS or ():
        match = pattern.fullmatch(value)
        if not match:
            continue
        parts = template.split("{VAR}")
        result = [parts[0]]
        for index, captured in enumerate(match.groups()):
            result.extend((translate_ui_text(captured, language), parts[index + 1]))
        return "".join(result)
    if partial:
        translated = value
        for source, target in _UI_PARTIAL_TRANSLATIONS or ():
            if source in translated:
                translated = translated.replace(source, target)
        return translated
    return value


@functools.lru_cache(maxsize=1)
def physical_memory_mb() -> int:
    """Return the installed physical memory in MiB, with a conservative fallback."""
    total_bytes = 0
    try:
        if sys.platform == "win32":
            class MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                total_bytes = int(status.ullTotalPhys)
        elif sys.platform == "darwin":
            libc = ctypes.CDLL("libc.dylib")
            value = ctypes.c_uint64()
            length = ctypes.c_size_t(ctypes.sizeof(value))
            if libc.sysctlbyname(b"hw.memsize", ctypes.byref(value), ctypes.byref(length), None, 0) == 0:
                total_bytes = int(value.value)
        else:
            try:
                for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
                    if line.startswith("MemTotal:"):
                        total_bytes = int(line.split()[1]) * 1024
                        break
            except (OSError, ValueError, IndexError):
                pass
            if not total_bytes:
                pages = int(os.sysconf("SC_PHYS_PAGES"))
                page_size = int(os.sysconf("SC_PAGE_SIZE"))
                total_bytes = pages * page_size
    except (AttributeError, OSError, TypeError, ValueError):
        total_bytes = 0
    if total_bytes <= 0:
        return 4096
    return max(256, min(2_147_483_647, total_bytes // (1024 * 1024)))


THEME_ARTWORK = {key: f"{key}-world.jpg" for key in THEMES}


def theme_artwork_path(key: Any) -> Path:
    return Path(__file__).resolve().parent / "assets" / THEME_ARTWORK[theme_key(key)]


USER_AGENT = f"SYNCMC/{APP_VERSION} (https://github.com/Evizka/SYNCMC)"
LOADERS = {"vanilla": "Vanilla", "fabric": "Fabric", "quilt": "Quilt",
           "forge": "Forge", "neoforge": "NeoForge"}
CURSEFORGE_GAME_ID = 432
CURSEFORGE_CLASS_IDS = {"mod": 6, "resourcepack": 12, "shader": 6552}
CURSEFORGE_LOADER_IDS = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}
CATALOG_SORTS = {"downloads", "newest", "updated", "relevance"}
CURSEFORGE_SORT_FIELDS = {"relevance": 2, "downloads": 6, "updated": 3, "newest": 11}
CATALOG_ICON_HOSTS = {"cdn.modrinth.com", "media.forgecdn.net"}
MAX_CATALOG_ICON_BYTES = 2 * 1024 * 1024
MAX_CATALOG_ICON_DIMENSION = 2048
CATALOG_ICON_CACHE_LIMIT = 96
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


def validate_curseforge_api_key(value: Any, *, required: bool = False) -> str:
    """Validate a local CurseForge key without ever including it in an error message."""
    if not isinstance(value, str):
        raise UserError("Некорректный API-ключ CurseForge.")
    key = value.strip()
    if len(key) > 512 or any(not char.isascii() or not char.isprintable() for char in key):
        raise UserError("Некорректный API-ключ CurseForge.")
    if required and not key:
        raise UserError("Для CurseForge укажите свой API-ключ в Настройки → CurseForge.")
    return key


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


def merge_version_choices(catalog: Iterable[str], keep: Iterable[str]) -> list[str]:
    """Catalog order first, but a saved/custom version stays visible and selectable.

    Refreshing the Mojang catalog must never drop the version a build already uses:
    the dropdown keeps that value as its first entry even when the remote list has
    moved on or returned an incomplete result.
    """
    merged: list[str] = []
    for value in catalog or ():
        if not isinstance(value, str):
            continue
        text = value.strip()
        if text and text not in merged:
            merged.append(text)
    missing: list[str] = []
    for value in keep or ():
        if not isinstance(value, str):
            continue
        text = value.strip()
        if text and text not in merged and text not in missing:
            missing.append(text)
    return missing + merged


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


def private_party_target(value: str, *, default_port: int = 25589) -> tuple[str, int] | None:
    """Return a non-public IP target without retaining or exposing the invitation token."""
    text = value.strip()
    try:
        if "://" in text:
            parsed = urlsplit(text)
            host = parsed.hostname or ""
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        else:
            host, port = text, default_port
            if host.startswith("[") and "]" in host:
                closing = host.index("]")
                suffix = host[closing + 1:]
                host = host[1:closing]
                if suffix.startswith(":") and suffix[1:].isdigit():
                    port = int(suffix[1:])
            elif host.count(":") == 1:
                candidate, suffix = host.rsplit(":", 1)
                if suffix.isdigit():
                    host, port = candidate, int(suffix)
        address = ipaddress.ip_address(host)
    except (ValueError, TypeError):
        return None
    return None if address.is_global else (host, port)


def party_address_hint(value: str, *, default_port: int = 25589) -> str:
    target = private_party_target(value, default_port=default_port)
    if not target:
        return ""
    host, port = target
    address = ipaddress.ip_address(host)
    display_host = f"[{host}]" if ":" in host else host
    endpoint = f"{display_host}:{port}"
    if address.is_loopback:
        return (f"{endpoint} доступен только на этом компьютере. Укажите LAN/VPN-адрес хоста; "
                "для Radmin возьмите IP из списка Radmin VPN. Если вы уже в общей сети, разрешите "
                "входящий TCP-порт в брандмауэре хоста.")
    return (f"{endpoint} — локальный адрес, доступный только в той же LAN/VPN. Для друга из другой сети "
            "используйте IP хоста из общей VPN; в Radmin это IP из списка, а не домашний 192.168.x.x. "
            "Если вы уже в общей сети, разрешите входящий TCP-порт в брандмауэре хоста.")


def radmin_vpn_ipv4_from_output(output: str) -> str:
    """Read the IPv4 address from the Radmin VPN adapter section in ipconfig output."""
    current_is_radmin = False
    address_pattern = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
    for line in output.splitlines():
        if line.strip() and not line[:1].isspace() and line.rstrip().endswith(":"):
            current_is_radmin = "radmin" in line.casefold()
        if not current_is_radmin or not re.search(r"ipv4", line, re.IGNORECASE):
            continue
        for candidate in address_pattern.findall(line):
            try:
                address = ipaddress.IPv4Address(candidate)
            except ipaddress.AddressValueError:
                continue
            if not (address.is_unspecified or address.is_loopback or address.is_link_local or address.is_multicast):
                return str(address)
    return ""


def detect_radmin_vpn_ipv4() -> str:
    """Find an active Radmin VPN address on Windows without changing firewall rules."""
    if sys.platform != "win32":
        return ""
    try:
        result = subprocess.run(["ipconfig"], capture_output=True, text=True, errors="replace", timeout=3,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return radmin_vpn_ipv4_from_output(result.stdout or "")


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


def _mod_metadata_value(value: Any, limit: int = 96) -> str:
    if not isinstance(value, str):
        return ""
    value = " ".join(value.split()).strip()
    if not value or value.startswith("${") or len(value) > limit:
        return ""
    return value


def jar_mod_identity(path: Path) -> tuple[str, str]:
    """Read a small, known metadata entry from a JAR without extracting it."""
    preferred = ("fabric.mod.json", "META-INF/mods.toml", "mcmod.info", "META-INF/MANIFEST.MF")
    found_title = found_version = ""
    try:
        with zipfile.ZipFile(path) as archive:
            members = {item.filename: item for item in archive.infolist() if not item.is_dir()}
            for member in preferred:
                info = members.get(member)
                if not info or info.file_size < 1 or info.file_size > 256 * 1024:
                    continue
                with archive.open(info) as stream:
                    raw = stream.read(256 * 1024 + 1)
                if len(raw) > 256 * 1024:
                    continue
                text = raw.decode("utf-8-sig", errors="replace")
                title = version = ""
                if member in ("fabric.mod.json", "mcmod.info"):
                    try:
                        data = json.loads(text)
                    except (ValueError, TypeError):
                        continue
                    if member == "mcmod.info":
                        data = data[0] if isinstance(data, list) and data else data
                    if isinstance(data, dict):
                        title = _mod_metadata_value(data.get("name") or data.get("displayName") or data.get("id"))
                        version = _mod_metadata_value(data.get("version"))
                elif member.endswith("mods.toml"):
                    try:
                        import tomllib
                        data = tomllib.loads(text)
                        entries = data.get("mods", [])
                        first = entries[0] if isinstance(entries, list) and entries else {}
                        if isinstance(first, dict):
                            title = _mod_metadata_value(first.get("displayName") or first.get("modId"))
                            version = _mod_metadata_value(first.get("version"))
                    except (ImportError, ValueError, TypeError):
                        in_first_mod = False
                        for line in text.splitlines():
                            if line.strip() == "[[mods]]":
                                in_first_mod = not title and not version
                                continue
                            if not in_first_mod:
                                continue
                            match = re.match(r"^\s*(displayName|modId|version)\s*=\s*['\"]([^'\"\r\n]{1,96})['\"]", line)
                            if match:
                                value = _mod_metadata_value(match.group(2))
                                if match.group(1) in ("displayName", "modId") and not title:
                                    title = value
                                elif match.group(1) == "version" and not version:
                                    version = value
                else:
                    unfolded = re.sub(r"\r?\n[ \t]+", "", text)
                    fields = {}
                    for line in unfolded.splitlines():
                        key, separator, value = line.partition(":")
                        if separator:
                            fields[key.strip()] = value.strip()
                    title = _mod_metadata_value(fields.get("Implementation-Title") or fields.get("Specification-Title"))
                    version = _mod_metadata_value(fields.get("Implementation-Version") or fields.get("Specification-Version"))
                found_title = found_title or title
                found_version = found_version or version
                if found_title and found_version:
                    return found_title, found_version
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError, EOFError, NotImplementedError, zlib.error):
        pass
    return found_title, found_version


_MOD_ICON_CACHE: OrderedDict[tuple[str, int, int], Any] = OrderedDict()
_MOD_ICON_CACHE_LIMIT = 256
_MOD_ICON_MAX_BYTES = 1024 * 1024


def _jar_member_text(members: dict[str, Any], archive: zipfile.ZipFile, name: str) -> str:
    info = members.get(name)
    if not info or info.file_size < 1 or info.file_size > 256 * 1024:
        return ""
    with archive.open(info) as stream:
        raw = stream.read(256 * 1024 + 1)
    if len(raw) > 256 * 1024:
        return ""
    return raw.decode("utf-8-sig", errors="replace")


def jar_mod_icon(path: Path, size: int = 64) -> Any:
    """Decode the mod's own icon from its JAR; never extracts the archive to disk."""
    if not QT_AVAILABLE:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (str(path), stat.st_size, int(stat.st_mtime))
    if key in _MOD_ICON_CACHE:
        _MOD_ICON_CACHE.move_to_end(key)
        return _MOD_ICON_CACHE[key]
    image = _load_jar_icon(path)
    scaled = None
    if image is not None and not image.isNull():
        scaled = image.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
    _MOD_ICON_CACHE[key] = scaled
    if len(_MOD_ICON_CACHE) > _MOD_ICON_CACHE_LIMIT:
        _MOD_ICON_CACHE.popitem(last=False)
    return scaled


def _load_jar_icon(path: Path) -> Any:
    try:
        with zipfile.ZipFile(path) as archive:
            members = {item.filename: item for item in archive.infolist() if not item.is_dir()}
            wanted = []
            for member in ("fabric.mod.json", "quilt.mod.json"):
                text = _jar_member_text(members, archive, member)
                if not text:
                    continue
                try:
                    data = json.loads(text)
                except (ValueError, TypeError):
                    continue
                if isinstance(data, dict):
                    icon = _mod_metadata_value(data.get("icon"), limit=160).replace("\\", "/").lstrip("/")
                    if icon:
                        wanted.append(icon)
            text = _jar_member_text(members, archive, "META-INF/mods.toml")
            if text:
                match = re.search(r"^\s*logoFile\s*=\s*['\"]([^'\"\r\n]{1,160})['\"]", text, re.M)
                if match:
                    wanted.append(match.group(1).replace("\\", "/").lstrip("/"))
            text = _jar_member_text(members, archive, "mcmod.info")
            if text:
                try:
                    data = json.loads(text)
                except (ValueError, TypeError):
                    data = None
                data = data[0] if isinstance(data, list) and data else data
                if isinstance(data, dict):
                    logo = _mod_metadata_value(data.get("logoFile"), limit=160).replace("\\", "/").lstrip("/")
                    if logo:
                        wanted.append(logo)
            wanted.extend(("pack.png", "icon.png", "assets/icon.png", "logo.png", "META-INF/icon.png"))
            for candidate in wanted:
                info = members.get(candidate)
                if not info or not 0 < info.file_size <= _MOD_ICON_MAX_BYTES:
                    continue
                with archive.open(info) as stream:
                    raw = stream.read(_MOD_ICON_MAX_BYTES + 1)
                if len(raw) > _MOD_ICON_MAX_BYTES:
                    continue
                image = QImage()
                if image.loadFromData(raw) and not image.isNull():
                    return image
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError, EOFError, NotImplementedError, zlib.error):
        pass
    return None


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
    icon: str = "portal"
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
                   "jvm_args", "pre_command", "post_command", "server", "sync_url", "sync_mode", "last_sync_rev", "icon")
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
        if self.icon not in INSTANCE_ICONS:
            raise UserError("Неизвестная иконка сборки.")
        if not (256 <= self.ram_min <= self.ram_max <= 2_147_483_647):
            raise UserError("RAM должна быть не меньше 256 МБ; минимум не может превышать максимум.")
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
        self.settings = {"client_id": "", "curseforge_api_key": "", "default_ram": 4096, "theme": DEFAULT_THEME,
                         "layout": "comfortable", "sort": "favorite", "last_instance": "", "language": "ru"}
        try:
            saved = read_json(self.root / "settings.json", {})
            if not isinstance(saved, dict):
                raise UserError("Некорректный settings.json.")
            self.settings.update(saved)
        except UserError as exc:
            self.settings_error = str(exc)
        ram = self.settings.get("default_ram")
        ram_limit = physical_memory_mb()
        if type(ram) is not int or not 256 <= ram <= 2_147_483_647:
            self.settings["default_ram"] = min(4096, ram_limit)
            self.settings_error = self.settings_error or "Некорректная RAM в settings.json; используется безопасное значение."
        elif ram > ram_limit:
            self.settings["default_ram"] = ram_limit
            self.settings_error = self.settings_error or "Максимальная RAM ограничена установленной памятью компьютера."
        if not isinstance(self.settings.get("client_id"), str):
            self.settings["client_id"] = ""
            self.settings_error = self.settings_error or "Некорректный Client ID в settings.json."
        try:
            self.settings["curseforge_api_key"] = validate_curseforge_api_key(
                self.settings.get("curseforge_api_key", ""))
        except UserError:
            self.settings["curseforge_api_key"] = ""
            self.settings_error = self.settings_error or "Некорректный API-ключ CurseForge в settings.json."
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
        self.settings["language"] = language_key(self.settings.get("language"))
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
            for name in ("modrinth.json", "curseforge.json"):
                tracker = source.directory / name
                if tracker.exists():
                    shutil.copyfile(tracker, stage / name)
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


def quick_file_counts(root: Path) -> tuple[int, int]:
    """Count files without stat/resolve or widget creation for the build overview."""
    if root.is_symlink() or not root.exists():
        return 0, 0
    enabled = total = 0
    pending = [root]
    try:
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        total += 1
                        enabled += not entry.name.endswith(".disabled")
    except OSError:
        return 0, 0
    return enabled, total


def quick_world_count(root: Path) -> int:
    """Count world directories for the overview; detailed listing remains lazy."""
    if root.is_symlink() or not root.exists():
        return 0
    try:
        with os.scandir(root) as entries:
            return sum(entry.is_dir(follow_symlinks=False) for entry in entries if not entry.is_symlink())
    except OSError:
        return 0


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


def catalog_icon_url(value: Any) -> str:
    """Accept only HTTPS icons from the two catalog CDNs; never follow arbitrary URLs."""
    if not isinstance(value, str) or not value or len(value) > 2048:
        return ""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return ""
    host = (parsed.hostname or "").rstrip(".").casefold()
    if (parsed.scheme != "https" or host not in CATALOG_ICON_HOSTS or port not in (None, 443)
            or parsed.username or parsed.password or not parsed.path.startswith("/")):
        return ""
    return value


def fetch_catalog_icon(url: str) -> bytes:
    """Fetch a small optional catalog icon without credentials or redirecting off-CDN."""
    safe_url = catalog_icon_url(url)
    if not safe_url:
        raise UserError("Ссылка на значок каталога не прошла проверку безопасности.")
    session = BoundedSession()
    try:
        with session.get(safe_url, stream=True, allow_redirects=False, timeout=(5, 10),
                         headers={"Accept": "image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8"}) as response:
            if 300 <= response.status_code < 400:
                raise UserError("CDN значков перенаправил запрос.")
            response.raise_for_status()
            if catalog_icon_url(response.url) != safe_url:
                raise UserError("CDN значков вернул другой адрес.")
            content_type = str(response.headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
            if content_type and not content_type.startswith("image/"):
                raise UserError("CDN значков вернул не изображение.")
            data = bytearray()
            for chunk in response.iter_content(32 * 1024):
                if not chunk:
                    continue
                data.extend(chunk)
                if len(data) > MAX_CATALOG_ICON_BYTES:
                    raise UserError("Значок каталога превышает допустимый размер.")
            if not data:
                raise UserError("CDN значков вернул пустой ответ.")
            return bytes(data)
    finally:
        session.close()


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
    META_NAMES = {"instance.json", "sync_state.json", "modrinth.json", "curseforge.json"}

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


def party_failure(exc: Exception, url: str = "") -> dict[str, Any]:
    """Classify errors without exposing a bearer URL or an untrusted response body."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    network_error = isinstance(exc, (requests.Timeout, requests.ConnectionError))
    private_target = private_party_target(url) if network_error and url else None
    kind = ("invitation" if status in (401, 403) else "session" if status == 409
            else "busy" if status in (429, 502, 503, 504)
            else "private_address" if private_target else "timeout" if isinstance(exc, requests.Timeout)
            else "network" if isinstance(exc, requests.ConnectionError)
            else "protocol" if isinstance(exc, UserError) else "local" if isinstance(exc, OSError)
            else "unexpected")
    messages = {
        "invitation": "Хост отклонил приглашение. Попросите у друга действующую ссылку.",
        "session": "Хост не принял сессию. Дождитесь автоматического переподключения.",
        "busy": "Хост временно занят. MCSync повторит запрос автоматически.",
        "timeout": "Хост отвечает слишком долго. Проверка повторится автоматически.",
        "network": "Связь с хостом потеряна. Приглашение сохранено, переподключаемся.",
        "private_address": "Адрес из приглашения не маршрутизируется через интернет. Подключите оба компьютера "
                           "к одной LAN/VPN и используйте адрес хоста в этой сети (для Radmin — IP из списка "
                           "Radmin VPN, а не домашний 192.168.x.x). Если вы уже в общей сети, разрешите "
                           "входящий TCP-порт в брандмауэре хоста. MCSync не передаёт трафик через облако.",
        "protocol": "Ответ хоста несовместим или повреждён. Обновите MCSync у обоих участников.",
        "local": "Не удалось прочитать локальные настройки пати. Откройте диагностику.",
        "unexpected": "Проверка пати не завершилась. Повторим её автоматически.",
    }
    error_message = messages[kind]
    if private_target:
        host, port = private_target
        display_host = f"[{host}]" if ":" in host else host
        error_message = f"Не удаётся подключиться к {display_host}:{port}. " + error_message
    return {"error_kind": kind, "error_message": error_message, "error": redact(str(exc))[:180]}


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
                      **party_failure(exc, source), "retry_seconds": delay}
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
            raise UserError("Выберите папки для раздачи. Строгий режим доступен только вместе с папкой mods.")
        self.store, self.instance_id = store, instance_id
        self.port, self.token = port, token or secrets.token_urlsafe(24)
        if not re.fullmatch(r"[A-Za-z0-9_\-]{16,128}", self.token):
            raise UserError("Некорректный токен раздачи.")
        self.folders, self.excludes, self.strict = folders, excludes, strict
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self._lifecycle_lock = threading.RLock()
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
        with self._lifecycle_lock:
            if self.httpd is not None or self.thread is not None:
                raise UserError("Эта пати уже запущена.")
            self._start_locked(bind)

    def _start_locked(self, bind: str) -> None:
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
                self._request_registered = False
                super().setup()
                self.connection.settimeout(20)
                self.server.track_request(self.connection)
                self._request_registered = True

            def finish(self) -> None:
                try:
                    super().finish()
                finally:
                    if self._request_registered:
                        self.server.untrack_request(self.connection)
                        self._request_registered = False

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

        serving = threading.Event()

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True
            slots = threading.BoundedSemaphore(32)

            def __init__(self, *args: Any, **kwargs: Any):
                self._request_condition = threading.Condition()
                self._active_sockets: set[socket.socket] = set()
                self._closing_requests = False
                super().__init__(*args, **kwargs)

            def track_request(self, connection: socket.socket) -> None:
                with self._request_condition:
                    if not self._closing_requests:
                        self._active_sockets.add(connection)
                        return
                with contextlib.suppress(OSError):
                    connection.shutdown(socket.SHUT_RDWR)
                with contextlib.suppress(OSError):
                    connection.close()

            def untrack_request(self, connection: socket.socket) -> None:
                with self._request_condition:
                    self._active_sockets.discard(connection)
                    self._request_condition.notify_all()

            def close_active_requests(self, timeout: float = 3.0) -> None:
                with self._request_condition:
                    self._closing_requests = True
                    connections = tuple(self._active_sockets)
                for connection in connections:
                    with contextlib.suppress(OSError):
                        connection.shutdown(socket.SHUT_RDWR)
                    with contextlib.suppress(OSError):
                        connection.close()
                deadline = time.monotonic() + timeout
                with self._request_condition:
                    while self._active_sockets:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        self._request_condition.wait(remaining)

            def service_actions(self) -> None:
                serving.set()

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

        server = Server((bind, self.port), Handler)
        self.port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1},
                                  name="SyncHost", daemon=True)
        self.httpd, self.thread = server, thread
        try:
            thread.start()
            if not serving.wait(timeout=2):
                raise UserError("Не удалось запустить службу пати.")
        except BaseException:
            self.httpd = None
            self.thread = None
            server.server_close()
            if thread.is_alive():
                thread.join(timeout=3)
            raise

    def url(self, address: str) -> str:
        address = address.strip()
        if not address or re.search(r"[/\s?#@]", address):
            raise UserError("Введите IP или DNS-имя без http:// и порта.")
        if ":" in address and not address.startswith("["):
            address = f"[{address}]"
        return normalize_sync_url(f"http://{address}:{self.port}/{self.token}")

    def stop(self) -> None:
        with self._lifecycle_lock:
            server, thread = self.httpd, self.thread
            if server is None and thread is None:
                return
            try:
                if server is not None and thread is not None and thread.is_alive():
                    server.shutdown()
            finally:
                try:
                    if server is not None:
                        server.server_close()
                finally:
                    if server is not None:
                        server.close_active_requests()
                    self.httpd = None
                    self.thread = None
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=3)


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
                for key in ("name", "notes", "group", "icon", "ram_min", "ram_max", "width", "height", "server"):
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
               offset: int = 0, sort: str = "downloads") -> list[dict[str, Any]]:
        if sort not in CATALOG_SORTS:
            raise UserError("Некорректная сортировка каталога.")
        facets = [[f"project_type:{project_type}"]]
        if inst is not None:
            facets.append([f"versions:{inst.minecraft}"])
            if project_type == "mod" and inst.loader != "vanilla":
                facets.append([f"categories:{inst.loader}"])
        result = self.get("/search", query=query, facets=json.dumps(facets), limit=30,
                          offset=offset, index=sort)
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


class CurseForgeClient:
    """CurseForge Core API wrapper. The personal API key is sent only to api.curseforge.com."""
    API = "https://api.curseforge.com/v1"

    def __init__(self, api_key: str):
        self.api_key = validate_curseforge_api_key(api_key, required=True)
        self.session = BoundedSession()

    def __enter__(self) -> CurseForgeClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.session.close()

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        if not path.startswith("/") or ".." in path or "?" in path or "#" in path:
            raise UserError("Некорректный запрос CurseForge.")
        try:
            result = fetch_json(self.session, self.API + path,
                                headers={"Accept": "application/json", "x-api-key": self.api_key},
                                params=params, allow_redirects=False)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if status in (401, 403):
                raise UserError("CurseForge отклонил API-ключ. Проверьте его в Настройки → CurseForge.") from None
            if status == 429:
                raise UserError("CurseForge временно ограничил запросы. Попробуйте позже.") from None
            raise UserError(f"CurseForge вернул ошибку HTTP {status or 'неизвестно'}.") from None
        if not isinstance(result, dict) or "data" not in result:
            raise UserError("CurseForge вернул некорректный ответ API.")
        return result

    def search(self, query: str, project_type: str, inst: Instance | None,
               offset: int = 0, sort: str = "downloads") -> list[dict[str, Any]]:
        if project_type not in CURSEFORGE_CLASS_IDS:
            raise UserError("CurseForge не поддерживает этот тип проекта.")
        if sort not in CATALOG_SORTS:
            raise UserError("Некорректная сортировка каталога.")
        if not isinstance(query, str) or len(query) > 200:
            raise UserError("Слишком длинный запрос CurseForge.")
        if type(offset) is not int or not 0 <= offset <= 10_000:
            raise UserError("Некорректная страница CurseForge.")
        params: dict[str, Any] = {"gameId": CURSEFORGE_GAME_ID,
                                  "classId": CURSEFORGE_CLASS_IDS[project_type],
                                  "searchFilter": query.strip(), "sortField": CURSEFORGE_SORT_FIELDS[sort],
                                  "sortOrder": "desc", "pageSize": 30, "index": offset}
        if inst is not None:
            params["gameVersion"] = inst.minecraft
            loader_id = CURSEFORGE_LOADER_IDS.get(inst.loader) if project_type == "mod" else None
            if loader_id is not None:
                params["modLoaderType"] = loader_id
        data = self.get("/mods/search", **params)["data"]
        if not isinstance(data, list):
            raise UserError("CurseForge вернул некорректные результаты поиска.")
        hits = []
        for hit in data:
            if (not isinstance(hit, dict) or type(hit.get("id")) is not int or hit["id"] <= 0
                    or not isinstance(hit.get("name"), str) or not hit["name"].strip()
                    or not isinstance(hit.get("summary", ""), str)):
                raise UserError("CurseForge вернул некорректные результаты поиска.")
            authors = hit.get("authors", [])
            author = ", ".join(item["name"].strip() for item in authors
                                if isinstance(item, dict) and isinstance(item.get("name"), str)
                                and item["name"].strip()) if isinstance(authors, list) else ""
            logo = hit.get("logo") if isinstance(hit.get("logo"), dict) else {}
            links = hit.get("links") if isinstance(hit.get("links"), dict) else {}
            icon_url = logo.get("url", "") if isinstance(logo.get("url", ""), str) else ""
            website_url = links.get("websiteUrl", "") if isinstance(links.get("websiteUrl", ""), str) else ""
            hits.append({"provider": "curseforge", "project_id": hit["id"], "project_type": project_type,
                         "title": hit["name"], "slug": hit.get("slug", ""), "author": author,
                         "description": hit.get("summary", ""), "downloads": hit.get("downloadCount", 0),
                         "icon_url": icon_url, "website_url": website_url})
        return hits

    def latest_file(self, mod_id: int, inst: Instance, project_type: str) -> dict[str, Any]:
        if type(mod_id) is not int or mod_id <= 0 or project_type not in CURSEFORGE_CLASS_IDS:
            raise UserError("Некорректный проект CurseForge.")
        if project_type == "mod" and inst.loader == "vanilla":
            raise UserError("Для модов CurseForge сначала выберите Fabric, Quilt, Forge или NeoForge.")
        params: dict[str, Any] = {"gameVersion": inst.minecraft, "pageSize": 50, "index": 0}
        loader_id = CURSEFORGE_LOADER_IDS.get(inst.loader) if project_type == "mod" else None
        if loader_id is not None:
            params["modLoaderType"] = loader_id
        files = self.get(f"/mods/{mod_id}/files", **params)["data"]
        if not isinstance(files, list):
            raise UserError("CurseForge вернул некорректный список файлов.")
        extension = ".jar" if project_type == "mod" else ".zip"
        candidates = []
        for item in files:
            if not isinstance(item, dict) or item.get("isAvailable") is False:
                continue
            filename = item.get("fileName")
            versions = item.get("gameVersions", [])
            if (not isinstance(filename, str) or not filename.lower().endswith(extension)
                    or (isinstance(versions, list) and versions and inst.minecraft not in versions)):
                continue
            try:
                safe_name = relative_path(filename)
            except UserError:
                continue
            if "/" in safe_name or "\\" in safe_name:
                continue
            candidates.append(item)
        candidates.sort(key=lambda item: (item.get("releaseType") == 1,
                                         str(item.get("fileDate", ""))), reverse=True)
        if not candidates:
            raise UserError(f"В CurseForge нет совместимого файла для Minecraft {inst.minecraft} / {LOADERS[inst.loader]}.")
        return candidates[0]

    def download_url(self, mod_id: int, file_id: int) -> str:
        if type(mod_id) is not int or mod_id <= 0 or type(file_id) is not int or file_id <= 0:
            raise UserError("Некорректный файл CurseForge.")
        value = self.get(f"/mods/{mod_id}/files/{file_id}/download-url")["data"]
        if not isinstance(value, str):
            raise UserError("CurseForge не вернул ссылку на файл.")
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise UserError("CurseForge вернул небезопасную ссылку для скачивания.")
        return value


def curseforge_sha1(file: dict[str, Any]) -> str:
    hashes = file.get("hashes", [])
    if not isinstance(hashes, list):
        raise UserError("CurseForge не вернул контрольную сумму файла.")
    digest = next((entry.get("value", "") for entry in hashes
                   if isinstance(entry, dict) and entry.get("algo") == 1), "")
    if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{40}", digest):
        raise UserError("CurseForge не вернул корректную SHA-1.")
    return digest.lower()


def install_curseforge(inst: Instance, mod_id: int, project_type: str, api_key: str, *,
                       title: str = "", client: CurseForgeClient | None = None,
                       selected_file: dict[str, Any] | None = None, progress: Progress = no_progress,
                       cancel: threading.Event | None = None) -> list[str]:
    """Resolve required CurseForge mod dependencies, stage files, verify SHA-1, then commit."""
    if inst.sync_url:
        raise UserError("Проекты синхронизируемой сборки устанавливает хост; загрузите их в его локальной сборке.")
    if project_type not in CURSEFORGE_CLASS_IDS or type(mod_id) is not int or mod_id <= 0:
        raise UserError("Некорректный проект CurseForge.")
    if project_type == "mod" and inst.loader == "vanilla":
        raise UserError("Для модов CurseForge сначала выберите Fabric, Quilt, Forge или NeoForge.")
    own_client = client is None
    client = client or CurseForgeClient(api_key)
    try:
        tracker = read_json(inst.directory / "curseforge.json", {})
    except BaseException:
        if own_client:
            client.__exit__(None, None, None)
        raise
    if not isinstance(tracker, dict) or any(not isinstance(key, str) or not isinstance(value, dict)
                                            for key, value in tracker.items()):
        if own_client:
            client.__exit__(None, None, None)
        raise UserError("Некорректный curseforge.json.")
    resolved: dict[int, tuple[str, dict[str, Any]]] = {}

    def resolve(project_id: int, kind: str, file: dict[str, Any] | None = None) -> None:
        check_cancel(cancel)
        if project_id in resolved:
            return
        chosen = file or client.latest_file(project_id, inst, kind)
        if not isinstance(chosen, dict):
            raise UserError("CurseForge вернул некорректный файл.")
        resolved[project_id] = (kind, chosen)  # mark before recursion; cycles cannot loop forever
        if kind != "mod":
            return
        dependencies = chosen.get("dependencies", [])
        if not isinstance(dependencies, list):
            raise UserError("CurseForge вернул некорректные зависимости.")
        for dependency in dependencies:
            if not isinstance(dependency, dict):
                raise UserError("CurseForge вернул некорректные зависимости.")
            if dependency.get("relationType") != 3:
                continue
            dependency_id = dependency.get("modId")
            if type(dependency_id) is not int or dependency_id <= 0:
                raise UserError("CurseForge вернул некорректную обязательную зависимость.")
            resolve(dependency_id, "mod")

    try:
        resolve(mod_id, project_type, selected_file)
        replacements: dict[str, Path] = {}
        deletions: set[str] = set()
        expected: dict[str, str | None] = {}
        updated = copy.deepcopy(tracker)
        installed_titles: list[str] = []
        with FileTransaction(inst) as transaction:
            for index, (project_id, (kind, file)) in enumerate(resolved.items()):
                check_cancel(cancel)
                filename = file.get("fileName")
                if not isinstance(filename, str):
                    raise UserError("CurseForge не вернул имя файла.")
                filename = relative_path(filename)
                extension = ".jar" if kind == "mod" else ".zip"
                if "/" in filename or not filename.lower().endswith(extension):
                    raise UserError("CurseForge вернул имя файла неподдерживаемого формата.")
                file_id = file.get("id")
                if type(file_id) is not int or file_id <= 0:
                    raise UserError("CurseForge не вернул корректный номер файла.")
                digest = curseforge_sha1(file)
                size = file.get("fileLength")
                if type(size) is not int or not 0 <= size <= MAX_FILE_SIZE:
                    raise UserError("CurseForge вернул недопустимый размер файла.")
                folder = {"mod": "mods", "resourcepack": "resourcepacks", "shader": "shaderpacks"}[kind]
                key = str(project_id)
                old = tracker.get(key, {})
                if old and (old.get("project_id") != project_id or not isinstance(old.get("path", ""), str)):
                    raise UserError("Некорректная запись проекта в curseforge.json.")
                old_path = old.get("path", "")
                if old_path:
                    pack_path(old_path)
                if old_path and fingerprint(inst.game_dir, old_path + ".disabled") is not None:
                    old_path += ".disabled"
                    filename += ".disabled"
                relative = folder + "/" + filename
                current = fingerprint(inst.game_dir, relative)
                if current is not None and relative != old_path and current != digest:
                    raise UserError(f"{relative} уже существует и не принадлежит этому проекту.")
                if old_path and old_path != relative and fingerprint(inst.game_dir, old_path) is not None:
                    old_hash = fingerprint(inst.game_dir, old_path)
                    if old_hash != old.get("sha1"):
                        raise UserError(f"{old_path} изменён вручную. Установка отменена, чтобы не потерять файл.")
                    if any(value.get("path") in (old_path, old_path.removesuffix(".disabled"))
                           for other_id, value in updated.items() if other_id != key):
                        raise UserError("Файл используется несколькими проектами; автоматическое удаление запрещено.")
                    deletions.add(old_path)
                    expected[old_path] = old_hash
                if relative in replacements and sha1_file(replacements[relative]) != digest:
                    raise UserError("Разные проекты CurseForge пытаются установить файлы с одним именем.")
                expected[relative] = current
                display = title if project_id == mod_id and title else file.get("displayName", "")
                display = display if isinstance(display, str) and display else f"Проект CurseForge {project_id}"
                if current != digest and relative not in replacements:
                    url = client.download_url(project_id, file_id)
                    staged = transaction.staged_path(relative)
                    progress(f"Скачивание {display}", index, len(resolved))
                    # Do not pass the API session: its x-api-key header must never reach the CDN.
                    download_file(url, staged, sha1=digest, size=size,
                                  progress=progress, cancel=cancel)
                    replacements[relative] = staged
                updated[key] = {"project_id": project_id, "file_id": file_id, "title": display,
                                "project_type": kind, "path": relative.removesuffix(".disabled"),
                                "sha1": digest}
                installed_titles.append(display)
            transaction.commit(replacements, sorted(deletions - set(replacements)),
                               {"curseforge.json": updated}, expected, cancel)
        return list(dict.fromkeys(installed_titles))
    finally:
        if own_client:
            client.__exit__()


def update_curseforge(inst: Instance, api_key: str, *, progress: Progress = no_progress,
                      cancel: threading.Event | None = None) -> list[str]:
    tracker = read_json(inst.directory / "curseforge.json", {})
    if not isinstance(tracker, dict):
        raise UserError("Некорректный curseforge.json.")
    updated: list[str] = []
    with CurseForgeClient(api_key) as client:
        for key, record in list(tracker.items()):
            check_cancel(cancel)
            if not isinstance(key, str) or not key.isdigit() or not isinstance(record, dict):
                raise UserError("Некорректная запись проекта в curseforge.json.")
            project_id = int(key)
            kind = record.get("project_type", "mod")
            if kind not in CURSEFORGE_CLASS_IDS:
                raise UserError("Некорректный тип проекта в curseforge.json.")
            latest = client.latest_file(project_id, inst, kind)
            if latest["id"] != record.get("file_id"):
                updated.extend(install_curseforge(inst, project_id, kind, api_key, title=record.get("title", ""),
                                                  client=client, selected_file=latest,
                                                  progress=progress, cancel=cancel))
                tracker = read_json(inst.directory / "curseforge.json", {})
        return list(dict.fromkeys(updated))


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


def qt_runtime_message(import_error: str, *, platform: str | None = None) -> str:
    """Turn common Qt shared-library failures into actionable, OS-specific guidance."""
    platform = platform or sys.platform
    error = redact(import_error.strip()) or "неизвестная ошибка загрузки"
    if platform == "linux":
        if "libGL.so.1" in import_error or "libEGL.so.1" in import_error:
            advice = ("Не хватает системной библиотеки OpenGL. Debian/Ubuntu: "
                      "sudo apt install libgl1 libegl1; Fedora: sudo dnf install mesa-libGL mesa-libEGL; "
                      "Arch: sudo pacman -S mesa.")
        else:
            advice = ("Проверьте системные библиотеки Qt/OpenGL для Linux; для Debian/Ubuntu "
                      "команда установки приведена в README.md.")
    else:
        advice = "Проверьте установку PySide6 из requirements.txt и системные зависимости Qt для вашей ОС."
    return f"Не удалось загрузить PySide6: {error}\n{advice}"


def diagnostic_report(store: Store) -> dict[str, Any]:
    """Shareable-ish report. Never exports account names, tokens, hooks or sync URLs."""
    checks = [{"check": "qt_runtime", "ok": QT_AVAILABLE,
               "message": "PySide6 доступен" if QT_AVAILABLE else qt_runtime_message(QT_IMPORT_ERROR)}]
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
            "curseforge_api_key_configured": bool(store.settings.get("curseforge_api_key")),
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
    from PySide6.QtCore import (QBuffer, QByteArray, QEvent, QEventLoop, QObject, QPoint, QRect, QSize, Qt, QTimer, QUrl,
                                QIODevice, QLockFile, QPropertyAnimation, QVariantAnimation, QEasingCurve, Signal, Slot)
    from PySide6.QtGui import (QColor, QDesktopServices, QFont, QFontMetrics, QIcon, QImage, QImageReader,
                              QKeySequence, QShortcut, QLinearGradient, QPainter, QPainterPath, QPalette, QPen,
                              QPixmap, QPolygon)
    from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QApplication, QCheckBox, QComboBox,
                                  QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
                                  QHBoxLayout, QLabel,
                                  QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                                  QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                                  QScrollArea, QSizePolicy, QSlider, QSpinBox, QSplitter, QStackedWidget, QStatusBar, QStyle,
                                  QStyledItemDelegate, QTabWidget, QToolButton, QVBoxLayout,
                                  QWidget)
    QT_AVAILABLE = True
except ImportError as exc:
    QT_AVAILABLE, QT_IMPORT_ERROR = False, str(exc)


if QT_AVAILABLE:
    class BackgroundWorkerSignals(QObject):
        """Application-lifetime signal bus; filesystem workers never touch widget objects."""
        files_ready = Signal(str, int, object, str)
        summary_ready = Signal(str, int, object)
        updates_ready = Signal(str, int, object)

    _BACKGROUND_WORKER_SIGNALS: BackgroundWorkerSignals | None = None

    def background_worker_signals() -> BackgroundWorkerSignals:
        global _BACKGROUND_WORKER_SIGNALS
        if _BACKGROUND_WORKER_SIGNALS is None:
            application = QApplication.instance()
            if application is None:
                raise RuntimeError("A QApplication is required before starting filesystem workers.")
            _BACKGROUND_WORKER_SIGNALS = BackgroundWorkerSignals(application)
        return _BACKGROUND_WORKER_SIGNALS

    def theme_style(key: str = DEFAULT_THEME) -> str:
        colors = dict(THEMES[theme_key(key)])
        colors["success"] = success_color(key)
        stylesheet = """
        QWidget { color: @text; font-size: 13px; letter-spacing: 0.3px; }
        QMainWindow, QDialog, QWidget#central, QWidget#overviewContent { background: @bg; }
        QLabel { background: transparent; }
        QLabel#brand { font-size: 20px; font-weight: 700; color: @text; letter-spacing: -0.5px; }
        QLabel#pageTitle { font-size: 19px; font-weight: 600; }
        QLabel#title { font-size: 26px; font-weight: 700; }
        QLabel#sectionTitle { font-size: 14px; font-weight: 600; }
        QLabel#statValue { font-size: 24px; font-weight: 700; }
        QPushButton#segment:checked { background: @soft; color: @accent; border-color: @border; }
        QLabel#notice { color: @warning; background: @raised; border-radius: 6px; padding: 7px; }
        QLabel#muted { color: @muted; }
        QLabel#kicker { color: @muted; font-size: 10px; font-weight: 600; }
        QLabel#warning { color: @warning; }
        QLabel#badge { background: @soft; color: @accent; border-radius: 6px; padding: 5px 9px; font-size: 11px; }
        QLabel#badge[status="local"] { color: @muted; background: @raised; }
        QLabel#badge[status="pending"] { color: @warning; background: @raised; }
        QLabel#badge[connected="true"] { color: @success; background: @raised; }
        QFrame#sidebar { background: @sidebar; border: none; border-radius: 18px; }
        QFrame#card { background: @surface; border: 1px solid @border; border-left: 3px solid @accent; border-radius: 12px; }
        QFrame#modActions { background: @surface; border: 1px solid @border; border-radius: 12px; }
        QFrame#noticeBanner { background: @raised; border: 1px solid @border; border-left: 3px solid @accent; border-radius: 12px; }
        QFrame#sidebarDivider { background: @border; border: none; max-height: 1px; }
        QFrame#statCard { background: transparent; border: none; border-radius: 10px; }
        QFrame#statCard[interactive="true"]:hover, QFrame#statCard:focus { background: @raised; }
        QFrame#statStrip { background: @surface; border: none; border-radius: 14px; }
        QLabel#statValue { font-size: 28px; font-weight: 700; }
        QFrame#partyCard { background: @surface; border: 1px solid @border; border-radius: 14px; }
        QListWidget#partyRoster { background: transparent; border: none; padding: 0; }
        QListWidget#partyRoster::item { margin: 0; padding: 0; }
        QFrame#accountCard { background: @surface; border: 1px solid @border; border-radius: 12px; }
        QListWidget#accountList { background: transparent; border: none; padding: 4px; }
        QListWidget#accountList::item { padding: 8px 10px; border-radius: 8px; margin: 2px 0; }
        QListWidget#accountList::item:selected { background: @soft; }
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
        QSpinBox#memoryInput { font-weight: 600; }
        QSlider#memorySlider { background: transparent; min-height: 28px; }
        QSlider#memorySlider::groove:horizontal {
            height: 6px; background: @raised; border: 1px solid @border; border-radius: 4px;
        }
        QSlider#memorySlider::sub-page:horizontal {
            border-radius: 3px;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 @accent, stop:1 @hover);
        }
        QSlider#memorySlider::add-page:horizontal { background: @border; border-radius: 3px; }
        QSlider#memorySlider::handle:horizontal {
            background: @text; border: 3px solid @accent; width: 14px; margin: -7px 0; border-radius: 10px;
        }
        QSlider#memorySlider::handle:horizontal:hover { background: @hover; border-color: @hover; }
        QSlider#memorySlider::handle:horizontal:pressed { background: @accent; border-color: @hover; }
        QSlider#memorySlider::handle:horizontal:focus { border-color: @hover; }
        QSlider#memorySlider::groove:horizontal:disabled { background: @surface; }
        QSlider#memorySlider::sub-page:horizontal:disabled { background: @border; }
        QSlider#memorySlider::handle:horizontal:disabled { background: @surface; border-color: @muted; }
        QComboBox QAbstractItemView { background: @surface; color: @text; selection-background-color: @soft; }
        QPushButton, QToolButton {
            background: @raised; color: @text; border: 1px solid @border; border-radius: 15px;
            padding: 9px 18px; min-height: 28px; font-size: 14px; font-weight: 600;
        }
        QPushButton:hover, QToolButton:hover { background: @soft; border-color: @accent; }
        QPushButton:pressed, QToolButton:pressed { background: @surface; border-color: @accent; }
        QPushButton:focus, QToolButton:focus { border-color: @border; }
        QDialogButtonBox QPushButton:hover { background: @soft; border-color: @accent; }
        QDialogButtonBox QPushButton:pressed { background: @surface; }
        QPushButton:disabled, QToolButton:disabled { color: @muted; background: @surface; border-color: @border; }
        QPushButton#play, QPushButton#primary, QPushButton#lobbyPlay {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 @hover, stop:1 @accent);
            color: @on_accent; font-weight: 700; border: 1px solid transparent;
        }
        QPushButton#play { padding: 12px 30px; font-size: 16px; border-radius: 25px; min-height: 34px; }
        QPushButton#primary { padding: 10px 20px; min-height: 32px; }
        QLabel#cinematicTitle { font-size: 34px; font-weight: 800; color: #ffffff; }
        QLabel#lobbyTitle { font-size: 58px; font-weight: 800; color: #ffffff; }
        QLabel#lobbyKicker { color: #b6abc9; font-size: 11px; font-weight: 600; letter-spacing: 2px; }
        QLabel#lobbyMeta { color: #c2c8d5; font-size: 13px; }
        QLabel#lobbyFooter { color: #adb8c9; font-size: 11px; }
        QLabel#lobbyChip { background: rgba(15,20,29,155); color: #d8dce6; border-radius: 20px; padding: 11px 18px; font-size: 11px; }
        QPushButton#lobbyChipButton {
            background: rgba(15,20,29,180); color: #e5e8f1; border: 1px solid rgba(255,255,255,38);
            border-radius: 18px; padding: 9px 18px; min-height: 28px; font-size: 13px;
        }
        QPushButton#lobbyChipButton:hover { background: rgba(25,32,45,225); border-color: @accent; color: #ffffff; }
        QPushButton#lobbyChipButton:focus { border-color: rgba(255,255,255,38); }
        QPushButton#lobbyChipButton[connected="true"] { color: #7ee7b5; }
        QPushButton#lobbyPlay { border-radius: 30px; min-height: 38px; padding: 14px 34px; font-size: 17px; }
        QPushButton#lobbyPlay:hover { border: 1px solid @hover; }
        QPushButton#lobbyPlay:pressed { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 @accent, stop:1 @soft); }
        QPushButton#lobbyConfigure {
            background: rgba(25,31,42,205); color: #f3f5fa; border: 1px solid rgba(180,190,210,70);
            border-radius: 28px; min-height: 32px; padding: 12px 28px; font-size: 14px; font-weight: 600;
        }
        QPushButton#lobbyConfigure:hover { background: rgba(42,48,63,225); border-color: @accent; }
        QPushButton#lobbyConfigure:focus { border-color: rgba(180,190,210,70); }
        QPushButton#lobbyConfigure:pressed { background: rgba(16,21,31,230); }
        QPushButton#lobbyConfigure:disabled { color: @muted; background: rgba(25,31,42,120); border-color: @border; }
        QPushButton#nav {
            text-align: left; padding: 9px 16px; min-height: 36px; border: none;
            border-radius: 8px; background: transparent; color: @muted; font-size: 13px;
            margin: 1px 8px;
        }
        QPushButton#nav:hover { background: @raised; color: @text; }
        QPushButton#nav:checked {
            background: @raised; color: @text; padding-left: 16px;
        }
        QFrame#catalogSourceRail { background: @surface; border: 1px solid @border; border-radius: 14px; }
        QPushButton#catalogSource {
            text-align: left; padding: 9px 10px; min-height: 30px; border-radius: 9px;
            background: transparent; border-color: transparent; font-size: 13px;
        }
        QPushButton#catalogSource:hover { background: @raised; border-color: @border; }
        QPushButton#catalogSource:checked { background: @soft; border-color: @border; color: @accent; }
        QPushButton#catalogSource:focus { border-color: @border; }
        QListWidget#catalogResults { background: @surface; border: 1px solid @border; border-radius: 14px; padding: 5px; }
        QListWidget#catalogResults::item { padding: 9px; border-radius: 10px; margin: 3px; min-height: 48px; }
        QListWidget#catalogResults::item:selected { background: @soft; color: @text; border: 1px solid @border; }
        QLabel#catalogProjectIcon { background: @raised; border: 1px solid @border; border-radius: 12px; padding: 7px; }
        QLabel#catalogProjectTitle { font-size: 20px; font-weight: 700; }
        QLabel#catalogProjectBody { color: @muted; }
        QFrame#card, QFrame#statStrip { border-radius: 22px; }
        QFrame#partyCard { border-radius: 22px; }
        QFrame#libraryEmptyState { background: @surface; border: 1px dashed @border; border-radius: 18px; }
        QPushButton#segment { padding: 10px 16px; min-height: 32px; border-radius: 14px; border: none; }
        QPushButton#ghost, QToolButton#ghost { background: transparent; border-color: transparent; }
        QPushButton#ghost:hover, QToolButton#ghost:hover { background: @soft; border-color: @border; }
        QPushButton#ghost:focus, QToolButton#ghost:focus { border-color: transparent; }
        QPushButton#ghost:disabled, QToolButton#ghost:disabled { color: @muted; background: transparent; }
        QPushButton#danger { color: @danger; background: @surface; border-color: @border; font-weight: 600; }
        QPushButton#danger:hover { background: @raised; border-color: @danger; }
        QPushButton#danger:disabled { color: @muted; }
        QListWidget { background: @surface; border: 1px solid @border; border-radius: 9px; outline: none; padding: 5px; }
        QListWidget#instances, QListWidget#libraryGrid { background: transparent; border: none; padding: 2px; }
        QListWidget#instances::item { padding: 6px 10px; border-radius: 8px; margin: 1px 6px; }
        QListWidget#instances::item:hover { background: @raised; }
        QListWidget#instances::item:selected { background: @soft; }
        QListWidget#modList { background: @surface; border: 1px solid @border; border-radius: 9px; padding: 4px; }
        QListWidget#modList::item { padding: 2px 6px; border-radius: 6px; margin: 2px; }
        QPushButton#modStatusTab { border: none; border-radius: 14px; padding: 4px 14px; font-size: 12px;
            background: @surface; color: @muted; }
        QPushButton#modStatusTab:hover { background: @raised; }
        QPushButton#modStatusTab:checked { background: @accent; color: #0d1017; font-weight: bold; }
        QListWidget::item { padding: 11px 9px; border-radius: 6px; margin: 2px; }
        QListWidget::item:selected { background: @soft; color: @text; }
        QListWidget::item:hover:!selected { background: @raised; }
        QTabWidget::pane { border: none; background: transparent; }
        QTabBar { background: transparent; }
        QTabBar::tab {
            background: transparent; color: @muted; padding: 10px 12px;
            border-bottom: 2px solid @border; margin-bottom: 8px;
        }
        QTabBar::tab:selected { color: @text; border-bottom-color: transparent; }
        QTabBar::tab:hover { color: @accent; }
        QFrame#tabMotionIndicator, QFrame#pageMotionIndicator { background: @accent; border: none; border-radius: 1px; }
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
        QFrame#taskProgressCard {
            background: @surface; border: 1px solid @border; border-radius: 13px; min-height: 46px;
        }
        QFrame#taskProgressCard[progressVariant="launch"] {
            background: @raised; border: 1px solid @accent;
        }
        QFrame#taskProgressCard[progressVariant="download"] {
            background: @surface; border: 1px solid @border;
        }
        QFrame#taskProgressCard[progressState="error"] { border-color: @danger; }
        QFrame#taskProgressCard[progressState="done"] { border-color: @success; }
        QFrame#taskProgressCard QProgressBar#taskBar { min-height: 8px; background: @border; }
        QFrame#taskProgressCard QProgressBar#taskBar::chunk { background: @accent; border-radius: 4px; }
        QLabel#taskStage { color: @text; font-size: 13px; }
        QLabel#taskPercent { color: @accent; font-size: 13px; font-weight: 700; }
        QFrame#taskProgressCard[progressVariant="launch"] QLabel#taskStage { font-weight: 600; }
        QFrame#taskProgressCard[progressVariant="download"] QLabel#taskPercent { color: @muted; }
        QCheckBox { padding: 4px 0; spacing: 8px; }
        QSplitter::handle { background: transparent; width: 12px; }
        QMenu { background: @surface; border: 1px solid @border; border-radius: 8px; padding: 6px; }
        QMenu::item { padding: 8px 24px 8px 12px; border-radius: 5px; }
        QMenu::item:selected { background: @soft; }
        QMenu::separator { height: 1px; background: @border; margin: 5px; }
        QStatusBar { background: @bg; color: @muted; font-size: 11px; }
        QStatusBar::item { border: none; }
        QToolTip { background: @surface; color: @text; border: 1px solid @border; padding: 6px; }
        QPushButton#play:hover, QPushButton#primary:hover { border: 1px solid @hover; }
        QPushButton#play:focus, QPushButton#primary:focus, QPushButton#lobbyPlay:focus { border: 1px solid transparent; }
        QPushButton#play:pressed, QPushButton#primary:pressed {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 @accent, stop:1 @soft);
        }
        QPushButton#play:disabled, QPushButton#primary:disabled, QPushButton#lobbyPlay:disabled {
            background: @surface; color: @muted; border: 1px solid @border;
        }
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
        app.setProperty("accentColor", colors["accent"])
        app.setStyleSheet(theme_style(key))
        spotify_font = ["Circular", "Inter", "DM Sans", "Segoe UI", "SF Pro Display",
                        "Helvetica Neue", "Ubuntu", "Noto Sans", "Cantarell", "DejaVu Sans"]
        font = QFont()
        font.setStyleHint(QFont.StyleHint.SansSerif)
        font.setFamilies(spotify_font)
        font.setPointSize(10)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.2)
        app.setFont(font)

    def motion_enabled() -> bool:
        app = QApplication.instance()
        return app is not None and not bool(app.property("reducedMotion"))

    def repaint_visible_widget_tree(root: QWidget | None) -> None:
        """Synchronously paint an exposed page and its visible controls without hover."""
        if root is None or not root.isVisible():
            return
        root.ensurePolished()
        root.updateGeometry()
        for widget in [root, *root.findChildren(QWidget)]:
            if widget.isVisible():
                widget.ensurePolished()
                widget.update()
                widget.repaint()

    class WorldSurface(QWidget):
        """Theme-matched local voxel art; content and hit targets remain native Qt."""
        def __init__(self, key: str = DEFAULT_THEME):
            super().__init__()
            self.key = theme_key(key)
            self.artwork = QPixmap(str(theme_artwork_path(self.key)))
            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        def set_theme(self, key: str) -> None:
            self.key = theme_key(key)
            self.artwork = QPixmap(str(theme_artwork_path(self.key)))
            self.update()

        def paintEvent(self, event: Any) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            rect = self.rect()
            clip = QPainterPath()
            clip.addRoundedRect(rect, 22, 22)
            painter.setClipPath(clip)
            if not self.artwork.isNull():
                scaled = self.artwork.scaled(rect.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                            Qt.TransformationMode.SmoothTransformation)
                x = (scaled.width() - rect.width()) // 2
                y = (scaled.height() - rect.height()) // 2
                painter.drawPixmap(rect, scaled, QRect(x, y, rect.width(), rect.height()))
            else:
                paint_landscape(painter, rect, self.key, 4)
            veil = QLinearGradient(0, 0, rect.width(), 0)
            veil.setColorAt(0, QColor(7, 11, 17, 215))
            veil.setColorAt(0.54, QColor(7, 11, 17, 145))
            veil.setColorAt(1, QColor(7, 11, 17, 70))
            painter.fillRect(rect, veil)
            bottom = QLinearGradient(0, rect.height() // 3, 0, rect.height())
            bottom.setColorAt(0, QColor(7, 11, 17, 0))
            bottom.setColorAt(1, QColor(7, 11, 17, 215))
            painter.fillRect(rect, bottom)
            painter.end()

    class HeroFrame(WorldSurface):
        def __init__(self, key: str):
            super().__init__(key)
            self.setMinimumHeight(175)
            self.setObjectName("cinematicHero")

    class MotionFeedbackMixin:
        """Smooth, theme-aware hover and press feedback shared by both Qt button types."""
        MOTION_RADII = {"nav": 8, "segment": 14, "play": 25, "lobbyPlay": 28,
                        "lobbyConfigure": 28, "lobbyChipButton": 18, "catalogSource": 9}

        def _init_motion(self) -> None:
            self.hover_amount = 0.0
            self.press_amount = 0.0
            self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
            self.hover_animation = QVariantAnimation(self)
            self.hover_animation.setDuration(450)
            self.hover_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
            self.hover_animation.valueChanged.connect(self._hover_value)
            self.press_animation = QVariantAnimation(self)
            self.press_animation.setDuration(300)
            self.press_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.press_animation.valueChanged.connect(self._press_value)

        def _hover_value(self, value: Any) -> None:
            self.hover_amount = float(value)
            self.update()

        def _press_value(self, value: Any) -> None:
            self.press_amount = float(value)
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

        def animate_press(self, target: float) -> None:
            self.press_animation.stop()
            if not motion_enabled():
                self._press_value(float(target))
                return
            self.press_animation.setStartValue(self.press_amount)
            self.press_animation.setEndValue(float(target))
            self.press_animation.start()

        def motion_corner_radius(self, rect: QRect) -> float:
            radius = self.property("motionRadius")
            if type(radius) not in (int, float):
                radius = self.MOTION_RADII.get(self.objectName(), 15)
            return min(float(radius), max(0.0, rect.height() / 2))

        def enterEvent(self, event: Any) -> None:
            super().enterEvent(event)
            if self.isEnabled():
                self.animate_hover(1.0)

        def leaveEvent(self, event: Any) -> None:
            super().leaveEvent(event)
            self.animate_hover(0.0)
            self.animate_press(0.0)

        def hideEvent(self, event: Any) -> None:
            super().hideEvent(event)
            self.hover_animation.stop()
            self.press_animation.stop()
            self.hover_amount = 0.0
            self.press_amount = 0.0

        def mousePressEvent(self, event: Any) -> None:
            super().mousePressEvent(event)
            if event.button() == Qt.MouseButton.LeftButton:
                self.animate_press(1.0)

        def mouseReleaseEvent(self, event: Any) -> None:
            super().mouseReleaseEvent(event)
            self.animate_press(0.0)

        def paintEvent(self, event: Any) -> None:
            super().paintEvent(event)
            is_checked = self.isCheckable() and self.isChecked()
            if not self.isEnabled() or (not is_checked and self.hover_amount <= 0 and self.press_amount <= 0):
                return
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = self.rect().adjusted(1, 1, -1, -1)
            path = QPainterPath()
            radius = self.motion_corner_radius(rect)
            path.addRoundedRect(rect, radius, radius)
            painter.setClipPath(path)

            app = QApplication.instance()
            accent_value = app.property("accentColor") if app else None
            accent = QColor(str(accent_value)) if accent_value else self.palette().color(QPalette.ColorRole.Highlight)
            if is_checked and self.objectName() == "nav":
                bar_w = 3
                bar = QRect(rect.left(), rect.top(), bar_w, rect.height())
                bar_path = QPainterPath()
                bar_path.addRoundedRect(rect.left(), rect.top(), max(bar_w, radius), rect.height(), radius, radius)
                painter.setClipPath(bar_path)
                painter.fillRect(bar, accent)
                painter.setClipPath(path)
            wash = QColor(accent)
            wash.setAlpha(round(22 * self.hover_amount))
            painter.fillPath(path, wash)
            if self.hover_amount > 0:
                center = -80 + (self.width() + 160) * self.hover_amount
                sheen = QLinearGradient(center - 90, 0, center + 90, 0)
                sheen.setColorAt(0, QColor(255, 255, 255, 0))
                sheen.setColorAt(0.35, QColor(255, 255, 255, round(36 * self.hover_amount)))
                sheen.setColorAt(0.65, QColor(255, 255, 255, round(36 * self.hover_amount)))
                sheen.setColorAt(1, QColor(255, 255, 255, 0))
                painter.fillRect(rect, sheen)
            if self.press_amount > 0:
                painter.fillPath(path, QColor(0, 0, 0, round(52 * self.press_amount)))
            painter.end()

    class MotionButton(MotionFeedbackMixin, QPushButton):
        """QPushButton with visible motion that never moves or shrinks its click target."""
        def __init__(self, text: str):
            self._mcsync_source_text = text
            super().__init__(translate_ui_text(text))
            self._init_motion()

        def setText(self, text: str) -> None:
            self._mcsync_source_text = text
            super().setText(translate_ui_text(text))

        def setAccessibleName(self, name: str) -> None:
            self._mcsync_source_accessible_name = name
            super().setAccessibleName(translate_ui_text(name))

    class MotionToolButton(MotionFeedbackMixin, QToolButton):
        """Animated counterpart for icon/menu tool buttons."""
        def __init__(self):
            super().__init__()
            self._init_motion()

        def setText(self, text: str) -> None:
            self._mcsync_source_text = text
            super().setText(translate_ui_text(text))

        def setAccessibleName(self, name: str) -> None:
            self._mcsync_source_accessible_name = name
            super().setAccessibleName(translate_ui_text(name))

    class FadeStack(QStackedWidget):
        """Switch content immediately; animate a separate accent rule, never page opacity."""
        def __init__(self):
            super().__init__()
            self.transition_indicator = QFrame(self)
            self.transition_indicator.setObjectName("pageMotionIndicator")
            self.transition_indicator.setFixedHeight(3)
            self.transition_indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.transition_indicator.setStyleSheet("border-radius: 1px;")
            self.transition_indicator.hide()
            self.transition = QVariantAnimation(self)
            self.transition.valueChanged.connect(self.set_transition_geometry)
            self.transition.setDuration(500)
            self.transition.setEasingCurve(QEasingCurve.Type.InOutQuart)
            self.transition.finished.connect(self.finish_transition)
            self._content_refresh_timer = QTimer(self)
            self._content_refresh_timer.setSingleShot(True)
            self._content_refresh_timer.timeout.connect(self.refresh_current_page)
            self.currentChanged.connect(lambda _index: self.schedule_current_page_refresh())

        def refresh_current_page(self) -> None:
            repaint_visible_widget_tree(self.currentWidget())

        def schedule_current_page_refresh(self) -> None:
            if not self._content_refresh_timer.isActive():
                self._content_refresh_timer.start(0)

        def showEvent(self, event: Any) -> None:
            super().showEvent(event)
            self.schedule_current_page_refresh()

        def set_transition_geometry(self, geometry: QRect) -> None:
            self.transition_indicator.setGeometry(geometry)

        def finish_transition(self) -> None:
            self.transition_indicator.hide()

        def setCurrentIndex(self, index: int) -> None:
            if index == self.currentIndex() or not 0 <= index < self.count():
                return
            self.transition.stop()
            self.finish_transition()
            super().setCurrentIndex(index)
            self.reveal_current()

        def setCurrentWidget(self, widget: QWidget) -> None:
            self.setCurrentIndex(self.indexOf(widget))

        def reveal_current(self) -> None:
            self.transition.stop()
            self.finish_transition()
            if not motion_enabled() or not self.isVisible():
                return
            end = QRect(0, 0, max(0, self.width()), 3)
            self.transition_indicator.setGeometry(0, 0, 0, 3)
            self.transition_indicator.show()
            self.transition_indicator.raise_()
            self.transition.setStartValue(QRect(0, 0, 0, 3))
            self.transition.setEndValue(end)
            self.transition.start()

        def disable_motion(self) -> None:
            self.transition.stop()
            self.finish_transition()

        def resizeEvent(self, event: Any) -> None:
            super().resizeEvent(event)
            if self.transition.state() == QPropertyAnimation.State.Running:
                self.transition.setEndValue(QRect(0, 0, max(0, self.width()), 3))

        def hideEvent(self, event: Any) -> None:
            self.transition.stop()
            self.finish_transition()
            super().hideEvent(event)

    class AnimatedTabWidget(QTabWidget):
        """Animate only the tab underline; page widgets remain fully native and repaint normally."""
        def __init__(self):
            super().__init__()
            self.tab_motion_indicator = QFrame(self.tabBar())
            self.tab_motion_indicator.setObjectName("tabMotionIndicator")
            self.tab_motion_indicator.setFixedHeight(3)
            self.tab_motion_indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.transition = QVariantAnimation(self)
            self.transition.setDuration(450)
            self.transition.setEasingCurve(QEasingCurve.Type.InOutQuart)
            self.transition.valueChanged.connect(self.set_indicator_geometry)
            self._indicator_index = -1
            self._indicator_sync_timer = QTimer(self)
            self._indicator_sync_timer.setSingleShot(True)
            self._indicator_sync_timer.timeout.connect(self.sync_indicator)
            self.transition.finished.connect(self.finish_transition)
            self.currentChanged.connect(self.animate_current_page)
            self._content_refresh_timer = QTimer(self)
            self._content_refresh_timer.setSingleShot(True)
            self._content_refresh_timer.timeout.connect(self.refresh_current_page)
            self.currentChanged.connect(lambda _index: self.schedule_current_page_refresh())
            self._indicator_sync_timer.start(0)

        def refresh_current_page(self) -> None:
            repaint_visible_widget_tree(self.currentWidget())

        def schedule_current_page_refresh(self) -> None:
            if not self._content_refresh_timer.isActive():
                self._content_refresh_timer.start(0)

        def showEvent(self, event: Any) -> None:
            super().showEvent(event)
            self.schedule_current_page_refresh()

        def set_indicator_geometry(self, geometry: QRect) -> None:
            self.tab_motion_indicator.setGeometry(geometry)

        def indicator_geometry(self, index: int) -> QRect:
            if not 0 <= index < self.count():
                return QRect()
            tab = self.tabBar().tabRect(index)
            if tab.isNull() or tab.width() <= 0:
                return QRect()
            return QRect(tab.left(), tab.bottom() - 1, tab.width(), 3)

        def sync_indicator(self) -> None:
            index = self.currentIndex()
            target = self.indicator_geometry(index)
            if target.isNull():
                return
            if self.transition.state() == QPropertyAnimation.State.Running:
                self.transition.setEndValue(target)
            else:
                self.tab_motion_indicator.setGeometry(target)
                self.tab_motion_indicator.show()
                self.tab_motion_indicator.raise_()
            self._indicator_index = index

        def finish_transition(self) -> None:
            target = self.indicator_geometry(self.currentIndex())
            if not target.isNull():
                self.tab_motion_indicator.setGeometry(target)
                self.tab_motion_indicator.show()
                self.tab_motion_indicator.raise_()
            self._indicator_index = self.currentIndex()

        def animate_current_page(self, index: int) -> None:
            self.transition.stop()
            if not 0 <= index < self.count():
                return
            target = self.indicator_geometry(index)
            if target.isNull():
                self._indicator_index = index
                self._indicator_sync_timer.start(0)
                return
            start = self.tab_motion_indicator.geometry()
            previous_index = self._indicator_index
            self._indicator_index = index
            self.tab_motion_indicator.show()
            self.tab_motion_indicator.raise_()
            if (previous_index < 0 or start.isNull() or start.width() <= 0
                    or not motion_enabled() or not self.isVisible()):
                self.tab_motion_indicator.setGeometry(target)
                return
            self.transition.setStartValue(start)
            self.transition.setEndValue(target)
            self.transition.start()

        def disable_motion(self) -> None:
            self.transition.stop()
            self.sync_indicator()

        def resizeEvent(self, event: Any) -> None:
            super().resizeEvent(event)
            self._indicator_sync_timer.start(0)

        def hideEvent(self, event: Any) -> None:
            self.transition.stop()
            self.finish_transition()
            super().hideEvent(event)

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
            # Build icons are no longer shown in lists or cards; the stored field is kept for compatibility.
            x = rect.left() + 16
            available = max(20, rect.width() - 26)
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
                painter.drawText(QRect(x, rect.top() + 52, available, 15), Qt.AlignmentFlag.AlignVCenter,
                                 translate_ui_text(state))
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
            description = translate_ui_text(value.get("description", ""))
            painter.drawText(QRect(x, rect.top() + 33, width, 18), Qt.AlignmentFlag.AlignVCenter,
                             QFontMetrics(font).elidedText(description, Qt.TextElideMode.ElideRight, width))
            painter.restore()


    class ModListDelegate(QStyledItemDelegate):
        """Compact installed-mod row: real JAR icon, title, version and local file date."""
        def __init__(self, main: MainWindow):
            super().__init__(main)
            self.main = main

        def sizeHint(self, option: Any, index: Any) -> QSize:
            return QSize(420, 52)

        def paint(self, painter: QPainter, option: Any, index: Any) -> None:
            value = index.data(int(Qt.ItemDataRole.UserRole) + 1) or {}
            colors = THEMES[self.main.theme]
            selected = bool(option.state & QStyle.StateFlag.State_Selected)
            hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = option.rect.adjusted(1, 1, -1, -1)
            if selected or hovered:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(colors["soft"] if selected else colors["raised"]))
                painter.drawRoundedRect(rect, 7, 7)
            icon_rect = QRect(rect.left() + 5, rect.center().y() - 20, 40, 40)
            icon = value.get("icon")
            shape = QPainterPath()
            shape.addRoundedRect(icon_rect, 10, 10)
            painter.setPen(Qt.PenStyle.NoPen)
            if isinstance(icon, QImage) and not icon.isNull():
                painter.save()
                painter.setClipPath(shape)
                if value.get("enabled", True):
                    painter.drawImage(icon_rect, icon)
                else:
                    painter.setOpacity(0.55)
                    painter.drawImage(icon_rect, icon)
                painter.restore()
            else:
                painter.setBrush(QColor(colors["raised"]))
                painter.drawRoundedRect(icon_rect, 10, 10)
                tile_font = QFont(option.font)
                tile_font.setPixelSize(10)
                tile_font.setBold(True)
                painter.setFont(tile_font)
                painter.setPen(QColor(colors["accent"] if value.get("enabled", True) else colors["muted"]))
                painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, "JAR")
            badge = QRect(icon_rect.right() - 12, icon_rect.bottom() - 12, 12, 12)
            painter.setBrush(QColor(colors["bg"]))
            painter.drawEllipse(badge)
            painter.setBrush(QColor(colors["accent"] if value.get("enabled", True) else colors["muted"]))
            painter.drawEllipse(badge.adjusted(3, 3, -3, -3))
            if value.get("update_available"):
                up_badge = QRect(icon_rect.left() - 2, icon_rect.top() - 2, 16, 16)
                painter.setBrush(QColor("#e6c744"))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(up_badge)
                up_font = QFont(option.font)
                up_font.setPixelSize(10)
                up_font.setBold(True)
                painter.setFont(up_font)
                painter.setPen(QColor("#1a1e2e"))
                painter.drawText(up_badge, Qt.AlignmentFlag.AlignCenter, "↑")
            date_width = 112
            date_x = rect.right() - date_width - 8
            detail_font = QFont(option.font)
            detail_font.setPixelSize(11)
            metrics = QFontMetrics(detail_font)
            version = str(value.get("version") or "—")
            chip_width = min(150, metrics.horizontalAdvance(version) + 18)
            chip = QRect(date_x - chip_width - 12, rect.center().y() - 11, chip_width, 22)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors["raised"]))
            painter.drawRoundedRect(chip, 11, 11)
            painter.setFont(detail_font)
            painter.setPen(QColor(colors["accent"] if value.get("enabled", True) else colors["muted"]))
            painter.drawText(chip, Qt.AlignmentFlag.AlignCenter,
                             metrics.elidedText(version, Qt.TextElideMode.ElideRight, chip_width - 10))
            painter.setPen(QColor(colors["muted"]))
            painter.drawText(QRect(date_x, rect.top(), date_width, rect.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                             str(value.get("updated", "—")))
            name_x, name_width = rect.left() + 53, max(24, chip.left() - rect.left() - 63)
            title_font = QFont(option.font)
            title_font.setPixelSize(13)
            title_font.setBold(bool(value.get("enabled", True)))
            painter.setFont(title_font)
            painter.setPen(QColor(colors["text"] if value.get("enabled", True) else colors["muted"]))
            title = str(value.get("display_name") or value.get("name", ""))
            painter.drawText(QRect(name_x, rect.top(), name_width, rect.height()), Qt.AlignmentFlag.AlignVCenter,
                             QFontMetrics(title_font).elidedText(title, Qt.TextElideMode.ElideRight, name_width))
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
            self._mcsync_source_text = text
            translated = translate_ui_text(text)
            super().setText(translated)
            self._mcsync_source_tooltip = text
            self.setToolTip(translated)

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

    class LobbyTitle(ElidedLabel):
        """Clearly visible text slide/fade; layout and button hit targets do not move."""
        def __init__(self):
            super().__init__()
            self.reveal_amount = 1.0
            self.setObjectName("lobbyTitle")

        def paintEvent(self, event: Any) -> None:
            painter = QPainter(self)
            painter.setFont(self.font())
            color = QColor("#ffffff")
            color.setAlpha(round(255 * self.reveal_amount))
            painter.setPen(color)
            rect = self.contentsRect().adjusted(round(42 * (1 - self.reveal_amount)), 0, 0, 0)
            painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, rect.width()))
            painter.end()

    class CinematicLobby(WorldSurface):
        """One full-scene launch screen. Management panes are deliberately not on the home page."""
        def __init__(self, main: MainWindow):
            super().__init__(main.theme)
            self.main = main
            self.setObjectName("lobby")
            self.last_identity = ""
            self.reveal = QVariantAnimation(self)
            self.reveal.setDuration(650)
            self.reveal.setEasingCurve(QEasingCurve.Type.InOutQuart)
            self.reveal.valueChanged.connect(self._reveal_value)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(42, 30, 42, 28)
            layout.setSpacing(18)
            top = QHBoxLayout()
            self.ram_chip = label("", "lobbyChip")
            self.party_chip = button("Пати", main.show_party, "lobbyChipButton")
            self.party_chip.setAccessibleName("Открыть участников и соединение пати")
            self.profile = button("Аккаунты", main.show_accounts, "lobbyChipButton")
            self.profile.setParent(self)
            self.profile.hide()
            top.addWidget(self.ram_chip)
            top.addSpacing(8)
            top.addWidget(self.party_chip)
            top.addStretch()
            layout.addLayout(top)
            layout.addStretch(2)
            content = QVBoxLayout()
            content.setSpacing(12)
            self.kicker = label("ВАША СБОРКА", "lobbyKicker")
            self.title = LobbyTitle()
            self.title.setMinimumHeight(76)
            self.meta = label("", "lobbyMeta", True)
            self.description = label("", "lobbyMeta", True)
            self.description.setMaximumWidth(570)
            content.addWidget(self.kicker)
            content.addWidget(self.title)
            content.addWidget(self.meta)
            content.addWidget(self.description)
            actions = QHBoxLayout()
            actions.setSpacing(12)
            self.play = button("▶  Играть", main.launch, "lobbyPlay")
            self.play.setMinimumWidth(184)
            self.play.setAccessibleName("Играть в выбранную сборку")
            self.configure = button("Настроить", main.show_details, "lobbyConfigure")
            self.configure.setMinimumWidth(184)
            self.configure.setAccessibleName("Открыть рабочее пространство сборки")
            self.create = button("+  Создать сборку", main.show_library, "lobbyConfigure")
            self.create.setMinimumWidth(184)
            self.connect = button("Подключиться к другу", main.show_library, "lobbyChipButton")
            self.open_library = button("Открыть библиотеку", main.show_library, "lobbyConfigure")
            self.open_library.setMinimumWidth(184)
            self.actions_layout = actions
            actions.addWidget(self.play)
            actions.addWidget(self.open_library)
            actions.addStretch()
            self.configure.hide()
            self.create.hide()
            self.connect.hide()
            content.addSpacing(10)
            content.addLayout(actions)
            layout.addLayout(content)
            layout.addStretch(3)
            bottom = QHBoxLayout()
            self.sync_note = label("", "lobbyFooter", True)
            self.sync_note._mcsync_allow_partial = True
            self.runtime_note = label("", "lobbyFooter")
            bottom.addWidget(self.sync_note, 1)
            bottom.addWidget(self.runtime_note, 0, Qt.AlignmentFlag.AlignBottom)
            layout.addLayout(bottom)

        def _reveal_value(self, value: Any) -> None:
            self.title.reveal_amount = float(value)
            self.title.update()

        def animate_reveal(self) -> None:
            self.reveal.stop()
            if not motion_enabled() or not self.isVisible():
                self._reveal_value(1.0)
                return
            self.reveal.setStartValue(0.08)
            self.reveal.setEndValue(1.0)
            self.reveal.start()

        def disable_motion(self) -> None:
            self.reveal.stop()
            self._reveal_value(1.0)

        def hideEvent(self, event: Any) -> None:
            self.reveal.stop()
            super().hideEvent(event)

        def refresh(self, inst: Instance | None) -> None:
            if inst is None:
                self.kicker.setText("ДОБРО ПОЖАЛОВАТЬ В MCSYNC")
                self.title.setText("ВЫБЕРИТЕ СБОРКУ")
                self.meta.clear()
                self.description.setText("Откройте библиотеку, чтобы выбрать или создать сборку.")
                self.play.hide()
                self.configure.hide()
                self.create.hide()
                self.connect.hide()
                self.open_library.show()
                self.play.setEnabled(False)
                self.open_library.setEnabled(not self.main.busy)
                self.ram_chip.clear()
                self.profile.setText("Аккаунты")
                self.party_chip.setText("Пати")
                self.party_chip.setProperty("connected", False)
                self.party_chip.style().unpolish(self.party_chip)
                self.party_chip.style().polish(self.party_chip)
                self.party_chip.setEnabled(not self.main.busy)
                self.profile.setEnabled(not self.main.busy)
                self.sync_note.clear()
                self.runtime_note.clear()
                return
            self.play.show()
            self.configure.hide()
            self.create.hide()
            self.connect.hide()
            self.open_library.hide()
            self.key = self.main.theme
            self.kicker.setText("С ДРУЗЬЯМИ" if inst.sync_url or inst.id in self.main.hosts else inst.group.upper() if inst.group else "MINECRAFT JAVA")
            self.title.setText(inst.name.upper())
            self.meta.setText(f"Minecraft {inst.minecraft} · {LOADERS[inst.loader]}" +
                              (f" {inst.loader_version}" if inst.loader_version else ""))
            text = " ".join(inst.notes.split())
            self.description.setText(text[:220] if text else
                                     "Всё готово для следующего приключения. Просто нажмите «Играть»." if self.main.accounts.selected() else
                                     "Сначала выберите аккаунт в разделе «Аккаунты». Java и Minecraft установятся автоматически.")
            self.ram_chip.setText(f"ПАМЯТЬ  ·  {human_size(inst.ram_max * 1024**2)}")
            self.profile.setText("Аккаунты")
            state = self.main.sync_checks.get(inst.id, {})
            room = self.main.party_states.get(inst.id, {}).get("room")
            if inst.id in self.main.hosts:
                self.party_chip.setText("●  Пати открыта")
                endpoint = self.main.lan_endpoint(inst)
                note = ("Приглашение сохранено. Мир Minecraft по LAN не подтверждён открытым; в игре нажмите Esc → Открыть для сети."
                        if not endpoint else f"Приглашение сохранено · Minecraft LAN: {endpoint}")
            elif inst.sync_url and state.get("online"):
                count = len(room["members"]) if room and room.get("members") else None
                self.party_chip.setText(f"●  В пати · {count}" if count else "●  Хост на связи")
                note = "Обновления проверяются перед игрой · смена версии с подтверждением."
            elif inst.sync_url:
                self.party_chip.setText("◌  Переподключение" if state.get("online") is False else "◌  Подключаемся")
                note = party_connection_text(state)
            else:
                self.party_chip.setText("Пригласить друзей")
                note = "Локальная сборка · создайте пати, чтобы играть вместе."
            self.party_chip.setProperty("connected", bool(inst.id in self.main.hosts or state.get("online")))
            self.party_chip.style().unpolish(self.party_chip)
            self.party_chip.style().polish(self.party_chip)
            self.sync_note.setText(note)
            self.runtime_note.setText("В ИГРЕ  ·  " + playtime_text(inst.playtime))
            running = inst.id in self.main.games
            self.play.setText("■  Остановить" if running else "▶  Играть")
            self.play.setEnabled(not self.main.busy or running)
            self.configure.setEnabled(not self.main.busy and not self.main.is_locked(inst.id))
            self.party_chip.setEnabled(not self.main.busy)
            self.profile.setEnabled(not self.main.busy)
            if self.last_identity != inst.id:
                self.last_identity = inst.id
                self.animate_reveal()

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
        if key == "ocean":
            moon = QColor("#cfe9f2")
            moon.setAlpha(150)
            painter.setBrush(moon)
            painter.drawRect(rect.right() - 9 * unit, rect.top() + 3 * unit, 3 * unit, 3 * unit)
            painter.setBrush(QColor("#5fc9db"))
            for i in range(18):
                x = rect.left() + (i * 79 + variant * 23) % max(1, rect.width())
                y = rect.top() + (i * 17 + 11) % max(1, rect.height() // 2)
                painter.drawRect(x, y, 2, 2)
        if key == "cloud":
            painter.setBrush(QColor(255, 255, 255, 120))
            for index in range(3):
                x = rect.left() + rect.width() * (2 + index * 2) // 9
                y = rect.top() + unit * (1 + index % 2)
                painter.drawRect(x, y, unit * 4, unit * 2)
        if key in ("ember", "paper", "cloud"):
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
        if key == "ocean":
            for level in range(3):
                color = QColor(colors["accent"])
                color.setAlpha(60 + 30 * level)
                painter.setBrush(color)
                y = rect.top() + rect.height() * (7 + level) // 10
                for x in range(rect.left(), rect.right(), unit * 6):
                    painter.drawRect(x + (level % 2) * unit * 2, y, unit * 3, unit)
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
            # The build icon is intentionally not painted on cards; data stays serialized for old profiles.
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
            painter.drawText(QRect(x, rect.top() + 127, width, 18), Qt.AlignmentFlag.AlignVCenter,
                             translate_ui_text(status))
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


    class LocalizedLabel(QLabel):
        """A QLabel that localizes both its initial and later dynamic UI text."""
        def setText(self, text: str) -> None:
            self._mcsync_source_text = text
            super().setText(translate_ui_text(
                text, partial=bool(getattr(self, "_mcsync_allow_partial", False))))

    class LocalizedStatusBar(QStatusBar):
        def showMessage(self, text: str, timeout: int = 0) -> None:
            self._mcsync_source_message = text
            super().showMessage(translate_ui_text(text, partial=True), timeout)

        def clearMessage(self) -> None:
            self._mcsync_source_message = ""
            super().clearMessage()

    def label(text: str = "", kind: str = "", wrap: bool = False) -> QLabel:
        result = LocalizedLabel()
        result.setText(text)
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
        result.setProperty("motionRadius", MotionFeedbackMixin.MOTION_RADII.get(kind, 15))
        result.clicked.connect(callback)
        return result

    def row(*widgets: QWidget) -> QHBoxLayout:
        layout = QHBoxLayout()
        for widget in widgets:
            layout.addWidget(widget)
        return layout

    class MemorySlider(QWidget):
        """Theme-styled, nonlinear RAM slider paired with an exact numeric input."""
        valueChanged = Signal(int)
        slider_steps = 1000

        def __init__(self, title: str, minimum: int, maximum: int, step: int, value: int,
                     parent: QWidget | None = None):
            super().__init__(parent)
            self._title = title
            self._minimum, self._maximum = minimum, maximum
            self.setToolTip("Максимум ограничен физической памятью компьютера. "
                            "Ползунок меняет RAM плавно; точное значение можно ввести справа.")
            layout = QHBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(10)
            self.slider = QSlider(Qt.Orientation.Horizontal, self)
            self.slider.setObjectName("memorySlider")
            self.slider.setRange(0, self.slider_steps)
            self.slider.setSingleStep(2)
            self.slider.setPageStep(48)
            self.slider.setTracking(True)
            self.slider.setMinimumWidth(104)
            self.slider.setAccessibleName(title)
            self.slider.setAccessibleDescription("Нелинейный ползунок оперативной памяти; точное значение доступно в поле справа.")
            self.spinbox = QSpinBox(self)
            self.spinbox.setObjectName("memoryInput")
            self.spinbox.setRange(minimum, maximum)
            self.spinbox.setSingleStep(step)
            self.spinbox.setSuffix(" МБ")
            self.spinbox.setValue(value)
            self.spinbox.setFixedWidth(126)
            self.spinbox.setAccessibleName(title + " в мегабайтах")
            self.slider.setValue(self.position_for_value(self.spinbox.value()))
            self.slider.valueChanged.connect(self._slider_changed)
            self.spinbox.valueChanged.connect(self._spinbox_changed)
            layout.addWidget(self.slider, 1)
            layout.addWidget(self.spinbox)

        def position_for_value(self, value: int) -> int:
            span = self._maximum - self._minimum
            if span <= 0:
                return 0
            fraction = (min(self._maximum, max(self._minimum, int(value))) - self._minimum) / span
            return round(math.sqrt(fraction) * self.slider_steps)

        def value_for_position(self, position: int) -> int:
            span = self._maximum - self._minimum
            if span <= 0:
                return self._minimum
            fraction = min(self.slider_steps, max(0, int(position))) / self.slider_steps
            return round(self._minimum + span * fraction * fraction)

        def _slider_changed(self, position: int) -> None:
            self.spinbox.setValue(self.value_for_position(position))

        def _spinbox_changed(self, value: int) -> None:
            position = self.position_for_value(value)
            if self.slider.value() != position:
                was_blocked = self.slider.blockSignals(True)
                self.slider.setValue(position)
                self.slider.blockSignals(was_blocked)
            self.valueChanged.emit(value)

        def value(self) -> int:
            return self.spinbox.value()

        def setValue(self, value: int) -> None:
            self.spinbox.setValue(value)

        def minimum(self) -> int:
            return self._minimum

        def maximum(self) -> int:
            return self._maximum

    def message(parent: QWidget | None, title: str, text: str, *, question: bool = False) -> bool:
        safe_title = redact(title)
        safe_text = redact(text)
        if not question and parent is not None:
            window = parent.window()
            if hasattr(window, "show_notice"):
                window.show_notice(safe_title, safe_text)
                return False
            status = getattr(window, "statusBar", None)
            if callable(status):
                status().showMessage(f"{safe_title}: {safe_text}", 10_000)
                return False
        # Native confirmation windows are reserved for consequential actions. Validation and
        # operation errors are shown in the main window's inline notice banner instead.
        box = QMessageBox(parent)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setWindowTitle(translate_ui_text(safe_title, partial=True))
        box.setText(translate_ui_text(safe_text, partial=True))
        box.setIcon(QMessageBox.Icon.Question if question else QMessageBox.Icon.Warning)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                               if question else QMessageBox.StandardButton.Ok)
        if question:
            box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _source_text(widget: QWidget, attribute: str, current: str) -> str:
        source = getattr(widget, attribute, None)
        if source is None:
            source = current
            setattr(widget, attribute, source)
        return str(source)

    def localize_widget(widget: QWidget, language: str | None = None) -> None:
        """Translate one widget; dynamic pages are handled as their controls appear."""
        language = language_key(language if language is not None else _UI_LANGUAGE)
        if widget.isWindow() and widget.windowTitle():
            original = _source_text(widget, "_mcsync_source_window_title", widget.windowTitle())
            widget.setWindowTitle(translate_ui_text(original, language))
        if isinstance(widget, QLabel):
            original = _source_text(widget, "_mcsync_source_text", widget.text())
            allow_partial = bool(getattr(widget, "_mcsync_allow_partial", False))
            translated = translate_ui_text(original, language, partial=allow_partial)
            if widget.text() != translated:
                widget.setText(translated)
                widget._mcsync_source_text = original
                if hasattr(widget, "_mcsync_source_tooltip"):
                    widget._mcsync_source_tooltip = original
        if isinstance(widget, QAbstractButton):
            original = _source_text(widget, "_mcsync_source_text", widget.text())
            translated = translate_ui_text(original, language)
            if widget.text() != translated:
                widget.setText(translated)
                widget._mcsync_source_text = original
        if isinstance(widget, QLineEdit) and widget.placeholderText():
            original = _source_text(widget, "_mcsync_source_placeholder", widget.placeholderText())
            widget.setPlaceholderText(translate_ui_text(original, language))
        if isinstance(widget, QSpinBox):
            for attribute, getter, setter in (
                    ("_mcsync_source_suffix", widget.suffix, widget.setSuffix),
                    ("_mcsync_source_prefix", widget.prefix, widget.setPrefix),
                    ("_mcsync_source_special_value_text", widget.specialValueText, widget.setSpecialValueText)):
                current = getter()
                if current:
                    original = _source_text(widget, attribute, current)
                    setter(translate_ui_text(original, language))
        tooltip = widget.toolTip()
        if tooltip:
            original = _source_text(widget, "_mcsync_source_tooltip", tooltip)
            widget.setToolTip(translate_ui_text(original, language))
        accessible = widget.accessibleName()
        if accessible:
            original = _source_text(widget, "_mcsync_source_accessible_name", accessible)
            translated = translate_ui_text(original, language)
            if accessible != translated:
                widget.setAccessibleName(translated)
                widget._mcsync_source_accessible_name = original
        if isinstance(widget, QComboBox):
            original_items = getattr(widget, "_mcsync_source_items", None)
            if original_items is None:
                original_items = []
            if len(original_items) > widget.count():
                original_items = original_items[:widget.count()]
            while len(original_items) < widget.count():
                original_items.append(widget.itemText(len(original_items)))
            widget._mcsync_source_items = original_items
            for index, original in enumerate(original_items):
                widget.setItemText(index, translate_ui_text(original, language))
        if isinstance(widget, QTabWidget):
            original_tabs = getattr(widget, "_mcsync_source_tabs", None)
            if original_tabs is None:
                original_tabs = []
            if len(original_tabs) > widget.count():
                original_tabs = original_tabs[:widget.count()]
            while len(original_tabs) < widget.count():
                index = len(original_tabs)
                original_tabs.append((widget.tabText(index), widget.tabToolTip(index)))
            widget._mcsync_source_tabs = original_tabs
            for index, (title, tooltip_text) in enumerate(original_tabs):
                widget.setTabText(index, translate_ui_text(title, language))
                widget.setTabToolTip(index, translate_ui_text(tooltip_text, language))
        if isinstance(widget, QMenu):
            if not hasattr(widget, "_mcsync_source_menu_title"):
                widget._mcsync_source_menu_title = widget.title()
            if widget.title():
                widget.setTitle(translate_ui_text(widget._mcsync_source_menu_title, language))
            for action in widget.actions():
                if not hasattr(action, "_mcsync_source_text"):
                    action._mcsync_source_text = action.text()
                action.setText(translate_ui_text(action._mcsync_source_text, language))
                if action.toolTip():
                    if not hasattr(action, "_mcsync_source_tooltip"):
                        action._mcsync_source_tooltip = action.toolTip()
                    action.setToolTip(translate_ui_text(action._mcsync_source_tooltip, language))

    def localize_widget_tree(root: QWidget, language: str | None = None) -> None:
        """Apply one language consistently to widget text, controls, tooltips and menus."""
        language = language_key(language if language is not None else _UI_LANGUAGE)
        for widget in [root, *root.findChildren(QWidget)]:
            localize_widget(widget, language)

    _UI_LOCALIZATION_FILTER: QObject | None = None

    def install_ui_localization(app: QApplication) -> None:
        global _UI_LOCALIZATION_FILTER
        if _UI_LOCALIZATION_FILTER is not None:
            return

        class LocalizationFilter(QObject):
            def eventFilter(self, watched: QObject, event: Any) -> bool:
                if event.type() == QEvent.Type.Show and isinstance(watched, QWidget):
                    if watched.isWindow():
                        localize_widget_tree(watched)
                    else:
                        localize_widget(watched)
                return False

        _UI_LOCALIZATION_FILTER = LocalizationFilter(app)
        app.installEventFilter(_UI_LOCALIZATION_FILTER)

    def _icon_pixmap(name: str, color: str, size: int = 32) -> QPixmap:
        """Draw crisp, theme-aware interface icons with Qt paths; no emoji-font glyphs."""
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 32.0, size / 32.0)
        pen = QPen(QColor(color))
        pen.setWidthF(2.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        wash = QColor(color)
        wash.setAlpha(32)
        painter.setBrush(wash)

        def path(points: list[tuple[float, float]], close: bool = False) -> QPainterPath:
            shape = QPainterPath()
            shape.moveTo(*points[0])
            for point in points[1:]:
                shape.lineTo(*point)
            if close:
                shape.closeSubpath()
            return shape

        if name == "overview":
            painter.drawLine(6, 26, 26, 26)
            for x, y, height in ((8, 18, 8), (14, 12, 14), (20, 7, 19)):
                painter.drawRoundedRect(QRect(x, y, 4, height), 1.5, 1.5)
        elif name == "mods":
            painter.drawRoundedRect(QRect(6, 6, 9, 9), 2, 2)
            painter.drawRoundedRect(QRect(17, 6, 9, 9), 2, 2)
            painter.drawRoundedRect(QRect(6, 17, 9, 9), 2, 2)
            painter.drawRoundedRect(QRect(17, 17, 9, 9), 2, 2)
            painter.drawEllipse(QRect(12, 12, 8, 8))
        elif name == "resources":
            painter.drawRoundedRect(QRect(5, 6, 22, 20), 3, 3)
            painter.drawEllipse(QRect(9, 10, 4, 4))
            painter.drawPath(path([(7, 23), (13, 17), (17, 21), (21, 15), (26, 22)]))
        elif name == "shaders":
            painter.drawEllipse(QRect(11, 11, 10, 10))
            for x1, y1, x2, y2 in ((16, 4, 16, 8), (16, 24, 16, 28), (4, 16, 8, 16),
                                  (24, 16, 28, 16), (7.5, 7.5, 10, 10), (22, 22, 24.5, 24.5),
                                  (7.5, 24.5, 10, 22), (22, 10, 24.5, 7.5)):
                painter.drawLine(round(x1), round(y1), round(x2), round(y2))
        elif name == "worlds":
            painter.drawPath(path([(16, 4), (27, 10), (27, 22), (16, 28), (5, 22), (5, 10)], True))
            painter.drawLine(16, 4, 16, 16)
            painter.drawLine(5, 10, 16, 16)
            painter.drawLine(27, 10, 16, 16)
            painter.drawLine(16, 16, 16, 28)
        elif name == "catalog":
            painter.drawEllipse(QRect(5, 5, 16, 16))
            painter.drawLine(18, 18, 27, 27)
            painter.drawLine(13, 9, 13, 17)
            painter.drawLine(9, 13, 17, 13)
        elif name == "console":
            painter.drawRoundedRect(QRect(4, 6, 24, 20), 3, 3)
            painter.drawPath(path([(9, 12), (13, 16), (9, 20)]))
            painter.drawLine(16, 20, 22, 20)
        elif name == "logs":
            painter.drawPath(path([(8, 4), (19, 4), (25, 10), (25, 28), (8, 28)], True))
            painter.drawLine(18, 5, 18, 11)
            painter.drawLine(18, 11, 24, 11)
            painter.drawLine(12, 16, 21, 16)
            painter.drawLine(12, 20, 21, 20)
            painter.drawLine(12, 24, 19, 24)
        elif name == "home":
            painter.drawPath(path([(5, 14), (16, 5), (27, 14)]))
            painter.drawPath(path([(8, 13), (8, 26), (24, 26), (24, 13)]))
            painter.drawPath(path([(14, 26), (14, 19), (18, 19), (18, 26)]))
        elif name == "party":
            painter.drawRoundedRect(QRect(4, 5, 17, 14), 4, 4)
            painter.drawPath(path([(8, 19), (7, 24), (13, 19)]))
            painter.drawRoundedRect(QRect(12, 12, 16, 13), 4, 4)
            painter.drawPath(path([(23, 25), (25, 29), (19, 25)]))
            for x in (8, 12, 16):
                painter.drawEllipse(QRect(x, 11, 2, 2))
            for x in (17, 21, 25):
                painter.drawEllipse(QRect(x, 18, 2, 2))
        elif name == "library":
            for y in (8, 16, 24):
                painter.drawRoundedRect(QRect(5, y - 2, 4, 4), 1, 1)
                painter.drawLine(13, y, 27, y)
        elif name == "filters":
            for y, x in ((8, 12), (16, 21), (24, 15)):
                painter.drawLine(5, y, 27, y)
                painter.drawEllipse(QRect(x - 2, y - 2, 4, 4))
        elif name == "settings":
            painter.drawEllipse(QRect(10, 10, 12, 12))
            painter.drawEllipse(QRect(14, 14, 4, 4))
            for angle in range(0, 360, 45):
                radians = math.radians(angle)
                painter.drawLine(round(16 + 8 * math.cos(radians)), round(16 + 8 * math.sin(radians)),
                                 round(16 + 12 * math.cos(radians)), round(16 + 12 * math.sin(radians)))
        elif name == "build":
            painter.drawPath(path([(16, 4), (27, 10), (27, 22), (16, 28), (5, 22), (5, 10)], True))
            painter.drawLine(16, 4, 16, 16)
            painter.drawLine(5, 10, 16, 16)
            painter.drawLine(27, 10, 16, 16)
            painter.drawLine(16, 16, 16, 28)
        elif name == "accounts":
            painter.drawEllipse(QRect(12, 5, 8, 8))
            painter.drawEllipse(QRect(3, 9, 7, 7))
            painter.drawEllipse(QRect(22, 9, 7, 7))
            painter.drawPath(path([(8, 27), (8, 23), (10, 18), (16, 16), (22, 18), (24, 23), (24, 27)]))
            painter.drawPath(path([(2, 26), (3, 21), (6, 18), (9, 18)]))
            painter.drawPath(path([(23, 18), (26, 18), (29, 21), (30, 26)]))
        elif name == "create":
            painter.drawRoundedRect(QRect(6, 6, 20, 20), 5, 5)
            painter.drawLine(16, 10, 16, 22)
            painter.drawLine(10, 16, 22, 16)
        elif name == "connect":
            painter.drawPath(path([(12, 20), (9, 23), (9, 27), (12, 30), (16, 30), (19, 27)]))
            painter.drawPath(path([(20, 12), (23, 9), (27, 9), (30, 12), (30, 16), (27, 19)]))
            painter.drawPath(path([(12, 20), (20, 12)]))
            painter.drawPath(path([(18, 20), (22, 16)]))
        elif name == "diagnostics":
            painter.drawRoundedRect(QRect(6, 5, 20, 22), 4, 4)
            painter.drawLine(11, 11, 21, 11)
            painter.drawLine(11, 16, 21, 16)
            painter.drawLine(11, 21, 17, 21)
            painter.drawEllipse(QRect(22, 21, 7, 7))
            painter.drawLine(27, 27, 30, 30)
        painter.end()
        return pixmap

    def interface_icon(name: str, color: str = "#9aa5bd", selected_color: str | None = None) -> QIcon:
        """Small vector icons with active-state colors and no emoji or external font dependency."""
        active = selected_color or color
        icon = QIcon()
        for size in (16, 18, 24, 32):
            icon.addPixmap(_icon_pixmap(name, color, size), QIcon.Mode.Normal, QIcon.State.Off)
            icon.addPixmap(_icon_pixmap(name, active, size), QIcon.Mode.Active, QIcon.State.Off)
            icon.addPixmap(_icon_pixmap(name, active, size), QIcon.Mode.Selected, QIcon.State.Off)
            icon.addPixmap(_icon_pixmap(name, color, size), QIcon.Mode.Disabled, QIcon.State.Off)
        return icon

    def build_instance_icon(name: str = "portal", accent: str = "#b9a0ff") -> QIcon:
        """Small, switchable Minecraft-style pixel emblems for instance cards."""
        key = name if name in INSTANCE_ICONS else "portal"
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(Qt.PenStyle.NoPen)

        def rect(x: int, y: int, width: int, height: int, color: str) -> None:
            painter.fillRect(QRect(x, y, width, height), QColor(color))

        dark, shadow = "#171b27", "#252c3a"
        teal, violet = "#4c9998", "#766bb2"
        if key == "portal":
            rect(3, 1, 10, 2, dark)
            rect(2, 3, 2, 10, dark)
            rect(12, 3, 2, 10, dark)
            rect(3, 12, 10, 2, dark)
            rect(4, 2, 8, 2, violet)
            rect(3, 4, 2, 8, violet)
            rect(11, 4, 2, 8, violet)
            rect(4, 11, 8, 2, violet)
            rect(5, 4, 6, 7, teal)
            rect(6, 4, 4, 1, accent)
            rect(6, 10, 4, 1, violet)
        elif key == "sword":
            for step in range(8):
                x, y = 10 - step, 1 + step
                rect(x, y, 2, 2, dark)
                rect(x, y, 1, 1, "#dbe6ed")
            rect(3, 10, 7, 2, shadow)
            rect(4, 11, 2, 4, "#9d714e")
            rect(2, 13, 4, 2, "#c08a5b")
            rect(9, 2, 1, 1, accent)
        elif key == "pickaxe":
            rect(3, 2, 10, 2, dark)
            rect(2, 3, 3, 2, dark)
            rect(11, 3, 3, 2, dark)
            rect(4, 3, 8, 1, accent)
            rect(6, 4, 2, 2, "#b8c7d1")
            for step in range(7):
                rect(8 - step, 5 + step, 2, 1, "#a97855" if step > 3 else "#c29062")
            rect(3, 12, 2, 2, "#a97855")
        elif key == "torch":
            rect(6, 1, 4, 2, "#e9b76d")
            rect(5, 3, 6, 2, "#db8456")
            rect(6, 5, 4, 2, accent)
            rect(7, 7, 2, 7, "#9b6b4c")
            rect(6, 13, 4, 2, "#664c43")
        elif key == "chest":
            rect(2, 4, 12, 2, dark)
            rect(3, 6, 10, 7, "#8b5a3b")
            rect(3, 6, 10, 2, "#bd8050")
            rect(2, 12, 12, 2, dark)
            rect(4, 8, 8, 1, "#d6a365")
            rect(7, 8, 2, 4, "#f0c979")
            rect(7, 9, 2, 1, "#775438")
        elif key == "creeper":
            rect(4, 1, 8, 2, dark)
            rect(3, 3, 10, 9, dark)
            rect(4, 3, 8, 8, "#73a66c")
            rect(5, 5, 2, 2, "#17251e")
            rect(9, 5, 2, 2, "#17251e")
            rect(7, 7, 2, 2, "#26372a")
            rect(6, 9, 4, 2, "#17251e")
            rect(5, 12, 2, 2, dark)
            rect(9, 12, 2, 2, dark)
        elif key == "book":
            rect(2, 2, 6, 12, dark)
            rect(8, 2, 6, 12, dark)
            rect(3, 3, 5, 10, "#9c6caa")
            rect(8, 3, 5, 10, "#546f9b")
            rect(7, 2, 2, 12, "#d0b779")
            rect(4, 5, 3, 1, accent)
            rect(9, 5, 3, 1, "#a8d4c9")
            rect(4, 8, 3, 1, "#d5bfdc")
            rect(9, 8, 3, 1, "#c2d1e7")
        painter.end()
        icon = QIcon()
        for size in (16, 18, 24, 28, 32, 36, 42, 48, 64):
            icon.addPixmap(pixmap.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
                                         Qt.TransformationMode.FastTransformation))
        return icon

    def app_icon(color: str | None = None) -> QIcon:
        """Load the approved flat pixel-portal brand icon with a matching vector fallback."""
        asset = Path(__file__).resolve().parent / "assets" / "app-icon.png"
        icon = QIcon(str(asset))
        return icon if not icon.isNull() else build_instance_icon("portal", color or THEMES[DEFAULT_THEME]["accent"])

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
        logs_scanned = Signal(int, str, object, str)
        catalog_icon_ready = Signal(str, bytes)

    class BackupBridge(QObject):
        progress = Signal(str, object, object)
        finished = Signal(str)

    class TaskProgressIndicator(QWidget):
        """Animated ring that shows the launcher is working, even without a percentage."""

        def __init__(self, parent: QWidget | None = None):
            super().__init__(parent)
            self.setFixedSize(30, 30)
            self.setAccessibleName("Индикатор выполнения")
            self.phase = 0.0
            self.step = 0
            self.accent = QColor("#65dfb7")
            self.track = QColor("#33405a")
            self.timer = QTimer(self)
            self.timer.setInterval(45)
            self.timer.timeout.connect(self.advance)

        def is_animating(self) -> bool:
            return self.timer.isActive()

        def set_colors(self, accent: Any, track: Any) -> None:
            self.accent = QColor(accent)
            self.track = QColor(track)
            self.update()

        def start(self) -> None:
            self.step = 0
            if not self.timer.isActive():
                self.timer.start()
            self.update()

        def stop(self) -> None:
            self.timer.stop()
            self.phase = 0.0
            self.update()

        def advance(self) -> None:
            """Rotate the sweep; a gentler step keeps reduced-motion sessions calm."""
            self.step = (self.step + 1) % 8
            self.phase = (self.phase + (0.06 if not motion_enabled() else 0.19)) % 1.0
            self.update()

        def paintEvent(self, event: Any) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            ring = self.rect().adjusted(4, 4, -4, -4)
            painter.setPen(QPen(self.track, 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(ring)
            painter.setPen(QPen(self.accent, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            start = int(-self.phase * 360 * 16)
            painter.drawArc(ring, start, int(108 * 16))
            painter.setBrush(self.accent)
            painter.setPen(Qt.PenStyle.NoPen)
            radius = ring.width() / 2 - 6
            center = ring.center()
            offset = QPoint(int(center.x() + radius * math.cos(self.phase * 2 * math.pi)),
                            int(center.y() + radius * math.sin(self.phase * 2 * math.pi)))
            painter.drawEllipse(offset, 2, 2)
            painter.end()


    class TaskProgressCard(QFrame):
        """Compact in-window progress card for launch preparation and downloads.

        It replaces the popup progress window: stage, percentage and cancel stay in the
        main window. Launch and download tasks share the widget but use distinct accents.
        """
        cancel_requested = Signal()
        VARIANTS = ("launch", "download")

        def __init__(self, parent: QWidget | None = None):
            super().__init__(parent)
            self.setObjectName("taskProgressCard")
            self.setProperty("progressVariant", "download")
            self.setProperty("progressState", "idle")
            self.variant = "download"
            self.state = "idle"
            layout = QHBoxLayout(self)
            layout.setContentsMargins(12, 9, 12, 9)
            layout.setSpacing(10)
            self.indicator = TaskProgressIndicator(self)
            self.indicator.hide()
            self.stage_label = label("Готово к запуску", "taskStage")
            self.stage_label._mcsync_allow_partial = True
            self.percent_label = label("", "taskPercent")
            self.percent_label.setMinimumWidth(46)
            self.percent_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.bar = QProgressBar()
            self.bar.setObjectName("taskBar")
            self.bar.setRange(0, 1000)
            self.bar.setValue(0)
            self.bar.setMaximumWidth(180)
            self.bar.hide()
            self.cancel_btn = button("Отменить", self.cancel_requested.emit)
            self.cancel_btn.setObjectName("taskCancel")
            self.cancel_btn.hide()
            layout.addWidget(self.indicator)
            layout.addWidget(self.stage_label, 1)
            layout.addWidget(self.bar)
            layout.addWidget(self.percent_label)
            layout.addWidget(self.cancel_btn)

        def set_theme_colors(self, accent: Any, track: Any) -> None:
            self.indicator.set_colors(accent, track)

        def _repolish(self) -> None:
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

        def set_state(self, state: str) -> None:
            self.state = state
            self.setProperty("progressState", state)
            self._repolish()

        def begin(self, variant: str = "download", stage: str = "") -> None:
            """Show the card for a running task; launch and download get distinct accents."""
            self.variant = variant if variant in self.VARIANTS else "download"
            self.setProperty("progressVariant", self.variant)
            self.set_state("running")
            self.set_stage(stage)
            self.last_maximum = 0
            self.set_percent(0, 0)
            self.indicator.show()
            self.indicator.start()
            self.cancel_btn.show()
            self._repolish()

        def set_stage(self, text: str) -> None:
            self.stage_label.setText(text)

        def set_percent(self, value: int, maximum: int = 0) -> None:
            self.last_maximum = int(maximum) if maximum else 0
            if maximum and maximum > 0:
                share = max(0.0, min(1.0, value / maximum))
                self.bar.setRange(0, 1000)
                self.bar.setValue(int(share * 1000))
                self.bar.show()
                self.percent_label.setText(f"{int(share * 100)}%")
            else:
                self.bar.hide()
                self.percent_label.setText("…")

        def finish(self, state: str = "done", *, stage: str = "") -> None:
            self.indicator.stop()
            self.indicator.hide()
            self.bar.hide()
            self.cancel_btn.hide()
            if stage:
                self.set_stage(stage)
            completed = state == "done" and self.last_maximum > 0
            self.percent_label.setText("100%" if completed else "")
            self.set_state(state)

        def is_running(self) -> bool:
            return self.state == "running"


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
            self.network_hint = label("", "warning", True)
            self.network_hint.hide()
            layout.addWidget(self.network_hint)
            self.url.textChanged.connect(self.update_network_hint)
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

        def update_network_hint(self, _text: str = "") -> None:
            hint = party_address_hint(self.url.text())
            self.network_hint.setText(hint)
            self.network_hint.setVisible(bool(hint))

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
        _UNSET = object()

        def __init__(self, folder: str, main: MainWindow):
            super().__init__()
            self.folder, self.main = folder, main
            self._instance: Instance | None = None
            self._instance_id = ""
            self._rows: list[dict[str, Any]] = []
            self._dirty = True
            self._scan_pending = False
            self._generation = 0
            self._locked = False
            self._rendered_instance_id = ""
            self._clear_selection_on_render = False
            self._quick_summary: tuple[int, int] | None = None
            self._summary_pending = False
            self._worker_token = uuid.uuid4().hex
            self._worker_signals = background_worker_signals()
            self._worker_signals.files_ready.connect(self.finish_scan)
            self._worker_signals.summary_ready.connect(self.finish_summary_scan)
            self._worker_signals.updates_ready.connect(self.finish_update_check)
            self._updates: dict[str, dict[str, Any]] = {}
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 5, 0, 0)
            layout.setSpacing(10)
            heading = QHBoxLayout()
            title = {"mods": "Моды", "resourcepacks": "Ресурспаки", "shaderpacks": "Шейдеры", "saves": "Миры"}[folder]
            if folder != "mods":
                heading.addWidget(label(title, "sectionTitle"))
            heading.addStretch()
            self.summary = label("", "muted")
            heading.addWidget(self.summary)
            self.refresh_btn = button("Обновить список", lambda: self.refresh(force=True), "ghost")
            heading.addWidget(self.refresh_btn)
            layout.addLayout(heading)
            self.hint = label("Список загрузится при первом открытии вкладки.", "muted", True)
            self.hint._mcsync_allow_partial = True
            self.hint.setVisible(folder != "mods")
            layout.addWidget(self.hint)
            self.filter_field = QLineEdit()
            self.filter_field.setPlaceholderText("Поиск модов…" if folder == "mods" else "Найти файл…")
            self.filter_field.setClearButtonEnabled(True)
            self.filter_field.setAccessibleName("Поиск модов" if folder == "mods" else "Поиск файлов сборки")
            self.list = DropList()
            self.list.setMouseTracking(True)
            if folder == "mods":
                self.list.setObjectName("modList")
                self.list.setUniformItemSizes(True)
            self.list.setItemDelegate(ModListDelegate(main) if folder == "mods" else FileDelegate(main))
            self.list.setAccessibleName("Установленные моды" if folder == "mods" else "Файлы сборки")
            self.filter_field.textChanged.connect(self.apply_filter)
            self._enabled_filter: str = "all"
            self.list.itemSelectionChanged.connect(self.update_selection_buttons)
            self._editable = False
            self.list.dropped.connect(self.add_paths)
            self.list.itemDoubleClicked.connect(lambda _: self.open_world() if folder == "saves" else self.toggle())
            self.add_btn = button("ZIP мира" if folder == "saves" else "Добавить файл" if folder == "mods" else "Добавить",
                                  self.pick_files)
            self.toggle_btn = button("Переключить" if folder == "mods" else "Включить / выключить", self.toggle)
            self.delete_btn = button("Удалить", self.delete, "danger")
            self.backup_btn = button("Бэкап мира", self.backup)
            if folder != "saves":
                self.backup_btn.hide()
            self.folder_btn = button("Папка mods" if folder == "mods" else "Открыть папку", self.open_folder)
            self.download_btn: QPushButton | None = None
            self.mod_details: QLabel | None = None
            self.folder_import_btn: QPushButton | None = None
            if folder == "mods":
                self.refresh_btn.hide()
                self.filter_field.setMinimumWidth(0)
                files_column = QVBoxLayout()
                files_column.setContentsMargins(0, 0, 0, 0)
                files_column.setSpacing(7)
                self._status_tabs = QHBoxLayout()
                self._status_tabs.setSpacing(6)
                self._status_buttons: dict[str, QPushButton] = {}
                for key, label_text in (("all", "Все"), ("enabled", "Включены"), ("disabled", "Отключены")):
                    btn = QPushButton(label_text)
                    btn.setObjectName("modStatusTab")
                    btn.setCheckable(True)
                    btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    btn.setFixedHeight(28)
                    btn.clicked.connect(lambda _=False, k=key: self._set_enabled_filter(k))
                    self._status_tabs.addWidget(btn)
                    self._status_buttons[key] = btn
                self._status_tabs.addStretch()
                self._status_count_label = label("", "muted")
                self._status_tabs.addWidget(self._status_count_label)
                files_column.addLayout(self._status_tabs)
                files_column.addWidget(self.filter_field)
                columns = QHBoxLayout()
                columns.setContentsMargins(39, 0, 13, 0)
                columns.setSpacing(0)
                columns.addWidget(label("МОД", "kicker"), 1)
                version_header = label("ВЕРСИЯ", "kicker")
                version_header.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                version_header.setFixedWidth(88)
                date_header = label("ИЗМЕНЁН", "kicker")
                date_header.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                date_header.setFixedWidth(112)
                columns.addWidget(version_header)
                columns.addWidget(date_header)
                files_column.addLayout(columns)
                files_column.addWidget(self.list, 1)
                self.download_btn = button("Скачать моды", self.open_catalog, "primary")
                self.download_btn.setAccessibleName("Открыть каталог модов")
                self.add_btn.setToolTip("Выбрать файл мода .jar с компьютера")
                side = QFrame()
                side.setObjectName("modActions")
                side.setMinimumWidth(190)
                side.setMaximumWidth(230)
                side_layout = QVBoxLayout(side)
                side_layout.setContentsMargins(12, 12, 12, 12)
                side_layout.setSpacing(8)
                side_layout.addWidget(self.download_btn)
                side_layout.addWidget(self.add_btn)
                divider = QFrame()
                divider.setObjectName("sidebarDivider")
                divider.setFixedHeight(1)
                side_layout.addWidget(divider)
                side_layout.addWidget(self.toggle_btn)
                side_layout.addWidget(self.delete_btn)
                self.update_btn = button("Обновить мод", self._update_selected_mod, "primary")
                self.update_btn.setVisible(False)
                self.update_btn.setAccessibleName("Обновить выбранный мод")
                side_layout.addWidget(self.update_btn)
                self.changelog_btn = button("Чейнджлог", self._show_selected_changelog, "ghost")
                self.changelog_btn.setVisible(False)
                side_layout.addWidget(self.changelog_btn)
                self._selected_update_info: dict[str, Any] | None = None
                side_layout.addWidget(self.folder_btn)
                side_layout.addSpacing(7)
                side_layout.addWidget(label("СВЕДЕНИЯ", "kicker"))
                self.mod_details = label("Выберите мод, чтобы посмотреть сведения.", "muted", True)
                self.mod_details.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
                side_layout.addWidget(self.mod_details)
                content = QHBoxLayout()
                content.setSpacing(12)
                content.addLayout(files_column, 1)
                content.addWidget(side)
                layout.addLayout(content, 1)
            else:
                layout.addWidget(self.filter_field)
                layout.addWidget(self.list, 1)
                if folder == "saves":
                    self.folder_import_btn = button("Папка мира", self.pick_world_folder)
                    actions = row(self.add_btn, self.folder_import_btn, self.backup_btn, self.delete_btn, self.folder_btn)
                    self.toggle_btn.hide()
                else:
                    actions = row(self.add_btn, self.toggle_btn, self.delete_btn, self.folder_btn)
                    self.backup_btn.hide()
                layout.addLayout(actions)

        def set_context(self, inst: Instance | None, locked: bool = False) -> None:
            instance_id = inst.id if inst else ""
            if instance_id != self._instance_id:
                self._instance_id = instance_id
                self._instance = inst
                self._rows = []
                self._quick_summary = None
                self._generation += 1
                self._scan_pending = False
                self._summary_pending = False
                self._dirty = True
                self._clear_selection_on_render = True
            else:
                self._instance = inst
            self._locked = locked
            self.update_controls()

        def mark_dirty(self) -> None:
            self._dirty = True
            self._quick_summary = None
            self._generation += 1
            self._scan_pending = False
            self._summary_pending = False

        def refresh(self, inst: Instance | None | object = _UNSET, locked: bool | None = None, *, force: bool = False) -> None:
            if inst is not self._UNSET or locked is not None:
                self.set_context(self._instance if inst is self._UNSET else inst,
                                 self._locked if locked is None else locked)
            if force:
                self.mark_dirty()
            if not self._instance:
                self._rows = []
                self._quick_summary = (0, 0)
                self._dirty = False
                self._scan_pending = False
                self._summary_pending = False
                self.render_rows([])
                self.update_controls()
                self.set_default_hint()
                return
            if not self._dirty:
                if self._rendered_instance_id != self._instance_id:
                    self.render_rows(self._rows)
                self.update_controls()
                self.set_default_hint()
                return
            if self._scan_pending:
                self.update_controls()
                return
            if self._rendered_instance_id != self._instance_id:
                self.render_rows([])
                self._rendered_instance_id = ""
            self._scan_pending = True
            generation, inst_snapshot = self._generation, self._instance
            folder = self.folder
            worker_signals, worker_token = self._worker_signals, self._worker_token
            self.hint.setText("Загружаем список файлов в фоне…")
            self.update_controls()

            def scan() -> None:
                def publish(rows: list[dict[str, Any]], error: str) -> None:
                    worker_signals.files_ready.emit(worker_token, generation, rows, error)

                try:
                    root = inst_snapshot.game_dir / folder
                    rows = []
                    if root.is_symlink():
                        raise UserError(f"Символические ссылки не поддерживаются: {root.name}")
                    if folder == "saves":
                        if root.exists():
                            for path in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
                                if path.is_symlink():
                                    raise UserError(f"Символические ссылки не поддерживаются: {path.name}")
                                if path.is_dir():
                                    rows.append({"relative": path.name, "name": path.name, "enabled": True,
                                                 "kind": "МИР", "size": 0,
                                                 "description": "Папка мира · двойной клик — открыть"})
                    else:
                        for relative, path in iter_files(root):
                            stat_result = path.stat()
                            size = stat_result.st_size
                            enabled = not relative.endswith(".disabled")
                            name = relative.removesuffix(".disabled")
                            row_data = {"relative": relative, "name": name, "enabled": enabled,
                                        "kind": "JAR" if folder == "mods" else "ZIP", "size": size,
                                        "description": f"{'Включён' if enabled else 'Отключён'} · {human_size(size)}"}
                            if folder == "mods":
                                title, version = jar_mod_identity(path) if name.casefold().endswith(".jar") else ("", "")
                                row_data.update(display_name=title or Path(name).stem,
                                                version=version or "—",
                                                icon=jar_mod_icon(path) if name.casefold().endswith(".jar") else None,
                                                updated=time.strftime("%d.%m.%Y", time.localtime(stat_result.st_mtime)))
                            rows.append(row_data)
                        if folder == "mods":
                            rows.sort(key=lambda item: (str(item.get("display_name", item["name"])).casefold(),
                                                        item["relative"].casefold()))
                    publish(rows, "")
                except Exception as exc:
                    publish([], redact(str(exc)) or type(exc).__name__)

            threading.Thread(target=scan, name=f"MCSync-files-{folder}", daemon=True).start()

        @Slot(str, int, object, str)
        def finish_scan(self, worker_token: str, generation: int, rows: list[dict[str, Any]], error: str) -> None:
            if (worker_token != self._worker_token or generation != self._generation or
                    self._instance_id != self.main.current_id()):
                return
            self._scan_pending = False
            active = (self.main.main_pages.currentWidget() is self.main.detail_stack and
                      self.main.detail_stack.currentWidget() is self.main.details and
                      self.main.tabs.currentWidget() is self)
            if error:
                self._dirty = True
                if active:
                    self.update_controls()
                    self.hint.setText("Не удалось прочитать папку: " + error)
                    self.summary.setText("Файлов: —")
                if (self.main.current_id() == self._instance_id and
                        self.main.main_pages.currentWidget() is self.main.detail_stack):
                    self.main.update_summary(self._instance)
                return
            self._rows = rows
            self._dirty = False
            self._quick_summary = None
            if active:
                self.render_rows(rows)
                self.update_controls()
                self.set_default_hint()
            else:
                self._rendered_instance_id = ""
            if self.main.current_id() == self._instance_id and self.main.main_pages.currentWidget() is self.main.detail_stack:
                self.main.update_summary(self._instance)
            if self.folder == "mods" and not error and rows:
                self._start_update_check()

        def _start_update_check(self) -> None:
            inst = self._instance
            if not inst or inst.sync_url:
                return
            generation, worker_signals, worker_token = self._generation, self._worker_signals, self._worker_token

            def check() -> None:
                try:
                    updates: dict[str, dict[str, Any]] = {}
                    mr_tracker = read_json(inst.directory / "modrinth.json", {})
                    cf_tracker = read_json(inst.directory / "curseforge.json", {})
                    if isinstance(mr_tracker, dict):
                        with ModrinthClient() as client:
                            for pid, info in mr_tracker.items():
                                if not isinstance(info, dict):
                                    continue
                                installed_vid = info.get("version_id", "")
                                path = info.get("path", "")
                                try:
                                    latest = client.latest(pid, inst)
                                    if latest.get("id") and latest["id"] != installed_vid:
                                        entry: dict[str, Any] = {
                                            "provider": "modrinth", "project_id": pid,
                                            "latest_version": latest.get("version_number", ""),
                                            "latest_name": latest.get("name", ""),
                                            "changelog": latest.get("changelog", ""),
                                            "path": path,
                                        }
                                        if path:
                                            updates[path] = entry
                                except Exception:
                                    pass
                    if isinstance(cf_tracker, dict):
                        api_key = self.main.store.settings.get("curseforge_api_key", "")
                        if api_key:
                            try:
                                with CurseForgeClient(api_key) as client:
                                    for key, info in cf_tracker.items():
                                        if not isinstance(info, dict):
                                            continue
                                        installed_fid = info.get("file_id", "")
                                        project_id = info.get("project_id", 0)
                                        path = info.get("path", "")
                                        if not project_id:
                                            continue
                                        try:
                                            latest = client.latest_file(int(project_id), inst, "mod")
                                            if latest.get("id") and latest["id"] != installed_fid:
                                                updates[path or key] = {
                                                    "provider": "curseforge", "project_id": project_id,
                                                    "latest_version": latest.get("displayName", ""),
                                                    "latest_name": latest.get("displayName", ""),
                                                    "changelog": latest.get("changelog", ""),
                                                    "path": path,
                                                }
                                        except Exception:
                                            pass
                            except Exception:
                                pass
                    worker_signals.updates_ready.emit(worker_token, generation, updates)
                except Exception:
                    worker_signals.updates_ready.emit(worker_token, generation, {})

            threading.Thread(target=check, name="MCSync-update-check", daemon=True).start()

        @Slot(str, int, object)
        def finish_update_check(self, worker_token: str, generation: int, updates: dict[str, Any]) -> None:
            if worker_token != self._worker_token or generation != self._generation:
                return
            self._updates = updates if isinstance(updates, dict) else {}
            self._apply_update_badges()

        def _apply_update_badges(self) -> None:
            for i in range(self.list.count()):
                item = self.list.item(i)
                data = item.data(int(Qt.ItemDataRole.UserRole) + 1) or {}
                relative = item.data(Qt.ItemDataRole.UserRole) or ""
                has_update = relative in self._updates
                if has_update:
                    data["update_available"] = True
                    data["update_info"] = self._updates[relative]
                else:
                    data.pop("update_available", None)
                    data.pop("update_info", None)
                item.setData(int(Qt.ItemDataRole.UserRole) + 1, data)
            self.list.viewport().update()

        def render_rows(self, rows: list[dict[str, Any]]) -> None:
            selection = set() if self._clear_selection_on_render else set(self.selected())
            self._clear_selection_on_render = False
            scroll = self.list.verticalScrollBar().value()
            self.list.blockSignals(True)
            self.list.clear()
            for row_data in rows:
                relative = row_data["relative"]
                if self.folder == "saves":
                    item = QListWidgetItem(row_data["name"])
                    display_data = {"name": row_data["name"], "enabled": row_data["enabled"],
                                    "kind": row_data["kind"], "description": row_data["description"]}
                    tooltip = relative
                elif self.folder == "mods":
                    title = row_data.get("display_name") or row_data["name"]
                    version = row_data.get("version", "—")
                    updated = row_data.get("updated", "—")
                    status = "Включён" if row_data["enabled"] else "Отключён"
                    item = QListWidgetItem(f"{title} · {version} · {updated}")
                    display_data = dict(row_data)
                    tooltip = (f"{title}\nВерсия: {version}\nИзменён: {updated}\n"
                               f"Файл: {relative}\\nРазмер: {human_size(row_data.get('size', 0))} · {status}")
                else:
                    enabled = row_data["enabled"]
                    size = row_data["size"]
                    item = QListWidgetItem(f"{'●' if enabled else '○'}  {relative}   ·   {human_size(size)}")
                    display_data = {"name": row_data["name"], "enabled": row_data["enabled"],
                                    "kind": row_data["kind"], "description": row_data["description"]}
                    tooltip = relative
                item.setData(Qt.ItemDataRole.UserRole, relative)
                item.setData(int(Qt.ItemDataRole.UserRole) + 1, display_data)
                item.setToolTip(tooltip)
                self.list.addItem(item)
            for i in range(self.list.count()):
                item = self.list.item(i)
                item.setSelected(item.data(Qt.ItemDataRole.UserRole) in selection)
            self.list.blockSignals(False)
            self.list.verticalScrollBar().setValue(scroll)
            self._rendered_instance_id = self._instance_id
            self.summary.setText(f"Файлов: {self.list.count()}")
            self.apply_filter()

        def set_default_hint(self) -> None:
            inst = self._instance
            managed = bool(inst and inst.sync_url and self.folder != "saves")
            self.hint.setText("Этими файлами управляет хост. Изменения вносите у него." if managed else
                              "Перетащите папку/ZIP мира сюда." if self.folder == "saves" else
                              "Перетащите сюда .jar / .zip. Выключенные файлы имеют суффикс .disabled.")

        def update_controls(self) -> None:
            inst, locked = self._instance, self._locked
            managed = bool(inst and inst.sync_url and self.folder != "saves")
            files_ready = bool(inst) and not self._dirty and not self._scan_pending
            editable = files_ready and not locked and not managed
            for widget in (self.add_btn, self.toggle_btn, self.delete_btn):
                widget.setEnabled(editable)
            if self.folder_import_btn:
                self.folder_import_btn.setEnabled(editable)
            self.backup_btn.setEnabled(bool(inst) and not locked)
            self.folder_btn.setEnabled(bool(inst))
            self.refresh_btn.setEnabled(bool(inst) and not locked and not self._scan_pending)
            if self.download_btn is not None:
                self.download_btn.setEnabled(bool(inst) and not locked and not managed and not self.main.busy)
            self.list.setEnabled(files_ready)
            self.list.setAcceptDrops(editable)
            self._editable = editable
            self.update_selection_buttons()

        def request_summary_scan(self) -> None:
            if not self._instance or self._summary_pending or self._scan_pending or self._quick_summary is not None:
                return
            self._summary_pending = True
            generation, inst_snapshot, folder = self._generation, self._instance, self.folder
            worker_signals, worker_token = self._worker_signals, self._worker_token

            def scan_summary() -> None:
                root = inst_snapshot.game_dir / folder
                result = (0, quick_world_count(root)) if folder == "saves" else quick_file_counts(root)
                worker_signals.summary_ready.emit(worker_token, generation, result)

            threading.Thread(target=scan_summary, name=f"MCSync-summary-{folder}", daemon=True).start()

        @Slot(str, int, object)
        def finish_summary_scan(self, worker_token: str, generation: int, result: tuple[int, int]) -> None:
            if (worker_token != self._worker_token or generation != self._generation or
                    self._instance_id != self.main.current_id()):
                return
            self._summary_pending = False
            self._quick_summary = result
            if (self.main.current_id() == self._instance_id and
                    self.main.detail_stack.currentWidget() is self.main.details):
                self.main.update_summary(self._instance)

        def summary_counts(self) -> tuple[int, int] | None:
            if not self._instance:
                return 0, 0
            if not self._dirty and not self._scan_pending:
                if self.folder == "saves":
                    return 0, len(self._rows)
                total = len(self._rows)
                enabled = sum(bool(row.get("enabled", True)) for row in self._rows)
                return enabled, total
            if self._quick_summary is None:
                self.request_summary_scan()
            return self._quick_summary

        def world_count(self) -> int | None:
            counts = self.summary_counts()
            return counts[1] if counts is not None else None

        def _set_enabled_filter(self, key: str) -> None:
            self._enabled_filter = key
            for k, btn in self._status_buttons.items():
                btn.setChecked(k == key)
            self.apply_filter()

        def apply_filter(self, *args: Any) -> None:
            query = self.filter_field.text().casefold()
            enabled_key = getattr(self, "_enabled_filter", "all")
            shown = 0
            total_enabled, total_disabled = 0, 0
            for i in range(self.list.count()):
                item = self.list.item(i)
                data = item.data(int(Qt.ItemDataRole.UserRole) + 1) or {}
                searchable = " ".join(str(data.get(key, "")) for key in
                                      ("name", "display_name", "version", "updated", "relative"))
                text_match = query in searchable.casefold()
                enabled = data.get("enabled", True)
                if enabled:
                    total_enabled += 1
                else:
                    total_disabled += 1
                status_match = (enabled_key == "all" or
                                (enabled_key == "enabled" and enabled) or
                                (enabled_key == "disabled" and not enabled))
                visible = text_match and status_match
                item.setHidden(not visible)
                if not visible:
                    item.setSelected(False)
                shown += int(visible)
            noun = "Модов" if self.folder == "mods" else "Файлов"
            self.summary.setText(f"{noun}: {shown} / {self.list.count()}" if query or enabled_key != "all" else f"{noun}: {self.list.count()}")
            if hasattr(self, "_status_buttons"):
                self._status_buttons["all"].setText(f"Все ({self.list.count()})")
                self._status_buttons["enabled"].setText(f"Включены ({total_enabled})")
                self._status_buttons["disabled"].setText(f"Отключены ({total_disabled})")
            self.update_selection_buttons()

        def update_selection_buttons(self) -> None:
            selected_items = self.list.selectedItems()
            selected = bool(selected_items)
            self.toggle_btn.setEnabled(self._editable and selected)
            self.delete_btn.setEnabled(self._editable and selected)
            if self.mod_details is None:
                return
            if not selected_items:
                self.mod_details.setText("Выберите мод, чтобы посмотреть сведения.")
                return
            if len(selected_items) > 1:
                self.mod_details.setText(f"Выбрано модов: {len(selected_items)}")
                return
            data = selected_items[0].data(int(Qt.ItemDataRole.UserRole) + 1) or {}
            lines = [
                f"{data.get('display_name') or data.get('name', '')}",
                f"Версия: {data.get('version', '—')}",
                f"Изменён: {data.get('updated', '—')}",
                f"Файл: {data.get('relative', '')}",
                f"Размер: {human_size(data.get('size', 0))} · "
                f"{'включён' if data.get('enabled', True) else 'отключён'}",
            ]
            if data.get("update_available"):
                info = data["update_info"]
                lines.append(f"\n⬆ Обновление: {info.get('latest_version', '—')}")
            self.mod_details.setText("\n".join(lines))
            if hasattr(self, "update_btn"):
                has_update = bool(data.get("update_available"))
                self.update_btn.setVisible(has_update)
                self._selected_update_info = data.get("update_info") if has_update else None
                if hasattr(self, "changelog_btn"):
                    self.changelog_btn.setVisible(has_update and bool(self._selected_update_info and self._selected_update_info.get("changelog")))

        def selected(self) -> list[str]:
            return [item.data(Qt.ItemDataRole.UserRole) for item in self.list.selectedItems()]

        def open_catalog(self) -> None:
            if self.folder == "mods":
                self.main.open_mod_catalog()

        def _update_selected_mod(self) -> None:
            info = self._selected_update_info
            if not info:
                return
            inst = self._instance
            if not inst:
                return
            provider = info.get("provider", "")
            project_id = info.get("project_id")
            if not project_id:
                return
            try:
                if provider == "modrinth":
                    install_modrinth(inst, str(project_id))
                elif provider == "curseforge":
                    api_key = self.main.store.settings.get("curseforge_api_key", "")
                    if not api_key:
                        raise UserError("Для CurseForge укажите API-ключ в Настройки → CurseForge.")
                    install_curseforge(inst, int(project_id), "mod", api_key)
                else:
                    raise UserError("Неизвестный источник мода.")
                self.refresh(force=True)
                self.main.statusBar().showMessage("Мод обновлён.", 5000)
            except UserError as exc:
                message(self.main, "Не удалось обновить мод", str(exc))

        def _show_selected_changelog(self) -> None:
            info = self._selected_update_info
            if not info or not info.get("changelog"):
                return
            title = info.get("latest_name") or info.get("project_id", "Мод")
            changelog = str(info["changelog"])
            dlg = QDialog(self.main)
            dlg.setWindowTitle(f"Чейнджлог — {title}")
            dlg.resize(520, 400)
            layout = QVBoxLayout(dlg)
            layout.addWidget(label(f"Чейнджлог {title}", "title"))
            text = QPlainTextEdit()
            text.setReadOnly(True)
            text.setPlainText(changelog or "Нет описания изменений.")
            layout.addWidget(text, 1)
            layout.addWidget(button("Закрыть", dlg.accept))
            dlg.exec()

        def pick_files(self) -> None:
            if self.folder == "saves":
                paths, _ = QFileDialog.getOpenFileNames(self, "ZIP мира", filter="ZIP (*.zip)")
            elif self.folder == "mods":
                paths, _ = QFileDialog.getOpenFileNames(
                    self, "Добавить файлы модов", filter="Моды Minecraft (*.jar *.jar.disabled);;JAR (*.jar);;Все файлы (*)")
            else:
                paths, _ = QFileDialog.getOpenFileNames(
                    self, "Добавить файлы", filter="Ресурспаки и шейдеры (*.zip *.zip.disabled);;Все файлы (*)")
            if paths:
                self.add_paths([Path(path) for path in paths])

        def pick_world_folder(self) -> None:
            path = QFileDialog.getExistingDirectory(self, "Папка мира")
            if path:
                self.add_paths([Path(path)])

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
                        suffix = source.name.casefold()
                        if self.folder == "mods" and not suffix.endswith((".jar", ".jar.disabled")):
                            raise UserError("В mods можно добавлять только .jar или .jar.disabled.")
                        if self.folder != "mods" and not suffix.endswith((".zip", ".zip.disabled")):
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
            title = name + (" · " + translate_ui_text("Вы") if data.get("self") else "") + (
                " · " + translate_ui_text("хост") if data.get("role") == "host" else "")
            painter.drawText(content, Qt.AlignmentFlag.AlignVCenter,
                             painter.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, content.width()))
            font.setBold(False)
            font.setPixelSize(11)
            painter.setFont(font)
            healthy = success_color(self.main.theme)
            painter.setPen(QColor(healthy if data.get("ready") else colors["warning"]))
            content.translate(0, 20)
            painter.drawText(content, Qt.AlignmentFlag.AlignVCenter,
                             painter.fontMetrics().elidedText(
                                 translate_ui_text(data.get("caption", ""), partial=True),
                                 Qt.TextElideMode.ElideRight, content.width()))
            painter.restore()

    class PartyPanel(QFrame):
        """A real roster, not a decorative online counter. All untrusted text is plain."""
        def __init__(self, main: MainWindow):
            super().__init__()
            self.main = main
            self.setMinimumWidth(0)
            self.setObjectName("partyCard")
            layout = QVBoxLayout(self)
            layout.setContentsMargins(18, 16, 18, 16)
            layout.setSpacing(8)
            heading = QHBoxLayout()
            heading.setSpacing(8)
            self.status_dot = QLabel("●")
            self.status_dot.setFixedWidth(16)
            self.status_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.status_dot.setStyleSheet(f"color: {THEMES[main.theme]['muted']}; font-size: 14px;")
            heading.addWidget(self.status_dot)
            self.title = ElidedLabel("Пати с друзьями")
            self.title.setObjectName("sectionTitle")
            heading.addWidget(self.title, 1)
            self.badge = label("Постоянная ссылка", "badge")
            layout.addLayout(heading)
            layout.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignLeft)
            self.rename = button("Моё имя", main.show_settings, "ghost")
            self.action = button("Пригласить друзей", main.summary_sync_action)
            self.action.setAccessibleName("Приглашение или обновление пати")
            self.connection = label("", "muted", True)
            self.connection._mcsync_allow_partial = True
            self.connection.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(self.connection)
            self.lan_notice = label("", "warning", True)
            self.lan_notice._mcsync_allow_partial = True
            self.lan_notice.setTextFormat(Qt.TextFormat.PlainText)
            self.lan_notice.hide()
            layout.addWidget(self.lan_notice)
            self.lan_btn = button("Доп. параметры LAN", main.show_advanced_lan, "ghost")
            self.lan_btn.hide()
            layout.addWidget(self.lan_btn, 0, Qt.AlignmentFlag.AlignLeft)
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
            self.explanation._mcsync_allow_partial = True
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
                self.main.show_connection_help()

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
                self.title.setText("Пати с друзьями")
                self.badge.setText("Сначала выберите сборку")
                self.badge.setProperty("status", "local")
                self.badge.setProperty("connected", False)
                self.badge.style().unpolish(self.badge)
                self.badge.style().polish(self.badge)
                self.status_dot.setStyleSheet("color: #97a2ba; font-size: 14px;")
                self.connection.setText("Откройте библиотеку, чтобы создать сборку или подключиться к другу.")
                self.roster.clear()
                self.roster.hide()
                self.explanation.setText("Ваша пати остаётся приватной; ссылки-приглашения отправляйте только друзьям.")
                self.action.setText("Открыть библиотеку")
                self.action.setEnabled(not self.main.busy)
                self.lan_notice.hide()
                self.lan_btn.hide()
                self.repair.hide()
                self.rename.setEnabled(not self.main.busy)
                self._roster_key = None
                return
            state = self.main.party_states.get(inst.id, {})
            host = self.main.hosts.get(inst.id)
            room = host.party_snapshot() if host else state.get("room") if state.get("online") else None
            is_host = bool(host)
            online = is_host or state.get("online") is True
            connected = bool(inst.sync_url)
            local_owner = not connected
            self.lan_btn.setVisible(local_owner)
            self.lan_btn.setEnabled(local_owner and not self.main.busy and not self.main.is_locked(inst.id))
            if is_host:
                endpoint = self.main.lan_endpoint(inst)
                self.lan_notice.setText(
                    f"Minecraft LAN подтверждён вручную · {endpoint}. Если мир закрыт, откройте его в Minecraft через Esc → Открыть для сети."
                    if endpoint else
                    "Раздача сборки активна, но открытие мира Minecraft по LAN не подтверждено. В игре нажмите Esc → Открыть для сети; порт укажите в параметрах LAN.")
                self.lan_notice.show()
            else:
                self.lan_notice.hide()
            self.title.setText("Вы — хост пати" if is_host else "Ваша пати" if connected else "Пати с друзьями")
            self.badge.setText(f"● {len(room['members'])} в сети" if room else "● Хост в сети" if online else
                               "Переподключение…" if state.get("online") is False else
                               "Подключаемся…" if connected else "Постоянная ссылка")
            self.badge.setProperty("status", "linked" if online else "pending" if connected else "local")
            self.badge.setProperty("connected", online)
            self.badge.style().unpolish(self.badge)
            self.badge.style().polish(self.badge)
            dot_color = "#65dfb7" if online else "#e6c744" if connected else "#97a2ba"
            self.status_dot.setStyleSheet(f"color: {dot_color}; font-size: 14px;")
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
                        item_title = peer["name"] + (" · " + translate_ui_text("Вы") if peer["id"] == own_id else "") + (
                            " · " + translate_ui_text("хост") if peer["role"] == "host" else "")
                        item = QListWidgetItem(item_title + " — " + translate_ui_text(caption, partial=True))
                        item.setData(int(Qt.ItemDataRole.UserRole) + 1, data)
                        self.roster.addItem(item)
                self.resize_roster()
            if connected and online and state.get("supported") is False:
                explanation = "Хост использует старый MCSync. Связь проверяется автоматически; для списка друзей обновите его до 0.3.0+."
            elif connected and not online and state.get("error_kind") == "private_address":
                explanation = ("В приглашении локальный IP: он доступен только в той же LAN/VPN. "
                               "Для другой сети используйте IP хоста в общей VPN; если вы уже в сети, "
                               "разрешите входящий TCP-порт пати в брандмауэре хоста.")
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
            self.main = main
            self.setWindowTitle("Помощь с подключением к пати")
            self.resize(520, 390)
            layout = QVBoxLayout(self)
            inst = main.current_instance()
            state = main.party_states.get(inst.id, {}) if inst else {}
            private_address = state.get("error_kind") == "private_address"
            if private_address:
                self.resize(580, 480)
            layout.addWidget(label("Проверьте адрес хоста" if private_address else "Пати сохранена", "title"))
            if private_address and inst:
                layout.addWidget(label(party_address_hint(inst.sync_url), "warning", True))
                steps = (("1. Общая сеть", ("Для друга из другой сети подключите оба компьютера к одной VPN "
                                               "(например, Tailscale или Radmin) и используйте VPN-IP хоста.")),
                         ("2. Хост", ("Оставьте MCSync открытым и разрешите входящий TCP-порт пати "
                                      "в брандмауэре на интерфейсе LAN/VPN.")),
                         ("3. Приглашение", ("Замените ссылку на адрес из VPN. MCSync не является облачным "
                                              "ретранслятором и автоматически не обходит NAT; HTTP-порт не следует открывать "
                                              "в интернет без понимания рисков.")))
            else:
                layout.addWidget(label("MCSync уже переподключается сам. Повторно нажимать «Проверить» не нужно.", "muted", True))
                steps = (("1. Хост", "У друга должен быть открыт MCSync и включена пати."),
                         ("2. Общая сеть", "Вы должны видеть LAN/VPN-адрес хоста. Порт пати — не порт Minecraft-сервера."),
                         ("3. Приглашение", "Если адрес или секрет поменялся, замените приглашение — файлы и миры сохранятся."))
            for title, text in steps:
                layout.addWidget(label(title, "sectionTitle"))
                layout.addWidget(label(text, "muted", True))
            actions = QHBoxLayout()
            if inst and inst.sync_url:
                actions.addWidget(button("Заменить приглашение…", main.change_invitation))
            actions.addWidget(button("Диагностика", main.show_diagnostics, "ghost"))
            actions.addWidget(button("Назад к пати", main.back_from_subpage, "ghost"))
            layout.addLayout(actions)

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
            self.lan_notice = label("", "warning", True)
            layout.addWidget(self.lan_notice)
            layout.addWidget(button("Доп. параметры LAN", self.open_lan_properties, "ghost"))
            form = QFormLayout()
            self.radmin_ip = detect_radmin_vpn_ipv4()
            saved_address = settings.get("address", "")
            try:
                saved_ip = ipaddress.ip_address(saved_address)
                if saved_ip.is_private and saved_address != self.radmin_ip:
                    saved_address = ""
            except ValueError:
                pass
            initial_address = self.radmin_ip or saved_address
            self.address = QLineEdit(initial_address)
            self.address.setPlaceholderText("IP Radmin VPN или общий VPN-IP")
            self.radmin_btn = button(f"Использовать IP Radmin VPN · {self.radmin_ip or 'не найден'}",
                                     self.use_radmin_address, "ghost")
            self.radmin_btn.setToolTip("Подставить IPv4-адрес адаптера Radmin VPN в приглашение.")
            self.address_hint = label("", "warning", True)
            self.port = QSpinBox()
            self.port.setRange(1024, 65535)
            self.port.setValue(settings.get("port", 25589))
            form.addRow("IP/DNS для друзей", self.address)
            form.addRow("", self.radmin_btn)
            form.addRow("", self.address_hint)
            form.addRow("HTTP-порт", self.port)
            self.address.textChanged.connect(self.update_address_hint)
            self.port.valueChanged.connect(self.update_address_hint)
            self.update_address_hint()
            layout.addLayout(form)
            share_card = QFrame()
            share_card.setObjectName("card")
            share_layout = QVBoxLayout(share_card)
            share_layout.setContentsMargins(16, 14, 16, 14)
            share_layout.setSpacing(8)
            share_layout.addWidget(label("Папки для передачи друзьям", "sectionTitle"))
            share_layout.addWidget(label(
                "Выбранные папки синхронизируются участникам пати. Миры и аккаунты не передаются; "
                "проверьте конфиги на пароли и токены.", "muted", True))
            self.folders = {}
            folder_names = {"mods": "Моды", "config": "Конфиги",
                            "resourcepacks": "Ресурспаки", "shaderpacks": "Шейдеры"}
            folder_help = {
                "mods": "Файлы модов. Строгий режим убирает у друзей лишние .jar только из этой папки.",
                "config": "Настройки модов и игры. Проверьте, что здесь нет паролей или токенов.",
                "resourcepacks": "Текстуры и ресурспаки (.zip).",
                "shaderpacks": "Шейдер-паки (.zip).",
            }
            folder_rows = (QHBoxLayout(), QHBoxLayout())
            for index, folder in enumerate(SYNC_FOLDERS):
                box = QCheckBox(folder_names[folder])
                box.setAccessibleName(f"Передавать папку {folder_names[folder]} друзьям")
                box.setToolTip(folder_help[folder])
                box.setChecked(folder in settings.get("folders", SYNC_FOLDERS))
                box.toggled.connect(self.update_folder_settings)
                self.folders[folder] = box
                folder_rows[index // 2].addWidget(box)
            for folder_row in folder_rows:
                folder_row.addStretch(1)
                share_layout.addLayout(folder_row)
            self.folder_hint = label("", "muted", True)
            share_layout.addWidget(self.folder_hint)
            layout.addWidget(share_card)

            self.autostart = QCheckBox("Восстанавливать пати при следующем открытии MCSync")
            self.autostart.setChecked(settings.get("auto_start", True) is True)
            layout.addWidget(self.autostart)
            self.advanced_toggle = button("Строгий режим и исключения  ▾", self.toggle_advanced, "ghost")
            layout.addWidget(self.advanced_toggle)
            self.advanced = QWidget()
            advanced_layout = QVBoxLayout(self.advanced)
            advanced_layout.setContentsMargins(0, 0, 0, 0)
            self.strict = QCheckBox("Удалять у друзей лишние .jar и .jar.disabled в папке «Моды»")
            self.strict.setChecked(settings.get("strict", True))
            advanced_layout.addWidget(self.strict)
            self.strict_hint = label("В строгом режиме состав модов у друзей совпадает с хостом.", "muted", True)
            advanced_layout.addWidget(self.strict_hint)
            advanced_layout.addWidget(label("Исключения (маски fnmatch, одна на строку)"))
            self.excludes = QPlainTextEdit("\n".join(settings.get("excludes", ["*.part", "*.tmp"])))
            self.excludes.setMaximumHeight(95)
            advanced_layout.addWidget(self.excludes)
            layout.addWidget(self.advanced)
            self.advanced.hide()
            self.update_folder_settings()
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
            layout.addWidget(button("Назад к пати", self.main.back_from_subpage, "ghost"))
            self.refresh()

        def open_lan_properties(self) -> None:
            self.main.show_advanced_lan(return_to=self)

        def toggle_advanced(self) -> None:
            show = not self.advanced.isVisible()
            self.advanced.setVisible(show)
            self.advanced_toggle.setText("Строгий режим и исключения  ▴" if show else
                                         "Строгий режим и исключения  ▾")

        def update_folder_settings(self, *_args: Any) -> None:
            mods_selected = self.folders["mods"].isChecked()
            active = self.inst.id in self.main.hosts
            if not mods_selected and self.strict.isChecked():
                self.strict.setChecked(False)
            self.strict.setEnabled(mods_selected and not active and not self.main.busy)
            self.strict_hint.setText(
                "В строгом режиме у друзей удаляются лишние моды .jar из папки «Моды»." if mods_selected else
                "Строгий режим недоступен без папки «Моды»: её содержимое не будет проверяться и изменяться.")
            selected = any(box.isChecked() for box in self.folders.values())
            self.folder_hint.setText("Выберите хотя бы одну папку для передачи." if not selected else
                                     "Папку «Моды» можно отключить; строгий режим при этом выключается автоматически.")
            for box in self.folders.values():
                box.setEnabled(not active and not self.main.busy)
            if hasattr(self, "start_btn"):
                self.start_btn.setEnabled(not active and not self.main.busy and selected and bool(self.address.text().strip()))

        def use_radmin_address(self) -> None:
            if self.radmin_ip and not self.main.hosts.get(self.inst.id):
                self.address.setText(self.radmin_ip)
                self.state_label.setText("Используется IP Radmin VPN. Создайте пати и отправьте новое приглашение.")

        def update_address_hint(self, _value: Any = None) -> None:
            hint = party_address_hint(self.address.text(), default_port=self.port.value())
            self.address_hint.setText(hint)
            self.address_hint.setVisible(bool(hint))
            self.radmin_btn.setVisible(bool(self.radmin_ip and self.address.text().strip() != self.radmin_ip))
            if hasattr(self, "folders") and hasattr(self, "strict"):
                self.update_folder_settings()

        def refresh(self) -> None:
            host = self.main.hosts.get(self.inst.id)
            active = host is not None
            self.start_btn.setEnabled(not active and not self.main.busy)
            self.stop_btn.setEnabled(active)
            self.copy_btn.setEnabled(active)
            for widget in (self.address, self.port, self.autostart, self.strict, self.excludes, *self.folders.values()):
                widget.setEnabled(not active)
            self.radmin_btn.setEnabled(not active and not self.main.busy)
            invitation = ""
            if host:
                address = self.address.text().strip()
                if address:
                    try:
                        invitation = host.url(address)
                    except (UserError, ValueError):
                        pass
                self.url_field.setText(invitation)
                self.copy_btn.setEnabled(bool(invitation))
            else:
                self.url_field.clear()
            if host and invitation:
                state_text = "Пати открыта. Отправьте приглашение один раз; друзья переподключатся сами."
            elif host:
                state_text = ("Пати запущена, но приглашение не сформировано. Остановите её, укажите IP Radmin VPN "
                              "или адрес общей VPN-сети и создайте пати заново.")
            else:
                state_text = "Нажмите «Создать пати», затем скопируйте приглашение. Для Radmin используйте VPN-IP."
            self.state_label.setText(state_text)
            endpoint = self.main.lan_endpoint(self.inst)
            self.lan_notice.setText(
                f"Minecraft LAN подтверждён вручную · {endpoint}. MCSync не проверяет и не открывает игровой порт."
                if endpoint else
                "Создание пати не открывает мир Minecraft. В игре нажмите Esc → Открыть для сети; затем укажите порт в параметрах LAN.")
            self.update_folder_settings()

        def start_host(self) -> None:
            selected_folders = [p for p, box in self.folders.items() if box.isChecked()]
            if not self.address.text().strip():
                self.state_label.setText("Укажите IP Radmin VPN или другой общей VPN-сети; домашний LAN-IP не подставляется автоматически.")
                return
            if not selected_folders:
                self.folder_hint.setText("Выберите хотя бы одну папку для передачи.")
                return
            settings = {"address": self.address.text().strip(), "port": self.port.value(),
                        "auto_start": self.autostart.isChecked(),
                        "strict": self.strict.isChecked() and "mods" in selected_folders,
                        "folders": selected_folders,
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
            invitation = self.url_field.text().strip()
            if not invitation:
                return
            QApplication.clipboard().setText(invitation)
            self.state_label.setText("Ссылка скопирована. Отправьте её только друзьям, которым доверяете.")

    class AdvancedLanPropertiesPage(QWidget):
        """Minecraft LAN details are separate from MCSync's party file-sync port."""
        def __init__(self, main: MainWindow):
            super().__init__()
            self.main = main
            self.instance_id = ""
            self.radmin_ip = detect_radmin_vpn_ipv4()
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 4, 0, 0)
            layout.setSpacing(12)
            layout.addWidget(label("Дополнительные параметры LAN", "title"))
            layout.addWidget(label(
                "MCSync раздаёт файлы сборки отдельно. Чтобы друзья вошли в ваш мир, откройте его в Minecraft: "
                "Esc → Открыть для сети. Порт появится в игровом чате.", "muted", True))
            card = QFrame()
            card.setObjectName("card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(18, 16, 18, 16)
            form = QFormLayout()
            self.address = QLineEdit()
            self.address.setPlaceholderText("IP Radmin VPN, например 26.x.x.x")
            self.address.setAccessibleName("IP для подключения к миру по LAN")
            self.port = QSpinBox()
            self.port.setRange(0, 65535)
            self.port.setSpecialValueText("Не указан")
            self.port.setValue(0)
            self.port.setAccessibleName("Порт Minecraft LAN из игрового чата")
            form.addRow("IP Radmin VPN", self.address)
            form.addRow("Порт мира", self.port)
            card_layout.addLayout(form)
            self.world_opened = QCheckBox("Я открыл мир в Minecraft через «Открыть для сети»")
            self.world_opened.setAccessibleName("Подтвердить, что мир открыт для сети")
            self.world_opened.toggled.connect(self.set_world_opened)
            card_layout.addWidget(self.world_opened)
            self.state = label("", "warning", True)
            self.state._mcsync_allow_partial = True
            card_layout.addWidget(self.state)
            layout.addWidget(card)
            actions = QHBoxLayout()
            self.save_btn = button("Сохранить", self.save, "primary")
            self.copy_btn = button("Скопировать IP:порт", self.copy_endpoint)
            self.copy_btn.setEnabled(False)
            actions.addWidget(self.save_btn)
            actions.addWidget(self.copy_btn)
            actions.addStretch()
            actions.addWidget(button("Назад", main.back_from_subpage, "ghost"))
            layout.addLayout(actions)
            layout.addStretch(1)
            self.address.textChanged.connect(self.update_state)
            self.port.valueChanged.connect(self.update_state)

        def refresh(self) -> None:
            inst = self.main.current_instance()
            self.instance_id = inst.id if inst else ""
            settings = self.main.store.settings
            address = settings.get("minecraft_lan_address", "")
            if not isinstance(address, str):
                address = ""
            try:
                saved_ip = ipaddress.ip_address(address)
                if saved_ip.is_private and address != self.radmin_ip:
                    address = ""
            except ValueError:
                pass
            address = self.radmin_ip or address
            port = settings.get("minecraft_lan_port", 0)
            if type(port) is not int or not 0 <= port <= 65535:
                port = 0
            self.address.blockSignals(True)
            self.port.blockSignals(True)
            self.world_opened.blockSignals(True)
            self.address.setText(address)
            self.port.setValue(port)
            self.world_opened.setChecked(bool(inst and inst.id in self.main.lan_open_confirmed))
            self.address.blockSignals(False)
            self.port.blockSignals(False)
            self.world_opened.blockSignals(False)
            editable = bool(inst and not inst.sync_url and not self.main.busy and not self.main.is_locked(inst.id))
            self.address.setEnabled(editable)
            self.port.setEnabled(editable)
            self.world_opened.setEnabled(editable)
            self.save_btn.setEnabled(editable)
            self.update_state()

        def _endpoint_from_fields(self) -> str:
            inst = self.main.current_instance()
            address = self.address.text().strip()
            port = self.port.value()
            if (not inst or inst.sync_url or not self.world_opened.isChecked() or not address or not port or
                    any(char.isspace() or char in "/?#@" for char in address)):
                return ""
            host = f"[{address}]" if ":" in address and not address.startswith("[") else address
            return f"{host}:{port}"

        def update_state(self, *_args: Any) -> None:
            inst = self.main.current_instance()
            if not inst:
                self.state.setText("Сначала выберите сборку в библиотеке.")
                self.copy_btn.setEnabled(False)
                return
            if inst.sync_url:
                self.state.setText("Открыть мир может только хост. Попросите у него Radmin VPN-IP и порт Minecraft.")
                self.copy_btn.setEnabled(False)
                return
            if not self.world_opened.isChecked():
                self.state.setText("Мир не подтверждён как открытый. В игре нажмите Esc → Открыть для сети.")
            elif not self.port.value():
                self.state.setText("Мир отмечен открытым. Укажите порт, который Minecraft показал в чате.")
            elif not self.address.text().strip():
                self.state.setText("Укажите IP Radmin VPN; домашний LAN-IP не подставляется автоматически.")
            else:
                endpoint = self._endpoint_from_fields()
                self.state.setText(f"Адрес для друзей: {endpoint}. MCSync не проверяет порт и не меняет firewall/NAT.")
            self.copy_btn.setEnabled(bool(self._endpoint_from_fields()))

        def set_world_opened(self, opened: bool) -> None:
            if not self.instance_id:
                return
            if opened:
                if not self.save():
                    self.world_opened.blockSignals(True)
                    self.world_opened.setChecked(False)
                    self.world_opened.blockSignals(False)
                    return
                self.main.lan_open_confirmed.add(self.instance_id)
            else:
                self.main.lan_open_confirmed.discard(self.instance_id)
            self.update_state()
            inst = self.main.current_instance()
            if inst:
                self.main.party_panel.refresh(inst)
                self.main.lobby_page.refresh(inst)

        def save(self) -> bool:
            address = self.address.text().strip()
            if address and (len(address) > 253 or any(char.isspace() or char in "/?#@" for char in address)):
                self.main.show_notice("Проверьте IP", "Введите IP или DNS без порта и пробелов.")
                return False
            settings = self.main.store.settings
            previous = dict(settings)
            settings["minecraft_lan_address"] = address
            settings["minecraft_lan_port"] = self.port.value()
            try:
                self.main.store.save_settings()
            except OSError as exc:
                settings.clear()
                settings.update(previous)
                self.main.show_notice("Не удалось сохранить", redact(str(exc)))
                return False
            self.update_state()
            inst = self.main.current_instance()
            if inst:
                self.main.party_panel.refresh(inst)
                self.main.lobby_page.refresh(inst)
            return True

        def copy_endpoint(self) -> None:
            endpoint = self._endpoint_from_fields()
            if not endpoint:
                self.update_state()
                return
            QApplication.clipboard().setText(endpoint)
            self.main.show_notice("LAN-адрес скопирован", "Передайте его игрокам в своей Radmin VPN-сети.")

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

        def setText(self, text: str) -> None:
            self._mcsync_source_text = text
            super().setText(translate_ui_text(text))

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
            self.resize(780, 520)
            root = QVBoxLayout(self)
            root.setContentsMargins(18, 14, 18, 12)
            root.setSpacing(12)
            root.addWidget(label("Аккаунты", "title"))
            columns = QHBoxLayout()
            columns.setSpacing(12)
            left_card = QFrame()
            left_card.setObjectName("card")
            left_card_layout = QVBoxLayout(left_card)
            left_card_layout.setContentsMargins(12, 12, 12, 12)
            left_card_layout.setSpacing(8)
            self.list = QListWidget()
            self.list.setObjectName("accountList")
            self.list.currentItemChanged.connect(self.selected_changed)
            left_card_layout.addWidget(self.list, 1)
            self.offline_name = QLineEdit()
            self.offline_name.setMaxLength(16)
            self.offline_name.setPlaceholderText("Ник: 3–16 латинских букв, цифр или _")
            self.offline_name.returnPressed.connect(self.add_offline)
            left_card_layout.addWidget(self.offline_name)
            left_card_layout.addLayout(row(button("Добавить офлайн", self.add_offline), button("Войти с Microsoft", self.add_microsoft)))
            left_card_layout.addLayout(row(button("Выбрать", self.select), button("Удалить", self.remove, "danger")))
            columns.addWidget(left_card, 1)
            right_card = QFrame()
            right_card.setObjectName("card")
            right_card_layout = QVBoxLayout(right_card)
            right_card_layout.setContentsMargins(12, 12, 12, 12)
            right_card_layout.setSpacing(8)
            right_card_layout.addWidget(label("Скин", "sectionTitle"))
            self.skin = SkinPreview()
            right_card_layout.addWidget(self.skin)
            self.slim = QCheckBox("Модель Slim (Alex)")
            self.slim.toggled.connect(self.set_slim)
            right_card_layout.addWidget(self.slim)
            right_card_layout.addLayout(row(button("Открыть PNG", self.open_png), button("Скин Microsoft", self.fetch_skin)))
            columns.addWidget(right_card)
            root.addLayout(columns, 1)
            root.addWidget(label("Офлайн-аккаунт не проходит авторизацию на online-mode серверах. "
                                 "Локальный PNG — только предпросмотр, скин в игре не подменяется. "
                                 "Microsoft-токены хранятся локально в accounts.json без шифрования.", "warning", True))
            root.addWidget(button("Готово", self.accept))
            self.refresh()

        def current(self) -> dict[str, Any] | None:
            item = self.list.currentItem()
            return item.data(Qt.ItemDataRole.UserRole) if item else None

        def refresh(self) -> None:
            self.list.clear()
            accent = THEMES[self.main.theme]["accent"]
            for account in self.main.accounts.data["accounts"]:
                selected = account["id"] == self.main.accounts.data["selected"]
                is_ms = account["type"] == "microsoft"
                type_label = "Microsoft • Java Edition" if is_ms else "Офлайн"
                prefix = "★ " if selected else ""
                item = QListWidgetItem(f"{prefix}{account['name']}\n{type_label}")
                item.setData(Qt.ItemDataRole.UserRole, account)
                icon_name = "accounts" if is_ms else "home"
                item.setIcon(interface_icon(icon_name, THEMES[self.main.theme]["muted"], accent))
                self.list.addItem(item)
                if selected:
                    self.list.setCurrentItem(item)
            self.list.setIconSize(QSize(24, 24))
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
            name = self.offline_name.text().strip()
            if not name:
                self.offline_name.setFocus()
                return
            try:
                self.main.accounts.add_offline(name)
                self.offline_name.clear()
                self.refresh()
            except UserError as exc:
                message(self, "Не удалось добавить аккаунт", str(exc))

        def add_microsoft(self) -> None:
            dialog = MicrosoftLoginDialog(self.main.store.settings.get("client_id", ""), self)

            def saved(page: MicrosoftLoginDialog) -> QWidget:
                if page.account:
                    self.main.accounts.put(page.account)
                    self.refresh()
                return self

            self.main.show_inline_dialog("microsoft_login", dialog, title="Вход Microsoft",
                                         nav_key="accounts", return_to=self, on_accept=saved,
                                         keep_previous=True)

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
            self.resize(720, 620)
            root = QVBoxLayout(self)
            root.setContentsMargins(18, 14, 18, 12)
            root.addWidget(label(f"Настройки · MCSync {APP_VERSION}", "title"))

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            content = QWidget()
            sections = QVBoxLayout(content)
            sections.setContentsMargins(2, 2, 10, 2)
            sections.setSpacing(10)

            def section(title: str) -> tuple[QVBoxLayout, QFormLayout]:
                frame = QFrame()
                frame.setObjectName("card")
                card_layout = QVBoxLayout(frame)
                card_layout.setContentsMargins(16, 14, 16, 14)
                card_layout.setSpacing(9)
                card_layout.addWidget(label(title, "sectionTitle"))
                form = QFormLayout()
                form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
                form.setHorizontalSpacing(16)
                form.setVerticalSpacing(8)
                card_layout.addLayout(form)
                sections.addWidget(frame)
                return card_layout, form

            appearance_layout, appearance_form = section("Оформление")
            self.theme_field = QComboBox()
            for key, info in THEMES.items():
                swatch = QPixmap(20, 20)
                swatch.fill(Qt.GlobalColor.transparent)
                sp = QPainter(swatch)
                sp.setRenderHint(QPainter.RenderHint.Antialiasing)
                sp.setPen(Qt.PenStyle.NoPen)
                sp.setBrush(QColor(info["accent"]))
                sp.drawRoundedRect(0, 0, 20, 20, 5, 5)
                sp.end()
                self.theme_field.addItem(QIcon(swatch), info["name"], key)
            self.theme_field.setCurrentIndex(max(0, self.theme_field.findData(main.theme)))
            self.layout_field = QComboBox()
            for key, text in LAYOUTS.items():
                self.layout_field.addItem(text, key)
            self.layout_field.setCurrentIndex(max(0, self.layout_field.findData(main.layout_mode)))
            self.language_field = QComboBox()
            self.language_field.addItem("Русский", "ru")
            self.language_field.addItem("English", "en")
            self.language_field.setCurrentIndex(max(0, self.language_field.findData(main.language)))
            appearance_form.addRow("Тема", self.theme_field)
            self.theme_hint = label("", "muted", True)

            def refresh_theme_hint(_index: int = 0) -> None:
                self.theme_hint.setText(translate_ui_text(THEMES[theme_key(self.theme_field.currentData())]["description"]))

            self.theme_field.currentIndexChanged.connect(refresh_theme_hint)
            refresh_theme_hint()
            appearance_form.addRow("", self.theme_hint)
            appearance_form.addRow("Компоновка", self.layout_field)
            appearance_form.addRow("Язык", self.language_field)
            self.reduced_motion = QCheckBox("Уменьшить анимации и переходы")
            self.reduced_motion.setChecked(bool(main.store.settings.get("reduced_motion", False)))
            appearance_layout.addWidget(self.reduced_motion)

            _, party_form = section("Пати")
            self.party_name_field = QLineEdit(main.store.settings.get("party_name", ""))
            self.party_name_field.setMaxLength(32)
            self.party_name_field.setPlaceholderText("Имя, которое увидят друзья")
            party_form.addRow("Ваше имя", self.party_name_field)

            services_layout, services_form = section("Вход и каталоги")
            self.client_id = QLineEdit(main.store.settings.get("client_id", ""))
            self.client_id.setPlaceholderText("Свой Azure Application (Client) ID")
            services_form.addRow("Microsoft Client ID", self.client_id)
            self.curseforge_key_field = QLineEdit(main.store.settings.get("curseforge_api_key", ""))
            self.curseforge_key_field.setAccessibleName("Персональный API-ключ CurseForge")
            self.curseforge_key_field.setPlaceholderText("Личный API-ключ CurseForge")
            self.curseforge_key_field.setEchoMode(QLineEdit.EchoMode.Password)
            services_form.addRow("CurseForge API-ключ", self.curseforge_key_field)
            self.curseforge_key_reveal = QCheckBox("Показать API-ключ")
            self.curseforge_key_reveal.toggled.connect(lambda shown: self.curseforge_key_field.setEchoMode(
                QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password))
            services_group = services_layout
            services_group.addWidget(self.curseforge_key_reveal)
            services_group.addWidget(label("Нужен ваш собственный ключ. Он хранится локально и используется только для запросов к CurseForge.",
                                           "muted", True))
            services_group.addWidget(button("CurseForge for Studios", lambda:
                                            QDesktopServices.openUrl(QUrl("https://console.curseforge.com/")), "ghost"))
            services_group.addWidget(label("Для Microsoft требуется собственный public-client Azure Client ID. Пароль вводится только на сайте Microsoft.",
                                           "muted", True))
            services_group.addWidget(button("Регистрация Microsoft-приложения", lambda:
                                            QDesktopServices.openUrl(QUrl("https://aka.ms/AppRegInfo")), "ghost"))

            _, memory_form = section("Память")
            self.ram = MemorySlider("RAM новых сборок", 256, physical_memory_mb(), 256,
                                    int(main.store.settings.get("default_ram", 4096)))
            memory_form.addRow("RAM новых сборок", self.ram)

            data_layout, _ = section("Данные и диагностика")
            data_layout.addWidget(label("Папка данных: " + str(main.store.root), "muted", True))
            data_layout.addLayout(row(button("Открыть папку данных", lambda: open_path(main.store.root)),
                                      button("Диагностика", main.show_diagnostics)))
            data_layout.addWidget(label("Ctrl+N — библиотека · Ctrl+F — поиск · Ctrl+S — сохранить · F1 — диагностика",
                                        "muted", True))
            data_layout.addWidget(label("Независимый проект; не связан с Mojang/Microsoft или PolyMC/Prism.",
                                        "muted", True))
            sections.addStretch(1)
            scroll.setWidget(content)
            root.addWidget(scroll, 1)

            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
            buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
            buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
            buttons.accepted.connect(self.save)
            buttons.rejected.connect(self.reject)
            root.addWidget(buttons)

        def save(self) -> None:
            chosen = self.theme_field.currentData()
            chosen_language = language_key(self.language_field.currentData())
            try:
                alias = party_name(self.party_name_field.text())
                curseforge_key = validate_curseforge_api_key(self.curseforge_key_field.text())
            except UserError as exc:
                message(self, "Проверьте настройки", str(exc))
                return
            settings = self.main.store.settings
            previous = dict(settings)
            settings.update(reduced_motion=self.reduced_motion.isChecked(), party_name=alias,
                            client_id=self.client_id.text().strip(), curseforge_api_key=curseforge_key,
                            default_ram=self.ram.value(), theme=chosen, layout=self.layout_field.currentData(),
                            language=chosen_language)
            try:
                self.main.store.save_settings()
            except OSError as exc:
                settings.clear()
                settings.update(previous)
                message(self, "Не удалось сохранить настройки", str(exc))
                return
            QApplication.instance().setProperty("reducedMotion", self.reduced_motion.isChecked())
            if self.reduced_motion.isChecked():
                self.main.main_pages.disable_motion()
                self.main.overview_stack.disable_motion()
                self.main.detail_stack.disable_motion()
                self.main.tabs.disable_motion()
                self.main.lobby_page.disable_motion()
            self.main.set_theme(chosen)
            self.main.set_layout_mode(self.layout_field.currentData())
            self.main.set_language(chosen_language)
            localize_widget_tree(self, chosen_language)
            self.main.update_catalog_controls()
            self.main.party_monitor.refresh()
            self.main.refresh_party_state()
            self.accept()

    class MainWindow(QMainWindow):
        def __init__(self, store: Store, *, network_enabled: bool = True, theme: str | None = None, layout: str | None = None):
            super().__init__()
            self.setStatusBar(LocalizedStatusBar(self))
            self.store, self.accounts = store, Accounts(store)
            self.language = set_ui_language(store.settings.get("language", "ru"))
            application = QApplication.instance()
            application.setProperty("uiLanguage", self.language)
            install_ui_localization(application)
            application.setProperty("reducedMotion", bool(store.settings.get("reduced_motion", False)))
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
            self.bridge.catalog_icon_ready.connect(self.catalog_icon_loaded)
            self._catalog_icon_cache: OrderedDict[str, QImage] = OrderedDict()
            self._catalog_icon_pending: set[str] = set()
            self._catalog_icon_queue: queue.Queue[str | None] = queue.Queue()
            self._catalog_icon_stop = threading.Event()
            self._catalog_icon_workers: list[threading.Thread] = []
            self.bridge.task_done.connect(self.task_done)
            self.bridge.progress.connect(self.task_progress)
            self.bridge.confirm_sync.connect(self.on_confirm_sync)
            self.bridge.update_check_done.connect(self.on_update_check)
            self.bridge.logs_scanned.connect(self.logs_scan_done)
            self.bridge.game_output.connect(self.on_game_output)
            self.bridge.game_finished.connect(self.on_game_finished)
            self.hosts: dict[str, SyncHost] = {}
            self.lan_open_confirmed: set[str] = set()
            self.games: dict[str, GameSession] = {}
            self.buffers: dict[str, list[str]] = {}
            self.update_badges: set[str] = set()
            self.checking = False
            self.closing = False
            self.busy = False
            self.task: dict[str, Any] | None = None
            self.task_number = 0
            self.loaded_id = ""
            self.logs_dirty = True
            self.logs_dirty_instances: set[str] = set()
            self.logs_instance = ""
            self.logs_entries: list[tuple[str, str]] = []
            self.logs_error = ""
            self.logs_generation = 0
            self.logs_pending = False
            self.logs_pending_instance = ""
            self.logs_rescan_requested = False
            self.logs_rendered_instance = ""
            self.logs_selected_path = ""
            self.setWindowTitle(f"MCSync {APP_VERSION} — сборки для друзей")
            self.setWindowIcon(app_icon(THEMES[self.theme]["accent"]))
            self.resize(1280, 860)
            self.setMinimumSize(1000, 690)
            central = QWidget()
            central.setObjectName("central")
            self.setCentralWidget(central)
            outer = QVBoxLayout(central)
            outer.setContentsMargins(18, 18, 18, 6)
            outer.setSpacing(0)
            splitter = QSplitter(Qt.Orientation.Horizontal)
            self.workspace_splitter = splitter
            splitter.setChildrenCollapsible(False)
            self.sidebar = QFrame()
            self.sidebar.setObjectName("sidebar")
            self.sidebar.setMinimumWidth(225)
            self.sidebar.setMaximumWidth(275)
            left_layout = QVBoxLayout(self.sidebar)
            left_layout.setContentsMargins(14, 12, 14, 8)
            left_layout.setSpacing(3)
            brand_row = QHBoxLayout()
            self.brand_icon = label()
            self.brand_icon.setPixmap(app_icon(THEMES[self.theme]["accent"]).pixmap(28, 28))
            self.brand_icon.setFixedSize(36, 36)
            self.brand_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            brand_row.addWidget(self.brand_icon)
            self.brand_label = label("MCSync", "brand")
            brand_row.addWidget(self.brand_label)
            brand_row.addStretch()
            left_layout.addLayout(brand_row)
            left_layout.addSpacing(6)
            self.nav_buttons: dict[str, QPushButton] = {}

            def add_nav(key: str, title: str, icon_name: str, callback: Callable) -> QPushButton:
                nav = button(title, callback, "nav")
                nav.setIcon(interface_icon(icon_name, THEMES[self.theme]["muted"], THEMES[self.theme]["accent"]))
                nav.setIconSize(QSize(19, 19))
                nav.setFixedHeight(40)
                nav.setCheckable(True)
                nav.setProperty("iconName", icon_name)
                nav.setProperty("navKey", key)
                nav.setAccessibleName(title)
                nav.setToolTip(title)
                left_layout.addWidget(nav)
                self.nav_buttons[key] = nav
                return nav

            self.home_btn = add_nav("home", "Главная", "home", self.show_lobby)
            self.library_btn = add_nav("library", "Библиотека", "library", self.show_library)
            self.party_btn = add_nav("party", "Пати", "party", self.show_party)
            separator = QFrame()
            separator.setObjectName("sidebarDivider")
            separator.setFixedHeight(1)
            left_layout.addSpacing(4)
            left_layout.addWidget(separator)
            self.accounts_btn = add_nav("accounts", "Аккаунты", "accounts", self.show_accounts)
            left_layout.addStretch(1)
            separator2 = QFrame()
            separator2.setObjectName("sidebarDivider")
            separator2.setFixedHeight(1)
            left_layout.addWidget(separator2)
            left_layout.addSpacing(4)
            self.settings_btn = add_nav("settings", "Настройки", "settings", self.show_settings)
            self.search = QLineEdit()
            self.search.setPlaceholderText("Поиск сборки…")
            self.search.setClearButtonEnabled(True)
            self.search.setAccessibleName("Поиск сборки")
            self.groups = QComboBox()
            self.groups.addItem("Все группы", None)
            self.groups.setAccessibleName("Группа сборок")
            self.groups.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            self.groups.setMinimumContentsLength(12)
            self.filter_toggle = button("Фильтры ▾", self.toggle_filters, "ghost")
            self.filter_toggle.setFixedHeight(38)
            self.groups.hide()
            self.sort_combo = QComboBox()
            for text, value in (("Избранное сначала", "favorite"), ("По названию", "name"), ("Недавно играли", "recent")):
                self.sort_combo.addItem(text, value)
            self.sort_combo.setCurrentIndex(max(0, self.sort_combo.findData(store.settings.get("sort"))))
            self.sort_combo.setAccessibleName("Порядок сборок")
            self.sort_combo.hide()
            self.instances = QListWidget(self)
            self.instances.setObjectName("instances")
            self.instances.setIconSize(QSize(42, 42))
            self.instances.setItemDelegate(InstanceDelegate(self))
            self.instances.setMouseTracking(True)
            self.instances.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.instances.setMinimumHeight(50)
            self.instances.setAccessibleName("Внутренний выбор сборки")
            self.instances.currentItemChanged.connect(self.on_instance_changed)
            self.instances.itemDoubleClicked.connect(lambda _: self.launch())
            self.instances.hide()
            self.count_label = label("", "muted")
            self.new_btn = button("+  Создать сборку", self.create_instance, "primary")
            self.connect_btn = button("Подключиться к другу", self.connect_instance, "ghost")
            self.import_btn = button("Импорт .mrpack / ZIP", self.import_instance, "ghost")
            for widget in (self.new_btn, self.connect_btn, self.import_btn):
                widget.setFixedHeight(40)
            self.sidebar_layout = left_layout
            self.library_expanded = True
            splitter.addWidget(self.sidebar)

            workspace = QWidget()
            workspace_layout = QVBoxLayout(workspace)
            workspace_layout.setContentsMargins(8, 0, 0, 0)
            workspace_layout.setSpacing(10)
            header = QHBoxLayout()
            self.page_title = label("Библиотека", "pageTitle")
            header.addWidget(self.page_title)
            header.addStretch()
            self.account_combo = QComboBox(workspace)
            self.account_combo.setMinimumWidth(155)
            self.account_combo.setMaximumWidth(230)
            self.account_combo.setAccessibleName("Аккаунт для запуска Minecraft")
            self.account_combo.currentIndexChanged.connect(self.account_changed)
            self.account_combo.hide()
            self.header_widget = QWidget()
            self.header_widget.setLayout(header)
            workspace_layout.addWidget(self.header_widget)
            self.notice_banner = QFrame()
            self.notice_banner.setObjectName("noticeBanner")
            notice_layout = QHBoxLayout(self.notice_banner)
            notice_layout.setContentsMargins(12, 8, 8, 8)
            notice_layout.setSpacing(12)
            notice_copy = QVBoxLayout()
            notice_copy.setSpacing(2)
            self.notice_title = label("", "sectionTitle")
            self.notice_body = label("", "muted", True)
            self.notice_body.setTextFormat(Qt.TextFormat.PlainText)
            notice_copy.addWidget(self.notice_title)
            notice_copy.addWidget(self.notice_body)
            notice_layout.addLayout(notice_copy, 1)
            self.notice_close = button("×", self.clear_notice, "ghost")
            self.notice_close.setAccessibleName("Скрыть сообщение")
            self.notice_close.setFixedSize(34, 34)
            notice_layout.addWidget(self.notice_close, 0, Qt.AlignmentFlag.AlignTop)
            self.notice_banner.hide()
            workspace_layout.addWidget(self.notice_banner)
            self.notice_timer = QTimer(self)
            self.notice_timer.setSingleShot(True)
            self.notice_timer.timeout.connect(self.clear_notice)
            self.recovery_label = label("", "notice", True)
            self.recovery_label.hide()
            workspace_layout.addWidget(self.recovery_label)
            self.main_pages = FadeStack()
            self.library_page = self.build_library_page()
            self.main_pages.addWidget(self.library_page)
            self.detail_stack = FadeStack()
            self.empty_page = self.build_empty_page()
            self.detail_stack.addWidget(self.empty_page)
            self.details = QWidget()
            detail_layout = QVBoxLayout(self.details)
            detail_layout.setContentsMargins(0, 0, 0, 0)
            detail_layout.setSpacing(13)
            self.hero = HeroFrame(self.theme)
            hero_layout = QVBoxLayout(self.hero)
            hero_layout.setContentsMargins(20, 18, 20, 16)
            hero_layout.setSpacing(11)
            title_row = QHBoxLayout()
            self.hero_icon = label()
            self.hero_icon.setPixmap(build_instance_icon("portal", THEMES[self.theme]["accent"]).pixmap(42, 42))
            self.hero_icon.hide()
            title_row.addWidget(self.hero_icon, 0, Qt.AlignmentFlag.AlignTop)
            title_row.addSpacing(8)
            title_col = QVBoxLayout()
            title_col.setSpacing(4)
            self.hero_kicker = ElidedLabel("СБОРКА MINECRAFT")
            self.hero_kicker.setObjectName("kicker")
            self.hero_kicker.hide()
            self.title_label = ElidedLabel("Выберите сборку")
            self.title_label.setObjectName("cinematicTitle")
            self.meta_label = ElidedLabel("Создайте свою или подключитесь к другу по ссылке.")
            self.meta_label.setObjectName("muted")
            title_col.addWidget(self.title_label)
            title_col.addWidget(self.meta_label)
            title_row.addLayout(title_col, 1)
            title_row.addSpacing(25)
            hero_layout.addLayout(title_row)
            actions = QHBoxLayout()
            actions.setSpacing(8)
            self.play_btn = button("▶  Играть", self.launch, "play")
            self.play_btn.setMinimumWidth(210)
            self.play_btn.setToolTip("Minecraft и Java подготовятся автоматически. Ctrl+Enter — играть / остановить.")
            self.sync_btn = button("Обновить сейчас", self.sync_now)
            self.host_btn = button("Пригласить друзей", self.show_host)
            self.more_btn = MotionToolButton()
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
            self.flow_hint.hide()
            self.tabs = AnimatedTabWidget()
            self.tabs.setDocumentMode(True)
            self.tabs.setIconSize(QSize(18, 18))
            self.tabs.tabBar().setUsesScrollButtons(True)
            self.tabs.tabBar().setExpanding(False)
            self.tabs.tabBar().setMouseTracking(True)
            self.tabs.tabBar().setAttribute(Qt.WidgetAttribute.WA_Hover, True)
            self.tabs.setMinimumWidth(0)
            self.tabs.tabBar().setDrawBase(False)
            self.tab_icon_names: list[str] = []

            def add_tab(widget: QWidget, title: str, icon_name: str, description: str) -> None:
                index = self.tabs.addTab(
                    widget,
                    interface_icon(icon_name, THEMES[self.theme]["muted"], THEMES[self.theme]["accent"]),
                    title,
                )
                self.tabs.setTabToolTip(index, description)
                self.tabs.setTabWhatsThis(index, description)
                self.tab_icon_names.append(icon_name)

            self.overview = self.build_instance_overview()
            add_tab(self.overview, "Обзор", "overview", "Краткая сводка сборки, её готовность и заметки.")
            self.file_panels = {}
            file_tabs = (("mods", "Моды", "mods", "Установка, включение и удаление модов."),
                         ("resourcepacks", "Ресурсы", "resources", "Ресурспаки для внешнего вида игры."),
                         ("shaderpacks", "Шейдеры", "shaders", "Шейдер-паки для графики Minecraft."),
                         ("saves", "Миры", "worlds", "Игровые миры и их ZIP-бэкапы."))
            for folder, title, icon_name, description in file_tabs:
                panel = FilePanel(folder, self)
                self.file_panels[folder] = panel
                add_tab(panel, title, icon_name, description)
            self.modrinth_tab = self.build_modrinth()
            self.catalog_page = self.modrinth_tab
            self.console_instance = ""
            self.console = QPlainTextEdit()
            self.console.setReadOnly(True)
            self.console.setMaximumBlockCount(5000)
            self.console.setStyleSheet("font-family: Consolas, 'DejaVu Sans Mono', monospace; font-size: 12px;")
            add_tab(self.console, "Консоль", "console", "Вывод текущего запуска Minecraft.")
            self.logs_panel = self.build_logs()
            add_tab(self.logs_panel, "Логи", "logs", "Файлы журналов Minecraft и отчёты о сбоях.")
            self.tabs.currentChanged.connect(self.on_build_tab_changed)
            detail_layout.addWidget(self.tabs, 1)
            self.detail_stack.addWidget(self.details)
            self.main_pages.addWidget(self.detail_stack)
            self.main_pages.addWidget(self.catalog_page)
            self.lobby_page = CinematicLobby(self)
            self.main_pages.addWidget(self.lobby_page)
            self.party_page = self.build_party_page()
            self.main_pages.addWidget(self.party_page)
            self.copy_page = self.build_copy_page()
            self.main_pages.addWidget(self.copy_page)
            self.inline_pages: dict[str, QWidget] = {}
            self.inline_returns: dict[QWidget, QWidget] = {}
            self.inline_handlers: dict[QWidget, Callable | None] = {}
            self.page_routes: dict[QWidget, tuple[str, str, bool]] = {
                self.library_page: ("library", "Библиотека", False),
                self.detail_stack: ("library", "", True),
                self.catalog_page: ("library", "Каталог модов", False),
                self.lobby_page: ("home", "Главная", True),
                self.party_page: ("party", "Пати", False),
                self.copy_page: ("library", "Копировать сборку", False),
            }
            workspace_layout.addWidget(self.main_pages, 1)
            self.task_card = TaskProgressCard(workspace)
            self.task_card.set_theme_colors(THEMES[self.theme]["accent"], THEMES[self.theme]["border"])
            self.task_card.cancel_requested.connect(self.cancel_task)
            self.task_label = self.task_card.stage_label
            self.progress_bar = self.task_card.bar
            self.cancel_btn = self.task_card.cancel_btn
            self.task_percent = self.task_card.percent_label
            workspace_layout.addWidget(self.task_card)
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
            self.set_library_rail(False)
            if self.layout_mode != "gallery":
                self.show_lobby()
            shortcuts = {"Ctrl+F": self.focus_library_search, "Ctrl+S": self.save_current,
                         "Ctrl+N": self.show_library, "Ctrl+Return": self.launch,
                         "Ctrl+L": self.show_library, "Ctrl+,": lambda: self.open_manager("parameters"),
                         "Ctrl+Shift+T": self.cycle_theme,
                         "F1": self.show_diagnostics}
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

        def show_notice(self, title: str, text: str) -> None:
            self.notice_timer.stop()
            self.notice_title._mcsync_allow_partial = True
            self.notice_body._mcsync_allow_partial = True
            self.notice_title.setText(redact(title))
            self.notice_body.setText(redact(text))
            self.notice_banner.show()
            self.notice_timer.start(12_000)

        def clear_notice(self) -> None:
            if hasattr(self, "notice_timer"):
                self.notice_timer.stop()
            if hasattr(self, "notice_banner"):
                self.notice_banner.hide()

        def _show_workspace_page(self, widget: QWidget, *, nav_key: str | None = None,
                                 title: str | None = None, hide_header: bool | None = None) -> None:
            if self.main_pages.indexOf(widget) < 0:
                if isinstance(widget, QDialog):
                    widget.setParent(self.main_pages, Qt.WindowType.Widget)
                    widget.setWindowModality(Qt.WindowModality.NonModal)
                self.main_pages.addWidget(widget)
            current = self.main_pages.currentWidget()
            if current is not widget and isinstance(current, MicrosoftLoginDialog):
                current.cancel.set()
            route = self.page_routes.get(widget, ("library", "", False))
            nav_key = nav_key or route[0]
            title = title if title is not None else route[1]
            hide_header = route[2] if hide_header is None else hide_header
            self.page_routes[widget] = (nav_key, title, hide_header)
            if self.main_pages.currentWidget() is self.detail_stack and widget is not self.detail_stack:
                self.flush_draft()
            self.header_widget.setVisible(not hide_header)
            if not hide_header:
                self.page_title.setText(title)
            self.main_pages.setCurrentWidget(widget)
            for key, nav in self.nav_buttons.items():
                nav.setChecked(key == nav_key)
            if widget is self.library_page:
                self.library_grid.viewport().update()
            if widget is self.party_page:
                self.party_panel.refresh(self.current_instance())

        def show_inline_dialog(self, key: str, page: QDialog, *, title: str, nav_key: str,
                               return_to: QWidget | None = None, on_accept: Callable | None = None,
                               keep_previous: bool = False) -> None:
            return_to = return_to or self.main_pages.currentWidget()
            if not keep_previous:
                previous = self.inline_pages.get(key)
                if previous is self.main_pages.currentWidget():
                    page.deleteLater()
                    return
                if previous is not None:
                    if hasattr(previous, "cancel") and isinstance(previous.cancel, threading.Event):
                        previous.cancel.set()
                    self.main_pages.removeWidget(previous)
                    self.inline_returns.pop(previous, None)
                    self.inline_handlers.pop(previous, None)
                    previous.deleteLater()
                self.inline_pages[key] = page
            else:
                self.inline_pages[f"{key}:{id(page)}"] = page
            page.setParent(self.main_pages, Qt.WindowType.Widget)
            page.setWindowModality(Qt.WindowModality.NonModal)
            page.setMinimumSize(0, 0)
            self.main_pages.addWidget(page)
            self.inline_returns[page] = return_to
            self.inline_handlers[page] = on_accept
            page.accepted.connect(lambda p=page: QTimer.singleShot(
                0, lambda page=p: self._finish_inline_dialog(page, True)))
            page.rejected.connect(lambda p=page: QTimer.singleShot(
                0, lambda page=p: self._finish_inline_dialog(page, False)))
            self.page_routes[page] = (nav_key, title, False)
            self._show_workspace_page(page)

        def _finish_inline_dialog(self, page: QWidget, accepted: bool) -> None:
            target = self.inline_returns.pop(page, None)
            handler = self.inline_handlers.pop(page, None)
            if accepted and handler:
                try:
                    destination = handler(page)
                    if isinstance(destination, QWidget):
                        target = destination
                except (UserError, OSError, ValueError) as exc:
                    message(self, "Не удалось выполнить действие", str(exc))
                    target = page
            if target is None or self.main_pages.indexOf(target) < 0:
                target = self.lobby_page
            self._show_workspace_page(target)
            if target is self.lobby_page:
                self.lobby_page.refresh(self.current_instance())

        def show_inline_page(self, page: QWidget, *, title: str, nav_key: str,
                             return_to: QWidget | None = None) -> None:
            return_to = return_to or self.main_pages.currentWidget()
            self.inline_returns[page] = return_to
            self.page_routes[page] = (nav_key, title, False)
            self._show_workspace_page(page)

        def back_from_subpage(self) -> None:
            current = self.main_pages.currentWidget()
            target = self.inline_returns.pop(current, None)
            if target is None or self.main_pages.indexOf(target) < 0:
                target = self.party_page
            self._show_workspace_page(target)
            if target is self.detail_stack:
                self.refresh_active_build_tab()

        def set_library_rail(self, expanded: bool = True) -> None:
            # The navigation remains labeled and vertical at every window size; only the
            # library filters collapse. This avoids an icon-only mystery rail.
            self.library_expanded = True
            self.sidebar.setMinimumWidth(225)
            self.sidebar.setMaximumWidth(275)
            self.sidebar_layout.setContentsMargins(14, 12, 14, 8)
            self.workspace_splitter.setSizes([248, max(600, self.width() - 248)])
            self.sidebar.updateGeometry()

        def toggle_library_rail(self) -> None:
            self.show_library()

        def focus_library_search(self) -> None:
            if (self.main_pages.currentWidget() is self.detail_stack and
                    self.detail_stack.currentWidget() is self.details and
                    self.tabs.currentWidget() in self.file_panels.values()):
                panel = self.tabs.currentWidget()
                if panel is not None and hasattr(panel, "filter_field"):
                    panel.filter_field.setFocus()
                    panel.filter_field.selectAll()
                    return
            self.show_library()
            self.gallery_search.setFocus()

        def toggle_filters(self) -> None:
            visible = not self.groups.isVisible()
            self.groups.setVisible(visible)
            self.sort_combo.setVisible(visible)
            self.filter_toggle.setText("Фильтры ▴" if visible else "Фильтры ▾")

        def resizeEvent(self, event: Any) -> None:
            super().resizeEvent(event)
            if hasattr(self, "party_panel"):
                self.party_panel.updateGeometry()

        def build_empty_page(self) -> QWidget:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.addStretch(1)
            icon = label()
            icon.setPixmap(build_instance_icon("portal", THEMES[self.theme]["accent"]).pixmap(78, 78))
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.empty_icon = icon
            layout.addWidget(icon)
            self.empty_title = label("Всё начинается со сборки", "title")
            self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.empty_title)
            self.empty_hint = label("Откройте библиотеку, чтобы создать, импортировать или подключиться к сборке.",
                                    "muted", True)
            self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.empty_hint)
            actions = QHBoxLayout()
            actions.addStretch()
            actions.addWidget(button("Открыть библиотеку", self.show_library, "primary"))
            actions.addStretch()
            layout.addSpacing(12)
            layout.addLayout(actions)
            layout.addStretch(2)
            return page

        def build_party_page(self) -> QWidget:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 2, 0, 0)
            layout.setSpacing(10)
            info_card = QFrame()
            info_card.setObjectName("card")
            info_layout = QHBoxLayout(info_card)
            info_layout.setContentsMargins(14, 10, 14, 10)
            info_icon = QLabel("ℹ")
            info_icon.setStyleSheet(f"font-size: 16px; color: {THEMES[self.theme]['muted']};")
            info_layout.addWidget(info_icon)
            info_text = label(
                "Пати работает напрямую в общей LAN/VPN-сети. MCSync не ретранслирует трафик и не обходит NAT.",
                "muted", True)
            info_layout.addWidget(info_text, 1)
            layout.addWidget(info_card)
            layout.addWidget(self.party_panel, 1)
            return page

        def build_copy_page(self) -> QWidget:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 2, 0, 0)
            card = QFrame()
            card.setObjectName("card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(24, 22, 24, 22)
            card_layout.setSpacing(12)
            card_layout.addWidget(label("Независимая копия", "title"))
            card_layout.addWidget(label(
                "Копия получит отдельные файлы и больше не будет синхронизироваться с хостом. "
                "Миры и локальные настройки копируются.", "muted", True))
            self.copy_name_field = QLineEdit()
            self.copy_name_field.setPlaceholderText("Название копии")
            self.copy_name_field.returnPressed.connect(self.submit_copy)
            card_layout.addWidget(self.copy_name_field)
            self.copy_error = label("", "warning", True)
            card_layout.addWidget(self.copy_error)
            card_layout.addLayout(row(button("Создать копию", self.submit_copy, "primary"),
                                     button("Назад", self.back_from_subpage, "ghost")))
            layout.addWidget(card, 0, Qt.AlignmentFlag.AlignTop)
            layout.addStretch(1)
            return page

        def set_language(self, value: str) -> None:
            """Switch the complete window in place while preserving drafts and selections."""
            self.language = set_ui_language(value)
            app = QApplication.instance()
            app.setProperty("uiLanguage", self.language)
            localize_widget_tree(self, self.language)
            status = self.statusBar()
            message = getattr(status, "_mcsync_source_message", "")
            if message and status.currentMessage():
                status.showMessage(message)
            if hasattr(self, "party_panel"):
                self.party_panel._roster_key = None
                self.party_panel.refresh(self.current_instance())
            if hasattr(self, "lobby"):
                self.lobby.refresh(self.current_instance())

        def set_theme(self, key: str) -> None:
            """Change appearance without reloading/discarding in-progress instance fields."""
            self.theme = theme_key(key)
            apply_theme(QApplication.instance(), self.theme)
            color = THEMES[self.theme]["accent"]
            muted = THEMES[self.theme]["muted"]
            self.setWindowIcon(app_icon(color))
            for nav in self.nav_buttons.values():
                icon_name = nav.property("iconName")
                if icon_name:
                    nav.setIcon(interface_icon(str(icon_name), muted, color))
            for index, icon_name in enumerate(self.tab_icon_names):
                self.tabs.setTabIcon(index, interface_icon(icon_name, muted, color))
            if hasattr(self, "catalog_source_buttons"):
                for source, provider in self.catalog_source_buttons.items():
                    icon_name = "catalog" if source == "modrinth" else "library"
                    provider.setIcon(interface_icon(icon_name, muted, color))
                self.modrinth_selection_changed()
            self.brand_icon.setPixmap(app_icon(color).pixmap(34, 34))
            if hasattr(self, "task_card"):
                self.task_card.set_theme_colors(color, THEMES[self.theme]["border"])
            self.hero_icon.setPixmap(build_instance_icon("portal", color).pixmap(52, 52))
            self.empty_icon.setPixmap(build_instance_icon("portal", color).pixmap(78, 78))
            self.hero.set_theme(self.theme)
            if hasattr(self, "lobby_page"):
                self.lobby_page.set_theme(self.theme)
            self.library_empty_icon.setPixmap(build_instance_icon("portal", color).pixmap(52, 52))
            self.library_grid.viewport().update()
            self.instances.viewport().update()

        def cycle_theme(self) -> None:
            names = list(THEMES)
            idx = names.index(self.theme) if self.theme in names else 0
            self.set_theme(names[(idx + 1) % len(names)])

        def build_library_page(self) -> QWidget:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 2, 0, 0)
            layout.setSpacing(10)
            filters = QHBoxLayout()
            filters.addWidget(self.search, 1)
            filters.addWidget(self.filter_toggle)
            layout.addLayout(filters)
            filter_options = QHBoxLayout()
            filter_options.addWidget(self.groups, 1)
            filter_options.addWidget(self.sort_combo, 1)
            filter_options.addStretch()
            layout.addLayout(filter_options)
            actions = QHBoxLayout()
            actions.addWidget(self.count_label)
            actions.addStretch()
            actions.addWidget(self.new_btn)
            actions.addWidget(self.connect_btn)
            actions.addWidget(self.import_btn)
            layout.addLayout(actions)

            self.library_empty = QFrame()
            self.library_empty.setObjectName("libraryEmptyState")
            self.library_empty.setAccessibleName("Состояние библиотеки")
            empty_layout = QVBoxLayout(self.library_empty)
            empty_layout.setContentsMargins(28, 24, 28, 24)
            empty_layout.setSpacing(9)
            empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.library_empty_icon = label()
            self.library_empty_icon.setPixmap(build_instance_icon("portal", THEMES[self.theme]["accent"]).pixmap(52, 52))
            self.library_empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_layout.addWidget(self.library_empty_icon, 0, Qt.AlignmentFlag.AlignCenter)
            self.library_empty_title = label("", "sectionTitle")
            self.library_empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_layout.addWidget(self.library_empty_title)
            self.library_empty_hint = label("", "muted", True)
            self.library_empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_layout.addWidget(self.library_empty_hint)
            layout.addWidget(self.library_empty, 1)
            self.library_empty.hide()

            self.gallery_search = self.search
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
            return page

        def show_library(self) -> None:
            self.flush_draft()
            self._show_workspace_page(self.library_page)

        def show_details(self) -> None:
            self._show_workspace_page(self.detail_stack)
            if self.detail_stack.currentWidget() is self.details:
                self.refresh_active_build_tab()

        def open_mod_catalog(self) -> None:
            inst = self.current_instance()
            if not inst:
                self.statusBar().showMessage("Сначала выберите сборку в библиотеке.", 5000)
                return
            if inst.sync_url or self.is_locked(inst.id) or self.busy:
                self.statusBar().showMessage("Каталог скачивает моды только в разблокированную локальную сборку.", 7000)
                return
            if not self.save_current(notify=False):
                return
            mod_index = self.mr_type.findData("mod")
            if mod_index >= 0:
                self.mr_type.setCurrentIndex(mod_index)
            self.show_inline_page(self.catalog_page, title="Каталог модов", nav_key="library",
                                  return_to=self.detail_stack)
            self.search_catalog()

        def refresh_active_build_tab(self) -> None:
            if self.main_pages.currentWidget() is not self.detail_stack or self.detail_stack.currentWidget() is not self.details:
                return
            inst = self.current_instance()
            widget = self.tabs.currentWidget()
            if widget in self.file_panels.values():
                widget.set_context(inst, bool(inst and self.is_locked(inst.id)) or self.busy)
                widget.refresh()
            elif widget is self.logs_panel:
                self.refresh_logs(force=False)
            elif widget is self.overview and inst:
                self.update_summary(inst)

        def on_build_tab_changed(self, index: int) -> None:
            if self.main_pages.currentWidget() is not self.detail_stack or self.detail_stack.currentWidget() is not self.details:
                return
            if 0 <= index < self.tabs.count():
                widget = self.tabs.widget(index)
                if widget in self.file_panels.values():
                    inst = self.current_instance()
                    widget.set_context(inst, bool(inst and self.is_locked(inst.id)) or self.busy)
                    widget.refresh()
                    if inst:
                        self.update_summary(inst)
                elif widget is self.logs_panel:
                    self.refresh_logs(force=False)
                elif widget is self.overview:
                    self.update_summary(self.current_instance())

        def show_lobby(self) -> None:
            self.flush_draft()
            self.lobby_page.refresh(self.current_instance())
            self._show_workspace_page(self.lobby_page)
            self.lobby_page.animate_reveal()

        def open_manager(self, page: str = "parameters") -> None:
            if page == "party":
                self.show_party()
                return
            self.show_details()
            if page == "parameters":
                self.show_overview_page(1)
            elif page in self.file_panels:
                self.tabs.setCurrentWidget(self.file_panels[page])

        def show_party(self) -> None:
            self.party_panel.refresh(self.current_instance())
            self._show_workspace_page(self.party_page)

        def show_advanced_lan(self, checked: bool = False, *, return_to: QWidget | None = None) -> None:
            if not self.current_instance():
                self.show_library()
                return
            if not hasattr(self, "advanced_lan_page"):
                self.advanced_lan_page = AdvancedLanPropertiesPage(self)
            self.advanced_lan_page.refresh()
            self.show_inline_page(self.advanced_lan_page, title="Дополнительные параметры LAN",
                                  nav_key="party", return_to=return_to or self.main_pages.currentWidget())

        def open_library_instance(self, item: QListWidgetItem) -> None:
            instance_id = item.data(Qt.ItemDataRole.UserRole)
            self.refresh_instances(instance_id, navigate=False)
            self.show_details()

        def on_instance_changed(self, *args: Any) -> None:
            active_page = self.main_pages.currentWidget() if hasattr(self, "main_pages") else None
            previous = self.loaded_id
            self.load_detail()
            if active_page is self.lobby_page:
                self.show_lobby()
            elif active_page is self.party_page:
                self.party_panel.refresh(self.current_instance())
            elif active_page is self.detail_stack:
                self.refresh_active_build_tab()
            elif isinstance(active_page, HostDialog):
                self.show_party()
                self.show_host()
            if self.loaded_id != previous and self.details.isVisible() and motion_enabled():
                self.detail_stack.reveal_current()

        def set_layout_mode(self, value: str) -> None:
            self.layout_mode = layout_key(value)
            compact = self.layout_mode == "compact"
            self.hero.setMinimumHeight(220 if compact else 310)
            self.hero.layout().setContentsMargins(26 if compact else 34, 24 if compact else 34,
                                                  26 if compact else 34, 22 if compact else 28)
            self.hero.layout().setSpacing(14 if compact else 20)
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
            switch.addWidget(button("Диагностика", self.show_diagnostics, "ghost"))
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
                self.show_details()
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
            if not inst:
                self.show_library()
                return
            if inst.sync_url:
                if inst.id in self.update_badges:
                    self.sync_now()
                else:
                    self.show_overview_page(1)
            else:
                self.show_host()

        def update_summary(self, inst: Instance | None) -> None:
            if inst is None:
                return
            mod_counts = self.file_panels["mods"].summary_counts()
            if mod_counts is None:
                self.stat_mods.set_value("…", "Подсчитываем файлы в фоне")
            else:
                enabled, total = mod_counts
                self.stat_mods.set_value(str(enabled), f"Включено · всего файлов {total}")
            world_counts = self.file_panels["saves"].summary_counts()
            if world_counts is None:
                self.stat_worlds.set_value("…", "Подсчитываем миры в фоне")
            else:
                self.stat_worlds.set_value(str(world_counts[1]), "Локальные миры · ZIP-бэкапы")
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
                      "icon": inst.icon, "notes": self.notes_field.toPlainText(),
                      "java": self.java_field.text().strip(),
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
                fields = {"name": self.name_field, "group": self.group_field,
                          "minecraft": self.mc_field,
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
                        if isinstance(field, (QSpinBox, MemorySlider)):
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

        def ensure_version_choice(self, field: QComboBox, value: Any) -> None:
            """Keep the saved version as a real dropdown entry, not just free text."""
            if not isinstance(value, str):
                return
            text = value.strip()
            if text and field.findText(text) < 0:
                field.insertItem(0, text)

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
            # The build icon picker was removed in 0.5.6; built-in artwork is no longer user-visible.
            # Instance.icon stays serialized so profiles written by older versions keep working.
            self.mc_field = QComboBox()
            self.mc_field.setObjectName("minecraftVersion")
            self.mc_field.setEditable(True)
            self.mc_field.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            self.mc_field.setMinimumContentsLength(8)
            self.mc_field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.mc_field.addItems(self.cached_versions() or ["1.21.1", "1.20.1"])
            self.loader_field = QComboBox()
            for key, title in LOADERS.items():
                self.loader_field.addItem(title, key)
            self.loader_version_field = QComboBox()
            self.loader_version_field.setEditable(True)
            self.loader_version_field.setObjectName("loaderVersion")
            self.loader_version_field.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            self.loader_version_field.setMinimumContentsLength(8)
            self.loader_version_field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.loader_version_field.lineEdit().setPlaceholderText("Пусто = авто")
            self.loader_field.currentIndexChanged.connect(self.loader_changed)
            self.mc_versions_btn = button("Обновить список", self.fetch_mc_versions)
            self.mc_versions_btn.setToolTip("Заново загрузить список версий Minecraft; сохранённая версия останется выбранной.")
            self.mc_versions_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self.loader_versions_btn = button("Совместимые версии", self.fetch_loader_versions)
            self.loader_versions_btn.setToolTip("Подобрать версии загрузчика для выбранной версии Minecraft.")
            self.loader_versions_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            form.addRow("Название", self.name_field)
            form.addRow("Группа", self.group_field)
            minecraft_row = row(self.mc_field, self.mc_versions_btn)
            minecraft_row.setStretchFactor(self.mc_field, 1)
            minecraft_row.setStretchFactor(self.mc_versions_btn, 0)
            form.addRow("Minecraft", minecraft_row)
            form.addRow("Загрузчик", self.loader_field)
            loader_version_row = row(self.loader_version_field, self.loader_versions_btn)
            loader_version_row.setStretchFactor(self.loader_version_field, 1)
            loader_version_row.setStretchFactor(self.loader_versions_btn, 0)
            form.addRow("Версия загрузчика", loader_version_row)
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
            ram_limit = physical_memory_mb()
            self.ram_min = MemorySlider("Минимум RAM", 256, ram_limit, 256, 512)
            self.ram_max = MemorySlider("Максимум RAM", 256, ram_limit, 256, min(4096, ram_limit))
            form.addRow("RAM мин. / макс.", row(self.ram_min, self.ram_max))
            self.java_field = QLineEdit()
            self.java_field.setPlaceholderText("Авто — Java от Mojang")
            self.java_pick_btn = button("Путь", self.pick_java, "ghost")
            self.java_find_btn = button("Найти Java", self.find_java, "ghost")
            form.addRow("Java", row(self.java_field, self.java_pick_btn, self.java_find_btn))
            self.launch_form = form
            self.java_candidates = QComboBox()
            self.java_candidates.setAccessibleName("Найденные версии Java")
            self.java_candidates.currentIndexChanged.connect(self.use_java_candidate)
            self.java_candidate_label = label("Системные варианты Java", "muted")
            form.addRow(self.java_candidate_label, self.java_candidates)
            form.setRowVisible(self.java_candidates, False)
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
            self.advanced_btn = MotionToolButton()
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
            layout.setContentsMargins(0, 4, 0, 0)
            layout.setSpacing(10)

            heading = QHBoxLayout()
            self.catalog_back_btn = button("← К модам", self.back_from_subpage, "ghost")
            heading.addWidget(self.catalog_back_btn)
            heading.addStretch()
            layout.addLayout(heading)

            # Keep the combo as the accessible source state; the visible provider rail
            # matches the compact catalogue switcher from the reference design.
            self.catalog_source = QComboBox(panel)
            self.catalog_source.addItem("Modrinth", "modrinth")
            self.catalog_source.addItem("CurseForge", "curseforge")
            self.catalog_source.setAccessibleName("Источник каталога проектов")
            self.catalog_source.hide()
            source_rail = QFrame()
            source_rail.setObjectName("catalogSourceRail")
            source_rail.setMinimumWidth(132)
            source_rail.setMaximumWidth(168)
            source_layout = QVBoxLayout(source_rail)
            source_layout.setContentsMargins(9, 12, 9, 12)
            source_layout.setSpacing(7)
            source_layout.addWidget(label("ИСТОЧНИК", "kicker"))
            self.catalog_source_buttons: dict[str, QPushButton] = {}
            for source, text, icon_name in (("modrinth", "Modrinth", "catalog"),
                                             ("curseforge", "CurseForge", "library")):
                provider = button(text, lambda checked=False, key=source: self.set_catalog_source(key),
                                  "catalogSource")
                provider.setCheckable(True)
                provider.setAccessibleName(f"Каталог {text}")
                provider.setToolTip(f"Искать проекты на {text}")
                provider.setIcon(interface_icon(icon_name, THEMES[self.theme]["muted"], THEMES[self.theme]["accent"]))
                provider.setIconSize(QSize(18, 18))
                source_layout.addWidget(provider)
                self.catalog_source_buttons[source] = provider
            source_layout.addStretch()
            self.cf_settings_btn = button("API-ключ…", self.show_settings, "ghost")
            source_layout.addWidget(self.cf_settings_btn)
            self.catalog_key_hint = label("Для CurseForge нужен личный API-ключ. Он хранится только на этом компьютере.",
                                          "warning", True)
            source_layout.addWidget(self.catalog_key_hint)

            self.mr_query = QLineEdit()
            self.mr_query.setPlaceholderText("Поиск: Sodium, Iris, ресурспак…")
            self.mr_query.setAccessibleName("Поиск в каталоге")
            self.mr_type = QComboBox()
            self.mr_type.setAccessibleName("Тип проекта")
            for text, value in (("Моды", "mod"), ("Ресурспаки", "resourcepack"),
                                ("Шейдеры", "shader"), ("Сборки", "modpack")):
                self.mr_type.addItem(text, value)
            self.mr_search_btn = button("Найти", self.search_catalog, "primary")
            search_row = QHBoxLayout()
            search_row.addWidget(self.mr_query, 1)
            search_row.addWidget(self.mr_type)
            search_row.addWidget(self.mr_search_btn)
            layout.addLayout(search_row)
            self.mr_sort = QComboBox()
            self.mr_sort.setAccessibleName("Сортировка проектов")
            for text, value in (("Сначала популярные", "downloads"), ("Недавно обновлённые", "updated"),
                                ("Сначала новые", "newest"), ("По релевантности", "relevance")):
                self.mr_sort.addItem(text, value)
            self.mr_filter = QCheckBox("Совместимые с этой сборкой")
            self.mr_filter.setChecked(True)
            self.mr_filter.setToolTip("Ограничить выдачу версией Minecraft и загрузчиком выбранной локальной сборки.")
            filter_row = QHBoxLayout()
            filter_row.addWidget(label("Сортировка", "muted"))
            filter_row.addWidget(self.mr_sort)
            filter_row.addSpacing(12)
            filter_row.addWidget(self.mr_filter)
            filter_row.addStretch()
            layout.addLayout(filter_row)

            self.mr_results = QListWidget()
            self.mr_results.setObjectName("catalogResults")
            self.mr_results.setIconSize(QSize(38, 38))
            self.mr_results.setUniformItemSizes(True)
            self.mr_results.setAccessibleName("Результаты каталога")
            self.mr_results.itemDoubleClicked.connect(lambda _: self.install_selected_modrinth())
            self.mr_results.currentItemChanged.connect(self.modrinth_selection_changed)

            self.catalog_details = QFrame()
            self.catalog_details.setObjectName("card")
            self.catalog_details.setMinimumWidth(280)
            details_layout = QVBoxLayout(self.catalog_details)
            details_layout.setContentsMargins(18, 17, 18, 16)
            details_layout.setSpacing(10)
            project_header = QHBoxLayout()
            self.catalog_project_icon = label()
            self.catalog_project_icon.setObjectName("catalogProjectIcon")
            self.catalog_project_icon.setFixedSize(56, 56)
            self.catalog_project_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            project_header.addWidget(self.catalog_project_icon, 0, Qt.AlignmentFlag.AlignTop)
            project_identity = QVBoxLayout()
            self.catalog_project_title = label("Выберите проект", "catalogProjectTitle", True)
            self.catalog_project_author = label("Modrinth или CurseForge", "muted")
            project_identity.addWidget(self.catalog_project_title)
            project_identity.addWidget(self.catalog_project_author)
            project_header.addLayout(project_identity, 1)
            self.catalog_project_badge = label("КАТАЛОГ", "badge")
            project_header.addWidget(self.catalog_project_badge, 0, Qt.AlignmentFlag.AlignTop)
            details_layout.addLayout(project_header)
            self.catalog_project_stats = label("Поиск по каталогам Minecraft Java", "muted", True)
            details_layout.addWidget(self.catalog_project_stats)
            self.catalog_project_description = label(
                "Выберите результат, чтобы посмотреть описание, автора и совместимость.",
                "catalogProjectBody", True)
            self.catalog_project_description.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            details_layout.addWidget(self.catalog_project_description, 1)
            self.catalog_project_target = label("Установка выберет последнюю совместимую версию.", "muted", True)
            details_layout.addWidget(self.catalog_project_target)
            details_layout.addStretch(1)
            self.catalog_project_link = button("Открыть страницу проекта ↗", self.open_catalog_project, "ghost")
            self.catalog_project_link.setEnabled(False)
            details_layout.addWidget(self.catalog_project_link, 0, Qt.AlignmentFlag.AlignLeft)

            self.catalog_splitter = QSplitter(Qt.Orientation.Horizontal)
            self.catalog_splitter.setChildrenCollapsible(False)
            self.catalog_splitter.addWidget(self.mr_results)
            self.catalog_splitter.addWidget(self.catalog_details)
            self.catalog_splitter.setStretchFactor(0, 3)
            self.catalog_splitter.setStretchFactor(1, 4)
            self.catalog_splitter.setSizes([390, 510])
            content_row = QHBoxLayout()
            content_row.setSpacing(10)
            content_row.addWidget(source_rail)
            content_row.addWidget(self.catalog_splitter, 1)
            layout.addLayout(content_row, 1)

            self.mr_context: tuple[Any, ...] | None = None
            self.catalog_search_generation = 0
            self.catalog_append_pending = False
            self.mr_offset, self.mr_more = 0, False
            self.mr_page_label = label("Готово к поиску", "muted")
            self.mr_page_label._mcsync_allow_partial = True
            self.mr_previous = button("← Назад", lambda: self.change_modrinth_page(-1), "ghost")
            self.mr_next = button("Далее →", lambda: self.change_modrinth_page(1), "ghost")
            self.mr_previous.setEnabled(False)
            self.mr_next.setEnabled(False)
            self.mr_previous.hide()
            self.mr_next.hide()
            layout.addWidget(self.mr_page_label)
            self.mr_results.verticalScrollBar().valueChanged.connect(self.catalog_scroll_changed)
            self.mr_query.textChanged.connect(self.invalidate_modrinth_pages)
            self.mr_type.currentIndexChanged.connect(self.invalidate_modrinth_pages)
            self.mr_sort.currentIndexChanged.connect(self.invalidate_modrinth_pages)
            self.mr_filter.toggled.connect(self.invalidate_modrinth_pages)
            self.catalog_source.currentIndexChanged.connect(self.catalog_source_changed)
            self.mr_install_btn = button("Установить + зависимости", self.install_selected_modrinth, "primary")
            self.mr_update_btn = button("Обновить проекты", self.update_mods, "ghost")
            self.mr_update_btn.setToolTip("Обновляются только проекты, установленные через выбранный каталог в этом лаунчере.")
            action_row = QHBoxLayout()
            action_row.addWidget(self.mr_install_btn)
            action_row.addWidget(self.mr_update_btn)
            action_row.addStretch()
            layout.addLayout(action_row)
            layout.addWidget(label("Установка проверяет Minecraft и загрузчик выбранной сборки.", "muted"))
            self.mr_query.returnPressed.connect(self.search_catalog)
            self.catalog_source_changed()
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

        def lan_endpoint(self, inst: Instance | None) -> str:
            if not inst or inst.sync_url or inst.id not in self.lan_open_confirmed:
                return ""
            settings = self.store.settings
            address = settings.get("minecraft_lan_address", "")
            port = settings.get("minecraft_lan_port", 0)
            if (not isinstance(address, str) or not address.strip() or
                    any(char.isspace() or char in "/?#@" for char in address) or
                    type(port) is not int or not 1 <= port <= 65535):
                return ""
            host = address.strip()
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            return f"{host}:{port}"

        def is_locked(self, instance_id: str) -> bool:
            return instance_id in self.games or bool(self.task and self.task.get("instance_id") == instance_id)

        def refresh_instances(self, selected_id: str = "", *, reload_fields: bool = True, navigate: bool = True) -> None:
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
            group_names = sorted({inst.group for inst in all_instances if inst.group})
            self.groups.clear()
            self.groups.addItem(translate_ui_text("Все группы"), None)
            for name in group_names:
                self.groups.addItem(name, name)
            self.groups._mcsync_source_items = ["Все группы", *group_names]
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
                metadata = {"name": inst.name, "detail": f"{inst.minecraft} · {LOADERS[inst.loader]}",
                            "icon": inst.icon, "linked": bool(inst.sync_url), "update": inst.id in self.update_badges,
                            "running": inst.id in self.games, "favorite": inst.favorite}
                item = QListWidgetItem(f"{prefix}{inst.name}\n{detail}")
                item.setData(Qt.ItemDataRole.UserRole, inst.id)
                item.setData(int(Qt.ItemDataRole.UserRole) + 1, metadata)
                item.setToolTip(inst.name + ("\nЕсть обновления у хоста" if inst.id in self.update_badges else ""))
                self.instances.addItem(item)
                tile = QListWidgetItem(inst.name)
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
            has_library_results = self.library_grid.count() > 0
            self.library_grid.setVisible(has_library_results)
            self.library_empty.setVisible(not has_library_results)
            if not has_library_results:
                if all_instances:
                    self.library_empty_title.setText("Сборки не найдены")
                    self.library_empty_hint.setText("Измените запрос или сбросьте фильтры.")
                else:
                    self.library_empty_title.setText("Библиотека пока пуста")
                    self.library_empty_hint.setText("Создайте сборку, импортируйте её или подключитесь к другу.")
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
            if explicit and navigate:
                self.show_details()
            self.store.settings["last_instance"] = self.current_id()
            if self.main_pages.currentWidget() is self.detail_stack:
                self.refresh_active_build_tab()


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
                self.empty_hint.setText("Измените запрос или сбросьте фильтры." if filtered else
                                        "Откройте библиотеку, чтобы создать, импортировать или подключиться к сборке.")
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
                    self.ensure_version_choice(self.mc_field, inst.minecraft)
                    self.mc_field.setCurrentText(inst.minecraft)
                    self.loader_field.blockSignals(True)
                    self.loader_field.setCurrentIndex(self.loader_field.findData(inst.loader))
                    self.loader_field.blockSignals(False)
                    self.ensure_version_choice(self.loader_version_field, inst.loader_version)
                    self.loader_version_field.setCurrentText(inst.loader_version)
                    self.server_field.setText(inst.server)
                    self.sync_mode_field.setCurrentIndex(self.sync_mode_field.findData(inst.sync_mode))
                    self.java_field.setText(inst.java)
                    self.java_candidates.clear()
                    self.launch_form.setRowVisible(self.java_candidates, False)
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
            self.delete_btn.setEnabled(can_edit)
            for panel in self.file_panels.values():
                panel.set_context(inst, locked or self.busy)
            self.update_summary(inst)
            if inst is None and hasattr(self, "party_panel"):
                self.party_panel.refresh(None)
            self.update_catalog_controls()
            self.mr_previous.setEnabled(not self.busy and bool(self.mr_context) and self.mr_offset > 0)
            self.mr_next.setEnabled(not self.busy and bool(self.mr_context) and self.mr_more)
            if self.console_instance != (inst.id if inst else ""):
                self.console_instance = inst.id if inst else ""
                self.console.setPlainText("\n".join(self.buffers.get(inst.id, [])) if inst else "")
            current_log_id = inst.id if inst else ""
            self.logs_dirty = (current_log_id != self.logs_instance or
                               current_log_id in self.logs_dirty_instances or
                               (self.logs_pending and self.logs_pending_instance == current_log_id))
            if (self.main_pages.currentWidget() is self.detail_stack and self.tabs.currentWidget() is self.logs_panel):
                self.refresh_logs(force=False)
            if hasattr(self, "lobby_page"):
                self.lobby_page.refresh(inst)
                if self.main_pages.currentWidget() is self.party_page:
                    self.party_panel.refresh(inst)
            for widget in (*self.nav_buttons.values(), self.new_btn, self.connect_btn, self.import_btn, self.account_combo,
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
                if hasattr(self, "lobby_page"):
                    self.lobby_page.refresh(self.current_instance())

        def show_accounts(self) -> None:
            page = AccountsDialog(self)

            def closed(_dialog: QWidget) -> None:
                self.refresh_accounts()
                self.lobby_page.refresh(self.current_instance())

            self.show_inline_dialog("accounts", page, title="Аккаунты", nav_key="accounts",
                                    on_accept=closed)

        def show_settings(self) -> None:
            page = SettingsDialog(self)

            def saved(_dialog: QWidget) -> QWidget | None:
                return self.library_page if self.layout_mode == "gallery" else None

            self.show_inline_dialog("settings", page, title="Настройки", nav_key="settings",
                                    on_accept=saved)

        def show_diagnostics(self) -> None:
            page = DiagnosticsDialog(self)
            self.show_inline_dialog("diagnostics", page, title="Диагностика", nav_key="settings")

        def show_connection_help(self) -> None:
            page = ConnectionHelpDialog(self)
            self.show_inline_dialog("connection_help", page, title="Помощь с подключением", nav_key="party")

        def loader_changed(self, *args: Any) -> None:
            self.loader_version_field.clear()
            enabled = self.loader_field.currentData() != "vanilla"
            self.loader_version_field.setEnabled(enabled)
            self.loader_versions_btn.setEnabled(enabled)

        def backup_worlds_inline(self, inst: Instance) -> bool:
            """Keep long ZIP work in the main window's shared progress strip, never a popup."""
            cancel = threading.Event()
            loop = QEventLoop(self)
            bridge = BackupBridge(self)
            result: dict[str, str] = {"error": ""}
            self._backup_cancel = cancel
            self._backup_loop = loop
            self.busy = True
            self.task_card.begin("download", "Создание ZIP-копии миров…")
            self.refresh_instances(reload_fields=False, navigate=False)

            def progress(text: str, value: int, maximum: int) -> None:
                self.task_card.set_stage(text)
                self.task_card.set_percent(int(value), int(maximum))

            def finished(error: str) -> None:
                result["error"] = error
                loop.quit()

            bridge.progress.connect(progress)
            bridge.finished.connect(finished)

            def work() -> None:
                try:
                    backup_worlds(inst, progress=bridge.progress.emit, cancel=cancel)
                    check_cancel(cancel)
                    bridge.finished.emit("")
                except Cancelled:
                    bridge.finished.emit("cancel")
                except Exception as exc:
                    bridge.finished.emit(redact(str(exc)))

            worker = threading.Thread(target=work, name="MCSync-world-backup", daemon=True)
            worker.start()
            loop.exec()
            worker.join(timeout=2)
            self._backup_cancel = None
            self._backup_loop = None
            self.busy = False
            self.refresh_instances(reload_fields=False, navigate=False)
            error = result["error"]
            if error == "cancel":
                self.task_card.finish("cancelled", stage="Создание бэкапа отменено")
                self.statusBar().showMessage("Создание бэкапа отменено; версия сборки не изменена.", 8000)
                return False
            if error:
                self.task_card.finish("error", stage="Бэкап не создан")
                message(self, "Бэкап не создан", error + "\nВерсия сборки не изменена.")
                return False
            self.task_card.finish("done", stage="Бэкап миров создан")
            return True

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
                    if not self.backup_worlds_inline(inst):
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

            def create(page: NewInstanceDialog) -> QWidget | None:
                try:
                    inst = self.store.create(page.name.text(), minecraft=page.mc.currentText().strip(),
                                             loader=page.loader.currentData(),
                                             loader_version=page.loader_version.text().strip())
                except (UserError, OSError, ValueError) as exc:
                    message(self, "Не удалось создать сборку", str(exc))
                    return page
                self.search.clear()
                self.groups.setCurrentIndex(0)
                self.refresh_instances(inst.id, navigate=False)
                return self.detail_stack

            self.show_inline_dialog("create_instance", dialog, title="Новая сборка", nav_key="library",
                                    on_accept=create)

        def connect_instance(self) -> None:
            dialog = ConnectDialog(self)
            self.show_inline_dialog("connect_instance", dialog, title="Подключиться к другу",
                                    nav_key="library", on_accept=self._connect_from_dialog)

        def _connect_from_dialog(self, dialog: ConnectDialog) -> QWidget | None:
            try:
                url = normalize_sync_url(dialog.url.text())
                requested_name = dialog.name.text().strip()
                self.store.settings["party_name"] = party_name(dialog.alias.text())
                self.store.save_settings()
            except (UserError, OSError) as exc:
                message(self, "Не удалось сохранить приглашение", str(exc))
                return dialog
            for existing in self.store.list_instances():
                if existing.sync_url == url:
                    self.search.clear()
                    self.groups.setCurrentIndex(0)
                    self.refresh_instances(existing.id, navigate=False)
                    self.party_monitor.refresh()
                    self.statusBar().showMessage(
                        "Вы уже в этой пати. Приглашение сохранено; соединение восстановится автоматически.", 8000)
                    return self.detail_stack

            def work(progress: Progress, cancel: threading.Event) -> Instance:
                progress("Подключение к хосту…", 0, 0)
                try:
                    with BoundedSession() as session:
                        manifest = validate_manifest(fetch_json(session, url + "/manifest.json"))
                except (requests.Timeout, requests.ConnectionError) as exc:
                    raise UserError(party_failure(exc, url)["error_message"]) from None
                check_cancel(cancel)
                inst = self.store.create(requested_name or manifest["name"], minecraft=manifest["minecraft"],
                                         loader=manifest["loader"], loader_version=manifest["loader_version"], sync_url=url)
                # Keep the subscription if the first download fails, so it can be retried.
                return sync_instance(self.store, inst.id, progress=progress, cancel=cancel).instance

            def done(inst: Instance) -> None:
                self.search.clear()
                self.groups.setCurrentIndex(0)
                self.refresh_instances(inst.id, navigate=False)
                self.show_details()

            self.run_task("Подключение к сборке", work, done)
            return self.library_page

        def copy_instance(self) -> None:
            inst = self.current_instance()
            if not inst or self.is_locked(inst.id) or not self.save_current(notify=False):
                return
            inst = self.store.load(inst.id)
            self.copy_source_id = inst.id
            self.copy_name_field.setText(inst.name + " — копия")
            self.copy_error.clear()
            self.show_inline_page(self.copy_page, title="Копировать сборку", nav_key="library")
            self.copy_name_field.setFocus()
            self.copy_name_field.selectAll()

        def submit_copy(self) -> None:
            inst = self.store.load(getattr(self, "copy_source_id", "")) if getattr(self, "copy_source_id", "") else None
            name = self.copy_name_field.text().strip()
            if not inst:
                self.copy_error.setText("Сборка больше не найдена.")
                return
            try:
                dataclasses.replace(inst, name=name).validate()
            except (UserError, ValueError) as exc:
                self.copy_error.setText(str(exc))
                self.copy_name_field.setFocus()
                return
            self.copy_error.clear()

            def done(new: Instance) -> None:
                self.refresh_instances(new.id, navigate=False)
                self.show_details()

            self.run_task("Копирование сборки", lambda p, c: self.store.copy_instance(inst, name), done, inst.id)

        def delete_instance(self) -> None:
            inst = self.current_instance()
            if not inst or self.busy or self.is_locked(inst.id):
                return
            host = self.hosts.get(inst.id)
            warning = ("\nАктивная пати будет остановлена." if host else "")
            if not message(self, "Удалить сборку целиком?", inst.name + warning +
                           "\nБудут удалены её файлы, миры и локальные бэкапы. Экспортируйте важные данные заранее.",
                           question=True):
                return
            if host:
                settings_path = inst.directory / "host_settings.json"
                try:
                    try:
                        settings = read_json(settings_path, {})
                    except (UserError, OSError):
                        backup_private_file(settings_path)
                        settings = {}
                    if not isinstance(settings, dict):
                        backup_private_file(settings_path)
                        settings = {}
                    settings["auto_start"] = False
                    atomic_json(settings_path, settings)
                except (UserError, OSError) as exc:
                    message(self, "Не удалось подготовить пати к удалению", redact(str(exc)))
                    return
                self.hosts.pop(inst.id, None)
                self.host_errors.pop(inst.id, None)

            def work(progress: Progress, cancel: threading.Event) -> None:
                if host:
                    host.stop()
                check_cancel(cancel)
                self.store.delete(inst)

            self.run_task("Удаление сборки", work,
                          lambda _: self.refresh_instances(), inst.id)

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
            dialog.trust.setChecked(True)
            self.show_inline_dialog("change_invitation", dialog, title="Заменить приглашение",
                                    nav_key="party", on_accept=self._save_changed_invitation)

        def _save_changed_invitation(self, dialog: ConnectDialog) -> QWidget | None:
            inst = self.current_instance()
            if not inst or not inst.sync_url:
                return self.party_page
            try:
                url = normalize_sync_url(dialog.url.text())
                alias = party_name(dialog.alias.text())
                self.store.settings["party_name"] = alias
                self.store.save_settings()
                self.store.update(inst.id, sync_url=url)
            except (UserError, OSError) as exc:
                message(self, "Приглашение не сохранено", redact(str(exc)))
                return dialog
            if self.network_enabled:
                self.party_monitor.forget(inst)
            for mapping in (self.party_states, self.sync_checks):
                mapping.pop(inst.id, None)
            self.update_badges.discard(inst.id)
            self.party_monitor.refresh()
            self.load_detail(reload_fields=False)
            self.party_panel.refresh(self.current_instance())
            self.statusBar().showMessage(
                "Приглашение заменено. Файлы и миры сохранены; версии проверятся с подтверждением перед игрой.", 10000)
            return self.party_page

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
            if not inst or not self.save_current(notify=False):
                return
            if inst.sync_url:
                message(self, "Нельзя создать раздачу", "Для раздачи нужна собственная сборка, а не подписка на другого хоста.")
                return
            page = HostDialog(self, self.store.load(inst.id))
            self.show_inline_dialog("host", page, title="Настройки пати", nav_key="party")

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

            inst = self.current_instance()
            previous = self.mc_field.currentText().strip()
            saved = inst.minecraft if inst else ""

            def done(versions: list[str]) -> None:
                merged = merge_version_choices(versions, (previous, saved))
                kept = [value for value in (previous, saved) if value and value not in versions]
                self.mc_field.blockSignals(True)
                self.mc_field.clear()
                self.mc_field.addItems(merged)
                self.mc_field.setCurrentText(previous or saved)
                self.mc_field.blockSignals(False)
                if kept:
                    self.statusBar().showMessage("Список версий обновлён. Сохранённая версия оставлена в списке.", 8000)
                else:
                    self.statusBar().showMessage("Список версий обновлён (релизы, затем снапшоты).", 8000)

            self.run_task("Список Minecraft", work, done, variant="download")

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
            previous = self.loader_version_field.currentText().strip()
            saved = inst.loader_version

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
                self.ensure_version_choice(self.mc_field, candidate.minecraft)
                self.mc_field.setCurrentText(candidate.minecraft)
                self.loader_field.blockSignals(True)
                self.loader_field.setCurrentIndex(self.loader_field.findData(candidate.loader))
                self.loader_field.blockSignals(False)
                merged = merge_version_choices(versions, (saved, previous))
                self.loader_version_field.blockSignals(True)
                self.loader_version_field.clear()
                self.loader_version_field.addItems(merged)
                self.loader_version_field.setCurrentText(saved or previous or (merged[0] if merged else ""))
                self.loader_version_field.blockSignals(False)
                self.loader_version_field.setEnabled(True)
                self.loader_versions_btn.setEnabled(True)
                self.statusBar().showMessage("Выберите версию и сохраните настройки.", 8000)

            self.run_task("Версии загрузчика", work, done, variant="download")

        def pick_java(self) -> None:
            path, _ = QFileDialog.getOpenFileName(self, "Java executable", filter="Java (java java.exe javaw.exe);;Все файлы (*)")
            if path:
                self.java_field.setText(path)

        def find_java(self) -> None:
            def done(versions: list[dict[str, Any]]) -> None:
                self.java_candidates.blockSignals(True)
                self.java_candidates.clear()
                if not versions:
                    self.java_candidates.blockSignals(False)
                    self.launch_form.setRowVisible(self.java_candidates, False)
                    message(self, "Java", "Системная Java не найдена. Оставьте поле пустым для автоустановки.")
                    return
                for version in versions:
                    self.java_candidates.addItem(
                        f"Java {version['version']} — {version['java_path']}", version["java_path"])
                self.java_candidates.setCurrentIndex(0)
                self.java_candidates.blockSignals(False)
                self.launch_form.setRowVisible(self.java_candidates, True)
                self.use_java_candidate(0)
            self.run_task("Поиск Java", lambda p, c: launcher_lib().java_utils.find_system_java_versions_information(), done)

        def use_java_candidate(self, index: int) -> None:
            if not hasattr(self, "java_candidates") or index < 0:
                return
            path = self.java_candidates.itemData(index)
            if path:
                self.java_field.setText(str(path))

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
            if inst.id in self.hosts:
                self.lan_open_confirmed.discard(inst.id)

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
            self.run_task("Подготовка запуска", work, done, inst.id, variant="launch")

        @Slot(str, str)
        def on_game_output(self, instance_id: str, text: str) -> None:
            self.mark_logs_dirty(instance_id)
            buffer = self.buffers.setdefault(instance_id, [])
            buffer.append(text)
            if len(buffer) > 5000:
                del buffer[: len(buffer) - 5000]
            if self.current_id() == instance_id:
                self.console.appendPlainText(text)

        @Slot(str, int, float, str)
        def on_game_finished(self, instance_id: str, code: int, elapsed: float, error: str) -> None:
            session = self.games.pop(instance_id, None)
            self.lan_open_confirmed.discard(instance_id)
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
            self.catalog_search_generation += 1
            self.catalog_append_pending = False
            self.mr_context, self.mr_offset, self.mr_more = None, 0, False
            self.mr_previous.setEnabled(False)
            self.mr_next.setEnabled(False)
            self.mr_results.clear()
            self.mr_page_label.setText("Настройки поиска изменились · нажмите «Найти»")
            self.update_catalog_details(None)

        def catalog_cached_image(self, url: Any) -> QImage | None:
            safe_url = catalog_icon_url(url)
            image = self._catalog_icon_cache.get(safe_url) if safe_url else None
            if image is not None:
                self._catalog_icon_cache.move_to_end(safe_url)
            return image

        def catalog_list_icon(self, hit: dict[str, Any], fallback_name: str) -> QIcon:
            image = self.catalog_cached_image(hit.get("icon_url"))
            if image is not None:
                return QIcon(QPixmap.fromImage(image).scaled(
                    self.mr_results.iconSize(), Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
            return interface_icon(fallback_name, THEMES[self.theme]["muted"], THEMES[self.theme]["accent"])

        def queue_catalog_icons(self, hits: list[dict[str, Any]]) -> None:
            urls = set()
            for hit in hits:
                url = catalog_icon_url(hit.get("icon_url"))
                if url and url not in self._catalog_icon_cache and url not in self._catalog_icon_pending:
                    self._catalog_icon_pending.add(url)
                    self._catalog_icon_queue.put(url)
                    urls.add(url)
            if urls and not self._catalog_icon_workers:
                for index in range(min(3, len(urls))):
                    worker = threading.Thread(target=self.catalog_icon_worker,
                                              name=f"MCSync-catalog-icons-{index + 1}", daemon=True)
                    self._catalog_icon_workers.append(worker)
                    worker.start()

        def catalog_icon_worker(self) -> None:
            while not self._catalog_icon_stop.is_set():
                try:
                    url = self._catalog_icon_queue.get(timeout=0.25)
                except queue.Empty:
                    continue
                if url is None:
                    self._catalog_icon_queue.task_done()
                    return
                try:
                    data = fetch_catalog_icon(url)
                except Exception:
                    data = b""  # The vector project-type icon remains as a safe fallback.
                try:
                    if not self._catalog_icon_stop.is_set():
                        self.bridge.catalog_icon_ready.emit(url, data)
                except RuntimeError:
                    return
                finally:
                    self._catalog_icon_queue.task_done()

        def catalog_icon_loaded(self, url: str, data: bytes) -> None:
            self._catalog_icon_pending.discard(url)
            if self.closing or not data or catalog_icon_url(url) != url:
                return
            buffer = QBuffer()
            buffer.setData(QByteArray(data))
            if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
                return
            reader = QImageReader(buffer)
            reader.setDecideFormatFromContent(True)
            size = reader.size()
            if (not size.isValid() or size.width() <= 0 or size.height() <= 0
                    or size.width() > MAX_CATALOG_ICON_DIMENSION
                    or size.height() > MAX_CATALOG_ICON_DIMENSION):
                buffer.close()
                return
            image = reader.read()
            buffer.close()
            if image.isNull():
                return
            image = image.scaled(QSize(64, 64), Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            if image.isNull():
                return
            self._catalog_icon_cache[url] = image
            self._catalog_icon_cache.move_to_end(url)
            while len(self._catalog_icon_cache) > CATALOG_ICON_CACHE_LIMIT:
                self._catalog_icon_cache.popitem(last=False)
            list_size = self.mr_results.iconSize()
            for index in range(self.mr_results.count()):
                item = self.mr_results.item(index)
                hit = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(hit, dict) and catalog_icon_url(hit.get("icon_url")) == url:
                    pixmap = QPixmap.fromImage(image).scaled(
                        list_size, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
                    item.setIcon(QIcon(pixmap))
            selected = self.mr_results.currentItem()
            hit = selected.data(Qt.ItemDataRole.UserRole) if selected else {}
            if isinstance(hit, dict) and catalog_icon_url(hit.get("icon_url")) == url:
                self.catalog_project_icon.setPixmap(QPixmap.fromImage(image).scaled(
                    36, 36, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))

        def set_catalog_source(self, source: str) -> None:
            index = self.catalog_source.findData(source)
            if index >= 0 and index != self.catalog_source.currentIndex():
                self.catalog_source.setCurrentIndex(index)
            for key, provider in self.catalog_source_buttons.items():
                provider.setChecked(key == source)

        def catalog_project_url(self, hit: dict[str, Any]) -> str:
            source = hit.get("provider", self.catalog_source.currentData())
            project_type = hit.get("project_type", "mod")
            if source == "modrinth":
                slug = hit.get("slug") or hit.get("project_id")
                if isinstance(slug, str) and slug:
                    kind = project_type if project_type in ("mod", "resourcepack", "shader", "modpack") else "mod"
                    return f"https://modrinth.com/{kind}/{quote(slug, safe='')}"
                return ""
            website = hit.get("website_url", "")
            if isinstance(website, str) and website:
                parsed = urlsplit(website)
                if (parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password
                        and (parsed.hostname == "curseforge.com" or parsed.hostname.endswith(".curseforge.com"))):
                    return website
            slug = hit.get("slug", "")
            if not isinstance(slug, str) or not slug:
                return ""
            section = {"mod": "mc-mods", "resourcepack": "texture-packs", "shader": "shaders"}.get(project_type)
            return f"https://www.curseforge.com/minecraft/{section}/{quote(slug, safe='')}" if section else ""

        def update_catalog_details(self, hit: dict[str, Any] | None) -> None:
            if not hit:
                self.catalog_project_icon.setPixmap(interface_icon(
                    "catalog", THEMES[self.theme]["muted"], THEMES[self.theme]["accent"]).pixmap(36, 36))
                self.catalog_project_title.setText("Выберите проект")
                self.catalog_project_author.setText("Modrinth или CurseForge")
                self.catalog_project_badge.setText("КАТАЛОГ")
                self.catalog_project_stats.setText("Моды, ресурспаки и шейдеры для Minecraft Java")
                self.catalog_project_description.setText(
                    "Выберите результат слева, чтобы увидеть описание, автора, ссылку и целевую версию.")
                self.catalog_project_target.setText("Установка выберет последнюю совместимую версию.")
                self.catalog_project_link.setProperty("catalogUrl", "")
                self.catalog_project_link.setEnabled(False)
                return
            project_type = hit.get("project_type", "mod")
            icon_name = {"mod": "mods", "resourcepack": "resources", "shader": "shaders",
                         "modpack": "catalog"}.get(project_type, "catalog")
            colors = THEMES[self.theme]
            image = self.catalog_cached_image(hit.get("icon_url"))
            if image is None:
                self.catalog_project_icon.setPixmap(
                    interface_icon(icon_name, colors["muted"], colors["accent"]).pixmap(36, 36))
            else:
                self.catalog_project_icon.setPixmap(QPixmap.fromImage(image).scaled(
                    36, 36, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
            self.catalog_project_title.setText(str(hit.get("title", "Проект")))
            author = hit.get("author", "")
            self.catalog_project_author.setText(str(author) if author else str(hit.get("provider", "")))
            badge = {"mod": "МОД", "resourcepack": "РЕСУРСПАК", "shader": "ШЕЙДЕР", "modpack": "СБОРКА"}.get(
                project_type, "ПРОЕКТ")
            self.catalog_project_badge.setText(badge)
            downloads = hit.get("downloads")
            stats = str(hit.get("provider", "Каталог"))
            if type(downloads) is int and downloads >= 0:
                stats += " · " + f"{downloads:,}".replace(",", " ") + " загрузок"
            self.catalog_project_stats.setText(stats)
            description = hit.get("description", "")
            description = description.strip() if isinstance(description, str) else ""
            self.catalog_project_description.setText(
                description[:560] + ("…" if len(description) > 560 else "") if description else
                "Автор не добавил описание проекта.")
            context = self.mr_context
            target = context[3] if context and len(context) >= 4 else None
            if target:
                self.catalog_project_target.setText(
                    f"Подбор версии: Minecraft {target.minecraft} · {LOADERS[target.loader]} · последняя совместимая")
            elif project_type == "modpack":
                self.catalog_project_target.setText("Сборка будет импортирована в новую отдельную инстанцию.")
            else:
                self.catalog_project_target.setText("Выберите локальную сборку для установки совместимой версии.")
            url = self.catalog_project_url(hit)
            self.catalog_project_link.setProperty("catalogUrl", url)
            self.catalog_project_link.setEnabled(bool(url))

        def open_catalog_project(self) -> None:
            url = self.catalog_project_link.property("catalogUrl")
            if isinstance(url, str) and url:
                QDesktopServices.openUrl(QUrl(url))

        def catalog_source_changed(self, *args: Any) -> None:
            source = self.catalog_source.currentData()
            relevance_index = self.mr_sort.findData("relevance")
            if relevance_index >= 0:
                label_text = "По релевантности" if source == "modrinth" else "По популярности"
                self.mr_sort.setItemText(relevance_index, label_text)
            for key, provider in self.catalog_source_buttons.items():
                provider.setChecked(key == source)
            modpack_index = self.mr_type.findData("modpack")
            modpack_item = self.mr_type.model().item(modpack_index)
            modpack_item.setEnabled(source == "modrinth")
            if source == "curseforge" and self.mr_type.currentData() == "modpack":
                self.mr_type.setCurrentIndex(self.mr_type.findData("mod"))
            self.cf_settings_btn.setVisible(source == "curseforge")
            self.catalog_key_hint.setVisible(source == "curseforge" and
                                             not bool(self.store.settings.get("curseforge_api_key")))
            if source == "curseforge":
                self.mr_update_btn.setText("Обновить CurseForge-проекты")
                self.mr_update_btn.setToolTip("Обновляются только CurseForge-проекты, установленные в этом лаунчере.")
            else:
                self.mr_update_btn.setText("Обновить Modrinth-проекты")
                self.mr_update_btn.setToolTip("Обновляются только Modrinth-проекты, установленные в этом лаунчере.")
            self.invalidate_modrinth_pages()
            self.modrinth_selection_changed()

        def update_catalog_controls(self) -> None:
            source = self.catalog_source.currentData()
            has_key = bool(self.store.settings.get("curseforge_api_key"))
            self.catalog_key_hint.setVisible(source == "curseforge" and not has_key)
            self.cf_settings_btn.setVisible(source == "curseforge")
            self.cf_settings_btn.setEnabled(not self.busy)
            for provider in self.catalog_source_buttons.values():
                provider.setEnabled(not self.busy)
            for widget in (self.mr_query, self.mr_type, self.mr_sort, self.mr_filter, self.mr_search_btn,
                           self.mr_previous, self.mr_next):
                widget.setEnabled(not self.busy)
            self.mr_update_btn.setEnabled(not self.busy)
            self.modrinth_selection_changed()

        def catalog_scroll_changed(self, value: int = 0) -> None:
            if not self.mr_results.isVisible():
                return
            scrollbar = self.mr_results.verticalScrollBar()
            near_bottom = scrollbar.maximum() == 0 or scrollbar.maximum() - value <= max(2, scrollbar.pageStep() // 4)
            if (near_bottom and self.mr_context and self.mr_more and not self.busy
                    and not self.catalog_append_pending):
                self.catalog_append_pending = True
                self.search_catalog(offset=self.mr_offset + 30, context=self.mr_context, append=True)

        def change_modrinth_page(self, direction: int) -> None:
            if not self.busy and self.mr_context:
                offset = self.mr_offset + direction * 30
                if offset >= 0:
                    self.search_catalog(offset=offset, context=self.mr_context)

        def search_modrinth(self, *, offset: int = 0, context: tuple | None = None) -> None:
            """Compatibility name retained for callers; searches the chosen catalog source."""
            self.search_catalog(offset=offset, context=context)

        def search_catalog(self, *, offset: int = 0, context: tuple | None = None,
                           append: bool = False) -> None:
            if self.busy:
                return
            if append:
                if not self.mr_context or not self.mr_more:
                    self.catalog_append_pending = False
                    return
                context = self.mr_context
                offset = self.mr_offset + 30
            if context:
                if len(context) == 5:
                    source, query, kind, inst, sort = context
                elif len(context) == 4:
                    source, query, kind, inst = context
                    sort = self.mr_sort.currentData()
                elif len(context) == 3:
                    query, kind, inst = context
                    source, sort = self.catalog_source.currentData(), self.mr_sort.currentData()
                else:
                    raise UserError("Некорректный контекст поиска каталога.")
            else:
                source, query, kind = self.catalog_source.currentData(), self.mr_query.text().strip(), self.mr_type.currentData()
                inst = self.current_instance() if self.mr_filter.isChecked() else None
                sort = self.mr_sort.currentData()
            api_key = self.store.settings.get("curseforge_api_key", "")
            if source == "curseforge" and not api_key:
                self.catalog_key_hint.setVisible(True)
                self.statusBar().showMessage("Для CurseForge сначала укажите API-ключ в настройках.", 8000)
                return
            if source == "curseforge" and kind == "modpack":
                self.mr_type.setCurrentIndex(self.mr_type.findData("mod"))
                kind = "mod"
            if sort not in CATALOG_SORTS:
                raise UserError("Некорректная сортировка каталога.")
            context = (source, query, kind, inst, sort)
            self.catalog_search_generation += 1
            generation = self.catalog_search_generation
            if append:
                self.catalog_append_pending = True
                self.mr_page_label.setText("Загружаем ещё результаты…")
            else:
                self.catalog_append_pending = False
                self.mr_results.clear()
                self.update_catalog_details(None)
                self.mr_page_label.setText("Поиск в каталоге…")

            def work(progress: Progress, cancel: threading.Event) -> list[dict[str, Any]]:
                if source == "modrinth":
                    with ModrinthClient() as client:
                        hits = client.search(query, kind, inst, offset=offset, sort=sort)
                else:
                    with CurseForgeClient(api_key) as client:
                        hits = client.search(query, kind, inst, offset=offset, sort=sort)
                check_cancel(cancel)
                return hits

            def done(hits: list[dict[str, Any]]) -> None:
                if generation != self.catalog_search_generation:
                    return
                self.catalog_append_pending = False
                self.mr_context, self.mr_offset, self.mr_more = context, offset, len(hits) == 30
                self.mr_results.blockSignals(True)
                if not append:
                    self.mr_results.clear()
                icon_names = {"mod": "mods", "resourcepack": "resources", "shader": "shaders",
                              "modpack": "catalog"}
                for hit in hits:
                    hit = dict(hit)
                    hit.setdefault("provider", source)
                    title = hit.get("title", "Проект")
                    description = hit.get("description", "")
                    author = hit.get("author", "")
                    details = ""
                    if isinstance(author, str) and author:
                        details = (details + " · " if details else "") + author
                    downloads = hit.get("downloads")
                    if type(downloads) is int and downloads >= 0:
                        details = (details + " · " if details else "") + f"{downloads:,}".replace(",", " ") + " загрузок"
                    project_kind = hit.get("project_type", context[2])
                    icon_name = icon_names.get(project_kind, "catalog")
                    icon = self.catalog_list_icon(hit, icon_name)
                    item = QListWidgetItem(icon, title + ("\n" + details if details else ""))
                    item.setSizeHint(QSize(330, 66))
                    item.setData(Qt.ItemDataRole.UserRole, hit)
                    item.setToolTip(description if isinstance(description, str) else title)
                    self.mr_results.addItem(item)
                self.mr_results.blockSignals(False)
                self.queue_catalog_icons(hits)
                target = f" · {inst.minecraft} / {LOADERS[inst.loader]}" if inst else " · все версии"
                provider = "Modrinth" if source == "modrinth" else "CurseForge"
                if append:
                    result_text = f"Загружено: {self.mr_results.count()}" if hits else "Все результаты загружены"
                else:
                    result_text = f"Результаты {offset + 1}–{offset + len(hits)}" if hits else "Ничего не найдено"
                self.mr_page_label.setText(f"{provider}: {result_text}{target}")
                self.mr_previous.setEnabled(offset > 0)
                self.mr_next.setEnabled(self.mr_more)
                if hits and not append:
                    self.mr_results.setCurrentRow(0)
                elif not hits and not self.mr_results.count():
                    self.update_catalog_details(None)
                self.modrinth_selection_changed()
                if self.mr_more:
                    QTimer.singleShot(0, lambda: self.catalog_scroll_changed(
                        self.mr_results.verticalScrollBar().value()))
            provider_name = "Modrinth" if source == "modrinth" else "CurseForge"
            self.run_task(f"Поиск {provider_name}", work, done)

        def modrinth_selection_changed(self, *args: Any) -> None:
            item, inst = self.mr_results.currentItem(), self.current_instance()
            data = item.data(Qt.ItemDataRole.UserRole) if item else {}
            self.update_catalog_details(data if isinstance(data, dict) and data else None)
            source = data.get("provider", self.catalog_source.currentData()) if isinstance(data, dict) else ""
            modpack = bool(data and source == "modrinth" and data.get("project_type") == "modpack")
            eligible = bool(data and (modpack or
                            (inst and not inst.sync_url and not self.is_locked(inst.id))))
            needs_loader = bool(source == "curseforge" and data and data.get("project_type") == "mod"
                                and inst and inst.loader == "vanilla")
            if (source == "curseforge" and not self.store.settings.get("curseforge_api_key")) or needs_loader:
                eligible = False
            if needs_loader:
                self.mr_install_btn.setToolTip("Выберите Fabric, Quilt, Forge или NeoForge в настройках сборки.")
            elif source == "curseforge" and not self.store.settings.get("curseforge_api_key"):
                self.mr_install_btn.setToolTip("Добавьте личный API-ключ CurseForge в настройках.")
            else:
                self.mr_install_btn.setToolTip("")
            self.mr_install_btn.setEnabled(not self.busy and eligible)
            self.mr_update_btn.setEnabled(not self.busy and bool(inst and not inst.sync_url and not self.is_locked(inst.id))
                                           and (source != "curseforge" or bool(self.store.settings.get("curseforge_api_key"))))

        def install_selected_modrinth(self) -> None:
            item = self.mr_results.currentItem()
            if not item:
                return
            hit, inst = item.data(Qt.ItemDataRole.UserRole), self.current_instance()
            source = hit.get("provider", self.catalog_source.currentData())
            kind = hit.get("project_type", "mod")
            title = hit.get("title", "Проект")
            if kind == "modpack" and source == "modrinth":
                if not message(self, "Установить сборку?", title +
                               "\nБудет создана новая сборка. Вы доверяете модам из этого проекта?", question=True):
                    return
                filtered = inst if self.mr_filter.isChecked() else None
                self.run_task("Установка Modrinth-сборки", lambda p, c: install_modrinth_pack(self.store,
                              hit["project_id"], filtered, progress=p, cancel=c),
                              lambda new: self.refresh_instances(new.id))
                return
            if not inst or self.is_locked(inst.id) or inst.sync_url:
                message(self, "Каталог", "Выберите разблокированную локальную сборку. В подписке файлы устанавливает хост.")
                return
            if source == "curseforge" and not self.store.settings.get("curseforge_api_key"):
                self.catalog_key_hint.setVisible(True)
                message(self, "Нужен API-ключ CurseForge", "Добавьте личный API-ключ в Настройки → CurseForge.")
                return
            if not self.save_current(notify=False):
                return
            inst = self.store.load(inst.id)
            if not message(self, "Установить проект?", title +
                           "\nБудут установлены совместимые обязательные зависимости. Устанавливайте файлы только из источников, которым доверяете.",
                           question=True):
                return
            if source == "curseforge":
                try:
                    project_id = int(hit["project_id"])
                except (TypeError, ValueError):
                    message(self, "CurseForge", "У проекта некорректный номер.")
                    return
                key = self.store.settings.get("curseforge_api_key", "")
                self.run_task("Установка CurseForge", lambda p, c: install_curseforge(
                              inst, project_id, kind, key, title=title, progress=p, cancel=c),
                              lambda titles: self.catalog_install_done(inst, source, kind, titles), inst.id)
            else:
                self.run_task("Установка Modrinth", lambda p, c: install_modrinth(
                              inst, hit["project_id"], progress=p, cancel=c),
                              lambda titles: self.catalog_install_done(inst, source, kind, titles), inst.id)

        def catalog_install_done(self, inst: Instance, source: str, kind: str, titles: list[str]) -> None:
            provider = "CurseForge" if source == "curseforge" else "Modrinth"
            folder = {"mod": "mods", "resourcepack": "resourcepacks", "shader": "shaderpacks"}.get(kind, "mods")
            summary = "Установлены: " + ", ".join(titles)
            host = self.hosts.get(inst.id)
            if host:
                if folder in host.folders:
                    summary += ". Друг получит выбранные файлы при следующей синхронизации или запуске."
                else:
                    summary += f". Папка {folder} сейчас выключена в настройках пати; остановите пати и включите её, чтобы передавать файлы."
            else:
                summary += f". Для передачи другу включите папку {folder} в настройках пати."
            self.statusBar().showMessage(provider + " · " + summary, 20000)

        def update_mods(self) -> None:
            inst = self.current_instance()
            if not inst or inst.sync_url or self.is_locked(inst.id):
                return
            source = self.catalog_source.currentData()
            if source == "curseforge":
                key = self.store.settings.get("curseforge_api_key", "")
                if not key:
                    self.catalog_key_hint.setVisible(True)
                    self.statusBar().showMessage("Для обновления CurseForge добавьте API-ключ в настройках.", 8000)
                    return
                function = lambda p, c: update_curseforge(inst, key, progress=p, cancel=c)
                title, provider = "Обновление CurseForge", "CurseForge"
            else:
                function = lambda p, c: update_modrinth(inst, progress=p, cancel=c)
                title, provider = "Обновление Modrinth", "Modrinth"
            def done(titles: list[str]) -> None:
                text = "Обновлены: " + ", ".join(titles) if titles else f"Новых совместимых версий {provider} нет."
                self.statusBar().showMessage(text, 15000)
            self.run_task(title, function, done, inst.id)

        def mark_logs_dirty(self, instance_id: str = "") -> None:
            instance_id = instance_id or self.current_id()
            if instance_id:
                self.logs_dirty_instances.add(instance_id)
            if instance_id == self.current_id():
                self.logs_dirty = True
            if self.logs_pending and self.logs_pending_instance == instance_id:
                self.logs_rescan_requested = True

        def refresh_logs(self, force: bool = True) -> None:
            inst = self.current_instance()
            instance_id = inst.id if inst else ""
            needs_refresh = self.logs_dirty or instance_id in self.logs_dirty_instances
            if not force and not needs_refresh and self.logs_instance == instance_id:
                if self.logs_rendered_instance != instance_id:
                    self.render_logs()
                return
            if self.logs_pending and self.logs_pending_instance == instance_id and not force:
                return
            self.logs_generation += 1
            generation = self.logs_generation
            self.logs_pending = False
            self.logs_pending_instance = ""
            self.logs_rescan_requested = False
            if inst is None:
                self.logs_entries = []
                self.logs_error = ""
                self.logs_instance = ""
                self.logs_dirty = False
                self.logs_combo.blockSignals(True)
                self.logs_combo.clear()
                self.logs_combo._mcsync_source_items = []
                self.logs_combo.blockSignals(False)
                self.logs_combo.setEnabled(True)
                self.log_view.clear()
                self.logs_rendered_instance = ""
                return

            inst_directory, game_directory = inst.directory, inst.game_dir
            self.logs_selected_path = str(self.logs_combo.currentData() or self.logs_selected_path)
            self.logs_combo.blockSignals(True)
            self.logs_combo.clear()
            loading_title = "Загружаем список логов…"
            self.logs_combo.addItem(translate_ui_text(loading_title), "")
            self.logs_combo._mcsync_source_items = [loading_title]
            self.logs_combo.blockSignals(False)
            self.logs_combo.setEnabled(False)
            self.log_view.clear()
            self.logs_pending = True
            self.logs_pending_instance = instance_id

            def scan() -> None:
                entries: list[tuple[str, str]] = []
                error = ""
                try:
                    launcher = inst_directory / "launcher.log"
                    if launcher.is_file() and not launcher.is_symlink():
                        entries.append(("launcher.log", str(launcher)))
                    for folder in ("logs", "crash-reports"):
                        for relative, path in reversed(iter_files(game_directory / folder)):
                            if path.suffix.casefold() in (".log", ".txt"):
                                entries.append((folder + "/" + relative, str(path)))
                except Exception as exc:
                    error = redact(str(exc)) or type(exc).__name__
                try:
                    self.bridge.logs_scanned.emit(generation, instance_id, entries, error)
                except RuntimeError:
                    pass  # The main window may have closed before the index was ready.

            threading.Thread(target=scan, name="MCSync-log-index", daemon=True).start()

        @Slot(int, str, object, str)
        def logs_scan_done(self, generation: int, instance_id: str,
                           entries: list[tuple[str, str]], error: str) -> None:
            if generation != self.logs_generation:
                return
            rescan = self.logs_rescan_requested
            self.logs_rescan_requested = False
            self.logs_pending = False
            self.logs_pending_instance = ""
            self.logs_instance = instance_id
            self.logs_entries = entries
            self.logs_error = error
            if rescan:
                self.logs_dirty_instances.add(instance_id)
            else:
                self.logs_dirty_instances.discard(instance_id)
            current_id = self.current_id()
            self.logs_dirty = bool(rescan and current_id == instance_id) or current_id != instance_id or current_id in self.logs_dirty_instances
            active = (current_id == instance_id and
                      self.main_pages.currentWidget() is self.detail_stack and
                      self.detail_stack.currentWidget() is self.details and
                      self.tabs.currentWidget() is self.logs_panel)
            if active and rescan:
                self.refresh_logs(force=False)
                return
            if active:
                self.render_logs()
            if error and current_id == instance_id:
                self.statusBar().showMessage("Не удалось прочитать список логов: " + error, 8000)

        def render_logs(self) -> None:
            self.logs_combo.blockSignals(True)
            self.logs_combo.clear()
            source_titles: list[str] = []
            if self.logs_error:
                error_title = "Ошибка чтения списка логов"
                self.logs_combo.addItem(translate_ui_text(error_title), "")
                source_titles.append(error_title)
            else:
                for title, path in self.logs_entries:
                    self.logs_combo.addItem(title, path)
                    source_titles.append(title)
            self.logs_combo._mcsync_source_items = source_titles
            selected = self.logs_combo.findData(self.logs_selected_path)
            self.logs_combo.setCurrentIndex(max(0, selected))
            self.logs_combo.blockSignals(False)
            self.logs_combo.setEnabled(True)
            self.logs_rendered_instance = self.logs_instance
            if self.logs_error:
                self.log_view.setPlainText(self.logs_error)
            else:
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

        def run_task(self, title: str, function: Callable, done: Callable | None = None, instance_id: str = "",
                     *, variant: str = "download") -> None:
            if self.busy:
                self.statusBar().showMessage("Сначала завершите текущую операцию.", 5000)
                return
            self.task_number += 1
            task_id = self.task_number
            cancel = threading.Event()
            self.task = {"id": task_id, "cancel": cancel, "done": done,
                         "instance_id": instance_id, "title": title, "variant": variant}
            self.busy = True
            self.task_card.begin(variant, title + "…")
            self.refresh_instances(reload_fields=False, navigate=False)

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
            self.task_card.set_stage(redact(text))
            self.task_card.set_percent(int(value), int(maximum))

        @Slot(int, object, str)
        def task_done(self, task_id: int, result: Any, error: str) -> None:
            if not self.task or self.task["id"] != task_id:
                return
            callback = self.task["done"]
            completed_title = self.task.get("title", "")
            completed_instance = self.task.get("instance_id", "")
            self.task, self.busy = None, False
            file_mutations = {"Добавление файлов", "Переключение файлов", "Удаление", "Синхронизация",
                              "Подготовка запуска", "Установка Modrinth", "Обновление Modrinth",
                              "Установка CurseForge", "Обновление CurseForge"}
            if not error and completed_title in file_mutations and completed_instance:
                for panel in self.file_panels.values():
                    if panel._instance_id == completed_instance:
                        panel.mark_dirty()
            if not error and completed_title in {"Синхронизация", "Подготовка запуска"} and completed_instance:
                self.mark_logs_dirty(completed_instance)
            self.refresh_instances(reload_fields=False)
            self.party_monitor.refresh()
            if completed_title.startswith("Поиск "):
                self.catalog_append_pending = False
                if error:
                    self.mr_page_label.setText("Не удалось загрузить результаты")
            if error.startswith("cancel:"):
                self.task_card.finish("cancelled", stage=error[7:])
            elif error:
                self.task_card.finish("error", stage="Операция не завершена")
                message(self, "Ошибка", error)
            else:
                self.task_card.finish("done", stage="Готово")
                if callback:
                    try:
                        callback(result)
                    except Exception as exc:
                        message(self, "Ошибка интерфейса", str(exc))

        def cancel_task(self) -> None:
            if self.task:
                self.task["cancel"].set()
                self.task_card.set_stage("Отмена… (ожидание завершения текущего запроса)")
            elif getattr(self, "_backup_cancel", None):
                self._backup_cancel.set()
                self.task_card.set_stage("Отмена создания бэкапа…")

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
            if hasattr(self, "lobby_page"):
                self.lobby_page.refresh(inst)

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
            self._catalog_icon_stop.set()
            for _ in self._catalog_icon_workers:
                self._catalog_icon_queue.put(None)
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
        error = qt_runtime_message(QT_IMPORT_ERROR)
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
    app.setWindowIcon(app_icon())
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
