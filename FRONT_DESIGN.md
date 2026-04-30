# FRONT_DESIGN.md — GODO 프론트엔드 설계 SSOT

> **용도**: GODO 프로젝트의 두 프론트엔드(RPi5 로컬 execution window + 외부 web client) 설계
> 문서. 사용자/팀원이 읽는 SSOT, 한국어 + 영어 engineering term 혼용. 구현 세부는
> `godo-webctl/CODEBASE.md` 및 (예정) `godo-frontend/CODEBASE.md` 참조.
>
> **분리 이유**: 프론트엔드 영역이 커서 `SYSTEM_DESIGN.md`에서 분리. SYSTEM_DESIGN은
> RT pipeline / AMCL / FreeD / 매핑 같은 백엔드+제어 측면에 집중.
>
> 결정 일자: 2026-04-28 (사용자 결정 fold-in).

---

## 1. Scope

GODO에는 **두 종류의 프론트엔드**가 있다:

1. **Local execution window** — `news-pi01`(RPi 5) 자체에서 띄우는 데스크탑 앱. 운영자가
   현장에서 시스템 상태(트래커/웹서버/IRQ pin 등)를 직관적으로 확인하고, 문제가 생기면
   즉시 kill/start 할 수 있게 하는 **orchestrator + status panel** 역할.
2. **Web client** — 외부(스튜디오 PC, 스튜디오 모바일, 사무실 Mac 등)에서 브라우저로
   접속하는 운영 콘솔. 매핑 결과 확인, calibrate 트리거, config 편집, 진단 모니터링.

두 프론트는 **공통 Svelte+Vite 코드베이스**를 쓰지만 **로컬 모드에서만 보이는 추가 페이지(B-LOCAL)**가 있다.
공유 코드 = SSOT. 로컬 전용 페이지는 IP 화이트리스트(`127.0.0.1`/`::1`)로만 표시.

## 2. Stack — 결정됨 (`.claude/memory/frontend_stack_decision.md`)

| 영역 | 선택 |
|---|---|
| 빌드 | Vite (8.x) |
| 프레임워크 | Svelte |
| 라우팅 | SPA (svelte-spa-router) |
| 차트 | (P1에서 결정 — uPlot 후보) |
| Map 렌더 | Canvas 2D |
| Realtime transport | **SSE** + polling fallback (분석 §4.1) |
| Auth | JWT (localStorage), bcrypt password |
| i18n | 한국어 단일, engineering term은 영어 잔존 (CPU/Temp/AMCL 등) |
| 폰트 | 시스템 폰트 (Pretendard 우선, fallback Noto Sans KR) |
| **UI 스타일** | **Confluence/Atlassian 스타일** — 깔끔한 사각/약한 라운드(2-4px), 직선 레이아웃, 정보 밀도 위주. **둥근 약품통 같은 큰 라운드 버튼 / glassmorphism / soft-UI 트렌드 안 씀**. 테이블·카드·세로 spacing이 명확하고 운영용으로 한 화면에 정보가 많이 들어가는 디자인. |

**서빙 모델**: 단일 FastAPI 프로세스(`godo-webctl`)가 SPA bundle을 `/`에 mount + JSON API를
`/api/*`에 mount. Admin 콘솔 / 클라이언트 viewer를 별 프로세스로 분리하지 않음 — 한 프로세스가
auth role에 따라 가시성을 제어. (Multi-process 분리는 보안/부하 둘 다 이득 없음, complexity만 증가.)

## 3. 결정 로그 — 사용자 답변 fold-in

### A. 두 프론트 관계

**선택: A2 하이브리드 (orchestrator + 공통 Svelte 앱)**

User 의도: A1(단일 앱 + Chromium kiosk)은 "백엔드 프로세스가 실제로 떠있는지" 직관 확인이
어렵다. 따라서:

- **Local window가 orchestrator 역할** — godo-tracker / godo-webctl / godo-irq-pin 3개
  systemd 서비스의 status를 시각적으로 보여주고 start/stop 버튼 제공. Single-instance
  discipline은 systemd가 이미 보장 (Restart=on-failure, BindToMachineID 등).
- 부팅 시 자동 시작 (systemd `WantedBy=graphical.target`).
- **Kiosk 모드는 불필요** — 일반 데스크탑 윈도우로 띄움.
- 외부 client에서는 **B-LOCAL 페이지가 안 보임** (IP 체크).

이 구조의 장점: 로컬 운영자가 한 화면에서 (a) 시스템 동작 여부 (b) 모드 토글 같은 정상 운영
둘 다 처리. systemd가 실 process 관리 → orchestrator는 read+control UI일 뿐.

### B. 페이지 셋

```text
P0 (1차 구현):
  - B-DASH    Dashboard (모드 chip, quick actions, 최근 활동, last-pose 요약, health)
  - B-MAP     Map view (PGM + 실시간 pose marker + 1초 trail + (선택) particle cloud)
  - B-AUTH    Login / 토큰 카운터
  - B-LOCAL   ★ Local-only orchestrator 패널 (서비스 상태 + start/stop/restart + 로그 tail)

P1 (2차):
  - B-DIAG    Diagnostics (AMCL std/iter/converged + 시스템 metric + journald tail)
  - B-CONFIG  Config editor (~30 Tier-2 키, reload-class 표시 §D-Q2)

P2 (3차, Phase 4.5):
  - B-MAPEDIT Map editor (사람/크레인 마스킹 — §I-Q1 결정 후)
  - B-SYSTEM  System (CPU/mem/disk/journald + 셧다운/재부팅 버튼)
  - B-BACKUP  Backup history (list + restore)
```

User 답변 (B-Q1/Q2): 우선순위 OK, **낮은 layer부터 가자**. 페이지 셋 추가/삭제 없음.

### C. 페이지별 기능 세부

**B-DASH**: 모드 chip + Calibrate / Live toggle / Backup quick actions + 최근 5개 활동 + last-pose 한 줄 + health (CPU temp / 서비스 상태).

**B-MAP**:
- PGM 캔버스 (서버측 PNG 변환, 클라이언트는 `<img>` decode)
- AMCL pose marker: 점 + heading 화살표
- **1초 trail** (C-Q1 결정) — 1 Hz 갱신 가정 시 1점, 5 Hz 시 5점. trail 길어지면 직선처럼 보여 의미 적음.
- **Particle cloud (조건부 도입)** — C-Q2 분석:
  - particle cloud = AMCL의 N=500 particle (가설 pose 후보들). 맵과 별개.
  - 부하 분석: 500점 × (x, y, weight) × 4 bytes = 6 KB per frame. 1 Hz 도입 시 6 KB/s, 5 Hz 시 30 KB/s. **트래커 부하: AMCL은 이미 particle을 가지고 있으니 추가 비용은 직렬화 + 전송만 (~0.1 ms CPU/frame)**. → **부하 거의 없음, 도입 권장**.
  - 단 P0가 아닌 P1(B-DIAG)로 옮겨서 첫 구현 부하 줄일 것 추천. 결정: P1로 이동.
- pan/zoom (마우스 휠 + 드래그, 모바일 pinch H-Q4).
- 좌표 hover 표시.

**B-AUTH**: username + password 폼 + JWT 토큰 발급. 세션 timeout 6h (F-Q2). 상단 바 우측 "Logged in as <name> · 세션 5h 32m 후 만료" 표시. 페이지 클릭(라우트 이동) 시 토큰 갱신 (refresh token endpoint).

**B-LOCAL** (로컬 모드 전용):
- 3개 서비스 카드: godo-tracker / godo-webctl / godo-irq-pin
  - 상태 chip (active=green / failed=red / inactive=grey)
  - Start / Stop / Restart 버튼 (auth 필요)
  - 마지막 30줄 journald tail
- "Reboot Pi" / "Shutdown Pi" 버튼 (auth + confirm dialog)
- 시스템 health 요약 (CPU temp, RT jitter)

**B-DIAG**: AMCL get_last_pose 5 Hz SSE (E-Q1) — x/y/yaw + std + iter + converged + forced + sparkline. 시스템 metric (CPU temp, RT jitter from `godo_jitter` 또는 tracker exposed). journald tail (`/api/logs/tail?unit=godo-tracker&n=50`).

