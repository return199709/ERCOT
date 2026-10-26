# Assumptions

Each entry: the assumption, why, and how to revisit it. Fill in as decided.

## To settle before building

- [ ] **Years in scope** and the resulting row-count estimate (measure it).
- [ ] **Footprint filter**: balancing authority = ERCOT, and how plants are
      mapped to it.
- [ ] **CO₂ unit** in the published data, and the single conversion point.
- [ ] **Timestamp semantics** (local standard vs daylight time) and the single
      UTC conversion point.
- [ ] **Measurement flags**: which flags mean measured vs substituted, and how
      the measured share is computed.
- [ ] **Intensity definition** and its stated limitations (fossil CEMS, gross
      load, total generation denominator).
- [ ] **Reconciliation source** and tolerance for the annual check.
- [ ] **Completeness rule**: how expected hours per unit-month are defined
      (outages, retirements, new units).
- [ ] **Rejection thresholds**: when a run fails vs warns.
