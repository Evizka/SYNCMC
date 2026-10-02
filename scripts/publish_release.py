#!/usr/bin/env python3
"""Publish verified CI ZIPs without downloading them through the developer sandbox.

Run inside GitHub Actions with GH_TOKEN. A release stays a draft until every archive
and checksum is validated and uploaded. Published releases are never overwritten.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import zipfile
from pathlib import Path

ARCHIVES = {
    "MCSync-windows-x64.zip": "MCSync/",
    "MCSync-linux-x64.zip": "MCSync/",
    "MCSync-macos-arm64.zip": "MCSync.app/Contents/Resources/",
}
ARTIFACT_NAMES = {"MCSync-Windows-X64", "MCSync-Linux-X64", "MCSync-macOS-ARM64"}
REQUIRED_JOBS = {"windows-latest", "ubuntu-22.04", "macos-14",
                 "Real game / Java / loader installation (Windows)"}
PRIVATE_FILES = {"accounts.json", "settings.json", "draft.json", "host_settings.json", "sync_state.json", "installed.json"}


def gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"GitHub {' '.join(args[:2])}: {result.stderr.strip()}")
    return result.stdout


def api_pages(endpoint: str) -> list:
    # Older gh versions emit adjacent JSON documents with --paginate and have no --slurp.
    text = gh("api", endpoint, "--paginate").lstrip()
    decoder = json.JSONDecoder()
    pages = []
    while text:
        page, offset = decoder.raw_decode(text)
        pages.append(page)
        text = text[offset:].lstrip()
    return pages


def constants(source: str) -> dict[str, str]:
    values = {}
    for statement in ast.parse(source).body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name) and target.id in ("APP_VERSION", "DEFAULT_THEME"):
                    values[target.id] = ast.literal_eval(statement.value)
    return values


def validate_run(run: dict, repository: str) -> str:
    if (run.get("status") != "completed" or run.get("conclusion") != "success"
            or run.get("event") not in ("push", "workflow_dispatch")
            or (run.get("head_repository") or {}).get("full_name") != repository
            or run.get("path") != ".github/workflows/build.yml"):
        raise ValueError("Release requires a successful trusted build workflow, not a fork/PR run")
    sha = run.get("head_sha", "")
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise ValueError("Invalid build commit")
    return sha


def validate_build_results(jobs: list[dict], artifacts: list[dict]) -> None:
    successful = {job["name"] for job in jobs if job.get("conclusion") == "success"}
    available = {item["name"] for item in artifacts if not item.get("expired", True)}
    if not REQUIRED_JOBS <= successful or not ARTIFACT_NAMES <= available:
        raise ValueError("All three native builds and the live installation check must succeed; artifacts must not expire")


def validate_archives(directory: Path, source: bytes) -> list[Path]:
    assets = []
    for name, prefix in ARCHIVES.items():
        archive, checksum = directory / name, directory / (name + ".sha256")
        expected = checksum.read_text().strip().split()
        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        if expected != [actual, name]:
            raise ValueError("Invalid checksum: " + name)
        with zipfile.ZipFile(archive) as bundle:
            if bundle.testzip() is not None:
                raise ValueError("Corrupt ZIP: " + name)
            # Git on Windows may check out CRLF; no other source difference is allowed.
            packaged_source = bundle.read(prefix + "source/mcsync.py").replace(b"\r\n", b"\n")
            if packaged_source != source.replace(b"\r\n", b"\n"):
                raise ValueError("Archive source differs from the verified build commit: " + name)
            if any(Path(path).name in PRIVATE_FILES for path in bundle.namelist()):
                raise ValueError("Archive contains private launcher data: " + name)
            if name.startswith("MCSync-windows") and bundle.read("MCSync/MCSync.exe")[:2] != b"MZ":
                raise ValueError("Missing Windows executable")
        assets.extend((archive, checksum))
    return assets


def requested_run_id(explicit: str, commit_message: str) -> str:
    if explicit:
        run_id = explicit
    else:
        first_line = commit_message.splitlines()[0] if commit_message else ""
        match = re.fullmatch(r"release: ([0-9]+)", first_line)
        if not match:
            raise ValueError("Publication push must start with 'release: BUILD_RUN_ID'")
        run_id = match[1]
    if not re.fullmatch(r"[0-9]+", run_id):
        raise ValueError("Run ID must be numeric")
    return run_id


def inspect_run(run_id: str, repository: str, output: Path) -> dict:
    if not re.fullmatch(r"[0-9]+", run_id):
        raise ValueError("Run ID must be numeric")
    run = json.loads(gh("api", f"repos/{repository}/actions/runs/{run_id}"))
    sha = validate_run(run, repository)
    job_pages = api_pages(f"repos/{repository}/actions/runs/{run_id}/jobs")
    artifact_pages = api_pages(f"repos/{repository}/actions/runs/{run_id}/artifacts")
    validate_build_results([job for page in job_pages for job in page["jobs"]],
                           [item for page in artifact_pages for item in page["artifacts"]])
    source = subprocess.check_output(["git", "show", sha + ":mcsync.py"])
    version = constants(source.decode())["APP_VERSION"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Invalid application version")
    metadata = {"sha": sha, "tag": "v" + version, "version": version, "run_id": run_id,
                "repository": repository, "build_url": run["html_url"]}
    output.write_text(json.dumps(metadata))
    return metadata


def publish(directory: Path, metadata_path: Path) -> None:
    info = json.loads(metadata_path.read_text())
    source = subprocess.check_output(["git", "show", info["sha"] + ":mcsync.py"])
    assets = validate_archives(directory, source)
    source_zip = directory / f"MCSync-source-{info['version']}.zip"
    subprocess.run(["git", "archive", "--format=zip", "--prefix=MCSync-source/",
                    "--output=" + str(source_zip), info["sha"]], check=True)
    checksum = source_zip.with_suffix(".zip.sha256")
    checksum.write_text(f"{hashlib.sha256(source_zip.read_bytes()).hexdigest()}  {source_zip.name}\n")
    assets.extend((source_zip, checksum))
    pages = api_pages(f"repos/{info['repository']}/releases")
    existing = [item for page in pages for item in page]
    release = next((item for item in existing if item["tag_name"] == info["tag"]), None)
    if release:
        if not release["draft"]:
            raise ValueError("This release is already published; do not overwrite immutable binaries")
        if release["target_commitish"] != info["sha"]:
            raise ValueError("Existing draft targets a different commit")
    tag_ref = f"refs/tags/{info['tag']}"
    tagged = subprocess.run(["git", "rev-parse", "--verify", tag_ref + "^{commit}"], text=True, capture_output=True)
    if tagged.returncode == 0 and tagged.stdout.strip() != info["sha"]:
        raise ValueError("Existing tag points at a different commit")
    notes = directory / "release-notes.md"
    notes.write_text(f"""## Скачать и запустить
