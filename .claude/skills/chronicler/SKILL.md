---
name: chronicler
description: At session-close, bundle all the session's PRs, decisions, and lessons into the SSOT documents (PROGRESS.md, doc/history.md, per-stack CODEBASE.md, FRONT_DESIGN.md, SYSTEM_DESIGN.md). Run when operator signals session end. NEXT_SESSION.md and `.claude/memory/` are explicitly Parent's territory — chronicler does NOT touch them.
---

# chronicler — session-close documentation skill

You are now in **session-close mode**. This skill is invoked by the operator when they decide the current session is wrapping up. Your job is to bundle everything the session produced into the GODO SSOT document family — in ONE coherent docs commit and PR — so the next session can hit the ground running.

This skill runs in the **main conversation context** — you have full memory of what happened this session (PRs opened, decisions locked, operator phrasings, lessons). That context is the most valuable input. Do NOT delegate to a subagent; the conversation memory cannot be transferred losslessly into a brief.

## Trigger conditions

Operator says some variant of:

- "세션 마무리하자"
- "이제 다음 세션 작업으로 넘어가자"
- "정리하고 끝내자"
- `/chronicler` slash command (this skill's invocation)

If the operator just merged the session's last PR and there's no pending work, **propose** invoking chronicler proactively (do NOT auto-invoke).

## Out of scope — Parent's territory (NOT this skill)

These remain Parent's direct responsibility, BEFORE or AFTER chronicler runs:

- **`NEXT_SESSION.md`** — cold-start cache. Curating "what does the next session need to know" requires ongoing-conversation judgment. Parent rewrites it as a whole, referencing chronicler's output.
- **`.claude/memory/*`** — semantic memories (feedback / project / reference). New entries emerge from conversation moments, not from a procedural sweep. Parent writes them when the lesson surfaces.
- **`.claude/agents/*`** — agent definitions (operator-locked discipline; CLAUDE.md §6).

If chronicler discovers a memory entry was missed, flag it for Parent — don't write it.

## Pre-flight (Phase 0)

Before any edit:

```bash
# 1. Confirm we're not stranded on a feature branch from earlier work
git status
git branch --show-current

# 2. Sync main to capture every PR that merged this session
git checkout main
git pull --rebase

# 3. Branch off main for the docs commit
git checkout -b docs/YYYY-MM-DD-Nth-session-close
git branch --show-current   # Verify per feedback_check_branch_before_commit.md
```

The branch name MUST follow `docs/YYYY-MM-DD-Nth-session-close` so it's discoverable in the changelog later. Use today's KST date and the session ordinal (track in conversation — it's "twelfth-session" / "thirteenth-session" etc., counted in PROGRESS.md).

## Phase 1: Gather inventory

Pull objective facts from git/gh. The conversation memory provides the *interpretive* layer; git provides the *factual* layer.

```bash
# All PRs that merged into main during this session
# Adjust --search filter or --limit per session length
gh pr list --state merged --search "merged:>YYYY-MM-DDTHH:MM:SSZ" --limit 30 \
  --json number,title,mergedAt,headRefName,baseRefName,body | jq -r '.[] | "PR #\(.number) — \(.title) [base: \(.baseRefName)]"'

# All commits added since session-start commit (find the start by checking
# the previous chronicler commit OR PROGRESS.md last session-block boundary)
git log --oneline <session-start-commit>..HEAD

# Open PRs (pending HIL or merge)
gh pr list --state open --limit 10

# Per-PR detail when needed
gh pr view <N> --json title,body,files,mergeCommit
```

Build a **session inventory table** (don't write this to a file yet — keep in conversation):

| PR # | issue# | Title | Status | Branch | Key files |
|---|---|---|---|---|---|

Note any PRs that touched `main` directly (e.g., `dd348ba` from twelfth session) — flag for the lesson section.

Note any PRs that "merged" into a dead branch (stacked-PR base trap) — flag for the lesson section.

## Phase 2: Classify the doc-update surface

For each PR, decide which docs it touches:

| PR change type | Doc surfaces |
|---|---|
| New / modified component, module, file pattern | per-stack `CODEBASE.md` change-log + (if introduces invariant) invariant body |
| New design decision (UX rule, architectural pattern) | `FRONT_DESIGN.md` or `SYSTEM_DESIGN.md` (an I-Q entry, §C row, §6/7 wire row) |
| Test-only / docs-only / hotfix without invariant | per-stack `CODEBASE.md` change-log only (no invariant text change) |
| **Family-shape shift** — new stack, renamed module, new cross-stack arrow | Root `CODEBASE.md` and/or root `DESIGN.md` (rare; cascade-edit rule from `feedback_codebase_md_freshness.md`) |
| Lesson learned / rule locked / process correction | Parent writes memory entry (NOT this skill) |

If you're uncertain whether a change "shifts the family shape", default to **leaf-only**. Adding a root-level entry without a leaf counterpart, or vice versa, is a Mode-B Critical finding per `.claude/memory/feedback_codebase_md_freshness.md`.

## Phase 3: PROGRESS.md (English session log)

`PROGRESS.md` is the cross-session technical narrative. Append this session's block at the **top** of the `## Session log` section (most recent first).

Format (mirror the existing twelfth-session block — keep the same density):

```markdown
### YYYY-MM-DD (bucket-and-time-range KST → KST, Nth-session — short title)

[Opening paragraph: one sentence overall thesis + key structural finding.]

**Notable structural revelation** (if any): [conceptual lesson surfaced; cross-link the memory entry Parent will/has written.]

**Process violation + lesson** (if any): [what went wrong + what's locked in feedback memory.]

**N PRs landed/queued this session**:

| PR | Issue | Title | State |
|---|---|---|---|
| #N | issue#X | ... | merged / open / dead-merge |

[Optional: lessons / cross-cutting rules locked.]

**Open queue for next session** (priority order, operator-locked):
1. issue#X — title (priority rationale)
2. ...
```

Date+time stamp rule (CLAUDE.md §6): use bucket label (early morning / morning / afternoon / evening / late-night) PLUS explicit KST time range. Multiple sessions same day must be ordered + distinguishable.

## Phase 4: doc/history.md (Korean narrative)

Same content as PROGRESS but for the human reader — Korean tone, 운영자 phrasing 인용 OK, "왜 / 무엇을 결정했는가" 중심. Engineering terms 영어 원문 유지 (per CLAUDE.md §1).

Format (mirror existing blocks):

```markdown
## YYYY-MM-DD (오후/심야 등 — KST → KST, N 번째 세션 — 짧은 제목)

### 한 줄 요약

[1-2 sentence 결정/발견 요약.]

### N개 PR

| PR | issue# | 제목 | 결과 |
|---|---|---|---|

### [핵심 발견 / 운영자 결정 / 프로세스 lesson 등 섹션]

[narrative paragraphs.]

### 다음 세션 큐

[issue 우선순위 + 잠금 사유.]
```

Reverse chronological order — newest at top of file (after the header section).

Cross-link: anything in PROGRESS.md should be findable here in Korean form. The two files are paired narratives, not duplicates.

## Phase 5: Per-stack CODEBASE.md change-log entries

For each stack (`godo-frontend/`, `godo-webctl/`, `production/RPi5/`) that the session touched:

1. Open the stack's `CODEBASE.md`
2. Find the `## Change log` (or `## 변경 로그`) section
3. Add a new entry at the TOP

Entry format:

```markdown
### YYYY-MM-DD HH:MM KST — issue#N.M / Track-X — short title

#### Added

- `<path>` — what was added + why (one sentence per file).

#### Changed

- `<path>` — what changed + why.

#### Removed

- `<path>` — what was removed (rare; e.g., dropped duplicate code).

#### Invariants

- Added `(letter)`: [invariant statement, pinned by tests/<file>].
- Extended `(existing-letter)`: [what changed].

#### Test counts (optional)

- vitest: 274 → 278 (+4 from `<file>::case`)
- Bundle delta: +2.33 kB gzip (measured via `npm run build`)
```

If a PR introduced a new invariant letter, ALSO add the invariant body in the appropriate position in the file (look for "## Invariants" section — invariants are alphabetical `(a) (b) ...`). The change-log entry references the invariant; the invariant body is the SSOT.

If you find the SAME PR's change log was already added by Parent earlier (before chronicler ran), ENRICH rather than duplicate. Read existing content first.

**Doc gap retroactive entries**: if Phase 1 inventory shows a previously-merged PR has NO change-log entry (e.g., PR #50 in twelfth session), add a retroactive entry with a header note: `> Retroactive change-log entry: PR #N (merged) shipped without a change-log entry. Doc gap filled here for completeness — chronicler audit YYYY-MM-DD HH:MM KST.`

## Phase 6: Design SSOTs (FRONT_DESIGN / SYSTEM_DESIGN)

Touch ONLY when the session introduced a new design decision (not a bug fix in an existing pattern).

`FRONT_DESIGN.md` typical updates:

- §C / §I-Q: add a new I-Q entry for a new UI rule (e.g., I6 Pinch carve-out, I7 Map common header in twelfth session)
- §6 / §7.1: wire row for a new `POST /api/...` endpoint
- §C route table: row for a new SPA route or sub-tab
- §8 Phase tracker: update phase progress

`SYSTEM_DESIGN.md` typical updates:

- New module / file pattern in the C++/webctl backend
- Change to data-flow diagram (e.g., new SSE channel)
- New scheduling decision (RT path, cold path, etc.)

I-Q entry format (FRONT_DESIGN):

```markdown
#### IN. Title (issue#N.M, 2026-MM-DD context)

[1-2 paragraph design narrative. Operator phrasing 인용 OK. Cross-link
to per-stack CODEBASE invariant + memory entry where applicable.]
```

When NOT to touch design SSOTs: hotfixes, test-only PRs, doc-only PRs. The change-log captures those at per-stack level.

## Phase 7: Root cascade verification

Open root `CODEBASE.md` and root `DESIGN.md`. Verify they're UNCHANGED unless the session shifted the family shape:

- New stack added (rare — e.g., a new top-level directory parallel to `godo-webctl/` or `godo-frontend/`)
- Module renamed at the top level
- Cross-stack data flow arrow added/changed (e.g., new wire path between webctl and tracker)

If none of those: leave both files alone. Per `.claude/memory/feedback_codebase_md_freshness.md`, a root edit without a corresponding leaf shape-shift is a Critical finding.

If the session DID shift family shape: update both root scaffolds in the SAME commit; never half-cascade.

## Phase 8: Commit + push + PR

Single commit for all the docs changes. Branch already created in Phase 0.

```bash
# Verify branch (defense per feedback_check_branch_before_commit.md)
git status && git branch --show-current
# Expected: docs/YYYY-MM-DD-Nth-session-close

git add PROGRESS.md doc/history.md \
        godo-frontend/CODEBASE.md \
        godo-webctl/CODEBASE.md \
        production/RPi5/CODEBASE.md \
        FRONT_DESIGN.md \
        SYSTEM_DESIGN.md
# Only stage the files that were actually modified — `git status` first.

git commit -m "docs: YYYY-MM-DD Nth-session close — short summary

[multi-paragraph body summarizing PR list + lessons + queue.]

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
"

# Verify the commit landed on the right branch — the [branch <hash>]
# token in `git commit`'s output should NOT say `[main <hash>]`.

git push -u origin docs/YYYY-MM-DD-Nth-session-close
```

Then open the PR via `gh pr create --base main` with a body that mirrors the commit message.

Do NOT merge the PR yourself. Operator merges after a glance.

## Phase 9: Hand-off to Parent

Once the docs PR is open, signal that chronicler's work is done and Parent's remaining responsibilities are:

1. **`NEXT_SESSION.md` rewrite** — new version that absorbs chronicler's output as input. The 3-step rule from `feedback_next_session_cache_role.md`: read prior NEXT_SESSION → record absorbed items in SSOT (chronicler did this) → prune NEXT_SESSION.
2. **New memory entries (`.claude/memory/`)** — any lesson that surfaced this session and isn't yet captured. Common categories: `feedback_*` (process / collaboration rules), `project_*` (decisions, observations), `reference_*` (external pointers).
3. **`MEMORY.md` index update** — one-line entry per new memory file.
4. **(optional) Branch cleanup** — local `git branch -d <feat-branches>` for everything merged this session.

Parent commits these on a SEPARATE branch (or on the same docs PR branch if minor) and pushes.

## Format hygiene

- Date+time in KST with bucket label (CLAUDE.md §6).
- Engineering terms in English (no translation: stack frame, particle filter, sigma, etc.).
- Operator phrasing kept verbatim where quoted — that's the audit trail.
- Unicode box drawing for diagrams (┌─┐│└─┘├┤┬┴┼▼▲► — never ASCII +-|).
- No emojis in docs (unlike chat). Per `feedback_emoji_allowed.md`: emojis OK in chat, NOT in code/docs/commits.

## When NOT to invoke chronicler

- Session is mid-flight (PRs still open, awaiting HIL).
- Operator hasn't signaled session-close.
- Session produced ZERO merged PRs and ZERO meaningful decisions (rare — usually means the session was research/exploration only; in that case, optionally update `doc/history.md` only with a "research session" stub).
- Operator wants to defer (rare; just say "OK, we'll skip chronicler this time and it goes to next session's open queue").

## When to escalate to Parent (interrupt the procedure)

- Family-shape shift detected (Phase 7) — confirm with operator before touching root files.
- A PR's commits suggest a memory entry is missing — flag it; let Parent decide.
- Conflicting changelog entries from concurrent PRs — sequence them by `mergedAt` and document the order.

## Closing message

After Phase 8 is done, end with:

```
세션 close 문서화 완료. 다음 단계:
- PR #<docs-pr-number> 머지 (운영자)
- NEXT_SESSION.md + 새 메모리 entry (Parent 영역, 후속 commit)

이번 세션 N개 PR + M개 lesson 잠금. 다음 세션 큐 1순위: issue#X.
```

That's the chronicler hand-off.
