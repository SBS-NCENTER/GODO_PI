---
name: Emojis allowed in user-facing chat
description: User explicitly permitted emojis in chat replies (2026-04-28). Default Claude Code rule says "no emojis unless requested" — this is the request.
type: feedback
---

Emojis OK in user-facing chat replies.

**Why:** User explicitly said "이모지 써도 됨요~~" on 2026-04-28 after Parent had been deliberately suppressing them per the default Claude Code rule ("Only use emojis if the user explicitly requests it"). The permission is open-ended, not tied to a specific situation.

**How to apply:**
- User-facing chat replies (Korean, friendly tone): emojis are welcome where they fit naturally — celebration moments, gentle warnings, status callouts. Don't sprinkle them mechanically.
- **Code, comments, commit messages, in-repo docs, agent prompts: still NO emojis.** CLAUDE.md §6 "Code and docs" / "Language policy" is unchanged. The Write/Edit tool default ("Avoid writing emojis to files unless asked") still applies.
- Tasteful use only — a celebratory 🎉 when a hardware test passes is fine; a 🚀 on every routine step is not.
