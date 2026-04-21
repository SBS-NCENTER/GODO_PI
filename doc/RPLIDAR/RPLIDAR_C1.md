# RPLIDAR C1 — Phase 0 deep dive

> **Purpose**: the Single Source of Truth for the SLAMTEC RPLIDAR C1 in this project — technical specs, communication, SDK, environmental suitability, and design implications.
>
> **Source priority**: SLAMTEC official datasheet v1.0 (local copy) > SLAMTEC official FAQ / SDK > vendor wikis / blogs.
>
> **Last updated**: 2026-04-20

---

## 0. At a glance

```text
┌──────────────────────────────────────────────────────────────┐
│ SLAMTEC RPLIDAR C1M1-R2   (released 2023-10)                 │
├──────────────────────────────────────────────────────────────┤
│ Principle    │ Direct TOF (DTOF) + SL-DTOF fusion            │
│ Laser        │ 905 nm NIR, Class 1, 20 W peak / 1.4 ns pulse │
│ Range        │ 0.05–12 m (white 70%) / 0.05–6 m (black 10%)  │
│ Accuracy     │ ±30 mm (single sample)                        │
│ Resolution   │ 15 mm                                         │
│ Scan rate    │ 8–12 Hz (typ. 10 Hz)                          │
│ Sample rate  │ 5 kHz (angular resolution 0.72° @ 10 Hz)      │
│ Ambient lim. │ 40,000 lux                                    │
│ IP rating    │ IP54                                          │
│ UART         │ 3.3 V TTL, 460,800 bps, 8N1                   │
│ Power        │ 5 V ±4 %, start 800 mA / run 230–260 mA       │
│ Size / mass  │ 55.6 × 55.6 × 41.3 mm / 110 g                 │
│ Op. temp.    │ −10 to +40 °C                                 │
└──────────────────────────────────────────────────────────────┘
```

---

## 1. Measurement principle and optics

| Item | Value | Note |
| --- | --- | --- |
| Principle | **Direct TOF (DTOF)** | SLAMTEC's "SL-DTOF fusion ranging" |
| Source | Modulated-pulse NIR laser | — |
| Wavelength | **905 nm** (typ.), 895–915 nm | Near-infrared band |
| Peak power | 20 W | Average power far lower |
| Pulse length | 1.4 ns (typ.) | — |
| Laser safety | **IEC-60825 Class 1** | Eye-safe; no shielding required |

### Design implications

- **DTOF**: accuracy degradation with range is much milder than with triangulation (A-series).
- **Ambient-light immunity**: 40,000 lux headroom is ample for indoor lighting.
- **905 nm NIR**: visible-light colors are irrelevant. The green / blue chroma paint itself is not the issue; what matters is its NIR reflectivity.

---

## 2. Core performance specs (official datasheet)

| Item | Value |
| --- | --- |
| Distance range (70 % reflect) | 0.05–12 m |
| Distance range (10 % reflect) | 0.05–6 m |
| **Accuracy** | **±30 mm** (25 °C, 10–90 % reflectance) |
| **Resolution** | **15 mm** |
| Sample rate | 5 kHz (fluctuation < 1 %) |
| Scanning frequency | 8–12 Hz (typ. 10 Hz, fluctuation < 5 %) |
| Angular resolution | 0.72° @ 10 Hz |
| Scan field flatness | 0°–1.5° (customizable) |
| Ambient-light limit | 40,000 lux |
| IP rating | IP54 |
| Working temperature | −10 to +40 °C |
| Storage temperature | −20 to +60 °C |
| Weight | 110 g |
| Dimensions | 55.6 × 55.6 × 41.3 mm |
| Mounting | 4 × M2.5, screw depth ≤ 4 mm |

### Precision math (important)

- Angular step between samples is 0.72°, so the linear gap at range `r` is `r × tan(0.72°)`:
  - `r = 3 m` → ≈ 38 mm
  - `r = 5 m` → ≈ 63 mm
  - `r = 10 m` → ≈ 126 mm
- Single-sample error ±30 mm, assuming white noise, shrinks by √N when averaged over N samples.
- A 5–10 s static 1-shot scan buys:
  - ≈ 50–100 frames
  - hundreds of samples per direction
  - theoretically millimeter-level, realistically ≤ 10 mm accuracy.

