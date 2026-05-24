# obsidian-project-skill

Project orchestration skill for Obsidian/OpenClaw workflows.

## Contents
- `SKILL.md`
- `scripts/project.py`
- `templates/project.md`
- `templates/plan.md`
- `templates/session.md`

## Notes
- `project.py` resolves `06. System/paths.md` by discovery (or `SKIFF_PATHS_MD` override), with no hardcoded vault path.
- Templates load from `TEMPLATES_DIR` first, then fall back to bundled `templates/` in this repo.
