import React from 'react';
import { type MapPoint } from '../types/navigation';

export interface MapMarker {
  id: string;
  x: number;
  y: number;
  color?: string;
  size?: number;
  label?: string;
  /**
   * `origin` / `destination` render the minimal start & end symbols.
   * `route` is kept as a backward-compatible alias of `origin`.
   */
  variant?: 'default' | 'route' | 'origin' | 'destination';
  onClick?: () => void;
}

export interface MapFocus {
  x: number;
  y: number;
  /** 1 = whole floor plan, 6 = tightest close-up. */
  zoom?: number;
  /**
   * Pushes the focus point above the centre of the frame, as a fraction of the
   * visible height. Use it to keep the point clear of a bottom sheet.
   */
  yBias?: number;
}

interface MapCanvasProps {
  mapImageUrl: string;
  markers?: MapMarker[];
  route?: MapPoint[];
  currentPose?: {
    x: number;
    y: number;
    headingDeg?: number | null;
  } | null;
  /** Recentres and zooms the map. Users can still pan/zoom away from it afterwards. */
  focus?: MapFocus | null;
  /** Enables wheel zoom, drag pan and pinch zoom. */
  interactive?: boolean;
  className?: string;
}

const MAP_SIZE = 500;
const MIN_ZOOM = 1;
const MAX_ZOOM = 6;

/** Flat palette — no gradients anywhere, so every layer reads at a glance. */
const ROUTE_COLOR = '#0d6efd';
const POSE_COLOR = '#0d6efd';
const ORIGIN_COLOR = '#111315';
const DESTINATION_COLOR = '#e5484d';

/**
 * Pose symbol, in screen pixels.
 *
 * A small flat accent disc with a radar fan for the bearing. The pose is
 * intentionally a different shape from the dotted route, so one accent colour
 * can still communicate both symbols without making them look identical.
 */
const POSE_RADIUS = 7;

/** The origin ring keeps its casing - it can sit anywhere on the plan. */
const ORIGIN_CASING = 2.6;

/** The bearing fan. Flat fill, no gradient - the outline carries it over a dark plan. */
const POSE_FAN_RADIUS = 30;
const POSE_FAN_HALF_ANGLE = 32;
const POSE_FAN_OPACITY = 0.32;
const POSE_FAN_EDGE_OPACITY = 0.62;
const POSE_CASING_RADIUS = 2.4;

/** Dotted trail, in screen pixels: each accent dot sits on a white casing. */
const ROUTE_DOT_SPACING = 17;
const ROUTE_DOT_RADIUS = 4;
const ROUTE_DOT_CASING_RADIUS = 6.2;

interface ViewBox {
  cx: number;
  cy: number;
  /** Side length of the square visible area, in map units. */
  size: number;
}

const FULL_VIEW: ViewBox = { cx: MAP_SIZE / 2, cy: MAP_SIZE / 2, size: MAP_SIZE };

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

/** Keeps the visible square inside the floor plan at every zoom level. */
function clampView(view: ViewBox): ViewBox {
  const size = clamp(view.size, MAP_SIZE / MAX_ZOOM, MAP_SIZE / MIN_ZOOM);
  const half = size / 2;
  return {
    size,
    cx: clamp(view.cx, half, MAP_SIZE - half),
    cy: clamp(view.cy, half, MAP_SIZE - half),
  };
}

function viewFromFocus(focus: MapFocus): ViewBox {
  const size = MAP_SIZE / clamp(focus.zoom ?? 2.5, MIN_ZOOM, MAX_ZOOM);
  return clampView({
    cx: focus.x,
    cy: focus.y + size * (focus.yBias ?? 0),
    size,
  });
}

/** Emits evenly spaced points along the true route length, not per vertex. */
function sampleAlongPath(points: MapPoint[], spacing: number): MapPoint[] {
  if (points.length < 2 || spacing <= 0) {
    return [];
  }

  const samples: MapPoint[] = [points[0]];
  let carried = 0;

  for (let index = 1; index < points.length; index += 1) {
    const from = points[index - 1];
    const to = points[index];
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const length = Math.hypot(dx, dy);
    if (length === 0) {
      continue;
    }

    let travelled = spacing - carried;
    while (travelled <= length) {
      const ratio = travelled / length;
      samples.push({ x: from.x + dx * ratio, y: from.y + dy * ratio });
      travelled += spacing;
    }
    carried = (carried + length) % spacing;
  }

  return samples;
}

