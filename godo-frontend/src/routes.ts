import type { Component } from 'svelte';
import Backup from './routes/Backup.svelte';
import Config from './routes/Config.svelte';
import Dashboard from './routes/Dashboard.svelte';
import Diagnostics from './routes/Diagnostics.svelte';
import Local from './routes/Local.svelte';
import Login from './routes/Login.svelte';
import Map from './routes/Map.svelte';
import MapEdit from './routes/MapEdit.svelte';
import NotFound from './routes/NotFound.svelte';
import System from './routes/System.svelte';

export const routes: Record<string, Component> = {
  '/': Dashboard,
  '/login': Login,
  '/map': Map,
  '/map-edit': MapEdit,
  '/local': Local,
  '/diag': Diagnostics,
  '/config': Config,
  '/system': System,
  '/backup': Backup,
};

export const notFoundComponent: Component = NotFound;
