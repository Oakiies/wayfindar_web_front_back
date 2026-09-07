"""Abstract base for retrieval backends."""
from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
import torch


class RetrievalBackend(ABC):
    name: str  # registry key — must be set on each subclass

    @abstractmethod
    def load_model(self, data_dir: Path, cfg: dict) -> torch.nn.Module:
        """Load and return the retrieval model (on CPU; caller moves to device)."""
        ...

    def descriptor_file(self, cfg: dict) -> str:
        return cfg.get('descriptor_file', 'global_descriptors.npy')

    def pca_file(self, cfg: dict) -> str:
        return cfg.get('pca_file', '')

    def model_cache_key(self, data_dir: Path, cfg: dict) -> str:
        """Key identifying interchangeable loaded models.

        Default assumes the model is floor-independent (depends only on the
        retrieval mode), so all floors share a single loaded instance. Backends
        whose weights depend on per-floor assets must override this.
        """
        return self.name
