import type { Component } from 'svelte';
import Config from './routes/Config.svelte';
import Dashboard from './routes/Dashboard.svelte';
import Diagnostics from './routes/Diagnostics.svelte';
import Local from './routes/Local.svelte';
import Login from './routes/Login.svelte';
import Map from './routes/Map.svelte';
import NotFound from './routes/NotFound.svelte';
import System from './routes/System.svelte';

export const routes: Record<string, Component> = {
  '/': Dashboard,
  '/login': Login,
  '/map': Map,
  '/local': Local,
  '/diag': Diagnostics,
  '/config': Config,
  '/system': System,
};

export const notFoundComponent: Component = NotFound;
