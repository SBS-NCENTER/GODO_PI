import type { Component } from 'svelte';
import Dashboard from './routes/Dashboard.svelte';
import Local from './routes/Local.svelte';
import Login from './routes/Login.svelte';
import Map from './routes/Map.svelte';
import NotFound from './routes/NotFound.svelte';

export const routes: Record<string, Component> = {
  '/': Dashboard,
  '/login': Login,
  '/map': Map,
  '/local': Local,
};

export const notFoundComponent: Component = NotFound;