**B-CONFIG**: Tier-2 키 테이블, 각 행에 (key, current, edit, **reload-class 표시**). reload-class별 표시 (D-Q2):
- `hot` 클래스: 즉시 반영, 회색 ✓ 아이콘
- `restart` 클래스: 변경 후 "godo-tracker 재시작 필요" 메시지 + **붉은 ! 아이콘**
- `recalibrate` 클래스: "재시작 + 재캘리브레이션 필요" + 붉은 ‼ 아이콘
- 사용자가 적용 안 된 키를 한 눈에 식별 가능

**B-MAPEDIT** (P2, §I-Q1 분석 후 결정 — 구현됨 2026-04-30, `feat/p4.5-track-b-mapedit`).
- `/map-edit` 라우트 + 사이드바 진입점 (`Map Edit`).
- 활성 맵 underlay 위에 brush-erase 마스크 페인팅 (반경 5..100 CSS px 슬라이더, 기본 15).
- Apply 시 (admin only): auto-backup → atomic PGM rewrite → restart-pending sentinel touch.
- 응답 `{ok, backup_ts, pixels_changed, restart_required: true}` → 성공 토스트 + 3초 후 `/map`로 redirect + 글로벌 `RestartPendingBanner` 표출.
- 적용은 godo-tracker 재시작 후 (System 탭 또는 loopback `/local`). hot reload 미채택 (deferred indefinitely).

**B-MAPEDIT-2** (P2, 구현됨 2026-04-30, `feat/p4.5-track-b-mapedit-2-origin-pick`).
- `/map-edit` 라우트 안에 origin pick 섹션 추가 (Edit sub-tab 안의 co-resident 블록 — 별도 sub-tab 아님 — operator-locked).
- 두 입력 모드 항상 side-by-side 노출 (single-input은 regression):
  - **Mode A (GUI pick)**: 캔버스 클릭으로 `pixelToWorld` 변환 후 numeric 필드에 pre-fill. `setCandidate`가 mode를 항상 `absolute`로 강제 (T1 fold).
  - **Mode B (numeric entry)**: `x_m` / `y_m` 직접 입력 + `absolute` ↔ `delta` 토글.
- Sign convention for `delta` mode: **ADD** (operator-locked 2026-04-30 KST). `new_origin = current_origin + (x_m, y_m)`. SUBTRACT는 regression.
- 입력 검증: locale-comma (`,`) 거부, NaN/Inf 거부, `|value| > 1000 m` 거부.
- Apply 시 (admin only): auto-backup → atomic YAML `origin[0]/origin[1]` 재작성 (theta + 다른 모든 byte 보존) → restart-pending sentinel touch.
- 응답 `{ok, backup_ts, prev_origin, new_origin, restart_required: true}` → 성공 토스트 + 3초 후 `/map`로 redirect + 글로벌 `RestartPendingBanner` 표출.
- 적용은 godo-tracker 재시작 후 — tracker는 boot 시 YAML 읽음 (hot reload 미채택, B-MAPEDIT과 동일 패턴).
- B-MAPEDIT-3 (rotation, theta-only edit) 은 별도 후속 PR — `.claude/memory/project_map_edit_origin_rotation.md` 참조.

**B-SYSTEM**: CPU temp 5분 graph + 메모리 + 디스크 + journald + Reboot/Shutdown (auth + 원격 OK per C-Q3). PR-2(2026-04-29) 추가: **GODO 서비스** 패널 (1 Hz polling, 카드 1개/서비스, ActiveState chip + uptime + PID + memory + redacted env collapse + admin Start/Stop/Restart 버튼).

**B-BACKUP**: `/var/lib/godo/map-backups/<UTC ts>/` 리스트 + restore 버튼.

### D. Config 변경 적용 방식

**선택: D3 — Hybrid (RAM 즉시 + atomic file write 동기 + 실패 reject)**

Tracker 측 흐름:
```text
webctl PATCH /api/config {key: value}
  ↓
tracker UDS set_config {key, value}
  ↓
tracker validates value
  ↓
tracker atomic-writes /etc/godo/tracker.toml (tmpfile + rename)
  ↓
tracker updates RAM Config
  ↓
reload-class에 따라:
  - hot → 즉시 효과 (예: deadband_mm 변경)
  - restart → flag만 RAM에 set, 효과는 다음 systemctl restart에서
  - recalibrate → flag만 set, OneShot 재트리거 시 효과
  ↓
UDS reply ok / err (atomic-write 실패 시 reject, RAM도 안 바뀜)
```

**D-Q2 결정 fold-in**: 
- restart/recalibrate 클래스의 자동 재시작은 안 함 (방송 중 위험).
- B-CONFIG에서 변경된 restart/recalibrate 키 옆에 붉은 ! 아이콘 + "재시작 필요" 메시지.
- 운영자가 적당한 시점에 B-LOCAL의 "Restart godo-tracker" 버튼 클릭.

### E. 진단 데이터 표시

**선택: E3 — 둘 다 (브라우저 B-DIAG + CLI `pose_watch.py`)**

**갱신 주기 5 Hz, transport SSE** (E-Q1):

- 5 Hz는 사람 눈에 매끄럽게 보이는 최소치. 1 Hz는 끊겨 보이고, 10 Hz는 모바일 배터리 부담.
- get_last_pose 5 Hz × 180B reply ≈ 900 B/s = 7 Kbps per client. 부하 0.

### F. 인증 / 권한

**선택: F2 — multi-user (username + password)**

- 사용자 테이블 (`/var/lib/godo/auth/users.json` 또는 SQLite). 각 user: username + bcrypt(password) + role (`admin` / `viewer`).
- **viewer**: 모든 페이지 read-only. 수정 버튼 disabled.
- **admin**: 모든 작업 가능 (calibrate / config / mapedit / shutdown).
- **F-Q2**: 토큰 만료 6h. JWT payload에 `exp` 필드. 페이지 라우트 이동 시 백엔드 `/api/auth/refresh` 호출 → 새 토큰 발급. 상단 바에 "**Logged in as <name>** · 5h 32m 후 만료" 카운트다운.
- **F-Q3**: 모든 데이터 (config 값, 시스템 metric, journald) 다 노출. 보안 격리 안 함 — 운영팀 신뢰 모델.
- 비밀번호 변경: B-LOCAL에 "사용자 관리" 패널 (admin만), `/api/auth/users/<name>` PATCH로 password reset. RPi5 측 CLI helper도 제공:
  ```bash
  ssh news-pi01
  sudo -u ncenter godo-webctl-passwd  # interactive prompt
  sudo systemctl reload godo-webctl
  ```
- **첫 부팅 시 default admin 1개 (`ncenter` / `ncenter`)** — **첫 로그인 시 변경 강제 안 함**. 운영팀 내부 정책으로 비밀번호 관리. 외부 anonymous 접근 방지용 안전장치 수준 (악의적 외부인 차단 ≠ 강력한 보안).

### G. UI 디테일

