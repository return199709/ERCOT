# Findings

**Status: first results, from one month.** The pipeline was run end to end on
June 2025 (2025-06-01 to 2025-06-30): ingest on 2026-10-07 and 2026-10-08,
and `make analyze` plus `make summary` re-run on 2026-10-26 with the corrected
peak window, zone inheritance, congestion attribution and the constraint
dictionary. Every number below is
copied from that run's digest. Nothing here comes from synthetic fixtures or
from memory of how ERCOT behaves.

One month cannot support the year-over-year trend analysis or the constraint
seasonality view, and a single June is a hot, high-solar, high-congestion
month that should not be read as typical. Treat these as a validated first
cut, not conclusions.

## Scope of the run

| | |
| --- | --- |
| Period | 2025-06-01 to 2025-06-30 |
| DAM settlement points | 1,012 |
| Nodes with a resolvable hub | 978 |
| Node-hours of basis | 714,264 |
| Zone recovered through an identical price series | 59 settlement points, 0 zone conflicts |
| Outside the analysis by class | four DC ties (`DC_E`, `DC_L`, `DC_N`, `DC_R`): no zone, no hub |
| Unmapped, excluded | 15 unit-level names with no listed twin (`BYU_CC1`, `CHE_CC1`, `FORMOSA_CC1`, ...) |
| Constraint names resolved to stations | 436 of 450 |
| RTM rows | 2,946,821 (15-minute) |
| Data quality | 0 duplicate keys, 0 null prices, 0 wholly absent location-days; 7 locations with partial coverage; 7 partial RTM days |
| Shared price series | 180 groups covering 550 DAM locations settle at identical prices (same electrical bus) |

The shared-series point matters for every ranking below: a top-25 list can
contain the same price series several times under different names. Pairs such
as `ENDPARK_ESS1` / `FLUVANNA_1_2` and `TORR_ALL` / `CORAZON_RN` are one
observation each.

Zone inheritance (`ASSUMPTIONS.md` §1b) recovered 59 of the 78 points the
settlement point list alone could not place, with no group showing a zone
conflict. The dispatch node-day count rose by exactly 59 x 30, so the
recovered points flow through every downstream table.

## 1. Basis distribution

System-wide mean basis was −$0.13/MWh and the median node −$0.33/MWh, so the
hubs sit near the centre of the distribution as designed. The tails are wide.

**Worst nodes by mean basis ($/MWh, n = 720 hours each):**

| Location | mean | P5 | P95 | std |
| --- | --- | --- | --- | --- |
| ENDPARK_ESS1 / FLUVANNA_1_2 | −15.20 | −53.27 | 1.40 | 18.09 |
| BBREEZE_1_2 / ELSAUZ_ALL | −14.81 | −51.16 | 0.20 | 20.08 |
| LAUR_BESS_RN | −14.44 | −54.47 | 0.19 | 20.22 |
| TORR_ALL / CORAZON_RN | −13.74 | −55.07 | 0.52 | 20.11 |
| RN_SR_WIND1 | −13.72 | −50.82 | 0.19 | 19.21 |
| L_FRE_ESR_RN | −13.64 | −50.79 | 0.19 | 19.15 |
| LARDVFTN_G4 / G5 | −13.49 | −66.66 | 1.83 | 23.51 |
| OUTP_SLR_RN | −13.49 | −53.91 | 0.36 | 19.72 |
| CHALUP_ALL | −13.31 | −49.71 | 0.19 | 18.83 |
| BORDAS_345 | −13.17 | −51.38 | 0.62 | 19.30 |

These are South Texas (Rio Grande Valley, Laredo) and West Texas wind, solar
and storage nodes. The P95 near zero and P5 near −$50 say the pattern is not a
steady discount but frequent deep congestion hours against a flat baseline.

**Nodes at a premium to hub:** POTEETS_RN +$34.26, ELMCRK_RN +$29.09,
RUSSEKST_RN +$21.07, JUNORTH_RN / JUNCTION_RN about +$20, with P95 values of
$65 to $166. These sit on the import side of constraints and are the storage
sites of section 7.

525 of 978 nodes (53.7%) had a negative mean basis.

## 2. On-peak versus off-peak

On-peak is ERCOT 5×16 (hour-ending 07 to 22, weekdays, no NERC holidays):
336 on-peak and 384 off-peak hours per node in June.

Most of the worst nodes are more negative on-peak than off-peak, which is not
what a pure solar-cannibalisation story predicts:

| Location | off-peak mean | on-peak mean |
| --- | --- | --- |
| BBREEZE_1_2 / ELSAUZ_ALL | −10.49 | −19.74 |
| LAUR_BESS_RN | −10.18 | −19.30 |
| RN_SR_WIND1 | −9.70 | −18.32 |
| TORR_ALL / CORAZON_RN | −11.63 | −16.15 |
| ENDPARK_ESS1 / FLUVANNA_1_2 | −18.35 | −11.60 |

