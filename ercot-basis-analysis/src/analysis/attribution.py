"""Analysis 5b: attribute each node's basis to the constraints that drive it.

The ranking in `constraints.py` says which constraints cost the most across
ERCOT. It does not say which constraint is behind a particular node's
discount. This module does, from the structure of nodal pricing.

In the day-ahead market a bus price is the energy price plus, for every
binding constraint k, the bus's shift factor times the constraint's shadow
price. A hub is a weighted average of bus prices, so

    basis_i(t) = sum_k [ SF_hub,k - SF_i,k ] * mu_k(t)

with no intercept: when nothing binds, basis is zero. ERCOT publishes the
shadow prices mu_k(t) but not the shift factors, so the bracket is estimated
per node by least squares of hourly basis on hourly shadow prices. Each fitted
coefficient reads as "$/MWh of basis per $/MWh of shadow price on constraint
k", and coefficient times the constraint's mean shadow price is that
constraint's contribution to the node's mean basis. The largest contribution
names the dominant constraint.

What the estimate is not:

* Not exact. Shift factors change with topology and outages within a month,
  hubs are averaged over buses with weights the feeds do not carry, and only
  the top constraints enter the fit. The mean residual reports what the
  included constraints leave unexplained.
* Not causal in the econometric sense, but structurally grounded: the linear
  form is how the market clears, not a modelling convenience.
* Day-ahead only. Both sides of the fit come from the same DAM clearing, so
  they are consistent. A real-time counterpart needs a real-time basis table,
  which does not exist yet.

Constraints that always bind together are collinear and split their joint
effect between them unstably; their *combined* contribution is still
well-determined. An optional ridge penalty tames this at the cost of some
bias; it is off by default so the headline numbers stay plain least squares.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.analysis.common import require
from src.analysis.constraints import normalise
from src.config import (
    ATTRIBUTION_MATERIAL_BASIS,
    ATTRIBUTION_MATERIAL_CONTRIBUTION,
    ATTRIBUTION_MIN_BOUND_HOURS,
    ATTRIBUTION_MIN_HOURS,
    ATTRIBUTION_RIDGE,
    ATTRIBUTION_TOP_K,
)

BY_NODE_COLUMNS = [
    "Location", "n_hours", "n_constraints", "mean_basis", "explained_mean",
    "residual_mean", "r2", "dominant_constraint", "dominant_contribution",
    "dominant_share",
]
CONTRIBUTION_COLUMNS = [
    "Location", "constraint", "coefficient", "mean_shadow_price",
    "contribution", "abs_share",
]
BY_CONSTRAINT_COLUMNS = [
    "constraint", "nodes_dominated", "nodes_affected", "total_abs_contribution",
    "mean_shadow_price_all_hours", "hours_bound",
]


def shadow_price_matrix(
    dam_shadow_prices: pd.DataFrame,
    top_k: int = ATTRIBUTION_TOP_K,
    min_bound_hours: int = ATTRIBUTION_MIN_BOUND_HOURS,
    hours: pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    """Hourly wide matrix: index = hour (UTC), one column per constraint.

    Constraints are kept if they bound for at least `min_bound_hours` hours,
    then the `top_k` by total congestion cost are retained. A constraint that
    is not binding in an hour has shadow price zero in that hour, which is a
    fact about the market and not an imputation. Several rows for one
    constraint in one hour (distinct contingencies) are summed.

    The feed carries rows only for binding intervals, so an hour in which
    nothing bound is absent from it, not zero. Pass `hours` (the price
    table's hours) and those hours are added as all-zero rows, but only
    inside the span the feed actually covers: a missing feed day is left
    missing rather than read as a congestion-free day.
    """
    norm = normalise(dam_shadow_prices, "dam")
    if norm.empty:
        return pd.DataFrame()
    norm = norm.assign(hour=norm["time"].dt.floor("h"))
    hours_bound = norm.groupby("constraint")["hour"].nunique()
    eligible = hours_bound[hours_bound >= min_bound_hours].index
    norm = norm[norm["constraint"].isin(eligible)]
    if norm.empty:
        return pd.DataFrame()
    keep = (
        norm.groupby("constraint")["cost"].sum().abs()
        .sort_values(ascending=False).head(top_k).index
    )
    wide = (
        norm[norm["constraint"].isin(keep)]
        .pivot_table(index="hour", columns="constraint", values="shadow_price",
                     aggfunc="sum", fill_value=0.0)
        .sort_index()
    )
    wide.columns.name = None
    if hours is not None and len(wide):
        lo, hi = wide.index.min(), wide.index.max()
        in_span = pd.DatetimeIndex(hours)
        in_span = in_span[(in_span >= lo) & (in_span <= hi)]
        wide = wide.reindex(wide.index.union(in_span), fill_value=0.0).sort_index()
    return wide


def _fit(y: np.ndarray, x: np.ndarray, ridge: float) -> tuple[np.ndarray, float]:
    """No-intercept least squares; returns (coefficients, r2).

    r2 is computed about the mean of y, as usual, even though the fit has no
    intercept. It can therefore be negative when the included constraints
    explain a node's basis worse than its own mean would, which is exactly
    the case worth noticing.
    """
    if ridge > 0:
        k = x.shape[1]
        x_aug = np.vstack([x, np.sqrt(ridge) * np.eye(k)])
        y_aug = np.concatenate([y, np.zeros(k)])
        beta = np.linalg.lstsq(x_aug, y_aug, rcond=None)[0]
    else:
        beta = np.linalg.lstsq(x, y, rcond=None)[0]
    resid = y - x @ beta
    ss_res = float(resid @ resid)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return beta, r2


def attribute(
    basis_df: pd.DataFrame,
    dam_shadow_prices: pd.DataFrame,
    top_k: int = ATTRIBUTION_TOP_K,
    min_bound_hours: int = ATTRIBUTION_MIN_BOUND_HOURS,
    min_hours: int = ATTRIBUTION_MIN_HOURS,
    ridge: float = ATTRIBUTION_RIDGE,
    material_basis: float = ATTRIBUTION_MATERIAL_BASIS,
    material_contribution: float = ATTRIBUTION_MATERIAL_CONTRIBUTION,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Fit every node. Returns (by_node, contributions, by_constraint).

    A node is fitted on the hours where both its basis and the shadow price
    matrix exist; nodes with fewer than `min_hours` such hours are skipped
    rather than fitted on a sliver.

    `by_node` and `contributions` carry every fitted coefficient. The
    per-constraint tallies in `by_constraint` apply materiality floors:
    `nodes_dominated` counts only nodes whose |mean basis| is at least
    `material_basis`, and `nodes_affected` counts only nodes where the
    constraint's |contribution| is at least `material_contribution`. Without
    the floors every constraint touches every node and a node with a basis
    of a few cents has a "dominant" constraint of a few cents.
    `mean_shadow_price_all_hours` averages over every hour, zeros included,
    so it is lower than the bound-hours mean in the constraint ranking.
    """
    require(basis_df, ["Location", "interval_start_utc", "basis"], "attribution")
    empty = (pd.DataFrame(columns=BY_NODE_COLUMNS),
             pd.DataFrame(columns=CONTRIBUTION_COLUMNS),
             pd.DataFrame(columns=BY_CONSTRAINT_COLUMNS))

    b = basis_df[["Location", "interval_start_utc", "basis"]].dropna(subset=["basis"])
    b = b.assign(hour=pd.to_datetime(b["interval_start_utc"], utc=True).dt.floor("h"))
    y_wide = b.pivot_table(index="hour", columns="Location", values="basis",
                           aggfunc="mean")
    x_wide = shadow_price_matrix(dam_shadow_prices, top_k, min_bound_hours,
                                 hours=y_wide.index)
    if x_wide.empty:
        return empty
    common = y_wide.index.intersection(x_wide.index)
    if len(common) < min_hours:
        return empty
    x_all = x_wide.loc[common]
    y_all = y_wide.loc[common]
    constraints = list(x_all.columns)
    mean_shadow = x_all.mean(axis=0).to_numpy()

    node_rows: list[dict] = []
    contrib_rows: list[dict] = []
    for location in y_all.columns:
        y = y_all[location]
        mask = y.notna().to_numpy()
        if mask.sum() < min_hours:
            continue
        x = x_all.to_numpy(dtype=float)[mask]
        yv = y.to_numpy(dtype=float)[mask]
        beta, r2 = _fit(yv, x, ridge)
        # Contribution to this node's mean basis over the hours it was fitted on.
        contrib = beta * x.mean(axis=0)
        explained = float(contrib.sum())
        mean_basis = float(yv.mean())
        abs_total = float(np.abs(contrib).sum())
        dominant = int(np.argmax(np.abs(contrib))) if abs_total > 0 else None

        node_rows.append({
            "Location": location,
            "n_hours": int(mask.sum()),
            "n_constraints": len(constraints),
            "mean_basis": mean_basis,
            "explained_mean": explained,
            "residual_mean": mean_basis - explained,
            "r2": r2,
            "dominant_constraint": constraints[dominant] if dominant is not None else None,
            "dominant_contribution": float(contrib[dominant]) if dominant is not None else np.nan,
            "dominant_share": (float(contrib[dominant]) / mean_basis
                               if dominant is not None and mean_basis != 0 else np.nan),
        })
        for j, name in enumerate(constraints):
            if beta[j] == 0 and contrib[j] == 0:
                continue
            contrib_rows.append({
                "Location": location,
                "constraint": name,
                "coefficient": float(beta[j]),
                "mean_shadow_price": float(mean_shadow[j]),
                "contribution": float(contrib[j]),
                "abs_share": float(abs(contrib[j]) / abs_total) if abs_total > 0 else np.nan,
            })

    by_node = pd.DataFrame(node_rows, columns=BY_NODE_COLUMNS)
    contributions = pd.DataFrame(contrib_rows, columns=CONTRIBUTION_COLUMNS)
    if by_node.empty:
        return by_node, contributions, pd.DataFrame(columns=BY_CONSTRAINT_COLUMNS)

    by_node = by_node.sort_values("mean_basis").reset_index(drop=True)
    contributions = (contributions.reindex(contributions["contribution"].abs()
                                           .sort_values(ascending=False).index)
                     .reset_index(drop=True))

    hours_bound = (x_all != 0).sum(axis=0)
    material_nodes = by_node[by_node["mean_basis"].abs() >= material_basis]
    dominated = material_nodes["dominant_constraint"].value_counts()
    material_rows = contributions[
        contributions["contribution"].abs() >= material_contribution
    ]
    affected = material_rows.groupby("constraint")["Location"].nunique()
    abs_contrib = contributions.groupby("constraint")["contribution"].apply(
        lambda s: float(s.abs().sum())
    )
    by_constraint = pd.DataFrame({
        "constraint": constraints,
        "nodes_dominated": [int(dominated.get(c, 0)) for c in constraints],
        "nodes_affected": [int(affected.get(c, 0)) for c in constraints],
        "total_abs_contribution": [float(abs_contrib.get(c, 0.0)) for c in constraints],
        "mean_shadow_price_all_hours": mean_shadow,
        "hours_bound": [int(hours_bound[c]) for c in constraints],
    }, columns=BY_CONSTRAINT_COLUMNS)
    by_constraint = by_constraint.sort_values(
        ["nodes_dominated", "total_abs_contribution"], ascending=False
    ).reset_index(drop=True)
    return by_node, contributions, by_constraint


def top_contributions(contributions: pd.DataFrame, location: str,
                      n: int = 5) -> pd.DataFrame:
    """The n largest-magnitude contributions for one node, for drill-downs."""
    if contributions.empty:
        return contributions
    rows = contributions[contributions["Location"] == location]
    return rows.reindex(rows["contribution"].abs().sort_values(ascending=False).index) \
        .head(n).reset_index(drop=True)
