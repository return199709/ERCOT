# Findings

**Status: not yet produced. No ERCOT data has been ingested.**

This file is deliberately empty of results. The pipeline that will generate
them is built and tested, but it has never run against real prices, so there
is nothing here to report.

Writing plausible-looking numbers into this file — from synthetic fixtures,
from memory of ERCOT market behaviour, or from anything other than ingested
data — would be fabrication. The test fixtures under `tests/` are synthetic by
construction and exist only to exercise code paths; they are not market data
and must never be reported as findings.

## Why it is empty

This project was built in a remote container whose network policy blocks every
ERCOT host (`api.ercot.com`, `ercotb2c.b2clogin.com`, `www.ercot.com`,
`sso.ercot.com`). Requests fail at the TLS tunnel with a 403 policy denial,
before authentication, so no credential can unblock them.

## How to fill it in

On a machine with outbound access to ERCOT:

```bash
cp .env.example .env         # then add your real credentials
make install
make ingest-mapping          # settlement point -> load zone, needed for basis
make ingest MONTH=2025-06    # one month first, to validate
make analyze
make app
```

Then write up, with one chart each:

1. Worst-basis nodes and where they cluster geographically.
2. Whether negative basis is widening year over year, and at which nodes.
3. How basis co-moves with West and Panhandle wind and solar output.
4. Which constraints carry the most congestion cost, and their seasonality.
5. Where day-ahead settles persistently above or below real time.

## Limitations to carry into the write-up

- **Hub assignment is an assumption, not a fact.** ERCOT publishes no
  node-to-hub mapping. See `ASSUMPTIONS.md` §1; the four NOIE zones are the
  weakest links. Re-check conclusions against the `basis_vs_HB_*` columns.
- **Gaps are excluded, not filled.** Read `reports/quality/` before quoting any
  node-level number; a node with many missing intervals may have a mean basis
  computed from an unrepresentative slice.
- **Correlation is not causation** for the renewable analysis.
- **The storage screen is an upper bound** — it ignores round-trip efficiency,
  degradation and cycling limits.
- **Constraint names change** between ERCOT model updates, so a constraint
  ranked over 24 months may not refer to one physical element throughout.
