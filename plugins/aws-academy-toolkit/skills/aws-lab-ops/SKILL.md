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
  management and text retrieval on a browser the student is already
  authenticated in, not authentication itself: navigating to the course's
  AWS Academy page, clicking **Start Lab**, typing `cat ~/.aws/credentials`
  into the already-authenticated embedded terminal, and copy/pasting that
  already-displayed temporary credential text via keyboard shortcuts (see
  Workflow 0 for the exact bounded technique and its one-attempt fallback
  to manual paste).
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
does and doesn't guarantee — full automation, including pulling out the
credential text, is attempted but not guaranteed to work every time (see
Workflow 0), so don't oversell it:

> "Do you have the Claude in Chrome extension connected, and are you
> logged into your AWS Academy course in that browser? If so I can try to
> open the page, start the lab, and pull the credentials automatically —
> it usually works, but if it doesn't I'll just ask you to paste the
> credential block yourself. If you'd rather skip the automation entirely
> and do the whole thing yourself, that's fine too."

Save whichever they pick (`true`/`false`) so this is never asked again.
Note this preference doesn't have to be perfectly reliable forever — if
`browser_assist` is `true` but Claude in Chrome genuinely isn't connected in
a given session, just say so and fall back to Workflow 1 for *that* session
without changing the saved preference (it might be connected again next
time).

## Workflow 0 (primary, if browser_assist=true) — browser-assisted start + credential refresh

**Why not just read the "AWS Details" panel directly:** it sits inside a
cross-origin Vocareum iframe, so `get_page_text`/`read_page` return
nothing, and reading the OS clipboard via `navigator.clipboard.readText()`
hits a native permission dialog the extension's tools can't click through.
Typing and clicking still work fine inside that iframe (cross-origin only
blocks *JS reads*, not synthesized input), which is what the technique
below relies on.

1. **Load the tools.** `ToolSearch` for
   `select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__tabs_create_mcp,mcp__claude-in-chrome__javascript_tool`
   in one call.
2. **Navigate** to the saved course URL. The lab page embeds a Vocareum
   panel with a status dot (`AWS 🔴`/`AWS 🟢`), a budget readout ("Used
   $X of $50"), a timer, buttons (**Start Lab**, **End Lab**, **AWS
   Details**, **Readme**, **Reset**), and an embedded terminal.
3. **Screenshot once** to read the status dot and budget. Report both to
   the student before doing anything else; if the budget is above ~80% of
   the cap, warn them explicitly since this course's budget doesn't reset
   on session restart.
4. **If the status is not already running:** click **Start Lab**. State
   plainly that you're doing this (it consumes session time/budget — that's
   expected, but the student should know). Poll with a screenshot every
   ~15-20s, timeout at 5 minutes, until the dot goes green and the terminal
   prompt is live. Lab startup commonly takes 1-3 minutes. **If it's
   already running,** skip straight to the next step.
5. **Get the credentials via the terminal, one bounded attempt:**
   a. Click into the embedded terminal, type `cat ~/.aws/credentials`,
      press Enter. Screenshot once to confirm the `[default]` block
      printed (sanity check only — don't transcribe it from this
      screenshot).
   b. Select the terminal's output (drag-select the printed lines, or
      select-all inside the terminal pane) and copy it
      (`cmd+c` on macOS / `ctrl+c` on Windows/Linux — this is a plain
      copy, no permission dialog).
   c. Open a **new tab** (`tabs_create_mcp`) and use `javascript_tool` to
      inject a plain textarea this tab fully owns —
      `document.body.innerHTML = '<textarea id="paste-target" autofocus style="width:99vw;height:95vh;font-family:monospace"></textarea>'`
      — then click into that textarea and paste (`cmd+v` / `ctrl+v`;
      pasting is also permission-free, unlike reading the clipboard via
      JS).
   d. Read the pasted text back with `javascript_tool` —
      `document.getElementById('paste-target').value` — this is a normal
      same-page JS read (the tab is Claude's own blank page, not the
      cross-origin iframe), so it returns exact text with no OCR risk.
   e. Close the extra tab. Validate the extracted text contains
      `aws_access_key_id=`, `aws_secret_access_key=`, and
      `aws_session_token=` before using it.
6. **If step 5 succeeds:** feed the extracted block straight into the
   script instead of asking the student to paste it themselves:
   ```bash
   printf '%s' "$EXTRACTED_BLOCK" | python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aws-lab/refresh_credentials.py"
   ```
   Then continue to Workflow 1b below (reattach the node security group) —
   don't skip it just because credentials came from the automated path.
7. **If step 5 fails at any point** (paste comes back empty, doesn't
   validate, or any sub-step errors) — **this is one bounded attempt, not
   a chain to keep escalating.** Don't fall back to screenshot OCR, don't
   retry a different clipboard trick. Say plainly that automated
   extraction didn't work this time and drop straight to Workflow 1.

This technique is untested against a live session as of this writing —
first time it's actually run, treat it as provisional: if it works,
great, keep using it; if it breaks in a way not covered above, fall back
per step 7 and mention what specifically failed so this section can be
fixed.

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
4. Continue to Workflow 1b below — don't stop here.

## Workflow 1b — reattach the node security group (every session, not optional)

Run this immediately after Workflow 0 or Workflow 1 succeeds, every single
time, even if it was attached last session:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aws-lab/attach_myeksgroup_to_nodes.py"
```

This is transcribed directly from this course's own AWS-Setup-TUT1.pdf,
which explicitly warns: **"Security group needs to be changed when starting
a new session."** AWS Academy can swap out the underlying EC2 instances
between sessions without touching the EKS cluster or node group objects, so
a node that had `MyEKSGroup` attached last session may be a different
instance now, without it — silently breaking NodePort/curl access to
anything the student deployed, in a way that looks like a Kubernetes bug
but isn't. The script is idempotent (skips nodes that already have it), so
running it every time costs nothing when nothing changed. Report the
resolved account ID — not the raw secret values — once both this and
credential refresh are done.

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
2. Finds the default VPC/subnets and tags them for the in-tree LB controller
   (needed for the Gateway/LoadBalancer path in L2-L4; this base tutorial
   itself doesn't use a load balancer, but the later labs do).
3. Creates/verifies `MyEKSGroup` — **All TCP, port range 0-65535, from
   0.0.0.0/0** (not just port 80 — transcribed exactly from this course's
   AWS-Setup-TUT1.pdf, description text "Allow all HTTP requests" despite
   covering all ports).
4. Creates the `MyEKS` cluster (custom configuration, not EKS Auto Mode)
   and the `MyEKS-nodegroup` managed node group (2x `t3.medium`, 20 GiB
   disk, on-demand, default AMI), both using `LabRole` (the only IAM role
   Academy allows) — no custom IAM role, no OIDC/IRSA setup. Every field
   here matches the tutorial's own console screenshots exactly; anything
   the tutorial doesn't mention changing (Kubernetes version, AMI type,
   cluster authentication mode) is left at whatever AWS currently defaults
   to, not hardcoded.
5. Attaches `MyEKSGroup` directly to each worker node's primary network
   interface (see Workflow 1b — this step also reruns standalone every
   session, not just during bootstrap).
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
security group exists **and is actually attached to every current node**
(a `[WARN]` here means run Workflow 1b, not that something is broken),
kubectl can list nodes, helm works. Report the first failing check plainly
rather than the raw AWS CLI error — translate it using the reference doc
when the cause is an Academy-specific restriction rather than a real bug.

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
