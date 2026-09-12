# SPILLTRACE — Architecture Decision Record

**Owner:** Agent 0 · Every entry states the decision, why, what was rejected, and the
evidence it rests on.  Research was performed on **2026-09-10**; claims are labelled
**CONFIRMED** (verified against an official source or a live API call) or **UNCERTAIN**.

---

## Part 1 — Host and platform decisions

### AD-01 — Compose spec, runtime auto-detected (Docker *or* Podman)
The PRD asks for Docker.  The development host has **Podman 5.8.4 (rootless) and no
Docker**.  Rather than fork the setup, the repository ships one Compose-spec
`docker-compose.yml` and a `Makefile` that resolves the runtime in this order:
`docker compose` → `docker-compose` → `podman-compose` → `podman compose`.
Verified: `podman-compose 1.6.0` parses the file including YAML anchors and
`${VAR:?error}` interpolation.
*Rejected:* maintaining separate Podman files (drift), or requiring Docker (blocks this host).

### AD-02 — Python 3.12 inside containers, not the host's 3.14
The host runs **Python 3.14.7**, which is ahead of wheel availability for parts of the
scientific stack (notably PyTorch).  All Python execution happens in containers pinned
to `python:3.12-slim`, which is also the right answer for reproducibility.
`rasterio` and `pyproj` ship manylinux wheels with GDAL/PROJ bundled, so **no system
GDAL install is required** — this removes the single most painful geospatial build step.

### AD-03 — Own `JobQueue` on Redis rather than Celery/RQ/Arq
Requirements are modest and specific: at-least-once delivery, durable state, progress
reporting, retry, and recovery from a crashed worker.  A thin abstraction over Redis
lists (`BLMOVE` into a per-worker processing list, heartbeat, stale-claim reaper) gives
exactly that in ~200 lines, keeps handlers as plain async functions that unit-test
without a broker, and avoids Celery's serializer/broker surface.
**The database is the source of truth for job state; Redis is only transport** — a
worker crash therefore never loses job history.
*Rejected:* Celery (weight, sync-first), RQ (no async), Arq (closest alternative; own
implementation chosen for the explicit DB-as-truth model and testability).

### AD-04 — One Python package, three entrypoints
`backend/src/spilltrace` is installed once and run as `spilltrace.api`,
`spilltrace.worker` or `spilltrace.worker.ais_ingestor`.  The PRD's flat
`backend/ worker/ ml/` split invites code drift and triple dependency maintenance.
Layering is enforced by a test: `core` may not import `adapters`, `db`, `api` or `worker`.

### AD-05 — Ports and adapters for every external dependency
Each external system sits behind a `Protocol` in `core/ports.py` with a real and a
deterministic implementation, selected by environment variable.  This is what makes the
PRD's "dummy-first" strategy safe rather than dishonest: every artifact carries
`data_provenance ∈ {REAL, SYNTHETIC, MIXED}`, which propagates to the UI and the report.
Synthetic vessel names are suffixed `(SYNTHETIC)` (CON-009).

---

## Part 2 — Sentinel-1 / Copernicus Data Space (DATA-001)

### AD-06 — Keycloak password grant with a service account
**CONFIRMED.** Token endpoint
`https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token`,
realm `CDSE`, public `client_id=cdse-public`, grant `password` (`totp` field for 2FA).
Access token lives **10 minutes**; refresh window **60 minutes**; max 100 sessions.
Implementation refreshes at ~8 minutes.
**UNCERTAIN:** whether `client_credentials` tokens are accepted by
`download.dataspace.copernicus.eu` — documented only for openEO/Sentinel Hub, which CDSE
itself calls experimental.  Not used.

### AD-07 — OData for catalogue search, not STAC
Both work, but STAC has a trap: **`product:type` is platform-dependent** — Sentinel-1C
scenes carry `IW_GRDH_1S_C` while Sentinel-1A carries `IW_GRDH_1S`, so filtering on
`product:type` alone **silently drops every S1C scene** (CONFIRMED by live probe: the
same AOI/window returned 3 S1C + 3 S1A). OData uses `IW_GRDH_1S` for both.
OData also exposes the full attribute set via `$expand=Attributes`.
Query shape used:
```
$filter=Collection/Name eq 'SENTINEL-1'
  and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType'
        and att/OData.CSC.StringAttribute/Value eq 'IW_GRDH_1S')
  and OData.CSC.Intersects(area=geography'SRID=4326;POLYGON((...))')
  and ContentDate/Start gt <iso> and ContentDate/Start lt <iso>
```
Gotchas encoded in the adapter: the polygon **must close**; `relativeOrbitNumber` is an
**Integer** attribute (`OData.CSC.IntegerAttribute`); `polarisationChannels` is the
**ampersand-joined string `"VV&VH"`**, not a list; `orbitDirection` is uppercase in OData
and lowercase in STAC.

