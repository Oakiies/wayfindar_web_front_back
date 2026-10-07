/** Venue focus: ask the backend to localize only within one venue (POST /api/focus). */
import { buildApiUrl } from '../api/client';

interface FocusResponse {
  success?: boolean;
  focus_venue?: string | null;
  current_floor?: string;
  error?: string;
}

export async function setBackendFocusVenue(venue: string | null): Promise<FocusResponse> {
  const response = await fetch(buildApiUrl('/api/focus'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ venue }),
  });
  const payload = (await response.json().catch(() => ({}))) as FocusResponse;
  if (!response.ok || payload.success === false) {
    throw new Error(payload.error ?? `Focus request failed (${response.status})`);
  }
  return payload;
}
