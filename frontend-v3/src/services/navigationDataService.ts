import {
  type ConnectorLink,
  type FloorGraph,
  type FloorInfo,
  type GraphNode,
  type MapPoint,
  type NavigationDataset,
  type RouteResult,
  type RouteSegment,
  type Store,
} from '../types/navigation';
import {
  API_BASE_URL,
  stripTrailingSlash,
  fetchJsonWithTimeout as fetchJsonWithTimeoutShared,
} from '../api/client';

interface BuildingFloorConfig {
  id: string;
  label?: string;
  order?: number;
  enabled?: boolean;
  map_image: string;
  graph_json?: string;
}

interface BuildingConfig {
  default_floor?: string;
  floors?: BuildingFloorConfig[];
  connector_links?: Array<{
    id?: string;
    group_id?: string;
    type?: string;
    weight?: number;
    accessible?: boolean;
    enabled?: boolean;
    from?: {
      floor_id?: string;
      node_id?: string;
      node_label?: string;
    };
    to?: {
      floor_id?: string;
      node_id?: string;
      node_label?: string;
    };
  }>;
}

interface GraphJsonNode {
  label?: string;
  metadata?: {
    floor?: string | number;
    type?: string;
    position?: {
      x?: number;
      y?: number;
    };
  };
}

interface GraphJsonEdge {
  source: string;
  target: string;
  metadata?: {
    distance?: number;
  };
}

interface GraphJson {
  graph?: {
    nodes?: Record<string, GraphJsonNode>;
    edges?: GraphJsonEdge[];
  };
}

interface BackendFloorsResponse {
  floors?: Array<{
    id: string;
    label?: string;
    order?: number;
  }>;
  default_floor?: string;
}

interface BackendRoomsResponse {
  rooms?: Array<{
    id: string | number;
    name: string;
    type?: string;
    floor_id: string;
    x: number;
    y: number;
  }>;
}

type GroupedStore = {
  id: string;
  name: string;
  type: string;
  floorId: string;
  xSum: number;
  ySum: number;
  count: number;
  nodeIds: string[];
};

const SYSTEM_DATA_ROOT = '/system_data';
const FETCH_TIMEOUT_MS = 7000;
const METERS_PER_PIXEL = 0.2;
const WALKING_SPEED_METERS_PER_MIN = 75;
const MAP_COORDINATE_RANGE = 500;

const TYPE_META: Record<string, { category: string; logo: string; color: string }> = {
  room: { category: 'Room', logo: '🏢', color: '#2563eb' },
  room_access: { category: 'Room Access', logo: '🚪', color: '#0ea5e9' },
  restroom: { category: 'Restroom', logo: '🚻', color: '#0d9488' },
  elevator: { category: 'Elevator', logo: '🛗', color: '#7c3aed' },
  stairs: { category: 'Stairs', logo: '🪜', color: '#ea580c' },
  fire_exit: { category: 'Fire Exit', logo: '🚨', color: '#dc2626' },
  entrance: { category: 'Entrance', logo: '🚪', color: '#16a34a' },
  poi: { category: 'POI', logo: '📍', color: '#db2777' },
  intersection: { category: 'Intersection', logo: '•', color: '#64748b' },
  unknown: { category: 'Other', logo: '📌', color: '#64748b' },
};

function resolveTypeMeta(type: string): { category: string; logo: string; color: string } {
  const normalizedType = String(type || 'unknown').trim().toLowerCase();
  return TYPE_META[normalizedType] ?? TYPE_META.unknown;
}

function normalizePlaceName(name: string, nodeType?: string): string {
  const value = String(name || '').trim();
  const normalizedType = String(nodeType || '').trim().toLowerCase();

  // Keep door/access suffixes for room_access nodes so positions are not averaged
  // across different access points (e.g. 203_a + 203_b) which can shift markers.
  if (normalizedType === 'room_access') {
    return value;
  }

  if (!value.includes('_')) {
    return value;
  }

  const parts = value.split('_');
  const suffix = parts.at(-1) ?? '';
  if (parts.length >= 2 && suffix.length === 1 && /^[a-zA-Z]$/.test(suffix)) {
    return parts.slice(0, -1).join('_');
  }

  return value;
}

