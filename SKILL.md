---
name: project
description: "Scaffolds and orchestrates Mike's project / plan / session workflow in `03. Work/`. Six ops: `/project new` stamps a project file from `06. System/templates/project.md`; `/project plan` scaffolds a phased plan linked back to a project; `/project session` writes a timestamped session linked to project + active plan (with `--successor-of` for rotation handoffs, enforcing the scope-reduction invariant); `/project status` rewrites the orchestrator-maintained Live status block on a project page atomically; `/project reconcile` walks sessions newest-first to find the anchor and flag orphaned in-progress sessions; `/project orchestrate` reads project + active plan + last session, proposes a session goal, dispatches subagents (Explore, general-purpose) or existing Skiff skills, and writes back progress with every material write confirmed first (project files stay human-only per schema). At ~30 percent remaining context the orchestrator wraps the current session and scaffolds a successor so the next invocation resumes in a fresh window. `/project orchestrate --autonomous` runs the loop unattended under `/loop` until the active plan is complete, with relaxed autonomy gates, soft/hard thresholds, anchor reconciliation on resume, and a hard scope-reduction invariant on successor sessions. Use when user says '/project', 'new project', 'kick off a project', 'start a session on X', 'new plan for X', 'log a session', 'orchestrate project X', 'run project X', 'advance project X', or any request to create or progress a project / plan / session entity in 03. Work/."
type: skill
---

# project

Scaffolder + orchestrator for Mike's project / plan / session workflow under `03. Work/`. Replaces the manual copy-the-template flow and adds an orchestrator that runs a project forward by dispatching subagents and other Skiff skills.

## Templates the skill reads

- `06. System/templates/project.md` → `03. Work/projects/{Project Name}.md`
- `06. System/templates/plan.md` → `03. Work/plans/YYYY-MM-DD {Title}.md`
- `06. System/templates/session.md` → `03. Work/sessions/YYYY-MM-DD-HHMM-{slug}.md`

All paths resolve through `06. System/paths.md` (`PROJECTS_DIR`, `PLANS_DIR`, `SESSIONS_DIR`, `TEMPLATES_DIR`, `VAULT_ROOT`) at runtime.

## Six operations

The first three (`new`, `plan`, `session`) and the two utility ops (`status`, `reconcile`) are backed by `scripts/project.py`. The sixth (`orchestrate`) is foreground-Claude logic — there is no `orchestrate` subcommand in the script.

### 1. `/project new "Project Name"`

Scaffold a project file.

```sh
python3 ~/Skiff/00.\ Workspace/skills/shared/project/scripts/project.py new "AI is the New UI"
```

- Reads `templates/project.md`, strips `_meta`, replaces `{Project Name}`.
- Stamps `added: YYYY-MM-DD` (today). Defaults `status: someday-maybe`, `priority: normal` (already in template).
- Writes to `PROJECTS_DIR/{Project Name}.md`.
- Opens in Obsidian unless `--no-open`.

If the project file already exists, exits non-zero unless `--force`.

### 2. `/project plan "Project Name"` (optional `--title "Plan Title"`)

Scaffold a plan linked back to a project.

```sh
python3 .../project.py plan "AI is the New UI"
python3 .../project.py plan "AI is the New UI" --title "Phase 1 Scaffold"
```

- Fuzzy-resolves the project (case-insensitive substring match on file stems in `PROJECTS_DIR`). Ambiguous matches list candidates and exit; tell the user to disambiguate.
- Default title = project name; `--title` overrides.
- Writes to `PLANS_DIR/YYYY-MM-DD {Title}.md`.
- Stamps `date:` to today and adds `related: - "[[Project Name]]"`.

### 3. `/project session "Project Name" "descriptor"`

Scaffold a session linked to project + active plan.

```sh
python3 .../project.py session "AI is the New UI" "phase-2-build"
```

