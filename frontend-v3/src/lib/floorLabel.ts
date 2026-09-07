/** "Floor 2" -> "F2", so a floor pill stays a circle at any label length. */
export function shortFloorLabel(label: string): string {
  return String(label ?? '').replace(/floor/gi, 'F').replace(/\s+/g, '') || label;
}
