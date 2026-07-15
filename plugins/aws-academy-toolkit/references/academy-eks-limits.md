# AWS Academy Learner Lab — EKS/IAM constraints reference

This is the ground truth all three skills (`aws-lab-ops`, `lab-tutor`,
`deploy-doctor`) reason from. It exists because Academy's restrictions are not
generic AWS behavior — a normal AWS account or a tutorial found online will
routinely suggest things that are blocked here. When advising a student or
scripting automation, check claims against this file before asserting them.

## Account/session mechanics

- One Learner Lab account persists for the whole course. **Start Lab** resumes
  it; **End Lab** suspends EC2 instances only — NAT gateways, load balancers,
  and RDS keep running and billing. **Reset** wipes all resources (and cannot
  be undone) but is a different action from running out of budget.
- Session length is ~4 hours before EC2 instances are auto-suspended; restart
  the lab to resume them. Nodes may come back with different instance IDs and
  lost node labels (matters for L3/L4 storage — see below).
- Budget is small (course sets it; treat it as scarce) and does not reset on
  session restart. Spend tracking can lag up to 8 hours. When it's spent, the
  account is deactivated with no recovery — a genuinely new account is issued.
  A freshly issued account has **never created a load balancer or EKS
  resource before**, which matters for the service-linked-role race below.
- Region is locked to `us-east-1` (this course uses `us-east-1`); do not let a
  script default to any other region.
- Quotas observed in practice: ~32 vCPU ceiling and a small (~9) concurrent
  instance-count ceiling in the region — the instance-count cap bites before
  vCPU does. Keep the node group small (2 nodes, small instance type).

## IAM — the central constraint

- You cannot create IAM users, groups, or roles, and you cannot attach a
  managed or custom policy to any role, including the pre-created `LabRole`
  (`iam:AttachRolePolicy` is denied). Every AWS resource that needs an IAM
  identity must reuse `LabRole` as-is.
- The one exception: `iam:CreateServiceLinkedRole` is allowed, but Academy's
  own docs say to expect the **first** call to fail and require a retry —
  build retry-with-backoff around anything that triggers an SLR creation
  (EKS cluster creation, EKS nodegroup creation, and critically **the first
  `Service: type=LoadBalancer` ever created on a fresh account**, which needs
  `AWSServiceRoleForElasticLoadBalancing`). Pre-creating that SLR once at the
  start of a bootstrap script avoids the race instead of hoping the first
  Service creation retries correctly.
- Because of this, **IRSA (IAM Roles for Service Accounts) does not work**.
  Any component that wants its own IAM role via an OIDC-federated service
  account — AWS Load Balancer Controller, cluster-autoscaler, EBS/EFS CSI
  driver, external-dns, cert-manager's Route53 solver — will fail to
  provision or will run with no real permissions. Do not associate an OIDC
  provider with the cluster; `eksctl utils associate-iam-oidc-provider` and
  `eksctl create iamserviceaccount` both need `iam:CreateRole`/
  `iam:CreateOpenIDConnectProvider` and are blocked.
- `eksctl` itself is usable only in restricted form: pass explicit
  `iam.serviceRoleARN` / node group `iam.instanceRoleARN` set to `LabRole`,
  and only use `managedNodeGroups` (self-managed `nodeGroups` go through a
  CloudFormation template that creates its own instance profile — blocked).
  Plain `aws eks create-cluster` / `create-nodegroup` CLI calls are simpler
  and are what this repo's scripts use.

## How the guestbook labs get a working LoadBalancer without IRSA

This is the load-bearing trick that makes L2–L4's EKS variants work at all:

- A plain Kubernetes `Service` of `type: LoadBalancer` on EKS is still
  reconciled by the **legacy in-tree AWS cloud provider** running inside the
  AWS-managed control plane (not a pod you install). AWS's own EKS Best
  Practices Guide confirms this path is legacy-but-supported and creates a
  Classic Load Balancer by default. It authenticates using the **cluster's**
  IAM role (the one passed as `--role-arn` to `create-cluster`), not the node
  role — so `LabRole` must be the cluster role, and its existing EC2/ELB
  permissions (broad, since EC2 and ELB are both in Academy's allowed-service
  list) are what let this work, plus the SLR exception above.
- This is why the course's Gateway API implementation (Envoy Gateway) needs no
  AWS Load Balancer Controller install: Envoy Gateway just creates a plain
  `type: LoadBalancer` Service, and the in-tree controller does the rest.