- Resolves the project, then finds the latest plan whose `related:` contains `[[Project Name]]` and whose `status` is `active` or `draft`. Sorts by `date:` desc. Links it via `related:`. If no plan matches, links the session to project only and prints a note.
- Filename `YYYY-MM-DD-HHMM-{project-kebab}-{descriptor-kebab}.md` matches the existing convention (e.g. `2026-05-08-1031-garmin-daily-sync-kickoff.md`).
- Stamps `date:` to today and `session_id: {slug}-{date}` to match existing sessions.

**Rotation-successor form** (used by the orchestrator at context handoff):

```sh
python3 .../project.py session "AI is the New UI" "continue-3" \
  --successor-of "2026-05-17-1430-ai-is-the-new-ui-phase-2-build" \
  --delegated-scope "Finish phase-2 steps 4-6; capture review notes" \
  --kept-work "Phase-3 build; final review"
```

When `--successor-of` is set, the script **enforces the scope-reduction invariant** (hard fail): `--delegated-scope` AND `--kept-work` must both be non-empty. The prior session is appended to `related:`, the new session's frontmatter carries `delegated_scope` / `kept_work` values, and the Goal block is prefilled as `Continue from [[<prior>]]: <scope>` / `Kept work for future sessions: <kept_work>`.

### 4. `/project status "Project Name"` (--active-plan, --active-session, --last-outcome, --next-action, --iterations, --blocked-on)

Rewrite the orchestrator-maintained `## Live status` block on the project page atomically. The block lives between `<!-- BEGIN LIVE STATUS -->` and `<!-- END LIVE STATUS -->` markers in the project template — those are the only lines this op ever touches. Each invocation:

- Reads the project file and captures its mtime.
- Applies any supplied field updates; preserves untouched fields.
- Always stamps `last_updated` to the current ISO timestamp.
- Re-reads mtime just before write and **fails fast** if the file changed under us (human edit collision).

Empty-string args explicitly clear a field (e.g. `--blocked-on ""`). Omitted args leave the field as-is.

```sh
python3 .../project.py status "AI is the New UI" \
  --active-plan "2026-05-12 Phase 2 Build" \
  --active-session "2026-05-17-1430-ai-is-the-new-ui-continue-3" \
  --last-outcome "Phase-2 step 3 closed; outline draft ready for review" \
  --next-action "Run phase-2 step 4 (synthesis pass)" \
  --iterations "12"
```

### 5. `/project reconcile "Project Name"`

Walk sessions linked to the project newest-first (chronological order via filename prefix). Print:

- **anchor**: the most recent session with a complete `## Outcome` block — the safe resume point.
- **orphaned**: any session with `status: in-progress` that lacks an Outcome. These are crash-mid-rotation artifacts the orchestrator should NOT treat as the resume point.

Used at the start of every `/project orchestrate --autonomous` tick as a pre-flight (see Resume protocol below).

```sh
python3 .../project.py reconcile "AI is the New UI"
```

### 6. `/project orchestrate "Project Name"`

Foreground Claude becomes the orchestrator. Single-pass per invocation = one focused session. See the **Orchestrator workflow** section below for the full procedure.

## Path resolution

The script resolves anchors from `06. System/paths.md` at runtime — never hardcoded. Override the paths.md location with `SKIFF_PATHS_MD=/some/other/paths.md` if you need to test in a sandbox.

Anchors consumed: `VAULT_ROOT`, `PROJECTS_DIR`, `PLANS_DIR`, `SESSIONS_DIR`, `TEMPLATES_DIR`.

## Write boundaries (load-bearing)

The skill enforces these so the orchestrator does not silently violate the schema's `write_class: human-only` constraint on projects.

