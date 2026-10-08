"""Optimal battery dispatch: an energy model, not a price heuristic.

The storage screen in `storage.py` takes the mean of a day's four highest
hours minus its four lowest. That is an upper bound, not a revenue: it
assumes a battery can be in two places at once, charges and discharges with
no losses, and never wears out.

This module solves the actual operating problem. For each node-day it finds
the charge/discharge schedule maximising revenue subject to the physics:

    state of charge   0 <= soc <= energy capacity
    power limit       |charge|, |discharge| <= power rating
    round trip loss   energy stored = energy bought x efficiency
    degradation       a cost per MWh of throughput, which is what actually
                      restrains cycling in practice

Solved by dynamic programming over a discretised state of charge with
perfect foresight. Perfect foresight is deliberate and must be read as such:
it yields the *maximum extractable* value, an upper bound on what a real
operator bidding against forecasts could capture. It is the standard way to
size the prize; it is not a trading backtest.

Revenue is decomposed into the part a battery at the hub would have earned
from the system-wide price shape, and the part attributable to this node's
own basis. That separation is the point of the exercise: it distinguishes a
site that is good because ERCOT is volatile from one that is good because
this particular node is congested.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.analysis.common import require


@dataclass(frozen=True)
class BatterySpec:
    """A price-taking storage asset.

    Defaults describe a 100 MWh / 4-hour lithium-ion system, the shape most
    commonly built in ERCOT.
    """

    power_mw: float = 25.0
    duration_hours: float = 4.0
    round_trip_efficiency: float = 0.85
    degradation_cost_per_mwh: float = 5.0
    soc_steps: int = 40

    @property
    def energy_mwh(self) -> float:
        return self.power_mw * self.duration_hours

    def __post_init__(self) -> None:
        if not 0 < self.round_trip_efficiency <= 1:
            raise ValueError("round_trip_efficiency must be in (0, 1]")
        if self.power_mw <= 0 or self.duration_hours <= 0:
            raise ValueError("power_mw and duration_hours must be positive")
        if self.soc_steps < 2:
            raise ValueError("soc_steps must be at least 2")


def dispatch_day(prices: np.ndarray, spec: BatterySpec) -> dict:
    """Optimal schedule for one day of hourly prices.

    Returns revenue, throughput, equivalent full cycles and the schedule.
    Starts and ends empty, so days are independent and a month is the sum of
    its days rather than one long optimisation that could park energy across
    midnight.
    """
    hours = len(prices)
    if hours == 0:
        return {"revenue": 0.0, "throughput_mwh": 0.0, "cycles": 0.0,
                "schedule": np.zeros(0)}

    levels = np.linspace(0.0, spec.energy_mwh, spec.soc_steps + 1)
    step = levels[1] - levels[0]
    # Most MWh the battery can move in one hour, in whole SoC steps.
    max_step = max(1, int(round(spec.power_mw / step)))

    # value[t, i] = best revenue from hour t onward, starting at SoC level i.
    value = np.full((hours + 1, len(levels)), -np.inf)
    value[hours, 0] = 0.0          # must finish empty
    choice = np.zeros((hours, len(levels)), dtype=np.int16)

    efficiency = spec.round_trip_efficiency
    deltas = np.arange(-max_step, max_step + 1)

    for t in range(hours - 1, -1, -1):
        price = prices[t]
        for d in deltas:
            start = max(0, -d)
            end = min(len(levels), len(levels) - d)
            if start >= end:
                continue
            origin = np.arange(start, end)
            target = origin + d
            moved = abs(d) * step

            if d > 0:            # charging: buy more than we store
                cash = -price * moved / efficiency
            elif d < 0:          # discharging: sell what leaves the battery
                cash = price * moved
            else:
                cash = 0.0
            cash -= spec.degradation_cost_per_mwh * moved

            candidate = cash + value[t + 1, target]
            better = candidate > value[t, origin]
            rows = origin[better]
            value[t, rows] = candidate[better]
            choice[t, rows] = d

    # Walk the policy forward from empty.
    schedule = np.zeros(hours)
    soc = 0
    throughput = 0.0
    for t in range(hours):
        d = int(choice[t, soc])
        schedule[t] = -d * step          # positive = discharge to grid
        throughput += abs(d) * step
        soc += d

    revenue = float(value[0, 0]) if np.isfinite(value[0, 0]) else 0.0
    return {
        "revenue": revenue,
        "throughput_mwh": throughput,
        "cycles": throughput / (2 * spec.energy_mwh) if spec.energy_mwh else 0.0,
        "schedule": schedule,
    }


def dispatch_series(df: pd.DataFrame, spec: BatterySpec,
                    price_col: str = "SPP") -> pd.DataFrame:
    """Run the dispatch per location-day over an hourly price table."""
    require(df, ["Location", "local_date", price_col], "dispatch_series")

    rows = []
    for (location, day), group in df.groupby(["Location", "local_date"]):
        prices = group.sort_values("interval_start_utc")[price_col].to_numpy(
            dtype=float
        )
        if np.isnan(prices).any() or len(prices) < 8:
            # A short or holed day cannot be dispatched honestly; skip it
            # rather than optimise against invented prices.
            continue
        result = dispatch_day(prices, spec)
        rows.append({
            "Location": location,
            "local_date": day,
            "revenue": result["revenue"],
            "throughput_mwh": result["throughput_mwh"],
            "cycles": result["cycles"],
            "hours": len(prices),
        })
    return pd.DataFrame(rows)


def annualise(daily: pd.DataFrame, spec: BatterySpec) -> pd.DataFrame:
    """Per-node revenue, scaled to $/kW-year for comparability."""
    if daily.empty:
        return pd.DataFrame(columns=["Location", "days", "total_revenue",
                                     "revenue_per_day", "annual_per_kw",
                                     "mean_cycles"])
    out = daily.groupby("Location", as_index=False).agg(
        days=("revenue", "size"),
        total_revenue=("revenue", "sum"),
        revenue_per_day=("revenue", "mean"),
        mean_cycles=("cycles", "mean"),
    )
    kw = spec.power_mw * 1000.0
    out["annual_per_kw"] = out["revenue_per_day"] * 365.0 / kw
    return out.sort_values("annual_per_kw", ascending=False).reset_index(drop=True)


def decompose(node_daily: pd.DataFrame, hub_daily: pd.DataFrame) -> pd.DataFrame:
    """Split node revenue into hub price shape versus this node's basis.

    A battery at the hub earns from ERCOT's system-wide daily price shape.
    Anything a node earns beyond that is attributable to its own basis. The
    split distinguishes a site that is merely in a volatile market from one
    that is genuinely well placed.
    """
    if node_daily.empty or hub_daily.empty:
        return pd.DataFrame(columns=["Location", "node_revenue", "hub_revenue",
                                     "basis_revenue", "basis_share"])

    hub = hub_daily.groupby("local_date", as_index=False).agg(
        hub_revenue=("revenue", "mean")
    )
    merged = node_daily.merge(hub, on="local_date", how="inner")
    merged["basis_revenue"] = merged["revenue"] - merged["hub_revenue"]

    out = merged.groupby("Location", as_index=False).agg(
        node_revenue=("revenue", "sum"),
        hub_revenue=("hub_revenue", "sum"),
        basis_revenue=("basis_revenue", "sum"),
    )
    out["basis_share"] = (out["basis_revenue"] / out["node_revenue"]).where(
        out["node_revenue"] != 0
    )
    return out.sort_values("basis_revenue", ascending=False).reset_index(drop=True)
