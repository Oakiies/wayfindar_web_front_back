import { useEffect, useMemo, useRef, useState } from 'react';
import MainMapView from './components/MainMapView';
import NavigationView, { type ViewMode } from './components/NavigationView';
import RoutePlanningView, { type SearchContext } from './components/RoutePlanningView';
import SearchView from './components/SearchView';
import StoreDetailView from './components/StoreDetailView';
import VideoTestPanel from './components/VideoTestPanel';
import {
  localizeLiveFrame,
  stopNavigationOnUnload,
  type ArWorldPayload,
} from './services/navigationTestService';
import { type MapPoint, type Store } from './types/navigation';
import { useNavigationData } from './hooks/useNavigationData';
import { useRoutePlanning } from './hooks/useRoutePlanning';
import { buildSearchStores } from './lib/storeSearch';
import {
  headingFromPath,
  headingFromVector,
  inferIncomingCoordinateDivisor,
  normalizeDegrees,
} from './lib/geometry';
import {
  LIVE_CAMERA_CAPTURE_INTERVAL_MS,
  LIVE_CAMERA_JPEG_QUALITY,
  CAMERA_CALIBRATION_HEIGHT,
  CAMERA_CALIBRATION_WIDTH,
  LOCALHOST_HOSTS,
  resolveCameraErrorMessage,
} from './lib/camera';

type View = 'map' | 'search' | 'storeDetail' | 'routePlanning' | 'navigation';
type LiveTransitionTarget = {
  node_id?: string;
  x: number;
  y: number;
  type?: string;
  name?: string;
  to_floor?: string;
} | null;

type LiveStreamPayload = {
  session_id?: number;
  current_floor?: string;
  destination_floor?: string;
  method?: string;
  tracking_mode?: string;
  orientation?: number;
  path?: Array<[number, number]>;
  position?: { x: number; y: number } | null;
  next_transition?: {
    from_floor?: string;
    to_floor?: string;
    from_node?: string;
    to_node?: string;
  } | null;
  transition_target?: LiveTransitionTarget;
};

const ALL_FILTER = 'All';

