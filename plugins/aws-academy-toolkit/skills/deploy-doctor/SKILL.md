---
name: deploy-doctor
description: Check whether a student group's own project (web app, API, whatever they built) will actually run locally and on this course's AWS Academy EKS, and fix what's broken. Use when a team asks "will this deploy", "why won't our pod start", "does this work on EKS", or wants their Kubernetes manifests/Helm chart reviewed before or after deploying to MyEKS. Different from aws-lab-ops (that's the shared cluster infrastructure) and lab-tutor (that's the guided L1-L4 exercises) — this is for each team's own deliverable.
---

# Deploy doctor

Group projects get deployed to the same restricted `MyEKS` cluster the L1-L4
labs use. Generic Kubernetes/EKS advice from tutorials, blog posts, or an
LLM's own training data routinely assumes things this course's account
cannot do (custom IAM roles, IRSA, dynamic EBS provisioning — see
[`${CLAUDE_PLUGIN_ROOT}/references/academy-eks-limits.md`](../../references/academy-eks-limits.md)).
A team that doesn't know this can burn hours debugging a `CrashLoopBackOff`
or a Pending PVC that isn't actually their bug.

This skill has three jobs, roughly in order: verify it runs locally, scan
for known Academy-incompatible patterns, then verify it actually deploys on
`MyEKS` — and fix what's fixable rather than just reporting it, since a
team pressed for time needs a working deployment, not just a diagnosis.

## Step 1 — does it even run locally first?

Before touching Kubernetes at all, confirm the team's app runs via its own
`docker compose` (or equivalent) setup. If it doesn't run in plain Docker,
no amount of Kubernetes debugging will fix it — say so plainly and help
with that first.

## Step 2 — static scan for Academy-incompatible patterns

Run (always via the plugin's own path, not a relative one, since this skill
runs from the plugin's installed location, not the team's project directory):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aws-lab/academy_k8s_lint.py" <path-to-their-manifests-or-repo>
```

This flags things like IRSA annotations, ALB Ingress Controller usage, EBS/EFS
CSI StorageClasses, external-dns/cert-manager DNS-01 solvers, and
Terraform/eksctl configs that try to create their own IAM roles — all of
which fail silently or with confusing errors on this account. The script
only detects and explains; it does not attempt to auto-rewrite anything
semantic (e.g. converting an ALB Ingress into a Gateway API HTTPRoute),
because that requires understanding the specific app's routing needs. Do
that rewrite yourself, using this course's own L2-L4 EKS manifests as the
working reference pattern for this account (ask the student for their lab
repo/folder if you need to see the exact `gateway.yaml`/`httproute.yaml`
this course uses), and apply it directly rather than just describing it —
the team needs a deployment that works, not homework.

Common substitutions to reach for:

| Team has | Replace with |
|---|---|
| ALB Ingress / `alb.ingress.kubernetes.io/*` | Envoy Gateway `GatewayClass`/`Gateway`/`HTTPRoute`, same as this course's L2 lab |
| A `StorageClass` expecting dynamic EBS | A static `hostPath` PV + node label (this course's L3 lab pattern), or an external datastore |
| A ServiceAccount with an IRSA role-arn annotation | Drop it; check whether LabRole's node permissions already cover the need |
| A custom Terraform/eksctl IAM role | Point the same field at the existing `LabRole` ARN |

## Step 3 — verify against the real cluster

Once local + static checks pass:

1. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aws-lab/verify_eks.py"` — confirm
   the shared cluster itself is healthy before blaming the team's manifests
   for something that's actually a cluster-wide problem.
2. Build and push their images to ECR the same way this course's L1 lab
   does (one ECR repo per image, `imagePullPolicy: Always`), unless they
   already have their own ECR repos.
3. `kubectl apply` their manifests, then actually watch it come up
   (`kubectl get pods -w`, `kubectl describe pod`, `kubectl logs`) — don't
   just apply and assume success.
4. If they exposed a Service via the Gateway/LoadBalancer pattern, confirm
   the `MyEKSGroup` security group ID is correctly substituted (not left as
   `<my-eks-group-id>` or the bare name) and that the load balancer actually
   gets an external address.

## When something fails, diagnose before rewriting

Cross-check the failure mode against the reference doc: a Pending PVC, an
unbound node-affinity error, or a load balancer stuck with no external
address are very often the known Academy constraints, not bugs unique to
this team's code. Explain which one it is, then apply the fix.

## Boundary with lab-tutor

Group-project debugging is not the guided L1-L4 exercises — the learning
objective here is "ship a working deployment," not "discover the mechanism
yourself," so it's fine to be direct and fix things rather than running the
hint ladder. Still explain *why* something failed when you fix it (in terms
of the actual AWS/Kubernetes mechanism), since that's the whole point of
doing this course and the team will hit the same class of issue again on
their own.

## Cross-platform note

If `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aws-lab/academy_k8s_lint.py" ...`
fails with "command not found", retry with `python` instead — some Windows
installs only expose one of the two.