The South Texas group (BBREEZE, LAUR_BESS, CORAZON) is roughly twice as
discounted on-peak, consistent with export constraints binding when load is
high. ENDPARK / FLUVANNA in the west is the reverse, consistent with overnight
wind. Section 5b names the constraints behind each.

## 3. Basis and renewable output

Pearson correlation between hourly basis and hourly regional generation
(n ≈ 719 hours):

| Location | series | correlation |
| --- | --- | --- |
| HRZN_SLR_UN1, PEARSA_1_24, PEARSALL_RN, MROW_SLR_RN | NorthWest solar | −0.73 |
| TAYGETE_ALL, TAYGETE2_ALL, TOYAH_RN, REROCK_ALL, HOVEY_GEN, SGSA_DGR, ERSL_RN | NorthWest solar | −0.72 |
| HART_WND_RN | Panhandle wind | −0.72 |

A cluster of West Texas nodes loses $0.72 to $0.73 of basis per standard
deviation of NorthWest solar output. The sign and the geography are right.
Correlation is not causation: solar output, load and binding constraints all
co-move through the day. The solar region names are ERCOT's own and do not
map one-for-one onto the wind regions (`ASSUMPTIONS.md` §13).

## 4. Negative prices

12,747 of 727,944 DAM node-hours (1.75%) cleared negative; 353 of 1,012
settlement points saw at least one negative hour.

| Location | negative hours (of 720) | share | min price |
| --- | --- | --- | --- |
| ENDPARK_ESS1 / FLUVANNA_1_2 | 167 | 23% | −40.10 |
| DERMOTT_ALL | 149 | 21% | −30.84 |
| JADE_SLR_ALL | 148 | 21% | −30.13 |
| ANDMDSLR_ALL | 147 | 20% | −30.84 |
| AMADEUS_ALL | 145 | 20% | −30.84 |
| NOVA2S_UNIT1 | 140 | 19% | −25.11 |
| BBREEZE_1_2 / ELSAUZ_ALL | 134 | 19% | −36.51 |

The same West Texas solar and storage nodes that lead the worst-basis list
spend a fifth of June below zero.

## 5. Constraints by congestion cost

Ranked by shadow price × interval hours across DAM and SCED combined. The
element column comes from the feeds' own station and facility fields
(`ASSUMPTIONS.md` §18).

| constraint | element | total $-hours | intervals bound | mean shadow | max shadow |
| --- | --- | --- | --- | --- | --- |
| 6437__F | SCRCV 138 kV to KNAPP 138 kV | 137,239 | 3,850 | 240.59 | 2,160.00 |
| POT_PEAR_1 | PEARSALL 69 kV to POTEETS 69 kV | 130,504 | 1,658 | 521.81 | 2,585.54 |
| HARGRO_TWINBU1_1 | TWINBU 138 kV to HARGROVE 138 kV | 93,822 | 1,248 | 583.09 | 3,500.00 |
| HAINE__LA_PAL1_1 | LA_PALMA 138 kV to HAINE_DR 138 kV | 81,900 | 2,556 | 221.60 | 1,681.31 |
| ABNTHW_SERDEV1_1 | ABNTHWST 138 kV (transformer, same station both ends) | 72,438 | 708 | 519.29 | 3,500.00 |
| LARDVN_LASCRU1_1 | LARDVNTH 138 kV to LASCRUCE 138 kV | 61,963 | 2,433 | 162.70 | 1,261.94 |
| 1710__C | BELCNTY 138 kV to SALSW 138 kV | 58,178 | 1,015 | 320.11 | 3,500.00 |
| TREADW_YELWJC1_1 | TREADWEL 138 kV to YELWJCKT 138 kV | 44,598 | 2,542 | 155.86 | 3,163.88 |

Six constraints reached the $3,500 to $4,500/MWh shadow price caps at least
once. Thirteen of the top fifteen are 138 kV or 69 kV elements; the only
345 kV entry, STP to WAP, carries the single highest shadow price ($4,500)
but a modest total. June's congestion cost was mostly in the sub-transmission
network, not the backbone.

## 5b. Which constraint drives each node

Each node's hourly day-ahead basis was regressed, with no intercept, on the
hourly shadow prices of the 40 costliest constraints (`ASSUMPTIONS.md` §17).
The form is how nodal prices are built, so a good fit is expected if the
right constraints are in the set, and a bad one says the driver is outside
it.

