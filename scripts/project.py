#!/usr/bin/env python3
"""project - scaffolder for Skiff project / plan / session entities.

Resolves vault paths via 06. System/paths.md at runtime. Reads templates from
06. System/templates/{project,plan,session}.md. Stamps frontmatter, strips
_meta, writes the file, optionally opens it in Obsidian.

Subcommands:
  new        Scaffold a project at PROJECTS_DIR/{Name}.md
  plan       Scaffold a plan at PLANS_DIR/YYYY-MM-DD {Title}.md
  session    Scaffold a session at SESSIONS_DIR/YYYY-MM-DD-HHMM-{slug}.md
             With --successor-of, enforces the scope-reduction invariant
             (--delegated-scope and --kept-work must both be non-empty).
  status     Rewrite the orchestrator-maintained `## Live status` block on a
             project page atomically (mtime-guarded read-modify-write).
  reconcile  Walk sessions for a project newest-first; print the anchor
             (most recent session with a complete Outcome) and flag any
             `in-progress` sessions missing an Outcome as orphaned.

The orchestrator op (`/project orchestrate`) is not a CLI subcommand. That
logic lives in SKILL.md as instructions for the foreground Claude.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from urllib.parse import quote


def _discover_paths_file() -> Path:
    env = os.environ.get("SKIFF_PATHS_MD")
    if env:
        return Path(os.path.expanduser(env))

    candidates: list[Path] = []
    script_dir = Path(__file__).resolve().parent
    candidates.extend([script_dir, *script_dir.parents])
    cwd = Path.cwd().resolve()
    candidates.extend([cwd, *cwd.parents])

    seen: set[Path] = set()
    for base in candidates:
        if base in seen:
            continue
        seen.add(base)
        probe = base / "06. System" / "paths.md"
        if probe.exists():
            return probe

    sys.exit(
        "error: could not find 06. System/paths.md. "
        "Set SKIFF_PATHS_MD to an explicit file path."
    )


PATHS_FILE = _discover_paths_file()


def resolve(anchor: str) -> str:
    """Look up a path anchor in 06. System/paths.md and return its first value line."""
    text = PATHS_FILE.read_text()
    m = re.search(rf"^## {re.escape(anchor)}$\n(.+?)(?:\n##|\Z)", text, re.M | re.S)
    if not m:
        raise KeyError(f"unknown path anchor: {anchor}")
    for line in m.group(1).strip().splitlines():
        line = line.strip()
        if not line or line.startswith("-") or line.startswith("#"):
            continue
        return line
    raise ValueError(f"anchor {anchor} has no value line")


def vault_root() -> Path:
    return Path(os.path.expanduser(resolve("VAULT_ROOT")))


def vault_name() -> str:
    try:
        return resolve("VAULT_NAME")
    except KeyError:
        return "Skiff"


def vault_path(anchor: str) -> Path:
    """Resolve an anchor as an absolute path. Vault-relative anchors join under VAULT_ROOT."""
    raw = resolve(anchor)
    if raw.startswith("~") or raw.startswith("/"):
        return Path(os.path.expanduser(raw))
    return vault_root() / raw


def kebab(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s


def split_frontmatter(text: str) -> tuple[str, str]:
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        raise ValueError("no frontmatter block found")
    return m.group(1), m.group(2)


def join_frontmatter(fm: str, body: str) -> str:
    return f"---\n{fm}\n---\n{body}"


def strip_meta(text: str) -> str:
    """Drop the top-level `_meta:` block from frontmatter, keeping everything else."""
    fm, body = split_frontmatter(text)
    lines = fm.splitlines()
    out, skip = [], False
    for line in lines:
        if line.startswith("_meta:"):
            skip = True
            continue
        if skip:
            # children are indented; bail when we hit a non-indented, non-empty line
            if line and not line.startswith((" ", "\t")):
                skip = False
                out.append(line)
            # else: still inside the _meta block, drop
            continue
        out.append(line)
    return join_frontmatter("\n".join(out).rstrip(), body)


def stamp_frontmatter(text: str, edits: dict[str, str]) -> str:
    """Edit or append top-level frontmatter keys. Preserves block structure."""
    fm, body = split_frontmatter(text)
    lines = fm.splitlines()
    handled: set[str] = set()
    for i, line in enumerate(lines):
        for key, val in edits.items():
            if key in handled:
                continue
            if re.match(rf"^{re.escape(key)}:\s*", line):
                lines[i] = f"{key}: {val}"
                handled.add(key)
                break
    for key, val in edits.items():
        if key not in handled:
            lines.append(f"{key}: {val}")
    return join_frontmatter("\n".join(lines), body)


def add_related(text: str, link_stems: list[str]) -> str:
    """Append wikilinks to the `related:` list. Drops the empty `[[]]` placeholder."""
    fm, body = split_frontmatter(text)
    lines = fm.splitlines()

    start = None
    for i, line in enumerate(lines):
        if re.match(r"^related:\s*$", line):
            start = i
            break

    if start is None:
        new_block = ["related:"] + [f'  - "[[{s}]]"' for s in link_stems]
        return join_frontmatter("\n".join(lines + new_block), body)

    end = start
    for j in range(start + 1, len(lines)):
        if re.match(r"^\s+-\s", lines[j]):
            end = j
            continue
        break

    existing: list[str] = []
    for j in range(start + 1, end + 1):
        line = lines[j].strip()
        if re.match(r'^-\s*"?\[\[\]\]"?\s*$', line):
            continue
        existing.append(line)

    new_items = list(existing)
    for s in link_stems:
        cand = f'- "[[{s}]]"'
        if cand not in new_items:
            new_items.append(cand)

    new_block = [lines[start]] + [f"  {it}" for it in new_items]
    rebuilt = lines[:start] + new_block + lines[end + 1:]
    return join_frontmatter("\n".join(rebuilt), body)


def load_template(name: str) -> str:
    primary = vault_path("TEMPLATES_DIR") / f"{name}.md"
    if primary.exists():
        return primary.read_text()
    fallback = Path(__file__).resolve().parents[1] / "templates" / f"{name}.md"
    if fallback.exists():
        return fallback.read_text()
    sys.exit(
        f"error: template '{name}.md' not found in "
        f"{vault_path('TEMPLATES_DIR')} or {fallback.parent}"
    )


def list_projects() -> list[Path]:
    projects_dir = vault_path("PROJECTS_DIR")
    return sorted(
        p for p in projects_dir.glob("*.md")
        if not p.name.endswith(".bak") and not p.name.startswith(".")
    )


def matches_for(query: str) -> list[Path]:
    q = query.lower().strip()
    return [p for p in list_projects() if q in p.stem.lower()]


def resolve_project(query: str) -> Path:
    """Fuzzy-resolve a single project file. Exit non-zero on miss or ambiguous match."""
    # exact stem match wins outright
    for p in list_projects():
        if p.stem.lower() == query.lower().strip():
            return p
    candidates = matches_for(query)
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        sys.exit(f"error: no project matched '{query}' in {vault_path('PROJECTS_DIR')}")
    sys.exit(
        f"error: ambiguous project '{query}'. matches:\n  "
        + "\n  ".join(p.stem for p in candidates)
    )


def active_plan_for(project_stem: str) -> Path | None:
    """Return the most recent active/draft plan whose related: includes [[project_stem]]."""
    plans_dir = vault_path("PLANS_DIR")
    candidates: list[tuple[str, Path]] = []
    for p in plans_dir.glob("*.md"):
        try:
            text = p.read_text()
        except Exception:
            continue
        m = re.match(r"^---\n(.*?)\n---", text, re.S)
        if not m:
            continue
        fm = m.group(1)
        status_m = re.search(r"^status:\s*(\S+)", fm, re.M)
        status = status_m.group(1).strip() if status_m else ""
        if status not in ("active", "draft"):
            continue
        if f"[[{project_stem}]]" not in fm:
            continue
        date_m = re.search(r"^date:\s*(\S+)", fm, re.M)
        date = date_m.group(1).strip() if date_m else ""
        candidates.append((date, p))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def open_in_obsidian(target: Path) -> None:
    rel = target.relative_to(vault_root())
    url = f"obsidian://open?vault={quote(vault_name())}&file={quote(str(rel))}"
    subprocess.run(["open", url], check=False)


# ---------- subcommands ----------

def cmd_new(args: argparse.Namespace) -> None:
    name = args.name.strip()
    if not name:
        sys.exit("error: project name required")
    target = vault_path("PROJECTS_DIR") / f"{name}.md"
    if target.exists() and not args.force:
        sys.exit(f"error: {target} already exists (use --force to overwrite)")

    tpl = load_template("project")
    tpl = strip_meta(tpl)
    today = _dt.date.today().isoformat()
    tpl = stamp_frontmatter(tpl, {"added": today})
    tpl = tpl.replace("{Project Name}", name)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(tpl)
    print(f"wrote {target}")
    if not args.no_open:
        open_in_obsidian(target)


def cmd_plan(args: argparse.Namespace) -> None:
    project = resolve_project(args.project)
    project_stem = project.stem
    title = (args.title or project_stem).strip()
    today = _dt.date.today().isoformat()

    target = vault_path("PLANS_DIR") / f"{today} {title}.md"
    if target.exists() and not args.force:
        sys.exit(f"error: {target} already exists (use --force to overwrite)")

    tpl = load_template("plan")
    tpl = strip_meta(tpl)
    tpl = stamp_frontmatter(tpl, {"date": today})
    tpl = add_related(tpl, [project_stem])
    tpl = tpl.replace("{Plan Title}", title)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(tpl)
    print(f"wrote {target}")
    print(f"  linked to: [[{project_stem}]]")
    if not args.no_open:
        open_in_obsidian(target)


def _resolve_successor_session(stem_query: str) -> Path:
    """Resolve a prior session by exact stem or unique suffix substring."""
    sessions_dir = vault_path("SESSIONS_DIR")
    q = stem_query.strip()
    if not q:
        sys.exit("error: --successor-of cannot be empty")
    # Strip wikilink wrapping if user passed "[[stem]]"
    q = q.strip("[]").strip()
    candidates = sorted(p for p in sessions_dir.glob("*.md") if q in p.stem)
    if not candidates:
        sys.exit(f"error: no session matched '{stem_query}' in {sessions_dir}")
    # Prefer exact stem match
    for p in candidates:
        if p.stem == q:
            return p
    if len(candidates) == 1:
        return candidates[0]
    sys.exit(
        f"error: ambiguous --successor-of '{stem_query}'. matches:\n  "
        + "\n  ".join(p.stem for p in candidates)
    )


def cmd_session(args: argparse.Namespace) -> None:
    project = resolve_project(args.project)
    project_stem = project.stem
    descriptor = (args.descriptor or "session").strip()

    # Scope-reduction invariant: a rotation successor MUST declare both
    # --delegated-scope and --kept-work. Hard fail otherwise.
    successor_of: Path | None = None
    if args.successor_of:
        delegated_scope = (args.delegated_scope or "").strip()
        kept_work = (args.kept_work or "").strip()
        if not delegated_scope or not kept_work:
            sys.exit(
                "error: --successor-of requires non-empty --delegated-scope AND "
                "--kept-work (scope-reduction invariant)."
            )
        successor_of = _resolve_successor_session(args.successor_of)

    now = _dt.datetime.now()
    today = now.date().isoformat()
    hhmm = now.strftime("%H%M")
    slug = f"{kebab(project_stem)}-{kebab(descriptor)}"
    target = vault_path("SESSIONS_DIR") / f"{today}-{hhmm}-{slug}.md"
    if target.exists() and not args.force:
        sys.exit(f"error: {target} already exists (use --force to overwrite)")

    tpl = load_template("session")
    tpl = strip_meta(tpl)
    session_id = f"{slug}-{today}"
    fm_edits: dict[str, str] = {"date": today, "session_id": session_id}
    if successor_of is not None:
        fm_edits["delegated_scope"] = _yaml_dq((args.delegated_scope or "").strip())
        fm_edits["kept_work"] = _yaml_dq((args.kept_work or "").strip())
    tpl = stamp_frontmatter(tpl, fm_edits)

    links = [project_stem]
    plan = active_plan_for(project_stem)
    if plan is not None:
        links.append(plan.stem)
    if successor_of is not None:
        links.append(successor_of.stem)
    tpl = add_related(tpl, links)

    desc_human = descriptor.replace("-", " ").strip().title() or "Session"
    title = f"{project_stem} - {desc_human}"
    tpl = tpl.replace("{Session Title}", title)

    if successor_of is not None:
        goal_block = (
            "## Goal\n\n"
            f"Continue from [[{successor_of.stem}]]: "
            f"{(args.delegated_scope or '').strip()}\n\n"
            f"Kept work for future sessions: {(args.kept_work or '').strip()}\n"
        )
        tpl = re.sub(
            r"## Goal\n\nWhat this session aims to accomplish \(outcome, not tasks\)\.\n",
            goal_block,
            tpl,
            count=1,
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(tpl)
    print(f"wrote {target}")
    for l in links:
        print(f"  linked to: [[{l}]]")
    if plan is None:
        print("  (no active plan found - linked to project only)")
    if successor_of is not None:
        print(f"  successor of: [[{successor_of.stem}]]")
    if not args.no_open:
        open_in_obsidian(target)


def _yaml_dq(s: str) -> str:
    """Quote a string as a YAML double-quoted scalar (used for frontmatter values)."""
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


# ---------- Live status block on the project page ----------

LIVE_BEGIN = "<!-- BEGIN LIVE STATUS -->"
LIVE_END = "<!-- END LIVE STATUS -->"

# Keys allowed inside the Live status block. Order is the canonical write order.
LIVE_KEYS = (
    "last_updated",
    "active_plan",
    "active_session",
    "last_outcome",
    "next_action",
    "iterations",
    "blocked_on",
)


def _parse_live_block(text: str) -> tuple[int, int, dict[str, str]] | None:
    """Return (start_idx, end_idx, kv) for the Live status block, or None if absent.

    start_idx/end_idx are line indices of the BEGIN/END marker lines.
    kv preserves whatever values are currently in the block.
    """
    lines = text.splitlines()
    start = end = -1
    for i, ln in enumerate(lines):
        if ln.strip() == LIVE_BEGIN:
            start = i
        elif ln.strip() == LIVE_END:
            end = i
            break
    if start < 0 or end < 0 or end <= start:
        return None
    kv: dict[str, str] = {}
    for ln in lines[start + 1 : end]:
        m = re.match(r"\s*-\s*([a-z_]+)\s*:\s*(.*)$", ln)
        if m:
            kv[m.group(1)] = m.group(2).strip()
    return start, end, kv


def _render_live_block(kv: dict[str, str]) -> list[str]:
    out = [LIVE_BEGIN]
    for k in LIVE_KEYS:
        v = kv.get(k, "")
        out.append(f"- {k}: {v}")
    out.append(LIVE_END)
    return out


def cmd_status(args: argparse.Namespace) -> None:
    project = resolve_project(args.project)

    text = project.read_text()
    mtime_before = project.stat().st_mtime_ns
    parsed = _parse_live_block(text)
    if parsed is None:
        sys.exit(
            f"error: no Live status block found in {project}. "
            f"Re-scaffold from the template or paste the BEGIN/END markers manually."
        )
    start, end, kv = parsed

    # Apply CLI updates. Empty string explicitly clears a field; --bump only
    # refreshes last_updated.
    updates: dict[str, str | None] = {
        "active_plan": args.active_plan,
        "active_session": args.active_session,
        "last_outcome": args.last_outcome,
        "next_action": args.next_action,
        "iterations": args.iterations,
        "blocked_on": args.blocked_on,
    }
    for k, v in updates.items():
        if v is not None:
            kv[k] = v

    now_iso = _dt.datetime.now().replace(microsecond=0).isoformat()
    kv["last_updated"] = now_iso

    lines = text.splitlines()
    new_block = _render_live_block(kv)
    rebuilt = "\n".join(lines[:start] + new_block + lines[end + 1 :])
    if text.endswith("\n"):
        rebuilt += "\n"

    # mtime guard: if the project file was touched since we read it, bail rather
    # than clobber a concurrent human edit.
    mtime_now = project.stat().st_mtime_ns
    if mtime_now != mtime_before:
        sys.exit(
            f"error: project file changed under us ({project}). Re-run after the "
            f"human edit settles. (mtime delta: {mtime_now - mtime_before} ns)"
        )

    project.write_text(rebuilt)
    print(f"updated live status: {project}")
    for k in LIVE_KEYS:
        print(f"  {k}: {kv.get(k, '')}")


# ---------- reconcile (anchor recovery) ----------

OUTCOME_PLACEHOLDER = "(Filled when complete)"


def _has_complete_outcome(text: str) -> bool:
    """A session has a complete Outcome iff its `## Outcome` block contains
    non-placeholder content before the next `##` heading or EOF."""
    m = re.search(r"^## Outcome\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not m:
        return False
    body = m.group(1).strip()
    if not body:
        return False
    if body == OUTCOME_PLACEHOLDER:
        return False
    # Treat a body that is only the placeholder plus whitespace/blank lines as empty.
    stripped = re.sub(r"\s+", " ", body).strip()
    return stripped not in ("", OUTCOME_PLACEHOLDER)


def _session_status(text: str) -> str:
    m = re.search(r"^status:\s*(\S+)", text, re.M)
    return m.group(1).strip() if m else ""


def _sessions_for(project_stem: str) -> list[Path]:
    sessions_dir = vault_path("SESSIONS_DIR")
    out: list[Path] = []
    for p in sessions_dir.glob("*.md"):
        try:
            text = p.read_text()
        except Exception:
            continue
        m = re.match(r"^---\n(.*?)\n---", text, re.S)
        if not m:
            continue
        if f"[[{project_stem}]]" in m.group(1):
            out.append(p)
    # Sessions are timestamp-prefixed, so a lexical sort is chronological.
    return sorted(out)


def cmd_reconcile(args: argparse.Namespace) -> None:
    project = resolve_project(args.project)
    project_stem = project.stem
    sessions = _sessions_for(project_stem)
    if not sessions:
        print(f"no sessions found linked to [[{project_stem}]]")
        return

    # Statuses that represent a real resume point: completed work or an
    # explicit pause. `dropped` is abandoned work, not a continuation, so it
    # is skipped over to anchor on the most recent live state.
    ANCHOR_STATUSES = {"done", "review", "blocked"}

    anchor: Path | None = None
    orphans: list[Path] = []
    # Walk newest-first.
    for p in reversed(sessions):
        text = p.read_text()
        status = _session_status(text)
        complete = _has_complete_outcome(text)
        if status == "in-progress" and not complete:
            orphans.append(p)
            continue
        if status == "dropped":
            # Skip — neither an anchor nor an orphan.
            continue
        if complete and status in ANCHOR_STATUSES and anchor is None:
            anchor = p
            # Stop at the first valid anchor — older sessions are irrelevant
            # for resume purposes (the Expand-footer + sessions-corpus grep
            # handle older recall).
            break

    print(f"project: {project_stem}")
    print(f"sessions scanned: {len(sessions)}")
    if anchor is not None:
        print(f"anchor: {anchor.stem}")
    else:
        print("anchor: (none — no session has a complete Outcome)")
    if orphans:
        print(f"orphaned ({len(orphans)}):")
        for p in orphans:
            print(f"  {p.stem}")
    else:
        print("orphaned: none")


def main() -> None:
    p = argparse.ArgumentParser(
        prog="project",
        description="Scaffolder for Skiff project / plan / session entities.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_new = sub.add_parser("new", help="Scaffold a project file.")
    p_new.add_argument("name", help='Project name (e.g. "AI is the New UI").')
    p_new.add_argument("--no-open", action="store_true")
    p_new.add_argument("--force", action="store_true")
    p_new.set_defaults(func=cmd_new)

    p_plan = sub.add_parser("plan", help="Scaffold a phased plan linked to a project.")
    p_plan.add_argument("project", help="Project name or fuzzy match.")
    p_plan.add_argument("--title", help="Override plan title (default: project name).")
    p_plan.add_argument("--no-open", action="store_true")
    p_plan.add_argument("--force", action="store_true")
    p_plan.set_defaults(func=cmd_plan)

    p_ses = sub.add_parser("session", help="Scaffold a session linked to project + active plan.")
    p_ses.add_argument("project", help="Project name or fuzzy match.")
    p_ses.add_argument("descriptor", help='Short descriptor (e.g. "phase-2-build").')
    p_ses.add_argument(
        "--successor-of",
        help="Stem of the prior session this one continues from. Requires "
        "--delegated-scope and --kept-work.",
    )
    p_ses.add_argument(
        "--delegated-scope",
        help="What this successor session will accomplish. Required with --successor-of.",
    )
    p_ses.add_argument(
        "--kept-work",
        help="Work that remains for future sessions after this one. Required "
        "with --successor-of (scope-reduction invariant).",
    )
    p_ses.add_argument("--no-open", action="store_true")
    p_ses.add_argument("--force", action="store_true")
    p_ses.set_defaults(func=cmd_session)

    p_status = sub.add_parser(
        "status",
        help="Rewrite the orchestrator-maintained Live status block on a project page.",
    )
    p_status.add_argument("project", help="Project name or fuzzy match.")
    p_status.add_argument("--active-plan", help="Plan wikilink stem or empty.")
    p_status.add_argument("--active-session", help="Session wikilink stem or empty.")
    p_status.add_argument("--last-outcome", help="One-line summary of the last session outcome.")
    p_status.add_argument("--next-action", help="One-line next action.")
    p_status.add_argument("--iterations", help="Cumulative dispatches/iterations counter.")
    p_status.add_argument("--blocked-on", help="Blocker description, or empty if unblocked.")
    p_status.set_defaults(func=cmd_status)

    p_rec = sub.add_parser(
        "reconcile",
        help="Walk sessions newest-first; print the anchor and any orphaned in-progress sessions.",
    )
    p_rec.add_argument("project", help="Project name or fuzzy match.")
    p_rec.set_defaults(func=cmd_reconcile)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
