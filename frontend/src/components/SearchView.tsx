import { ArrowLeft } from 'lucide-react';
import { ChevronLeft, ChevronRight, MapPin, Navigation, Search as SearchIcon, X } from 'lucide-react';
import React, { useEffect, useRef } from 'react';
import { type Store } from '../types/navigation';

interface SearchViewProps {
  searchQuery: string;
  setSearchQuery: (query: string) => void;
  selectedFilter: string;
  filters: string[];
  filteredStores: Store[];
  showMyLocationOption: boolean;
  handleMyLocationSelect: () => void;
  allowFloorScopeToggle: boolean;
  showAllFloors: boolean;
  searchFloorLabel: string;
  toggleFloorScope: () => void;
  closeSearch: () => void;
  handleStoreClick: (store: Store) => void;
  setSelectedFilter: (f: string) => void;
}

const SearchView: React.FC<SearchViewProps> = ({
  searchQuery,
  setSearchQuery,
  selectedFilter,
  filters,
  filteredStores,
  showMyLocationOption,
  handleMyLocationSelect,
  allowFloorScopeToggle,
  showAllFloors,
  searchFloorLabel,
  toggleFloorScope,
  closeSearch,
  handleStoreClick,
  setSelectedFilter,
}) => {
  const searchInputRef = useRef<HTMLInputElement>(null);
  const resultLabel = `${filteredStores.length} place${filteredStores.length === 1 ? '' : 's'}`;
  const floorScopeMessage = showAllFloors ? 'All floors' : `Showing only ${searchFloorLabel}`;
  const resultSummary = allowFloorScopeToggle ? `${resultLabel} (${floorScopeMessage})` : resultLabel;
  const floorScopeButtonLabel = showAllFloors ? `Only ${searchFloorLabel}` : 'All floors';
  const BackIcon = ArrowLeft || ChevronLeft;

  useEffect(() => {
    searchInputRef.current?.focus();
  }, []);

  return (
    <div className="flex h-full flex-col bg-[#f0eeea]">
      <div className="px-4 pb-3 pt-4">
        <div className="flex items-center gap-3">
          <button
            onClick={closeSearch}
            className="flex h-[38px] w-[38px] flex-shrink-0 items-center justify-center rounded-full text-neutral-600 transition active:scale-95"
            style={{
              background: 'rgba(255,255,255,0.85)',
              border: '0.5px solid rgba(0,0,0,0.1)',
              backdropFilter: 'blur(12px)',
            }}
          >
            <BackIcon className="h-[18px] w-[18px]" />
          </button>

          <div className="relative flex-1">
            <input
              type="text"
              placeholder="Search destination..."
              ref={searchInputRef}
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              className="w-full rounded-full border border-[#e8e5e0] bg-white py-2 pl-9 pr-9 text-base text-[#1a1a1a] focus:border-[#ccc] focus:outline-none focus:ring-0 sm:text-sm"
            />
            <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#bbb]" />
          </div>

          <button
            onClick={closeSearch}
            className="flex h-[38px] w-[38px] flex-shrink-0 items-center justify-center rounded-full text-neutral-400 transition active:scale-95"
            style={{
              background: 'rgba(255,255,255,0.85)',
              border: '0.5px solid rgba(0,0,0,0.1)',
              backdropFilter: 'blur(12px)',
            }}
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="flex gap-2 overflow-x-auto px-4 pb-3 no-scrollbar">
        {filters.map((filter) => (
          <button
            key={filter}
            type="button"
            className={`flex-shrink-0 whitespace-nowrap rounded-full border px-4 py-1.5 text-xs tracking-[0.02em] transition-colors ${
              selectedFilter === filter
                ? 'border-[#1c1c1c] bg-[#1c1c1c] text-white'
                : 'border-[#e8e5e0] bg-white text-[#888] hover:border-[#ccc] hover:text-[#444]'
            }`}
            onClick={() => setSelectedFilter(filter)}
          >
            {filter}
          </button>
        ))}
      </div>

      <div className="flex min-h-0 flex-1 flex-col border-t border-[#ece9e4] bg-white">
        <div className="flex items-center justify-between gap-3 px-4 pb-1 pt-3">
          <div className="text-[11px] uppercase tracking-[0.06em] text-[#bbb]">{resultSummary}</div>
          {allowFloorScopeToggle ? (
            <button
              type="button"
              onClick={toggleFloorScope}
              className="rounded-full border border-[#e8e5e0] bg-[#f8f6f2] px-3 py-1 text-[11px] font-medium tracking-[0.02em] text-[#7b746b] transition-colors hover:border-[#d8d2c9] hover:bg-[#f3efe9]"
            >
              {floorScopeButtonLabel}
            </button>
          ) : null}
        </div>

        <div className="flex-1 overflow-y-auto bg-white">
          {showMyLocationOption || filteredStores.length > 0 ? (
            <div className="divide-y divide-[#f0ede8]">
              {showMyLocationOption ? (
                <button
                  type="button"
                  className="flex w-full items-center gap-3.5 bg-transparent px-4 py-3.5 text-left transition-colors hover:bg-[#f0ede8]"
                  onClick={handleMyLocationSelect}
                >
                  <div className="flex h-[46px] w-[46px] flex-shrink-0 items-center justify-center overflow-hidden rounded-[10px] bg-[#f0ede8] text-[#8a7d6e]">
                    <Navigation className="h-5 w-5" />
                  </div>

                  <div className="min-w-0 flex-1">
                    <h3 className="mb-0.5 text-sm font-medium tracking-[0.01em] text-[#1a1a1a]">My location</h3>
                    <p className="text-[11px] tracking-[0.03em] text-[#aaa]">Use current location as origin</p>
                  </div>

                  <ChevronRight className="h-4 w-4 flex-shrink-0 text-[#d0ccc6]" />
                </button>
              ) : null}

              {filteredStores.map((store) => (
                <button
                  key={store.id}
                  className="flex w-full items-center gap-3.5 bg-transparent px-4 py-3.5 text-left transition-colors hover:bg-[#f0ede8]"
                  onClick={() => handleStoreClick(store)}
                >
                  <div className="flex h-[46px] w-[46px] flex-shrink-0 items-center justify-center overflow-hidden rounded-[10px] bg-[#f0ede8]">
                    {store.logoSrc ? (
                      <img src={store.logoSrc} alt={`${store.name} logo`} className="h-9 w-9 object-contain" />
                    ) : (
                      <span className="text-[20px]">{store.logo}</span>
                    )}
                  </div>

                  <div className="min-w-0 flex-1">
                    <h3 className="mb-0.5 text-sm font-medium tracking-[0.01em] text-[#1a1a1a]">{store.name}</h3>
                    <p className="mb-0.5 flex items-center gap-1 text-xs text-[#999]">
                      <MapPin className="h-2.5 w-2.5" />
                      {store.floor}
                    </p>
                    <p className="text-[11px] tracking-[0.03em] text-[#bbb]">{store.category}</p>
                  </div>

                  <ChevronRight className="h-4 w-4 flex-shrink-0 text-[#d0ccc6]" />
                </button>
              ))}
            </div>
          ) : (
            <div className="px-4 py-12 text-center">
              <SearchIcon className="mx-auto mb-3 h-7 w-7 text-[#d0ccc6]" strokeWidth={1.5} />
              <p className="mb-1 text-sm font-medium text-[#aaa]">No places found</p>
              <p className="text-xs text-[#ccc]">Try a different keyword or filter</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default SearchView;
