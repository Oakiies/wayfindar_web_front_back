import numpy as np
import cv2
from collections import deque


def normalize_angle_deg(angle_deg):
    return float(angle_deg % 360.0)


def _wrap_rad(a: float) -> float:
    """Wrap angle to [-π, π]."""
    return float((a + np.pi) % (2 * np.pi) - np.pi)


class MedianWindowSmoother:
    """
    Sliding-window median smoother for angles.
    
    WHY MEDIAN instead of EMA:
    - A single bad PnP frame gives a wildly wrong yaw (e.g. off by 120°).
    - With EMA, that bad value bleeds into many future frames (slow decay).
    - With median, one outlier in a window of N frames has ZERO effect on the output
      as long as fewer than N/2 frames are bad.
    - When the user genuinely turns, ALL recent frames will agree → median shifts fast.
    
    This gives us: fast response to real turns + immunity to PnP outliers.
    """
    def __init__(self, window_size=7):
        # window_size: number of recent frames to keep.
        # 7 = tolerates up to 3 bad frames out of 7 while still being correct.
        self.window = deque(maxlen=window_size)
        self.last_output = None

    def update(self, angle_deg, confidence=10):
        angle_deg = normalize_angle_deg(angle_deg)

        # Low-confidence frames get lower weight by being added fewer times
        # (or we can just skip adding them if very low confidence)
        if confidence < 3:
            # Very bad frame — don't add to window, return last known good
            return self.last_output if self.last_output is not None else angle_deg

        self.window.append(angle_deg)

        if len(self.window) == 0:
            self.last_output = angle_deg
            return angle_deg

        # Circular median via sin/cos
        sins = np.sin(np.radians(list(self.window)))
        coss = np.cos(np.radians(list(self.window)))
        median_sin = np.median(sins)
        median_cos = np.median(coss)
        result = normalize_angle_deg(np.degrees(np.arctan2(median_sin, median_cos)))
        self.last_output = result
        return result


# Keep AngleSmoother as alias for backward compatibility
class AngleSmoother(MedianWindowSmoother):
    def __init__(self, alpha=0.1):
        # alpha ignored — we use window-based approach now
        super().__init__(window_size=7)


