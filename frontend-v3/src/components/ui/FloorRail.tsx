import React from 'react';
import { shortFloorLabel } from '../../lib/floorLabel';

export interface FloorRailItem {
  id: string;
  label: string;
}

interface FloorRailProps {
  floors: FloorRailItem[];
  activeFloorId: string;
  onSelect: (floorId: string) => void;
  className?: string;
}

/**
 * Vertical floor switcher. Shared by the home map and the navigation map so
 * changing floors always looks and behaves the same.
 */
const FloorRail: React.FC<FloorRailProps> = ({ floors, activeFloorId, onSelect, className = '' }) => {
  if (floors.length < 2) {
    return null;
  }

  return (
    <nav
      aria-label="Floor"
      className={`pointer-events-auto absolute right-4 top-1/2 z-30 -translate-y-1/2 ${className}`}
    >
      <div className="glass flex flex-col items-center gap-1 rounded-full p-1.5">
        {floors.map((floor) => {
          const active = floor.id === activeFloorId;
          return (
            <button
              key={floor.id}
              type="button"
              onClick={() => onSelect(floor.id)}
              aria-pressed={active}
              aria-label={floor.label}
              className={`press flex h-9 w-9 items-center justify-center rounded-full border border-transparent text-[13px] font-semibold ${
                active
                  ? 'border-floor-active-line bg-floor-active text-floor-active-ink shadow-none'
                  : 'text-ink-3 hover:bg-ink/5 hover:text-ink'
              }`}
            >
              {shortFloorLabel(floor.label)}
            </button>
          );
        })}
      </div>
    </nav>
  );
};

export default FloorRail;