| File | Scaffolder writes? | Orchestrator writes? |
|------|--------------------|----------------------|
| Session (`SESSIONS_DIR/...`) | Yes — full scaffold | Yes, freely (per-write confirmation in interactive `orchestrate`; auto in `--autonomous` for Progress, Outcome, and the Expand footer). |
| Plan (`PLANS_DIR/...`) | Yes — full scaffold | Narrowly: tick boxes the session completed; flip plan status only on plan-level completion (confirmed first). In `--autonomous`, ticks auto-apply when the session DoD explicitly maps to specific steps; **plan status flips remain human-gated even in autonomous mode**. |
| Project (`PROJECTS_DIR/...`) | Yes — initial scaffold only (`new` op) | **Never to human-authored sections.** The `status` op rewrites ONLY the fenced `## Live status` block (mtime-guarded). All other fields — `status`, `next_action`, `waiting_on`, Overview, Scope, Why now, Dependencies — are drafted inside the session Outcome for Mike to copy up. |

The `new`, `plan`, `session`, and `status` ops are the only routes that write to project files. `new` creates; `status` rewrites only the Live status block between its markers. `new` exits unless `--force` if the project already exists.

## Out of scope

- Writes to `02. Wiki/` (D18 — wiki is human-gated; not relevant here anyway since `03. Work/` is not wiki, but stated for clarity).
- Multi-session chaining inside one orchestrate invocation. Context rotation hands off; the next `/project orchestrate` invocation resumes from the successor session.
- Touching files outside `03. Work/projects|plans|sessions/`.
- Generating substance — Overview, Why now, Scope, Goal, Steps, Outcome stay human-written. The skill scaffolds the container.

---

## Orchestrator workflow

When invoked as `/project orchestrate "Project Name"`, foreground Claude follows this procedure. The script is not involved beyond the scaffolders it already provides (`new`, `plan`, `session`).

### 1. Read context

- Read `PROJECTS_DIR/{Project Name}.md`. Pay attention to `status`, `next_action`, `waiting_on`, Scope (in/out), Dependencies.
- Read the latest `active` or `draft` plan whose `related:` contains `[[Project Name]]`, sorted by `date:` desc.
- Read the most recent session linked to the project (sort `SESSIONS_DIR/YYYY-MM-DD-HHMM-...` files by name, filter by `related:` containing `[[Project Name]]`).

If any of these are missing, surface that and ask Mike whether to scaffold them first (a fresh project may have no plan yet).

### 2. Propose a session goal

From the active plan's next unchecked step (or steps in the current phase), draft a single-sentence session goal with an explicit Definition of Done. Present it to Mike. Wait for confirmation or redirection. Do not proceed silently.

### 3. Propose the session scaffold

Show Mike the proposed filename, frontmatter (`date`, `session_id`, `related:` links), and Goal block. On confirmation, invoke `scripts/project.py session` to write it. Open in Obsidian.

### 4. Dispatch subagents and skills

Based on the session's Definition of Done, pick the right executor for each chunk of work:

| Need | Executor |
|------|----------|
| Read-only investigation / "where is X" | `Explore` subagent |
| Code or file edits | `general-purpose` subagent (worktree isolation for risky changes) |
| High-stakes output (investor-facing, model output) | Second `general-purpose` subagent reviews the first agent's diff |
| Domain work matched by an existing Skiff skill | Invoke the skill directly — `/fmp-enrich`, `/last30`, `/hamhelmer`, `/earnings-call`, `/cashflow-memo`, etc. Mike has confirmed skill dispatch is in scope. Prefer this over re-implementing. |

Pass each subagent the project Overview + Scope, the active plan's current phase, and the session Goal + Definition of Done as inline context. Do not ask subagents to re-read paths.md or templates.

### 5. Write back progress

As subagents return, write to the session's `## Progress` section. **In-flight Progress bullets are exempt from per-write confirmation** — they are narration of subagent results, not structural changes. Keep them tight: one bullet per dispatch, headline result only, not the full subagent output.

**Material writes always require confirmation before they land:**
- Session `## Outcome` block
- Session status flip (e.g. `in-progress → review`)
- Plan checkbox ticks (mark `[x]` for steps the session completed)
- Plan status flips
- Proposed project frontmatter deltas (drafted INSIDE the session Outcome, never written to the project file)

Show Mike the proposed write and the target path. Wait for OK. Then write.

### 6. Close the session