/**
 * Radar fan, drawn opening along +x and rotated into place by the caller.
 *
 * A pie sector rather than a triangle: the arc reads as a field of view, the
 * way a radar sweep does, where a straight-edged wedge read as an arrowhead
 * stuck to the dot. Filled flat and outlined - no gradient - because a fading
 * cone vanishes over the dark parts of a floor plan, which is what sank the
 * original translucent version.
 */
function buildRadarFanPath(radius: number, halfAngleDeg: number): string {
  const a = (halfAngleDeg * Math.PI) / 180;
  const x = radius * Math.cos(a);
  const y = radius * Math.sin(a);
  return `M 0 0 L ${x} ${-y} A ${radius} ${radius} 0 0 1 ${x} ${y} Z`;
}

/**
 * A true map pin: a circle of `radius` whose centre sits `distance` above the
 * tip, closed by the two straight lines that are tangent to that circle. The
 * tangents make the taper meet the head smoothly instead of bulging.
 */
function buildPinPath(radius: number, distance: number): string {
  const cosPhi = radius / distance;
  const sinPhi = Math.sqrt(Math.max(0, 1 - cosPhi * cosPhi));
  const tangentX = radius * sinPhi;
  const tangentY = -distance + radius * cosPhi;

  return [
    'M 0 0',
    `L ${tangentX} ${tangentY}`,
    `A ${radius} ${radius} 0 1 0 ${-tangentX} ${tangentY}`,
    'Z',
  ].join(' ');
}

