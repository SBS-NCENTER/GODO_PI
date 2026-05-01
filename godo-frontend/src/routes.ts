import type { Component } from 'svelte';
import Backup from './routes/Backup.svelte';
import Config from './routes/Config.svelte';
import Dashboard from './routes/Dashboard.svelte';
import Diagnostics from './routes/Diagnostics.svelte';
import Local from './routes/Local.svelte';
import Login from './routes/Login.svelte';
import Map from './routes/Map.svelte';
// MapEdit is no longer a top-level route — it renders inside Map.svelte
// when the Edit sub-tab is active. The /map-edit URL is preserved
// (it routes to Map and Map auto-selects the Edit sub-tab) so
// existing bookmarks, e2e specs, and the post-Apply redirect keep
// working. Map Edit family — see routes/Map.svelte for the sub-tab
// hosting code.
import NotFound from './routes/NotFound.svelte';
import System from './routes/System.svelte';

export const routes: Record<string, Component> = {
  '/': Dashboard,
  '/login': Login,
  '/map': Map,
  '/map-edit': Map,
  // issue#14 — Mapping sub-tab URL. Routes to Map.svelte which
  // auto-selects the Mapping sub-tab when route.path === '/map-mapping'.
  '/map-mapping': Map,
  '/local': Local,
  '/diag': Diagnostics,
  '/config': Config,
  '/system': System,
  '/backup': Backup,
};

export const notFoundComponent: Component = NotFound;