- Because there's no AWS Load Balancer Controller, the BYO-security-group
  annotation (`service.beta.kubernetes.io/aws-load-balancer-security-groups`)
  is **not guaranteed to auto-manage the worker node security group's
  ingress rule** the way the modern controller does. Don't assume it's wired
  automatically — explicitly (and idempotently) authorize inbound TCP
  30000-32767 on the node/cluster security group from `MyEKSGroup`'s ID as a
  bootstrap step.
- Subnets must be tagged for the in-tree controller to pick them for a
  public-facing LB, and default/manually-created VPCs are not tagged this way
  by default:
  - `kubernetes.io/role/elb=1` on public subnets
  - `kubernetes.io/cluster/MyEKS=shared` on the subnets used by the cluster
  - Use ≥2 subnets in different AZs — LB creation validates AZ spread.

## Storage: no dynamic provisioning

- The EBS CSI driver needs its own IAM role (normally via IRSA) — blocked for
  the same reason as above. There is no working "gp2/gp3 StorageClass →
  dynamic EBS volume" path on this course's EKS.
- L3/L4 instead use a **static `hostPath` PersistentVolume** pinned to one
  worker node via a `storage-demo=postgres` node label. This is intentionally
  not production-grade: if AWS Academy replaces/restarts the worker node, the
  label and the on-disk data are both gone, and the label must be reapplied
  (`kubectl label node <name> storage-demo=postgres --overwrite`) before the
  StatefulSet will schedule again. `deploy-doctor` and `lab-tutor` should
  treat "PVC won't bind" or "Pod Pending with node-affinity error" on EKS as
  this known issue first, not a new bug.
- Any student project that wants real persistence on this course's EKS should
  not assume a StorageClass will dynamically provision anything. Either reuse
  the static-PV pattern, or point at an external managed datastore outside
  the cluster (e.g. a database the team runs elsewhere) rather than relying
  on EBS/EFS CSI.

## Known-good resource names (this course)

- EKS cluster: `MyEKS`, region `us-east-1`.
- Security group: `MyEKSGroup` — inbound TCP 80 from `0.0.0.0/0`; its ID
  (`sg-...`, not the name) is what gets used in the
  `aws-load-balancer-security-groups` annotation.
- ECR repositories: `guestbook-frontend`, `guestbook-backend` (one-time
  create per account, safe to skip if already present).
- IAM role for everything: `LabRole` (both `--role-arn` at cluster creation
  and `--node-role` at nodegroup creation).

## What this means for `deploy-doctor` (student group projects)

When a student team's own Kubernetes manifests/Helm charts are checked
against this course's EKS, flag and suggest a fix for any of:

| Pattern found | Why it fails here | Suggested fix |
|---|---|---|
| `eks.amazonaws.com/role-arn` annotation on a ServiceAccount (IRSA) | No OIDC provider, no custom role creation | Drop IRSA; if the workload needs AWS API access, see if `LabRole`'s existing node permissions already cover it — if not, the feature isn't available here |
| AWS Load Balancer Controller / `alb.ingress.kubernetes.io/*` annotations, `Ingress` with `ingressClassName: alb` | LBC needs an IRSA service account | Use a plain `Service: type=LoadBalancer` (or this course's Gateway API + Envoy Gateway pattern) instead of an ALB Ingress |
| `StorageClass` referencing `ebs.csi.aws.com` / `efs.csi.aws.com`, or a PVC expecting dynamic provisioning | EBS/EFS CSI driver needs IRSA | Use a static `hostPath` PV + node label (as L3/L4 do), or an external datastore |
| `external-dns`, `cert-manager` Route53/ACM solvers | Both typically need an IRSA role for Route53/ACM API calls | Skip automatic DNS/TLS automation; use the LB's own DNS name over plain HTTP for course purposes |
| A Terraform/CDK/eksctl config that creates its own IAM role or attaches a policy | Blocked outright | Point every `role_arn`/`serviceRoleARN`/`instanceRoleARN` at the existing `LabRole` ARN |
| Anything assuming multiple AZ-redundant NAT gateways, cross-region resources, or >2 nodes of a large instance type | Budget/quota | Right-size to the existing quotas above before troubleshooting further |

## Sources

- AWS Academy Learner Lab – Foundation Services (official course PDF)
- AWS EKS Best Practices Guide — Load Balancing (docs.aws.amazon.com)
- AWS EKS node IAM role / service-linked role docs (docs.aws.amazon.com)
- `terraform-aws-eks` issue #87 (ELB service-linked-role first-use race)
- This repo's own `cluster-setup/verify-eks.ps1` and `L1`–`L4` `instructions-eks.md`,
  which document the cluster/SG names and the storage/gateway workarounds this
  file generalizes from.