### AD-08 — Download per-band COG nodes, not the whole SAFE
**CONFIRMED by live probe.** CDSE stores each GRD twice: `IW_GRDH_1S` (original SAFE,
median **1.72 GB**) and `IW_GRDH_1S-COG` (median **1.16 GB**).  The zipper node endpoint
serves a single measurement file:
```
https://zipper.dataspace.copernicus.eu/odata/v1/Products(<uuid>)
  /Nodes(<name>.SAFE)/Nodes(measurement)/Nodes(<file>-cog.tiff)/$value
```
Measured on one scene: **VV 568 MB, VH 431 MB** — about 1.0 GB for both bands versus
1.7 GB for the archive, *and* they are Cloud-Optimised GeoTIFFs, so rasterio can
window-read without downloading the whole file.  This is the single biggest practical
win available for a laptop-scale deployment.
Also encoded: `HEAD` returns **405** (probe with a ranged `GET`); redirects must be
followed with the auth header retained (`--location-trusted` equivalent).
Free-tier quotas: 12 TB / 30 days, **4 concurrent connections**, 2 000 req/min.
The downloader therefore caps concurrency at 4.

---

## Part 3 — Training dataset (DATA-002)

### AD-09 — The dataset is ~96.5 GB; acquisition is subsetted and explicit
**CONFIRMED via the Zenodo REST API.** The PRD's dataset is Trujillo-Acatitla et al.
(CC-BY-4.0, DOI `10.1016/j.marpolbul.2024.116549`):

| Part | Record | Contents | Size |
|---|---|---|---|
| I | `8346860` | 1 200 oil-spill images + masks | 40.7 GB |
| **II** | **`8253899`** | **685 no-oil + 685 look-alike + masks** | **45.9 GB** |
| III | `13761290` | test set: 150 oil / 150 look-alike / 150 no-oil + GT | 9.86 GB |

Images are **2048×2048×2 GeoTIFF**, Sentinel-1 **Sigma0 in dB**, two bands VV/VH; masks
are single-band with foreground `1`, background `0`; test masks are **not** georeferenced
and are named `<index>_segmentation.tif`.  Archives are **7-Zip**.
**UNCERTAIN:** exact dtype and whether band 1 is VV or VH — not stated on the record
pages.  The loader therefore **probes one file and fails loudly on mismatch** rather than
assuming (task P10-002).

Consequences accepted:
1. The downloader supports **ranged, resumable** requests (verified: an unauthenticated
   ranged GET returned `206 PARTIAL_CONTENT`) and a `--max-images` subset mode.
2. Default acquisition target is **Part III (9.86 GB)** plus an optional slice of Part II,
   because a full 96 GB pull is not reasonable on the target hardware.
3. A **synthetic SAR dataset generator** ships so every ML test runs offline (P10-007).
4. Any split we create ourselves is documented as **not** the paper's split, so our
   numbers are never presented as comparable to published benchmarks.

### AD-10 — Published metrics we must not confuse ourselves with
The dataset paper reports U-Net + Focal Loss at 99 % accuracy / **96 % IoU** on its own
tiles, and 95 % / 90 % IoU end-to-end.  An independent paper on the same data reports
86.5 % Dice / 92.1 % IoU.  On the *other* common benchmark (Krestenitis M4D, 5-class),
honest numbers are **mIoU 60–72 %** with **oil-class IoU 50–66 %** — plain U-Net 64.97
mIoU / 53.79 oil IoU, 2026 SOTA (OilSAM2) 72.62 / 65.92.
**Rule adopted:** we report **per-class Dice/IoU for the oil class**, plus precision and
recall at a stated threshold — never a mean over classes that includes `sea`, which
inflates the headline.  We never publish a number we did not measure.

---

## Part 4 — SAR segmentation model (DATA-008)

### AD-11 — U-Net stays, but as a *configurable* baseline
Current SOTA is SAM2/Mamba/transformer-based (OilSAM2, OSDMamba, SegFormer) and all of it
requires a GPU (published runs use L40/V100).  This host is **CPU-only, 8 threads,
15 GB RAM, no CUDA**.  Plain U-Net is ~8 mIoU behind SOTA — real but not decisive — and is
what the PRD specifies.
The code is structured so a GPU run is a **config change only**: one `TrainConfig`
dataclass from YAML, `device` resolved once, AMP behind a flag (no-op on CPU), encoder
behind a factory (`simple` | `resnet34` | `segformer`), patch size and stride in config.

