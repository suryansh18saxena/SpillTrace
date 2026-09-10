"""Evidence report assembly and rendering (AC-12, AC-13).

The report is what an investigator works from, so the tests here are about *what must
always be present*: sources, timestamps, model versions, and language that does not
over-claim.
"""

from __future__ import annotations

from spilltrace.core.disclaimers import (
    ATTRIBUTION_DISCLAIMER,
    FORBIDDEN_PHRASES,
    REPORT_LIMITATIONS,
    SYNTHETIC_DATA_NOTICE,
    contains_forbidden_language,
)
from spilltrace.core.report import assemble_report, render_html
from spilltrace.core.report.assemble import REQUIRED_SECTIONS


def build(**overrides):
    base: dict[str, object] = {
        "case": {
            "case_ref": "ST-2026-0001",
            "title": "Gulf of Kutch — suspected operational discharge",
            "status": "COMPLETED",
            "start_time": "2026-08-12T14:12:00Z",
            "end_time": "2026-08-14T07:12:00Z",
            "created_at": "2026-08-14T09:00:00Z",
            "data_provenance": "SYNTHETIC",
            "aoi_summary": "21.9000°–23.1000° N, 68.6000°–70.4000° E (24,000 km²)",
        },
        "scene": {
            "product_id": "S1A_IW_GRDH_1SDV_20260814T011200_SYNTHETIC_0042",
            "provider": "SYNTHETIC",
            "mission": "SENTINEL-1",
            "platform": "S1A",
            "product_type": "IW_GRDH_1S",
            "sensor_mode": "IW",
            "acquisition_time": "2026-08-14T01:12:00Z",
            "polarizations": ["VV", "VH"],
            "orbit_direction": "DESCENDING",
            "relative_orbit": 107,
            "checksum_sha256": "a" * 64,
        },
        "detection": {
            "id": "11111111-1111-1111-1111-111111111111",
            "detected_at": "2026-08-14T01:12:00Z",
            "area_km2": 85.35,
            "perimeter_km": 90.33,
            "detection_confidence": 0.71,
            "threshold": 0.5,
            "model_name": "synthetic-generator",
            "model_version": "1.0.0",
            "model_metrics": {},
            "probability_raster_uri": "s3://spilltrace/probability/x.tif",
            "data_provenance": "SYNTHETIC",
        },
        "verification": {
            "status": "VERIFIED",
            "verification_confidence": 0.907,
            "wind_speed_ms": 5.4,
            "wind_direction_deg": 232.0,
            "wind_source": "SYNTHETIC",
            "explanation": "The detected feature is consistent with an oil-like surface film.",
            "rules": [
                {
                    "label": "Wind conditions",
                    "applicable": True,
                    "passed": True,
                    "observed": 5.4,
                    "threshold": {"optimal_ms": [4, 10]},
                    "weight": 0.30,
                },
            ],
        },
        "environment": {
            "source": "SYNTHETIC",
            "dataset_id": None,
            "variables": ["eastward_wind", "northward_wind"],
            "time_start": "2026-08-12T14:12:00Z",
            "time_end": "2026-08-14T07:12:00Z",
            "grid_resolution_deg": 0.05,
            "storage_uri": "s3://spilltrace/environment/x.npz",
            "checksum_sha256": "b" * 64,
            "summary": {"wind_speed": {"min": 4.3, "mean": 5.4, "max": 6.6, "units": "m s-1"}},
        },
        "drift": {
            "engine": "analytical",
            "mode": "BACKWARD",
            "seed": 42,
            "number_of_particles": 6000,
            "ensemble_members": 6,
            "duration_hours": 18.0,
            "time_step_seconds": 900,
            "origin_confidence": 0.633,
            "origin_area_km2": 522.3,
            "contour_areas": [(0.9, 522.3), (0.75, 300.1), (0.5, 148.7)],
            "inferred_start": "2026-08-13T08:57:00Z",
            "inferred_end": "2026-08-13T13:42:00Z",
            "density_grid_uri": "s3://spilltrace/drift/d.tif",
        },
        "ais": {
            "source": "SYNTHETIC",
            "vessel_count": 6,
            "position_count": 4618,
            "rejected_count": 4,
            "trajectory_count": 8,
            "vessels": [
                {
                    "mmsi": 419008412,
                    "imo": 9542871,
                    "name": "SAGAR PRABHA (SYNTHETIC)",
                    "ship_type_name": "Tanker",
                    "flag_country": "India",
                    "position_count": 822,
                    "max_gap_minutes": 0.0,
                    "coverage_ratio": 1.0,
                },
            ],
        },
        "attributions": [
            {
                "rank": 1,
                "mmsi": 419008412,
                "vessel_name": "SAGAR PRABHA (SYNTHETIC)",
                "final_score": 0.9546,
                "confidence_label": "HIGH",
                "closest_approach_km": 0.0,
                "scoring_version": "prd-j-v1",
                "weights": {"origin_proximity": 0.35},
                "factors": [
                    {
                        "key": "origin_proximity",
                        "label": "Origin proximity",
                        "weight": 0.35,
                        "score": 0.96,
                        "contribution": 0.336,
                        "explanation": "Entered the 50% origin probability contour.",
                    },
                ],
            }
        ],
        "artifacts": [
            {
                "artifact_type": "REPORT_HTML",
                "label": "Evidence report (HTML)",
                "storage_uri": "s3://spilltrace/reports/r.html",
                "media_type": "text/html",
                "size_bytes": 22737,
                "checksum_sha256": "c" * 64,
                "data_provenance": "SYNTHETIC",
            },
        ],
        "software_version": "0.1.0",
        "git_sha": "abc1234",
        "provider_modes": {
            "satellite": {"implementation": "FixtureCatalogue", "mode": "SYNTHETIC"}
        },
        "shortfall_note": None,
    }
    base.update(overrides)
    return assemble_report(**base)


