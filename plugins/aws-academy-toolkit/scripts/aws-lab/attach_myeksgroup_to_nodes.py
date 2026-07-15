#!/usr/bin/env python3
"""Attach MyEKSGroup to the primary network interface of every current
MyEKS worker node.

This is not a one-time setup step. Per this course's own AWS-Setup-TUT1.pdf
("Security group needs to be changed when starting a new session"), AWS
Academy can swap out the underlying EC2 instances between lab sessions
without touching the EKS cluster/node group objects themselves — so a node
that had MyEKSGroup attached last session may be a completely different
instance this session, without it. Re-run this after every credential
refresh, not just once after bootstrap_eks.py.

Idempotent: skips instances that already have the security group attached.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    CLUSTER_NAME,
    NODEGROUP_NAME,
    SECURITY_GROUP_NAME,
    LabCliError,
    check_credentials,
    fail,
    log,
    run_aws,
    run_aws_json,
)


def find_security_group_id() -> str:
    sgs = run_aws_json([
        "ec2", "describe-security-groups",
        "--filters", f"Name=group-name,Values={SECURITY_GROUP_NAME}",
    ])["SecurityGroups"]
    if not sgs:
        fail(f"Security group '{SECURITY_GROUP_NAME}' not found — run bootstrap_eks.py first.")
    return sgs[0]["GroupId"]


def find_node_instance_ids() -> list[str]:
    reservations = run_aws_json([
        "ec2", "describe-instances",
        "--filters",
        f"Name=tag:eks:cluster-name,Values={CLUSTER_NAME}",
        f"Name=tag:eks:nodegroup-name,Values={NODEGROUP_NAME}",
        "Name=instance-state-name,Values=running",
    ])["Reservations"]
    return [i["InstanceId"] for r in reservations for i in r["Instances"]]


def primary_eni_id(instance_id: str) -> str:
    instances = run_aws_json(["ec2", "describe-instances", "--instance-ids", instance_id])["Reservations"][0]["Instances"]
    for ni in instances[0]["NetworkInterfaces"]:
        if ni["Attachment"]["DeviceIndex"] == 0:
            return ni["NetworkInterfaceId"]
    fail(f"Could not find a primary (device-index 0) network interface for {instance_id}")


def ensure_attached(eni_id: str, sg_id: str) -> bool:
    """Returns True if the SG was already attached, False if just added."""
    eni = run_aws_json(["ec2", "describe-network-interfaces", "--network-interface-ids", eni_id])["NetworkInterfaces"][0]
    current_group_ids = [g["GroupId"] for g in eni["Groups"]]
    if sg_id in current_group_ids:
        return True
    new_group_ids = current_group_ids + [sg_id]
    run_aws(["ec2", "modify-network-interface-attribute", "--network-interface-id", eni_id, "--groups", *new_group_ids])
    return False


def attach_to_all_nodes() -> tuple[int, int]:
    """Returns (already_attached_count, newly_attached_count). Raises on hard failure."""
    sg_id = find_security_group_id()
    instance_ids = find_node_instance_ids()
    if not instance_ids:
        fail(f"No running instances found for node group '{NODEGROUP_NAME}' — is the cluster up? "
             "Run verify_eks.py first.")

    already, newly = 0, 0
    for instance_id in instance_ids:
        eni_id = primary_eni_id(instance_id)
        if ensure_attached(eni_id, sg_id):
            log(f"{instance_id} ({eni_id}): already has {SECURITY_GROUP_NAME}")
            already += 1
        else:
            log(f"{instance_id} ({eni_id}): attached {SECURITY_GROUP_NAME}")
            newly += 1
    return already, newly


def main():
    try:
        check_credentials()
    except LabCliError as exc:
        fail(str(exc))

    already, newly = attach_to_all_nodes()
    log(f"done: {already} node(s) already had it, {newly} node(s) newly attached")


if __name__ == "__main__":
    main()
