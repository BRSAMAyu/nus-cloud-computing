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
from attach_myeksgroup_to_nodes import find_node_instance_ids, primary_eni_id  # noqa: E402
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
    sg_id = sgs[0]["GroupId"]
    log(f"[PASS] security group {SECURITY_GROUP_NAME} exists ({sg_id})")

    # AWS Academy can swap out node instances between sessions (per this
    # course's own AWS-Setup-TUT1.pdf), so a security group that was
    # attached last session may be missing from this session's actual
    # nodes. This is a read-only check — it doesn't fix anything, just
    # tells the caller whether attach_myeksgroup_to_nodes.py needs a rerun.
    try:
        instance_ids = find_node_instance_ids()
        missing = []
        for instance_id in instance_ids:
            eni_id = primary_eni_id(instance_id)
            eni = run_aws_json(["ec2", "describe-network-interfaces", "--network-interface-ids", eni_id])["NetworkInterfaces"][0]
            if sg_id not in [g["GroupId"] for g in eni["Groups"]]:
                missing.append(instance_id)
        if missing:
            log(f"[WARN] {SECURITY_GROUP_NAME} is NOT attached to {len(missing)} node(s): {missing}")
            log("       Run attach_myeksgroup_to_nodes.py to fix this before relying on NodePort access.")
        else:
            log(f"[PASS] {SECURITY_GROUP_NAME} is attached to all {len(instance_ids)} current node(s)")
    except LabCliError as exc:
        log(f"[WARN] could not check node security group attachment: {exc}")

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
