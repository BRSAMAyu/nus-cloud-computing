#!/usr/bin/env python3
"""Scan a student project's Kubernetes/Helm/Terraform/eksctl files for
patterns that work on generic EKS but are blocked on this course's AWS
Academy Learner Lab account (no custom IAM roles, no IRSA/OIDC, no dynamic
EBS/EFS provisioning). See references/academy-eks-limits.md for the "why"
behind every rule here.

This is a plain-text/regex scanner on purpose — no PyYAML dependency, so it
runs on any machine with just python3, and it still catches Helm templates
that aren't valid standalone YAML.

Usage:
    python3 academy_k8s_lint.py [path]        # defaults to the current directory
    python3 academy_k8s_lint.py path --fix     # comment out flagged lines with a TODO note
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

SCAN_EXTENSIONS = {".yaml", ".yml", ".tf"}
SKIP_DIRS = {".git", "node_modules", ".terraform", "vendor", "__pycache__"}


@dataclass
class Rule:
    pattern: re.Pattern
    summary: str
    why: str
    fix: str


RULES = [
    Rule(
        re.compile(r"eks\.amazonaws\.com/role-arn"),
        "IRSA annotation on a ServiceAccount",
        "No OIDC provider and no custom IAM role creation on this account, so this annotation can never resolve to a usable role.",
        "Drop the annotation. If the workload needs AWS API access, check whether LabRole's existing node permissions already cover it (they often do for EC2/ELB/ECR); if not, this feature isn't available on this course's account.",
    ),
    Rule(
        re.compile(r"alb\.ingress\.kubernetes\.io/|ingressClassName:\s*alb|kubernetes\.io/ingress\.class:\s*[\"']?alb"),
        "AWS Load Balancer Controller / ALB Ingress annotation",
        "The AWS Load Balancer Controller needs an IRSA service account, which isn't available here.",
        "Use a plain `Service` of `type: LoadBalancer`, or this course's Gateway API + Envoy Gateway pattern (see L2-lab/L2-lab/instructions-eks.md) instead of an ALB Ingress.",
    ),
    Rule(
        re.compile(r"ebs\.csi\.aws\.com|efs\.csi\.aws\.com"),
        "EBS/EFS CSI driver reference (StorageClass provisioner or CSI volume)",
        "The CSI driver needs an IRSA role to call the AWS API; there is no working dynamic-provisioning path on this account.",
        "Use a static hostPath PersistentVolume pinned to a labeled node (see L3-lab/L3-lab/starter/manifests-eks/postgres-pv.yaml for the pattern this course already uses), or point at a datastore hosted outside the cluster.",
    ),
    Rule(
        re.compile(r"external-dns\.alpha\.kubernetes\.io/|external-dns"),
        "external-dns usage",
        "external-dns typically needs an IRSA role for Route53 API calls.",
        "Skip automatic DNS registration for course purposes; use the load balancer's own AWS-assigned DNS name directly.",
    ),
    Rule(
        re.compile(r"cert-manager\.io/cluster-issuer|dns01:"),
        "cert-manager DNS-01 solver (Route53/ACM)",
        "The Route53/ACM DNS-01 solver typically needs an IRSA role.",
        "Skip automated TLS for course purposes, or terminate TLS somewhere that doesn't need AWS API access (e.g. at the application layer).",
    ),
    Rule(
        re.compile(r'resource\s+"aws_iam_role"|resource\s+"aws_iam_policy"|resource\s+"aws_iam_role_policy_attachment"'),
        "Terraform IAM role/policy resource",
        "iam:CreateRole / iam:AttachRolePolicy are both denied on this account.",
        "Remove the resource and point every role_arn/serviceRoleARN/instanceRoleARN elsewhere in the config at the existing LabRole ARN instead.",
    ),
    Rule(
        re.compile(r"eksctl create iamserviceaccount|associate-iam-oidc-provider|withOIDC:\s*true|iam:\s*\n\s*withOIDC"),
        "eksctl OIDC/IRSA setup",
        "Associating an OIDC provider and creating IAM service accounts both need IAM permissions this account doesn't have.",
        "Remove the OIDC/iamserviceaccount step; set iam.serviceRoleARN and managedNodeGroups[].iam.instanceRoleARN to the LabRole ARN directly in the eksctl ClusterConfig.",
    ),
]


def iter_files(root: Path):
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in SCAN_EXTENSIONS:
            yield path


def scan(root: Path):
    findings = []
    for path in iter_files(root):
        try:
            lines = path.read_text(errors="ignore").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, start=1):
            for rule in RULES:
                if rule.pattern.search(line):
                    findings.append((path, lineno, line.strip(), rule))
    return findings


def apply_fix(findings):
    by_file = {}
    for path, lineno, _line, rule in findings:
        by_file.setdefault(path, []).append((lineno, rule))

    for path, hits in by_file.items():
        lines = path.read_text().splitlines(keepends=True)
        for lineno, rule in sorted(hits, key=lambda h: -h[0]):
            idx = lineno - 1
            original = lines[idx]
            indent = original[: len(original) - len(original.lstrip())]
            note = f"{indent}# TODO(academy-eks-limits): {rule.summary} — {rule.fix}\n"
            lines[idx] = note + indent + "# " + original.lstrip()
        path.write_text("".join(lines))


def main():
    args = [a for a in sys.argv[1:] if a != "--fix"]
    fix_mode = "--fix" in sys.argv
    root = Path(args[0]) if args else Path(".")
    if not root.exists():
        print(f"path not found: {root}")
        sys.exit(1)

    findings = scan(root)
    if not findings:
        print("No AWS-Academy-EKS-incompatible patterns found.")
        return

    print(f"Found {len(findings)} pattern(s) likely incompatible with this course's Academy EKS:\n")
    for path, lineno, line, rule in findings:
        print(f"{path}:{lineno}: {rule.summary}")
        print(f"  matched: {line}")
        print(f"  why: {rule.why}")
        print(f"  fix: {rule.fix}\n")

    if fix_mode:
        apply_fix(findings)
        print("Commented out each flagged line with a TODO note. Review and apply the suggested "
              "fix by hand — these are usually app-specific (e.g. rewriting an Ingress as a Gateway "
              "API HTTPRoute) and not safe to fully automate.")
    else:
        print("Run again with --fix to comment out each flagged line with a TODO note "
              "(does not rewrite manifests automatically — see suggested fixes above).")


if __name__ == "__main__":
    main()
