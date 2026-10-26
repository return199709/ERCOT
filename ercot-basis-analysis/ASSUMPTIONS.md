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

**DC ties are outside the analysis by design.** `DC_E`, `DC_N`, `DC_L`,
`DC_R` and `DC_S` are priced settlement points for the ties to the Eastern
Interconnection and Mexico. They sit in no load zone and settle against no
hub, so they carry no basis and are excluded as a class rather than listed
as mapping failures.

**Nodes whose load zone cannot be determined are never guessed.** They are
returned in an `unmapped` list, excluded from basis, and reported. Assigning
them a plausible-looking hub would produce confident and wrong numbers.

## 1b. Zone inheritance through identical price series

The settlement point list covers about 93% of the names in the DAM price feed
(measured on the 2026-09-28 list against June 2025 prices by
`make inspect-mapping`). The remainder are mostly unit-level names such as
`FOO_CC1` beside a listed `FOO_RN`: different settlement point names for the
same electrical bus, which therefore carry a byte-identical price series.

**Assumption:** an unmapped point whose price series is identical, interval
for interval over the whole period, to a listed node's series sits on the same
bus and inherits that node's load zone. This is a lookup, not an inference,
and the rule is strict: a group whose mapped members sit in different zones
recovers nothing, a group with no mapped member recovers nothing, and listed
points are never rewritten. Every recovered point is written to the
`zone_map_recovered` table with the node it inherited from and the number of
intervals the two series agree on, so the step is auditable and reversible.

Implemented in `extend_zone_map_by_shared_series`; applied before basis is
computed. The 88 resource nodes for which ERCOT's `Hub` column is populated
are *not* used to override the load-zone proxy; that would be a change of
policy rather than of coverage and is left as an open decision.

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

The constants are hour-*ending* numbers, as ERCOT quotes them, and the code
converts them to interval starts (06:00 through 21:00). Results produced before
2026-10-17 used a 15-hour window that dropped the 06:00 interval; the June 2025
on/off-peak table in `reports/findings.md` is marked accordingly and should be
regenerated.

## 5. Missing data is never filled

Gaps, duplicates and settlement-point membership changes are detected and
written to `reports/quality/`. They are **never** interpolated, forward-filled
or zero-filled. A silently patched price series produces basis numbers that
look authoritative and are wrong.

**What detection covers.** The full location x day grid, not only the
location-days that returned rows. Grouping by (location, day) and comparing
the count to the expected interval total finds a *short* day but never a
*missing* one, because an absent location-day forms no group. Real June 2025
data carried 29 wholly absent location-days that an earlier version of this
check reported as zero gaps. Absences and partial days are now reported
separately under `kind`.

**Lifecycle is not loss.** Each location is only held to account between its
own first and last observed date, so a settlement point commissioned or
retired mid-period is not reported as gapped. Those appear instead in a
coverage table, because their statistics rest on fewer days than the rest and
rankings across them are not like-for-like.

**What happens to a flagged location-day.** It is *not* dropped wholesale.
Excluding a day that is missing one hour would discard twenty-three good
observations. Per-interval statistics use what exists and report `n` beside
every figure, so thin data is visible rather than silently equal-weighted
against complete data. Day-level analyses that a short day would distort
guard themselves: the storage screen returns NaN when a day cannot supply two
disjoint 4-hour windows.

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

## 15. Battery dispatch is a model, not a heuristic -- and its limits

`storage.py` ranks nodes by the mean of a day's four highest hours minus its
four lowest. That is a price statistic, not a revenue: it assumes one cycle a
day, no losses, and no wear.

`dispatch.py` solves the operating problem instead, by dynamic programming
over a discretised state of charge:

| Constraint | Treatment |
|---|---|
| Energy capacity | `0 <= soc <= power x duration` |
| Power rating | hourly charge/discharge capped at the rating |
| Round-trip loss | applied on the charge side: stored = bought x efficiency |
| Degradation | a cost per MWh of throughput, not a hard cycle cap |
| Day boundaries | starts and ends empty, so days are independent |

Defaults: 25 MW / 100 MWh (4-hour), 85% round trip, $5/MWh throughput cost.
All four live in `src/config.py`.

**The screen is not a bound in either direction**, which is why it was worth
replacing rather than tuning. Measured on constructed days:

| Day shape | Screen | Optimal, lossless | Optimal, real losses |
|---|---|---|---|
| One trough, one peak | $9,000 | $9,000 (1.0 cycle) | $7,824 (1.0 cycle) |
| Volatile | $10,416 | $14,240 (3.0 cycles) | $11,647 (2.2 cycles) |
| Spiky | $6,875 | $6,875 (0.2 cycles) | $6,515 (0.2 cycles) |

