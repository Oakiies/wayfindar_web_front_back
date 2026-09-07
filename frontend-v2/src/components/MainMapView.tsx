import { LayoutGrid, MapPin, Search } from 'lucide-react';
import React from 'react';
import MapCanvas from './MapCanvas';
import { type FloorInfo } from '../types/navigation';

interface MainMapViewProps {
  floors: FloorInfo[];
  selectedFloorId: string;
  mapImageUrl: string;
  navGridDots: number[];
  openSearch: () => void;
  onSelectFloor: (floorId: string) => void;
  onOpenVideoTest: () => void;
}

function floorButtonLabel(label: string): string {
  const compact = label.replace(/floor/gi, 'F').replace(/\s+/g, '');
  return compact || label;
}

const MainMapView: React.FC<MainMapViewProps> = ({
  floors,
  selectedFloorId,
  mapImageUrl,
  navGridDots,
  openSearch,
  onSelectFloor,
  onOpenVideoTest,
}) => {
  const floorButtons = [...floors].sort((a, b) => b.order - a.order);
  const showVideoTestButton = false;
  const selectedFloorLabel =
    floors.find((floor) => floor.id === selectedFloorId)?.label ?? 'the current floor';

  return (
    <div className="relative h-full w-full overflow-hidden bg-canvas text-ink-2">
      <div className="absolute inset-0">
        <MapCanvas
          mapImageUrl={mapImageUrl}
          className="h-full w-full"
          title={`Floor plan of ${selectedFloorLabel}`}
        />
      </div>

      {/* Floor rail — vertically centred so it stays reachable one-handed */}
      <nav
        aria-label="Floor"
        className="pointer-events-auto absolute right-3 top-1/2 z-20 flex -translate-y-1/2 flex-col"
      >
        <div className="glass flex flex-col items-center gap-1 rounded-full p-1.5">
          {floorButtons.map((floor) => {
            const active = floor.id === selectedFloorId;
            return (
              <button
                key={floor.id}
                type="button"
                onClick={() => onSelectFloor(floor.id)}
                aria-pressed={active}
                aria-label={floor.label}
                className={`press tap flex items-center justify-center rounded-full px-2 text-[13px] font-semibold ${
                  active
                    ? 'bg-ink text-white shadow-sm'
                    : 'text-ink-3 hover:bg-black/5 hover:text-ink'
                }`}
              >
                {floorButtonLabel(floor.label)}
              </button>
            );
          })}
        </div>
      </nav>

      {/* Search entry point. This is a button, not an input — so it carries no
          decorative clear affordance that would do nothing when tapped. */}
      <div className="pointer-events-auto absolute inset-x-4 top-[max(1rem,env(safe-area-inset-top))] z-20">
        <button
          type="button"
          onClick={openSearch}
          className="glass press tap flex w-full items-center gap-3 rounded-full px-5 text-left hover:bg-white/95"
        >
          <Search className="h-[18px] w-[18px] shrink-0 text-ink-3" strokeWidth={2} aria-hidden="true" />
          <span className="flex-1 text-[15px] text-ink-3">Search destination</span>
        </button>
      </div>

      {showVideoTestButton ? (
        <div className="pointer-events-auto absolute left-4 top-24 z-20">
          <button
            type="button"
            onClick={onOpenVideoTest}
            className="glass press tap rounded-xl px-3 text-[12px] font-semibold uppercase tracking-[0.08em] text-ink-2"
          >
            Test Video Localize
          </button>
        </div>
      ) : null}

      {/* Bottom tab bar — 2 destinations, both 44px+, current tab announced */}
      <div className="absolute inset-x-0 bottom-0 z-20 px-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
        <nav
          aria-label="Main"
          className="glass rounded-sheet px-4 py-2"
        >
          <ul className="grid grid-cols-2">
            <li className="contents">
              <button
                type="button"
                aria-current="page"
                className="press tap flex flex-col items-center justify-center gap-1 rounded-2xl py-1 text-accent-ink"
              >
                <MapPin className="h-6 w-6" aria-hidden="true" />
                <span className="text-[13px] font-semibold">Map</span>
              </button>
            </li>
            <li className="contents">
              <button
                type="button"
                onClick={openSearch}
                className="press tap flex flex-col items-center justify-center gap-1 rounded-2xl py-1 text-ink-3 hover:text-ink"
              >
                {navGridDots.length > 0 ? (
                  <span className="grid h-6 w-6 grid-cols-3 place-content-center gap-1" aria-hidden="true">
                    {navGridDots.map((dot) => (
                      <span key={dot} className="h-1.5 w-1.5 rounded-full bg-current" />
                    ))}
                  </span>
                ) : (
                  <LayoutGrid className="h-6 w-6" aria-hidden="true" />
                )}
                <span className="text-[13px] font-semibold">Places</span>
              </button>
            </li>
          </ul>
        </nav>
      </div>
    </div>
  );
};

export default MainMapView;
