#!/usr/bin/env python3
"""Recreate this course's EKS environment (MyEKS + MyEKSGroup + ECR repos)
from nothing but AWS CLI access to a fresh/reissued AWS Academy account.

Every step is idempotent: re-running this script after a partial failure, or
against an account that already has some pieces, only creates what's
missing. Read references/academy-eks-limits.md first if you're touching this
script — every non-obvious step here (LabRole reuse, the service-linked-role
retry, the subnet tags) exists because of a specific Academy restriction
documented there.

Security group config and the node-ENI-attachment step are transcribed
directly from this course's own AWS-Setup-TUT1.pdf: MyEKSGroup allows All
TCP 0-65535 from anywhere (not just port 80), and is attached directly to
each worker node's primary network interface, not wired through the
cluster's own security group. That attachment step also runs every time
this script executes (not just once), because the PDF documents that AWS
Academy can swap out node instances between sessions.

Usage:
    python3 bootstrap_eks.py            # create/repair everything
    python3 bootstrap_eks.py --dry-run  # print the plan without changing anything
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attach_myeksgroup_to_nodes import attach_to_all_nodes  # noqa: E402
from common import (  # noqa: E402
    CLUSTER_NAME,
    ECR_REPOS,
    NODE_COUNT,
    NODE_INSTANCE_TYPE,
    NODEGROUP_NAME,
    REGION,
    SECURITY_GROUP_NAME,
    LabCliError,
    check_credentials,
    fail,
    get_account_id,
    log,
    run_aws,
    run_aws_json,
    with_retry,
)

DRY_RUN = "--dry-run" in sys.argv


def step(title: str):
    log(f"=== {title} ===")


def ensure_elb_service_linked_role():
    step("Ensuring the ELB service-linked role exists (avoids the first-LoadBalancer race)")
    roles = run_aws_json(["iam", "list-roles", "--query",
                           "Roles[?RoleName=='AWSServiceRoleForElasticLoadBalancing'].RoleName"])
    if roles:
        log("already exists")
        return
    if DRY_RUN:
        log("[dry-run] would run: aws iam create-service-linked-role --aws-service-name elasticloadbalancing.amazonaws.com")
        return

    def create():
        run_aws(["iam", "create-service-linked-role", "--aws-service-name", "elasticloadbalancing.amazonaws.com"])

    try:
        with_retry(create, what="create ELB service-linked role")
    except LabCliError as exc:
        if "has been taken" in str(exc):
            log("role appeared between check and create — fine")
        else:
            raise


def find_default_vpc_and_subnets():
    step("Locating default VPC and subnets (>=2 AZs)")
    vpcs = run_aws_json(["ec2", "describe-vpcs", "--filters", "Name=isDefault,Values=true"])
    if not vpcs or not vpcs["Vpcs"]:
        fail("No default VPC found. This script assumes the Academy account's default VPC; "
             "if your course provisions a custom VPC instead, set subnet IDs manually.")
    vpc_id = vpcs["Vpcs"][0]["VpcId"]

    subnets = run_aws_json(["ec2", "describe-subnets", "--filters", f"Name=vpc-id,Values={vpc_id}"])["Subnets"]
    by_az = {}
    for s in subnets:
        by_az.setdefault(s["AvailabilityZone"], s["SubnetId"])
    subnet_ids = list(by_az.values())[:3]  # 2-3 AZs is plenty for a lab cluster
    if len(subnet_ids) < 2:
        fail(f"Only found {len(subnet_ids)} usable subnet(s) across distinct AZs; EKS/ELB need at least 2.")
    log(f"vpc={vpc_id} subnets={subnet_ids}")
    return vpc_id, subnet_ids


def tag_subnets_for_elb(subnet_ids: list[str]):
    step("Tagging subnets so the in-tree LoadBalancer controller can find them")
    if DRY_RUN:
        log(f"[dry-run] would tag {subnet_ids} with kubernetes.io/role/elb=1, kubernetes.io/cluster/{CLUSTER_NAME}=shared")
        return
    run_aws([
        "ec2", "create-tags", "--resources", *subnet_ids,
        "--tags", "Key=kubernetes.io/role/elb,Value=1", f"Key=kubernetes.io/cluster/{CLUSTER_NAME},Value=shared",
    ])
    log("tagged")


def ensure_security_group(vpc_id: str) -> str:
    step(f"Ensuring security group {SECURITY_GROUP_NAME} (All TCP 0-65535 from anywhere, per AWS-Setup-TUT1.pdf)")
    existing = run_aws_json([
        "ec2", "describe-security-groups",
        "--filters", f"Name=group-name,Values={SECURITY_GROUP_NAME}", f"Name=vpc-id,Values={vpc_id}",
    ])["SecurityGroups"]
    if existing:
        sg_id = existing[0]["GroupId"]
        log(f"already exists: {sg_id}")
    else:
        if DRY_RUN:
            log(f"[dry-run] would create security group {SECURITY_GROUP_NAME} in {vpc_id}")
            return "sg-dryrun"
        created = run_aws_json([
            "ec2", "create-security-group", "--group-name", SECURITY_GROUP_NAME,
            "--description", "Allow all HTTP requests",
            "--vpc-id", vpc_id,
        ])
        sg_id = created["GroupId"]
        log(f"created: {sg_id}")

    if not DRY_RUN:
        try:
            run_aws([
                "ec2", "authorize-security-group-ingress", "--group-id", sg_id,
                "--protocol", "tcp", "--port", "0-65535", "--cidr", "0.0.0.0/0",
            ])
            log("authorized inbound All TCP (0-65535) from 0.0.0.0/0")
        except LabCliError as exc:
            if "InvalidPermission.Duplicate" in str(exc):
                log("inbound rule already present")
            else:
                raise
    return sg_id


def cluster_status() -> str | None:
    result = run_aws(["eks", "describe-cluster", "--name", CLUSTER_NAME], check=False)
    if result.returncode != 0:
        return None
    import json
    return json.loads(result.stdout)["cluster"]["status"]


def ensure_cluster(subnet_ids: list[str], account_id: str):
    step(f"Ensuring EKS cluster {CLUSTER_NAME}")
    status = cluster_status()
    if status == "ACTIVE":
        log("already ACTIVE")
        return
    if status is not None:
        log(f"cluster exists with status {status}; waiting for ACTIVE")
    else:
        if DRY_RUN:
            log(f"[dry-run] would create cluster {CLUSTER_NAME} with role LabRole in subnets {subnet_ids}")
            return
        role_arn = f"arn:aws:iam::{account_id}:role/LabRole"

        def create():
            run_aws([
                "eks", "create-cluster", "--name", CLUSTER_NAME,
                "--role-arn", role_arn,
                "--resources-vpc-config", f"subnetIds={','.join(subnet_ids)}",
                "--access-config", "authenticationMode=API_AND_CONFIG_MAP",
            ])

        with_retry(create, what="create EKS cluster (control plane)")

    if DRY_RUN:
        return
    log("waiting for cluster to become ACTIVE (typically 10-20 minutes)...")
    run_aws(["eks", "wait", "cluster-active", "--name", CLUSTER_NAME])
    log("cluster is ACTIVE")


def ensure_nodegroup(subnet_ids: list[str], account_id: str):
    step(f"Ensuring node group {NODEGROUP_NAME}")
    result = run_aws(["eks", "describe-nodegroup", "--cluster-name", CLUSTER_NAME,
                       "--nodegroup-name", NODEGROUP_NAME], check=False)
    if result.returncode == 0:
        import json
        status = json.loads(result.stdout)["nodegroup"]["status"]
        if status == "ACTIVE":
            log("already ACTIVE")
            return
        log(f"node group exists with status {status}; waiting for ACTIVE")
    else:
        if DRY_RUN:
            log(f"[dry-run] would create node group {NODEGROUP_NAME} ({NODE_COUNT}x {NODE_INSTANCE_TYPE}, role LabRole)")
            return
        role_arn = f"arn:aws:iam::{account_id}:role/LabRole"

        def create():
            run_aws([
                "eks", "create-nodegroup", "--cluster-name", CLUSTER_NAME,
                "--nodegroup-name", NODEGROUP_NAME,
                "--node-role", role_arn,
                "--subnets", *subnet_ids,
                "--instance-types", NODE_INSTANCE_TYPE,
                "--scaling-config", f"minSize={NODE_COUNT},maxSize={NODE_COUNT},desiredSize={NODE_COUNT}",
                "--disk-size", "20",
                "--capacity-type", "ON_DEMAND",
            ])

        with_retry(create, what="create EKS node group")

    if DRY_RUN:
        return
    log("waiting for node group to become ACTIVE (typically a few minutes)...")
    run_aws(["eks", "wait", "nodegroup-active", "--cluster-name", CLUSTER_NAME, "--nodegroup-name", NODEGROUP_NAME])
    log("node group is ACTIVE")


def attach_security_group_to_nodes():
    step("Attaching MyEKSGroup to each worker node's primary network interface")
    if DRY_RUN:
        log("[dry-run] would attach MyEKSGroup to every running MyEKS node's primary ENI")
        return
    try:
        already, newly = attach_to_all_nodes()
        log(f"{already} node(s) already had it, {newly} node(s) newly attached")
    except LabCliError as exc:
        log(f"WARNING: could not attach MyEKSGroup to nodes automatically: {exc}")
        log("Run attach_myeksgroup_to_nodes.py again once the node group is ACTIVE.")


def ensure_ecr_repos():
    step("Ensuring ECR repositories")
    for repo in ECR_REPOS:
        result = run_aws(["ecr", "describe-repositories", "--repository-names", repo], check=False)
        if result.returncode == 0:
            log(f"{repo}: already exists")
            continue
        if DRY_RUN:
            log(f"[dry-run] would create ECR repo {repo}")
            continue
        run_aws(["ecr", "create-repository", "--repository-name", repo])
        log(f"{repo}: created")


def update_kubeconfig():
    step("Updating local kubeconfig")
    if DRY_RUN:
        log("[dry-run] would run: aws eks update-kubeconfig")
        return
    run_aws(["eks", "update-kubeconfig", "--name", CLUSTER_NAME])
    log("kubeconfig updated")


def label_storage_node():
    step("Labeling one worker node storage-demo=postgres (needed by L3/L4)")
    if DRY_RUN:
        log("[dry-run] would label the first node storage-demo=postgres")
        return
    import subprocess
    result = subprocess.run(
        ["kubectl", "get", "nodes", "-o", "jsonpath={.items[0].metadata.name}"],
        capture_output=True, text=True,
    )
    node = result.stdout.strip()
    if not node:
        log("no nodes visible yet via kubectl — skip and rerun this script once nodes are Ready")
        return
    subprocess.run(["kubectl", "label", "node", node, "storage-demo=postgres", "--overwrite"], check=False)
    log(f"labeled {node}")


def main():
    log(f"region={REGION} cluster={CLUSTER_NAME} security-group={SECURITY_GROUP_NAME}"
        + (" [DRY RUN]" if DRY_RUN else ""))

    try:
        check_credentials()
    except LabCliError as exc:
        fail(str(exc))
    account_id = get_account_id()
    log(f"account={account_id}")

    ensure_elb_service_linked_role()
    vpc_id, subnet_ids = find_default_vpc_and_subnets()
    tag_subnets_for_elb(subnet_ids)
    my_eks_group_id = ensure_security_group(vpc_id)
    ensure_cluster(subnet_ids, account_id)
    ensure_nodegroup(subnet_ids, account_id)
    attach_security_group_to_nodes()
    ensure_ecr_repos()
    update_kubeconfig()
    label_storage_node()

    step("Done")
    log(f"MyEKSGroup id: {my_eks_group_id}")
    log("Next: run verify_eks.py to confirm kubectl/helm can reach the cluster.")


if __name__ == "__main__":
    main()
