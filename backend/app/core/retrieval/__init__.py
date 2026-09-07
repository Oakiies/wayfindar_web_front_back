# Import backend modules so their @register decorators run and populate _REGISTRY.
from app.core.retrieval import netvlad_backend, cosplace_backend, megaloc_backend  # noqa: F401
from app.core.retrieval import vpr_backends  # noqa: F401  (salad8192, mixvpr4096, mixvpr512)
from app.core.retrieval.registry import get_backend, supported_modes

__all__ = ['get_backend', 'supported_modes']
