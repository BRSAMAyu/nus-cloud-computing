#!/usr/bin/env python3
"""SessionStart hook: the one shared place all three skills get their
session-level context from, instead of each skill re-implementing its own
"check the config, ask the student, explain myself" logic.

Two things happen here, every session:

1. Once ever (gated by a marker file in ${CLAUDE_PLUGIN_DATA}): inject a
   short orientation explaining the three skills exist and how first-run
   setup works. Never repeats after that.
2. Every session, cheaply: inject whatever the student already has saved
   (course_url, language, browser_assist) as plain context, so no skill
   needs to shell out to lab_config.py just to check — it's already in
   context by the time the student's first message arrives. This is also
   what makes language/course-URL/browser-automation preferences apply
   uniformly across all three skills without each one repeating the same
   instructions.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lab_config import get_value  # noqa: E402

MARKER_NAME = "onboarded.marker"

WELCOME = """\
This is the student's first Claude Code session since installing the
`aws-academy-toolkit` plugin (nus-cloud-computing marketplace). Before
responding to whatever they actually asked, give a short (3-5 sentence)
one-time orientation — not a wall of text — covering:

1. Three skills are available: `aws-lab-ops` (start/resume the AWS Academy
   lab session, refresh credentials, rebuild/verify/tear down the shared
   MyEKS cluster), `lab-tutor` (Socratic help with the L1-L4 Kubernetes
   labs), and `deploy-doctor` (checks whether a group project will deploy
   to this course's EKS). They don't need to invoke these explicitly by
   name — just describe what they need and the right one activates.
2. Saved settings (course URL, language, browser-automation preference —
   see the "Saved session config" block also in this context) persist
   across every future session, so first-run questions only happen once.

Keep this brief and skip it entirely if it would be redundant with
whatever the student's actual first message already makes obvious.
"""


def marker_path() -> Path:
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    base = Path(plugin_data) if plugin_data else Path.home() / ".config" / "nus-cloud-computing"
    return base / MARKER_NAME


def describe(key: str, value: str | None, unset_hint: str) -> str:
    return f"- {key}: {value!r}" if value else f"- {key}: not set — {unset_hint}"


def build_config_block() -> str:
    course_url = get_value("course_url")
    language = get_value("language")
    browser_assist = get_value("browser_assist")
    lines = [
        "Saved session config for this student (already loaded — do not "
        "re-run lab_config.py just to check these; only re-run it to change "
        "a value):",
        describe("course_url", course_url,
                 "aws-lab-ops will ask for it the first time it's needed"),
        describe("language", language,
                 "mirror whatever language the student writes in, as usual"),
        describe("browser_assist", browser_assist,
                 "aws-lab-ops will ask once whether to try Claude-in-Chrome "
                 "browser automation or use manual credential paste, then "
                 "remember the answer"),
    ]
    return "\n".join(lines)


def main() -> None:
    marker = marker_path()
    parts = [build_config_block()]
    first_run = not marker.exists()
    if first_run:
        parts.insert(0, WELCOME)

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n\n".join(parts),
        }
    }))

    if first_run:
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("onboarded\n")
        except OSError:
            pass  # better to show the welcome again than crash the hook


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - a hook must never break the session
        print(f"onboarding hook error (non-fatal): {exc}", file=sys.stderr)
        sys.exit(1)
