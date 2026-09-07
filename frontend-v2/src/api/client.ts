/**
 * Shared HTTP client config.
 *
 * Single source of truth for the backend base URL and fetch helpers.
 * Previously this logic was duplicated across navigationDataService.ts and
 * navigationTestService.ts.
 */

export const DEFAULT_FETCH_TIMEOUT_MS = 8000;

export function stripTrailingSlash(value: string): string {
  return value.replace(/\/+$/, '');
}

function resolveApiBaseUrl(): string {
  const envBaseUrl = String(import.meta.env.VITE_API_BASE_URL ?? '').trim();
  if (envBaseUrl) {
    return stripTrailingSlash(envBaseUrl);
  }
  // Default to same-origin requests so the Vite dev proxy can bridge to backend.
  return '';
}

export const API_BASE_URL = resolveApiBaseUrl();

export function buildApiUrl(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return API_BASE_URL ? `${API_BASE_URL}${normalizedPath}` : normalizedPath;
}

export async function fetchJsonWithTimeout<T>(
  url: string,
  timeoutMs = DEFAULT_FETCH_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const timeoutHandle = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      signal: controller.signal,
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) {
      throw new Error(`Request failed (${response.status}) for ${url}`);
    }
    return (await response.json()) as T;
  } finally {
    window.clearTimeout(timeoutHandle);
  }
}
