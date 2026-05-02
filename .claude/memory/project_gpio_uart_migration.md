---
name: GPIO UART 직결 migration plan (issue#17 candidate)
description: RPLIDAR C1을 CP2102N USB 어댑터에서 Pi 5 GPIO UART (PL011) 직결로 옮기는 long-term migration. 결정 컨텍스트 + trigger 조건. 풀 spec은 doc/RPLIDAR/RPi5_GPIO_UART_migration.md.
type: project
---

## What

CP2102N USB-to-UART 어댑터를 제거하고 RPLIDAR C1의 4-pin (VCC + TX + RX + GND)을 Pi 5 GPIO UART4 (GPIO 12/13, `/dev/ttyAMA4`)에 직결.

이미 ttyAMA0은 FreeD 수신용 사용 중 (PL011 UART0, GPIO 14/15). UART4는 자유 + I2C/SPI/I2S 핀과 미충돌.

## Why (decisions worth remembering)

### Trigger — issue#14 mapping pipeline HIL의 cp210x stale state

operator HIL (2026-05-02 KST):
- godo-tracker 정지 → 즉시 mapping container 시작
- → CP2102N USB CDC가 SET_LINE_CODING에 응답 안 함 (`-110 ETIMEDOUT`)
- → rplidar_node `code 80008004` (RESULT_OPERATION_TIMEOUT)
- → 약 10초 기다리면 정상

CP2102N stale state는 USB CDC layer 자체의 race. SDK는 정상 cleanup (stop + 200ms + setMotorSpeed(0) + close) 수행함. 그럼에도 driver 내부 handle이 immediate cleanup 안 됨.

### 단기 mitigation (issue#16, 1단계) — 채택

webctl이 mapping start 전:
- cp210x readable check (`os.open(O_RDWR|O_EXCL)`)
- 필요시 driver unbind/rebind via sysfs
- Pre-check gate (Start 버튼 활성화 조건 명시 + SPA에 표시)

이게 충분하면 GPIO migration 보류 가능.

### 장기 mitigation (issue#17, 이 문서) — 보류 / on-demand

- USB CDC layer 자체 제거 → stale state 원인 사라짐
- 다른 부수 효과: latency ↓ (5-15ms → <1ms), 어댑터 단일 실패점 제거

### 운영 시나리오 적합성

- LiDAR가 크레인 베이스 pan-axis 중심에 mount → 한 번 설치 후 거의 분리 안 함
- → hot-plug 필요 없음 → GPIO 직결의 Pi-power-off cost 무시 가능
- operator 직접 발언 (2026-05-02 KST): "자주 안 빼고 한번 설치하면 라이다와 연결 해제는 거의 안할거야"

### 미선택 이유 (지금 ship 안 하는 이유)

- 1단계로 cp210x stale state가 운영에 충분히 영향 안 줄 것으로 기대
- hardware 변경 (점퍼 와이어 + decoupling cap 납땜) 작업 시간
- config.txt + 재부팅 + tracker.toml 갱신 cascade

## How to apply

### Trigger (when to actually do it)

다음 중 하나가 충족되면 issue#17 ship:

1. issue#16 단기 mitigation 후에도 cp210x stale state가 매핑 1회당 5초 이상 추가 지연 빈번
2. CP2102N 어댑터 자체 고장 (단일 실패점 actualisation)
3. operator가 명시적으로 GPIO migration 요청

### 작업 순서

doc/RPLIDAR/RPi5_GPIO_UART_migration.md §5 follow:
1. PSU 27W 확인
2. C1 4-pin → GPIO 12/13/5V/GND 점퍼 와이어 + 1000µF cap 납땜
3. config.txt에 `dtoverlay=uart4-pi5` 추가 + reboot
4. tracker.toml `lidar_port = "/dev/ttyAMA4"`
5. SPA System tab → tracker restart → Calibrate sanity check
6. mapping pipeline scenarios A-G 검증
7. issue#10 (udev `/dev/rplidar` 심링크) deprecate — GPIO 직결이면 enumeration 변동 자체 없음

### 작업 시간

~1시간 (점퍼 작업 30분 + config 5분 + tracker 검증 10분 + mapping 검증 20분).

## Cross-references

- `doc/RPLIDAR/RPi5_GPIO_UART_migration.md` — 풀 spec (이 메모리의 운영 SSOT)
- `doc/RPLIDAR/RPLIDAR_C1.md` §6 — MCU/SBC compatibility matrix, electrical spec
- `.claude/memory/project_calibration_alternatives.md` — sibling calibration architecture decisions
- `production/RPi5/src/core/config_defaults.hpp` — `LIDAR_PORT` default 변경 시 동기화
- `production/RPi5/systemd/godo-mapping@.service` — `--device=${LIDAR_DEV}` 사용
- issue#10 (udev /dev/rplidar) — GPIO migration 후 deprecate
- issue#16 (mapping pre-check + cp210x recovery) — 단기 mitigation, 1단계
- issue#17 (이 entry) — GPIO migration, 2단계
