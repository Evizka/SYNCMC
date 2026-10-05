#!/usr/bin/env python3
"""Emit JUnit failures as CI annotations without depending on downloadable runner logs."""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def annotations(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []
    root = ET.parse(path).getroot()
    output = []
    for case in root.iter("testcase"):
        for failure in (*case.findall("failure"), *case.findall("error")):
            title = case.get("name", "Test failure")
            text = failure.text or failure.get("message", "Test failed")
            text = re.sub(r"(https?://[^/\s]+/)[A-Za-z0-9_-]{16,}(?=/|[\s'\"),]|$)", r"\1[hidden]", text)
            text = re.sub(r"/[A-Za-z0-9_-]{16,}(?=/(?:manifest\.json|party(?:\.json|/)|files/))", "/[hidden]", text)
            output.append((title, text[-6000:]))
    return output


def escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


if __name__ == "__main__":
    for title, message in annotations(Path(sys.argv[1])):
        print(f"::error title={escape(title).replace(',', ' ').replace(':', ' ')}::{escape(message)}", flush=True)
