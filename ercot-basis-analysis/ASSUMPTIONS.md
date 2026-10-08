# Assumptions

Every choice here could reasonably have gone another way. Each is implemented
in `src/config.py` unless noted, so changing an assumption means changing one
value, not hunting through the analysis code.

Status: **no ERCOT data has been ingested yet**, so none of these has been
validated against real prices. They are design decisions awaiting data.

## 1. Hub assignment (the most consequential choice)

ERCOT publishes **no node-to-hub mapping**. Trading hubs are averages over
defined sets of electrical buses, so "which hub does this node belong to" is an
analyst decision, not a lookup.

**Assumption:** each resource node is assigned the hub of its load zone.

| Load zone | Assigned hub | Basis |
|---|---|---|
| `LZ_NORTH` | `HB_NORTH` | geographic match |
| `LZ_SOUTH` | `HB_SOUTH` | geographic match |
| `LZ_WEST` | `HB_WEST` | geographic match |
| `LZ_HOUSTON` | `HB_HOUSTON` | geographic match |
| `LZ_AEN` (Austin Energy) | `HB_SOUTH` | **judgment call** — NOIE zone, no hub of its own |
| `LZ_CPS` (CPS Energy) | `HB_SOUTH` | **judgment call** — NOIE zone |
| `LZ_LCRA` | `HB_SOUTH` | **judgment call** — NOIE zone |
| `LZ_RAYBN` (Rayburn) | `HB_NORTH` | **judgment call** — NOIE zone |

The four NOIE rows are the weakest links. A node in one of those zones could
defensibly be referenced to a different hub, which would change its basis.

**Mitigation:** basis is also computed against all four trading hubs and
`HB_BUSAVG` (`basis_vs_HB_*` columns), so any conclusion can be re-cut against
a different reference without re-ingesting.

**Nodes whose load zone cannot be determined are never guessed.** They are
returned in an `unmapped` list, excluded from basis, and reported. Assigning
them a plausible-looking hub would produce confident and wrong numbers.

## 2. Node-to-zone source

The node-to-zone lookup comes from ERCOT's settlement point list
(`get_settlement_points_electrical_bus_mapping`). Column spellings vary between
report revisions, so `build_zone_map` probes candidate names and **raises**
if none match, rather than silently returning an empty map that would make
every node unmapped.

## 3. Time and daylight saving

- ERCOT settles on Central Prevailing Time. Every processed table carries
  `interval_start_utc`, and **all joins key on UTC**, never on local time.
- Spring forward (23-hour day): the missing 02:00 hour is correct, not a gap.
  `expected_intervals` returns 23 hourly / 92 quarter-hourly for that day.
- Fall back (25-hour day): the repeated 01:00 hour is two distinct UTC
  instants. Expected counts are 25 / 100.

Treating every day as 24 hours would report two false gaps and one false
duplicate per year, per node.

## 4. On-peak definition

ERCOT 5×16: hours ending 07:00–22:00 CPT, Monday–Friday, excluding the six
NERC holidays (New Year's Day, Memorial Day, Independence Day, Labor Day,
Thanksgiving, Christmas), observed on the nearest weekday.

Some desks use 7×16. Change `PEAK_WEEKDAYS` in `src/config.py` to switch.

## 5. Missing data is never filled

Gaps, duplicates and settlement-point membership changes are detected and
written to `reports/quality/`. They are **never** interpolated, forward-filled
or zero-filled. Analyses exclude affected location-days. A silently patched
price series produces basis numbers that look authoritative and are wrong.

## 6. Congestion cost units

Shadow price is a $/MWh rate, but DAM intervals are one hour and SCED
intervals are five minutes. Summing raw shadow prices across both markets
would weight a 5-minute SCED interval as heavily as a full DAM hour.

**Assumption:** constraints are ranked by `shadow_price × interval_hours`
($-hours), so the two markets are comparable. A constraint counts as *bound*
in an interval when its shadow price is non-zero.

## 7. Real-time to hourly

RTM 15-minute prices are averaged to hourly with a simple mean before being
compared to DAM. The four intervals are equal length, so the unweighted mean
is the correct hourly equivalent.

## 8. Persistent DA–RT bias

A node is flagged when |mean spread| exceeds two standard errors of the mean —
i.e. the bias is unlikely to be sampling noise. This is a screen, not a
trading signal, and it does not adjust for autocorrelation, which will make
the test somewhat permissive on serially correlated price data.

## 9. Storage screen

Average daily (mean of top 4 hours) − (mean of bottom 4 hours), computed on
DAM hourly prices. A day with fewer than 8 priced hours returns NaN rather
than a spread built from overlapping windows. This ignores round-trip
efficiency, degradation, cycling limits and state-of-charge constraints, so it
is an upper bound on arbitrage value.

## 10. Renewable correlation

Pearson correlation between hourly basis and hourly regional wind/solar
output, reported only where at least 30 paired observations exist.
Correlation is not causation: congestion, load and outages co-move with
renewable output.

## 11. Widening negative basis

Flagged when a node's mean basis is negative **and** fell by at least
$1.00/MWh year over year. Nodes with only one year of data are excluded rather
than reported as unchanged.

## 12. Hub reconstruction check

`validate_hub_reconstruction` compares a published hub price to the mean of
member nodes. ERCOT hub weights are defined over *buses* and are not part of
these feeds, so a non-zero difference is expected. The function **reports the
discrepancy and does not assert a match** — if the weights turn out not to be
recoverable, that is itself the finding.

## 13. Renewable region taxonomies differ between wind and solar

Confirmed against the live feeds, not assumed. Both the wind and solar
reports are **wide**: one `GEN <REGION>` column per region, alongside
`COP HSL <REGION>` columns that are High Sustained Limit, i.e. available
capacity rather than output.

| Feed | Regions |
|---|---|
| Wind | `COASTAL`, `NORTH`, `PANHANDLE`, `SOUTH`, `WEST`, `SYSTEM WIDE` |
| Solar | `CenterEast`, `CenterWest`, `FarEast`, `FarWest`, `NorthWest`, `SouthEast`, `SYSTEM WIDE` |

Two consequences:

- **The two feeds cannot be compared region-for-region.** There is no solar
  `WEST` or `PANHANDLE` at all. The nearest solar analogues to the windy west
  are `FarWest` and `NorthWest`, which is an **assumption** about geographic
  correspondence, not an ERCOT-defined mapping.
- **Only `GEN *` columns are read.** Correlating basis against `COP HSL`
  would be correlating against capacity instead of generation — a silent and
  badly wrong analysis. Requesting a region a feed does not have raises
  rather than dropping the series.

Focus regions are `WIND_FOCUS_REGIONS` and `SOLAR_FOCUS_REGIONS` in
`src/config.py`.

## 14. The settlement point mapping needs an explicit date

`get_settlement_points_electrical_bus_mapping` has `date=None` in its
signature, but the `@support_date_range` decorator rejects the call without
one. The mapping is fetched as a single snapshot as of the ingest start date
and reused for the whole period. Settlement points that appear or disappear
within the period are reported by the quality checks (§5) rather than
reconciled against multiple snapshots.
