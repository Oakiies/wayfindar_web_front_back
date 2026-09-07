import {
  ArrowUp,
  Camera,
  CameraOff,
  CornerUpLeft,
  CornerUpRight,
  Layers,
  Map as MapIcon,
  MapPin,
  Navigation as NavigationIcon,
  RotateCcw,
  X,
} from 'lucide-react';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import ARFloorThreeOverlay, { type TransitionTargetMarker } from './ARFloorThreeOverlay';
import MapCanvas from './MapCanvas';
import IconButton from './ui/IconButton';
import FloorRail from './ui/FloorRail';
import { type MapPoint, type Store } from '../types/navigation';
import { type ArWorldPayload } from '../services/navigationTestService';
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
  liveArWorld?: ArWorldPayload | null;
  activeFloorId: string;
  activeFloorLabel: string;
  routeFloorSequence?: Array<{ id: string; label: string }>;
  onSelectRouteFloor?: (floorId: string) => void;
  cameraActive: boolean;
  cameraError?: string | null;
  cameraVideoRef: React.RefObject<HTMLVideoElement | null>;
  toggleCamera: () => void;
}

const MAP_POPUP_MARGIN = 12;
// Keep the preview square so the 500x500 floor plan stays a true top-down map
// instead of being letterboxed into a short strip under a toolbar.
const MAP_POPUP_DEFAULT_SIZE = { width: 230, height: 230 };
const MAP_POPUP_EXPANDED_SIZE = { width: 340, height: 340 };

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
  liveArWorld = null,
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
  const [popupExpanded, setPopupExpanded] = useState(false);
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
  const showRouteFloorStack = arViewMode === 'map' && routeFloorSequence.length > 1;

  const togglePopupSize = () => {
    setPopupExpanded((previous) => !previous);
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
      ? { id: 'origin', x: originPoint.x, y: originPoint.y, size: 8, variant: 'origin' as const }
      : null,
    destinationPoint && (!hideStaticMarkers || showDestinationWhenStaticHidden)
      ? {
          id: 'destination',
          x: destinationPoint.x,
          y: destinationPoint.y,
          size: 12,
          variant: 'destination' as const,
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
    ? { x: livePosition.x, y: livePosition.y, headingDeg: liveHeadingDeg ?? undefined }
    : null;
  const cameraSectionStyle: React.CSSProperties | undefined =
    arViewMode === 'split' ? { height: `${splitCameraRatio * 100}%` } : undefined;

  const guidance = useMemo(
    () => buildNavigationGuidance(routePath, livePosition, liveHeadingDeg),
    [liveHeadingDeg, livePosition, routePath]
  );

  /**
   * One icon per manoeuvre. Colour is reserved for the two states that need
   * attention - off-route and arrival; everything else stays neutral so the cue
   * never competes with the route drawn on the map.
   */
  const guidancePresentation = useMemo(() => {
    const kind: GuidanceKind = guidance?.kind ?? 'straight';

    switch (kind) {
      case 'left':
        return { Icon: CornerUpLeft, accentClass: 'bg-white/15 text-white' };
      case 'right':
        return { Icon: CornerUpRight, accentClass: 'bg-white/15 text-white' };
      case 'uturn':
        return { Icon: RotateCcw, accentClass: 'bg-white/15 text-white' };
      case 'off-route':
        return { Icon: NavigationIcon, accentClass: 'bg-warn/25 text-warn' };
      case 'arrive':
        return { Icon: MapPin, accentClass: 'bg-ok/25 text-ok' };
      case 'straight':
      default:
        return { Icon: ArrowUp, accentClass: 'bg-white/15 text-white' };
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

  /**
   * routeTime arrives as "2 min" and routeMeta as "120 m (mock)" or
   * "45 m | 2 floors". Split them so the number can carry the visual weight and
   * the unit / qualifier can sit quietly beside it.
   */
  const [etaValue, etaUnit] = useMemo(() => {
    const match = /^\s*([\d.,]+)\s*(.*)$/.exec(routeTime ?? '');
    return match ? [match[1], match[2]] : [routeTime || '—', ''];
  }, [routeTime]);

  const [metaText, metaNote] = useMemo(() => {
    const raw = (routeMeta ?? '').replace(/\s*\|\s*/g, ' · ');
    const match = /^(.*?)\s*\(([^)]+)\)\s*$/.exec(raw);
    return match ? [match[1], match[2]] : [raw, null];
  }, [routeMeta]);

  const destinationName = routeDestinationStore?.name || destination || 'Destination';
  const destinationFloor = routeDestinationStore?.floor || activeFloorLabel;

  const modeOptions: Array<{ mode: ViewMode; label: string; Icon: typeof MapPin; enabled: boolean }> = [
    { mode: 'ar', label: 'AR navigate', Icon: Layers, enabled: true },
    { mode: 'split', label: 'Split view', Icon: Layers, enabled: showSplitViewOption },
    { mode: 'map', label: 'Map only', Icon: MapPin, enabled: true },
  ];

  return (
    <div ref={splitContainerRef} className="relative flex h-full flex-col overflow-hidden bg-paper">
      {showModeMenu && (
        <div className="animate-fade-in glass pointer-events-auto absolute right-4 top-[calc(max(1rem,env(safe-area-inset-top))+3.75rem)] z-[75] w-48 rounded-[var(--radius-lg)] p-1.5 text-ink">
          <div className="eyebrow px-2.5 py-1.5">View mode</div>
          {modeOptions
            .filter((option) => option.enabled)
            .map(({ mode, label, Icon }) => (
              <button
                key={mode}
                type="button"
                onClick={() => handleSelectMode(mode)}
                aria-pressed={arViewMode === mode}
                className={`press flex w-full items-center gap-2.5 rounded-[var(--radius-sm)] px-2.5 py-2.5 text-left text-[14px] font-medium ${
                  arViewMode === mode ? 'bg-ink text-white' : 'text-ink-2 hover:bg-paper-2'
                }`}
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span>{label}</span>
              </button>
            ))}
        </div>
      )}

      {/* ---------------- Camera / AR pane ---------------- */}
      <div
        className={`relative w-full bg-black ${
          arViewMode === 'ar' ? 'h-full overflow-hidden' : arViewMode === 'map' ? 'hidden' : ''
        }`}
        style={cameraSectionStyle}
      >
        {cameraActive ? (
          arViewMode === 'ar' ? (
            <div className="relative h-full w-full overflow-hidden bg-black">
              <video ref={cameraVideoRef} autoPlay muted playsInline className="h-full w-full object-cover" />

              {guidance && (
                <div className="pointer-events-none absolute inset-0 z-10">
                  <ARFloorThreeOverlay
                    routePath={routePath}
                    livePosition={livePosition}
                    liveHeadingDeg={liveHeadingDeg}
                    transitionTarget={liveTransitionTarget}
                    enabled={cameraActive && arViewMode === 'ar'}
                    arWorld={liveArWorld}
                    videoRef={cameraVideoRef}
                    videoFit="cover"
                  />
                </div>
              )}
            </div>
          ) : (
            <video ref={cameraVideoRef} autoPlay muted playsInline className="h-full w-full object-cover" />
          )
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-neutral-900 px-6 text-center text-white/70">
            <div>
              <Camera className="mx-auto mb-3 h-9 w-9 opacity-50" strokeWidth={1.5} />
              <p className="text-[15px] font-semibold text-white/90">Camera unavailable</p>
              {cameraError && <p className="mt-2 max-w-[280px] text-[13px] text-white/60">{cameraError}</p>}
            </div>
          </div>
        )}

        <div className="absolute inset-x-0 top-0 z-20 px-4 pt-[max(1rem,env(safe-area-inset-top))]">
          <div className="flex items-start justify-between gap-3">
            <IconButton tone="dark" label="Exit navigation" onClick={resetToMap}>
              <X className="h-5 w-5" />
            </IconButton>

            {/* Turn instruction - the single most important thing on screen. */}
            <div className="glass-dark pointer-events-none flex min-w-0 flex-1 items-center gap-3 rounded-full px-4 py-2.5 text-white">
              <GuidanceIcon className="h-6 w-6 shrink-0" strokeWidth={2.5} />
              <span className="truncate text-[17px] font-semibold tracking-[-0.01em]">
                {guidance?.text ?? 'Follow route'}
              </span>
            </div>

            <div className="flex shrink-0 gap-2">
              <IconButton
                tone="dark"
                label={cameraActive ? 'Turn camera off' : 'Turn camera on'}
                onClick={toggleCamera}
              >
                {cameraActive ? <CameraOff className="h-5 w-5" /> : <Camera className="h-5 w-5" />}
              </IconButton>
              <IconButton tone="dark" label="View mode" onClick={toggleModeMenu} aria-expanded={showModeMenu}>
                <MapIcon className="h-5 w-5" />
              </IconButton>
            </div>
          </div>
        </div>

        {arViewMode === 'split' && (
          <div
            className="absolute bottom-[-6px] left-0 h-3 w-full cursor-row-resize bg-white/10"
            onPointerDown={startSplitDrag}
          />
        )}

          {arViewMode === 'ar' && !isLandscape && (
            <div className="pointer-events-none absolute inset-0 z-30 flex items-center justify-center p-6">
              <div className="glass-dark rounded-[var(--radius-lg)] px-5 py-4 text-center text-white">
                <p className="text-[15px] font-semibold">Rotate phone to landscape</p>
                <p className="mt-1 text-[13px] text-white/70">Localization will start after the screen is horizontal.</p>
              </div>
            </div>
          )}

        {arViewMode === 'ar' && cameraActive && isLandscape && (
          <div
            className="pointer-events-auto absolute z-30 overflow-hidden rounded-[var(--radius-lg)] border-2 border-ink-3/80 bg-paper/95 text-ink shadow-2xl"
            role="region"
            aria-label="Navigation map preview"
            style={{
              right: MAP_POPUP_MARGIN,
              top: 64,
              width: popupSize.width,
              height: popupSize.height,
            }}
          >
            <button
              type="button"
              className="block h-full w-full text-left"
              onClick={togglePopupSize}
              aria-label={`${popupExpanded ? 'Shrink' : 'Expand'} ${activeFloorLabel} map preview`}
            >
              <MapCanvas
                mapImageUrl={mapImageUrl}
                route={routePath}
                markers={mapMarkers}
                currentPose={currentPose}
                className="h-full w-full"
              />
            </button>
          </div>
        )}
      </div>

      {/* ---------------- Map pane ---------------- */}
      <div
        className={`relative w-full bg-paper ${
          arViewMode === 'map' ? 'h-full' : arViewMode === 'ar' ? 'hidden' : ''
        }`}
        style={arViewMode === 'split' ? { height: `${100 - splitCameraRatio * 100}%` } : undefined}
      >
        {arViewMode === 'map' && (
          <>
            <div className="pointer-events-none absolute inset-x-0 top-0 z-30 h-32 bg-gradient-to-b from-paper/90 to-transparent" />
            <div className="absolute inset-x-0 top-0 z-40 flex items-center gap-2.5 px-4 pt-[max(1rem,env(safe-area-inset-top))]">
              <IconButton label="Exit navigation" onClick={resetToMap}>
                <X className="h-5 w-5" />
              </IconButton>

              <div className="glass flex flex-1 items-center justify-center rounded-full px-4 py-2.5">
                <span className="truncate text-[14px] font-semibold text-ink">{activeFloorLabel}</span>
              </div>

              <IconButton label="View mode" onClick={toggleModeMenu} aria-expanded={showModeMenu}>
                <MapIcon className="h-5 w-5" />
              </IconButton>
            </div>
          </>
        )}

        {showRouteFloorStack && (
          <FloorRail
            floors={routeFloorSequence}
            activeFloorId={activeFloorId}
            onSelect={(floorId) => onSelectRouteFloor?.(floorId)}
          />
        )}

        <MapCanvas
          mapImageUrl={mapImageUrl}
          route={routePath}
          markers={mapMarkers}
          currentPose={currentPose}
          interactive
          className="h-full w-full"
        />

        {(liveMethod || liveTrackingMode) && (
          <div className="glass absolute bottom-4 left-4 z-20 rounded-full px-3 py-1.5 text-[11px] font-medium text-ink-2">
            {[liveMethod && `Method ${liveMethod}`, liveTrackingMode && `Track ${liveTrackingMode}`]
              .filter(Boolean)
              .join(' \u00b7 ')}
          </div>
        )}
      </div>

      {/* Standalone turn cue, map mode only - AR mode shows it in the top bar. */}
      {showStandaloneTurnCue ? (
        <div className="pointer-events-none absolute inset-x-0 top-[calc(max(1rem,env(safe-area-inset-top))+4.25rem)] z-40 flex justify-center px-4">
          <div className="glass-dark animate-fade-in inline-flex items-center gap-3 rounded-full py-2.5 pl-2.5 pr-5 text-white">
            <span
              className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full ${guidancePresentation.accentClass}`}
            >
              <GuidanceIcon className="h-6 w-6" strokeWidth={2.5} />
            </span>
            <span className="text-[16px] font-semibold leading-tight">{turnCueLabel}</span>
          </div>
        </div>
      ) : null}

      {/* Destination summary card. */}
      {arViewMode !== 'ar' && (
        <div
          className={`absolute inset-x-0 z-30 ${
            isLandscape ? 'bottom-2 px-3' : 'bottom-0 px-4 pb-[max(1rem,env(safe-area-inset-bottom))]'
          }`}
        >
          <div
            className={`glass flex items-center rounded-[var(--radius-lg)] ${
              isLandscape ? 'gap-3 p-2' : 'gap-3 p-2.5'
            }`}
          >
            {/* Logo tile, same treatment as the store detail sheet. */}
            <span
              className={`flex shrink-0 items-center justify-center overflow-hidden rounded-[var(--radius-sm)] border border-line-2 bg-surface-2 ${
                isLandscape ? 'h-10 w-10 text-lg' : 'h-10 w-10 text-[20px]'
              }`}
            >
              {routeDestinationStore?.logoSrc ? (
                <img src={routeDestinationStore.logoSrc} alt="" className="h-full w-full object-contain" />
              ) : (
                <span>{routeDestinationStore?.logo || '\u{1F4CD}'}</span>
              )}
            </span>

            <span className="min-w-0 flex-1">
              <span className="eyebrow block">Heading to</span>
              <span
                className={`mt-0.5 block truncate font-semibold tracking-[-0.01em] text-ink ${
                  isLandscape ? 'text-[14px]' : 'text-[15px]'
                }`}
              >
                {destinationName}
              </span>
              <span className={`block truncate text-ink-3 ${isLandscape ? 'text-[11px]' : 'text-[13px]'}`}>
                {destinationFloor}
              </span>
            </span>

            <span className={`w-px self-stretch bg-line ${isLandscape ? 'my-0.5' : 'my-1'}`} aria-hidden="true" />

            {/* ETA carries the weight; unit and distance stay quiet beside it. */}
            <span className={`shrink-0 text-right ${isLandscape ? 'pl-2 pr-1' : 'pl-3 pr-1.5'}`}>
              <span className="flex items-baseline justify-end gap-1">
                <span
                  className={`font-bold leading-none tracking-[-0.03em] text-ink ${
                    isLandscape ? 'text-[20px]' : 'text-[24px]'
                  }`}
                >
                  {etaValue}
                </span>
                {etaUnit ? (
                  <span className={`font-medium text-ink-3 ${isLandscape ? 'text-[11px]' : 'text-[13px]'}`}>
                    {etaUnit}
                  </span>
                ) : null}
              </span>

              <span
                className={`mt-1 flex items-center justify-end gap-1.5 ${
                  isLandscape ? 'text-[11px]' : 'text-[12px]'
                }`}
              >
                <span className="text-ink-3">{metaText}</span>
                {metaNote ? (
                  <span className="rounded-full bg-paper-2 px-1.5 py-px text-[10px] font-medium uppercase tracking-[0.04em] text-ink-4">
                    {metaNote}
                  </span>
                ) : null}
              </span>
            </span>
          </div>
        </div>
      )}

    </div>
  );
};

export default NavigationView;
