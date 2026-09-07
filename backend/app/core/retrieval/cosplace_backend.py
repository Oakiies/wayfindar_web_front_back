from pathlib import Path
from app.core.retrieval.base import RetrievalBackend
from app.core.retrieval.registry import register


@register
class CosPlaceBackend(RetrievalBackend):
    name = 'cosplace'

    def load_model(self, data_dir: Path, cfg: dict):
        from app.core.localization import load_cosplace_model
        return load_cosplace_model(
            weights_path=cfg.get('weights_path', ''),
            backbone=cfg.get('backbone', 'ResNet50'),
            output_dim=cfg.get('output_dim', 2048),
        )