class KalmanSmoother:
    def __init__(self, process_noise=2.0, measurement_noise=100.0, min_init_frames=5):
        """
        Pixel-space Kalman Filter Parameters:
        - process_noise: 2.0 (model uncertainty - allows for walking acceleration)
        - measurement_noise: 100.0 (PnP localization variance, std ~10px)
        - min_init_frames: 5 (initialization stability)
        """
        self.kf = cv2.KalmanFilter(4, 2)
        
        # State Transition Matrix
        self.kf.transitionMatrix = np.array([
            [1, 0, 1, 0],
            [0, 1, 0, 1],
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ], dtype=np.float32)
        
        # Measurement Matrix
        self.kf.measurementMatrix = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0]
        ], dtype=np.float32)
        
        # Process Noise
        self.kf.processNoiseCov = np.eye(4, dtype=np.float32) * process_noise
        
        # Measurement Noise
        self.kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * measurement_noise
        
        # Error Covariance
        self.kf.errorCovPost = np.eye(4, dtype=np.float32) * 500.0
        
        self.is_initialized = False
        self.last_timestamp = None
        self.init_buffer = []
        self.min_init_frames = min_init_frames
        self.base_measurement_noise = measurement_noise
        
        self.prev_smoothed = None
        
        self.angle_smoother = AngleSmoother()
        
        # Separate smoother for velocity-derived heading
        self.velocity_heading_smoother = MedianWindowSmoother(window_size=5)
        
        # Minimum speed (px/sec) to trust velocity heading over PnP heading
        self.MIN_SPEED_FOR_VELOCITY_HEADING = 8.0
        self.MIN_CONFIDENCE_FOR_VELOCITY_HEADING = 12
        self.TURN_OVERRIDE_DEG = 35.0
        
        # Outlier tracking
        self.consecutive_outliers = 0
        # Shorter timeout helps recover faster after turns with phone video artifacts.
        self.MAX_CONSECUTIVE_OUTLIERS = 3

        # [FIX] Recent accepted position history for spatial consistency check
        # Tracks last N confirmed-good positions to detect ambiguous relocalization
        self.position_history = deque(maxlen=8)
        # Require fewer consistent frames so legitimate heading/trajectory changes
        # are accepted faster (important when sampling every ~1-2s).
        self.CONSISTENCY_WINDOW = 3
        self.candidate_pos = None     # (x, y) candidate for relocation
        self.candidate_count = 0      # consecutive frames that agree with candidate
        self.CANDIDATE_AGREE_DIST = 55.0  # px: candidate frames must cluster within this
        self.fast_init = False        # True = use 3 frames instead of min_init_frames

    def update(self, x, y, timestamp, confidence_score=10, measured_heading=None):
        current_measurement = np.array([[np.float32(x)], [np.float32(y)]])
        
        if not self.is_initialized:
            self.init_buffer.append((x, y))

            # [FIX] fast_init: after a forced reset due to consecutive outliers,
            # we already know the correct region so only need 3 frames to confirm.
            required = 3 if self.fast_init else self.min_init_frames

            if len(self.init_buffer) < required:
                print(f"  [Smoother] Buffering {len(self.init_buffer)}/{required} "
                      f"({'fast' if self.fast_init else 'normal'})...")
                return None, None
            
            # Robust initialization with IQR filtering
            init_data = np.array(self.init_buffer)
            median_x = np.median(init_data[:, 0])
            median_y = np.median(init_data[:, 1])
            
            # กรอง outliers ด้วย IQR
            q1_x, q3_x = np.percentile(init_data[:, 0], [25, 75])
            q1_y, q3_y = np.percentile(init_data[:, 1], [25, 75])
            iqr_x, iqr_y = q3_x - q1_x, q3_y - q1_y
            
            valid_mask = (
                (init_data[:, 0] >= q1_x - 1.5*iqr_x) & 
                (init_data[:, 0] <= q3_x + 1.5*iqr_x) &
                (init_data[:, 1] >= q1_y - 1.5*iqr_y) & 
                (init_data[:, 1] <= q3_y + 1.5*iqr_y)
            )
            
            if np.sum(valid_mask) >= 3:
                filtered_data = init_data[valid_mask]
                median_x = np.median(filtered_data[:, 0])
                median_y = np.median(filtered_data[:, 1])
            
            print(f"  [Smoother] Initialized: ({median_x:.1f}, {median_y:.1f})")
            
            self.kf.statePost = np.array([
                [np.float32(median_x)], 
                [np.float32(median_y)], 
                [0], 
                [0]
            ], dtype=np.float32)
            
            self.last_timestamp = timestamp
            self.is_initialized = True
            self.init_buffer = []
            self.fast_init = False   # reset fast-init flag after successful init
            self.prev_smoothed = (median_x, median_y)
            self.position_history.append((median_x, median_y))

            return float(median_x), float(median_y)
        
        # Calculate time delta
        dt = timestamp - self.last_timestamp
        self.last_timestamp = timestamp
        
        # Handle time gaps
        if dt > 5.0 or dt < 0:
            print("  [Smoother] Time gap detected, re-initializing...")
            self.is_initialized = False
            return self.update(x, y, timestamp, confidence_score)
        
        # Clamp dt to prevent instability, but allow slower sampling intervals
        # (e.g., 2s) to avoid lagging prediction and false outlier rejection.
        dt = max(0.01, min(dt, 3.0))
            
        # Update transition matrix
        self.kf.transitionMatrix[0, 2] = dt
        self.kf.transitionMatrix[1, 3] = dt
        
        # Predict
        prediction = self.kf.predict()
        pred_x, pred_y = prediction[0, 0], prediction[1, 0]
        
        # Adaptive measurement noise based on confidence
        # base = 100.0 (std ~10px) — scales with inlier count
        if confidence_score >= 20:
            dynamic_R = self.base_measurement_noise * 0.5    # 50 (std ~7px) - high trust
        elif confidence_score >= 15:
            dynamic_R = self.base_measurement_noise * 0.8    # 80 (std ~9px) - good trust
        elif confidence_score >= 10:
            dynamic_R = self.base_measurement_noise * 1.0    # 100 (std ~10px) - normal
        elif confidence_score >= 5:
            dynamic_R = self.base_measurement_noise * 2.0    # 200 (std ~14px) - cautious
        else:
            dynamic_R = self.base_measurement_noise * 4.0    # 400 (std ~20px) - very cautious
            
        self.kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * dynamic_R

        # ── Adaptive Outlier Gate ─────────────────────────────────────────
        # Uses Kalman's prediction error covariance to auto-scale the threshold.
        # When Kalman is uncertain → gate is WIDE → accepts movement.
        # When Kalman is confident (steady motion) → gate is TIGHT → rejects outliers.
        dist = np.sqrt((x - pred_x)**2 + (y - pred_y)**2)
        
        # Extract position uncertainty from Kalman's prediction covariance
        # errorCovPre[0,0] = variance in x, errorCovPre[1,1] = variance in y
        pred_std_x = np.sqrt(float(self.kf.errorCovPre[0, 0]))
        pred_std_y = np.sqrt(float(self.kf.errorCovPre[1, 1]))
        pred_std = np.sqrt(pred_std_x**2 + pred_std_y**2)  # combined uncertainty
        
        # Adaptive threshold = base_multiplier * prediction_uncertainty
        # - High confidence measurement → lower multiplier (trust meas more)
        # - Low confidence → higher multiplier (trust Kalman more)
        if confidence_score >= 15:
            n_sigma = 3.5   # permissive: accept if within 3.5 sigma
        elif confidence_score >= 10:
            n_sigma = 3.0   # normal
        else:
            n_sigma = 2.5   # strict for low confidence
        
        # max_dist scales with Kalman uncertainty:
        #   - Just initialized / no velocity → pred_std is large → wide gate
        #   - Moving steadily → pred_std shrinks → tight gate
        max_dist = n_sigma * pred_std
        
        # Floor: never reject anything closer than 40px (PnP noise + walking)
        # Ceiling: never accept anything beyond 150px (prevents wild jumps)
        max_dist = np.clip(max_dist, 40.0, 150.0)
        
        is_outlier = dist > max_dist
        
        print(f"  [DEBUG] meas=({x:.1f},{y:.1f}) pred=({pred_x:.1f},{pred_y:.1f}) "
              f"dist={dist:.1f} thresh={max_dist:.1f} pred_std={pred_std:.1f} "
              f"conf={confidence_score} dt={dt:.3f}")
        
        # ── Consistency Logic ─────────────────────────────────────────────

        # [FIX] Spatial consistency gate for high-confidence detections
        # Problem: high inlier count in ambiguous areas (similar corridors) can
        # cause false positive jumps.  Solution: require the new position to be
        # consistent across CONSISTENCY_WINDOW frames before accepting it.
        if is_outlier and confidence_score >= 25:
            # Check if this measurement agrees with an ongoing candidate
            if self.candidate_pos is not None:
                cand_dist = np.sqrt((x - self.candidate_pos[0])**2 +
                                    (y - self.candidate_pos[1])**2)
                if cand_dist <= self.CANDIDATE_AGREE_DIST:
                    self.candidate_count += 1
                    print(f"  [Smoother] Candidate consistent {self.candidate_count}/{self.CONSISTENCY_WINDOW}: "
                          f"dist_to_cand={cand_dist:.1f}px, conf={confidence_score}")
                    if self.candidate_count >= self.CONSISTENCY_WINDOW:
                        # Enough evidence — accept the jump
                        print(f"  [Smoother] Candidate confirmed. Jumping to ({x:.1f}, {y:.1f})")
                        is_outlier = False
                        self.candidate_pos = None
                        self.candidate_count = 0
                        # Reset Kalman state to new position so filter doesn't fight
                        self.kf.statePost = np.array([
                            [np.float32(x)], [np.float32(y)], [0], [0]
                        ], dtype=np.float32)
                        self.kf.errorCovPost = np.eye(4, dtype=np.float32) * 500.0
                else:
                    # New candidate in a different location — reset
                    self.candidate_pos = (x, y)
                    self.candidate_count = 1
                    print(f"  [Smoother] New candidate at ({x:.1f}, {y:.1f}) conf={confidence_score}")
            else:
                # First time seeing a high-confidence outlier — start tracking
                self.candidate_pos = (x, y)
                self.candidate_count = 1
                print(f"  [Smoother] Candidate started at ({x:.1f}, {y:.1f}) conf={confidence_score}")
        else:
            # Low-confidence outlier or non-outlier → clear candidate
            if not is_outlier:
                self.candidate_pos = None
                self.candidate_count = 0

        if is_outlier:
            self.consecutive_outliers += 1
            if self.consecutive_outliers >= self.MAX_CONSECUTIVE_OUTLIERS:
                print(f"  [Smoother] Max outliers reached ({self.consecutive_outliers}). "
                      f"Fast-resetting to ({x:.1f}, {y:.1f})")
                self.is_initialized = False
                self.consecutive_outliers = 0
                self.fast_init = True   # [FIX] use shorter buffer after forced reset
                return self.update(x, y, timestamp, confidence_score, measured_heading)

            print(f"  [Smoother] Outlier rejected ({self.consecutive_outliers}/{self.MAX_CONSECUTIVE_OUTLIERS}): "
                  f"dist={dist:.1f}, thresh={max_dist:.1f}, conf={confidence_score}")
            # Return last trusted position to prevent backward/phantom drift while turning.
            if self.prev_smoothed is not None:
                out_x, out_y = float(self.prev_smoothed[0]), float(self.prev_smoothed[1])
            else:
                out_x, out_y = float(pred_x), float(pred_y)

            # Return held position + hold last trusted heading
            if measured_heading is not None:
                fallback_heading = self.angle_smoother.last_output if self.angle_smoother.last_output is not None else measured_heading
                last_heading = normalize_angle_deg(fallback_heading)
                return out_x, out_y, float(last_heading)
            return out_x, out_y
            
        # If we reach here, it's not an outlier
        self.consecutive_outliers = 0
        
        # Correct
        estimated = self.kf.correct(current_measurement)
        smooth_x, smooth_y = float(estimated[0, 0]), float(estimated[1, 0])

        # Post-smooth jump check
        if self.prev_smoothed is not None:
            jump_dist = np.sqrt(
                (smooth_x - self.prev_smoothed[0])**2 +
                (smooth_y - self.prev_smoothed[1])**2
            )
            if jump_dist > 100.0:
                print(f"  [Smoother] WARNING: Large jump after smooth: {jump_dist:.1f}px")

        self.prev_smoothed = (smooth_x, smooth_y)
        self.position_history.append((smooth_x, smooth_y))  # [FIX] track accepted positions
        
        # ===== HEADING LOGIC =====
        # For this application, trust pose-derived heading first and use the
        # angle smoother to suppress single-frame yaw spikes. Velocity-based
        # heading is intentionally disabled because it lags and can point the
        # wrong way when position estimates drift.

        smooth_heading = None
        if measured_heading is not None:
            last_heading = self.angle_smoother.last_output

            if confidence_score < 3 and last_heading is not None:
                smooth_heading = last_heading
                print(f"  [Heading] HOLD-LOWCONF mode: conf={confidence_score}, heading={smooth_heading:.1f}deg")
            else:
                smooth_heading = self.angle_smoother.update(measured_heading, confidence=confidence_score)
                print(f"  [Heading] PNP-PRIMARY mode: conf={confidence_score}, heading={smooth_heading:.1f}deg")

            return float(smooth_x), float(smooth_y), normalize_angle_deg(smooth_heading)

        return float(smooth_x), float(smooth_y)


