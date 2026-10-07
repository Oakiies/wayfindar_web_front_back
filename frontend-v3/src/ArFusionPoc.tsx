import { useEffect, useRef, useState } from 'react';
import ARFloorThreeOverlay, { type ArPdrPose } from './components/ARFloorThreeOverlay';
import { buildApiUrl } from './api/client';
import { type MapPoint } from './types/navigation';
import { type ArWorldPayload } from './services/navigationTestService';
import {
  CAMERA_CALIBRATION_HEIGHT,
  CAMERA_CALIBRATION_WIDTH,
} from './lib/camera';

// Isolated AR test page: does NOT touch App.tsx/main.tsx or any production
// route — separate Vite HTML entry (ar-fusion-poc.html), separate mount
// point. Reuses the real ARFloorThreeOverlay component as-is (stylized
// fallback mode: livePosition/liveHeadingDeg only, no arWorld K/R/t) so the
// AR rendering itself is production code, not a reimplementation.
//
// The PDR + VaL fusion logic below is a direct port of the already-debugged
// vanilla JS in public/pdr-fusion-poc.html (gyro-primary heading, Weinberg
// step length, WebARNav-style confidence-weighted position+heading blend,
// front-back ambiguity defense, drift-triggered VaL calls). Ported mechanically
// to avoid re-deriving/re-breaking anything that conversation already fixed.
// Unlike that page, this one doesn't need full trajectory history for
// rendering — AR only cares about the *current* position/heading — so PDR
// state tracks a single running point instead of a path array.

const MAP_COORD_RANGE = 500;
// The floor graph is stored in roughly 500 map units across the plan. Use a
// provisional value so PDR can move the marker immediately after fix #1; the
// second fix replaces it with an observed map-units-per-metre value.
const PROVISIONAL_MAP_UNITS_PER_METER = 8;
const USER_MARKER_RADIUS = 3;
const USER_HEADING_FAN_RADIUS = 13;
// The public AR fusion PoC is calibrated against the floor 5 map. Sending it
// as an initial hint keeps cold-start localization on the intended floor while
// the backend can still auto-fallback if the frame does not match.
const POC_DEFAULT_FLOOR = 'floor5';

interface PdrState {
  gravity: { x: number; y: number; z: number };
  gravityInitialized: boolean;
  dynamic: number;
  previousDynamic: number;
  peak: number;
  peakTime: number;
  candidateValley: number;
  trailingMin: number | null;
  stepArmed: boolean;
  armTime: number;
  lastStepTime: number;
  maxRotationDuringArm: number;
  fallStreak: number;
  avgStepInterval: number | null;
  stepCount: number;
  lastStepLength: number;
  lastContinuousUpdateAt: number;
  heading: number;
  headingTarget: number;
  baseAlpha: number | null;
  lastMotionTime: number;
  warmupUntil: number;
  calibrationReadyUntil: number;
  calibrationSamples: number[];
  noiseFloor: number;
  adaptiveStepLength: number;
  peakThreshold: number;
  prominenceThreshold: number;
  minStepInterval: number;
  lastImuTime: number;
  basePeakThreshold: number;
  relax: number;
  lastEvent: string;
}

interface ValState {
  originMap: MapPoint | null;
  originPdr: MapPoint | null;
  headingOffsetRad: number | null;
  scale: number | null;
  lastFixMap: MapPoint | null;
  lastFixPdr: MapPoint | null;
  fixCount: number;
  callInFlight: boolean;
  driftSinceFix: number;
  dmax: number;
  coordDivisor: number;
  pendingFlipHeading: number | null;
  pendingFlipCount: number;
  forceHeadingOnce: boolean;
  lastFixAt: number;
  floorId: string;
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}
function normalizeAngle(angle: number): number {
  return Math.atan2(Math.sin(angle), Math.cos(angle));
}
function isFiniteAcceleration(v: DeviceMotionEventAcceleration | null): boolean {
  return !!v && Number.isFinite(v.x) && Number.isFinite(v.y) && Number.isFinite(v.z);
}
function rotateVector(dx: number, dy: number, angleRad: number): { dx: number; dy: number } {
  const cos = Math.cos(angleRad);
  const sin = Math.sin(angleRad);
  return { dx: dx * cos - dy * sin, dy: dx * sin + dy * cos };
}
// PDR heading is compass-like (0 = up, clockwise-positive), while the map
// frame uses atan2 coordinates (0 = right/east, +90 = down/south).
function pdrHeadingToMapAngle(headingRad: number): number {
  return normalizeAngle(headingRad - Math.PI / 2);
}
function inferDivisor(x: number, y: number): number {
  const maxCoordinate = Math.max(Math.abs(x), Math.abs(y));
  if (!Number.isFinite(maxCoordinate) || maxCoordinate <= MAP_COORD_RANGE * 1.1) return 1;
  return Math.max(1, Math.round(maxCoordinate / MAP_COORD_RANGE));
}

function freshPdr(): PdrState {
  return {
    gravity: { x: 0, y: 0, z: 9.81 }, gravityInitialized: false,
    dynamic: 0, previousDynamic: 0, peak: 0, peakTime: 0, candidateValley: 0, trailingMin: null,
    stepArmed: false, armTime: 0, lastStepTime: -Infinity, maxRotationDuringArm: 0, fallStreak: 0, avgStepInterval: null,
    stepCount: 0, lastStepLength: 0, lastContinuousUpdateAt: 0,
    heading: 0, headingTarget: 0, baseAlpha: null, lastMotionTime: 0,
    // Keep this short: sensor permission is requested before VaL, so the
    // motion stream can already settle while the first image is localizing.
    warmupUntil: performance.now() + 300, calibrationReadyUntil: 0, calibrationSamples: [], noiseFloor: 0,
    adaptiveStepLength: 0, peakThreshold: 0.36, prominenceThreshold: 0.09, minStepInterval: 280, lastImuTime: 0,
    basePeakThreshold: 0.36, relax: 1, lastEvent: '',
  };
}
function freshVal(dmax: number): ValState {
  return {
    originMap: null, originPdr: null, headingOffsetRad: null, scale: null,
    lastFixMap: null, lastFixPdr: null, fixCount: 0, callInFlight: false,
    driftSinceFix: 0, dmax, coordDivisor: 1,
    pendingFlipHeading: null, pendingFlipCount: 0, forceHeadingOnce: false,
    lastFixAt: 0, floorId: '',
  };
}

interface Room {
  id: string;
  name: string;
  type: string;
  floor_id: string;
  x: number;
  y: number;
}

interface LiveLocalizeResponse {
  success: boolean;
  floor_id: string;
  position: { x: number; y: number };
  orientation: number;
  path?: number[][];
  destination_coords?: { x: number; y: number } | null;
  nav_text?: string;
  num_inliers?: number;
  inlier_ratio?: number;
  localize_time?: number;
  message?: string;
  error?: string;
  ar_world_status?: string;
  // Real 6-DoF pose + poc_ar_arrow's ribbon/caret geometry — only present when
  // a destination was given (needs a route to draw along) and the pose gates
  // pass. ARFloorThreeOverlay already has a complete renderer for this exact
  // shape; falls back to the stylized livePosition/liveHeadingDeg view when
  // this is null (e.g. no destination selected, or pose quality too low).
  ar_world?: ArWorldPayload | null;
}

