import React from 'react';
import { type MapPoint } from '../types/navigation';

export interface MapMarker {
  id: string;
  x: number;
  y: number;
  color?: string;
  size?: number;
  label?: string;
  variant?: 'default' | 'route';
  onClick?: () => void;
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
  className?: string;
  /** Accessible name for the map. Falls back to a generic description. */
  title?: string;
}

const MAP_SIZE = 500;

/**
 * Marker fills live here rather than as literals in each view: they are SVG
 * paint values, so they cannot be Tailwind classes, and every screen has to
 * agree on what "start", "destination" and "floor change" look like.
 * Values mirror --color-origin / --color-dest / --color-warn in index.css.
 */
export const MAP_MARKER_COLORS = {
  origin: '#15803d',
  destination: '#dc2626',
  transitionStairs: '#b45309',
  transitionLift: '#15803d',
} as const;

function polarToCartesian(cx: number, cy: number, radius: number, angleRad: number): { x: number; y: number } {
  return {
    x: cx + Math.cos(angleRad) * radius,
    y: cy + Math.sin(angleRad) * radius,
  };
}

function buildHeadingFanPath(
  cx: number,
  cy: number,
  headingRad: number,
  spreadRad: number,
  innerRadius: number,
  outerRadius: number
): string {
  const startRad = headingRad - spreadRad;
  const endRad = headingRad + spreadRad;
  const outerStart = polarToCartesian(cx, cy, outerRadius, startRad);
  const outerEnd = polarToCartesian(cx, cy, outerRadius, endRad);
  const innerEnd = polarToCartesian(cx, cy, innerRadius, endRad);
  const innerStart = polarToCartesian(cx, cy, innerRadius, startRad);
  const largeArcFlag = spreadRad * 2 > Math.PI ? 1 : 0;

  return [
    `M ${outerStart.x} ${outerStart.y}`,
    `A ${outerRadius} ${outerRadius} 0 ${largeArcFlag} 1 ${outerEnd.x} ${outerEnd.y}`,
    `L ${innerEnd.x} ${innerEnd.y}`,
    `A ${innerRadius} ${innerRadius} 0 ${largeArcFlag} 0 ${innerStart.x} ${innerStart.y}`,
    'Z',
  ].join(' ');
}

