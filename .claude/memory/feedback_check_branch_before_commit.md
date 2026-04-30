---
name: Always verify branch before commit/push
description: On the shared Pi 5 host the operator's `git checkout` switches the working tree silently for me too. Run `git branch --show-current` (or `git status`) before every commit and push to confirm I'm not on `main`.
type: feedback
---

The Pi 5 production host is **shared** between me (Claude Code) and the operator. We both work in the same `/home/ncenter/projects/GODO/` checkout. When the operator does `git checkout main` (e.g., to deploy after a PR merge), MY working tree silently follows — there is no notification or system reminder.

If I then commit without verifying the branch, my changes land on `main` locally, and `git push` (with no args) goes straight to `origin/main`, **bypassing PR review**.

This happened on 2026-04-30 KST: after PR #48 merged, the operator ran `git checkout main` for deployment. I subsequently made a follow-up edit (pinch-zoom sensitivity hotfix) thinking I was still on `fix/p4.5-pan-clamp-and-pinch-zoom`. The commit (dd348ba) landed on `main` and pushed directly. The operator chose to leave it (Option C — small docs-grade content, already-deployed change), but the violation was real.

**Why:** GODO's commit-safety protocol (`CLAUDE.md` §"Executing actions with care" / §"Committing changes with git") forbids direct main-branch pushes. My internal model of "I'm on branch X" was stale; the working tree had moved underneath me silently.

**How to apply:** every commit + push sequence MUST start with an explicit branch check:

1. **Before staging files**: `git status` (which prints the branch on its first line) OR `git branch --show-current`. Read the output — do not skip.
2. **If on `main` (or any branch I did not deliberately create this session)**: STOP. Either `git checkout` to the right branch, or `git checkout -b` to make a new one.
3. **Before `git push`**: re-check. If I just made a commit and the commit message header shows `[main <hash>]` instead of `[branch-name <hash>]`, do NOT push — recover via `git reset --soft HEAD~1` then re-checkout to the right branch.
4. **Belt-and-braces**: when committing a follow-up to a previous PR's branch, prefer `git push origin <branch>` (explicit) over bare `git push`. The bare form silently follows the upstream of whatever HEAD currently points to.

**Operator-side check that helped catch it**: the `[main dd348ba]` token in the commit-output line was visible in conversation. If I had read that line carefully BEFORE running `git push`, I would have seen `main` and stopped. So: **read git's output, don't just assume success**.

This rule applies to ALL future shared-Pi work. Even small docs-only changes go through a feature branch + PR if the alternative is touching `main` directly.