| ID | 결정 |
|---|---|
| G-Q1 사이드바 | collapsible (>1024px 폭에서 펼침 default), 모바일 hamburger |
| G-Q2 브레드크럼 | 표시 (페이지 깊이 2단계) |
| G-Q3 favicon | `:D` SVG (32×32 + 192×192 PNG fallback for older browsers) |
| G-Q4 다크/라이트 | **라이트 default**, **회색 톤** (`#f5f5f7` background, `#2c2c30` text — 완전 백색 #fff 아님), 토글로 다크 모드, 사용자 선택 localStorage 저장 |
| G-Q5 i18n | 한국어 단일, engineering term은 영어 잔존 — 사전: `CPU`, `Temp`, `AMCL`, `LiDAR`, `OneShot`, `Live`, `Idle`, `RT`, `IRQ`, `jitter`, `std`, `iterations`, `converged`, `pose`, `latency`, `Hz`, `bps` 등 |
| G-Q6 폰트 | 시스템 폰트 우선 (`-apple-system, BlinkMacSystemFont, "Pretendard", "Noto Sans KR", sans-serif`) — 외부 web font 안 씀 (오프라인 + 빠름) |

### H. Map 뷰어

| ID | 결정 |
|---|---|
| H-Q1 렌더링 | Canvas 2D |
| H-Q2 transport | **SSE primary + polling fallback** (분석 §4.1 — WS는 우리 use case에 불필요). 크롬 메모리 절약 모드에서 탭 활성화 시 즉시 1회 polling 후 SSE 재연결. |
| H-Q3 trail | **1초** (5 Hz × 1s = 5점) — C-Q1 결정과 일치 |
| H-Q4 pinch-zoom | 지원 (모바일 우선; 라이브러리: hammerjs 또는 minimal pointer event 핸들러) |
| H-Q5 scale (Track D, 2026-04-29) | **resolution-aware via mapMetadata store**. 초기 구현은 `MAP_PIXELS_PER_METER = 100` 하드코드 (0.01 m/cell 가정) 였는데 실제 slam_toolbox 맵은 0.05 m/cell이라 5× 어긋남. PR #29 (Track D)에서 const 삭제 + `/api/maps/{name}/yaml` (기존) + `/api/maps/{name}/dimensions` (신규, PGM header 파싱) fetch 후 `worldToCanvas` 가 `metadata.resolution / origin / height` 사용. Image draw는 `naturalWidth × zoom`, world↔canvas는 `imgRow = (height-1) - (wy - origin_y) / resolution` 한 줄에 Y-flip 격리 (ROS map_server convention: origin=bottom-left pixel). 새 invariant `(x)` 결정. |
| H-Q6 scan overlay (Track D-2, 2026-04-29) | **`projectScanToWorld`가 RPLIDAR CW raw 각도를 negate 해서 REP-103 CCW로 변환** (`doc/RPLIDAR/RPLIDAR_C1.md:128`). 동시에 Mode-A M3의 `pose_valid !== 1` gate 제거 — operator가 AMCL 컨버전스 전에도 LiDAR 스캔 모양을 visual debug 가능 (chicken-and-egg 해소). PoseCanvas는 `mapMetadata` 와 `lastScan` 둘 다 기다린 후 redraw. 시각 검증: scan 점이 PGM 벽선과 정확히 align. |
| H-Q7 image-refetch on map change (PR #29 M3) | `mapImageUrl` prop 변경 시 reactive `$effect`로 bitmap 자동 re-fetch. 그 전엔 `onMount` 시점에만 fetch라서 preview swap 시 새 좌표 + 옛 비트맵 합성되는 silent half-fix 였음. |

### I. Map editor — §4.2 분석 후 결정

User 답변 (I-Q1): 구현 시간보다 **production 부하**와 **맵 변경 적용 속도/정확성**이 결정 기준.
아래 §4.2 분석에 따라 **I2 + restart-required**가 둘 다 우위. 채택 (2026-04-29 supersession; hot reload는 deferred indefinitely).

> **2026-04-29 supersession**: hot reload는 deferred indefinitely 결정. 채택은
> **I2 + restart-required (no hot reload)**. 이유: tracker 재시작은 (a) 메모리
> 가비지 청소 + RT-process leak 면역, (b) AMCL occupancy_grid 동시성 path
> 추가 회피 (seqlock/RCU 불필요), (c) Track E 활성화 패턴과 동일한 검증된
> 길. 맵 편집은 저빈도 operator-triggered 이벤트라 3-5초 다운타임이 비용
> 아님. 자세한 내용은 §4.2 supersession block + B-MAPEDIT 플랜
> (`.claude/tmp/plan_track_b_mapedit.md`).

#### I3. Origin pick (B-MAPEDIT-2)

운영자가 활성 맵의 world origin `(x, y)`를 재지정 (theta는 deferred PR B-MAPEDIT-3). 두 입력 모드 — GUI pick (캔버스 클릭으로 pixel→world 변환) + numeric entry (절대값 또는 delta) — 둘 다 항상 동시에 노출 (operator-locked, single-input은 regression). 변경은 YAML `origin[0]/origin[1]`만 재작성하고 `origin[2]` (theta) + 다른 모든 YAML byte는 verbatim 보존. PGM bytes는 손대지 않음. Auto-backup-first → atomic YAML rewrite → restart-pending sentinel touch (3-step 시퀀스, B-MAPEDIT과 동일). Tracker C++ 변경 0 — boot 시 YAML 읽음.

Sign convention for `delta` mode: **ADD** (operator-locked 2026-04-30 KST). 운영자가 입력한 `(x_m, y_m)`은 *new origin이 current origin에서 얼마나 떨어졌는지* — `new_origin = current_origin + (x_m, y_m)`. 운영자 phrasing: "실제 원점 위치는 여기서 (x, y)만큼 더 간 곳". SUBTRACT는 wrong (Mode-A 검토에서 spec memory의 literal "subtract" 표현과 example의 ADD 의미가 모순됨을 잡아냄 — 운영자가 ADD 확정).

---

## 4. Open question 분석

### 4.1 SSE vs WebSocket — H-Q2 추가 질의

User 질의 요지: "계속 페이지에서 접속하여 확인할 것인데 WS가 더 안정적일까?"

| 비교 | SSE | WebSocket |
|---|---|---|
| 방향 | Server → Client only | Bidirectional |
| 프로토콜 | HTTP + `text/event-stream` (HTTP/1.1 또는 H2) | TCP upgrade frame |
| 자동 재연결 | 브라우저 `EventSource`가 **기본 제공** (재시도 간격 noticeable) | 수동 구현 필요 (timer + reconnect logic) |
| FastAPI 측 | `StreamingResponse` 한 줄 | `websockets` 라이브러리 추가 |
| Proxy / 방화벽 | HTTP 그대로 통과 | 일부 corp proxy가 WS upgrade 차단 |
| 디버깅 | `curl` 가능, 로그가 텍스트 라인 | 바이너리 frame, 도구 필요 |
| 대역폭 오버헤드 | HTTP keep-alive (~50B header per session) | WS frame 6B/메시지 |
| Tab 비활성화 시 | 브라우저가 connection 닫으면 EventSource가 자동 재연결 | 닫히면 수동 재연결 작성 필요 |

**우리 use case 분석**:
- 데이터 흐름 = **server → client only** (pose, AMCL diagnostics, journald tail)
- client → server 통신은 모두 **POST endpoint** (calibrate trigger, config PATCH 등) — 별도 streaming 안 필요
- "안정성"의 정의가 "장시간 끊기지 않음"이라면 **SSE가 더 안정적** — 자동 재연결 built-in
- 부하 측면: 동등 (양쪽 다 1 keep-alive connection × N clients)

**결론: SSE 채택** (이미 §3.E/H에 반영). WS는 우리 use case에 over-engineered.

**Polling fallback 전략**:
- 페이지 load 시 1회 즉시 `/api/last_pose` GET → 화면 즉시 채움
- 그 다음 SSE `/api/last_pose/stream`로 전환, 5 Hz push 받음
- 탭 비활성화 (Page Visibility API hidden) → SSE 자동 끊김
- 탭 활성화 → 1회 polling으로 즉시 최신 표시 → SSE 재구독

### 4.2 I1 (live masking) vs I2 (post-edit) — Map editor

User 질의 요지: "production 부담", "맵 변경 적용 시간 + 정확성".

#### Production 부하 비교

| 항목 | I1 라이브 마스킹 | I2 사후 PGM 편집 |
|---|---|---|
| Cold path 매 scan 처리 | mask layer 룩업 360 ray × 10 Hz = 3,600 lookup/s | **0 (편집기는 webctl에서만 동작)** |
| Tracker 메모리 | mask grid 추가 (~100 KB) | 0 |
| Tracker C++ 변경 | cold_writer + UDS endpoint + mask 갱신 | 0 |
| Webctl 측 | 마스크 갱신 broker 역할 + 시간-가변 mask 직렬화 | numpy + Pillow로 PGM 편집 |
| RT jitter 영향 | mask lookup이 cache miss 유발 가능 (위험성 있음) | 0 |
| Phase 5 진입 조건 | C++ 신규 모듈 (테스트 + Mode-B + 검증 필요) | 작은 webctl 추가 |

→ **I2가 production 부담 0 (cold path 손 안 댐)**

#### 맵 변경 적용 시간 비교

| 시나리오 | I1 | I2 (no reload class) | I2 + hot reload class |
|---|---|---|---|
| 운영자가 마스크/edit 적용 → tracker가 인식까지 | 다음 scan (~100 ms) | tracker restart (~5s) | 즉시 (~10-100 ms) |

I2에 **hot reload class를 도입**하면 webctl이 PGM 저장 → tracker가 inotify로 감지 → AMCL의
occupancy_grid를 RAM에서 swap (atomic shared_ptr swap 같은 패턴) → 다음 scan부터 새 맵 사용.
여기서 시간은 inotify latency (~10ms) + 맵 로드 (occupancy_grid 수 MB라면 ~100ms) 정도.

→ **I2 + hot reload는 I1과 거의 동등한 적용 속도** (인지 가능한 차이 ≤ 100ms)

#### 정확성 비교

| 항목 | I1 | I2 |
|---|---|---|
| 운영자가 보고 결정 | "지금 사람이 거기 있을 거야" 예측 | **실제 매핑된 PGM**을 보고 식별 |
| 잘못 마스킹 시 영향 | 진짜 벽도 reject → AMCL 발산 위험 | backup에서 restore (안전한 fallback) |
| 반복 transient (매 방송 같은 위치 크레인) | 운영자가 매번 마스크 다시 그려야 함 (지속성 없음) | 한 번 편집 + restore 안 하면 영구 |
| transient의 "그림자" 처리 | 마스킹된 ray만 무시. 잔여 ghost 가능 | PGM 직접 편집 → 깨끗 |

→ **I2가 정확성에서도 우위** (실제 맵을 보고 작업 + safer failure mode)

#### 종합

| 차원 | I1 | I2 + hot reload |
|---|---|---|
| Production 부하 | 작지만 0은 아님 + RT jitter 위험 | **0** |
| 적용 속도 | ~100 ms | ~10-100 ms (동등) |
| 정확성 | 예측 의존, 잘못하면 발산 위험 | **실제 맵 기반, 안전** |
| 구현 비용 | 큼 (C++ + 시간-가변 mask + 검증) | 작음 (Python only) |
| 향후 확장 | 라이브 마스크는 I2 위에 쌓을 수 있음 | I2 먼저 → I1 필요 시 추가 |

**결론: I2 + hot map reload class 채택.** I-Q1 결정 fold-in.

> **2026-04-29 supersession** — 위 종합표의 "I2 + hot reload" 컬럼은 **현재 적용
> 안 됨**. 안전성 우선 원칙에 따라 hot reload는 indefinitely deferred. 실
> 적용은 **I2 + restart-required**:
>
> | 차원 | I2 + restart-required (현재 채택) | (참고) I2 + hot reload (deferred) |
> |---|---|---|
> | Production 부하 | **0** (cold path 손 안 댐, 동일) | 0 (동일) |
> | 적용 속도 | tracker 재시작 ~5s | ~10-100 ms |
> | 정확성 | 실제 맵 기반, 안전 (동일) | 실제 맵 기반, 안전 (동일) |
> | RT 안정성 | **occupancy_grid 동시성 path 0** | atomic swap 필요 (seqlock/RCU) |
> | 메모리 안정성 | **재시작이 RT-process leak 면역** | 누적 가능 |
> | 구현 비용 | **작음 (Python only, Track E 패턴 재사용)** | C++ inotify + 동시성 패턴 추가 |
> | 다운타임 | 3-5s/편집 (저빈도 operator action이라 OK) | 0 |
>
> 운영자는 편집 후 `/local`의 "Restart godo-tracker"로 재시작하거나 sysadmin이
> 외부에서 `systemctl restart`. 응답은 `{ok: true, restart_required: true}` →
> SPA가 RestartPendingBanner 표출. PR-CONFIG의 restart-pending sentinel과
> 동일 메커니즘. 자세한 내용은 B-MAPEDIT 플랜 참조.

세부 결정:
- **I-Q2 도구셋**: erase brush + polygon select + flood fill (3개 모두 numpy로 단순. 스튜디오에서 운영자가 "지금 그 영역만 지우고 싶어" 케이스 다양함)
- **I-Q3 brush 단위**: N×N (N은 운영자가 슬라이더로 조정 1~50 cell). 기본 5 (= 25 cm).
- **자동 backup**: 매 edit 직전에 `/var/lib/godo/map-backups/<UTC ts>_pre_edit/`에 원본 보관. /api/map/backup 인프라 재사용.
- **hot reload class** 도입: tracker가 `/etc/godo/maps/<map>.pgm` inotify watch + AMCL occupancy_grid 안전 교체. 별도 SYSTEM_DESIGN §5/§11 갱신 필요.

---

## 5. Top-level scaffold reorganization (2026-04-28 결정)

User 결정 fold-in: 새 frontend 도입을 계기로 top-level 디렉토리를 정리:

```text
변경 전 (현재)                    변경 후 (Phase 4.5 시작 시)
─────────────                    ──────────────────────────
/                                /
├─ production/RPi5/              ├─ production/RPi5/        (그대로 유지 — RT C++)
├─ godo-webctl/         ◄── 이동 ├─ godo-frontend/     ★신규 (Vite + Svelte)
├─ godo-mapping/        ◄── 이동 ├─ godo-backend/      (godo-webctl rename + 확장)
├─ XR_FreeD_to_UDP/              ├─ XR_FreeD_to_UDP/         (그대로 — 레거시 fallback)
├─ doc/                          ├─ doc/
├─ prototype/                    ├─ prototype/
│   └─ Python/                   │   ├─ Python/             (Phase 1-2 prototype)
│                                │   ├─ godo-webctl-min/    ★Phase 4-3 minimal 보관
│                                │   └─ godo-mapping/       ★Docker mapping 보관
├─ CLAUDE.md                     ├─ CLAUDE.md (§5 dir tree 갱신)
├─ SYSTEM_DESIGN.md              ├─ SYSTEM_DESIGN.md
├─ FRONT_DESIGN.md ★신규         ├─ FRONT_DESIGN.md
└─ PROGRESS.md                   └─ PROGRESS.md
```

이유:
- `godo-webctl`은 Phase 4-3 minimal scope (3 endpoint)으로 의도적으로 작게 만들었음. Phase 4.5+ 확장 시 새 `godo-backend`로 rename + 재구성하는 것이 SSOT 명확. 옛 minimal 버전은 prototype으로 보관 (참고용 + rollback 안전망).
- `godo-mapping`은 1년에 몇 번만 쓰는 one-off Docker tool. Top-level 차지하는 게 부담. `prototype/godo-mapping/`로 옮겨도 사용 시점은 동일하게 (`bash prototype/godo-mapping/scripts/run-mapping.sh ...`).
- **이동에 따른 영향**: systemd unit 파일의 `WorkingDirectory` / `ExecStart` 경로 갱신, README 모든 path 업데이트, CLAUDE.md §5 갱신, 기존 PR (Track B #7) 리베이스. → **별도 PR로 하나씩 분리**해서 진행 안전.

이동 시점: Phase 4.5 frontend planner 가동 직전. 일단 다음 세션에서 (a) Track B PR #7 머지 → (b) hotfix-c1-launch 머지 → (c) scaffold 정리 PR → (d) frontend planner 가동 순.

## 6. Architecture overview

### 6.1 프로세스 토폴로지 (A2 hybrid)

```text
┌─────────────────── RPi 5 (news-pi01) ───────────────────────┐
│                                                              │
│  systemd targets:                                            │
│  ┌─────────────────────────┐                                 │
│  │ godo-tracker.service    │ ← RT C++ 바이너리              │
│  │ godo-webctl.service     │ ← FastAPI + SPA serve          │
│  │ godo-irq-pin.service    │ ← oneshot at boot              │
│  │ godo-local-window.service│ ← Chromium window (autostart) │
│  └─────────────────────────┘                                 │
│                  │                                           │
│                  │ systemctl status / journalctl            │
│                  │ (read by webctl B-LOCAL via subprocess)  │
│                  ▼                                           │
│  ┌──────────────────────────────────────────────┐           │
│  │ godo-webctl FastAPI (port 8080)              │           │
│  │  ├ /              SPA bundle                  │           │
│  │  ├ /api/*         JSON endpoints              │           │
│  │  └ /api/*/stream  SSE streams                 │           │
│  └────────┬─────────────────────────────────────┘           │
│           │                                                  │
│  ┌────────▼─────────┐         ┌─────────────────────┐       │
│  │ Local Chromium   │         │ External browsers   │       │
│  │ window (X11/wayland)       │ (스튜디오 PC, 모바일,│       │
│  │ → http://127.0.0.1:8080    │   사무실 Mac)       │       │
│  │                  │         │ → http://news-pi01:8080     │
│  │ B-LOCAL 페이지 표시│         │ B-LOCAL 페이지 안 보임      │
│  │ (IP=127.0.0.1)   │         │ (IP=非 loopback)    │       │
│  └──────────────────┘         └─────────────────────┘       │
└──────────────────────────────────────────────────────────────┘
```

**핵심 원칙**:
- **systemd가 actual process manager**. 단일 인스턴스, auto-restart, boot 순서.
- **B-LOCAL은 webctl의 페이지일 뿐** — 별도 native 앱 아님. IP 화이트리스트로만 표시.
- **godo-local-window.service** = `chromium --app=http://127.0.0.1:8080 --window-size=1280,800` autostart.
- 외부 client는 B-LOCAL이 안 보이고, B-SYSTEM의 reboot 버튼만 (auth 필요).

### 6.2 라우팅 (SPA)

```text
/                         → B-DASH
/map                      → B-MAP
/diag                     → B-DIAG
/config                   → B-CONFIG
/map-edit                 → B-MAPEDIT  (P2; sub-tab inside /map per PR #41)
                              + B-MAPEDIT-2 origin pick (co-resident block, 2026-04-30)
/system                   → B-SYSTEM   (P2)
/backup                   → B-BACKUP   (P2)
/local                    → B-LOCAL    (loopback only)
/login                    → B-AUTH
```

### 6.3 API endpoint 추가 list (Phase별)

기존 (Phase 4-3 + Track B):
- `GET  /api/health`
- `POST /api/calibrate`
- `POST /api/map/backup`
- `GET  /api/last_pose` (Track B로 추가됨)

추가될 (Phase별):

**P0**:
- `POST /api/auth/login` — body {username, password} → {token, exp}
- `POST /api/auth/logout`
- `GET  /api/auth/me`
- `POST /api/auth/refresh`
- `POST /api/live` — Live mode toggle (set_mode {Live/Idle})
- `GET  /api/last_pose/stream` — SSE
- `GET  /api/map/image` — 현재 활성 맵의 PGM → PNG 변환
- `GET  /api/activity?n=5` — 최근 활동 로그 (webctl 자체 관리)
- `GET  /api/local/services` — systemctl status 3개 (loopback only)
- `POST /api/local/service/<name>/<action>` — start|stop|restart (loopback only, auth)
- `GET  /api/local/journal/<name>?n=30` — journald tail (loopback only)
- `POST /api/system/reboot` / `/shutdown` (auth admin)

**P1**:
- `GET  /api/diag/stream` — SSE for AMCL pose + system metrics 5 Hz
- `GET  /api/system/jitter` — godo_jitter snapshot
- `GET  /api/system/scan_rate` — /scan 토픽 rate (tracker exposed)
- `GET  /api/system/resources` — CPU temp / mem / disk
- `GET  /api/logs/tail?unit=<svc>&n=50` — journald tail
- `GET  /api/config` — Tier-2 키 전체
- `PATCH /api/config` — body {key: value, ...} → tracker UDS set_config
- `GET  /api/config/schema` — 키 메타 (description, reload_class, type, range)

**P2**:
- `POST /api/map/edit` — body {ops: [{type: erase|fill|flood, mask: [[x,y]...]}]}
- `GET  /api/map/backup/list`
- `POST /api/map/backup/<ts>/restore`
- `POST /api/auth/users` (admin) — body {username, password, role}
- `PATCH /api/auth/users/<name>/password` (admin or self)
- `DELETE /api/auth/users/<name>` (admin)

### 6.4 Tracker C++ 측 변경 (전체 영향 정리)

| 결정 | C++ 변경 |
|---|---|
| D3 (config PATCH, 있음 PR-CONFIG-α/β) | `core/config_schema.hpp` 의 37-row `constexpr ConfigSchemaRow[]` 가 SSOT; `config/validate.cpp` (type+range), `config/atomic_toml_writer.cpp` (mkstemp+fsync+rename + parent-writable check), `config/apply.cpp::apply_set` (validate→atomic write→ram update→hot/restart-pending publish), `core/hot_config.hpp` 의 `Seqlock<HotConfig>` (cold_writer가 매 iteration `hot_cfg_seq.load()` 후 cfg-fallback), `config/restart_pending.cpp` (sentinel file touch/clear), 3 새 UDS branches (`get_config`, `get_config_schema`, `set_config`), 3 새 build greps |
| PR-DIAG jitter exposure (있음) | Thread D가 `JitterRing::record(delta_ns)`로 sample을 ring에 적재; `rt/diag_publisher.cpp` (SCHED_OTHER)가 1 Hz로 percentile + summary 계산 후 `Seqlock<JitterSnapshot>`에 publish + UDS `get_jitter` |
| PR-DIAG amcl_rate exposure (있음) | Cold writer가 매 AMCL iteration마다 `AmclRateAccumulator::record(now_ns)` 호출 (Mode-A M1: `Seqlock<AmclRateRecord>`); diag_publisher가 두-틱 differencing으로 Hz 계산 + UDS `get_amcl_rate` (Mode-A M2 fold rename) |
| I2 + restart-required (있음, B-MAPEDIT 2026-04-30) | webctl: `map_edit.py` (Pillow 기반 PGM brush-erase, atomic write) + `restart_pending.touch()` (sentinel writer; tracker는 boot 시 clear). C++ tracker 변경 0. |

→ Track B처럼 별도 hotfix/feature 단위로 PR 단위 분리 추천.

### 6.5 Realtime (SSE) 채널

| 채널 | URL | rate | payload |
|---|---|---|---|
| Last pose | `/api/last_pose/stream` | 5 Hz | `LastPose` JSON (Track B schema) |
| Last scan | `/api/last_scan/stream` | 5 Hz | `LastScan` JSON (Track D schema) |
| Diagnostics combined (있음) | `/api/diag/stream` | 5 Hz | `{pose, jitter, amcl_rate, resources}` (PR-DIAG; Mode-A M2 fold renamed scan_rate) |
| Service status | `/api/local/services/stream` | 1 Hz | systemctl status 3개 |
| Journal tail | `/api/logs/<svc>/stream` | event-driven | journalctl --follow output (P1.5 — PR-DIAG에서 deferred) |

### 6.6 Auth flow

```text
1. 사용자가 /login 페이지에서 username + password 입력
2. POST /api/auth/login
   ├ 서버: bcrypt 검증 + JWT 발급 (exp = now + 6h, role 포함)
   └ localStorage.setItem('godo_token', jwt)
3. 모든 SPA fetch에 Authorization: Bearer <token> 헤더
4. 서버 미들웨어가 JWT 검증 + role 체크
5. 페이지 라우트 변경 시 → POST /api/auth/refresh → 새 토큰
6. 6h 미사용 시 만료 → 자동 logout
```

JWT secret: `/var/lib/godo/auth/jwt_secret` (서버 첫 부팅 시 random 생성, 600 perms).

---

## 7. API endpoint table (LIVING — 백엔드 ↔ 프론트 SSOT)

> **이 표는 living document**. 새 endpoint 추가 / 변경 / 폐기 시마다 같은 PR에서 갱신.
> 프론트와 백엔드는 이 표에 합의된 wire schema만 사용한다. CODEBASE.md
> (`godo-backend/CODEBASE.md` + `godo-frontend/CODEBASE.md`) 의 invariant로 핀.

### 7.1 HTTP endpoints

| Method · Path | 권한 | Phase | 페이지 | Request body | Reply body | 설명 |
|---|---|---|---|---|---|---|
| `GET /api/health` | public | 4-3 (있음) | DASH | — | `{ok: bool, mode: str}` | UDS get_mode round-trip |
| `POST /api/calibrate` | admin | 4-3 (있음) | DASH | — | `{ok: bool}` | UDS set_mode {OneShot} |
| `POST /api/map/backup` | admin | 4-3 (있음) | BACKUP | — | `{ts: str, path: str}` | atomic 두-단계 copy |
| `GET /api/last_pose` | viewer | TrackB (있음) | MAP, DIAG | — | `LastPose` (Track B schema) | get_last_pose UDS round-trip |
| `GET /api/last_scan` | public | Track D (있음) | MAP | — | `LastScan` (Track D schema) | get_last_scan UDS round-trip; raw polar + anchor pose |
| `POST /api/auth/login` | public | P0 (있음) | AUTH | `{username, password}` | `{token, exp, role}` | bcrypt 검증 + JWT 발급 |
| `POST /api/auth/logout` | viewer | P0 (있음) | AUTH | — | `{ok}` | localStorage 만료 (서버는 stateless JWT) |
| `GET /api/auth/me` | viewer | P0 (있음) | (전 페이지 상단) | — | `{username, role, exp}` | 토큰 검증 + 만료까지 남은 초 |
| `POST /api/auth/refresh` | viewer | P0 (있음) | (auto) | — | `{token, exp}` | 라우트 이동 시 토큰 갱신 |
| `POST /api/live` | admin | P0 (있음) | DASH | `{enable: bool}` | `{ok, mode}` | UDS set_mode {Live\|Idle} |
| `GET /api/map/image` | viewer | P0 (있음) | MAP | — | PNG image binary | active 맵의 PGM → PNG (Pillow), 캐시 5분, realpath-keyed (PR-C) |
| `GET /api/maps` | viewer | P0 (있음) | MAP | — | `MapEntry[]` | maps_dir 안의 모든 페어 + active flag (PR-C) |
| `GET /api/maps/<name>/image` | viewer | P0 (있음) | MAP | — | PNG image binary | 특정 맵 PNG (PR-C) |
| `GET /api/maps/<name>/yaml` | viewer | P0 (있음) | MAP | — | text/plain | 특정 맵 YAML (PR-C) |
| `POST /api/maps/<name>/activate` | admin | P0 (있음) | MAP | — | `{ok, restart_required: true}` | atomic symlink swap; tracker 재시작 필요 (PR-C) |
| `DELETE /api/maps/<name>` | admin | P0 (있음) | MAP | — | `{ok}` | non-active 맵 페어 삭제; active는 409 (PR-C) |
| `GET /api/activity?n=<int>` | viewer | P0 (있음) | DASH | — | `[{ts, type, detail}]` | webctl 자체 활동 로그 |
| `GET /api/local/services` | admin (loopback) | P0 (있음) | LOCAL | — | `[{name, active, since}]` | systemctl status 3개 |
| `POST /api/local/service/<name>/<action>` | admin (loopback) | P0 (있음) | LOCAL | — | `{ok, status}` | start \| stop \| restart; pre-flight ActiveState gate (PR-2): 409 service_starting on start/restart during `activating`, 409 service_stopping on stop during `deactivating` |
| `GET /api/system/services` | public | P2 (있음) | SYSTEM | — | `{ services: SystemServiceEntry[] }` | systemctl show; 1 s TTL cache; env redacted by substring allow-list; anon read (Track F) |
| `POST /api/system/service/<name>/<action>` | admin | P2 (있음) | SYSTEM | — | `{ok, status}` | start \| stop \| restart; admin-non-loopback (mirror /api/system/reboot); shares services.control() with /api/local/service/* so transition gate (409) inherited; subprocess-failed until polkit Task #28 lands |
| `GET /api/local/journal/<name>?n=<int>` | admin (loopback) | P0 (있음) | LOCAL | — | `[str]` | journalctl tail |
| `POST /api/system/reboot` | admin | P0 (있음) | LOCAL, SYSTEM | — | `{ok}` | shutdown -r now (5s grace) |
| `POST /api/system/shutdown` | admin | P0 (있음) | LOCAL, SYSTEM | — | `{ok}` | shutdown -h now (5s grace) |
| `GET /api/system/jitter` | public | P1 (있음) | DIAG, SYSTEM | — | `JitterSnapshot` (PR-DIAG schema) | RT thread jitter snapshot via seqlock; anon read (Track F) |
| `GET /api/system/amcl_rate` | public | P1 (있음) | DIAG | — | `AmclIterationRate` (PR-DIAG schema) | AMCL 반복 cadence (Mode-A M2 fold renamed scan_rate); anon read |
| `GET /api/system/resources` | public | P1 (있음) | SYSTEM, DIAG | — | `Resources` (PR-DIAG schema) | thermal_zone0 + /proc/meminfo + statvfs; 1s TTL cache; anon read |
| `GET /api/logs/tail?unit=<svc>&n=<int>` | public | P1 (있음) | DIAG, SYSTEM | — | `[str]` | journalctl --no-pager; allow-list = ALLOWED_SERVICES; anon read |
| `GET /api/config` | public | P1 (있음) | CONFIG | — | `{<key>: <value>, ...}` (37 keys) | Tier-2 키 전체; webctl projection through `config_view.project_config_view`; anon read (Track F) |
| `GET /api/config/schema` | public | P1 (있음) | CONFIG | — | `[{name, type, min, max, default, reload_class, description}]` | 37-row 메타; webctl serves the cached Python parse of `config_schema.hpp`; 60s cache; anon read |
| `PATCH /api/config` | admin | P1 (있음) | CONFIG | `{key, value}` | `{ok, reload_class}` | 단일 키 only; webctl pre-validates body size + special-char shape; 트래커가 schema 매칭 + atomic TOML write + RAM update + restart-pending flag touch (`reload_class != "hot"` 일 때) |
| `GET /api/system/restart_pending` | public | P1 (있음) | CONFIG, DASH | — | `{pending: bool}` | 트래커가 set_config 후 touch한 sentinel file 존재 여부; SPA의 RestartPendingBanner 가 구독 |
| `POST /api/map/edit` | admin | P2 (있음, 2026-04-30) | MAPEDIT | multipart `mask` part (PNG, ≤ 4 MiB) | `{ok, backup_ts, pixels_changed, restart_required: true}` | Pillow brush-erase + auto-backup-first + restart-pending sentinel; tracker 재시작 필요 |
| `POST /api/map/origin` | admin | P2 (있음, 2026-04-30) | MAPEDIT | JSON `{x_m: float, y_m: float, mode: "absolute"\|"delta"}` (≤ 256 B) | `{ok, backup_ts, prev_origin: [x,y,θ], new_origin: [x,y,θ], restart_required: true}` | Line-level YAML `origin[0]/origin[1]` 재작성 (theta verbatim 보존) + auto-backup-first + restart-pending sentinel; PGM bytes unchanged; ADD sign convention for delta; tracker 재시작 필요 |
| `GET /api/map/backup/list` | anon | P2 | BACKUP | — | `[{ts, files, size}]` | /var/lib/godo/map-backups/ scan |
| `POST /api/map/backup/<ts>/restore` | admin | P2 | BACKUP | — | `{ok}` | cp + reload |
| `POST /api/auth/users` | admin | P2 | LOCAL | `{username, password, role}` | `{ok}` | 사용자 추가 |
| `PATCH /api/auth/users/<name>/password` | admin or self | P2 | LOCAL | `{old, new}` | `{ok}` | password reset |
| `DELETE /api/auth/users/<name>` | admin | P2 | LOCAL | — | `{ok}` | 사용자 삭제 |

### 7.2 SSE streams

| Path | 권한 | Phase | 페이지 | Frame | 설명 |
|---|---|---|---|---|---|
| `GET /api/last_pose/stream` | viewer | P0 (있음) | MAP | `LastPose` JSON @ 5 Hz | get_last_pose 폴링 → push |
| `GET /api/last_scan/stream` | public | Track D (있음) | MAP | `LastScan` JSON @ 5 Hz | get_last_scan 폴링 → push; ~14 KiB/frame |
| `GET /api/diag/stream` | public | P1 (있음) | DIAG | `{pose, jitter, amcl_rate, resources}` @ 5 Hz | 통합 진단 (Mode-A M2 fold: amcl_rate); anon read |
| `GET /api/local/services/stream` | admin (loopback) | P0 (있음) | LOCAL | `[{name, active, since}]` @ 1 Hz | 서비스 상태 변화 |
| `GET /api/logs/<svc>/stream` | viewer | P1 | DIAG, SYSTEM | journalctl --follow line-by-line | journald event-driven |

### 7.3 UDS commands (tracker side)

| Command | Phase | webctl endpoint | C++ 변경 |
|---|---|---|---|
| `ping` | 4-3 (있음) | `/api/health` (sub) | — |
| `set_mode {Idle\|OneShot\|Live}` | 4-3 (있음) | `/api/calibrate`, `/api/live` | — |
| `get_mode` | 4-3 (있음) | `/api/health`, polled | — |
| `get_last_pose` | TrackB (있음) | `/api/last_pose`, SSE | — |
| `get_last_scan` | Track D (있음) | `/api/last_scan`, SSE | LastScan struct + format_ok_scan in cold writer + UDS branch |
| `get_config` | P1 (있음) | `/api/config` | tracker emits Config (37 Tier-2 keys) as JSON via `config/apply_get_all`; webctl rarely calls — Python mirror parses `config_schema.hpp` directly |
| `get_config_schema` | P1 (있음) | `/api/config/schema` | tracker emits the schema array via `config/apply_get_schema`; same fallback as above |
| `set_config {key, value}` | P1 (있음) | `PATCH /api/config` | `config/apply.cpp::apply_set` validates + atomic TOML write (`atomic_toml_writer.cpp`) + RAM update under `live_cfg_mtx` + `hot_cfg_seq.store` (Hot class) + `restart_pending::touch_pending_flag` (Restart/Recalibrate class) |
| `get_jitter` | P1 (있음) | `/api/system/jitter` | RT thread records into `JitterRing`; `rt/diag_publisher.cpp` publishes summary via `Seqlock<JitterSnapshot>` |
| `get_amcl_rate` | P1 (있음) | `/api/system/amcl_rate` | Cold writer records each AMCL iteration into `AmclRateAccumulator` (Mode-A M1: `Seqlock<AmclRateRecord>`); diag_publisher computes Hz over its 1 s tick (Mode-A M2 renamed scan_rate) |

### 7.4 UI / 프론트 측 wire SSOT

- 모든 wire string (CMD_*, FIELD names, status enum)은 `godo-frontend/src/lib/protocol.ts`에 단일 mirror
- `godo-backend`는 `godo-webctl/protocol.py` pattern 그대로 유지 (LAST_POSE_FIELDS 같은 패턴 확장)
- 두 측의 string drift는 cross-test로 catch (현재 godo-webctl `test_protocol.py` pattern 확장)

### 7.5 갱신 규칙

- 새 endpoint 추가 시: 본 §7 표 + `godo-backend/src/...` 코드 + `godo-frontend/src/lib/api.ts` 동시 수정 (한 PR 안에서)
- Schema 변경 시: 동일 PR + cross-test 갱신
- 폐기 시: 행에 ~~취소선~~ + "deprecated 2026-XX-XX, replaced by ..." 메모 추가, 한 release 후 삭제
- 버전 번호 안 둠 (단일 in-house product) — 대신 git history가 권위 있음

## 8. Phase plan

### Phase 1 — Frontend planner kick-off (다음 세션 시작)

- code-planner agent에게 §3 결정 + §4 분석 + §5 architecture 전달
- planner output: P0 페이지 셋의 task breakdown, file-level change spec
- expected scaffold:
  ```text
  /godo-frontend/                  ← 신규 top-level dir, Vite project
    ├─ vite.config.ts
    ├─ package.json
    ├─ src/
    │   ├─ main.ts
    │   ├─ App.svelte
    │   ├─ routes/                 ← Dashboard, Map, Auth, Local
    │   ├─ lib/
    │   │   ├─ api.ts              ← fetch wrapper + JWT
    │   │   ├─ sse.ts              ← EventSource manager
    │   │   └─ auth.ts
    │   └─ stores/                 ← svelte stores (token, mode, etc.)
    ├─ public/                     ← favicon (:D SVG)
    └─ CODEBASE.md
  
  /godo-webctl/                    ← 기존, 추가 endpoints
    └─ src/godo_webctl/
        ├─ auth.py                 ← 신규, JWT + bcrypt
        ├─ sse.py                  ← 신규, StreamingResponse helpers
        └─ app.py                  ← P0 endpoints 추가
  ```

### Phase 2 — P0 구현 (Track C-1)

- B-DASH / B-MAP / B-AUTH / B-LOCAL
- webctl P0 endpoints
- godo-local-window.service systemd unit
- 1차 머지

### Phase 3 — P1 구현 (Track C-2)

- B-DIAG (있음, PR-DIAG, 2026-04-29 — `feat/p4.5-track-b-diag`) — 4-panel
  Diagnostics page (Pose / Jitter / AMCL rate + Resources / Journal tail);
  multiplexed `/api/diag/stream` SSE @ 5 Hz (`{pose, jitter, amcl_rate,
  resources}`); 5 new endpoints + 1 new SSE channel (모두 anon read,
  Track F 패턴). Tracker C++: `JitterRing` + `JitterStats` + `AmclRateAccumulator`
  (Mode-A M1 Seqlock<AmclRateRecord>) + `diag_publisher` (SCHED_OTHER
  thread) + 2 새 UDS 명령 (`get_jitter`, `get_amcl_rate`). 3 새 build
  greps (hot-path-jitter / jitter-publisher / amcl-rate-publisher).
- B-CONFIG (있음, PR-CONFIG-α + PR-CONFIG-β, 2026-04-29 —
  `feat/p4.5-track-b-config-spa`) — Config editor 페이지. PR-α 는 C++
  tracker 측 (`core/config_schema.hpp` 37-row 스키마, `config/validate`,
  `config/atomic_toml_writer`, `config/apply.cpp` apply_set/get,
  `core/hot_config.hpp` `Seqlock<HotConfig>`, `config/restart_pending`,
  3 새 UDS 명령 `get_config`/`get_config_schema`/`set_config`,
  3 새 build greps `[hot-path-config-grep]` /
  `[hot-config-publisher-grep]` / `[atomic-toml-write-grep]`).
  PR-β 는 cold_writer reader migration (`hot_cfg_seq.load()` per
  iteration with cfg-fallback) + webctl 4 새 endpoints (`/api/config`,
  `/api/config/schema`, `PATCH /api/config`, `/api/system/restart_pending`)
  + SPA `/config` route + `RestartPendingBanner` (글로벌, App.svelte
  마운트). 모두 Track F 패턴 (read=anon, mutate=admin).
- C++ Mode-B 통과 후 머지

### Phase 4 — P2 구현 (Track C-3, Phase 4.5)

- B-MAPEDIT (있음, 2026-04-30, `feat/p4.5-track-b-mapedit`) — brush-erase 페인팅 + auto-backup + restart-required. webctl `map_edit.py` (Pillow 기반 atomic PGM rewrite) + `restart_pending.touch()` (sentinel writer; tracker는 boot 시 clear). SPA `routes/MapEdit.svelte` + `components/MapMaskCanvas.svelte` (sole-owner 마스크 상태, DPR-격리 좌표). Mode-A 5 majors + 4 nits + 4 test-bias 모두 fold; backend 628 pytest + frontend 203 vitest 모두 green.
- B-MAPEDIT-2 (있음, 2026-04-30, `feat/p4.5-track-b-mapedit-2-origin-pick`) — origin pick (dual GUI + numeric input). webctl `map_origin.py` (line-level YAML `origin:` 재작성, theta verbatim 보존) + 기존 `backup.backup_map` + `restart_pending.touch()` 재사용 (3-step 시퀀스 invariant `(ab)`). SPA `components/OriginPicker.svelte` + `lib/originMath.ts` + `MapMaskCanvas` mode-prop split. ADD sign convention (operator-locked 2026-04-30 KST). Mode-A M1..M5 + S1..S5 + T1..T5 + N1..N3 모두 fold; backend 671 pytest + frontend 220 vitest 모두 green.
- B-SYSTEM / B-BACKUP
- I2 hot reload class — **deferred indefinitely** (2026-04-29 결정, FRONT_DESIGN §4.2 supersession block 참조). 운영 안정성 우선; B-MAPEDIT는 restart-required 패턴으로 충분.

### Phase 5 — Field integration

- 실 스튜디오 운영 + UE 연동 + 8h 안정성 테스트

### Phase 4.5+ Track D — Live LIDAR overlay (P0.5, 2026-04-28 user 요청)

운영자가 B-MAP 페이지에서 **현재 RPLIDAR가 보고 있는 raw scan**을 맵 underlay 위 오버레이로 토글해서 볼 수 있게. localization / FreeD UDP 송출은 **0 영향** (seqlock read-only path).

**모티베이션**: still 맵 + 추정 pose만 보면 "내 위치 추정이 맞나?"를 운영자가 검증할 수 없음. 라이다가 실제로 보는 점들을 같은 좌표계에 겹쳐 그리면 — pose가 맞으면 scan 점들이 벽선 위에 정확히 떨어지고, 어긋나면 시각적으로 즉시 보임. AMCL 수렴 디버깅에도 직접 사용.

**상태 (2026-04-29)**: PR-D로 구현됨 (`feat/p4.5-track-d-live-lidar`). Mode-A 3 majors + 6 nits + 2 test-bias 모두 fold; tracker 32 hardware-free doctest + webctl 275 pytest + frontend 67 vitest + 18 playwright 모두 green.

**스코프 (구현됨)**:
- tracker C++: `LastScan` struct (`core/rt_types.hpp`) + `format_ok_scan` (`uds/json_mini.cpp`) + `get_last_scan` UDS handler. Cold writer publishes a snapshot at the same seam where it publishes LastPose (UNCONDITIONAL, mirrors deadband-bypass discipline). Hot path (Thread D) is fully insulated — `[hot-path-isolation-grep]` build step verifies thread_d_rt's body has zero `last_scan_seq` references; `[scan-publisher-grep]` verifies only cold_writer.cpp (+ 1 boot init in main.cpp) stores into the seqlock.
- webctl: `uds_client.get_last_scan` + `/api/last_scan` (anon, single-shot) + `/api/last_scan/stream` (anon, SSE @ 5 Hz). Per-frame ~14 KiB JSON, 5 Hz → ~70 KB/s SSE (감수 가능, ≤ 200 KB/s for 3 concurrent subscribers).
- SPA: `PoseCanvas`에 scan layer 추가 (3rd layer between map underlay and trail), `ScanToggle` 컴포넌트 + `scanOverlay` store (sessionStorage persistence, default OFF), `lastScan` store (SSE-fed, lifecycle gated on the toggle), polar→Cartesian transform uses the SCAN's anchor pose (Mode-A TM5 — zero pose↔scan skew).

**FRONT_DESIGN §8 wire schema deviations from the original sketch** (per Mode-A N3 + M1):
- Drop `intensities` (C1 strong/weak flag is not visualization-grade; per `doc/RPLIDAR/RPLIDAR_C1.md` §3).
- Drop `scan_time` — replaced by `published_mono_ns` (ordering only; freshness uses arrival-wall-clock).
- Drop `header_seq` — covered by `valid + pose_valid + iterations` triple.
- Replace `(angle_min, angle_increment)` with parallel `angles_deg[]` array (per Mode-A M1 — `scan_ops::downsample` filters non-uniformly, so `angle_min + i × increment` is wrong for the AMCL-aligned beam decimation).
- Add `pose_x_m / pose_y_m / pose_yaw_deg` anchor pose (Mode-A TM5: SPA uses these for the world-frame transform, NOT a separately-fetched pose).
- Add `pose_valid` flag (Mode-A M3: distinguishes legitimate (0,0,0) anchor from non-converged AMCL run).

**UX 결정 (확정)**: 새 LIDAR 탭을 만들지 않고 **B-MAP 오버레이 토글**로. 같은 데이터를 두 화면에 보이는 SSOT 위반 회피 + "내 추정 위치에서 라이다가 뭘 보고 있나?" 라는 운영자의 mental model에 직접 매핑.

### Phase 4.5+ Track E — Multi-map management (P0.5, 2026-04-28 user 요청)

운영자가 B-MAP 페이지에서 **여러 버전의 맵 (studio_v1, studio_v2, …)을 list로 보고 / 활성 맵 지정 / 삭제**할 수 있게. 매핑 Docker 세션이 새 맵을 떨어뜨릴 때마다 같은 디렉토리에 누적되고, 운영자가 GUI로 어느 맵으로 운영할지 고름.

**모티베이션**: 현재는 webctl이 단일 `cfg.map_path`만 알고 있어서 (a) 새 맵 만들면 매번 systemd env 수정 + restart 필요, (b) 옛 맵으로 fallback 하려면 SSH로 직접 파일 조작, (c) 어떤 맵이 활성인지 운영자가 한눈에 못 봄. UI로 통합하면 fallback도 한 클릭, 관리도 GUI.

**아키텍처**:
- 맵 저장소: `/var/lib/godo/maps/<name>.{pgm,yaml}` 페어. **활성 맵은 `/var/lib/godo/maps/active.pgm` symlink로 표시** (atomic `os.replace`로 갱신 가능). 매핑 Docker 컨테이너의 output volume이 같은 디렉토리.
- godo-tracker C++ **변경 0** — tracker는 시작 시 `cfg.map_path`(symlink) 읽음. 활성 맵 변경 후엔 tracker 재시작 필요 (P2 hot-reload 도입 전까지). 활성 변경 후 webctl이 운영자에게 "tracker 재시작 필요" 안내 (또는 admin 클릭으로 자동 `systemctl restart godo-tracker`).
- webctl: `cfg.map_path` (single) → `cfg.maps_dir` (default `/var/lib/godo/maps/`) + active symlink resolver로 재구성. 기존 `/api/map/image`는 active 맵을 반환하는 것으로 호환 유지.

**상태 (2026-04-29)**: PR-C로 구현됨 (`feat/p4.5-track-e-map-management`). Mode-A 5 majors + 6 nits + 3 test-bias 모두 fold; backend 251 pytest + frontend 35 vitest + 14 playwright 모두 green.

**스코프**:
- 신규 endpoint 5개 (구현됨): `GET /api/maps` (list), `GET /api/maps/<name>/image` (single map PNG), `POST /api/maps/<name>/activate` (admin, atomic symlink swap), `DELETE /api/maps/<name>` (admin, 활성 맵엔 409 거부), `GET /api/maps/<name>/yaml`.
- Path traversal 방지: `name` regex `^[a-zA-Z0-9_-]{1,64}$`, 절대 사용자 입력 그대로 path concat 금지.
- 권한: list/image는 `require_user`, activate/delete는 `require_admin` (PR-A 패턴 그대로).
- SPA Map.svelte 확장: 맵 선택 패널 (사이드 또는 페이지 상단 토글), 각 맵에 "기본으로 지정" / "삭제" 버튼 (admin disabled), confirm dialog reuse, 활성 맵 강조 표시.

**UX 결정**: 새 페이지 만들지 않고 **B-MAP 페이지에 통합**. 운영자가 "이 맵으로 본다"와 "이 맵을 활성화한다"가 같은 화면에서 자연스러움.

**예상 작업량**: webctl ~250 LOC + 테스트 ~150 LOC + SPA ~200 LOC + 테스트 ~50 LOC ≈ 650 LOC. PR-B 머지 후 Track E로 단독 진행 (Track D보다 우선 — 운영 편의성 더 직접적).

---

## 9. 보류 / 추후 결정

- **차트 라이브러리**: P1 진입 시 결정 (uPlot 후보, lightweight + Canvas 기반).
- **B-MAP particle cloud**: P0가 아닌 P1로 옮김 (B-DIAG와 함께). 부하는 0이지만 첫 구현 부하 줄임.
- **I1 추가 도입 여부**: I2가 실 운영에서 부족하다고 판명되면 (예: 매 방송마다 같은 transient 반복) Phase 5 이후에 평가.
- **mobile native app**: 추후 결정. PWA로 충분할 수도.

---

## 10. 참고 링크

- [SYSTEM_DESIGN.md](./SYSTEM_DESIGN.md) — RT pipeline / AMCL / FreeD / 매핑 (백엔드)
- [PROGRESS.md](./PROGRESS.md) — 일별 진행 상태
- [doc/history.md](./doc/history.md) — Phase-level decision history (한국어)
- [godo-webctl/CODEBASE.md](./godo-webctl/CODEBASE.md) — webctl module map
- (예정) `godo-frontend/CODEBASE.md` — frontend module map (Phase 1 진입 시 생성)
- `.claude/memory/frontend_stack_decision.md` — Vite + Svelte 결정 기록
