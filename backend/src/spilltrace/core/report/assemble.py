"""Collect every artifact of a case into one structured document."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from spilltrace.core.disclaimers import (
    ATTRIBUTION_DISCLAIMER,
    REPORT_LIMITATIONS,
    SYNTHETIC_DATA_NOTICE,
)
from spilltrace.core.enums import DataProvenance
from spilltrace.core.time import isoformat_utc, utcnow

#: Sections that must be present in every report (AC-12).  Asserted by tests.
REQUIRED_SECTIONS: tuple[str, ...] = (
    "case",
    "scene",
    "detection",
    "verification",
    "environment",
    "drift",
    "ais",
    "attribution",
    "artifacts",
    "provenance",
    "limitations",
)


@dataclass(slots=True)
class ReportData:
    case: dict[str, Any]
    scene: dict[str, Any] | None
    detection: dict[str, Any] | None
    verification: dict[str, Any] | None
    environment: dict[str, Any] | None
    drift: dict[str, Any] | None
    ais: dict[str, Any]
    attribution: dict[str, Any]
    artifacts: list[dict[str, Any]]
    provenance: dict[str, Any]
    limitations: list[str]
    generated_at: datetime = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": isoformat_utc(self.generated_at),
            "case": self.case,
            "scene": self.scene,
            "detection": self.detection,
            "verification": self.verification,
            "environment": self.environment,
            "drift": self.drift,
            "ais": self.ais,
            "attribution": self.attribution,
            "artifacts": self.artifacts,
            "provenance": self.provenance,
            "limitations": self.limitations,
        }

    def missing_sections(self) -> list[str]:
        payload = self.to_dict()
        return [name for name in REQUIRED_SECTIONS if payload.get(name) in (None, {}, [])]


def assemble_report(
    *,
    case: dict[str, Any],
    scene: dict[str, Any] | None,
    detection: dict[str, Any] | None,
    verification: dict[str, Any] | None,
    environment: dict[str, Any] | None,
    drift: dict[str, Any] | None,
    ais: dict[str, Any],
    attributions: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    software_version: str,
    git_sha: str,
    provider_modes: dict[str, dict[str, str]],
    shortfall_note: str | None = None,
) -> ReportData:
    provenance_values = [
        case.get("data_provenance"),
        (detection or {}).get("data_provenance"),
        (drift or {}).get("data_provenance"),
    ]
    overall = _overall_provenance(provenance_values)

    limitations = list(REPORT_LIMITATIONS)
    if overall is not DataProvenance.REAL:
        # Put the synthetic notice first: it changes how everything else should be read.
        limitations.insert(0, SYNTHETIC_DATA_NOTICE)
    if drift and drift.get("engine") == "analytical":
        limitations.append(
            "The reverse drift used the analytical advection-diffusion engine, not a "
            "full oil-weathering model. Evaporation, emulsification, entrainment, "
            "vertical mixing and Stokes drift were not simulated."
        )
    if verification and verification.get("status") == "UNCERTAIN":
        limitations.append(
            "Look-alike verification returned UNCERTAIN for this detection. The feature "
            "may be oil, but a natural look-alike could not be excluded."
        )
    if shortfall_note:
        limitations.append(shortfall_note)
    if (detection or {}).get("model_metrics") in (None, {}):
        limitations.append(
            "The detection model in this case has no recorded evaluation metrics, so its "
            "measured accuracy on independent data is unknown."
        )

    return ReportData(
        case=case,
        scene=scene,
        detection=detection,
        verification=verification,
        environment=environment,
        drift=drift,
        ais=ais,
        attribution={
            "disclaimer": ATTRIBUTION_DISCLAIMER,
            "candidate_count": len(attributions),
            "shortfall_note": shortfall_note,
            "ranked": attributions,
        },
        artifacts=artifacts,
        provenance={
            "software_version": software_version,
            "git_sha": git_sha,
            "data_provenance": str(overall),
            "providers": provider_modes,
            "generated_at": isoformat_utc(utcnow()),
        },
        limitations=limitations,
    )


def _overall_provenance(values: list[Any]) -> DataProvenance:
    from spilltrace.core.provenance import combine_provenance

    return combine_provenance(*[v for v in values if v])


__all__ = ["REQUIRED_SECTIONS", "ReportData", "assemble_report"]
