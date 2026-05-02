/**
 * issue#14 — Mapping pipeline protocol field-name + state-string pins.
 *
 * Drift policy: changing any value here without changing the
 * corresponding `protocol.py` line (and re-running the backend
 * `tests/test_protocol.py`) is a code-review block.
 */

import { describe, expect, it } from 'vitest';
import {
  ERR_CONTAINER_START_TIMEOUT,
  ERR_CONTAINER_STOP_TIMEOUT,
  ERR_DOCKER_UNAVAILABLE,
  ERR_IMAGE_MISSING,
  ERR_INVALID_MAPPING_NAME,
  ERR_MAPPING_ACTIVE,
  ERR_MAPPING_ALREADY_ACTIVE,
  ERR_NAME_EXISTS,
  ERR_NO_ACTIVE_MAPPING,
  ERR_PREVIEW_NOT_YET_PUBLISHED,
  ERR_STATE_FILE_CORRUPT,
  ERR_TRACKER_STOP_FAILED,
  MAPPING_MONITOR_FIELDS,
  MAPPING_STATE_FAILED,
  MAPPING_STATE_IDLE,
  MAPPING_STATE_RUNNING,
  MAPPING_STATE_STARTING,
  MAPPING_STATE_STOPPING,
  MAPPING_STATUS_FIELDS,
  VALID_MAPPING_STATES,
} from '../../src/lib/protocol';

describe('protocol — issue#14 mapping pipeline', () => {
  it('mapping state strings match webctl protocol', () => {
    expect(MAPPING_STATE_IDLE).toBe('idle');
    expect(MAPPING_STATE_STARTING).toBe('starting');
    expect(MAPPING_STATE_RUNNING).toBe('running');
    expect(MAPPING_STATE_STOPPING).toBe('stopping');
    expect(MAPPING_STATE_FAILED).toBe('failed');
  });

  it('VALID_MAPPING_STATES has exactly 5 members', () => {
    expect(VALID_MAPPING_STATES.size).toBe(5);
    expect(VALID_MAPPING_STATES.has('idle')).toBe(true);
    expect(VALID_MAPPING_STATES.has('starting')).toBe(true);
    expect(VALID_MAPPING_STATES.has('running')).toBe(true);
    expect(VALID_MAPPING_STATES.has('stopping')).toBe(true);
    expect(VALID_MAPPING_STATES.has('failed')).toBe(true);
  });

  it('MAPPING_STATUS_FIELDS tuple order is wire-stable', () => {
    expect(MAPPING_STATUS_FIELDS).toEqual([
      'state',
      'map_name',
      'container_id_short',
      'started_at',
      'error_detail',
      'journal_tail_available',
    ]);
  });

  it('MAPPING_MONITOR_FIELDS tuple order is wire-stable (Docker-only)', () => {
    expect(MAPPING_MONITOR_FIELDS).toEqual([
      'valid',
      'container_id_short',
      'container_state',
      'container_cpu_pct',
      'container_mem_bytes',
      'container_net_rx_bytes',
      'container_net_tx_bytes',
      'var_lib_godo_disk_avail_bytes',
      'var_lib_godo_disk_total_bytes',
      'in_progress_map_size_bytes',
      'published_mono_ns',
    ]);
  });

  it('mapping error codes pinned', () => {
    expect(ERR_INVALID_MAPPING_NAME).toBe('invalid_mapping_name');
    expect(ERR_NAME_EXISTS).toBe('name_exists');
    expect(ERR_MAPPING_ALREADY_ACTIVE).toBe('mapping_already_active');
    expect(ERR_MAPPING_ACTIVE).toBe('mapping_active');
    expect(ERR_IMAGE_MISSING).toBe('image_missing');
    expect(ERR_DOCKER_UNAVAILABLE).toBe('docker_unavailable');
    expect(ERR_TRACKER_STOP_FAILED).toBe('tracker_stop_failed');
    expect(ERR_CONTAINER_START_TIMEOUT).toBe('container_start_timeout');
    expect(ERR_CONTAINER_STOP_TIMEOUT).toBe('container_stop_timeout');
    expect(ERR_NO_ACTIVE_MAPPING).toBe('no_active_mapping');
    expect(ERR_PREVIEW_NOT_YET_PUBLISHED).toBe('preview_not_yet_published');
    expect(ERR_STATE_FILE_CORRUPT).toBe('state_file_corrupt');
  });
});