When the session's Definition of Done is met:
- Draft the `## Outcome` block: what was produced, what changed, what's left, any proposed project-level deltas (`next_action`, `status`, `waiting_on`).
- Propose flipping session status to `review` (not `done` — Mike marks done).
- Propose plan checkbox ticks for the steps completed.
- If the plan's current phase is now fully checked, propose flipping plan status (`draft` → `active`, or `active` → `done`).
- Surface any proposed project frontmatter changes for Mike to copy up manually.

Confirm each. Then write.

### Stop conditions (return control to Mike)

- Definition of Done met (proposed Outcome ready for review).
- A subagent reports a blocker the orchestrator cannot route around. Propose session status → `blocked` and a project `waiting_on:` value.
- A proposed write would touch the project file directly. Stop — that's a human-only surface.
- A proposed action breaks the plan's stated scope or Mike's explicit instructions. Stop and surface.
- More than ~3 subagent dispatches without progress (cost guardrail).
- Remaining context approaches ~30% — trigger the rotation procedure below.

### Context-aware session rotation

The orchestrator must monitor remaining context and wrap cleanly before auto-compaction kicks in. Auto-compaction is lossy; a clean handoff preserves the chain.

When remaining context approaches ~30%:

1. Stop dispatching new subagents.
2. Propose the current session's wrap:
   - `## Outcome` describing state-at-handoff (what completed, what's mid-flight, what's pending).
   - Session status → `review` (not `done`).
3. On confirmation, write the wrap.
4. Propose a successor session via `scripts/project.py session`:
   - Same project, descriptor like `continue-{N}` or whatever fits the residual work.
   - The successor's `related:` will pick up project + active plan automatically; manually append `[[<prior session stem>]]` so the chain is explicit.
   - Goal block prefilled with `Continue from [[<prior session>]]: <one-line residual summary>`.
5. Write the successor and return control. Tell Mike: "Context rotation complete. Re-invoke `/project orchestrate "Project Name"` in a fresh window to resume from the new session."

Do not attempt to continue work into the successor session within the same invocation. The whole point of rotation is to drop into a fresh window.

---

## Autonomous mode (`/project orchestrate --autonomous "Project Name"`)

Designed to run under `/loop`: each tick re-enters the orchestrator in a fresh window, reads vault state, advances the active plan, rotates, and returns. The loop continues until the **active plan reaches all-checkboxes-ticked** — at which point the orchestrator proposes `plan.status → done`, which is a human gate, and the loop pauses.

Use the substrate:

```sh
/loop /project orchestrate --autonomous "AI is the New UI"
```

State lives on disk: project page Live status block, session chain, plan checkboxes. Nothing depends on conversation context surviving between ticks.

### Done condition (one chain = one plan)

The chain terminates when the orchestrator proposes flipping the active plan from `active` → `done` and Mike either approves (loop ends; Mike re-arms for the next plan) or rejects (loop pauses for human input). The orchestrator never writes `plan.status: done` autonomously.

Autonomous mode operates on **one plan at a time**. To advance through multiple plans, Mike re-points the loop after each completion.

### Autonomy gates (relaxed vs. interactive mode)

