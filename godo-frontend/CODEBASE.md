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

Entries are archived weekly under [`CODEBASE/`](./CODEBASE/) (ISO 8601 weeks, KST Mon–Sun). The master keeps invariants + Index only; per-week dated entries live in their archive file.

| Week | Date range (KST) | Archive |
| --- | --- | --- |
| 2026-W19 | 2026-05-04 → 2026-05-10 | [CODEBASE/2026-W19.md](./CODEBASE/2026-W19.md) |
| 2026-W18 | 2026-04-27 → 2026-05-03 | [CODEBASE/2026-W18.md](./CODEBASE/2026-W18.md) |

---

## Quick reference links

- Project guide: [`CLAUDE.md`](../CLAUDE.md) — operating rules + agent pipeline + deploy.
- Cross-stack scaffold: [`CODEBASE.md`](../CODEBASE.md) (root) — module roles + cross-stack data flow.
- Frontend design SSOT: [`FRONT_DESIGN.md`](../FRONT_DESIGN.md) — page contracts + route map + auth model + component composition.
- Sibling stacks:
  - Backend (web control plane): [`godo-webctl/CODEBASE.md`](../godo-webctl/CODEBASE.md) — serves the SPA bundle and `/api/*` + SSE; this stack consumes those wire shapes.
  - C++ tracker: [`production/RPi5/CODEBASE.md`](../production/RPi5/CODEBASE.md) — never reached directly; all SPA traffic transits webctl.
- Project state: [`PROGRESS.md`](../PROGRESS.md) (English) · [`doc/history.md`](../doc/history.md) (Korean).
- Most recent shipping: [`CODEBASE/2026-W19.md`](./CODEBASE/2026-W19.md).
- README (build + dev runbook): [`README.md`](./README.md).
