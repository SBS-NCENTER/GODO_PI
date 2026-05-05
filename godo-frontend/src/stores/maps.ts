/**
 * Maps store — Track E (PR-C).
 *
 * Refresh-on-action only (per Mode-A N6 — no periodic polling). The
 * store re-fetches `/api/maps` on:
 *   (a) explicit `refresh()` (Map page mounts),
 *   (b) post-`activate(name)`,
 *   (c) post-`remove(name)`.
 *
 * Mutations short-circuit client-side via `MAPS_NAME_REGEX_PATTERN_STR`
 * so a typo never reaches the network. The backend re-validates the
 * same regex (defence-in-depth — `maps.validate_name`).
 */

import { writable, type Writable } from 'svelte/store';
import { apiDelete, apiGet, apiPost } from '$lib/api';
import {
  MAPS_NAME_REGEX_PATTERN_STR,
  type MapEntry,
  type MapGroup,
  type MapListResponse,
  type ActivateResponse,
} from '$lib/protocol';

// Compile once at module load. The regex is anchored (`^…$`) on both
// sides per the SSOT in `godo_webctl.constants.MAPS_NAME_REGEX`.
const NAME_REGEX = new RegExp(MAPS_NAME_REGEX_PATTERN_STR);

export class InvalidMapName extends Error {
  constructor(name: string) {
    super(`invalid map name: ${name}`);
    this.name = 'InvalidMapName';
  }
}

export const maps: Writable<MapEntry[]> = writable([]);

// issue#28 — pristine + variants tree shape for the new `<MapList>`
// grouped renderer. Populated alongside `maps` in `refresh()`.
export const mapGroups: Writable<MapGroup[]> = writable([]);

export function isValidMapName(name: string): boolean {
  return NAME_REGEX.test(name);
}

function assertValidName(name: string): void {
  if (!isValidMapName(name)) throw new InvalidMapName(name);
}

export async function refresh(): Promise<MapEntry[]> {
  // issue#28.1 — server response is `{groups: MapGroup[]}` only;
  // the legacy `flat` key was hard-removed. Flatten `groups` here so
  // legacy `<MapListPanel>` (consumes `MapEntry[]`) keeps working.
  const resp = await apiGet<MapListResponse>('/api/maps');
  const groups: MapGroup[] = resp.groups ?? [];
  const flat: MapEntry[] = groups.flatMap((g) =>
    g.pristine ? [g.pristine, ...g.variants] : g.variants,
  );
  maps.set(flat);
  mapGroups.set(groups);
  return flat;
}

export async function activate(name: string): Promise<ActivateResponse> {
  assertValidName(name);
  const resp = await apiPost<ActivateResponse>(`/api/maps/${encodeURIComponent(name)}/activate`);
  await refresh();
  return resp;
}

export async function remove(name: string): Promise<void> {
  assertValidName(name);
  await apiDelete(`/api/maps/${encodeURIComponent(name)}`);
  await refresh();
}
