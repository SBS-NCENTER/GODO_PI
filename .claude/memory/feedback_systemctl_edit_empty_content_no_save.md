---
name: systemctl edit empty-content gotcha (silent no-save)
description: When `sudo systemctl edit <unit>` exits with empty content, systemd refuses to write the override and leaves the existing override in place — silently. The operator thinks they removed a directive but the next restart picks up the unchanged override. To remove a directive, replace it with a `# disabled` comment OR delete the override file directly via `rm`.
type: feedback
---

## Rule

When using `sudo systemctl edit <unit>` to **remove** a directive (not just change one), do NOT save an empty file. systemd's behavior:

```
Editor closed without saving... (or with empty content)
/etc/systemd/system/<unit>.d/override.conf: after editing, new contents are empty, not writing file.
```

systemd refuses to write an empty override.conf and **leaves the existing file unchanged**. The operator's intent (remove directive) is silently no-op'd. The next `systemctl restart <unit>` will pick up the unchanged override.

## Why

systemd's override.conf semantics treat "missing file" and "empty file" differently:
- Missing file → no override (clean state).
- Non-empty file → applies the directives in it.
- Empty file (after `systemctl edit`) → would be ambiguous, so systemd refuses to create one.

This is well-intentioned (preserves override state if you accidentally save with no content), but it surprises operators who think "I removed the line, it should be gone".

## How to apply

Two safe paths to genuinely remove a directive added via `systemctl edit`:

### Option A — replace with comment

```bash
sudo systemctl edit <unit>
# Replace the directive line with a single comment (or any non-directive content):
#   [Service]
#   # Environment="GODO_PHASE0=1"  # disabled YYYY-MM-DD
# Save: Ctrl+O Enter Ctrl+X
sudo systemctl daemon-reload
sudo systemctl restart <unit>
```

The `[Service]` section header alone is also valid — systemd accepts a section with no directives.

### Option B — delete the override file directly

```bash
sudo rm /etc/systemd/system/<unit>.d/override.conf
sudo rmdir /etc/systemd/system/<unit>.d/   # optional: remove empty directory
sudo systemctl daemon-reload
sudo systemctl restart <unit>
```

Cleanest path when you're sure the override should be gone entirely.

### Verification

```bash
systemctl show <unit> -p Environment    # should show empty Environment= for env-var overrides
systemctl cat <unit>                     # should NOT print the override.conf section (or it's empty)
```

## When this rule kicks in

- Any `sudo systemctl edit <unit>` session where the goal is to **remove** an existing override directive.
- Documentation that says "delete the line and save" — flag it with the empty-content trap warning.
- Mode-B reviewers should call out any deploy doc that says "remove via systemctl edit" without specifying option A or B.

## Why this matters (twenty-seventh-session 2026-05-06 incident)

Operator added `Environment="GODO_PHASE0=1"` for issue#11 P4-2-11-0 Phase-0 measurement HIL. After capturing the data, attempted to disable via `sudo systemctl edit godo-tracker.service` → deleted the line → exited the editor → ran `sudo systemctl restart godo-tracker`. systemd silently refused to write the empty file. Diagnosis took ~30 seconds:
1. `systemctl show -p Environment` → still `Environment=GODO_PHASE0=1`
2. `cat /etc/systemd/system/godo-tracker.service.d/override.conf` → file unchanged at original mtime
3. journalctl confirmed PHASE0 lines still emitting from the supposedly-disabled tracker

Recovery via Option B (`rm` + `rmdir` + `daemon-reload` + `restart`).