| | |
| --- | --- |
| Nodes fitted | 978 |
| Median R² | 0.97 |
| Nodes with R² ≥ 0.5 | 952 |
| Nodes with R² < 0 | 0 |

The fit is close to exact: for the worst nodes the residual mean is within a
few cents of zero. Forty constraints account for June's day-ahead basis.

**Worst nodes and the element behind each:**

| Location | mean basis | dominant element | contribution | share of basis | R² |
| --- | --- | --- | --- | --- | --- |
| ENDPARK_ESS1 / FLUVANNA_1_2 | −15.20 | SCRCV 138 kV to KNAPP 138 kV (`6437__F`) | −14.60 | 96% | 0.99 |
| ELSAUZ_ALL / BBREEZE_1_2 | −14.81 | LA_PALMA 138 kV to HAINE_DR 138 kV | −4.76 | 32% | 0.98 |
| LAUR_BESS_RN | −14.44 | LA_PALMA 138 kV to HAINE_DR 138 kV | −6.06 | 42% | 0.99 |
| TORR_ALL / CORAZON_RN | −13.74 | LARDVNTH 138 kV to LASCRUCE 138 kV | −8.41 | 61% | 0.97 |
| RN_SR_WIND1 | −13.72 | LA_PALMA 138 kV to HAINE_DR 138 kV | −5.31 | 39% | 0.99 |
| L_FRE_ESR_RN | −13.64 | LA_PALMA 138 kV to HAINE_DR 138 kV | −5.29 | 39% | 0.99 |
| LARDVFTN_G4 / G5 | −13.49 | LARDVNTH 138 kV to LASCRUCE 138 kV | −11.37 | 84% | 0.99 |
| OUTP_SLR_RN | −13.49 | LARDVNTH 138 kV to LASCRUCE 138 kV | −8.11 | 60% | 0.97 |
| CHALUP_ALL | −13.31 | LA_PALMA 138 kV to HAINE_DR 138 kV | −5.16 | 39% | 0.99 |
| BORDAS_345 | −13.17 | LARDVNTH 138 kV to LASCRUCE 138 kV | −7.72 | 59% | 0.97 |

Three stories, not twenty-five, and each is one 138 kV line:

- **West Texas** (ENDPARK, FLUVANNA): the Scurry County to Knapp 138 kV
  line, `6437__F`, is 96% of the basis. One line is the whole story at
  those nodes, and it is also the costliest constraint in ERCOT for the
  month.
- **Rio Grande Valley** (BBREEZE, ELSAUZ, LAUR_BESS, RN_SR_WIND1, L_FRE_ESR,
  CHALUP): the La Palma to Haine Drive 138 kV line is the largest single
  driver at 32 to 42%, with the rest spread across several other Valley
  export constraints. The discount here is a portfolio, which is why it is
  deeper on-peak when all of them bind.
- **Laredo** (TORR, CORAZON, LARDVFTN, OUTP_SLR, BORDAS, RELOJ): the Laredo
  VFT North to Las Cruces 138 kV line carries 58 to 84%.

Pearsall to Poteets 69 kV (`POT_PEAR_1`), second in the cost ranking,
dominates none of the discount nodes: it is the import constraint behind
the POTEETS and PEARSALL premium.

**Which elements move the most nodes**, counting only nodes with at least
$1/MWh of mean basis and contributions of at least $1/MWh:

| element | constraint | nodes dominated | nodes affected | mean shadow (all hours) | hours bound |
| --- | --- | --- | --- | --- | --- |
| VICTORIA 138 kV to MAGRUDER 138 kV | MAGRUD_VICTOR2_1 | 163 | 364 | 5.47 | 608 |
| MDO 345 kV to PHR 345 kV | MDOPHR99_A | 151 | 148 | 12.53 | 324 |
| LNGSW 345 kV to CONSW 345 kV | 6056__Z | 119 | 162 | 17.79 | 356 |
| SCRCV 138 kV to KNAPP 138 kV | 6437__F | 87 | 195 | 90.98 | 555 |
| LA_PALMA 138 kV to HAINE_DR 138 kV | HAINE__LA_PAL1_1 | 50 | 91 | 52.58 | 417 |
| LARDVNTH 138 kV to LASCRUCE 138 kV | LARDVN_LASCRU1_1 | 48 | 147 | 43.90 | 488 |
| (unresolved) | E_PASP | 42 | 185 | 13.38 | 258 |

Two kinds of constraint show up here. The three at the top have low shadow
prices but bind for hundreds of hours and reach hundreds of nodes with small
contributions each: broad, shallow congestion across a region, the
Victoria-area line in particular touching 364 nodes. The three below them
are the deep, local ones from the worst-node table: high shadow prices,
fewer nodes, large contributions each. A site screen should treat these
differently; the first kind shifts a whole zone's basis by a dollar or two,
the second decides whether a specific site is viable.

