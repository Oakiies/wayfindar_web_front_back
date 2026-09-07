import { ArrowLeft, ArrowUpDown, Navigation, X } from 'lucide-react';
import React, { useEffect, useRef, useState } from 'react';
import MapCanvas, { MAP_MARKER_COLORS } from './MapCanvas';
import { type MapPoint, type Store } from '../types/navigation';

export type SearchContext = 'map' | 'route-origin' | 'route-destination';

interface RoutePlanningViewProps {
  origin: string;
  destination: string;
  routeDestinationStore: Store | null;
  routeTime: string;
  routeMeta: string;
  mapImageUrl: string;
  activeFloorLabel: string;
  routePath: MapPoint[];
  originPoint: MapPoint | null;
  destinationPoint: MapPoint | null;
  openSearch: (ctx: SearchContext) => void;
  swapRoutePoints: () => void;
  handleConfirmRoute: () => void;
  backToStore: () => void;
  resetToMap: () => void;
}

function toFloorBadge(label: string): string {
  const raw = String(label || '').trim();
  if (!raw) {
    return '-';
  }
  const compact = raw.replace(/floor/gi, 'F').replace(/\s+/g, ' ').trim();
  return compact;
}

function clampValue(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

const RoutePlanningView: React.FC<RoutePlanningViewProps> = ({
  origin,
  destination,
  routeDestinationStore,
  routeTime,
  routeMeta,
  mapImageUrl,
  activeFloorLabel,
  routePath,
  originPoint,
  destinationPoint,
  openSearch,
  swapRoutePoints,
  handleConfirmRoute,
  backToStore,
  resetToMap,
}) => {
  const sheetRef = useRef<HTMLDivElement | null>(null);
  const sheetMaxOffsetRef = useRef(220);
  const [sheetOffsetY, setSheetOffsetY] = useState(0);
  const [sheetDragging, setSheetDragging] = useState(false);

  const markers = [
    originPoint
      ? {
          id: 'origin',
          x: originPoint.x,
          y: originPoint.y,
          color: MAP_MARKER_COLORS.origin,
          label: 'S',
          size: 8,
          variant: 'route' as const,
        }
      : null,
    destinationPoint
      ? {
          id: 'destination',
          x: destinationPoint.x,
          y: destinationPoint.y,
          color: MAP_MARKER_COLORS.destination,
          label: 'D',
          size: 8,
          variant: 'route' as const,
        }
      : null,
  ].filter((marker): marker is NonNullable<typeof marker> => marker !== null);

  const timeLabel = routeTime && routeTime.trim() ? routeTime : 'N/A';
  const metaLabel = routeMeta && routeMeta.trim() ? routeMeta : 'distance unavailable';
  const floorBadge = toFloorBadge(activeFloorLabel);
  const originLabel = origin || 'My location';
  const destinationLabel = destination || routeDestinationStore?.name || 'Select destination';
  const hasDestination = Boolean(destination || routeDestinationStore?.name);

  useEffect(() => {
    const updateMaxOffset = () => {
      if (!sheetRef.current) {
        return;
      }
      const sheetHeight = sheetRef.current.getBoundingClientRect().height;
      const nextMaxOffset = Math.max(0, sheetHeight - 90);
      sheetMaxOffsetRef.current = nextMaxOffset;
      setSheetOffsetY((previous) => clampValue(previous, 0, nextMaxOffset));
    };

    updateMaxOffset();
    window.addEventListener('resize', updateMaxOffset);
    return () => window.removeEventListener('resize', updateMaxOffset);
  }, []);

  const startSheetDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    const startY = event.clientY;
    const startOffset = sheetOffsetY;
    setSheetDragging(true);

    const handleMove = (moveEvent: PointerEvent) => {
      const deltaY = moveEvent.clientY - startY;
      setSheetOffsetY(clampValue(startOffset + deltaY, 0, sheetMaxOffsetRef.current));
    };

    const handleUp = () => {
      window.removeEventListener('pointermove', handleMove);
      window.removeEventListener('pointerup', handleUp);
      setSheetDragging(false);
      setSheetOffsetY((current) => {
        if (current < 36) {
          return 0;
        }
        if (sheetMaxOffsetRef.current - current < 36) {
          return sheetMaxOffsetRef.current;
        }
        return current;
      });
    };

    window.addEventListener('pointermove', handleMove);
    window.addEventListener('pointerup', handleUp);
  };

  return (
    <div className="relative flex h-full flex-col overflow-hidden bg-canvas">
      <div className="relative h-full overflow-hidden bg-canvas">
        <MapCanvas
          mapImageUrl={mapImageUrl}
          route={routePath}
          markers={markers}
          title={`Route from ${originLabel} to ${destinationLabel} on ${activeFloorLabel}`}
          className="h-full w-full"
        />

        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 top-0 z-[2] h-64 bg-gradient-to-b from-canvas/90 to-transparent"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 bottom-0 z-[2] h-36 bg-gradient-to-t from-canvas to-transparent"
        />

        <div className="absolute inset-x-0 top-0 z-20 flex items-center justify-between px-4 pt-[max(1rem,env(safe-area-inset-top))]">
          <button
            type="button"
            onClick={backToStore}
            aria-label="Back to place details"
            className="glass press tap flex items-center justify-center rounded-full text-ink-2"
          >
            <ArrowLeft className="h-[18px] w-[18px]" aria-hidden="true" />
          </button>
          <button
            type="button"
            onClick={resetToMap}
            aria-label="Cancel and return to map"
            className="glass press tap flex items-center justify-center rounded-full text-ink-2"
          >
            <X className="h-[18px] w-[18px]" aria-hidden="true" />
          </button>
        </div>

        {/* Origin / destination picker. Both fields carry a visible label โ€”
            a placeholder alone disappears the moment a value is set. */}
        <div className="glass absolute inset-x-4 top-[calc(max(1rem,env(safe-area-inset-top))_+_56px)] z-20 flex items-center gap-3 rounded-card p-3.5">
          <div className="flex shrink-0 flex-col items-center pt-6" aria-hidden="true">
            <span className="h-2.5 w-2.5 rounded-full border-2 border-origin bg-surface" />
            <span className="my-1 h-9 w-0.5 rounded-full bg-line" />
            <span className="h-2.5 w-2.5 rounded-full bg-dest" />
          </div>

          <div className="min-w-0 flex-1 space-y-2">
            <div>
              <span id="route-from-label" className="mb-1 block text-[12px] font-semibold uppercase tracking-[0.08em] text-ink-3">
                From
              </span>
              <button
                type="button"
                onClick={() => openSearch('route-origin')}
                aria-labelledby="route-from-label route-from-value"
                className="press flex min-h-[44px] w-full items-center rounded-field border border-line bg-surface px-3 text-left hover:border-ink-3"
              >
                <span id="route-from-value" className="truncate text-[15px] font-medium text-ink">
                  {originLabel}
                </span>
              </button>
            </div>

            <div>
              <span id="route-to-label" className="mb-1 block text-[12px] font-semibold uppercase tracking-[0.08em] text-ink-3">
                To
              </span>
              <button
                type="button"
                onClick={() => openSearch('route-destination')}
                aria-labelledby="route-to-label route-to-value"
                className="press flex min-h-[44px] w-full items-center rounded-field border border-line bg-surface px-3 text-left hover:border-ink-3"
              >
                <span
                  id="route-to-value"
                  className={`truncate text-[15px] font-medium ${hasDestination ? 'text-ink' : 'text-ink-3'}`}
                >
                  {destinationLabel}
                </span>
              </button>
            </div>
          </div>

          <button
            type="button"
            onClick={swapRoutePoints}
            aria-label="Swap start and destination"
            className="press tap flex shrink-0 items-center justify-center rounded-full border border-line bg-sunken text-ink-2 hover:border-ink-3 hover:text-ink"
          >
            <ArrowUpDown className="h-[18px] w-[18px]" aria-hidden="true" />
          </button>
        </div>

        <div className="glass absolute bottom-5 right-4 z-20 rounded-lg px-3 py-1.5 text-[12px] font-semibold tracking-wide text-ink">
          {floorBadge}
        </div>
      </div>

      <div
        ref={sheetRef}
        className="absolute inset-x-0 bottom-0 z-30"
        style={{
          transform: `translateY(${sheetOffsetY}px)`,
          transition: sheetDragging ? 'none' : 'transform 200ms var(--ease-out-soft)',
        }}
      >
        <div className="rounded-t-sheet relative flex shrink-0 flex-col border-t border-line-soft bg-elevated px-[18px] pb-[max(1rem,env(safe-area-inset-bottom))] pt-3.5 shadow-sheet">
          <div
            onPointerDown={startSheetDrag}
            role="separator"
            aria-label="Drag to resize route summary"
            className="mx-auto mb-4 h-1.5 w-10 cursor-grab touch-none rounded-full bg-line active:cursor-grabbing"
          />

          {/* The estimate is the one number people came here for, so it gets
              the largest type on the screen. aria-live announces recalcs. */}
          <div className="mb-5 text-center" aria-live="polite">
            <p className="text-[44px] font-bold leading-none tracking-[-0.04em] text-ink">{timeLabel}</p>
            <p className="mt-2 text-[13px] text-ink-2">{metaLabel} ยท estimated walking time</p>
          </div>

          <div className="flex gap-2.5">
            <button
              type="button"
              onClick={resetToMap}
              className="press h-[52px] flex-1 rounded-[14px] border border-line bg-surface text-[15px] font-semibold text-ink-2 hover:bg-sunken hover:text-ink"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleConfirmRoute}
              className="press flex h-[52px] flex-[1.4] items-center justify-center gap-2 rounded-[14px] bg-ink text-[15px] font-semibold text-white hover:bg-ink-2"
            >
              <Navigation className="h-[18px] w-[18px]" aria-hidden="true" />
              Start
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default RoutePlanningView;
