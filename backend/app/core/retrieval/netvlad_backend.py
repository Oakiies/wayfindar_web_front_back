from pathlib import Path
from app.core.retrieval.base import RetrievalBackend
from app.core.retrieval.registry import register


@register
class NetVLADBackend(RetrievalBackend):
    name = 'netvlad'

    def load_model(self, data_dir: Path, cfg: dict):
        from app.core.localization import load_netvlad_model
        centroids = data_dir / cfg.get('centroids_file', 'netvlad_centroids.npy')
        return load_netvlad_model(centroids)

    def model_cache_key(self, data_dir: Path, cfg: dict) -> str:
        # NetVLAD centroids are per-floor, so models are not interchangeable
        # across floors with different centroid files.
        centroids = data_dir / cfg.get('centroids_file', 'netvlad_centroids.npy')
        return f"netvlad:{centroids.resolve()}"
