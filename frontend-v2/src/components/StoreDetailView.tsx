import { ArrowLeft, Heart, MapPin, Navigation, Search } from 'lucide-react';
import React, { useEffect, useRef, useState } from 'react';
import MapCanvas, { MAP_MARKER_COLORS } from './MapCanvas';
import { type Store } from '../types/navigation';

interface StoreDetailViewProps {
  selectedStore: Store;
  mapImageUrl: string;
  openSearch: () => void;
  resetToMap: () => void;
  handleStartRoute: () => void;
}

function clampValue(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

const StoreDetailView: React.FC<StoreDetailViewProps> = ({
  selectedStore,
  mapImageUrl,
  openSearch,
  resetToMap,
  handleStartRoute,
}) => {
  const [saved, setSaved] = useState(false);
  const sheetRef = useRef<HTMLDivElement | null>(null);
  const sheetMaxOffsetRef = useRef(260);
  const [sheetOffsetY, setSheetOffsetY] = useState(0);
  const [sheetDragging, setSheetDragging] = useState(false);
  const floorShort = selectedStore.floor.replace('Floor ', 'F');
  const mapShiftPercent = Math.max(10, Math.min(38, (selectedStore.y / 500) * 42 - 6));

  useEffect(() => {
    const updateMaxOffset = () => {
      if (!sheetRef.current) {
        return;
      }
      const sheetHeight = sheetRef.current.getBoundingClientRect().height;
      const nextMaxOffset = Math.max(0, sheetHeight - 88);
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
    <div className="relative h-full w-full overflow-hidden bg-canvas">
      <div className="absolute inset-0 z-0 overflow-hidden">
        <div
          className="absolute inset-0"
          style={{ transform: `translateY(-${mapShiftPercent}%)`, transformOrigin: '50% 0%' }}
        >
          <MapCanvas
            mapImageUrl={mapImageUrl}
            title={`${selectedStore.name} on ${selectedStore.floor}`}
            markers={[
              {
                id: selectedStore.id,
                x: selectedStore.x,
                y: selectedStore.y,
                color: MAP_MARKER_COLORS.destination,
                size: 10,
                label: 'D',
                variant: 'route' as const,
              },
            ]}
            className="h-full w-full"
          />
        </div>
      </div>

      {/* Scrims: give the floating chrome a predictable background to sit on
          so its text keeps contrast whatever the floor plan looks like. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 z-[1] h-32 bg-gradient-to-b from-canvas/95 to-transparent"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 bottom-0 z-[1] h-1/2 bg-gradient-to-t from-elevated to-transparent"
      />

      <div className="absolute inset-x-0 top-0 z-10 flex items-center gap-2 px-4 pt-[max(1rem,env(safe-area-inset-top))]">
        <button
          type="button"
          onClick={resetToMap}
          aria-label="Back to map"
          className="glass press tap flex shrink-0 items-center justify-center rounded-full text-ink-2"
        >
          <ArrowLeft className="h-[18px] w-[18px]" aria-hidden="true" />
        </button>

        <button
          type="button"
          onClick={openSearch}
          className="glass press tap flex flex-1 items-center gap-2.5 rounded-full px-4 text-left text-ink-3"
        >
          <Search className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span className="truncate text-[15px]">Find places</span>
        </button>

        <span className="glass flex h-11 shrink-0 items-center rounded-full px-3.5 text-[13px] font-semibold tracking-wide text-ink">
          {floorShort}
        </span>
      </div>

      <div
        ref={sheetRef}
        className="rounded-t-sheet absolute inset-x-0 bottom-0 z-20 border-t border-line-soft bg-elevated px-[18px] pb-[max(1.5rem,env(safe-area-inset-bottom))] pt-3.5 shadow-sheet"
        style={{
          transform: `translateY(${sheetOffsetY}px)`,
          transition: sheetDragging ? 'none' : 'transform 200ms var(--ease-out-soft)',
        }}
      >
        <div
          onPointerDown={startSheetDrag}
          role="separator"
          aria-label="Drag to resize details"
          className="mx-auto mb-4 h-1.5 w-10 cursor-grab touch-none rounded-full bg-line active:cursor-grabbing"
        />

        <div className="mb-4 flex items-start gap-3">
          <div className="flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-2xl border border-line-soft bg-sunken text-2xl">
            {selectedStore.logoSrc ? (
              <img src={selectedStore.logoSrc} alt="" className="h-full w-full object-contain" />
            ) : (
              <span aria-hidden="true">{selectedStore.logo}</span>
            )}
          </div>

          <div className="min-w-0 flex-1">
            <h2 className="truncate text-[21px] font-bold leading-tight tracking-tight text-ink">
              {selectedStore.name}
            </h2>
            <p className="mt-1 flex items-center gap-1.5 text-[13px] text-ink-2">
              <MapPin className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              <span className="truncate">
                {selectedStore.category} · {selectedStore.floor}
              </span>
            </p>
          </div>

          <button
            type="button"
            onClick={() => setSaved((state) => !state)}
            aria-pressed={saved}
            aria-label={saved ? 'Remove from saved places' : 'Save this place'}
            className={`press tap flex shrink-0 items-center justify-center rounded-full border ${
              saved
                ? 'border-accent-line bg-accent-soft text-accent-ink'
                : 'border-line-soft bg-sunken text-ink-3 hover:text-ink-2'
            }`}
          >
            <Heart className={`h-[18px] w-[18px] ${saved ? 'fill-current' : ''}`} aria-hidden="true" />
          </button>
        </div>

        {/* One unmistakable next step — the pattern this screen exists for */}
        <button
          type="button"
          onClick={handleStartRoute}
          className="press flex h-[52px] w-full items-center justify-center gap-2 rounded-[14px] bg-ink text-[15px] font-semibold tracking-tight text-white hover:bg-ink-2"
        >
          <Navigation className="h-[18px] w-[18px]" aria-hidden="true" />
          Navigate here
        </button>
      </div>
    </div>
  );
};

export default StoreDetailView;