| Surface | Interactive `orchestrate` | `--autonomous` |
|---|---|---|
| Session `## Progress` bullets | auto | auto |
| Session `## Outcome` block | confirm before write | **auto** (drafted via 3-level escalation) |
| Session `## Expand for details on:` footer | confirm before write | **auto** (required for any rotation-participating session) |
| Plan checkbox ticks | confirm before write | **auto when** the session's DoD explicitly maps to specific step text |
| Plan status flip (`active → done`) | confirm before write | **gated — pauses the loop** |
| Project Live status block | n/a (interactive mode didn't write this) | **auto** via `scripts/project.py status` (mtime-guarded) |
| Project frontmatter or human sections | drafted in session Outcome | drafted in session Outcome (no change) |

### Two-stage thresholds (soft + hard)

The orchestrator tracks dispatches (subagent calls, skill invocations) and a coarse context-remaining heuristic. Two trigger points:

- **Soft (~50% remaining context OR 12 dispatches OR 30min):** flush the project Live status block now via `project status` — `last_updated`, `active_session`, `last_outcome`, `next_action`, current `iterations` counter. Keep working.
- **Hard (~30% remaining context OR 25 dispatches OR 60min):** stop dispatching new work, begin rotation procedure (see below).

The soft flush satisfies [[feedback-project-handoff-durability]] automatically — by the time the hard threshold trips, the project page already reflects current state.

### Three-level Outcome escalation (rotation always converges)

When the hard threshold trips, the orchestrator must close the session's `## Outcome` block. Under context pressure, drafting a coherent narrative Outcome may fail. Escalate:

1. **Normal:** standard Outcome draft — what was produced, what changed, what's left, proposed project-level deltas. Stamp `outcome_grade: normal`.
2. **Terse:** if Normal fails or the model is clearly degraded, fall back to a structured dump — checked vs. unchecked plan steps, raw Progress bullets, open questions, no synthesis. Stamp `outcome_grade: terse`.
3. **Fallback:** if Terse also fails (or the model can't produce stable output), write a deterministic templated Outcome from session frontmatter + plan-checkbox state only, with NO LLM call. Title + DoD + frontmatter values + "successor should investigate: <unfinished DoD items>". Stamp `outcome_grade: fallback`.

A `terse` or `fallback` Outcome is a signal to the human reviewer that the session needs a follow-up read. The chain still proceeds — the loop never breaks mid-handoff.

The `## Expand for details on:` footer is required for any rotation-participating session. Even in `fallback` grade, list the open questions / dropped specifics there so the successor knows what to fetch.

### Scope-reduction invariant on successor sessions (hard fail)

The successor scaffold call MUST pass `--delegated-scope` and `--kept-work`. `scripts/project.py session --successor-of <stem>` exits non-zero if either is empty. If the orchestrator cannot articulate what's left after the successor will run, the work is not decomposed enough — the loop halts and surfaces to Mike.

```sh
python3 .../project.py session "Project" "continue-3" \
  --successor-of "<prior-session-stem>" \
  --delegated-scope "<what this successor accomplishes>" \
  --kept-work "<what remains for future sessions>"
```

This is the structural guarantee against infinite kick-the-can chains. A successor that says "continue prior session" with empty `kept_work` is rejected.

### Resume protocol (anchor reconciliation on every tick)

Each `--autonomous` invocation begins with:

1. `project reconcile "<Project>"` — print the anchor session and any orphans.
2. If orphans exist (in-progress sessions without a complete Outcome — typically a prior tick that crashed mid-rotation), surface them to Mike. Do NOT silently treat an orphan as the resume point. Mike either marks them `dropped` or completes the Outcome by hand; the loop pauses until then.
3. Anchor at the most recent session with a complete Outcome. Read it (Outcome + Expand footer). Use the Expand footer to decide what, if anything, to fetch from older sessions via an Explore subagent — do NOT load older sessions into foreground context wholesale.
4. Read the active plan; read the project page (Overview + Scope + Live status block).
5. Decide the next session's Goal from the plan's next unchecked steps, scoped tightly to fit in one session's budget.

### Sessions-corpus recall (cheap before expensive)

Before any web search or fresh subagent dispatch on a topic, the orchestrator first greps the sessions corpus:

```sh
rg -l "<topic>" "03. Work/sessions/" | head -5
```

If matches exist, read those sessions' Outcomes (cheap). If detail beyond the Outcome is needed, dispatch a read-only Explore subagent scoped to specific session paths with a focused question. This is the vault analog of LCM's `lcm_grep → lcm_describe → lcm_expand_query` escalation.

### Per-item work uses parallel subagent dispatch (no foreground loops)

When the session needs to process more than two items (e.g. research five companies, review three PRs, classify a list), dispatch parallel subagents in a single message — each with a structured output schema in its prompt — rather than iterating in the foreground. The orchestrator aggregates the typed returns. This keeps per-item intermediate work out of the main context window.

### Large-artifact externalization

Any subagent output that would exceed ~3k tokens of detail (deep-research dumps, large structured datasets) writes to a sibling artifact file:

```
03. Work/sessions/<session-stem>-artifact-<slug>.md
```

The session Outcome carries a one-line reference + a 5-line exploration summary, not the full content. The artifact stays on disk, greppable.

### Hard stops (return control to Mike, end the loop)

The autonomous loop halts and surfaces — DOES NOT continue — when:

- The active plan's last unchecked step is now checked → propose `plan.status: active → done` (human gate).
- A reconcile pre-flight finds an orphaned session.
- A scope-reduction invariant failure (the orchestrator couldn't articulate `delegated_scope` + `kept_work` for a needed successor).
- 8 sessions completed in one chain without plan completion (cost guardrail).
- 2 consecutive sessions report zero plan-checkbox progress (drift detector).
- A subagent flags scope violation against the plan's stated scope.
- The project file's mtime changed between reads (human edited mid-run); next `status` write fails and the loop bails to avoid clobbering.

In all halt cases, the orchestrator writes a final Outcome to the in-flight session and updates the project Live status block with `blocked_on: <reason>` before returning.

---

## Implementation notes

- The script is one file: `scripts/project.py`. No venv needed — stdlib only.
- Vault paths resolve via `06. System/paths.md`. Read it at runtime; never cache.
- Frontmatter editing is line-based: stamp existing keys in place; append missing keys at the end of the FM block. The `related:` list is special-cased to drop the empty `[[]]` placeholder and append wikilinks.
- The `_meta:` block is stripped from templates before writing.
- Slug generation: `{project-name-kebab}-{descriptor-kebab}`. ASCII-only via NFKD normalization + non-alphanumeric replacement. Lowercase.
- Active-plan resolution: scan `PLANS_DIR` for files whose frontmatter `related:` contains `[[Project Name]]` and `status` is `active` or `draft`. Sort by `date:` desc; pick first.
- Successor session resolution (`--successor-of`): exact stem match preferred; otherwise unique substring match in `SESSIONS_DIR/*.md`. Accepts `[[stem]]` wrapping. Ambiguous matches list candidates and exit non-zero.
- Live status block parser: locates lines between `<!-- BEGIN LIVE STATUS -->` and `<!-- END LIVE STATUS -->`, parses `- key: value` entries, re-renders in canonical key order on every write. Outside the markers, the project file is untouched.
- Mtime guard on `project status`: capture `st_mtime_ns` immediately after read; re-stat just before write; bail if it changed. Resolution is nanoseconds; same-process self-edits never trip it because the second stat is read before the write.
- Anchor walk (`project reconcile`): sort sessions lexicographically (filename prefix is `YYYY-MM-DD-HHMM`, so lex == chronological); walk newest-first; collect `in-progress` sessions with no Outcome as orphans; stop at the first session with a complete Outcome (the anchor).
- Outcome completeness test: `## Outcome` body, stripped, is non-empty AND not equal to `(Filled when complete)`.
- Obsidian open uses `obsidian://open?vault=Skiff&file=<urlencoded vault-relative path>`. Suppressible with `--no-open`.
- For renames or moves of project / plan / session files, use the `obsidian` CLI (`obsidian move ...`), never `mv` or `git mv`. This skill does not move files — but if the orchestrator ever needs to, that is the route.

## Triggers

- `/project`, `/project new`, `/project plan`, `/project session`, `/project status`, `/project reconcile`, `/project orchestrate`, `/project orchestrate --autonomous`
- "new project", "kick off a project", "start a project"
- "new plan for X", "plan for project X"
- "start a session on X", "log a session", "session on project X"
- "orchestrate project X", "run project X", "advance project X", "drive project X forward"
- "run project X to completion", "loop on project X", "let it run on X" (→ `--autonomous` under `/loop`)
