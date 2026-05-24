---
_meta:
  description: Project — unified status tracker and workspace
  folder: "03. Work/projects/"
  filename: "{Project Name}.md"
  schema: 06. System/schemas/project.md
  status_values: [someday-maybe, in-progress, blocked, paused, done, dropped]
  priority_values: [low, normal, high, critical]

type: project
status: someday-maybe
priority: normal
next_action: ""
added: ""
waiting_on: ""
dropped_reason: ""
tags:
  - project
---
# {Project Name}

## Overview

## Why now

## Scope

**In scope:**
-

**Out of scope:**
-

## Dependencies

## Sessions

```dataview
TABLE status, date
FROM "03. Work/sessions"
WHERE contains(related, this.file.link)
SORT date DESC
```

## Plans

```dataview
TABLE status, date
FROM "03. Work/plans"
WHERE contains(related, this.file.link)
SORT date DESC
```

## Open Tasks

```dataview
TASK
FROM "03. Work/sessions"
WHERE contains(related, this.file.link) AND !completed
GROUP BY file.link
```

## Live status

<!-- orchestrator-maintained: do not hand-edit between these markers; the `project status` op rewrites this block atomically -->
<!-- BEGIN LIVE STATUS -->
- last_updated:
- active_plan:
- active_session:
- last_outcome:
- next_action:
- iterations:
- blocked_on:
<!-- END LIVE STATUS -->
