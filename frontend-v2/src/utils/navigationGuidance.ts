import { type MapPoint } from '../types/navigation';

export type GuidanceKind = 'straight' | 'left' | 'right' | 'uturn' | 'off-route' | 'arrive';

export interface RouteFrame {
  anchor: MapPoint;
  projectedPoint: MapPoint;
  forwardPoints: MapPoint[];
  distanceToRoute: number;
  routeHeadingDeg: number | null;
  headingReferenceDeg: number | null;
  relativeTurnDeg: number | null;
  remainingDistance: number;
}

export interface NavigationGuidance {
  kind: GuidanceKind;
  text: string;
  shortText: string;
  hasLivePose: boolean;
  isUpcomingTurn: boolean;
  routeFrame: RouteFrame;
}

interface SegmentProjection {
  distance: number;
  projectedPoint: MapPoint;
  segmentIndex: number;
}

function pointDistance(a: MapPoint, b: MapPoint): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

export function normalizeDegrees(value: number): number {
  const normalized = value % 360;
  return normalized >= 0 ? normalized : normalized + 360;
}

export function normalizeSignedDegrees(value: number): number {
  return ((value + 180) % 360 + 360) % 360 - 180;
}

export function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

export function headingFromPoints(from: MapPoint, to: MapPoint): number {
  return normalizeDegrees((Math.atan2(to.y - from.y, to.x - from.x) * 180) / Math.PI);
}

function dedupeSequentialPoints(points: MapPoint[], epsilon = 0.01): MapPoint[] {
  const deduped: MapPoint[] = [];

  for (const point of points) {
    const previous = deduped.at(-1);
    if (previous && pointDistance(previous, point) <= epsilon) {
      continue;
    }
    deduped.push(point);
  }

  return deduped;
}

function projectPointToSegment(point: MapPoint, start: MapPoint, end: MapPoint, segmentIndex: number): SegmentProjection {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const lengthSquared = dx * dx + dy * dy;

  if (lengthSquared <= 1e-6) {
    return {
      distance: pointDistance(point, start),
      projectedPoint: start,
      segmentIndex,
    };
  }

  const tRaw = ((point.x - start.x) * dx + (point.y - start.y) * dy) / lengthSquared;
  const t = clamp(tRaw, 0, 1);
  const projectedPoint = {
    x: start.x + dx * t,
    y: start.y + dy * t,
  };

  return {
    distance: pointDistance(point, projectedPoint),
    projectedPoint,
    segmentIndex,
  };
}

function getNearestProjection(routePath: MapPoint[], anchor: MapPoint): SegmentProjection | null {
  if (routePath.length === 0) {
    return null;
  }

  if (routePath.length === 1) {
    return {
      distance: pointDistance(anchor, routePath[0]),
      projectedPoint: routePath[0],
      segmentIndex: 0,
    };
  }

  let best: SegmentProjection | null = null;
  for (let index = 0; index < routePath.length - 1; index += 1) {
    const candidate = projectPointToSegment(anchor, routePath[index], routePath[index + 1], index);
    if (!best || candidate.distance < best.distance) {
      best = candidate;
    }
  }

  return best;
}

function buildForwardPoints(routePath: MapPoint[], projection: SegmentProjection | null): MapPoint[] {
  if (routePath.length === 0) {
    return [];
  }

  if (!projection) {
    return [...routePath];
  }

  const suffixStart = Math.min(projection.segmentIndex + 1, routePath.length - 1);
  return dedupeSequentialPoints([projection.projectedPoint, ...routePath.slice(suffixStart)]);
}

function sumPathDistance(points: MapPoint[]): number {
  let total = 0;
  for (let index = 1; index < points.length; index += 1) {
    total += pointDistance(points[index - 1], points[index]);
  }
  return total;
}

function getPrimaryRouteHeading(forwardPoints: MapPoint[]): number | null {
  for (let index = 1; index < forwardPoints.length; index += 1) {
    if (pointDistance(forwardPoints[index - 1], forwardPoints[index]) >= 1) {
      return headingFromPoints(forwardPoints[index - 1], forwardPoints[index]);
    }
  }
  return null;
}

function findUpcomingTurn(
  forwardPoints: MapPoint[]
): { turnAngleDeg: number; distanceAhead: number } | null {
  if (forwardPoints.length < 3) {
    return null;
  }

  let distanceAhead = 0;
  for (let index = 1; index < forwardPoints.length - 1; index += 1) {
    const previous = forwardPoints[index - 1];
    const current = forwardPoints[index];
    const next = forwardPoints[index + 1];
    const incomingDistance = pointDistance(previous, current);
    const outgoingDistance = pointDistance(current, next);

    if (incomingDistance < 1 || outgoingDistance < 1) {
      continue;
    }

    distanceAhead += incomingDistance;

    const incomingHeading = headingFromPoints(previous, current);
    const outgoingHeading = headingFromPoints(current, next);
    const turnAngleDeg = normalizeSignedDegrees(outgoingHeading - incomingHeading);

    if (Math.abs(turnAngleDeg) >= 28) {
      return {
        turnAngleDeg,
        distanceAhead,
      };
    }
  }

  return null;
}