`E_PASP` is one of 14 names (of 450) the feeds carry without station
fields; it is reported by name.

## 6. Day-ahead versus real-time

639 of 1,012 settlement points were flagged as persistently biased, 564 with
day-ahead above real-time and 75 the other way. The strongest real-time
premia are at the same premium nodes as section 1 (RUSSEKST_RN −$10.00 mean
spread, LANTANA_RN −$4.91, BATCAVE_RN −$3.34).

The flag count is inflated. The test treats hourly spreads as independent,
and they are serially correlated, so the standard error is too small. Read
the 639 as "most of the market carried a day-ahead premium in June 2025",
which is a known pattern, not as 639 independent trading signals.

## 7. Storage

**7a. Price screen.** Mean daily top-4 minus bottom-4 hour spread: POTSVIL_RN
$156.97, POTEETS_RN $141.10, ELMCRK_RN $130.45, RUSSEKST_RN $85.99,
HOLCOMB_RN1 $80.64.

**7b. Optimal dispatch**, 25 MW / 100 MWh, 85% round trip, $5/MWh
throughput cost, perfect foresight, so an upper bound and not a backtest:

| Location | revenue per day | $/kW-year | cycles per day |
| --- | --- | --- | --- |
| POTSVIL_RN | 14,574 | 212.79 | 1.01 |
| POTEETS_RN | 12,739 | 185.99 | 1.02 |
| ELMCRK_RN | 11,714 | 171.02 | 1.00 |
| HOLCOMB_RN1 | 6,730 | 98.26 | 1.00 |
| CALLAHA_WND1 | 6,673 | 97.43 | 1.11 |
| GUNMTN_NODE | 6,060 | 88.47 | 1.01 |

Median across all nodes: $41/kW-year. The dispatch model cycles about once a
day at these prices; the degradation cost is doing its job.

**7c. Where the revenue comes from.** A battery at the trading hubs earned
$84,895 over the month from the system-wide price shape. Against that:

| Location | node revenue | basis revenue | basis share |
| --- | --- | --- | --- |
| POTSVIL_RN | 437,233 | 352,338 | 81% |
| POTEETS_RN | 382,162 | 297,267 | 78% |
| ELMCRK_RN | 351,405 | 266,510 | 76% |
| HOLCOMB_RN1 | 201,905 | 117,010 | 58% |
| CALLAHA_WND1 | 200,205 | 115,310 | 58% |

Median basis share across all nodes: −0.1%. Basis added value at 456 of 919
nodes and subtracted it at the rest.

This is the most useful single result of the run. For the typical node,
siting adds nothing to a battery's arbitrage value: it earns the hub shape.
For a small set of import-constrained nodes behind `POT_PEAR_1`, three
quarters of the value is the site. Those sites are also where the DA–RT
spread is most negative, so the perfect-foresight figure overstates what a
day-ahead-bidding operator would capture there more than it does elsewhere.

## What this run validated

- The ingest, quality, mapping and analysis code works against live ERCOT
  feeds. Two schema assumptions were wrong and were caught by `make doctor`
  before the backfill: the mapping column is `Resource Node`, and the
  historical load series needs the archive endpoint, not the MIS listing.
- The load-zone proxy for hub assignment covers 93.5% of nodes from the
  settlement point list alone.
- The shared-series check found 180 groups; without it the worst-25 list
  would have counted several buses twice. The same groups recovered 59
  unmapped points with no zone conflicts.
- The structural attribution model fits with a median R² of 0.97 and
  near-zero residuals, which is what nodal pricing theory predicts if the
  shadow prices in the set are the ones that matter. It names
  geographically coherent constraints for each cluster of discount nodes.
- The constraint dictionary resolved 436 of 450 names from the feeds' own
  station fields, so the attribution reads in terms of named 138 kV lines
  rather than identifiers.

## What it did not validate

- Anything about trend or seasonality (one month).
- Whether the NOIE zone-to-hub choices (`ASSUMPTIONS.md` §1) matter; re-cut
  against the `basis_vs_HB_*` columns before quoting a NOIE node.
- Fourteen constraint names (3%) the feeds carry without station fields,
  `E_PASP` among them. They are reported by name.

## Next

1. Backfill 12 to 24 months, stopping at or treating explicitly the
   2025-12-05 RTC+B go-live, and fill in trend and seasonality. Attribution
   over a longer window will also show whether the three lines above are
   June phenomena or structural.
2. One chart per section above, then a one-page write-up on the template in
   `docs/portfolio/CONVENTIONS.md`.
3. A demo-data path so the dashboard can be hosted without ERCOT
   credentials.
