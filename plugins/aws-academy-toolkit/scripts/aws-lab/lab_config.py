#!/usr/bin/env python3
"""Per-student local configuration: the student's AWS Academy Canvas module
URL (the "Launch AWS Academy Learner Lab" page).

This is deliberately stored OUTSIDE the plugin and outside any git repo, in
the student's home directory, because it's personal to their own course
enrollment and must never end up committed anywhere shared.

Usage as a CLI:
    python3 lab_config.py get
    python3 lab_config.py set "https://awsacademy.instructure.com/courses/.../modules/items/..."

Usage as a module (from the browser-driven workflow):
    from lab_config import get_course_url, set_course_url
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "nus-cloud-lab"
CONFIG_FILE = CONFIG_DIR / "config.json"


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


def get_course_url() -> str | None:
    return _load().get("course_url")


def set_course_url(url: str) -> None:
    data = _load()
    data["course_url"] = url.strip()
    _save(data)


def main():
    if len(sys.argv) < 2:
        print("usage: lab_config.py get|set [url]")
        sys.exit(1)

    action = sys.argv[1]
    if action == "get":
        url = get_course_url()
        print(url or "")
    elif action == "set":
        if len(sys.argv) < 3:
            print("usage: lab_config.py set <url>")
            sys.exit(1)
        set_course_url(sys.argv[2])
        print(f"saved to {CONFIG_FILE}")
    else:
        print(f"unknown action: {action}")
        sys.exit(1)


if __name__ == "__main__":
    main()
