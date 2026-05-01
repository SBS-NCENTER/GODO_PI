---
name: SPA restart-pending banner stale across non-action paths
description: PR #45 fixed banner clearing after a service-restart action click, but operator observes (2026-05-01 09:30+ KST during issue#3 HIL on news-pi01) the banner persists past tracker restart in other paths — Config-tab edits, page-time idle polling, etc. Workaround = manual page reload. Real fix = audit every code path that clears /var/lib/godo/restart_pending and ensure the SPA's polling/SSE channel reflects the change.
type: project
---

## What operator observed

During issue#3 HIL on news-pi01 (2026-05-01 KST, after PR #54 + #55 deploy + σ sweep work):

> "godo-tracker 재시작 필요 — B-LOCAL에서 'Restart godo-tracker' 버튼 클릭" 이 메시지는 페이지를 수동 새로고침 하기 전까지는 계속 떠있는다. 다른 작업할 때에도 그랬어.

The banner is the SPA's restart-pending indicator (driven by `GET /api/system/restart_pending` against the `/var/lib/godo/restart_pending` sentinel file). After tracker restart the sentinel SHOULD be cleared by the tracker itself on startup (`godo::config::clear_pending_flag`), and the SPA's polling should pick it up. Operator's observation: it doesn't, until the page is hard-reloaded.

## What PR #45 already covered

`fix/p4.5-restart-banner-refresh-after-action` (eleventh-session) refreshed the banner immediately after the operator clicks a System-tab service-restart button. That path works. The problem is now: the banner can be raised by paths the operator did NOT initiate from the SPA, AND the restart can happen via paths that don't trigger the SPA's post-action refresh hook.

## Suspected root cause

One of (or combination):

1. **Polling cadence too slow** — SPA polls `/api/system/restart_pending` only on a long interval; tracker restart happens before next poll, sentinel clears, but the SPA already has a stale "true" snapshot it never re-fetches.
2. **Banner state not subscribed to the polling result** — the Svelte component reads from the SSE stream or store but the store is updated only on action paths (PR #45 hook), not on idle polling.
3. **No SSE channel for restart-pending** — only HTTP polling, and the polling timer pauses when the tab loses focus / when the connection drops.
4. **Recalibrate-class cfg edits also raise the sentinel** unintentionally — invariant `apply.cpp` semantics: should restart-class only raise it, but a coding bug might raise it for recalibrate too.

## Workaround for now

Hard reload the SPA page (Ctrl+Shift+R). The polling re-initialises, sees sentinel cleared, banner disappears.

## Additional observation (2026-05-01 09:50+ KST during issue#3 σ sweep)

After one hard reload mid-session, subsequent restart-pending events dismissed cleanly without further reloads. Suggests the bug is a **first-load polling-lock that self-heals after one reset cycle** rather than a per-event leak. Frontend candidate: a guard flag (e.g., `bannerDismissed` boolean) that wasn't being re-armed on first mount. Investigate the SPA's banner state initialisation in particular (vs. the action-driven path PR #45 fixed).

## Self-healing hypothesis disproven (2026-05-01 11:50 KST after PR #56 deploy)

After PR #56 (frame fix) deploy + tracker restart, banner re-stuck. Operator: "또 자동으로 안 사라진다. 새로고침해야 사라짐." Each session-resume on a freshly-rebooted SPA tab requires a hard-reload before the banner clears. The "self-heals after one reset" pattern from earlier was a coincidence of the reload itself; the lock recurs whenever a fresh polling cycle is needed.

→ Real fix: SPA's polling/SSE guard flag on initial mount + after every service-action that mutates `restart_pending` server-side. Affects every tracker / webctl / godo-irq-pin restart, not just the operator-initiated one. Schedule as a small follow-up frontend PR after issue#3 σ work concludes.

## Real fix candidates

- Add a 1 Hz polling on `/api/system/restart_pending` with explicit store update (no caching).
- OR add an SSE stream for the sentinel state so it's push-based (matches `/api/last_pose/stream` precedent).
- OR audit every cfg key that triggers the sentinel and confirm only `ReloadClass::Restart` keys do.
- Verify the SSE/poll timer survives tab-focus changes.

## Priority

After issue#3 HIL completes (PR #54 merge or rework). Not a blocker — workaround works. Track as a separate small follow-up PR.
