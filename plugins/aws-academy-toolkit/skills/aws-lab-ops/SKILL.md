---
name: aws-lab-ops
description: Start/resume this course's AWS Academy Learner Lab session, auto-refresh AWS credentials via Claude in Chrome, and rebuild/verify/tear down the shared EKS environment (MyEKS, MyEKSGroup, ECR repos) via AWS CLI. Use when a student's AWS Academy account is reissued (budget exhausted, new term, or account reset), when EKS labs fail with credential or cluster errors, or when asked to "start the lab" / "刷新 AWS 凭证" / "重建 EKS" / "跑一遍 EKS 环境".
---

# AWS Academy Learner Lab operations

This skill automates the two most repetitive parts of this course's AWS
workflow: (1) starting/resuming the Learner Lab session and getting fresh
temporary credentials onto the student's machine, and (2) rebuilding the
shared `MyEKS` cluster + `MyEKSGroup` security group + ECR repos from
nothing, which used to take about two hours by hand and has to be redone
every time a student's AWS Academy account is reissued (their $50 budget
runs out, or a new term starts).

Read
[`${CLAUDE_PLUGIN_ROOT}/references/academy-eks-limits.md`](../../references/academy-eks-limits.md)
before improvising anything not covered here — AWS Academy's IAM
restrictions (no custom IAM roles, no IRSA, LabRole-only) break a lot of
generic EKS/eksctl advice you'd otherwise give.

