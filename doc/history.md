# GODO 작업 히스토리

> **용도**: 사람이 읽는 날짜별 작업 기록. 기술적 상세는 [PROGRESS.md](../PROGRESS.md) (영문) / [SYSTEM_DESIGN.md](../SYSTEM_DESIGN.md) 참조.
>
> **규칙**:
> - 최신 항목이 위로 오도록 역순 정렬.
> - 세션당 1개 블록. 같은 날 여러 세션이면 `(새벽/오전/오후/저녁/심야)` 등으로 구분.
> - 기술 용어는 영어 원문 유지 (예: seqlock, hot path, SCHED_FIFO — 번역 금지).
> - 구현 세부는 PROGRESS.md 영문 항목과 교차 참조. 여기는 "왜 / 무엇을 결정했는가" 중심.

---

## 2026-05-01 (오후 — 12:30 KST → 14:30 KST, 열네 번째 세션 — issue#8 banner polling backstop + issue#9 mode action-hook + CLAUDE.md §8 Deployment + PR workflow 거버넌스 정리)

### 한 줄 요약

작은 frontend PR 두 건(issue#8, issue#9)과 거버넌스 PR 한 건(#58)으로 banner UX 일관성 정리. issue#5는 깨끗한 cold-start condition으로 다음 세션 이월. 운영자 HIL 중 **emergent vs explicit** 패턴이 드러나 issue#8 + issue#9 사이의 연결고리를 명시적 코드로 잠금.

### 3 PR

| PR | issue | 제목 | 결과 |
|---|---|---|---|
| #58 | governance | docs: thirteenth-session memory bundle + cold-start refresh + CLAUDE.md §8 + issue#N labelling | merged (squash) |
| #59 | issue#8 | restart-pending banner polling backstop | merged (squash) |
| #60 | issue#9 | action-driven mode refresh hook | merged (web UI merge commit) |

### 핵심 발견 — emergent vs explicit behaviour

issue#9는 운영자 HIL 관찰에서 시작됨. PR #59 배포 후 "godo-tracker가 응답하지 않습니다" tracker-down banner가 Start/Restart 누르자마자 일관된 타이밍으로 사라짐. 운영자 인용: "지금 일관되게 ... 메시지 사라지는 속도가 start나 restart 버튼 누르자마자 일관된 타이밍으로 사라짐."

코드 추적 결과 — PR #59이 직접 빠르게 만든 게 아니었음. PR #59의 폴링 backstop은 **별도 store** (`restartPending`)을 갱신하고, App.svelte tracker-down banner가 읽는 `mode.trackerOk`는 `mode.ts`의 1Hz 폴링이 단독으로 갱신함. 운영자가 본 빠름은 hard-reload 직후 mount-time polling phase가 정렬되어 클릭 직후 다음 tick이 잘 잡힌 **emergent property**였음. 깨지기 쉽고 문서화도 안 된 동작.

PR #60은 PR #45 / PR #59의 action-driven refresh 패턴을 `mode.ts`에도 미러해서 emergent 동작을 explicit + deterministic하게 잠금:

- `refreshMode()` export — 즉시 `/api/health` fetch + polling interval phase reset
- `ServiceCard.svelte` + `ServiceStatusCard.svelte`: action() 끝에 `void refreshMode()` 호출 (`refreshRestartPending` 옆에)

결과:
- **Stop 클릭**: banner HTTP RTT 안에 등장 (수십 ms)
- **Restart 클릭**: bounce 동안 transient unreachable 캐치 (운영자한테 "액션 먹었음" 즉각 피드백)
- **Start 클릭**: 여전히 tracker boot time bound. 즉시 fetch는 보통 still unreachable. 이건 polling-cadence로 못 빠르게 함.

**교훈**: 운영자가 "consistent fast" 라고 인지한 동작이 polling-phase 우연일 수 있음. 보존할 가치가 있는 동작이면 명시적으로 잠그자.

### 운영자 잠금 — 거버넌스

1. **`issue#N / issue#N.M` 라벨링 규칙을 cache → SSOT 승격**: 정수+소수점 네이밍이 `NEXT_SESSION.md` "Naming convention reminder"에만 살아있었는데, 운영자 인용: "이건 우리 claude.md에 지침 작성하자. 메모리가 너무 많으면 너가 참조하는 컨텍스트가 너무 많을 것 같아." → CLAUDE.md §6 sub-section으로 이동. (내가 잠깐 만들었던 메모리 entry `feedback_issue_naming_scheme.md`는 삭제 — cold-start 부담 줄이는 운영자 의도에 맞춤.)
2. **CLAUDE.md §8 Deployment + PR workflow 신설**: 최근 PR들 (#54, #55, #56, #58, #59, #60)에 ad-hoc로 흩어져있던 deploy/HIL/merge 절차를 SSOT로 박음. 운영자 인용: "claude.md에 지침사항으로 정리해도 좋겠어. 내가 직접 확인하면서 해보려구." 포함된 것:
   - **stack-deploy 매트릭스** (frontend / webctl / RPi5 tracker / multi-stack)
   - **rsync trailing-slash 함정** — 본 세션에서 직접 운영자가 빠진 그 함정. 정답 / 망가진 형태 둘 다 명시 + 복구 명령
   - 표준 파이프라인 다이어그램, HIL 검증 체크리스트, merge etiquette, pre-deploy 함정

### 운영자 HIL에서 드러난 운영 함정 두 건

- **rsync trailing-slash 함정**: 운영자가 첫 명령어 (정답)를 실행한 직후 trailing slash 붙은 두 번째 명령어를 실행. `--delete`가 첫 명령어가 만든 `dist/` 서브디렉터리를 wipe → SPA 자산이 `/opt/godo-frontend/{index.html,assets,...}`에 직접 놓이고 webctl env-var는 `/opt/godo-frontend/dist/`을 보고 있어서 SPA 깨짐. 복구는 같은 정답 명령 재실행 — `--delete`가 잘못 놓인 top-level 파일들 청소 + `dist/` 재생성. CLAUDE.md §8에 두 형태 나란히 박음.
- **GitHub web UI 기본 머지 스타일**: 운영자가 PR #60을 web UI에서 머지 → 기본값 "Create a merge commit" 적용 → main에 merge commit + feature commit 두 개. PR #58/#59은 `gh pr merge --squash`로 squash됨 → 한 commit. 기능 동일, 히스토리 스타일만 차이. 일단 기록만 하고 액션 없음.

### 다음 세션 큐 (운영자 잠금 — 깨끗한 cold-start로 시작)

1. **issue#5 — Live mode pipelined hint** (P0, 풀 파이프라인). Live ≡ pipelined one-shot driven by previous-pose-as-hint. issue#3 (PR #54)급 아키텍처 영향. 디자인 잠금: `project_calibration_alternatives.md` "Live mode hint pipeline" 섹션.
2. **Far-range automated rough-hint** (P0, issue#5 후속).
3. **issue#4 — AMCL silent-converge diagnostic**.
4. **restart-pending banner non-action 경로 fix** — PR #59이 action 경로는 잡았지만 initial mount + idle polling 경로는 polling/SSE guard flag 필요.
5. **B-MAPEDIT-2 origin reset** (cosmetic).
6. **issue#6 — B-MAPEDIT-3 yaw rotation**.
7. **issue#7 — boom-arm angle masking** (optional).

---

## 2026-05-01 (새벽 ~ 늦은 오전 — 00:00 KST → 12:18 KST, 열세 번째 세션 — issue#3 pose hint UI + install fix + AMCL frame y-flip 잠재 버그 fix)

### 한 줄 요약

issue#3 (pose hint UI) 풀 파이프라인 PR을 끝내고 운영자 HIL에 들어간 순간, 프로젝트 시작 이래 잠복하던 두 개의 production-critical 버그가 동시에 노출됐다. (1) `/etc/godo` ReadOnlyPaths 때문에 SPA Config-tab의 모든 write가 실패 → install fix PR (PR #55) 별도로 처리. (2) PGM raster 순서와 AMCL kernel의 cell convention 불일치로 모든 AMCL 결과가 캔버스 중심 기준 (x, y, yaw) 점대칭 mirror → frame fix PR (PR #56) 별도로 처리. 운영자가 "yaw와 위치가 x축 대칭되어있는 듯한 느낌" 직감으로 root cause를 가리킨 게 결정적. 본 issue#3 σ 튜닝은 frame 정상화 후 운영자가 "hint = 운영자의 강한 명령" semantic으로 lock-in.

### 3개 PR

| PR | issue# | 제목 | 결과 |
|---|---|---|---|
| #54 | issue#3 | initial pose hint UI for AMCL multi-basin fix | 머지 |
| #55 | — | install fix — tracker.toml moved to /var/lib/godo for RW under sandbox | 머지 |
| #56 | — | AMCL row-flip PGM at load to match bottom-first cell convention | 머지 |

### issue#3 풀 파이프라인 — UX 두 번 재구성

Planner → Reviewer Mode-A (1 Critical + 6 Must + 8 Should + 5 Nit) → Writer (6 commits) → Reviewer Mode-B (1 Critical + 4 Must + 10 Should + 5 Nit). 운영자 입력으로 plan을 두 번 재구성:

1. **Blended (A click+drag) + (B two-click) + C numeric companion 제스처** — 처음에 Planner가 옵션 A 단독 + numeric companion으로 추천했는데 운영자가 "A, B 둘 다 같이 녹이는 것은 어때? C도 x,y numeric 옆에 yaw numeric 입력창 함께"라고 지시. drag threshold 8 px로 A/B를 implicit 분기하는 단일 상태 머신.
2. **issue#6 reuse hook 미루기** — 운영자가 "issue#6도 회전 중심 대신 지금처럼 두 점으로 해도 될 것 같은데, 어차피 map edit 탭에 위치를 찍어서 진행할 수 있으니까~~ 이건 그때 가서 생각해보자" → component naming 그대로 (`<PoseHintLayer/>`). issue#6 작업 시점에 reuse 결정.

운영자가 보내준 정량 측정 (one-shot ~0.5 m, Live ~4 m) 데이터가 plan의 σ default 결정 기반.

### Production-critical revelation #1 — install ReadOnlyPaths

운영자가 SPA Config 탭에서 σ 튜닝하려고 했는데 PATCH가 모두 `write_failed`. webctl 로그에 traceback 없음 (handled exception). 직접 UDS로 set_config 보내서 응답 보니 `parent_not_writable: Read-only file system`. mount 보면 `/`는 `rw,noatime`, ncenter shell에서 직접 mktemp `/etc/godo/`도 성공. 결정타: `systemctl show godo-tracker | grep ReadOnly` → **`ReadOnlyPaths=/etc/godo`** + `ProtectSystem=strict`. systemd sandbox가 tracker process 입장에서만 read-only 만든 것. `mkstemp + rename` for atomic TOML write가 EROFS로 실패.

해결 방향: tracker.toml의 default 경로를 `/var/lib/godo` (이미 `ReadWritePaths`)로 이동. install.sh 새 step `[6/8]` — 빈 토ml seed + `/etc/godo/tracker.toml` 마이그레이션. `production/RPi5/CODEBASE.md`의 design separation: `/etc/godo` = read-only system config (env), `/var/lib/godo` = mutable runtime state (TOML, maps, JWT secret).

이 버그는 **잠재(latent)**였다. 프로젝트 내내 SPA Config-tab의 write 경로를 누구도 사용하지 않았기 때문. issue#3가 Tier-2 σ 튜닝을 위해 처음 그 경로를 사용 → 발견.

### Production-critical revelation #2 — AMCL y-flip frame bug

PR #54 머지 + production deploy 후 운영자가 calibrate 결과를 보다가 **"x, y, yaw 모두 캔버스 중심 기준 점대칭"** 패턴을 발견. PGM 검은색 벽과 LiDAR 청록색 scan은 같은 모양인데 180° 회전된 위치. 운영자가 명확히 가설 제시: "AMCL은 정상이고, 반환 좌표 방향이나 부호가 달라서 map pgm과 오버레이가 일치하지 않는 듯 한 느낌이라면?".

코드 트레이스로 확인:
- PGM (P5) raster: row-major top-row-first (byte 0 = top-left).
- ROS YAML `origin: [ox, oy, 0]`: bottom-left pixel의 world coord.
- GODO AMCL kernels (`Amcl::seed_global` at amcl.cpp:92-97, `evaluate_scan` at scan_ops.cpp:84-85): `cells[cy * W + cx]` indexing, treating `(cx, cy=0)` as cell anchored at world `(origin_x, origin_y)`.

**불일치**: kernel은 `cells[0..W-1]`이 BOTTOM row여야 한다고 가정하지만 PGM bytes는 TOP row first. 결과: AMCL 내부 frame이 vertically inverted. 자기 frame 안에서는 self-consistent (likelihood + seed가 둘 다 inverted convention 사용 → 수렴 작동), 하지만 출력 pose가 YAML 의미와 mirror된 frame.

**Fix 옵션 비교**:
- Option X (load-time row flip): `occupancy_grid.cpp::load_map`에서 PGM bytes를 row 단위로 뒤집어 cells 저장. 한 곳만 수정.
- Option Y (per-lookup flip): scan_ops.cpp 등에서 매 cell lookup에 `(height-1) - cy` 추가. 다중 site.

Option Y는 **fix가 안 됨**. 왜냐하면 `build_likelihood_field`의 EDT 패스가 `grid.cells`를 array order로 처리 → EDT 거리 자체가 inverted frame에서 측정됨 → lookup-side flip만으로 cancel 안 됨. **Option X 단일 fix**가 정답.

PR #56 row-flip 추가, 운영자 HIL: 50% 완벽 정합 + 45% 약한 yaw bias + 5% 가짜 basin (multi-basin 잔존 — issue#3가 정확히 처방하는 패턴).

이 버그도 **잠재**였다. 음수 origin이던 시절에는 운영자가 이 frame에 익숙해져서 "정상"으로 받아들임. PR #43 (B-MAPEDIT-2 origin pick) 이후 origin이 ADD convention으로 누적되며 양수 origin이 되자 시각적으로 더 극단화 → 노출.

### 운영자 잠금 결정 (메모리 entries)

세 가지 핵심 lock-in:

1. **Hint = 강한 명령, 약한 prior 아님** (`project_hint_strong_command_semantics.md`). frame 정상화 후 σ sweep: σ_xy ∈ {0.3, 0.4, 0.5} 모두 hint 위치 우세 (likelihood가 hint cloud 못 깸). 운영자: "가까운 곳 두면 실제위치 우세. 이상한 곳 두면 먼 곳 우세. 일단 난 지금의 힌트도 좋은 것 같아. hint 안에 있을 때에는 정밀도가 저하되면 안 된다는 것이 내 생각". σ default 0.5 m / 20° 잠금.
2. **Live mode = pipelined one-shot driven by previous-pose-as-hint** (`project_calibration_alternatives.md` Live mode 섹션). 운영자: "Live 모드도 힌트 기능을 적용해야할 것 같아. 시동만 걸어주면 그 뒤부터는 이전 프레임을 힌트삼아 calibration하는 작업을 pipeline으로 serial하게 진행하는 것이 좋겠어." issue#5 재정의: bare `step()`을 폐기하고 매 tick `converge_anneal(hint=pose[t-1])`로. Live carry-over σ는 inter-tick crane 이동 한계 기반 (작게).
3. **Far-range automated rough-hint — production hint 자동화 방향** (`project_calibration_alternatives.md` Automated rough-hint 섹션). 운영자: "그 뒤에는 hint 자동화 방안 생각하는 것이 좋겠다 — 먼 곳의 점들로부터 러프하게 hint 위치, 방향 잡고 그 hint를 발판삼아 전체 범위에서 다시 정확하게 현재위치 계산. 왜냐하면 먼 곳의 점들은 고정된 스튜디오 지형지물인 확률 높음, 또한 특징점 추출이 빠름". Two-stage: stage 1 = far-range feature → rough hint, stage 2 = AMCL precise. 이전에 적힌 approach A (image match) / B (GPU features) / C (pre-marked landmarks)를 흡수 — far-range pre-filter가 핵심 innovation.

세 결정 모두 카메라 AF 비유의 일관된 framing: 위상차 검출 (빠른 거친 phase) + 콘트라스트 검출 (정밀한 narrow refine) + 수동 초점 (operator override).

### 프로세스 lesson

- **production tracker.toml ↔ branch Config struct 호환성** (`feedback_toml_branch_compat.md`). PR #56 deploy 시 init failed: `/var/lib/godo/tracker.toml`에 PR #54의 σ 키들이 있었고, PR #56은 main에서 분기되어 그 키 모름 → `unknown TOML key` 무한 restart. 해결: hint 두 줄 직접 sed 삭제 후 deploy. 미래 mitigation: pre-deploy hygiene check.
- **restart-pending banner stale recurrence** (`project_restart_pending_banner_stale.md` 업데이트). PR #45가 service-action 직후 새로고침은 cover했지만, **다른 path에서 발생할 때 stale lock**. self-healing 가설 무효 — 매번 reload 필요. 작은 frontend follow-up PR.
- **PR 머지 순서 실수**: 운영자가 PR #54 (issue#3)를 PR #56 (frame fix) 전에 머지. 회복 가능 — PR #56을 새 main에 rebase, conflict 0건, force-push. 안전한 순서는 frame fix 먼저였지만 cosmetic.
- **origin pick 누적 cosmetic**: `04.29_v3.yaml` origin이 SLAM-원본 `[-10.855, -7.336, 0]`에서 4번 ADD pick 누적되어 `[14.995, 26.164, 0]`. frame fix가 origin 부호 무관하게 작동 → 정리는 cosmetic 후속 작업.

### 다음 세션 큐 (운영자 잠금 우선순위)

1. **issue#5 — Live mode pipelined hint** (재정의된 형태). bare step() 폐기 + 매 tick 이전 pose를 hint로 carry. `project_calibration_alternatives.md` Live 섹션 참조.
2. **Far-range automated rough-hint** (NEW direction). two-stage: 먼 점 feature → 거친 hint → AMCL 정밀. operator-friendly automation의 핵심 path.
3. **issue#4 — AMCL silent-converge diagnostic**. issue#5 + far-range 자동화 효과 정량 측정. 이번 세션 HIL data가 baseline.
4. **restart-pending banner real fix** (small frontend PR). polling/SSE guard flag 정상화.
5. **B-MAPEDIT-2 origin reset** (cosmetic). yaml origin을 SLAM-원본 또는 운영자 의미 있는 값으로 reset.
6. **issue#6 — B-MAPEDIT-3 yaw rotation** (deferred). 운영자가 "그때 가서 생각해보자" 했던 reuse 시점 검토.
7. **issue#7 — boom-arm angle masking** (optional, issue#4 결과에 따라).

---

## 2026-04-30 (오후 ~ 심야 — 14:00 KST → 22:00 KST, 열두 번째 세션 — 9 PR: B-MAPEDIT-2 origin pick 풀 파이프라인 + Map viewport 공유 + HIL 사이클로 발견된 5건 hotfix)

### 한 줄 요약

B-MAPEDIT-2 (원점 평행이동) 풀 파이프라인 PR (#43)으로 시작 → 운영자 HIL → 4건의 추가 PR → 다시 PR β (Map viewport 공유 인프라) 풀 파이프라인 → HIL → 또 다시 3건의 hotfix. 한 세션에 9 PR이 무더기로 처리됨. 더 중요한 발견: 운영자가 HIL 중 두 가지 다른 좌표 문제(AMCL 정확도 vs frame 재정의)를 같은 도구로 풀려는 mindset 오류 의심을 surface, 그 직교성을 메모리에 잠금. test4/test5 스크린샷으로 AMCL multi-basin yaw 문제 발견 (one-shot 5° vs live 90° 같은 물리 위치) — issue#3 (pose hint)이 다음 세션 P0.

### 9개 PR

| PR | issue# | 제목 | 결과 |
|---|---|---|---|
| #43 | — | B-MAPEDIT-2 origin pick (dual GUI + numeric, ADD 부호) | merged |
| #44 | — | B-MAPEDIT-2 minor cleanup | merged |
| #45 | issue#1 | service action 후 restart-pending banner refresh | merged |
| #46 | issue#2 | shared map viewport + zoom UX 통일 + Map Edit LiDAR 오버레이 | merged |
| #47 | issue#2.1 | Last pose card + Tracker controls (stacked PR — base 문제로 dead branch에 머지됨) | merged 표시지만 main 미적용 → #51로 복구 |
| #48 | issue#2.2 | panClamp single-case + pinch zoom (HIL hotfix) | merged + dd348ba 직커밋 sensitivity follow-up |
| #49 | — | branch-check feedback memory (process violation 잠금) | merged |
| #50 | issue#2.3 | Map Edit overlay/pan/pinch (PR #46 HIL hotfix — mapCanvas 중복 제거) | merged |
| #51 | issue#2.4 | Map page common header — TrackerControls/LastPoseCard/ScanToggle 통합 + Overview 블록 순서 | open |

### B-MAPEDIT-2 (PR #43): 운영자 ADD 결정의 무게

기획 단계에서 Mode-A 리뷰어가 "delta 부호 규칙이 spec memory에 모호하다 — operator-blocking" 경고. SUBTRACT 가설은 worked example과 모순. ADD로 운영자 확인 받고 잠금. 운영자 표현: "실제 원점 위치는 여기서 (x, y)만큼 더 간 곳". 이 결정이 모든 후속 ADD-기반 도구의 출발점 (B-MAPEDIT-3 yaw rotation도 동일).

### PR β (#46): 공유 viewport + 4가지 운영자 잠금 규칙

`.claude/memory/project_map_viewport_zoom_rules.md`에 4 규칙 잠금:
1. zoom UX 통일 — 좌측 위 (+/−) 버튼 + 숫자 입력. **마우스 휠 zoom 금지**
2. min-zoom = 첫 로딩 viewport height (resize 추적 X)
3. LiDAR 오버레이 /map ↔ /map-edit 공유 (같은 코드)
4. 코드 재사용 강제 — 페이지별 중복은 regression

5개 commit으로 phasing (scan overlay 추출 → viewport factory → zoom controls + 휠 제거 → MapEdit 통합 → docs). 273 vitest pass.

### HIL → 3건 hotfix in PR β의 한 라이프사이클

PR #46 deploy 직후 운영자 보고:
- **panClamp 버그**: `mw > viewportW − 2·OVERSCAN`에서 lo/hi 바운드 역전 → 매 mousemove가 한쪽 edge로 snap, 못 돌아옴. → PR #48에서 단일 대칭 공식으로 재작성.
- **핀치 줌 부재**: 마우스 휠 제거하면서 트랙패드 핀치도 같이 죽음 → onwheel + ctrlKey 게이트로 구별. → PR #48.
- **핀치 감도 지나침**: 한 제스처에 1.25^20 ≈ 86× 폭주 → fractional factor (deltaY/100 = 1 step). → dd348ba 직커밋 (process violation, 후술).
- **MapMaskCanvas 중복 mapCanvas**: PR β에서 이 canvas 삭제 누락 → underlay PGM + scan을 가림. → PR #50에서 제거 + transform: scale로 viewport 추적.

각 fix가 별도 PR로 풀 파이프라인 검증 거치지 않고 바로 패치된 건 운영자 통증이 즉각적이었기 때문. 다음 세션부터 HIL feedback도 plan/review 거치는 절차로 환원.

### Mindset orthogonality lesson (가장 중요한 발견)

세션 중반, 운영자가 mindset 오류 의심 surface:
> "지도의 레이아웃과 현재 라이다의 오버레이가 서로 완전히 겹치지 않는 이유가 어디에서 오는 것인지 헷갈린다. 1번과 2번이 다른 것인지, 아니면 같은 것인지."

함께 풀어내며 두 문제가 **직교**임을 명확히:
- **Problem 1 (AMCL 정확도)**: 시각적 mismatch는 AMCL이 잘못된 basin에 수렴한 결과. issue#3 (pose hint), issue#4 (silent-converge 진단), issue#5 (pipelined K-step)로 처방.
- **Problem 2 (frame 재정의)**: UE에 가는 (x, y)가 운영자 멘탈 좌표계와 어긋남. B-MAPEDIT-2 (issue 완료) + B-MAPEDIT-3 (issue#6)로 처방.

같은 시각화에서 두 문제가 함께 보이지만 도구는 완전히 다름. `feedback_two_problem_taxonomy.md`로 영구 잠금.

### test4/test5 — multi-basin yaw 결정적 증거

운영자가 같은 물리 위치에서 캡처한 두 스크린샷:
- test4 (one-shot): 청록 scan ~5–10° 시계방향 회전 (vs PGM)
- test5 (live): 청록 scan **~90° 회전** (PGM의 오른쪽 세로벽이 가로선으로 표시됨)

scan 형상은 두 모드 동일. 즉 LiDAR는 같은 방을 보고 있고, **AMCL이 같은 입력에 대해 90° 다른 yaw 답을 내놓는 중**. T자 스튜디오 + 낮은 feature density에서 multi-basin yaw가 활성. `σ_xy = 0.01 m, converged` 표시도 거짓 positive — particle filter가 한 basin에 모이긴 했지만 진짜 위치에서 멀리 떨어진 곳.

→ issue#3 (pose hint)이 P0. 운영자가 "대략 여기" 클릭 → particle 초기 spread 좁음 → 90° basin 진입 자체 차단. issue#4 (진단 metric)로 효과 측정. `project_amcl_multi_basin_observation.md`로 잠금.

### Process violation: dd348ba 직커밋

핀치 감도 sensitivity hotfix를 만들면서, 운영자가 PR #48 deploy 위해 `git checkout main` 한 게 같은 Pi의 내 working tree까지 silently 전환시킴. branch 확인 안 하고 commit + push → origin/main 직접 푸시, PR review 우회. 운영자 Option C 선택 (작은 docs-grade hotfix, 이미 deploy됨, 그대로 두고 lesson만 lock). `feedback_check_branch_before_commit.md`로 잠금 (PR #49) — `git branch --show-current` + commit-output `[branch <hash>]` 토큰 확인 필수.

### PR #47 dead-branch 문제

PR #47이 base = `feat/p4.5-track-b-map-viewport-shared-zoom` (PR #46 feat branch)로 열림. PR #46이 main에 merge되면서 feat branch가 닫혔는데, GitHub은 PR #47 base를 자동 retarget 안 함 → PR #47이 닫힌 feat branch에 merge됨, main 미도달. GitHub에선 "merged"로 표시되지만 실제 main엔 변경 없음. 이번 세션 끝에 발견되어 PR #51 (issue#2.4)이 #47의 컴포넌트 복구 + 새 layout을 함께 처리.

**향후 stacked PR 규칙**: base 가 feat-branch면 (a) parent merge 직후 main으로 retarget OR (b) parent merge까지 stacked PR open 안 함. 둘 중 하나로 강제.

### 다음 세션 큐 (운영자 잠금 우선순위)

```
issue#3  pose hint (multi-basin 직격, P0)
issue#4  AMCL silent-converge 진단 (issue#3 효과 측정용)
issue#5  pipelined K-step Live AMCL (per-scan 안정성)
issue#6  B-MAPEDIT-3 yaw rotation (AMCL 안정화 후)
issue#7  boom-arm angle masking (선택, issue#4 결과 따라)
```

---

## 2026-04-30 (늦은 오전 ~ 이른 오후 — 10:08 KST → 13:30 KST, 열한 번째 세션 — 4 PR: B-MAPEDIT brush + prod hotfix 2건 + Map sub-tab 리팩터 + 계층적 SSOT doc reorg)

### 한 줄 요약

**Track B-MAPEDIT (브러시 erase + 자동 백업 + restart-required) 단일 PR 출하 + HIL 중 prod 회귀 2건 잡아 hotfix PR 머지 + 운영자 두 후속 요청 (Map Edit 를 Map 탭의 sub-tab 으로 이동, 그리고 root `CODEBASE.md`/`DESIGN.md` + cascade rule 으로 doc 계층화) 까지 한 세션에 4 PR 출하.** 두 회귀 모두 PR-A2 (열 번째 세션) 가 가르쳐준 "테스트는 그린, prod 는 깨짐" 의 cross-language drift 패턴 — 두 번째 사례 + 세 번째 사례 (`python-multipart` + `getMaskPng` alpha) 가 같이 나오면서 구조적 gap 으로 확정.

> 기술 상세는 [PROGRESS.md 2026-04-30 late morning 블록](../PROGRESS.md#session-log) 참조.

### 왜 이렇게 결정했는가

#### B-MAPEDIT (PR #39) — Mode-A 폴드 14항목 + Mode-B F1 폴드, 단일 PR

운영자 HIL 결과 일관성을 보장하기 위해 plan §8 Mode-A 폴드의 모든 항목 (M1-M3 mandatory + S1-S3 + T1-T4 + N1-N3) 을 writer 단계에서 선반영. plan-time `(y)` invariant letter 가 PR-B/PR-C 머지로 stale 해진 상태였고 writer 가 main 을 다시 확인하고 `(aa)` 로 자동 시프트 — Mode-B 가 이를 ACCEPT. F1 (`restart_pending` directory mode 0750→0755) 는 docstring 약속과의 drift 였어서 Mode-B fold 로 즉시 반영. F2 (`mask_decode_failed` 네이밍) 는 wire surface 확장이 필요하고 SPA 자체 송신 경로에선 트립되지 않아 follow-up 으로 deferred.

#### Map Edit 구조 — origin pick + rotation 은 별도 PR 로 분리

운영자 요청: "보정값을 GUI 와 더불어 수치를 입력해서도 반영 가능하게". 첫 응답 시점에 plan 확장과 별개 PR 분리 두 안 제시 → 운영자 결정: **각각 따로 분리해서 진행** + B-MAPEDIT-2 (origin pick) 에 dual-input 포함. spec 메모리 `project_map_edit_origin_rotation.md` 신규 생성, B-MAPEDIT 본 PR 와 같은 브랜치에서 docs-only 커밋 (`0d2c1ec`) 으로 선반영. 향후 B-MAPEDIT-2 / B-MAPEDIT-3 plan 작성자가 single-input 으로 제출하면 spec 위반으로 회귀 표시.

#### prod 회귀 2건 — cross-language drift 의 구조적 gap

**Fix 1 (`python-multipart` 누락)**: Starlette `request.form()` 가 런타임에 `python-multipart` 필요. dev `.venv` 는 transitive 로 들어와 있어서 11/11 통합테스트 그린, prod `--no-dev` 는 빠짐. writer + Mode-B 둘 다 "Starlette 1.0 자체 multipart parser" 라는 잘못된 주장 그대로 통과. **dev 그린 ≠ prod 그린** 이라는 메타-교훈.

**Fix 2 (`getMaskPng` 알파=255 만개)**: Fix 1 풀고 첫 Apply 가 활성 PGM 전체를 FREE 로 덮음. 원인: `MapMaskCanvas.svelte::getMaskPng()` 가 unpainted 픽셀에도 alpha=255 를 깔아서, 백엔드의 alpha-as-paint 분기 (`map_edit.py:177-181`) 가 모든 픽셀을 paint 로 해석. 운영자 데이터 손실은 **0** — backup-first ordering 이 백업 먼저 만들어 둬서 즉시 복구. 회귀 테스트는 `putImageData` spy 로 round-trip 검증. 기존 test pass 가 못 잡은 이유: 캔버스 shim 의 `toBlob` 가 고정 4바이트 placeholder 만 반환 → 진짜 mask round-trip (JS getMaskPng → PNG → 백엔드 Pillow 디코드) 이 end-to-end 로 한번도 안 돌아봄.

#### Degenerate-metric audit 메모

활성 PGM 이 100% FREE 였을 때 AMCL one-shot 이 `σ_xy=0` 으로 "수렴" 보고하면서 `pose.yaw` 는 165° → 135° → 333° → 292° 로 2초 간격 wildly bouncing. 운영자 관찰 ("맵이 없어 보이는데도 one shot 에서 converge 하는 듯한 모습이 신기해") → Parent 설명: zero likelihood gradient → 모든 particle 동률 가중치 → resampling 이 차이 못 만들어 → particle collapse → 분산 0 → 수렴 메트릭만 trivially 통과. 운영자가 "비슷한 silent 버그를 audit 하자" 라 결정 → 메모리 entry `project_silent_degenerate_metric_audit.md` 에 10개 후보 (AMCL one-shot/Live/D-5, FreeD smoother, UE 60Hz publisher, webctl /api/health, restart_pending sentinel, map activate symlink, backup list, systemd active, diag SSE) 영구 저장. B-MAPEDIT-2 출하 후 audit 진행.

#### 백엔드 + 프론트엔드 분리 deploy 의 함정

이번 세션의 dispatch 실수 — main 머지 후 frontend `npm run build` + rsync 만 하고 webctl src 의 rsync 를 빠뜨림. 9:57 (머지 전) app.py 가 prod 에 그대로 → `map/edit` 라우트 자체가 없어 405. 다음부터는 deploy 스크립트화 검토 (현재는 README 의 manual rsync 절차).

#### Map Edit 메뉴 위치 — Map 페이지 sub-tab 으로 이동 (PR #41)

운영자 HIL 직후 결정 (12:30 KST): Map Edit 를 사이드바 top-level 항목에서 Map 페이지의 Edit sub-tab 으로 이동. 패턴은 System 탭의 Processes / Extended resources sub-tab (PR-B). URL 시맨틱은 두 가지 선택지 중 **URL-backed** (`/map` → Overview, `/map-edit` → Edit) 채택 — System sub-tab 은 session-scoped (모니터링용) 라서 component-local 이 맞지만 Map Edit 는 destination-scoped (chat 으로 받은 `/map-edit` 링크, e2e 직접 navigate, post-Apply 후 `/map` 으로 redirect) 라서 refresh + back-button + external bookmark 모두 자연스럽게 동작해야 함. 6 files / +121 / -16, 백엔드 0 LOC, 기존 e2e + unit 테스트 anchor 그대로 유지 (data-testid 보존).

#### Doc 계층화 — root CODEBASE.md + DESIGN.md + cascade rule (PR #42)

운영자 분석 (11:50 KST): "SSOT 문서들이 여기저기 흩어져 있고 내용도 많아서 새 세션 cold-start 가 복잡함. SSOT = RAM, NEXT_SESSION = cache 비유. 계위로 정리하고 cascade 수정 룰을 박자". 두 가지 가드레일 합의:

1. **루트 CODEBASE.md 는 scaffold + 모듈 역할 + cross-stack 데이터흐름만**. 인배리언트 텍스트 (per-stack `(a)..(z)..` 항목들) 는 **절대 루트로 복사 안 함**. 안 그러면 두 군데 invariant 가 drift.
2. **NEXT_SESSION.md 는 cache, 3-step 흡수 루틴 강제** — task 흡수 후 PROGRESS / history / CODEBASE / memory 에 기록 → NEXT_SESSION 항목 prune. 세션 종료 시점에 통째로 재작성, 중간 수정 금지.

루트 `CODEBASE.md` (192 LOC) = 3-stack overview + per-stack 모듈 역할 + cross-stack 데이터흐름 다이어그램 + per-stack CODEBASE.md 링크. 루트 `DESIGN.md` (70 LOC) = SYSTEM_DESIGN + FRONT_DESIGN TOC + "어떤 결정이 어디에 land 하는가" 표. CLAUDE.md §3 Phases 는 stale 했음 ("Phase 1 ◄ current" 인데 실제는 Phase 4.5 P2) — refresh. §6 에 cascade rule + NEXT_SESSION cache role 두 룰 추가. 메모리 entry 2개 (`feedback_codebase_md_freshness.md` 확장 + `feedback_next_session_cache_role.md` 신규).

핵심: Mode-B reviewer 가 root↔leaf 모순/누락을 Critical 로 처리 — cascade 강제력의 출처. half-cascade 금지.

### 산출물

- 4 PR merged: #39 (`7fd7a26`), #40 (`9c5166e`), #41 (`9322644`), #42 (`787c986`).
- main = `787c986`.
- Test baselines: backend 615 → 628 (+13), frontend unit 197 → 204 (+7), e2e 37 → 40 (+3). PR #41/#42 zero test deltas (UX 리팩터 + docs).
- HIL 검증: 페인트 3회 (장애물 2회 + 빈 공간 1회) 모두 백업 스냅샷 4개 (`20260430T031846Z` 복구 base + `033105Z`/`033202Z`/`033221Z` 정상 edit 3개), 활성 PGM 히스토그램 정상 (occupied 1386 / unknown 5258 / free 5004 — 벽 보존), tracker 로그 yaw tripwire 0건. PR #41 의 sub-tab 리팩터 도 HIL 검증 — 사이드바 정리 + URL 보존 + `/map-edit` 직접 진입 모두 정상.
- 새 메모리 entry 4개: `project_map_edit_origin_rotation.md` (Map Edit 가족 dual-input spec), `project_silent_degenerate_metric_audit.md` (10개 audit 후보), `feedback_codebase_md_freshness.md` (cascade rule 추가), `feedback_next_session_cache_role.md` (3-step 흡수 루틴).
- 새 root doc 2개: `CODEBASE.md`, `DESIGN.md`.

### 결정 요약

- B-MAPEDIT 가족 (brush + origin + rotation) 은 3 PR 로 분리. brush 는 본 세션 출하 (#39 + #40 hotfix); origin (B-MAPEDIT-2) + rotation (B-MAPEDIT-3) 은 별도 PR + dual-input 스펙 mandatory.
- Map Edit 메뉴 위치 = Map 탭의 Edit sub-tab. URL-backed 시맨틱 (System sub-tab 은 component-local 인 점과 분리 — 의도적).
- Doc 계위 살아남: root `CODEBASE.md` + `DESIGN.md` 가 navigation hub, per-stack 파일이 SSOT. cascade rule 이 두 레벨의 분리를 보호 (Mode-B 가 root↔leaf 모순을 Critical 로 처리).
- NEXT_SESSION.md = cache, 세션 종료 시 통째로 재작성. 중간 수정 금지. 3-step 흡수 루틴이 standard practice.
- cross-language wire drift 는 1차 (PR-A2) → 2/3차 (PR #40) 로 발현 회수 늘어남. 구조적 gap 확정 → wire-shape SSOT pin (regex-extract) + canvas-PNG round-trip CI 가 다음 세션 우선순위 #3.
- silent degenerate-metric 패턴 audit task 화 (#6). B-MAPEDIT-2 출하 후 schedule.
- 다음 세션 #1 작업: **B-MAPEDIT-2 origin pick (dual-input GUI + numeric)** — ~150 LOC, spec memory 에 박혀있음.

---

## 2026-04-30 (오전 — 06:07 KST → 10:08 KST, 열 번째 세션 — PR-A1 + PR-A2 + PR-B + PR-C 4 PR 한 세션 처리)

### 한 줄 요약

**한 세션 안에 4개 PR 머지 (#37 #35 #36 #38) 완료.** PR-A 후속 폴리시 (PR-A1 = login1 polkit rule for reboot/shutdown, PR-A2 = config keys envelope unwrap) 두 작은 hotfix + 큰 feature 두 개 (PR-B = System tab process monitor + extended resources sub-tabs, PR-C = Config tab View/Edit safety gate + best-effort Apply). 두 큰 feature 는 planner → Mode-A → writer → Mode-B 풀 파이프라인을 백그라운드로 병렬 실행.

> 기술 상세는 [PROGRESS.md 2026-04-30 morning 블록](../PROGRESS.md#session-log) 참조.

### 왜 이렇게 결정했는가

#### PR-A1 — login1 polkit rule (Reboot/Shutdown 버튼이 안 됨)

PR-A 머지 직후 운영자 HIL: SPA System tab 의 "Reboot Pi" / "Shutdown Pi" 버튼이 HTTP 500 `subprocess_failed`. PR-A 의 polkit rule 은 `org.freedesktop.systemd1.manage-units` (start/stop/restart) 만 허용했는데, `shutdown -r/-h +0` 은 systemd-logind 의 D-Bus API 경유 → `org.freedesktop.login1.{reboot,power-off}*` 라는 다른 action family. webctl 가 non-login systemd service 라 `*-multiple-sessions` / `*-ignore-inhibit` variant 까지 다 도달 가능 — 6개 variant 전부 allow. halt / suspend / hibernate 는 의도적으로 제외. CODEBASE invariant `(o)` 가 두 룰 (manage-units + login1) 의 lock-step discipline 으로 확장됨.

#### PR-A2 — Config keys envelope unwrap (latent wire-shape drift)

운영자 질문: "Config 탭이 트래커 켜져 있는데도 모두 — 표시." 라이브 진단: `curl /api/config` 가 정상 응답 (`{"keys":{"amcl.foo":1,...}}`) — 즉 webctl→tracker 통신은 살아있음. 그런데 SPA 가 못 받는 게 문제 → 추적해 보니 wire-shape drift.

C++ `json_mini.cpp:374::format_ok_get_config` 는 의도적으로 `{"ok":true,"keys":{...}}` 로 envelope wrap (스키마 endpoint 의 `format_ok_get_config_schema` 와 일관). 그런데 Python `project_config_view` 는 `ok` 만 strip 하고 `keys` 를 통과시킴 → SPA 의 `current = {"keys":{...}}` → `current["amcl.foo"]` → undefined → "—" 렌더링. **PR-CONFIG-β 출시 이후 계속 잠복**했던 버그. 잡히지 않은 이유: 단위 테스트 + 통합 테스트 둘 다 가짜 UDS 응답을 평탄한 (잘못된) shape 으로 mock — 픽스처가 production wire 와 drift.

수정: `project_config_view` 가 `keys` envelope 를 unwrap; 픽스처 4개를 실제 C++ wire shape 으로 reshape; `uds_client.get_config` docstring 정정. **C++ 변경 0** — projection layer 가 SPA 의 평탄-dict 계약을 만족시키는 올바른 위치.

이 사건의 메타-교훈: cross-language wire 의 양쪽 mock 이 모두 잘못되면 "테스트 통과 + 라이브 깨짐" 이 가능. 다음 세션에 cross-language SSOT pin (PR-B 의 `test_godo_process_names_match_cmake_executables` 같은 regex-extract 검증) 을 wire-shape 에도 적용 검토할 만함.

#### PR-B — System tab process monitor + extended resources

운영자 우선순위 #1. 메모리 spec (`project_system_tab_service_control.md`) 기반 + 작업 중 운영자 추가 결정으로 scope 일부 변경:

1. **GPU 모니터링 drop**: V3D `gpu_busy_percent` 가 RPi 5 + Trixie firmware 에서 unreliable (raspberrypi/linux #7230). 운영자 결정: "안 보여줘도 돼". CPU temp 는 기존 System tab CPU 스파크라인이 이미 처리하므로 GPU temp 도 불필요. → `EXTENDED_RESOURCES_FIELDS` = 6 필드 (no gpu_pct, no gpu_temp_c).
2. **Whitelist 범위 반전**: 원래 plan 은 GODO 5개 프로세스만 filter. 운영자 결정: "RPi5 에서 실행되는 모든 프로세스를 모니터링". → enumerate every PID, classify per-row (`general` / `godo` / `managed`). Kernel thread (cmdline 빈) 만 제외. duplicate_alert 는 GODO 만 적용 (bash shell 2개는 정상).
3. **Row styling — typography over background shading**: 운영자 처음엔 옅은 음영 제안 → reviewer 가 dark-mode contrast 문제 지적 → 양쪽 mode 다 텍스트 weight + color 로 강조 (managed 3개는 amber `--color-status-warn` accent + bold). 기존 CSS variable 만 사용 — 새 hex 토큰 없음.
4. **`i` 정보 popover**: 운영자가 "godo-irq-pin 은 oneshot 이라 PID 가 안 보이는 게 정상" 같은 운영 지식을 추가 콜라잡 안 하고 SPA 안에서 알게끔. HTML5 `<details><summary>` fallback (popover dep 추가 안 함).
5. **Filter UI**: 텍스트 검색 + "GODO only" 토글. 둘 다 client-side (백엔드 query param 추가 없음).
6. **컬럼 추가**: `user` (uid → username via stdlib `pwd`) + `state` (R/S/D/Z/T/I/W/X). 운영자: "그 정보도 있으면 좋겠어".

writer 가 9개 must-fix Mode-A fold + 5개 Mode-B fold 를 모두 plan-fold 로 흡수해서 단일 PR (3 commits squashed) 로 머지. 모든 cross-language SSOT pin 테스트 그린.

#### PR-C — Config 탭 View/Edit safety gate

운영자 발견: 현재 Config 탭은 admin 이 입력 박스에 타이핑하면 blur 시점에 즉시 PATCH. "실수로 값이 변경되는 것을 방지하려면 EDIT 버튼이 필요할 것 같아". 운영자 spec 으로 `project_config_tab_edit_mode_ux.md` 영구 저장.

핵심 결정 3개:

1. **Best-effort sequential Apply (not all-or-nothing)**: "다 해보고 안되는 것만 포기". 백엔드 0 LOC (기존 `PATCH /api/config` single-key endpoint loop). atomic bulk verb 추가는 C++ UDS verb 까지 수정해야 해서 ~150 LOC; tracker 는 키 단위 적용이라 partial-apply 가 일관성 깨지지 않음 (operationally independent keys).
2. **Cancel never PATCHes**: 클라 측 pending 만 폐기. 이미 적용된 키는 tracker 에서 새 current 가 됐으므로 자연스럽게 보존. reverse-PATCH 는 "rollback PATCH 도 실패 가능 → 일관성 깨짐" 이라 의도적 회피. 운영자 walkthrough 시나리오 (3개 중 2개 성공, 1개 실패 → Cancel) 가 정확히 이 동작을 자연스럽게 만족.
3. **Default 값 표시**: `(default: <row.default>)` muted hint — `ConfigSchemaRow.default` 가 이미 wire 에 있어서 프론트엔드만 작업.

writer 의 첫 commit 후 Mode-B 가 실제 UX 버그 발견: 진행 라벨 `적용 중… (k/N)` 가 항상 `0/N` 으로 렌더링. `applyProgress.k` 가 한 번 0 으로 set 되고 increment 안 됨. 가장 단순한 fix = 카운터 자체 drop 하고 `적용 중…` 만 표시 → follow-up commit `94dc4a1` 으로 정리. operator 요청 라벨 ("k/N 진행률") 자체가 spec 에 명시 안 됐고, broken 상태 출하보다 단순 "적용 중…" 가 정직.

#### Tooling 측면 — 한 세션에 4 PR 의 의의

이전 마라톤 세션 (#34 PR-A) 에선 한 PR 에 9개 fix 를 fold 한 것이 "조밀한 작업" 의 표본이었다면, 이번 세션은 정반대의 표본 — 각 PR 이 독립 변수 (다른 file group, 다른 invariant letter, 다른 스토리) 라 분리가 옳음. PR-A1/A2 는 작은 hotfix → planner/reviewer 생략하고 직접 writer (Pipeline short-circuit, `feedback_pipeline_short_circuit.md` 정책 적용). PR-B/C 는 feature 규모 → 풀 파이프라인. 4 PR 모두 backgound 에이전트 + 분리 브랜치 패턴으로 충돌 없이 진행.

PR-C 가 PR-B 머지 후에 머지될 때 invariant letter (z) → (z) 그대로 유효 (PR-B 가 (y) 점유). 충돌 1건 (`godo-frontend/src/lib/constants.ts` 의 추가 라인) 은 rebase 로 해결 — 양쪽 블록 다 keep.

### 산출물

- 4 PR merged: #37 (`43e100c`), #35 (`b701f83`), #36 (`9c52446`), #38 (`5d3cb95`).
- main = `5d3cb95`.
- Test baselines: backend 521 → 615 (+94 — PR-B 의 76개 + PR-A2 의 18개 reshape), frontend unit 164 → 197 (+33 — PR-B 의 18개 + PR-C 의 15개), e2e 변화 없음.
- HIL 검증 완료: install.sh 재실행 (polkit count 13→14), webctl 재시작 후 `/api/health` ok, frontend dist 재배포 후 SPA 새로고침 — Config 탭 37 키 모두 라이브 값 + EDIT 모드 동작, System 탭 Reboot/Shutdown 200 OK, Processes / Extended resources sub-tab 정상.
- 새 메모리 entry 1개: `project_config_tab_edit_mode_ux.md` — PR-C 운영자 결정 근거 영구 저장 (Cancel-no-PATCH 이유 + best-effort 이유).

### 결정 요약

- 한 세션에 4 PR 처리는 background agent 파이프라인 + branch isolation 으로 가능. 다음에도 독립적인 작업 묶음에선 같은 패턴 적용 가능.
- PR-A2 (config keys unwrap) 가 가르쳐주는 메타-교훈: cross-language wire 의 양쪽 mock 이 동시에 잘못되면 잠복 가능. 다음 세션에 wire-shape SSOT pin (regex-extract 검증) 적용 검토.
- PR-B 의 GPU 드롭 + 모든 프로세스 enumerate 으로 방향 전환은 운영자 라이브 의도와 부합. spec 메모리는 항상 plan 보다 우위 — plan 작성 도중 spec 이 바뀌면 plan 본체는 두고 fold 로 처리하는 패턴이 두 번째 정착.
- PR-C 의 Cancel-no-PATCH 결정은 향후 누군가 "symmetry 를 위해 reverse-PATCH 추가" 하려고 할 때 메모리에서 막아야 함 — `project_config_tab_edit_mode_ux.md` 가 그 가드.
- 다음 세션 우선순위: B-MAPEDIT (brush erase) 가 P0, B-MAPEDIT-2 (origin pick) 가 P1.

---

## 2026-04-30 (새벽 — 00:00 KST → 06:07 KST, 아홉 번째 세션 — PR-A 풀 systemd 스위치오버)

### 한 줄 요약

**PR-A 한 PR (#34, squash-merged `dcded7c`) 안에 systemd 스위치오버 + polkit 게이트 + 운영자 service-management policy + 9개의 부수 버그 fix 가 모두 fold 됨. SPA System tab 의 Start/Stop/Restart 버튼이 마침내 실제로 동작 (이전 HTTP 500 `subprocess_failed`). uptime / memory / env_redacted / env_stale 모두 채워짐. 운영 모델: `godo-irq-pin` + `godo-webctl` 부팅시 자동 시작, `godo-tracker` 는 SPA Start 버튼으로 수동 시작.**

> 기술 상세는 [PROGRESS.md 2026-04-30 early-morning 블록](../PROGRESS.md#session-log) 참조.

### 왜 이렇게 결정했는가

#### Polkit rule 한 줄 → systemd 풀 스위치오버로 scope 폭발

NEXT_SESSION.md 우선순위 #1 = "System tab 서비스 컨트롤" 이었음. 작업 시작 시점엔 ~120 LOC (unit 파일 3개 + polkit rule + installer + tests) 로 추정했는데, repo 정찰 해보니 unit 파일들은 이미 4월 26일 시점에 들어가 있었음. **NEXT_SESSION.md / `project_system_tab_service_control.md` 가 outdated** 였던 것. 이 정찰 결과를 운영자 보고 → "이런 누락사항 발견하면 같이 정리하자" 합의 → 메모리 보정. 이 경험이 새 feedback memory `feedback_codebase_md_freshness.md` 로 영구 기록됨.

실제 PR-A 의 코드 본체는 polkit rule 한 파일 (~50 LOC) 만 빠진 상태였고, 호스트 설치 + 운영 정책 결정이 진짜 작업 비중. 운영자가 "라이브 환경에서는 클라이언트로 웹에 접속해서 사용. 그동안 script 직접 실행은 System tab 이 미완이라 어쩔 수 없이 쓴 임시방편" 이라고 운영 의도 명확히 함 → SPA = 표준 control plane 이라는 architectural decision 이 메모리에 영구 기록 (`project_godo_service_management_model.md`).

#### tracker manual-start 결정의 함의

운영자가 "부팅시 재시작에서 오류가 발생할 여지가 있다면, tracker 프로세스는 웹 페이지에서 원격으로 실행하는 것으로" 결정. 근거: tracker 가 mlock + SCHED_FIFO 50 + CPU 3 pin + RPLIDAR USB 디바이스 의존 → unit 파일 regression 시 부팅 fail-loop 위험 가장 큼. irq-pin + webctl 은 oneshot 이거나 가벼운 ASGI 라 위험 작음.

이 결정이 unit 파일 의존 관계 재구성을 강제함:
- `godo-webctl.service` 가 `Wants/After=godo-tracker.service` 를 가지면 부팅시 webctl 가 tracker 를 끌어옴 → 정책 위반.
- `Wants` 제거 + `/run/godo` 디렉토리 ownership flip (이전엔 tracker 의 `RuntimeDirectory=godo` 가 만들었음) → webctl 가 `RuntimeDirectory=godo` + `RuntimeDirectoryPreserve=yes` 들고 부팅, tracker 도 `RuntimeDirectoryPreserve=yes` 추가해서 systemd reference-counting 으로 양쪽 다 stop 해야 디렉토리 사라지게.

webctl 자체로 tracker 없이도 정상 부팅 가능 — `/api/health` 가 `tracker:"unreachable"` 로 응답하고 SPA 는 그걸 그대로 표시 + 운영자가 SPA Start 클릭으로 tracker 부활.

#### HIL 에서 줄줄이 나온 9개 부수 버그를 한 PR 에 fold 한 이유

운영자의 (β) 결정 — "조밀한 작업" 위해 한 PR 에 다 묶기. 분리 PR 들로 가면 매번 컨텍스트 재구성 비용. 이 세션은 운영 의도 (SPA System tab 이 진짜로 동작) 까지 한 번에 닫는 게 가치. 이게 9가지 fix 가 한 PR 에 모인 이유:

1. **Polkit rule** (원래 scope)
2. **운영자 service-management policy 채택** (architectural)
3. **/run/godo ownership flip** (정책 의 함의)
4. **`ReadWritePaths=/var/lib/godo`** 추가 (`restart_pending` ROFS warning fix)
5. **`/etc/godo/{tracker,webctl}.env` 템플릿 + installer 자동 seed**
6. **`/boot/firmware/cmdline.txt` 에 `cgroup_enable=memory` 추가** (RPi 5 firmware default 가 `cgroup_disable=memory` 라 cgroup 메모리 controller 차단 — `MemoryAccounting=yes` 만으로는 안 됨. reboot 필요한 host kernel cmdline 변경)
7. **`godo-irq-pin.sh` device-name lookup**: 부팅 후 IRQ 번호 shift 발견 (SPI 가 IRQ 183 → 182) → hardcoded IRQ 번호 list 가 reboot 마다 fragile. `/proc/interrupts` 를 device-name 으로 매칭하도록 재작성.
8. **`ActiveEnterTimestampRealtime` → `ActiveEnterTimestampMonotonic`**: systemd 257 (Trixie) 가 Realtime variant 를 노출 안 해서 SPA 에 uptime 이 "—" 였음. `systemctl show --property=` output 에 그 키가 silently 빠지는 패턴 — 진단에 시간 걸림.
9. **`env_redacted` envfile-based** (was `/proc/<pid>/environ` based): cap-bearing tracker 가 kernel-marked non-dumpable 라 cross-process /proc/*/environ read 가 EPERM. envfile 텍스트 read 로 우회 — 운영자 의도 ("envfile 의 setting 이 진짜 적용됐는지 확인") 와 직접 부합. `env_stale: bool` 필드도 같이 추가 — envfile mtime > active_since_unix → SPA 에 amber "envfile newer — restart pending" 배지.

이 중 #6, #7 은 운영 host 의 실제 reboot 이 필요한 변경. 운영자 "이 와중에 reboot 가자" 결정 → `/boot/firmware/cmdline.txt` 백업 후 `cgroup_enable=memory` append → `systemctl reboot`. Reboot 후 #7 의 IRQ shift 가 즉시 노출됨 (godo-irq-pin.service fail) → device-name lookup 으로 fix → 재배포 → 재검증 통과.

#### Post-merge 발견된 2개 follow-up

운영자 SPA 사용 중 발견:

- **ServiceStatusCard `lastError` UX 버그**: 409 transition error 만 auto-dismiss 하고 다른 에러는 영구 표시. webctl self-restart `subprocess_failed` + tracker restart `request_aborted` 가 sticky-red 로 남음. 모든 에러를 5초 auto-dismiss + service active 시 즉시 클리어 하는 `$effect` 추가. → commit `71f2ef9`.
- **Config 탭 비어있음**: webctl 의 `config_schema.py::_CPP_SCHEMA_PATH` 가 dev-tree sibling layout 만 가정. PR-A 후 webctl 이 `/opt/godo-webctl/` 로 옮겨지면서 `/opt/production/RPi5/...` 라는 존재 안 하는 path 를 찾아 HTTP 503 `schema_unavailable`. Tier 해결: env var override > dev tree > `/opt/godo-tracker/share/` fallback. installer 가 `config_schema.hpp` 도 `/opt/godo-tracker/share/` 에 복사. → commit `c4f6cce`.

두 follow-up 다 같은 PR-A branch 에 push → squash merge 시 한 commit (`dcded7c`).

#### 운영자 mental model 정정 — SSE / cpu_temp / tracker 응답 배너

세션 끝에 운영자 질문: "webctl 죽었어도 cpu_temp 가 갱신되는데 tracker 데이터 지연 메시지가 떠 있는 게 신기하다." 디버깅으로 데이터 source 분리 확인:

- **cpu_temp 변동**: `/api/diag/stream` SSE — webctl 가 host `/sys/class/thermal/...` 직접 read. tracker 와 무관.
- **"tracker 응답하지 않습니다" 배너**: `/api/health` polling 의 `tracker: "ok"|"unreachable"` 필드. webctl 의 UDS client 가 `/run/godo/ctl.sock` 에 connect 한 결과.

webctl 부활 후 cpu_temp 는 즉시 valid (host 측정 1줄), 하지만 webctl 의 UDS client 가 tracker 와 reconnect 하는 동안 짧은 fail 윈도우 존재 → 두 indicator 가 일시적으로 충돌하는 것처럼 보였던 것. 실측: webctl restart 1.6초, EventSource default retry 3초 — 합쳐 ~3-4초 sigma. 운영자 mental model 정정 완료.

### 산출물

- 1 PR merged: #34 (`dcded7c`).
- main = `dcded7c`.
- Test baselines: backend 502 → 521 (+19), frontend unit 변화 없음 (env_stale stub field 통과).
- HIL 검증 완료: SPA Start/Stop/Restart 200 OK, env_redacted 채워짐, env_stale touch flip 동작, Config 탭 40 rows 렌더, 부정 케이스 404/400.
- 새 메모리 entry 2개:
  - `feedback_codebase_md_freshness.md` — CODEBASE.md SSOT 갱신 discipline.
  - `project_godo_service_management_model.md` — 운영자 service-management policy.

### 결정 요약

- PR-A scope 가 polkit rule 한 줄 → systemd 풀 스위치오버 + 9개 부수 fix 로 폭발한 건 운영자의 (β) 결정 ("조밀한 작업") 의 결과. 분리 PR 들로 가면 컨텍스트 재구성 비용 컸을 것.
- `godo-tracker` manual-start 정책은 RT 프로세스의 부팅 fail-loop 위험을 회피하는 보수적 선택. 운영자가 SPA Start 버튼으로 명시적으로 활성화.
- `/run/godo` 의 RuntimeDirectory ownership 가 webctl 로 flip 됨 — Phase 4-2 D Mode-A amendment S8 ("owned exclusively by tracker") 가 새 정책에 의해 superseded.
- envfile-based env display + `env_stale` staleness indicator 가 cap-bearing process 의 non-dumpable 제약을 우회하는 architecture 차원 결정. 운영자 의도 ("envfile setting 이 적용됐는지 확인") 와 직접 부합.
- 다음 세션 우선순위: PR-B (process monitor + extended resources) 가 P0. PR-A 가 풀어준 SPA 운영 모델 위에서 다음 layer 의 가시성.

---

## 2026-04-29 (저녁~심야 — 16:35 KST → 2026-04-30 00:30 KST, 네 번째~여덟 번째 마라톤 close)

### 한 줄 요약

**AMCL 컨버전스 0% → 100% 해결 (PR #32). 5-PR 마라톤 (Track D 스케일/Y-flip → SPA CW→CCW → C++ AMCL CW→CCW → sigma annealing → freed-passthrough port hotfix). 두 번의 misdiagnosis (D-3 angle convention, D-4 map row order) 끝에 진짜 root cause = `AMCL_SIGMA_HIT_M=0.05` 가 너무 타이트해서 5000개 random particle 중 어느 것도 ±5cm 내 anchor 못 잡음을 empirical sweep 으로 확인. Coarse-to-fine sigma annealing + auto-minima tracking 으로 k_post 10/10 / σ_xy median 0.009m 달성. 운영자 시각 검증 통과.**

> 기술 상세는 [PROGRESS.md 2026-04-29 evening through midnight 블록](../PROGRESS.md#session-log) 참조. Empirical sweep 데이터는 `.claude/memory/project_amcl_sigma_sweep_2026-04-29.md` 참조.

### 왜 이렇게 결정했는가

#### 5번 가설 갈아엎은 그 디버그 아크

오늘 misdiagnosis 가 두 번 이어진 후 진짜 원인 도달까지의 흐름:

1. **PR #29 후 (Track D scale fix)**: 운영자 HIL 시각 검증 → "오버레이 5× 크기는 맞췄는데 상하반전됨". → Y-flip 가설.
2. **PR #30 (Track D-2 SPA CW→CCW)**: SPA 의 `projectScanToWorld` 가 RPLIDAR 의 raw CW 각도를 표준 CCW 수학 (`r*sin(a)`) 그대로 써서 ly 부호 반전. doc/RPLIDAR/RPLIDAR_C1.md:128 의 "θ (0–360°, clockwise)" 가 single source of truth. SPA 한 줄 fix → 운영자 확인: "스캔 모양 자체는 지도랑 딱 맞는다" — single-basin shape lock OK 인데 pose 는 매번 ~5.5m 어긋남.
3. **PR #31 (Track D-3 C++ AMCL CW→CCW)**: SPA 와 같은 fix 를 production C++ AMCL 에도 적용. **이걸로 컨버전스 1-in-15 → 100% 될 거라 예상.** Mode-A APPROVE-WITH-FOLD + Writer + Mode-B APPROVE → merge → HIL → **σ_xy 6.7m 동일, k_post 0/10**. 가설 ❌.
4. **Track D-4 시도 (map row order)**: `occupancy_grid::load_map` 이 PGM bytes 를 raw 로 저장 (row 0 = image top), 그런데 `evaluate_scan` 의 `cy = (yw - origin_y)/res` 는 ROS convention 상 cy=0 = world bottom 가정. 둘이 어긋나서 매번 잘못된 셀 읽고 있음 → Y-mirror. row-flip 추가 → HIL 동일 σ ~6.7m. 가설 ❌. (D-4 unmerged; D-3 merged 유지 — 수학 discipline 차원).
5. **Sigma sweep (~21:00 KST, 결정적 데이터)**: σ_hit 5개 값 (1.0, 0.5, 0.2, 0.1, 0.05) 에서 각 10번 calibrate → σ=0.2 alone 이 9/10 / σ_xy median 0.006m, σ=1.0 이 2/10 / single basin, σ=0.1 / 0.05 가 0/10. **Convergence cliff 가 0.1 ↔ 0.2 사이**. → 진짜 원인 = sigma_hit 가 5cm 짜리 cell map 에서 5000개 random particle 이 ±5cm 안에 들 확률을 보장하지 못해서 likelihood 가 거의 uniform 이 됨 → AMCL 변별 못함.
6. **사용자 제안한 coarse-to-fine annealing**: σ=1.0 으로 single basin lock 후 σ=0.5 → 0.2 → 0.1 → 0.05 로 좁혀가기. PR #32 default schedule `[1.0, 0.5, 0.2, 0.1, 0.05]`. 첫 HIL → k_post 0/10 / σ median 0.036m. Annealing 이 single basin 은 잡았는데 final phase σ=0.05 가 sub-cell 영역 (Gaussian 너비 5cm = cell 너비) 에서 over-tight 되어 particle 더 못 좁힘. 수동 override `[1.0, 0.5, 0.2]` → k_post 10/10 / σ median 0.012m.
7. **사용자 제안한 auto-minima tracking + patience-2 early break**: schedule 은 cliff 너머까지 가게 하고, 각 phase 마다 best (min) σ_xy 추적, 2 consecutive worse-than-best phases 면 break, return best (not last). Default 5-phase 그대로 두어도 알아서 phase 2 (σ=0.2) 에서 멈춤. HIL → **k_post 10/10 / σ median 0.009m** (수동 3-phase override 보다도 좋음). Schedule 을 자유롭게 granularize 해도 안전 — 알고리즘이 self-stop.

#### 사용자가 제안한 architectural pattern — 가변 스코프 / CPU 파이프라인

> "약간 우리 가변 스코프같은거지. 빠른 속도의 물체는 줌아웃, 느린 속도의 물체는 줌인 해서 더 자세히 볼 수 있는 것."
> "cpu의 파이프라인처럼 계산 하는거야."

이번 annealing 은 sequential 구현. Future work: parallel pipelined version (cores 0/1/2 에 σ_k tier 별로 N개 chain 동시 실행, K+N-1 ticks 만에 끝남 — Track D-5-P). 같은 패턴이 SSE 송출, FreeD smoother, Live tracker 등에도 적용 가능 — 다음 세션 audit 항목 (Task #9). Spec 은 `.claude/memory/project_pipelined_compute_pattern.md`.

#### Map editor 차기 작업 우선순위

운영자가 세션 close 직전 추가 요청:
- **Origin pick** (~90 LOC, 고-ROI): 운영자가 스튜디오 중앙에 막대 세우고 → 스캔에 점으로 잡힘 → SPA `/map` 편집 모드에서 그 점 클릭 → world (0,0) 으로 설정. YAML origin 한 줄 갱신. 평행이동만 필요.
- **Map rotation** (~250 LOC, 보류): YAML origin theta 활용 + SPA/C++ 양쪽 회전 행렬 적용. 운영자가 RPi5 의 VideoCore VII GPU 활용 가능성 제기 (HDMI 1개만 사용하니 GPU 자원 남음). 아키텍처적으로 흥미로운 angle 이지만 baseline measurement + POC 먼저 — research-grade.

Spec 정리: `.claude/memory/project_map_edit_origin_rotation.md`, `.claude/memory/project_videocore_gpu_for_matrix_ops.md`.

#### 운영자가 정한 다음 세션 우선순위

1. System 탭 — Start/Stop/Restart 버튼 실제로 동작하게 (systemd units + polkit) + 프로세스 모니터링 (htop/ps -ef 상응 + duplicate-PID alert + CPU/GPU 사용률).
2. B-MAPEDIT (브러시 erase, plan ready).
3. B-MAPEDIT-2 origin pick.
4. Pipelined-pattern audit.
5. B-MAPEDIT-3 rotation + GPU POC.

### 산출물

- 5 PRs merged: #29 #30 #31 #32 #33.
- main = `194599b`.
- Test baselines: backend 491→502 (+11), frontend unit 143→165 (+22), e2e 36→37 (+1).
- HIL 검증 완료: tracker 가 default schedule + auto-minima 로 매번 (1.15, ~0, 173°) 수렴, σ_xy median 0.009m. 운영자 visual confirm.

### 결정 요약

- D-2 / D-3 (CW→CCW 부호 fix) 는 hypothesized root cause 였으나 sweep 으로 부정됨. defensive math discipline 으로 main 에 유지 — 향후 코드 가독성 차원.
- D-4 (load_map row-flip) 는 마찬가지로 영향 없어서 unmerged. 작업 트리에서만 시도 후 revert.
- D-5 (sigma annealing + auto-minima) 가 진짜 fix. Single-basin lock + cell-resolution-aware self-stopping.
- 운영자가 제안한 design idea (annealing schedule, auto-minima, pipelined pattern, GPU 활용) 가 architectural 으로 핵심. 메모리에 4개 entry 신규 작성.
- 다음 세션 우선순위: System tab 서비스 컨트롤 + 프로세스 모니터 (operational convenience 가 가장 큰 즉각 가치).

---

## 2026-04-29 (오후 — 12:33–16:34 KST, 세 번째 close)

### 한 줄 요약

**Mapping 파이프라인의 fatal bug 가 ~24h 동안 잠복해 있던 것을 발견 + 수정 (PR #28). 동시에 service observability + admin-non-loopback service action endpoint 도 출하 (PR #27). 세션 막바지 (~16:30 KST) 에 SPA scan-overlay 5× 스케일 + Y-flip 추정 버그까지 추가로 진단해서 다음 세션 1순위로 큐잉.**

> 기술적 상세는 [PROGRESS.md 2026-04-29 afternoon 블록](../PROGRESS.md#session-log) 참조.

### 왜 이렇게 결정했는가

#### Mapping bug — Plan A (rf2o) 채택 vs Plan C (config-only) 거부

`launch/map.launch.py:44-50` 의 static identity TF `odom→laser` 가 slam_toolbox 의 `minimum_travel_distance: 0.5` (Jazzy default) 게이트에 odom motion = 0 으로 보고 → 단 1프레임만 통합 → 모든 PGM 이 단일 위치 부채꼴로 저장된 상태. 4개 맵 모두 occupied 63-114 cells (정상 수천 대비) 로 통계 confirm.

세 가지 옵션:
- **Plan A (rf2o_laser_odometry)**: scan-derived odometry 노드를 colcon overlay 로 빌드 → 진짜 motion 을 publish. 정석. ROS 2 hand-carried 매핑의 canonical pattern.
- **Plan B (laser_scan_matcher fork)**: AlexKaravaev 포트. 비활성, 백업용.
- **Plan C (config-only)**: `minimum_travel_distance: 0.0` 으로 게이트 완전 해제. slam_toolbox 내부 Karto scan-matcher 가 모든 motion estimation 을 떠맡음. 단순하지만 featureless 환경에서 발산 위험.

사용자 선택: **"옵션 A 정석대로 가자"**. 이유: long-term stability (`Embedded_CheckPoint` 기준), 향후 다른 스튜디오에서도 robust, scan-matcher 가 main motion estimator 가 아닌 보정 역할로 남는 게 ROS 2 표준. Plan C 는 hotfix fallback 으로 invariant `(h)` 에 명시 보존.

#### M1 fold critical — `name='rf2o_laser_odometry'` byte-equal 강제

Mode-A reviewer 의 가장 중요한 발견: rf2o 노드가 launch Node 에서 `name=` 을 명시 안 하면 ROS 2 가 `CLaserOdometry2DNode` 라는 source default 로 등록 → YAML 의 `rf2o_laser_odometry:` 네임스페이스 키랑 안 맞아서 **파라미터 로딩 silent 실패** → rf2o 가 hardcoded defaults 로 부팅 (`base_frame_id=base_link`, `init_pose_from_topic='/base_pose_ground_truth'`) → init pose 토픽이 없으니 영원히 대기 → odom→laser TF publish 안 함. **우리가 막 빠져나온 함정의 정확히 대칭 실패 모드**.

빌드만 통과해도 런타임에 같은 증상 재발할 수 있던 위험을 plan + DoD 양쪽에 grep verification 으로 박아둠.

#### Build-first gate 도입 (Plan A 가 빌드 안 되면 Plan C 즉시 hotfix)

rf2o ros2 브랜치는 2023-04 이후 활동 없음, GitHub Issue #43 (2026-03-11) "Jazzy 에서 동작 안 함" open, PR #41 (format-1→3 migration) 미머지. 빌드 자체가 위험할 수 있음. 그래서 writer 의 **첫 단계를 Dockerfile edit + docker build 로 한정** — 빌드 실패 시 launch.py / YAML 등 후속 edit 절대 진행 안 함. 빌드 실패 = Plan C 한 파일 변경으로 즉시 same-session hotfix 경로 보장.

결과: 첫 시도에 빌드 통과 (47.3 s, 1 package, no warnings). PR #41 의 정확한 수정을 in-Dockerfile 로 두 줄 sed 로 적용.

#### B-MAPEDIT 의 mid-session 폐기 결정

Mapping bug 발견 시점 (~14:30 KST) 에 B-MAPEDIT writer 는 이미 ~50분 돌면서 ~600 LOC + 수정 21개 파일 + 신규 7개 파일 (`map_edit.py`, `MapEdit.svelte`, `MapMaskCanvas.svelte`, etc.) 작성 완료 상태. 옵션:
- (a) stash 로 보관 → 매핑 fix 후 복구 시도
- (b) 그냥 폐기 → 다음 세션에 fresh 로 재실행

사용자 선택: **(b)**. 이유: "나중에 꼬일 것 같아". 매핑 픽스가 underlying assumption (좋은 PGM 의 존재) 을 바꿀 수 있고, B-MAPEDIT 는 진짜 맵 위에서 brush size / mask resolution 등 UX 검토가 필요할 수 있음. Stash 복구 시 conflicts + 재테스트 부담이 fresh 작성보다 클 가능성. 매핑이 진짜 fix 됐으니 다음 세션 cold-start 로 깔끔하게.

#### Track D 스케일 버그 — 즉시 fix 가 아닌 NEXT_SESSION 큐잉

세션 막바지에 발견. 임팩트 큰 UX 버그지만:
1. Mapping/AMCL critical path 영향 없음 (operator 가 보는 그림만 어긋남, 백엔드 AMCL 은 정확)
2. AMCL 1/15 수렴이 진짜 production 차단 요소 (Phase 2 hardware-gated)
3. Track D 스케일 fix 는 명확히 좁힌 버그라 다음 세션 cold-start 에서도 빨리 처리 가능

세션 길이 + 사용자/모델 둘 다 길게 달려옴 + Track D fix 가 평가 기간이 추가로 필요한 (HIL 검증) 작업인 것 고려 → NEXT_SESSION 1순위로 큐잉이 안전.

#### CLAUDE.md §6 — KST 시간대 SSOT 작성 규칙 추가

오늘만 같은 날짜로 3개 close (오전, 오후, 심야) 가 발생. 이런 패턴이 자주 일어나니까 **모든 date-bearing entry 에 KST (GMT+9) 시간 명시 의무화**. CLAUDE.md §6 "Context maintenance" 하위에 새 sub-section 으로 형식 규칙 박아둠 (PROGRESS.md / doc/history.md / CODEBASE.md change-log / NEXT_SESSION.md / plan files / memory files 각각 컨벤션).

### 운영 현황 (news-pi01, 2026-04-29 16:34 KST 종료 시점)

- main = `f311218`. webctl 동작 중 (PID 386478, 12:11 KST 시작).
- godo-tracker: 사용자의 calibrate 테스트 후 foreground terminal 에 살아있을 가능성 — 다음 세션 시작 시 `pgrep -af godo_tracker_rt` 로 확인.
- godo-mapping container image 재빌드됨 (rf2o overlay 포함, SHA `92b3076da18e…`).
- Active map: `04.29_v3.pgm` (두 바퀴 워킹 + loop closure, 14.4×18.2m, 2978 occupied / 60.7% free).
- 직전 broken map (`0429_2.pgm`) 은 디스크에 남아있지만 active 심볼릭은 새 맵으로 교체됨.
- LAN-IP 차단 (SBS_XR_NEWS AP client-isolation), Tailscale `100.127.59.15` 만 동작.
- Tmux session `godo` (created Wed Apr 29 12:33 KST) 여전히 attached.

### 다음 세션 첫 작업 후보

1. **Track D 스케일 + Y-flip fix** (TL;DR #1, ~150-250 LOC) — `MAP_PIXELS_PER_METER` 하드코딩 제거 + YAML resolution SSOT 사용 + 이미지 Y-flip.
2. **B-MAPEDIT 재실행** (TL;DR #2, ~950 LOC) — `.claude/tmp/plan_track_b_mapedit.md` §8 fold 적용된 plan 그대로.
3. **AMCL Phase 2 hardware-gated 진단** (TL;DR #3) — LiDAR pivot offset 측정 + AMCL Tier-2 파라미터 튜닝.

순서는 다음 세션 cold-start 에서 NEXT_SESSION.md 보고 결정.

---

## 2026-04-29 (오전 — first close, P1 일괄 배포)

### 한 줄 요약

**Phase 4.5 P1 일괄 배포 — Track D (Live LIDAR overlay) + B-DIAG (Diagnostics) + B-CONFIG α/β 4개 PR 풀파이프라인 통과 후 main 머지. 운영 surface 가 P1 단계까지 사실상 완성됨. 다음은 P2 (B-MAPEDIT / B-SYSTEM / B-BACKUP).**

> 기술적 상세는 [PROGRESS.md 2026-04-29 블록](../PROGRESS.md#session-log) 참조.

### 왜 이렇게 결정했는가

#### Track D 와이어 스키마 — `angles_deg[]` 병렬 배열 (Mode-A M1)

원안은 `angle_min + i × increment` 의 uniform-angle 가정이었음. Mode-A reviewer 가 `src/lidar/sample.hpp` 의 per-sample `angle_deg` + `scan_ops::downsample()` 의 non-uniform 필터(`distance_mm <= 0` 와 range 외 샘플 드롭)을 지적. 두 옵션:
- (a) `angles_deg[LAST_SCAN_RANGES_MAX]` 병렬 배열 추가 — 시켰jul 페이로드 5824 → ~11.6 KiB, 와이어 ~12.2 KB/frame
- (b) raw `frame.samples` 를 stride 로 복사 — AMCL beam SSOT 깨짐

채택: **(a)**. AMCL-beam SSOT 유지하면서 non-uniform angle 정직하게 반영. SSE 5 Hz × 12.2 KB = ~61 KB/s/subscriber 로 1 Mbps 업링크에 16× headroom 여유.

#### B-DIAG 의 `scan_rate` → `amcl_iteration_rate` 이름 변경 (Mode-A M2)

원안은 "scan_rate" 였지만 실제 metric 은 cold writer 의 publish cadence — 즉 AMCL iteration rate. Idle 모드에서 LiDAR 가 parked 면 0 Hz, OneShot 모드에선 버튼 누를 때 1번. 운영자 mental model 충돌 ("LiDAR 가 죽었나?" 오해). Reviewer 가 정직성 요구.

채택: 모든 layer (struct / JSON / endpoint URL / SPA UI / build greps) rename. `<RatePanel/>` 옆에 AMCL `mode` indicator 같이 표시해서 "Idle 일 때 0 Hz 는 의도된 동작" 이 운영자에게 보이도록.

#### B-DIAG publisher thread 분리 — inline P² streaming-quantile 거부 (Mode-A P-Arch)

대안으로 P² streaming-quantile 알고리즘이 O(1)/sample 로 inline 컴파일 가능. 하지만:
- Thread D 라이프타임 동안 state 누적 → 재시작 시 per-tick state reset 필요
- bursty distribution 에 bias (1ms GC pause 가 영원히 p99 = 2µs 에 남음)
- branchy update logic 이 30ns ring write 보다 비쌈
- 무엇보다 **publisher thread 가 try/catch 격리** 제공 — Thread D 는 못 함 (59.94 Hz 핫 패스 영향)

채택: SCHED_OTHER lock-free ring + 1 Hz publish + try/catch 격리. PR-DIAG 의 가장 큰 architecture decision.

#### B-CONFIG 의 2-PR split — Mode-A push-back (M3)

원안은 단일 PR ~2650 LOC. Mode-A reviewer 가 1500 LOC borderline 초과 + 3 language × 38 files 라 Mode-B reviewer attention dilution 우려 + Wave 1/2 의 자연스러운 seam 지적.

두 안 비교:
- (i) 단일 PR 강행 — 한 번에 보고 머지, 검증 round 1번
- (ii) 2-PR split (α C++ only Waves 0+1, β webctl + SPA Waves 2+3+4)

채택: **(ii)**. PR-α 는 `test_set_config_e2e_ipc.cpp` 로 webctl 없이도 end-to-end 검증 가능 → 독립 머지 가능. PR-β 가 cold_writer reader migration + cross-language parity 책임. 이전 PR-DIAG 에서 splitting seam 으로 거론됐던 패턴 그대로 적용.

#### 스택 PR 머지 메커니즘 — gh `--delete-branch` 함정

PR #14 (Track D) `gh pr merge --rebase --delete-branch` 가 `feat/p4.5-track-d-live-lidar` 헤드 브랜치 삭제 → GitHub 가 그 브랜치를 base 로 참조하던 PR #15 를 **자동 close**. Reopen API 는 base 가 사라져서 실패. PR #16/#17 도 체인 반응으로 같은 운명.

해결: 각 upstream 머지 후 → 로컬 `git rebase origin/main` + `git push --force-with-lease` → `gh pr create` 로 새 PR (#18/#19/#20) 띄우기. 4번 머지 = 4번 재생성. 감사 추적은 새 PR 번호로 옮겨가고 원래 PR 들은 cross-link 만 남김.

**교훈**: 다음에 stacked PR 가 있으면 upstream 머지 **전에** 다음 PR 의 base 를 main 으로 retarget 해두면 자동 close 회피 가능. gh 의 default 가 "close on base-deleted" 이지 "auto-retarget" 이 아님.

#### Post-merge UX 핫픽스 — Config 빈 테이블 + Sidebar anon 가시화

LAN 브라우저 검증 직후 두 문제 발견 (commit `265f5f6`):
1. **Config 페이지가 0 row** — `stores/config.ts` 의 `Promise.all` 이 `/api/config` 503 (tracker unreachable) 에 reject 되면서 schema (37 rows) 도 store 에 못 넣음. `Promise.allSettled` 로 변경 → schema 가 독립적으로 land, current 는 `{}` 로 남고 `fmtCurrent(undefined)` → "—" 렌더링.
2. **Config link 가 admin 만 보임** — `Sidebar.svelte` 의 `{#if isAdmin}` gate. Track F (read anon, mutate admin) 모델은 이미 `<ConfigEditor>` 의 `admin` prop 으로 enforce 되고 있어서 Sidebar gate 는 중복 + 운영자 친화적이지 않음. 사용자 요청: "로그인 하지 않은 상태에서도 config 페이지와 diagnostics 데이터는 모두 볼 수 있게 하는 것이 좋겠어".

두 fix 모두 클라이언트 사이드만; 백엔드 변경 없음. 테스트는 이미 `test_config_anon_returns_503_when_tracker_down` 으로 503 contract 가 핀돼 있어서 회귀 발생 안 함.

### 운영 현황 (news-pi01, 2026-04-29 종료 시점)

- main = `265f5f6` — Phase 4.5 P0 + P0.5 (Track D, Track E) + P1 (B-DIAG, B-CONFIG α/β) + post-merge fix 모두 안착.
- webctl PID 2172257 on `0.0.0.0:8080`, SPA bundle `index-B1VL4OVo.js` (28.07 KB gzipped), studio_v2 active map.
- godo-tracker 미구동 (의도된 상태).
- LAN PC ↔ dev box 직통은 SBS_XR_NEWS AP client-isolation 으로 막힘 — Tailscale `100.127.59.15:8080` 으로 우회 (이미 동작 확인).
- 다음 세션: Phase 4.5 P2 (B-MAPEDIT / B-SYSTEM / B-BACKUP) 진입. B-SYSTEM 부터 가는 게 가장 작음 (DIAG 인프라 재활용); B-MAPEDIT 은 `§I-Q1` 마스킹 방식 결정 필요.

---

## 2026-04-28 (저녁·심야)

### 한 줄 요약

**Track E (Multi-map management) 파이프라인 완주 — PR-B 콜드 머지 + PR-13 딜리버리. 5 endpoints + atomic symlink swap + admin-gated SPA panel. 30 files / 256 pytest / 37 vitest / 14 playwright. Phase 4.5 P0 운영 surface 사실상 완성, LAN 검증만 남김.**

> 기술적 상세는 [PROGRESS.md 2026-04-28 evening 블록](../PROGRESS.md#session-log) 참조.

### 왜 이렇게 결정했는가

#### PR-B 콜드 머지 — LAN 라운드트립 비용 vs. 검증 marginal

오전 NEXT_SESSION.md 계획은 "LAN PC에서 Chrome HTTPS-First 인터셉트 검증 후 머지" 였음. 실제로는 사용자가 Tailscale + `192.168.3.22:8080` 양쪽에서 dev box 직접 동작 확인 → SPA UX는 이미 end-to-end 검증, HTTPS-First는 클라이언트 한정 동작이라 추가 LAN 라운드트립의 marginal value 없다고 판단 → cold merge.

이 판단은 PR-13에는 적용 안 함. Track E 는 새 storage architecture (`/var/lib/godo/maps/` + symlink) + 새 admin-gated UI (3-button ConfirmDialog + non-loopback 버튼 hide) + systemd `ReadWritePaths` 추가가 끼어 있어 LAN 환경에서의 새 검증이 의미 있음 → "내일 아침 LAN 체크 후 머지" 로 보류.

#### Track E 파이프라인 — 4-라운드 풀가동의 이유

Track E 의 위협 모델이 충분히 다양했음 — path traversal, TOCTOU on symlink swap, concurrent activate, cache stale, legacy back-compat. 5개 다른 종류의 실수 표면이라 양쪽 reviewer 라운드 모두 가치 있었음.

planner → Mode-A reviewer → Parent fold → writer → Mode-B reviewer → Parent fold 6단계 모두 거쳤고, Mode-A 가 5 majors + 6 nits + 3 test-bias 잡아냄:
- M1: `realpath` containment 가 모든 public function 진입에서 (defence-in-depth), `assert` 금지 (production `-O` 에서 사라짐)
- M2: two-syscall create+replace 만 (`tempfile.mkstemp` 는 잠재 EXDEV 리스크)
- M3: `set_active` 시작 시 매번 `.active.*.tmp` sweep (이전 크래시 잔재 청소)
- M4: `window.location.hostname` 비-loopback → restart 버튼 hide (UI 가 거짓말하는 상황 방지)
- M5: systemd `ReadWritePaths` 문서화

전부 writer 호출 전 plan 에 인라인 fold.

Mode-B 는 1 major + 5 nits + 2 test-bias. Major 만 fold 하고 4 nits 는 의도적 deferral:
1. `cfg.map_path is None` dead-code branch — Settings 타입(`Path`, `Path | None` 아님) 때문에 unreachable, follow-up cleanup
2. e2e stub server 의 Track F 정렬 누락 (`/api/last_pose` etc. 가 여전히 `_claims_or_401`) — pre-PR-B drift, Track E 회귀 아님
3. e2e shared global stub state — `workers=1` 한정 OK, 향후 병렬화 시 조치
4. concurrent-flock 테스트 40 ms wall-clock 여유 — `threading.Event` 패턴이 더 견고

4개 다 fold 하면 PR-13 사이즈 + 추가 검증 round 가 붙는데 실제 위험은 M4 하나뿐. 진짜 위험만 fold, 나머지는 Track D 또는 별도 follow-up 에 묶기로 결정.

#### Atomic symlink swap — 핵심 디자인 디시플린

`os.symlink` + `os.replace` 두 syscall 로 끝. `tempfile.mkstemp` 안 씀 (생성 위치가 다른 디렉토리면 EXDEV 로 rename 실패; 같은 디렉토리 내 `secrets.token_hex(8)` 임시 이름만). `flock(LOCK_EX)` 로 activate 직렬화 + 시작 시 stale `.active.*.tmp` sweep. POSIX `rename(2)` atomic 이라 reader (image endpoint) 가 도중 상태를 못 봄.

cache invalidation 도 같이: `map_image.py` 의 cache key 를 `(path, mtime_ns)` → `(realpath, target_mtime_ns)` 로 변경. symlink swap 시 realpath 가 바뀌니 같은 mtime 도 stale 안 됨.

#### M4 단위 테스트 — Svelte 5 `mount()` 직접 호출

Mode-B M4 는 "M4 의 hide 동작이 e2e 만 검증되고 단위 테스트 없음" 지적. `@testing-library/svelte` 의존성 추가 대신 Svelte 5 빌트인 `mount(...)` 으로 jsdom 에 실제 컴포넌트를 마운팅하는 vitest 추가. `vitest.config.ts` 별도로 두고 (`style: false` 전처리 + `resolve.conditions = ['browser']`) production svelte.config.js 와 충돌 회피. 비-loopback 에서 hide / loopback `127.0.0.1` 에서 render 양쪽 다 검증 (anti-tautology).

### 운영 현황 (news-pi01, 2026-04-28 심야 종료 시점)

- main = `1f5f3c4` — PR-A + PR-B + Track F + FRONT_DESIGN §8 모두 머지 완료
- PR-13 push 완료, 다음 날 LAN 체크 후 머지 예정
- webctl `0.0.0.0:8080` 동작 중, studio_v2 맵 서빙 (PR-13 머지 후 `cfg.maps_dir` 설정 + `godo-maps-migrate` 1회 실행 필요)
- godo-tracker 미구동 (의도된 상태 — banner 정상 표시)
- 다음 세션: PR-13 LAN 체크 + 머지 → Track D (Live LIDAR overlay) 풀 파이프라인. `get_last_scan` UDS handler 가 Track B 이후 첫 cross-language touch.

---

## 2026-04-28

### 오늘의 한 줄 요약

**Phase 4.5 P0 프론트엔드 — 백엔드 PR-A 머지 + SPA PR-B 오픈 + Track F (anon read 모델) fold + Track D/E 명세 확정. Vite+Svelte 5 SPA가 21KB로 떨어졌고 운영자가 LAN 브라우저로 라이브 데이터 모니터링 + 로그인 후 제어가 됨.**

> 기술적 상세는 [PROGRESS.md 2026-04-28 블록](../PROGRESS.md#session-log) 참조.

### 왜 이렇게 결정했는가

#### "anonymous read / login-gated mutation" — 운영 현실에서 나온 요구

당초 PR-A의 auth 모델은 "모든 endpoint require_user, mutation은 require_admin" 이었음. 사용자가 PR-B SPA 라이브 검증 중 확인: "로그인 안 해도 모니터링은 돼야 한다 — 운영자가 자리에서 잠깐 보러 올 때마다 로그인하는 건 비현실적." 이게 Track F의 모티브.

세 가지 선택지:
- (a) 로그인 후에만 모든 화면 보임 — 채택 안 함 (위 모티브)
- (b) 일부만 anon, 핵심은 require_user — 절반의 절차, 절반의 보호 (양쪽 모두 손해)
- (c) **모든 read endpoint anon, mutation은 admin** ★ — read는 LAN 보안 (loopback 게이트는 그대로), mutation은 1차 방어선 (LAN-exposed credential-stuffing 방지엔 bcrypt(12) ≈ 300ms). 채택.

세 가지 게이트가 이제 직교한다:
1. **Loopback 게이트** (`/api/local/*`) — 키오스크 본체에서만 보임, 인증 무관
2. **Auth 게이트** (mutation) — admin 토큰 필요, anon은 401
3. **Role 게이트** — 미래 viewer 사용자 분리 (P2)

backend invariant (n)에 명시 + parametrized test로 모든 mutation endpoint anon 401 검증.

#### Track E를 별도 PR로 분리 — 스코프 디시플린

사용자가 "맵 여러 버전 관리 + 활성 맵 지정 + 삭제 GUI" 요청. 가능한 두 가지 모양:
- (a) PR-B에 fold — UI는 같은 Map 페이지라 자연스러움
- (b) **별도 Track E PR** ★ — 채택

이유: PR-B는 이미 Mode-B 통과한 P0 SPA. Track E는 ~650 LOC + 새 storage architecture (`/var/lib/godo/maps/` + `active.pgm` symlink) + 새 systemd `ReadWritePaths` + 매핑 Docker 컨테이너 volume mount 변경 + tracker 재시작 흐름. 다른 PR 단위. 머지 사이즈 깨끗.

planner agent가 ~620줄 plan 생성 (path-traversal 위협 모델, atomic symlink swap 프로토콜, concurrent-activate flock, cache invalidation 키 변경, back-compat 마이그레이션 모두 포함). Mode-A reviewer 재실행 중 — 다음 세션에 결과 받음.

#### Track D (Live LIDAR overlay) — Phase 2 디버그 도구로서의 정체

사용자 요청: B-MAP 페이지에서 "라이다가 지금 보고 있는 점들"을 오버레이 토글로. 새 LIDAR 탭 안 만들고 같은 화면에 통합 결정 — "내 위치 추정이 맞나?"라는 운영자의 mental model에 직접 매핑됨. Pose가 맞으면 scan 점들이 벽선에 정확히 떨어지고, 어긋나면 시각적으로 즉시 보임. **AMCL 수렴 디버깅 도구로서의 가치가 더 큼** — 오늘 사용자가 v2 맵에서 직선만 보이는 걸 직접 확인한 것과 직결.

tracker C++ 변경은 `get_last_scan` UDS handler 추가뿐 (seqlock read 1회, μs-level, hot-path 0 영향). 별도 Track D로 진행, Track E 머지 후.

#### AMCL 수렴 실패 — 시각으로 확인한 root cause

오전 매핑 직후의 AMCL 첫 실 테스트 결과 (xy_std 5.9 m, 10 000 particles × 200 iter 비수렴) 가 오늘 SPA로 시각화된 맵을 통해 확인됨. studio_v2 (107s walk + loop closure) 도 직선 위주, fine feature 부족. T자형 + 거의 직사각형 벽 → likelihood surface 가 평탄 → 거울대칭 위치들이 모두 동등 후보. yaw 가 매번 wildly 다른 값으로 수렴한 이유.

Phase 2 lever (NEXT_SESSION.md 그대로):
- ICP-based initial pose seed (가장 효과 클 듯)
- Retro-reflector landmarks at step corners
- 더 천천히 + 여러 번 walk + slam_toolbox loop_closure_threshold 낮추기
- LiDAR 20cm offset → pivot center 재정렬 (필수)

알고리즘 작업은 LiDAR 재정렬 후 본격 진입. 오늘은 운영 surface에 집중.

### 운영 현황 (news-pi01, 2026-04-28 종료 시점)

- webctl `0.0.0.0:8080` 구동 중, studio_v2 맵 서빙
- `~/.local/state/godo/auth/` 에 JWT secret + users.json (sudo 불필요한 dev 셋업)
- godo-tracker 미구동 (의도된 상태) — banner 정상 표시
- PR-B (#12) push 완료, 사용자 LAN 검증 후 머지 예정
- Track E plan + Mode-A reviewer 백그라운드 진행 중

---

## 2026-04-27

### 오늘의 한 줄 요약

**Track A (Docker SLAM 툴체인) 머지 → Track B (AMCL 진단 readout + repeatability harness + pose_watch) 완성. 진단 surface "always-on, on-demand" 원칙 정식 채택.**

> 기술적 상세는 [PROGRESS.md 2026-04-27 두 블록](../PROGRESS.md#session-log) 참조.

---

### 이른 — Track A 잔여 작업 머지 + news-pi01 Docker bring-up

- 어제(2026-04-26) 닫은 cold-start brief(`NEXT_SESSION.md`)에 따라 Track A부터 진행. `track-a-mapping` 브랜치에 plan v1 → Mode-A REWORK(15 finding) → plan v2 → Mode-A v2 → writer → Mode-B REWORK(1 Major + 4 Minor) 풀 파이프라인 완주.
- **Major 버그 (Mode-B가 잡음)**: `entrypoint.sh`의 `MAP_SAVER_CMD` 기본값에서 `-f ${MAP_OUT_BASE}` 플래그가 빠져있었음. production에서 `nav2_map_server map_saver_cli`가 자기 default(`./map`)로 폴백 → 컨테이너 내부 `/godo-mapping/map.{pgm,yaml}`로 silent write → 운영자는 bind-mounted `maps/`가 비어있는 채로 `Ctrl+C` 깨끗하게 떨어진 줄 알고 종료. 세 군데(`entrypoint.sh:40-42` 코멘트, `CODEBASE.md:181-184` 문서)는 의도된 동작을 정확히 적어놨는데 실제 default 한 줄만 어긋나 있었음. Parent가 narrow one-shot fix로 직접 수정 (3 Edit, 약 10줄).
- **PR #6 self-merge (rebase)** → `news-pi01`에서 Docker 설치(`apt install docker.io` + `usermod -aG docker ncenter`) → 재부팅 후 `docker run hello-world`(arm64v8) 정상 → `verify-no-hw.sh --full` 통과(292초, ~800 MB 풀, 18개 테스트 + docker build + image `--help` smoke). Track A 정식 closeout.
- **subagent reviewer API 안정성 이슈** 두 번 연속 발생 — Mode-A v2 confirmation pass가 `API Error: Unexpected end of JSON input`으로 33분 → 3.6시간 매달리다 실패. Parent가 직접 v2 verification matrix 작성(15/15 ✅) 후 진행. 이후 Track B의 Mode-A v2도 같은 패턴(파이프라인 단축)으로 생략 결정 — Track A precedent으로 굳어짐.

### 낮 — Track B planner + pose-readback 결정

- NEXT_SESSION에 적힌 Track B 가정("standalone Python script")이 깨짐. Tracker의 `get_mode` 응답이 `mode`만 돌려주고 AMCL pose는 cold writer 내부 seqlock에만 publish됨 → 외부에서 읽을 surface가 아예 없음. 4가지 transport 옵션 평가:
  1. **UDS 명령 신설** (`get_last_pose`) — C++ ~80 LOC additive. 기존 `set_mode/get_mode/ping` dispatch 패턴, seqlock 재사용.
  2. webctl `/api/last_pose` HTTP 라우트 — webctl이 어차피 트래커에서 pose 읽어와야 하므로 C++ 변경은 동일하게 필요 + HTTP surface 추가됨.
  3. tracker가 `/run/godo/last_pose.json` 주기 write — 매 publish마다 fsync 비용 + 새 persistence surface.
  4. `get_mode` reply 확장 — schema-drift 위험. user의 "no schema drift" 원칙과 정확히 반대.
- **Option 1 채택** — 가장 작은 blast radius. user의 "the latter (option 2) is cleaner" 직감은 "C++ 안 건드리는 길이 있다"는 가정에 기반했지만, 분석해보니 어떤 옵션도 C++ 변경을 피할 수 없음.
- 사용자 핵심 질문: **"우리 진단 툴은 production에선 비활성화하고 dev/문제 발생 시만 켜는 설계인가?"** — 답: 아니다. **"관측 surface는 always-on, 소비는 on-demand"** 패턴 정식 채택. `get_last_pose` UDS endpoint는 production에서도 항상 노출 (cost ~30 ns/AMCL iter; 호출 없으면 0). 무엇이 on/off 되는가는 *consumer* 선택 — frontend 진단 패널, CLI watch 도구, repeatability harness 모두 얇은 consumer. Prometheus / OpenTelemetry 류 패턴. 방송 중 "지금 발산이었나?" 진단할 surface가 그 순간 이미 존재해야 함 — compile-flag로 gate하면 쓸모 없음.

### 낮 → 오후 — Mode-A REWORK + plan v2

- Reviewer Mode-A v1 결과 6 must-fix:
  1. `LastPose` 크기 산수 틀림 (40 B 주장 → 실제 56 B with `published_mono_ns`).
  2. Cross-language SSOT가 Python에 3 replica → 1 mirror로 정리 필요.
  3. "godo_webctl import 금지" + `pytest.importorskip` 모순 — runtime 금지 vs test-time SSOT 핀을 분리해야 함.
  4. `--shots 1`이면 `statistics.stdev`가 `StatisticsError` raise → exit 1 갈림(legitimate happy path를 bad-CLI exit으로 오염).
  5. `last_pose_seq` ordering 핀이 5개 `g_amcl_mode = Idle` store site 중 어느 것에 적용되는지 모호 — only L302 (OneShot success path)으로 명확화.
  6. cold_writer 시그니처 변경이 기존 테스트 10개 사이트로 cascade — file-level change spec에 빠짐.
- 6개 모두 v2에 fold + Should/Nit 14개도 한꺼번에 fold. Track A precedent 따라 Mode-A v2 재검토 생략, 곧바로 Writer 진행.

### 오후 → 저녁 — Option B vs C + writer

- 사용자 질문: "진단 툴을 frontend에서 켜고 끄거나 cmd 창 띄워서 받을 수 있는가?" — yes, Track B가 첫 진단 endpoint 자체를 만들고 frontend 패널/CLI watch 도구는 위에 올라가는 얇은 consumer. 그 중 cmd watch 도구를 Track B 범위에 포함할지가 결정 포인트:
  - **Option B**: `repeatability.py`에 `--watch` 모드 추가 (한 스크립트, 두 모드).
  - **Option C**: 별도 `pose_watch.py` 스크립트 + 공통 `_uds_bridge.py` 헬퍼 모듈.
- **Option C 채택** — Single Responsibility (측정 ≠ 모니터링; 시간 압박과 운영 audience가 다름). 1년 후 Grafana exporter나 healthcheck script 추가할 때도 같은 분리 패턴이 자연스러움. 새 invariant (g) "godo-mapping/scripts/ 의 모든 UDS 클라이언트는 `from _uds_bridge import UdsBridge` MUST — copy-paste 금지" 등록.
- **Writer 4개 deviation** 보고 → Mode-B가 모두 accept:
  - 테스트 call site 카운트 drift (plan 7 → actual 4): 모든 surviving 사이트에 `Seqlock<LastPose>` thread.
  - `verify-no-hw.sh --quick` pytest 2-tier resolver (system pytest → uv fallback): F20 spec의 superset, Docker dep 도입 안 함.
  - 추가 테스트 케이스 (`test_busy_tracker_returns_3`): 양성 coverage 추가.
  - **(critical) `run_live_iteration`도 `last_pose_seq` publish**: F5 race는 OneShot→Idle 전환에만 존재. Live는 매 AMCL iter마다 Idle로 가지 않으므로 race 없음. `forced=1/0` 플래그로 OneShot vs Live 구분. **이게 없으면 `pose_watch.py`가 Live mode 중 stale pose에 freeze** — 이 도구 만든 이유 자체가 사라짐.
- Mode-B는 **APPROVE-WITH-NITS** (3 cosmetic — CODEBASE.md trailing blank line × 3, README drift caveat 한 문장, 출력 예시 timestamp 동일 cosmetic). Parent가 직접 fold(narrow fix → 3 Edit + 1 sed truncate).

### 저녁 → 심야 — 문서 정비 + closeout

- **PROGRESS.md** Track A + Track B 두 블록 추가 (영문 세부, "current state + next-up" 체크리스트).
- **doc/history.md** 이 파일에 한국어 + 결정 narrative 추가 (현재 작성 중).
- **SYSTEM_DESIGN.md** §7 (UDS 프로토콜)에 새 `get_last_pose` 명령 + reply 스키마 + "진단 surface always-on" 원칙 추가 예정.
- 사용자가 history.md 위치(`doc/history.md`) + 한국어/영어 혼용 컨벤션을 명시 → memory에 reference entry 등록 (`reference_history_md.md`). 이 파일이 존재한다는 사실 자체가 future session에서 PROGRESS.md만 보고 끝내는 실수를 막아줌.
- branch `track-b-repeatability`에 3개 commit (feat / docs(memory) / docs closeout). Track A precedent 따라 PR로 push → user self-merge → news-pi01에서 `--quick` 재검증.

### 오늘 푸시된 커밋 요약

(closeout commit + push 후 추가 예정)

### 다음 세션 시작 시 확인할 것

1. **LiDAR 재연결** (월요일 예정) → `repeatability.py --shots 100`으로 Phase 1 재현성 측정 + first hardware audit (occupancy_grid.cpp:148-154 YAML key 비교).
2. **Track A live mapping run** — `bash run-mapping.sh control_room_v1` → `maps/control_room_v1.{pgm,yaml}` 생성 → `/etc/godo/maps/`로 복사 → 트래커 시작 시 `occupancy_grid::load_map` 통과 확인.
3. **Frontend planning** (NEXT_SESSION 원래 Track C) — 남겨둔 5 bucket 논의: 페이지 셋, 실시간 데이터 source, 메커니즘(polling/SSE), 맵 렌더링(Canvas 2D), 디자인(다크모드).
4. **Track A `verify-no-hw.sh --full`이 발견한 `nav2_map_server` Jazzy YAML 키 목록**과 `occupancy_grid.cpp:148-154` 비교는 실제 매핑 1회 후가 의미 있음.
5. systemd install on news-pi01 (`production/RPi5/systemd/install.sh`) — 이미 어제 끝났음, 재확인만.

---

## 2026-04-24

### 오늘의 한 줄 요약

**RPi5에서 RPLIDAR C1 실기 구동 확인 → Phase 4-1 (RT hot path) 전체 파이프라인 완주 → 오늘 총 15개 커밋 `origin/main` 푸시.**

---

### 이른 오전 — RPi5 하드웨어 구동 검증

- 전날 환경 설정·깃 설정 완료한 `news-pi01`(RPi5, Debian 13 Trixie aarch64)에서 첫 실물 테스트.
- 2D LiDAR가 바닥 기울기에 민감한 점 논의 — **지도 제작 시 5 m 이동하면 0.01°의 미세 tilt로도 원래 물체가 사라진 것처럼 보이는 현상**이 발생 가능함을 지적. 정확도 우선 원칙에 따라 Phase 1에 (8) 바닥 tilt 측정, (9) 레벨링 마운트 설계 두 항목을 추가하기로 결정. 문서는 Plan A로 완성(`doc/hardware/floor_tilt_survey_TS5.md` + `leveling_mount.md`), 현장 방문은 추후로 보류.
- RPi5로 옮긴 김에 C++ SDK 직접 구동까지 확인하기로. `godo_smoke` 바이너리를 ultra_simple과 동시 실행 가능한 상태로 먼저 착수 (Plan B).

### 오전 — Phase 3 완주 + C1 first light

- Plan B 구현체(`/production/RPi5/`) 완성. `godo_smoke` 5프레임 캡처 시 `grabScanDataHq` 첫 호출이 모터 spin-up 도중 timeout으로 실패하는 현상 관찰. `ultra_simple`은 조용히 재시도로 넘어가는 패턴이었음.
- **일시적 timeout을 최대 5회 연속까지 허용하도록 수정** (`lidar_source_rplidar.cpp`, 약 14줄 변경). 커밋 `49fdc2b`.
- 30프레임 / 500프레임 테스트 통과. 3회 반복 재현성 확인:
  - **godo_smoke steady-state: 10.02 / 10.03 / 10.52 Hz** (spec 10 Hz 맞음)
  - ultra_simple: 4,768 / 4,848 / 4,770 SPS (스펙 5,000 SPS의 ~96 %)
  - godo_smoke: 5,108 / 5,109 / 5,108 SPS
- 결론: **우리 post-processing(validate + CSV write + session log) 오버헤드는 사실상 0**. 30프레임 테스트에서 평균 7 Hz처럼 보였던 것은 startup transient(1.5s / 3s 총 시간)가 통계를 왜곡한 것뿐.
- 시각화: `rate_compare.png` + `xy_scan.png` × 3 iter. xy scan에서 studio 벽면 윤곽이 세 번 모두 거의 완벽히 중첩되는 것을 육안으로 확인 (약 mm 수준 재현성).

### 낮 — SYSTEM_DESIGN.md 대폭 개정

- 아키텍처 핵심 결정 3개를 도식화 + 문서화:
  1. **Hot/Cold path 분리**: 59.94 Hz FreeD→UDP 경로는 hard deadline (~16.7 ms), LiDAR+AMCL 경로는 최대 1 s 지연 허용. 두 경로 사이는 `std::atomic<Offset>`(초기 안) → **`Seqlock<T>` 템플릿**(v3 수정안)으로 교차.
  2. **Offset smoother 선형 램프 (방식 A)**: AMCL 결과가 도착하면 `live_offset`이 `target_offset`으로 `T_ramp` 동안 선형 보간. UE 화면에 눈에 보이는 step change 방지. EMA / rate-limit 대비 전환 시간 예측 가능성으로 선택.
  3. **Yaw wrap을 두 지점에 명시**: smoother 내부 `lerp_angle`(최단 호), FreeD pan 재인코딩 `wrap_signed24`(signed 24-bit lsb fold). 레거시 `XR_FreeD_to_UDP`는 pan 산술을 안 했기 때문에 wrap 함수가 없었다는 점을 문서화.
- Trigger UX (Q6) 해결: 물리 버튼(GPIO) + HTTP POST(godo-webctl). 두 경로 모두 같은 `std::atomic<bool> calibrate_requested`로 수렴.
- FastAPI vs 커스텀 C++ 웹: **FastAPI 별도 프로세스 강력 권장**. RT 바이너리에 HTTP 스택을 넣으면 alloc/락 간섭 위험이 제로가 아니기 때문.

### 낮 → 오후 — Mode-A 리뷰 → 설계 재정비

- code-reviewer Mode-A 첫 리뷰 결과 **REWORK 판정**. 블로커 5개:
  1. aarch64에서 24~29바이트 struct의 `std::atomic<T>`는 lock-free 아님 (LSE2 없이는).
  2. smoother의 `target != target_new` float 비교는 AMCL 노이즈로 매 틱 fire.
  3. Phase 4-3에 map editor UI까지 끼어있음 — Phase 5급 스코프.
  4. Q6 primitive가 세 군데에서 "queue" / "atomic<bool>"로 불일치.
  5. AMCL divergence clamp가 `live` 기준이라 큰 재-localization 시 stale offset 교착.
- **v3 개정으로 5개 전부 해결**:
  1. `Seqlock<T>` 템플릿 명시 (single-writer + N-reader, 64-byte alignment).
  2. seqlock의 **generation counter**(정수) 기반 edge detection + `frac ≥ 1.0` 시 `live ← target` 값 복사.
  3. Phase 4-3 스코프 축소 → 3 endpoint (`/health`, `/map/backup`, `/calibrate`); map editor는 Phase 4.5로 분리.
  4. `std::atomic<bool> calibrate_requested` 한 곳으로 통일, queue 승격 경로는 미래 작업으로 명시.
  5. Clamp 기준을 `live`가 아니라 **직전 accepted target**으로, 명시적 calibrate_now 시 bypass.
- AMCL 정적 노이즈 대응으로 사용자 제기 → **cold path deadband filter** 신설 (기본 10 mm / 0.1°). gen counter + deadband 조합으로 ramp가 완주할 수 있음.
- 런타임 튜닝 가능한 값(IP, 포트, T_ramp 등) 관리 전략 합의: **Tier 1 (constexpr in `core/constants.hpp`) + Tier 2 (TOML 기반 `Config`, env 오버라이드)**. 추후 React 설정 페이지에서 편집 가능하도록 **reload-class 분류**(hot / restart / recalibrate)도 미리 명시.
- Mode-A v3 verification → **PASS-WITH-NOTES** (서브섹션 넘버링 §12.x → §11.x 글리치 하나만 즉시 수정).

### 오후 — FreeD 전송 경로 결정

- RPi5의 **RP1 I/O 컨트롤러** 이야기 — 자체 IRQ 컨트롤러와 DMA 엔진을 가진 PCIe-attached 남교(south bridge). IRQ 분리가 구조적으로 쉬워져서 RT 관점에서 유리.
- FreeD 수신을 USB-CDC(`/dev/ttyACM0`)에서 **하드웨어 PL011 UART0 (`/dev/ttyAMA0`)** 로 전환. USB bulk 폴링 주기(~8 ms)의 jitter 제거.
- 크레인 FreeD 출력(RS-232 ±12 V)은 **YL-128 (MAX3232) 모듈**로 3.3 V TTL 변환 후 GPIO15(pin 10)에 직결. 사용자의 Arduino R4 필드 교훈 두 가지 중요:
  1. **YL-128 VCC는 반드시 Pi 3V3 (핀 1 or 17)** — 5 V 주면 TTL 출력이 5 V가 되어 Pi GPIO 파괴 위험.
  2. **저항 분압 금지** — 이전 빌드에서 intermittent framing error 원인이었음. 3.3 V / 3.3 V 직결이 정답.
- SYSTEM_DESIGN.md §6.3에 배선 + 부팅 설정(`enable_uart=1`, `dtparam=uart0=on`, `cmdline.txt`에서 `console=serial0,115200` 제거) 체크리스트 반영.

### 저녁 — Phase 4-1 플래너 v1 → Mode-A → v2

- code-planner로 **Phase 4-1 = RT hot path만**(LiDAR/AMCL/webctl 제외) 계획 생성. 13 task, ~9 엔지니어 일수 규모.
- Mode-A 리뷰 결과 6 must-fix + 4 should-fix 발견:
  - `doc/freed_wiring.md` 태스크 누락
  - `serial_reader.cpp`에 8O1 termios 플래그 명시 필요
  - `P4-1-10`의 yaw blocker 직접 명시 누락
  - `test_seqlock_roundtrip.cpp` 위치 모순
  - 리스크 행 부족 (콘솔 owner race, 비-D1 패킷)
  - invariant (e) 실효성 확보
- 전부 반영한 **Plan v2** 산출. Writer 착수 가능한 상태로 확정.

### 저녁 → 심야 — Writer 실행 + Mode-B 리뷰 + cleanup

- code-writer가 **13개 태스크를 모두 구현** (약 34분간 백그라운드). 6개 incremental commit:
  - `f28abe7` tomlplusplus v3.4.0 submodule
  - `8363465` core + yaw + smoother + rt-setup foundation
  - `96319e4` freed parser + serial reader + UDP sender
  - `7f63f90` godo_tracker_rt + godo_jitter 바이너리
  - `95c9991` 10개 hardware-free 테스트 타겟
  - `72f4c28` wiring 문서 + scripts + CODEBASE invariant (e)
- 16/16 hardware-free 테스트 green (Phase 3 6개 회귀 + Phase 4-1 10개 신규).
- Writer가 명시한 **4개 deviation** 전부 CODEBASE.md에 문서화:
  1. `std::span` → `(ptr, size)` (C++17 한정 문법)
  2. `mlockall`을 RLIMIT_MEMLOCK 체크 후 호출 (dev host에서 thread_create 실패 방지)
  3. PTY 환경에서 8O1 flags가 EINVAL이라 tcsetattr는 warn-and-continue + `O_NONBLOCK` 폴백
  4. `[rt-alloc-grep]`이 UdpSender 생성자 내 `std::string(...)` 하나 감지 — 시작-once, hot path 아님
- **Jitter baseline (news-pi01, RT 권한 없이)**: p50=58 µs, p99=2028 µs, max=5338 µs. setup-pi5-rt.sh 적용 후 재측정이 "진짜" 숫자.
- Mode-B 리뷰 → **APPROVE-WITH-NOTES**. Must-fix 0개, should-fix 4개(문서/클린업). 전부 cleanup 커밋 `49f874d`에 반영:
  - `yaw::wrap_signed24` 코멘트를 pan + X/Y 양쪽 용도로 확장 문서화
  - `serial_reader`의 `O_NONBLOCK`을 termios 실패(PTY) 경로에만 적용 — 실제 PL011에서는 blocking read 유지
  - `test_rt_replay` 축소-assertion을 deviation #5로 추가
  - Magic number(`1000.0`, `64.0`, `32768.0`) → `FREED_POS_LSB_PER_M` / `FREED_PAN_LSB_PER_DEG` 명명 상수
  - Main startup 순서를 SYSTEM_DESIGN §6.2와 동일화 + 3-arg POSIX `main` 사용
- 8개 커밋 전부 `origin/main`(SBS-NCENTER/GODO_PI)에 푸시 완료.

### 심야 — 문서 정비

- RPi5 공식 PDF 4종을 `doc/hardware/RPi5/sources/`에 로컬 보관:
  - `raspberry-pi-5-product-brief.pdf` (1.1 MB)
  - `raspberry-pi-5-mechanical-drawing.pdf` (175 kB)
  - `rp1-peripherals.pdf` (3.5 MB — GPIO/UART/SPI/I²C 레지스터 레벨 참조)
  - `raspberry-pi-uart-connector.pdf` (241 kB — 참고용)
- **중요한 발견**: Raspberry Pi는 **Pi 5부터 공식 schematic PDF를 공개하지 않음**. Pi 4B / Pi 3 / Pi 2B / Pi 1 / Zero 전부 공개돼 있는데 Pi 5만 mechanical drawing + STEP 파일까지만 공개. 보드 전기 디자인이 필요하면 RP1 peripherals 매뉴얼 + 상용 공개되어있는 compliance 테스트 리포트 수준에서 충분.
- `doc/hardware/RPi5/README.md`에 40-pin 핀맵 + GODO 전용 배선(YL-128 결선) + 주의사항 정리.
- `PROGRESS.md`의 Current phase / Next up 재구성. Phase 4-1 closeout(hardware 셋업 + jitter 재측정) + Phase 4-2 queue(LiDAR + AMCL) + Phase 4-3 minimal(godo-webctl 3 endpoint) + Phase 4.5 deferred(map editor + React) + Phase 5(현장 통합).
- 이 파일(`doc/history.md`) 신설. 앞으로 날짜별 세션 기록은 여기에 한국어로, `PROGRESS.md`는 "현재 상태 + 남은 작업" 영문 체크리스트 용도로 분리 유지.

### 오늘 푸시된 커밋 요약 (origin/main: 49f874d)

```
49f874d fix(rpi5-rt): Mode-B follow-ups — constants, wrap semantics,
                     serial reader, main ordering
72f4c28 docs(rpi5): Phase 4-1 wiring doc + scripts + CODEBASE invariant (e)
95c9991 test(rpi5-rt): 10 hardware-free targets covering Phase 4-1 surface
7f63f90 feat(rpi5-rt): godo_tracker_rt binary + godo_jitter harness
96319e4 feat(rpi5-rt): FreeD parser + serial reader + UDP sender
8363465 feat(rpi5-rt): core + yaw + smoother + rt-setup foundation
f28abe7 feat(rpi5-rt): add tomlplusplus v3.4.0 submodule for config loader
879f950 docs(system): pin FreeD transport to PL011 UART0 via YL-128
807e210 docs(system): fix subsection numbering §12.x → §11.x
c6ee335 docs(system): v3 addressing Mode-A blockers + constants scaffold
30edbf1 docs(system): hot/cold path split, smoother, yaw wrap, Q6 resolved
49fdc2b fix(rpi5): tolerate transient grabScanDataHq failures during spin-up
72f4c28 docs(rpi5): Phase 4-1 wiring doc + scripts + CODEBASE invariant (e)
95a69c1 docs(hardware): tilt survey + leveling mount methodology (Plan A)
3436d96 feat(rpi5): add production C++ scaffold + godo_smoke binary (Plan B)
```

### 다음 세션 시작 시 확인할 것

1. RPi5 물리 셋업 (setup-pi5-rt.sh + YL-128 결선 + cmdline.txt) 실행 여부.
2. `godo_jitter` post-setup 재측정 결과 (`test_sessions/TS<N>/jitter_summary.md`).
3. 크레인 FreeD 실물 결선 후 `godo_tracker_rt` end-to-end 동작 로그.
4. 상기 결과에 따라 Phase 4-2 (LiDAR + AMCL + deadband) 플래너 착수.

---

## 2026-04-23

### 한 줄 요약
floor tilt survey + leveling mount 방법론 문서화 (Plan A) + RPi5 C++ Phase 3 scaffold 구축 (`godo_smoke` + 3-way 비교 워크플로우) (Plan B).

### 메모
- 두 Plan 병렬 진행. PROGRESS.md 충돌 방지 위해 **Plan B 먼저 커밋, Plan A 나중에 append** 순서로 정리.
- Phase 3 scaffold는 invariants (a)(b)(c)(d) 4개 pin.
  - (a) no ABC — duck-typed `LidarSourceRplidar` vs `LidarSourceFake`
  - (b) test-include split — `test_csv_writer_readback`는 production include path 제외
  - (c) hot-path allocation 허용 범위(smoke 스코프)
  - (d) setlocale("C")은 main에서만
- Python 프로토타입과의 **byte-identical CSV parity** 테스트 `test_csv_parity` 통과 (uv run + cmp -s).

---

## 2026-04-21

### 한 줄 요약
알고리즘 방향 확정 (Approach B + O3 → O4) + RPi5 + 네이티브 C++ 단일 바이너리 결정 + SHOTOKU FreeD Pan 의미 정확화 + 에이전트 파이프라인 공식화.

### 메모
- FreeD Pan = **base-local** (pan-head 엔코더, 바퀴 평행 규칙 덕분에 사실상 world-frame과 동일).
- AMCL이 `(x, y, yaw)` 3-DOF를 동시에 출력 → yaw 별도 보정 불필요.
- Docker + ROS 2 Jazzy + slam_toolbox는 **지도 제작 시에만** 한 번 사용, 런타임은 네이티브 C++.
- Q7 해결: FreeD 수신·변환·송신 전부 RPi5 C++ 바이너리 내부.

---

## 2026-04-20

### 한 줄 요약
Phase 0 완료 — RPLIDAR C1 deep dive + CLAUDE.md 9-section 구조화.

### 메모
- `doc/RPLIDAR/RPLIDAR_C1.md` 작성 (측정 원리, 스펙, UART 프로토콜, SDK 분석, chroma studio 적합성).
- 원본 PDF 2개 (`C1 datasheet v1.0`, `S&C-series protocol v2.8`) → `doc/RPLIDAR/sources/`에 오프라인 참조용 보관.
- 프로젝트 전체 재시작 가능성을 위해 `PROGRESS.md` 신설.