It overstates when efficiency and wear bite, and understates when prices
swing more than once in a day.

**Perfect foresight is deliberate and must be read as such.** The model knows
the whole day's prices in advance, so its output is the *maximum extractable*
value -- an upper bound on what an operator bidding against forecasts could
capture. It sizes the prize; it is not a trading backtest, and the figures
should never be quoted as achievable revenue.

**Other limits.** The battery is a price taker: it never moves the price it
trades against, which is reasonable for one 100 MWh asset among ERCOT's
thousands of MW of storage and would not be for a fleet. No ancillary service
revenue, which in ERCOT is a large share of real storage income, so the
figures understate total value while overstating the arbitrage component. A
day with missing hours or a null price is skipped rather than optimised
against gaps.

## 16. Revenue decomposition against the hub

Dispatch revenue is split into what a battery at the trading hubs would have
earned from ERCOT's system-wide daily price shape, and the remainder
attributable to the node's own basis. The hub benchmark is the mean across
the four trading hubs, not each node's assigned hub, so the split measures
"volatile market" against "well-placed site" rather than re-importing the hub
assignment assumption from section 1.

## 17. Congestion attribution: structure, not correlation

In the day-ahead market a bus price is the energy price plus, for each
binding constraint, the bus's shift factor times the constraint's shadow
price. A hub is a weighted average of bus prices. So a node's basis is

    basis(t) = sum over constraints k of [SF_hub,k - SF_node,k] x mu_k(t)

with no intercept: no binding constraint, no basis. ERCOT publishes mu (the
shadow prices) but not the shift factors.

**Assumption:** the bracketed shift-factor differences are estimated per node
by no-intercept least squares of hourly DAM basis on the hourly DAM shadow
prices of the top `ATTRIBUTION_TOP_K` constraints by congestion cost (those
that bound for at least `ATTRIBUTION_MIN_BOUND_HOURS` hours). A constraint's
contribution to a node's mean basis is coefficient x mean shadow price; the
largest contribution names the dominant constraint. The residual mean is what
the included constraints leave unexplained.

What this is not:

- **Not exact.** Shift factors move with topology and outages within the
  period, hub weights are not in the feeds, and only the top constraints are
  included. R² is reported per node, computed about the mean as usual, so it
  can be negative when the included constraints explain a node worse than its
  own mean would. That is the signal that the driver is outside the set.
- **Not a correlation study.** The linear form is how the market clears, so
  the coefficients have a physical reading ($/MWh of basis per $/MWh of shadow
  price). But constraints that always bind together are collinear and split
  their joint effect unstably; read their contributions as a group. An
  optional ridge penalty (`ATTRIBUTION_RIDGE`, default 0) stabilises them at
  the cost of bias and must be disclosed if used.
- **Day-ahead only.** DAM basis on DAM shadow prices, from the same clearing.
  A real-time counterpart needs a real-time basis table, which does not
  exist yet; SCED shadow prices are therefore not used here.
- **Tallies use materiality floors.** Least squares gives every node a
  coefficient on every constraint, so without a floor every constraint
  "affects" every node and a node with a few cents of basis has a dominant
  constraint worth a few cents. A node counts as dominated only if its
  |mean basis| is at least `ATTRIBUTION_MATERIAL_BASIS` ($1/MWh), and a
  constraint counts as affecting a node only if its |contribution| is at
  least `ATTRIBUTION_MATERIAL_CONTRIBUTION` ($1/MWh). The per-node and
  per-contribution tables are unfiltered; only the per-constraint tallies
  apply the floors.
- **Same-hour only.** Shadow prices and basis are matched hour for hour.
  Several rows for one constraint in one hour (different contingencies) are
  summed, matching how `constraints.py` keys on constraint name.

## 18. Constraint names are resolved from the feeds, not looked up elsewhere

Constraint names such as `6437__F` are identifiers. Both shadow price feeds
carry, on every row, the from and to station, their voltage levels, the
limiting facility and the contingency under which the constraint bound. The
dictionary (`constraint_dictionary` table) reduces those rows to one record
per name.

**Assumption:** where a name appears with more than one value for an
attribute, the most frequent value is the element's description, and the
number of distinct contingencies is reported beside it. A name that has
covered several physical situations is therefore visible as such rather than
silently collapsed. Names absent from both feeds keep themselves as their
label, so the `element` column is never blank. No external mapping file or
ERCOT network model is consulted.