export default function ArFusionPoc() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const captureCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const cameraStreamRef = useRef<MediaStream | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const recordingChunksRef = useRef<Blob[]>([]);
  const recordingStartedAtRef = useRef(0);
  const recordingStartedIsoRef = useRef('');
  const recordingRef = useRef(false);
  const datasetPdrLinesRef = useRef<string[]>([]);
  const datasetLocalizationLinesRef = useRef<string[]>([]);
  const datasetDownloadUrlsRef = useRef<string[]>([]);
  const sensorsAttachedRef = useRef(false);
  const latestImuRef = useRef({ gx: 0, gy: 0, gz: 0 });
  const latestCompassAlphaDegRef = useRef<number | null>(null);
  const pdrRef = useRef<PdrState>(freshPdr());
  const pdrPosRef = useRef<MapPoint>({ x: 0, y: 0 }); // raw PDR position (metres), no history kept — AR only needs "now"
  const fusedPosRef = useRef<MapPoint>({ x: 0, y: 0 }); // fused position (metres), same frame as pdrPosRef
  const valRef = useRef<ValState>(freshVal(5));
  const runningRef = useRef(false);
  const pdrActiveRef = useRef(false);
  const rafRef = useRef(0);
  const heightCmRef = useRef(170);
  const autoStepLengthRef = useRef(true);
  const manualStepLengthRef = useRef(0.71);
  const selectedDestinationRef = useRef<Room | null>(null);
  const minimapCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const arWorldRef = useRef<ArWorldPayload | null>(null);
  const arPdrAnchorMapRef = useRef<MapPoint | null>(null);
  const arPdrPoseRef = useRef<ArPdrPose>({ deltaWorld: [0, 0, 0], deltaYawRad: 0 });
  const arPdrLastUpdateAtRef = useRef(0);
  const arPdrHeadingBaseRef = useRef<number | null>(null);
  const mapImageFloorIdRef = useRef('');
  const startupTokenRef = useRef(0);
  // mirrors of routePath/destination state for use inside tick()'s rAF closure,
  // which is captured once at start() and would otherwise read stale state —
  // livePosition/heading are recomputed fresh from refs each frame already,
  // these two just needed the same treatment.
  const routePathRef = useRef<MapPoint[]>([]);
  const destinationCoordsRef = useRef<MapPoint | null>(null);

  const [running, setRunning] = useState(false);
  const [statusText, setStatusText] = useState('READY TO START');
  const [detailText, setDetailText] = useState('');
  const [debugText, setDebugText] = useState('');
  const [livePosition, setLivePosition] = useState<MapPoint | null>(null);
  const [liveHeadingDeg, setLiveHeadingDeg] = useState<number | null>(null);
  const [routePath, setRoutePath] = useState<MapPoint[]>([]);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [destinationId, setDestinationId] = useState('');
  const [navText, setNavText] = useState('');
  const [arWorld, setArWorld] = useState<ArWorldPayload | null>(null);
  const [dmax, setDmax] = useState(5);
  const [minimapMapUrl, setMinimapMapUrl] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [datasetDownloads, setDatasetDownloads] = useState<Array<{ label: string; filename: string; url: string }>>([]);

  const arWorldHasGeometry = Boolean(
    arWorld
    && ((arWorld.carets?.length ?? 0) > 0 || (arWorld.chevrons?.length ?? 0) > 0 || (arWorld.ribbon_quads?.length ?? 0) > 0)
    && arWorld.imgWH[0] > 0
    && arWorld.imgWH[1] > 0
  );

  useEffect(() => { valRef.current.dmax = dmax; }, [dmax]);

  // Rooms list is independent of camera/PDR — load as soon as the page opens.
  useEffect(() => {
    fetch(buildApiUrl('/api/rooms?all=1'))
      .then((r) => r.json())
      .then((data) => setRooms(Array.isArray(data.rooms) ? data.rooms : []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    selectedDestinationRef.current = rooms.find((r) => r.id === destinationId) ?? null;
  }, [rooms, destinationId]);

  function getHeightStepLength(): number {
    const cm = heightCmRef.current;
    return Number.isFinite(cm) && cm >= 80 && cm <= 250 ? clamp((cm / 100) * 0.415, 0.35, 1.2) : 0.7;
  }

  function applyRelaxedThresholds(pdr: PdrState) {
    pdr.peakThreshold = clamp(pdr.basePeakThreshold * pdr.relax, 0.18, 0.65);
    pdr.prominenceThreshold = clamp(pdr.peakThreshold * 0.28, 0.07, 0.22);
  }
  function applyPdrThresholds(pdr: PdrState) {
    const noiseFloor = pdr.noiseFloor || 0.01;
    pdr.basePeakThreshold = clamp((noiseFloor * 2.2 + 0.28) / 0.8, 0.3, 0.65);
    applyRelaxedThresholds(pdr);
  }
  function updatePdrWatchdog(pdr: PdrState, timestamp: number) {
    if (!pdr.calibrationReadyUntil || timestamp < pdr.calibrationReadyUntil) return;
    const sinceStep = pdr.lastStepTime === -Infinity ? timestamp - pdr.calibrationReadyUntil : timestamp - pdr.lastStepTime;
    const sinceMotion = timestamp - pdr.lastMotionTime;
    const before = pdr.relax;
    if (sinceMotion < 400 && sinceStep > 1200) pdr.relax = clamp(pdr.relax - 0.004, 0.55, 1);
    else if (sinceStep < 400) pdr.relax = clamp(pdr.relax + 0.01, 0.55, 1);
    if (pdr.relax !== before) applyRelaxedThresholds(pdr);
  }
  function finalizePdrCalibration(pdr: PdrState) {
    if (pdr.calibrationReadyUntil) return;
    const samples = [...pdr.calibrationSamples].sort((a, b) => a - b);
    pdr.noiseFloor = Math.max(0.01, samples.length ? samples[Math.floor((samples.length - 1) * 0.95)] : 0);
    applyPdrThresholds(pdr);
    pdr.calibrationReadyUntil = performance.now() + 1200;
  }
  function getStepLength(pdr: PdrState, peak: number, valley: number): number {
    if (!autoStepLengthRef.current) return clamp(manualStepLengthRef.current || getHeightStepLength(), 0.35, 1.2);
    const amplitude = clamp(peak - valley, 0.08, 6.0);
    const weinberg = clamp((0.7 / Math.cbrt(Math.max(0.25, peak))) * Math.pow(amplitude, 0.25), 0.35, 1.2);
    const raw = clamp(weinberg * 0.65 + getHeightStepLength() * 0.35, 0.35, 1.2);
    pdr.adaptiveStepLength = clamp(pdr.adaptiveStepLength ? pdr.adaptiveStepLength * 0.65 + raw * 0.35 : raw, 0.35, 1.2);
    return pdr.adaptiveStepLength;
  }

  // Keep PDR output continuous between detected footfalls. Step detection still
  // estimates stride length, but the estimated distance is spread over the
  // user's current stride interval so the AR pose can move on every render
  // frame, matching the high-frequency PDR described by WebARNav.
  function advanceContinuousPdr(now: number) {
    if (!pdrActiveRef.current) return;
    const pdr = pdrRef.current;
    if (pdr.lastContinuousUpdateAt <= 0) {
      pdr.lastContinuousUpdateAt = now;
      return;
    }
    const dt = clamp((now - pdr.lastContinuousUpdateAt) / 1000, 0, 0.1);
    pdr.lastContinuousUpdateAt = now;
    if (dt <= 0 || pdr.lastStepLength <= 0 || !Number.isFinite(pdr.lastStepTime)) return;

    const intervalSeconds = Math.max(0.28, (pdr.avgStepInterval ?? 560) / 1000);
    const nominalSpeed = clamp(pdr.lastStepLength / intervalSeconds, 0.25, 2.2);
    // Fade the prediction out when the IMU has stopped seeing motion. This
    // prevents the high-rate extrapolation from walking away while standing.
    const motionAge = pdr.lastMotionTime > 0 ? now - pdr.lastMotionTime : Infinity;
    const motionFactor = clamp(1 - Math.max(0, motionAge - 320) / 420, 0, 1);
    const distance = nominalSpeed * motionFactor * dt;
    if (distance <= 0) return;

    const prev = pdrPosRef.current;
    const next = {
      x: prev.x + distance * Math.sin(pdr.heading),
      y: prev.y - distance * Math.cos(pdr.heading),
    };
    pdrPosRef.current = next;
    const prevFused = fusedPosRef.current;
    fusedPosRef.current = { x: prevFused.x + (next.x - prev.x), y: prevFused.y + (next.y - prev.y) };
    valRef.current.driftSinceFix += distance;
    maybeTriggerLocalize();
  }

  function registerPdrStep(pdr: PdrState, peak: number, timestamp: number) {
    const elapsed = timestamp - pdr.lastStepTime;
    if (elapsed < pdr.minStepInterval || timestamp < pdr.warmupUntil) { pdr.lastEvent = 'reject:too-fast'; return; }
    const stepLength = getStepLength(pdr, peak, pdr.candidateValley);
    if (Number.isFinite(elapsed)) pdr.avgStepInterval = pdr.avgStepInterval === null ? elapsed : pdr.avgStepInterval * 0.7 + elapsed * 0.3;
    pdr.lastStepLength = stepLength;
    pdr.lastStepTime = timestamp; pdr.stepCount += 1;
    pdr.lastEvent = `STEP #${pdr.stepCount} · ${stepLength.toFixed(2)}m`;
    maybeTriggerLocalize();
  }

  function updatePdrFromMotion(pdr: PdrState, event: DeviceMotionEvent) {
    pdr.lastEvent = '';
    const linear = isFiniteAcceleration(event.acceleration) ? event.acceleration : null;
    const acceleration = linear || (isFiniteAcceleration(event.accelerationIncludingGravity) ? event.accelerationIncludingGravity : null);
    if (!acceleration || acceleration.x === null || acceleration.y === null || acceleration.z === null) return;
    const timestamp = performance.now();
    const magnitude = Math.hypot(acceleration.x, acceleration.y, acceleration.z);
    let dynamic: number;
    if (linear) dynamic = magnitude;
    else {
      if (!pdr.gravityInitialized) { pdr.gravity = { x: acceleration.x, y: acceleration.y, z: acceleration.z }; pdr.gravityInitialized = true; }
      else { const a = 0.9; pdr.gravity.x = pdr.gravity.x * a + acceleration.x * (1 - a); pdr.gravity.y = pdr.gravity.y * a + acceleration.y * (1 - a); pdr.gravity.z = pdr.gravity.z * a + acceleration.z * (1 - a); }
      dynamic = Math.hypot(acceleration.x - pdr.gravity.x, acceleration.y - pdr.gravity.y, acceleration.z - pdr.gravity.z);
    }
    pdr.previousDynamic = pdr.dynamic; pdr.dynamic = pdr.dynamic * 0.55 + dynamic * 0.45;
    if (timestamp < pdr.warmupUntil) { if (pdr.calibrationSamples.length < 180) pdr.calibrationSamples.push(pdr.dynamic); return; }
    if (pdr.dynamic > 0.28) pdr.lastMotionTime = timestamp;
    updatePdrWatchdog(pdr, timestamp);
    pdr.trailingMin = pdr.trailingMin === null ? pdr.dynamic : Math.min(pdr.trailingMin, pdr.dynamic) + Math.max(0, pdr.dynamic - pdr.trailingMin) * 0.015;
    const rotationRateMagnitude = Math.hypot(latestImuRef.current.gx, latestImuRef.current.gy, latestImuRef.current.gz);
    if (!pdr.stepArmed) {
      const enoughTime = timestamp - pdr.lastStepTime > pdr.minStepInterval;
      if (enoughTime && pdr.dynamic > pdr.peakThreshold) {
        pdr.stepArmed = true; pdr.armTime = timestamp; pdr.candidateValley = pdr.trailingMin;
        pdr.peak = pdr.dynamic; pdr.peakTime = timestamp; pdr.maxRotationDuringArm = rotationRateMagnitude; pdr.fallStreak = 0;
        pdr.lastEvent = `arm ${pdr.dynamic.toFixed(2)}`;
      }
      return;
    }
    if (pdr.dynamic > pdr.peak) { pdr.peak = pdr.dynamic; pdr.peakTime = timestamp; pdr.fallStreak = 0; }
    else if (pdr.dynamic < pdr.previousDynamic) pdr.fallStreak += 1;
    pdr.maxRotationDuringArm = Math.max(pdr.maxRotationDuringArm, rotationRateMagnitude);
    const dropMargin = Math.max(pdr.peak * 0.15, pdr.prominenceThreshold * 0.5, 0.06);
    const droppedFromPeak = pdr.fallStreak >= 2 && pdr.peak - pdr.dynamic > dropMargin;
    if (droppedFromPeak) {
      const prominence = pdr.peak - pdr.candidateValley;
      const riseDuration = pdr.peakTime - pdr.armTime;
      const waveDuration = timestamp - pdr.armTime;
      const previousInterval = pdr.lastStepTime === -Infinity ? Infinity : pdr.peakTime - pdr.lastStepTime;
      const validShape = riseDuration >= 50 && riseDuration <= 500 && waveDuration >= 140 && waveDuration <= 950;
      const validPeak = pdr.peak > pdr.peakThreshold;
      const validProminence = prominence > pdr.prominenceThreshold;
      const validRotation = pdr.maxRotationDuringArm < 150;
      const validRhythm = pdr.avgStepInterval === null || previousInterval === Infinity || previousInterval >= pdr.avgStepInterval * 0.72;
      if (validPeak && validProminence && validShape && validRotation && validRhythm) registerPdrStep(pdr, pdr.peak, pdr.peakTime);
      else if (!validPeak) pdr.lastEvent = 'reject:weak';
      else if (!validProminence) pdr.lastEvent = 'reject:prominence';
      else if (!validShape) pdr.lastEvent = 'reject:shape';
      else if (!validRotation) pdr.lastEvent = 'reject:rotation';
      else if (!validRhythm) pdr.lastEvent = 'reject:rhythm';
      pdr.stepArmed = false; pdr.peak = 0; pdr.candidateValley = 0;
    }
  }

  function onDeviceMotion(event: DeviceMotionEvent) {
    if (!pdrActiveRef.current) return;
    const pdr = pdrRef.current;
    const linear = isFiniteAcceleration(event.acceleration) ? event.acceleration : null;
    if (!linear && !isFiniteAcceleration(event.accelerationIncludingGravity)) return;
    const rotation = event.rotationRate || ({} as DeviceMotionEventRotationRate);
    latestImuRef.current = { gx: Number(rotation.alpha || 0), gy: Number(rotation.beta || 0), gz: Number(rotation.gamma || 0) };
    // pdr.heading is CLOCKWISE-positive (matches dx=sin(θ),dy=-cos(θ) on a
    // y-down PDR-metres frame). Both W3C sources are CCW-positive, so negate —
    // see poc-pdr/note.md "แก้ mirror ที่แท้จริง" for the on-device proof.
    if (pdr.lastImuTime) {
      const dt = clamp((performance.now() - pdr.lastImuTime) / 1000, 0, 0.1);
      pdr.heading = normalizeAngle(pdr.heading - latestImuRef.current.gx * (Math.PI / 180) * dt);
    }
    pdr.lastImuTime = performance.now();
    updatePdrFromMotion(pdr, event);
  }

  function onDeviceOrientation(event: DeviceOrientationEvent) {
    if (!pdrActiveRef.current) return;
    const pdr = pdrRef.current;
    if (!Number.isFinite(event.alpha)) return;
    latestCompassAlphaDegRef.current = event.alpha;
    const alpha = (event.alpha as number) * (Math.PI / 180);
    if (pdr.baseAlpha === null) { pdr.baseAlpha = alpha; return; }
    pdr.headingTarget = normalizeAngle(pdr.baseAlpha - alpha); // paired negation with the gyro above
    const diff = normalizeAngle(pdr.headingTarget - pdr.heading);
    const weight = Math.abs(diff) > Math.PI / 3 ? 0.01 : 0.04;
    pdr.heading = normalizeAngle(pdr.heading + diff * weight);
  }

  // pdr.heading + fixed calibration → the map-space point AR should render at.
  // pdr-frame coordinates are relative (metres from session start); this
  // projects them into the same coordinate space as the backend's own
  // position.x/y, matching what ARFloorThreeOverlay/production expects.
  function toMapSpace(pdrPoint: MapPoint): MapPoint | null {
    const val = valRef.current;
    if (!val.originMap || !val.originPdr || val.headingOffsetRad === null) return null;
    const scale = val.scale ?? PROVISIONAL_MAP_UNITS_PER_METER;
    const rel = rotateVector((pdrPoint.x - val.originPdr.x) * scale, (pdrPoint.y - val.originPdr.y) * scale, val.headingOffsetRad);
    return { x: val.originMap.x + rel.dx, y: val.originMap.y + rel.dy };
  }
  function currentHeadingDeg(): number | null {
    const val = valRef.current;
    if (val.headingOffsetRad === null) return null;
    const mapAngle = pdrHeadingToMapAngle(pdrRef.current.heading) + val.headingOffsetRad;
    // inverse of the +π applied to backend orientation in applyValFix, so this
    // This is the same map convention production feeds to liveHeadingDeg.
    let deg = (mapAngle * 180) / Math.PI;
    deg = ((deg % 360) + 360) % 360;
    return deg;
  }

  function appendDatasetLine(target: { current: string[] }, payload: unknown) {
    if (!recordingRef.current || recordingStartedAtRef.current <= 0) return;
    target.current.push(`${JSON.stringify({
      tMs: Math.max(0, performance.now() - recordingStartedAtRef.current),
      ...(payload as Record<string, unknown>),
    })}\n`);
  }

  function recordLocalizationEvent(event: string, response: unknown) {
    appendDatasetLine(datasetLocalizationLinesRef, { event, response });
  }

  function recordPdrSample(now: number, mapPos: MapPoint | null) {
    if (!recordingRef.current || recordingStartedAtRef.current <= 0) return;
    const pdr = pdrRef.current;
    const val = valRef.current;
    const video = videoRef.current;
    datasetPdrLinesRef.current.push(`${JSON.stringify({
      tMs: Math.max(0, now - recordingStartedAtRef.current),
      videoTime: video?.currentTime ?? null,
      sensor: { ...latestImuRef.current, compassAlphaDeg: latestCompassAlphaDegRef.current },
      pdr: {
        x: pdrPosRef.current.x,
        y: pdrPosRef.current.y,
        headingRad: pdr.heading,
        dynamic: pdr.dynamic,
        stepCount: pdr.stepCount,
        lastStepLength: pdr.lastStepLength,
        lastEvent: pdr.lastEvent,
      },
      fused: { ...fusedPosRef.current },
      map: mapPos ? { ...mapPos } : null,
      val: {
        fixCount: val.fixCount,
        driftSinceFix: val.driftSinceFix,
        floorId: val.floorId,
        callInFlight: val.callInFlight,
      },
      arPdrPose: {
        deltaWorld: [...arPdrPoseRef.current.deltaWorld],
        deltaYawRad: arPdrPoseRef.current.deltaYawRad,
      },
    })}\n`);
  }

  function clearDatasetDownloads() {
    datasetDownloadUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    datasetDownloadUrlsRef.current = [];
    setDatasetDownloads([]);
  }

  function finishDatasetRecording(recorder: MediaRecorder, endedAt: number) {
    const startedAt = recordingStartedAtRef.current;
    const sessionId = `ar-dataset-${new Date().toISOString().replace(/[:.]/g, '-')}`;
    const mimeType = recorder.mimeType || 'video/webm';
    const extension = mimeType.includes('mp4') ? 'mp4' : 'webm';
    const videoBlob = new Blob(recordingChunksRef.current, { type: mimeType });
    const manifest = {
      schemaVersion: 1,
      sessionId,
      startedAt: recordingStartedIsoRef.current,
      durationMs: Math.max(0, endedAt - startedAt),
      videoFile: `${sessionId}.camera.${extension}`,
      pdrFile: `${sessionId}.pdr.jsonl`,
      localizationFile: `${sessionId}.localization.jsonl`,
      videoMimeType: mimeType,
      camera: {
        width: videoRef.current?.videoWidth ?? 0,
        height: videoRef.current?.videoHeight ?? 0,
        requestedWidth: CAMERA_CALIBRATION_WIDTH,
        requestedHeight: CAMERA_CALIBRATION_HEIGHT,
      },
      destination: selectedDestinationRef.current
        ? { id: selectedDestinationRef.current.id, name: selectedDestinationRef.current.name, floorId: selectedDestinationRef.current.floor_id }
        : null,
      pdrSampleCount: datasetPdrLinesRef.current.length,
      localizationEventCount: datasetLocalizationLinesRef.current.length,
      clock: 'tMs is relative to performance.now() at recording start; videoTime is the camera element clock when available.',
      page: window.location.href,
    };
    const downloads = [
      { label: 'วิดีโอกล้อง', blob: videoBlob, filename: manifest.videoFile },
      { label: 'PDR log', blob: new Blob(datasetPdrLinesRef.current, { type: 'application/x-ndjson' }), filename: manifest.pdrFile },
      { label: 'Localization log', blob: new Blob(datasetLocalizationLinesRef.current, { type: 'application/x-ndjson' }), filename: manifest.localizationFile },
      { label: 'Manifest', blob: new Blob([JSON.stringify(manifest, null, 2)], { type: 'application/json' }), filename: `${sessionId}.manifest.json` },
    ] as const;
    clearDatasetDownloads();
    const links = downloads.map(({ label, blob, filename }) => {
      const url = URL.createObjectURL(blob);
      datasetDownloadUrlsRef.current.push(url);
      return { label, filename, url };
    });
    setDatasetDownloads(links);
    recordingChunksRef.current = [];
    datasetPdrLinesRef.current = [];
    datasetLocalizationLinesRef.current = [];
    recordingStartedAtRef.current = 0;
    recordingStartedIsoRef.current = '';
    setDetailText(`dataset พร้อมดาวน์โหลด · ${manifest.pdrSampleCount} PDR samples`);
  }

  function startDatasetRecording() {
    const stream = cameraStreamRef.current;
    if (!runningRef.current || !stream) {
      setDetailText('เริ่มกล้องก่อนจึงจะบันทึก Dataset ได้');
      return;
    }
    if (typeof MediaRecorder === 'undefined') {
      setDetailText('เบราว์เซอร์นี้ไม่รองรับการบันทึกวิดีโอ');
      return;
    }
    const mimeType = [
      'video/webm;codecs=vp9',
      'video/webm;codecs=vp8',
      'video/webm',
      'video/mp4',
    ].find((type) => MediaRecorder.isTypeSupported(type)) || '';
    try {
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recordingChunksRef.current = [];
      datasetPdrLinesRef.current = [];
      datasetLocalizationLinesRef.current = [];
      clearDatasetDownloads();
      recordingStartedAtRef.current = performance.now();
      recordingStartedIsoRef.current = new Date().toISOString();
      recordingRef.current = true;
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) recordingChunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        finishDatasetRecording(recorder, performance.now());
        mediaRecorderRef.current = null;
      };
      mediaRecorderRef.current = recorder;
      recorder.start(1000);
      setRecording(true);
      setDetailText('กำลังบันทึกวิดีโอ + PDR · กดหยุดเพื่อดาวน์โหลด');
    } catch (error) {
      recordingRef.current = false;
      setDetailText(`เริ่มบันทึกไม่ได้: ${(error as Error).message}`);
    }
  }

  function stopDatasetRecording() {
    const recorder = mediaRecorderRef.current;
    if (!recorder) return;
    recordingRef.current = false;
    setRecording(false);
    if (recorder.state !== 'inactive') recorder.stop();
  }

  function applyValFix(response: LiveLocalizeResponse) {
    const val = valRef.current;
    const pdr = pdrRef.current;
    advanceContinuousPdr(performance.now());
    const currentPdrPoint = pdrPosRef.current;
    if (val.fixCount === 0) val.coordDivisor = inferDivisor(response.position.x, response.position.y);
    const mapPoint = { x: response.position.x / val.coordDivisor, y: response.position.y / val.coordDivisor };
    // +π: backend orientation's zero/handedness differs from atan2's — see
    // poc-pdr/note.md "หลัง mirror หายแล้ว: เหลือ constant 180°"
    const orientationRad = normalizeAngle((Number(response.orientation || 0) * Math.PI) / 180);
    const w2 = clamp(val.driftSinceFix / val.dmax, 0, 1);
    const w1 = 1 - w2;

    if (val.fixCount === 0) {
      val.originMap = mapPoint;
      val.originPdr = { ...currentPdrPoint };
      val.headingOffsetRad = normalizeAngle(orientationRad - pdrHeadingToMapAngle(pdr.heading));
      val.scale = PROVISIONAL_MAP_UNITS_PER_METER;
    } else {
      if (val.lastFixMap && val.lastFixPdr) {
        const mapDist = Math.hypot(mapPoint.x - val.lastFixMap.x, mapPoint.y - val.lastFixMap.y);
        const pdrDist = Math.hypot(currentPdrPoint.x - val.lastFixPdr.x, currentPdrPoint.y - val.lastFixPdr.y);
        if (pdrDist > 0.3 && mapDist > 0) {
            const newScale = mapDist / pdrDist;
            val.scale = val.fixCount === 1 || !val.scale
              ? newScale
              : val.scale * 0.5 + newScale * 0.5;
        }
      }
      // Correct pdr.heading directly, NOT headingOffsetRad — headingOffsetRad
      // is a one-time calibration; nudging it here would have no history to
      // retroactively disturb in this AR page (we don't keep a path array),
      // but keeping the same architecture as the debugged 2D PoC avoids
      // reintroducing that bug if trajectory history is ever added back.
      const impliedHeading = normalizeAngle(
        orientationRad - (val.headingOffsetRad ?? 0) + Math.PI / 2,
      );
      const headingDiff = normalizeAngle(impliedHeading - pdr.heading);
      const NEAR_180 = 2.4;
      if (val.forceHeadingOnce) {
        pdr.heading = impliedHeading;
        val.pendingFlipHeading = null; val.pendingFlipCount = 0; val.forceHeadingOnce = false;
      } else if (Math.abs(headingDiff) > NEAR_180) {
        if (val.pendingFlipHeading !== null && Math.abs(normalizeAngle(impliedHeading - val.pendingFlipHeading)) < 0.5) {
          pdr.heading = impliedHeading;
          val.pendingFlipHeading = null; val.pendingFlipCount = 0;
        } else {
          val.pendingFlipHeading = impliedHeading; val.pendingFlipCount = 1;
          pdr.heading = normalizeAngle(pdr.heading + headingDiff * w2 * 0.1);
        }
      } else {
        val.pendingFlipHeading = null; val.pendingFlipCount = 0;
        pdr.heading = normalizeAngle(pdr.heading + headingDiff * w2);
      }
    }
    val.lastFixMap = mapPoint; val.lastFixPdr = { ...currentPdrPoint }; val.fixCount += 1;

    let fixInMeters: MapPoint;
    if (val.scale && val.originMap && val.originPdr && val.headingOffsetRad !== null) {
      const rel = rotateVector(mapPoint.x - val.originMap.x, mapPoint.y - val.originMap.y, -val.headingOffsetRad);
      fixInMeters = { x: val.originPdr.x + rel.dx / val.scale, y: val.originPdr.y + rel.dy / val.scale };
    } else {
      fixInMeters = fusedPosRef.current;
    }
    const prevFused = fusedPosRef.current;
    fusedPosRef.current = { x: w1 * prevFused.x + w2 * fixInMeters.x, y: w1 * prevFused.y + w2 * fixInMeters.y };
    val.driftSinceFix = 0; val.lastFixAt = performance.now();
    val.floorId = response.floor_id || val.floorId;

    if (Array.isArray(response.path) && response.path.length > 1) {
      const scaledPath = response.path.map((p) => ({ x: p[0] / val.coordDivisor, y: p[1] / val.coordDivisor }));
      setRoutePath(scaledPath);
      routePathRef.current = scaledPath;
    }
    destinationCoordsRef.current = response.destination_coords
      ? { x: response.destination_coords.x / val.coordDivisor, y: response.destination_coords.y / val.coordDivisor }
      : null;
    loadMapImage(val.floorId);
    setNavText(response.nav_text || '');
    // Use the world-registered ribbon/caret payload produced by
    // backend/poc_ar_arrow. Its visual pose is stabilized like the PoC and is
    // refreshed on each VaL correction; the overlay applies only the PDR
    // translation bridge between corrections. A successful localization can
    // still fail the stricter AR gates, so retain the last world payload for a
    // short hold instead of clearing the scene between valid fixes.
    const receivedArWorld = response.ar_world ?? null;
    const isHeldArWorld = Boolean(receivedArWorld && Number(receivedArWorld.heldAge ?? 0) > 0);
    const nextArWorld = receivedArWorld ?? arWorldRef.current;
    if (receivedArWorld && !isHeldArWorld) {
      arWorldRef.current = receivedArWorld;
    }
    // The PDR state is anchored by the same raw VaL map point used to seed
    // fusedPosRef. The payload's pdr_anchor_map comes from the stabilized
    // camera pose and can lag response.position by a few floor-plan pixels;
    // mixing those two bases creates a false lateral translation immediately
    // after every fix (the visible symptom is an AR lane stuck to one side).
    // The payload basis still converts subsequent PDR deltas into AR world
    // coordinates; only the zero point must remain the VaL point.
    if (receivedArWorld && !isHeldArWorld) {
      arPdrAnchorMapRef.current = { ...mapPoint };
      arPdrPoseRef.current.deltaWorld = [0, 0, 0];
    }
    if (receivedArWorld && !isHeldArWorld && val.headingOffsetRad !== null) {
      const headingDir = rotateVector(
        Math.sin(pdr.heading),
        -Math.cos(pdr.heading),
        val.headingOffsetRad,
      );
      arPdrHeadingBaseRef.current = Math.atan2(headingDir.dy, headingDir.dx);
    } else if (receivedArWorld && !isHeldArWorld) {
      arPdrHeadingBaseRef.current = null;
    }
    if (receivedArWorld && !isHeldArWorld) {
      arPdrPoseRef.current.deltaYawRad = 0;
      arPdrLastUpdateAtRef.current = performance.now();
    }
    setArWorld(nextArWorld);
    const arShapeCount = nextArWorld
      ? (nextArWorld.carets?.length || nextArWorld.ribbon_quads?.length || 0)
      : 0;
    const arLabel = nextArWorld
      ? isHeldArWorld || (!receivedArWorld && arWorldRef.current)
        ? `AR HOLD (${arShapeCount})`
        : `AR READY (${arShapeCount})`
      : selectedDestinationRef.current
        ? `AR ${response.ar_world_status || 'PAYLOAD UNAVAILABLE'}`
        : 'AR WAITING FOR DESTINATION';
    setDetailText(
      `VAL FIX #${val.fixCount} · floor ${response.floor_id} · inliers ${response.num_inliers ?? '—'} (${Math.round((response.inlier_ratio ?? 0) * 100)}%) · w2=${w2.toFixed(2)} · ${arLabel}`
    );
  }

  async function captureJpegBlob(): Promise<Blob | null> {
    const video = videoRef.current;
    const canvas = captureCanvasRef.current;
    if (!video || !canvas || !cameraStreamRef.current) return null;
    const w = video.videoWidth;
    const h = video.videoHeight;
    if (!w || !h) return null;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    canvas.width = CAMERA_CALIBRATION_WIDTH;
    canvas.height = CAMERA_CALIBRATION_HEIGHT;
    if (h > w) {
      // The localization camera is calibrated in landscape. Keep the same
      // portrait-to-landscape normalization as poc_sqrtvins/mobile.html.
      // The positive rotation is important: it is the camera-to-map
      // orientation used by the working PoC on mobile browsers.
      ctx.save();
      ctx.translate(CAMERA_CALIBRATION_WIDTH / 2, CAMERA_CALIBRATION_HEIGHT / 2);
      ctx.rotate(Math.PI / 2);
      const rotatedScale = Math.max(CAMERA_CALIBRATION_WIDTH / h, CAMERA_CALIBRATION_HEIGHT / w);
      ctx.drawImage(video, -(w * rotatedScale) / 2, -(h * rotatedScale) / 2, w * rotatedScale, h * rotatedScale);
      ctx.restore();
    } else {
      ctx.drawImage(video, 0, 0, CAMERA_CALIBRATION_WIDTH, CAMERA_CALIBRATION_HEIGHT);
    }
    return new Promise((resolve) => {
      let settled = false;
      const finish = (blob: Blob | null) => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timeoutId);
        resolve(blob);
      };
      const timeoutId = window.setTimeout(() => finish(null), 5000);
      canvas.toBlob(finish, 'image/jpeg', 0.82);
    });
  }

  async function callLocalize(): Promise<LiveLocalizeResponse | null> {
    const val = valRef.current;
    if (val.callInFlight) return null;
    val.callInFlight = true;
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 20000);
    try {
      setDetailText('capturing camera frame…');
      const blob = await captureJpegBlob();
      if (!blob) {
        setDetailText('camera frame ยังไม่พร้อม — กำลังลองใหม่');
        return null;
      }
      const form = new FormData();
      form.append('frame', blob, 'frame.jpg');
      form.append('floor_id', POC_DEFAULT_FLOOR);
      form.append('auto_floor', '1');
      const room = selectedDestinationRef.current;
      if (room) { form.append('destination', room.name); form.append('destination_floor', room.floor_id); }
      const res = await fetch(buildApiUrl('/api/live-localize'), { method: 'POST', body: form, signal: controller.signal });
      if (!res.ok) throw new Error(`localize request failed (${res.status})`);
      const data: LiveLocalizeResponse = await res.json();
      if (!data.success || !data.position) {
        recordLocalizationEvent('failure', data);
        setDetailText(`VAL fail: ${data.message || data.error || 'no match'}`);
        return null;
      }
      recordLocalizationEvent('success', data);
      applyValFix(data);
      return data;
    } catch (error) {
      const message = (error as Error).name === 'AbortError'
        ? 'VAL timeout หลัง 20 วินาที — กำลังลองใหม่'
        : `VAL error: ${(error as Error).message}`;
      recordLocalizationEvent('error', { message });
      setDetailText(message);
      return null;
    } finally {
      window.clearTimeout(timeoutId);
      val.callInFlight = false;
    }
  }

  function maybeTriggerLocalize() {
    const val = valRef.current;
    // PDR is activated only after the first VaL anchor is accepted.
    if (!runningRef.current) return;
    if (!pdrActiveRef.current) return;
    if (val.fixCount === 0) return;
    if (val.callInFlight) return;
    if (val.driftSinceFix >= val.dmax) void callLocalize();
  }

  function waitForVideoReady(timeoutMs = 4000): Promise<boolean> {
    return new Promise((resolve) => {
      const start = performance.now();
      const check = () => {
        const v = videoRef.current;
        if (v && v.readyState >= 2 && v.videoWidth > 0) { resolve(true); return; }
        if (performance.now() - start > timeoutMs) { resolve(false); return; }
        window.setTimeout(check, 100);
      };
      check();
    });
  }

  async function enableCamera(): Promise<boolean> {
    try {
      const request = navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: CAMERA_CALIBRATION_WIDTH },
          height: { ideal: CAMERA_CALIBRATION_HEIGHT },
          aspectRatio: { ideal: 16 / 9 },
        },
        audio: false,
      });
      const timeout = new Promise<never>((_, reject) => window.setTimeout(() => reject(new Error('camera timed out (10s)')), 10000));
      const stream = await Promise.race([request, timeout]);
      cameraStreamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => {});
      }
      return true;
    } catch (error) {
      setDetailText(`camera error: ${(error as Error).message}`);
      return false;
    }
  }

  function enableSensors(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (!('DeviceMotionEvent' in window)) { reject(new Error('DeviceMotionEvent not supported')); return; }
      const requestPermission = (request: () => Promise<string>) =>
        Promise.race([request(), new Promise<string>((_, rej) => window.setTimeout(() => rej(new Error('sensor permission timed out')), 12000))]);
      const DME = DeviceMotionEvent as unknown as { requestPermission?: () => Promise<string> };
      const DOE = DeviceOrientationEvent as unknown as { requestPermission?: () => Promise<string> };
      const motionP = typeof DME.requestPermission === 'function' ? requestPermission(DME.requestPermission) : Promise.resolve('granted');
      motionP
        .then((motionPermission) => {
          const orientationP =
            typeof DOE.requestPermission === 'function' ? requestPermission(DOE.requestPermission) : Promise.resolve('granted');
          return orientationP.then((orientationPermission) => {
            if (motionPermission !== 'granted' || orientationPermission !== 'granted') throw new Error('sensor permission denied');
            if (!sensorsAttachedRef.current) {
              window.addEventListener('devicemotion', onDeviceMotion, true);
              window.addEventListener('deviceorientation', onDeviceOrientation, true);
              sensorsAttachedRef.current = true;
            }
            resolve();
          });
        })
        .catch(reject);
    });
  }

  function loadMapImage(floorId: string) {
    if (!floorId || floorId === mapImageFloorIdRef.current) return;
    mapImageFloorIdRef.current = floorId;
    // Keep the base map as a normal DOM image below the transparent canvas.
    // This avoids losing the map when mobile Safari delays canvas image decode.
    setMinimapMapUrl(buildApiUrl(`/api/map-image?floor_id=${encodeURIComponent(floorId)}&t=${Date.now()}`));
  }

  // Same real floor-plan + route + fused-position rendering as the debugged
  // 2D PoC's minimap (pdr-fusion-poc.html), reusing its exact heading-fan math
  // (rotateVector on the pdr-frame direction vector, not a re-derivation from
  // liveHeadingDeg degrees) so this doesn't reintroduce an already-fixed sign bug.
  function drawMinimap(mapPos: MapPoint | null) {
    const canvas = minimapCanvasRef.current;
    if (!canvas) return;
    const ratio = Math.max(1, window.devicePixelRatio || 1);
    const cssSize = canvas.clientWidth || 130;
    const backingSize = Math.round(cssSize * ratio);
    if (canvas.width !== backingSize || canvas.height !== backingSize) { canvas.width = backingSize; canvas.height = backingSize; }
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, cssSize, cssSize);

    const mapScale = cssSize / MAP_COORD_RANGE;
    const mapOrigin = { x: (cssSize - MAP_COORD_RANGE * mapScale) / 2, y: (cssSize - MAP_COORD_RANGE * mapScale) / 2 };
    const toScreen = (p: MapPoint) => ({ x: mapOrigin.x + p.x * mapScale, y: mapOrigin.y + p.y * mapScale });

    const routeNow = routePathRef.current;
    if (routeNow.length > 1) {
      ctx.beginPath();
      routeNow.forEach((p, i) => { const q = toScreen(p); if (i === 0) ctx.moveTo(q.x, q.y); else ctx.lineTo(q.x, q.y); });
      ctx.strokeStyle = 'rgba(244,114,182,.85)'; ctx.lineWidth = 2; ctx.setLineDash([2, 5]); ctx.lineCap = 'round'; ctx.stroke(); ctx.setLineDash([]);
    }
    const dest = destinationCoordsRef.current;
    if (dest) {
      const q = toScreen(dest);
      ctx.fillStyle = '#f472b6'; ctx.beginPath(); ctx.arc(q.x, q.y, 4, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = '#fff'; ctx.lineWidth = 1; ctx.stroke();
    }
    if (mapPos) {
      const q = toScreen(mapPos);
      const val = valRef.current;
      const pdr = pdrRef.current;
      if (val.headingOffsetRad !== null) {
        const dir = rotateVector(Math.sin(pdr.heading), -Math.cos(pdr.heading), val.headingOffsetRad);
        const angle = Math.atan2(dir.dy, dir.dx);
        const fanRadius = USER_HEADING_FAN_RADIUS, halfAngle = (32 * Math.PI) / 180;
        ctx.save(); ctx.translate(q.x, q.y);
        ctx.beginPath(); ctx.moveTo(0, 0); ctx.arc(0, 0, fanRadius, angle - halfAngle, angle + halfAngle); ctx.closePath();
        ctx.fillStyle = '#0d6efd'; ctx.globalAlpha = 0.32; ctx.fill();
        ctx.globalAlpha = 0.62; ctx.strokeStyle = '#0d6efd'; ctx.lineWidth = 1.2; ctx.stroke();
        ctx.globalAlpha = 1;
        ctx.restore();
      }
      ctx.beginPath(); ctx.arc(q.x, q.y, USER_MARKER_RADIUS, 0, Math.PI * 2); ctx.fillStyle = '#0d6efd'; ctx.fill();
    }
  }

  function updateArPdrPose(mapPos: MapPoint | null) {
    const world = arWorldRef.current;
    const anchor = arPdrAnchorMapRef.current;
    const xAxis = world?.pdr_map_x_axis_world;
    const yAxis = world?.pdr_map_y_axis_world;
    if (!world || !anchor || !mapPos || !xAxis || !yAxis) {
      arPdrPoseRef.current.deltaWorld = [0, 0, 0];
      arPdrPoseRef.current.deltaYawRad = 0;
      arPdrLastUpdateAtRef.current = performance.now();
      return;
    }
    // mapPos is normalized for the minimap, while the backend basis vectors
    // are per raw floor-plan pixel.
    const divisor = valRef.current.coordDivisor || 1;
    const dx = (mapPos.x - anchor.x) * divisor;
    const dy = (mapPos.y - anchor.y) * divisor;
    const targetDelta: [number, number, number] = [
      xAxis[0] * dx + yAxis[0] * dy,
      xAxis[1] * dx + yAxis[1] * dy,
      xAxis[2] * dx + yAxis[2] * dy,
    ];
    // Step detection updates PDR at footfall boundaries. Follow the target
    // over a short time constant so AR moves with the walk instead of jumping
    // once per detected step.
    const now = performance.now();
    const dt = arPdrLastUpdateAtRef.current > 0
      ? clamp((now - arPdrLastUpdateAtRef.current) / 1000, 0, 0.2)
      : 1 / 60;
    arPdrLastUpdateAtRef.current = now;
    const follow = 1 - Math.exp(-dt / 0.12);
    const current = arPdrPoseRef.current.deltaWorld;
    arPdrPoseRef.current.deltaWorld = [
      current[0] + (targetDelta[0] - current[0]) * follow,
      current[1] + (targetDelta[1] - current[1]) * follow,
      current[2] + (targetDelta[2] - current[2]) * follow,
    ];

    // Keep the registered route fixed while the phone rotates between visual
    // fixes. The heading delta is measured in the same y-down map frame used
    // by toMapSpace() and is applied around the payload's floor normal by the
    // AR renderer.
    const val = valRef.current;
    if (val.headingOffsetRad !== null && arPdrHeadingBaseRef.current !== null) {
      const headingDir = rotateVector(
        Math.sin(pdrRef.current.heading),
        -Math.cos(pdrRef.current.heading),
        val.headingOffsetRad,
      );
      const currentMapHeading = Math.atan2(headingDir.dy, headingDir.dx);
      const targetYaw = normalizeAngle(currentMapHeading - arPdrHeadingBaseRef.current);
      const currentYaw = arPdrPoseRef.current.deltaYawRad;
      const yawError = normalizeAngle(targetYaw - currentYaw);
      // Compass correction is intentionally weak indoors. Ignore sub-degree
      // changes so magnetic noise does not make a straight route wobble.
      const yawDeadband = (1.0 * Math.PI) / 180;
      arPdrPoseRef.current.deltaYawRad = Math.abs(yawError) < yawDeadband
        ? currentYaw
        : currentYaw + yawError * follow;
    } else {
      arPdrPoseRef.current.deltaYawRad = 0;
    }
  }

  function tick() {
    if (!runningRef.current) return;
    const pdr = pdrRef.current;
    const now = performance.now();
    advanceContinuousPdr(now);
    if (pdrActiveRef.current && now >= pdr.warmupUntil && !pdr.calibrationReadyUntil) finalizePdrCalibration(pdr);
    const mapPos = toMapSpace(fusedPosRef.current);
    updateArPdrPose(mapPos);
    recordPdrSample(now, mapPos);
    setLivePosition(mapPos);
    setLiveHeadingDeg(currentHeadingDeg());
    drawMinimap(mapPos);
    const val = valRef.current;
    const alpha = latestCompassAlphaDegRef.current;
    setDebugText(
      `steps ${pdr.stepCount} · α${alpha === null ? '—' : Math.round(alpha)}° pdr${Math.round((normalizeAngle(pdr.heading) * 180) / Math.PI)}° · drift ${val.driftSinceFix.toFixed(1)}/${val.dmax}m · fixes ${val.fixCount}`
    );
    rafRef.current = requestAnimationFrame(tick);
  }

  async function start() {
    if (runningRef.current) { stop(); return; }
    const startupToken = ++startupTokenRef.current;
    setStatusText('LOCALIZING · PDR OFF');
    pdrActiveRef.current = false;
    pdrRef.current = freshPdr();
    valRef.current = freshVal(dmax);
    pdrPosRef.current = { x: 0, y: 0 };
    fusedPosRef.current = { x: 0, y: 0 };
    setRoutePath([]); setNavText(''); setDetailText(''); setArWorld(null);
    arWorldRef.current = null;
    arPdrAnchorMapRef.current = null;
    arPdrPoseRef.current.deltaWorld = [0, 0, 0];
    arPdrPoseRef.current.deltaYawRad = 0;
    arPdrHeadingBaseRef.current = null;
    arPdrLastUpdateAtRef.current = 0;
    setLivePosition(null); setLiveHeadingDeg(null);
    routePathRef.current = []; destinationCoordsRef.current = null;
    mapImageFloorIdRef.current = ''; setMinimapMapUrl(null);
    // Keep the render loop alive for startup feedback. PDR remains spatially
    // unanchored until VaL returns, but collecting sensor samples now avoids
    // a second warmup gap after the first localization fix.
    runningRef.current = true; setRunning(true);
    rafRef.current = requestAnimationFrame(tick);
    // Show the calibrated base map immediately; the position/route overlay is
    // added after the first successful localization fix.
    loadMapImage(POC_DEFAULT_FLOOR);

    // Mobile Safari requires sensor permission to be requested synchronously
    // from the start-button gesture. Once granted, process motion immediately;
    // maybeTriggerLocalize() still prevents any PDR-driven request before the
    // first VaL anchor exists.
    let sensorReady = false;
    try {
      await enableSensors();
      sensorReady = true;
      pdrActiveRef.current = true;
    } catch (error) {
      setStatusText('SENSOR ERROR · PDR OFF');
      setDetailText((error as Error).message);
    }
    if (startupToken !== startupTokenRef.current) return;

    setStatusText('REQUESTING CAMERA');
    const cameraOk = await enableCamera();
    if (startupToken !== startupTokenRef.current) return;
    if (!cameraOk) {
      stop();
      setStatusText('CAMERA ERROR');
      return;
    }

    setStatusText('LOCALIZING · PDR OFF');
    await waitForVideoReady();
    let initialFix: LiveLocalizeResponse | null = null;
    for (let attempt = 1; attempt <= 4 && !initialFix; attempt++) {
      setDetailText(`full localize — attempt ${attempt}/4…`);
      initialFix = await callLocalize();
      if (!initialFix && attempt < 4) await new Promise((r) => window.setTimeout(r, 500));
    }
    if (startupToken !== startupTokenRef.current) return;
    if (!initialFix) {
      stop();
      setStatusText('LOCALIZE FAILED'); setDetailText('หาตำแหน่งเริ่มต้นไม่สำเร็จหลัง 4 ครั้ง — กด เริ่ม ใหม่');
      return;
    }

    if (startupToken !== startupTokenRef.current || !runningRef.current) return;

    // The first VaL fix anchors the PDR position accumulated since the button
    // press. Do not recreate freshPdr here: doing so discarded the settled
    // sensor state and made the first visible step arrive late.
    if (sensorReady) {
      pdrActiveRef.current = true;
      setStatusText('PDR ACTIVE · AR TRACKING');
    } else {
      setStatusText('AR STATIC · SENSOR ERROR');
      setDetailText('ตำแหน่งเริ่มต้นพร้อมแล้ว แต่ PDR ใช้งานไม่ได้ — ตรวจสิทธิ์ Motion/Orientation แล้วเริ่มใหม่');
    }
  }

  function stop() {
    startupTokenRef.current += 1;
    stopDatasetRecording();
    pdrActiveRef.current = false;
    runningRef.current = false; setRunning(false);
    cancelAnimationFrame(rafRef.current);
    if (sensorsAttachedRef.current) {
      window.removeEventListener('devicemotion', onDeviceMotion, true);
      window.removeEventListener('deviceorientation', onDeviceOrientation, true);
      sensorsAttachedRef.current = false;
    }
    if (cameraStreamRef.current) { cameraStreamRef.current.getTracks().forEach((t) => t.stop()); cameraStreamRef.current = null; }
    arWorldRef.current = null;
    arPdrAnchorMapRef.current = null;
    arPdrPoseRef.current.deltaWorld = [0, 0, 0];
    arPdrPoseRef.current.deltaYawRad = 0;
    arPdrHeadingBaseRef.current = null;
    arPdrLastUpdateAtRef.current = 0;
    setStatusText('READY TO START'); setLivePosition(null); setLiveHeadingDeg(null);
    mapImageFloorIdRef.current = ''; setMinimapMapUrl(null);
  }

  function handleDestinationChange(nextId: string) {
    const nextRoom = rooms.find((room) => room.id === nextId) ?? null;
    selectedDestinationRef.current = nextRoom;
    setDestinationId(nextId);
    if (!runningRef.current) return;

    // A destination can be selected after the initial fix. Re-localize now so
    // the backend can build route geometry; waiting for the next PDR drift
    // threshold made the AR layer look permanently absent.
    if (nextRoom) {
      setDetailText('กำลังสร้างเส้นทาง AR…');
      window.setTimeout(() => { void callLocalize(); }, 0);
    } else {
      arWorldRef.current = null;
      setArWorld(null);
      setRoutePath([]);
      routePathRef.current = [];
      setNavText('');
    }
  }

  useEffect(() => () => stop(), []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div style={{ position: 'fixed', inset: 0, background: '#000', overflow: 'hidden', fontFamily: 'system-ui, sans-serif' }}>
      <video ref={videoRef} autoPlay muted playsInline style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} />
      <canvas ref={captureCanvasRef} style={{ display: 'none' }} />
      <div style={{ position: 'absolute', inset: 0 }}>
        <ARFloorThreeOverlay
          routePath={routePath}
          livePosition={livePosition}
          liveHeadingDeg={liveHeadingDeg}
          enabled={running}
          videoRef={videoRef}
          videoFit="cover"
          arWorld={arWorld}
          pdrPoseRef={arPdrPoseRef}
          // This page must show only the world-registered AR from
          // poc_ar_arrow. Do not draw the screen-space fallback route.
          strictWorldAr
        />
      </div>

      {minimapMapUrl && (
        <div
          style={{
            position: 'fixed', top: 12, right: 12, width: 130, height: 130, zIndex: 60,
            overflow: 'hidden', borderRadius: 10, border: '2px solid rgba(148,163,184,.45)',
            boxShadow: '0 8px 22px rgba(0,0,0,.55)', background: '#0a1323',
          }}
          aria-label="แผนที่ย่อ"
        >
          {minimapMapUrl && (
            <img
              src={minimapMapUrl}
              alt="แผนที่ชั้นปัจจุบัน"
              style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'fill' }}
            />
          )}
          <canvas
            ref={minimapCanvasRef}
            style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
          />
        </div>
      )}

      {navText && (
        <div style={{ position: 'fixed', top: 12, left: '50%', transform: 'translateX(-50%)', padding: '8px 18px', borderRadius: 999, background: 'rgba(7,12,21,.82)', backdropFilter: 'blur(6px)', color: '#e5eefc', fontWeight: 700, zIndex: 60 }}>
          {navText}
        </div>
      )}

      {running && (
        <div
          style={{
            position: 'fixed', top: navText ? 54 : 12, left: '50%', transform: 'translateX(-50%)',
            padding: '6px 12px', borderRadius: 999, zIndex: 60,
            background: 'rgba(7,12,21,.76)', backdropFilter: 'blur(6px)',
            color: arWorld ? '#b4ecff' : destinationId ? '#fde68a' : '#fbbf24',
            font: '11px ui-monospace,monospace', whiteSpace: 'nowrap',
          }}
        >
          {arWorldHasGeometry
            ? 'AR WORLD READY'
            : destinationId
              ? 'AR WAITING FOR WORLD POSE'
              : 'AR WAITING — SELECT DESTINATION'}
        </div>
      )}

      {datasetDownloads.length > 0 && !recording && (
        <div style={{ position: 'fixed', left: 12, right: 12, bottom: 94, zIndex: 70, padding: 10, borderRadius: 12, background: 'rgba(7,12,21,.94)', border: '1px solid rgba(96,165,250,.55)', color: '#e5eefc', boxShadow: '0 10px 30px rgba(0,0,0,.45)' }}>
          <div style={{ fontWeight: 700, fontSize: 12, marginBottom: 7 }}>Dataset พร้อมดาวน์โหลด</div>
          {datasetDownloads[0] && (
            <video
              src={datasetDownloads[0].url}
              controls
              playsInline
              style={{ display: 'block', width: '100%', maxHeight: 150, borderRadius: 7, background: '#000', marginBottom: 8 }}
            />
          )}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {datasetDownloads.map((file) => (
              <a
                key={file.filename}
                href={file.url}
                download={file.filename}
                style={{ padding: '7px 9px', borderRadius: 7, background: '#2563eb', color: '#fff', fontSize: 11, fontWeight: 700, textDecoration: 'none' }}
              >
                ดาวน์โหลด {file.label}
              </a>
            ))}
          </div>
        </div>
      )}

      <div style={{ position: 'fixed', top: 12, left: 12, zIndex: 60, display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', borderRadius: 999, background: 'rgba(12,23,40,.75)', color: '#8da0b9', font: '10px ui-monospace,monospace' }}>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: running ? '#4ade80' : '#64748b' }} />
        {statusText}
      </div>

      <div style={{ position: 'fixed', left: 12, right: 12, bottom: 10, zIndex: 60, background: 'rgba(7,12,21,.82)', backdropFilter: 'blur(6px)', borderRadius: 10, padding: '6px 10px', color: '#8da0b9', font: '11px ui-monospace,monospace', textAlign: 'center', overflowX: 'auto', whiteSpace: 'nowrap' }}>
        {[detailText, debugText].filter(Boolean).join(' · ') || 'PDR + VaL fusion driving the real ARFloorThreeOverlay — waiting for AR payload'}
      </div>

      <div style={{ position: 'fixed', left: 12, right: 12, bottom: 46, zIndex: 60, display: 'flex', gap: 8, alignItems: 'center' }}>
        <select
          value={destinationId}
          onChange={(e) => handleDestinationChange(e.target.value)}
          style={{ flex: 1, minWidth: 0, padding: '8px 6px', borderRadius: 8, background: 'rgba(7,12,21,.85)', color: '#e5eefc', border: '1px solid rgba(148,163,184,.3)', fontSize: 12 }}
        >
          <option value="">— ไม่เลือกปลายทาง —</option>
          {rooms.map((r) => (
            <option key={r.id} value={r.id}>{r.name} · {r.floor_id}</option>
          ))}
        </select>
        <input
          type="number" min={1} max={30} step={0.5} value={dmax}
          onChange={(e) => setDmax(Number(e.target.value) || 5)}
          style={{ width: 56, padding: '8px 4px', borderRadius: 8, background: 'rgba(7,12,21,.85)', color: '#e5eefc', border: '1px solid rgba(148,163,184,.3)', fontSize: 12, textAlign: 'center' }}
          title="drift budget (m)"
        />
        <button
          onClick={() => void start()}
          style={{ minHeight: 40, padding: '8px 16px', borderRadius: 8, border: 'none', background: running ? '#334155' : '#4ade80', color: running ? '#e5eefc' : '#052e16', fontWeight: 700, cursor: 'pointer' }}
        >
          {running ? 'หยุด' : 'เริ่ม'}
        </button>
        <button
          onClick={() => (recording ? stopDatasetRecording() : startDatasetRecording())}
          disabled={!running && !recording}
          style={{ minHeight: 40, padding: '8px 12px', borderRadius: 8, border: `1px solid ${recording ? '#fca5a5' : '#64748b'}`, background: recording ? '#dc2626' : 'rgba(7,12,21,.86)', color: '#fff', fontWeight: 700, cursor: running || recording ? 'pointer' : 'not-allowed', opacity: running || recording ? 1 : 0.45, whiteSpace: 'nowrap' }}
        >
          {recording ? 'หยุดและดาวน์โหลด' : 'บันทึก Dataset'}
        </button>
      </div>
    </div>
  );
}
