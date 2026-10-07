/**
 * Dataset/stores/floors loading + derived floor lookups.
 * Extracted from App.tsx to shrink the root component's state surface.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';

import { setBackendFocusVenue } from '../services/focusService';
import { buildFloorMap, loadNavigationDataset } from '../services/navigationDataService';
import { type FloorInfo, type NavigationDataset, type Store } from '../types/navigation';

export interface InitialRouteTarget {
  defaultFloor: string;
  destinationStore: Store | null;
}

export interface UseNavigationData {
  dataset: NavigationDataset | null;
  stores: Store[];
  selectedFloorId: string;
  setSelectedFloorId: (floorId: string) => void;
  loadingData: boolean;
  dataError: string | null;
  floors: FloorInfo[];
  floorsById: Map<string, FloorInfo>;
  selectedFloor: FloorInfo | null;
  /** Set once after the dataset loads; App applies it to route-planning state. */
  initialRouteTarget: InitialRouteTarget | null;
  /** Venues other than the default building that can be focused for testing. */
  venues: string[];
  focusVenue: string | null;
  focusError: string | null;
  /** Restrict floors, stores and backend localization to one venue; null clears it. */
  setFocusVenue: (venue: string | null) => Promise<void>;
}

const FOCUS_STORAGE_KEY = 'wayfindar.focusVenue';

function readStoredFocus(): string | null {
  try {
    return window.localStorage.getItem(FOCUS_STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStoredFocus(venue: string | null): void {
  try {
    if (venue) {
      window.localStorage.setItem(FOCUS_STORAGE_KEY, venue);
    } else {
      window.localStorage.removeItem(FOCUS_STORAGE_KEY);
    }
  } catch {
    // Storage can be blocked; focus then simply resets on reload.
  }
}

export function useNavigationData(): UseNavigationData {
  const [dataset, setDataset] = useState<NavigationDataset | null>(null);
  const [stores, setStores] = useState<Store[]>([]);
  const [selectedFloorId, setSelectedFloorId] = useState('');
  const [loadingData, setLoadingData] = useState(true);
  const [dataError, setDataError] = useState<string | null>(null);
  const [initialRouteTarget, setInitialRouteTarget] = useState<InitialRouteTarget | null>(null);
  const [focusVenue, setFocusVenueState] = useState<string | null>(readStoredFocus);
  const [focusError, setFocusError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    const initializeDataset = async () => {
      setLoadingData(true);
      setDataError(null);

      try {
        const loadedDataset = await loadNavigationDataset();
        if (!isMounted) {
          return;
        }

        const visibleStores = loadedDataset.stores.filter((store) => store.type !== 'intersection');
        const defaultFloor = loadedDataset.defaultFloorId || loadedDataset.floors[0]?.id || '';

        setDataset(loadedDataset);
        setStores(visibleStores);
        setSelectedFloorId(defaultFloor);

        const initialDestination =
          visibleStores.find((store) => store.floorId === defaultFloor) ?? visibleStores[0] ?? null;
        setInitialRouteTarget({ defaultFloor, destinationStore: initialDestination });
      } catch (error) {
        if (!isMounted) {
          return;
        }
        const message = error instanceof Error ? error.message : 'Unable to load map data';
        setDataError(message);
      } finally {
        if (isMounted) {
          setLoadingData(false);
        }
      }
    };

    initializeDataset();

    return () => {
      isMounted = false;
    };
  }, []);

  const allFloors = useMemo(() => dataset?.floors ?? [], [dataset]);
  const venues = useMemo(
    () => Array.from(new Set(allFloors.map((floor) => floor.venue).filter((v): v is string => !!v))),
    [allFloors],
  );
  // A stored focus that no longer exists in the data must not hide every floor.
  const activeFocus = focusVenue && venues.includes(focusVenue) ? focusVenue : null;
  const floors = useMemo(
    () => (activeFocus ? allFloors.filter((floor) => floor.venue === activeFocus) : allFloors),
    [allFloors, activeFocus],
  );
  const visibleStores = useMemo(() => {
    if (!activeFocus) {
      return stores;
    }
    const floorIds = new Set(floors.map((floor) => floor.id));
    return stores.filter((store) => floorIds.has(store.floorId));
  }, [stores, floors, activeFocus]);
  const floorsById = useMemo(() => buildFloorMap(floors), [floors]);
  const selectedFloor = floorsById.get(selectedFloorId) ?? (floors.length > 0 ? floors[0] : null);

  // Keep the shown floor inside the focused venue, including on first load
  // with a focus restored from storage.
  useEffect(() => {
    if (activeFocus && floors.length > 0 && !floorsById.has(selectedFloorId)) {
      setSelectedFloorId(floors[0].id);
    }
  }, [activeFocus, floors, floorsById, selectedFloorId]);

  // Tell the backend whenever the effective focus is known (and on reload).
  useEffect(() => {
    if (!dataset) {
      return;
    }
    setBackendFocusVenue(activeFocus).catch((error: unknown) => {
      setFocusError(error instanceof Error ? error.message : 'Unable to set focus');
    });
  }, [dataset, activeFocus]);

  const setFocusVenue = useCallback(async (venue: string | null) => {
    setFocusError(null);
    writeStoredFocus(venue);
    setFocusVenueState(venue);
  }, []);

  return {
    dataset,
    stores: visibleStores,
    selectedFloorId,
    setSelectedFloorId,
    loadingData,
    dataError,
    floors,
    floorsById,
    selectedFloor,
    initialRouteTarget,
    venues,
    focusVenue: activeFocus,
    focusError,
    setFocusVenue,
  };
}
