# production/RPi5/

Production C++ application for the Raspberry Pi 5 host.

**Status:** Phase 3+ target — implementation has not started. This folder
is reserved for the unified binary that will integrate:

- RPLIDAR C1 capture and localization (Phase 1~2 validated in
  [`prototype/Python/`](../../prototype/Python/))
- FreeD packet receive and offset merge
- 59.94 fps UDP send to Unreal Engine

Once scaffolded (CMake), this directory will hold `CMakeLists.txt`,
`src/`, `include/`, and `tests/` per the layout described in
[`SYSTEM_DESIGN.md`](../../SYSTEM_DESIGN.md).

Until then, refer to the legacy Arduino reference at
[`XR_FreeD_to_UDP/`](../../XR_FreeD_to_UDP/) for the FreeD → UDP portion.
