export interface UploadVideoResponse {
  success?: boolean;
  filename?: string;
  path?: string;
  video_info?: {
    fps?: number;
    frame_count?: number;
    width?: number;
    height?: number;
  };
  error?: string;
}

export interface StartNavigationPayload {
  video_filename: string;
  origin?: string;
  destination: string;
  interval?: number;
  debug_mode?: boolean;
  floor_id?: string;
  destination_floor?: string;
}

export interface StartNavigationResponse {
  success?: boolean;
  error?: string;
  session_id?: number;
  start_floor?: string;
  destination_floor?: string;
  retrieval_mode?: string;
}

export interface NavigationStateResponse {
  active?: boolean;
  session_id?: number | null;
  frame_count?: number;
  history_length?: number;
  current_floor?: string | null;
  destination_floor?: string | null;
  position?: { x: number; y: number } | null;
  orientation?: number | null;
  path?: Array<[number, number]> | Array<number[]>;
  path_segments?: unknown[];
  method?: string | null;
  tracking_mode?: string | null;
  last_update?: Record<string, unknown> | null;
}

export interface LiveLocalizeResponse {
  success?: boolean;
  error?: string;
  message?: string;
  floor_id?: string;
  position?: { x: number; y: number } | null;
  orientation?: number | null;
  direction?: number | null;
  relative_bearing?: number | null;
  nav_text?: string;
  path?: Array<[number, number]> | Array<number[]>;
  path_segments?: unknown[];
  next_transition?: {
    from_floor?: string;
    to_floor?: string;
    from_node?: string;
    to_node?: string;
  } | null;
  transition_target?: {
    node_id?: string;
    x: number;
    y: number;
    type?: string;
    name?: string;
    to_floor?: string;
  } | null;
  destination_coords?: { x: number; y: number } | null;
  map_image_url?: string;
  localize_time?: number;
  method?: string;
  num_inliers?: number;
  num_matches?: number;
  inlier_ratio?: number;
  median_reproj_error?: number | null;
  timing?: {
    decode_ms?: number;
    localize_ms?: number;
    route_ms?: number;
    server_total_ms?: number;
  };
}

export interface LiveLocalizePerfMetrics {
  requestTotalMs: number;
  uploadMs: number;
  responseMs: number;
  responseParseMs: number;
}

export interface LocalizeLiveFramePayload {
  frameBlob: Blob;
  floorId?: string | null;
  destination?: string | null;
  destinationFloor?: string | null;
  autoFloor?: boolean;
  signal?: AbortSignal;
  onPerfMetrics?: (metrics: LiveLocalizePerfMetrics) => void;
}

// Base-URL + fetch helpers now live in a single shared module.
export { API_BASE_URL, buildApiUrl } from '../api/client';
import { buildApiUrl } from '../api/client';

export async function uploadVideoFile(
  videoFile: File,
  onProgress?: (progress01: number, loadedBytes: number, totalBytes: number) => void
): Promise<UploadVideoResponse> {
  const formData = new FormData();
  formData.append('video', videoFile);

  return await new Promise<UploadVideoResponse>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', buildApiUrl('/api/upload-video'));
    xhr.timeout = 15 * 60 * 1000;

    xhr.upload.onprogress = (event) => {
      if (!onProgress || !event.lengthComputable) {
        return;
      }
      const total = Math.max(1, event.total || 1);
      const loaded = Math.max(0, event.loaded || 0);
      onProgress(Math.min(1, loaded / total), loaded, total);
    };

    xhr.onerror = () => reject(new Error('Upload failed (network error)'));
    xhr.ontimeout = () => reject(new Error('Upload timeout'));

    xhr.onload = () => {
      let payload: UploadVideoResponse = {};
      try {
        if (typeof xhr.response === 'object' && xhr.response !== null) {
          payload = xhr.response as UploadVideoResponse;
        } else if (xhr.responseText) {
          payload = JSON.parse(xhr.responseText) as UploadVideoResponse;
        }
      } catch {
        payload = {};
      }

      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new Error(payload.error || `Upload failed (${xhr.status})`));
        return;
      }

      if (!payload.filename) {
        reject(new Error('Upload succeeded but filename is missing'));
        return;
      }

      resolve(payload);
    };

    xhr.send(formData);
  });
}

export async function startNavigationTest(payload: StartNavigationPayload): Promise<StartNavigationResponse> {
  const response = await fetch(buildApiUrl('/api/start-navigation'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });

  const data = (await response.json()) as StartNavigationResponse;
  if (!response.ok || !data.success) {
    throw new Error(data.error || 'Unable to start navigation test');
  }
  return data;
}

