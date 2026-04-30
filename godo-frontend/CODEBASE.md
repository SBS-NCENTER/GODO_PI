# godo-frontend — codebase map

## Scope

GODO 운영자 SPA. P0 페이지 4개 (DASH / MAP / AUTH / LOCAL) + 공통 shell
(TopBar / Sidebar / 테마). 백엔드는 PR-A에서 완성된 godo-webctl;
프론트는 HTTP/SSE wire만 알고 UDS는 모른다.

## Directory layout

```text
godo-frontend/
├─ package.json                       # pinned deps; npm scripts
├─ vite.config.ts                     # svelte plugin + dev proxy + path aliases
├─ tsconfig.json                      # strict, $lib/$stores/$components
├─ svelte.config.js                   # vitePreprocess + runes mode
├─ eslint.config.js                   # flat config (ESLint 9)
├─ .prettierrc / .prettierignore
├─ index.html                         # SPA shell, favicon link
├─ public/
│   └─ favicon.svg                    # :D glyph (FRONT_DESIGN §3 G-Q3)
├─ /src
│   ├─ main.ts                        # mount(App, #app)
│   ├─ App.svelte                     # router shell + auth gate
│   ├─ routes.ts                      # path → component map
│   ├─ /lib                           # framework-free helpers (no Svelte)
│   │   ├─ constants.ts               # SPA-internal Tier-1
│   │   ├─ protocol.ts                # wire-shape mirror of godo-webctl/protocol.py
│   │   ├─ router.ts                  # 30-line hash-router (per N9)
│   │   ├─ api.ts                     # apiFetch/apiGet/apiPost/apiPatch
│   │   ├─ auth.ts                    # login/logout/refresh/getClaims
│   │   ├─ sse.ts                     # SSEClient (token-on-URL + visibility)
│   │   └─ format.ts                  # Korean-friendly time/distance formatters
│   ├─ /stores
│   │   ├─ auth.ts                    # Writable<AuthSession|null> + localStorage
│   │   ├─ lastPose.ts                # SSE-fed; polling fallback
│   │   ├─ mode.ts                    # /api/health polled @ 1 Hz
│   │   └─ theme.ts                   # 'light' | 'dark', persisted
│   ├─ /components
│   │   ├─ TopBar.svelte              # session info + theme toggle + logout
│   │   ├─ Sidebar.svelte             # nav; LOCAL row only on loopback host
│   │   ├─ ModeChip.svelte            # Idle | OneShot | Live
│   │   ├─ ServiceCard.svelte         # systemd service status + actions
│   │   ├─ PoseCanvas.svelte          # canvas overlay + pan/zoom/trail
│   │   └─ ConfirmDialog.svelte       # reused for reboot/shutdown
│   ├─ /routes
│   │   ├─ Dashboard.svelte           # B-DASH
│   │   ├─ Map.svelte                 # B-MAP
│   │   ├─ Login.svelte               # B-AUTH
│   │   ├─ Local.svelte               # B-LOCAL (loopback-gated)
│   │   ├─ System.svelte              # B-SYSTEM (anon-readable; admin-gated buttons)
│   │   ├─ Backup.svelte              # B-BACKUP (anon-readable; admin-gated restore)
│   │   └─ NotFound.svelte
│   └─ /styles
│       ├─ tokens.css                 # CSS variables (light/dark)
│       └─ global.css                 # base + layout + chip/button/card
└─ /tests
    ├─ /unit                          # vitest
    │   ├─ api.test.ts                # 9 cases
    │   ├─ auth.test.ts               # 11 cases
    │   └─ sse.test.ts                # 9 cases
    └─ /e2e                           # playwright
        ├─ playwright.config.ts
        ├─ _stub_server.py            # stdlib HTTP server, mirrors webctl wire
        ├─ login.spec.ts              # 3 cases
        ├─ dashboard.spec.ts          # 3 cases
        ├─ map.spec.ts                # 2 cases
        └─ local.spec.ts              # 3 cases
```

## Dependency graph

```text
constants.ts ◄──── protocol.ts ◄────┐
                                     │
              router.ts ◄─── api.ts ◄┤
                                     ├── stores/* ◄──── components/* ◄── routes/*
              auth.ts (lib) ◄────────┤
              sse.ts ◄───────────────┤
              format.ts ◄────────────┘
```

`stores/auth.ts` wires `lib/api.ts` via `configureAuth({ getToken,
onUnauthorized })` at module-init — that's the only back-edge from a
store into a lib, deliberate and one-way.

## Module responsibilities

| Module                           | Responsibility                                                                                                                                                                                                                          |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `lib/constants.ts`               | SPA-internal Tier-1. **Every numeric literal in `src/` MUST trace here, to `protocol.ts`, or to a local iteration bound.**                                                                                                              |
| `lib/protocol.ts`                | Wire-shape mirror of `godo-webctl/src/godo_webctl/protocol.py` — types, mode names, error codes, LAST_POSE_FIELDS order.                                                                                                                |
| `lib/router.ts`                  | 30-line hash-router. Emits `route` rune; `navigate(path)` updates `location.hash`.                                                                                                                                                      |
| `lib/api.ts`                     | `apiFetch` adds Bearer header from auth store; 401 → clearSession + nav `/login`; non-2xx → throws `ApiError`.                                                                                                                          |
| `lib/sse.ts`                     | `SSEClient` — token-on-URL (Q3), Page Visibility handbrake, expired-token guard before reconnect.                                                                                                                                       |
| `lib/auth.ts`                    | `login/logout/refresh/getClaims/isExpired`. Decode-only on token (server is the SSOT for trust).                                                                                                                                        |
| `lib/format.ts`                  | Korean-friendly formatters for topbar countdown + pose readouts.                                                                                                                                                                        |
| `stores/auth.ts`                 | Persisted `AuthSession`. Writes from outside limited to `setSession/clearSession`.                                                                                                                                                      |
| `stores/lastPose.ts`             | SSE-fed `LastPose`; refcounts subscribers; polling fallback when SSE drops.                                                                                                                                                             |
| `stores/mode.ts`                 | Polls `/api/health` at HEALTH_POLL_MS; supports `setModeOptimistic` after button clicks.                                                                                                                                                |
| `stores/theme.ts`                | Light/dark theme; persisted in localStorage; sets `data-theme` attribute on `<html>`.                                                                                                                                                   |
| `components/PoseCanvas.svelte`   | Canvas with pan/zoom/trail; world↔canvas conversion via `mapMetadata.resolution + .origin + .height`.                                                                                                                                  |
| `lib/mapYaml.ts`                 | Pure parser for ROS map_server YAML (`image`, `resolution`, `origin`, `negate`); throws `MapYamlParseError` on malformed input.                                                                                                         |
| `stores/mapMetadata.ts`          | Composes `parseMapYaml` + `/api/maps/<name>/dimensions` fetch; refetches on `mapImageUrl` change with AbortController-cancelled previous load.                                                                                          |
| `components/MapListPanel.svelte` | Track E (PR-C). Lists every map under `${GODO_WEBCTL_MAPS_DIR}`; admin-gated activate / delete actions; reuses `<ConfirmDialog/>` with the optional `secondaryAction` prop.                                                             |
| `stores/maps.ts`                 | Track E. `Writable<MapEntry[]>` + `refresh()` / `activate(name)` / `remove(name)`. No periodic polling — refresh on mount, post-activate, post-remove only.                                                                             |
| `routes/Config.svelte`           | PR-C. Owns the page-level `mode` / `pending` / `applyResults` / `isApplying` state machine; renders EDIT / Cancel / Apply button group + tracker-inactive banner; reuses `<ConfirmDialog/>` for Cancel-with-pending. See invariant (z). |
| `components/ConfigEditor.svelte` | PR-C. Dumb controlled table: schema/current/admin/mode/pending/applyResults/isApplying as props; emits edits via `setPending` callback. No store back-edge.                                                                             |
| `stores/config.ts`               | `refresh()` + legacy `set()` (deferred-deletion) + `applyBatch(pending)` (PR-C best-effort sequential PATCH + post-loop `refresh()`).                                                                                                   |
| `routes/*.svelte`                | Page composition only — no business logic; orchestrate via stores + lib calls.                                                                                                                                                          |

## Invariants

### (a) Token-on-URL for SSE (per Q3 user decision)

`EventSource` cannot send custom headers, so SSE auth happens via
`?token=…` query param. Backend `_extract_bearer` accepts the fallback;
backend uvicorn access-log strips `?token=…` from URL lines so the
token never lands in journald.

`SSEClient` is the SOLE place that builds an `?token=` URL — components
must NOT construct EventSource directly.

### (b) Loopback gate is two-layer

The B-LOCAL page checks `window.location.hostname` against
`LOCAL_HOSTNAMES = ['127.0.0.1', 'localhost', '::1']` BEFORE making any
`/api/local/*` calls. The backend separately enforces 403 via
`Depends(loopback_only)`. **Both gates must agree.** Adding `'192.168.x.y'`
to `LOCAL_HOSTNAMES` without changing the backend gate would expose
controls that the backend then rejects — bad UX. Adding to the backend
without the frontend would surface the page on hosts that can't actually
use it.

### (c) No business logic in components

`routes/*.svelte` and `components/*.svelte` orchestrate via store
subscriptions + lib calls. The wire shapes belong to `lib/protocol.ts`;
the fetch/SSE plumbing belongs to `lib/{api,sse}.ts`. A component that
constructs JSON request bodies inline or massages backend responses with
ad-hoc transforms is a code-review block.

### (d) CSS-variable-only theming

Light/dark toggle flips `data-theme` on `<html>`; every visual difference
is a CSS variable in `src/styles/tokens.css`. Components MUST NOT branch
on theme value — read variables and let the cascade decide.

The PoseCanvas exception: canvas drawing uses hex literals
(`MAP_TRAIL_COLOR`, `MAP_POSE_COLOR`) because canvas is rasterised and
doesn't see CSS variables. Documented in-file.

### (e) No magic numbers

Every numeric literal in `src/` resolves to one of:

- a named export in `lib/constants.ts`
- a wire-side mirror in `lib/protocol.ts`
- a local iteration bound (e.g. `for (let i = 0; i < trail.length; i++)`)
- a CSS variable (in `.css` files only — CSS is not subject to the rule)

Reviewer Mode-B will fail any literal that violates this. Numeric literals
in tests are exempt (test fixtures are intentional values).

### (f) Wire SSOT — `lib/protocol.ts` mirrors `godo-webctl/src/godo_webctl/protocol.py`

Hand-mirrored. Drift detection is by inspection during code review +
backend's own `tests/test_protocol.py` (which regex-pins the C++ side).
Adding a field to `LAST_POSE_FIELDS` requires the same diff in:

1. C++ `production/RPi5/src/uds/json_mini.cpp::format_ok_pose`
2. `godo-webctl/src/godo_webctl/protocol.py::LAST_POSE_FIELDS`
3. `godo-frontend/src/lib/protocol.ts::LAST_POSE_FIELDS`

The frontend e2e stub server's canned `_canned_pose()` should also be
updated to include the new field.

### (g) Token persistence + cross-tab sync

`AuthSession` lives in `localStorage` under key `STORAGE_KEY_TOKEN =
'godo:auth'`. The auth store reads on init and writes on every change.
Cross-tab synchronisation is NOT implemented in P0 — closing the original
tab's session does not clear other tabs until they next reload. Acceptable
for P0 (1-2 operators, single window typically).

### (h) Default light theme

Theme defaults to `'light'` when `localStorage` is empty. Per
FRONT_DESIGN §3 G-Q4 (user decision: 라이트 default + 회색 톤). The
toggle flips between `'light'` and `'dark'`; no system-preference
auto-detect because the device may be a kiosk display with no OS-level
theme signal.

### (i) Test surface — playwright runs on dev machines only (per N8)

Playwright Chromium binary download (~170 MB) is gated behind
`npm run test:e2e` and is intended for developer machines (Mac/Linux x86).
RPi 5 CI runs only `npm run test:unit` (vitest, ~30 cases) plus the
backend `uv run pytest` suite. The e2e suite uses the in-tree
`tests/e2e/_stub_server.py` (stdlib only) so no real RPi backend is
required to run them.

### (k) Map-name regex mirror (Track E, PR-C)

`MAPS_NAME_REGEX_PATTERN_STR` in `src/lib/protocol.ts` MUST equal the
backend `MAPS_NAME_REGEX.pattern` from
`godo-webctl/src/godo_webctl/constants.py`. The frontend uses the
pattern for client-side `activate(name)` / `remove(name)`
short-circuiting (so a typo never hits the network). The backend
re-validates inside `maps.validate_name` (defence-in-depth — same
regex, different process).

Drift detection: by inspection during code review, plus the backend's
`tests/test_protocol.py::test_maps_name_regex_pattern_str_mirrors_constants`
which pins the backend mirror against `constants.py`. The frontend
mirror cannot be auto-checked at test time; the inspection contract is
that any change to the regex updates BOTH files in the same commit.

### (l) `<ConfirmDialog/>` accepts an optional `secondaryAction` (Track E, PR-C)

`components/ConfirmDialog.svelte` was extended (NOT replaced) with
optional props:

- `secondaryAction?: { label, handler } | null` — when set, renders a
  third button between cancel and confirm. The dialog still renders
  cancel + primary as before; reuses the same theming / a11y patterns.
- `showPrimary?: boolean` — when `false`, the primary (`onConfirm`)
  button is hidden and replaced with a tooltip placeholder. Used by
  `MapListPanel` to hide the "godo-tracker 재시작" button on
  non-loopback hostnames per Mode-A M4.
- `primaryHiddenTooltip?: string` — hover text for the placeholder.

A new `MultiActionDialog` was considered and rejected: the existing
component is small enough that two more optional props are cheaper
than a parallel implementation that would have to keep the same
theming + a11y discipline.

### (m) Track D — scan-overlay freshness uses arrival-wall-clock (Mode-A M2)

The `LastScan` wire body carries two clocks:

- `published_mono_ns` — tracker `CLOCK_MONOTONIC` ns at publish; an
  ORDERING primitive only.
- `_arrival_ms` — client-side, set inside `stores/lastScan.ts` at
  `Date.now()`-time of SSE frame arrival; never on the wire.

The freshness gate (`PoseCanvas.svelte::redraw`, `ScanToggle.svelte`)
computes `Date.now() - lastScan._arrival_ms` against
`MAP_SCAN_FRESHNESS_MS = 1000`. Subtracting `published_mono_ns`
directly from `Date.now()` would mix tracker monotonic time and
browser wall-clock — meaningless. The store stamps `_arrival_ms` on
every frame BEFORE pushing to subscribers, so the gate is computed in
a single clock domain.

Pinned by:

- `tests/unit/lastScan.test.ts::stamps _arrival_ms on every received frame (Mode-A M2)`,
- `tests/unit/poseCanvasFreshness.test.ts` (data-scan-fresh attribute
  flips when fake timers advance past the freshness window).

### (n) Track D — SPA does the polar→Cartesian transform; uses the SCAN's anchor pose (Mode-A TM5)

The server (`godo_tracker_rt`) emits raw polar (`angles_deg` +
`ranges_m` in the LiDAR frame) plus the anchor pose
(`pose_x_m / pose_y_m / pose_yaw_deg`) baked into the SAME LastScan
frame. The SPA does the world-frame transform using the SCAN's own
anchor — NOT the parallel `lastPose` store.

