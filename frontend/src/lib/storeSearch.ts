/** Pure store grouping/search helpers (extracted from App.tsx). */
import { type Store } from '../types/navigation';

export function isRoomLikeType(type: string): boolean {
  const normalized = String(type || '').trim().toLowerCase();
  return normalized === 'room' || normalized === 'room_access';
}

export function normalizeSearchRoomName(name: string): string {
  const value = String(name || '').trim();
  const match = value.match(/^(.*)_([a-zA-Z])$/);
  if (match && match[1]) {
    return match[1];
  }
  return value;
}

export function buildSearchStores(stores: Store[]): Store[] {
  const grouped = new Map<string, { roomLike: boolean; displayName: string; stores: Store[] }>();

  for (const store of stores) {
    const roomLike = isRoomLikeType(store.type);
    const displayName = roomLike ? normalizeSearchRoomName(store.name) : store.name;
    const groupType = roomLike ? 'room' : String(store.type || '').trim().toLowerCase();
    const key = `${store.floorId}::${groupType}::${displayName.toLowerCase()}`;
    const existing = grouped.get(key);
    if (existing) {
      existing.stores.push(store);
      continue;
    }
    grouped.set(key, { roomLike, displayName, stores: [store] });
  }

  const merged: Store[] = [];
  for (const group of grouped.values()) {
    const representative =
      group.stores.find((candidate) => String(candidate.type || '').trim().toLowerCase() === 'room') ??
      group.stores[0];

    const mergedNodeIds = Array.from(new Set(group.stores.flatMap((entry) => entry.nodeIds ?? [])));

    merged.push({
      ...representative,
      name: group.displayName,
      category: group.roomLike ? 'Room' : representative.category,
      type: group.roomLike ? 'room' : representative.type,
      nodeIds: mergedNodeIds,
    });
  }

  return merged;
}
