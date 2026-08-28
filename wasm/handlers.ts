/*
 * Scheduled agents over the grid.
 *
 * A view answers when somebody asks. The grid does not wait to be asked: the
 * cleanest window of the day is only useful BEFORE it happens, and by the time
 * anyone thinks to open a dashboard the wind has usually dropped. These run on a
 * clock and produce something a scheduler — or a person — can act on.
 *
 * A handler reads the graph with ctx.gateway.cypher.query. There is no global
 * `gateway` here, and `gateway.kg.query` is the code_mode surface rather than
 * the wasm one; the host tools granted inside wasm are cypher_query, sql_query
 * and sql_update. cypher_query takes no bound parameters, so every threshold
 * below is applied in TypeScript over a bounded read rather than concatenated
 * into the query string.
 */

type Row = Record<string, any>

async function read(ctx: any, cypher: string): Promise<Row[]> {
  const res = await ctx.gateway.cypher.query({ cypher })
  if (!res) return []
  if (Array.isArray(res)) return res
  if (Array.isArray(res.rows)) return res.rows
  if (res.data && Array.isArray(res.data.rows)) return res.data.rows
  return []
}

const num = (v: any): number => {
  // Number(null) is 0, and Number('') is 0. Both would turn "we have no value for this" into a
  // real, low, plausible number — an unscored project reported as 0/10 and ranked the most
  // exposed thing in the estate, which is what this helper originally did.
  if (v === null || v === undefined || v === '') return NaN
  const n = Number(v)
  return Number.isFinite(n) ? n : NaN
}

/*
 * The window sweep. Finds the cleanest half-hours still to come today and prices
 * the move for every site with a flexible load.
 *
 * `forecast` and not `actual` is load-bearing. `actual` is settled and exists
 * only for periods that have already passed, so a sweep built on it would
 * faithfully recommend a window earlier this morning — a wrong answer that looks
 * entirely reasonable, every time it runs.
 */
export async function cleanWindowSweep(args: { minSavingKg?: number }, ctx: any) {
  const periods = await read(ctx, `
    MATCH (g:GridSite)-[:HAS_GRID_TODAY]->(h:GridHalfHour)
    RETURN DISTINCT h.periodFrom AS periodFrom, h.forecast AS forecast, h.index AS band
    LIMIT 200
  `)
  const sites = await read(ctx, `
    MATCH (g:GridSite)
    RETURN g.name AS name, g.outcode AS outcode, g.workload AS workload,
           g.flexibleLoadKwh AS flexibleLoadKwh
    LIMIT 200
  `)

  const nowMs = Date.now()
  const parsed = periods
    .map(p => ({ at: String(p.periodFrom), g: num(p.forecast), band: p.band }))
    .filter(p => Number.isFinite(p.g))
  if (!parsed.length) {
    return { checkedAt: new Date().toISOString(), status: 'no grid data available', sites: [] }
  }

  const dayMean = parsed.reduce((s, p) => s + p.g, 0) / parsed.length
  // "Z" without seconds is not parseable everywhere; normalise before comparing.
  const ahead = parsed.filter(p => Date.parse(p.at.replace('Z', ':00Z')) > nowMs)
  const best = ahead.reduce<null | typeof parsed[0]>((b, p) => (b === null || p.g < b.g ? p : b), null)

  const floor = args && typeof args.minSavingKg === 'number' ? args.minSavingKg : 0
  const priced = sites
    .filter(s => Number.isFinite(num(s.flexibleLoadKwh)))
    .map(s => {
      const kwh = num(s.flexibleLoadKwh)
      const savedKg = best ? (kwh * (dayMean - best.g)) / 1000 : 0
      return {
        site: s.name,
        workload: s.workload,
        flexibleLoadKwh: kwh,
        moveTo: best ? best.at : null,
        cleanestGramsPerKwh: best ? best.g : null,
        dayMeanGramsPerKwh: Math.round(dayMean),
        kgCo2SavedPerDay: Math.round(savedKg * 10) / 10,
        tonnesCo2SavedPerYear: Math.round((savedKg * 365) / 100) / 10,
      }
    })
    .filter(s => s.kgCo2SavedPerDay >= floor)
    .sort((a, b) => b.kgCo2SavedPerDay - a.kgCo2SavedPerDay)

  const totalKg = priced.reduce((s, x) => s + x.kgCo2SavedPerDay, 0)

  return {
    checkedAt: new Date().toISOString(),
    windowsRemainingToday: ahead.length,
    dayMeanGramsPerKwh: Math.round(dayMean),
    cleanestWindowUtc: best ? best.at : null,
    cleanestGramsPerKwh: best ? best.g : null,
    totalKgCo2SavedPerDay: Math.round(totalKg * 10) / 10,
    headline: best
      ? `Cleanest remaining window today is ${String(best.at).slice(11, 16)} UTC at ${best.g} gCO2/kWh,` +
        ` against a day mean of ${Math.round(dayMean)}. Moving every flexible load there saves` +
        ` ${Math.round(totalKg * 10) / 10} kg CO2 today.`
      : 'No half-hours left today — the whole day has settled.',
    sites: priced,
  }
}

/*
 * Where, not when. Britain's regions routinely differ by a factor of three or
 * four at the same instant, so for work that can run in more than one place the
 * cheapest carbon decision is often a relocation rather than a delay. This says
 * whether that is true right now and by how much.
 */
export async function siteSpreadWatch(args: { minSpread?: number }, ctx: any) {
  const rows = await read(ctx, `
    MATCH (g:GridSite)-[:HAS_GRID_NOW]->(n:GridNow)
    RETURN g.name AS site, g.outcode AS outcode, n.intensity AS intensity, n.index AS band
    LIMIT 200
  `)
  const sites = rows
    .map(r => ({ site: r.site, outcode: r.outcode, g: num(r.intensity), band: r.band }))
    .filter(s => Number.isFinite(s.g))
    .sort((a, b) => a.g - b.g)

  if (sites.length < 2) {
    return {
      checkedAt: new Date().toISOString(),
      sitesCompared: sites.length,
      verdict: 'Fewer than two sites have a reading, so there is no spread to report.',
    }
  }

  const cleanest = sites[0]
  const dirtiest = sites[sites.length - 1]
  const spread = dirtiest.g - cleanest.g
  const floor = args && typeof args.minSpread === 'number' ? args.minSpread : 50

  return {
    checkedAt: new Date().toISOString(),
    sitesCompared: sites.length,
    cleanest,
    dirtiest,
    spreadGramsPerKwh: spread,
    timesDirtier: cleanest.g > 0 ? Math.round((dirtiest.g / cleanest.g) * 10) / 10 : null,
    worthRelocating: spread >= floor,
    verdict: spread >= floor
      ? `${dirtiest.site} is running at ${dirtiest.g} gCO2/kWh while ${cleanest.site} is at ${cleanest.g}` +
        ` — ${Math.round((dirtiest.g / Math.max(cleanest.g, 1)) * 10) / 10}x cleaner. Anything movable between them` +
        ' should be running at ' + cleanest.site + '.'
      : `All sites are within ${spread} gCO2/kWh of each other; where the work runs does not matter much right now.`,
    sites,
  }
}

/* Through the working day, so a recommendation is never more than a few hours
   stale and lands before the evening batch window is set. */
defineSchedule('cleanWindowSweep', '0 0 6,9,12,15,18 * * *')
/* Twice a day is enough for a regional comparison: the spread moves with weather
   fronts, not with the minute. */
defineSchedule('siteSpreadWatch', '0 30 7,16 * * *')