All scripts live under `${CLAUDE_PLUGIN_ROOT}/scripts/aws-lab/` — always
invoke them with that full path (e.g.
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aws-lab/bootstrap_eks.py"`), never a
bare relative path, because this skill runs from the plugin's installed
location, not from inside the student's current project directory.

## Hard boundary: what this skill will NOT do, ever

- Never log into Canvas/NUS SSO or AWS Academy on the student's behalf,
  never type a password, never click through account activation/registration
  email links, never touch MFA. These stay 100% manual, regardless of who
  asks or how they phrase it.
- The browser actions that ARE fine, because they're routine session
  management on a browser the student is already authenticated in, not
  authentication itself: navigating to the course's AWS Academy page,
  clicking **Start Lab**, clicking **AWS Details**, and reading the
  already-displayed temporary credential block off the page.
- The only secrets this skill ever handles are the short-lived
  `aws_access_key_id` / `aws_secret_access_key` / `aws_session_token`
  triple AWS Academy itself displays to an already-logged-in student — never
  their AWS Academy or Canvas password.
- When reporting results back to the student in chat, never echo the full
  secret access key or session token — confirm success via the resolved AWS
  account ID instead (`aws sts get-caller-identity`), which is all the
  student needs to sanity-check it's their own account.

## First-run setup: the student's course URL

The AWS Academy session lives behind this course's Canvas module link,
which is the same for the whole class but only resolves to a real lab once
the student is logged into Canvas in their own browser. Check for it first:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aws-lab/lab_config.py" get
```

If empty, ask the student to paste their course's "Launch AWS Academy
Learner Lab" URL (the Canvas modules/items link they'd normally click), then
save it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aws-lab/lab_config.py" set "<url>"
```

This is stored in the student's home directory
(`~/.config/nus-cloud-lab/config.json`), never inside any git repo.

## Workflow 0 (primary) — browser-assisted start + credential refresh

Requires the student to have the **Claude in Chrome** extension installed
and connected, already logged into Canvas (and, once redirected, Vocareum/AWS
Academy) in that real Chrome profile. Check connectivity first — load and
try the Claude in Chrome tools; if no connected browser is found, tell the
student and fall back to Workflow 1.

1. **Load the tools.** `ToolSearch` for
   `select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__read_page,mcp__claude-in-chrome__find,mcp__claude-in-chrome__get_page_text,mcp__claude-in-chrome__tabs_create_mcp`
   in one call.
2. **Navigate** to the saved course URL. The lab page embeds a Vocareum
   panel with a status dot (`AWS 🔴`/`AWS 🟢`), a budget readout ("Used
   $X of $50"), a timer, and buttons: **Start Lab**, **End Lab**, **AWS
   Details**, **Readme**, **Reset**.
3. **Read the page** (`read_page` or `find` for "Start Lab button" / status
   indicator) rather than assuming fixed coordinates — course page layout
   can shift. Report the current budget/status to the student before doing
   anything else; if the budget is above ~80% of the cap, warn them
   explicitly since this course's budget doesn't reset on session restart.
4. **If the status is not already running:** click **Start Lab**. State
   plainly that you're doing this (it consumes session time/budget — that's
   expected, but the student should know). Poll — re-`read_page` every
   ~15-20s, timeout at 5 minutes — until the status flips to running. Lab
   startup commonly takes 1-3 minutes.
   **If it's already running,** skip straight to the next step.
5. **Click AWS Details** to open the "Cloud Access" panel (skip if it's
   already open/visible). Locate the "AWS CLI" credential block — a
   monospace block starting with `[default]` followed by
   `aws_access_key_id=`, `aws_secret_access_key=`, `aws_session_token=`.
6. **Extract the text**, preferring `get_page_text` or `read_page` (actual
   DOM/accessibility text) over reading a screenshot — a screenshot risks a
   single mistranscribed character silently breaking the credentials, which
   `get_page_text`/`read_page` don't. Only fall back to a screenshot if both
   fail, and if you do, tell the student to double-check by falling back to
   Workflow 1 instead of trusting the transcription.
7. **Write it to disk and verify**, reusing the same validated path the
   manual flow uses — pipe the extracted block into the script rather than
   asking the student to paste it themselves:
   ```bash
   printf '%s' "$EXTRACTED_BLOCK" | python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aws-lab/refresh_credentials.py"
   ```
8. **Report** the resolved account ID, remaining session time, and budget
   used — not the raw secret values.

If any step fails (extension not connected, elements not found after a
couple of `read_page` retries, credential block doesn't validate), say so
plainly and drop to Workflow 1 rather than silently retrying forever or
guessing at values.

## Workflow 1 (fallback) — manual credential paste

Use this when Claude in Chrome isn't available/connected, or Workflow 0
couldn't extract a valid block.

1. Confirm the student has the lab started and "AWS Details" > "AWS CLI"
   open in their own browser (any browser — no extension needed for this
   path).
2. Ask them to paste the full credential block into the chat.
3. ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aws-lab/refresh_credentials.py"
   ```
   feeding it the pasted block via stdin (or write it to a temp file and
   pass the path as an argument). The script validates the block, backs up
   any existing `~/.aws/credentials`, writes the new one, and confirms with
   `aws sts get-caller-identity`.
4. Report the resolved account ID.

## Workflow 2 — rebuild MyEKS from scratch (after a budget-exhausted account reset)

Run the dry-run first and show the student the plan — cluster creation
alone takes 10-20 minutes and node group creation a few more, so set that
expectation before starting:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aws-lab/bootstrap_eks.py" --dry-run
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aws-lab/bootstrap_eks.py"
```

The script is idempotent — safe to re-run if it fails partway (a
`iam:CreateServiceLinkedRole` race on a brand-new account is expected and
retried automatically; see the reference doc). It:

1. Pre-creates the ELB service-linked role to dodge the first-LoadBalancer race.
2. Finds the default VPC/subnets and tags them for the in-tree LB controller.
3. Creates/verifies `MyEKSGroup` (inbound HTTP 80 from anywhere).
4. Creates the `MyEKS` cluster and a 2-node managed node group, both using
   `LabRole` (the only IAM role Academy allows) — no custom IAM role, no
   OIDC/IRSA setup.
5. Opens the NodePort range from `MyEKSGroup` into the cluster's node
   security group (needed for the Gateway/LoadBalancer path in L2-L4).
6. Creates the `guestbook-frontend` / `guestbook-backend` ECR repos.
7. Updates the local kubeconfig and labels one node `storage-demo=postgres`
   for the L3/L4 storage lab.

After it finishes, run Workflow 3 to confirm everything actually works
end-to-end before telling the student they're unblocked.

## Workflow 3 — verify the environment

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aws-lab/verify_eks.py"
```

Cross-platform (macOS/Windows) check: credentials valid, cluster ACTIVE,
security group exists, kubectl can list nodes, helm works. Report the first
failing check plainly rather than the raw AWS CLI error — translate it
using the reference doc when the cause is an Academy-specific restriction
rather than a real bug.

## Workflow 4 — tear down (stop paying for it)

Only run when the student explicitly asks (done with EKS labs for now, or
conserving budget before a long gap). Explain first that this deletes real
infrastructure, including load balancers Kubernetes created that
`aws eks delete-cluster` would otherwise leave running and billing:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aws-lab/teardown_eks.py"          # dry run, shows the plan
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aws-lab/teardown_eks.py" --yes    # after the student confirms
```

## Cross-platform notes

All scripts are plain Python 3 (stdlib only, no pip installs) and shell out
to `aws`/`kubectl`/`helm` on PATH — they run identically on Windows and
macOS. `${CLAUDE_PLUGIN_ROOT}` resolves correctly on both.