type StopNavigationPayload = {
  session_id?: number;
};

export async function stopNavigationTest(sessionId?: number | null): Promise<void> {
  const payload: StopNavigationPayload = {};
  if (typeof sessionId === 'number' && Number.isFinite(sessionId)) {
    payload.session_id = sessionId;
  }

  await fetch(buildApiUrl('/api/stop-navigation'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
}

export function stopNavigationOnUnload(sessionId?: number | null): void {
  const url = buildApiUrl('/api/stop-navigation');
  const payload: StopNavigationPayload = {};
  if (typeof sessionId === 'number' && Number.isFinite(sessionId)) {
    payload.session_id = sessionId;
  }
  const payloadText = JSON.stringify(payload);

  try {
    void fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: payloadText,
      keepalive: true,
    });
  } catch {
    // ignore
  }

  try {
    if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
      const beaconBody = new Blob([payloadText], { type: 'application/json' });
      navigator.sendBeacon(url, beaconBody);
    }
  } catch {
    // ignore
  }
}

export async function fetchNavigationState(): Promise<NavigationStateResponse> {
  const response = await fetch(buildApiUrl('/api/navigation-state'), {
    method: 'GET',
    cache: 'no-store',
  });
  if (!response.ok) {
    throw new Error(`Unable to fetch navigation state (${response.status})`);
  }
  return (await response.json()) as NavigationStateResponse;
}

export async function localizeLiveFrame(payload: LocalizeLiveFramePayload): Promise<LiveLocalizeResponse> {
  const formData = new FormData();
  formData.append('frame', payload.frameBlob, 'camera_frame.jpg');

  const floorId = String(payload.floorId ?? '').trim();
  const destination = String(payload.destination ?? '').trim();
  const destinationFloor = String(payload.destinationFloor ?? '').trim();
  const autoFloor = payload.autoFloor !== false;

  if (floorId) {
    formData.append('floor_id', floorId);
  }
  if (destination) {
    formData.append('destination', destination);
  }
  if (destinationFloor) {
    formData.append('destination_floor', destinationFloor);
  }
  formData.append('auto_floor', autoFloor ? '1' : '0');

  return await new Promise<LiveLocalizeResponse>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const requestStartAt = performance.now();
    let uploadDoneAt = requestStartAt;
    let abortedBySignal = false;

    const handleAbortSignal = () => {
      abortedBySignal = true;
      xhr.abort();
    };

    if (payload.signal) {
      if (payload.signal.aborted) {
        reject(new DOMException('Aborted', 'AbortError'));
        return;
      }
      payload.signal.addEventListener('abort', handleAbortSignal, { once: true });
    }

    const cleanup = () => {
      if (payload.signal) {
        payload.signal.removeEventListener('abort', handleAbortSignal);
      }
    };

    xhr.open('POST', buildApiUrl('/api/live-localize'));
    xhr.timeout = 120000;
    xhr.responseType = 'json';

    xhr.upload.onloadend = () => {
      uploadDoneAt = performance.now();
    };

    xhr.onerror = () => {
      cleanup();
      reject(new Error('Live localization failed (network error)'));
    };

    xhr.ontimeout = () => {
      cleanup();
      reject(new Error('Live localization timeout'));
    };

    xhr.onabort = () => {
      cleanup();
      if (abortedBySignal || payload.signal?.aborted) {
        reject(new DOMException('Aborted', 'AbortError'));
      } else {
        reject(new Error('Live localization aborted'));
      }
    };

    xhr.onload = () => {
      const responseArrivedAt = performance.now();
      const parseStartAt = performance.now();

      let data: LiveLocalizeResponse = {};
      try {
        if (typeof xhr.response === 'object' && xhr.response !== null) {
          data = xhr.response as LiveLocalizeResponse;
        } else if (xhr.responseText) {
          data = JSON.parse(xhr.responseText) as LiveLocalizeResponse;
        }
      } catch {
        data = {};
      }

      const parseEndAt = performance.now();
      payload.onPerfMetrics?.({
        requestTotalMs: Math.max(0, responseArrivedAt - requestStartAt),
        uploadMs: Math.max(0, uploadDoneAt - requestStartAt),
        responseMs: Math.max(0, responseArrivedAt - uploadDoneAt),
        responseParseMs: Math.max(0, parseEndAt - parseStartAt),
      });

      cleanup();

      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new Error(data.error || `Live localization failed (${xhr.status})`));
        return;
      }

      resolve(data);
    };

    xhr.send(formData);
  });
}
