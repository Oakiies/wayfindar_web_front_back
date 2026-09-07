/** Pure heading / coordinate math (extracted from App.tsx). */
import { type MapPoint } from '../types/navigation';

export const MAP_COORDINATE_RANGE = 500;

/** Structural input for inferIncomingCoordinateDivisor (compatible with LiveStreamPayload). */
export interface CoordinateSampleSource {
  position?: { x: number; y: number } | null;
  transition_target?: { x: number; y: number } | null;
  path?: Array<[number, number]>;
}

export function normalizeDegrees(value: number): number {
  const normalized = value % 360;
  return normalized >= 0 ? normalized : normalized + 360;
}

export function normalizeSignedDegrees(value: number): number {
  return ((value + 180) % 360 + 360) % 360 - 180;
}

export function headingFromVector(dx: number, dy: number, minDistance = 1.4): number | null {
  const distance = Math.hypot(dx, dy);
  if (!Number.isFinite(distance) || distance < minDistance) {
    return null;
  }
  return normalizeDegrees((Math.atan2(dy, dx) * 180) / Math.PI);
}

export function headingFromPath(position: MapPoint, path: MapPoint[]): number | null {
  for (const point of path) {
    const heading = headingFromVector(point.x - position.x, point.y - position.y, 2.2);
    if (heading !== null) {
      return heading;
    }
  }
  return null;
}

export function inferIncomingCoordinateDivisor(payload: CoordinateSampleSource): number {
  const samples: number[] = [];

  if (payload.position) {
    samples.push(Math.abs(Number(payload.position.x)));
    samples.push(Math.abs(Number(payload.position.y)));
  }
  if (payload.transition_target) {
    samples.push(Math.abs(Number(payload.transition_target.x)));
    samples.push(Math.abs(Number(payload.transition_target.y)));
  }
  if (Array.isArray(payload.path)) {
    for (const point of payload.path) {
      if (!Array.isArray(point) || point.length < 2) {
        continue;
      }
      samples.push(Math.abs(Number(point[0])));
      samples.push(Math.abs(Number(point[1])));
    }
  }

  const maxCoordinate = samples.reduce((acc, value) => (value > acc ? value : acc), 0);
  if (!Number.isFinite(maxCoordinate) || maxCoordinate <= MAP_COORDINATE_RANGE * 1.1) {
    return 1;
  }
  return Math.max(1, Math.round(maxCoordinate / MAP_COORDINATE_RANGE));
}
