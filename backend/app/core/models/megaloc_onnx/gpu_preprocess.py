"""GPU-side preprocessing for the MegaLoc global descriptor.

The stock `core.extract_global_features` does PIL Resize->518 + ToTensor +
Normalize on the CPU (~11ms) before the (already fast) ONNX forward. This module
monkey-patches that function at runtime (no core file edits) to do the resize +
normalize on the GPU with torch, so the whole retrieval step stays on-device.

Only the megaloc path (input_size 518x518) is redirected; anything else falls
back to the original implementation.

    from app.core.models.megaloc_onnx.gpu_preprocess import patch, unpatch
    patch()

Ported from navigate_indoor/poc_megaloc_onnx/gpu_preprocess.py. There the
function lives in a single `core.localization` module, so patching one
attribute was enough. Here `app.core.localization` is a package: `pipeline.py`
does `from .features import extract_global_features`, which copies the name
into pipeline's own module namespace — patching only `features.py`'s attribute
would miss every call pipeline.py makes internally. So `patch()` overwrites the
name in BOTH places; `localizer.py`'s `_verify_retrieval_dim` calls the
`features` module attribute directly and picks up the same patched function.
"""
import numpy as np
import torch
import torch.nn.functional as F
from pathlib import Path
import cv2

import app.core.localization as _localization_mod

_ORIG = _localization_mod.extract_global_features
_MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
_STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)


def _gpu_extract(image_input, model):
    backend = getattr(model, '_retrieval_backend', 'netvlad')
    input_size = getattr(model, '_input_size', None)
    if backend != 'megaloc' or input_size is None:
        return _ORIG(image_input, model)

    device = next(model.parameters()).device
    if isinstance(image_input, (str, Path)):
        bgr = cv2.imread(str(image_input))
    elif isinstance(image_input, np.ndarray):
        bgr = image_input
    else:
        return _ORIG(image_input, model)

    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    t = torch.from_numpy(rgb).to(device).permute(2, 0, 1).float().div_(255.0).unsqueeze(0)
    # transforms.Resize((H,W)) -> bilinear + antialias (matches torchvision default)
    t = F.interpolate(t, size=tuple(input_size), mode='bilinear',
                      align_corners=False, antialias=True)
    t = (t - _MEAN.to(device)) / _STD.to(device)

    with torch.no_grad():
        desc = model(t)
        if isinstance(desc, (tuple, list)):
            desc = desc[0]
        if not torch.is_tensor(desc):
            desc = torch.as_tensor(desc)
        if desc.ndim > 2:
            desc = torch.flatten(desc, 1)
        if desc.ndim == 1:
            desc = desc.unsqueeze(0)
        desc = desc.detach().cpu().numpy().reshape(-1).astype(np.float32)
    n = np.linalg.norm(desc)
    return desc / n if n > 1e-7 else desc


def patch():
    _localization_mod.extract_global_features = _gpu_extract


def unpatch():
    _localization_mod.extract_global_features = _ORIG