**CPU training configuration adopted** (P11-002):
| Setting | Value | Reason |
|---|---|---|
| Patch | 128×128, stride 96 | 256² is ~4× the compute |
| Channels | 2 (VV, VH), dB, percentile-clipped then standardised | dataset is dual-pol |
| Depth 4, base filters 16 | ≈1.9 M params | base 64 would be ≈31 M |
| Norm | **GroupNorm(8)**, not BatchNorm | small CPU batches make BN statistics unreliable |
| Loss | `0.5·BCEWithLogits(pos_weight) + 0.5·SoftDice`, 3-epoch BCE warm-up | compound losses are the most consistent performer under class imbalance |
| Optimiser | AdamW 3e-4, cosine | epoch-limited, Adam converges faster than SGD |
| Epochs | 30–40, early stop patience 8 on val **oil-class** Dice | not 100 — the budget does not exist |
| Precision | fp32 | no AMX on this CPU; bf16 would not help |
| Threads | `torch.set_num_threads(8)`, DataLoader `num_workers=2` | workers must not compete with compute threads |

**UNCERTAIN:** wall-clock. An extrapolated estimate is 4–10 h for 30 epochs; we will
**benchmark one epoch before committing** and report the measured figure.

### AD-12 — SAR normalisation is per-scene percentile clipping, recorded
**UNCERTAIN** whether a canonical fixed dB clip range exists — the literature clips by
percentile, not by a fixed pair.  We therefore clip at the per-scene 1st/99th dB
percentile, standardise, and **store the clip bounds in the run manifest** so the
transform is reproducible and invertible for reporting.
Augmentation is flips + rot90 + optional Gamma speckle only. **No photometric jitter** —
backscatter magnitude is the physical signal, not a nuisance variable.

### AD-13 — Honest generalisation caveat
Public benchmarks are overwhelmingly European waters, and the literature reports that
models trained on them degrade under geographic domain shift.  A model applied to the
Arabian Sea or Bay of Bengal will perform worse than its validation numbers suggest, and
the evidence report says so.

---

## Part 5 — Look-alike verification (FR-007)

### AD-14 — Three-class output, following operational practice
`VERIFIED` / `UNCERTAIN` / `FALSE_POSITIVE` mirrors the Solberg et al. (1999)
oil / uncertain / look-alike design, which on a 7 051-formation signature database
reported 94 % oil and 99 % look-alike (leave-one-out).  A binary verdict would over-claim;
`UNCERTAIN` is what keeps the result usable as evidence.  EMSA's CleanSeaNet likewise
publishes a *confidence level*, not a binary call.

### AD-15 — The wind gate, with real numbers
**CONFIRMED** from the SAR oil-spill meta-analysis (GIScience & Remote Sensing 2021,
Table 6, n = 340 reviewed studies) and Najoui et al. 2018 (1 333 scenes, 3 903 slicks:
**95 % of slicks detected between 2.09 and 8.33 m/s**):

| Wind at acquisition | Rule | Why |
|---|---|---|
| `< 2 m/s` | **REJECT** | "glassy sea"; no Bragg waves, so a dark patch is not attributable to oil |
| `2–4 m/s` | strong down-weight | detectable, but the look-alike population peaks here |
| `4–10 m/s` | **ACCEPT** (4–7 optimal) | the operational window |
| `10–12 m/s` | down-weight | only thick slicks survive — low recall, but a detection here is *more* likely genuine |
| `> 12 m/s` | **REJECT** | slicks broken up and dispersed |

### AD-16 — Transparent feature set (Topouzelis 2008, Sensors, Table 3)
25 features in five documented groups: geometric (area, perimeter, P/A, complexity, two
shape factors), backscatter/statistical (object & background mean/std/power-to-mean, and
the classic **Opm/Bpm ratio**), **contextual**, border gradient (mean/std/max), and GLCM
texture.  Every rule reports `observed`, `threshold`, `passed` and a sentence, so the
verdict is explainable rather than a black box.
Notably, **"presence of rig/ship, distance to ship" is a recognised contextual feature
class in this literature** — which means SPILLTRACE's AIS correlation is scientifically
grounded, not an invention.
Realistic expectation: ~75–90 % oil-class accuracy from a transparent rule engine, with
look-alike rejection the harder half (Nirchio: 90 % a priori → **74 % held-out**).
Biogenic slicks remain the hardest case and no feature set solves them reliably.
**UNCERTAIN:** CleanSeaNet's internal thresholds are not published; we cite none.

