---
name: Tracker-down banner action-driven refresh (issue#9)
description: SPA's App.svelte tracker-down banner clears within HTTP RTT after a tracker service action because ServiceCard / ServiceStatusCard action() now calls refreshMode() (mode.ts) alongside refreshRestartPending() (restartPending.ts). issue#9 made an emergent polling-phase-alignment behaviour explicit and deterministic.
type: project
---

## Origin observation (2026-05-01 KST)

Operator HIL after PR #59 deploy reported: "godo-tracker가
응답하지 않습니다" banner (App.svelte yellow tracker-down banner)
clears almost instantly on Start / Restart click — consistent
across multiple tries. Earlier sessions perceived it as taking
several seconds.

## Code-trace finding

PR #59 (`fix/issue-8-restart-pending-banner-poll-backstop`) added
1 Hz subscriber-counted polling to the `restartPending` store. It
does NOT touch `mode.trackerOk` — `mode.trackerOk` is written
exclusively by `mode.ts pollOnce` at the existing 1 Hz cadence.
Hence PR #59 had no direct mechanism to speed up the
App.svelte tracker-down banner.

Most plausible explanation for the observed speedup:

1. Hard-reload after PR #59 deploy realigned mode.ts polling phase
   to start at SPA mount. Subsequent action clicks land at an
   average ~500 ms before the next tick.
2. Foreground tab (no `setInterval` browser throttling).
3. webctl's `/api/health` is uncached — every call does a UDS
   round-trip to the tracker, so the response is fresh.
4. Prior expectation was probably confounded by background-tab
   throttling on an earlier session.

So the speedup was real-but-emergent, dependent on a
mount-time phase alignment that is fragile.

## Fix shipped (issue#9, PR #60)

Mirrored PR #45 / PR #59's action-driven refresh pattern for mode.ts:

- `mode.ts` exports `refreshMode()` — one-shot pollOnce + resets
  the polling interval phase so the NEXT tick fires
  `HEALTH_POLL_MS` after the refresh.
- `ServiceCard.svelte` + `ServiceStatusCard.svelte` action
  handlers call `void refreshMode()` alongside the existing
  `void refreshRestartPending()`.

**Resulting UX:**

- **Stop**: banner appears within HTTP RTT (no 1 s polling wait).
- **Restart**: catches the transient unreachable window during the
  bounce — gives the operator immediate "action took effect"
  feedback.
- **Start**: still bounded by tracker boot time. The immediate
  `/api/health` after `apiPost` returns typically still shows
  `tracker:"unreachable"` because tracker is mid-boot. The polling
  backstop catches the up-transition within 1 s.

## Caveat — what this does NOT fix

The Start-click case is still bounded by tracker boot latency
(map load + AMCL kernel build + mlock can take seconds). No
amount of polling-side acceleration changes that. If a future
HIL session surfaces this as a slow-feeling case, the fix would
be backend-side: an SSE channel for tracker liveness, OR a
short burst polling window (e.g. 200 ms for 5 s) on the SPA
side after a tracker action.

## Convention

Service-action handlers (Start / Stop / Restart for
godo-tracker, godo-webctl, godo-irq-pin) should call **both**
`refreshRestartPending()` AND `refreshMode()` after a successful
POST. This pattern is documented in the godo-frontend CODEBASE.md
change log; if a third tracker-state store is ever introduced,
its action-driven refresh hook should also land in the same
handler.
