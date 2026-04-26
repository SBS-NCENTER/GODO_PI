---
name: Frontend stack — Vite + Svelte
description: Phase 4.5 webctl frontend stack decision (Vite + Svelte chosen 2026-04-26)
type: project
---

Phase 4.5 (and any frontend extension beyond the current vanilla `index.html` in `godo-webctl/`) uses **Vite + Svelte**.

**Why:** Map editor + AMCL pose visualization + Tier-2 config editor need a reactive framework with rich canvas interaction. Svelte chosen over React for lighter build (~10-20KB gzipped vs ~150KB), gentler learning curve, and reactive syntax that fits the small/single-operator UI surface. Chosen over vanilla TS because the state management surface (multiple pages × live data × map editor canvas state) gets heavy enough to justify a framework. Chosen over HTMX because canvas-based map editor cannot be server-rendered.

**How to apply:**
- When scaffolding the Phase 4.5 frontend, run `npm create vite@latest` with the Svelte template (or the SvelteKit template if SSR is needed — likely overkill for our single-operator LAN-only context).
- Place under `godo-webctl/frontend/` or as a peer directory under `/godo-webctl/static-src/` — exact location decided at planning time.
- Build output (post-`vite build`) lands as static files served via FastAPI's existing `app.mount("/", StaticFiles(...))`.
- Vite 8 (released early 2026) integrates Rolldown + Lightning CSS by default; pin minor version in package.json.
- Do NOT pull in React, Streamlit, Gradio, or HTMX after this decision is locked in — switching costs a rewrite.

**Out-of-scope alternatives explicitly rejected:** React (overkill, heavy build), Vanilla TS (state management gets heavy at our planned scope), HTMX (canvas-incompatible), Streamlit/Gradio (separate process, doesn't pair with FastAPI cleanly, limited interaction).
