import { Loader2, Play, Square, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { API_BASE_URL, buildApiUrl, fetchNavigationState, startNavigationTest, stopNavigationTest, uploadVideoFile } from '../services/navigationTestService';
import ARFloorThreeOverlay from './ARFloorThreeOverlay';
import { replayArPose, replayPoseBracket } from '../services/replayArPose';
import { type ArWorldPayload } from '../services/navigationTestService';
import MapCanvas from './MapCanvas';
import { toMapUnits } from '../lib/mapFrame';
import { type FloorInfo, type MapPoint, type Store } from '../types/navigation';

type StreamUpdate = {
  frame?: number;
  timestamp?: number;
  type?: string;
  session_id?: number;
  current_floor?: string;
  destination_floor?: string;
  method?: string;
  tracking_mode?: string;
  tracking_status?: string;
  ar_world_status?: string;
  ar_payload_ready?: boolean;
  ar_projected_geometry?: boolean;
  ar_geometry_counts?: Record<string, number>;
  reason?: string;
  orientation?: number;
  relative_bearing?: number;
  ar_bearing?: number;
  ar_world?: ArWorldPayload | null;
  path?: Array<[number, number]>;
  position?: { x: number; y: number } | null;
  destination_coords?: { x: number; y: number } | null;
  map_image_url?: string;
  nav_text?: string;
  ar_state?: string;
  message?: string;
  total_frames?: number;
  total_time?: number;
  avg_frame_time?: number;
};

interface VideoTestPanelProps {
  open: boolean;
  stores: Store[];
  selectedFloorId: string;
  /** Floors by id, for the map frame of non-500x500 plans. */
  floorsById?: Map<string, FloorInfo>;
  livePosition?: MapPoint | null;
  liveHeadingDeg?: number | null;
  liveRoutePath?: MapPoint[];
  onNavigationStart?: (payload: StreamUpdate) => void;
  onNavigationUpdate?: (payload: StreamUpdate) => void;
  onNavigationStop?: () => void;
  onClose: () => void;
}

function sortStoresForSelect(stores: Store[]): Store[] {
  return [...stores]
    .filter((store) => store.type !== 'intersection')
    .sort((left, right) => {
      if (left.floorId !== right.floorId) {
        return left.floorId.localeCompare(right.floorId);
      }
      return left.name.localeCompare(right.name);
    });
}

function nowLabel(): string {
  const date = new Date();
  return date.toLocaleTimeString([], { hour12: false });
}

const API_LABEL = API_BASE_URL || 'same-origin (/api via Vite proxy)';
// The backend is paced on the video's native clock. Keep only a tiny startup
// cushion so the demo behaves like a live camera instead of waiting for a
// multi-second replay buffer.
const REPLAY_START_BUFFER_SECONDS = 0.15;

const VideoTestPanel = ({
  open,
  stores,
  selectedFloorId,
  floorsById,
  onNavigationStart,
  onNavigationUpdate,
  onNavigationStop,
  onClose,
}: VideoTestPanelProps) => {
  const streamRef = useRef<EventSource | null>(null);
  const videoElementRef = useRef<HTMLVideoElement | null>(null);
  const demoViewportRef = useRef<HTMLDivElement | null>(null);
  const enteredFullscreenRef = useRef(false);
  const statePollRef = useRef<number | null>(null);
  const pollBusyRef = useRef(false);
  const pollErrorCountRef = useRef(0);
  const lastHistoryLengthRef = useRef(0);
  const lastFrameCountRef = useRef(0);
  const activeSessionIdRef = useRef<number | null>(null);
  const runningRef = useRef(false);
  const hasLocalizationUpdateRef = useRef(false);
  const transientLocalizationMissesRef = useRef(0);
  const attemptedReplayReconnectRef = useRef(false);
  const firstFixWatchdogRef = useRef<number | null>(null);
  const timelineUpdatesRef = useRef<StreamUpdate[]>([]);
  const playbackStartedRef = useRef(false);
  const bufferingPauseRef = useRef(false);
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [videoPreviewUrl, setVideoPreviewUrl] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [lastUploadedFingerprint, setLastUploadedFingerprint] = useState<string | null>(null);
  const [lastUploadedFilename, setLastUploadedFilename] = useState<string | null>(null);
  const [destinationStoreId, setDestinationStoreId] = useState('');
  // Real navigation sends a backend keyframe about every 1.5s; the backend
  // now propagates that pose through native frames with KLT/PnP, so this
  // cadence no longer makes the AR overlay freeze between requests.
  const [intervalSeconds, setIntervalSeconds] = useState(1.5);
  const [debugMode, setDebugMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [statusText, setStatusText] = useState('Idle');
  const [lastUpdate, setLastUpdate] = useState<StreamUpdate | null>(null);
  const [presentedUpdate, setPresentedUpdate] = useState<StreamUpdate | null>(null);
  const [syncedArWorld, setSyncedArWorld] = useState<ArWorldPayload | null>(null);
  const [processingComplete, setProcessingComplete] = useState(false);
  const [isReplayBuffering, setIsReplayBuffering] = useState(false);
  const [bufferedThroughSeconds, setBufferedThroughSeconds] = useState(0);
  const [detectedFloorId, setDetectedFloorId] = useState<string | null>(null);
  const [demoViewMode, setDemoViewMode] = useState<'video' | 'ar'>('ar');
  const [isLandscape, setIsLandscape] = useState(() =>
    typeof window !== 'undefined' ? window.matchMedia('(orientation: landscape)').matches : true
  );
  const [logs, setLogs] = useState<string[]>([]);

  const storeOptions = useMemo(() => sortStoresForSelect(stores), [stores]);
  const destinationStore = useMemo(
    () => storeOptions.find((store) => store.id === destinationStoreId) ?? null,
    [destinationStoreId, storeOptions]
  );

  // Keep replay playback on the local Blob selected by the user. Switching to
  // /uploads/<filename> after the POST completes would download a large video
  // a second time before the preview can start (app_new.py uses the same local
  // object-URL approach). The server copy is still used by navigation workers.
  const demoVideoUrl = videoPreviewUrl
    ?? (lastUploadedFilename
      ? buildApiUrl(`/uploads/${encodeURIComponent(lastUploadedFilename)}`)
      : null);
  // Everything visible in the replay comes from the timeline update selected
  // by video.currentTime. The backend can process much faster than playback,
  // so lastUpdate is intentionally not used for rendering.
  const displayUpdate = presentedUpdate;
  const demoFloorId = displayUpdate?.current_floor || detectedFloorId || selectedFloorId;
  const demoMapUrl = displayUpdate?.map_image_url
    ? buildApiUrl(displayUpdate.map_image_url)
    : buildApiUrl(`/api/map-image?floor_id=${encodeURIComponent(demoFloorId)}`);
  const demoRoute = useMemo<MapPoint[]>(
    () =>
      (displayUpdate?.path ?? [])
        .filter((point): point is [number, number] => Array.isArray(point) && point.length >= 2)
        .map(([x, y]) => ({ x: Number(x), y: Number(y) }))
        .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y)),
    [displayUpdate?.path]
  );
  const displayPosition = displayUpdate?.position ?? null;
  const displayHeading = displayUpdate?.orientation ?? null;
  const pocInstruction = displayUpdate?.nav_text?.toUpperCase() ?? null;
  const pocInstructionClass = displayUpdate?.ar_state === 'arrived'
    ? 'border-emerald-300/45 bg-emerald-950/75 text-emerald-100'
    : syncedArWorld && pocInstruction?.startsWith('TURN')
      ? 'border-amber-300/45 bg-amber-950/75 text-amber-100'
      : 'border-cyan-200/35 bg-slate-950/70 text-cyan-100';
  const displayRoute = demoRoute;
  const demoDestination = displayUpdate?.destination_coords ?? (
    destinationStore && destinationStore.floorId === demoFloorId
      ? { x: destinationStore.x, y: destinationStore.y }
      : null
  );
  // Backend poses/routes are in plan pixels; MapCanvas draws in 500-unit map
  // space. Store coordinates are already in map units, so only payload
  // coordinates are converted.
  const demoFrame = floorsById?.get(demoFloorId)?.mapFrame ?? null;
  const mapRoute = useMemo(() => displayRoute.map((point) => toMapUnits(demoFrame, point)), [displayRoute, demoFrame]);
  const mapPose = displayPosition ? toMapUnits(demoFrame, displayPosition) : null;
  const mapDestination = displayUpdate?.destination_coords
    ? toMapUnits(demoFrame, displayUpdate.destination_coords)
    : demoDestination;

  const addLog = (line: string) => {
    setLogs((previous) => [`[${nowLabel()}] ${line}`, ...previous].slice(0, 40));
  };

  const recordTimelineUpdate = (payload: StreamUpdate) => {
    const timestamp = payload.timestamp;
    if (typeof timestamp !== 'number' || !Number.isFinite(timestamp)) {
      setPresentedUpdate(payload);
      return;
    }

    const updates = timelineUpdatesRef.current;
    const duplicateIndex = updates.findIndex((update) =>
      (typeof payload.frame === 'number' && update.frame === payload.frame) ||
      (typeof update.timestamp === 'number' && Math.abs(update.timestamp - timestamp) < 0.001)
    );
    if (duplicateIndex >= 0) {
      updates[duplicateIndex] = payload;
    } else {
      updates.push(payload);
      updates.sort((left, right) => Number(left.timestamp ?? 0) - Number(right.timestamp ?? 0));
    }

    const latestTimestamp = Number(updates[updates.length - 1]?.timestamp);
    if (Number.isFinite(latestTimestamp)) {
      setBufferedThroughSeconds(latestTimestamp);
    }
  };

  const markTimelineComplete = () => {
    setProcessingComplete(true);
    const video = videoElementRef.current;
    if (video && bufferingPauseRef.current) {
      bufferingPauseRef.current = false;
      setIsReplayBuffering(false);
      void video.play().catch(() => {
        // Playback controls remain available if autoplay is blocked.
      });
    }
  };

  const fileFingerprint = (file: File): string => `${file.name}:${file.size}:${file.lastModified}`;

  const clearFirstFixWatchdog = () => {
    if (firstFixWatchdogRef.current !== null) {
      window.clearTimeout(firstFixWatchdogRef.current);
      firstFixWatchdogRef.current = null;
    }
  };

  const armFirstFixWatchdog = () => {
    clearFirstFixWatchdog();
    firstFixWatchdogRef.current = window.setTimeout(() => {
      if (hasLocalizationUpdateRef.current) {
        return;
      }
      if (!attemptedReplayReconnectRef.current) {
        attemptedReplayReconnectRef.current = true;
        addLog('No update yet, reconnect stream with replay');
        const sessionId = activeSessionIdRef.current;
        if (sessionId === null) {
          return;
        }
        void connectStream(sessionId, 128).then((ok) => {
          addLog(ok ? 'Stream reconnected' : 'Stream reconnect failed');
        });
      }
      addLog('Still waiting for first localization fix (check backend terminal/logs)');
      setStatusText('Waiting first localization fix');
    }, 15000);
  };

  const stopStatePolling = () => {
    if (statePollRef.current !== null) {
      window.clearInterval(statePollRef.current);
      statePollRef.current = null;
    }
  };

  const buildPayloadFromState = (state: {
    session_id?: number | null;
    current_floor?: string | null;
    destination_floor?: string | null;
    method?: string | null;
    tracking_mode?: string | null;
    orientation?: number | null;
    path?: Array<[number, number]> | Array<number[]>;
    position?: { x: number; y: number } | null;
    frame_count?: number;
  }): StreamUpdate => ({
    type: 'update',
    session_id: typeof state.session_id === 'number' ? state.session_id : undefined,
    frame: typeof state.frame_count === 'number' ? state.frame_count : undefined,
    current_floor: state.current_floor ?? undefined,
    destination_floor: state.destination_floor ?? undefined,
    method: state.method ?? undefined,
    tracking_mode: state.tracking_mode ?? undefined,
    orientation: typeof state.orientation === 'number' ? state.orientation : undefined,
    path: Array.isArray(state.path) ? (state.path as Array<[number, number]>) : undefined,
    position: state.position ?? null,
  });

  const pollNavigationStateOnce = async () => {
    if (pollBusyRef.current) {
      return;
    }
    pollBusyRef.current = true;
    try {
      const expectedSessionId = activeSessionIdRef.current;
      if (expectedSessionId === null) {
        return;
      }
      const state = await fetchNavigationState(expectedSessionId);

      if (
        expectedSessionId !== null &&
        typeof state.session_id === 'number' &&
        Number.isFinite(state.session_id)
      ) {
        const delta = Math.abs(state.session_id - expectedSessionId);
        if (delta > 0.05) {
          return;
        }
      }

      const historyLength = typeof state.history_length === 'number' ? state.history_length : 0;
      const frameCount = typeof state.frame_count === 'number' ? state.frame_count : 0;

      if (historyLength < lastHistoryLengthRef.current || frameCount < lastFrameCountRef.current) {
        // New run or state reset from backend.
        lastHistoryLengthRef.current = 0;
        lastFrameCountRef.current = 0;
      }

      const hasNewHistory = historyLength > lastHistoryLengthRef.current;
      const hasNewFrame = frameCount > lastFrameCountRef.current;
      lastHistoryLengthRef.current = Math.max(lastHistoryLengthRef.current, historyLength);
      lastFrameCountRef.current = Math.max(lastFrameCountRef.current, frameCount);

      const hasPosition =
        !!state.position &&
        Number.isFinite(state.position.x) &&
        Number.isFinite(state.position.y);

      if (hasPosition && (hasNewHistory || hasNewFrame || !hasLocalizationUpdateRef.current)) {
        const payload = state.last_update?.type === 'update'
          ? (state.last_update as StreamUpdate)
          : buildPayloadFromState(state);
        hasLocalizationUpdateRef.current = true;
        clearFirstFixWatchdog();
        if (payload.current_floor) {
          setDetectedFloorId(payload.current_floor);
        }
        recordTimelineUpdate(payload);
        setLastUpdate(payload);
        setStatusText(state.active ? 'Running' : 'Completed');
        setRunning(true);
        onNavigationUpdate?.(payload);
      } else if (state.active && typeof state.frame_count === 'number' && state.frame_count > 0) {
        setStatusText(`Running (frame ${state.frame_count})`);
      }

      if (!state.active && runningRef.current) {
        activeSessionIdRef.current = null;
        setRunning(false);
        markTimelineComplete();
        bufferingPauseRef.current = false;
        setIsReplayBuffering(false);
        setStatusText('Completed');
        addLog('Navigation completed (state poll)');
        clearFirstFixWatchdog();
        stopStatePolling();
        onNavigationStop?.();
      }

      pollErrorCountRef.current = 0;
    } catch (error) {
      pollErrorCountRef.current += 1;
      if (pollErrorCountRef.current <= 2 || pollErrorCountRef.current % 10 === 0) {
        const message = error instanceof Error ? error.message : 'poll failed';
        addLog(`State poll warning: ${message}`);
      }
    } finally {
      pollBusyRef.current = false;
    }
  };

  const startStatePolling = () => {
    stopStatePolling();
    statePollRef.current = window.setInterval(() => {
      void pollNavigationStateOnce();
    }, 1000);
    void pollNavigationStateOnce();
  };

  const closeStream = () => {
    if (streamRef.current) {
      streamRef.current.close();
      streamRef.current = null;
    }
  };

  const resetSessionState = (nextStatus: string) => {
    activeSessionIdRef.current = null;
    setRunning(false);
    bufferingPauseRef.current = false;
    setIsReplayBuffering(false);
    setStatusText(nextStatus);
    setUploadProgress(null);
    stopStatePolling();
    clearFirstFixWatchdog();
    transientLocalizationMissesRef.current = 0;
    closeStream();
  };

  const connectStream = async (sessionId: number, replayCount = 0): Promise<boolean> => {
    closeStream();
    const query = new URLSearchParams({
      session_id: String(sessionId),
      replay: String(Math.max(0, replayCount)),
    });
    const stream = new EventSource(buildApiUrl(`/api/navigation-stream?${query.toString()}`));
    streamRef.current = stream;

    const connectedPromise = new Promise<boolean>((resolve) => {
      let settled = false;
      let opened = false;
      const settle = (value: boolean) => {
        if (settled) {
          return;
        }
        settled = true;
        resolve(value);
      };

      const connectTimeout = window.setTimeout(() => settle(opened), 1200);

      stream.onopen = () => {
        opened = true;
        addLog('Stream connected');
        window.clearTimeout(connectTimeout);
        settle(true);
      };

      stream.onerror = () => {
        if (!opened) {
          window.clearTimeout(connectTimeout);
          settle(false);
          addLog('Stream connection failed');
          closeStream();
          return;
        }

        addLog('Stream disconnected, fallback to state polling');
        if (runningRef.current) {
          setStatusText('Stream lost, polling state');
        }
        // Keep EventSource alive: the browser reconnects this same session URL
        // automatically while session-scoped polling covers the gap.
      };
    });

    stream.onmessage = (event) => {
      let payload: StreamUpdate;
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }

      const expectedSessionId = activeSessionIdRef.current;
      if (
        expectedSessionId !== null &&
        typeof payload.session_id === 'number' &&
        Math.abs(payload.session_id - expectedSessionId) > 0.05
      ) {
        return;
      }

      const type = payload.type ?? 'unknown';
      if (type === 'start') {
        if (payload.current_floor) {
          setDetectedFloorId(payload.current_floor);
        }
        setStatusText('Running');
        setRunning(true);
        addLog(`Start test on floor ${payload.current_floor ?? '-'} -> ${payload.destination_floor ?? '-'}`);
        onNavigationStart?.(payload);
        return;
      }

      if (type === 'update') {
        hasLocalizationUpdateRef.current = true;
        clearFirstFixWatchdog();
        setStatusText(
          payload.tracking_status === 'tracking_lost'
            ? 'Finding position'
            : payload.tracking_status === 'pose_rejected'
              ? 'Checking position'
              : 'Running'
        );
        setRunning(true);
        if (payload.current_floor) {
          setDetectedFloorId(payload.current_floor);
        }
        recordTimelineUpdate(payload);
        setLastUpdate(payload);
        onNavigationUpdate?.(payload);
        return;
      }

      if (type === 'warning') {
        addLog(`Warning: ${payload.message ?? 'unknown warning'}`);
        return;
      }

      if (type === 'status') {
        if (payload.message) {
          addLog(payload.message);
          setStatusText(payload.message);
        }
        return;
      }

      if (type === 'error') {
        const hasFrame = typeof payload.frame === 'number';
        if (hasFrame) {
          // A frame-level miss is expected while the first visual fix is being
          // found (and later when a keyframe needs a reseed). It is transient;
          // keep the stream alive and show one useful status instead of logging
          // the same message once per native video frame.
          transientLocalizationMissesRef.current += 1;
          if (
            !hasLocalizationUpdateRef.current &&
            transientLocalizationMissesRef.current === 1
          ) {
            setStatusText('Finding position');
            addLog('Finding position (temporary frame miss; retrying)');
          }
          return;
        }

        addLog(`Error: ${payload.message ?? 'unknown error'}`);
        resetSessionState('Error');
        onNavigationStop?.();
        return;
      }

      if (type === 'complete') {
        markTimelineComplete();
        resetSessionState('Completed');
        addLog(
          `Complete: ${payload.total_frames ?? 0} frames, ${(payload.total_time ?? 0).toFixed(2)}s, avg ${(payload.avg_frame_time ?? 0).toFixed(3)}s`
        );
        onNavigationStop?.();
      }
    };

    return await connectedPromise;
  };

  const handleStart = async () => {
    if (!videoFile) {
      addLog('Please select a video file');
      return;
    }
    if (!destinationStore) {
      addLog('Please select destination');
      return;
    }

    try {
      setLogs([]);
      timelineUpdatesRef.current = [];
      playbackStartedRef.current = false;
      bufferingPauseRef.current = false;
      setPresentedUpdate(null);
      setProcessingComplete(false);
      setIsReplayBuffering(true);
      setBufferedThroughSeconds(0);
      setDetectedFloorId(null);
      setLastUpdate(null);
      setUploadProgress(null);
      hasLocalizationUpdateRef.current = false;
      transientLocalizationMissesRef.current = 0;
      attemptedReplayReconnectRef.current = false;
      pollErrorCountRef.current = 0;
      lastHistoryLengthRef.current = 0;
      lastFrameCountRef.current = 0;
      activeSessionIdRef.current = null;
      stopStatePolling();
      clearFirstFixWatchdog();
      setBusy(true);
      const fingerprint = fileFingerprint(videoFile);
      let filename: string | null = null;

      if (lastUploadedFingerprint === fingerprint && lastUploadedFilename) {
        filename = lastUploadedFilename;
        setStatusText('Starting');
        addLog(`Reuse uploaded file: ${filename}`);
      } else {
        setStatusText('Uploading 0%');
        addLog(`Uploading ${videoFile.name}`);
        const uploadResult = await uploadVideoFile(videoFile, (progress01) => {
          const percent = Math.round(progress01 * 100);
          setUploadProgress(progress01);
          setStatusText(`Uploading ${percent}%`);
        });
        filename = uploadResult.filename ?? null;
        if (!filename) {
          throw new Error('Uploaded filename is missing');
        }
        setLastUploadedFingerprint(fingerprint);
        setLastUploadedFilename(filename);
        setUploadProgress(1);
        addLog(`Uploaded as ${filename}`);
      }

      setStatusText('Starting');

      const rawInterval = Number(intervalSeconds);
      const normalizedInterval =
        Number.isFinite(rawInterval) && rawInterval > 0
          ? Math.min(10, Math.max(0.05, rawInterval))
          : 0.05;
      setIntervalSeconds(Number(normalizedInterval.toFixed(2)));

      const startResult = await startNavigationTest({
        video_filename: filename,
        origin: 'My location',
        destination: destinationStore.name,
        interval: normalizedInterval,
        debug_mode: debugMode,
        // Do not send the map's currently selected floor: video mode is
        // explicitly auto-detected and the UI often opens while showing floor1.
        auto_floor: true,
        destination_floor: destinationStore.floorId,
      });
      if (typeof startResult.session_id === 'number' && Number.isFinite(startResult.session_id)) {
        activeSessionIdRef.current = startResult.session_id;
        addLog(`Session ${startResult.session_id}`);
      }

      const sessionId = activeSessionIdRef.current;
      if (sessionId === null) {
        throw new Error('Backend did not return a navigation session id');
      }

      setStatusText('Connecting stream');
      const streamConnected = await connectStream(sessionId, 128);
      if (!streamConnected) {
        addLog('Warning: session stream unavailable, using session-scoped polling');
      }
      if (activeSessionIdRef.current !== sessionId) {
        return;
      }

      onNavigationStart?.({
        type: 'start',
        session_id:
          typeof startResult.session_id === 'number' && Number.isFinite(startResult.session_id)
            ? startResult.session_id
            : undefined,
        // No current_floor here: the backend detects it from the video and
        // sends the real one on the stream's `start` event a moment later.
        destination_floor: destinationStore.floorId,
      });

      setRunning(true);
      setStatusText('Buffering AR timeline');
      addLog('Navigation test started');
      startStatePolling();
      armFirstFixWatchdog();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unable to start test';
      activeSessionIdRef.current = null;
      setStatusText('Error');
      addLog(`Error: ${message}`);
      setRunning(false);
      setUploadProgress(null);
      stopStatePolling();
      clearFirstFixWatchdog();
      closeStream();
    } finally {
      setBusy(false);
    }
  };

  const handleStop = async () => {
    const sessionId = activeSessionIdRef.current;
    try {
      setBusy(true);
      await stopNavigationTest(sessionId);
      addLog('Stopped by user');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Stop failed';
      addLog(`Stop error: ${message}`);
    } finally {
      setBusy(false);
      resetSessionState('Stopped');
      onNavigationStop?.();
    }
  };

  const handleClose = () => {
    void handleStop();
    void releaseLandscapeMode();
    onClose();
  };

  useEffect(() => {
    if (!videoFile) {
      setVideoPreviewUrl(null);
      return;
    }

    const objectUrl = URL.createObjectURL(videoFile);
    setVideoPreviewUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [videoFile]);

  useEffect(() => {
    const video = videoElementRef.current;
    if (!video || !demoVideoUrl) {
      return;
    }

    let animationFrame = 0;
    const synchronizePresentedUpdate = () => {
      const currentTime = video.currentTime;
      const updates = timelineUpdatesRef.current;
      let selected: StreamUpdate | null = null;
      for (const update of updates) {
        const timestamp = update.timestamp;
        if (typeof timestamp !== 'number') continue;
        if (timestamp > currentTime) {
          break;
        }
        selected = update;
      }
      // Navigation/map state follows the latest event, including HOLD. Use
      // only the pose at or before the visible video time: the replay must not
      // peek at a future backend sample to make the current frame look smooth.
      const [poseLeft] = replayPoseBracket(updates, currentTime);
      setSyncedArWorld(replayArPose(poseLeft, null, currentTime));
      setPresentedUpdate((previous) => previous === selected ? previous : selected);
    };
    const tick = () => {
      synchronizePresentedUpdate();
      // A camera feed never pauses while localization catches up. Keep the
      // replay moving and let the AR layer show the most recent causal pose.
      if (!video.paused && !video.ended) {
        animationFrame = window.requestAnimationFrame(tick);
      }
    };
    const startTicking = () => {
      window.cancelAnimationFrame(animationFrame);
      tick();
    };
    const stopTicking = () => {
      window.cancelAnimationFrame(animationFrame);
      synchronizePresentedUpdate();
    };

    video.addEventListener('play', startTicking);
    video.addEventListener('pause', stopTicking);
    video.addEventListener('timeupdate', synchronizePresentedUpdate);
    video.addEventListener('seeking', synchronizePresentedUpdate);
    video.addEventListener('seeked', synchronizePresentedUpdate);
    synchronizePresentedUpdate();

    return () => {
      window.cancelAnimationFrame(animationFrame);
      video.removeEventListener('play', startTicking);
      video.removeEventListener('pause', stopTicking);
      video.removeEventListener('timeupdate', synchronizePresentedUpdate);
      video.removeEventListener('seeking', synchronizePresentedUpdate);
      video.removeEventListener('seeked', synchronizePresentedUpdate);
    };
  }, [demoVideoUrl]);

  useEffect(() => {
    const video = videoElementRef.current;
    const updates = timelineUpdatesRef.current;
    const firstTimestamp = Number(updates[0]?.timestamp);
    const latestTimestamp = Number(updates[updates.length - 1]?.timestamp);
    if (
      playbackStartedRef.current ||
      !video ||
      !Number.isFinite(firstTimestamp) ||
      !Number.isFinite(latestTimestamp) ||
      (!processingComplete && latestTimestamp - firstTimestamp < REPLAY_START_BUFFER_SECONDS)
    ) {
      return;
    }

    playbackStartedRef.current = true;
    const startPlayback = () => {
      // Always present the complete uploaded clip from t=0.  The first
      // backend sample is only a readiness signal; seeking to it would hide
      // the opening frames and make the AR timeline look offset from the user
      // video.  Frames before the first causal pose simply have no world AR.
      video.currentTime = 0;
      bufferingPauseRef.current = false;
      setIsReplayBuffering(false);
      void video.play().catch(() => {
        // Muted autoplay may still be blocked; controls remain available.
      });
    };
    if (video.readyState >= HTMLMediaElement.HAVE_METADATA) {
      startPlayback();
    } else {
      video.addEventListener('loadedmetadata', startPlayback, { once: true });
    }
    return () => video.removeEventListener('loadedmetadata', startPlayback);
  }, [demoVideoUrl, lastUpdate, processingComplete]);

  useEffect(() => {
    runningRef.current = running;
  }, [running]);

  useEffect(() => {
    const media = window.matchMedia('(orientation: landscape)');
    const update = () => setIsLandscape(media.matches);
    update();
    media.addEventListener?.('change', update);
    return () => media.removeEventListener?.('change', update);
  }, []);

  const releaseLandscapeMode = async () => {
    try {
      if (enteredFullscreenRef.current && document.fullscreenElement === demoViewportRef.current) {
        await document.exitFullscreen();
      }
    } catch {
      // The browser may already have exited fullscreen with the Escape key.
    } finally {
      enteredFullscreenRef.current = false;
    }

    try {
      window.screen.orientation.unlock();
    } catch {
      // Orientation locking is not available in every browser.
    }
  };

  const enterLandscapeArMode = async () => {
    setDemoViewMode('ar');

    const viewport = demoViewportRef.current;
    if (viewport && document.fullscreenElement !== viewport && typeof viewport.requestFullscreen === 'function') {
      try {
        await viewport.requestFullscreen();
        enteredFullscreenRef.current = true;
      } catch {
        // Continue with the landscape hint when fullscreen is blocked.
      }
    }

    try {
      const orientation = window.screen.orientation as ScreenOrientation & {
        lock?: (value: 'landscape') => Promise<void>;
      };
      if (typeof orientation.lock === 'function') {
        await orientation.lock('landscape');
      }
    } catch {
      // iOS/Safari and non-fullscreen browsers may reject this request.
    }
  };

  useEffect(() => {
    return () => {
      stopStatePolling();
      clearFirstFixWatchdog();
      closeStream();
    };
  }, []);

  if (!open) {
    return null;
  }

  return (
    <div className="absolute inset-0 z-[70] bg-[#05070b]/95 p-2 backdrop-blur-[2px] sm:p-4">
      <div className="mx-auto flex h-full w-full max-w-[1440px] flex-col overflow-hidden rounded-[24px] border border-white/10 bg-[#0b0f17] shadow-2xl sm:rounded-[30px]">
        <div className="flex shrink-0 items-center justify-between border-b border-white/10 px-4 py-3 text-white sm:px-6">
          <div>
            <h2 className="text-base font-bold tracking-tight sm:text-lg">Walkthrough replay | landscape demo</h2>
            <p className="text-[11px] text-white/55">Phone horizontal simulation | API: {API_LABEL}</p>
          </div>
          <button
            type="button"
            onClick={handleClose}
            className="rounded-full p-2 text-white/65 transition hover:bg-white/10 hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div ref={demoViewportRef} className="relative min-h-0 flex-1 overflow-hidden bg-black">
          {demoVideoUrl ? (
            <div className="relative h-full w-full overflow-hidden bg-black">
              <video
                ref={videoElementRef}
                key={demoVideoUrl}
                src={demoVideoUrl}
                muted
                playsInline
                controls
                preload="auto"
                className="h-full w-full object-contain"
              />

              {demoViewMode === 'ar' && (
                <ARFloorThreeOverlay
                  routePath={demoRoute}
                  livePosition={displayPosition}
                  liveHeadingDeg={displayHeading}
                  transitionTarget={null}
                  arWorld={syncedArWorld}
                  videoRef={videoElementRef}
                  // Use the registered world payload whenever it is valid.
                  // World AR only: never draw the stylized screen-space
                  // fallback during a payload/tracking gap.
                  strictWorldAr
                  smoothCameraPose={false}
                  enabled
                />
              )}

              {demoViewMode === 'ar' && (
                <div role="status" aria-live="polite" className={`pointer-events-none absolute bottom-4 left-1/2 z-20 -translate-x-1/2 rounded-full border px-4 py-2 text-center text-[11px] font-semibold tracking-[0.08em] shadow-lg backdrop-blur ${pocInstructionClass}`}>
                  {displayUpdate?.ar_state === 'arrived'
                    ? 'ถึงบริเวณปลายทาง • ตรวจสอบป้ายห้อง'
                    : !syncedArWorld
                      ? String(displayUpdate?.ar_world_status ?? '').includes('route_behind_camera')
                        ? 'เส้นทางอยู่ด้านหลังกล้อง • กลับตัวตามแผนที่'
                        : displayUpdate?.tracking_status === 'tracking_lost'
                          ? 'กำลังหาตำแหน่งใหม่ • ยกกล้องให้เห็นทางเดิน'
                          : displayPosition
                            ? 'กำลังปรับตำแหน่ง • ดูแผนที่ประกอบ'
                            : 'กำลังหาตำแหน่งเริ่มต้น'
                      : <>
                          <span className="block">{pocInstruction || 'ดูเส้นทางบนแผนที่'}</span>
                          <span className="block font-normal">AR payload พร้อม • ใช้แผนที่ประกอบ</span>
                        </>}
                </div>
              )}
            </div>
          ) : (
            <div className="flex h-full items-center justify-center px-6 text-center text-white/65">
              <div>
                <p className="text-base font-semibold text-white">Choose a video to start the demo</p>
                <p className="mt-1 text-xs">The video fills the viewport while localization appears on the map in the top-right corner.</p>
              </div>
            </div>
          )}

          <div className="pointer-events-none absolute left-3 top-3 rounded-full border border-white/15 bg-black/60 px-3 py-1.5 text-[11px] font-semibold text-white backdrop-blur sm:left-5 sm:top-5">
            <span className={`mr-1.5 inline-block h-2 w-2 rounded-full ${isReplayBuffering ? 'animate-pulse bg-amber-400' : running ? 'animate-pulse bg-emerald-400' : 'bg-white/45'}`} />
            {isReplayBuffering
              ? `BUFFERING AR · ${bufferedThroughSeconds.toFixed(1)}s`
              : running
                ? 'LOCALIZING · SYNCED'
                : demoVideoUrl
                  ? 'READY TO REPLAY'
                  : 'WAITING FOR VIDEO'}
          </div>

          {demoVideoUrl && (
            <div className="absolute left-3 top-12 z-20 flex rounded-full border border-white/20 bg-black/65 p-1 text-[10px] font-semibold text-white shadow-lg backdrop-blur sm:left-5 sm:top-16">
              <button
                type="button"
                onClick={() => {
                  setDemoViewMode('video');
                  void releaseLandscapeMode();
                }}
                className={`rounded-full px-3 py-1.5 transition ${demoViewMode === 'video' ? 'bg-white text-slate-900' : 'text-white/70 hover:text-white'}`}
              >
                Video
              </button>
              <button
                type="button"
                onClick={() => void enterLandscapeArMode()}
                className={`rounded-full px-3 py-1.5 transition ${demoViewMode === 'ar' ? 'bg-cyan-400 text-slate-950' : 'text-white/70 hover:text-white'}`}
              >
                AR ทดลอง
              </button>
            </div>
          )}

          {demoViewMode === 'ar' && !isLandscape && (
            <div className="pointer-events-none absolute inset-0 z-30 flex items-center justify-center p-6">
              <div className="rounded-2xl border border-cyan-200/30 bg-slate-950/85 px-6 py-5 text-center text-white shadow-2xl backdrop-blur">
                <p className="text-sm font-semibold">Rotate phone to landscape</p>
                <p className="mt-1 text-xs text-white/75">AR replay is ready; turn the phone horizontally if the browser blocks auto-rotation.</p>
              </div>
            </div>
          )}

          <div className="absolute right-3 top-3 w-[min(34vw,300px)] min-w-[175px] overflow-hidden rounded-2xl border border-white/25 bg-black/70 p-1.5 shadow-2xl backdrop-blur-md sm:right-5 sm:top-5 sm:p-2">
            <div className="mb-1 flex items-center justify-between px-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-white/75">
              <span>Live map</span>
              <span>{demoFloorId}</span>
            </div>
            <div className="aspect-square overflow-hidden rounded-xl bg-slate-100">
              <MapCanvas
                mapImageUrl={demoMapUrl}
                mapFrame={demoFrame}
                followPose
                route={mapRoute}
                currentPose={mapPose ? {
                  x: mapPose.x,
                  y: mapPose.y,
                  headingDeg: displayHeading ?? undefined,
                } : null}
                markers={mapDestination ? [{
                  id: 'demo-destination',
                  x: mapDestination.x,
                  y: mapDestination.y,
                  color: '#dc2626',
                  size: 7,
                  label: 'D',
                }] : []}
                className="h-full w-full"
              />
            </div>
            <div className="flex items-center justify-between px-1 pt-1 text-[10px] text-white/75">
              <span>{displayPosition ? 'Position locked' : 'Waiting for fix'}</span>
              <span>{displayUpdate?.method ?? '-'}</span>
            </div>
          </div>

          {displayPosition && (
            <div className="absolute bottom-3 left-3 rounded-xl border border-white/15 bg-black/65 px-3 py-2 text-[11px] text-white shadow-lg backdrop-blur sm:bottom-5 sm:left-5">
              <p className="font-semibold">{displayUpdate?.current_floor ?? demoFloorId} | frame {displayUpdate?.frame ?? '-'}</p>
              <p className="mt-0.5 text-white/65">
                {displayPosition.x.toFixed(0)}, {displayPosition.y.toFixed(0)} | {displayUpdate?.nav_text ?? 'tracking'} | {displayHeading?.toFixed(1) ?? '-'} deg
              </p>
            </div>
          )}
        </div>

        <div className="max-h-[38%] shrink-0 space-y-4 overflow-y-auto bg-white px-4 py-4 text-left sm:px-6">
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
            <label className="mb-2 block text-xs font-semibold text-slate-600">Video file</label>
            <input
              type="file"
              accept="video/mp4,video/avi,video/quicktime,video/x-matroska,.mp4,.avi,.mov,.mkv"
              onChange={(event) => {
                setVideoFile(event.target.files?.[0] ?? null);
                setLastUploadedFingerprint(null);
                setLastUploadedFilename(null);
                timelineUpdatesRef.current = [];
                playbackStartedRef.current = false;
                setPresentedUpdate(null);
                setDetectedFloorId(null);
                setLastUpdate(null);
              }}
              className="block w-full text-xs text-slate-700 file:mr-3 file:rounded-lg file:border-0 file:bg-blue-600 file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-white hover:file:brightness-110"
            />
            <p className="mt-1 text-[11px] text-slate-500">{videoFile ? videoFile.name : 'No file selected'}</p>
            <p className="mt-1 text-[11px] text-slate-400">Large MOV files may take 30-120s to upload on Wi-Fi.</p>

            {uploadProgress !== null && uploadProgress < 1 && (
              <div className="mt-2">
                <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
                  <div
                    className="h-full bg-blue-600 transition-all"
                    style={{ width: `${Math.max(2, Math.round(uploadProgress * 100))}%` }}
                  />
                </div>
                <p className="mt-1 text-[11px] text-slate-500">{Math.round(uploadProgress * 100)}%</p>
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 gap-3">
            <div className="rounded-lg border border-slate-300 bg-slate-50 px-2 py-2">
              <span className="mb-1 block text-xs font-semibold text-slate-600">Start floor</span>
              <p className="text-sm text-slate-700">Auto detect from video</p>
            </div>
            <label className="block">
              <span className="mb-1 block text-xs font-semibold text-slate-600">Backend keyframe interval (sec)</span>
              <input
                type="number"
                min={0.05}
                max={10}
                step={0.05}
                value={intervalSeconds}
                onChange={(event) => setIntervalSeconds(Number.parseFloat(event.target.value))}
                className="w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm text-slate-800"
              />
              <p className="mt-1 text-[11px] text-slate-500">KLT/PnP tracks native video frames between backend requests.</p>
            </label>
          </div>

          <label className="block">
            <span className="mb-1 block text-xs font-semibold text-slate-600">Destination</span>
            <select
              value={destinationStoreId}
              onChange={(event) => setDestinationStoreId(event.target.value)}
              className="w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm text-slate-800"
            >
              <option value="">Choose destination and floor</option>
              {storeOptions.map((store) => (
                <option key={store.id} value={store.id}>
                  {store.name} ({store.floor})
                </option>
              ))}
            </select>
            <span className="mt-1 block text-[11px] text-slate-500">
              For the floor5 PoC comparison, choose Fire Exit 1 on floor5.
            </span>
          </label>

          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={debugMode}
              onChange={(event) => setDebugMode(event.target.checked)}
              className="h-4 w-4 rounded border-slate-300 text-blue-600"
            />
            Enable debug mode
          </label>

          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-600">Status</span>
              <span className="rounded-full bg-slate-900 px-2 py-0.5 text-[11px] font-semibold text-white">
                {statusText}
              </span>
            </div>
            {lastUpdate ? (
              <div className="space-y-1 text-xs text-slate-700">
                <p>
                  Video frame:{' '}
                  {typeof displayUpdate?.frame === 'number' ? displayUpdate.frame : '-'}
                </p>
                <p>
                  Backend latest:{' '}
                  {typeof lastUpdate.frame === 'number' ? lastUpdate.frame : '-'}
                </p>
                <p>Floor: {displayUpdate?.current_floor ?? lastUpdate.current_floor ?? '-'}</p>
                <p>
                  Position:{' '}
                  {displayUpdate?.position
                    ? `${displayUpdate.position.x.toFixed(1)}, ${displayUpdate.position.y.toFixed(1)}`
                    : '-'}
                </p>
                <p>Method: {displayUpdate?.method ?? lastUpdate.method ?? '-'}</p>
               <p>Tracking: {displayUpdate?.tracking_status ?? lastUpdate.tracking_status ?? displayUpdate?.tracking_mode ?? lastUpdate.tracking_mode ?? '-'}</p>
               <p>AR: {displayUpdate?.ar_world_status ?? lastUpdate.ar_world_status ?? '-'}</p>
              </div>
            ) : (
              <p className="text-xs text-slate-500">No localization update yet</p>
            )}
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
            <p className="mb-2 text-xs font-semibold text-slate-600">Logs</p>
            <div className="max-h-28 space-y-1 overflow-y-auto text-[11px] text-slate-700">
              {logs.length === 0 ? <p className="text-slate-500">No logs yet</p> : null}
              {logs.map((line, index) => (
                <p key={`${line}-${index}`} className="break-words">
                  {line}
                </p>
              ))}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2 border-t border-slate-200 p-4">
          <button
            type="button"
            onClick={running ? handleStop : handleStart}
            disabled={busy}
            className={`inline-flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm font-semibold text-white transition ${
              running ? 'bg-rose-600 hover:brightness-110' : 'bg-blue-600 hover:brightness-110'
            } disabled:opacity-60`}
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : running ? <Square className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            {running ? 'Stop Test' : 'Upload + Start'}
          </button>

          <button
            type="button"
            onClick={handleClose}
            className="inline-flex items-center justify-center gap-2 rounded-xl border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50"
          >
            <X className="h-4 w-4" />
            Close
          </button>
        </div>
      </div>
    </div>
  );
};

export default VideoTestPanel;