# ─────────────────────────────────────────────────────────────────────────────
# Extended Kalman Filter (unicycle motion model)
# ─────────────────────────────────────────────────────────────────────────────

class EKFSmoother:
    """
    Extended Kalman Filter with unicycle motion model.

    State:   [x, y, θ, v, ω]
    - x, y : floor-plan position (px)
    - θ    : heading (rad)
    - v    : linear speed (px/s)
    - ω    : angular velocity (rad/s)

    Process (non-linear):
        x' = x + v·cos(θ)·dt
        y' = y + v·sin(θ)·dt
        θ' = θ + ω·dt
        v' = v,  ω' = ω

    Measurement (linear, from PnP):
        z = [x_meas, y_meas, θ_meas]

    Advantage over KalmanSmoother: position and heading are filtered jointly —
    the filter knows the person moves in the direction they face, so lateral
    ghost-jumps are naturally suppressed without a separate angle smoother.
    """

    N = 5  # state dimension
    M = 3  # measurement dimension

    def __init__(
        self,
        process_noise: float = 2.0,
        measurement_noise: float = 100.0,
        min_init_frames: int = 5,
    ):
        self.Q = np.diag([
            process_noise,
            process_noise,
            np.radians(2.0) ** 2,
            1.0,
            np.radians(10.0) ** 2,
        ]).astype(np.float64)

        self.base_R_pos = float(measurement_noise)
        self.R = np.diag([
            measurement_noise,
            measurement_noise,
            np.radians(20.0) ** 2,
        ]).astype(np.float64)

        self.H = np.zeros((self.M, self.N), dtype=np.float64)
        self.H[0, 0] = 1.0
        self.H[1, 1] = 1.0
        self.H[2, 2] = 1.0

        self.state = np.zeros(self.N, dtype=np.float64)
        self.P = np.eye(self.N, dtype=np.float64) * 500.0

        self.is_initialized = False
        self.last_timestamp: float | None = None
        self.init_buffer: list = []
        self.min_init_frames = min_init_frames
        self.fast_init = False
        self.prev_smoothed: tuple | None = None
        self.consecutive_outliers = 0
        self.MAX_CONSECUTIVE_OUTLIERS = 3

    def _predict(self, dt: float) -> None:
        x, y, theta, v, omega = self.state
        self.state = np.array([
            x + v * np.cos(theta) * dt,
            y + v * np.sin(theta) * dt,
            _wrap_rad(theta + omega * dt),
            v,
            omega,
        ])
        F = np.eye(self.N, dtype=np.float64)
        F[0, 2] = -v * np.sin(theta) * dt
        F[0, 3] =  np.cos(theta) * dt
        F[1, 2] =  v * np.cos(theta) * dt
        F[1, 3] =  np.sin(theta) * dt
        F[2, 4] =  dt
        self.P = F @ self.P @ F.T + self.Q

    def _update(self, z: np.ndarray, R_scale: float = 1.0) -> None:
        R = self.R.copy()
        R[0, 0] *= R_scale
        R[1, 1] *= R_scale
        innov = z - self.H @ self.state
        innov[2] = _wrap_rad(innov[2])
        S = self.H @ self.P @ self.H.T + R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.state = self.state + K @ innov
        self.state[2] = _wrap_rad(self.state[2])
        I_KH = np.eye(self.N) - K @ self.H
        self.P = I_KH @ self.P @ I_KH.T + K @ R @ K.T

    def update(self, x, y, timestamp, confidence_score=10, measured_heading=None):
        """Same return contract as KalmanSmoother: (sx, sy) or (sx, sy, heading_deg)."""
        if not self.is_initialized:
            theta0 = np.radians(float(measured_heading)) if measured_heading is not None else 0.0
            self.init_buffer.append((float(x), float(y), theta0))
            required = 3 if self.fast_init else self.min_init_frames
            if len(self.init_buffer) < required:
                print(f"  [EKF] Buffering {len(self.init_buffer)}/{required}...")
                return (None, None, None) if measured_heading is not None else (None, None)

            buf = np.array(self.init_buffer)
            mx = float(np.median(buf[:, 0]))
            my = float(np.median(buf[:, 1]))
            mt = _wrap_rad(float(np.median(buf[:, 2])))
            self.state = np.array([mx, my, mt, 0.0, 0.0])
            self.P = np.eye(self.N, dtype=np.float64) * 500.0
            self.last_timestamp = timestamp
            self.is_initialized = True
            self.init_buffer = []
            self.fast_init = False
            sh = normalize_angle_deg(np.degrees(mt))
            self.prev_smoothed = (mx, my, sh)
            # ASCII only: this runs on the first fix of every session, and a
            # Thai-locale Windows console (cp874) cannot encode a degree sign.
            # print() then raises UnicodeEncodeError, the navigation worker
            # catches it, and the whole walk ends on frame one over a log line.
            print(f"  [EKF] Initialized: ({mx:.1f}, {my:.1f}, {sh:.1f} deg)")
            return (mx, my, sh) if measured_heading is not None else (mx, my)

        dt = float(timestamp - self.last_timestamp)
        self.last_timestamp = timestamp
        if dt > 5.0 or dt < 0:
            self.is_initialized = False
            return self.update(x, y, timestamp, confidence_score, measured_heading)
        dt = float(np.clip(dt, 0.01, 3.0))

        self._predict(dt)

        if confidence_score >= 20:
            R_scale = 0.5
        elif confidence_score >= 15:
            R_scale = 0.8
        elif confidence_score >= 10:
            R_scale = 1.0
        elif confidence_score >= 5:
            R_scale = 2.0
        else:
            R_scale = 4.0

        pred_x, pred_y = self.state[0], self.state[1]
        dist = float(np.hypot(x - pred_x, y - pred_y))
        pred_std = float(np.sqrt(self.P[0, 0] + self.P[1, 1]))
        n_sigma = 3.5 if confidence_score >= 15 else (3.0 if confidence_score >= 10 else 2.5)
        max_dist = float(np.clip(n_sigma * pred_std, 40.0, 150.0))
        is_outlier = dist > max_dist

        print(f"  [EKF] meas=({x:.1f},{y:.1f}) pred=({pred_x:.1f},{pred_y:.1f}) "
              f"dist={dist:.1f} thresh={max_dist:.1f} conf={confidence_score}")

        if is_outlier:
            self.consecutive_outliers += 1
            if self.consecutive_outliers >= self.MAX_CONSECUTIVE_OUTLIERS:
                print(f"  [EKF] Max outliers — resetting")
                self.is_initialized = False
                self.consecutive_outliers = 0
                self.fast_init = True
                return self.update(x, y, timestamp, confidence_score, measured_heading)
            print(f"  [EKF] Outlier {self.consecutive_outliers}/{self.MAX_CONSECUTIVE_OUTLIERS}")
            if self.prev_smoothed is not None:
                sx, sy, sh = self.prev_smoothed
            else:
                sx, sy = pred_x, pred_y
                sh = normalize_angle_deg(np.degrees(self.state[2]))
            return (float(sx), float(sy), float(sh)) if measured_heading is not None else (float(sx), float(sy))

        self.consecutive_outliers = 0
        theta_meas = np.radians(float(measured_heading)) if measured_heading is not None else self.state[2]
        z = np.array([float(x), float(y), float(theta_meas)])
        self._update(z, R_scale=R_scale)

        sx = float(self.state[0])
        sy = float(self.state[1])
        sh = normalize_angle_deg(np.degrees(self.state[2]))
        self.prev_smoothed = (sx, sy, sh)
        return (sx, sy, sh) if measured_heading is not None else (sx, sy)


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────

def create_smoother(cfg: dict):
    """
    Create a position smoother from a config dict.

    Expected keys:
      type              'kalman' | 'ekf'
      process_noise     float
      measurement_noise float
      min_init_frames   int
    """
    stype = (cfg.get('type') or 'kalman').lower()
    kw = dict(
        process_noise=float(cfg.get('process_noise', 2.0)),
        measurement_noise=float(cfg.get('measurement_noise', 100.0)),
        min_init_frames=int(cfg.get('min_init_frames', 5)),
    )
    if stype == 'ekf':
        return EKFSmoother(**kw)
    return KalmanSmoother(**kw)
