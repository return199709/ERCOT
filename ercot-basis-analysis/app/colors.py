"""Diverging colour scale for basis, centred on zero.

Basis is a polarity measure: sign carries the meaning, so the scale needs two
hues with a neutral midpoint at exactly zero and symmetric bounds. An
asymmetric range would put the neutral colour somewhere other than zero and
misreport which nodes trade at a discount.

Red-blue is the standard colour-vision-safe diverging pair. Implemented
directly so the dashboard needs no plotting dependency.
"""

from __future__ import annotations

# Negative pole (discount to hub), neutral midpoint, positive pole (premium).
NEGATIVE_POLE = (178, 24, 43)    # deep red
NEUTRAL = (247, 247, 247)        # near-white grey
POSITIVE_POLE = (33, 102, 172)   # deep blue


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> str:
    t = max(0.0, min(1.0, t))
    r, g, bl = (round(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return f"#{r:02x}{g:02x}{bl:02x}"


def diverging(value: float | None, vmax: float) -> str:
    """Map a value in [-vmax, +vmax] to a diverging colour. 0 -> neutral."""
    if value is None or vmax <= 0:
        return "transparent"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "transparent"
    if v != v:  # NaN
        return "transparent"
    t = min(abs(v) / vmax, 1.0)
    return _mix(NEUTRAL, NEGATIVE_POLE if v < 0 else POSITIVE_POLE, t)


def symmetric_bound(series) -> float:
    """Largest absolute value, so the scale is symmetric about zero."""
    try:
        m = float(abs(series).max())
    except (TypeError, ValueError):
        return 0.0
    return m if m == m and m > 0 else 0.0


def text_colour(value: float | None, vmax: float) -> str:
    """Ink that stays legible against the cell fill."""
    if value is None or vmax <= 0:
        return "inherit"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "inherit"
    if v != v:
        return "inherit"
    return "#ffffff" if abs(v) / vmax > 0.6 else "#1a1a1a"
