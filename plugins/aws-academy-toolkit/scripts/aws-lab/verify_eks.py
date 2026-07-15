#!/usr/bin/env python3
"""Cross-platform equivalent of cluster-setup/verify-eks.ps1.

Confirms credentials, the cluster, the security group, kubectl, and helm are
all in a working state — the same checks the PowerShell script runs, so
macOS/Linux students (and CI) get the identical verification Windows
students already had.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CLUSTER_NAME, SECURITY_GROUP_NAME, LabCliError, check_credentials, fail, log, run_aws_json  # noqa: E402


def require_tool(name: str):
    if shutil.which(name) is None:
        fail(f"Required tool '{name}' is not on PATH.")


def main():
    require_tool("aws")
    require_tool("kubectl")
    require_tool("helm")

    try:
        check_credentials()
    except LabCliError as exc:
        fail(str(exc))
    log("[PASS] AWS credentials are valid")

    cluster = run_aws_json(["eks", "describe-cluster", "--name", CLUSTER_NAME])
    status = cluster["cluster"]["status"] if cluster else None
    if status != "ACTIVE":
        fail(f"EKS cluster '{CLUSTER_NAME}' is not ACTIVE (status={status}).")
    log(f"[PASS] EKS cluster {CLUSTER_NAME} is ACTIVE")

    sgs = run_aws_json(["ec2", "describe-security-groups",
                         "--filters", f"Name=group-name,Values={SECURITY_GROUP_NAME}"])["SecurityGroups"]
    if not sgs:
        fail(f"Security group '{SECURITY_GROUP_NAME}' was not found.")
    log(f"[PASS] security group {SECURITY_GROUP_NAME} exists ({sgs[0]['GroupId']})")

    subprocess.run(["aws", "eks", "update-kubeconfig", "--name", CLUSTER_NAME, "--region", "us-east-1"],
                    capture_output=True, check=True)

    nodes = subprocess.run(["kubectl", "get", "nodes"], capture_output=True, text=True)
    if nodes.returncode != 0:
        fail(f"kubectl cannot reach the EKS worker nodes:\n{nodes.stderr}")
    log("[PASS] kubectl can reach EKS worker nodes")
    print(nodes.stdout)

    helm = subprocess.run(["helm", "version", "--short"], capture_output=True, text=True)
    if helm.returncode != 0:
        fail("Helm is not usable.")
    log("[PASS] EKS experiment environment verification completed")


if __name__ == "__main__":
    main()