---

## Part 6 — Environment and drift (DATA-003/004/009)

### AD-17 — Copernicus Marine toolbox v2, `open_dataset` over `subset`
**CONFIRMED:** package `copernicusmarine` **2.4.1** (2026-05-11, requires ≥3.10, EUPL);
pin `>=2.0,<3` because v1→v2 was a breaking rewrite; `numpy>=2.1` is a hard floor.
Credentials from `COPERNICUSMARINE_SERVICE_USERNAME`/`_PASSWORD` (read automatically) or
`~/.copernicusmarine/.copernicusmarine-credentials`.
Datasets adopted:
* **Currents:** `cmems_mod_glo_phy_anfc_merged-uv_PT1H-i` — hourly merged surface currents
  (circulation + tides + waves) at z = −0.494 m, variables `uo, vo, utide, vtide, utotal,
  vtotal, vsdx, vsdy`. Reanalysis fallback `cmems_mod_glo_phy_my_0.083deg_P1D-m`
  (1993-01-01 → 2026-06-23).
* **Wind:** `cmems_obs-wind_glo_phy_nrt_l4_0.125deg_PT1H` (NRT) /
  `cmems_obs-wind_glo_phy_my_l4_0.125deg_PT1H` (reanalysis).

**Known gap, recorded honestly:** the NRT wind product **starts June 2024** and the
reanalysis product lags real time by months — neither covers both a very recent event and
a pre-2007 one.  ERA5 via the CDS API is therefore implemented as the historical wind
fallback (endpoint is now `https://cds.climate.copernicus.eu/api`, `.cdsapirc` takes a
single personal access token, package `cdsapi>=0.7.7`).
**Attribution is mandatory** under the CMEMS licence and is emitted into every report:
*"Generated using E.U. Copernicus Marine Service Information; <DOIs>"*.

### AD-18 — OpenDrift is optional; an analytical engine is the always-available default
**CONFIRMED:** `opendrift` **1.14.12** (2026-08-31).  Two facts drive this decision:
1. It is heavy — `roaring_landmask` alone is a ~100 MB wheel, plus cartopy/netCDF4/pyproj,
   and `copernicusmarine` is a hard dependency dragging boto3/zarr/dask/pystac.
2. conda-forge's `environment.yml` pins things pyproject does not (`gdal>=3.1`,
   `proj<9.8`, and `adios_db>=1.2,<1.2.7` which **conflicts** with pyproject's
   `adios_db>1.2`).  pip-only is plausible on linux/x86_64 (every hard dep has a
   manylinux wheel) but is **UNCERTAIN until built**.

So `DriftEngine` has two implementations: `OpenOilEngine` (installed behind an
`INSTALL_DRIFT=true` build arg) and `AnalyticalDriftEngine` (advection + diffusion,
deterministic, always present).  When the fallback runs, the drift row records
`engine='analytical'` and the UI and report say so.  The reasoning chain never breaks and
never lies about what produced it.

**Good news, CONFIRMED by reading source** (`openoil/adios/dirjs.py`): oil types are
loaded from a **locally packaged `oils.xz`** — **no network access is needed at runtime**
to select an oil.  The legacy `oil_library` package is dead (replaced in v1.8.0) and must
not appear in requirements.

### AD-19 — OpenDrift API surface actually used (this changed recently)
**CONFIRMED from source:**
* **`o.history` no longer exists** — v1.13.0 replaced the recarray with an xarray
  `o.result`, which `run()` also returns.  **`o.get_lonlats()` is gone** (zero hits in
  master).  Read `o.result.lon` / `o.result.lat`, dims `(trajectory, time)`.
* **Backward run:** seed at the *observed* time, then
  `o.run(duration=timedelta(hours=H), time_step=-900, time_step_output=3600)` — duration
  stays **positive**; the model negates it internally and raises on a sign mismatch.
  `o.simulation_direction()` returns `-1`.
* Forcing scalars go through config, not `reader_constant`:
  `o.set_config('environment:fallback:x_wind', …)`.
* `reader_copernicusmarine://<dataset_id>` exists (v1.11.3+) and reads CMEMS credentials
  from the same env vars.
* Density: `o.get_histogram(pixelsize_m=…)`.

