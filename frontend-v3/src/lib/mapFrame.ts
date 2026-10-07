/**
 * Per-floor map frame: how a floor plan of any pixel size sits inside the
 * fixed 500x500 map-unit space that MapCanvas draws in.
 *
 * Source coordinates (graph nodes, backend poses, routes) are in floor-plan
 * pixels. They are scaled by ONE uniform factor (500 / longer side) so angles
 * and headings survive, and offset so the plan is centred in the square.
 * Floors without a declared size return no frame and keep the legacy path
 * (500x500 plans, optionally with the inferred integer divisor).
 */
import { type MapPoint } from '../types/navigation';

export const MAP_UNITS = 500;

export interface MapSize {
  width: number;
  height: number;
}

export interface MapFrame {
  /** Map units per source pixel. */
  scale: number;
  offsetX: number;
  offsetY: number;
  /** Drawn size of the plan image, in map units. */
  width: number;
  height: number;
}

export function parseMapSize(value: unknown): MapSize | null {
  if (!Array.isArray(value) || value.length < 2) {
    return null;
  }
  const width = Number(value[0]);
  const height = Number(value[1]);
  return Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0
    ? { width, height }
    : null;
}

export function buildMapFrame(size: MapSize | null | undefined): MapFrame | null {
  if (!size) {
    return null;
  }
  const scale = MAP_UNITS / Math.max(size.width, size.height);
  const width = size.width * scale;
  const height = size.height * scale;
  return {
    scale,
    offsetX: (MAP_UNITS - width) / 2,
    offsetY: (MAP_UNITS - height) / 2,
    width,
    height,
  };
}

/** Source pixels -> map units. With no frame the point is divided by `legacyDivisor`. */
export function toMapUnits(frame: MapFrame | null | undefined, point: MapPoint, legacyDivisor = 1): MapPoint {
  if (!frame) {
    return legacyDivisor === 1 ? point : { x: point.x / legacyDivisor, y: point.y / legacyDivisor };
  }
  return { x: point.x * frame.scale + frame.offsetX, y: point.y * frame.scale + frame.offsetY };
}