function App() {
  const {
    dataset,
    stores,
    selectedFloorId,
    setSelectedFloorId,
    loadingData,
    dataError,
    floors,
    floorsById,
    selectedFloor,
    initialRouteTarget,
  } = useNavigationData();

  const [currentView, setCurrentView] = useState<View>('map');
  const [lastViewBeforeSearch, setLastViewBeforeSearch] = useState<View>('map');
  const [searchContext, setSearchContext] = useState<SearchContext>('map');
  const [searchQuery, setSearchQuery] = useState('');
  const [showAllSearchFloors, setShowAllSearchFloors] = useState(false);
  const [selectedFilter, setSelectedFilter] = useState(ALL_FILTER);
  const [selectedStore, setSelectedStore] = useState<Store | null>(null);

  const {
    origin,
    setOrigin,
    originStore,
    setOriginStore,
    destination,
    setDestination,
    routeDestinationStore,
    setRouteDestinationStore,
    routePath,
    routeTime,
    routeMeta,
    activeRouteFloorId,
    setActiveRouteFloorId,
    effectiveOriginStore,
    isOriginAutoUnresolved,
    routeFloorSequence,
  } = useRoutePlanning(dataset, stores, floorsById, initialRouteTarget);

  const [arViewMode, setArViewMode] = useState<ViewMode>('ar');
  const [showModeMenu, setShowModeMenu] = useState(false);
  const [cameraActive, setCameraActive] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [showVideoTestPanel, setShowVideoTestPanel] = useState(() => {
    if (typeof window === 'undefined') {
      return false;
    }
    return new URLSearchParams(window.location.search).get('test') === 'localizer';
  });
  const [liveNavigationActive, setLiveNavigationActive] = useState(false);
  const [liveNavigationFloorId, setLiveNavigationFloorId] = useState('');
  const [liveNavigationPosition, setLiveNavigationPosition] = useState<MapPoint | null>(null);
  const [liveNavigationHeading, setLiveNavigationHeading] = useState<number | null>(null);
  const [liveNavigationRoutePath, setLiveNavigationRoutePath] = useState<MapPoint[]>([]);
  const [liveNavigationMethod, setLiveNavigationMethod] = useState<string | null>(null);
  const [liveNavigationTrackingMode, setLiveNavigationTrackingMode] = useState<string | null>(null);
  const [liveNavigationTransitionTarget, setLiveNavigationTransitionTarget] = useState<LiveTransitionTarget>(null);
  // Real camera-pose AR payload (K/R/t + world-space chevrons) from the latest
  // /api/live-localize response. Not run through inferIncomingCoordinateDivisor
  // like liveNavigationPosition/RoutePath — ar_world's coordinates are metres in
  // SLAM world space / camera space, not floor-plan pixels, so that conversion
  // does not apply here.
  const [liveNavigationArWorld, setLiveNavigationArWorld] = useState<ArWorldPayload | null>(null);
  const liveNavigationSessionIdRef = useRef<number | null>(null);
  const cameraVideoRef = useRef<HTMLVideoElement | null>(null);
  const cameraStreamRef = useRef<MediaStream | null>(null);
  const liveCameraCaptureCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const liveCameraLoopTimerRef = useRef<number | null>(null);
  const liveCameraRequestAbortRef = useRef<AbortController | null>(null);
  const liveCameraBusyRef = useRef(false);
  const lastLocalizedPositionRef = useRef<MapPoint | null>(null);
  const liveCameraContextRef = useRef<{ floorId: string; destination: string; destinationFloor: string }>({
    floorId: '',
    destination: '',
    destinationFloor: '',
  });

  const navGridDots = useMemo(() => Array.from({ length: 9 }, (_, index) => index), []);
  const [isCoarsePointer, setIsCoarsePointer] = useState(() => {
    if (typeof window === 'undefined') {
      return false;
    }
    return window.matchMedia('(pointer: coarse)').matches;
  });
  const [isLandscape, setIsLandscape] = useState(() => {
    if (typeof window === 'undefined') {
      return true;
    }
    return window.matchMedia('(orientation: landscape)').matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }

    const media = window.matchMedia('(orientation: landscape)');
    const update = () => setIsLandscape(media.matches);
    update();

    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', update);
      return () => media.removeEventListener('change', update);
    }

    media.addListener(update);
    return () => media.removeListener(update);
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }

    const media = window.matchMedia('(pointer: coarse)');
    const update = () => setIsCoarsePointer(media.matches);
    update();

    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', update);
      return () => media.removeEventListener('change', update);
    }

    media.addListener(update);
    return () => media.removeListener(update);
  }, []);

  useEffect(() => {
    const handleUnload = () => {
      stopNavigationOnUnload(liveNavigationSessionIdRef.current);
    };

    window.addEventListener('beforeunload', handleUnload);
    window.addEventListener('pagehide', handleUnload);

    return () => {
      window.removeEventListener('beforeunload', handleUnload);
      window.removeEventListener('pagehide', handleUnload);
    };
  }, []);

  const activeFloorIdForMap =
    currentView === 'routePlanning' || currentView === 'navigation'
      ? activeRouteFloorId || selectedFloorId
      : selectedFloorId;

  const activeFloorForMap =
    floorsById.get(activeFloorIdForMap) ??
    selectedFloor;

  const activeMapImageUrl = activeFloorForMap?.mapImageUrl ?? '';
  const activeFloorLabel = activeFloorForMap?.label ?? activeFloorIdForMap;
  const searchStores = useMemo(() => buildSearchStores(stores), [stores]);

  const filters = useMemo(() => {
    const categories = Array.from(new Set(searchStores.map((store) => store.category))).sort();
    return [ALL_FILTER, ...categories];
  }, [searchStores]);

  useEffect(() => {
    if (!filters.includes(selectedFilter)) {
      setSelectedFilter(ALL_FILTER);
    }
  }, [filters, selectedFilter]);

  const filteredStores = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase();

    return searchStores.filter((store) => {
      if (
        searchContext === 'map' &&
        !showAllSearchFloors &&
        selectedFloorId &&
        store.floorId !== selectedFloorId
      ) {
        return false;
      }

      if (selectedFilter !== ALL_FILTER && store.category !== selectedFilter) {
        return false;
      }

      if (!normalizedQuery) {
        return true;
      }

      const searchTarget = `${store.name} ${store.floor} ${store.category}`.toLowerCase();
      return searchTarget.includes(normalizedQuery);
    });
  }, [searchContext, searchQuery, searchStores, selectedFilter, selectedFloorId, showAllSearchFloors]);

  const handleStoreClick = (store: Store) => {
    setSearchQuery(store.name);

    if (searchContext === 'route-origin') {
      setOrigin(store.name);
      setOriginStore(store);
      setSelectedFloorId(store.floorId);
      setCurrentView(lastViewBeforeSearch);
      setLastViewBeforeSearch('map');
      setSearchContext('map');
      return;
    }

    if (searchContext === 'route-destination') {
      setDestination(store.name);
      setRouteDestinationStore(store);
      setSelectedFloorId(store.floorId);
      setCurrentView(lastViewBeforeSearch);
      setLastViewBeforeSearch('map');
      setSearchContext('map');
      return;
    }

    setSelectedStore(store);
    setSelectedFloorId(store.floorId);
    setCurrentView('storeDetail');
  };

  const handleMyLocationSelect = () => {
    setSearchQuery('');
    setOrigin('My location');
    setOriginStore(null);
    setCurrentView(lastViewBeforeSearch);
    setLastViewBeforeSearch('map');
    setSearchContext('map');
  };

  const handleStartRoute = () => {
    if (!selectedStore) {
      return;
    }

    setRouteDestinationStore(selectedStore);
    setDestination(selectedStore.name);
    setSelectedFloorId(selectedStore.floorId);
    setActiveRouteFloorId(selectedStore.floorId);
    setCurrentView('routePlanning');
  };

  const handleConfirmRoute = () => {
    setLiveNavigationActive(false);
    setLiveNavigationPosition(null);
    setLiveNavigationHeading(null);
    setLiveNavigationRoutePath([]);
    setLiveNavigationMethod(null);
    setLiveNavigationTrackingMode(null);
    setLiveNavigationTransitionTarget(null);
    setArViewMode('ar');
    setCurrentView('navigation');
  };

  const openSearch = (context: SearchContext = 'map') => {
    setSearchContext(context);
    setLastViewBeforeSearch(currentView);
    setShowAllSearchFloors(context !== 'map');

    if (context === 'route-origin') {
      setSearchQuery(originStore?.name ?? (origin === 'My location' ? '' : origin));
    } else if (context === 'route-destination') {
      setSearchQuery(routeDestinationStore?.name ?? destination);
    } else {
      setSearchQuery('');
    }

    setCurrentView('search');
  };

  const closeSearch = () => {
    setCurrentView(lastViewBeforeSearch);
    setLastViewBeforeSearch('map');
    setSearchContext('map');
  };

  const backToStore = () => {
    if (selectedStore) {
      setCurrentView('storeDetail');
      return;
    }

    setCurrentView('map');
  };

  const resetToMap = () => {
    setCurrentView('map');
    setShowModeMenu(false);
    setLiveNavigationTransitionTarget(null);
  };

  const swapRoutePoints = () => {
    const previousOriginStore = originStore;
    const previousDestinationStore = routeDestinationStore;
    const previousOriginLabel = origin;
    const previousDestinationLabel = destination;

    setOriginStore(previousDestinationStore);
    setRouteDestinationStore(previousOriginStore);
    setOrigin((previousDestinationStore?.name ?? previousDestinationLabel) || 'My location');
    setDestination(previousOriginStore?.name ?? previousOriginLabel);

    if (previousOriginStore) {
      setSelectedFloorId(previousOriginStore.floorId);
      setActiveRouteFloorId(previousOriginStore.floorId);
    }
  };

  const toggleModeMenu = () => {
    setShowModeMenu((previous) => !previous);
  };

  const stopLiveCameraLoop = () => {
    if (liveCameraLoopTimerRef.current !== null) {
      window.clearTimeout(liveCameraLoopTimerRef.current);
      liveCameraLoopTimerRef.current = null;
    }
    if (liveCameraRequestAbortRef.current) {
      liveCameraRequestAbortRef.current.abort();
      liveCameraRequestAbortRef.current = null;
    }
    liveCameraBusyRef.current = false;
  };

  const captureLiveCameraFrame = async (): Promise<Blob | null> => {
    const video = cameraVideoRef.current;
    if (!video || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
      return null;
    }

    const sourceWidth = video.videoWidth || 0;
    const sourceHeight = video.videoHeight || 0;
    if (sourceWidth <= 0 || sourceHeight <= 0) {
      return null;
    }

    const targetWidth = CAMERA_CALIBRATION_WIDTH;
    const targetHeight = CAMERA_CALIBRATION_HEIGHT;

    if (!liveCameraCaptureCanvasRef.current) {
      liveCameraCaptureCanvasRef.current = document.createElement('canvas');
    }
    const canvas = liveCameraCaptureCanvasRef.current;
    canvas.width = targetWidth;
    canvas.height = targetHeight;

    const context = canvas.getContext('2d', { alpha: false, desynchronized: true });
    if (!context) {
      return null;
    }

    context.drawImage(video, 0, 0, targetWidth, targetHeight);
    const frameBlob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob(resolve, 'image/jpeg', LIVE_CAMERA_JPEG_QUALITY);
    });
    return frameBlob;
  };

  const startCamera = async () => {
    if (cameraActive) {
      return;
    }

    let insecureContext = false;
    if (typeof window !== 'undefined') {
      const isSecure = window.isSecureContext;
      const host = window.location.hostname;
      const isLocalhost = LOCALHOST_HOSTS.has(host);
      if (!isSecure && !isLocalhost) {
        // Keep trying to open camera anyway; some browsers/dev setups can still allow it.
        insecureContext = true;
        setCameraError('Camera may require HTTPS URL (https://...) on this device');
      }
    }

    if (
      typeof navigator === 'undefined' ||
      !navigator.mediaDevices ||
      typeof navigator.mediaDevices.getUserMedia !== 'function'
    ) {
      setCameraError('This browser does not support camera access (getUserMedia).');
      return;
    }

    try {
      if (!insecureContext) {
        setCameraError(null);
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: 'environment' },
          aspectRatio: { ideal: 16 / 9 },
          width: { ideal: CAMERA_CALIBRATION_WIDTH },
          height: { ideal: CAMERA_CALIBRATION_HEIGHT },
        },
        audio: false,
      });

      cameraStreamRef.current = stream;
      setCameraActive(true);
      setCameraError(null);
    } catch (error) {
      console.error('Unable to start camera', error);
      setCameraError(resolveCameraErrorMessage(error));
      setCameraActive(false);
    }
  };

  const stopCamera = () => {
    stopLiveCameraLoop();

    if (cameraStreamRef.current) {
      cameraStreamRef.current.getTracks().forEach((track) => track.stop());
      cameraStreamRef.current = null;
    }

    setCameraActive(false);
    setLiveNavigationArWorld(null);

    if (cameraVideoRef.current) {
      cameraVideoRef.current.srcObject = null;
    }
  };

  const toggleCamera = () => {
    if (cameraActive) {
      stopCamera();
      return;
    }
    void startCamera();
  };

  useEffect(() => {
    liveCameraContextRef.current = {
      floorId: liveNavigationFloorId || activeFloorIdForMap || selectedFloorId || '',
      destination: routeDestinationStore?.name || destination || '',
      destinationFloor: routeDestinationStore?.floorId || '',
    };
  }, [
    activeFloorIdForMap,
    destination,
    liveNavigationFloorId,
    routeDestinationStore?.floorId,
    routeDestinationStore?.name,
    selectedFloorId,
  ]);

  useEffect(() => {
    const needsCamera =
      currentView === 'navigation' &&
      (arViewMode === 'split' || arViewMode === 'ar');

    if (needsCamera) {
      startCamera();
    } else {
      stopCamera();
      stopLiveCameraLoop();
    }

    return () => {
      stopCamera();
      stopLiveCameraLoop();
    };
  }, [currentView, arViewMode]);

  useEffect(() => {
    if (cameraActive && cameraVideoRef.current && cameraStreamRef.current) {
      cameraVideoRef.current.srcObject = cameraStreamRef.current;
      cameraVideoRef.current.play().catch(() => {
        // ignore autoplay errors
      });
    }
  }, [cameraActive, arViewMode]);

  useEffect(() => {
    const shouldRunLiveCamera =
      currentView === 'navigation' &&
      cameraActive &&
      isLandscape &&
      (arViewMode === 'split' || arViewMode === 'ar');

    if (!shouldRunLiveCamera) {
      stopLiveCameraLoop();
      if (
        currentView === 'navigation' &&
        cameraActive &&
        !isLandscape &&
        (arViewMode === 'split' || arViewMode === 'ar')
      ) {
        setLiveNavigationTrackingMode('awaiting_landscape');
      }
      return;
    }

    let cancelled = false;

    const tick = async () => {
      if (cancelled) {
        return;
      }

      if (liveCameraBusyRef.current) {
        liveCameraLoopTimerRef.current = window.setTimeout(tick, LIVE_CAMERA_CAPTURE_INTERVAL_MS);
        return;
      }

      const captureStartAt = performance.now();
      const frameBlob = await captureLiveCameraFrame();
      const extractMs = performance.now() - captureStartAt;
      if (!frameBlob) {
        liveCameraLoopTimerRef.current = window.setTimeout(tick, LIVE_CAMERA_CAPTURE_INTERVAL_MS);
        return;
      }

      liveCameraBusyRef.current = true;
      const controller = new AbortController();
      liveCameraRequestAbortRef.current = controller;
      const context = liveCameraContextRef.current;
      let perfUploadMs: number | null = null;
      let perfRequestTotalMs: number | null = null;
      let perfResponseMs: number | null = null;

      try {
        const response = await localizeLiveFrame({
          frameBlob,
          floorId: context.floorId,
          destination: context.destination,
          destinationFloor: context.destinationFloor,
          autoFloor: true,
          signal: controller.signal,
          onPerfMetrics: (metrics) => {
            perfUploadMs = Number.isFinite(metrics.uploadMs) ? metrics.uploadMs : null;
            perfRequestTotalMs = Number.isFinite(metrics.requestTotalMs) ? metrics.requestTotalMs : null;
            perfResponseMs = Number.isFinite(metrics.responseMs) ? metrics.responseMs : null;
          },
        });

        const backendTiming = response.timing;
        const backendLocalizeMs =
          typeof backendTiming?.localize_ms === 'number' && Number.isFinite(backendTiming.localize_ms)
            ? backendTiming.localize_ms
            : typeof response.localize_time === 'number' && Number.isFinite(response.localize_time)
              ? response.localize_time * 1000
              : null;
        const backendTotalMs =
          typeof backendTiming?.server_total_ms === 'number' && Number.isFinite(backendTiming.server_total_ms)
            ? backendTiming.server_total_ms
            : null;
        const backendToFrontendMs =
          perfResponseMs !== null && backendTotalMs !== null
            ? Math.max(0, perfResponseMs - backendTotalMs)
            : null;
        const decodeMs =
          typeof backendTiming?.decode_ms === 'number' && Number.isFinite(backendTiming.decode_ms)
            ? backendTiming.decode_ms
            : null;
        const routeMs =
          typeof backendTiming?.route_ms === 'number' && Number.isFinite(backendTiming.route_ms)
            ? backendTiming.route_ms
            : null;

        const formatMs = (value: number | null): string => {
          if (value === null || !Number.isFinite(value)) {
            return '-';
          }
          return `${value.toFixed(1)}ms`;
        };

        console.info(
          `[LIVE][PERF] extract=${formatMs(extractMs)} ` +
            `frontend->backend=${formatMs(perfUploadMs)} ` +
            `backend->frontend=${formatMs(backendToFrontendMs)} ` +
            `localize=${formatMs(backendLocalizeMs)} ` +
            `decode=${formatMs(decodeMs)} route=${formatMs(routeMs)} ` +
            `server_total=${formatMs(backendTotalMs)} request_total=${formatMs(perfRequestTotalMs)}`
        );

        const normalizedPath = Array.isArray(response.path)
          ? response.path
              .map((point) => {
                if (!Array.isArray(point) || point.length < 2) {
                  return null;
                }
                const px = Number(point[0]);
                const py = Number(point[1]);
                if (!Number.isFinite(px) || !Number.isFinite(py)) {
                  return null;
                }
                return [px, py] as [number, number];
              })
              .filter((point): point is [number, number] => point !== null)
          : undefined;

        if (
          response.success &&
          response.position &&
          Number.isFinite(response.position.x) &&
          Number.isFinite(response.position.y)
        ) {
          setLiveNavigationActive(true);
          applyLiveStreamUpdate({
            current_floor: response.floor_id || context.floorId,
            destination_floor: context.destinationFloor || undefined,
            method: response.method || 'live-localize',
            tracking_mode: 'camera_live',
            orientation:
              typeof response.orientation === 'number' && Number.isFinite(response.orientation)
                ? response.orientation
                : undefined,
            path: normalizedPath,
            position: response.position,
            next_transition: response.next_transition,
            transition_target: response.transition_target,
          });
          setLiveNavigationArWorld(response.ar_world ?? null);
        } else if (response.floor_id) {
          setLiveNavigationFloorId(response.floor_id);
          setActiveRouteFloorId(response.floor_id);
          setSelectedFloorId(response.floor_id);
          setLiveNavigationMethod(response.method || 'live-localize');
          setLiveNavigationTrackingMode('camera_no_fix');
          setLiveNavigationTransitionTarget(null);
          setLiveNavigationArWorld(null);
        }
      } catch (error) {
        if (!(error instanceof DOMException && error.name === 'AbortError')) {
          console.warn('Live camera localization failed:', error);
          setLiveNavigationTrackingMode('camera_error');
          setLiveNavigationArWorld(null);
        }
      } finally {
        if (liveCameraRequestAbortRef.current === controller) {
          liveCameraRequestAbortRef.current = null;
        }
        liveCameraBusyRef.current = false;
      }

      if (!cancelled) {
        liveCameraLoopTimerRef.current = window.setTimeout(tick, LIVE_CAMERA_CAPTURE_INTERVAL_MS);
      }
    };

    liveCameraLoopTimerRef.current = window.setTimeout(tick, 250);

    return () => {
      cancelled = true;
      stopLiveCameraLoop();
    };
  }, [arViewMode, cameraActive, currentView, isLandscape]);

  const routeDestinationPoint =
    routeDestinationStore && routeDestinationStore.floorId === activeFloorIdForMap
      ? { x: routeDestinationStore.x, y: routeDestinationStore.y }
      : null;

  const routeOriginPoint =
    !isOriginAutoUnresolved && effectiveOriginStore && effectiveOriginStore.floorId === activeFloorIdForMap
      ? { x: effectiveOriginStore.x, y: effectiveOriginStore.y }
      : null;

  const livePositionOnActiveFloor =
    liveNavigationPosition &&
    (!liveNavigationFloorId || liveNavigationFloorId === activeFloorIdForMap)
      ? liveNavigationPosition
      : null;

  const hasLiveRouteOnActiveFloor =
    liveNavigationRoutePath.length > 0 &&
    (!liveNavigationFloorId || liveNavigationFloorId === activeFloorIdForMap);

  const effectiveNavigationRoutePath = hasLiveRouteOnActiveFloor
    ? liveNavigationRoutePath
    : (isOriginAutoUnresolved && !livePositionOnActiveFloor)
      ? []
      : routePath;

  const navigationOriginPoint =
    isOriginAutoUnresolved && !livePositionOnActiveFloor ? null : routeOriginPoint;

  function applyLiveStreamUpdate(payload: LiveStreamPayload): void {
    const divisor = inferIncomingCoordinateDivisor(payload);
    let normalizedPosition: MapPoint | null = null;
    let convertedPath: MapPoint[] = [];

    if (payload.current_floor) {
      setLiveNavigationFloorId(payload.current_floor);
      setActiveRouteFloorId(payload.current_floor);
      setSelectedFloorId(payload.current_floor);
    }

    if (payload.position && Number.isFinite(payload.position.x) && Number.isFinite(payload.position.y)) {
      normalizedPosition = {
        x: payload.position.x / divisor,
        y: payload.position.y / divisor,
      };
      setLiveNavigationPosition(normalizedPosition);
    }

    if (Array.isArray(payload.path)) {
      convertedPath = payload.path
        .map((point) => {
          if (!Array.isArray(point) || point.length < 2) {
            return null;
          }
          const x = Number(point[0]);
          const y = Number(point[1]);
          if (!Number.isFinite(x) || !Number.isFinite(y)) {
            return null;
          }
          return { x: x / divisor, y: y / divisor };
        })
        .filter((point): point is MapPoint => point !== null);
      setLiveNavigationRoutePath(convertedPath);
    }

    if (
      payload.transition_target &&
      Number.isFinite(payload.transition_target.x) &&
      Number.isFinite(payload.transition_target.y)
    ) {
      setLiveNavigationTransitionTarget({
        node_id: payload.transition_target.node_id,
        x: Number(payload.transition_target.x) / divisor,
        y: Number(payload.transition_target.y) / divisor,
        type: payload.transition_target.type,
        name: payload.transition_target.name,
        to_floor: payload.transition_target.to_floor,
      });
    } else {
      setLiveNavigationTransitionTarget(null);
    }

    const backendHeading =
      typeof payload.orientation === 'number' && Number.isFinite(payload.orientation)
        ? normalizeDegrees(payload.orientation)
        : null;

    const previousPosition = lastLocalizedPositionRef.current;
    const motionHeading =
      normalizedPosition && previousPosition
        ? headingFromVector(
            normalizedPosition.x - previousPosition.x,
            normalizedPosition.y - previousPosition.y,
            1.2
          )
        : null;
    const pathHeading =
      normalizedPosition && convertedPath.length > 0
        ? headingFromPath(normalizedPosition, convertedPath)
        : null;

    if (normalizedPosition) {
      lastLocalizedPositionRef.current = normalizedPosition;
    }

    // Backend orientation is pose-derived and already uses MapCanvas's map
    // convention (0=east/right, 90=south/down). Motion/path headings are only
    // fallbacks when the backend did not provide an orientation.
    const targetHeading: number | null = backendHeading ?? motionHeading ?? pathHeading;

    if (targetHeading !== null) {
      setLiveNavigationHeading(normalizeDegrees(targetHeading));
    }

    setLiveNavigationMethod(payload.method ?? null);
    setLiveNavigationTrackingMode(payload.tracking_mode ?? null);
  }

  const handleVideoNavigationStart = (payload: LiveStreamPayload) => {
    liveNavigationSessionIdRef.current =
      typeof payload.session_id === 'number' && Number.isFinite(payload.session_id)
        ? payload.session_id
        : liveNavigationSessionIdRef.current;
    setLiveNavigationActive(true);
    setLiveNavigationPosition(null);
    setLiveNavigationHeading(null);
    setLiveNavigationRoutePath([]);
    setLiveNavigationMethod(null);
    setLiveNavigationTrackingMode(null);
    setLiveNavigationTransitionTarget(null);
    setCurrentView('navigation');
    setArViewMode('map');
    applyLiveStreamUpdate(payload);
  };

  const handleVideoNavigationUpdate = (payload: LiveStreamPayload) => {
    if (typeof payload.session_id === 'number' && Number.isFinite(payload.session_id)) {
      liveNavigationSessionIdRef.current = payload.session_id;
    }
    setLiveNavigationActive(true);
    setCurrentView('navigation');
    setArViewMode('map');
    applyLiveStreamUpdate(payload);
  };

  const handleVideoNavigationStop = () => {
    liveNavigationSessionIdRef.current = null;
    // Keep latest pose visible even if stream ends unexpectedly.
    if (!liveNavigationPosition) {
      setLiveNavigationActive(false);
    }
  };

  const selectedStoreMapImage =
    selectedStore && floorsById.get(selectedStore.floorId)
      ? floorsById.get(selectedStore.floorId)?.mapImageUrl ?? activeMapImageUrl
      : activeMapImageUrl;
  const immersiveCameraLayout = isCoarsePointer && currentView === 'navigation' && arViewMode === 'ar';
  const videoDemoLayout = showVideoTestPanel;

  if (loadingData) {
    return (
      <div className="flex h-[100dvh] items-center justify-center bg-paper">
        <div className="flex flex-col items-center gap-3 text-ink-3">
          <span className="h-6 w-6 animate-spin rounded-full border-2 border-line border-t-ink" />
          <p className="text-[14px]">Loading indoor map…</p>
        </div>
      </div>
    );
  }

  if (!dataset) {
    return (
      <div className="flex h-[100dvh] flex-col items-center justify-center gap-2 bg-paper px-6 text-center">
        <p className="text-[15px] font-semibold text-ink">Unable to load navigation data</p>
        {dataError && <p className="text-[13px] text-ink-3">{dataError}</p>}
      </div>
    );
  }

  return (
    <div
      className={`flex h-[100dvh] justify-center ${
        videoDemoLayout
          ? 'bg-[#05070b] sm:p-4'
          : `bg-paper-2 ${immersiveCameraLayout ? '' : 'sm:px-4 sm:py-6'}`
      }`}
    >
      <div
        className={`relative h-[100dvh] w-full overflow-hidden shadow-none ${
          videoDemoLayout
            ? 'bg-[#05070b] sm:h-[calc(100dvh-2rem)] sm:max-w-[1440px] sm:rounded-[32px] sm:shadow-2xl'
            : `bg-paper ${immersiveCameraLayout ? '' : 'sm:h-[780px] sm:max-w-[400px] sm:rounded-[40px] sm:shadow-[0_40px_80px_-30px_rgb(17_19_21/0.4)]'}`
        }`}
      >
        {!immersiveCameraLayout && !videoDemoLayout && (
          <div className="pointer-events-none absolute inset-0 z-50 hidden rounded-[40px] border border-ink/10 sm:block"></div>
        )}

        <div className={`relative h-full w-full ${videoDemoLayout ? 'bg-[#05070b]' : 'bg-paper'}`}>
          {currentView === 'navigation' ? (
            <NavigationView
              arViewMode={arViewMode}
              setArViewMode={setArViewMode}
              showModeMenu={showModeMenu}
              toggleModeMenu={toggleModeMenu}
              resetToMap={resetToMap}
              routeDestinationStore={routeDestinationStore}
              routeTime={routeTime}
              routeMeta={routeMeta}
              destination={destination}
              mapImageUrl={activeMapImageUrl}
              routePath={effectiveNavigationRoutePath}
              originPoint={navigationOriginPoint}
              destinationPoint={routeDestinationPoint}
              livePosition={livePositionOnActiveFloor}
              liveHeadingDeg={liveNavigationHeading}
              hideStaticMarkers={liveNavigationActive}
              showDestinationWhenStaticHidden={true}
              liveMethod={liveNavigationMethod}
              liveTrackingMode={liveNavigationTrackingMode}
              liveTransitionTarget={liveNavigationTransitionTarget}
              liveArWorld={liveNavigationArWorld}
              activeFloorId={activeFloorIdForMap}
              activeFloorLabel={activeFloorLabel}
              routeFloorSequence={routeFloorSequence}
              onSelectRouteFloor={setActiveRouteFloorId}
              cameraActive={cameraActive}
              cameraError={cameraError}
              cameraVideoRef={cameraVideoRef}
              toggleCamera={() => {
                setShowModeMenu(false);
                toggleCamera();
              }}
            />
          ) : currentView === 'routePlanning' ? (
            <RoutePlanningView
              origin={origin}
              destination={destination}
              routeDestinationStore={routeDestinationStore}
              routeTime={routeTime}
              routeMeta={routeMeta}
              mapImageUrl={activeMapImageUrl}
              activeFloorLabel={activeFloorLabel}
              routePath={routePath}
              originPoint={routeOriginPoint}
              destinationPoint={routeDestinationPoint}
              openSearch={openSearch}
              swapRoutePoints={swapRoutePoints}
              handleConfirmRoute={handleConfirmRoute}
              backToStore={backToStore}
              resetToMap={resetToMap}
            />
          ) : currentView === 'storeDetail' && selectedStore ? (
            <StoreDetailView
              selectedStore={selectedStore}
              mapImageUrl={selectedStoreMapImage}
              openSearch={() => openSearch()}
              resetToMap={resetToMap}
              handleStartRoute={handleStartRoute}
            />
          ) : currentView === 'search' ? (
            <SearchView
              searchQuery={searchQuery}
              setSearchQuery={setSearchQuery}
              selectedFilter={selectedFilter}
              filters={filters}
              filteredStores={filteredStores}
              showMyLocationOption={searchContext === 'route-origin'}
              handleMyLocationSelect={handleMyLocationSelect}
              allowFloorScopeToggle={searchContext === 'map'}
              showAllFloors={showAllSearchFloors}
              searchFloorLabel={selectedFloor?.label ?? selectedFloorId}
              toggleFloorScope={() => setShowAllSearchFloors((previous) => !previous)}
              closeSearch={closeSearch}
              handleStoreClick={handleStoreClick}
              setSelectedFilter={setSelectedFilter}
            />
          ) : (
            <MainMapView
              floors={floors}
              selectedFloorId={selectedFloorId}
              mapImageUrl={activeMapImageUrl}
              navGridDots={navGridDots}
              openSearch={() => openSearch()}
              onSelectFloor={setSelectedFloorId}
              onOpenVideoTest={() => setShowVideoTestPanel(true)}
            />
          )}

          <VideoTestPanel
            open={showVideoTestPanel}
            stores={stores}
            selectedFloorId={selectedFloorId}
            onNavigationStart={handleVideoNavigationStart}
            onNavigationUpdate={handleVideoNavigationUpdate}
            onNavigationStop={handleVideoNavigationStop}
            onClose={() => setShowVideoTestPanel(false)}
          />

          {dataError && (
            <div className="pointer-events-none absolute left-4 right-4 bottom-4 z-40 rounded-full bg-warn/15 px-4 py-2 text-center text-[12px] font-medium text-ink-2 backdrop-blur">
              Running with copied local data ({dataset.source}). Backend sync error: {dataError}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;

