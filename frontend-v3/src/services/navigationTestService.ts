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
  /**
   * false pins floor_id. Default (true) treats it as a hint only and lets the
   * backend detect the real floor from the video's own frames.
   */
  auto_floor?: boolean;
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

/**
 * World-space AR payload — real camera intrinsics/pose + chevron polygons in
 * SLAM world coordinates, computed backend-side (app/services/ar_service.py,
 * ported from navigate_indoor/services/ar_service.py). The browser projects
 * this itself with a three.js camera built from K/R/t every frame, instead of
 * receiving pre-flattened 2D screen coordinates — see ARFloorThreeOverlay.tsx.
 *
 * null/absent means "do not register anything to the world this frame" (weak
 * pose, no route ahead, or nothing survives the near clip) — the overlay then
 * falls back to its screen-fixed 2D guidance, which never depends on pose.
 */
export interface ArWorldPayload {
  /** ``poc_ar_arrow_v2`` for the floor-ribbon renderer; absent for legacy live payloads. */
  arVersion?: string;
  /** [fx, fy, cx, cy] in pixels, for the image actually sent to /api/live-localize. */
  K: [number, number, number, number];
  /** [width, height] in pixels, matching K's image. */
  imgWH: [number, number];
  /** PDR anchor and floor-map basis vectors in the same world as R/t. */
  pdr_anchor_map?: [number, number];
  pdr_map_x_axis_world?: [number, number, number];
  pdr_map_y_axis_world?: [number, number, number];
  /** World-to-camera rotation, row-major 3x3 (OpenCV convention: x right, y down, z forward). */
  R: [[number, number, number], [number, number, number], [number, number, number]];
  /** World-to-camera translation, [tx, ty, tz]. */
  t: [number, number, number];
  /** Each chevron is a closed, CONCAVE polygon outline in world-space [x, y, z] points. */
  chevrons: number[][][];
  /** v2 caret polygons and the continuous floor ribbon. */
  carets?: number[][][];
  ribbon_quads?: Array<[number[][], number]>;
  ribbon_edges?: number[][][];
  metres_per_unit?: number;
  /** Backend guidance classification: a shallow bend has no repeated turn caret. */
  guidance_mode?: 'gentle_corridor' | 'directional' | string;
  local_bend_deg?: number;
  destination_marker?: {
    centre: number[];
    top: number[];
    floor_outer: number[][];
    floor_inner: number[][];
    stem: number[][];
    head: number[][];
    title: string;
    distance_m?: number | null;
    arrived?: boolean;
  };
  /** Per-chevron opacity (index-aligned with chevrons), fading near/far by camera depth. */
  alphas?: number[];
  /** True for the raised turn/transition marker (distinct colour), false for floor chevrons. */
  marker: boolean;
  /** 0 for a fresh pose, up to 1 while briefly reusing the last trustworthy pose. */
  heldAge?: number;
}

export interface TrackingSeed {
  points_2d: Array<[number, number]>;
  points_3d: Array<[number, number, number]>;
  map_point_ids: number[];
  /** [fx, fy, cx, cy] in the seed frame's reference image coordinates. */
  K: [number, number, number, number];
  imgWH: [number, number];
  floor_projection?: {
    traj_center: [number, number, number];
    floor_v1: [number, number, number];
    floor_v2: [number, number, number];
    H: [[number, number, number], [number, number, number], [number, number, number]];
  } | null;
  quality?: {
    num_points?: number;
    num_inliers?: number;
    inlier_ratio?: number;
    median_reproj_error?: number | null;
  };
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
  ar_world?: ArWorldPayload | null;
  tracking_seed?: TrackingSeed | null;
  tracking_seed_frame_id?: string | null;
  tracking_seed_capture_time_ms?: string | null;
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
  frameId?: string | number;
  captureTimeMs?: number;
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

export async function fetchNavigationState(sessionId?: number | null): Promise<NavigationStateResponse> {
  const sessionQuery = typeof sessionId === 'number' && Number.isFinite(sessionId)
    ? `?session_id=${encodeURIComponent(String(sessionId))}`
    : '';
  const response = await fetch(buildApiUrl(`/api/navigation-state${sessionQuery}`), {
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
  if (payload.frameId !== undefined) {
    formData.append('frame_id', String(payload.frameId));
  }
  if (payload.captureTimeMs !== undefined && Number.isFinite(payload.captureTimeMs)) {
    formData.append('capture_time_ms', String(payload.captureTimeMs));
  }

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