### AD-20 — Ensembles: perturbation + wind-drift-factor distribution
Three mechanisms exist; we use two, matching official examples:
`drift:current_uncertainty` / `drift:wind_uncertainty` /
`environment:constant:horizontal_diffusivity`, plus a per-element
`wind_drift_factor ~ N(0.03, 0.01)` (docs: typically 0.033 with Stokes drift, 0.02 in
addition to it; ~0.035 for oil and iSphere drifters, with large uncertainty).
≥10 000 particles for backtracking.  The **seed is stored** so AC-07 (reproducible origin
region) is testable by hash equality.

---

## Part 7 — AIS (DATA-005/006/007)

### AD-21 — AISStream wire format, encoded exactly
**CONFIRMED.** `wss://stream.aisstream.io/v0/stream`.  Subscription must be the **first
frame within 3 seconds**; a resubscription **replaces** the previous one and is limited to
1/second.  `BoundingBoxes` is `[[[lat, lon], [lat, lon]], …]` — **latitude first**, which
is the number-one cause of "connected but silent".  An invalid subscription produces **no
error message**, so the adapter treats a missing `SubscriptionConfirmation` as a hard
failure.
Envelope: `{MessageType, MetaData, Message}` where `Message` has a single key equal to
`MessageType`.  **`MetaData` mixes casing** — `MMSI` and `ShipName` capitalised but
`latitude`, `longitude`, `time_utc` lowercase; `ShipName` is space-padded to 20 chars.
`time_utc` is Go's default format `YYYY-MM-DD HH:MM:SS.fffffffff +0000 UTC` with a
**variable-length** fraction (Go trims trailing zeros) — `datetime.fromisoformat` will
**not** parse it.  Position is read from `Message.PositionReport.Latitude/Longitude`,
which is unambiguously capitalised.
Operational limits: 3 connections/account, 3/IP; free of charge; **from September 2026
uncompressed connections are bandwidth-limited**, so the client negotiates
`permessage-deflate` and asserts `CompressionEnabled`.  API key is **server-side only** —
direct browser connections are not permitted (CON-004).
**UNCERTAIN:** whether an established idle connection is closed.  A stall watchdog
(no frame for 90 s → reconnect) is implemented, with library-level ping/pong, because
application sends count against the 1/s subscription-replacement limit.

### AD-22 — Units are already decoded; sentinels are filtered defensively
AISStream delivers physical units (`Sog` knots, `Cog` degrees, `TrueHeading` integer
degrees, `MaximumStaticDraught` metres) — **not** raw AIS integers.
**UNCERTAIN** whether it normalises ITU-R M.1371 sentinels, so the adapter drops/NULLs:
`Sog ≥ 102.2`, `Cog ≥ 360`, `TrueHeading == 511`, `|Lat| > 90`, `|Lon| > 180`,
`RateOfTurn == -128`, `Timestamp ≥ 60`.
**UNCERTAIN:** `RateOfTurn` units — schema says integer, so it is plausibly the raw
`ROT_AIS = 4.733·√(ROT_sensor)` encoding.  Decoded as `sign(x)·(x/4.733)²` and flagged for
empirical validation; ROT is not used in scoring.
`MetaData.time_utc` is **server receipt time**, not vessel transmit time — recorded as
such, and never treated as exact for sub-minute geometry.

### AD-23 — Two speed thresholds, not one
Reported `SOG > 30 kn` → invalid (the most common published cutoff; 25 kn is used for
merchant traffic specifically).  **Implied** speed from Haversine/Δt `> 40 kn` → impossible
jump.  These are different failure modes and must not share a number.
Kinematic check (Sinni & Kyriazanos): flag when displacement exceeds
`v_{i−1}·Δt + ½·a_max·Δt²` with `a_max = 0.15 kn/s`, and **check the next segment before
correcting** — one bad fix violates two segments, a genuine manoeuvre violates one.

### AD-24 — Three separately-named gap thresholds
There is **no single standard**; published values span 10 min to 12 h.  Conflating them is
how a system ends up implying wrongdoing from a satellite revisit gap.  So:
| Constant | Value | Meaning |
|---|---|---|
| `SEGMENT_GAP` | 30 min | split a trajectory into continuous segments |
| `SUSPICIOUS_GAP` | 2 h | flag for analyst review only |
| `DARK_PERIOD` | **12 h**, and only when the gap starts **> 50 nm from shore** in a
  region with adequate reception | the *only* one that may ever be surfaced as a signal |
The 12 h + 50 nm + reception-density conditions are Global Fishing Watch's published
criteria; below 12 h, gaps are unreliable because of satellite revisit periodicity.
Even then (CON-002) a dark period is **not** evidence of wrongdoing and is never scored as
such — it lowers `ais_reliability`, which *reduces* a vessel's score.

