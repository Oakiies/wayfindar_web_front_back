import {
  ArrowUp,
  Box,
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
  Store as StoreIcon,
  X,
} from 'lucide-react';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import ARFloorThreeOverlay, { type TransitionTargetMarker } from './ARFloorThreeOverlay';
import MapCanvas, { MAP_MARKER_COLORS } from './MapCanvas';
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
          color: MAP_MARKER_COLORS.origin,
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
          color: MAP_MARKER_COLORS.destination,
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
              ? MAP_MARKER_COLORS.transitionStairs
              : MAP_MARKER_COLORS.transitionLift,
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

  /* Each manoeuvre gets its own icon AND its own colour โ€” colour alone is
     never the only signal (accessibility: do not rely on colour). */
  const guidancePresentation = useMemo(() => {
    const kind: GuidanceKind = guidance?.kind ?? 'straight';

    switch (kind) {
      case 'left':
        return {
          Icon: CornerUpLeft,
          iconWrapClass: 'bg-blue-50 text-blue-800',
        };
      case 'right':
        return {
          Icon: CornerUpRight,
          iconWrapClass: 'bg-blue-50 text-blue-800',
        };
      case 'uturn':
        return {
          Icon: RotateCcw,
          iconWrapClass: 'bg-rose-50 text-rose-800',
        };
      case 'off-route':
        return {
          Icon: NavigationIcon,
          iconWrapClass: 'bg-amber-50 text-amber-900',
        };
      case 'arrive':
        return {
          Icon: MapPin,
          iconWrapClass: 'bg-emerald-50 text-emerald-800',
        };
      case 'straight':
      default:
        return {
          Icon: ArrowUp,
          iconWrapClass: 'bg-sky-50 text-sky-800',
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
    ? 'glass-dark mt-1 inline-flex items-center gap-2.5 rounded-full px-5 py-3'
    : 'glass-dark mt-1 inline-flex items-center gap-2 rounded-full px-4 py-2';
  const topGuidanceIconClass = showTurnCue ? 'h-6 w-6' : 'h-5 w-5';
  const topGuidanceTextClass = showTurnCue ? 'text-xl font-bold' : 'text-lg font-bold';
  const destinationName = routeDestinationStore?.name || destination || 'Destination';

  return (
    <div ref={splitContainerRef} className="relative flex h-full flex-col overflow-hidden bg-canvas text-white">
      {showModeMenu && (
        <div
          role="menu"
          aria-label="View mode"
          className="pointer-events-auto absolute right-3 top-1/2 z-[75] -translate-y-1/2 rounded-card border border-line-soft bg-elevated p-2 text-ink shadow-overlay"
        >
          <p className="mb-2 px-1 text-[12px] font-semibold uppercase tracking-wider text-ink-3">View mode</p>
          <div className="flex flex-col gap-1.5">
            <button
              type="button"
              role="menuitemradio"
              aria-checked={arViewMode === 'ar'}
              className={`press flex min-h-[44px] items-center gap-2.5 rounded-xl px-3 text-left text-[15px] font-semibold ${
                arViewMode === 'ar' ? 'bg-accent text-white' : 'text-ink-2 hover:bg-sunken hover:text-ink'
              }`}
              onClick={() => handleSelectMode('ar')}
            >
              <Box className="h-[18px] w-[18px]" aria-hidden="true" />
              <span>AR Navigate</span>
            </button>

            {showSplitViewOption && (
              <button
                type="button"
                role="menuitemradio"
                aria-checked={arViewMode === 'split'}
                className={`press flex min-h-[44px] items-center gap-2.5 rounded-xl px-3 text-left text-[15px] font-semibold ${
                  arViewMode === 'split' ? 'bg-accent text-white' : 'text-ink-2 hover:bg-sunken hover:text-ink'
                }`}
                onClick={() => handleSelectMode('split')}
              >
                <div className="h-[18px] w-[18px] rounded border-2 border-current" aria-hidden="true">
                  <div className="h-1/2 border-b-2 border-current"></div>
                </div>
                <span>Split View</span>
              </button>
            )}

            <button
              type="button"
              role="menuitemradio"
              aria-checked={arViewMode === 'map'}
              className={`press flex min-h-[44px] items-center gap-2.5 rounded-xl px-3 text-left text-[15px] font-semibold ${
                arViewMode === 'map' ? 'bg-accent text-white' : 'text-ink-2 hover:bg-sunken hover:text-ink'
              }`}
              onClick={() => handleSelectMode('map')}
            >
              <MapPin className="h-[18px] w-[18px]" aria-hidden="true" />
              <span>Map Only</span>
            </button>
          </div>
        </div>
      )}

      <div
        className={`on-glass relative w-full bg-black ${
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
          <div className="flex h-full w-full items-center justify-center bg-slate-900 px-6 text-white">
            <div className="max-w-[320px] text-center">
              <Camera className="mx-auto mb-3 h-10 w-10 text-slate-300" aria-hidden="true" />
              <p className="text-[15px] font-semibold">Camera unavailable</p>
              {cameraError && <p className="mt-2 text-[13px] leading-relaxed text-slate-200">{cameraError}</p>}
              <button
                type="button"
                onClick={toggleCamera}
                className="press tap mt-4 inline-flex items-center gap-2 rounded-full bg-white px-5 text-[14px] font-semibold text-ink"
              >
                <Camera className="h-4 w-4" aria-hidden="true" />
                Try again
              </button>
            </div>
          </div>
        )}

        <div className="absolute inset-x-0 top-0 z-20 bg-gradient-to-b from-black/75 to-transparent px-4 pb-8 pt-[max(0.75rem,env(safe-area-inset-top))]">
          <div className="relative flex items-start justify-between">
            <button
              type="button"
              onClick={resetToMap}
              aria-label="End navigation"
              className="glass-dark press tap flex items-center justify-center rounded-full text-white"
            >
              <X className="h-5 w-5" aria-hidden="true" />
            </button>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={toggleCamera}
                aria-label={cameraActive ? 'Turn camera off' : 'Turn camera on'}
                className="glass-dark press tap flex items-center justify-center rounded-full text-white"
              >
                {cameraActive ? (
                  <CameraOff className="h-5 w-5" aria-hidden="true" />
                ) : (
                  <Camera className="h-5 w-5" aria-hidden="true" />
                )}
              </button>
              <button
                type="button"
                onClick={toggleModeMenu}
                aria-label="Change view mode"
                aria-expanded={showModeMenu}
                aria-haspopup="menu"
                className="glass-dark press tap flex items-center justify-center rounded-full text-white"
              >
                <MapIcon className="h-5 w-5" aria-hidden="true" />
              </button>
            </div>

            <div
              className="pointer-events-none absolute left-1/2 top-0 -translate-x-1/2 text-center text-white"
              aria-live="polite"
            >
              <p className="text-[12px] font-semibold uppercase tracking-[0.1em] text-white/90">Direction</p>
              <p className={topGuidanceWrapClass}>
                <GuidanceIcon className={topGuidanceIconClass} aria-hidden="true" />
                <span className={topGuidanceTextClass}>{guidance?.text ?? 'Follow route'}</span>
              </p>
            </div>
          </div>
        </div>

        {arViewMode === 'split' && (
          <div
            className="absolute bottom-[-6px] left-0 h-3 w-full cursor-row-resize bg-white/20"
            onPointerDown={startSplitDrag}
            role="separator"
            aria-label="Drag to resize camera and map"
          ></div>
        )}

        {arViewMode === 'ar' && !isLandscape && (
          <div className="pointer-events-none absolute inset-0 z-30 flex items-center justify-center p-6">
            <div className="glass-dark rounded-card px-6 py-5 text-center text-white">
              <RotateCcw className="mx-auto mb-2 h-6 w-6" aria-hidden="true" />
              <p className="text-[15px] font-semibold">Rotate phone to landscape</p>
              <p className="mt-1 text-[13px] text-white/90">AR navigation works in horizontal orientation.</p>
            </div>
          </div>
        )}

        {arViewMode === 'ar' && isLandscape && (
          <div
            ref={popupRef}
            className="pointer-events-auto absolute z-30 overflow-hidden rounded-card border border-line-soft bg-elevated text-ink shadow-overlay"
            style={{
              left: popupPosition.x,
              top: popupPosition.y,
              width: popupSize.width,
            }}
          >
            <div
              className="flex cursor-grab items-center justify-between gap-2 border-b border-line-soft px-3 py-1.5 active:cursor-grabbing"
              onPointerDown={startPopupDrag}
              role="separator"
              aria-label="Drag to move the map"
            >
              <div className="flex min-w-0 items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wider text-ink-3">
                <Move className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                <span className="truncate">Map</span>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <span className="rounded-full bg-sunken px-2 py-0.5 text-[12px] font-bold text-ink-2">
                  {activeFloorLabel}
                </span>
                <button
                  type="button"
                  className="press flex h-9 w-9 items-center justify-center rounded-lg text-ink-2 hover:bg-sunken hover:text-ink"
                  onClick={togglePopupSize}
                  aria-label={popupExpanded ? 'Shrink map' : 'Expand map'}
                  aria-expanded={popupExpanded}
                >
                  {popupExpanded ? (
                    <Minimize2 className="h-4 w-4" aria-hidden="true" />
                  ) : (
                    <Maximize2 className="h-4 w-4" aria-hidden="true" />
                  )}
                </button>
              </div>
            </div>

            <button
              type="button"
              className="block w-full text-left"
              onClick={handlePopupMapClick}
              aria-label={popupExpanded ? 'Shrink map' : 'Expand map'}
            >
              <MapCanvas
                mapImageUrl={mapImageUrl}
                route={routePath}
                markers={mapMarkers}
                currentPose={currentPose}
                title={`Live position on ${activeFloorLabel}`}
                className={`${popupMapHeightClass} w-full`}
              />
            </button>
          </div>
        )}
      </div>

      <div
        className={`relative w-full bg-canvas ${
          arViewMode === 'map' ? 'h-full' : arViewMode === 'ar' ? 'hidden' : ''
        }`}
        style={arViewMode === 'split' ? { height: `${100 - splitCameraRatio * 100}%` } : undefined}
      >
        {arViewMode === 'map' && (
          <div className="absolute inset-x-0 top-0 z-40 flex items-center justify-between gap-3 px-4 pt-[max(1rem,env(safe-area-inset-top))]">
            <button
              type="button"
              onClick={resetToMap}
              aria-label="End navigation"
              className="glass press tap flex items-center justify-center rounded-full text-ink-2"
            >
              <X className="h-5 w-5" aria-hidden="true" />
            </button>
            <div className="glass rounded-2xl px-5 py-2 text-center">
              <p className="text-[12px] font-semibold uppercase tracking-[0.08em] text-ink-3">Current floor</p>
              <p className="text-[15px] font-bold text-ink">{activeFloorLabel}</p>
            </div>
            <button
              type="button"
              onClick={toggleModeMenu}
              aria-label="Change view mode"
              aria-expanded={showModeMenu}
              aria-haspopup="menu"
              className="glass press tap flex items-center justify-center rounded-full text-ink-2"
            >
              <MapIcon className="h-5 w-5" aria-hidden="true" />
            </button>
          </div>
        )}

        {showRouteFloorStack && (
          <nav
            aria-label="Floors along this route"
            className="pointer-events-auto absolute right-3 top-1/2 z-30 flex -translate-y-1/2 flex-col"
          >
            <div className="glass flex flex-col items-center gap-1 rounded-full p-1.5">
              {routeFloorSequence.map((floor) => {
                const active = floor.id === activeFloorId;
                return (
                  <button
                    key={floor.id}
                    type="button"
                    onClick={() => onSelectRouteFloor?.(floor.id)}
                    aria-pressed={active}
                    aria-label={floor.label}
                    className={`press tap flex items-center justify-center rounded-full px-2 text-[13px] font-semibold ${
                      active ? 'bg-ink text-white shadow-sm' : 'text-ink-3 hover:bg-black/5 hover:text-ink'
                    }`}
                  >
                    {formatFloorChipLabel(floor.label)}
                  </button>
                );
              })}
            </div>
          </nav>
        )}

        <MapCanvas
          mapImageUrl={mapImageUrl}
          route={routePath}
          markers={mapMarkers}
          currentPose={currentPose}
          title={`Live position and route on ${activeFloorLabel}`}
          className="h-full w-full"
        />

        {(liveMethod || liveTrackingMode) && (
          <div className="glass absolute bottom-4 left-4 rounded-full px-3.5 py-2 text-[12px] font-semibold text-ink-2">
            {liveMethod ? `Method: ${liveMethod}` : ''}
            {liveMethod && liveTrackingMode ? ' ยท ' : ''}
            {liveTrackingMode ? `Track: ${liveTrackingMode}` : ''}
          </div>
        )}
      </div>

      {showStandaloneTurnCue ? (
        <div className="pointer-events-none absolute inset-x-0 top-24 z-40 flex justify-center px-4">
          <div className="glass-dark inline-flex items-center gap-3 rounded-[22px] px-5 py-3 text-white">
            <div
              className={`flex h-14 w-14 shrink-0 items-center justify-center rounded-full ${guidancePresentation.iconWrapClass}`}
            >
              <GuidanceIcon className="h-8 w-8" aria-hidden="true" />
            </div>
            <div className="text-left">
              <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-white/90">Turn</p>
              <p className="text-[17px] font-bold leading-tight">{turnCueLabel}</p>
            </div>
          </div>
        </div>
      ) : null}

      {arViewMode !== 'ar' && (
        <div
          className={`absolute inset-x-0 z-30 ${
            isLandscape ? 'bottom-2 px-2' : 'bottom-0 px-4 pb-[max(1rem,env(safe-area-inset-bottom))]'
          }`}
        >
          <div
            className={`rounded-card border border-line-soft bg-surface text-ink shadow-card ${
              isLandscape ? 'p-2.5' : 'p-4'
            }`}
          >
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3">
                <span
                  className={`flex shrink-0 items-center justify-center overflow-hidden rounded-xl bg-sunken ${
                    isLandscape ? 'h-9 w-9 text-xl' : 'h-11 w-11 text-2xl'
                  }`}
                >
                  {routeDestinationStore?.logoSrc ? (
                    <img src={routeDestinationStore.logoSrc} alt="" className="h-full w-full object-contain" />
                  ) : routeDestinationStore?.logo ? (
                    <span aria-hidden="true">{routeDestinationStore.logo}</span>
                  ) : (
                    <StoreIcon className="h-5 w-5 text-ink-3" aria-hidden="true" />
                  )}
                </span>
                <div className="min-w-0">
                  <p className={`truncate font-bold text-ink ${isLandscape ? 'text-[14px]' : 'text-[16px]'}`}>
                    {destinationName}
                  </p>
                  <p className={`truncate text-ink-2 ${isLandscape ? 'text-[12px]' : 'text-[13px]'}`}>
                    {routeDestinationStore?.floor || activeFloorLabel}
                  </p>
                </div>
              </div>
              <div className="shrink-0 text-right">
                <p className={`font-bold text-accent-ink ${isLandscape ? 'text-[16px]' : 'text-[20px]'}`}>
                  {routeTime}
                </p>
                <p className={`text-ink-2 ${isLandscape ? 'text-[12px]' : 'text-[13px]'}`}>{routeMeta}</p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default NavigationView;
