# nus-cloud-computing — Claude Code plugin

A Claude Code plugin for the NUS cloud computing course: AWS Academy
Learner Lab session/credential automation, EKS rebuild-from-scratch, a
Socratic tutor for the L1-L4 Kubernetes labs, and a deployment checker for
group projects targeting this course's restricted AWS Academy EKS.

Kept as its own repo, separate from the lab content repo, because this
tooling needs to be available in *every* project directory a student opens
— this term's labs, next term's labs, a group project folder — not just one
specific lab checkout.

## Prerequisites

- A reasonably recent Claude Code CLI — run `claude update` first if you
  haven't updated in a while; the plugin marketplace commands used below
  need a version that supports `/plugin`.
- `python3` (or `python`) on PATH. Scripts try `python3` first and fall back
  to `python` automatically — some Windows installs only expose one of the
  two, some Linux setups only the other.
- `git`, AWS CLI v2, `kubectl`, `helm` — same prerequisites the labs
  themselves already require.

## Install (students, one-time per machine)

Inside Claude Code:

```
/plugin marketplace add https://github.com/BRSAMAyu/nus-cloud-computing.git
/plugin install aws-academy-toolkit@nus-cloud-computing
```

Use the full `https://...git` URL, not the `owner/repo` shorthand. The
shorthand form lets Claude Code choose SSH or HTTPS based on your local git
config, and on a machine that has `insteadOf` rewrites (or `gh auth
setup-git`) configured for SSH, it clones over SSH — and fails with
`Permission denied (publickey)` if you don't have a GitHub SSH key set up.
The explicit HTTPS URL always works with no GitHub auth at all, since this
repo is public.

If you already hit the SSH error, remove the half-added marketplace first,
then re-add with the HTTPS URL:

```
/plugin marketplace remove nus-cloud-computing
/plugin marketplace add https://github.com/BRSAMAyu/nus-cloud-computing.git
```

After installing, the three skills below are available in any directory
you run `claude` in.

### One shared onboarding, not three separate ones

A single `SessionStart` hook (not each skill re-asking its own questions)
handles session setup for all three skills at once:

- **First session ever after install:** a short, one-time orientation
  explaining the three skills — never shown again after that.
- **Every session:** your saved course URL, language preference, and
  browser-automation preference are loaded into context automatically, so
  no skill needs to ask twice or re-check a config file mid-conversation.

Three things get asked **once each**, the first time they're actually
needed (not all up front):

| Setting | Asked when | Remembered as |
|---|---|---|
| Course URL | first time you ask `aws-lab-ops` to start/refresh the lab | `course_url` |
| Browser automation vs. manual paste | same — `aws-lab-ops` asks you to pick, doesn't silently guess | `browser_assist` |
| Language | never asked — set it yourself only if you want consistency (see below) | `language` |

All three live in `~/.config/nus-cloud-computing/config.json` — local to
your machine, never committed anywhere, never shared between students.

### Language

Every skill defaults to mirroring whatever language you type in, same as
Claude normally does — no setup needed. If you'd rather all three skills
always respond in one language regardless of what you happen to type in a
given message (e.g. you want consistent Chinese explanations), set it once:

```
python3 "<plugin path>/scripts/aws-lab/lab_config.py" set language zh
```

(Ask Claude to run this for you — it'll resolve `<plugin path>` correctly.)

### Browser automation vs. manual credential paste

The `aws-lab-ops` skill can start/resume your AWS Academy lab session and
pull fresh credentials directly out of the browser — no copy-pasting — if
you have the **Claude in Chrome** extension installed and connected, and are
already logged into Canvas/AWS Academy in that Chrome profile. The first
time you ask it to start/refresh the lab, it asks you which you'd prefer
and remembers your answer — it never silently picks one for you. Either
way works the same from there on.

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
| `lab_config.py` | stores/reads course_url, language, and browser_assist locally |
| `onboarding_hook.py` | SessionStart hook: one-time welcome + injects saved config every session for all 3 skills |
| `refresh_credentials.py` | validates and writes a pasted/extracted credential block, verifies it |
| `bootstrap_eks.py` | idempotently (re)creates `MyEKS` + `MyEKSGroup` + ECR repos from a bare account |
| `attach_myeksgroup_to_nodes.py` | (re)attaches `MyEKSGroup` to every current node's primary network interface — must rerun every session |
| `verify_eks.py` | cross-platform health check (credentials, cluster, security group + its node attachment, kubectl, helm) |
| `teardown_eks.py` | deletes the node group, cluster, and any orphaned Kubernetes-created load balancers |
| `academy_k8s_lint.py` | scans a project's YAML/Terraform for Academy-incompatible patterns |

## Maintaining this repo

- Bump `version` in both `plugins/aws-academy-toolkit/.claude-plugin/plugin.json`
  and the matching entry in `.claude-plugin/marketplace.json` on every
  release students should actually receive — `/plugin update` and
  auto-update skip a plugin whose resolved version hasn't changed.
- `claude plugin validate .` from the repo root checks `marketplace.json`
  and every plugin's `plugin.json`/skill frontmatter before you push.

### Why credential capture is a bounded one-shot attempt, not naive retries

Tested live: reading the AWS CLI credential block directly off the "AWS
Details" panel doesn't work — it renders inside a cross-origin Vocareum
iframe (DOM/accessibility text extraction returns nothing), reading it via
`navigator.clipboard.readText()` hits a native OS permission dialog
automation can't click through, and OCR-ing it from a screenshot risks
silently swapping `0`/`O` in a 40-character secret.

`aws-lab-ops` works around this instead of giving up: type
`cat ~/.aws/credentials` into the lab's own embedded terminal, copy the
output with a keyboard shortcut (copying is permission-free, unlike
reading the clipboard back via JS), paste it into a textarea on a blank
tab Claude creates and fully owns, then read that textarea's value with a
normal same-page JS call — no cross-origin restriction, no OCR. This is
one bounded attempt; if any step in it fails, the skill drops straight to
asking the student to paste the block themselves rather than escalating
through more workarounds. As of this writing it hasn't been exercised
against a live session yet, so treat early runs as provisional.

There is a real alternative, but it needs your involvement: Vocareum (the
platform behind AWS Academy Learner Lab) has an official REST API
(`https://api.vocareum.com/api/v2/`) with an endpoint
(`courses/{courseId}/assignments/{assignmentId}/parts/{partId}/resources/{userId}`)
that returns a user's lab credentials and can start/extend their session —
no browser needed at all. Generating a personal access token for it is
restricted to Vocareum **Organization Admins** (Settings → Personal Access
Tokens), so individual students can't self-serve one. If you're willing to
generate and distribute per-student tokens as the course's org admin, this
API would fully replace the browser-automation path — far more reliable
and near-zero token cost — but that's course-infrastructure work only you
can do, not something this plugin can set up unilaterally.
