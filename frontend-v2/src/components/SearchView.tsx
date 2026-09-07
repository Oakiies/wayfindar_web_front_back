import { ArrowLeft, ChevronRight, MapPin, Navigation, Search as SearchIcon, X } from 'lucide-react';
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
  const resultSummary = allowFloorScopeToggle ? `${resultLabel} · ${floorScopeMessage}` : resultLabel;
  const floorScopeButtonLabel = showAllFloors ? `Only ${searchFloorLabel}` : 'All floors';
  const hasQuery = searchQuery.length > 0;

  useEffect(() => {
    searchInputRef.current?.focus();
  }, []);

  return (
    <div className="flex h-full flex-col bg-canvas">
      <div className="px-4 pb-3 pt-[max(1rem,env(safe-area-inset-top))]">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={closeSearch}
            aria-label="Back to map"
            className="glass press tap flex shrink-0 items-center justify-center rounded-full text-ink-2"
          >
            <ArrowLeft className="h-[18px] w-[18px]" aria-hidden="true" />
          </button>

          <div className="relative flex-1">
            <SearchIcon
              className="pointer-events-none absolute left-3.5 top-1/2 h-[18px] w-[18px] -translate-y-1/2 text-ink-3"
              aria-hidden="true"
            />
            <input
              type="search"
              /* 16px minimum, otherwise iOS Safari zooms the page on focus */
              className="h-11 w-full rounded-full border border-line bg-surface pl-11 pr-11 text-[16px] text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
              placeholder="Search destination"
              aria-label="Search destination"
              enterKeyHint="search"
              autoComplete="off"
              ref={searchInputRef}
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
            />
            {/* Only rendered when there is something to clear, so the control
                never sits there looking tappable while doing nothing. */}
            {hasQuery ? (
              <button
                type="button"
                onClick={() => {
                  setSearchQuery('');
                  searchInputRef.current?.focus();
                }}
                aria-label="Clear search"
                className="press absolute right-1 top-1/2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-full text-ink-3 hover:bg-black/5 hover:text-ink"
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </button>
            ) : null}
          </div>
        </div>
      </div>

      <div
        role="group"
        aria-label="Filter by category"
        className="no-scrollbar flex gap-2 overflow-x-auto px-4 pb-3"
      >
        {filters.map((filter) => {
          const active = selectedFilter === filter;
          return (
            <button
              key={filter}
              type="button"
              aria-pressed={active}
              className={`press flex min-h-[44px] shrink-0 items-center whitespace-nowrap rounded-full border px-4 text-[13px] font-medium ${
                active
                  ? 'border-ink bg-ink text-white'
                  : 'border-line bg-surface text-ink-2 hover:border-ink-3'
              }`}
              onClick={() => setSelectedFilter(filter)}
            >
              {filter}
            </button>
          );
        })}
      </div>

      <div className="flex min-h-0 flex-1 flex-col border-t border-line-soft bg-surface">
        <div className="flex items-center justify-between gap-3 px-4 pb-1.5 pt-3">
          <p aria-live="polite" className="text-[12px] font-medium text-ink-3">
            {resultSummary}
          </p>
          {allowFloorScopeToggle ? (
            <button
              type="button"
              onClick={toggleFloorScope}
              aria-label={showAllFloors ? `Show results on ${searchFloorLabel} only` : 'Show results on all floors'}
              className="press flex min-h-[36px] items-center rounded-full border border-line bg-sunken px-3.5 text-[12px] font-semibold text-ink-2 hover:border-ink-3 hover:text-ink"
            >
              {floorScopeButtonLabel}
            </button>
          ) : null}
        </div>

        <div className="flex-1 overflow-y-auto overscroll-contain bg-surface pb-[env(safe-area-inset-bottom)]">
          {showMyLocationOption || filteredStores.length > 0 ? (
            <ul className="divide-y divide-line-soft">
              {showMyLocationOption ? (
                <li>
                  <button
                    type="button"
                    className="press flex w-full items-center gap-3.5 px-4 py-3.5 text-left hover:bg-sunken"
                    onClick={handleMyLocationSelect}
                  >
                    <span className="flex h-[46px] w-[46px] shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent-ink">
                      <Navigation className="h-5 w-5" aria-hidden="true" />
                    </span>

                    <span className="min-w-0 flex-1">
                      <span className="block text-[15px] font-semibold text-ink">My location</span>
                      <span className="block text-[13px] text-ink-3">Use current location as origin</span>
                    </span>

                    <ChevronRight className="h-5 w-5 shrink-0 text-ink-3" aria-hidden="true" />
                  </button>
                </li>
              ) : null}

              {filteredStores.map((store) => (
                <li key={store.id}>
                  <button
                    type="button"
                    className="press flex w-full items-center gap-3.5 px-4 py-3.5 text-left hover:bg-sunken"
                    onClick={() => handleStoreClick(store)}
                  >
                    <span className="flex h-[46px] w-[46px] shrink-0 items-center justify-center overflow-hidden rounded-xl bg-sunken">
                      {store.logoSrc ? (
                        <img src={store.logoSrc} alt="" className="h-9 w-9 object-contain" />
                      ) : (
                        <span aria-hidden="true" className="text-[20px]">
                          {store.logo}
                        </span>
                      )}
                    </span>

                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[15px] font-semibold text-ink">{store.name}</span>
                      <span className="mt-0.5 flex items-center gap-1 text-[13px] text-ink-2">
                        <MapPin className="h-3 w-3 shrink-0" aria-hidden="true" />
                        {store.floor}
                      </span>
                      <span className="block text-[12px] text-ink-3">{store.category}</span>
                    </span>

                    <ChevronRight className="h-5 w-5 shrink-0 text-ink-3" aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <div className="px-6 py-16 text-center">
              <SearchIcon className="mx-auto mb-3 h-8 w-8 text-ink-3" strokeWidth={1.5} aria-hidden="true" />
              <p className="text-[15px] font-semibold text-ink">No places found</p>
              <p className="mt-1 text-[13px] text-ink-3">
                Try a different keyword
                {allowFloorScopeToggle && !showAllFloors ? ', or search across all floors' : ''}.
              </p>
              {allowFloorScopeToggle && !showAllFloors ? (
                <button
                  type="button"
                  onClick={toggleFloorScope}
                  className="press tap mt-4 inline-flex items-center rounded-full bg-ink px-5 text-[14px] font-semibold text-white"
                >
                  Search all floors
                </button>
              ) : null}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default SearchView;
