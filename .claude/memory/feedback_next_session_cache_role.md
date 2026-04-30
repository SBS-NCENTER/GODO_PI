---
name: NEXT_SESSION.md is a cache, not a SSOT
description: NEXT_SESSION.md is the cold-start cache (cache to SSOT-doc RAM). After a task is absorbed, record outcomes in PROGRESS/history and prune the corresponding NEXT_SESSION.md item — do not let it drift into a parallel ledger.
type: feedback
---

NEXT_SESSION.md is a **cache**, not a SSOT. The operator's analogy
(2026-04-30 11:50 KST):

> SSOT 문서들은 RAM, NEXT_SESSION.md 문서는 cache.

SSOT documents (PROGRESS.md, doc/history.md, .claude/memory/, the
per-stack CODEBASE.md files) are the durable, canonical state.
NEXT_SESSION.md is the throwaway cold-start aid that summarises
what's queued so a new session can hit the ground running without
opening every SSOT file. It is **always disposable**: at the moment
a task is picked up, the corresponding NEXT_SESSION.md entry is
absorbed into the conversation context and the file should be pruned
of it.

## The 3-step absorption routine (operator-locked)

When a session picks up a task from NEXT_SESSION.md:

1. **Read** the relevant TL;DR item + memory pointers + plan files. Do
   the work.
2. **Record** the outcome:
   - PROGRESS.md gets a session-log block (English, technical).
   - doc/history.md gets a session block (Korean narrative, decisions
     focused).
   - The relevant CODEBASE.md gets a change-log entry + invariant
     update (per `feedback_codebase_md_freshness.md`).
   - If the work generated reusable insight, a memory entry under
     `.claude/memory/`.
3. **Prune** the NEXT_SESSION.md item that was just done. It should NOT
   carry forward to the next session except in the form of a
   higher-level "shipped this session" header summary at the close.

## Why this matters

Without disciplined pruning, NEXT_SESSION.md becomes a second ledger
that drifts from the SSOTs:

- Items remain listed after they ship → next session re-evaluates work
  that's already done.
- Pointers to memory files / plan files become stale → the next session
  follows a dangling link.
- The TL;DR ranking grows linearly with session count instead of
  reflecting "what's actually queued right now."

Two real instances seen 2026-04-30:

1. NEXT_SESSION.md referenced `.claude/memory/project_map_edit_origin_rotation.md`
   as if it existed; the file was actually missing and had to be created
   on the spot. The reference had been written before the memo was filed.
2. The "tenth-session close" section enumerated every PR by SHA, but
   the operator's question "next-session priority" pulled from an older
   list. Mixing close-of-session telemetry with forward-looking queue
   blurs the cache role.

## How to apply

- At a session-close, NEXT_SESSION.md is fully rewritten (header
  refreshed with KST time + open-PRs count + active task list). Do not
  patch in place piece-by-piece across a whole session — refresh as the
  last act before commit.
- If a task is in flight at session-close, list it under "Tasks alive
  for next session" with a status hint, not under TL;DR (TL;DR is for
  what to start NEW).
- The "Where we are" block at session-close is permitted to repeat
  recent SSOT highlights briefly (it's the cache priming for the next
  cold-start). But it MUST link back to the SSOT (PROGRESS.md
  session-log entry) rather than restating multi-paragraph detail.
- When a session opens, check that every memory pointer / plan-file
  pointer in NEXT_SESSION.md actually resolves before relying on it.
  Missing pointers = stale cache; either restore the target or remove
  the pointer.

## What this is NOT

- It is NOT a guidance to delete NEXT_SESSION.md. The file is the
  primary cold-start aid; killing it would force every new session to
  re-read PROGRESS.md + history.md + memory in full.
- It is NOT a guidance to prune mid-session. The file is rewritten at
  session-close (after PROGRESS.md + history.md have been updated, so
  the SSOT lead is in place before the cache lags).
