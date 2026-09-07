"""Accelerated inference wiring (enabled by default via NAV_ACCEL=1).

Applies the validated fast stack to a localizer at creation time, WITHOUT editing
the core localization code:
  * SuperGlue  -> LightGlue            (app.core.models.lightglue_matcher)
  * optional torch MegaLoc -> ONNX MegaLoc fp16 (one shared session)
  * PIL/CPU preprocess -> GPU preprocess (monkey-patch extract_global_features)
  * top_k -> config.ACCEL_TOP_K

LightGlue is required when accelerated mode is enabled. ONNX MegaLoc is an
optional acceleration of the same MegaLoc model; it is disabled at startup by
default because ONNX session construction can be slower than Torch loading.
Set NAV_ACCEL_ONNX=1 only after measuring a win on the deployment machine. If
CUDA execution is not available, the code keeps the torch MegaLoc model rather
than changing retrieval backends.

Set NAV_ACCEL=0 only for an intentional legacy comparison run.
"""
import os
import threading

import app.config as config

_MEGA_ONNX = str(config.DATA_DIR_ROOT / 'models' / 'megaloc_fp16.onnx')
_USE_ONNX_AT_STARTUP = os.getenv('NAV_ACCEL_ONNX', '0').strip().lower() in {
    '1', 'true', 'yes', 'on'
}

_lock = threading.Lock()
_global_applied = False
_shared_onnx_mega = None


def _apply_global():
    """One-time: enable GPU preprocessing and set top_k. Idempotent."""
    global _global_applied
    if _global_applied:
        return
    try:
        import app.core.models.megaloc_onnx.gpu_preprocess as gp
        gp.patch()
        print("[ACCEL] MegaLoc GPU preprocessing enabled")
    except Exception as exc:
        print(f"[ACCEL] gpu_preprocess unavailable ({exc}); using CPU preprocess")
    try:
        import app.localization_config as lc
        lc.LOCALIZATION_PARAMS['top_k'] = config.ACCEL_TOP_K
        print(f"[ACCEL] top_k = {config.ACCEL_TOP_K}")
    except Exception as exc:
        print(f"[ACCEL] could not set top_k ({exc})")
    _global_applied = True


def _get_onnx_mega():
    """Shared ONNX-MegaLoc session (model is floor-independent -> one instance)."""
    global _shared_onnx_mega
    if _shared_onnx_mega is None:
        from app.core.models.megaloc_onnx.onnx_megaloc import OnnxMegaLoc
        _shared_onnx_mega = OnnxMegaLoc(_MEGA_ONNX)
    return _shared_onnx_mega


def accelerate_localizer(loc):
    """Swap in the fast components on an already-built Localizer (idempotent)."""
    if not config.ACCEL_MODE:
        return loc
    with _lock:
        _apply_global()

        # SuperGlue -> LightGlue. The Localizer has already required a
        # SuperPoint map, so silently keeping SuperGlue would violate the
        # requested production stack.
        if getattr(loc, 'matching_mode', None) == 'superpoint' \
                and getattr(loc, 'superglue_matcher', None) is not None:
            try:
                from app.core.models.lightglue_matcher import LightGlueMatcher
                if not isinstance(loc.superglue_matcher, LightGlueMatcher):
                    loc.superglue_matcher = LightGlueMatcher(mp=True, flash=True)
                    print(f"[ACCEL] {loc.floor_id}: SuperGlue -> LightGlue")
            except Exception as exc:
                raise RuntimeError(
                    f"LightGlue is required for the accelerated stack on {loc.floor_id}: {exc}"
                ) from exc
        elif getattr(loc, 'matching_mode', None) == 'superpoint':
            raise RuntimeError(
                f"SuperPoint is active on {loc.floor_id}, but no matcher is available; "
                "LightGlue is required and SuperGlue fallback is disabled."
            )

        # torch MegaLoc -> shared ONNX MegaLoc — ONLY if the ONNX session actually
        # runs on CUDA. On CPU it is ~476ms (SLOWER than torch on GPU ~49ms), so in
        # that case keep torch MegaLoc.
        if (
            _USE_ONNX_AT_STARTUP
            and getattr(loc, 'retrieval_mode', None) == 'megaloc'
            and os.path.exists(_MEGA_ONNX)
        ):
            try:
                if loc.retrieval_model.__class__.__name__ != 'OnnxMegaLoc':
                    onnx_m = _get_onnx_mega()
                    if getattr(onnx_m, 'on_cuda', False):
                        loc.retrieval_model = onnx_m
                        loc.netvlad_model = onnx_m
                        print(f"[ACCEL] {loc.floor_id}: MegaLoc torch -> ONNX fp16")
                    else:
                        print(f"[ACCEL] {loc.floor_id}: ONNX on CPU — keeping torch MegaLoc "
                              f"(GPU, faster). Fix: onnxruntime-gpu==1.20.1 (CUDA-12).")
            except Exception as exc:
                print(f"[ACCEL] {loc.floor_id}: ONNX MegaLoc unavailable, keeping torch ({exc})")
    return loc
