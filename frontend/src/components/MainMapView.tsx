import { MapPin, Search, X } from 'lucide-react';
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

  return (
    <div className="relative h-full w-full overflow-hidden bg-[#ececec] text-[#8a7d6e]">
      <div className="absolute inset-0">
        <MapCanvas mapImageUrl={mapImageUrl} className="h-full w-full" />
      </div>

      <div className="pointer-events-auto absolute right-3.5 top-1/2 z-20 flex -translate-y-1/2 transform flex-col gap-4">
        <div className="flex flex-col items-center gap-0.5 rounded-full border border-[#e0ddd8] bg-white/95 px-1.5 py-1.5 shadow-[0_2px_10px_rgba(0,0,0,0.05)] backdrop-blur">
          {floorButtons.map((floor) => {
            const active = floor.id === selectedFloorId;
            return (
              <button
                key={floor.id}
                type="button"
                onClick={() => onSelectFloor(floor.id)}
                className={`flex h-9 w-9 items-center justify-center rounded-full border border-transparent text-[11px] font-semibold transition-all duration-150 ${
                  active
                    ? 'border-[#d6cdbf] bg-[#e8e0d5] text-[#7a6e62]'
                    : 'text-[#c8c4be] hover:bg-[#f5f2ee] hover:text-[#888]'
                }`}
                title={floor.label}
              >
                {floorButtonLabel(floor.label)}
              </button>
            );
          })}
        </div>
      </div>

      <div className="pointer-events-auto absolute left-4 right-4 top-4 z-20">
        <button
          type="button"
          onClick={openSearch}
          className="flex w-full items-center gap-3 rounded-full border border-[#e0ddd8] bg-white px-4 py-[11px] shadow-[0_2px_12px_rgba(0,0,0,0.05)] transition-colors hover:bg-[#fcfbf9]"
        >
          <Search className="h-[18px] w-[18px] text-[#c8c4be]" strokeWidth={2} />
          <span className="flex-1 text-left text-[13px] text-[#c8c4be]">Search destination...</span>
          <X className="h-4 w-4 text-[#ddd]" strokeWidth={2} />
        </button>
      </div>

      {showVideoTestButton ? (
        <div className="pointer-events-auto absolute left-4 top-20 z-20">
          <button
            type="button"
            onClick={onOpenVideoTest}
            className="rounded-lg border border-[#e0ddd8] bg-white px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-[#a09c96] shadow-[0_1px_6px_rgba(0,0,0,0.04)] transition-colors hover:bg-[#fcfbf9] hover:text-[#8a7d6e]"
          >
            Test Video Localize
          </button>
        </div>
      ) : null}

      <div className="absolute bottom-0 left-0 right-0 space-y-3 px-4 pb-4">
        <div className="rounded-[28px] bg-white/95 px-6 py-4 text-gray-800 shadow-lg backdrop-blur">
          <div className="grid grid-cols-2 gap-6 text-center">
            <button type="button" className="flex flex-col items-center gap-2">
              <MapPin className="h-6 w-6" />
              <span className="text-sm font-semibold">Map</span>
            </button>
            <button
              type="button"
              className="flex flex-col items-center gap-2 text-gray-600"
              onClick={openSearch}
            >
              <div className="grid h-7 w-7 grid-cols-3 gap-1">
                {navGridDots.map((dot) => (
                  <div key={dot} className="h-1.5 w-1.5 rounded-full bg-current"></div>
                ))}
              </div>
              <span className="text-sm font-semibold">Places</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default MainMapView;