export function buildRouteFrame(
  routePath: MapPoint[],
  livePosition: MapPoint | null,
  liveHeadingDeg: number | null
): RouteFrame | null {
  if (routePath.length === 0) {
    return null;
  }

  const anchor = livePosition ?? routePath[0];
  const projection = getNearestProjection(routePath, anchor);
  const forwardPoints = buildForwardPoints(routePath, projection);
  const routeHeadingDeg = getPrimaryRouteHeading(forwardPoints);
  const headingReferenceDeg =
    typeof liveHeadingDeg === 'number' && Number.isFinite(liveHeadingDeg)
      ? normalizeDegrees(liveHeadingDeg)
      : routeHeadingDeg;

  return {
    anchor,
    projectedPoint: projection?.projectedPoint ?? routePath[0],
    forwardPoints,
    distanceToRoute: projection?.distance ?? 0,
    routeHeadingDeg,
    headingReferenceDeg,
    relativeTurnDeg:
      routeHeadingDeg !== null && headingReferenceDeg !== null
        ? normalizeSignedDegrees(routeHeadingDeg - headingReferenceDeg)
        : null,
    remainingDistance: sumPathDistance(forwardPoints),
  };
}

export function buildNavigationGuidance(
  routePath: MapPoint[],
  livePosition: MapPoint | null,
  liveHeadingDeg: number | null
): NavigationGuidance | null {
  const routeFrame = buildRouteFrame(routePath, livePosition, liveHeadingDeg);
  if (!routeFrame) {
    return null;
  }

  const hasLivePose = livePosition !== null;
  const relativeTurnDeg = routeFrame.relativeTurnDeg;
  const distanceToRoute = routeFrame.distanceToRoute;
  const upcomingTurn = findUpcomingTurn(routeFrame.forwardPoints);
  const headingAlignedWithRoute =
    relativeTurnDeg === null || Math.abs(relativeTurnDeg) <= 28;
  const canWarnOffRoute =
    hasLivePose &&
    !upcomingTurn &&
    routeFrame.remainingDistance > 10;
  const isHardOffRoute = canWarnOffRoute && distanceToRoute >= 68;

  if (routeFrame.remainingDistance <= 6) {
    return {
      kind: 'arrive',
      text: 'Destination ahead',
      shortText: 'Arrive',
      hasLivePose,
      isUpcomingTurn: false,
      routeFrame,
    };
  }

  if (relativeTurnDeg !== null && Math.abs(relativeTurnDeg) >= 145) {
    return {
      kind: 'uturn',
      text: 'Turn back',
      shortText: 'Turn back',
      hasLivePose,
      isUpcomingTurn: false,
      routeFrame,
    };
  }

  if (isHardOffRoute && relativeTurnDeg !== null && Math.abs(relativeTurnDeg) >= 70) {
    return {
      kind: relativeTurnDeg > 0 ? 'right' : 'left',
      text: relativeTurnDeg > 0 ? 'Head right back to route' : 'Head left back to route',
      shortText: 'Back to route',
      hasLivePose,
      isUpcomingTurn: false,
      routeFrame,
    };
  }

  if ((isHardOffRoute && !headingAlignedWithRoute) || distanceToRoute >= 90) {
    return {
      kind: 'off-route',
      text: 'Move back to route',
      shortText: 'Back to route',
      hasLivePose,
      isUpcomingTurn: false,
      routeFrame,
    };
  }

  if (relativeTurnDeg !== null && Math.abs(relativeTurnDeg) >= 40) {
    return {
      kind: relativeTurnDeg > 0 ? 'right' : 'left',
      text: relativeTurnDeg > 0 ? 'Turn right' : 'Turn left',
      shortText: relativeTurnDeg > 0 ? 'Right' : 'Left',
      hasLivePose,
      isUpcomingTurn: false,
      routeFrame,
    };
  }

  if (upcomingTurn && upcomingTurn.distanceAhead <= 34 && Math.abs(upcomingTurn.turnAngleDeg) >= 24) {
    return {
      kind: upcomingTurn.turnAngleDeg > 0 ? 'right' : 'left',
      text: upcomingTurn.turnAngleDeg > 0 ? 'Right turn ahead' : 'Left turn ahead',
      shortText: upcomingTurn.turnAngleDeg > 0 ? 'Right ahead' : 'Left ahead',
      hasLivePose,
      isUpcomingTurn: true,
      routeFrame,
    };
  }

  return {
    kind: 'straight',
    text: 'Go straight',
    shortText: 'Straight',
    hasLivePose,
    isUpcomingTurn: false,
    routeFrame,
  };
}
