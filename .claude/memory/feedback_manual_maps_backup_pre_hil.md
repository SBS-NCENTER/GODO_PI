---
name: Manual maps_dir snapshot before risky HIL
description: Before operator HIL on news-pi01 that could touch maps (mapping/edit/transform), Parent should propose a wholesale rsync of /var/lib/godo/maps/ into /home/ncenter/maps_backup_<YYYY-MM-DD>_<reason>/ as a per-session safety net.
type: feedback
---

When the operator is about to run HIL on news-pi01 that could mutate
`/var/lib/godo/maps/` (mapping pipeline, map editor, Apply/transform,
restore_backup, anything new touching `maps_dir`), Parent should
proactively propose a wholesale snapshot before HIL kicks off:

```
rsync -a /var/lib/godo/maps/ /home/ncenter/maps_backup_<YYYY-MM-DD>_<context>/
```

**Why:** The SPA's built-in backup feature (Backup tab) snapshots maps
on a per-pair basis, which is great for routine ops but doesn't
capture the entire `maps_dir` shape (orphan PGMs, unmatched sidecars,
in-flight derivatives) atomically. A wholesale rsync gives a
known-good rollback target that survives even if a sidecar / lineage
mutation goes sideways during HIL. Operator locked this in
2026-05-05 morning KST — "앞으로도 간간히 SPA의 백업 기능 말고 이렇게
수동 백업을 하는 것이 좋겠어요" — confirmed after using
`/home/ncenter/maps_backup_2026-05-05_pre_issue30_debug/` to recover
during the issue#30 HIL fold rounds.

**How to apply:**

- Trigger condition: Parent has just opened (or is about to open) a PR
  that the operator will HIL on news-pi01, AND the PR touches code
  that can write into `maps_dir` (anything in `godo-webctl/maps.py`,
  `sidecar.py`, `map_transform.py`, `backup.py`, the mapping pipeline
  containers, the SPA map editor / Apply path).
- Naming convention: `/home/ncenter/maps_backup_<YYYY-MM-DD>_<context>/`
  where `<context>` is short (`pre_issue30.1_hil`, `pre_issue28.1_hil`,
  etc.). Multiple snapshots per day are fine — each gets its own
  context suffix. Example precedents:
  - `/home/ncenter/maps_backup_2026-05-05_pre_issue30_debug/` (issue#30
    HIL morning)
  - `/home/ncenter/maps_backup_2026-05-05_tue_pre_issue30.1_hil/` (this
    session — issue#30.1 morning)
- Verify after copy: `diff <(ls source | sort) <(ls dest | sort)` should
  print nothing. File count + `du -sh` should match.
- Cleanup: keep snapshots until the next mapping session that
  intentionally overwrites the layout. Operator deletes old ones at
  their discretion; do NOT auto-prune.
- DO NOT propose this for HIL that only touches the SPA / read-only
  endpoints (Diag, Config, System tabs — anything that doesn't mutate
  `maps_dir`).
