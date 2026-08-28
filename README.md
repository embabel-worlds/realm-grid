# realm-grid

**When to run it.** The carbon intensity of the electricity behind your sites, half-hour by
half-hour, and the number that follows: how much CO2 you save by moving a flexible workload
into the cleanest window of the day.

```
GridSite ──HAS_GRID_NOW────▶ GridNow        regional, per site
UkPlace  ──HAS_GRID_NOW────▶ GridNow        the same, on realm-uk-streets' anchor
GridSite ──HAS_GRID_TODAY──▶ GridHalfHour   national, 48 periods
GridSite ──HAS_FUEL_MIX────▶ FuelShare      national, one row per fuel
```

Live, from three sites seeded as a test:

> **Manchester racks** — 420 kWh/day of batch ETL and model training, moved from the day's
> mean of 129 gCO2/kWh to the 11:30 window at 90 → **16.4 kg CO2/day, 6.0 tonnes/year**.
>
> **London office is 4.1× dirtier than York right now** (134 against 33 gCO2/kWh). For work
> that could run in either place, where it runs matters as much as when.

## Source

One: the [National Grid ESO carbon intensity API](https://carbonintensity.org.uk). Open,
keyless, no account, Great Britain only.

Only its **parameter-free** operations are used. The service does publish a rolling 48-hour
forecast, but every forward-looking endpoint requires an explicit `from` timestamp in its
path, and a producer's arguments are static — there is no way to say "from now". Declaring
those operations would have produced a realm that 400s on every call. So this realm answers
about **now** and about **today**, and says so rather than implying a forecast it cannot
fetch.

## Three decisions worth knowing about

**`forecast`, never `actual`, for anything still to come.** `actual` is settled and exists
only for periods that have passed. A cleanest-window computed from it would faithfully
recommend a window earlier this morning — a wrong answer that looks perfectly reasonable,
every time it runs. Every view and both handlers filter to periods ahead of now.

**Level is regional, shape is national — and they are never blurred.** Regional intensity
differs by a factor of three or four across Britain, so "how clean is my electricity" is a
regional question. But the half-hourly shape is only published nationally. This realm uses
the national curve to pick the hour and the regional reading to state the level, and every
view says which it is using.

**Two of the three producers take no key at all.** The national curve and the fuel mix are
the same figure for everybody, so they are declared without `keyArgs`: one HTTP call serves
any number of sites, and `echoKeyAs` links the rows back. Forty-eight periods across five
sites is forty-eight nodes and one request, not two hundred and forty and five.

## Getting an answer

```javascript
gateway.repository.createEntry({ type: "GridSite", data: {
  name: "CI fleet", outcode: "M3",
  workload: "nightly builds and model training",
  flexibleLoadKwh: "420",
}})
```

Then run `ShiftingSaves`, or open **Clean Window** (`apps/clean-window.html`).

## A trap worth recording

The regional endpoint nests a reading list inside a region element. Both of these fail the
same silent way — a successful HTTP call that produces no rows at all:

- a positional `[0]` in a `records:` path does not select; a nested wildcard
  (`$.data[*].data[*]`) does;
- an array index in the MIDDLE of a projection path (`data.0.intensity.forecast`) does not
  resolve either — the property arrives null, the identity check drops the record, and a
  perfectly good fetch yields nothing.

Select the record at the right depth and every projection below it is a plain field read.

## Testing

```bash
export EMBABEL_TOKEN=...
python3 scripts/test-views.py http://127.0.0.1:11043
```

Runs every view, fails on zero rows, surfaces every warning, and checks the guarantees:
that no recommended window is in the past, that the savings arithmetic reconciles against
the intensities it claims to use, and that regional and national figures are not confused.

## Licence

Apache 2.0. Carbon intensity data © National Grid ESO, used under its open terms.
