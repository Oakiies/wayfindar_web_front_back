import {
  ArrowUp,
  Camera,
  CameraOff,
  CornerUpLeft,
  CornerUpRight,
  Map as MapIcon,
  MapPin,
  Maximize2,
  Minimize2,
  Move,
  Navigation as NavigationIcon,
  RotateCcw,
  X,
} from 'lucide-react';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import ARFloorThreeOverlay, { type TransitionTargetMarker } from './ARFloorThreeOverlay';
import MapCanvas from './MapCanvas';
import { type MapPoint, type Store } from '../types/navigation';
import { buildNavigationGuidance, type GuidanceKind } from '../utils/navigationGuidance';

export type ViewMode = 'map' | 'split' | 'ar';

interface NavigationViewProps {
  arViewMode: ViewMode;
  setArViewMode: (mode: ViewMode) => void;
  showModeMenu: boolean;
  toggleModeMenu: () => void;
  resetToMap: () => void;
  routeDestinationStore: Store | null;
  routeTime: string;
  routeMeta: string;
  destination: string;
  mapImageUrl: string;
  routePath: MapPoint[];
  originPoint: MapPoint | null;
  destinationPoint: MapPoint | null;
  livePosition?: MapPoint | null;
  liveHeadingDeg?: number | null;
  hideStaticMarkers?: boolean;
  showDestinationWhenStaticHidden?: boolean;
  liveMethod?: string | null;
  liveTrackingMode?: string | null;
  liveTransitionTarget?: TransitionTargetMarker | null;
  activeFloorId: string;
  activeFloorLabel: string;
  routeFloorSequence?: Array<{ id: string; label: string }>;
  onSelectRouteFloor?: (floorId: string) => void;
  cameraActive: boolean;
  cameraError?: string | null;
  cameraVideoRef: React.RefObject<HTMLVideoElement | null>;
  toggleCamera: () => void;
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

const MAP_POPUP_MARGIN = 12;
const MAP_POPUP_DEFAULT_SIZE = { width: 230, height: 180 };
const MAP_POPUP_EXPANDED_SIZE = { width: 340, height: 260 };

interface PopupPosition {
  x: number;
  y: number;
}

const NavigationView: React.FC<NavigationViewProps> = ({
  arViewMode,
  setArViewMode,
  showModeMenu,
  toggleModeMenu,
  resetToMap,
  routeDestinationStore,
  routeTime,
  routeMeta,
  destination,
  mapImageUrl,
  routePath,
  originPoint,
  destinationPoint,
  livePosition = null,
  liveHeadingDeg = null,
  hideStaticMarkers = false,
  showDestinationWhenStaticHidden = true,
  liveMethod = null,
  liveTrackingMode = null,
  liveTransitionTarget = null,
  activeFloorId,
  activeFloorLabel,
  routeFloorSequence = [],
  onSelectRouteFloor,
  cameraActive,
  cameraError = null,
  cameraVideoRef,
  toggleCamera,
}) => {
  const [splitCameraRatio, setSplitCameraRatio] = useState(0.5);
  const showSplitViewOption = false;
  const splitContainerRef = useRef<HTMLDivElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);
  const popupDraggedRef = useRef(false);
  const [popupExpanded, setPopupExpanded] = useState(false);
  const [popupPosition, setPopupPosition] = useState<PopupPosition>({ x: 0, y: 0 });
  const [popupReady, setPopupReady] = useState(false);
  const [isLandscape, setIsLandscape] = useState(() => {
    if (typeof window === 'undefined') {
      return false;
    }
    return window.matchMedia('(orientation: landscape)').matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }

    const media = window.matchMedia('(orientation: landscape)');
    const update = () => setIsLandscape(media.matches);
    update();

    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', update);
      return () => media.removeEventListener('change', update);
    }