const MapCanvas: React.FC<MapCanvasProps> = ({
  mapImageUrl,
  markers = [],
  route = [],
  currentPose = null,
  className,
  title,
}) => {
  const idToken = React.useId().replace(/:/g, '');
  const titleId = `${idToken}-title`;
  const fanFarGradientId = `${idToken}-fan-far`;
  const fanMidGradientId = `${idToken}-fan-mid`;
  const fanCoreGradientId = `${idToken}-fan-core`;
  const haloGradientId = `${idToken}-halo`;
  const pinGradientId = `${idToken}-pin`;
  const bladeGradientId = `${idToken}-blade`;
  const glowFilterId = `${idToken}-glow`;
  const markerShadowFilterId = `${idToken}-marker-shadow`;
  const routePoints = route.map((point) => `${point.x},${point.y}`).join(' ');
  const headingRad =
    currentPose && typeof currentPose.headingDeg === 'number'
      ? (currentPose.headingDeg * Math.PI) / 180.0
      : null;

  const headingTip =
    currentPose && headingRad !== null ? polarToCartesian(currentPose.x, currentPose.y, 43, headingRad) : null;
  const headingFanFar =
    currentPose && headingRad !== null
      ? buildHeadingFanPath(currentPose.x, currentPose.y, headingRad, Math.PI / 5.4, 10, 48)
      : null;
  const headingFanMid =
    currentPose && headingRad !== null
      ? buildHeadingFanPath(currentPose.x, currentPose.y, headingRad, Math.PI / 8, 8, 38)
      : null;
  const headingFanCore =
    currentPose && headingRad !== null
      ? buildHeadingFanPath(currentPose.x, currentPose.y, headingRad, Math.PI / 12, 7, 29)
      : null;
  const bladeForward =
    currentPose && headingRad !== null
      ? buildHeadingFanPath(currentPose.x, currentPose.y, headingRad, Math.PI / 26, 4, 15)
      : null;
  const bladeLeft =
    currentPose && headingRad !== null
      ? buildHeadingFanPath(currentPose.x, currentPose.y, headingRad + 2.28, Math.PI / 26, 4, 11)
      : null;
  const bladeRight =
    currentPose && headingRad !== null
      ? buildHeadingFanPath(currentPose.x, currentPose.y, headingRad - 2.28, Math.PI / 26, 4, 11)
      : null;

  return (
    <svg
      viewBox={`0 0 ${MAP_SIZE} ${MAP_SIZE}`}
      className={className}
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-labelledby={titleId}
    >
      <title id={titleId}>{title ?? 'Indoor floor plan'}</title>
      <defs>
        <linearGradient
          id={fanFarGradientId}
          gradientUnits="userSpaceOnUse"
          x1={currentPose?.x ?? 0}
          y1={currentPose?.y ?? 0}
          x2={headingTip?.x ?? 1}
          y2={headingTip?.y ?? 1}
        >
          <stop offset="0%" stopColor="#60a5fa" stopOpacity="0.08" />
          <stop offset="72%" stopColor="#38bdf8" stopOpacity="0.38" />
          <stop offset="100%" stopColor="#0ea5e9" stopOpacity="0.16" />
        </linearGradient>
        <linearGradient
          id={fanMidGradientId}
          gradientUnits="userSpaceOnUse"
          x1={currentPose?.x ?? 0}
          y1={currentPose?.y ?? 0}
          x2={headingTip?.x ?? 1}
          y2={headingTip?.y ?? 1}
        >
          <stop offset="0%" stopColor="#93c5fd" stopOpacity="0.15" />
          <stop offset="70%" stopColor="#3b82f6" stopOpacity="0.56" />
          <stop offset="100%" stopColor="#2563eb" stopOpacity="0.34" />
        </linearGradient>
        <linearGradient
          id={fanCoreGradientId}
          gradientUnits="userSpaceOnUse"
          x1={currentPose?.x ?? 0}
          y1={currentPose?.y ?? 0}
          x2={headingTip?.x ?? 1}
          y2={headingTip?.y ?? 1}
        >
          <stop offset="0%" stopColor="#dbeafe" stopOpacity="0.52" />
          <stop offset="80%" stopColor="#2563eb" stopOpacity="0.78" />
          <stop offset="100%" stopColor="#1d4ed8" stopOpacity="0.65" />
        </linearGradient>
        <radialGradient id={haloGradientId} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#bae6fd" stopOpacity="0.55" />
          <stop offset="60%" stopColor="#60a5fa" stopOpacity="0.2" />
          <stop offset="100%" stopColor="#60a5fa" stopOpacity="0" />
        </radialGradient>
        <radialGradient id={pinGradientId} cx="35%" cy="35%" r="65%">
          <stop offset="0%" stopColor="#93c5fd" />
          <stop offset="70%" stopColor="#2563eb" />
          <stop offset="100%" stopColor="#1e40af" />
        </radialGradient>
        <linearGradient
          id={bladeGradientId}
          gradientUnits="userSpaceOnUse"
          x1={currentPose?.x ?? 0}
          y1={currentPose?.y ?? 0}
          x2={headingTip?.x ?? 1}
          y2={headingTip?.y ?? 1}
        >
          <stop offset="0%" stopColor="#f8fafc" stopOpacity="0.9" />
          <stop offset="100%" stopColor="#bfdbfe" stopOpacity="0.96" />
        </linearGradient>
        <filter id={glowFilterId} x="-90%" y="-90%" width="280%" height="280%">
          <feGaussianBlur stdDeviation="2.8" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <filter id={markerShadowFilterId} x="-160%" y="-220%" width="420%" height="420%">
          <feDropShadow dx="0" dy="1.5" stdDeviation="1.8" floodColor="#0f172a" floodOpacity="0.2" />
        </filter>
      </defs>

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
          <rect x="0" y="0" width={MAP_SIZE} height={MAP_SIZE} fill="#f3f2ef" />
          <text
            x={MAP_SIZE / 2}
            y={MAP_SIZE / 2 - 6}
            textAnchor="middle"
            dominantBaseline="middle"
            fill="#374151"
            fontSize="18"
            fontWeight="600"
          >
            Floor plan unavailable
          </text>
          <text
            x={MAP_SIZE / 2}
            y={MAP_SIZE / 2 + 18}
            textAnchor="middle"
            dominantBaseline="middle"
            fill="#5c6470"
            fontSize="13"
          >
            Route and markers are still shown below
          </text>
        </>
      )}

      {route.length > 1 && (
        <g aria-hidden="true">
          {/* White casing keeps the route readable over a busy floor plan */}
          <polyline
            points={routePoints}
            fill="none"
            stroke="#ffffff"
            strokeWidth="9"
            strokeOpacity="0.9"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <polyline
            points={routePoints}
            fill="none"
            stroke="#2563eb"
            strokeWidth="5.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {/* Dashes travel toward the destination to convey direction.
              The animation is disabled under prefers-reduced-motion. */}
          <polyline
            className="route-flow"
            points={routePoints}
            fill="none"
            stroke="#ffffff"
            strokeWidth="2.4"
            strokeOpacity="0.85"
            strokeDasharray="8 12"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </g>
      )}

      {markers.map((marker) => {
        const size = marker.size ?? 9;
        const color = marker.color ?? '#16a34a';
        const clickable = typeof marker.onClick === 'function';
        const label = marker.label?.slice(0, 2).toUpperCase() ?? '';

        if (marker.variant === 'route') {
          const dotRadius = Math.max(6, size * 0.82);

          return (
            <g
              key={marker.id}
              transform={`translate(${marker.x} ${marker.y})`}
              onClick={marker.onClick}
              className={clickable ? 'cursor-pointer' : undefined}
            >
              <g filter={`url(#${markerShadowFilterId})`}>
                <circle cx="0" cy="0" r={dotRadius + 2} fill="white" opacity="0.98" />
                <circle cx="0" cy="0" r={dotRadius} fill={color} opacity="0.98" />
                <text
                  x="0"
                  y="0.5"
                  textAnchor="middle"
                  dominantBaseline="middle"
                  fill="white"
                  fontSize={Math.max(8, dotRadius * 1.08)}
                  fontWeight="700"
                >
                  {label}
                </text>
              </g>
              <circle cx={-dotRadius * 0.36} cy={-dotRadius * 0.4} r={dotRadius * 0.38} fill="white" opacity="0.3" />
            </g>
          );
        }

        return (
          <g
            key={marker.id}
            onClick={marker.onClick}
            className={clickable ? 'cursor-pointer' : undefined}
          >
            <circle cx={marker.x} cy={marker.y} r={size + 1} fill="white" opacity="0.95" />
            <circle cx={marker.x} cy={marker.y} r={size} fill={color} opacity="0.95" />
            {marker.label && (
              <text
                x={marker.x}
                y={marker.y + 1}
                textAnchor="middle"
                dominantBaseline="middle"
                fill="white"
                fontSize="8"
                fontWeight="700"
              >
                {label}
              </text>
            )}
          </g>
        );
      })}

      {currentPose && (
        <g>
          <circle cx={currentPose.x} cy={currentPose.y} r={30} fill={`url(#${haloGradientId})`} />
          {headingFanFar && (
            <path d={headingFanFar} fill={`url(#${fanFarGradientId})`} filter={`url(#${glowFilterId})`} />
          )}
          {headingFanMid && <path d={headingFanMid} fill={`url(#${fanMidGradientId})`} />}
          {headingFanCore && <path d={headingFanCore} fill={`url(#${fanCoreGradientId})`} />}
          <circle cx={currentPose.x} cy={currentPose.y} r={18} fill="#60a5fa" opacity="0.14" />
          <circle cx={currentPose.x} cy={currentPose.y} r={11.5} fill="#ffffff" stroke="#93c5fd" strokeWidth="1.8" />
          {bladeLeft && <path d={bladeLeft} fill="#dbeafe" opacity="0.9" />}
          {bladeRight && <path d={bladeRight} fill="#dbeafe" opacity="0.9" />}
          {bladeForward && <path d={bladeForward} fill={`url(#${bladeGradientId})`} />}
          <circle cx={currentPose.x} cy={currentPose.y} r={4.8} fill={`url(#${pinGradientId})`} />
          <circle cx={currentPose.x} cy={currentPose.y} r={1.8} fill="#f8fafc" />
          {headingTip && <circle cx={headingTip.x} cy={headingTip.y} r={2.6} fill="#38bdf8" opacity="0.72" />}
        </g>
      )}
    </svg>
  );
};

export default MapCanvas;
