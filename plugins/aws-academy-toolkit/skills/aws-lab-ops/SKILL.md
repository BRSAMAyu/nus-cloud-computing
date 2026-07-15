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
  clicking **Start Lab**, and clicking **AWS Details** to open the panel.
  Reading the credential text back out of that panel is the student's job
  (see Workflow 0's note on why automated extraction doesn't work
  reliably here), not something this skill attempts.
- The only secrets this skill ever handles are the short-lived
  `aws_access_key_id` / `aws_secret_access_key` / `aws_session_token`
  triple AWS Academy itself displays to an already-logged-in student — never
  their AWS Academy or Canvas password.
- When reporting results back to the student in chat, never echo the full
  secret access key or session token — confirm success via the resolved AWS
  account ID instead (`aws sts get-caller-identity`), which is all the
  student needs to sanity-check it's their own account.

## Session config (shared across all three skills)

The `SessionStart` hook already loaded `course_url`, `language`, and
`browser_assist` into this conversation's context before your first message
— don't re-run `lab_config.py get` just to check them, that context block
already has the answer. Only shell out to `lab_config.py` to **set** a new
or changed value:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aws-lab/lab_config.py" set course_url "<url>"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aws-lab/lab_config.py" set language zh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aws-lab/lab_config.py" set browser_assist true
```

If `course_url` is unset, ask the student to paste their course's "Launch
AWS Academy Learner Lab" URL (the Canvas modules/items link) the first time
you actually need it (i.e. when they ask to start/refresh the lab, not
proactively out of nowhere), then save it — this only ever happens once per
machine.

If `browser_assist` is unset, ask the student **once**, explicitly, which
they'd prefer — don't silently pick one for them. Be accurate about what it
does and doesn't cover — pulling the credential text out automatically
doesn't work reliably (see Workflow 0's note), so don't oversell it:

> "Do you have the Claude in Chrome extension connected, and are you
> logged into your AWS Academy course in that browser? If so I can open
> the page and click Start Lab for you — you'll still need to paste the
> credential block yourself once it's ready, that part can't be automated
> reliably. If you'd rather just do the whole thing yourself in your own
> browser, that's fine too."

Save whichever they pick (`true`/`false`) so this is never asked again.
Note this preference doesn't have to be perfectly reliable forever — if
`browser_assist` is `true` but Claude in Chrome genuinely isn't connected in
a given session, just say so and fall back to Workflow 1 for *that* session
without changing the saved preference (it might be connected again next
time).

## Workflow 0 (primary, if browser_assist=true) — browser-assisted start + credential refresh

**Scope of automation, deliberately narrow:** browser automation handles
starting/resuming the lab session and getting the "AWS Details" panel open
— it does **not** attempt to extract the credential text itself. That split
is based on real testing, not caution for its own sake: the credential
block sits inside a cross-origin Vocareum iframe, so DOM/accessibility text
extraction (`get_page_text`, `read_page`) returns nothing; reading it via
the OS clipboard hits a native permission dialog the extension's tools
can't click through; and reading it off a screenshot risks silently
swapping `0`/`O` or `1`/`l`/`I` in a 40-character secret, which is a
correctness bug, not just a UX papercut. Don't re-attempt any of these — go
straight to asking the student to paste, immediately after confirming the
panel is open. This keeps the whole flow to about 8-10 tool calls instead
of 20-30.

1. **Load the tools.** `ToolSearch` for
   `select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__tabs_create_mcp`
   in one call. (`read_page`/`get_page_text` aren't worth loading here —
   see above.)
2. **Navigate** to the saved course URL. The lab page embeds a Vocareum
   panel with a status dot (`AWS 🔴`/`AWS 🟢`), a budget readout ("Used
   $X of $50"), a timer, and buttons: **Start Lab**, **End Lab**, **AWS
   Details**, **Readme**, **Reset**.
3. **Screenshot once** to read the status dot and budget. Report both to
   the student before doing anything else; if the budget is above ~80% of
   the cap, warn them explicitly since this course's budget doesn't reset
   on session restart.
4. **If the status is not already running:** click **Start Lab**. State
   plainly that you're doing this (it consumes session time/budget — that's
   expected, but the student should know). Poll with a screenshot every
   ~15-20s, timeout at 5 minutes, until the dot goes green. Lab startup
   commonly takes 1-3 minutes. **If it's already running,** skip straight
   to the next step.
5. **Click AWS Details** to open the "Cloud Access" panel (skip if already
   open), then one screenshot to confirm the `[default]` / `aws_access_key_id=`
   block is visible.
6. **Hand off immediately**: tell the student the panel is open and ask
   them to paste the credential block, exactly as in the manual flow below.
   Do not attempt extraction first.

If any earlier step fails (extension not connected, Start Lab click doesn't
register, status never flips green after the timeout), say so plainly and
drop to manual paste for the whole thing rather than retrying indefinitely.

## Workflow 1 — get the credentials into `~/.aws/credentials`

This step is the same regardless of whether Workflow 0 automated the
lab-start part or the student did it themselves in their own browser —
credential capture is always a manual paste, for the reasons above.

1. Confirm the student has the lab running and "AWS Details" > "AWS CLI"
   open (in whichever browser — no extension needed for this step).
2. Ask them to paste the full credential block into the chat.
3. ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aws-lab/refresh_credentials.py"
   ```
   feeding it the pasted block via stdin (or write it to a temp file and
   pass the path as an argument). The script validates the block, backs up
   any existing `~/.aws/credentials`, writes the new one, and confirms with
   `aws sts get-caller-identity`.
4. Report the resolved account ID — not the raw secret values.

## Is there an official API instead of the browser entirely?

Checked: Vocareum (the platform behind AWS Academy Learner Lab) does have
an official REST API with an endpoint that returns a user's lab session
credentials and can start/extend the session
(`courses/{courseId}/assignments/{assignmentId}/parts/{partId}/resources/{userId}`).
It is **not usable here**: generating a personal access token for it is
restricted to Vocareum Organization Admins in account Settings — individual
students have no self-service way to get one. If the course's teaching
staff ever want to issue per-student tokens themselves, this API would
replace browser automation entirely (far more reliable, near-zero token
cost) — that's a course-infrastructure decision for them, not something
this skill can set up on its own.

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

Some Windows Python installs only expose `python`, not `python3` (and vice
versa on some Linux setups only `python3` exists). If a `python3 ...`
invocation fails with "command not found", retry the identical command with
`python` before concluding something is actually broken.
