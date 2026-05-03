# SHOTOKU base-move & two-point cal-reset 설계 문서

> **Status**: deferred. issue#29 후보. SHOTOKU 베이스 이동/회전 보정 + 두-지점 캘리브레이션 리셋 워크플로우의 장기 설계 문서.
> Linked memory: `.claude/memory/project_shotoku_base_move_workflow.md` (작성 예정 — 이 문서가 issue#29로 ship될 때 lock).
> Author: 2026-05-03 KST (issue#27 진행 중 운영자가 base-move 시 FreeD 좌표계의 회전 의존성을 짚으면서 surfaced)
> Prerequisites: issue#27 (output_transform) merged + issue#28 (B-MAPEDIT-3 yaw rotation) merged.

---

## 1. 배경 및 surfaced 문제

### 1.1 현재 단순 가정의 한계

GODO의 1-shot calibrate (현재 production path)는 다음을 가정한다:

- LiDAR가 측정한 베이스 world position `(lidar_x, lidar_y)` 와 캘리브레이션 anchor 간의 차이 `(dx, dy)` 를 FreeD 패킷의 X/Y에 더하면 끝.
- yaw 방향 보정은 LiDAR yaw (= base_yaw + pan_angle) 와 FreeD pan 의 차이로 implicitly 보정 (그러나 production path는 dyaw=0 으로 운영, 회전 보정 사실상 미적용).
- 이 가정은 **베이스가 평행이동만 하고 회전하지 않는다**는 강한 전제 위에 성립.

CLAUDE.md §9 "Confirmed facts":
> The base does not rotate. Only the LiDAR rotates (with the pan head). The dolly wheels are always parallel, making physical base rotation very hard.

따라서 평면 평행이동만 가정하는 것은 운영상 합리적이었음. 그러나 다음 두 가지 시나리오가 감춰져 있었음:

### 1.2 SHOTOKU FreeD 좌표계의 본질

SHOTOKU FreeD 패킷의 X/Y/Z는 **two-point calibration으로 확정된 베이스 frame 안에서의 좌표**이지, 절대 world frame 좌표가 아님:

```
FreeD frame (cal-anchored frame):
  cam_x_FreeD = base_x_cal + R(base_yaw_cal) · local_camera_offset_x
  cam_y_FreeD = base_y_cal + R(base_yaw_cal) · local_camera_offset_y

  ※ local_camera_offset = boom 길이/각도/회전 + head pan/tilt 등 크레인 내부 sensor 결과
  ※ base_*_cal = SHOTOKU two-point calibration이 결정한 BASE 원점·축정렬
                  (운영 표준은 두-지점 cal 후 base_xy_cal=(0,0), base_yaw_cal=0)
```

LiDAR world frame은 우리 PGM 지도 + AMCL의 frame:

```
LiDAR world frame:
  cam_x_world = base_x_world + R(base_yaw_world) · local_camera_offset_x
  cam_y_world = base_y_world + R(base_yaw_world) · local_camera_offset_y

  ※ local_camera_offset 은 위와 동일 (크레인 내부 sensor는 frame과 무관)
```

두 frame을 일치시키는 transform:

```
cam_world = base_world + R(base_yaw_world - base_yaw_cal) · (cam_FreeD - base_cal)
```

base_yaw_world == base_yaw_cal 인 동안에는 회전항이 항등이라 단순 평행이동으로 환원되고, 이게 현재 production path가 동작하는 이유.

---

## 2. 세 가지 운영 케이스

### 2.1 Case A — 베이스 평행이동만 (current production)

```
base_yaw_world == base_yaw_cal  (회전 없음)
base_xy_world ≠ base_xy_cal     (이동만)

→ R(0) = I, local_camera_offset 그대로
→ cam_world = cam_FreeD + (base_world - base_cal) = cam_FreeD + (dx, dy)
```

✅ **현재 1-shot calibrate가 정확히 이 케이스 처리**. (dx, dy) 를 smoother → apply_offset_inplace 경로로 FreeD X/Y에 더함.

### 2.2 Case B — 베이스 회전 (현재 미처리)

```
base_yaw_world ≠ base_yaw_cal  (Δψ = base_yaw_world - base_yaw_cal)

→ cam_world = base_world + R(Δψ) · (cam_FreeD - base_cal)
→ pan_world = pan_FreeD + Δψ                        (UE측 pan에도 Δψ 더해야 함)
→ tilt/roll/z = unchanged                            (head 각도/높이는 base 회전과 무관)
```

미처리 영역. operator의 운영 환경에서 베이스가 회전할 일은 거의 없지만 (도리/휠 평행 고정), 만약 발생하면:
- LiDAR가 측정한 cam world position과 (cam_FreeD + dx,dy) 보정값이 회전한 만큼 어긋남
- UE 측 카메라 heading도 어긋남
- operator가 재 calibrate 하면 일시 해소 (anchor를 새 base 위치+yaw로 재설정)되지만, 회전 중에는 계속 어긋남

### 2.3 Case C — SHOTOKU two-point calibration 리셋

운영자가 SHOTOKU를 재캘리브레이션하면 (예: 베이스 이동 후 영점 재정의):
- FreeD가 보고하는 frame이 새 cal-anchored frame으로 즉시 변경
- 우리 시스템이 가지고 있던 (dx, dy) anchor 는 OLD cal frame 기준이라 즉시 무의미
- LiDAR가 측정하는 base position은 변하지 않음 (PGM world frame은 그대로)
- 우리 anchor를 **재구축**해야 함

---

## 3. 수식 정리 (구현 시 참조)

운영 표준이 `base_xy_cal=(0,0), base_yaw_cal=0` (SHOTOKU two-point cal 기본값) 이라 가정하면:

```
변수:
  cam_FreeD = (Fx, Fy)              FreeD 패킷의 X/Y (FreeD frame)
  pan_FreeD                          FreeD 패킷의 Pan (FreeD frame)
  base_world = (Bx, By)              우리 LiDAR가 측정한 base의 PGM world position
  base_yaw_world = ψ                 우리 LiDAR가 측정한 base의 yaw (= LiDAR yaw - pan_FreeD)

산식:
  cam_world_x = Bx + Fx·cos(ψ) - Fy·sin(ψ)
  cam_world_y = By + Fx·sin(ψ) + Fy·cos(ψ)
  pan_world   = pan_FreeD + ψ
  tilt/roll/z = unchanged
```

ψ가 작으면 (Case A) `cos≈1, sin≈0` 로 환원되어 `cam_world ≈ (Bx + Fx, By + Fy)` — 현재 동작과 일치.

### 3.1 base_yaw_world 의 연속 측정 (key insight)

**기존 시스템이 이미 가진 신호로 base_yaw_world 를 매 tick 계산 가능**:

```
LiDAR가 측정한 yaw (AMCL 출력) = base_yaw_world + pan_angle_from_head
                              ≡ base_yaw_world + pan_FreeD

따라서:
  base_yaw_world = lidar_yaw - pan_FreeD
```

이 값을 매 tick 트래킹하면:
- 정상 (Case A): constant (cal anchor 시점 yaw 값으로 lock)
- drift (Case B): 변화 감지 → operator 알람 + 자동 회전 보정 둘 다 옵션
- 갑자기 점프 (Case C): SHOTOKU re-cal 발생을 자동 감지 가능

---

## 4. 운영 워크플로우 제안

### 4.1 Case A (현재 동작) — 변경 없음

1-shot calibrate 그대로 사용.

### 4.2 Case B (베이스 회전) — 자동 보정 옵션

1. 매 cold-path tick (5 Hz) 마다 `base_yaw_world = lidar_yaw - pan_FreeD` 계산
2. 직전 anchor의 base_yaw_cal 과 비교, |Δψ| > threshold (예: 0.5°) 이면:
   - 옵션 a: SPA 알람 + operator 수동 재 calibrate
   - 옵션 b: 자동으로 anchor 의 base_yaw_cal 갱신 + R(Δψ) 보정 입혀서 smoother 통과
3. 둘 다 지원 (operator가 toggle), 운영 환경에 따라 선택

### 4.3 Case C (SHOTOKU re-cal) — Re-anchor 워크플로우

```
[Trigger] 운영자가 SHOTOKU 두-지점 cal 재실행
  ↓
[Step 1] SPA System 탭에 "Re-anchor SHOTOKU base" 버튼 노출
         (또는 base_yaw_world 의 갑작스런 점프 자동 감지)
  ↓
[Step 2] 운영자가 카메라를 known reference 자세로 park:
         - boom 중심 (camera optical center가 base 위에)
         - pan = 0, tilt = horizontal
         - SHOTOKU의 home position
  ↓
[Step 3] SPA 버튼 클릭 → 동시 capture:
         - LiDAR pose: (lidar_x, lidar_y, lidar_yaw)
         - FreeD pose: (Fx, Fy, pan_FreeD, ...)
  ↓
[Step 4] 시스템이 새 anchor 계산:
         base_xy_cal = lidar_xy   (LiDAR가 본 base 위치)
         base_yaw_cal = lidar_yaw - pan_FreeD  (그 시점 base yaw)
         (FreeD frame에서 base는 0,0,0 이므로 평행이동·회전 모두 캡쳐)
  ↓
[Step 5] anchor 를 runtime state로 저장:
         - in-process Seqlock 으로 hot-path 에 publish
         - 재부팅 후 살아남도록 /var/lib/godo/anchor.toml 같은 곳에 persist
         - SPA에 마지막 anchor timestamp + value 표시
```

### 4.4 자동 detect 옵션

`base_yaw_world` 의 시계열을 보고:
- 1초 동안 |dψ/dt| > threshold (예: 5°/s) → Case C re-cal 의심, SPA 알람
- 평균값이 anchor 와 |Δψ| > threshold 로 안정화되면 → Case B 회전 의심, 자동/수동 보정 가능

---

## 5. 구현 의존성

issue#29 ship 전 선행 필요:

1. **issue#27 (output_transform)** — 최종 송출 단에 transform 단이 마련되어 있어야 R(ψ) 회전 보정을 깔끔하게 끼워 넣을 수 있음. issue#27이 마련하는 자리가 정확히 base-move 회전 보정이 들어갈 자리.
2. **issue#28 (B-MAPEDIT-3 yaw rotation)** — 지도 자체의 yaw 보정이 별개 axis이지만, "yaw 처리 패턴 + dual GUI+numeric input" 의 표준이 정립되어 있어야 base-yaw 보정 UI에서 재사용 가능.
3. **issue#26 (cross-device latency measurement)** — base re-anchor 시 LiDAR와 FreeD의 simultaneous capture 가 필요한데, 두 시스템 간 시각 동기화가 보장돼야 함. issue#26 측정 도구가 두 frame 간 latency 를 quantify 한 후 들어가는 게 안전.

---

### 5.1 추가 의존성 — issue#27 HIL 발견 사항 (2026-05-04 KST)

issue#27 ship 시 운영자가 발견: **tracker는 YAML `origin[2]` (theta)를 boot 시 읽지 않음**. 별도 `cfg.amcl_origin_yaw_deg` Tier-2 config 키를 사용 (`cold_writer.cpp:371,377,385,515,521,529,649,655,663`). issue#28 (B-MAPEDIT-3) 가 먼저 이 plumbing을 고친 후에야 issue#29의 base re-anchor 워크플로우가 정상 동작 가능 — re-anchor가 새 base_yaw_cal 을 결정해도 tracker가 YAML theta 무시하면 의미 없음. issue#28의 fix path (a) "YAML origin[2] → AMCL frame 직결" or (b) "transactional 동시 갱신" 결정에 따라 issue#29 의 anchor 저장 형식(YAML vs. 별도 anchor.toml)도 영향 받음.

## 6. 미해결 질문 (issue#29 시작 시 풀어야 할 항목)

1. **Re-anchor 캡쳐의 simultaneous 보장**: LiDAR cold-path는 5 Hz, FreeD hot-path는 60 Hz. capture 시점에 두 값이 같은 물리 instant 를 반영하는지 보장 방법 (SO_TIMESTAMPNS_NEW + matching window?). issue#26 결과에 의존.
2. **회전 보정 적용 시점**: smoother 입력 (cold-path) vs apply_offset_inplace 단계 (hot-path). 회전 변환은 sin/cos 호출이 hot-path 60 Hz 에서 부담될 수 있어 lookup table or ramp-only 전략 필요.
3. **anchor persistence 형식**: 별도 TOML 파일 vs `tracker.toml` 의 한 섹션. 운영자가 anchor 를 manual override 할 수 있어야 함 vs 자동 갱신과의 충돌 방지.
4. **Case B 자동 보정 toggle 의 default**: opt-in (안전 우선) vs opt-out (편의 우선). operator HIL 결과에 의존.
5. **re-cal detection algorithm**: yaw 점프만으로 충분한가, 아니면 (base_x, base_y) 도 같이 봐야 하는가. SHOTOKU re-cal 은 보통 영점 재정의라 base_xy 도 같이 점프할 가능성 높음.
6. **UE 측 좌표계 정의 일치**: PIXOTOPE 가 base-move 후 변경된 frame 을 그대로 받아서 처리할지, 아니면 PIXOTOPE 의 reference 도 같이 갱신해야 할지. PIXOTOPE 측 워크플로우 확인 필요.
7. **head pan/tilt/roll 의 base 회전 의존성**: 본 문서는 head 각도가 base 회전과 독립이라 가정 (pan은 더해주지만 tilt/roll은 unchanged). 실제 SHOTOKU head 가 base local frame 의 pan 을 보고하는지, world frame 의 pan 을 보고하는지 확인 필요. (만약 world frame 이라면 pan 보정도 불필요.)

---

## 7. 트리거 조건 (언제 ship)

issue#29 는 다음 중 하나가 발생하면 즉시 spec lock + Planner kickoff:

- **운영 중 SHOTOKU 베이스가 2회 이상 의도치 않게 회전**한 사례 보고. (Case B 가 production-realistic)
- **SHOTOKU two-point cal 재실행이 운영 중 빈번**해진다 (현재는 거의 한 번 잡으면 끝). (Case C 의 빈도 증가)
- **PIXOTOPE 측에서 회전 보정 문제로 운영 어려움** 보고.
- **issue#28 ship 후 자연스럽게 yaw 처리 흐름이 정립**되어, issue#29 가 손쉽게 들어갈 수 있는 상태가 됨.

위 조건이 한동안 안 일어나면 이 문서는 현 상태로 보존, 필요할 때 picked up. (UART migration `issue#17` 과 동일한 deferred 패턴.)

---

## 8. 참조

- `CLAUDE.md` §1 Project overview, §9 Confirmed facts (base 비회전 가정)
- `SYSTEM_DESIGN.md` §6.1 hot-path / smoother 구조
- `production/RPi5/src/udp/sender.cpp` `apply_offset_inplace` (현재 dx/dy/dyaw 합성 위치)
- `production/RPi5/src/godo_tracker_rt/main.cpp:97-150` thread_d_rt RT 루프
- `.claude/tmp/plan_issue_27_map_polish_and_output_transform.md` (issue#27 plan — output_transform 단 위치)
- `.claude/memory/project_calibration_alternatives.md` (issue#3 hint + Live mode pipelined hint + far-range automated rough-hint)
- D1 spec: `/tmp/D1.jpeg` (operator-supplied 2026-05-03 KST), 본 repo 외부 자산
