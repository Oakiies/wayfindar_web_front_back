import { Crosshair, FlaskConical, MapPin, Search } from 'lucide-react';
import React from 'react';
import MapCanvas from './MapCanvas';
import FloorRail from './ui/FloorRail';
import { type MapFrame } from '../lib/mapFrame';
import { type FloorInfo } from '../types/navigation';

interface MainMapViewProps {
  floors: FloorInfo[];
  selectedFloorId: string;
  mapImageUrl: string;
  mapFrame?: MapFrame | null;
  navGridDots: number[];
  openSearch: () => void;
  onSelectFloor: (floorId: string) => void;
  onOpenVideoTest: () => void;
  /** Label of the venue the user can focus on (null = nothing to focus). */
  focusLabel: string | null;
  focusActive: boolean;
  onToggleFocus: () => void;
  focusError: string | null;
}

const MainMapView: React.FC<MainMapViewProps> = ({
  floors,
  selectedFloorId,
  mapImageUrl,
  mapFrame,
  navGridDots,
  openSearch,
  onSelectFloor,
  onOpenVideoTest,
  focusLabel,
  focusActive,
  onToggleFocus,
  focusError,
}) => {
  const floorButtons = [...floors].sort((a, b) => b.order - a.order);
  return (
    <div className="relative h-full w-full overflow-hidden bg-paper">
      <div className="absolute inset-0">
        <MapCanvas mapImageUrl={mapImageUrl} mapFrame={mapFrame} className="h-full w-full" />
      </div>

      {/* Top: a single search affordance. Nothing else competes with it. */}
      <div className="pointer-events-auto absolute inset-x-4 top-[max(1rem,env(safe-area-inset-top))] z-30">
        <button
          type="button"
          onClick={openSearch}
          className="glass press tap flex w-full items-center gap-3 rounded-full px-5 text-left"
        >
          <Search className="h-[18px] w-[18px] shrink-0 text-ink-3" strokeWidth={2} aria-hidden="true" />
          <span className="flex-1 text-[15px] text-ink-3">Search destination</span>
        </button>
      </div>

      <div className="pointer-events-auto absolute right-4 top-[calc(max(1rem,env(safe-area-inset-top))+3.75rem)] z-30">
        <button
          type="button"
          onClick={onOpenVideoTest}
          className="glass press tap flex items-center gap-2 rounded-full px-4 py-2 text-[13px] font-semibold text-ink shadow-sm"
          aria-label="Open Test Localizer"
        >
          <FlaskConical className="h-4 w-4" strokeWidth={2} aria-hidden="true" />
          <span>Test Localizer</span>
        </button>
      </div>

      {focusLabel && (
        <div className="pointer-events-auto absolute right-4 top-[calc(max(1rem,env(safe-area-inset-top))+6.75rem)] z-30 flex flex-col items-end gap-1">
          <button
            type="button"
            onClick={onToggleFocus}
            aria-pressed={focusActive}
            className={`press tap flex items-center gap-2 rounded-full px-4 py-2 text-[13px] font-semibold shadow-sm ${
              focusActive ? 'bg-accent text-surface' : 'glass text-ink'
            }`}
          >
            <Crosshair className="h-4 w-4" strokeWidth={2} aria-hidden="true" />
            <span>{focusActive ? `Focused: ${focusLabel}` : `Focus ${focusLabel}`}</span>
          </button>
          {focusError && <span className="rounded-full bg-warn/15 px-3 py-1 text-[11px] text-ink-2">{focusError}</span>}
        </div>
      )}

      <FloorRail floors={floorButtons} activeFloorId={selectedFloorId} onSelect={onSelectFloor} />

      {/* Bottom tab bar. 44px targets, one shape language with the search pill. */}
      <div className="absolute inset-x-0 bottom-0 z-30 px-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
        <nav aria-label="Main" className="glass rounded-full p-1.5">
          <ul className="grid grid-cols-3 gap-1">
            <li className="contents">
              <button
                type="button"
                aria-current="page"
                className="press tap flex flex-col items-center justify-center gap-0.5 rounded-full py-1.5 text-ink"
              >
                <MapPin className="h-[22px] w-[22px]" strokeWidth={2} aria-hidden="true" />
                <span className="text-[11px] font-semibold tracking-[0.01em]">Map</span>
              </button>
            </li>
            <li className="contents">
              <button
                type="button"
                onClick={openSearch}
                className="press tap flex flex-col items-center justify-center gap-0.5 rounded-full py-1.5 text-ink-3 hover:text-ink"
              >
                <span className="grid h-[22px] w-[22px] grid-cols-3 place-content-center gap-1" aria-hidden="true">
                  {navGridDots.map((dot) => (
                    <span key={dot} className="h-1.5 w-1.5 rounded-full bg-current" />
                  ))}
                </span>
                <span className="text-[11px] font-semibold tracking-[0.01em]">Places</span>
              </button>
            </li>
            <li className="contents">
              <button
                type="button"
                onClick={onOpenVideoTest}
                className="press tap flex flex-col items-center justify-center gap-0.5 rounded-full py-1.5 text-ink-3 hover:text-ink"
                aria-label="Open video localization test"
              >
                <FlaskConical className="h-[22px] w-[22px]" strokeWidth={2} aria-hidden="true" />
                <span className="text-[11px] font-semibold tracking-[0.01em]">Localizer</span>
              </button>
            </li>
          </ul>
        </nav>
      </div>
    </div>
  );
};

export default MainMapView;
