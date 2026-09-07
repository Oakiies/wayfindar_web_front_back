/**
 * Dataset/stores/floors loading + derived floor lookups.
 * Extracted from App.tsx to shrink the root component's state surface.
 */
import { useEffect, useMemo, useState } from 'react';

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
}

export function useNavigationData(): UseNavigationData {
  const [dataset, setDataset] = useState<NavigationDataset | null>(null);
  const [stores, setStores] = useState<Store[]>([]);
  const [selectedFloorId, setSelectedFloorId] = useState('');
  const [loadingData, setLoadingData] = useState(true);
  const [dataError, setDataError] = useState<string | null>(null);
  const [initialRouteTarget, setInitialRouteTarget] = useState<InitialRouteTarget | null>(null);

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

  const floors = dataset?.floors ?? [];
  const floorsById = useMemo(() => buildFloorMap(floors), [floors]);
  const selectedFloor = floorsById.get(selectedFloorId) ?? (floors.length > 0 ? floors[0] : null);

  return {
    dataset,
    stores,
    selectedFloorId,
    setSelectedFloorId,
    loadingData,
    dataError,
    floors,
    floorsById,
    selectedFloor,
    initialRouteTarget,
  };
}
