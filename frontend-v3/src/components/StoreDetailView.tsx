import { ArrowLeft, Heart, MapPin, Navigation, Search } from 'lucide-react';
import React, { useState } from 'react';
import MapCanvas from './MapCanvas';
import BottomSheet from './ui/BottomSheet';
import IconButton from './ui/IconButton';
import { shortFloorLabel } from '../lib/floorLabel';
import { type MapFrame } from '../lib/mapFrame';
import { type Store } from '../types/navigation';

interface StoreDetailViewProps {
  selectedStore: Store;
  mapImageUrl: string;
  mapFrame?: MapFrame | null;
  openSearch: () => void;
  resetToMap: () => void;
  handleStartRoute: () => void;
}

const StoreDetailView: React.FC<StoreDetailViewProps> = ({
  selectedStore,
  mapImageUrl,
  mapFrame,
  openSearch,
  resetToMap,
  handleStartRoute,
}) => {
  const [saved, setSaved] = useState(false);

  return (
    <div className="relative h-full w-full overflow-hidden bg-paper">
      <div className="absolute inset-0 z-0 overflow-hidden">
        <MapCanvas
          mapImageUrl={mapImageUrl}
          mapFrame={mapFrame}
          markers={[
            {
              id: selectedStore.id,
              x: selectedStore.x,
              y: selectedStore.y,
              size: 16,
              variant: 'destination' as const,
            },
          ]}
          focus={{ x: selectedStore.x, y: selectedStore.y, zoom: 3, yBias: 0.2 }}
          interactive
          className="h-full w-full"
        />
      </div>

      {/* Scrim keeps the floating controls legible over a busy floor plan. */}
      <div className="pointer-events-none absolute inset-x-0 top-0 z-[1] h-32 bg-gradient-to-b from-paper/90 to-transparent" />

      <div className="absolute inset-x-0 top-0 z-20 flex items-center gap-2.5 px-4 pt-[max(1rem,env(safe-area-inset-top))]">
        <IconButton label="Back to map" onClick={resetToMap}>
          <ArrowLeft className="h-[18px] w-[18px]" />
        </IconButton>

        {/* The header used to carry a back arrow and an X that both went back.
            One way out is enough; the freed space goes to search. */}
        <button
          type="button"
          onClick={openSearch}
          className="glass press tap flex flex-1 items-center gap-2.5 rounded-full px-4 text-left text-[14px] text-ink-3"
        >
          <Search className="h-4 w-4 shrink-0" />
          <span>Find places</span>
        </button>

        <span className="glass flex h-11 items-center rounded-full px-3.5 text-[13px] font-semibold text-ink-2">
          {shortFloorLabel(selectedStore.floor)}
        </span>
      </div>

      <BottomSheet peekHeight={96}>
        <div className="flex items-start gap-3.5">
          <div className="flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-[var(--radius-md)] border border-line-2 bg-surface-2 text-2xl">
            {selectedStore.logoSrc ? (
              <img src={selectedStore.logoSrc} alt="" className="h-full w-full object-contain" />
            ) : (
              <span>{selectedStore.logo}</span>
            )}
          </div>

          <div className="min-w-0 flex-1">
            <h2 className="truncate text-[21px] font-semibold leading-tight tracking-[-0.02em] text-ink">
              {selectedStore.name}
            </h2>
            <p className="mt-1 text-[13px] text-ink-3">
              {selectedStore.category} · {selectedStore.floor}
            </p>
          </div>

          <button
            type="button"
            onClick={() => setSaved((state) => !state)}
            aria-pressed={saved}
            aria-label={saved ? 'Remove from saved' : 'Save place'}
            className={`press flex h-10 w-10 shrink-0 items-center justify-center rounded-full border ${
              saved ? 'border-accent/30 bg-accent-soft text-accent' : 'border-line bg-surface-2 text-ink-4'
            }`}
          >
            <Heart className={`h-[17px] w-[17px] ${saved ? 'fill-current' : ''}`} />
          </button>
        </div>

        {selectedStore.address ? (
          <p className="mt-4 flex items-start gap-2.5 border-t border-line-2 pt-4 text-[13px] text-ink-2">
            <MapPin className="mt-px h-4 w-4 shrink-0 text-ink-4" aria-label="Address" />
            <span>{selectedStore.address}</span>
          </p>
        ) : null}

        <button type="button" onClick={handleStartRoute} className="btn-primary press mt-5 w-full">
          <Navigation className="h-[17px] w-[17px]" />
          Navigate
        </button>
      </BottomSheet>
    </div>
  );
};

export default StoreDetailView;
