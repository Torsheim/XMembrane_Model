"""HeiQ package compatibility and public namespace bootstrap."""

import numpy as _np


# The reviewed legacy V2 solver is hash-frozen and calls ``np.trapezoid``.
# NumPy 1.26 exposes the same operation as ``np.trapz``.  Provide the modern
# spelling at package bootstrap rather than editing the provenance-locked
# solver source; NumPy 2.x already defines it and is left unchanged.
if not hasattr(_np, "trapezoid"):
    _np.trapezoid = _np.trapz  # type: ignore[attr-defined]
