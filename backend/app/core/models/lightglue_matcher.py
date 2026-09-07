"""LightGlue matcher — drop-in replacement for hloc's SuperGlue (HlocMatcher).

Exposes the SAME `.match(kpts0, desc0, scores0, kpts1, desc1, scores1, ...)`
signature so it can be injected into an existing Localizer at runtime:

    loc.superglue_matcher = LightGlueMatcher(...)

No core files are modified. LightGlue consumes the very same SuperPoint
keypoints/descriptors already stored in each floor's keyframe database, so the
map does NOT need rebuilding.

Speed comes from three LightGlue features (all on by default here):
  * mixed precision (fp16 autocast) on the RTX 4070 Tensor Cores
  * flash attention
  * adaptive depth/width early-stopping (LightGlue's headline trick)
"""
import numpy as np
import torch
from lightglue import LightGlue


class LightGlueMatcher:
    def __init__(self,
                 filter_threshold: float = 0.1,
                 depth_confidence: float = 0.95,
                 width_confidence: float = 0.99,
                 flash: bool = True,
                 mp: bool = True,          # mixed precision (fp16)
                 compile_model: bool = False,
                 device: str = 'auto'):
        self.device = ('cuda' if torch.cuda.is_available() else 'cpu') if device == 'auto' else device
        self.model = LightGlue(
            features='superpoint',
            filter_threshold=filter_threshold,
            depth_confidence=depth_confidence,
            width_confidence=width_confidence,
            flash=flash,
            mp=mp,
        ).eval().to(self.device)
        if compile_model:
            try:
                self.model.compile()
            except Exception as exc:
                print(f"[LightGlue] compile skipped: {exc}")
        print(f"LightGlue matcher initialized on {self.device} "
              f"(fp16={mp}, flash={flash}, adaptive={depth_confidence}/{width_confidence})")

    @staticmethod
    def _img_size(kpts, shape):
        # LightGlue normalises keypoints by image_size = [W, H]. Infer from the
        # keypoint bounding box when the true frame shape is unknown (same trick
        # the core SuperGlue wrapper uses to avoid mis-normalisation).
        if shape is not None:
            h, w = shape
        elif len(kpts):
            w = float(np.max(kpts[:, 0])) + 8.0
            h = float(np.max(kpts[:, 1])) + 8.0
        else:
            h, w = 480.0, 640.0
        return float(w), float(h)

    def match(self,
              kpts0, desc0, scores0,
              kpts1, desc1, scores1,
              image0_shape=None, image1_shape=None):
        if kpts0 is None or kpts1 is None or len(kpts0) == 0 or len(kpts1) == 0:
            return np.empty((0, 2), np.int32), np.empty((0,), np.float32)

        w0, h0 = self._img_size(kpts0, image0_shape)
        w1, h1 = self._img_size(kpts1, image1_shape)
        dev = self.device

        # desc from the DB is (N, 256) == (N, D) which is exactly what LightGlue
        # wants (no transpose, unlike SuperGlue which needed (D, N)).
        data = {
            'image0': {
                'keypoints': torch.from_numpy(np.ascontiguousarray(kpts0)).float()[None].to(dev),
                'descriptors': torch.from_numpy(np.ascontiguousarray(desc0)).float()[None].to(dev),
                'image_size': torch.tensor([[w0, h0]], dtype=torch.float32, device=dev),
            },
            'image1': {
                'keypoints': torch.from_numpy(np.ascontiguousarray(kpts1)).float()[None].to(dev),
                'descriptors': torch.from_numpy(np.ascontiguousarray(desc1)).float()[None].to(dev),
                'image_size': torch.tensor([[w1, h1]], dtype=torch.float32, device=dev),
            },
        }

        with torch.no_grad():
            pred = self.model(data)

        m0 = pred['matches0'][0].cpu().numpy()            # (N0,) -> idx in img1 or -1
        sc = pred['matching_scores0'][0].cpu().numpy()    # (N0,)
        valid = m0 > -1
        match_indices = np.stack([np.where(valid)[0], m0[valid]], axis=1).astype(np.int32)
        match_scores = sc[valid].astype(np.float32)
        return match_indices, match_scores