### AD-25 — MMSI validation and the identity caveat
Nine digits; ship MID **201–775**; reserved prefixes excluded from vessel attribution
(`0MID…` group, `00MID…` coast station, `111MID…` SAR aircraft, `99MID…` AtoN,
`98MID…` auxiliary, `970/972/974…` SART/MOB/EPIRB, `8MID…` diver radio).
**MMSI is a radio identifier that gets reassigned; IMO from `ShipStaticData` is the
durable key.**  Both are stored, and vessel identity in the report states which was used.
AIS is also trivially spoofable (documented 2025 typologies include one MMSI broadcasting
from two locations at once).  An AIS position matching a slick is *consistent with*, not
proof of, that vessel's presence — wording carried in `core/disclaimers.py`.

### AD-26 — Never block the AIS read loop
AISStream drops messages for slow consumers.  The ingestor's socket read loop only parses
and enqueues; all database work happens in a separate task with batched writes.

---

## Part 8 — Product-safety decisions

### AD-27 — Disclaimers are code, not copy
All mandated language lives in `core/disclaimers.py` and is asserted by
`tests/unit/test_disclaimers.py`, including a `FORBIDDEN_PHRASES` list
("responsible vessel", "guilty", "proven", "legal probability", …) that generated text is
checked against.  This is how CON-001/002/003/007/008 and AC-13 stop being good intentions.

### AD-28 — Three confidences, never multiplied
`detection_confidence` (model), `verification_confidence` (look-alike rules) and
`origin_confidence` (drift) are separate, separately documented, and never combined into a
single number, because combining them would manufacture precision that none of them has
(ambiguity A-06).

### AD-29 — Never pad the candidate list
The PRD asks the MVP to show "at least 3 candidate vessels".  If fewer than three genuine
candidates exist, the UI says so.  The demo scenario is authored to contain more than
three; reality is reported as it is (ambiguity A-10).


---

## Part 9 — Decisions taken during integration

These three came from running the system, not from designing it. Each was a real defect
found by executing the pipeline or loading the API.

### AD-30 — Environmental data is fetched **before** look-alike verification
The PRD's numbered step list puts "verify look-alike" (step 7) before "get wind/current"
(step 8), and `PIPELINE_ORDER` originally followed it literally. Running the real path
exposed the consequence: `detect.verify` found no environmental run, so the wind rule
reported *not evaluated* on every case, and the single most useful physical
discriminator (AD-15) was structurally unreachable. Verification still returned
`VERIFIED`, at 0.667 confidence from 70% evidence coverage — a plausible answer produced
without its most important input.

`env.fetch` now precedes `detect.verify`. The same case then verifies at **0.788 with
100% coverage and `wind_window` applicable, observed 5.40 m/s**.

The PRD's ordering describes the *conceptual* chain, not an execution dependency graph.
Where the two disagree, the dependency wins, and the divergence is recorded here.

### AD-31 — A ranking that cannot discriminate must not label everything HIGH
The real path produced a 782 km² detection, which back-tracked to a 2 653 km² origin
region containing 13 of 20 vessels. All 13 scored 0.960 on origin proximity and all 13
were labelled **HIGH**.

Arithmetically correct; editorially false. "Thirteen vessels are strong candidates" is
the system reporting that it could not tell them apart, in language that says the
opposite — and naming thirteen vessels is thirteen times the harm of naming one. This is
exactly what CON-001 exists to prevent, and the weighted-sum model cannot notice it,
because each candidate is scored in isolation.

`core/scoring/discrimination.py` therefore checks the *field* before labels are
attached. Two independent failure modes cap the labels at MODERATE:

* **more than 3 candidates within 0.02 of the top origin-proximity score** — the region
  is consistent with all of them, which is not the same as supporting any one of them;
* **`origin_confidence` below 0.60** — the back-track never converged, so the region
  every candidate is measured against is itself weak evidence.

**Scores are never altered.** The full breakdown still shows 0.9424; only the
at-a-glance label is prevented from over-claiming, and a `discrimination_note` explaining
why travels with every affected candidate through the API and into the report. On the
same real case, 8 tied candidates now cap to MODERATE.

*Rejected:* multiplying `origin_confidence` into the score. That would manufacture a
single number blending two different kinds of uncertainty, which is what AD-28 forbids.
Capping a label is an editorial judgement about presentation; changing a score is a claim
about evidence.

### AD-32 — One Redis subscription for all SSE clients
The first SSE implementation opened a Redis pub/sub connection per browser tab. Load
found it before review did: opening streams in a loop drove the API container unhealthy.
Connections, event-loop tasks and file descriptors all scaled with *viewers* rather than
with work, so a few analysts with several tabs each could take the service down while it
was doing nothing.

