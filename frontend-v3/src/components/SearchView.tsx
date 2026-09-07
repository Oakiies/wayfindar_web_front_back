import { ArrowLeft, ChevronRight, MapPin, Navigation, Search as SearchIcon, X } from 'lucide-react';
import React, { useEffect, useRef } from 'react';
import IconButton from './ui/IconButton';
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
  const floorScopeButtonLabel = showAllFloors ? `Only ${searchFloorLabel}` : 'All floors';
  // Keep the active scope visible next to the count, so the toggle below reads
  // as an action rather than as a status.
  const resultSummary = allowFloorScopeToggle
    ? `${resultLabel} · ${showAllFloors ? 'All floors' : searchFloorLabel}`
    : resultLabel;

  useEffect(() => {
    searchInputRef.current?.focus();
  }, []);

  return (
    <div className="flex h-full flex-col bg-paper">
      <div className="px-4 pb-3 pt-[max(1rem,env(safe-area-inset-top))]">
        <div className="flex items-center gap-2.5">
          <IconButton label="Back" onClick={closeSearch}>
            <ArrowLeft className="h-[18px] w-[18px]" />
          </IconButton>

          {/* The old header had a back button and an X that both closed the
              view. The X now clears the query instead — one job each. */}
          <div className="relative flex-1">
            <SearchIcon className="pointer-events-none absolute left-4 top-1/2 h-[18px] w-[18px] -translate-y-1/2 text-ink-4" />
            <input
              type="text"
              placeholder="Search destination"
              ref={searchInputRef}
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              className="h-11 w-full rounded-full border border-line bg-surface pl-11 pr-10 text-[15px] text-ink placeholder:text-ink-4 focus:border-ink-4 focus:outline-none"
            />
            {searchQuery ? (
              <button
                type="button"
                aria-label="Clear search"
                onClick={() => {
                  setSearchQuery('');
                  searchInputRef.current?.focus();
                }}
                className="press absolute right-1.5 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full text-ink-4 hover:bg-paper-2 hover:text-ink-2"
              >
                <X className="h-4 w-4" />
              </button>
            ) : null}
          </div>
        </div>
      </div>

      <div className="no-scrollbar flex gap-2 overflow-x-auto px-4 pb-3">
        {filters.map((filter) => (
          <button
            key={filter}
            type="button"
            aria-pressed={selectedFilter === filter}
            className={`press shrink-0 whitespace-nowrap rounded-full border px-4 py-2 text-[13px] font-medium ${
              selectedFilter === filter
                ? 'border-ink bg-ink text-white'
                : 'border-line bg-surface text-ink-3 hover:text-ink'
            }`}
            onClick={() => setSelectedFilter(filter)}
          >
            {filter}
          </button>
        ))}
      </div>

      <div className="flex min-h-0 flex-1 flex-col rounded-t-[var(--radius-xl)] border-t border-line-2 bg-surface">
        <div className="flex items-center justify-between gap-3 px-5 pb-2 pt-4">
          <span className="eyebrow">{resultSummary}</span>
          {allowFloorScopeToggle ? (
            <button
              type="button"
              onClick={toggleFloorScope}
              className="press rounded-full border border-line bg-surface-2 px-3.5 py-1.5 text-[12px] font-medium text-ink-2 hover:bg-paper-2"
            >
              {floorScopeButtonLabel}
            </button>
          ) : null}
        </div>

        <div className="flex-1 overflow-y-auto overscroll-contain">
          {showMyLocationOption || filteredStores.length > 0 ? (
            <ul className="divide-y divide-line-2 pb-4">
              {showMyLocationOption ? (
                <li>
                  <button
                    type="button"
                    className="flex w-full items-center gap-3.5 px-5 py-3.5 text-left transition-colors hover:bg-surface-2"
                    onClick={handleMyLocationSelect}
                  >
                    <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[var(--radius-sm)] bg-accent-soft text-accent">
                      <Navigation className="h-5 w-5" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[15px] font-semibold text-ink">My location</span>
                      <span className="block text-[13px] text-ink-3">Use current location as origin</span>
                    </span>
                    <ChevronRight className="h-5 w-5 shrink-0 text-ink-4" />
                  </button>
                </li>
              ) : null}

              {filteredStores.map((store) => (
                <li key={store.id}>
                  <button
                    type="button"
                    className="flex w-full items-center gap-3.5 px-5 py-3.5 text-left transition-colors hover:bg-surface-2"
                    onClick={() => handleStoreClick(store)}
                  >
                    <span className="flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-[var(--radius-sm)] bg-surface-2 text-[20px]">
                      {store.logoSrc ? (
                        <img src={store.logoSrc} alt="" className="h-8 w-8 object-contain" />
                      ) : (
                        store.logo
                      )}
                    </span>

                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[15px] font-semibold text-ink">{store.name}</span>
                      <span className="mt-0.5 flex items-center gap-1 text-[13px] text-ink-3">
                        <MapPin className="h-3 w-3 shrink-0" />
                        {store.floor}
                        <span className="text-ink-4">·</span>
                        <span className="truncate text-ink-4">{store.category}</span>
                      </span>
                    </span>

                    <ChevronRight className="h-5 w-5 shrink-0 text-ink-4" />
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <div className="px-6 py-16 text-center">
              <SearchIcon className="mx-auto mb-3 h-8 w-8 text-ink-4" strokeWidth={1.5} />
              <p className="text-[15px] font-semibold text-ink-2">No places found</p>
              <p className="mt-1 text-[13px] text-ink-4">Try a different keyword or filter</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default SearchView;
