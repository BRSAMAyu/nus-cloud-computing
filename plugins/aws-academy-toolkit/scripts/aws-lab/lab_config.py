#!/usr/bin/env python3
"""Per-student local configuration: the AWS Academy Canvas module URL and an
optional language preference.

This is deliberately stored OUTSIDE the plugin and outside any git repo, in
the student's home directory, because it's personal to their own course
enrollment / preference and must never end up committed anywhere shared.

Usage as a CLI:
    python3 lab_config.py get course_url
    python3 lab_config.py set course_url "https://awsacademy.instructure.com/courses/.../modules/items/..."
    python3 lab_config.py get language
    python3 lab_config.py set language zh

Usage as a module (from the browser-driven workflow):
    from lab_config import get_value, set_value
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "nus-cloud-computing"
CONFIG_FILE = CONFIG_DIR / "config.json"
KNOWN_KEYS = ("course_url", "language", "browser_assist")


def _load() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


def get_value(key: str) -> str | None:
    return _load().get(key)


def set_value(key: str, value: str) -> None:
    data = _load()
    data[key] = value.strip()
    _save(data)


# Convenience wrappers kept for readability at call sites.
def get_course_url() -> str | None:
    return get_value("course_url")


def set_course_url(url: str) -> None:
    set_value("course_url", url)


def get_language() -> str | None:
    return get_value("language")


def set_language(language: str) -> None:
    set_value("language", language)


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("get", "set"):
        print("usage: lab_config.py get <course_url|language>")
        print("       lab_config.py set <course_url|language> <value>")
        sys.exit(1)

    action, key = sys.argv[1], sys.argv[2]
    if key not in KNOWN_KEYS:
        print(f"unknown key '{key}' (known: {', '.join(KNOWN_KEYS)})")
        sys.exit(1)

    if action == "get":
        print(get_value(key) or "")
    else:
        if len(sys.argv) < 4:
            print(f"usage: lab_config.py set {key} <value>")
            sys.exit(1)
        set_value(key, sys.argv[3])
        print(f"saved {key} to {CONFIG_FILE}")


if __name__ == "__main__":
    main()
