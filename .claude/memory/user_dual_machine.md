---
name: Dual-machine workflow (Mac + Windows)
description: User works on this GODO project from both Mac and Windows — project state must live in-repo, not in host-specific caches
type: user
---

The GODO project is worked on from both macOS and Windows. Therefore:

- **All cross-session state, progress, and decisions must live inside the project directory** (`PROGRESS.md`, `CLAUDE.md`, `doc/RPLIDAR/*.md`, etc.), not in host-specific caches.
- Avoid hard-coded absolute paths like `/Users/chunbae/...` in documents — they break on Windows. **Prefer project-relative paths.**
- Large reference assets (datasheet PDFs, etc.) should be **copied into the repo** (e.g., `doc/RPLIDAR/sources/`) instead of linked externally, so they stay available offline and cross-platform.
