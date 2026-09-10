# SPILLTRACE — ML Pipeline Specification

**Owner:** Agent 3 · Traces: FR-004…FR-007, DATA-002, DATA-008, DB-013, AC-03…AC-05
**Evidence base:** `docs/DECISIONS.md` AD-09…AD-16.

> **Rule that overrides everything else in this document: we never report a metric we did
> not measure.** If the model is weak, the number is published as measured and the report
> says so. A fabricated benchmark would make the entire evidence chain worthless.

---

## 1. Dataset (DATA-002)

Trujillo-Acatitla et al., CC-BY-4.0, DOI `10.1016/j.marpolbul.2024.116549`.

| Part | Zenodo record | Contents | Compressed |
|---|---|---|---|
| I | `8346860` | 1 200 oil-spill images + masks | 40.7 GB |
| II | `8253899` | **685 no-oil + 685 look-alike** + masks | 45.9 GB |
| III | `13761290` | test: 150 oil / 150 look-alike / 150 no-oil + GT | 9.86 GB |

Format: images `2048×2048×2` GeoTIFF, Sentinel-1 **Sigma0 in dB**, bands VV and VH;
masks single-band, foreground `1` / background `0`; test masks are **not** georeferenced
and are named `<index>_segmentation.tif`; archives are 7-Zip.

**Not stated by the publisher and therefore not assumed:** the pixel dtype, and whether
band 1 is VV or VH. `ml/src/dataset/validate.py` opens one file, reports what it actually
found, and **fails loudly** if it disagrees with the configured expectation.

### Acquisition strategy (P10-001)

96.5 GB total is not a reasonable default download. `ml/scripts/download_dataset.py`:

* resumable ranged GETs (Zenodo returns `206 PARTIAL_CONTENT` unauthenticated);
* MD5 verification against the values in the Zenodo record metadata;
* `--parts`, `--max-images N`, `--dry-run` so a laptop can take a documented subset;
* default target is **Part III (9.86 GB)**, optionally a slice of Part II.

Any split we create is **not** the paper's split, and every metric we publish states which
split produced it. Our numbers are never presented as comparable to published benchmarks.

### Leakage (P10-006)

Splits are made at **image level before tiling**, never at tile level — tiles from one
2048² image share speckle, sea state and often the same slick, so a tile-level split
leaks. Splits are written to `splits.json` with a hash of the member list and are
regenerated only with an explicit flag.

### Synthetic fallback (P10-007)

`ml/src/dataset/synthetic.py` generates deterministic 2-channel SAR-like tiles with
elongated dark slicks, speckle and a mask. Every ML test runs offline against it, so
CI never depends on a 96 GB download.

## 2. Preprocessing (FR-004, P9-001…P9-008)

```
GRD (COG) ──► read VV/VH windows ──► σ0 → dB ──► percentile clip ──► standardise
          ──► invalid/no-data mask ──► tile 128×128 stride 96 ──► ndarray[N,2,H,W]
```

* **dB conversion** `10·log10(σ0)`, guarding σ0 ≤ 0.
* **Clipping**: per-scene 1st/99th percentile of the dB histogram. There is no canonical
  fixed dB range in the literature — papers clip by percentile — so the bounds are
  **computed per scene and written into the run manifest**, which keeps the transform
  reproducible and invertible for reporting.
* **Standardisation**: `(x − mean) / std` using the same per-scene statistics.
* **No-data** pixels are masked and excluded from statistics and from loss.
* **Tiling** keeps each tile's affine transform so a prediction can be georeferenced back
  without re-deriving it.
* Single-polarisation scenes are handled by duplicating the available channel and
  recording `notes: ["VH unavailable; VV duplicated"]` — never silently.

## 3. Augmentation (P10-005)

Train split only: horizontal flip, vertical flip, rot90, and optional Gamma-distributed
speckle injection. **No brightness/contrast jitter** — backscatter magnitude is the
physical signal being measured, not a nuisance variable, and jittering it teaches the
model to ignore the very thing that distinguishes oil from sea. Seeded and reproducible.

## 4. Model (P11-001)

U-Net, deliberately configurable so a later GPU run is a config change only.

| Setting | CPU default | Rationale |
|---|---|---|
| input | `2 × 128 × 128` | 256² is ≈4× the compute |
| depth / base filters | 4 / 16 → ≈1.9 M params | base 64 would be ≈31 M |
| normalisation | **GroupNorm(8)** | small CPU batches make BatchNorm statistics unreliable |
| activation | SiLU | |
| head | 1 logit channel (binary oil / not-oil) | |
| encoder | factory: `simple` \| `resnet34` \| `segformer` | swap by string |

Everything numeric comes from `ml/configs/*.yaml` via a `TrainConfig` dataclass. `device`
is resolved once; there is no bare `.cuda()` or `.cpu()` anywhere. AMP sits behind a flag
that is a no-op on CPU.

## 5. Loss (P11-003)