---

## 3. Communication protocol and data format

### UART settings

| Item | Value |
| --- | --- |
| Interface | **TTL UART 3.3 V** |
| Baud rate | **460,800 bps** |
| Frame | 8N1 (8 data / 1 stop / no parity) |
| Output high voltage | 3.3 V typ (2.9–3.5) |
| Output low voltage | ≤ 0.4 V |
| Input high voltage | 3.3 V typ (2.4–3.5) |
| Input low voltage | ≤ 0.4 V |

### Frame structure (basics)

| Element | Value |
| --- | --- |
| Request start byte | `0xA5` |
| Response descriptor | `0xA5 0x5A` (2 bytes) |
| Checksum | XOR-based |
| Protocol compatibility | Supports both A-series Standard and S-series Express / Ultra |

### Per-sample data fields

| Field | Unit | Description |
| --- | --- | --- |
| Distance | mm | Distance from LiDAR center |
| Angle | degree | Sample angle (0–360) |
| Start signal | Boolean | New-frame flag |
| Quality | 0–255 (SDK level) | Signal strength / confidence |
| Flag | bits | Sync bit, etc. |
| Checksum | — | Frame checksum |

### Coordinate system

```text
       x  (scanner forward, θ=0°)
       ▲
       │
       │   θ (0–360°, clockwise)
       │
  ─────┼─────────► y
       │
   [RPLIDAR C1]   ← rotation axis = coordinate origin (left-handed)
```

---

## 4. SDK and Python bindings

### Official SDK — [Slamtec/rplidar_sdk](https://github.com/Slamtec/rplidar_sdk)

| Item | Value |
| --- | --- |
| Supported OS | x86 Windows, x86 Linux, macOS, ARM Linux |
| Language | C++ |
| License | SDK: BSD-2-Clause / demos: GPLv3 |
| Official C1 support | ✅ (A1 / A2 / A3 / S1 / S2 / S3 / **C1** / T1) |
| Key APIs | `grabScanDataHq()`, `getAllSupportedScanModes()` |
| Demos | `ultra_simple`, `simple_grabber`, `frame_grabber` (Windows only) |
| RoboStudio plugin | **Framegrabber** for debugging / visualization |

### Python bindings comparison

| Library | Official C1 support | Speed | Notes |
| --- | --- | --- | --- |
| `rplidar` (SkoltechRobotics) | ❌ (A1 / A2 only) | Low | Most popular but frequent frame drops |
| `pyrplidar` (Hyun-je) | ❌ | Medium | Generator-based, async-friendly |
| `Adafruit_CircuitPython_RPLIDAR` | ❌ | Low | Buggy; educational use only |
| `FastestRplidar` (SWIG wrapper) | ⚠ A2-primary | High | Wraps the C++ SDK; may need porting for C1 |
| **Official SDK + pybind11 / ctypes** | ✅ | Highest | **Recommended for this project** |

---

## 5. Raw vs SDK noise — root causes

**Observation**: scans look clean via RoboStudio / SDK, but noisy when read from Python directly.

### Causes, ordered by impact

| # | Cause | Impact | Mitigation |
| --- | --- | --- | --- |
| 1 | Ignoring the quality field (no filter) | ★★★★ | Drop samples with quality < 80 |
| 2 | Standard vs Express / Ultra mode confusion | ★★★★ | Use the SDK's Scan Mode API to pick the best mode |
| 3 | Frame-reassembly errors on checksum failures | ★★★ | Use the official SDK |
| 4 | Frame-sync bit misinterpretation (half-rotation frames) | ★★★ | Use the official SDK |
| 5 | USB-to-serial buffering causing timing drift | ★★ | Increase the receive buffer |
| 6 | Motor not yet in sync → angle drift | ★★ | Wait ~0.5 s after motor start |
| 7 | Python GC / GIL causing frame drops | ★★ | C++ wrapper or multiprocessing |

### Recommended Phase 1 approach

1. **Dump raw data with the official C++ SDK (`ultra_simple`)**, then analyze in Python.
2. If direct Python parsing is unavoidable: extend `pyrplidar` with an Express-mode implementation, or port FastestRplidar for C1.
3. For real-time processing, call the **C++ SDK directly** (RPi 5 on Linux).

---

## 6. MCU / SBC direct connection

