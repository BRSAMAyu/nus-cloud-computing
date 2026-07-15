"""Shared helpers for the AWS Academy Learner Lab automation scripts.

Every script in this directory shells out to the `aws` CLI (v2) instead of
boto3, on purpose: AWS CLI is already a prerequisite for the labs (see
ENVIRONMENT.md), and this keeps the scripts dependency-free (stdlib only) so
they run the same way on a fresh Windows or macOS machine with just
`python3` + `aws` on PATH.

Constants below match the names baked into this course's lab manuals
(L1-L4 instructions-eks.md, cluster-setup/verify-eks.ps1). See
references/academy-eks-limits.md for why each step exists.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time

REGION = "us-east-1"
CLUSTER_NAME = "MyEKS"
SECURITY_GROUP_NAME = "MyEKSGroup"
NODEGROUP_NAME = "MyEKSNodes"
ECR_REPOS = ["guestbook-frontend", "guestbook-backend"]
NODE_INSTANCE_TYPE = "t3.medium"
NODE_COUNT = 2
NODEPORT_RANGE = (30000, 32767)


class LabCliError(RuntimeError):
    """Raised when an `aws` CLI call fails in a way the caller should stop on."""


def log(message: str) -> None:
    print(f"[aws-lab] {message}", flush=True)


def run_aws(args: list[str], *, check: bool = True, quiet_stderr: bool = False) -> subprocess.CompletedProcess:
    """Run an `aws` CLI command and return the CompletedProcess.

    Always adds --region. Raises LabCliError with the captured stderr when
    check=True and the command fails, so callers get an actionable message
    instead of a bare non-zero exit code.
    """
    cmd = ["aws", *args, "--region", REGION]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        stderr = result.stderr.strip()
        raise LabCliError(f"`{' '.join(cmd)}` failed:\n{stderr}")
    return result


def run_aws_json(args: list[str]):
    result = run_aws([*args, "--output", "json"])
    return json.loads(result.stdout) if result.stdout.strip() else None


def with_retry(fn, *, attempts: int = 5, initial_delay: float = 5.0, what: str = "operation"):
    """Retry fn() with exponential backoff.

    Academy's own docs say the first iam:CreateServiceLinkedRole-triggering
    call commonly fails and needs a retry (see references/academy-eks-limits.md).
    This wraps that expectation instead of treating it as a hard failure.
    """
    delay = initial_delay
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except LabCliError as exc:
            last_error = exc
            log(f"{what} failed on attempt {attempt}/{attempts}: {exc}")
            if attempt == attempts:
                break
            log(f"retrying in {delay:.0f}s (service-linked-role races are expected on a fresh account)...")
            time.sleep(delay)
            delay *= 2
    raise LabCliError(f"{what} did not succeed after {attempts} attempts") from last_error


def get_account_id() -> str:
    ident = run_aws_json(["sts", "get-caller-identity"])
    return ident["Account"]


def check_credentials() -> str:
    """Return the account ID, or raise a clear error pointing at the fix."""
    try:
        return get_account_id()
    except LabCliError as exc:
        raise LabCliError(
            "AWS credentials are missing or expired.\n"
            "Start the AWS Academy Learner Lab, open 'AWS Details' > 'AWS CLI', "
            "and paste the credential block to the aws-lab-ops skill so it can "
            "write ~/.aws/credentials — this script cannot log in for you.\n"
            f"(underlying error: {exc})"
        ) from exc


def fail(message: str) -> None:
    log(f"ERROR: {message}")
    sys.exit(1)
