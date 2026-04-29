/**
 * Track D scale fix — minimal client-side parser for ROS map_server YAML.
 *
 * Extracts exactly four fields used by the SPA:
 *   - `image`        (string, basename of the PGM)
 *   - `resolution`   (number, meters per cell)
 *   - `origin`       ([x, y, theta] — world coord of the image's bottom-left
 *                    pixel, theta in radians; ROS map_server convention)
 *   - `negate`       (number 0|1)
 *
 * Why a hand-rolled parser:
 *
 * - The SPA needs only these four keys, all stable in ROS map_server for
 *   10+ years; pulling a full js-yaml (~30 kB gzipped) would dominate the
 *   bundle for 4 trivial regexes.
 * - Unknown / malformed keys should surface a typed `MapYamlParseError`
 *   so PoseCanvas can show a Korean error banner instead of silently
 *   miscalibrating.
 * - The parser is pure (no HTTP, no DOM, no Svelte) so it can be fuzzed
 *   in isolation.
 */

export interface MapYaml {
  image: string;
  resolution: number;
  origin: [number, number, number];
  negate: number;
}

export class MapYamlParseError extends Error {
  reason: string;
  constructor(reason: string, message?: string) {
    super(message ?? reason);
    this.reason = reason;
  }
}

const KEY_RESOLUTION = 'resolution';
const KEY_ORIGIN = 'origin';
const KEY_NEGATE = 'negate';
const KEY_IMAGE = 'image';

/**
 * Strip a single line of its `#`-comment tail. The comment marker only
 * counts when it is preceded by whitespace OR sits at column 0; this
 * mirrors a fragment of the YAML 1.2 rule and is sufficient for our
 * 4-key surface (no inline `#` ever appears inside a value we care
 * about).
 */
function stripComment(line: string): string {
  const idx = line.search(/(^|\s)#/);
  if (idx < 0) return line;
  // If the marker is preceded by whitespace, keep that whitespace; else
  // drop everything from column 0.
  return line.slice(0, idx === 0 ? 0 : idx + 1).replace(/\s+$/, '');
}

function findKeyLine(lines: string[], key: string): string | null {
  const re = new RegExp(`^\\s*${key}\\s*:\\s*(.*)$`);
  for (const raw of lines) {
    const line = stripComment(raw);
    const m = re.exec(line);
    if (m) return (m[1] ?? '').trim();
  }
  return null;
}

function parseNumber(raw: string, key: string): number {
  // Allow optional sign, decimal, scientific notation.
  if (!/^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(raw)) {
    throw new MapYamlParseError(`bad_${key}`, `${key} not a number: ${raw}`);
  }
  const v = Number(raw);
  if (!Number.isFinite(v)) {
    throw new MapYamlParseError(`bad_${key}`, `${key} not finite: ${raw}`);
  }
  return v;
}

function parseOrigin(raw: string): [number, number, number] {
  // ROS shape: `[x, y, theta]`. Whitespace-tolerant; trailing comma OK.
  const m = /^\[\s*([^,\]]+?)\s*,\s*([^,\]]+?)\s*,\s*([^,\]]+?)\s*\]$/.exec(raw);
  if (!m) {
    throw new MapYamlParseError('bad_origin', `origin not a 3-element list: ${raw}`);
  }
  const ox = parseNumber((m[1] ?? '').trim(), 'origin_x');
  const oy = parseNumber((m[2] ?? '').trim(), 'origin_y');
  const th = parseNumber((m[3] ?? '').trim(), 'origin_theta');
  return [ox, oy, th];
}

export function parseMapYaml(text: string): MapYaml {
  const lines = text.split(/\r?\n/);

  const resRaw = findKeyLine(lines, KEY_RESOLUTION);
  if (resRaw === null) {
    throw new MapYamlParseError('missing_resolution');
  }
  const resolution = parseNumber(resRaw, 'resolution');
  if (resolution <= 0) {
    throw new MapYamlParseError('bad_resolution', `resolution not positive: ${resRaw}`);
  }

  const originRaw = findKeyLine(lines, KEY_ORIGIN);
  if (originRaw === null) {
    throw new MapYamlParseError('missing_origin');
  }
  const origin = parseOrigin(originRaw);

  // image is REQUIRED (it tells the SPA which PGM to fetch — though
  // we use the URL directly, the cross-check catches mismatched pairs).
  const imageRaw = findKeyLine(lines, KEY_IMAGE);
  if (imageRaw === null) {
    throw new MapYamlParseError('missing_image');
  }
  const image = imageRaw.replace(/^['"]|['"]$/g, '');

  // negate is OPTIONAL — defaults to 0 per ROS convention.
  const negateRaw = findKeyLine(lines, KEY_NEGATE);
  const negate = negateRaw === null ? 0 : parseNumber(negateRaw, 'negate');

  return { image, resolution, origin, negate };
}
