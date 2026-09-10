"""Render an evidence report as self-contained, printable HTML.

Self-contained on purpose: an evidence artifact that needs a CDN to render is not an
evidence artifact.  No external fonts, no scripts, no network of any kind.
"""

from __future__ import annotations

import html
from typing import Any

from spilltrace.core.report.assemble import ReportData

_STYLE = """
:root{--ink:#111827;--muted:#4b5563;--line:#d1d5db;--bg:#ffffff;--panel:#f9fafb;
--accent:#0f766e;--warn:#92400e;--warnbg:#fffbeb;--warnline:#f59e0b}
*{box-sizing:border-box}
body{margin:0;padding:32px;background:var(--bg);color:var(--ink);
font:14px/1.55 "DejaVu Sans",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:960px;margin:0 auto}
h1{font-size:24px;margin:0 0 4px}
h2{font-size:17px;margin:32px 0 10px;padding-bottom:6px;border-bottom:2px solid var(--line)}
h3{font-size:14px;margin:18px 0 6px;color:var(--muted);text-transform:uppercase;
letter-spacing:.06em}
p{margin:0 0 10px}
.sub{color:var(--muted);margin:0 0 20px}
table{width:100%;border-collapse:collapse;margin:8px 0 16px;font-size:13px}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:var(--panel);font-weight:600;white-space:nowrap}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
code,.mono{font-family:"DejaVu Sans Mono",ui-monospace,Menlo,Consolas,monospace;font-size:12px}
.notice{border:1px solid var(--warnline);background:var(--warnbg);color:var(--warn);
padding:12px 14px;border-radius:6px;margin:0 0 18px;font-weight:600}
.disclaimer{border-left:4px solid var(--accent);background:var(--panel);
padding:12px 14px;margin:14px 0;border-radius:0 6px 6px 0}
.kv{display:grid;grid-template-columns:220px 1fr;gap:4px 16px;margin:0 0 14px}
.kv dt{color:var(--muted)}
.kv dd{margin:0}
ul{margin:0 0 12px;padding-left:20px}
li{margin-bottom:6px}
.rank{font-weight:700;font-variant-numeric:tabular-nums}
.bar{display:block;height:6px;border-radius:3px;background:var(--accent);min-width:2px}
.bartrack{background:var(--line);border-radius:3px;width:120px;display:inline-block;
vertical-align:middle}
footer{margin-top:40px;padding-top:14px;border-top:1px solid var(--line);
color:var(--muted);font-size:12px}
@media print{body{padding:0}h2{page-break-after:avoid}table{page-break-inside:avoid}}
"""


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _kv(pairs: list[tuple[str, Any]]) -> str:
    rows = "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in pairs if v not in (None, ""))
    return f"<dl class='kv'>{rows}</dl>" if rows else "<p>Not available.</p>"


def _bar(fraction: float) -> str:
    pct = max(0.0, min(1.0, float(fraction))) * 100
    return f"<span class='bartrack'><span class='bar' style='width:{pct:.0f}%'></span></span>"


