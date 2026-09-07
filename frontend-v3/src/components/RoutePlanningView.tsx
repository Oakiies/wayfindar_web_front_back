import { ArrowLeft, ArrowUpDown, Navigation } from 'lucide-react';
import React from 'react';
import MapCanvas from './MapCanvas';
import BottomSheet from './ui/BottomSheet';
import IconButton from './ui/IconButton';
import { shortFloorLabel } from '../lib/floorLabel';
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
  const markers = [
    originPoint
      ? { id: 'origin', x: originPoint.x, y: originPoint.y, size: 8, variant: 'origin' as const }
      : null,
    destinationPoint
      ? {
          id: 'destination',
          x: destinationPoint.x,
          y: destinationPoint.y,
          size: 12,
          variant: 'destination' as const,
        }
      : null,
  ].filter((marker): marker is NonNullable<typeof marker> => marker !== null);

  const [etaValue, etaUnit] = (() => {
    const match = /^\s*([\d.,]+)\s*(.*)$/.exec(routeTime ?? '');
    return match ? [match[1], match[2]] : [routeTime?.trim() || '—', ''];
  })();

  const [metaText, metaNote] = (() => {
    const raw = (routeMeta ?? '').replace(/\s*\|\s*/g, ' · ').trim();
    if (!raw) {
      return ['Distance unavailable', null];
    }
    const match = /^(.*?)\s*\(([^)]+)\)\s*$/.exec(raw);
    return match ? [match[1], match[2]] : [raw, null];
  })();
  const originLabel = origin || 'My location';
  const destinationLabel = destination || routeDestinationStore?.name || 'Select destination';

  return (
    <div className="relative flex h-full flex-col overflow-hidden bg-paper">
      <div className="relative h-full overflow-hidden">
        <MapCanvas mapImageUrl={mapImageUrl} route={routePath} markers={markers} interactive className="h-full w-full" />

        <div className="pointer-events-none absolute inset-x-0 top-0 z-[2] h-52 bg-gradient-to-b from-paper/90 to-transparent" />

        <div className="absolute inset-x-0 top-0 z-20 px-4 pt-[max(1rem,env(safe-area-inset-top))]">
          <div className="flex items-center gap-2.5">
            <IconButton label="Back" onClick={backToStore}>
              <ArrowLeft className="h-[18px] w-[18px]" />
            </IconButton>
            <span className="text-[15px] font-semibold tracking-[-0.01em] text-ink">Route</span>
            <span className="ml-auto glass flex h-11 items-center rounded-full px-3.5 text-[13px] font-semibold text-ink-2">
              {shortFloorLabel(activeFloorLabel)}
            </span>
          </div>

          {/* From / To card: the rail on the left mirrors how the route is drawn
              on the map — hollow dot for start, solid for destination. */}
          <div className="glass mt-3 flex items-center gap-3 rounded-[var(--radius-lg)] p-3.5">
            <div className="flex shrink-0 flex-col items-center pt-1">
              <span className="h-2.5 w-2.5 rounded-full border-2 border-ink-3 bg-surface" />
              <span className="my-1 h-7 w-px bg-line" />
              <span className="h-2.5 w-2.5 rounded-full bg-ink" />
            </div>

            <div className="min-w-0 flex-1 space-y-1.5">
              <button type="button" onClick={() => openSearch('route-origin')} className="field press truncate">
                {originLabel}
              </button>
              <button type="button" onClick={() => openSearch('route-destination')} className="field press truncate">
                {destinationLabel}
              </button>
            </div>

            <button
              type="button"
              onClick={swapRoutePoints}
              aria-label="Swap start and destination"
              className="press flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-line bg-surface-2 text-ink-3 hover:text-ink"
            >
              <ArrowUpDown className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      <BottomSheet peekHeight={100}>
        {/* The From / To card at the top already names both ends of the route,
            so the sheet gives the whole width to the estimate. */}
        <div className="pb-1 pt-1 text-center">
          <div className="flex items-baseline justify-center gap-1.5">
            <span className="text-[46px] font-bold leading-none tracking-[-0.045em] text-ink">{etaValue}</span>
            {etaUnit ? <span className="text-[18px] font-medium text-ink-3">{etaUnit}</span> : null}
          </div>

          <div className="mt-2.5 flex items-center justify-center gap-1.5 text-[13px] text-ink-3">
            <span>{metaText}</span>
            <span className="text-ink-4">·</span>
            <span>walking</span>
            {metaNote ? (
              <span className="rounded-full bg-paper-2 px-1.5 py-px text-[10px] font-medium uppercase tracking-[0.04em] text-ink-4">
                {metaNote}
              </span>
            ) : null}
          </div>
        </div>

        <div className="mt-5 flex gap-2.5">
          <button type="button" onClick={resetToMap} className="btn-secondary press flex-1">
            Cancel
          </button>
          <button type="button" onClick={handleConfirmRoute} className="btn-primary press flex-[1.6]">
            <Navigation className="h-[17px] w-[17px]" />
            Start
          </button>
        </div>
      </BottomSheet>
    </div>
  );
};

export default RoutePlanningView;