### Physical interface — XH2.54-5P connector

| Pin | Color | Signal | Description | Voltage |
| --- | --- | --- | --- | --- |
| 1 | Red | VCC | Power input | 4.8–5.2 V DC |
| 2 | Yellow | TX | UART TX (out) | 3.3 V TTL |
| 3 | Green | RX | UART RX (in) | 3.3 V TTL |
| 4 | Black | GND | Ground | 0 V |
| 5 | — | (NC / shield) | Unused | — |

**⚠ Important**: the C1 does **not** expose a MOTOCTL (PWM) pin. Motor speed is controlled exclusively via serial commands — a noticeable change from the A1.

### Power requirements

| Item | Value | Caveat |
| --- | --- | --- |
| Power voltage | 4.8–5.2 V (typ. 5.0) | Below range → measurements inaccurate |
| Power ripple | ≤ 150 mV | Above → unstable laser emission |
| **Start current (peak)** | **800 mA** | **Cold start transient** |
| Normal current | 230–260 mA (@ 10 Hz) | Steady-state |

### MCU / SBC compatibility matrix

| Device | UART direct | Power | Baud 460,800 | Verdict |
| --- | --- | --- | --- | --- |
| Arduino UNO / R3 (5 V) | ⚠ Level shifter recommended (5 → 3.3 V divider mandatory for RX) | USB 500 mA insufficient for 800 mA startup → external supply needed | ~3.5 % timing error, not recommended | ✗ Avoid |
| **Arduino R4 WiFi** | 3.3 V RX OK | Feed 5 V / 1 A via VIN | 48 MHz, OK | ✅ Feasible |
| **RPi Pico / Pico W** | **Direct OK** (3.3 V logic) | Separate 5 V / 1 A supply required for C1 | 125 MHz + PIO, plenty of headroom | ✅ Best for compact builds |
| **RPi 5** | USB-CP2102N (current) or GPIO UART direct | USB 5 V is sufficient | No issue | ✅ Most flexible |

### SPI support

**Not supported.** The C1 is UART-only.

---

## 7. Chroma-studio suitability

> Where official data is lacking, this section reasons from **physics** and **general NIR-reflectance ranges**. Empirical verification in Phase 1 is mandatory.

| Surface | 905 nm NIR reflectivity (estimate) | Effective range | Risk |
| --- | --- | --- | --- |
| Green chroma wall (paint) | 40–60 % | ≥ 10 m | Low (varies by paint) |
| Blue chroma wall | 40–60 % | ≥ 10 m | Low |
| **Black absorber (velvet)** | **< 5 %** | **≤ 3 m** | **⚠ Very high — possible data loss** |
| Metal gear (TV trolley) | Specular | Angle-dependent | Multi-path / missing returns |
| Monitor / TV screens | Specular + thin glass | Frontal angles unstable | Moderate |
| Clothes / skin | 10–40 % | 6–10 m | Low (people move below the LiDAR) |
| Studio doors | 30–50 % | Stable | Low (tracked as dynamic features) |
| HMI / LED lights | Visible only → not an issue | Within 40,000 lux | Low |

### Cautions

1. **Chroma-paint NIR reflectivity varies by manufacturer** — Phase 1 measurement is mandatory.
2. **Specular reflections from monitors / mirrors** must be rejected as outliers (quality + RANSAC).
3. **Black absorbers near the rotation axis** cause missing data in that direction → exclude from reference-scan features.
4. **Crane arm self-occlusion** — either include the occluded arc in the reference scan so it cancels out, or mask by pan-yaw.

---

## 8. C1 within the SLAMTEC lineup

| Model | Tech | Range | Sample rate | Angular res. | Tier | Primary use |
| --- | --- | --- | --- | --- | --- | --- |
| A1 | Triangulation | 0.15–12 m | 8 kHz | 0.36–0.9° | Budget | Home robots (basic) |
| A2 | Triangulation | 0.2–16 m | 16 kHz | 0.225° | Mid | General SLAM |
| A3 | Triangulation | 0.2–25 m | 16 kHz | 0.225° | Mid-high | Indoor + outdoor |
| **C1** | **Fusion DTOF** | **0.05–12 m** | **5 kHz** | **0.72°** | **Budget** | **Home / compact robots** |
| S1 | TOF | 0.1–40 m | 8–15 kHz | 0.391° | High | Indoor + outdoor long range |
| S2 | TOF | 0.05–30 m | 10 kHz | 0.12° | High | High-precision SLAM |
| S3 | TOF | 0.05–40 m | 10–20 kHz | 0.1125° | Top | Premium |