def render_html(report: ReportData) -> str:
    data = report.to_dict()
    case = data["case"]
    synthetic = data["provenance"].get("data_provenance") != "REAL"

    parts: list[str] = [
        "<title>SPILLTRACE evidence report</title>",
        f"<style>{_STYLE}</style>",
        "<main>",
        f"<h1>Evidence report — {_e(case.get('case_ref'))}</h1>",
        f"<p class='sub'>{_e(case.get('title'))}</p>",
    ]

    if synthetic:
        parts.append(
            "<div class='notice'>"
            + _e(next((n for n in data["limitations"] if "SYNTHETIC" in n), "SYNTHETIC DATA"))
            + "</div>"
        )

    parts.append(
        "<div class='disclaimer'><strong>"
        + _e(data["attribution"]["disclaimer"])
        + "</strong></div>"
    )

    # --- case ---
    parts.append("<h2>1. Case</h2>")
    parts.append(
        _kv(
            [
                ("Reference", case.get("case_ref")),
                ("Title", case.get("title")),
                ("Status", case.get("status")),
                ("Time window (UTC)", f"{case.get('start_time')} → {case.get('end_time')}"),
                ("Area of interest", case.get("aoi_summary")),
                ("Created", case.get("created_at")),
                ("Data provenance", case.get("data_provenance")),
            ]
        )
    )

    # --- scene ---
    parts.append("<h2>2. Satellite scene</h2>")
    scene = data["scene"]
    parts.append(
        _kv(
            [
                ("Product identifier", scene.get("product_id")),
                ("Provider", scene.get("provider")),
                ("Mission / platform", f"{scene.get('mission')} / {scene.get('platform')}"),
                (
                    "Product type / mode",
                    f"{scene.get('product_type')} / {scene.get('sensor_mode')}",
                ),
                ("Acquisition time (UTC)", scene.get("acquisition_time")),
                ("Polarizations", ", ".join(scene.get("polarizations") or [])),
                ("Orbit", f"{scene.get('orbit_direction')} rel. {scene.get('relative_orbit')}"),
                ("Checksum (SHA-256)", scene.get("checksum_sha256")),
            ]
        )
        if scene
        else "<p>No satellite scene is attached to this case.</p>"
    )

    # --- detection ---
    parts.append("<h2>3. Slick detection</h2>")
    detection = data["detection"]
    if detection:
        parts.append(
            _kv(
                [
                    ("Detected at (UTC)", detection.get("detected_at")),
                    ("Area", f"{detection.get('area_km2')} km²"),
                    ("Perimeter", f"{detection.get('perimeter_km')} km"),
                    ("Detection confidence", detection.get("detection_confidence")),
                    ("Probability threshold", detection.get("threshold")),
                    ("Model", f"{detection.get('model_name')} {detection.get('model_version')}"),
                    ("Model metrics", detection.get("model_metrics") or "none recorded"),
                    ("Probability raster", detection.get("probability_raster_uri")),
                ]
            )
        )
        parts.append(
            "<p class='sub'>Detection confidence is a model-internal quantity. It is "
            "reported separately from verification and origin confidence and is never "
            "combined with them.</p>"
        )
    else:
        parts.append("<p>No detection was produced for this case.</p>")

    # --- verification ---
    parts.append("<h2>4. Look-alike verification</h2>")
    verification = data["verification"]
    if verification:
        parts.append(
            _kv(
                [
                    ("Status", verification.get("status")),
                    ("Verification confidence", verification.get("verification_confidence")),
                    ("Wind speed", f"{verification.get('wind_speed_ms')} m/s"),
                    ("Wind direction", f"{verification.get('wind_direction_deg')}°"),
                    ("Wind source", verification.get("wind_source")),
                ]
            )
        )
        parts.append(f"<p>{_e(verification.get('explanation'))}</p>")
        rules = verification.get("rules") or []
        if rules:
            parts.append(
                "<h3>Rules evaluated</h3><table><tr><th>Check</th><th>Result</th>"
                "<th class='num'>Observed</th><th class='num'>Threshold</th>"
                "<th class='num'>Weight</th></tr>"
            )
            for rule in rules:
                verdict = (
                    "not evaluated"
                    if not rule.get("applicable")
                    else ("supports oil" if rule.get("passed") else "argues against oil")
                )
                parts.append(
                    f"<tr><td>{_e(rule.get('label'))}</td><td>{_e(verdict)}</td>"
                    f"<td class='num mono'>{_e(rule.get('observed'))}</td>"
                    f"<td class='num mono'>{_e(rule.get('threshold'))}</td>"
                    f"<td class='num'>{_e(rule.get('weight'))}</td></tr>"
                )
            parts.append("</table>")
    else:
        parts.append("<p>No verification result is recorded for this case.</p>")

    # --- environment ---
    parts.append("<h2>5. Environmental conditions</h2>")
    environment = data["environment"]
    if environment:
        parts.append(
            _kv(
                [
                    ("Source", environment.get("source")),
                    ("Dataset", environment.get("dataset_id") or "not applicable"),
                    ("Variables", ", ".join(environment.get("variables") or [])),
                    (
                        "Time range (UTC)",
                        f"{environment.get('time_start')} → {environment.get('time_end')}",
                    ),
                    ("Grid resolution", f"{environment.get('grid_resolution_deg')}°"),
                    ("Stored file", environment.get("storage_uri")),
                    ("Checksum (SHA-256)", environment.get("checksum_sha256")),
                ]
            )
        )
        summary = environment.get("summary") or {}
        if summary:
            parts.append(
                "<table><tr><th>Variable</th><th class='num'>Min</th>"
                "<th class='num'>Mean</th><th class='num'>Max</th><th>Units</th></tr>"
            )
            for name, stats in summary.items():
                parts.append(
                    f"<tr><td>{_e(name)}</td><td class='num'>{_e(stats.get('min'))}</td>"
                    f"<td class='num'>{_e(stats.get('mean'))}</td>"
                    f"<td class='num'>{_e(stats.get('max'))}</td>"
                    f"<td>{_e(stats.get('units'))}</td></tr>"
                )
            parts.append("</table>")
    else:
        parts.append("<p>No environmental data was retrieved for this case.</p>")

    # --- drift ---
    parts.append("<h2>6. Reverse drift and origin region</h2>")
    drift = data["drift"]
    if drift:
        parts.append(
            _kv(
                [
                    ("Engine", drift.get("engine")),
                    ("Mode", drift.get("mode")),
                    ("Random seed", drift.get("seed")),
                    ("Particles", drift.get("number_of_particles")),
                    ("Ensemble members", drift.get("ensemble_members")),
                    ("Duration", f"{drift.get('duration_hours')} h"),
                    ("Time step", f"{drift.get('time_step_seconds')} s"),
                    ("Origin confidence", drift.get("origin_confidence")),
                    ("Origin region area", f"{drift.get('origin_area_km2')} km²"),
                    (
                        "Inferred discharge window (UTC)",
                        f"{drift.get('inferred_start')} → {drift.get('inferred_end')}",
                    ),
                    ("Density grid", drift.get("density_grid_uri")),
                ]
            )
        )
        contours = drift.get("contour_areas") or []
        if contours:
            parts.append(
                "<table><tr><th>Probability region</th><th class='num'>Area (km²)</th></tr>"
            )
            for level, area in contours:
                parts.append(
                    f"<tr><td>{round(float(level) * 100)}% probability</td>"
                    f"<td class='num'>{area}</td></tr>"
                )
            parts.append("</table>")
        parts.append(
            "<div class='disclaimer'>"
            + _e(next((n for n in data["limitations"] if "probability region" in n), ""))
            + "</div>"
        )
    else:
        parts.append("<p>No reverse-drift run was completed for this case.</p>")

    # --- AIS ---
    parts.append("<h2>7. AIS data</h2>")
    ais = data["ais"]
    parts.append(
        _kv(
            [
                ("Source", ais.get("source")),
                ("Vessels observed", ais.get("vessel_count")),
                ("Positions ingested", ais.get("position_count")),
                ("Positions rejected by cleaning", ais.get("rejected_count")),
                ("Trajectories built", ais.get("trajectory_count")),
            ]
        )
    )
    vessels = ais.get("vessels") or []
    if vessels:
        parts.append(
            "<table><tr><th>MMSI</th><th>IMO</th><th>Name</th><th>Type</th><th>Flag</th>"
            "<th class='num'>Positions</th><th class='num'>Max gap (min)</th>"
            "<th class='num'>Coverage</th></tr>"
        )
        for vessel in vessels:
            parts.append(
                f"<tr><td class='mono'>{_e(vessel.get('mmsi'))}</td>"
                f"<td class='mono'>{_e(vessel.get('imo') or '—')}</td>"
                f"<td>{_e(vessel.get('name'))}</td><td>{_e(vessel.get('ship_type_name'))}</td>"
                f"<td>{_e(vessel.get('flag_country'))}</td>"
                f"<td class='num'>{_e(vessel.get('position_count'))}</td>"
                f"<td class='num'>{_e(vessel.get('max_gap_minutes'))}</td>"
                f"<td class='num'>{_e(vessel.get('coverage_ratio'))}</td></tr>"
            )
        parts.append("</table>")

    # --- attribution ---
    parts.append("<h2>8. Ranked candidate vessels</h2>")
    attribution = data["attribution"]
    ranked = attribution.get("ranked") or []
    if attribution.get("shortfall_note"):
        parts.append(f"<div class='notice'>{_e(attribution['shortfall_note'])}</div>")
    if ranked:
        parts.append(
            "<table><tr><th>Rank</th><th>Vessel</th><th>MMSI</th><th class='num'>Final score</th>"
            "<th>Evidence strength</th><th class='num'>Closest approach</th></tr>"
        )
        for row in ranked:
            parts.append(
                f"<tr><td class='rank'>{_e(row.get('rank'))}</td>"
                f"<td>{_e(row.get('vessel_name'))}</td>"
                f"<td class='mono'>{_e(row.get('mmsi'))}</td>"
                f"<td class='num'>{_e(row.get('final_score'))}</td>"
                f"<td>{_e(row.get('confidence_label'))}</td>"
                f"<td class='num'>{_e(row.get('closest_approach_km'))} km</td></tr>"
            )
        parts.append("</table>")

        for row in ranked:
            parts.append(
                f"<h3>Rank {_e(row.get('rank'))} — {_e(row.get('vessel_name'))} "
                f"(MMSI {_e(row.get('mmsi'))})</h3>"
            )
            parts.append(
                "<table><tr><th>Factor</th><th class='num'>Weight</th><th class='num'>Score</th>"
                "<th></th><th class='num'>Contribution</th><th>Why</th></tr>"
            )
            for factor in row.get("factors") or []:
                parts.append(
                    f"<tr><td>{_e(factor.get('label'))}</td>"
                    f"<td class='num'>{_e(factor.get('weight'))}</td>"
                    f"<td class='num'>{_e(round(float(factor.get('score', 0)), 3))}</td>"
                    f"<td>{_bar(float(factor.get('score', 0)))}</td>"
                    f"<td class='num'>{_e(round(float(factor.get('contribution', 0)), 4))}</td>"
                    f"<td>{_e(factor.get('explanation'))}</td></tr>"
                )
            parts.append("</table>")
        parts.append(
            f"<p class='sub'>Scoring model <code>{_e(ranked[0].get('scoring_version'))}</code> "
            "with weights " + _e(ranked[0].get("weights")) + ".</p>"
        )
    else:
        parts.append("<p>No candidate vessels were ranked for this case.</p>")

    # --- artifacts ---
    parts.append("<h2>9. Evidence artifacts</h2>")
    artifacts = data["artifacts"]
    if artifacts:
        parts.append(
            "<table><tr><th>Type</th><th>Label</th><th>Location</th>"
            "<th class='num'>Size</th><th>SHA-256</th></tr>"
        )
        for artifact in artifacts:
            parts.append(
                f"<tr><td>{_e(artifact.get('artifact_type'))}</td>"
                f"<td>{_e(artifact.get('label'))}</td>"
                f"<td class='mono'>{_e(artifact.get('storage_uri'))}</td>"
                f"<td class='num'>{_e(artifact.get('size_bytes'))}</td>"
                f"<td class='mono'>{_e((artifact.get('checksum_sha256') or '')[:16])}…</td></tr>"
            )
        parts.append("</table>")
    else:
        parts.append("<p>No stored artifacts are recorded for this case.</p>")

    # --- provenance ---
    parts.append("<h2>10. Provenance and reproducibility</h2>")
    provenance = data["provenance"]
    parts.append(
        _kv(
            [
                ("Software version", provenance.get("software_version")),
                ("Git revision", provenance.get("git_sha")),
                ("Report generated (UTC)", data["generated_at"]),
                ("Overall data provenance", provenance.get("data_provenance")),
            ]
        )
    )
    providers = provenance.get("providers") or {}
    if providers:
        parts.append("<table><tr><th>Data source</th><th>Implementation</th><th>Mode</th></tr>")
        for port, info in providers.items():
            parts.append(
                f"<tr><td>{_e(port)}</td><td class='mono'>{_e(info.get('implementation'))}</td>"
                f"<td>{_e(info.get('mode'))}</td></tr>"
            )
        parts.append("</table>")

    # --- limitations ---
    parts.append("<h2>11. Limitations and uncertainty</h2><ul>")
    for limitation in data["limitations"]:
        parts.append(f"<li>{_e(limitation)}</li>")
    parts.append("</ul>")

    parts.append(
        "<footer>SPILLTRACE — maritime pollution attribution system. "
        + _e(data["attribution"]["disclaimer"])
        + "</footer></main>"
    )
    return "\n".join(parts)


__all__ = ["render_html"]