function normalizeFloorId(value: string | number | undefined, fallbackFloorId: string): string {
  if (typeof value === 'number') {
    return `floor${value}`;
  }

  const raw = String(value || '').trim();
  if (!raw) {
    return fallbackFloorId;
  }

  if (raw.startsWith('floor')) {
    return raw;
  }

  const numeric = raw.match(/\d+/)?.[0];
  if (numeric) {
    return `floor${numeric}`;
  }

  return fallbackFloorId;
}

function toFiniteNumber(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function inferCoordinateDivisor(maxCoordinate: number): number {
  if (!Number.isFinite(maxCoordinate) || maxCoordinate <= MAP_COORDINATE_RANGE * 1.1) {
    return 1;
  }

  // Some maps are exported in a larger coordinate system (e.g. ~2000x2000)
  // but rendered in a 500x500 canvas in the frontend.
  const inferred = Math.round(maxCoordinate / MAP_COORDINATE_RANGE);
  return Math.max(1, inferred);
}

function euclideanDistance(a: GraphNode, b: GraphNode): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function pointDistance(a: MapPoint, b: MapPoint): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function attachStoreEndpoints(
  floorId: string,
  points: MapPoint[],
  originStore: Store | null,
  destinationStore: Store | null
): { points: MapPoint[]; extraDistance: number } {
  const adjustedPoints = [...points];
  let extraDistance = 0;

  if (originStore && originStore.floorId === floorId) {
    const originPoint = { x: originStore.x, y: originStore.y };
    if (adjustedPoints.length === 0) {
      adjustedPoints.push(originPoint);
    } else {
      const distance = pointDistance(originPoint, adjustedPoints[0]);
      if (distance <= 1) {
        adjustedPoints[0] = originPoint;
      } else {
        adjustedPoints.unshift(originPoint);
        extraDistance += distance;
      }
    }
  }

  if (destinationStore && destinationStore.floorId === floorId) {
    const destinationPoint = { x: destinationStore.x, y: destinationStore.y };
    if (adjustedPoints.length === 0) {
      adjustedPoints.push(destinationPoint);
    } else {
      const lastIndex = adjustedPoints.length - 1;
      const distance = pointDistance(destinationPoint, adjustedPoints[lastIndex]);
      if (distance <= 1) {
        adjustedPoints[lastIndex] = destinationPoint;
      } else {
        adjustedPoints.push(destinationPoint);
        extraDistance += distance;
      }
    }
  }

  return {
    points: adjustedPoints,
    extraDistance,
  };
}

function getGlobalNodeId(floorId: string, nodeId: string): string {
  return `${floorId}:${nodeId}`;
}

function parseGlobalNodeId(globalNodeId: string): { floorId: string; nodeId: string } | null {
  const separatorIndex = globalNodeId.indexOf(':');
  if (separatorIndex <= 0 || separatorIndex >= globalNodeId.length - 1) {
    return null;
  }

  return {
    floorId: globalNodeId.slice(0, separatorIndex),
    nodeId: globalNodeId.slice(separatorIndex + 1),
  };
}

function pushAdjacencyEdge(
  adjacency: Record<string, Array<{ to: string; weight: number }>>,
  from: string,
  to: string,
  weight: number
): void {
  if (!adjacency[from]) {
    adjacency[from] = [];
  }
  adjacency[from].push({ to, weight });
}

function resolveConnectorNodeId(floorGraph: FloorGraph | undefined, reference: ConnectorLink['from']): string | null {
  if (!floorGraph) {
    return null;
  }

  const nodeId = String(reference.nodeId || '').trim();
  if (nodeId && floorGraph.nodes[nodeId]) {
    return nodeId;
  }

  const nodeLabel = String(reference.nodeLabel || '').trim();
  if (!nodeLabel) {
    return null;
  }

  return Object.values(floorGraph.nodes).find((node) => node.name === nodeLabel)?.id ?? null;
}

function splitGlobalPathByFloor(dataset: NavigationDataset, globalPath: string[]): RouteSegment[] {
  const segments: RouteSegment[] = [];
  let currentFloorId = '';
  let currentNodeIds: string[] = [];

  const flush = () => {
    if (!currentFloorId || currentNodeIds.length === 0) {
      return;
    }

    const floorGraph = dataset.floorGraphs[currentFloorId];
    if (!floorGraph) {
      currentFloorId = '';
      currentNodeIds = [];
      return;
    }

    const points = currentNodeIds
      .map((nodeId) => floorGraph.nodes[nodeId])
      .filter((node): node is GraphNode => !!node)
      .map((node) => ({ x: node.x, y: node.y }));

    if (points.length > 0) {
      segments.push({
        floorId: currentFloorId,
        nodeIds: [...currentNodeIds],
        points,
      });
    }

    currentFloorId = '';
    currentNodeIds = [];
  };

  for (const globalNodeId of globalPath) {
    const parsed = parseGlobalNodeId(globalNodeId);
    if (!parsed) {
      continue;
    }

    if (!currentFloorId) {
      currentFloorId = parsed.floorId;
      currentNodeIds = [parsed.nodeId];
      continue;
    }

    if (parsed.floorId !== currentFloorId) {
      flush();
      currentFloorId = parsed.floorId;
      currentNodeIds = [parsed.nodeId];
      continue;
    }

    currentNodeIds.push(parsed.nodeId);
  }

  flush();
  return segments;
}

function buildBuildingAdjacency(
  dataset: NavigationDataset
): Record<string, Array<{ to: string; weight: number }>> {
  const adjacency: Record<string, Array<{ to: string; weight: number }>> = {};

  for (const [floorId, floorGraph] of Object.entries(dataset.floorGraphs)) {
    for (const nodeId of Object.keys(floorGraph.nodes)) {
      adjacency[getGlobalNodeId(floorId, nodeId)] = [];
    }

    for (const [nodeId, edges] of Object.entries(floorGraph.adjacency)) {
      const globalNodeId = getGlobalNodeId(floorId, nodeId);
      for (const edge of edges) {
        pushAdjacencyEdge(adjacency, globalNodeId, getGlobalNodeId(floorId, edge.to), edge.weight);
      }
    }
  }

  for (const link of dataset.connectorLinks) {
    if (link.enabled === false) {
      continue;
    }

    const fromNodeId = resolveConnectorNodeId(dataset.floorGraphs[link.from.floorId], link.from);
    const toNodeId = resolveConnectorNodeId(dataset.floorGraphs[link.to.floorId], link.to);
    if (!fromNodeId || !toNodeId) {
      continue;
    }

    const fromGlobalNodeId = getGlobalNodeId(link.from.floorId, fromNodeId);
    const toGlobalNodeId = getGlobalNodeId(link.to.floorId, toNodeId);
    pushAdjacencyEdge(adjacency, fromGlobalNodeId, toGlobalNodeId, link.weight);
    pushAdjacencyEdge(adjacency, toGlobalNodeId, fromGlobalNodeId, link.weight);
  }

  return adjacency;
}

function fetchJsonWithTimeout<T>(url: string, timeoutMs = FETCH_TIMEOUT_MS): Promise<T> {
  return fetchJsonWithTimeoutShared<T>(url, timeoutMs);
}

function parseFloorGraph(graphJson: GraphJson, fallbackFloorId: string): FloorGraph {
  const adjacency: Record<string, Array<{ to: string; weight: number }>> = {};
  const rawGraphNodes = graphJson.graph?.nodes ?? {};
  const rawNodes: GraphNode[] = [];
  let maxCoordinate = 0;

  for (const [nodeId, rawNode] of Object.entries(rawGraphNodes)) {
    const position = rawNode.metadata?.position;
    const floorId = normalizeFloorId(rawNode.metadata?.floor, fallbackFloorId);
    const name = String(rawNode.label || nodeId).trim();
    const type = String(rawNode.metadata?.type || 'unknown').trim().toLowerCase();
    const x = toFiniteNumber(position?.x, 0);
    const y = toFiniteNumber(position?.y, 0);

    rawNodes.push({
      id: nodeId,
      name,
      type,
      floorId,
      x,
      y,
    });
    maxCoordinate = Math.max(maxCoordinate, x, y);
  }

  const coordinateDivisor = inferCoordinateDivisor(maxCoordinate);
  const nodes: Record<string, GraphNode> = {};
  for (const node of rawNodes) {
    nodes[node.id] = {
      ...node,
      x: node.x / coordinateDivisor,
      y: node.y / coordinateDivisor,
    };
    adjacency[node.id] = [];
  }

  const rawEdges = graphJson.graph?.edges ?? [];
  for (const edge of rawEdges) {
    const source = edge.source;
    const target = edge.target;
    const sourceNode = nodes[source];
    const targetNode = nodes[target];

    if (!sourceNode || !targetNode) {
      continue;
    }

    const fallbackDistance = euclideanDistance(sourceNode, targetNode);
    const distance = toFiniteNumber(edge.metadata?.distance, fallbackDistance);

    adjacency[source].push({ to: target, weight: distance });
    adjacency[target].push({ to: source, weight: distance });
  }

  return {
    floorId: fallbackFloorId,
    nodes,
    adjacency,
  };
}

function createEmptyFloorGraph(floorId: string): FloorGraph {
  return {
    floorId,
    nodes: {},
    adjacency: {},
  };
}

function sortStores(stores: Store[], floorOrderById: Map<string, number>): Store[] {
  return [...stores].sort((a, b) => {
    const floorOrderA = floorOrderById.get(a.floorId) ?? Number.MAX_SAFE_INTEGER;
    const floorOrderB = floorOrderById.get(b.floorId) ?? Number.MAX_SAFE_INTEGER;

    if (floorOrderA !== floorOrderB) {
      return floorOrderA - floorOrderB;
    }

    return a.name.localeCompare(b.name);
  });
}

function groupedStoresToList(
  groupedStores: Map<string, GroupedStore>,
  floorLabelById: Map<string, string>,
  floorOrderById: Map<string, number>
): Store[] {
  const stores: Store[] = [];

  for (const grouped of groupedStores.values()) {
    const count = Math.max(1, grouped.count);
    const typeMeta = resolveTypeMeta(grouped.type);
    const floorLabel = floorLabelById.get(grouped.floorId) ?? grouped.floorId;

    stores.push({
      id: grouped.id,
      name: grouped.name,
      floorId: grouped.floorId,
      floor: floorLabel,
      floorThai: floorLabel,
      hours: '-',
      logo: typeMeta.logo,
      color: typeMeta.color,
      address: '',
      category: typeMeta.category,
      logoSrc: '',
      type: grouped.type,
      x: grouped.xSum / count,
      y: grouped.ySum / count,
      nodeIds: [...new Set(grouped.nodeIds)],
    });
  }

  return sortStores(stores, floorOrderById);
}

function upsertGroupedStore(groupedStores: Map<string, GroupedStore>, node: GraphNode): void {
  const normalizedName = normalizePlaceName(node.name, node.type);
  const key = `${node.floorId}::${node.type}::${normalizedName}`;

  const existing = groupedStores.get(key);
  if (!existing) {
    groupedStores.set(key, {
      id: node.id,
      name: normalizedName,
      type: node.type,
      floorId: node.floorId,
      xSum: node.x,
      ySum: node.y,
      count: 1,
      nodeIds: [node.id],
    });
    return;
  }

  existing.xSum += node.x;
  existing.ySum += node.y;
  existing.count += 1;
  existing.nodeIds.push(node.id);
}

function normalizeGroupedStoreCoordinates(groupedStores: Map<string, GroupedStore>): void {
  const maxCoordinateByFloor = new Map<string, number>();

  for (const grouped of groupedStores.values()) {
    const count = Math.max(1, grouped.count);
    const x = grouped.xSum / count;
    const y = grouped.ySum / count;
    const previousMax = maxCoordinateByFloor.get(grouped.floorId) ?? 0;
    maxCoordinateByFloor.set(grouped.floorId, Math.max(previousMax, x, y));
  }

  const divisorByFloor = new Map<string, number>();
  for (const [floorId, maxCoordinate] of maxCoordinateByFloor.entries()) {
    divisorByFloor.set(floorId, inferCoordinateDivisor(maxCoordinate));
  }

  for (const grouped of groupedStores.values()) {
    const divisor = divisorByFloor.get(grouped.floorId) ?? 1;
    if (divisor <= 1) {
      continue;
    }
    grouped.xSum /= divisor;
    grouped.ySum /= divisor;
  }
}

async function loadLocalDataset(): Promise<NavigationDataset> {
  const configUrl = `${SYSTEM_DATA_ROOT}/config/building.json`;
  const buildingConfig = await fetchJsonWithTimeout<BuildingConfig>(configUrl);

  const enabledFloors = [...(buildingConfig.floors ?? [])]
    .filter((floor) => floor.enabled !== false)
    .sort((a, b) => toFiniteNumber(a.order, 0) - toFiniteNumber(b.order, 0));

  const floors: FloorInfo[] = enabledFloors.map((floor) => ({
    id: floor.id,
    label: floor.label ?? floor.id,
    order: toFiniteNumber(floor.order, 0),
    mapImageUrl: `${SYSTEM_DATA_ROOT}/${floor.map_image}`,
    graphJsonUrl: floor.graph_json ? `${SYSTEM_DATA_ROOT}/${floor.graph_json}` : '',
  }));

  const floorLabelById = new Map(floors.map((floor) => [floor.id, floor.label]));
  const floorOrderById = new Map(floors.map((floor) => [floor.id, floor.order]));
  const connectorLinks: ConnectorLink[] = (buildingConfig.connector_links ?? [])
    .filter((link) => link.from?.floor_id && link.to?.floor_id)
    .map((link, index) => ({
      id: String(link.id || `connector-${index}`),
      groupId: typeof link.group_id === 'string' ? link.group_id : undefined,
      type: String(link.type || 'connector').trim().toLowerCase(),
      weight: toFiniteNumber(link.weight, 1),
      accessible: typeof link.accessible === 'boolean' ? link.accessible : undefined,
      enabled: typeof link.enabled === 'boolean' ? link.enabled : true,
      from: {
        floorId: normalizeFloorId(link.from?.floor_id, ''),
        nodeId: String(link.from?.node_id || '').trim() || undefined,
        nodeLabel: String(link.from?.node_label || '').trim() || undefined,
      },
      to: {
        floorId: normalizeFloorId(link.to?.floor_id, ''),
        nodeId: String(link.to?.node_id || '').trim() || undefined,
        nodeLabel: String(link.to?.node_label || '').trim() || undefined,
      },
    }))
    .filter((link) => link.from.floorId && link.to.floorId);
  const floorGraphs: Record<string, FloorGraph> = {};
  const groupedStores = new Map<string, GroupedStore>();

  for (const floor of floors) {
    if (!floor.graphJsonUrl) {
      floorGraphs[floor.id] = createEmptyFloorGraph(floor.id);
      continue;
    }

    const graphJson = await fetchJsonWithTimeout<GraphJson>(floor.graphJsonUrl);
    const floorGraph = parseFloorGraph(graphJson, floor.id);
    floorGraphs[floor.id] = floorGraph;

    for (const node of Object.values(floorGraph.nodes)) {
      upsertGroupedStore(groupedStores, node);
    }
  }

  const stores = groupedStoresToList(groupedStores, floorLabelById, floorOrderById);

  const defaultFloorId = floors.some((floor) => floor.id === buildingConfig.default_floor)
    ? String(buildingConfig.default_floor)
    : floors[0]?.id ?? '';

  return {
    source: 'local',
    floors,
    defaultFloorId,
    stores,
    floorGraphs,
    connectorLinks,
  };
}

async function loadBackendOverlay(localDataset: NavigationDataset, apiBaseUrl: string): Promise<NavigationDataset> {
  const baseUrl = stripTrailingSlash(apiBaseUrl);
  const floorsResponse = await fetchJsonWithTimeout<BackendFloorsResponse>(`${baseUrl}/api/floors`);
  const roomsResponse = await fetchJsonWithTimeout<BackendRoomsResponse>(`${baseUrl}/api/rooms?all=1`);

  const backendFloors = floorsResponse.floors ?? [];
  const backendRooms = roomsResponse.rooms ?? [];
  if (backendFloors.length === 0 || backendRooms.length === 0) {
    return localDataset;
  }

  const localFloorById = new Map(localDataset.floors.map((floor) => [floor.id, floor]));
  const mergedFloorById = new Map(localDataset.floors.map((floor) => [floor.id, { ...floor }]));

  for (const backendFloor of backendFloors) {
    const localFloor = localFloorById.get(backendFloor.id);
    mergedFloorById.set(backendFloor.id, {
      id: backendFloor.id,
      label: backendFloor.label ?? localFloor?.label ?? backendFloor.id,
      order: toFiniteNumber(backendFloor.order, localFloor?.order ?? 0),
      mapImageUrl: `${baseUrl}/api/map-image?floor_id=${encodeURIComponent(backendFloor.id)}`,
      graphJsonUrl: localFloor?.graphJsonUrl ?? '',
    });
  }

  const floors: FloorInfo[] = Array.from(mergedFloorById.values()).sort((a, b) => a.order - b.order);

  const floorLabelById = new Map(floors.map((floor) => [floor.id, floor.label]));
  const floorOrderById = new Map(floors.map((floor) => [floor.id, floor.order]));
  const fallbackFloorId = floors[0]?.id ?? localDataset.defaultFloorId;

  const groupedStores = new Map<string, GroupedStore>();
  for (const room of backendRooms) {
    const floorId = normalizeFloorId(room.floor_id, fallbackFloorId);
    const type = String(room.type || 'unknown').trim().toLowerCase();
    const name = normalizePlaceName(String(room.name || '').trim(), type);

    if (!floorId || !name || !floorLabelById.has(floorId)) {
      continue;
    }

    const key = `${floorId}::${type}::${name}`;
    const existing = groupedStores.get(key);
    if (!existing) {
      groupedStores.set(key, {
        id: String(room.id),
        name,
        type,
        floorId,
        xSum: toFiniteNumber(room.x, 0),
        ySum: toFiniteNumber(room.y, 0),
        count: 1,
        nodeIds: [],
      });
      continue;
    }

    existing.xSum += toFiniteNumber(room.x, 0);
    existing.ySum += toFiniteNumber(room.y, 0);
    existing.count += 1;
  }

  normalizeGroupedStoreCoordinates(groupedStores);
  const stores = groupedStoresToList(groupedStores, floorLabelById, floorOrderById);

  const defaultFloorId = floors.some((floor) => floor.id === floorsResponse.default_floor)
    ? String(floorsResponse.default_floor)
    : localDataset.defaultFloorId;

  return {
    source: 'backend',
    floors,
    defaultFloorId,
    stores,
    floorGraphs: localDataset.floorGraphs,
    connectorLinks: localDataset.connectorLinks,
  };
}

export async function loadNavigationDataset(): Promise<NavigationDataset> {
  const localDataset = await loadLocalDataset();

  const apiBaseUrl = API_BASE_URL;
  if (!apiBaseUrl) {
    return localDataset;
  }

  try {
    return await loadBackendOverlay(localDataset, apiBaseUrl);
  } catch (error) {
    console.warn('Failed to load backend navigation data. Falling back to local dataset.', error);
    return localDataset;
  }
}

type DijkstraResult = {
  distance: number;
  path: string[];
};

function shortestPath(
  adjacency: Record<string, Array<{ to: string; weight: number }>>,
  startNodeId: string,
  endNodeId: string
): DijkstraResult | null {
  if (!adjacency[startNodeId] || !adjacency[endNodeId]) {
    return null;
  }

  if (startNodeId === endNodeId) {
    return {
      distance: 0,
      path: [startNodeId],
    };
  }

  const nodeIds = Object.keys(adjacency);
  const unvisited = new Set(nodeIds);
  const distances: Record<string, number> = {};
  const previous: Record<string, string | null> = {};

  for (const nodeId of nodeIds) {
    distances[nodeId] = Number.POSITIVE_INFINITY;
    previous[nodeId] = null;
  }
  distances[startNodeId] = 0;

  while (unvisited.size > 0) {
    let currentNodeId: string | null = null;
    let currentDistance = Number.POSITIVE_INFINITY;

    for (const nodeId of unvisited) {
      if (distances[nodeId] < currentDistance) {
        currentDistance = distances[nodeId];
        currentNodeId = nodeId;
      }
    }

    if (!currentNodeId || !Number.isFinite(currentDistance)) {
      break;
    }

    unvisited.delete(currentNodeId);

    if (currentNodeId === endNodeId) {
      break;
    }

    for (const edge of adjacency[currentNodeId]) {
      if (!unvisited.has(edge.to)) {
        continue;
      }

      const nextDistance = currentDistance + edge.weight;
      if (nextDistance < distances[edge.to]) {
        distances[edge.to] = nextDistance;
        previous[edge.to] = currentNodeId;
      }
    }
  }

  if (!Number.isFinite(distances[endNodeId])) {
    return null;
  }

  const path: string[] = [];
  let nodeId: string | null = endNodeId;
  while (nodeId) {
    path.unshift(nodeId);
    if (nodeId === startNodeId) {
      break;
    }
    nodeId = previous[nodeId];
  }

  if (path[0] !== startNodeId) {
    return null;
  }

  return {
    distance: distances[endNodeId],
    path,
  };
}

function getStoreNodeCandidates(floorGraph: FloorGraph, store: Store): string[] {
  const directCandidates = store.nodeIds.filter((nodeId) => !!floorGraph.nodes[nodeId]);
  if (directCandidates.length > 0) {
    return directCandidates;
  }

  const normalizedStoreName = normalizePlaceName(store.name, store.type);
  const exactNameMatches = Object.values(floorGraph.nodes)
    .filter((node) => normalizePlaceName(node.name, node.type) === normalizedStoreName)
    .map((node) => node.id);

  if (exactNameMatches.length > 0) {
    return exactNameMatches;
  }

  return Object.values(floorGraph.nodes)
    .filter((node) => node.name.includes(store.name) || store.name.includes(node.name))
    .map((node) => node.id);
}

export function findRouteOnFloor(
  dataset: NavigationDataset,
  floorId: string,
  originStore: Store | null,
  destinationStore: Store | null
): RouteResult | null {
  if (!originStore || !destinationStore) {
    return null;
  }

  if (originStore.floorId !== floorId || destinationStore.floorId !== floorId) {
    return null;
  }

  const floorGraph = dataset.floorGraphs[floorId];
  if (!floorGraph) {
    return null;
  }

  const originCandidates = getStoreNodeCandidates(floorGraph, originStore);
  const destinationCandidates = getStoreNodeCandidates(floorGraph, destinationStore);
  if (originCandidates.length === 0 || destinationCandidates.length === 0) {
    return null;
  }

  let bestPath: string[] = [];
  let bestDistance = Number.POSITIVE_INFINITY;

  for (const originNodeId of originCandidates) {
    for (const destinationNodeId of destinationCandidates) {
      const candidate = shortestPath(floorGraph.adjacency, originNodeId, destinationNodeId);
      if (!candidate) {
        continue;
      }

      if (candidate.distance < bestDistance) {
        bestDistance = candidate.distance;
        bestPath = candidate.path;
      }
    }
  }

  if (bestPath.length === 0 || !Number.isFinite(bestDistance)) {
    return null;
  }

  const rawPoints = bestPath
    .map((nodeId) => floorGraph.nodes[nodeId])
    .filter((node): node is GraphNode => !!node)
    .map((node) => ({ x: node.x, y: node.y }));
  const { points, extraDistance } = attachStoreEndpoints(
    floorId,
    rawPoints,
    originStore,
    destinationStore
  );

  const totalDistance = bestDistance + extraDistance;
  const distanceMeters = totalDistance * METERS_PER_PIXEL;
  const durationMinutes = Math.max(1, Math.round(distanceMeters / WALKING_SPEED_METERS_PER_MIN));

  return {
    floorId,
    nodeIds: bestPath,
    points,
    distancePixels: totalDistance,
    distanceMeters,
    durationMinutes,
  };
}

export function findRouteBetweenStores(
  dataset: NavigationDataset,
  originStore: Store | null,
  destinationStore: Store | null
): RouteResult | null {
  if (!originStore || !destinationStore) {
    return null;
  }

  if (originStore.floorId === destinationStore.floorId) {
    const sameFloorRoute = findRouteOnFloor(dataset, originStore.floorId, originStore, destinationStore);
    if (!sameFloorRoute) {
      return null;
    }

    return {
      ...sameFloorRoute,
      segments: [
        {
          floorId: sameFloorRoute.floorId,
          nodeIds: sameFloorRoute.nodeIds,
          points: sameFloorRoute.points,
        },
      ],
    };
  }

  const originFloorGraph = dataset.floorGraphs[originStore.floorId];
  const destinationFloorGraph = dataset.floorGraphs[destinationStore.floorId];
  if (!originFloorGraph || !destinationFloorGraph) {
    return null;
  }

  const originCandidates = getStoreNodeCandidates(originFloorGraph, originStore).map((nodeId) =>
    getGlobalNodeId(originStore.floorId, nodeId)
  );
  const destinationCandidates = getStoreNodeCandidates(destinationFloorGraph, destinationStore).map((nodeId) =>
    getGlobalNodeId(destinationStore.floorId, nodeId)
  );
  if (originCandidates.length === 0 || destinationCandidates.length === 0) {
    return null;
  }

  const adjacency = buildBuildingAdjacency(dataset);
  let bestPath: string[] = [];
  let bestDistance = Number.POSITIVE_INFINITY;

  for (const originNodeId of originCandidates) {
    for (const destinationNodeId of destinationCandidates) {
      const candidate = shortestPath(adjacency, originNodeId, destinationNodeId);
      if (!candidate) {
        continue;
      }

      if (candidate.distance < bestDistance) {
        bestDistance = candidate.distance;
        bestPath = candidate.path;
      }
    }
  }

  if (bestPath.length === 0 || !Number.isFinite(bestDistance)) {
    return null;
  }

  let extraDistance = 0;
  const segments = splitGlobalPathByFloor(dataset, bestPath).map((segment) => {
    const adjustedSegment = attachStoreEndpoints(
      segment.floorId,
      segment.points,
      originStore,
      destinationStore
    );
    extraDistance += adjustedSegment.extraDistance;
    return {
      ...segment,
      points: adjustedSegment.points,
    };
  });
  const firstSegment = segments[0];
  if (!firstSegment) {
    return null;
  }

  const totalDistance = bestDistance + extraDistance;
  const distanceMeters = totalDistance * METERS_PER_PIXEL;
  const durationMinutes = Math.max(1, Math.round(distanceMeters / WALKING_SPEED_METERS_PER_MIN));

  return {
    floorId: firstSegment.floorId,
    nodeIds: firstSegment.nodeIds,
    points: firstSegment.points,
    distancePixels: totalDistance,
    distanceMeters,
    durationMinutes,
    segments,
  };
}

export function buildFloorMap(floors: FloorInfo[]): Map<string, FloorInfo> {
  return new Map(floors.map((floor) => [floor.id, floor]));
}