Reasoning: the AMCL pose at the moment the cold writer processed THIS
scan is exactly correct for THIS scan; using a separately-fetched
pose would re-introduce the SSE-skew the brief explicitly avoids.
The transform lives in `lib/scanTransform.ts::projectScanToWorld` so
unit tests can exercise the math without mounting the full
PoseCanvas component.

Mode-A M3 fold: `projectScanToWorld` returns an empty array unless
`scan.valid === 1 && scan.pose_valid === 1`. `pose_valid === 0`
means the AMCL run that produced this scan did not converge; the
anchor coordinates are undefined zeros, and rendering them would
mislead the operator.

Pinned by `tests/unit/poseCanvasScanLayer.test.ts` — TB2's three
non-trivial yaw cases (yaw=90°+beam=0°; yaw=45°+beam=0° to catch
x/y-swap; yaw=0°+beam=90° to catch yaw-vs-beam-angle confusion) +
gating tests + the TB1-equivalent positional integrity sweep.

### (o) Track D — `lastScan` SSE is gated on the `scanOverlay` toggle

The `lastScan` store opens its underlying `SSEClient` ONLY when
the `scanOverlay` store is `true` AND there is at least one
subscriber. The gating lives inside `stores/lastScan.ts`, not in
`Map.svelte`. Operators who never flip the toggle on never trigger
the tracker UDS `get_last_scan` round-trip; the cold writer's seqlock
publish is unaffected (Track D's "0 hot-path impact" promise extended
to the webctl layer).

`scanOverlay` persists in `sessionStorage` (NOT `localStorage`, per
Q-OQ-D2): same-tab reload preserves the operator's choice; new tab /
new operator session defaults OFF. The overlay generates ~30-60 KB/s
of WAN traffic at 5 Hz; OFF-by-default for any new session is the
defensive baseline.

Pinned by:

- `tests/unit/lastScan.test.ts::does not start SSE while overlay is off`,
- `tests/unit/lastScan.test.ts::starts SSE when overlay flips to on`,
- `tests/unit/lastScan.test.ts::stops SSE when overlay flips back to off`,
- `tests/unit/scanOverlay.test.ts` (4 cases — default off, persist,
  restore, toggle round-trip),
- `tests/e2e/map.spec.ts::scan toggle state persists through same-tab reload`.

### (p) PR-DIAG — Diagnostics store opens SSE only when subscribers exist

The `diag` store (`stores/diag.ts`) opens its underlying `SSEClient`
ONLY when at least one subscriber is registered (refcounted via
`subscribeDiag(fn)` → returns unsub closure). The gating lives inside
the store, NOT in `routes/Diagnostics.svelte`. A page that doesn't
mount the Diagnostics route never triggers `/api/diag/stream`; multiple
mounts share one SSE.

`_arrival_ms` is stamped on every frame on receipt (Mode-A M2 +
PR-DIAG N4 fold extension). The freshness gate in `Diagnostics.svelte`
reads `Date.now() - frame._arrival_ms`, NOT `published_mono_ns`
deltas (clock-domain mismatch — the C++ tracker's CLOCK_MONOTONIC and
the webctl-side `time.monotonic_ns()` are SEPARATE clock domains and
must never be compared).

Pinned by:

- `tests/unit/diag.test.ts::does not open SSE when there are no subscribers`,
- `tests/unit/diag.test.ts::sse opens on first subscribe and closes on last unsubscribe`,
- `tests/unit/diag.test.ts::stamps _arrival_ms on every received frame`.

### (q) PR-DIAG — JournalTail allow-list mirrors webctl

`components/JournalTail.svelte` hardcodes the allow-list dropdown
options as `['godo-tracker', 'godo-webctl', 'godo-irq-pin']` —
mirroring `godo_webctl.services::ALLOWED_SERVICES`. Drift detected by
inspection during code review (per OQ-DIAG-3). The webctl-side rejects
a non-listed unit anyway (HTTP 404 `unknown_service`) so a SPA-side
drift surfaces as a sad-UX 404, not a security hole.

`n` input is clamped client-side to `LOGS_TAIL_MAX_N_MIRROR = 500`;
the server's Pydantic `Field(le=...)` is the authoritative cap.

### (u) `MapMaskCanvas` is the sole owner of mask state (Track B-MAPEDIT)

The brush-mask `Uint8ClampedArray` lives inside
`components/MapMaskCanvas.svelte` instance state. `routes/MapEdit.svelte`
orchestrates (brush radius slider, Apply / Discard buttons, error
banner) and obtains the mask via `getMaskPng() -> Promise<Blob>` only
at submit time. No store, no global, no parent-side mirror.

`devicePixelRatio` is intentionally NOT baked into the mask coordinate
system (R2 mitigation + T4 fold pin). Pointer events are translated
from CSS coords to LOGICAL mask cells via the canvas's
`getBoundingClientRect()`:

```ts
lx = floor(((ev.clientX - rect.left) * width) / rect.width);
ly = floor(((ev.clientY - rect.top) * height) / rect.height);
```

So a click at CSS (50, 50) under `devicePixelRatio = 2` lands at
logical (50, 50), NOT (100, 100). The CSS box (`rect.width/height`)
takes the visible pixels into account; multiplying by the LOGICAL
`width/height` gives the canonical mask index regardless of zoom or
DPR.

PR β clarification: the brush layer is now visually composed _on top
of_ `<MapUnderlay/>` via `position: absolute; inset: 0;` on a wrapping
div managed by `MapEdit.svelte`. The mask buffer remains
`<MapMaskCanvas/>`-owned (sole owner discipline preserved). When a
`viewport` prop is supplied, the pointer-coord conversion ALSO inverts
the viewport's zoom + pan around the mask box center before mapping
CSS → logical. At zoom = 1, pan = 0 the math collapses to the original
identity form so the T4 fold's DPR-coord pin survives byte-identical.
The mask buffer is sized to logical PGM dimensions regardless of
viewport zoom; CSS scaling handles the visual zoom (the mask layer's
`image-rendering: pixelated` keeps tiles crisp at any ratio).

Apply path (mirrors webctl invariant (aa) on the wire side):

1. SPA calls `getMaskPng()` which builds a fresh canvas at the
   logical size, populates each cell with greyscale 255 / 0, and
   resolves a `Blob` from `canvas.toBlob('image/png')`.
2. SPA POSTs to `/api/map/edit` via `postMapEdit(blob)` —
   `FormData` body with a single `mask` part.
3. On 200: a success banner renders, `restartPending` store is
   refreshed (the global `RestartPendingBanner` immediately reflects
   the flag), and `navigate('/map')` fires after
   `MAP_EDIT_REDIRECT_DELAY_MS = 3000 ms`.
4. On 4xx: the response's `err` code surfaces inline; brush state
   is NOT cleared (operator can retry without redrawing).

The Apply button is `disabled = busy || role !== 'admin'` so anon
viewers see the page in read-only mode. The backend separately
returns 401 on the POST (defence-in-depth).

Restart UX cross-reference: edits require a `godo-tracker` restart
to take effect (the tracker reads PGM at boot only — Phase 4.5
deferred-indefinitely hot-reload decision per FRONT_DESIGN §4.2
2026-04-29 supersession block). Operators restart via either
`/local` (loopback-admin kiosk path) or `/system` (admin-non-loopback,
PR #27 service-controls). Per
`.claude/memory/project_godo_service_management_model.md`, the SPA is
the SOLE start/stop/restart UI; messaging in the success banner
points there, NOT at raw `systemctl`.

Bundle-size note: this PR adds ~+2.4 KB gzipped JS + ~+0.2 KB CSS
(measured 2026-04-30 11:30 KST against the immediate-pre-PR baseline);
under the planner's +5 KB ceiling.

Pinned by `tests/unit/mapEdit.test.ts` (6 cases — DPR coord pin (T4
fold), clear() reset, Apply FormData shape, anon disabled, success
redirect, error banner) + `tests/e2e/mapEdit.spec.ts` (3 cases — anon
view + admin happy path + viewer cannot apply).

### (t) Track B-SYSTEM PR-2 — services panel polls `/api/system/services` at 1 Hz, no SSE

`routes/System.svelte` adds a 5th panel rendering one
`<ServiceStatusCard/>` per allow-listed GODO service. Polls
`/api/system/services` via `setInterval(SYSTEM_SERVICES_POLL_MS = 1000)`
through `stores/systemServices.ts` (refcounted; opens on first
subscribe, closes on last). The timer is captured in `onMount` and
cleared in `onDestroy` (T5 fold pin: `vi.getTimerCount() === 0` after
the last unsub). 1 Hz × 1 s backend cache TTL is the matched cadence;
an SSE was rejected because operator UX gains nothing over the polled
shape.

Chip-class is single-sourced in `$lib/serviceStatus.ts` (1-export
module: `STATUS_TO_CHIP` map + `statusChipClass(s)`) and re-used by
both `ServiceCard` (loopback-admin actions on `/local`) and
`ServiceStatusCard` (read-only-or-admin twin on `/system`) so the two
cannot drift.

Both cards render `body.detail` (Korean) on a 409
`service_starting`/`service_stopping` response in their existing
`lastError` slot, with auto-dismiss after
`SERVICE_TRANSITION_TOAST_TTL_MS = 4000`. The dismiss timer is cleared
in `onDestroy`. ServiceStatusCard ALSO shows admin Start/Stop/Restart
buttons gated by `$isAdmin`; the click POSTs to
`apiSystemServiceAction(name, action)` which builds the
`/api/system/service/<name>/<action>` path. Anon viewers see the
read-only card with no buttons.

Stale-banner: when `Date.now() - svcState._arrival_ms >
SYSTEM_SERVICES_STALE_MS = 3000`, the panel header shows a "데이터
갱신 지연" inline tag (mirror of the Diagnostics page stale-banner
pattern; same `renderTick` heartbeat re-evaluation).

Pinned by `tests/unit/system.test.ts` (services panel renders + admin
button visibility + anon hides buttons + clicking restart POSTs to the
right path), `tests/unit/systemServices.test.ts` (T4 fold: exactly 4
fetches in 3500 ms; T5 fold: timer count drops to 0 on unmount),
`tests/unit/serviceStatus.test.ts` (chip-class drift catch),
`tests/unit/format.test.ts` (formatUptimeKo + formatBytesBinaryShort
corpus with S4 fold "51 MiB" pin), and `tests/e2e/system.spec.ts`
(3 new playwright cases: services panel renders, env collapse reveals
mixed redacted/non-redacted KEYs per T6 fold, admin restart click
under stub 409 surfaces Korean detail toast).

### (y) Track B-SYSTEM PR-B — System page sub-tab pattern + PR-B SSE stores

`routes/System.svelte` switches from a single-panel-list layout to a
sub-tab layout with three keys: `overview` (default — wraps the
original PR-SYSTEM panels), `processes`, `extended`. The sub-tab key
is held in component-local `$state` (`activeSubtab`); the URL doesn't
reflect it.

Discipline rationale:

1. **Component-local state, intentional reset on route change**
   (Final fold S3): operator clicks `/map` then comes back to
   `/system`, the sub-tab returns to `overview` and the search
   filter clears. Persisting via URL hash is a follow-up if
   operators request it (Risk R10 deferred).
2. **No new dependency** for the popover primitive (Final fold O2):
   the `i 도움말` block in `<ProcessTable/>` is a vanilla HTML5
   `<details><summary>` disclosure — click-to-toggle, NOT hover.
3. **Filters are CLIENT-SIDE only** (Mode-A S1 fold): the SSE URL
   carries only the `token` query param. A future writer adding
   `?filter=foo` to the SSE wire fails the `processes.test.ts`
   "SSE URL has only the token param" pin.
4. **Refcounted SSE per stream** (mirror of invariant (p)):
   `subscribeProcesses` / `subscribeResourcesExtended` share one
   `EventSource` across multiple subscribers; the underlying SSE
   closes only when the last subscriber unsubscribes. Pinned by
   `processes.test.ts::shares one SSE across multiple subscribers
(refcounted)` and the equivalent in `resourcesExtended.test.ts`.
5. **`_arrival_ms` stamped per frame** (Mode-A M6, mirror of
   invariant (m)): both PR-B stores stamp `Date.now()` on every
   received SSE frame so freshness gates use arrival-wall-clock,
   never `published_mono_ns` across the C++/webctl boundary.
6. **Typography over background shading** (Final fold §5 + Mode-A
   M5 + O1): managed-category process names render in
   `font-weight: bold` + `color: var(--color-status-warn)` — the
   existing token, no new colors. Duplicate rows get a
   `border-left: var(--border-width-emphasis) solid var(--color-status-err)`
   on the name cell only. New token: `--border-width-emphasis: 3px`
   in `tokens.css` (the only new token; reused colors from existing
   `--color-status-{warn,err}`).
7. **No raw hex literals** in `ProcessTable.svelte` or
   `ResourceBars.svelte` (per invariant (d)): every color references
   `var(--color-*)` from `tokens.css`. Verified by inspection
   during code review; mirror of invariant (e) "no magic numbers"
   discipline applied to colors.
8. **Cross-language SSOT** mirrored in `lib/protocol.ts`:
   `PROCESS_FIELDS` (10 fields), `EXTENDED_RESOURCES_FIELDS`
   (6 fields, GPU absent), `MANAGED_PROCESS_NAMES`,
   `GODO_PROCESS_NAMES`. Drift detected by inspection per
   the existing wire-mirror discipline.

Pinned by:

- `tests/unit/processes.test.ts` (6 cases — SSE refcount,
  `_arrival_ms` stamping, duplicate-alert propagation, token-only
  URL, malformed-payload drop).
- `tests/unit/resourcesExtended.test.ts` (4 cases — refcount,
  `_arrival_ms`, null GPU-style fields, malformed-payload drop).
- `tests/unit/processTable.test.ts` (8 cases — sort order, text
  search, GODO-only toggle, duplicate banner + per-row marker,
  info popover bullets, managed-category class, count summary).
- `tests/unit/system.test.ts` (existing 11 cases continue to pass —
  the sub-tab wrapping defaults to `overview` so existing panels
  still render on mount).

### (j) Router is home-grown (per N9)

The plan called for `svelte-spa-router@~4`. After install the package's
own description still reads "Router for SPAs using Svelte 4". Rather than
ship a router that explicitly targets the prior major version, we wrote
a 30-line hash-router (`src/lib/router.ts`). The trade-off: no nested
routes, no params (e.g. `/users/:id`), no transition hooks. None of these
are needed in P0 — every route is a static path.

If a future page needs URL params, replace `matchRoute` with a
trie/prefix matcher in the same file. The `route` rune + `navigate(path)`
contract is what the rest of the SPA depends on; keep that stable.

## Build flow

```text
src/main.ts  →  vite (esbuild)  →  Rollup tree-shake  →  dist/
                  │
                  ├─ Svelte plugin (svelte 5 compiler in runes mode)
                  ├─ TS compiler (strict)
                  └─ CSS transform (autoprefixer not enabled — modern targets only)
```

Bundle target: `es2022` (Chromium ≥ 110, Safari ≥ 16). Source maps
disabled in production build (smaller dist; debug builds use
`--sourcemap`). Chunk size warning limit set to 250 KB.

## Dev proxy

`vite.config.ts` proxies `/api → http://127.0.0.1:8080` in dev mode only.
Production has no proxy — godo-webctl serves both `/` (SPA) and `/api/*`
from the same origin (port 8080), so CORS is never invoked.

## Path aliases

