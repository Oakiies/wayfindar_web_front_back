/**
 * Route-planning state: origin/destination selection, computed route paths per
 * floor, and active route floor. Extracted from App.tsx.
 *
 * Owns the route-derivation effects; UI handlers in App call the exposed setters.
 */
import { useEffect, useMemo, useState } from 'react';

import { findRouteBetweenStores } from '../services/navigationDataService';
import { type FloorInfo, type MapPoint, type NavigationDataset, type Store } from '../types/navigation';
import { type InitialRouteTarget } from './useNavigationData';

const MY_LOCATION_MOCK_TIME = '2 min';
const MY_LOCATION_MOCK_DISTANCE = '120 m (mock)';

export interface RouteFloorOption {
  id: string;
  label: string;
}

export interface UseRoutePlanning {
  origin: string;
  setOrigin: (value: string) => void;
  originStore: Store | null;
  setOriginStore: (store: Store | null) => void;
  destination: string;
  setDestination: (value: string) => void;
  routeDestinationStore: Store | null;
  setRouteDestinationStore: (store: Store | null) => void;
  routePath: MapPoint[];
  routeFloorPaths: Record<string, MapPoint[]>;
  routeTime: string;
  routeMeta: string;
  activeRouteFloorId: string;
  setActiveRouteFloorId: (floorId: string) => void;
  effectiveOriginStore: Store | null;
  isOriginAutoUnresolved: boolean;
  routeFloorSequence: RouteFloorOption[];
}

export function useRoutePlanning(
  dataset: NavigationDataset | null,
  stores: Store[],
  floorsById: Map<string, FloorInfo>,
  initialRouteTarget: InitialRouteTarget | null,
): UseRoutePlanning {
  const [origin, setOrigin] = useState('My location');
  const [originStore, setOriginStore] = useState<Store | null>(null);
  const [destination, setDestination] = useState('');
  const [routeDestinationStore, setRouteDestinationStore] = useState<Store | null>(null);

  const [routePath, setRoutePath] = useState<MapPoint[]>([]);
  const [routeFloorPaths, setRouteFloorPaths] = useState<Record<string, MapPoint[]>>({});
  const [routeTime, setRouteTime] = useState('N/A');
  const [routeMeta, setRouteMeta] = useState('Select origin and destination');
  const [activeRouteFloorId, setActiveRouteFloorId] = useState('');

  const fallbackOriginStore = useMemo(() => {
    if (!routeDestinationStore) {
      return null;
    }
    const sameFloorStores = stores.filter((store) => store.floorId === routeDestinationStore.floorId);
    if (sameFloorStores.length === 0) {
      return null;
    }
    return (
      sameFloorStores.find((store) => ['entrance', 'elevator', 'stairs'].includes(store.type)) ??
      sameFloorStores[0]
    );
  }, [stores, routeDestinationStore]);

  const effectiveOriginStore = originStore ?? fallbackOriginStore;
  const isOriginAutoUnresolved = originStore === null && origin.trim().toLowerCase() === 'my location';

  // Apply the initial route target once the dataset loads.
  useEffect(() => {
    if (!initialRouteTarget) {
      return;
    }
    setActiveRouteFloorId(initialRouteTarget.defaultFloor);
    if (initialRouteTarget.destinationStore) {
      setRouteDestinationStore(initialRouteTarget.destinationStore);
      setDestination(initialRouteTarget.destinationStore.name);
    }
  }, [initialRouteTarget]);

  useEffect(() => {
    if (!dataset || !routeDestinationStore) {
      setRouteFloorPaths({});
      setRoutePath([]);
      setRouteTime('N/A');
      setRouteMeta('Select destination');
      return;
    }

    const previewFloorId = !isOriginAutoUnresolved && effectiveOriginStore
      ? effectiveOriginStore.floorId
      : routeDestinationStore.floorId;
    setActiveRouteFloorId(previewFloorId);

    if (isOriginAutoUnresolved) {
      setRouteFloorPaths({});
      setRoutePath([]);
      setRouteTime(MY_LOCATION_MOCK_TIME);
      setRouteMeta(MY_LOCATION_MOCK_DISTANCE);
      return;
    }

    if (!effectiveOriginStore) {
      setRouteFloorPaths({});
      setRoutePath([]);
      setRouteTime('N/A');
      setRouteMeta('Select origin');
      return;
    }

    const route = findRouteBetweenStores(dataset, effectiveOriginStore, routeDestinationStore);
    if (!route) {
      setRouteFloorPaths({});
      setRoutePath([]);
      setRouteTime('N/A');
      setRouteMeta('No route found');
      return;
    }

    const segments = route.segments?.length
      ? route.segments
      : [{ floorId: route.floorId, nodeIds: route.nodeIds, points: route.points }];
    const nextFloorPaths = Object.fromEntries(segments.map((segment) => [segment.floorId, segment.points]));

    setRouteFloorPaths(nextFloorPaths);
    setRouteTime(`${route.durationMinutes} min`);
    setRouteMeta(`${Math.round(route.distanceMeters)} m${segments.length > 1 ? ` | ${segments.length} floors` : ''}`);
    setActiveRouteFloorId(segments[0]?.floorId ?? previewFloorId);
  }, [dataset, effectiveOriginStore, isOriginAutoUnresolved, routeDestinationStore]);

  useEffect(() => {
    const availableFloorIds = Object.keys(routeFloorPaths);
    if (availableFloorIds.length === 0) {
      setRoutePath([]);
      return;
    }
    const floorId = routeFloorPaths[activeRouteFloorId] ? activeRouteFloorId : availableFloorIds[0];
    setRoutePath(routeFloorPaths[floorId] ?? []);
  }, [activeRouteFloorId, routeFloorPaths]);

  const routeFloorSequence = useMemo<RouteFloorOption[]>(
    () =>
      Object.keys(routeFloorPaths).map((floorId) => ({
        id: floorId,
        label: floorsById.get(floorId)?.label ?? floorId,
      })),
    [floorsById, routeFloorPaths],
  );

  return {
    origin,
    setOrigin,
    originStore,
    setOriginStore,
    destination,
    setDestination,
    routeDestinationStore,
    setRouteDestinationStore,
    routePath,
    routeFloorPaths,
    routeTime,
    routeMeta,
    activeRouteFloorId,
    setActiveRouteFloorId,
    effectiveOriginStore,
    isOriginAutoUnresolved,
    routeFloorSequence,
  };
}
