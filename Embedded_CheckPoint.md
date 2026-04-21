# Embedded System Reliability Checklist

> Critical failure patterns per platform (Arduino, ESP8266/ESP32, STM32, Raspberry Pi, etc.) and a pre-deployment checklist for long-term operation.

---

## 1. Cross-platform failure patterns

Recurring defects that show up on virtually every embedded platform.

### 1.1 Memory-related defects

| Failure type | Symptom | Cause | Mitigation |
| --- | --- | --- | --- |
| **Stack overflow** | Random crashes, variable corruption | Deep recursion, large local arrays | Monitor stack usage; cap local buffer sizes |
| **Heap fragmentation** | `malloc` failure after long runtime | Repeated dynamic alloc/free | Prefer static allocation; use memory pools |
| **Stack-heap collision** | Unpredictable behavior, hard faults | Excessive stack + heap usage | Reserve guard regions in the linker script |
| **Buffer overrun** | Adjacent data corruption, security holes | Missing bounds checks | Use `strncpy`, validate array indices |
| **Dangling pointers** | Intermittent crashes | Reference to freed memory | NULL after free; clarify ownership |

**Practical tip — measure free memory at runtime (Arduino)**

```cpp
// Free SRAM at runtime
int freeMemory() {
    extern int __heap_start, *__brkval;
    int v;
    return (int)&v - (__brkval == 0 ? (int)&__heap_start : (int)__brkval);
}

void loop() {
    if (freeMemory() < 200) {
        // Warning: memory nearly exhausted
    }
}
```

### 1.2 Missing watchdog timer (WDT)

Skipping the watchdog is **one of the most common design defects** in systems intended for long-term operation.

- **Symptom**: the firmware enters an infinite loop or hits a hard fault and stays dead forever.
- **Mitigation**: pet the WDT from the main loop under nominal conditions, and deliberately skip the reset when abnormal state is detected to force a reboot.

```cpp
// Arduino example
#include <avr/wdt.h>

void setup() {
    wdt_enable(WDTO_8S);  // 8-second watchdog
}

void loop() {
    wdt_reset();  // reset only when healthy
    // main logic
}
```

```cpp
// ESP8266 / ESP32 example
void loop() {
    ESP.wdtFeed();  // software WDT pet
    yield();        // yield to system tasks (mandatory)
}
```

### 1.3 Power-related defects

| Failure type | Symptom | Cause | Mitigation |
| --- | --- | --- | --- |
| **Brown-out** | Intermittent resets, data corruption | Voltage dip when motors / relays switch | Decoupling capacitors; separate supply rail |
| **Power noise** | Unstable ADC readings, comms errors | Switching-regulator ripple | LC filters, LDOs, ferrite beads |
| **No reverse-polarity protection** | Dead ICs | Reversed supply connection | Series diode or P-MOSFET protection |
| **Surge / ESD** | Immediate or delayed failure | Surge via external connectors | TVS diodes, ESD-protection ICs |
| **Inrush current** | Blown fuses, unstable supply | Large bulk-cap initial charge | Soft-start circuit or NTC thermistor |

### 1.4 Communication-related defects

| Link | Common failures | Mitigation |
| --- | --- | --- |
| **I2C** | Bus lockup (SDA stuck LOW) | Clock-stretching timeouts, bus-recovery routine |
| **SPI** | CS-pin contention, SPI access from ISRs | Dedicated CS pins, never touch SPI from an ISR |
| **UART** | Framing errors, buffer overrun | Checksum / CRC, HW flow control |
| **WiFi / BLE** | No automatic reconnect after drop | Connection watchdog + explicit reconnect logic |
| **UDP** | Packet loss, no ordering guarantee | Sequence numbers, retries, heartbeats |

### 1.5 Interrupt-related defects

- **Race conditions**: declare variables shared between an ISR and the main loop as `volatile`, and guard access with `cli()` / `sei()` or `noInterrupts()` / `interrupts()`.
- **Long processing inside an ISR**: no `Serial.print()`, no `delay()`, no dynamic allocation. Set a flag and handle it from the main loop.
- **Priority inversion**: use priority-inheritance mutexes when running under an RTOS.

---

## 2. Platform-specific failure patterns

