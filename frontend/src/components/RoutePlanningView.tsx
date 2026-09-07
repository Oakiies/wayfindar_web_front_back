import { ArrowLeft, ArrowUpDown, Navigation, X } from 'lucide-react';
import React, { useEffect, useRef, useState } from 'react';
import MapCanvas from './MapCanvas';
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
          color: '#16a34a',
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
          color: '#ef4444',
          label: 'D',
          size: 8,
          variant: 'route' as const,
        }
      : null,
  ].filter((marker): marker is NonNullable<typeof marker> => marker !== null);

  const timeLabel = routeTime && routeTime.trim() ? routeTime : 'N/A';
  const metaLabel = routeMeta && routeMeta.trim() ? routeMeta : 'distance unavailable';
  const floorBadge = toFloorBadge(activeFloorLabel);

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
    <div
      className="relative flex h-full flex-col overflow-hidden bg-[#ececec]"
      style={{ fontFamily: "'Helvetica Neue', Helvetica, Arial, sans-serif" }}
    >
      <div className="relative h-full overflow-hidden bg-[linear-gradient(155deg,#ececec_0%,#e7e7e7_100%)]">
        <MapCanvas mapImageUrl={mapImageUrl} route={routePath} markers={markers} className="h-full w-full" />

        <div className="pointer-events-none absolute inset-x-0 top-0 z-[2] h-56 bg-[linear-gradient(to_bottom,rgba(247,245,242,0)_0%,transparent_100%)]" />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-[2] h-36 bg-[linear-gradient(to_top,#ececec_0%,transparent_100%)]" />

        <div className="absolute inset-x-0 top-0 z-20 flex items-center justify-between px-4 pt-4">
          <button
            onClick={backToStore}
            className="flex h-[38px] w-[38px] items-center justify-center rounded-full text-[#666] transition active:scale-95"
            style={{ background: 'rgba(255,255,255,.88)', border: '0.5px solid rgba(0,0,0,.08)' }}
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          <button
            onClick={resetToMap}
            className="flex h-[38px] w-[38px] items-center justify-center rounded-full text-[#666] transition active:scale-95"
            style={{ background: 'rgba(255,255,255,.88)', border: '0.5px solid rgba(0,0,0,.08)' }}
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>

        <div
          className="absolute left-4 right-4 top-[68px] z-20 flex items-center gap-3 rounded-[20px] p-4"
          style={{ background: 'rgba(255,255,255,.95)', border: '0.5px solid rgba(0,0,0,.07)' }}
        >
          <div className="flex flex-shrink-0 flex-col items-center">
            <div className="h-[10px] w-[10px] rounded-full border-2 border-[#b0aa9e] bg-[#efefef]" />
            <div className="my-[3px] h-8 w-[1.5px] bg-[#e8e4de]" />
            <div className="h-[10px] w-[10px] rounded-full bg-[#1c1c1c]" />
          </div>

          <div className="min-w-0 flex-1 space-y-1.5">
            <button
              onClick={() => openSearch('route-origin')}
              className="w-full truncate rounded-[10px] border border-[rgba(0,0,0,.06)] bg-[#efefef] px-3 py-2 text-left text-[13px] font-medium text-[#333] transition hover:bg-[#e9e9e9]"
            >
              {origin || 'My location'}
            </button>
            <button
              onClick={() => openSearch('route-destination')}
              className="w-full truncate rounded-[10px] border border-[rgba(0,0,0,.06)] bg-[#efefef] px-3 py-2 text-left text-[13px] font-medium text-[#333] transition hover:bg-[#e9e9e9]"
            >
              {destination || routeDestinationStore?.name || 'Select destination'}
            </button>
          </div>

          <button
            onClick={swapRoutePoints}
            className="flex h-[34px] w-[34px] flex-shrink-0 items-center justify-center rounded-full border border-[rgba(0,0,0,.06)] bg-[#efefef] text-[#b0aa9e] transition hover:bg-[#e9e9e9] hover:text-[#666]"
          >
            <ArrowUpDown className="h-4 w-4" />
          </button>
        </div>

        <div
          className="absolute bottom-[18px] right-4 z-20 rounded-[8px] px-[10px] py-[5px] text-[11px] font-semibold tracking-[0.08em] text-[#555]"
          style={{ background: 'rgba(255,255,255,.9)', border: '0.5px solid rgba(0,0,0,.09)' }}
        >
          {floorBadge}
        </div>
      </div>

      <div
        ref={sheetRef}
        className="absolute inset-x-0 bottom-0 z-30"
        style={{
          transform: `translateY(${sheetOffsetY}px)`,
          transition: sheetDragging ? 'none' : 'transform 180ms ease-out',
        }}
      >
        <div className="pointer-events-none absolute inset-0 bg-[#f7f7f6]" />

        <div className="relative flex flex-shrink-0 flex-col rounded-t-3xl border-t border-[#ece9e4] bg-[#f7f7f6] px-[18px] pb-[max(10px,env(safe-area-inset-bottom))] pt-[14px]">
          <div
            onPointerDown={startSheetDrag}
            className="mx-auto mb-[14px] h-1 w-9 cursor-grab touch-none rounded-full bg-[#e0ddd8] active:cursor-grabbing"
          />
          <div className="mb-4 text-center">
            <div className="text-[40px] font-bold leading-none tracking-[-0.04em] text-[#1a1a1a]">{timeLabel}</div>
            <div className="mt-1 text-xs tracking-[0.02em] text-[#b0aa9e]">{metaLabel} · estimated walking time</div>
          </div>

          <div
            className="mb-4 rounded-[14px] p-3.5"
            style={{ background: '#f7f7f6', border: '0.5px solid rgba(0,0,0,.03)' }}
          >
            <div className="mb-1.5 flex items-start justify-between">
              <span className="flex items-center gap-1 text-[10px] uppercase tracking-[0.08em] text-[#c0bab2]">
                <Navigation className="h-2.5 w-2.5" />
                From
              </span>
              <span className="text-[10px] uppercase tracking-[0.08em] text-[#c0bab2]">To</span>
            </div>

            <div className="flex items-end justify-between gap-2">
              <span className="max-w-[45%] truncate text-[13px] font-medium text-[#888]">{origin || 'My location'}</span>
              <span className="text-sm text-[#d0ccc6]">→</span>
              <span className="max-w-[50%] truncate text-right text-sm font-semibold text-[#1a1a1a]">
                {destination || routeDestinationStore?.name || 'Destination'}
              </span>
            </div>
          </div>

          <div className="mt-auto flex gap-2">
            <button
              onClick={resetToMap}
              className="h-[50px] flex-1 rounded-[14px] border border-[rgba(0,0,0,.03)] bg-[#f7f7f6] text-sm font-semibold text-[#888] transition hover:bg-[#f1f1ef]"
            >
              Cancel
            </button>
            <button
              onClick={handleConfirmRoute}
              className="flex h-[50px] flex-[1.4] items-center justify-center gap-2 rounded-[14px] bg-[#1c1c1c] text-sm font-semibold text-white transition hover:bg-[#333]"
            >
              <Navigation className="h-3.5 w-3.5" />
              Start
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default RoutePlanningView;
