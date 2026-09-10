# SPILLTRACE — AIS Pipeline Specification

**Owner:** Agent 4 · Traces: FR-011…FR-014, SCORE-006, CON-002, CON-007, AC-08, AC-09
**Evidence base:** `docs/DECISIONS.md` AD-21…AD-26.

```
AISStream WSS ──► ingest loop ──► normalise ──► validate ──► PostGIS
   (or synthetic)      (no DB work here)                        │
                                                                ▼
                                            clean ──► segment ──► trajectory ──► quality
                                                                                    │
                                                                                    ▼
                                                            correlate ──► score (SCORE-006)
```

---

## 1. Ingestion (FR-011)

**Endpoint** `wss://stream.aisstream.io/v0/stream`. The API key is server-side only; the
browser never connects (CON-004).

Subscription — **first frame, within 3 seconds**, and it *replaces* rather than adds:

```json
{ "APIKey": "<server-side>",
  "BoundingBoxes": [[[22.0, 68.5], [23.5, 70.5]]],
  "FilterMessageTypes": ["PositionReport", "ShipStaticData"] }
```

**Corner pairs are `[latitude, longitude]` — latitude first.** Reversing them yields a
connection that succeeds and then stays silent forever, because an invalid subscription
produces no error. The client therefore:

1. asserts a `SubscriptionConfirmation` frame arrives, and fails hard if it does not;
2. negotiates `permessage-deflate` and asserts `CompressionEnabled` (from September 2026
   uncompressed connections are bandwidth-limited);
3. runs a **stall watchdog** — no frame for 90 s → tear down and reconnect;
4. reconnects with exponential backoff + jitter, re-subscribing every time;
5. rate-limits subscription updates to 1/second;
6. **never touches the database in the read loop** — AISStream drops messages for slow
   consumers, so the loop only parses and enqueues, and a separate task writes in batches.

### Envelope quirks (each one is a real bug if ignored)

| Quirk | Handling |
|---|---|
| `Message` has a single key equal to `MessageType` | `payload = msg["Message"][msg["MessageType"]]` |
| `MetaData` mixes casing: `MMSI`, `ShipName` capitalised; `latitude`, `longitude`, `time_utc` lowercase | read defensively, but prefer `payload["Latitude"]/["Longitude"]` |
| `ShipName` is space-padded to 20 characters | `.strip()` |
| `time_utc` is Go's `2026-08-01 18:20:43.237370229 +0000 UTC` with a **variable-length** fraction | regex parser; `datetime.fromisoformat` fails on this |
| `time_utc` is **server receipt time**, not transmit time | stored as such; never used for sub-minute geometry |

## 2. Normalisation (AIS-005…AIS-008)

Units arrive already decoded — `Sog` in knots, `Cog` in degrees, `TrueHeading` integer
degrees, `MaximumStaticDraught` in metres. Whether AISStream normalises ITU-R M.1371
sentinel values is **not documented**, so they are filtered defensively at the boundary
and converted to `NULL`, never to a number:

| Field | Sentinel | Meaning |
|---|---|---|
| `Sog` | `≥ 102.2` | not available / ≥ 102.2 kn |
| `Cog` | `≥ 360` | not available |
| `TrueHeading` | `511` | not available |
| `Latitude` | `> 90` (91) | not available |
| `Longitude` | `> 180` (181) | not available |
| `RateOfTurn` | `-128` | not available |
| `Timestamp` (second-of-minute) | `60`–`63` | receiver status, not a time |
| ship `Type` | `0`, or `> 99` | not available |
| Dimension A/B `511`, C/D `63` | at-or-above limit | |
| ETA month `0`, day `0`, hour `24`, minute `60` | not available | |

`RateOfTurn` is **UNCERTAIN** — the schema types it as an integer, so it may be the raw
`ROT_AIS = 4.733·√(ROT_sensor)` encoding. It is decoded as `sign(x)·(x/4.733)²`, flagged
for empirical validation, and **not used in scoring**.

### MMSI validity (AIS-006)

Nine digits; ship MID (first three) in **201–775**. Reserved prefixes are recorded but
excluded from vessel attribution:

| Pattern | Station |
|---|---|
| `MIDXXXXXX` | ship — the only form used for attribution |
| `0MIDXXXXX` / `00MIDXXXX` | group of ships / coast station |
| `111MIDXXX` | SAR aircraft |
| `99MIDXXXX` / `98MIDXXXX` | aid to navigation / auxiliary craft |
| `970/972/974…` | AIS SART / MOB / EPIRB-AIS |
| `8MIDXXXXX` | diver's radio |

**MMSI is a radio identifier and is reassigned over time.** IMO from `ShipStaticData`
is the durable key; both are stored and the report states which was used.

## 3. Cleaning (FR-012, P17-001…P17-007)

Order matters — each step assumes the previous one ran.