`tsconfig.json` `paths` + `vite.config.ts` `resolve.alias`:

| Alias           | Resolves to        |
| --------------- | ------------------ |
| `$lib/*`        | `src/lib/*`        |
| `$stores/*`     | `src/stores/*`     |
| `$components/*` | `src/components/*` |

These exist to make module imports source-of-truth-explicit (e.g.
`import { apiGet } from '$lib/api'` cannot accidentally resolve to a
node_modules package called `lib`).

## Theme variable map (excerpt)

| Variable             | Light value | Dark value | Used by                   |
| -------------------- | ----------- | ---------- | ------------------------- |
| `--color-bg`         | `#f5f5f7`   | `#1d1d20`  | `body`                    |
| `--color-bg-elev`    | `#ffffff`   | `#28282b`  | `.card`, topbar           |
| `--color-text`       | `#2c2c30`   | `#e6e6e9`  | global                    |
| `--color-accent`     | `#1565c0`   | `#4a8be0`  | primary buttons, link     |
| `--color-status-ok`  | `#2e7d32`   | `#66bb6a`  | active chip               |
| `--color-status-err` | `#c62828`   | `#ef5350`  | error chip, danger button |

Full set in `src/styles/tokens.css`.

## Stub server contract

`tests/e2e/_stub_server.py` mirrors the wire shapes of
`godo-webctl/src/godo_webctl/app.py` exactly. **When adding a new
endpoint to the backend, update the stub in the same PR.** Otherwise the
e2e suite goes green on outdated wire shapes and the SPA breaks against
the real backend.

The stub serves both:

- `/api/*` — canned JSON / SSE responses
- `/` and everything else — serves `dist/index.html` (the built SPA)

so a single stub process is enough to drive playwright. No vite
preview proxy needed.

## Change log

### 2026-04-30 20:30 KST — PR β shared map viewport + zoom UX uniform + Map Edit LiDAR overlay

Operator HIL request 2026-04-30 KST: zoom UX must be uniform across
all map-showing tabs (top-left (+/−) buttons + numeric input — no
mouse wheel); min-zoom captured once at first map load; LiDAR overlay
shared between `/map` and `/map-edit` so the operator can verify
scan-vs-map alignment in real time during edits. Operator-locked rules
in `.claude/memory/project_map_viewport_zoom_rules.md`.

#### Added

- `src/components/MapUnderlay.svelte` — Sole owner of the shared PGM
  bitmap fetch + canvas mount + LiDAR scan render path. Both `/map`
  and `/map-edit` compose this component. Layer paint order is FIXED:
  bitmap → scan dots → `ondraw` parent hook. Imperative `worldToCanvas`
  / `canvasToWorld` API exposed via `bind:this` as a thin passthrough
  to the viewport's pure helpers (Mode-A M4).
- `src/components/MapZoomControls.svelte` — Top-left absolute-positioned
  panel with (+) and (−) buttons + `<input type="text" inputmode="decimal">`.
  Both Enter and blur commit triggers (Mode-A N3); locale-comma
  rejected with Korean copy `쉼표(,) 대신 점(.)을 사용하세요. 예: 150`
  (Mode-A N1).
- `src/lib/mapViewport.svelte.ts` — Per-instance rune-state factory
  (`createMapViewport()`) + the full pure-helper set (`clampZoom`,
  `applyZoomStep`, `parsePercent`, `panClamp`, `worldToCanvas`,
  `canvasToWorld`, `canvasToImagePixel`, `imagePixelToCanvas`). Single
  math SSOT (Mode-A M4 — no closure leaks; the factory wraps the pure
  helpers with `$state`). `setMapDims` is a one-shot at the FACTORY
  level (Mode-A M5 — `_dimsCaptured` private boolean in the closure).
- `src/lib/constants.ts` — Added `MAP_ZOOM_STEP = 1.25` (rich docstring
  documenting alternatives + operator-experience trade-off — Mode-A S3),
  `MAP_ZOOM_PERCENT_MIN_DEFAULT`, `MAP_ZOOM_PERCENT_MAX = 1000`,
  `MAP_ZOOM_PERCENT_DEFAULT`, `MAP_ZOOM_PERCENT_DECIMAL_DISPLAY`,
  `MAP_PAN_OVERSCAN_PX = 100`.
- `tests/unit/mapViewport.test.ts` — 34 vitest cases (pure helpers +
  factory state + round-trip identity ×3 + parsePercent boundary
  cases + setMapDims one-shot + null→A→null→B map-switch survival +
  no `resize` listener registered).
- `tests/unit/mapZoomControls.test.ts` — 11 vitest cases (both Enter
  AND blur commit triggers + locale-comma rejection + soft-clamp on
  out-of-range + Mode-A T3 chain integration).
- `tests/unit/mapUnderlayScan.test.ts` — 5 vitest cases (Rule 3 + Rule
  4 single scan-render code path + Mode-A S1 layer paint order).
- `tests/unit/mapViewportNoWheelImports.test.ts` — 3 vitest cases
  (Mode-A T5 wheel-removal structural pin).

#### Changed

- `src/components/PoseCanvas.svelte` — Refactored from a 500-LOC
  zoom/pan/scan/pose owner to a thin ~140-LOC wrapper that composes
  `<MapUnderlay/>` and supplies a `drawPoseLayer` hook for the trail +
  pose dot. Wheel listener DELETED. Selectors `data-testid="pose-canvas-wrap"`
  and `data-testid="pose-canvas"` preserved (the underlay's canvas is
  retargeted via `canvasTestId` prop).
- `src/components/MapMaskCanvas.svelte` — Accepts an optional
  `viewport` prop (Mode-A M4 — drop-in for the never-shipped
  `underlayWorldToCanvas` plan-draft prop). Pointer-coord conversion
  uses the viewport to invert zoom + pan around the mask box center;
  collapses to identity at zoom = 1, pan = 0 (T4 fold survives
  byte-identical). Mask buffer remains sole-owned (invariant `(u)`).
- `src/routes/Map.svelte` — Creates a per-route `mapViewport` instance
  via `createMapViewport()`, shared with `<PoseCanvas/>` and
  `<MapZoomControls/>`. New `.canvas-stack` wrapper hosts the
  absolute-positioned zoom controls.
- `src/routes/MapEdit.svelte` — Composes `<MapUnderlay/>` (showing live
  scan overlay) + `<MapMaskCanvas/>` (visually layered on top) +
  `<MapZoomControls/>` + `<ScanToggle/>`. Subscribes to `lastScan` +
  `scanOverlay` mirror of `/map` so operators verify scan-vs-map
  alignment during edits (Rule 3).
- `src/lib/constants.ts` — DELETED `MAP_WHEEL_ZOOM_FACTOR` (structural
  witness that wheel zoom is gone).
- `tests/unit/mapEdit.test.ts` — Canvas shim extended to cover
  MapUnderlay's redraw surface (clearRect / arc / fill / stroke /
  moveTo / lineTo / fillStyle setter / etc.).
- `tests/e2e/map.spec.ts` — REPLACED 'wheel-zoom survives' case with
  '(+) zoom button survives' (same intent, new mechanism). Added 2
  NEW cases: `/map` zoom-button + `/map-edit` zoom-button-with-scan-
  overlay (Mode-A M2 selector fix — `data-testid="scan-toggle-btn"`
  not `scan-overlay-toggle`).

#### Removed

- `MAP_WHEEL_ZOOM_FACTOR` constant (structural witness that wheel zoom
  is gone). A writer reintroducing it without first amending Rule 1 in
  `.claude/memory/project_map_viewport_zoom_rules.md` AND updating
  invariant `(ab)` fails Mode-A Critical (pinned by
  `tests/unit/mapViewportNoWheelImports.test.ts`).

#### Tests

- vitest: 220 → 273 (+53 new = 34 mapViewport + 11 mapZoomControls +
  5 mapUnderlayScan + 3 mapViewportNoWheelImports).
- playwright: 38/44 → 40/46 (+2 NEW + 1 REPLACED). The pre-existing 6
  baseline flakes (config × 4, map.spec hover, system.spec restart-409)
  unchanged per Mode-A R7 — out of scope; do not regress, do not fix.
- `npm run lint` clean on PR paths (5 pre-existing prettier warnings
  in unrelated files unchanged from main).
- `npm run build` clean. Bundle delta: JS 118.02 → 123.87 kB raw,
  **42.76 → 44.85 kB gzipped (+2.09 kB)**; CSS 25.69 → 27.14 kB raw,
  5.06 → 5.30 kB gzipped (+0.24 kB). Net JS+CSS gzipped: **+2.33 kB**.
  Within the +5 kB ceiling documented in PR #43.

#### Mode-A folds applied

- M1 panClamp two-case spec (Q7 added) + 12b sibling test.
- M2 e2e selector fix (`scan-toggle-btn` not `scan-overlay-toggle`) +
  greppable-selector process pin.
- M3 wheel-zoom rollback gated on operator amendment to Rule 1 +
  invariant `(ab)` clause.
- M4 single math SSOT (`mapViewport.svelte.ts`); `MapMaskCanvas`
  consumes `viewport` directly; round-trip identity tests at zoom ∈
  {0.5, 1.0, 2.0}.
- M5 `setMapDims` factory-internal idempotency (`_dimsCaptured` in
  closure, not in caller); test 10b survives null→A→null→B.
- S1 layer paint order pinned via canvas-call-order test.
- S2 brush-coord parametrized over zoom × DPR (T4 fold survives
  byte-identical at zoom = 1, pan = 0).
- S3 `MAP_ZOOM_STEP = 1.25` rich docstring; tests assert exact value.
- S4 `MAP_DEFAULT_ZOOM` / `MAP_MIN_ZOOM` / `MAP_MAX_ZOOM` kept (no
  rename — drive-by avoidance); documented as internal-only.
- S5 bundle-size MEASURED (above).
- S6 freshness gate continues to be pinned at the new sole-owner site
  via existing `poseCanvasFreshness.test.ts` (mounts the pose-canvas
  wrapper which now wraps MapUnderlay; the gate runs at the new site).
- T1 `_resetLastScanForTests()` in `beforeEach` for the shared scan
  store.
- T2 parsePercent boundaries (empty/Infinity/-50/100.5/0).
- T3 chain integration ((+) (+) [type 200 Enter] (−)).
- T4 synchronous-emit-on-subscribe captures dims at mount.
- T5 wheel-zoom-removal mechanical pins (3 cases).
- N1 Korean copy for validation banners.
- N2 per-instance rationale documented in invariant `(ab)`.
- N3 BOTH onchange + onkeydown Enter commit triggers.

#### Total frontend test count

