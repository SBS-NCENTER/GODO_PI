# godo-mapping — SLAM 매핑 도구

GODO LiDAR 기반 카메라 위치 추적 시스템의 **2D occupancy-grid 지도**를
생성하는 Docker 기반 SLAM 툴체인입니다. RPLIDAR C1을 들고 컨트롤룸을 약 1분
정도 천천히 걸으면 `maps/<map_name>.{pgm,yaml}` 파일이 만들어지며, 이 파일은
`production/RPi5`의 `occupancy_grid.cpp::load_map`이 그대로 읽어들입니다.

ROS 2 의존성은 전부 컨테이너 안에 격리되어 있어 호스트 RPi 5에는 ROS를
설치하지 않습니다.

## 사전 준비

### 호스트 요구사항

- Linux (RPi 5 / 일반 dev box)
- Docker
- (실행 시에만) RPLIDAR C1 + USB CP2102 동글
- (선택) `bash`, `python3` — `verify-no-hw.sh --quick`에 필요

### 1회용 셋업

```bash
git clone <repo> GODO
cd GODO/godo-mapping
bash scripts/verify-no-hw.sh --quick     # ~1초, Docker 데몬 불필요
bash scripts/verify-no-hw.sh --full      # ~5분, ~800 MB pull, Docker 데몬 필요
```

`--full`은 `godo-mapping:dev` 이미지를 빌드하고 `--help` smoke 테스트까지
끝냅니다. 이미지가 캐시된 뒤에는 LiDAR가 연결된 운영 환경에서 추가 네트워크
없이 매핑을 시작할 수 있습니다.

## 운영 절차 (5단계)

LiDAR가 USB로 꽂혀 있고 `godo-mapping:dev` 이미지가 빌드된 상태를 전제합니다.

```bash
cd /path/to/GODO
bash godo-mapping/scripts/run-mapping.sh control_room_v1
```

1. 위 명령을 실행하면 컨테이너가 뜨면서 `slam_toolbox`와 `rplidar_ros`가
   `/scan` 토픽을 시작합니다.
2. RPLIDAR C1을 손에 들고 매핑할 공간을 **천천히 (~30 cm/s)** 한 바퀴 돕니다.
   가능하면 시작점으로 돌아와 loop closure가 일어나도록 합니다.
3. 약 1분 정도 (스튜디오 면적 기준) 걸린 뒤 터미널에서 `Ctrl+C`를 누릅니다.
4. `entrypoint.sh`의 trap이 `nav2_map_server map_saver_cli`를 호출해
   `godo-mapping/maps/control_room_v1.pgm` + `.yaml`을 저장합니다.
5. 두 파일을 `/etc/godo/maps/`로 복사하면 production tracker가 다음 부팅에서
   읽어들입니다.

```bash
sudo cp godo-mapping/maps/control_room_v1.{pgm,yaml} /etc/godo/maps/
sudo systemctl restart godo-tracker
```

### 환경 변수 오버라이드

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `LIDAR_DEV` | `/dev/ttyUSB0` | LiDAR가 다른 USB 포트로 잡힐 때 사용 |
| `IMAGE_TAG` | `godo-mapping:dev` | 다른 이미지 태그를 쓸 때 |

```bash
LIDAR_DEV=/dev/ttyUSB1 bash godo-mapping/scripts/run-mapping.sh studio_v2
```

## 첫 매핑 후 검증 (필수, plan F11)

저장된 YAML 키 집합이 `production/RPi5/src/localization/occupancy_grid.cpp`의
허용 집합과 일치해야 tracker가 부팅 시 throw하지 않습니다.

```bash
cat godo-mapping/maps/control_room_v1.yaml
```

콜론 좌측의 모든 키를 `occupancy_grid.cpp:148-154`의 union 집합과
대조합니다.

```text
required    = { image, resolution, origin, occupied_thresh,
                free_thresh, negate }
warn_accept = { mode, unknown_thresh }
```

이 집합 밖의 키 (예: `cost_translation_table`)가 보이면:

- ❌ `entrypoint.sh`에서 YAML을 후처리하지 마세요.
- ✅ Path (a) ONLY: `production/RPi5/src/localization/occupancy_grid.cpp::warn_accept`에
  키를 추가하는 follow-up 이슈를 만듭니다. C++ allowlist이 SSOT입니다.
- 본 작업은 Track A 범위 밖이며, Parent에게 보고 후 별도 세션에서 처리합니다.

## Track B — Repeatability measurement

`godo_tracker_rt`가 `systemctl start godo-tracker`로 떠 있는 상태에서, 베이스를
물리적으로 고정해 두고 OneShot calibration을 N번 반복 실행해 AMCL 결과의
재현성을 측정하는 도구입니다. Phase 1 측정 instrument이며, 결과 CSV는 Phase
5 hardware-in-the-loop E2E 시험의 reference baseline 역할을 합니다.

```bash
python3 godo-mapping/scripts/repeatability.py --shots 100 --interval-s 2.0
```

### 옵션 요약

