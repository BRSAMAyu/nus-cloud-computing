# nus-cloud-computing — Claude Code plugin

A Claude Code plugin for the NUS cloud computing course: AWS Academy
Learner Lab session/credential automation, EKS rebuild-from-scratch, a
Socratic tutor for the L1-L4 Kubernetes labs, and a deployment checker for
group projects targeting this course's restricted AWS Academy EKS.

Kept as its own repo, separate from the lab content repo, because this
tooling needs to be available in *every* project directory a student opens
— this term's labs, next term's labs, a group project folder — not just one
specific lab checkout.

## Install (students, one-time per machine)

Inside Claude Code:

```
/plugin marketplace add <org>/nus-cloud-computing
/plugin install aws-academy-toolkit@nus-cloud-computing
```

Replace `<org>` with wherever this repo ends up hosted (e.g.
`your-github-username/nus-cloud-computing`). After installing, the three
skills below are available in any directory you run `claude` in.

### Recommended: connect Claude in Chrome

The `aws-lab-ops` skill can start/resume your AWS Academy lab session and
pull fresh credentials directly out of the browser — no copy-pasting — if
you have the **Claude in Chrome** extension installed and connected, and are
already logged into Canvas/AWS Academy in that Chrome profile. Without it,
the skill falls back to asking you to paste the credential block yourself;
everything else works the same either way.

### First-run: your course URL

The first time you use `aws-lab-ops`, it'll ask for your course's "Launch
AWS Academy Learner Lab" URL (the Canvas modules/items link). It's saved
locally at `~/.config/nus-cloud-lab/config.json` — never committed anywhere,
never shared between students.

## What's in the plugin

### `aws-academy-toolkit` (the plugin)

- **`aws-lab-ops`** — starts/resumes the AWS Academy Learner Lab session and
  refreshes credentials (browser-assisted via Claude in Chrome, with a
  manual-paste fallback), and rebuilds/verifies/tears down the shared
  `MyEKS` cluster + `MyEKSGroup` security group + ECR repos via AWS CLI.
  Turns what used to be a ~2-hour manual EKS setup into a script — useful
  every time an AWS Academy account gets reissued (budget exhausted, new
  term).

  Hard boundary, by design: this skill never logs into Canvas/AWS Academy,
  never touches a password or MFA, never registers an account. It only
  automates what's possible once a student is already authenticated
  themselves — clicking Start Lab, and reading the temporary credentials
  AWS Academy already displays to them.

- **`lab-tutor`** — Socratic help with the L1-L4 guestbook labs
  (reconciliation loops, Service/DNS, ConfigMaps/Secrets, Gateway API,
  storage, probes/PDBs). Teaches through graduated hints instead of handing
  over working YAML, so students build real understanding rather than
  copy-pasting to a green checkmark. Reads whichever lab's
  `instructions.md`/`instructions-eks.md` is in the student's current
  project directory, since lab content is distributed separately per
  lecture and isn't bundled in this plugin.

- **`deploy-doctor`** — for the group-project phase: checks whether a
  team's own app/manifests will run locally and on this course's `MyEKS`,
  flags patterns that work on generic EKS tutorials but are blocked here
  (IRSA, ALB Ingress Controller, dynamic EBS provisioning), and fixes what
  it can rather than just reporting problems.

### `references/academy-eks-limits.md`

The shared knowledge base all three skills reason from: exactly what AWS
Academy's Learner Lab blocks (custom IAM roles, IRSA/OIDC, dynamic EBS/EFS
storage), why the course's EKS labs work around each restriction the way
they do, and a lookup table `deploy-doctor` uses to flag incompatible
patterns in a team's own project.

### `scripts/aws-lab/`

Plain Python 3 (stdlib only — no pip installs), shells out to
`aws`/`kubectl`/`helm` on PATH. Runs identically on Windows and macOS.

| Script | Purpose |
|---|---|
| `common.py` | shared AWS CLI wrapper + retry/backoff helpers |
| `lab_config.py` | stores the student's course URL locally |
| `refresh_credentials.py` | validates and writes a pasted/extracted credential block, verifies it |
| `bootstrap_eks.py` | idempotently (re)creates `MyEKS` + `MyEKSGroup` + ECR repos from a bare account |
| `verify_eks.py` | cross-platform health check (credentials, cluster, security group, kubectl, helm) |
| `teardown_eks.py` | deletes the node group, cluster, and any orphaned Kubernetes-created load balancers |
| `academy_k8s_lint.py` | scans a project's YAML/Terraform for Academy-incompatible patterns |

## Maintaining this repo

- Bump `version` in both `plugins/aws-academy-toolkit/.claude-plugin/plugin.json`
  and the matching entry in `.claude-plugin/marketplace.json` on every
  release students should actually receive — `/plugin update` and
  auto-update skip a plugin whose resolved version hasn't changed.
- `claude plugin validate .` from the repo root checks `marketplace.json`
  and every plugin's `plugin.json`/skill frontmatter before you push.
