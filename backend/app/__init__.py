"""Indoor navigation backend package.

Adds bundled third-party libraries (hloc, SuperGluePretrainedNetwork) to
sys.path so they can be imported with their original top-level names
(`import hloc`, etc.). These are only needed for the SuperPoint/SuperGlue
matching mode, which is loaded lazily.
"""
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
_THIRD_PARTY = _BACKEND / 'app' / 'third_party'
for _p in (
    _THIRD_PARTY,
    _THIRD_PARTY / 'SuperGluePretrainedNetwork',
    # Fallback: SuperGlue may still live under the legacy core/ dir if a file
    # lock prevented relocation. hloc/superpoint only.
    _BACKEND / 'core' / 'SuperGluePretrainedNetwork',
):
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
