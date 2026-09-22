"""ERCOT nodal basis and congestion dashboard.

Reads only the derived tables written by `make analyze`. If a table is
missing the section explains what to run; nothing is ever simulated to fill
an empty panel.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.colors import diverging, symmetric_bound, text_colour  # noqa: E402
from src import db  # noqa: E402
from src.config import TOP_CONSTRAINTS_N, WORST_NODES_TOP_N  # noqa: E402

st.set_page_config(page_title="ERCOT Basis & Congestion", layout="wide")


@st.cache_data(show_spinner=False)
def load(table: str) -> pd.DataFrame | None:
    try:
        return db.read_processed(table)
    except FileNotFoundError:
        return None


def need(table: str, what: str) -> None:
    st.info(f"**{what}** is not available yet — `{table}` has not been built. "
            "Run `make ingest MONTH=YYYY-MM` then `make analyze`.")


def style_diverging(frame: pd.DataFrame, bound: float):
    """Colour a numeric grid on a zero-centred diverging scale."""
    return frame.style.apply(
        lambda col: [
            f"background-color: {diverging(v, bound)}; color: {text_colour(v, bound)}"
            for v in col
        ],
        axis=0,
    ).format("{:,.2f}", na_rep="—")


# --------------------------------------------------------------------------
st.title("ERCOT Nodal Basis & Congestion")
st.caption(
    "Basis = node settlement point price − assigned hub price. Nodes are "
    "assigned the hub of their load zone; ERCOT publishes no node→hub mapping, "
    "so this is a stated assumption (see ASSUMPTIONS.md)."
)

basis_by_node = load("basis_by_node")
worst = load("worst_nodes")
basis_table = load("basis")

if basis_by_node is None:
    need("basis_by_node", "The basis tables")
    st.stop()

# --- headline numbers -----------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Nodes analysed", f"{basis_by_node['Location'].nunique():,}")
c2.metric("Mean basis", f"${basis_by_node['mean'].mean():,.2f}")
c3.metric("Most negative", f"${basis_by_node['mean'].min():,.2f}")
c4.metric("Most positive", f"${basis_by_node['mean'].max():,.2f}")

tabs = st.tabs([
    "Worst basis", "Hour × month", "Constraints", "Node drill-down",
    "DA vs RT", "Storage screen", "Data quality",
])

# --- 1. worst nodes -------------------------------------------------------
with tabs[0]:
    st.subheader(f"Worst {WORST_NODES_TOP_N} nodes by mean basis")
    if worst is None or worst.empty:
        need("worst_nodes", "Worst-node ranking")
    else:
        chart = worst.set_index("Location")["mean"]
        st.bar_chart(chart, height=380, color="#b2182b")
        st.caption("Mean basis in $/MWh. More negative means the node settles "
                   "further below its hub.")
        st.dataframe(worst, width="stretch")

# --- 2. hour x month heatmap ---------------------------------------------
with tabs[1]:
    st.subheader("Mean basis by hour and month")
    if basis_table is None or basis_table.empty:
        need("basis", "The hour × month heatmap")
    else:
        nodes = sorted(basis_table["Location"].dropna().unique())
        pick = st.selectbox("Settlement point", ["(all nodes)"] + list(nodes))
        subset = basis_table if pick == "(all nodes)" else \
            basis_table[basis_table["Location"] == pick]
        grid = subset.pivot_table(index="hour", columns="month",
                                  values="basis", aggfunc="mean")
        if grid.empty:
            st.warning("No basis values for that selection.")
        else:
            bound = symmetric_bound(grid.stack())
            st.caption(f"Diverging scale centred on zero, ±${bound:,.2f}/MWh. "
                       "Red = discount to hub, blue = premium.")
            st.dataframe(style_diverging(grid, bound), width="stretch")

# --- 3. constraints -------------------------------------------------------
with tabs[2]:
    st.subheader(f"Top {TOP_CONSTRAINTS_N} binding constraints")
    constraints = load("top_constraints")
    if constraints is None or constraints.empty:
        need("top_constraints", "Constraint ranking")
    else:
        st.bar_chart(constraints.set_index("constraint")["total_cost"],
                     height=380, color="#2166ac")
        st.caption("Congestion cost in $-hours: shadow price × interval "
                   "duration, so DAM hours and 5-minute SCED intervals are "
                   "weighted comparably.")
        st.dataframe(constraints, width="stretch")

        seasonal = load("constraint_seasonality")
        if seasonal is not None and not seasonal.empty:
            st.subheader("Seasonality")
            top_names = constraints["constraint"].head(8).tolist()
            pivot = seasonal[seasonal["constraint"].isin(top_names)].pivot_table(
                index="month", columns="constraint", values="total_cost",
                aggfunc="sum",
            )
            st.line_chart(pivot, height=320)

# --- 4. node drill-down ---------------------------------------------------
with tabs[3]:
    st.subheader("Node drill-down")
    if basis_table is None or basis_table.empty:
        need("basis", "Node drill-down")
    else:
        nodes = sorted(basis_table["Location"].dropna().unique())
        node = st.selectbox("Node", nodes, key="drill")
        rows = basis_table[basis_table["Location"] == node].copy()
        stats = basis_by_node[basis_by_node["Location"] == node]
        if not stats.empty:
            s = stats.iloc[0]
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Mean basis", f"${s['mean']:,.2f}")
            m2.metric("P5", f"${s['p5']:,.2f}")
            m3.metric("P95", f"${s['p95']:,.2f}")
            m4.metric("Intervals", f"{int(s['n']):,}")

        peak = load("basis_by_node_peak")
        if peak is not None:
            node_peak = peak[peak["Location"] == node]
            if not node_peak.empty:
                st.write("**On-peak vs off-peak**")
                st.dataframe(node_peak[["period", "n", "mean", "p5", "p95"]],
                             width="stretch")

        rows = rows.sort_values("interval_start_utc")
        st.line_chart(rows.set_index("interval_start_utc")["basis"], height=320)
        st.caption(f"Basis over time for {node} ($/MWh).")

# --- 5. DA vs RT ----------------------------------------------------------
with tabs[4]:
    st.subheader("Day-ahead versus real-time")
    da_rt = load("da_rt_by_node")
    if da_rt is None or da_rt.empty:
        need("da_rt_by_node", "DA vs RT analysis")
    else:
        biased = da_rt[da_rt["persistent_bias"].fillna(False)]
        st.metric("Nodes with persistent bias", f"{len(biased):,}")
        st.caption("Flagged when |mean spread| exceeds two standard errors — "
                   "a bias unlikely to be noise.")
        st.dataframe(da_rt, width="stretch")

# --- 6. storage -----------------------------------------------------------
with tabs[5]:
    st.subheader("Storage arbitrage screen")
    spread = load("storage_spread")
    if spread is None or spread.empty:
        need("storage_spread", "Storage screen")
    else:
        top = spread.head(25)
        st.bar_chart(top.set_index("Location")["mean_spread"], height=380,
                     color="#2166ac")
        st.caption("Average daily top-4-hour minus bottom-4-hour spread "
                   "($/MWh), before round-trip efficiency and cycling limits.")
        st.dataframe(spread, width="stretch")

# --- 7. data quality ------------------------------------------------------
with tabs[6]:
    st.subheader("Data quality")
    st.caption("Gaps are reported, never filled. Affected location-days are "
               "excluded from the analyses rather than interpolated.")
    from src.config import QUALITY_REPORTS
    reports = sorted(QUALITY_REPORTS.glob("*.md")) if QUALITY_REPORTS.exists() else []
    if not reports:
        st.info("No quality reports yet. Run `make analyze`.")
    for report in reports:
        with st.expander(report.stem, expanded=True):
            st.markdown(report.read_text())
