from pathlib import Path
from app.core.retrieval.base import RetrievalBackend
from app.core.retrieval.registry import register


@register
class MegaLocBackend(RetrievalBackend):
    name = 'megaloc'

    def load_model(self, data_dir: Path, cfg: dict):
        from app.core.localization import load_megaloc_model
        return load_megaloc_model()
