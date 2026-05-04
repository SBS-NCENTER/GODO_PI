<script lang="ts">
  /**
   * issue#28 — origin + axis overlay (REP-103 colors).
   *
   * Renders the world origin as a small dot, with red +x axis and
   * green +y axis extending to screen edges. Rotates with the YAML
   * `origin_yaw_deg` so the operator visually verifies the rotation
   * after Apply.
   */

  import {
    AXIS_LABEL_FONT_PX,
    AXIS_LINE_WIDTH_PX,
    AXIS_X_COLOR,
    AXIS_Y_COLOR,
  } from '../lib/constants.js';

  interface Props {
    canvas: HTMLCanvasElement | null;
    zoomPxPerMeter: number;
    worldOriginX: number;
    worldOriginY: number;
    yamlOriginX: number;
    yamlOriginY: number;
    yamlOriginYawDeg: number;
  }

  let {
    canvas,
    zoomPxPerMeter,
    worldOriginX,
    worldOriginY,
    yamlOriginX,
    yamlOriginY,
    yamlOriginYawDeg,
  }: Props = $props();

  $effect(() => {
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const cx = (yamlOriginX - worldOriginX) * zoomPxPerMeter;
    const cy = canvas.height - (yamlOriginY - worldOriginY) * zoomPxPerMeter;

    const yawRad = (yamlOriginYawDeg * Math.PI) / 180;
    // World +x in canvas coords is (cosθ, -sinθ) because canvas Y is
    // flipped from world Y. World +y is (sinθ, cosθ) → canvas
    // (sinθ, -cosθ). Length set to canvas diagonal so the line crosses
    // the screen edge regardless of pan.
    const len = Math.hypot(canvas.width, canvas.height);
    const dxX = Math.cos(yawRad) * len;
    const dyX = -Math.sin(yawRad) * len;
    const dxY = -Math.sin(yawRad) * len;
    const dyY = -Math.cos(yawRad) * len;

    ctx.save();
    ctx.lineWidth = AXIS_LINE_WIDTH_PX;
    // +x (red).
    ctx.strokeStyle = AXIS_X_COLOR;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + dxX, cy + dyX);
    ctx.stroke();
    // +y (green).
    ctx.strokeStyle = AXIS_Y_COLOR;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + dxY, cy + dyY);
    ctx.stroke();

    // Origin dot.
    ctx.fillStyle = '#1f2937';
    ctx.beginPath();
    ctx.arc(cx, cy, 4, 0, Math.PI * 2);
    ctx.fill();

    // Axis labels.
    ctx.fillStyle = AXIS_X_COLOR;
    ctx.font = `${AXIS_LABEL_FONT_PX}px sans-serif`;
    ctx.fillText('+x', cx + dxX * 0.05 + 6, cy + dyX * 0.05 - 2);
    ctx.fillStyle = AXIS_Y_COLOR;
    ctx.fillText('+y', cx + dxY * 0.05 + 4, cy + dyY * 0.05 + 12);

    ctx.restore();
  });
</script>

<!-- pure-canvas overlay; no DOM children -->
