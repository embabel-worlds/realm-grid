---
name: grid
description: Answer questions about electricity carbon intensity and when to run flexible workloads — how clean the grid is at a site right now, which hours today are cleanest, how much CO2 shifting a workload saves, what is generating, and how much the sites differ. Use for "when should we run this", "how clean is our power", "is now a good time", "what would shifting save", "which site should this run at", or any question about carbon, grid intensity or carbon-aware scheduling.
---

# The grid, and when to use it

Britain's carbon intensity swings by a factor of three or four within a single day and by
as much again between regions. Flexible work — nightly builds, batch ETL, model training,
vehicle charging — does not care when or where it runs. This realm turns that into a
number.

## Run a view

| The question | The view |
|---|---|
| Is now a good time? | `GridNow` — per site, regional |
| When today is cleanest? | `CleanestWindowToday` — remaining hours only |
| What does shifting save? | `ShiftingSaves` — kg/day and tonnes/year |
| What does the day look like? | `TodayCurve` — 48 half-hours |
| Where should this run? | `SpreadAcrossSites` |
| Why is it clean or dirty? | `FuelMixNow` |
| The same for places we watch | `UkPlaceGridNow` |
| Write it up | `SchedulingBriefing` — costs a model call |

Two scheduled agents run without being asked: `cleanWindowSweep` five times through the
day, and `siteSpreadWatch` twice.

## The two things to get right

**Read `forecast`, not `actual`, for anything still to come.** `actual` is settled and
exists only for periods that have already passed. A "cleanest window" computed from
`actual` silently only ever considers the past — the exact opposite of the question, and
it looks entirely reasonable because the numbers are real.

**Level is regional; shape is national.** How clean a site's electricity actually is comes
from `GridNow` and differs sharply by region. The half-hourly curve is published
nationally only, so it is the right thing to pick an HOUR from and the wrong thing to
quote as a site's own figure. Never present one as the other.

## Saying it properly

- **Quote the band, not just the number.** 134 gCO2/kWh means nothing to most people;
  "moderate, and about four times dirtier than York right now" means something.
- **Under 100 is clean, over 250 is dirty**, and a normal day spans roughly a factor of
  three. Use that to calibrate, not a fixed threshold.
- **The annual saving is an order-of-magnitude figure.** It assumes today's spread is
  typical, which it is not exactly. It answers "is this worth doing at all", and it scales
  linearly with the `flexibleLoadKwh` the user entered — so if that was a guess, say so.
- **A site with no `flexibleLoadKwh` cannot be priced**, and its absence from
  `ShiftingSaves` means "not recorded", never "nothing to gain".
- **Great Britain only.** The source does not cover Northern Ireland or anywhere outside
  GB. A site elsewhere is out of scope, not clean.
- **Times are UTC.** In British Summer Time the clock the user reads is an hour ahead of
  every figure here; say "UTC" every time rather than letting them assume local.

## Warnings

A `PRODUCER_ERROR` means a reading could not be fetched. In this realm an empty result
reads as "nothing to report", so name the sites that failed rather than presenting a short
list as a complete one.