`api/events_broker.py` now keeps a single process-wide subscriber and fans messages out
to in-process asyncio queues. Measured with 30 concurrent streams: Redis connections went
**3 → 4**, not 3 → 33, and the API stayed healthy and answered ordinary queries
throughout.

Two further protections, both load-bearing:

* **Bounded per-client queues that drop the oldest event.** Job status is a
  *current-state* signal; a suspended tab wants the latest event, not a backlog of stale
  ones, and must never make the broker buffer without limit.
* **A cap of 64 concurrent streams per process**, returning 503 with a retry hint. A
  misbehaving client degrades itself rather than everyone.

### AD-33 — The production detector is an smp ResNet-34 U-Net loaded by a plain-torch twin

*2026-09-12.* The first checkpoint trained on real Sentinel-1 data (`ml/runs/colab-resnet34-run3`,
Trujillo-Acatitla Parts I/II subset, Google Colab T4) was produced by an external script with
`segmentation_models_pytorch.Unet(encoder_name="resnet34", in_channels=2, classes=1)` and saved as
`{"model": state_dict, "args": …, "epoch": 42, "val": {…}}` — not the format `ml/src/train.py` writes.

* **Architecture:** `spilltrace/ml/resnet_unet.py` reproduces smp's module tree in plain PyTorch with
  identical parameter names and forward semantics, so the checkpoint loads with `strict=True` and no
  new runtime dependency (smp would pull in `timm` and `huggingface_hub`). Verified against
  `segmentation_models_pytorch==0.5.0` on the real weights: **max |Δlogit| = 0.0** on 256², 128² and
  512×384 inputs; 24,433,233 parameters on both sides. `UNetModel` detects the format from the payload
  keys and still loads the repository's own plain U-Net.
* **Metrics are validation-split, and say so.** The checkpoint's `val` block (Dice 0.841, IoU 0.725,
  precision 0.769, recall 0.928 at epoch 42) is the training script's hold-out, not an independent test
  set; it is registered under a `validation` group with an explicit `split` note and the ML Ops page
  renders it as such. No test metrics are invented.
* **Normalisation is a known gap.** The training script's input normalisation was not recorded, so
  inference uses AD-12's per-scene percentile clip + standardisation and the model notes state that a
  distribution mismatch is possible. The choice is recorded in every detection's run manifest.
* **Tiling follows the model:** a trained model is tiled at its registry `input_size` (256) with a
  3/4 stride (192); the analytical detector keeps 128/96.
* **`INSTALL_ML` lives in `.env`** and is passed as a compose build arg, so `make up` (which builds)
  cannot silently rebuild a torch-less image after `make build-ml`.
* **Provenance:** a detection by a REAL model over a SYNTHETIC scene is `MIXED`, and the case rolls
  up to the same label (see AD-34).

### AD-34 — A case's provenance describes its evidence, not its author's intent

*2026-09-12.* `cases.data_provenance` used to be whatever the case was created with, so the fixture
walk-through case read **REAL** while every scene, detection and vessel in it was SYNTHETIC — a
CON-009 violation. `spilltrace/db/provenance.py` now rolls the label up from the contributing rows
(scenes via `case_scenes`, detections, drift runs, environmental runs, trajectories, attributions)
with `combine_provenance` whenever a pipeline settles (`worker/pipeline.advance`); a case with no
evidence keeps its declared label. `python -m spilltrace.db.provenance` backfilled existing rows
(ST-2026-0001: REAL → MIXED).

### AD-5 amendment — Public imagery basemaps, with an offline switch

*2026-09-12.* AD-5's "zero external requests" basemap gave analysts no geographic context at all.
Every map now composes Esri World Imagery (default), Esri Ocean, CARTO Dark/Light and the original
offline graticule into **one** MapLibre style (`frontend/src/lib/map/basemaps.ts`), switched by layer
visibility so evidence layers are never torn down. What changed and what did not:

* Tile services are public and unauthenticated; **no credential is attached** — the bearer token is
  still added only to our own API origin (CON-004). The CSP allows exactly those hosts.
* A tile request discloses the viewport to the provider. The **Offline** basemap restores the
  zero-external-request behaviour, and the map falls back to it automatically (with a notice) when
  imagery cannot be reached. Imagery is context; every evidence layer still comes from the API.
* MapLibre GL was kept over Leaflet: WebGL rendering, globe projection, and 2,200 lines of working
  overlay code. Attribution follows the active basemap.

### AD-35 — AISStream has no usable coverage in Indian waters (CONFIRMED)