| 옵션 | 기본값 | 설명 |
| --- | --- | --- |
| `--shots N` | `100` | OneShot 반복 횟수 (`N >= 1`) |
| `--interval-s F` | `2.0` | shot 사이 sleep (초). converge() 평균 ~1초 + 여유 |
| `--out PATH` | `<repo>/godo-mapping/measurements/repeatability_<ISO>.csv` | 결과 CSV 경로; 부모 디렉터리는 자동 생성 |
| `--socket PATH` | `/run/godo/ctl.sock` | UDS 소켓 경로 |
| `--uds-timeout-s F` | `1.0` | UDS 호출 timeout (초) — tracker server-side `SO_RCVTIMEO`에 맞춤 |
| `--oneshot-timeout-s F` | `15.0` | OneShot 후 `get_mode==Idle` 대기 한도 |
| `--dry-run` | off | tracker probe만 하고 shot은 트리거하지 않음 |

### CSV 스키마

```text
idx, timestamp_unix,
valid, x_m, y_m, yaw_deg, xy_std_m, yaw_std_deg,
iterations, converged, forced, published_mono_ns
```

`valid=0`인 행은 sentinel입니다 (timeout / divergence / 일시적 UDS 실패).
`valid=1` 행만 통계 요약에 포함됩니다.

### Exit 코드

| 코드 | 의미 |
| --- | --- |
| 0 | 성공 |
| 1 | CLI 검증 실패 (예: `--shots 0`) |
| 2 | tracker UDS unreachable (초기 ping 실패) |
| 3 | tracker가 Idle이 아님 (Live / OneShot 진행 중) |
| 4 | `set_mode("OneShot")` 거부됨 |
| 5 | CSV 파일 open / write 오류 |
| 6 | 첫 shot 전에 SIGINT — 행이 한 줄도 기록되지 않음 |
| 7 | tracker-death streak: UDS 연속 실패 3회 — `journalctl -u godo-tracker` 점검 |
| 130 | SIGINT (적어도 1행 기록 후) — POSIX 128 + SIGINT |

### 운영 권장 흐름

1. 베이스를 calibration 위치에 고정.
2. `systemctl is-active godo-tracker` 확인.
3. `python3 godo-mapping/scripts/repeatability.py --shots 100 --dry-run`로
   tracker 도달성 + Idle 상태 확인.
4. 본 측정: `python3 godo-mapping/scripts/repeatability.py --shots 100`.
5. CSV를 pandas / Excel에서 열어 `xy_std_m`, `x_m`/`y_m` 분포를 확인.

> `--interval-s F`는 best-effort sleep입니다. converge() 시간이 길어지면
> 실제 간격은 `max(interval_s, shot_duration)`이며 harness는 보정하지
> 않습니다.

## Live pose watch (cmd window 모니터링)

본방 / 리허설 중에 다른 cmd 창을 띄워두고 AMCL의 마지막 pose를 한 줄씩
실시간으로 흘려보내는 도구입니다. 운영자가 "지금 tracker가 무엇을 보고
있는가"를 한 화면으로 보는 용도이며, repeatability harness와 달리 tracker
상태를 변경하지 않습니다 (`get_last_pose` read-only).

```bash
python3 godo-mapping/scripts/pose_watch.py --interval 0.5
```

### 옵션 요약

| 옵션 | 기본값 | 설명 |
| --- | --- | --- |
| `--socket PATH` | `/run/godo/ctl.sock` | UDS 소켓 경로 |
| `--interval F` | `0.5` | 폴링 간격 (초). `0.5 = 2 Hz` |
| `--format text\|json` | `text` | `text` = 사람용 1줄, `json` = log shipping용 1줄 JSON |
| `--once` | off | 한 줄 출력 후 종료 (smoke test 용도) |

### 출력 예 (text)

```text
2026-04-27T15:32:01Z  x=+1.234  y=-2.567  yaw=+42.10  std=12.3mm  iter= 12  OneShot  OK
2026-04-27T15:32:01.5Z  x=+1.234  y=-2.567  yaw=+42.10  std=12.3mm  iter= 12  OneShot  OK
DISCONNECTED  ConnectionRefusedError: [Errno 111] Connection refused
2026-04-27T15:32:09Z  x=+1.235  y=-2.566  yaw=+42.11  std=11.8mm  iter= 11  Live     OK
```

### 재접속 동작

tracker가 죽거나 (systemctl restart) UDS가 일시적으로 사라지면:

1. 한 줄짜리 `DISCONNECTED <원인>` sentinel을 출력.
2. backoff 1s → 2s → 4s 순으로 retry, 그 이후로는 매 4초마다 재시도.
3. 재접속에 성공하면 sentinel 없이 정상 pose 줄로 돌아옵니다.

### 권장 운용

`tmux` / `screen` 안에서 띄워두면 SSH 세션이 끊어져도 살아남습니다.
`Ctrl+C` (SIGINT) 또는 `kill <pid>` (SIGTERM) 모두 ~200 ms 안에 클린하게
exit 0으로 종료합니다.

```bash
tmux new -s pose-watch
python3 godo-mapping/scripts/pose_watch.py --format json | tee /tmp/pose-$(date +%Y%m%d).log
# Ctrl+B D로 detach
```

