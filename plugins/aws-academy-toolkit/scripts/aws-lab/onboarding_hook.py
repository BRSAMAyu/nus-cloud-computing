#!/usr/bin/env python3
"""SessionStart hook: show a one-time orientation message the first time a
student opens Claude Code after installing this plugin, then never again.

Runs on every session (that's how SessionStart works), so it must stay fast
and silent after the first run: a marker file in the plugin's persistent
data directory (${CLAUDE_PLUGIN_DATA}, survives updates/reinstalls) records
that onboarding already happened.

Per Claude Code's SessionStart contract, printing a JSON object with
hookSpecificOutput.additionalContext injects that text into the model's
context before the first prompt; printing nothing (and exiting 0) does
nothing, which is what every session after the first should do.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

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
2. First-run setup for `aws-lab-ops`: it will ask for their AWS Academy
   course URL once (stored locally, never shared).
3. If they have the Claude in Chrome extension connected and are already
   logged into their course page, credential refresh can be fully
   automatic; otherwise it'll ask them to paste the credential block
   manually — both work fine.
4. They can set a language preference (e.g. Chinese) if they'd rather all
   three skills consistently respond in a language other than whatever
   they happen to type in a given message — mention this only briefly,
   as an option, not a requirement.

Keep this brief and skip it entirely if it would be redundant with
whatever the student's actual first message already makes obvious.
"""


def marker_path() -> Path:
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    base = Path(plugin_data) if plugin_data else Path.home() / ".config" / "nus-cloud-computing"
    return base / MARKER_NAME


def main() -> None:
    marker = marker_path()
    if marker.exists():
        # Already onboarded on this machine — stay silent and fast.
        return

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": WELCOME,
        }
    }))

    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("onboarded\n")
    except OSError:
        # If we can't persist the marker, better to onboard again next
        # session than to crash the hook.
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - a hook must never break the session
        print(f"onboarding hook error (non-fatal): {exc}", file=sys.stderr)
        sys.exit(1)
