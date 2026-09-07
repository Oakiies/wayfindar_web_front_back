import { ArrowLeft, Heart, Navigation, Phone, Search, Share2, X } from 'lucide-react';
import React, { useEffect, useRef, useState } from 'react';
import MapCanvas from './MapCanvas';
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
    <div
      className="relative h-full w-full overflow-hidden"
      style={{ background: '#f0eeea', fontFamily: "'DM Sans', sans-serif" }}
    >
      <div className="absolute inset-0 z-0 overflow-hidden">
        <div
          className="absolute inset-0"
          style={{ transform: `translateY(-${mapShiftPercent}%)`, transformOrigin: '50% 0%' }}
        >
          <MapCanvas
            mapImageUrl={mapImageUrl}
            markers={[
              {
                id: selectedStore.id,
                x: selectedStore.x,
                y: selectedStore.y,
                color: '#ef4444',
                size: 10,
                label: 'D',
                variant: 'route' as const,
              },
            ]}
            className="h-full w-full"
          />
        </div>
      </div>

      <div
        className="pointer-events-none absolute inset-x-0 top-0 z-[1] h-28"
        style={{ background: 'linear-gradient(to bottom, rgba(240,238,234,0.95) 0%, transparent 100%)' }}
      />
      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 z-[1]"
        style={{ height: '52%', background: 'linear-gradient(to top, #f8f8f6 0%, transparent 100%)' }}
      />

      <div className="absolute inset-x-0 top-0 z-10 flex items-center gap-2.5 px-4 pt-4">
        <button
          onClick={resetToMap}
          className="flex h-[38px] w-[38px] flex-shrink-0 items-center justify-center rounded-full text-neutral-600 active:scale-95"
          style={{
            background: 'rgba(255,255,255,0.85)',
            border: '0.5px solid rgba(0,0,0,0.1)',
            backdropFilter: 'blur(12px)',
          }}
        >
          <ArrowLeft className="h-[18px] w-[18px]" />
        </button>

        <button
          onClick={openSearch}
          className="flex h-[38px] flex-1 items-center gap-2 rounded-full px-3.5 text-neutral-400"
          style={{
            background: 'rgba(255,255,255,0.88)',
            border: '0.5px solid rgba(0,0,0,0.1)',
            backdropFilter: 'blur(12px)',
            fontSize: 13,
          }}
        >
          <Search className="h-3.5 w-3.5" />
          <span>Find places...</span>
        </button>

        <button
          onClick={resetToMap}
          className="flex h-[38px] w-[38px] flex-shrink-0 items-center justify-center rounded-full text-neutral-400 active:scale-95"
          style={{
            background: 'rgba(255,255,255,0.85)',
            border: '0.5px solid rgba(0,0,0,0.1)',
            backdropFilter: 'blur(12px)',
          }}
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div
        className="absolute right-4 top-16 z-10 rounded-[10px] px-3 py-1.5 text-xs font-semibold tracking-widest text-neutral-700"
        style={{
          background: 'rgba(255,255,255,0.9)',
          border: '0.5px solid rgba(0,0,0,0.1)',
          backdropFilter: 'blur(10px)',
        }}
      >
        {floorShort}
      </div>

      <div
        ref={sheetRef}
        className="absolute inset-x-0 bottom-0 z-20 rounded-t-[28px] px-[18px] pb-8 pt-[14px]"
        style={{
          background: 'rgba(252,252,250,0.97)',
          backdropFilter: 'blur(24px)',
          borderTop: '0.5px solid rgba(0,0,0,0.07)',
          transform: `translateY(${sheetOffsetY}px)`,
          transition: sheetDragging ? 'none' : 'transform 180ms ease-out',
        }}
      >
        <div
          onPointerDown={startSheetDrag}
          className="mx-auto mb-[18px] h-1 w-9 cursor-grab touch-none rounded-full active:cursor-grabbing"
          style={{ background: 'rgba(0,0,0,0.1)' }}
        />

        <div className="mb-[14px] flex items-start gap-3">
          <div
            className="flex h-14 w-14 flex-shrink-0 items-center justify-center overflow-hidden rounded-2xl text-2xl"
            style={{ background: '#f3f3f0', border: '0.5px solid rgba(0,0,0,0.07)' }}
          >
            {selectedStore.logoSrc ? (
              <img src={selectedStore.logoSrc} alt={selectedStore.name} className="h-full w-full object-contain" />
            ) : (
              <span>{selectedStore.logo}</span>
            )}
          </div>

          <div className="min-w-0 flex-1">
            <h2 className="text-[20px] font-semibold leading-tight tracking-tight text-neutral-900">
              {selectedStore.name}
            </h2>
            <p className="mt-0.5 text-xs font-normal text-neutral-400">
              {selectedStore.category} · {selectedStore.floor}
            </p>
          </div>

          <button
            onClick={() => setSaved((state) => !state)}
            className="flex h-[34px] w-[34px] flex-shrink-0 items-center justify-center rounded-full transition-all active:scale-95"
            style={{
              background: saved ? '#eff6ff' : '#f3f3f0',
              border: `0.5px solid ${saved ? '#bfdbfe' : 'rgba(0,0,0,0.07)'}`,
              color: saved ? '#3b82f6' : '#9ca3af',
            }}
            aria-label={saved ? 'Unsave place' : 'Save place'}
          >
            <Heart className={`h-[16px] w-[16px] ${saved ? 'fill-current' : ''}`} />
          </button>
        </div>

        <div className="my-[14px]" style={{ height: '0.5px', background: 'rgba(0,0,0,0.07)' }} />

       

        <div className="flex gap-2">
          <button
            onClick={handleStartRoute}
            className="flex h-[50px] flex-1 items-center justify-center gap-2 rounded-[14px] text-sm font-semibold tracking-tight text-white active:scale-[0.97]"
            style={{ background: '#111', border: 'none', transition: 'transform 0.15s' }}
          >
            <Navigation className="h-4 w-4" />
            Navigate
          </button>

          <button
            className="flex h-[50px] w-[50px] flex-shrink-0 items-center justify-center rounded-[14px] text-neutral-500"
            style={{ background: '#f3f3f0', border: '0.5px solid rgba(0,0,0,0.07)' }}
          >
            <Phone className="h-[17px] w-[17px]" />
          </button>

          <button
            className="flex h-[50px] w-[50px] flex-shrink-0 items-center justify-center rounded-[14px] text-neutral-500"
            style={{ background: '#f3f3f0', border: '0.5px solid rgba(0,0,0,0.07)' }}
          >
            <Share2 className="h-[17px] w-[17px]" />
          </button>
        </div>
      </div>
    </div>
  );
};

export default StoreDetailView;

