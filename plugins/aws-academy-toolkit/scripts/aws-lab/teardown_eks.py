#!/usr/bin/env python3
"""Tear down MyEKS (node group, cluster, and any load balancers Kubernetes
created) so nothing keeps billing after a lab session.

`aws eks delete-cluster` does NOT clean up Classic/Network Load Balancers
that Kubernetes Services created — those keep running and billing even
after the cluster is gone. This script finds and removes them first.

This is destructive. It requires --yes; without it, it only prints what it
would delete.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CLUSTER_NAME, NODEGROUP_NAME, LabCliError, check_credentials, fail, log, run_aws, run_aws_json  # noqa: E402

CONFIRMED = "--yes" in sys.argv


def find_cluster_load_balancers() -> list[str]:
    clbs = run_aws_json(["elb", "describe-load-balancers"]) or {"LoadBalancerDescriptions": []}
    matches = []
    for lb in clbs.get("LoadBalancerDescriptions", []):
        name = lb["LoadBalancerName"]
        tags = run_aws_json(["elb", "describe-tags", "--load-balancer-names", name])
        tag_dict = {t["Key"]: t["Value"] for t in tags["TagDescriptions"][0]["Tags"]} if tags else {}
        if any(k.startswith("kubernetes.io/cluster/") for k in tag_dict):
            matches.append(("classic", name))

    v2 = run_aws_json(["elbv2", "describe-load-balancers"]) or {"LoadBalancers": []}
    for lb in v2.get("LoadBalancers", []):
        arn = lb["LoadBalancerArn"]
        tags = run_aws_json(["elbv2", "describe-tags", "--resource-arns", arn])
        tag_dict = {t["Key"]: t["Value"] for t in tags["TagDescriptions"][0]["Tags"]} if tags else {}
        if any(k.startswith("kubernetes.io/cluster/") for k in tag_dict):
            matches.append(("v2", arn))
    return matches


def main():
    try:
        check_credentials()
    except LabCliError as exc:
        fail(str(exc))

    if not CONFIRMED:
        log("DRY RUN (pass --yes to actually delete). Plan:")

    log(f"1. Delete node group {NODEGROUP_NAME} (if present)")
    log(f"2. Delete cluster {CLUSTER_NAME} (if present)")
    load_balancers = find_cluster_load_balancers()
    if load_balancers:
        log(f"3. Delete {len(load_balancers)} Kubernetes-created load balancer(s): {load_balancers}")
    else:
        log("3. No Kubernetes-created load balancers found")

    if not CONFIRMED:
        log("Nothing was deleted. Re-run with --yes to proceed.")
        return

    for kind, ident in load_balancers:
        if kind == "classic":
            run_aws(["elb", "delete-load-balancer", "--load-balancer-name", ident])
        else:
            run_aws(["elbv2", "delete-load-balancer", "--load-balancer-arn", ident])
        log(f"deleted load balancer {ident}")

    result = run_aws(["eks", "describe-nodegroup", "--cluster-name", CLUSTER_NAME,
                       "--nodegroup-name", NODEGROUP_NAME], check=False)
    if result.returncode == 0:
        run_aws(["eks", "delete-nodegroup", "--cluster-name", CLUSTER_NAME, "--nodegroup-name", NODEGROUP_NAME])
        log("waiting for node group deletion...")
        run_aws(["eks", "wait", "nodegroup-deleted", "--cluster-name", CLUSTER_NAME, "--nodegroup-name", NODEGROUP_NAME])
        log("node group deleted")
    else:
        log("node group already absent")

    result = run_aws(["eks", "describe-cluster", "--name", CLUSTER_NAME], check=False)
    if result.returncode == 0:
        run_aws(["eks", "delete-cluster", "--name", CLUSTER_NAME])
        log("waiting for cluster deletion...")
        run_aws(["eks", "wait", "cluster-deleted", "--name", CLUSTER_NAME])
        log("cluster deleted")
    else:
        log("cluster already absent")

    log("Done. ECR repositories and their images were left alone (no meaningful cost); "
        "rerun bootstrap_eks.py whenever you need the cluster back.")


if __name__ == "__main__":
    main()