```
L = 0.5 · BCEWithLogits(pos_weight = clamp(neg/pos, max=10)) + 0.5 · SoftDice
```
with a **3-epoch BCE-only warm-up**. Compound Dice+BCE losses are the most consistent
performers under heavy class imbalance; standalone Tversky is unstable and is used only if
recall on thin slicks turns out to be the measured failure mode (then Focal-Tversky
α=0.7, β=0.3, γ=0.75). A six-hyperparameter combo loss is not affordable on a CPU budget —
there is no room for the sweep.

## 6. Training (P11-004…P11-007)

AdamW, LR 3e-4, cosine decay, batch 8, 30–40 epochs, early stop patience 8 on
**validation oil-class Dice**, fp32, `torch.set_num_threads(8)`, DataLoader
`num_workers=2` (more workers compete with compute threads). Deterministic seeding;
`config.yaml` is saved beside every checkpoint so a CPU run and a GPU run are comparable
artifacts.

Empty-mask tiles are subsampled to ~30–40 % of the training set — keeping every all-sea
tile spends most of the compute budget on the easiest possible examples.

**Wall clock is unmeasured.** One epoch is benchmarked before a full run is committed, and
the measured figure is what gets reported.

## 7. Metrics (P11-006, P11-011)

Reported per threshold sweep and at the selected operating point:

* **Dice** and **IoU for the oil class**
* **Precision** and **Recall** at a stated threshold
* pixel accuracy, reported but never headlined

**We report the oil class, not a mean over classes.** A mean that includes `sea` and
`land` is dominated by trivially-easy pixels: on the standard 5-class benchmark, plain
U-Net scores 64.97 mIoU but only **53.79 oil-class IoU**, and 2026 SOTA reaches 72.62 /
65.92. Published papers on our specific dataset report up to 96 % IoU on their own tiles
and their own split; an independent group reports 86.5 % Dice / 92.1 % IoU on the same
data. Those are ceilings from GPU runs, not targets for ours.

Honest expectation for the configuration above: **oil-class Dice ≈ 0.60–0.75, IoU ≈
0.45–0.60** on an in-domain split. Whatever we actually measure is what we publish.

**Geographic domain shift is stated in the evidence report:** these benchmarks are
overwhelmingly European waters, and models trained on them are documented to degrade
elsewhere — including the Indian waters this system targets.

## 8. Model registry (P11-008, DB-013)

Every trained checkpoint writes a `model_versions` row: name, version, framework, task,
**measured** metrics, params, `training_manifest` (config, git sha, dataset manifest hash,
seed, split hash, environment), `artifact_uri` + `checksum_sha256`, `input_channels`,
`input_size`, `normalization`. Exactly one version per name may be `is_active`, enforced
by a partial unique index. Every detection records the `model_version_id` that produced it.

## 9. Inference (FR-005, FR-006, P12-001…P12-008)

```
tiles → model → per-tile probability → overlap-blended stitch → probability GeoTIFF
      → threshold (+ hysteresis) → morphological open/close, min-area filter
      → polygonize → geodesic area/perimeter → MultiPolygon(4326) → spill_detections
```

Overlapping tiles are blended with a cosine window so tile seams do not appear as
detection edges. Morphology is configurable and its parameters are recorded — an
undocumented `opening` can delete a real thin slick.

`detection_confidence` is defined as the **area-weighted mean predicted probability over
the retained polygons**, and is documented as a model-internal quantity. It is never
multiplied by verification or origin confidence (AD-28).

### The no-model path
When no trained checkpoint is registered, `SPILLTRACE_SEGMENTATION_MODEL=analytical`
selects a deterministic detector (adaptive-threshold dark-region finder). Its output is
labelled `data_provenance=SYNTHETIC`, `model=analytical-detector`, and the UI and report
say a trained model was not used. The pipeline keeps working; nobody is misled.

## 10. Look-alike verification (FR-007)

Detailed rules in `docs/DECISIONS.md` AD-14…AD-16. Summary:

* three-class outcome `VERIFIED` / `UNCERTAIN` / `FALSE_POSITIVE`;
* wind gate: reject `< 2 m/s` (glassy sea — no Bragg waves to damp) and `> 12 m/s`
  (slicks dispersed); accept 4–10 m/s; down-weight 2–4 and 10–12 m/s;
* geometric, backscatter-statistical, border-gradient and texture features from the
  25-feature operational set;
* every rule emits `observed`, `threshold`, `passed`, `weight` and a sentence.

Evaluated on the public look-alike test set; the measured confusion matrix is published
(P13-010). Biogenic slicks are the acknowledged hard case and no feature set resolves them
reliably — the report says so rather than pretending otherwise.

## 11. Tests (P22-003)

Shapes and dtypes through the whole tile path; VV/VH channel ordering; loss values against
hand-computed cases; metrics against hand-computed confusion matrices; determinism under a
fixed seed; checkpoint save/load round-trip; stitching seam continuity; polygonization
against known shapes; graceful failure on a missing checkpoint, a corrupt raster and an
all-zero mask.