### Suitability for this project

**Strengths**

- ✅ DTOF → uniform accuracy across the range.
- ✅ 5 cm blind range → can be mounted right under the crane arm.
- ✅ Class 1 laser, 110 g → no issue mounting on the crane.
- ✅ Inexpensive, low power, supported on Windows / macOS / Linux / ARM Linux.

**Weaknesses**

- ⚠ 0.72° angular resolution is coarse compared to the S-series → multi-frame averaging is mandatory.
- ⚠ 5 kHz sample rate is 1/2 to 1/4 of the S-series.
- ⚠ ±30 mm single-sample error cannot hit a 1–2 cm target without multi-frame averaging.

### Re-validation

Given our profile — 1-shot static measurement, ≤ 12 m studio, 1–2 cm tolerance, mounted above head height — **C1 is sufficient**. S2 / S3 would be overkill for the cost.

---

## 9. Design implications for this project

```text
┌──────────────────────────────────────────────────────────────────┐
│ 1. Phase 1 prototype:                                            │
│    Dump raw data with the official C++ SDK (ultra_simple),       │
│    then analyze in Python. Solves the "Python data is noisy"     │
│    issue at its root.                                            │
│                                                                  │
│ 2. Coordinate-setup (axis B): reference scan + ICP preferred.    │
│    0.72° angular resolution makes pure wall-fitting too coarse;  │
│    ICP matches the overall wall shape and is more robust.        │
│                                                                  │
│ 3. Compute pipeline (axis C): RPi 5 first.                       │
│    Official SDK has first-class ARM Linux support, and           │
│    ICP / Python / C++ are all easy to run there.                 │
│    The cleanest combo is: RPi 5 computes + UDP-sends the offset. │
│                                                                  │
│ 4. Accuracy strategy:                                            │
│    "1-shot" = 5–10 s of static scanning = 50–100 frames.         │
│    Hundreds of samples per direction; √N averaging reaches       │
│    ≤ 10 mm comfortably.                                          │
│                                                                  │
│ 5. Environmental safeguards:                                     │
│    Exclude black-absorber directions, reject monitor / mirror    │
│    returns as RANSAC outliers.                                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## 10. Empirical checks deferred to Phase 1

1. Measured NIR reflectivity and effective range against the green / blue chroma paint at 905 nm.
2. Quantitative noise comparison: official SDK raw data vs. Python library output.
3. Position repeatability over a 3–10 s static scan (is ≤ 1 cm reachable?).
4. Crane-arm self-occlusion footprint and masking strategy.
5. Maximum stable sample rate on Linux through the current USB-CP2102N adapter.

---

## 11. Sources

### Local copies (in this repository)

- [SLAMTEC RPLIDAR C1 datasheet v1.0 (2023-10-13)](./sources/SLAMTEC_rplidar_datasheet_C1_v1.0_en.pdf) — **primary source**.
- [SLAMTEC RPLIDAR S&C-series protocol v2.8](./sources/SLAMTEC_rplidar_protocol_v2.8_en.pdf) — packet-level reference.

### External links

- [SLAMTEC RPLIDAR C1 product page](https://www.slamtec.com/en/c1)
- [SLAMTEC RPLIDAR FAQ (includes the baud-rate table)](https://wiki.slamtec.com/display/SD/RPLIDAR+FAQ)
- [Slamtec/rplidar_sdk (GitHub, official SDK)](https://github.com/Slamtec/rplidar_sdk)
- [RPLIDAR C1 Waveshare wiki](https://www.waveshare.com/wiki/RPLIDAR_C1)
- [pyrplidar (Python library)](https://github.com/Hyun-je/pyrplidar)
- [FastestRplidar (SWIG C++ wrapper)](https://github.com/thehapyone/FastestRplidar)
- [SLAMTEC LiDAR lineup comparison — Génération Robots](https://www.generationrobots.com/blog/en/slamtec-lidar-a-practical-comparison-for-easy-decision-making/)