const MapCanvas: React.FC<MapCanvasProps> = ({
  mapImageUrl,
  markers = [],
  route = [],
  currentPose = null,
  focus = null,
  interactive = false,
  className,
}) => {
  const svgRef = React.useRef<SVGSVGElement | null>(null);
  const [view, setView] = React.useState<ViewBox>(() => (focus ? viewFromFocus(focus) : FULL_VIEW));

  const focusX = focus?.x;
  const focusY = focus?.y;
  const focusZoom = focus?.zoom;
  const focusYBias = focus?.yBias;

  React.useEffect(() => {
    if (focusX === undefined || focusY === undefined) {
      return;
    }
    setView(viewFromFocus({ x: focusX, y: focusY, zoom: focusZoom, yBias: focusYBias }));
  }, [focusX, focusY, focusZoom, focusYBias]);

  /**
   * Side of the drawn square, in CSS pixels. `preserveAspectRatio="meet"` fits
   * the square viewBox inside the box and letterboxes the rest, so this is the
   * shorter side of whatever the caller sized us to.
   *
   * It is measured rather than assumed because the symbol sizes below are meant
   * to be screen pixels. Dividing by MAP_SIZE instead only holds when the canvas
   * happens to be 500px; in the 230x180 AR popup it shrank a 7px pose dot to
   * 2.5px, which is how the marker ended up disappearing into the trail.
   */
  const [drawnPx, setDrawnPx] = React.useState(MAP_SIZE);

  React.useEffect(() => {
    const svg = svgRef.current;
    if (!svg || typeof ResizeObserver === 'undefined') {
      return;
    }
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      const drawn = Math.min(width, height);
      if (drawn > 0) {
        setDrawnPx(drawn);
      }
    });
    observer.observe(svg);
    return () => observer.disconnect();
  }, []);

  /** Map units per rendered pixel — used to keep symbols the same on-screen size at any zoom. */
  const unitsPerPixel = view.size / drawnPx;
  const s = (value: number) => value * unitsPerPixel;

  /** Converts a client point to map coordinates, accounting for the meet letterboxing. */
  const toMapPoint = (clientX: number, clientY: number): { x: number; y: number } | null => {
    const svg = svgRef.current;
    if (!svg) {
      return null;
    }
    const rect = svg.getBoundingClientRect();
    const drawn = Math.min(rect.width, rect.height);
    if (drawn <= 0) {
      return null;
    }
    const scale = drawn / view.size;
    const offsetX = (rect.width - drawn) / 2;
    const offsetY = (rect.height - drawn) / 2;
    return {
      x: view.cx - view.size / 2 + (clientX - rect.left - offsetX) / scale,
      y: view.cy - view.size / 2 + (clientY - rect.top - offsetY) / scale,
    };
  };

  const mapUnitsPerClientPixel = (): number => {
    const svg = svgRef.current;
    if (!svg) {
      return unitsPerPixel;
    }
    const rect = svg.getBoundingClientRect();
    const drawn = Math.min(rect.width, rect.height);
    return drawn > 0 ? view.size / drawn : unitsPerPixel;
  };

  /** Zooms by `factor` while keeping the map point under the cursor stationary. */
  const zoomAround = (clientX: number, clientY: number, factor: number) => {
    const anchor = toMapPoint(clientX, clientY);
    setView((previous) => {
      const next = clampView({ ...previous, size: previous.size / factor });
      if (!anchor) {
        return next;
      }
      const ratio = next.size / previous.size;
      return clampView({
        size: next.size,
        cx: anchor.x + (previous.cx - anchor.x) * ratio,
        cy: anchor.y + (previous.cy - anchor.y) * ratio,
      });
    });
  };

  // React registers `wheel` passively on the root, so preventDefault only works
  // from a listener we attach ourselves.
  const zoomAroundRef = React.useRef(zoomAround);
  zoomAroundRef.current = zoomAround;

  React.useEffect(() => {
    const svg = svgRef.current;
    if (!interactive || !svg) {
      return;
    }
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      zoomAroundRef.current(event.clientX, event.clientY, Math.exp(-event.deltaY * 0.0016));
    };
    svg.addEventListener('wheel', onWheel, { passive: false });
    return () => svg.removeEventListener('wheel', onWheel);
  }, [interactive]);

  const pointersRef = React.useRef(new Map<number, { x: number; y: number }>());
  const pinchDistanceRef = React.useRef<number | null>(null);

  const handlePointerDown = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!interactive) {
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    pointersRef.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    pinchDistanceRef.current = null;
  };

  const handlePointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!interactive) {
      return;
    }
    const pointers = pointersRef.current;
    const previous = pointers.get(event.pointerId);
    if (!previous) {
      return;
    }
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });

    if (pointers.size >= 2) {
      const [a, b] = Array.from(pointers.values());
      const distance = Math.hypot(a.x - b.x, a.y - b.y);
      const lastDistance = pinchDistanceRef.current;
      pinchDistanceRef.current = distance;
      if (lastDistance && distance > 0) {
        zoomAround((a.x + b.x) / 2, (a.y + b.y) / 2, distance / lastDistance);
      }
      return;
    }

    const perPixel = mapUnitsPerClientPixel();
    const dx = (event.clientX - previous.x) * perPixel;
    const dy = (event.clientY - previous.y) * perPixel;
    setView((current) => clampView({ ...current, cx: current.cx - dx, cy: current.cy - dy }));
  };

  const endPointer = (event: React.PointerEvent<SVGSVGElement>) => {
    pointersRef.current.delete(event.pointerId);
    if (pointersRef.current.size < 2) {
      pinchDistanceRef.current = null;
    }
  };

  const routeTrail = route.length > 1 ? sampleAlongPath(route, ROUTE_DOT_SPACING) : [];
  const headingDeg =
    currentPose && typeof currentPose.headingDeg === 'number' ? currentPose.headingDeg : null;

  return (
    <svg
      ref={svgRef}
      viewBox={`${view.cx - view.size / 2} ${view.cy - view.size / 2} ${view.size} ${view.size}`}
      className={className}
      preserveAspectRatio="xMidYMid meet"
      style={interactive ? { touchAction: 'none', cursor: 'grab' } : undefined}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endPointer}
      onPointerCancel={endPointer}
    >
      {mapImageUrl ? (
        <image
          href={mapImageUrl}
          x="0"
          y="0"
          width={MAP_SIZE}
          height={MAP_SIZE}
          preserveAspectRatio="none"
        />
      ) : (
        <>
          <rect x="0" y="0" width={MAP_SIZE} height={MAP_SIZE} fill="#e2e8f0" />
          <text
            x={MAP_SIZE / 2}
            y={MAP_SIZE / 2}
            textAnchor="middle"
            dominantBaseline="middle"
            fill="#475569"
            fontSize={s(18)}
            fontWeight="600"
          >
            No map image
          </text>
        </>
      )}

      {routeTrail.length > 0 && (
        <g aria-hidden="true">
          {/* White casing keeps every trail dot readable over room fills and
              wall lines while the route and pose stay on one accent colour. */}
          <g>
            {routeTrail.map((point, index) => (
              <circle
                key={`route-casing-${index}`}
                cx={point.x}
                cy={point.y}
                r={s(ROUTE_DOT_CASING_RADIUS)}
                fill="#ffffff"
              />
            ))}
          </g>
          <g>
            {routeTrail.map((point, index) => (
              <circle
                key={`route-dot-${index}`}
                cx={point.x}
                cy={point.y}
                r={s(ROUTE_DOT_RADIUS)}
                fill={ROUTE_COLOR}
              />
            ))}
          </g>
        </g>
      )}

      {markers.map((marker) => {
        const clickable = typeof marker.onClick === 'function';
        const variant = marker.variant === 'route' ? 'origin' : marker.variant ?? 'default';

        if (variant === 'destination') {
          const color = marker.color ?? DESTINATION_COLOR;
          const radius = s(marker.size ?? 11);

          return (
            <g
              key={marker.id}
              transform={`translate(${marker.x} ${marker.y})`}
              onClick={marker.onClick}
              className={clickable ? 'cursor-pointer' : undefined}
            >
              {/* Flat teardrop: one fill, one hairline casing, one hole. The
                  hole is what reads as a pin rather than a blob at small sizes. */}
              <path
                d={buildPinPath(radius, radius * 2.4)}
                fill={color}
                stroke="#ffffff"
                strokeWidth={radius * 0.16}
                strokeLinejoin="round"
              />
              <circle cx="0" cy={-radius * 2.4} r={radius * 0.3} fill="#ffffff" />
            </g>
          );
        }

        if (variant === 'origin') {
          const color = marker.color ?? ORIGIN_COLOR;
          const radius = s(marker.size ?? 8);

          return (
            <g
              key={marker.id}
              transform={`translate(${marker.x} ${marker.y})`}
              onClick={marker.onClick}
              className={clickable ? 'cursor-pointer' : undefined}
            >
              <circle cx="0" cy="0" r={radius + s(ORIGIN_CASING) * 0.8} fill="#ffffff" />
              <circle cx="0" cy="0" r={radius} fill="none" stroke={color} strokeWidth={radius * 0.34} />
            </g>
          );
        }

        const color = marker.color ?? '#16a34a';
        const radius = s(marker.size ?? 9);
        const label = marker.label?.slice(0, 2).toUpperCase() ?? '';

        return (
          <g
            key={marker.id}
            transform={`translate(${marker.x} ${marker.y})`}
            onClick={marker.onClick}
            className={clickable ? 'cursor-pointer' : undefined}
          >
            <circle cx="0" cy="0" r={radius * 1.18} fill="#ffffff" />
            <circle cx="0" cy="0" r={radius} fill={color} />
            {label && (
              <text
                x="0"
                y={radius * 0.05}
                textAnchor="middle"
                dominantBaseline="middle"
                fill="#ffffff"
                fontSize={radius * 0.95}
                fontWeight="700"
              >
                {label}
              </text>
            )}
          </g>
        );
      })}

      {currentPose && (
        /* Position glides to each new fix instead of teleporting. Only the
           translate is animated - rotating the bearing would spin the long way
           round whenever the heading wraps past 360. */
        <g
          transform={`translate(${currentPose.x} ${currentPose.y})`}
          style={{ transition: 'transform 320ms linear' }}
        >
          {/* Radar fan: flat fill, flat outline, no gradient. Drawn first so
              the dot sits on top of its own apex. */}
          {headingDeg !== null && (
            <g transform={`rotate(${headingDeg})`}>
              <path
                d={buildRadarFanPath(s(POSE_FAN_RADIUS), POSE_FAN_HALF_ANGLE)}
                fill={POSE_COLOR}
                opacity={POSE_FAN_OPACITY}
              />
              <path
                d={buildRadarFanPath(s(POSE_FAN_RADIUS), POSE_FAN_HALF_ANGLE)}
                fill="none"
                stroke={POSE_COLOR}
                strokeWidth={s(1.4)}
                strokeLinejoin="round"
                opacity={POSE_FAN_EDGE_OPACITY}
              />
            </g>
          )}

          {/* The white casing separates the live pose from both the dotted
              trail and the floor-plan drawing while keeping one accent hue. */}
          <circle r={s(POSE_RADIUS + POSE_CASING_RADIUS)} fill="#ffffff" />
          <circle r={s(POSE_RADIUS)} fill={POSE_COLOR} />
        </g>
      )}

    </svg>
  );
};

export default MapCanvas;
