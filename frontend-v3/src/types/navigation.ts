import { type MapFrame } from '../lib/mapFrame';

export interface MapPoint {
  x: number;
  y: number;
}

export interface FloorInfo {
  id: string;
  label: string;
  order: number;
  mapImageUrl: string;
  graphJsonUrl: string;
  /** Building/venue tag from building.json; floors sharing one can be focused together. */
  venue?: string;
  /** Set when the plan is not the legacy 500x500; see lib/mapFrame.ts. */
  mapFrame?: MapFrame | null;
}

export interface Store {
  id: string;
  name: string;
  floorId: string;
  floor: string;
  floorThai: string;
  hours: string;
  logo: string;
  color: string;
  address: string;
  category: string;
  logoSrc: string;
  type: string;
  x: number;
  y: number;
  nodeIds: string[];
}

export interface GraphNode {
  id: string;
  name: string;
  type: string;
  floorId: string;
  x: number;
  y: number;
}

export interface FloorGraph {
  floorId: string;
  nodes: Record<string, GraphNode>;
  adjacency: Record<string, Array<{ to: string; weight: number }>>;
}

export interface ConnectorNodeRef {
  floorId: string;
  nodeId?: string;
  nodeLabel?: string;
}

export interface ConnectorLink {
  id: string;
  groupId?: string;
  type: string;
  weight: number;
  accessible?: boolean;
  enabled?: boolean;
  from: ConnectorNodeRef;
  to: ConnectorNodeRef;
}

export interface NavigationDataset {
  source: 'local' | 'backend';
  floors: FloorInfo[];
  defaultFloorId: string;
  stores: Store[];
  floorGraphs: Record<string, FloorGraph>;
  connectorLinks: ConnectorLink[];
}

export interface RouteSegment {
  floorId: string;
  nodeIds: string[];
  points: MapPoint[];
}

export interface RouteResult {
  floorId: string;
  nodeIds: string[];
  points: MapPoint[];
  distancePixels: number;
  distanceMeters: number;
  durationMinutes: number;
  segments?: RouteSegment[];
}