| Step | Rule | Flag |
|---|---|---|
| Deduplicate | identical `(mmsi, timestamp_1s, round(lat,5), round(lon,5))`; also sub-second repeats. Enforced again by a DB unique constraint on `(mmsi, timestamp, source)` | `DUPLICATE` |
| Coordinates | range check; reject exact `(0, 0)` | `INVALID_COORDINATE`, `NULL_ISLAND` |
| Timestamps | reject future (> now + 5 min) and epoch-zero; sort per MMSI | `BAD_TIMESTAMP`, `FUTURE_TIMESTAMP` |
| Reported speed | `SOG > 30 kn` → invalid | `IMPLAUSIBLE_SOG` |
| Implied speed | Haversine/Δt `> 40 kn` → impossible jump | `IMPOSSIBLE_JUMP` |
| Kinematic | displacement `> v_{i−1}·Δt + ½·a_max·Δt²`, `a_max = 0.15 kn/s`; **check segment `i→i+1` too before correcting** | `KINEMATIC_OUTLIER` |
| COG consistency | `|COG − bearing(p_{i−1}, p_i)| > 90°` while `SOG > 1 kn` | `COG_INCONSISTENT` |

Two speed thresholds, deliberately different numbers: a reported-field error and a
derived-position error are different failure modes. Checking the following segment before
correcting matters because **one bad fix violates two segments while a genuine manoeuvre
violates one** — correcting naïvely destroys real course changes.

Flagged rows are **kept** with `is_valid = false` and a reason. Evidence is not deleted.

## 4. Gaps — three thresholds, deliberately named apart (AD-24, CON-002)

| Constant | Value | Use |
|---|---|---|
| `SEGMENT_GAP` | 30 min | split a trajectory into continuous segments |
| `SUSPICIOUS_GAP` | 2 h | flag for analyst review only |
| `DARK_PERIOD` | **12 h**, only when the gap begins **> 50 nm from shore** in a region with adequate reception | the only one that may be surfaced as a signal |

Below 12 h, gaps are unreliable because a single sun-synchronous AIS satellite takes about
that long to re-cover a location; nearer than 50 nm, terrestrial/satellite coverage
differences dominate. These are Global Fishing Watch's published criteria.

**Even a qualifying dark period is not evidence of wrongdoing.** It lowers
`ais_reliability`, which *reduces* the vessel's final score. It is never scored as guilt,
and `AIS_GAP_DISCLAIMER` is attached wherever a gap is displayed.

## 5. Trajectories (FR-013)

Per vessel, per case time window: order by timestamp → split on `SEGMENT_GAP` → build a
`LineString` per segment (segments of one point are recorded but produce no geometry).

Statistics stored: `position_count`, `distance_km` (geodesic), `duration_hours`,
`mean/max_sog_knots`, `gap_count`, `max_gap_minutes`, `total_gap_minutes`,
`coverage_ratio`, `quality_score`, `quality_flags`.

`coverage_ratio = observed_positions / expected_positions`, where expected comes from the
Class A reporting rate (2–10 s under way, 3 min at anchor) conservatively floored at one
report per 3 minutes. Values are clamped to `[0, 1]`.

## 6. AIS reliability factor (SCORE-006, resolves ambiguity A-03)

The PRD names the factor but does not define it. Composite of five sub-scores, each in
`[0,1]`, combined with the stated weights:

| Sub-score | Definition | Weight |
|---|---|---|
| `coverage` | `coverage_ratio` as above | 0.30 |
| `continuity` | `1 − min(1, max_gap_minutes / 720)` (720 min = the dark-period threshold) | 0.25 |
| `density` | `min(1, position_count / expected_for_window)` | 0.20 |
| `cleanliness` | `1 − rejected_positions / total_positions` | 0.15 |
| `identity` | `static_completeness`: fraction of {IMO, name, callsign, type, dimensions} present | 0.10 |

A vessel with sparse AIS gets a **lower** score, never a higher one — the system cannot
reward absence of evidence, and saying "it went dark, therefore it did it" is exactly the
inference CON-002 forbids.

## 7. Correlation (FR-014)

1. **Spatial** — valid positions intersecting `origin_geometry` buffered by
   `correlation_buffer_km` (default 5 km), or trajectories within that distance.
2. **Temporal** — timestamps inside `[inferred_start − tol, inferred_end + tol]`,
   default tolerance 2 h.
3. **Measures per candidate** — minimum geodesic distance to the region, the highest
   probability contour entered, dwell time inside, closest-approach time, and whether the
   track enters, leaves, crosses or merely passes.
4. **Explanation** — every candidate carries a sentence saying why it was included.

If fewer than three candidates exist, the list is short and the UI says so. It is never
padded (A-10).

## 8. Coverage honesty (CON-007)

Every AIS-derived view carries `AIS_COVERAGE_DISCLAIMER`. The system records, per case,
the observed reception density in the AOI, so an analyst can see whether "no vessels
found" means *there were none* or *we could not see them*. Absence of a vessel is not
evidence of absence.

## 9. Tests

Unit (`tests/unit/test_ais_*.py`): every sentinel value; every MMSI prefix class; the Go
timestamp format including the no-fraction and 9-digit-fraction cases; each cleaning rule
with a crafted pathological track; the two-segment jump case; gap classification at each
threshold boundary; reliability sub-scores at 0, 1 and mid-range.
Integration: fake WebSocket server → parser → PostGIS, including reconnect and duplicate
suppression. GIS: trajectory geometry validity, segment splitting, geodesic length.