vitest: 273; playwright: 40/46 passing (40 if you count the 6
baseline flakes as not-this-PR's-problem; 46 total).

### 2026-04-30 12:50 KST — Map Edit moved into Map page as a sub-tab (operator HIL request)

Operator HIL request 2026-04-30 12:30 KST: move the Map Edit menu from a top-level sidebar entry to a sub-tab inside the Map page, mirroring the System tab's Processes / Extended resources sub-tab idiom (PR-B).

#### Changed

- `src/routes/Map.svelte` — Hosts the Edit sub-tab. Reads `route.path` to derive `activeSubtab`: `/map` → Overview, `/map-edit` → Edit. Sub-tab clicks call `navigate('/map' | '/map-edit')` so the URL stays in sync (refresh + browser back-button preserve view; bookmarks to `/map-edit` keep working). Sub-tab styling cloned verbatim from `System.svelte` (consistent visual idiom across the SPA). Overview content unchanged from prior `Map.svelte` body; Edit content delegates to `<MapEdit />`.
- `src/routes/MapEdit.svelte` — Removed top-level breadcrumb + `<h2>Map Edit</h2>` (now provided by the parent `Map.svelte` outer wrapper). The `data-testid="map-edit-page"` container is preserved so existing e2e + unit tests anchor unchanged. `RestartPendingBanner` stays inside the editor body. The post-Apply `navigate('/map')` redirect is unchanged — operator lands on Overview after a successful edit.
- `src/routes.ts` — `/map-edit` now mounts `Map` (was `MapEdit`). Inline comment explains why `MapEdit` is no longer top-level. The `MapEdit` import + route entry are gone from this file; the component is imported by `Map.svelte` instead.
- `src/components/Sidebar.svelte` — `Map Edit` nav row removed. Only the `Map` row appears in the sidebar; operators reach the editor via the Map page's Edit sub-tab.
- `src/lib/constants.ts` — Added `MAP_SUBTAB_OVERVIEW = 'overview'`, `MAP_SUBTAB_EDIT = 'edit'`. Comment notes URL-backed semantics (unlike System.svelte's component-local sub-tab state).

#### Why URL-backed sub-tabs (Map) but component-local (System)?

System's three sub-tabs are session-scoped views (Processes / Extended resources are SSE streams the operator toggles for monitoring); deep-linking to a specific sub-tab would surprise more than help. Map's Edit sub-tab is destination-scoped — operators receive `/map-edit` URLs in chat, e2e specs hit it directly, and the post-Apply redirect to `/map` is part of the editor contract. URL-backed makes refresh + back-button + external links all work without state-restoration code. The pattern split is intentional, not an oversight.

#### Tests + LOC

- All 204 vitest cases pass unchanged (existing `tests/unit/mapEdit.test.ts` mounts `MapEdit` directly, so the refactor doesn't perturb it).
- E2E `tests/e2e/mapEdit.spec.ts` keeps working: `/#/map-edit` → router resolves to `Map` → Map auto-selects Edit sub-tab → MapEdit renders with the same `data-testid="map-edit-page"` anchor.
- Bundle delta: JS 111.32 → 112.13 KB raw (+0.81 KB), gzip 40.53 → 40.80 KB (+0.27 KB).

### 2026-04-30 11:30 KST — Track B-MAPEDIT (frontend) — Map editor + restart-required

#### Added

- `src/routes/MapEdit.svelte` — `/map-edit` page. Renders the active
  map underlay + brush surface + Apply / Discard controls + restart-
  pending banner. Apply path: build PNG from `MapMaskCanvas.getMaskPng()`,
  POST `/api/map/edit` (multipart), refresh `restartPending` store,
  navigate to `/map` after `MAP_EDIT_REDIRECT_DELAY_MS = 3000 ms`.
  Anon viewers see the page; the Apply button is disabled.
- `src/components/MapMaskCanvas.svelte` — Brush surface. Owns the mask
  `Uint8ClampedArray` sized to PGM logical dimensions. Pointer events
  paint a circular kernel; CSS coords are mapped to LOGICAL mask
  coords via `getBoundingClientRect()` so `devicePixelRatio` never
  bleeds into the mask index space (T4 fold). Exports `getMaskPng()`
  and `clear()` to the parent route. SOLE owner of mask state per
  invariant (u).
- `src/routes.ts` — `/map-edit` → `MapEdit` route entry.
- `src/components/Sidebar.svelte` — `Map Edit` nav row (visible to all
  roles; Apply gating happens at the input level).
- `src/lib/protocol.ts` — `EditResponse` interface +
  `ERR_MASK_SHAPE_MISMATCH`, `ERR_MASK_TOO_LARGE`, `ERR_MASK_DECODE_FAILED`,
  `ERR_EDIT_FAILED`, `ERR_ACTIVE_MAP_MISSING` constants. Mirror of the
  webctl-side `protocol.py` additions.
- `src/lib/constants.ts` — `BRUSH_RADIUS_PX_MIN/MAX/DEFAULT` (5/100/15),
  `MASK_PNG_MAX_BYTES = 4_194_304`, `MAP_EDIT_REDIRECT_DELAY_MS = 3000`.
- `src/lib/api.ts::postMapEdit(maskBlob, init?)` — multipart helper
  that wraps a `Blob` into `FormData` and POSTs to `/api/map/edit`.
  Distinct from `apiPost` (which JSON-encodes its body).
- `tests/unit/mapEdit.test.ts` — 6 vitest cases: T4 DPR-coord pin,
  `clear()` reset, Apply FormData shape, anon disabled, success
  redirect, error inline.
- `tests/e2e/mapEdit.spec.ts` — 3 playwright cases: anon page, admin
  happy path with restart-pending banner, viewer cannot apply.
- `tests/e2e/_stub_server.py` — `_h_map_edit` handler. On admin
  success, flips `RESTART_PENDING_FLAG` to True so subsequent
  `/api/system/restart_pending` GETs return `{pending: true}`.

#### Changed

- Invariant (u) added (see above).

#### Removed

- (none)

#### Tests

- 197 → 203 vitest (+6 from this PR). All 29 unit-test files green.
- e2e is dev-only per invariant (i); 3 new playwright cases added but
  not run in this RPi 5 writer session (project policy).
- `npm run lint` clean on PR paths (5 pre-existing prettier warnings
  in unrelated files unchanged from main).
- `npm run build` clean. Bundle delta: JS 38.16 → 40.53 KB gzipped
  (+2.37 KB), CSS 4.62 → 4.83 KB gzipped (+0.21 KB). Total
  `~+2.6 KB gzip`, well under the +5 KB ceiling.

#### Mode-A folds applied (M1 letter shift, T4, N1, N2, N3)

- M1 — frontend invariant `(u)` (NOT `(t)`): `(t)` is taken on main
  by Track B-SYSTEM PR-2; `(u)` was the next free letter as of
  2026-04-30 (`(r)` and `(s)` are also free but cluster less well
  with the recent invariants).
- T4 — vitest case 1 asserts logical mask cell (50, 50) is painted
  for a CSS click at (50, 50) under `devicePixelRatio = 2`. A
  DPR-bug writer would have written into (100, 100) which is
  out-of-range; the adjacent (49, 49) check sanity-asserts the
  paint kernel did not over-shoot.
- N1 — banner copy points operators at System tab / `/local` for the
  restart, NOT raw `systemctl` per
  `.claude/memory/project_godo_service_management_model.md`.
- N2 — `package.json` unchanged (no new dep; FormData + fetch are
  browser standard).
- N3 — total LOC ~530 frontend (component + route + tests + small
  protocol/constants edits) within plan budget.

### 2026-04-30 14:00 KST — Track B-SYSTEM PR-B (frontend) — System tab sub-tabs

#### Added

- `src/lib/protocol.ts` — `PROCESS_FIELDS` (10), `ProcessEntry`,
  `ProcessesSnapshot`, `EXTENDED_RESOURCES_FIELDS` (6),
  `ExtendedResources`, `MANAGED_PROCESS_NAMES`, `GODO_PROCESS_NAMES`,
  `ProcessCategory` literal type. Mirror of the webctl SSOT in
  `godo_webctl/protocol.py`.
- `src/lib/constants.ts` — `PROCESSES_POLL_FALLBACK_MS`,
  `EXTENDED_RESOURCES_POLL_FALLBACK_MS`, `CPU_BAR_HEIGHT_PX`,
  `SYSTEM_SUBTAB_OVERVIEW`, `SYSTEM_SUBTAB_PROCESSES`,
  `SYSTEM_SUBTAB_EXTENDED`.
- `src/styles/tokens.css` — `--border-width-emphasis: 3px` (NEW
  token; reuses existing `--color-status-{warn,err}` for typography
  colors per Mode-A M5 + Final fold O1).
- `src/stores/processes.ts` — refcounted SSE store for
  `/api/system/processes/stream`. One initial fetch covers
  the SSE-connect gap; `_arrival_ms` stamped per frame.
- `src/stores/resourcesExtended.ts` — same pattern for
  `/api/system/resources/extended/stream`.
- `src/components/ProcessTable.svelte` — sortable table with
  text-search + GODO-only filter + duplicate-alert banner + per-row
  duplicate marker + `<details>`-style info popover (3 documented
  bullet strings per Final fold S4).
- `src/components/ResourceBars.svelte` — per-core CPU bars + mem bar
  - disk bar. No SVG / rings (operator decision); null-tolerant.
- `src/routes/System.svelte` — wraps the existing 5-panel content in
  a default `overview` sub-tab + adds `processes` and `extended`
  sub-tabs. `activeSubtab` is component-local `$state`.
- `tests/unit/processes.test.ts` — 6 cases (SSE refcount,
  `_arrival_ms`, duplicate-alert propagation, token-only URL,
  malformed-payload drop).
- `tests/unit/resourcesExtended.test.ts` — 4 cases.
- `tests/unit/processTable.test.ts` — 8 cases (sort, search, GODO
  toggle, duplicate banner + row marker, popover bullets, managed
  styling, count summary).

#### Changed

- Invariant (y) added (see above).
- `routes/System.svelte` no longer flattens its 5 panels; they live
  inside the default `overview` sub-tab. Existing
  `tests/unit/system.test.ts` (11 cases) continues to pass —
  defaulting to `overview` keeps the original DOM tree on mount.

#### Removed

- (none)

#### Tests

- 164 → 182 hardware-free vitest (+18 from PR-B frontend half).
- `npm run lint` clean on all PR-B paths (no new warnings).

#### Mode-A folds applied

- Final fold (07:09 KST) + Operator decisions:
  - GPU widget dropped entirely (no `gpu_pct` in
    `EXTENDED_RESOURCES_FIELDS`, no GPU panel).
  - All-PID enumeration with category classifier; kernel threads
    excluded.
  - `category` (NOT `class`) wire field name.
  - Sub-tab + filter state component-local; resets on route change.
  - HTML5 `<details><summary>` popover (no new component dep).
  - `--color-status-warn` reused for managed accent; new
    `--border-width-emphasis: 3px` token only.
- M3 — `category` everywhere (no `class`).
- M5 — no raw hex; only token references.
- M6 — `_arrival_ms` stamped per frame; pinned by per-store tests.
- S1 — token-only SSE URL; pinned by `processes.test.ts`.
- S4 — popover-bullets test (`processTable.test.ts`).
- S5 — single banner string (no restart-detection sub-text);
  TODO comment in `ProcessTable.svelte` references the deferred
  Phase 4-5 polish item.

### 2026-04-30 17:30 KST — Track D scale + Y-flip fix

#### Added

- `src/lib/mapYaml.ts` — pure parser for ROS map_server YAML; extracts
  `image / resolution / origin / negate`. Throws `MapYamlParseError`
  on missing or malformed fields; tolerates blank + comment lines.
- `src/lib/protocol.ts` — `MapYaml`, `MapDimensions`, `MapMetadata`
  interfaces. `MapMetadata` composes both wire shapes plus a
  `source_url` field for store-side staleness detection.
- `src/stores/mapMetadata.ts` — `Writable<MapMetadata | null>` +
  `loadMapMetadata(mapImageUrl)`. Parallel-fetches YAML + dimensions
  via `apiFetch` / `apiGet`; AbortController-cancels the previous
  load on rapid name changes (Mode-A T2 fold pin).
- `tests/unit/mapYaml.test.ts` (6 cases — minimal valid + missing
  resolution + bad type + 3-element origin + non-zero theta + comment
  tolerance).
- `tests/unit/mapMetadata.test.ts` (5 cases — parallel fetch + name
  derivation + cancellation race + 404 + parse-error).
- `tests/unit/poseCanvasScale.test.ts` (8 cases — Mode-A T3 hand-
  computed integers: §C-1 identity, §C-2 non-zero origin, §C-3
  Y-flip pin (the fail-then-pass DoD gate per S1), §C-4 direction
  sanity, §C-5 zoom-equiv, §C-6 non-square (M2 rewrite), §C-7
  resolution variance, §C-8 inverse-resolution scaling (T1 rewrite)).
- `tests/unit/poseCanvasImageReload.test.ts` + `_PoseCanvasHost.svelte`
  (Mode-A M3 reactive image refetch — assert exactly 1 fetch on
  initial mount, 2 after first prop change, 3 after second).
- `tests/e2e/map.spec.ts` — 1 new playwright case "scan overlay
  survives wheel-zoom (Track D scale fix)".

#### Changed

- `src/components/PoseCanvas.svelte` — (a) subscribes to
  `$stores/mapMetadata`; (b) `worldToCanvas` / `canvasToWorld` now
  read `metadata.resolution`, `.origin`, `.width`, `.height` (Y-flip
  in the single `H - 1 - (wy - oy)/res` line); (c) image draw uses
  `img.naturalWidth × zoom` anchored to canvas centre — the world
  frame sits on the SAME centre via `(imgCol - width/2)` so the
  overlay aligns with the bitmap at every zoom; (d) `MAP_PIXELS_PER_METER`
  import deleted; (e) reactive `$effect(() => mapImageUrl)` refetches
  BOTH bitmap + metadata on prop change (Mode-A M3); (f) non-zero
  theta warning banner (Mode-A S6); (g) overlay gating extended to
  `meta != null`.
- `src/lib/constants.ts` — DELETED `MAP_PIXELS_PER_METER` (the
  structural witness for the fix).
- `tests/unit/poseCanvasFreshness.test.ts` — inject identity metadata
  mock + add Mode-A S5 case (scan stays fresh when metadata resolves
  at t=400ms because Date.now() - 0 = 400 < MAP_SCAN_FRESHNESS_MS).
- `tests/e2e/_stub_server.py` — new `_h_maps_dimensions(name)` handler
  returning `{width: 200, height: 100}` non-square (so the e2e suite
  exercises the H-1 - (wy-oy)/res row math); existing YAML stub
  unchanged (the earlier "placeholder" claim was a misread per Mode-A
  S4 fold).
- `CODEBASE.md` — module-responsibilities row updated; new invariant
  `(x)` documented.

#### Removed

- `src/lib/constants.ts::MAP_PIXELS_PER_METER` — pre-flight grep
  captured (single hit in `src/`, two hits in `src/components/`).
  Post-deletion grep returns zero hits in `src/`.

#### Tests

- 143 → 164 vitest unit cases (+21 from this PR: 6 mapYaml + 5
  mapMetadata + 8 poseCanvasScale + 1 poseCanvasImageReload + 1
  Mode-A S5 freshness case; existing freshness tests amended in place).
- 36 → 37 passing playwright e2e cases (+1 from `map.spec.ts`). The
  pre-existing `config.spec.ts: anonymous viewer does NOT see the
Config nav row` failure remains red (unrelated to this PR).
- `npm run lint` clean for new files; pre-existing warning in
  `tests/unit/maps.test.ts` is unchanged.
- `npm run build` produces 33.18 kB gzipped JS (was 31.89 kB on
  `main e68e035`; +1.29 KB delta — within the +2.0 KB Mode-A M3+S6
  budget).

#### Mode-A folds applied

- M1: §C-3 rewritten as a fail-on-unfixed test pinning
  `worldToCanvas(0, 0).cy === 249` against the new metadata-aware
  math; FAILED on `main e68e035` (cy=75) and PASSED on the new
  code — fail-then-pass evidence in PR body.
- M2: §C-6 worked example uses non-square `width=200, height=50`
  with origin=[0,0,0]; literal-integer expected coords.
- M3: P4-D5 step iii — reactive `$effect` for image refetch added.
  Pinned by `poseCanvasImageReload.test.ts` via a Svelte 5 host
  component that mutates an internal `$state(url)`.
- M4: webctl invariant tail = `(x)` on `main e68e035`; this PR adds
  `(y)` to webctl. Frontend tail = `(w)`; this PR adds `(x)`.
- S1: §C-3 fail-on-unfixed-then-pass evidence captured.
- S2: pre-flight grep of `MAP_PIXELS_PER_METER` recorded; post-
  deletion grep returns zero hits in `src/`.
- S3: line 102 module-responsibilities row updated to read
  `mapMetadata.resolution + .origin + .height`.
- S5: scan-arrives-at-t=0 / metadata-at-t=400ms / fresh case added
  to `poseCanvasFreshness.test.ts`.
- S6: non-zero theta warning banner in `PoseCanvas.svelte` (visible
  to operator, not a silent `console.warn`).
- T1: §C-8 replaces the vacuous "constant deleted" test with the
  inverse-resolution scaling property (delta_b = 2 × delta_a).
- T2: `mapMetadata.test.ts::cancellation race` strengthened to spy
  on store transitions and assert v1 NEVER leaks into the store.
- T3: §C-1 expected coords are hand-computed literal integers, not
  formula-recomputed.

### 2026-04-29 — Track D: Live LIDAR overlay (Phase 4.5+ P0.5)

#### Added

- `src/lib/protocol.ts` — `LastScan` interface (11 fields), tuple
  `LAST_SCAN_HEADER_FIELDS`, `LAST_SCAN_RANGES_MAX = 720`,
  `CMD_GET_LAST_SCAN`. `_arrival_ms` is documented as a CLIENT-SIDE
  field (set in the SSE adapter, never on the wire).
- `src/lib/constants.ts` — 5 new constants:
  `MAP_SCAN_DOT_RADIUS_PX = 1.5`, `MAP_SCAN_DOT_COLOR = '#26a69a'`
  (teal — Q-OQ-D3 color-blind friendly trio with pose red and trail
  blue), `MAP_SCAN_DOT_OPACITY = 0.7`, `MAP_SCAN_FRESHNESS_MS = 1000`,
  `LAST_SCAN_POLL_FALLBACK_MS = 1000`.
- `src/lib/scanTransform.ts` — pure function `projectScanToWorld(scan)`
  that does the polar→Cartesian world-frame transform using the SCAN's
  own anchor pose (invariant (n)); empty array when validity flags fail
  (Mode-A M3 — pose_valid gate). Extracted so unit tests can exercise
  the math without mounting PoseCanvas.
- `src/stores/scanOverlay.ts` — `Writable<boolean>` toggle store with
  `sessionStorage` persistence (key `godo:scanOverlay`), default OFF,
  `setScanOverlay/toggleScanOverlay/_resetScanOverlayForTests`.
- `src/stores/lastScan.ts` — SSE-fed store + polling fallback,
  refcounted subscribers, lifecycle GATED on the `scanOverlay` toggle
  (invariant (o)). Stamps `_arrival_ms = Date.now()` on every frame
  before emit (Mode-A M2). Mirrors `stores/lastPose.ts` structure.
- `src/components/ScanToggle.svelte` — on/off button + freshness badge
  ("최신" / "약간 지연됨" / "정지됨"). Computes the badge state from
  `Date.now() - scan._arrival_ms` (invariant (m)). 250 ms heartbeat
  tick so the badge animates even when no new SSE frame arrives.
- `tests/unit/scanOverlay.test.ts` (4 cases), `lastScan.test.ts`
  (8 cases), `poseCanvasScanLayer.test.ts` (10 cases — TB2 three
  non-trivial yaw cases + gating + TB1-equivalent positional integrity),
  `poseCanvasFreshness.test.ts` (2 cases — Mode-A M2 patch using
  `vi.useFakeTimers`), `scanToggle.test.ts` (6 cases).
- `tests/e2e/map.spec.ts` — 4 new playwright cases: toggle visible /
  defaults off, toggle on shows ≥ 5 dots via `data-scan-count`,
  toggle off clears, sessionStorage persists same-tab reload.
- `tests/e2e/_stub_server.py` — `_canned_scan()` (5-dot canned shape),
  `/api/last_scan` GET handler (anon), `/api/last_scan/stream` SSE
  handler (anon, mirrors `last_pose_stream` pattern).

#### Changed

- `src/components/PoseCanvas.svelte` — extended with optional
  `scan: LastScan | null` and `scanOverlayOn: boolean = false` props.
  `redraw()` adds a third draw layer between the map underlay and the
  trail loop, calling `projectScanToWorld(scan)` and rendering the
  resulting world-frame points as teal dots. `data-scan-count` and
  `data-scan-fresh` attributes are exposed on the wrap div for e2e
  selector reliability (Q-OQ-D9).
- `src/routes/Map.svelte` — mounts `<ScanToggle/>` above
  `<PoseCanvas/>`; subscribes to `lastScan` and threads `scan` +
  `scanOverlayOn` into `<PoseCanvas/>`. The lastScan subscription
  lifecycle is automatic — the store gates its own SSE on the
  scanOverlay flag.

#### Tests

- 47 → 67 vitest unit cases (+20: scanOverlay 4, lastScan 8,
  poseCanvasScanLayer 10, poseCanvasFreshness 2, scanToggle 6 —
  minus map_list_panel's 2 + auth's 11 + ... net delta is +20).
- 14 → 18 playwright e2e cases (+4 from `map.spec.ts`).
- `npm run lint` clean; `npm run build` produces ~22 kB gzipped.

#### Notes

- `LastScan` is canonically defined in `production/RPi5/src/core/
rt_types.hpp::struct LastScan`. The TS interface order matches the
  wire body emitted by `godo-webctl/src/godo_webctl/app.py::
_last_scan_view`, which iterates `LAST_SCAN_HEADER_FIELDS`. Drift
  detected by inspection per invariant (n).

### 2026-04-29 — Track E Mode-B folds (M4 unit test + lint scaffold)

#### Added

- `tests/unit/map_list_panel.test.ts` — 2 vitest cases mounting the
  real `MapListPanel` component into jsdom via Svelte 5's built-in
  `mount(...)` API (no `@testing-library/svelte` dependency added).
  Pins the Mode-A M4 hide-button contract: with
  `window.location.hostname` stubbed to `192.168.1.50`, the activate
  dialog's primary button is HIDDEN and the placeholder span carrying
  the `로컬 kiosk에서만 가능` tooltip renders in its slot. Companion
  case on `127.0.0.1` proves the primary button DOES render on
  loopback (anti-tautology check).
- `vitest.config.ts` — dedicated test config so the svelte plugin can
  run with `style: false` preprocessing under vitest (the production
  `vite.config.ts` + `svelte.config.js` use `vitePreprocess()` with
  default style preprocessing, which `preprocessCSS` cannot consume
  inside vitest's transform pipeline). Adds `resolve.conditions =
['browser']` so `mount(...)` resolves to svelte's client build under
  jsdom.

#### Changed

- `vite.config.ts` — removed the embedded `test:` block (now lives in
  `vitest.config.ts`); production build is unchanged.

#### Tests

- 37 vitest unit cases (was 35; +2 from `map_list_panel.test.ts`).
- 14 playwright e2e cases unchanged.
- `npm run lint` clean; `npm run build` produces ~22 kB gzipped.

### 2026-04-29 — PR-C: Track E (multi-map management)

#### Added

- `src/components/MapListPanel.svelte` — list every map under
  `${GODO_WEBCTL_MAPS_DIR}`, mark the active row, expose admin-gated
  `기본으로 지정` + `삭제` buttons. Reuses `<ConfirmDialog/>` with the
  new `secondaryAction` prop (per invariant (l)). Refresh on mount /
  post-activate / post-remove only — no polling (per Mode-A N6).
- `src/stores/maps.ts` — `Writable<MapEntry[]>` + `refresh()` /
  `activate(name)` / `remove(name)`. Mutations short-circuit
  client-side via `MAPS_NAME_REGEX_PATTERN_STR`.
- `src/lib/api.ts::apiDelete` — companion of `apiGet`/`apiPost`.
- `src/lib/protocol.ts` — 4 new error-code mirrors
  (`ERR_INVALID_MAP_NAME`, `ERR_MAP_NOT_FOUND`, `ERR_MAP_IS_ACTIVE`,
  `ERR_MAPS_DIR_MISSING`), `MAPS_NAME_REGEX_PATTERN_STR`, `MapEntry`
  - `MapListResponse` + `ActivateResponse` interfaces.
- `tests/unit/maps.test.ts` — 6 vitest cases covering the store
  contract + client-side validator.
- `tests/e2e/map.spec.ts` — 3 new playwright cases (list panel,
  activate flow, delete-disabled-on-active).
- `tests/e2e/_stub_server.py` — 5 new endpoints, in-memory map state
  shared across tests, loopback-flag flag (`?stub_loopback=…`) for
  the M4 non-loopback restart-button test path.

#### Changed

- `src/components/ConfirmDialog.svelte` — extended with optional
  `secondaryAction`, `showPrimary`, `primaryHiddenTooltip` props
  (invariant (l)). Cancel + primary still render as before; existing
  callers unaffected.
- `src/routes/Map.svelte` — mounts `<MapListPanel/>` above
  `<PoseCanvas/>`; threads a local `previewUrl` state so clicking a
  non-active row repaints the canvas with that map (back-compat
  default `/api/map/image` resolves through the active symlink).

#### Tests

- 35 vitest unit cases (was 29; +6 from `maps.test.ts`).
- 14 playwright e2e cases (was 11; +3 from `map.spec.ts`).
- `npm run lint` clean; `npm run build` produces ~22 kB gzipped.

### 2026-04-28 — PR-B: P0 frontend SPA

#### Added

- New top-level directory `godo-frontend/` (Vite 6 + Svelte 5 + TypeScript).
- `package.json` — pinned deps, scripts (`dev`/`build`/`preview`/
  `test:unit`/`test:e2e`/`lint`/`format`).
- `vite.config.ts` — Svelte plugin, dev proxy `/api → 127.0.0.1:8080`,
  path aliases.
- `src/lib/constants.ts` — 30+ SPA-internal Tier-1 constants.
- `src/lib/protocol.ts` — wire-shape mirror of `godo-webctl/protocol.py`.
- `src/lib/router.ts` — 30-line hash-router (per N9).
- `src/lib/api.ts` — `apiFetch/apiGet/apiPost/apiPatch` with auth header
  - 401 redirect + typed `ApiError`.
- `src/lib/sse.ts` — `SSEClient` with token-on-URL + Page Visibility
  handbrake + expired-token guard.
- `src/lib/auth.ts` — login/logout/refresh + decode-only `getClaims`.
- `src/lib/format.ts` — Korean-friendly formatters.
- `src/stores/{auth,lastPose,mode,theme}.ts`.
- `src/components/{TopBar,Sidebar,ModeChip,ServiceCard,PoseCanvas,
ConfirmDialog}.svelte`.
- `src/routes/{Dashboard,Map,Login,Local,NotFound}.svelte`.
- `src/styles/{tokens,global}.css` — Confluence-style: light default,
  sharp 2-4px corners, dense vertical spacing.
- `public/favicon.svg` — `:D` glyph (per FRONT_DESIGN §3 G-Q3).
- `tests/unit/{api,auth,sse}.test.ts` — 29 vitest cases.
- `tests/e2e/{login,dashboard,map,local}.spec.ts` — 11 playwright cases.
- `tests/e2e/_stub_server.py` — stdlib HTTP server, mirrors webctl wire.
- `tests/e2e/playwright.config.ts` — webServer auto-launches stub.
- `README.md`, `CODEBASE.md` (this file).

#### Tests

- 29 vitest unit cases, 11 playwright e2e cases. All green.
- `npm run lint` clean (eslint 9 + prettier 3).
- `npm run build` produces ~21 kB gzipped total (well under 200 kB target).

#### Deviations from plan (writer apply-notes)

- **Vite version**: plan called for "Vite 8.x". At writer time the
  highest Vite that has shipped is 6.x (5.4 LTS, 6.0 current). Using
  Vite 6.0 + `@sveltejs/vite-plugin-svelte@5.0` (only that combo
  installs without peer-dep warnings against Svelte 5.20).
- **Svelte version**: bumped to `~5.20` from the plan's `~5.0`. Svelte
  5.0.5 had a known bug where `<script lang="ts">` with `interface`
  declarations + `: T[]` type annotations in `const` declarations
  produced a `Not implemented type annotation EmptyStatement` esrap
  error. 5.20 fixes it.
- **`svelte-spa-router` replaced**: per N9. The package description still
  says "Router for SPAs using Svelte 4"; we wrote a 30-line hash-router.
- **`@types/node`** kept on Node 20 line (`~20.14.0`) since RPi 5 ships
  Node 20 from Debian Bookworm.
- **`SubmitEvent` type** in `Login.svelte` requires browser globals in
  ESLint config — added `globals.browser` via the `globals` package.

---

## 2026-04-29 — PR-DIAG (Track B-DIAG) — Diagnostics page

### Added

- `src/lib/protocol.ts` — wire shapes:
  - `interface JitterSnapshot` (mirrors C++ rt_types + format_ok_jitter).
  - `interface AmclIterationRate` (Mode-A M2 fold renamed scan_rate).
  - `interface Resources` (webctl-only — no C++ counterpart).
  - `interface DiagFrame` (multiplexed top-level keys: pose / jitter /
    amcl_rate / resources). `_arrival_ms` is a CLIENT-SIDE NON-WIRE
    field set on receipt by the diag store.
  - Field-order tuples `JITTER_FIELDS` / `AMCL_RATE_FIELDS` /
    `RESOURCES_FIELDS` / `DIAG_FRAME_FIELDS`.
  - `CMD_GET_JITTER` / `CMD_GET_AMCL_RATE` literals (anchor for the
    cross-language drift triple).
- `src/lib/constants.ts` — 9 new SPA-internal constants:
  `DIAG_SPARKLINE_DEPTH`, `DIAG_SPARKLINE_WIDTH_PX`,
  `DIAG_SPARKLINE_HEIGHT_PX`, `DIAG_FRESHNESS_MS`,
  `DIAG_POLL_FALLBACK_MS`, `LOGS_TAIL_MAX_N_MIRROR`,
  `LOGS_TAIL_DEFAULT_N`, `JITTER_PANEL_COLOR`,
  `AMCL_RATE_PANEL_COLOR`, `RESOURCES_PANEL_COLOR`.
- `src/stores/diag.ts` (NEW) — SSE-fed `Writable<DiagFrame | null>` +
  `Writable<DiagSparklineState>` (5 ring buffers of depth 60 frames =
  12 s @ 5 Hz lookback). Refcounted; SSE opens on first subscriber,
  closes on last. 1 Hz polling fallback when SSE drops. Stamps
  `_arrival_ms` on every received frame.
- `src/stores/journalTail.ts` (NEW) — manual-refresh state
  `Writable<JournalTailState>` + `refreshJournalTail(unit, n)`
  function. NOT polled; operator clicks Refresh.
- `src/components/DiagSparkline.svelte` (NEW, ~110 LOC) — canvas-based
  sparkline. Auto-scales y-axis to data range. No external chart lib —
  the FRONT_DESIGN §9 chart-library decision is still pending; this
  component lets PR-DIAG ship independently (OQ-DIAG-1).
- `src/components/JournalTail.svelte` (NEW, ~120 LOC) — allow-list
  dropdown + n-input + refresh button + monospace `<pre>` body.
  Hardcoded mirror of `services.ALLOWED_SERVICES`.
- `src/routes/Diagnostics.svelte` (NEW, ~210 LOC) — B-DIAG page. Four
  sub-panels in CSS-grid auto-fit (>=420 px columns):
  Pose / Jitter / AMCL rate + Resources / Journal tail. Stale-frame
  greying via `DIAG_FRESHNESS_MS` against
  `Date.now() - frame._arrival_ms`. Re-render tick once per second
  so the freshness gate evaluates without a new SSE frame.
- `src/routes.ts` — `/diag` → `Diagnostics` registered.
- `src/components/Sidebar.svelte` — added `/diag` nav row.
- `tests/e2e/_stub_server.py` — 5 new endpoint stubs:
  `/api/system/jitter`, `/api/system/amcl_rate`, `/api/system/resources`,
  `/api/diag/stream`, `/api/logs/tail`.

### Tests (new)

- `tests/unit/diag.test.ts` (8 cases — subscribe/unsub refcount,
  SSE open/close, no SSE without subscribers, \_arrival_ms stamping,
  sparkline ring depth, ring drops oldest at depth, polling fallback
  on SSE error, reset).
- `tests/unit/diagSparkline.test.ts` (5 cases — empty input, flat-line,
  polyline shape, label + chip render, "—" chip on empty input).
- `tests/unit/journalTail.test.ts` (4 cases — allow-list dropdown,
  loading-disables-button, empty-state, error-state).
- `tests/e2e/diagnostics.spec.ts` (5 cases — route renders, all four
  panels visible, jitter chip populates after login, allow-list
  dropdown count, journal Refresh fetches lines).

### Mode-A folds applied

- M2: `scan_rate` → `amcl_rate` everywhere — interface name, field
  tuple, DiagFrame key, store field.
- N4: SPA `_arrival_ms` pattern extended from Track D's LastScan to
  the multiplexed DiagFrame (one stamp per frame; sub-panels share it).
- OQ-DIAG-1: hand-rolled canvas sparkline (not uPlot / not SVG) —
  decoupled from FRONT_DESIGN §9 chart-library decision.
- OQ-DIAG-3: `JournalTail` allow-list hardcoded in SPA (not fetched
  from a new endpoint); drift detected by code review per invariant (q).
- OQ-DIAG-8: polling fallback at 1 Hz (not 5 Hz) — the choppier
  cadence is itself a useful operator signal that "SSE is broken".

### Total frontend test count

84 vitest cases (was 67 pre-PR-DIAG). 23 playwright e2e cases (was 18).
`npm run lint` clean; `npm run build` green; bundle 68.59 kB
(gzip 25.96 kB) — +1.1 kB raw vs pre-PR-DIAG.

## 2026-04-29 — Track B-CONFIG (PR-CONFIG-β): /config page

### Added

- `src/lib/protocol.ts` (extended) — `RELOAD_CLASS_HOT/_RESTART/_RECALIBRATE`
  literals + `ReloadClass` type, `VALID_RELOAD_CLASSES` set,
  `ConfigValueType` union, `ConfigSchemaRow`, `ConfigKV`,
  `ConfigGetResponse`, `ConfigPatchBody`, `ConfigSetResult`,
  `RestartPendingResponse`. Hand-mirrored from the Python NamedTuple
  in `godo-webctl/src/godo_webctl/config_schema.py`; drift catch by
  inspection per invariant (k).
- `src/stores/config.ts` — `Writable<ConfigState>` with
  `{schema, current, errors}`. `refresh()` parallel-fetches
  `/api/config/schema` + `/api/config`. `set(key, value)` does
  optimistic update + PATCH; on 400 rolls back the local value and
  populates `errors[key]` from the tracker's `detail` text. On
  success refetches `/api/config` for an authoritative read AND
  triggers `refreshRestartPending()` so the global banner updates
  immediately on `restart`/`recalibrate` edits.
- `src/stores/restartPending.ts` — `Writable<{pending, trackerOk}>`.
  `refresh()` joins `/api/system/restart_pending` with
  `/api/health.tracker`; the banner component differentiates the
  two failure modes (Mode-A S5 fold).
- `src/components/RestartPendingBanner.svelte` — top-of-app red
  banner with two failure-mode messages: "godo-tracker 재시작 필요"
  (tracker ok + flag set) vs "godo-tracker 시작 실패 — journalctl 확인"
  (tracker unreachable + flag set). Non-dismissable; the C++ boot
  clears the flag.
- `src/components/ConfigEditor.svelte` — main editor table. One row
  per schema entry; type-aware input (number / number / text per
  Int / Double / String). Submit on blur or Enter; Escape cancels.
  Reload-class glyph (✓ / ! / !!) with tooltip on the leftmost cell.
  Anonymous viewers see disabled inputs. On 400 the row's `error[key]`
  shows under the input.
- `src/routes/Config.svelte` — page composition: header + editor.
  The banner is global (App.svelte) so we DO NOT double-render here.
- `src/routes.ts` — register `/config` → `Config.svelte`.
- `src/components/Sidebar.svelte` — admin-only "Config" nav row.
- `src/App.svelte` — `RestartPendingBanner` mounted globally so it's
  visible on every page (DASH, MAP, DIAG, CONFIG, LOCAL).

### Tests

- New: `tests/unit/config.test.ts` (4 cases) — refresh + optimistic
  set + 400 rollback + network-error rollback.
- New: `tests/unit/restartPending.test.ts` (4 cases) — pending + ok,
  pending + tracker-down, flag-clear, dual-API-error fallback.
- New: `tests/unit/protocol.test.ts` (7 cases) — interface shape +
  reload-class string pins.
- New: `tests/e2e/config.spec.ts` (5 cases) — anonymous-disabled,
  admin nav-link + edit hot key, restart banner appears on
  `restart`-class edit, anon-no-nav, inline 400 error.
- Extended: `tests/e2e/_stub_server.py` — 4 stub schema rows (one per
  reload-class + type combo) + in-memory `RESTART_PENDING_FLAG`
  state; `do_PATCH` handler routes `/api/config`.

### Invariants

- (r) `/config` is admin-gated by Sidebar visibility ONLY (Track F:
  the page itself renders for anon, with disabled inputs). The PATCH
  is admin-gated server-side; SPA disablement is UX polish.
- (s) `RestartPendingBanner` is mounted at App.svelte ONLY (single
  source). Routes MUST NOT double-render the component — playwright
  strict mode catches this regression.
- (t) `config.set()` triggers `restartPending.refresh()` after PATCH
  success (fire-and-forget). The unit test pins this side-effect by
  verifying the head 4 calls match the synchronous PATCH+refetch
  sequence; restart-pending refresh happens after.
- (u) The TS interfaces in `lib/protocol.ts` are hand-mirrored from
  the Python NamedTuple at compile time. The runtime schema fetch
  populates the field DATA, but the field TYPES come from this file.
  Drift catch: `tests/unit/protocol.test.ts` constructor pins.

### (v) PR-SYSTEM — `/system` reuses the diag store; no second SSE

`routes/System.svelte` calls `subscribeDiag(fn)` (the same entry point
`Diagnostics.svelte` uses). The CPU-temperature sparkline reads from
`diagSparklines.cpu_temp_c`, not from a parallel ring. When both
`/diag` and `/system` are mounted (e.g. tabbed), `_getSubscriberCount
ForTests()` reports 2 but invariant (p) keeps the underlying SSE at 1.
`System.svelte` MUST capture the unsubscribe closure returned by
`subscribeDiag(fn)` and call it in `onDestroy` (mirror of
`Diagnostics.svelte:50-54`); failing to do so silently leaks a
subscriber and defeats invariant (p). A System-side resources-poll on
`/api/system/resources` is a code-review block.

Pinned by `tests/unit/system.test.ts::renders four panels, registers
one diag subscriber on mount, and unsubs on unmount` (subscriber count
== 1 after mount, == 0 after unmount).

### (x) Track D scale fix — resolution-aware scan overlay

`PoseCanvas.svelte`'s world↔canvas math reads from the
`$stores/mapMetadata` store (not a hardcoded `MAP_PIXELS_PER_METER`
constant). The store composes:

- `parseMapYaml(text)` over the body of `GET /api/maps/<name>/yaml`
  (resolution, origin, negate),
- the JSON shape of `GET /api/maps/<name>/dimensions` (width, height
  read from PGM header bytes — see godo-webctl invariant (y)).

The transform formula (Mode-A M2 fold pin — non-square width != height
exercised by `tests/unit/poseCanvasScale.test.ts §C-6`):

```
img_col = (wx - origin_x) / resolution
img_row = (height - 1) - (wy - origin_y) / resolution     // Y-flip
cx = canvas.width  / 2 + panX + (img_col - width  / 2) * zoom
cy = canvas.height / 2 + panY + (img_row - height / 2) * zoom
```

The single Y-flip lives in the `(height - 1) - ...` term. World +y
maps to a SMALLER canvas y (higher on screen), matching the ROS
map_server convention that `origin` is the world coord of the
bottom-left pixel.

The `MAP_PIXELS_PER_METER` constant was deleted as the structural
witness — no SPA code path can drift back to a hardcoded scale.

`mapImageUrl` prop changes trigger a reactive `$effect` that refetches
BOTH the bitmap and the metadata (Mode-A M3 fold). Pre-fix, only the
metadata refetched, so a `previewUrl` swap in MapListPanel painted
new coords on old pixels.

For non-zero `theta` in `origin[2]`, the canvas renders an in-canvas
warning banner ("이 맵은 회전 정보(theta)를 갖지만 SPA가 회전을
그리지 못합니다 — 좌표가 어긋날 수 있습니다") in the same DOM slot as
`mapLoadError` (Mode-A S6 fold) — a follow-up ticket will add the
sin/cos image rotation. The banner is operator-visible, not a silent
`console.warn`.

The scan overlay renders ONLY when `mapMetadata` is non-null AND the
freshness gate (Mode-A M2) passes. While metadata is loading, the
canvas falls back to a centred Cartesian frame so the pose dot still
renders (back-compat with the `/api/map/image` 404 path).

Pinned by:

- `tests/unit/mapYaml.test.ts` (6 cases),
- `tests/unit/mapMetadata.test.ts` (5 cases — including Mode-A T2
  cancellation race),
- `tests/unit/poseCanvasScale.test.ts` (8 cases — hand-computed
  literal integers per Mode-A T3, NOT formula-recomputed),
- `tests/unit/poseCanvasImageReload.test.ts` (Mode-A M3 reactive
  refetch — call count 1→2→3 on prop changes via a Svelte 5 host
  component),
- `tests/unit/poseCanvasFreshness.test.ts::Mode-A S5: scan stays
fresh when metadata resolves at t=400ms`,
- `tests/e2e/map.spec.ts::scan overlay survives wheel-zoom`.

### (w) PR-SYSTEM — sparkline window matches `DIAG_SPARKLINE_DEPTH × SSE_TICK_MS`

The System page sparkline label is computed from constants, not
hardcoded. Current value: `60 × 200 ms = 12000 ms = 12 s`.
FRONT_DESIGN §C describes B-SYSTEM as having a "5분 graph"; this is
a deliberate, documented deferral — bumping to 5 min requires growing
the central `DIAG_SPARKLINE_DEPTH` to 1500 (60 KB total store cost),
which is cheap but affects `/diag` simultaneously and so is left to
a deliberate follow-up. The System page MUST NOT carry its own
parallel deeper ring. Pinned by
`tests/unit/system.test.ts::sparkline label is derived from
DIAG_SPARKLINE_DEPTH × SSE_TICK_MS`.

### (z) PR-C — Config tab page-level Edit-mode safety gate

`routes/Config.svelte` owns the `mode: 'view' | 'edit'`, `pending:
Record<string,string>`, `applyResults`, and `isApplying` state. The
state is page-local — unmounting `/config` (route change) resets
all of them; this is the safety property that prevents a forgotten
Edit-mode in another tab from poisoning the next session. Hoisting
any of these to a store would defeat the operator-stated
"실수로 값이 변경되는 것을 방지" requirement and is a code-review block.

`components/ConfigEditor.svelte` is now a dumb controlled table:
`mode`, `pending`, `applyResults`, `setPending`, `isApplying`, plus
schema/current/admin come in as props; nothing flows back into the
config store from this component. Inputs are `disabled = mode==='view'
|| !admin || isApplying`. The previous on-blur PATCH path was deleted
— operator-driven Apply is the only mutation route.

`stores/config.ts::applyBatch(pending)` is a best-effort sequential
PATCH loop (memory §"Why best-effort, not all-or-nothing"). Snapshot
order is pinned at call time via `Object.entries(pending)`; failures
do NOT short-circuit. Post-loop sequence:
`await refresh()` (authoritative truth) + `void
refreshRestartPending()` (fire-and-forget). Returns `Array<{key, ok,
error?}>` so the caller can render per-row markers and surface
detail strings. Changing this to "stop on first failure" or wrapping
in a bulk endpoint for atomicity is a regression unless the operator
re-asks.

`stores/config.ts::set()` is retained as a tested-but-unused symbol
after the per-row blur-PATCH UI was deleted in this PR; its 4
existing unit tests at `tests/unit/config.test.ts` (lines 53-147)
document the contract for future re-use, and deletion is deferred
to a follow-up sweep PR per minimum-change discipline.

Cancel is **client-side only** — never fires a PATCH, never fires a
reverse-PATCH (memory §"Why Cancel is client-side only"). With
`pending === 0` it short-circuits to View; with `pending > 0` it
opens `<ConfirmDialog/>` (`message="${N}개 변경사항이 폐기됩니다.
계속하시겠습니까?"`) and on 확인 clears the pending dict + returns
to View. If somebody adds a reverse-PATCH path "for symmetry," that
is a regression — re-read `.claude/memory/project_config_tab_edit_mode_ux.md`.

The schema `default` value renders as a muted `(default: <value>)`
hint under each row's Current value (`.default-hint` CSS uses
`word-break: break-all` + `max-width: 100%` so long string defaults
wrap inside the 10em Current column rather than push the table
wider).

The tracker-inactive banner is sourced from the existing
`systemServices` polling store (invariant (t)) — no new endpoint.
Banner suppression rule: render the banner ONLY when the store
has fetched a non-empty services list AND the `godo-tracker` row's
`active_state !== 'active'`. On initial mount before the first
`/api/system/services` resolution the banner stays suppressed (R5
false-positive avoidance). On an inactive→active transition the
page fires `void refresh()` so the operator sees fresh values
immediately.

The Apply mid-loop button label is the Korean string
`적용 중… (k/N)` per Final fold O1; the surrounding EDIT/Cancel/Apply
button bases stay English to mirror `Sidebar.svelte`'s nav labels.

Pinned by `tests/unit/config.test.ts`:

- 4 existing `set()` cases (refresh / set-success / set-400 /
  set-network-error) at the top of the file (deferred deletion path).
- 4 new `applyBatch` cases: all-success, all-failure, mixed (A+B
  succeed C fails), `Object.entries`-snapshot ordering.
- 5 new state-machine cases: View→Edit admin-gating, Cancel-no-pending
  (no dialog), Cancel-with-pending → 확인 (clears + View),
  Cancel-with-pending → 취소 (preserves + Edit), Apply all-success
  (auto returns to View + markers fade after
  `CONFIG_APPLY_RESULT_MARKER_TTL_MS = 2000 ms`),
  Apply partial (stays in Edit, ✗ + error visible).
- 3 new banner cases: tracker active → no banner, tracker inactive →
  banner with the canonical Korean substring, tracker reactivation →
  banner disappears + `refresh()` fires.
- 1 new `(default: ...)` hint render case.
- 1 new Cancel-after-partial-apply walkthrough (continuation of the
  partial-apply test): operator clicks Cancel after a partial Apply,
  the confirm dialog shows `1개 변경사항이 폐기됩니다`, no NEW PATCH
  is fired by the cancel path.

Total: 19 cases in `tests/unit/config.test.ts` post-PR.

### (aa) `OriginPicker.svelte` is the sole owner of origin-edit form state; `MapMaskCanvas` mode-prop split keeps DPR isolation (Track B-MAPEDIT-2)

> Letter rationale: `(z)` is taken (PR-C, line 1320 above) and the next
> free letter is `(aa)`. Mirrors webctl's `(aa) → (ab)` continuation
> from PR #39.

The dual-input origin form (`x_m`, `y_m`, `mode`) lives ENTIRELY inside
`<OriginPicker/>` instance state. `<MapEdit/>` orchestrates layout +
the brush-vs-origin click-mode toggle but does NOT mirror the form
values in any store. The exported imperative API
`OriginPicker.setCandidate({x_m, y_m})` is the only path by which a
parent component (the MapEdit GUI-pick handler) can pre-fill the form;
parents cannot read the current form values back — Apply payload is
emitted via the `onapply` callback prop.

The Origin section is a co-resident block INSIDE the Edit sub-tab
(NOT a peer sub-tab); operator-locked decision per spec memory +
planner §7 open question 4. A future "Origin sub-tab" refactor is a
regression unless the operator re-asks.

`MapMaskCanvas.svelte` gains a `mode: 'paint' | 'origin-pick'` prop
(default `'paint'`). In `'origin-pick'` mode pointer events bypass the
mask buffer entirely and emit `oncoordpick(lx, ly)` with logical PGM
coords. Mask state is byte-identical to a paint-mode no-op pointer
event — invariant (u) holds. T4 fold's DPR isolation continues to
apply (logical coords are the canonical emit shape regardless of
`devicePixelRatio` or CSS scale).

`lib/originMath.ts` is the SPA-side sole-owner of pixel↔world math:
`pixelToWorld(px, py, dims, resolution, origin)` applies the ROS
Y-flip convention `world_y = origin[1] + (height - 1 - py) * resolution`
exactly once. The `-1` is load-bearing — Mode-A reviewer M4 caught a
draft missing it (would silently shift the candidate marker by one
cell row, ~5 cm at typical 0.05 m/cell — 2× the operator's accuracy
target). PoseCanvas's existing world↔canvas math is NOT extracted into
this module in this PR (would be a refactor outside the LOC budget);
the documented rule is "every NEW pixel↔world site uses originMath.ts".

`resolveDelta(currentOrigin, dx, dy)` uses the **ADD sign convention**
(operator-locked 2026-04-30 KST, see
`.claude/memory/project_map_edit_origin_rotation.md`):
`new_origin = currentOrigin + (dx, dy)`. Operator phrasing: "실제
원점 위치는 여기서 (x, y)만큼 더 간 곳". Korean operator-copy in the
picker reads "Delta: 입력한 값을 현재 origin에 **더해서** 새 origin이
됩니다." (NOT "빼서"). SUBTRACT is a regression that would silently
shift the origin by 2× the typed offset.

Apply path mirrors webctl invariant `(ab)` on the wire side:

1. SPA validates inputs (finite, magnitude bound `ORIGIN_X_Y_ABS_MAX_M
= 1_000.0`, locale-comma rejected).
2. SPA POSTs `/api/map/origin` via `postMapOrigin({x_m, y_m, mode})`
   — JSON-encoded (NOT multipart; brush-edit was multipart for the
   binary mask).
3. On 200: success banner `완료: (prev) → (new)` + fire-and-forget
   `refreshRestartPending` + `setTimeout(navigate('/map'),
ORIGIN_PICK_REDIRECT_DELAY_MS = 3000)`.
4. On 4xx/5xx: error banner inline; form values preserved (no clear).

The picker uses `<input type="text" inputmode="decimal">` (NOT
`type="number"`) so the raw string is preserved for the locale-comma
rejection check. `Number.isFinite` is the load-bearing finiteness
gate (mirror of webctl's `math.isfinite` discipline).

Pinned by `tests/unit/originMath.test.ts` (6 cases incl. M4 Y-flip
off-by-one + delta ADD pin), `tests/unit/originPicker.test.ts` (10
cases incl. mode toggle + locale-comma reject + NaN-like reject +
`setCandidate` flips mode to absolute (T1 fold) + payload shape pin +
MapMaskCanvas mode-prop default + origin-pick byte-identical mask
buffer (T5 fold)), `tests/e2e/mapEdit.spec.ts` (3 new cases: admin
numeric apply, admin GUI-pick pre-fill, viewer cannot apply).

### (ab) PR β — shared map viewport + zoom UX uniform + Map Edit LiDAR overlay

`<MapUnderlay/>` is the SOLE owner of the shared viewport plus
scan-overlay render path. `<MapZoomControls/>` is the SOLE zoom-input
UI. `mapViewport.svelte.ts::createMapViewport()` is the SOLE owner of
zoom, pan, and min-zoom state; the factory is per-component-instance
(Q2 — operator navigating `/map` ↔ `/map-edit` gets a fresh viewport;
module-scope singletons would leak state across navigation and require
manual reset between vitest cases — extends `System.svelte`'s sub-tab
state-reset idiom from invariant `(y)`).

**Mouse-wheel zoom is FORBIDDEN.** The `MAP_WHEEL_ZOOM_FACTOR` constant
was deleted as the structural witness that wheel zoom is gone.
Re-introducing wheel-zoom requires (a) operator confirmation in
`.claude/memory/project_map_viewport_zoom_rules.md` (Rule 1 currently
FORBIDS it), (b) updating this invariant's wheel-zoom-forbidden clause,
(c) THEN re-adding the constant + listener. A writer who restores a
wheel listener WITHOUT (a)+(b) fails Mode-A Critical. Pinned by
`tests/unit/mapViewportNoWheelImports.test.ts` (3 mechanical cases):
the constant is `undefined`; no `.svelte` file under `src/components`
or `src/routes` contains `onwheel=` / `onWheel`; no `.svelte` or `.ts`
file registers a `'wheel'` listener via `addEventListener`.

**Layer paint order in `<MapUnderlay/>` is FIXED**: (1) PGM bitmap, (2)
LiDAR scan dots (gated on `scanOverlayOn` + freshness + non-null
`mapMetadata`), (3) `ondraw(ctx, worldToCanvas)` parent hook
(pose+trail on Overview; `null` on Edit). A writer reordering layers
fails Mode-A Critical. Pinned by
`tests/unit/mapUnderlayScan.test.ts::layer paint order`.

**Min-zoom semantic** (operator-locked Rule 2): captured ONCE from
`window.innerHeight` at the FIRST `setMapDims(w, h)` call. Subsequent
calls are NO-OPs at the FACTORY level — the `_dimsCaptured` boolean
lives in the factory closure, NOT in the caller (Mode-A M5). A future
writer who routes map-switch through `null → fresh-non-null` cannot
accidentally re-trigger the capture. NO `addEventListener('resize',
...)` anywhere; pinned by `tests/unit/mapViewport.test.ts::no resize
listener registered`.

**Single math SSOT** (Mode-A M4): `mapViewport.svelte.ts` exports the
full pure-helper set as named exports SEPARATE from `createMapViewport`:
`clampZoom`, `applyZoomStep`, `parsePercent`, `panClamp`,
`worldToCanvas`, `canvasToWorld`, `canvasToImagePixel`,
`imagePixelToCanvas`. All take inputs as parameters — no closure leak;
unit tests exercise the math without a Svelte mount. The factory
wraps them with `$state`. `<MapUnderlay/>`'s `bind:this` API
(`worldToCanvas` / `canvasToWorld`) is a passthrough that supplies
`(canvas.width, canvas.height)` and forwards to the pure helper.
`<MapMaskCanvas/>` consumes `viewport` directly (Mode-A M4 — the draft
plan's `underlayWorldToCanvas` prop never shipped); brush math at
non-trivial zoom uses `viewport.canvasToImagePixel(...)` to invert
the underlay's transform around the mask box center, collapsing to
identity at zoom = 1, pan = 0 (T4 fold's DPR-coord pin survives
byte-identical).

**`panClamp` two-case spec** (Mode-A M1 + Parent fold Q7):
smaller-than-viewport axis → centered (pan = 0); larger-than-viewport
axis → clamped so the projected map keeps `MAP_PAN_OVERSCAN_PX = 100`
overlap with the viewport on every side. Eliminates the operator's
"map escapes off-screen" pain.

**Numeric input UX** (Mode-A N1 + N3): `type="text" inputmode="decimal"`
mirrors the OriginPicker idiom (PR #43); locale-comma `1,234` rejected
explicitly; NaN/Inf rejected. BOTH `onchange` (blur) AND `onkeydown`
Enter call `setZoomFromPercent`. Negative input (operator typo) clamps
to `minZoom` per Parent fold T2.

**`MAP_ZOOM_STEP = 1.25`** chosen with rich docstring covering the
alternatives evaluated (1.25× / √2 / 1.5× / 2×) and the
operator-experience trade-off (Mode-A S3). Tests assert the EXACT
value via `applyZoomStep(1.0, +1) === 1.25`.

**Bundle-size delta** (Mode-A S5 — measured, not estimated):
`dist/assets/index-*.js` 118.02 → 123.87 kB raw; **42.76 → 44.85 kB
gzipped (+2.09 kB)**. CSS 25.69 → 27.14 kB raw; 5.06 → 5.30 kB gzipped
(+0.24 kB). Net JS+CSS gzipped: **+2.33 kB**. Within the +5 kB ceiling
documented in PR #43.

Pinned by `tests/unit/mapViewport.test.ts` (34 cases — pure helpers +
factory state + round-trip identity + setMapDims survives null→A→null→B

- no resize listener), `tests/unit/mapZoomControls.test.ts` (11 cases —
  both Enter AND blur commit triggers + locale-comma + clamp + chain
  integration T3), `tests/unit/mapUnderlayScan.test.ts` (5 cases — Rule 3
- Rule 4 single code path + layer paint order S1),
  `tests/unit/mapViewportNoWheelImports.test.ts` (3 cases — wheel-removal
  structural pin T5), e2e `tests/e2e/map.spec.ts` (2 NEW + 1 REPLACED).

## 2026-04-30 09:00 KST — PR-C: Config tab Edit-mode UX

### Added

- `src/lib/constants.ts` — `CONFIG_APPLY_RESULT_MARKER_TTL_MS = 2000 ms`
  (per-row ✓/✗ marker fade-out after Apply resolves).
- `src/stores/config.ts::applyBatch(pending)` + `ApplyBatchResult`
  interface — best-effort sequential PATCH loop with one final
  `await refresh()` + fire-and-forget `refreshRestartPending()`.
  See invariant (z).
- 15 new vitest cases in `tests/unit/config.test.ts` (4 `applyBatch`
  - 5 state-machine + 3 banner + 1 default + 2
    walkthrough/continuation), bringing the file from 4 → 19 cases
    and the suite from 164 → 179 cases.

### Changed

- `src/routes/Config.svelte` (43 → ~290 LOC) — owns `mode` /
  `pending` / `applyResults` / `isApplying`; renders the
  EDIT / Cancel / Apply button group; subscribes to `systemServices`
  for the tracker-inactive banner; renders `<ConfirmDialog/>` for
  Cancel-with-pending (reuses the same component as
  `MapListPanel.svelte`).
- `src/components/ConfigEditor.svelte` (266 → ~263 LOC) — refactored
  to a dumb controlled table: removed `submit()` / `onblur` /
  `busy[]` / `errors[]` coupling to the store-`set()` path; accepts
  `mode` / `isApplying` / `pending` / `setPending` / `applyResults`
  props; renders the new `(default: <value>)` hint under each row's
  Current value; ✓/✗ marker + error text now sourced from
  `applyResults[key]`.
- `src/lib/protocol.ts` — added a comment under
  `ConfigSchemaRow.default` linking to invariant (z). No type
  change.

### Removed

- `src/components/ConfigEditor.svelte::submit()` / `onblur` PATCH
  path / `busy[]` / `pending` local state (hoisted to
  `Config.svelte`). The previous behavior fired a PATCH on every
  input blur, which the operator flagged as accident-prone.

### Tests

- New: `tests/unit/config.test.ts` grew 4 → 19 cases (+15). Total
  suite 164 → 179 cases. All pass (`npm run test:unit`).

## 2026-04-29 — PR-SYSTEM (Track B-SYSTEM): /system page

### Added

- `src/routes/System.svelte` (~210 LOC) — B-SYSTEM page. Four panels
  in CSS-grid auto-fit: CPU-temperature sparkline (panel-cpu-temp),
  Resources mem/disk numbers (panel-resources), Journal tail
  (panel-journal — reuses `<JournalTail/>`), Power buttons
  (panel-power — admin-gated reboot/shutdown wrapped by
  `<ConfirmDialog/>`). Subscribes to the existing `diag` store via
  `subscribeDiag` (invariant (v)); captures the unsub closure and
  calls it in `onDestroy` (invariant (v) + N3 fold). The anon-hint
  string is verbatim mirror of `routes/Local.svelte:169` ("제어 동작은
  로그인이 필요합니다.") per Mode-A M2 fold.
- `tests/unit/system.test.ts` (6 cases — see below).
- `tests/e2e/system.spec.ts` (3 cases — see below).

### Changed

- `src/routes.ts` — register `/system → System.svelte` (1 line +
  1 import).
- `src/components/Sidebar.svelte` — append `{ path: '/system', label:
'System' }` to the `items` array. The Sidebar generates
  `data-testid="nav-system"` automatically from the lowercased label.

### Tests

- New: `tests/unit/system.test.ts` (6 cases):
  - `renders four panels, registers one diag subscriber on mount, and
unsubs on unmount` — N3 fold pin (subscriber count round-trips
    0 → 1 → 0).
  - `sparkline label is derived from DIAG_SPARKLINE_DEPTH × SSE_TICK_MS`
    — T1 fold (no magic literal; survives a future depth bump).
  - `anon viewer sees disabled reboot + shutdown buttons and the
verbatim anon-hint` — M2 fold (string verbatim from
    `routes/Local.svelte:169`).
  - `admin viewer sees enabled reboot + shutdown buttons (no
anon-hint)` — anti-tautology partner of (3).
  - `reboot click opens the confirm dialog; cancel does NOT call
apiPost` — pivot-on-user-choice pin.
  - `reboot confirm-confirm calls apiPost('/api/system/reboot')
exactly once` — M3 fold (anti-typo pin: never `/shutdown`).
- New: `tests/e2e/system.spec.ts` (3 cases):
  - `system: happy path renders all four panels with SSE-fed
resources` — login first (SSEClient token gate), assert
    sparkline + mem/disk + journal-empty render. Sparkline selector
    scoped inside `panel-cpu-temp` per N1 fold.
  - `system: anon viewer sees disabled reboot button + verbatim hint`.
  - `system: sidebar nav link routes to /system`.
- `tests/e2e/_stub_server.py` — NO changes (N4 fold: the four
  endpoints `/api/system/resources`, `/api/logs/tail`,
  `/api/system/reboot`, `/api/system/shutdown` already exist at
  lines 825, 827, 872, 873 from PR-DIAG and PR-B).

### Mode-A folds applied

- M1: kept `DIAG_SPARKLINE_DEPTH = 60` (12 s window). FRONT_DESIGN §C
  "5분" → 12 s deviation called out explicitly; upgrade path is a
  deliberate one-line constant bump in a follow-up PR that updates
  both `/diag` and `/system` labels coherently.
- M2: anon-hint string is verbatim mirror of `routes/Local.svelte:169`.
- M3: confirm-success unit test added (test 6 — anti-typo pin).
- N1: e2e sparkline assertion scoped inside `panel-cpu-temp`.
- N3: `onDestroy` MUST call the `subscribeDiag` unsub closure;
  unit test 1 asserts subscriber count returns to 0 on unmount.
- N4: zero changes to `_stub_server.py` (pre-existing stubs verified).
- T1: sparkline label test reads constants, not literals.

### Bundle size

Pre-PR baseline: `dist/assets/index.js` 74.97 kB / gzip 28.07 kB.
After PR-SYSTEM: 79.27 kB / gzip 28.95 kB. Delta: +4.30 kB raw /
**+0.88 kB gzipped** — well under the 2 KB cap.

### Total frontend test count after PR-SYSTEM

`npm run test:unit` 99 → 105 cases. `npm run test:e2e` 30 → 33 cases
(31 of 33 pass; the pre-existing `config.spec.ts::config: anonymous
viewer does NOT see the Config nav row` failure from commit `265f5f6`
— where Config nav was made anon-visible without updating the test
— is unrelated to this PR and remains red).

### 2026-04-29 — Track B-BACKUP: map-backup history page (P2 Step 2)

#### Added

- `src/routes/Backup.svelte` — `/backup` page. Anon-readable table of
  every `<ts>` snapshot under `cfg.backup_dir`; admin-gated 복원
  button per row + `<ConfirmDialog/>` two-line body (per Mode-A N2
  fold). On success, banner shows `BACKUP_RESTORE_SUCCESS_TOAST`
  (mirrors Track E activate flow per Mode-A N1 fold). Mounts mirror
  `MapListPanel.svelte` structure verbatim.
- `src/lib/constants.ts` — 2 new SSOT constants per Mode-A TB1 fold:
  - `BACKUP_RESTORE_SUCCESS_TOAST` — the success toast wording;
    imported by both `Backup.svelte` AND `tests/unit/backup.test.ts`
    (no literal-string duplication).
  - `BACKUP_RESTORE_OVERWRITE_WARNING` — the dialog warning line.
- `src/lib/protocol.ts` — `BackupEntry`, `BackupListResponse`,
  `RestoreResponse` interfaces + 2 error-code mirrors
  (`ERR_BACKUP_NOT_FOUND`, `ERR_RESTORE_NAME_CONFLICT`). Mode-A M5
  fold: only 2 codes (`backup_dir_missing` was dropped — list returns
  `[]` uniformly).
- `tests/unit/backup.test.ts` — 6 vitest cases: list-newest-first,
  anon-disabled, admin-enabled, confirm flow POSTs once, success
  banner shows imported `BACKUP_RESTORE_SUCCESS_TOAST` (TB1 SSOT
  pin), 4xx surfaces inline `body.err`.
- `tests/e2e/backup.spec.ts` — 3 playwright cases: anon table renders
  with disabled restore, admin restore confirm flow + success toast,
  sidebar nav row routes to `/backup`.
- `tests/e2e/_stub_server.py` — list + restore handlers with in-memory
  `BACKUPS_STATE` (2 canonical-stamp entries seeded). Restore mirrors
  the backend wire shape: 422 on malformed `<ts>` + 404 on unknown +
  200 with `{ok, ts, restored}` on success.

#### Changed

- `src/routes.ts` — 1 new line: `'/backup': Backup`.
- `src/components/Sidebar.svelte` — 1 new row in `items`:
  `{ path: '/backup', label: 'Backup' }`.

#### Removed

- (none)

#### Tests

- 105 → 111 vitest unit cases (+6 from `backup.test.ts`).
- 31 → 34 playwright e2e cases (+3 from `backup.spec.ts`). One
  pre-existing failure (`config.spec.ts: anonymous viewer does NOT
see the Config nav row`) is unrelated — predated this PR (the
  earlier `265f5f6 fix(p4.5)` commit made the Config nav anon-visible
  but left this stale test on disk).
- `npm run lint` clean; `npm run build` produces 29.97 kB gzipped JS
  (was 28.95 kB; +1.02 kB delta — well under the +3 KB Mode-A N3
  budget).

#### No new invariants

Existing coverage suffices:

- (e) no magic numbers — `Backup.svelte` has none (every literal
  resolves to `lib/constants.ts`, a wire-side string in
  `lib/protocol.ts`, or a local iteration bound).
- (j) home-grown router — `/backup` is a static path.
- (l) `<ConfirmDialog/>` reused for restore confirm.

#### Mode-A folds applied

- M1: backend invariant added as `(t)`.
- M3: `FRONT_DESIGN.md:505` `viewer` → `anon` brought into alignment
  with Track F.
- M5: backend list endpoint returns 200 always; SPA expects empty
  `items` for both missing-dir and empty-dir cases.
- N1: success toast wording mirrors Track E (`MapListPanel.svelte:116`).
- N2: confirm dialog body is two-line (`'<ts>'` line + warning line).
- TB1: toast strings exported as constants in `lib/constants.ts`;
  `Backup.svelte` AND `tests/unit/backup.test.ts` import the same
  symbol.

## 2026-04-29 — Track B-SYSTEM PR-2: service observability

### Added

- `src/lib/serviceStatus.ts` (NEW) — `STATUS_TO_CHIP` map + `statusChipClass(s)`
  helper. Single source of the chip-class mapping; both `ServiceCard`
  and `ServiceStatusCard` import from here so visual drift is impossible.
- `src/components/ServiceStatusCard.svelte` (NEW) — read-only-or-admin
  twin of `ServiceCard.svelte`. Renders ActiveState chip + SubState +
  Korean uptime + PID + memory + a collapsible env-vars list. Shows
  Start/Stop/Restart buttons when `isAdmin` is true; POSTs to
  `/api/system/service/<name>/<action>`. 409 transition responses
  render `body.detail` in the lastError slot with auto-dismiss
  (`SERVICE_TRANSITION_TOAST_TTL_MS`). The dismiss timer is cleared
  in `onDestroy`.
- `src/components/EnvVarsList.svelte` (NEW) — collapsible
  `<details>` rendering KEY=VALUE lines. Redacted KEYs (value ===
  `REDACTED_PLACEHOLDER`) get a `(secret)` suffix label and a muted
  italic value class. Keys are sorted alphabetically for deterministic
  rendering.
- `src/stores/systemServices.ts` (NEW) — refcounted polling store.
  `subscribeSystemServices(fn)` opens a `setInterval` at
  `SYSTEM_SERVICES_POLL_MS = 1000` on first subscribe, clears it on
  last unsub. `_arrival_ms` stamped on every successful fetch.
  Last-good `services` array preserved on fetch error so the panel
  shows stale-but-visible (the stale banner triggers on the freshness
  gap).
- `src/lib/protocol.ts` — `SystemServiceEntry` interface,
  `SystemServicesResponse` interface, `SYSTEM_SERVICES_FIELDS` tuple,
  `apiSystemServiceAction(name, action)` path builder, error codes
  `ERR_SERVICE_STARTING` / `ERR_SERVICE_STOPPING`,
  `REDACTED_PLACEHOLDER = "<redacted>"` (mirror of webctl).
- `src/lib/constants.ts` — `SYSTEM_SERVICES_POLL_MS = 1000`,
  `SYSTEM_SERVICES_STALE_MS = 3000`, `SERVICE_TRANSITION_TOAST_TTL_MS
= 4000`.
- `src/lib/format.ts` — `formatUptimeKo(active_since_unix, now_unix)`
  Korean uptime ("1일 2시간"), `formatBytesBinaryShort(n)` base-1024
  short bytes ("51 MiB"). S4 fold rename (was `formatBytesShort`).

### Changed

- `src/components/ServiceCard.svelte` — uses `statusChipClass` from
  `$lib/serviceStatus`. New 409 `service_starting`/`service_stopping`
  branch in the action handler renders `body.detail` (Korean) with
  auto-dismiss after `SERVICE_TRANSITION_TOAST_TTL_MS`. The dismiss
  timer is cleared in `onDestroy`.
- `src/routes/System.svelte` — adds a 5th panel "GODO 서비스" rendering
  one `<ServiceStatusCard/>` per service from the `systemServices`
  store. Subscribes via `subscribeSystemServices` in `onMount`; calls
  the unsub closure in `onDestroy`. Stale-banner uses the existing
  `renderTick` heartbeat against `SYSTEM_SERVICES_STALE_MS`.

### Tests

- `tests/unit/format.test.ts` (NEW, 19 cases) — `formatRemaining` +
  `formatMeters` + `formatDegrees` (existing) + `formatUptimeKo`
  (10 cases including 0초/null/M분 S초/H시간 M분/D일 H시간 boundaries
  - clock-skew clamp) + `formatBytesBinaryShort` (5 cases including
    the S4 fold "51 MiB" corpus pin).
- `tests/unit/serviceStatus.test.ts` (NEW, 3 cases) — chip-class
  drift catch, mapped lookup, fallback for unknown words.
- `tests/unit/systemServices.test.ts` (NEW, 5 cases) —
  open/close on refcount, T4 fold (exactly 4 fetches in 3500 ms),
  T5 fold (timer count === 0 on unmount), `_arrival_ms` stamping,
  last-good preserved on error.
- `tests/unit/system.test.ts` — 5 new cases (services panel renders,
  env (secret) tag visible, admin sees action buttons, anon does not,
  clicking restart POSTs to `/api/system/service/<name>/restart`).
  Existing "renders four panels" updated to "renders five panels".
- `tests/e2e/system.spec.ts` — 3 new playwright cases (services panel
  shows 3 cards + env collapse reveals mixed redacted/non-redacted
  KEYs per T6 fold + admin clicks restart with stubbed 409 → Korean
  toast renders).
- `tests/e2e/_stub_server.py` — `_canned_system_services()` (3-row
  mixed-env corpus), `/api/system/services` GET route,
  `_route_system_service_action()` + POST route plumbing,
  `STUB_FLAGS["system_service_409"]` flag flipped via
  `?stub_svc_409=starting|stopping`.

### Total frontend test count

`npm run test:unit` 111 → 143 cases (+32). `npm run test:e2e`
unchanged at 36 passing (33 → 36 passing, +3 new system cases; the
1 pre-existing failure (`config.spec.ts: anonymous viewer does NOT
see the Config nav row`) is unrelated to this PR).

### Mode-A folds applied

- M1: backend invariants (v) + (w) + (x); SPA invariant (t).
- M2: `FRONT_DESIGN.md` §7.1 7-column row format.
- M3: Korean particle convention (Korean reading) — backend literal pin.
- M4: 7-field dataclass / interface mirror.
- M5: per-service degradation; no 503 wire path.
- N1: stale-banner threshold = 3 × poll cadence (3000 ms).
- N2: panel uses default `.panel` style; no sparkline.
- S4: `formatBytesBinaryShort` rename; base-1024 explicit.
- T4: vitest `vi.useFakeTimers()` asserts EXACTLY 4 fetches in 3500 ms.
- T5: `vi.getTimerCount() === 0` after last unsub.
- T6: playwright stub corpus mixes redacted + non-redacted KEYs.

## 2026-04-30 04:55 KST — PR-A SPA addendum: env_stale badge on Environment summary

### Added

- `EnvVarsList.svelte` accepts an optional `stale: boolean` prop. When
  true, the `<summary>` line renders a small amber "envfile newer —
  restart pending" badge alongside the `Environment (N)` count.
  Operator sees at a glance that they edited `/etc/godo/<svc>.env`
  after the service started, so the displayed env content reflects
  the staged file but the running process is still on the old values.
  CSS uses `--color-status-warn` + `--color-status-warn-bg` tokens
  (with hex fallbacks) so the badge respects theming.
- `protocol.ts::SYSTEM_SERVICES_FIELDS` extended to 8 entries with
  `env_stale`. `SystemServiceEntry` interface gains
  `env_stale: boolean`.

### Changed

- `ServiceStatusCard.svelte` — passes `service.env_stale` through
  to `<EnvVarsList>` as `stale`.
- `tests/unit/system.test.ts` + `tests/unit/systemServices.test.ts`
  - `tests/e2e/_stub_server.py` corpora seeded with `env_stale: False`
    on every `SystemServiceEntry` so the schema parity check stays green.

### Why a badge instead of a top-level "restart pending" pill

The staleness predicate is per-envfile; only the affected service
shows a marker. A top-level page-wide "restart pending" pill would
imply every service is affected. The badge sits next to the count it
qualifies, which keeps the signal local to its source.

### `ServiceStatusCard` lastError UX — auto-dismiss + active-state clear

The original Track B-SYSTEM PR-2 wired auto-dismiss only for the 409
transition gate (`service_starting` / `service_stopping`); every other
error code (`subprocess_failed`, `request_aborted`, network failures,
…) parked in `lastError` indefinitely until the next user click. PR-A
HIL surfaced the failure mode:

- `webctl` self-restart inevitably returns `subprocess_failed`: webctl
  invokes `systemctl restart godo-webctl`, the subprocess captures a
  non-zero exit (the new uvicorn replaces the old before the wait
  completes), and the SPA renders the error sticky-red even though
  the next poll shows the service back to `active(running)`.
- `tracker` restart sometimes outlasts the SPA fetch timeout (mlock +
  map load + AMCL kernel rebuild), surfacing as `request_aborted`
  even though the service comes up cleanly seconds later.

PR-A widens the auto-dismiss path to ALL error codes (5 s, the same
`SERVICE_TRANSITION_TOAST_TTL_MS` the 409 path used) and adds a
`$effect` that clears `lastError` immediately when a polling tick
reports the service `active` and the SPA is not mid-action. The
combination handles both the timer-fires-while-tab-hidden case and
the operator-clicks-and-walks-away case without ever showing a stale
error past the next successful poll.

## 2026-04-30 14:37 KST — Track B-MAPEDIT-2 (Phase 4.5 P2): origin pick (dual GUI + numeric input)

### Added

- `src/components/OriginPicker.svelte` — Sole-owner component for the
  dual-input origin form. Mode toggle (absolute / delta), two
  `<input type="text" inputmode="decimal">` fields with locale-comma
  rejection + magnitude bound + finite check. Exports
  `setCandidate({x_m, y_m})` so the parent route's GUI-pick handler can
  pre-fill (and force mode back to `'absolute'` per T1 fold). Apply
  emits `OriginPatchBody` via the `onapply` callback. Korean delta-mode
  hint reads "Delta: 입력한 값을 현재 origin에 **더해서** 새 origin이
  됩니다." (operator-locked ADD sign convention).
- `src/lib/originMath.ts` — Pure helpers `pixelToWorld(px, py, dims,
resolution, origin)` (ROS Y-flip with the load-bearing `height - 1 -
py`), `resolveDelta(currentOrigin, dx, dy)` (ADD sign convention),
  `resolveAbsolute(absX, absY)` (identity wrapper for shape symmetry).
- `src/lib/protocol.ts` — `OriginMode = 'absolute' | 'delta'` literal,
  `OriginPatchBody` interface, `OriginEditResponse` interface,
  `ERR_ORIGIN_*` mirrors of webctl's protocol constants.
- `src/lib/constants.ts` — `ORIGIN_X_Y_ABS_MAX_M = 1_000.0` (mirror of
  webctl), `ORIGIN_DECIMAL_DISPLAY_MM = 3` (1 mm display rounding),
  `ORIGIN_PICK_REDIRECT_DELAY_MS = 3000`.
- `src/lib/api.ts::postMapOrigin<T>(body)` — typed JSON POST helper
  (distinct from `postMapEdit` which is multipart).
- `tests/unit/originMath.test.ts` — 6 vitest cases: center/top-left/
  bottom-left pixel mappings + negative origin + ADD sign-convention
  pin + identity passthrough.
- `tests/unit/originPicker.test.ts` — 10 vitest cases: mode toggle +
  payload shape, NaN-like rejection, locale-comma rejection, negative
  values allowed, `setCandidate` pre-fill (T1 fold flips mode to
  absolute), payload key shape pin, role-based disable, MapMaskCanvas
  default mode, MapMaskCanvas `'origin-pick'` mode-prop split (T5 fold:
  mask buffer byte-identical + `oncoordpick` called once).
- `tests/e2e/mapEdit.spec.ts` — 3 new playwright cases: admin numeric
  absolute apply → success banner + restart-pending banner; admin
  GUI-pick on canvas pre-fills the picker; viewer cannot apply.
- `tests/e2e/_stub_server.py` — `POST /api/map/origin` handler (admin-
  gated, mirrors backend success path; flips `RESTART_PENDING_FLAG`).

### Changed

- `src/components/MapMaskCanvas.svelte` — Added `mode: 'paint' |
'origin-pick'` prop (default `'paint'`) + `oncoordpick?: (lx, ly) =>
void` callback prop. In origin-pick mode pointer-down emits
  `oncoordpick(lx, ly)` with logical PGM coords and the mask buffer is
  NOT touched — invariant (u) holds (mask state byte-identical to a
  paint-mode no-op). `cursor: cell` for affordance. Drag-paint
  short-circuits in origin-pick mode (no per-move emits).
- `src/routes/MapEdit.svelte` — Wired `<OriginPicker/>` block beside
  the existing brush toolbar. Click-mode toggle checkbox flips
  `MapMaskCanvas.mode` between `'paint'` and `'origin-pick'`. GUI-pick
  callback runs `pixelToWorld` from `originMath.ts` and pushes the
  result into `OriginPicker.setCandidate(...)`. Apply path posts via
  `postMapOrigin`, fires `refreshRestartPending`, and redirects to
  `/map` after `ORIGIN_PICK_REDIRECT_DELAY_MS`.

### Invariants

- Added `(aa)`: `OriginPicker.svelte` is the sole owner of origin-edit
  form state; `MapMaskCanvas` mode-prop split keeps DPR isolation;
  `lib/originMath.ts` is the SPA-side sole-owner of pixel↔world math;
  Origin section is a co-resident block inside Edit sub-tab (NOT a peer
  sub-tab — operator-locked); Y-flip uses `height - 1 - py` (M4 fold);
  delta uses ADD sign convention (operator-locked 2026-04-30 KST).

### Test counts

- vitest: 220 (was 204; +16 new = 6 originMath + 10 originPicker).
- playwright: 38 of 44 passing; the 6 baseline failures (config.spec ×
  4, map.spec hover, system.spec restart-409) are pre-existing flakes
  unrelated to this PR. The 3 new origin-pick cases all pass; 1 fix
  to the existing brush-edit happy-path test (strict-mode locator
  collision after PR #41 added the page-local RestartPendingBanner).