## 트러블슈팅

### `LiDAR device '/dev/ttyUSB0' not found`

다른 USB 포트로 잡혔을 가능성이 큽니다. `dmesg | tail` 또는 `ls /dev/ttyUSB*`로
확인 후 `LIDAR_DEV` 환경변수로 오버라이드합니다.

### `container 'godo-mapping' is already running`

이전 실행이 정상 종료되지 않았습니다.

```bash
docker stop godo-mapping
docker rm godo-mapping        # --rm으로 시작했지만 강제 종료된 경우
```

### `'maps/<name>.pgm' already exists`

같은 이름으로 두 번 매핑하려 하고 있습니다. 의도적이라면 기존 파일을
백업한 뒤 삭제하거나, 새 이름을 사용합니다.

```bash
mv godo-mapping/maps/control_room_v1.pgm godo-mapping/maps/control_room_v1.pgm.bak
mv godo-mapping/maps/control_room_v1.yaml godo-mapping/maps/control_room_v1.yaml.bak
```

### Stale dev images

오래된 dev 이미지를 정리하거나 처음부터 다시 빌드하려면:

```bash
docker image prune --filter label=godo-mapping
# 또는 강제 재빌드:
docker rmi godo-mapping:dev && bash scripts/verify-no-hw.sh --full
```

### `MAP_NAME env-var is required`

내부에서만 발생합니다. `scripts/run-mapping.sh`를 우회해 직접 `docker run`을
한 경우이며, `-e MAP_NAME=<name>`을 추가해야 합니다.

### Ctrl+C 후 지도 파일이 비어 있음 / 만들어지지 않음

매핑 시작 후 너무 빨리 (`launch graph` 가 다 뜨기 전에) Ctrl+C 했을 가능성이
큽니다. 약 5초 정도 기다렸다가 매핑 동작을 시작하세요.

### Hardware-free 검증

LiDAR가 연결되지 않은 dev 박스에서 코드 수정 직후 lint:

```bash
bash godo-mapping/scripts/verify-no-hw.sh --quick   # ~1초
bash godo-mapping/scripts/verify-no-hw.sh --full    # ~5분 (Docker 데몬 필요)
```

### 지도가 한 프레임짜리로만 저장됨 (≤ 200 occupied pixels)

PGM이 단일 위치에서 찍힌 부채꼴 모양만 담고 있고 occupied 픽셀이 200개 이하라면
`rf2o_laser_odometry_node`가 죽었거나 publish가 멈춘 경우입니다. 진단:

```bash
docker exec godo-mapping ros2 topic hz /odom_rf2o     # ~10 Hz가 정상; 0 Hz면 rf2o 사망/침묵
docker logs godo-mapping 2>&1 | tail -100             # rf2o 크래시 스택트레이스 확인
```

`/odom_rf2o`가 0 Hz라면 `slam_toolbox`가 `odom -> laser` TF를 못 받아
`map_saver_cli`가 단일 스캔만 적분하게 됩니다. CODEBASE.md invariant (h) 참조.

## 디렉터리 구조

```text
godo-mapping/
├─ Dockerfile                    # FROM ros:jazzy-ros-base + apt + 2개 colcon overlay (rplidar_ros, rf2o_laser_odometry)
├─ launch/map.launch.py          # rf2o + rplidar_c1 + slam_toolbox async 노드
├─ config/
│   ├─ rf2o.yaml                 # rf2o_laser_odometry 파라미터 (Tier-2)
│   └─ slam_toolbox_async.yaml   # base_frame=laser, save_map_timeout=10.0
├─ entrypoint.sh                 # SIGINT/SIGTERM trap → map_saver_cli
├─ scripts/
│   ├─ run-mapping.sh            # 호스트 docker-run 래퍼
│   └─ verify-no-hw.sh           # --quick / --full
├─ tests/test_entrypoint_trap.sh # bare-bash trap mock 테스트
├─ maps/                         # *.pgm, *.yaml 결과물 (gitignored)
├─ README.md                     # ← 이 문서
└─ CODEBASE.md                   # 모듈 맵 + invariants + change log
```

## 참고

- 컨테이너 내부 ROS 분리: `production/RPi5/`와 `godo-webctl/`는 ROS를 import하지
  않습니다 (`grep -rn 'rclcpp\|ament' production/RPi5/src/` returns 0).
  `--network=host`는 안전합니다.
- 컨테이너는 2026-04-29부터 `rf2o_laser_odometry_node`도 함께 띄워서 `/scan`을
  scan-to-scan registration으로 받아 `odom -> laser` TF를 publish합니다 (구
  static identity TF의 단일-프레임 매핑 버그 수정). CODEBASE.md invariant (h) 참조.
- 매핑 결과 SSOT: `production/RPi5/src/localization/occupancy_grid.cpp::load_map`
  (PGM P5 8-bit + flat key:value YAML).
- 본 도구는 매핑 전용입니다. localization (AMCL)은 production tracker가 매핑된
  지도를 입력 받아 별도로 처리합니다.
