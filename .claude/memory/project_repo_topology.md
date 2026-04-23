---
name: Repo topology and multi-machine workflow
description: Three machines (Mac, Windows, RPi5) share GODO via the company SSOT remote SBS-NCENTER/GODO_PI; personal chunbay/GODO is a one-way mirror clone, not used for pushes.
type: project
---

GODO is developed across three hosts and one authoritative GitHub repo.

**Machines**
- **Mac** (`/Users/chunbae/Workspaces/GODO`) — main dev.
- **Windows** — dev / on-site testing.
- **RPi5** — production target, accessed via VSCode SSH remote. Lives under `production/RPi5/` when checked out.

**Git remotes (as of 2026-04-23)**
- **SSOT:** `https://github.com/SBS-NCENTER/GODO_PI.git` (company account). All three machines point `origin` here. This is where everyone pushes and pulls.
- **Mirror only:** `https://github.com/chunbay/GODO.git` (personal account). Kept as a one-way clone / backup. **Do not push to it.** It exists because the project started there before the company split; kept around for history.

**Why:** Company-owned code needs to live in a company-owned GitHub org. Earlier work happened in a personal repo, and splitting it out cleanly (instead of rewriting history) was easier via "company = SSOT, personal = mirror." Confirmed identical history on 2026-04-23 (HEAD `b8bbfac`).

**How to apply:**
- Multi-machine workflow rules in CLAUDE.md §6 "Cross-platform hygiene" stay exactly as written — they are remote-agnostic and still correct. Machine switch protocol: commit + push on machine A → `git pull --rebase` on machine B.
- Before suggesting `git remote set-url` or similar changes, verify the user's intent — the split was deliberate, don't "unify" personal and company repos.
- All cross-session state must live **inside the repo** (`PROGRESS.md`, `CLAUDE.md`, `doc/`, `.claude/memory/`), never in host-specific caches like `~/.claude/projects/.../memory/`. This rule predates the repo split and still applies.
- Avoid hard-coded absolute paths like `/Users/chunbae/...` in committed docs — they break on Windows and RPi5. Prefer project-relative paths.
- Large reference assets (PDFs, datasheets) go **inside the repo** (e.g., `doc/RPLIDAR/sources/`), never external links only, so they stay available on the offline RPi5 and cross-platform.