- **Windows x64:** `MCSync-windows-x64.zip` → распаковать целиком → `MCSync/MCSync.exe`.
- **Linux x64:** `MCSync-linux-x64.zip` → `MCSync/MCSync`.
- **macOS Apple Silicon:** `MCSync-macos-arm64.zip` → `MCSync.app`.
- Python не нужен. Это прямые ZIP без дополнительной обёртки GitHub Actions.
- Не переносите один EXE отдельно от `_internal`; не смешивайте файлы разных версий.
- Сохраните portable `data`/`portable.txt` перед обновлением. Обычная папка данных остаётся отдельно.

## MCSync {info['version']}
Aurora по умолчанию; шесть тем и три компоновки. Карточки, избранное, черновики,
диагностика, поиск файлов, страницы Modrinth и исправления установки/журналов.
Прежняя сохранённая тема не сбрасывается: при необходимости выберите Aurora в настройках.

## Проверки
[Успешная сборка и проверки]({info['build_url']}): Windows/Linux/macOS, source/frozen startup,
HTTP/GUI-тесты и реальная Windows-установка Minecraft 1.21.1 / Mojang Java / пяти загрузчиков.
Коммит: `{info['sha']}`. Все ZIP дополнительно проверены по SHA-256 и встроенному исходнику.

Предварительная версия; файлы не подписаны. Вход Microsoft с одобренным Client ID,
GPU и произвольные модпаки требуют проверки на реальном ПК. Важные миры сохраняйте отдельно.
Игра, аккаунты и приватные данные не включены в архивы. Сверяйте файлы `.sha256`.
""", encoding="utf-8")
    if release:
        gh("release", "edit", info["tag"], "--repo", info["repository"], "--notes-file", str(notes))
    else:
        gh("release", "create", info["tag"], "--repo", info["repository"], "--target", info["sha"],
           "--title", f"MCSync {info['version']} — Aurora", "--prerelease", "--draft", "--notes-file", str(notes))
    gh("release", "upload", info["tag"], "--repo", info["repository"], "--clobber", *(str(path) for path in assets))
    uploaded = json.loads(gh("release", "view", info["tag"], "--repo", info["repository"], "--json", "assets,isDraft"))
    actual_assets = {item["name"]: item["size"] for item in uploaded["assets"]}
    expected_assets = {path.name: path.stat().st_size for path in assets}
    if not uploaded["isDraft"] or actual_assets != expected_assets:
        raise ValueError("Uploaded assets are incomplete or unexpected; release remains a draft")
    gh("release", "edit", info["tag"], "--repo", info["repository"], "--prerelease", "--draft=false")
    print(f"Published: https://github.com/{info['repository']}/releases/tag/{info['tag']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--run-id", default="")
    inspect.add_argument("--commit-message", default="")
    inspect.add_argument("--metadata", type=Path, required=True)
    upload = sub.add_parser("publish")
    upload.add_argument("--directory", type=Path, required=True)
    upload.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "inspect":
        run_id = requested_run_id(args.run_id, args.commit_message)
        inspect_run(run_id, os.environ["GITHUB_REPOSITORY"], args.metadata)
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                output.write(f"run_id={run_id}\n")
    else:
        publish(args.directory, args.metadata)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            # Keep failures readable via the Checks API even when runner logs are inaccessible.
            message = f"{type(error).__name__}: {error}"
            message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print("::error title=Release publication::" + message, flush=True)
        raise