    media.addListener(update);
    return () => media.removeListener(update);
  }, []);

  const popupSize = popupExpanded ? MAP_POPUP_EXPANDED_SIZE : MAP_POPUP_DEFAULT_SIZE;
  const popupMapHeightClass = popupExpanded ? 'h-[260px]' : 'h-[180px]';
  const showRouteFloorStack = arViewMode === 'map' && routeFloorSequence.length > 1;

  const formatFloorChipLabel = (label: string): string => {
    const compact = label.replace(/floor/gi, 'F').replace(/\s+/g, '');
    return compact || label;
  };

  const clampPopupPosition = (x: number, y: number, width: number, height: number): PopupPosition => {
    if (typeof window === 'undefined') {
      return { x, y };
    }

    const maxX = Math.max(MAP_POPUP_MARGIN, window.innerWidth - width - MAP_POPUP_MARGIN);
    const maxY = Math.max(64, window.innerHeight - height - MAP_POPUP_MARGIN);
    return {
      x: clamp(x, MAP_POPUP_MARGIN, maxX),
      y: clamp(y, 64, maxY),
    };
  };

  useEffect(() => {
    if (arViewMode !== 'ar' || !isLandscape) {
      setPopupReady(false);
    }
  }, [arViewMode, isLandscape]);

  useEffect(() => {
    if (typeof window === 'undefined' || arViewMode !== 'ar' || !isLandscape) {
      return;
    }

    setPopupPosition((previous) => {
      const initial = popupReady
        ? previous
        : {
            x: window.innerWidth - popupSize.width - MAP_POPUP_MARGIN,
            y: 64,
          };
      return clampPopupPosition(initial.x, initial.y, popupSize.width, popupSize.height);
    });

    if (!popupReady) {
      setPopupReady(true);
    }
  }, [arViewMode, isLandscape, popupReady, popupSize.height, popupSize.width]);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }

    const handleResize = () => {
      setPopupPosition((previous) =>
        clampPopupPosition(previous.x, previous.y, popupSize.width, popupSize.height)
      );
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [popupSize.height, popupSize.width]);

  const togglePopupSize = () => {
    setPopupExpanded((previous) => !previous);
  };

  const startPopupDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    const startX = event.clientX;
    const startY = event.clientY;
    const origin = popupPosition;
    popupDraggedRef.current = false;

    const move = (pointerEvent: PointerEvent) => {
      const dx = pointerEvent.clientX - startX;
      const dy = pointerEvent.clientY - startY;
      if (!popupDraggedRef.current && Math.hypot(dx, dy) > 3) {
        popupDraggedRef.current = true;
      }
      const next = clampPopupPosition(
        origin.x + dx,
        origin.y + dy,
        popupSize.width,
        popupSize.height
      );
      setPopupPosition(next);
    };

    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.setTimeout(() => {
        popupDraggedRef.current = false;
      }, 0);
    };

    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  const handlePopupMapClick = () => {
    if (popupDraggedRef.current) {
      return;
    }
    togglePopupSize();
  };

  const handleSelectMode = (mode: ViewMode) => {
    setArViewMode(mode);
    if (showModeMenu) {
      toggleModeMenu();
    }
  };

  const updateSplitHeight = (y: number) => {
    if (!splitContainerRef.current) {
      return;
    }

    const rect = splitContainerRef.current.getBoundingClientRect();
    const ratio = (y - rect.top) / rect.height;
    setSplitCameraRatio(Math.min(0.9, Math.max(0.2, ratio)));
  };

  const startSplitDrag = (event: React.PointerEvent) => {
    event.preventDefault();
    updateSplitHeight(event.clientY);

    const move = (pointerEvent: PointerEvent) => updateSplitHeight(pointerEvent.clientY);
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };

    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  const mapMarkers = [
    !hideStaticMarkers && originPoint
      ? {
          id: 'origin',
          x: originPoint.x,
          y: originPoint.y,
          color: '#16a34a',
          label: 'S',
          size: 9,
          variant: 'route' as const,
        }
      : null,
    (destinationPoint && (!hideStaticMarkers || showDestinationWhenStaticHidden))
      ? {
          id: 'destination',
          x: destinationPoint.x,
          y: destinationPoint.y,
          color: '#ef4444',
          label: 'D',
          size: 10,
          variant: 'route' as const,
        }
      : null,
    liveTransitionTarget
      ? {
          id: 'transition-target',
          x: liveTransitionTarget.x,
          y: liveTransitionTarget.y,
          color:
            typeof liveTransitionTarget.type === 'string' && liveTransitionTarget.type.toLowerCase().includes('stair')
              ? '#f59e0b'
              : '#22c55e',
          label:
            typeof liveTransitionTarget.type === 'string' && liveTransitionTarget.type.toLowerCase().includes('stair')
              ? 'S'
              : 'L',
          size: 12,
        }
      : null,
  ].filter((marker): marker is NonNullable<typeof marker> => marker !== null);

  const currentPose = livePosition
    ? {
        x: livePosition.x,
        y: livePosition.y,
        headingDeg: liveHeadingDeg ?? undefined,
      }
    : null;
  const cameraSectionStyle: React.CSSProperties | undefined =
    arViewMode === 'split' ? { height: `${splitCameraRatio * 100}%` } : undefined;

  const guidance = useMemo(
    () => buildNavigationGuidance(routePath, livePosition, liveHeadingDeg),
    [liveHeadingDeg, livePosition, routePath]
  );

  const guidancePresentation = useMemo(() => {
    const kind: GuidanceKind = guidance?.kind ?? 'straight';

    switch (kind) {
      case 'left':
        return {
          Icon: CornerUpLeft,
          iconWrapClass: 'bg-blue-100 text-blue-700',
          chipClass: 'border-blue-200 bg-blue-500/20 text-white',
        };
      case 'right':
        return {
          Icon: CornerUpRight,
          iconWrapClass: 'bg-blue-100 text-blue-700',
          chipClass: 'border-blue-200 bg-blue-500/20 text-white',
        };
      case 'uturn':
        return {
          Icon: RotateCcw,
          iconWrapClass: 'bg-rose-100 text-rose-700',
          chipClass: 'border-rose-300 bg-rose-500/25 text-white',
        };
      case 'off-route':
        return {
          Icon: NavigationIcon,
          iconWrapClass: 'bg-amber-100 text-amber-700',
          chipClass: 'border-amber-200 bg-amber-500/25 text-white',
        };
      case 'arrive':
        return {
          Icon: MapPin,
          iconWrapClass: 'bg-emerald-100 text-emerald-700',
          chipClass: 'border-emerald-200 bg-emerald-500/25 text-white',
        };
      case 'straight':
      default:
        return {
          Icon: ArrowUp,
          iconWrapClass: 'bg-sky-100 text-sky-700',
          chipClass: 'border-white/30 bg-black/50 text-white',
        };
    }
  }, [guidance?.kind]);

  const GuidanceIcon = guidancePresentation.Icon;
  const showTurnCue =
    Boolean(guidance) &&
    (guidance?.kind === 'left' ||
      guidance?.kind === 'right' ||
      guidance?.kind === 'uturn' ||
      guidance?.isUpcomingTurn);
  const showStandaloneTurnCue = showTurnCue && arViewMode === 'map';
  const turnCueLabel = guidance?.isUpcomingTurn ? guidance.shortText : guidance?.text ?? '';
  const topGuidanceWrapClass = showTurnCue
    ? 'mt-1 inline-flex items-center gap-2 rounded-full border border-white/30 bg-black/60 px-5 py-3 shadow-2xl backdrop-blur'
    : 'mt-1 inline-flex items-center gap-2 rounded-full border border-white/20 bg-black/35 px-4 py-2 backdrop-blur';
  const topGuidanceIconClass = showTurnCue ? 'h-6 w-6' : 'h-5 w-5';
  const topGuidanceTextClass = showTurnCue ? 'text-xl font-bold' : 'text-lg font-bold';

  return (
    <div ref={splitContainerRef} className="relative flex h-full flex-col overflow-hidden bg-[#f0eeea] text-white">
      {showModeMenu && (
        <div className="pointer-events-auto absolute right-3 top-1/2 z-[75] -translate-y-1/2 rounded-2xl border border-white/40 bg-white/90 p-2 text-slate-800 shadow-2xl backdrop-blur-xl">
          <div className="mb-2 px-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">View Mode</div>
          <div className="flex flex-col gap-1.5">
            <button
              className={`flex items-center gap-2 rounded-xl px-3 py-2 text-left text-sm font-semibold transition ${
                arViewMode === 'ar' ? 'bg-blue-500 text-white' : 'hover:bg-slate-100'
              }`}
              onClick={() => handleSelectMode('ar')}
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"
                />
              </svg>
              <span>AR Narvigate</span>
            </button>

            {showSplitViewOption && (
              <button
                className={`flex items-center gap-2 rounded-xl px-3 py-2 text-left text-sm font-semibold transition ${
                  arViewMode === 'split' ? 'bg-blue-500 text-white' : 'hover:bg-slate-100'
                }`}
                onClick={() => handleSelectMode('split')}
              >
                <div className="h-4 w-4 rounded border-2 border-current">
                  <div className="h-1/2 border-b-2 border-current"></div>
                </div>
                <span>Split View</span>
              </button>
            )}

            <button
              className={`flex items-center gap-2 rounded-xl px-3 py-2 text-left text-sm font-semibold transition ${
                arViewMode === 'map' ? 'bg-blue-500 text-white' : 'hover:bg-slate-100'
              }`}
              onClick={() => handleSelectMode('map')}
            >
              <MapPin className="h-4 w-4" />
              <span>Map Only</span>
            </button>
          </div>
        </div>
      )}

      <div
        className={`relative w-full bg-black ${
          arViewMode === 'ar' ? 'h-full overflow-hidden' : arViewMode === 'map' ? 'hidden' : ''
        }`}
        style={cameraSectionStyle}
      >
        {cameraActive ? (
          arViewMode === 'ar' ? (
            <div className="relative h-full w-full overflow-hidden bg-black">
              <video ref={cameraVideoRef} autoPlay muted playsInline className="h-full w-full object-cover"></video>

              {guidance && (
                <div className="pointer-events-none absolute inset-0 z-10">
                  <ARFloorThreeOverlay
                    routePath={routePath}
                    livePosition={livePosition}
                    liveHeadingDeg={liveHeadingDeg}
                    transitionTarget={liveTransitionTarget}
                    enabled={cameraActive && arViewMode === 'ar'}
                  />
                </div>
              )}
            </div>
          ) : (
            <video ref={cameraVideoRef} autoPlay muted playsInline className="h-full w-full object-cover"></video>
          )
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-gradient-to-b from-slate-700 to-slate-900 text-white/70">
            <div className="text-center">
              <Camera className="mx-auto mb-2 h-10 w-10 opacity-60" />
              <p className="text-sm">Camera unavailable</p>
              {cameraError && <p className="mt-2 max-w-[280px] text-xs text-white/80">{cameraError}</p>}
            </div>
          </div>
        )}

        <div className="absolute top-0 left-0 right-0 z-20 bg-gradient-to-b from-black/70 to-transparent p-4">
          <div className="relative flex items-center justify-between">
            <button onClick={resetToMap} className="rounded-full bg-white/20 p-2 backdrop-blur">
              <X className="h-6 w-6 text-white" />
            </button>

            <div className="flex items-center gap-2">
              <button
                onClick={toggleCamera}
                className="rounded-full bg-white/20 p-2 backdrop-blur transition hover:bg-white/30"
                title={cameraActive ? 'Turn camera off' : 'Turn camera on'}
              >
                {cameraActive ? <CameraOff className="h-5 w-5 text-white" /> : <Camera className="h-5 w-5 text-white" />}
              </button>
              <button onClick={toggleModeMenu} className="rounded-full bg-white/20 p-2 backdrop-blur">
                <MapIcon className="h-6 w-6 text-white" />
              </button>
            </div>

            <div className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-center text-white">
              <div className="text-sm opacity-80">Direction</div>
              <div className={topGuidanceWrapClass}>
                <GuidanceIcon className={topGuidanceIconClass} />
                <span className={topGuidanceTextClass}>{guidance?.text ?? 'Follow route'}</span>
              </div>
            </div>
          </div>
        </div>

        {arViewMode === 'split' && (
          <div
            className="absolute bottom-[-6px] left-0 h-3 w-full cursor-row-resize bg-white/10"
            onPointerDown={startSplitDrag}
          ></div>
        )}

        {arViewMode === 'ar' && !isLandscape && (
          <div className="pointer-events-none absolute inset-0 z-30 flex items-center justify-center p-6">
            <div className="rounded-2xl bg-black/70 px-5 py-4 text-center text-white backdrop-blur">
              <p className="text-sm font-semibold">Rotate phone to landscape</p>
              <p className="mt-1 text-xs text-white/80">Use AR Narvigate in horizontal orientation.</p>
            </div>
          </div>
        )}

        {arViewMode === 'ar' && isLandscape && (
          <div
            ref={popupRef}
            className="pointer-events-auto absolute z-30 overflow-hidden rounded-2xl border border-white/40 bg-white/92 text-slate-900 shadow-2xl backdrop-blur-md"
            style={{
              left: popupPosition.x,
              top: popupPosition.y,
              width: popupSize.width,
            }}
          >
            <div
              className="flex cursor-grab items-center justify-between border-b border-slate-200/80 px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-slate-600 active:cursor-grabbing"
              onPointerDown={startPopupDrag}
            >
              <div className="flex items-center gap-1.5">
                <Move className="h-3.5 w-3.5" />
                <span>Map Popup</span>
              </div>
              <div className="flex items-center gap-1">
                <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[9px] font-bold text-slate-700">
                  {activeFloorLabel}
                </span>
                <button
                  type="button"
                  className="rounded-md p-1 text-slate-600 transition hover:bg-slate-200/80 hover:text-slate-900"
                  onClick={togglePopupSize}
                  title={popupExpanded ? 'Shrink map' : 'Expand map'}
                >
                  {popupExpanded ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
                </button>
              </div>
            </div>

            <button
              type="button"
              className="block w-full text-left"
              onClick={handlePopupMapClick}
              title="Tap to resize map"
            >
              <MapCanvas
                mapImageUrl={mapImageUrl}
                route={routePath}
                markers={mapMarkers}
                currentPose={currentPose}
                className={`${popupMapHeightClass} w-full`}
              />
            </button>
          </div>
        )}
      </div>

      <div
        className={`relative w-full bg-[#f0eeea] ${
          arViewMode === 'map' ? 'h-full' : arViewMode === 'ar' ? 'hidden' : ''
        }`}
        style={arViewMode === 'split' ? { height: `${100 - splitCameraRatio * 100}%` } : undefined}
      >
        {arViewMode === 'map' && (
          <div className="absolute top-0 left-0 right-0 z-40 bg-gradient-to-b from-black/70 to-transparent p-4">
            <div className="flex items-center justify-between">
              <button onClick={resetToMap} className="rounded-full bg-white/20 p-2 backdrop-blur">
                <X className="h-6 w-6 text-white" />
              </button>
              <div className="rounded-2xl bg-white/90 px-6 py-3 text-slate-900 shadow-lg">
                <div className="text-center">
                  <div className="text-xs text-gray-600">Current Floor</div>
                  <div className="text-sm font-bold text-gray-900">{activeFloorLabel}</div>
                </div>
              </div>
              <button onClick={toggleModeMenu} className="rounded-full bg-white/20 p-2 backdrop-blur">
                <MapIcon className="h-6 w-6 text-white" />
              </button>
            </div>
          </div>
        )}

        {showRouteFloorStack && (
          <div className="pointer-events-auto absolute right-4 top-1/2 z-30 flex -translate-y-1/2 flex-col gap-4">
            <div className="flex flex-col items-center gap-1 rounded-full border border-slate-100 bg-white/95 px-1.5 py-2 shadow-lg backdrop-blur">
              {routeFloorSequence.map((floor) => {
                const active = floor.id === activeFloorId;
                return (
                  <button
                    key={floor.id}
                    type="button"
                    onClick={() => onSelectRouteFloor?.(floor.id)}
                    className={`flex h-10 w-10 items-center justify-center rounded-full text-sm font-semibold transition-colors ${
                      active
                        ? 'bg-slate-900 text-white shadow-md'
                        : 'text-slate-500 hover:bg-slate-100 hover:text-slate-700'
                    }`}
                    title={floor.label}
                  >
                    {formatFloorChipLabel(floor.label)}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        <MapCanvas mapImageUrl={mapImageUrl} route={routePath} markers={mapMarkers} currentPose={currentPose} className="h-full w-full" />


        {(liveMethod || liveTrackingMode) && (
          <div className="absolute left-4 bottom-4 rounded-full bg-white/90 px-3 py-1.5 text-[11px] font-semibold text-slate-800 shadow">
            {liveMethod ? `Method: ${liveMethod}` : ''}
            {liveMethod && liveTrackingMode ? ' | ' : ''}
            {liveTrackingMode ? `Track: ${liveTrackingMode}` : ''}
          </div>
        )}
      </div>

      {showStandaloneTurnCue ? (
        <div className="pointer-events-none absolute inset-x-0 top-24 z-40 flex justify-center px-4">
          <div className="inline-flex items-center gap-3 rounded-[22px] border border-white/30 bg-black/55 px-5 py-3 text-white shadow-2xl backdrop-blur-md">
            <div className={`flex h-14 w-14 items-center justify-center rounded-full ${guidancePresentation.iconWrapClass}`}>
              <GuidanceIcon className="h-8 w-8" />
            </div>
            <div className="text-left">
              <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-white/70">Turn</div>
              <div className="text-base font-bold leading-tight">{turnCueLabel}</div>
            </div>
          </div>
        </div>
      ) : null}

      {arViewMode !== 'ar' && (
        <div className={`absolute left-0 right-0 z-30 ${isLandscape ? 'bottom-2 px-2' : 'bottom-0 p-4'}`}>
          <div className={`border border-gray-200 bg-white text-slate-900 shadow-xl ${isLandscape ? 'rounded-xl p-2.5' : 'rounded-2xl p-4'}`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className={isLandscape ? 'text-2xl' : 'text-3xl'}>{routeDestinationStore?.logo || '??'}</div>
                <div>
                  <div className={`${isLandscape ? 'text-sm' : 'text-base'} font-bold text-gray-900`}>{routeDestinationStore?.name || destination || 'Destination'}</div>
                  <div className={`${isLandscape ? 'text-[11px]' : 'text-sm'} text-gray-600`}>{routeDestinationStore?.floor || activeFloorLabel}</div>
                </div>
              </div>
              <div className="text-right">
                <div className={`${isLandscape ? 'text-base' : 'text-xl'} font-bold text-blue-600`}>{routeTime}</div>
                <div className={`${isLandscape ? 'text-[11px]' : 'text-sm'} text-gray-600`}>{routeMeta}</div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default NavigationView;

