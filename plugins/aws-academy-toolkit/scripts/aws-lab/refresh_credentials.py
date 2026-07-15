#!/usr/bin/env python3
"""Write a freshly-copied AWS Academy Learner Lab credential block to
~/.aws/credentials and verify it works.

This does NOT log in for you. AWS Academy's "AWS Details" > "AWS CLI" panel
already prints a ready-to-use [default] credentials block (temporary
access key, secret key, session token) once you've started the lab in your
browser and authenticated yourself. Copy that block and hand it to this
script — either as a file or piped via stdin — and it writes it to the
standard AWS CLI location and confirms `aws sts get-caller-identity` works.

Usage:
    python3 refresh_credentials.py                 # paste the block, then Ctrl-D / Ctrl-Z+Enter
    python3 refresh_credentials.py creds.txt        # read the block from a file
    pbpaste | python3 refresh_credentials.py        # macOS: pipe straight from the clipboard
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import LabCliError, check_credentials, log  # noqa: E402

REQUIRED_KEYS = ("aws_access_key_id", "aws_secret_access_key", "aws_session_token")


def read_block() -> str:
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).read_text()
    log("Paste the credential block from AWS Academy's 'AWS Details' > 'AWS CLI' panel,")
    log("then press Ctrl-D (macOS/Linux) or Ctrl-Z then Enter (Windows):")
    return sys.stdin.read()


def validate(block: str) -> None:
    missing = [k for k in REQUIRED_KEYS if not re.search(rf"^\s*{k}\s*=", block, re.MULTILINE | re.IGNORECASE)]
    if missing:
        raise ValueError(
            "That doesn't look like a full AWS CLI credential block — missing: "
            + ", ".join(missing)
            + ". Copy the entire block from AWS Details > AWS CLI, including [default]."
        )
    if "[default]" not in block:
        # Academy always includes this header, but tolerate a bare key=value paste.
        block = "[default]\n" + block
    return block


def write_credentials(block: str) -> Path:
    aws_dir = Path.home() / ".aws"
    aws_dir.mkdir(parents=True, exist_ok=True)
    creds_path = aws_dir / "credentials"
    if creds_path.exists():
        backup = creds_path.with_suffix(".credentials.bak")
        backup.write_text(creds_path.read_text())
        log(f"backed up existing credentials to {backup}")
    creds_path.write_text(block.strip() + "\n")
    return creds_path


def main() -> None:
    raw = read_block()
    try:
        normalized = validate(raw)
    except ValueError as exc:
        log(f"ERROR: {exc}")
        sys.exit(1)

    path = write_credentials(normalized)
    log(f"wrote {path}")

    try:
        account_id = check_credentials()
    except LabCliError as exc:
        log(f"ERROR: credentials were written but still don't work: {exc}")
        sys.exit(1)

    log(f"credentials are valid for account {account_id}")


if __name__ == "__main__":
    main()
