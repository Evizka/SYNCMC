#!/usr/bin/env python3
"""Opt-in real downloads: install game/loaders/Java, validate command, never start a game.

No Microsoft account or credentials are used. Game/runtime files remain in a temporary
folder and are never put into build archives. This is separate from deterministic tests.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import mcsync as m


def check(loaders: list[str], minecraft: str = "1.21.1") -> dict:
    report = {"application": m.APP_VERSION, "minecraft": minecraft, "platform": sys.platform, "installations": []}
    m.check_launcher_library()
    with tempfile.TemporaryDirectory(prefix="mcsync-live-install-") as directory:
        store = m.Store(directory)
        account = m.Accounts(store).add_offline("MCSyncSmoke")
        for loader in loaders:
            started = time.monotonic()
            print(f"Installing {minecraft} / {loader} with automatic Mojang Java", flush=True)
            inst = store.create("Network smoke " + loader, minecraft=minecraft, loader=loader, ram_min=512, ram_max=1024)
            for attempt in range(2):
                try:
                    current, version, java = m.ensure_install(store, inst)
                    break
                except (m.requests.Timeout, m.requests.ConnectionError):
                    if attempt:
                        raise
                    print("Temporary upstream network failure; retrying this loader once", flush=True)
                    time.sleep(2)
            major = m.java_major_version(java)
            assert major >= 21, f"Expected Java 21+ for {minecraft}, got {major}"
            assert m.installation_ready(store, current), f"Missing marker/version JSON for {loader}"
            command = m.minecraft_command(store, current, version, java, account)
            assert command[0] == java and "-Xmx1024M" in command
            assert "--gameDir" in command and "--assetsDir" in command
            assert version in command
            # A second call exercises an actually installed marker; no forced repair.
            ready, ready_version, ready_java = m.ensure_install(store, current)
            assert ready.identity == current.identity and ready_version == version and ready_java == java
            report["installations"].append({"loader": loader, "loader_version": current.loader_version,
                                             "installed_version": version, "java_major": major,
                                             "seconds": round(time.monotonic() - started, 1)})
            print(json.dumps(report["installations"][-1]), flush=True)
    report["limitations"] = "No game/GPU launch, Microsoft sign-in or arbitrary modpack compatibility is tested."
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loaders", choices=list(m.LOADERS), nargs="+", default=["vanilla", "fabric", "neoforge"])
    parser.add_argument("--minecraft", default="1.21.1")
    parser.add_argument("--report", type=Path, default=ROOT / "test-output" / "live-install.json")
    args = parser.parse_args()
    try:
        result = check(args.loaders, args.minecraft)
        m.atomic_json(args.report, result)
    except Exception as exc:
        # Annotations can be read through GitHub API even if signed log downloads
        # are unavailable in a particular sandbox. These checks use no credentials.
        error = m.redact(traceback.format_exc()).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print("::error title=Live installation failed::" + error, flush=True)
        m.atomic_json(args.report, {"version": m.APP_VERSION, "error": m.redact(str(exc))})
        raise
