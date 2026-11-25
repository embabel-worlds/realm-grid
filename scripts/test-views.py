#!/usr/bin/env python3
"""Run every view this realm ships against a LIVE host, and check its guarantees.

Row counts are not the interesting failure here. This realm's characteristic bug
is a full, plausible table that recommends a window EARLIER TODAY — which happens
the moment anything reads `actual` (settled, past-only) instead of `forecast`.
The numbers are real, the table looks right, and the advice is useless. So the
ground-truth section asserts the properties rather than the volume:

  * no recommended window is in the past;
  * the savings arithmetic reconciles against the intensities it claims to use;
  * the day's mean really is the mean of the day's periods;
  * settled and unsettled periods are labelled the way the data says.

    export EMBABEL_TOKEN=...
    python3 scripts/test-views.py [http://127.0.0.1:11043]
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:11043").rstrip("/")
TOKEN = os.environ.get("EMBABEL_TOKEN")

VIEWS = {
    "GridNow":             {"limit": 25},
    "UkPlaceGridNow":      {"limit": 25},
    "TodayCurve":          {"limit": 48},
    "CleanestWindowToday": {"limit": 6},
    "ShiftingSaves":       {"limit": 25},
    "FuelMixNow":          {"limit": 12},
    "SpreadAcrossSites":   {},
    "SchedulingBriefing":  {"limit": 12},
}

# Empty is legitimate here only where the realm genuinely may have nothing to say.
MAY_BE_EMPTY = {
    "UkPlaceGridNow":      "realm-uk-streets may not be installed; this join is then dormant",
    "CleanestWindowToday": "after the last settlement period of the day there is no window left",
}

failures, notes = [], []


# A figure the engine marks short is not the realm's figure, and a battery that counts it reports
# drift that is the source's. short(d) reads an answer's own error, reason, warnings and outcome and
# is None when the answer is whole, else the line that stands in for the figure: "REFUSED: <why>"
# or "PARTIAL <n>: <the engine's reason>". It reads both wires: a query answer (`rows`, `warnings`
# as strings opening with the engine's code) and a view envelope (`status`, `outcome`, `warnings`
# as {code, message}).
# Raw warning codes that mean rows or values may be missing (the engine's incompleteness kinds).
# Cost notes (FILTERED_IN_GRAPH, AGGREGATE_NOT_PUSHED, EMPTY_NOT_KEPT, PUSHDOWN_VALUE_UNMATCHED),
# FILTER_STARVED (an honest empty), STALE_COPY, FIELDS_WITHHELD and UNKNOWN_VIA leave every row in place.
SHORT_CODES = (
    "PARTIAL_RESULT", "PRODUCER_ERROR", "NEEDS_FILTER", "NEEDS_PRODUCER", "FILTER_REJECTED",
    "UNPUSHED_FILTER", "AMBIGUOUS_LABEL", "INCOMPLETE_TRAVERSAL", "INCOMPLETE_RANKING",
    "INCOMPLETE_AGGREGATE", "INCOMPLETE_INPUT", "MATERIALIZATION_FAILED", "REDUCTION_FAILED",
    "UNPARSEABLE_ANSWER", "TERMS_UNAVAILABLE", "COMPUTE_FAILED", "PROPERTY_NOT_STORED",
    "FOLLOW_CAPPED", "UNLINKED_CHILDREN", "RESOLUTION_DROPPED", "AGENTIC_DEGRADED",
    "SOURCE_UNANSWERED",
)
# The typed `reason` a query result carries when it is not a clean answer and not an honest empty.
SHORT_REASONS = ("UNBOUNDED", "PARTIAL_NOT_MATCHED", "UNPUSHED_FILTER", "DISCONNECTED",
                 "INTERNAL_ERROR", "WRITE_IN_PROGRESS", "KILLED", "TOO_EXPENSIVE")
# Public warning codes on a view envelope that mean the same.
SHORT_PUBLIC = ("PARTIAL", "REDUCTION_FAILED", "COMPUTE_FAILED", "PROPERTY_NOT_STORED",
                "AGENTIC_DEGRADED", "RATE_LIMITED", "SOURCE_UNAVAILABLE", "SOURCE_REJECTED",
                "INVALID_FILTER", "UNPUSHED_FILTER", "TOO_BROAD", "FETCH_CAPPED",
                "INDEX_UNAVAILABLE", "ARGUMENT_REFUSED")


def short(d, figure=None):
    tag = "PARTIAL" if figure is None else "PARTIAL %s" % (figure,)
    if not isinstance(d, dict):
        return "REFUSED: not an engine answer: " + str(d)[:160]
    if "outcome" in d or "status" in d:  # a view envelope
        err = d.get("error") or {}
        if d.get("status") != "SUCCEEDED":
            return "REFUSED: %s %s" % (d.get("status"), (err.get("code", "") + " " + err.get("message", "")).strip()[:160] if isinstance(err, dict) else str(err)[:160])
        ws = [w for w in d.get("warnings") or [] if isinstance(w, dict) and w.get("code") in SHORT_PUBLIC]
        if d.get("outcome") not in ("OK", "EMPTY") or ws:
            why = ws[0]["code"] + ": " + ws[0].get("message", "") if ws else "outcome " + str(d.get("outcome"))
            return "%s: %s" % (tag, why[:200])
        return None
    if d.get("error"):
        return "REFUSED: " + str(d["error"])[:160]
    if d.get("run"):
        return "%s: the run had not finished (%s)" % (tag, d["run"])
    ws = [w for w in d.get("warnings") or [] if isinstance(w, str) and w.split(":", 1)[0].strip() in SHORT_CODES]
    if ws:
        return "%s: %s" % (tag, ws[0][:200])
    if d.get("reason") in SHORT_REASONS:
        return "%s: reason %s" % (tag, d["reason"])
    return None


def run_view(name, params):
    req = urllib.request.Request(
        f"{BASE}/api/v1/admin/kg/views/{name}/run",
        data=json.dumps(params).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


def parse(ts):
    """The API writes `2026-08-28T11:30Z` — no seconds, which fromisoformat rejects."""
    if not ts:
        return None
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00")
                                  if len(str(ts)) > 17 else str(ts).replace("Z", ":00+00:00"))


def check_views():
    results = {}
    for name, params in VIEWS.items():
        try:
            res = run_view(name, params)
        except urllib.error.HTTPError as e:
            failures.append(f"{name}: HTTP {e.code} {e.read()[:200]!r}")
            continue
        except Exception as e:  # noqa: BLE001 — a harness reports; it does not raise
            failures.append(f"{name}: {e}")
            continue
        results[name] = res
        rows, warns = res.get("rows") or [], res.get("warnings") or []
        # A warning that says rows are missing fails the view: its table is not the answer, however
        # plausible it looks. Every other warning stays a note to read.
        s = short(res, len(rows))
        if s:
            failures.append(f"{name}: {s}")
        if not rows and name not in MAY_BE_EMPTY:
            failures.append(f"{name}: ZERO ROWS — a join that never fires looks exactly like this")
        for w in warns:
            notes.append(f"{name}: {str(w)[:200]}")
        why = f"  ({MAY_BE_EMPTY[name]})" if not rows and name in MAY_BE_EMPTY else ""
        print(f"  {name:<22}{len(rows):>4} rows{why}")
    return results


def check_ground_truth(results):
    now = datetime.now(timezone.utc)

    # 1. THE guarantee: never recommend a window that has already gone.
    for row in (results.get("CleanestWindowToday") or {}).get("rows") or []:
        t = parse(row.get("startsUtc"))
        if t and t < now:
            failures.append(
                f"ground truth: CleanestWindowToday offers {row.get('startsUtc')}, which is in the "
                f"past — something is reading `actual` (settled, past-only) instead of `forecast`"
            )
    print("  no recommended window is in the past")

    # 2. The savings arithmetic must follow from the numbers it prints.
    for row in (results.get("ShiftingSaves") or {}).get("rows") or []:
        kwh = row.get("flexibleLoadKwhPerDay")
        mean, best = row.get("dayMeanGramsPerKwh"), row.get("cleanestGramsPerKwh")
        claimed = row.get("kgCo2SavedPerDay")
        if None in (kwh, mean, best, claimed):
            continue
        expect = kwh * (mean - best) / 1000.0
        if abs(expect - claimed) > 0.2:
            failures.append(
                f"ground truth: {row.get('site')} claims {claimed} kg/day, but "
                f"{kwh} kWh x ({mean} - {best}) g/kWh = {round(expect, 1)} kg"
            )
        if claimed < 0:
            failures.append(f"ground truth: {row.get('site')} claims a NEGATIVE saving ({claimed} kg)")
        yearly = row.get("tonnesCo2SavedPerYear")
        if yearly is not None and abs(yearly - claimed * 365 / 1000.0) > 0.2:
            failures.append(
                f"ground truth: {row.get('site')} annual {yearly} t does not follow from {claimed} kg/day"
            )
    print("  savings arithmetic reconciles against its own inputs")

    # 3. The day mean must be the mean of the day.
    curve = (results.get("TodayCurve") or {}).get("rows") or []
    saves = (results.get("ShiftingSaves") or {}).get("rows") or []
    if curve and saves:
        vals = [r["forecast"] for r in curve if r.get("forecast") is not None]
        if vals:
            mean = sum(vals) / len(vals)
            claimed = saves[0].get("dayMeanGramsPerKwh")
            if claimed is not None and abs(mean - claimed) > 1.5:
                failures.append(
                    f"ground truth: day mean reported as {claimed} but the curve's own mean is {round(mean)}"
                )
    print("  the day mean is the mean of the day")

    # 4. Settled/unsettled must match what the data actually carries.
    for row in curve:
        settled = row.get("actual") is not None
        if settled != (row.get("status") == "settled"):
            failures.append(
                f"ground truth: {row.get('periodFrom')} labelled '{row.get('status')}' "
                f"but actual={row.get('actual')}"
            )
    print("  settled and unsettled periods are labelled honestly")

    # 5. Regional and national must not be silently equated.
    gn = (results.get("GridNow") or {}).get("rows") or []
    if gn and curve:
        if all(r.get("gramsCo2PerKwh") == curve[0].get("forecast") for r in gn) and len(gn) > 1:
            notes.append("GridNow matches the national curve exactly for every site — "
                         "verify the regional producer is really being used")
    print("  regional readings are not the national number")


def main():
    if not TOKEN:
        sys.exit("EMBABEL_TOKEN is not set — this harness needs an admin bearer token. It refuses "
                 "to run rather than report a green that only means it never asked.")
    print(f"realm-grid against {BASE}\n\nviews:")
    results = check_views()
    print("\nground truth:")
    check_ground_truth(results)

    if notes:
        print("\nwarnings and observations:")
        for n in notes:
            print(f"  {n}")
    if failures:
        print(f"\nFAILED ({len(failures)}):")
        for f in failures:
            print(f"  {f}")
        sys.exit(1)
    print("\nOK — every view answered and every guarantee holds.")


if __name__ == "__main__":
    main()