### 2.1 Arduino (AVR: ATmega328P, ATmega2560)

| Defect | Explanation | Mitigation |
| --- | --- | --- |
| **`String` heap fragmentation** | Repeated `String` create/destroy fragments the heap → crash after long uptime | Use fixed `char[]` buffers + `snprintf()` |
| **EEPROM write endurance** | 100,000-write limit exceeded → data loss | Minimize write frequency; wear leveling; write only on change |
| **`analogRead()` contamination** | ADC multiplexer retains residual voltage across channel changes | Discard the first reading after a channel switch |
| **`millis()` overflow** | Rolls over to 0 after ~49.7 days → broken time comparisons | Use `(millis() - previousMillis >= interval)` (unsigned subtraction) |
| **PWM / timer conflicts** | `Servo`, `tone()`, and `analogWrite()` share timers | Consult the timer-assignment table; swap libraries on conflict |

### 2.2 ESP8266

| Defect | Explanation | Mitigation |
| --- | --- | --- |
| **Soft WDT reset from missing `yield()`** | The WiFi stack runs in the background; long loops without `yield()` trigger soft WDT | Insert `yield()` whenever blocking for ≥ 100 ms |
| **WiFi instability (auto-reconnect fails)** | Fails to recover after AP disconnect | `WiFi.setAutoReconnect(true)` + manual reconnect logic |
| **Crash during flash write** | Power loss during SPIFFS / LittleFS write corrupts the filesystem | Journaling writes, commit-complete flag |
| **GPIO16 quirks** | GPIO16 behaves differently under `digitalWrite` (no internal pull-up) | Avoid for non-deep-sleep-wake usage |
| **Single ADC channel** | ESP8266 has only one ADC (A0), 0–1 V range | Voltage divider; external MUX for multi-channel |

### 2.3 ESP32

| Defect | Explanation | Mitigation |
| --- | --- | --- |
| **Dual-core race conditions** | Core 0 (WiFi) vs. Core 1 (user code) contending for shared variables | `portMUX`, FreeRTOS mutexes / semaphores |
| **False brown-out detection** | USB supply occasionally triggers unnecessary brown-out resets | Lower the brown-out threshold or disable detection |
| **WiFi + BLE together → heap exhaustion** | Running both stacks simultaneously runs out of heap | Pick one, or use a PSRAM-equipped module |
| **GPIO strap-pin conflicts** | GPIO 0, 2, 5, 12, 15 participate in boot-mode selection | Verify external pull-ups / downs don't break boot |
| **Task stack overflow** | Under-sized FreeRTOS task stacks | Monitor via `uxTaskGetStackHighWaterMark()` |

### 2.4 STM32

| Defect | Explanation | Mitigation |
| --- | --- | --- |
| **Clock misconfiguration** | Wrong PLL / prescaler settings break UART baud rate and timing | Verify the CubeMX clock tree; confirm with an oscilloscope |
| **DMA cache coherency** | DCache ↔ DMA buffer mismatch on Cortex-M7 (e.g., STM32H7) | Place DMA buffers in a non-cacheable region, or invalidate the cache |
| **Interrupt during flash write** | Taking an interrupt while programming internal flash causes a hard fault | Disable interrupts around flash writes |
| **Hard-fault debugging difficulty** | Root cause of a hard fault is hard to find | Implement a hard-fault handler that dumps the stack frame |
| **Power-domain init missing** | Backup domain and analog blocks require explicit enable | Check HAL_PWR and RCC init order |

### 2.5 Raspberry Pi (Linux-based)

| Defect | Explanation | Mitigation |
| --- | --- | --- |
| **SD card corruption** | Sudden power loss corrupts the filesystem | Read-only root FS (OverlayFS), UPS module, periodic `sync` |
| **No hard real-time GPIO** | The Linux scheduler makes microsecond timing unreliable | Delegate real-time control to a separate MCU; use `pigpio` |
| **Swap thrashing** | Running out of physical RAM triggers swap → SD wear + slow-down | Disable or minimize swap; consider zram |
| **Kernel panics** | Driver conflicts, OOM killer activity | Monitor kernel logs; enable the hardware watchdog |
| **Thermal throttling** | CPU clock drops on overheat → sudden performance loss | Heatsink / fan; monitor `vcgencmd measure_temp` |
| **Time-sync failure** | No RTC means time resets on every boot | Add an RTC module or NTP-sync |

