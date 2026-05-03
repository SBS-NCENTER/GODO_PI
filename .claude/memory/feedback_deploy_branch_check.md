---
name: Verify git branch + working tree state before production rsync
description: Production rsync deploys whatever the working tree currently has — if Parent is mid-PR on a feature branch, the live system gets unmerged code. Operator deploy SOP must include `git status` + `git branch --show-current` BEFORE rsync.
type: feedback
---

The Pi 5 host (`news-pi01`) shares the working tree at `/home/ncenter/projects/GODO/` between Parent (Claude Code, doing PR work) and the operator (doing deploy). When Parent is mid-PR on a feature branch, the working tree contains UNMERGED code — anything operator's `rsync` picks up at that moment lands on the live system.

**What happened (2026-05-03 eighteenth-session, ~07:30 KST)**: After PR #72 merged, operator ran the standard deploy sequence including:

```bash
sudo rsync -a --delete --exclude='.venv' --exclude='__pycache__' \
    /home/ncenter/projects/GODO/godo-webctl/ /opt/godo-webctl/
```

But Parent was simultaneously working on issue#10.1 in `feat/issue-10.1-lidar-serial-config-row` (Phase 1 / planner phase already complete). The writer agent had already bumped `EXPECTED_ROW_COUNT 52 → 53` in `godo-webctl/src/godo_webctl/config_schema.py:111`. The rsync therefore deployed **53-pin webctl** against the **live 52-row tracker schema** (still PR #72 binary). webctl `/api/config/schema` returned 503 ("rows count mismatch") and SPA Config tab went empty.

Hotfix: `sudo sed -i 's/EXPECTED_ROW_COUNT: Final\[int\] = 53/EXPECTED_ROW_COUNT: Final[int] = 52/' /opt/godo-webctl/.../config_schema.py` + webctl restart. After issue#10.1 merged, redeploy aligned everything to 53 naturally.

**Why this is unique to GODO**: most production-deploy patterns assume a clean source-of-truth (e.g., GitHub Actions building from a tag). GODO's deploy is operator-driven from the dev workstation's working tree because the dev workstation IS the production host. There's no separation of "build artifact" vs "working tree".

**How to apply (operator deploy SOP — pre-rsync gate)**:

1. **Always check branch before rsync**:
   ```bash
   cd /home/ncenter/projects/GODO
   git status                 # working tree clean? on main?
   git branch --show-current  # explicit branch check
   ```
   If output is anything other than `main` (or the expected merged branch), STOP.

2. **If Parent is mid-PR** (working tree shows feature branch + uncommitted/committed work), use one of:
   - **Option A — stash + switch + redeploy**:
     ```bash
     git stash
     git switch main && git pull --ff-only origin main
     sudo rsync -a --delete --exclude='.venv' --exclude='__pycache__' \
         /home/ncenter/projects/GODO/godo-webctl/ /opt/godo-webctl/
     sudo systemctl restart godo-webctl
     git switch <feature-branch>
     git stash pop
     ```
   - **Option B — explicit checkout-only-the-stack**:
     ```bash
     git checkout main -- godo-webctl/   # restore main state for the stack
     sudo rsync ...                       # deploy
     git checkout <feature-branch> -- godo-webctl/   # restore feature state
     ```
     (Riskier: working tree changes for that path are clobbered by checkout. Only safe if no operator-level edits exist outside committed work.)

3. **For tracker / RPi5 stack**: `bash production/RPi5/scripts/build.sh` reads the working tree's source. Same branch-awareness applies — never build from a feature branch unless you intend to deploy that branch.

4. **For godo-frontend**: `npm run build` writes `dist/`; same pattern. `sudo rsync -a --delete /home/ncenter/projects/GODO/godo-frontend/dist /opt/godo-frontend/` (note the trailing-slash convention from CLAUDE.md §8 — `dist` source without trailing slash means `/opt/godo-frontend/dist/` becomes the target path).

**Why this rule matters now**: Auto-mode + multi-PR sessions mean Parent often opens a new PR's branch IMMEDIATELY after the previous PR merges. The window where "working tree on main = safe to deploy" can be very short (sometimes minutes). Branch awareness must be procedural, not memory-based.

Cross-references:
- `feedback_check_branch_before_commit.md` — sister rule, but for the OPPOSITE direction (Parent committing on operator's branch). Both are "shared working tree" hazards.
- `CLAUDE.md` §8 — Standard deploy pipeline doesn't currently document the branch-awareness step. Future SOP update should fold this in.