*2026-09-12.* The `ais-ingestor` was reconnecting every 90 s and had collected zero real
positions. Measured directly against `wss://stream.aisstream.io/v0/stream` with our own key:

| Subscription | Position reports |
|---|---|
| Indian EEZ box `[[2,60],[26,98]]` + `FilterMessageTypes` (what we send) | **0 in 40 s** |
| Same box, no message filter | **0 in 40 s** |
| Whole world | **1,593 in 30 s** |

Geography of that worldwide sample: Europe 1,147 · North America 247 · elsewhere 199 ·
**Indian waters 0**. The key is valid, the subscription is confirmed, and the bounding box is
in AISStream's required latitude-first order. AISStream is fed by volunteer receivers whose
coverage is overwhelmingly North Atlantic, so **the feed simply cannot supply Indian-water
AIS**. This is the concrete form of CON-007 and must not be papered over.

**Two code defects this exposed, now fixed:**

* `_session` treated 90 s of silence as `ConnectionError` and reconnected. A quiet sea is a
  result, not a broken socket — and the websocket's own ping/pong already detects a dead link.
  The loop now polls in 30 s slices, stays connected, and states the quiet every 5 minutes.
* Nothing reported what the feed had actually delivered, so "subscribed and silent" looked
  identical to "no vessels were there". `AISStreamProvider.describe()` now reports
  `messages_received`, `last_message_at` and `subscribed_at`, and the ingestor logs them every
  10 minutes.

**Consequence for demonstrations:** a case built from live sources gets real Sentinel-1 imagery
and a real model result, but **no candidate vessels**, because there is no AIS to correlate. A
vessel ranking therefore needs either the synthetic AIS provider (labelled SYNTHETIC) or a
different AIS source. Until then a live case rolls up to MIXED at best — see also AD-34 and the
`analytical` drift engine.


### AD-36 — A supplied scene is ingested through the real path, and its units are read, not assumed

*2026-09-12.* The catalogue path answers "which Sentinel-1 pass covered this area?". Demonstrating
the trained model needs a different question answered: an analyst already holds a measurement file
— a research-dataset tile, an archived GRD subset — and wants the ordinary investigation run over
it. `POST /cases/{case_id}/scenes/upload` does exactly that and nothing more: it leaves the
database in the state `scene.download` would have left it in (a `satellite_scenes` row marked
DOWNLOADED, a selected `case_scenes` link, per-band objects and a `bundle.json`), then starts the
pipeline at `sar.preprocess`. **No stage downstream of the upload knows the scene arrived by
upload**, which is the point — the real code path is the one being exercised.

**The units trap.** Catalogue products carry σ0 as *linear power*; the Trujillo-Acatitla dataset
this model was trained on publishes σ0 in **dB**. The two are indistinguishable to a file reader,
and `sigma0_to_db` rejects anything at or below `MIN_VALID_SIGMA0 = 1e-8`. dB values are negative,
so converting a dB raster to dB a second time does not merely distort it — it marks **every pixel
invalid** and the scene returns *empty*. Measured on a 256 × 256 dB raster with a synthetic slick:

| Path | Valid pixels |
|---|---|
| dB raster through the linear conversion (before) | **0 of 65,536** |
| dB raster with `already_db=True` | **65,536 of 65,536** |
| Linear raster, unchanged behaviour | 4,096 of 4,096 |

An empty scene looks like "no oil was found" — a plausible, quiet, *wrong* answer. So units are
carried explicitly in `SceneBundle.extra["units"]`, `sar.preprocess` honours them, and the upload
endpoint decides by inspecting the pixels (any negative value means dB) and **records the reason it
decided** alongside the scene. The analyst can override it; the reason is shown either way.

**Georeferencing.** A tile with a CRS is reprojected to EPSG:4326 so its detections share one
coordinate system with every other layer. A tile without one cannot be positioned from its own
contents; it is stretched onto the case AOI so the chain can run, and the scene notes say so in
plain words — *the shape of any detection is real, but its latitude and longitude are a placement,
not a measurement.*

**Provenance is REAL, with a caveat attached.** A Sentinel-1 measurement does not stop being a real
observation because it arrived by upload, and labelling it SYNTHETIC would be false in the other
direction. What the platform cannot do is *vouch* for it, so every uploaded scene carries: "SPILLTRACE
did not retrieve it from a catalogue and cannot verify its origin, acquisition time or processing
history." The case still rolls up to MIXED whenever its AIS or environmental inputs are synthetic
(AD-34), which is the honest outcome for a demonstration.
