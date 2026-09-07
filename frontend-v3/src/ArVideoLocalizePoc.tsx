import { useEffect, useState } from 'react';
import VideoTestPanel from './components/VideoTestPanel';
import { buildApiUrl } from './api/client';
import { type Store } from './types/navigation';

type RoomRecord = {
  id?: string | number;
  name?: string;
  type?: string;
  floor_id?: string;
  x?: number;
  y?: number;
};

function toStores(value: unknown): Store[] {
  if (!value || typeof value !== 'object' || !Array.isArray((value as { rooms?: unknown }).rooms)) {
    return [];
  }
  return (value as { rooms: RoomRecord[] }).rooms
    .map((room) => ({
      id: String(room.id ?? room.name ?? ''),
      name: String(room.name ?? room.id ?? 'Destination'),
      floorId: String(room.floor_id ?? 'floor5'),
      floor: String(room.floor_id ?? 'floor5'),
      floorThai: String(room.floor_id ?? 'floor5'),
      hours: '',
      logo: '',
      color: '#0d6efd',
      address: '',
      category: String(room.type ?? 'room'),
      logoSrc: '',
      type: String(room.type ?? 'room'),
      x: Number(room.x ?? 0),
      y: Number(room.y ?? 0),
      nodeIds: [],
    }))
    .filter((room) => room.id && room.name && Number.isFinite(room.x) && Number.isFinite(room.y));
}

export default function ArVideoLocalizePoc() {
  const [stores, setStores] = useState<Store[]>([]);

  useEffect(() => {
    fetch(buildApiUrl('/api/rooms?all=1'))
      .then((response) => response.json())
      .then((data) => setStores(toStores(data)))
      .catch(() => setStores([]));
  }, []);

  return (
    <div className="relative min-h-screen bg-[#05070b]">
      <div className="pointer-events-none fixed left-4 top-3 z-[90] rounded-full border border-cyan-200/25 bg-slate-950/80 px-3 py-1.5 text-[10px] font-semibold tracking-[0.08em] text-cyan-100 shadow-lg backdrop-blur">
        VIDEO LOCALIZE + AR · NO PDR / NO IMU
      </div>
      <VideoTestPanel
        open
        stores={stores}
        selectedFloorId="floor5"
        onClose={() => { window.location.href = '/'; }}
      />
    </div>
  );
}
