import type { Component } from 'svelte';
import Config from './routes/Config.svelte';
import Dashboard from './routes/Dashboard.svelte';
import Diagnostics from './routes/Diagnostics.svelte';
import Local from './routes/Local.svelte';
import Login from './routes/Login.svelte';
import Map from './routes/Map.svelte';
import NotFound from './routes/NotFound.svelte';

export const routes: Record<string, Component> = {
  '/': Dashboard,
  '/login': Login,
  '/map': Map,
  '/local': Local,
  '/diag': Diagnostics,
  '/config': Config,
};

export const notFoundComponent: Component = NotFound;
