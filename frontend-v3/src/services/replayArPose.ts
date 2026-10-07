import type { ArWorldPayload } from './navigationTestService';

const MAX_CAUSAL_POSE_AGE_SECONDS = 0.15;

export interface ReplayArSample {
  timestamp?: number;
  current_floor?: string;
  method?: string;
  ar_world?: ArWorldPayload | null;
}

function usableReplayPose(sample: ReplayArSample): boolean {
  return !!sample.ar_world
    && sample.method !== 'HOLD_LAST_FIX'
    && (sample.ar_world.heldAge ?? 0) <= 0;
}

export function replayPoseBracket(
  samples: ReplayArSample[], time: number,
): [ReplayArSample | null, ReplayArSample | null] {
  let left: ReplayArSample | null = null;
  let right: ReplayArSample | null = null;
  for (const sample of samples) {
    if (sample.timestamp === undefined || !usableReplayPose(sample)) continue;
    if (sample.timestamp <= time) left = sample;
    else {
      right = sample;
      break;
    }
  }
  return [left, right];
}

/** Return only a pose measured at or before the presented video frame.
 * ``right`` is deliberately ignored: a future sample is not evidence for the
 * image currently on screen and must never be used to interpolate/extrapolate
 * AR. The small age gate matches the live camera transport contract.
 */
export function replayArPose(
  left: ReplayArSample | null, right: ReplayArSample | null, time: number,
): ArWorldPayload | null {
  void right;
  const a = left?.ar_world;
  if (!a || left?.timestamp === undefined || time < left.timestamp
      || left.method === 'HOLD_LAST_FIX' || (a.heldAge ?? 0) > 0) return null;
  const age = time - left.timestamp;
  return age <= MAX_CAUSAL_POSE_AGE_SECONDS ? a : null;
}
