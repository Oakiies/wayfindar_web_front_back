"""SALAD and MixVPR retrieval backends.

Their descriptors were already built for several floors by
`extract/extract_vpr_features.py`, but nothing could query them — the localizer
only knew netvlad/cosplace/megaloc, so the files sat unused. These backends
close that gap by loading the *same* models at query time.

Both sides must agree exactly or the dot-product retrieval is meaningless, so
each loader tags the model with the input size `extract_vpr_features.py` used
(`MODEL_INPUT_SIZES` there); `core.localization._global_transform_for_model`
reads that tag and rebuilds the identical Resize/ToTensor/Normalize pipeline.
Descriptors are L2-normalized on both sides.

MixVPR needs assets that are not pip-installable — a clone of
https://github.com/amaralibey/MixVPR and the official checkpoint. Paths come
from the backend config (`repo_path` / `weights_path`, relative to the project
root), defaulting to the copies already vendored in this repo.
"""
import contextlib
import sys
from pathlib import Path

import torch

from app.core.retrieval.base import RetrievalBackend
from app.core.retrieval.registry import register

ROOT = Path(__file__).resolve().parents[2]


def _resolve(p: str) -> Path:
    """Config paths are project-root relative unless given absolute."""
    path = Path(p)
    return path if path.is_absolute() else ROOT / path


def _strip_state_dict_prefixes(state_dict: dict) -> dict:
    cleaned = {}
    for key, value in state_dict.items():
        for prefix in ("model.", "module."):
            if key.startswith(prefix):
                key = key[len(prefix):]
        cleaned[key] = value
    return cleaned


@contextlib.contextmanager
def _importable(repo_path: Path, top_level: str):
    """Import `top_level` from `repo_path`, even if that name is already taken.

    SALAD (via torch.hub) and MixVPR both ship a top-level package called
    `models`. Whichever loads first wins sys.modules, and the second silently
    gets the wrong one — MixVPR's helper.get_backbone then appears to reject its
    own arguments. So: evict the name, import from this repo, put it all back.
    """
    saved_path = list(sys.path)
    saved_modules = {k: v for k, v in sys.modules.items()
                     if k == top_level or k.startswith(top_level + '.')}
    for k in saved_modules:
        del sys.modules[k]
    sys.path.insert(0, str(repo_path))
    try:
        yield
    finally:
        sys.path[:] = saved_path
        for k in [k for k in sys.modules if k == top_level or k.startswith(top_level + '.')]:
            del sys.modules[k]
        sys.modules.update(saved_modules)


def _load_checkpoint_into(model: torch.nn.Module, ckpt_path: Path) -> None:
    ckpt = torch.load(ckpt_path, map_location="cpu")
    state_dict = ckpt.get("state_dict", ckpt) if isinstance(ckpt, dict) else ckpt
    model.load_state_dict(_strip_state_dict_prefixes(state_dict), strict=True)


@register
class Salad8192Backend(RetrievalBackend):
    """DINOv2 + SALAD, 8448-dim in practice (8192 cluster + 256 token)."""

    name = 'salad8192'

    def load_model(self, data_dir: Path, cfg: dict):
        print("Loading SALAD model (DINOv2 + SALAD)...")
        repo = cfg.get('repo_path', '')
        hub_repo = str(_resolve(repo)) if repo else 'serizba/salad'
        hub_kwargs = {'source': 'local'} if repo else {}
        model = torch.hub.load(hub_repo, 'dinov2_salad', pretrained=True,
                               agg_args=None, **hub_kwargs)
        model._retrieval_backend = self.name
        model._input_size = tuple(cfg.get('input_size', (322, 322)))
        model.eval()
        return model


class _MixVPRBackend(RetrievalBackend):
    """Shared body; the two registered variants differ only in aggregator size."""

    out_channels: int
    out_rows: int

    def load_model(self, data_dir: Path, cfg: dict):
        repo_path = _resolve(cfg.get('repo_path', 'external/MixVPR'))
        ckpt_path = _resolve(cfg.get('weights_path', ''))
        if not repo_path.exists():
            raise RuntimeError(
                f"MixVPR repo not found at {repo_path}. Clone "
                "https://github.com/amaralibey/MixVPR there or set repo_path in "
                "BACKEND_CONFIGS."
            )
        if not cfg.get('weights_path') or not ckpt_path.exists():
            raise RuntimeError(
                f"MixVPR checkpoint not found at {ckpt_path}. Set weights_path in "
                "BACKEND_CONFIGS to the official pretrained checkpoint."
            )

        print(f"Loading MixVPR model (out_channels={self.out_channels}, rows={self.out_rows})...")
        with _importable(repo_path, 'models'):
            from models import helper   # provided by the MixVPR clone

            class MixVPRModel(torch.nn.Module):
                def __init__(self, agg_config):
                    super().__init__()
                    self.backbone = helper.get_backbone(
                        backbone_arch='resnet50', pretrained=True,
                        layers_to_freeze=1, layers_to_crop=[4],
                    )
                    self.aggregator = helper.get_aggregator('MixVPR', agg_config)

                def forward(self, x):
                    return self.aggregator(self.backbone(x))

            # Built inside the context: the layers must come from *this* clone.
            model = MixVPRModel({
                'in_channels': 1024, 'in_h': 20, 'in_w': 20,
                'out_channels': self.out_channels, 'mix_depth': 4,
                'mlp_ratio': 1, 'out_rows': self.out_rows,
            })
        _load_checkpoint_into(model, ckpt_path)
        model._retrieval_backend = self.name
        model._input_size = tuple(cfg.get('input_size', (320, 320)))
        model.eval()
        return model


@register
class MixVPR4096Backend(_MixVPRBackend):
    name = 'mixvpr4096'
    out_channels = 1024
    out_rows = 4


@register
class MixVPR512Backend(_MixVPRBackend):
    name = 'mixvpr512'
    out_channels = 256
    out_rows = 2
