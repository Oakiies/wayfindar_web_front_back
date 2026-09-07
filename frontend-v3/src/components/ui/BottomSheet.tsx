import React, { useEffect, useRef, useState } from 'react';

interface BottomSheetProps {
  children: React.ReactNode;
  /** How much of the sheet stays on screen when dragged all the way down. */
  peekHeight?: number;
  className?: string;
}

function clampValue(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

/**
 * Draggable bottom sheet with a snap-to-nearest-edge release.
 * StoreDetailView and RoutePlanningView each carried their own copy of this
 * logic; they now share one implementation.
 */
const BottomSheet: React.FC<BottomSheetProps> = ({ children, peekHeight = 88, className = '' }) => {
  const sheetRef = useRef<HTMLDivElement | null>(null);
  const maxOffsetRef = useRef(240);
  const [offsetY, setOffsetY] = useState(0);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    const updateMaxOffset = () => {
      if (!sheetRef.current) {
        return;
      }
      const nextMaxOffset = Math.max(0, sheetRef.current.getBoundingClientRect().height - peekHeight);
      maxOffsetRef.current = nextMaxOffset;
      setOffsetY((previous) => clampValue(previous, 0, nextMaxOffset));
    };

    updateMaxOffset();
    window.addEventListener('resize', updateMaxOffset);
    return () => window.removeEventListener('resize', updateMaxOffset);
  }, [peekHeight]);

  const startDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    const startY = event.clientY;
    const startOffset = offsetY;
    setDragging(true);

    const handleMove = (moveEvent: PointerEvent) => {
      setOffsetY(clampValue(startOffset + (moveEvent.clientY - startY), 0, maxOffsetRef.current));
    };

    const handleUp = () => {
      window.removeEventListener('pointermove', handleMove);
      window.removeEventListener('pointerup', handleUp);
      setDragging(false);
      // Snap to whichever edge is nearer once the drag ends.
      setOffsetY((current) => {
        if (current < 36) {
          return 0;
        }
        if (maxOffsetRef.current - current < 36) {
          return maxOffsetRef.current;
        }
        return current;
      });
    };

    window.addEventListener('pointermove', handleMove);
    window.addEventListener('pointerup', handleUp);
  };

  return (
    <div
      ref={sheetRef}
      className={`animate-sheet-in absolute inset-x-0 bottom-0 z-30 rounded-t-[var(--radius-xl)] border-t border-line-2 bg-surface px-5 pb-[max(1.25rem,env(safe-area-inset-bottom))] pt-3 shadow-[var(--shadow-float)] ${className}`}
      style={{
        transform: `translateY(${offsetY}px)`,
        transition: dragging ? 'none' : 'transform 220ms var(--ease-out)',
      }}
    >
      <div
        onPointerDown={startDrag}
        role="separator"
        aria-label="Drag to resize panel"
        className="mx-auto mb-4 h-1 w-10 cursor-grab touch-none rounded-full bg-ink-4/50 active:cursor-grabbing"
      />
      {children}
    </div>
  );
};

export default BottomSheet;
