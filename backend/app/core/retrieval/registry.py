"""Backend registry — maps mode name → RetrievalBackend class."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.retrieval.base import RetrievalBackend

_REGISTRY: dict[str, type] = {}


def register(cls):
    """Class decorator: add a backend to the registry under cls.name."""
    _REGISTRY[cls.name] = cls
    return cls


def get_backend(name: str) -> 'RetrievalBackend':
    cls = _REGISTRY.get((name or '').strip().lower())
    if cls is None:
        raise ValueError(
            f"Unknown retrieval mode {name!r}. "
            f"Available: {sorted(_REGISTRY)}"
        )
    return cls()


def supported_modes() -> set[str]:
    return set(_REGISTRY)