---

## 3. Pre-deployment checklist for long-term operation

### 3.1 Power stability

- [ ] Measure supply voltage at peak load (oscilloscope recommended).
- [ ] Confirm decoupling caps placement (100 nF near IC power pins + 10–100 µF at the supply entry).
- [ ] Check voltage-regulator temperature (thermal camera or contact probe).
- [ ] Measure ripple / noise on the power rail (with switching regulators).
- [ ] Verify reverse-polarity and ESD protection.
- [ ] Power-cycle test (brown-out / instant-off scenarios, ≥ 100 cycles).

### 3.2 Memory stability

- [ ] Run static analysis for buffer overruns and uninitialized variables.
- [ ] Measure peak stack / heap usage at runtime (worst case).
- [ ] Audit every `String`, `new`, `malloc` site (replace with static allocation when possible).
- [ ] Compute EEPROM / flash write frequency (will it exceed endurance in its lifetime?).
- [ ] Memory-leak test (≥ 24 h soak; track free-memory trend).

### 3.3 Communication stability

- [ ] Measure error rate (send ≥ 10,000 packets; collect error / loss statistics).
- [ ] Verify timeout and retransmission logic.
- [ ] Simulate peer termination and verify recovery.
- [ ] WiFi: verify operation in weak-signal conditions (RSSI ≤ −70 dBm).
- [ ] I2C: verify bus-recovery routine exists.
- [ ] Long-lived connection test (WiFi / BLE ≥ 24 h continuous).

### 3.4 Thermal and environmental

- [ ] Test across expected operating temperature range (min and max).
- [ ] Validate thermal design (≥ 1 h continuous peak load, temperature must plateau).
- [ ] Humidity / condensation robustness (coating, sealing if needed).
- [ ] Vibration / shock test (for mobile deployments).
- [ ] Connector / cable intermittent-contact simulation.

### 3.5 Software robustness

- [ ] Watchdog enabled and exercised.
- [ ] Range-check every external input (sensor outliers, incoming messages).
- [ ] Exercise every error path (unresponsive sensor, comms failure, file-write failure, ...).
- [ ] `millis()` overflow handled (49.7-day boundary).
- [ ] ISR bodies minimized (measure ISR execution time).
- [ ] Shared-variable protection (`volatile`, critical sections).
- [ ] OTA rollback mechanism for failed updates.

### 3.6 Long-running stress tests

| Test | Minimum recommended duration | What to verify |
| --- | --- | --- |
| **Continuous operation** | 72 h (ideally 2 weeks) | Memory leaks, perf drift, resource exhaustion |
| **Power on/off cycling** | ≥ 1,000 cycles | Boot stability, data integrity |
| **Comms load** | 24 h | Packet loss, connection recovery |
| **Temperature cycling** | 50 cycles (min ↔ max) | Solder cracks, thermal expansion issues |
| **Edge-case injection** | — | Sensor disconnects, abnormal voltages, concurrent events |

### 3.7 Final pre-production checks

- [ ] Firmware version scheme in place.
- [ ] Bootloader protected against accidental overwrite.
- [ ] Debug prints (`Serial.print`) removed or disabled.
- [ ] Logging system implemented (for post-mortem root-cause analysis).
- [ ] Field-update path defined (OTA or physical access).
- [ ] Recovery mode implemented (safe-mode boot on firmware corruption).
- [ ] Relevant certifications checked (CE, FCC, KC, etc., as required).

---

## 4. Summary — three principles for long-term reliability

**First, design deterministically.**
Minimize dynamic allocation. Every resource usage should be predictable at compile time. "It'll probably work" doesn't fly in embedded.

**Second, assume failure.**
Sensors break, communications drop, power is unstable. Every external dependency needs timeouts, retries, and fallback logic. The watchdog is not optional.

**Third, you don't know what you don't measure.**
Stack usage, heap headroom, comms error rate, operating temperature — measure them, don't guess. Problems that emerge only in long-term operation (memory leaks, heap fragmentation, timer overflow) cannot be caught by short-term testing.