class TestAssembly:
    def test_every_required_section_is_present(self) -> None:
        assert build().missing_sections() == []

    def test_missing_sections_are_reported_not_hidden(self) -> None:
        report = build(drift=None, environment=None)
        assert set(report.missing_sections()) == {"drift", "environment"}

    def test_required_section_list_is_complete(self) -> None:
        payload = build().to_dict()
        for section in REQUIRED_SECTIONS:
            assert section in payload

    def test_provenance_is_combined_across_inputs(self) -> None:
        assert build().provenance["data_provenance"] == "SYNTHETIC"

    def test_generated_timestamp_is_utc(self) -> None:
        assert build().to_dict()["generated_at"].endswith("Z")


class TestLimitations:
    def test_all_mandated_disclaimers_appear(self) -> None:
        limitations = build().limitations
        for mandated in REPORT_LIMITATIONS:
            assert mandated in limitations

    def test_synthetic_notice_leads_the_limitations(self) -> None:
        assert build().limitations[0] == SYNTHETIC_DATA_NOTICE

    def test_analytical_engine_is_disclosed(self) -> None:
        text = " ".join(build().limitations)
        assert "analytical advection-diffusion engine" in text
        assert "weathering" in text

    def test_unmeasured_model_is_disclosed(self) -> None:
        # A model with no recorded metrics must not be presented as validated.
        assert any("no recorded evaluation metrics" in line for line in build().limitations)

    def test_uncertain_verification_is_disclosed(self) -> None:
        report = build(verification={**build().verification, "status": "UNCERTAIN"})
        assert any("UNCERTAIN" in line for line in report.limitations)

    def test_shortfall_note_is_carried_through(self) -> None:
        note = "Only 2 candidate vessel(s) met the correlation criteria."
        report = build(shortfall_note=note)
        assert note in report.limitations
        assert report.attribution["shortfall_note"] == note


class TestRendering:
    def test_html_is_self_contained(self) -> None:
        html = render_html(build())
        # An evidence artifact that needs a CDN to render is not an evidence artifact.
        assert "http://" not in html.replace("http://localhost", "")
        assert "https://" not in html
        assert "<script" not in html.lower()

    def test_all_sections_are_rendered(self) -> None:
        html = render_html(build())
        for heading in (
            "Case",
            "Satellite scene",
            "Slick detection",
            "Look-alike verification",
            "Environmental conditions",
            "Reverse drift",
            "AIS data",
            "Ranked candidate vessels",
            "Evidence artifacts",
            "Provenance and reproducibility",
            "Limitations and uncertainty",
        ):
            assert heading in html

    def test_the_disclaimer_is_prominent(self) -> None:
        html = render_html(build())
        assert html.count(ATTRIBUTION_DISCLAIMER) >= 2  # header and footer

    def test_synthetic_notice_is_shown(self) -> None:
        assert "SYNTHETIC DEMONSTRATION DATA" in render_html(build())

    def test_reproducibility_fields_are_rendered(self) -> None:
        html = render_html(build())
        for value in ("0.1.0", "abc1234", "42", "6000", "prd-j-v1"):
            assert value in html

    def test_sources_and_checksums_are_rendered(self) -> None:
        html = render_html(build())
        assert "S1A_IW_GRDH_1SDV_20260814T011200_SYNTHETIC_0042" in html
        assert "cccccccccccccccc" in html  # truncated artifact checksum

    def test_factor_breakdown_is_rendered(self) -> None:
        html = render_html(build())
        assert "Origin proximity" in html
        assert "Entered the 50% origin probability contour." in html

    def test_no_prejudicial_language(self) -> None:
        # The mandated disclaimers quote the phrases they forbid in order to deny them,
        # so they are excluded from the scan; everything else must be clean.
        assert contains_forbidden_language(render_html(build())) == []

    def test_the_scan_still_catches_a_real_over_claim(self) -> None:
        report = build()
        report.case["description"] = "The responsible vessel has been identified."
        assert "responsible vessel" in contains_forbidden_language(report.case["description"])

    def test_provenance_is_not_a_false_positive(self) -> None:
        # "provenance" contains "proven"; a substring scan would flag every artifact.
        assert contains_forbidden_language("data provenance: SYNTHETIC") == []

    def test_html_escapes_injected_content(self) -> None:
        report = build(case={**build().case, "title": "<script>alert('x')</script>"})
        html = render_html(report)
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html

    def test_empty_candidate_list_renders_honestly(self) -> None:
        html = render_html(build(attributions=[], shortfall_note="No candidate vessels..."))
        assert "No candidate vessels were ranked" in html

    def test_forbidden_phrases_list_is_non_trivial(self) -> None:
        assert len(FORBIDDEN_PHRASES) >= 5
        assert contains_forbidden_language("this vessel is guilty") == ["guilty"]
