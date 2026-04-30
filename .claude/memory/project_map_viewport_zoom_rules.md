---
name: Map viewport zoom + LiDAR overlay rules (PR β family)
description: Operator-locked rules for the shared map viewport — zoom UX (+/- buttons + numeric input, no scroll wheel), min-zoom = first-load viewport height, LiDAR overlay shared across map-showing tabs.
type: project
---

## Why this exists

Operator HIL feedback 2026-04-30 KST after B-MAPEDIT-2 ships:

> "map overview sub-tab과 map edit sub-tab 모두 맵 확대/축소 기능을 스크롤이 아닌 좌측 위 (+) 및 (-) 버튼, 수치 입력으로 배율 조정이 됐으면 좋겠어. … map overview 탭에서는 맵이 너무 불필요하게 많이 축소되는 것 같아. 최소 축소 비율은 브라우저의 세로 길이로 제한했으면 좋겠는걸? 이 규칙은 map이 보이는 모든 탭에 적용 가능했으면 좋겠어. 코드도 재사용 가능할거야 같은 기능이니"
>
> "지금 map edit 창에서도 LiDAR의 오버레이를 봐야 실제로 매칭 될지 실시간 확인이 가능할 것 같아. 또한 map edit창에서는 지도 확대/축소가 안되는 것이 좀 불편하다."

PR β bundles three operator-locked changes into a single shared-viewport refactor.

## Rule 1 — Zoom UX uniform across all map-showing tabs

**How to apply:** every tab that renders the map MUST use the shared zoom controls:

- **Top-left (+) and (−) buttons** for coarse zoom — discrete stepping (factor of √2 or similar; planner picks).
- **Numeric input field** showing the current zoom percentage (e.g. `100%` ↔ `400%`); operator can type a value directly.
- **No mouse wheel zoom**. Operator-locked: scroll wheel is reserved for page scroll, NOT zoom. Removing wheel zoom is a behavioral change from `PoseCanvas.svelte`'s current implementation.
- **No keyboard shortcut zoom in this PR**. (Could be added later if requested; not in PR β scope.)

Pan (drag with mouse) stays — only the zoom interaction changes.

## Rule 2 — Min-zoom = first-load viewport height (NOT resize-tracking)

**Operator-locked semantic (2026-04-30 KST):** the minimum zoom ratio is computed **once at first map load** based on `window.innerHeight` at that moment. The min-zoom value does NOT update when the operator subsequently resizes the browser window.

**Operator phrasing:** "최소 축소 비율 이건 브라우저 창이 변했을 때 계속 따라서 변하기보다는, 첫 로딩시 브라우저 세로 길이를 참조하도록 했으면 좋겠어."

**Why:** preventing the map from shrinking past the viewport height is the goal ("스크롤이나 마우스 클릭하다 보면 가끔 지도가 다른데로 도망가거나 너무 작아져서") — but tracking resize would create a moving floor that fights operator intent (e.g. operator sets a comfortable zoom, opens DevTools narrowing the window, the map auto-zooms-in unexpectedly). One-shot at first load is the predictable choice.

**Definition:** min-zoom is the zoom ratio at which the map's RENDERED HEIGHT equals `window.innerHeight` measured at first-load time. Below this ratio, the map would be smaller than the viewport vertically — disallowed.

## Rule 3 — LiDAR scan overlay shared between Overview and Edit

The `/map-edit` route (Edit sub-tab) MUST show the live LiDAR scan overlay so the operator can verify scan-vs-map alignment IN REAL TIME during edits. This is the same scan layer that already exists on `/map` (Overview) via `PoseCanvas.svelte` — extract to a shared component so both routes consume the same code.

**Operator phrasing:** "지금 map edit 창에서도 LiDAR의 오버레이를 봐야 실제로 매칭 될지 실시간 확인이 가능할 것 같아."

**Tabs in scope:** `/map`, `/map-edit`. Other tabs do NOT render the map (verified 2026-04-30 — Diag/System/Dashboard/Backup/Local/Login/Config don't show the map).

## Rule 4 — Code reuse mandate

Operator phrasing: "코드도 재사용 가능할거야 같은 기능이니". The zoom controls + viewport state + scan overlay logic MUST live in a single shared component / store. Per-page duplication is a regression (flag in Mode-A review).

**Suggested architecture (planner refines):** a `MapUnderlay.svelte` shared component owns the underlay rendering + scan overlay; a `mapViewport` runes store (or a `useMapViewport.svelte.ts` factory) owns zoom + pan + min-zoom state. Both Map Overview and Map Edit page compose the underlay + add their page-specific overlays (pose marker, brush layer, origin picker, rotation gizmo) on top.

## Out of scope for PR β

- Touchscreen / pinch-zoom gestures (defer until operator requests).
- Keyboard zoom shortcuts (defer).
- Zoom-to-cursor (the +/- buttons zoom around the viewport center; OK).
- Saving the operator's last zoom across sessions (defer).
- Resize-tracking of min-zoom (explicitly EXCLUDED per operator decision).
- B-MAPEDIT-3 rotation (separate PR γ stacked on β).

## Branch + sequencing

- PR β branch: `feat/p4.5-track-b-map-viewport-shared-zoom` (off `main` 2026-04-30 KST after PR #43 + #44 + #45 all merged).
- PR γ (B-MAPEDIT-3 rotation) stacks on PR β after merge.
- Each PR ships independently — separate merges.
